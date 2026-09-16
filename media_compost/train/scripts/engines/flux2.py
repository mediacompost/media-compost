"""FLUX.2 engine: flow-matching transformer, LLM text encoder.

Serves the FLUX.2 Klein releases, 4B and 9B — one engine, because the
transformer, the latent packing, the position ids and the LoRA targets are
the same for both; what differs is the size, which is a matter of memory
rather than of code. It is also what puts them in one architecture group in
the app. (It served FLUX.2 dev too, a 32B transformer with a 24B Mistral
encoder, until that was dropped — nothing here was specific to it, since what
distinguished it was READ off the model rather than tabled: which pipeline
class the snapshot's `model_index.json` names, and whether the transformer
carries `guidance_embeds`. Both reads survive it, and the second is why:
a guidance-distilled release in this family would otherwise train against a
scale it never sees, with an ordinary-looking loss curve.)

Same rectified-flow objective as the Chroma engine — sample a timestep ``t``
(logit-normal, shifted by ``model_params.flow_shift``), mix
``x_t = (1 - t)·x0 + t·noise``, regress the transformer's velocity onto
``noise − x0`` — but almost everything around it differs from FLUX.1, so this
engine leans on the PIPELINE's own helpers rather than re-deriving them:

* the latent is patchified 2×2 into channels and then normalised by the VAE's
  own **batch-norm statistics** (``vae.bn.running_mean/var``), not by a
  ``scaling_factor``. Getting that wrong trains against a distribution the
  model has never seen, and nothing about the loss curve would say so.
* "packing" is a plain flatten to ``(b, h·w, c)`` — the 2×2 patching already
  happened above — and positions are 4-D ids from ``_prepare_latent_ids``.
* the text encoder is an **instruct LLM** (Qwen3): the prompt goes through a
  chat template, and the conditioning is three of its hidden layers stacked,
  not the final one.

So `self.pipe` is kept after loading and its static helpers are called
directly. Copying those four transforms into this file is how an engine
silently drifts from the model it is meant to train.
"""

from __future__ import annotations

from . import common
from .common import BaseEngine, masked_mean, param_group

#: The diffusers pipeline this model generates with. Read by
#: `generate.py` (the Evaluate tab), which builds a pipeline without
#: constructing an engine — so it lives HERE rather than in a second
#: table that a new model can be left out of.
PIPELINE = "Flux2KleinPipeline"
#: …and the family this engine serves, for a model whose own snapshot names
#: one of them (see `common.pipeline_class`). `PIPELINE` is what a repo with
#: nothing cached yet falls back to.
PIPELINES = ("Flux2KleinPipeline",)

# Same attention projections FLUX.1 exposes — Flux2Attention declares the
# identical set (to_q/k/v + to_out.0, and the added_* pair for the joint
# text stream).
TRANSFORMER_LORA_TARGETS = [
    "to_q", "to_k", "to_v", "to_out.0", "add_q_proj", "add_k_proj",
    "add_v_proj", "to_add_out",
]


class Engine(BaseEngine):
    # 8x from the VAE and 2x again from the patchify inside `encode_image`,
    # so one cell of what this engine caches covers 16 pixels.
    latent_scale = 16
    backbone_component = "transformer"

    adapter_targets = tuple(TRANSFORMER_LORA_TARGETS)
    flow_matching = True

    def load(self) -> None:

        cls = common.pipeline_class(self._pipeline_source(), PIPELINE, PIPELINES)
        pipe = self._from_pretrained(cls)
        # What came back, not what was asked for: `cls` is usually the auto
        # loader, so the model itself decided which of the family this is.
        cls = common.check_family(pipe, PIPELINES, "FLUX.2")
        # Kept, unlike the other engines: its helpers ARE this model's recipe.
        self.pipe = pipe
        self.tokenizer = pipe.tokenizer
        # Qwen3ForCausalLM (Klein) or Mistral 3 Small (dev) — the pipeline
        # picked which, and `encode_prompt` hides the difference.
        self.text_encoder = pipe.text_encoder
        self.vae = pipe.vae
        self.transformer = pipe.transformer
        self.sample_scheduler = pipe.scheduler
        self.pipe_cls = cls

        self.vae.requires_grad_(False)
        # The text encoder is an instruct LLM used only for conditioning; it
        # stays frozen in BOTH methods, so a "full finetune" here means the
        # transformer, exactly as it means the UNet for SD/SDXL.
        self.text_encoder.requires_grad_(False)
        if self.method == "lora":
            self.attach_adapter()
        else:
            self.transformer.requires_grad_(True)
        if self.hyper.get("gradient_checkpointing"):
            self.transformer.enable_gradient_checkpointing()
        # After the adapter is attached and the base is frozen —
        # `apply_fp8` converts exactly the weights that stay frozen.
        fp8 = self.apply_fp8(self.transformer)
        if fp8:
            print(f"frozen weights stored as fp8 ({fp8} layers)", flush=True)
        if self.apply_attention_slicing(self.transformer):
            print("attention slicing on", flush=True)

        self.vae.to(self.device)
        self.text_encoder.to(self.device)
        self.transformer.to(self.device)
        self.upcast_trainable()

    def _text_encoders(self):
        return []  # the LLM is never trained

    def trainable_params(self, lr: float):
        return [param_group(self.transformer.parameters(), lr)]

    # -- latents --------------------------------------------------------------

    def encode_image(self, img):
        """Pixel image -> the transformer's latent, `(1, C·4, h/16, w/16)`.

        Not the base class's `sample() * scaling_factor`: this VAE is followed
        by a 2×2 patchify and a batch-norm normalisation, so the pipeline's own
        `_encode_vae_image` is the only thing that produces what the
        transformer was trained on. It takes the distribution's MODE rather
        than a sample, which is also what a cache reused across every epoch
        should hold.
        """
        import numpy as np
        import torch

        w, h = img.size
        if w % self.latent_scale or h % self.latent_scale:
            # The 2x2 patchify below needs an even latent, and diffusers only
            # says "shape [...] is invalid for input of size N" when it isn't.
            # A bucket step that is not a multiple of 16 is the way to get
            # here, so name that rather than the reshape.
            raise ValueError(
                f"FLUX.2 needs image sizes that are multiples of "
                f"{self.latent_scale} px; got {w}x{h}. Set the dataset's "
                f"bucket step to a multiple of {self.latent_scale} "
                f"(64 is the default)."
            )
        arr = np.asarray(img, dtype=np.float32) / 127.5 - 1.0
        px = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0)
        px = px.to(self.device, dtype=self.vae.dtype)
        with torch.no_grad():
            return self.pipe._encode_vae_image(px, generator=None)

    @staticmethod
    def _unpack(packed, c: int, lh: int, lw: int):
        """Inverse of the pipeline's `_pack_latents` (a reshape + permute), so
        the loss can be taken in the latent's own (b, c, h, w) shape — which is
        the shape the per-cell alpha mask is built for."""
        b = packed.shape[0]
        return packed.permute(0, 2, 1).reshape(b, c, lh, lw)

    def _guidance(self, b: int, device):
        """The distilled guidance embedding, or None for a model without one.

        A guidance-distilled release takes the guidance
        scale as an input, and a run that trains it at a scale nobody
        generates at teaches the model the wrong thing at every scale. Klein
        is not, and its pipeline passes None — so the question is answered by
        the transformer's own config rather than by which model this is.
        """
        import torch

        if not getattr(self.transformer.config, "guidance_embeds", False):
            return None
        scale = float(self.model_params.get("guidance", 1.0) or 1.0)
        return torch.full([b], scale, device=device, dtype=torch.float32)

    def _encode_prompts(self, captions: list[str]):
        import torch

        with torch.no_grad():
            embeds, text_ids = self.pipe.encode_prompt(
                prompt=list(captions), device=self.device)
        return embeds.to(self.dtype), text_ids

    def _reference_tokens(self, refs, budget: int, b: int, device):
        """One visit's references as `(packed tokens, position ids)`.

        The pipeline's own two helpers do the work — `_encode_vae_image`
        through `encode_refs`, then `_prepare_image_ids`, which is what gives
        each reference its own T coordinate so the model can tell them apart
        and tell them from the picture it is producing. Every sample in this
        call shares the layout (`loop._forward` grouped them), so the ids are
        computed once and expanded.
        """
        import torch

        per_sample = [self.encode_refs(one, budget) for one in refs]
        packed = torch.stack([
            torch.cat([self.pipe._pack_latents(lat).squeeze(0)
                       for lat in one], dim=0)
            for one in per_sample
        ])
        ids = self.pipe._prepare_image_ids(per_sample[0]).to(device)
        return packed, ids.expand(b, -1, -1)

    def train_step(self, latents, captions, weights, rng, masks=None,
                   refs=None):
        import torch
        import torch.nn.functional as F

        b, c, lh, lw = latents.shape
        embeds, text_ids = self._encode_prompts(captions)

        # WHICH NOISE LEVEL this sample trains on — see timesteps.py. The
        # resolution shift rides on the model parameter it always did.
        t = self.flow_position(b, latents.device)
        t_ = t.view(b, 1, 1, 1)

        noise = torch.randn_like(latents)
        noisy = (1.0 - t_) * latents + t_ * noise

        packed = self.pipe._pack_latents(noisy)          # (b, lh*lw, c)
        img_ids = self.pipe._prepare_latent_ids(noisy).to(latents.device)
        # An INSTRUCTION visit's reference pictures ride behind the picture
        # being produced, in the one sequence, exactly as the pipeline lays
        # them out when it edits. `n_img` is taken BEFORE they are added: it
        # is what the prediction has to be cut back to.
        n_img = packed.shape[1]
        if refs and any(refs):
            ref_tokens, ref_ids = self._reference_tokens(
                refs, (lh * self.latent_scale) * (lw * self.latent_scale), b,
                latents.device)
            packed = torch.cat([packed, ref_tokens.to(packed.dtype)], dim=1)
            img_ids = torch.cat([img_ids, ref_ids], dim=1)
        # Under autocast, so a FULL finetune's fp32 master weights still do
        # their matmuls in `self.dtype` — see BaseEngine.autocast. A no-op for
        # LoRA, where the base is already that dtype.
        with self.autocast():
            pred = self.transformer(
                hidden_states=packed.to(self.dtype),
                # The sampling loop passes `timestep / 1000` for a 0..1000
                # scheduler timestep; ours is already the 0..1 flow position.
                timestep=t.to(self.dtype),
                guidance=self._guidance(b, latents.device),
                encoder_hidden_states=embeds,
                txt_ids=text_ids,
                img_ids=img_ids,
                return_dict=False,
            )[0]
        # The transformer returns the image tokens first, the reference ones
        # behind them — and only the first block is what was asked for.
        pred = self._unpack(pred[:, :n_img], c, lh, lw)

        target = noise - latents
        loss = F.mse_loss(pred.float(), target.float(), reduction="none")
        loss = masked_mean(loss, masks)
        wt = torch.tensor(weights, device=loss.device, dtype=loss.dtype)
        return (loss * wt).mean()

    # Weights: saving, loading and the portable file are BaseEngine's — this
    # engine's adapter sits on the transformer and nowhere else, which is what
    # the defaults there assume.

    # -- samples --------------------------------------------------------------

    def generate_samples(self, prompts, seed, steps, cfg, batch=1,
                         on_image=None, check=None):
        """`prompts` are (prompt, negative, width, height); a None size falls
        back to the model's native area.

        The pipeline takes no `negative_prompt` STRING, only embeddings — and
        pre-encoding one has to match its internal layering exactly or the
        transformer fails on a batch mismatch ("the size of tensor a (2) must
        match tensor b (4)"). With guidance on it encodes its own empty-string
        negative anyway, so a test prompt's negative is dropped here with a
        line in the log, the same way generate.py handles it for the Evaluate
        tab.

        Like Chroma, this keeps the pipeline's own decode: the latents are
        packed and batch-norm-normalised in a layout only the pipeline knows
        how to undo, and its VAE runs at the model dtype, so the MPS cast that
        blackens SDXL samples never triggers (see common.decode_samples).
        """
        import torch

        pipe = self.pipe
        pipe.set_progress_bar_config(disable=True)
        area = int(self.minfo.get("area", 1024))
        was_training = self.transformer.training
        self.transformer.eval()
        out = [None] * len(prompts)
        told_about_negatives = False
        with self.sampling(self.transformer):
            for idxs, ps, ns, w, h in common.sample_groups(prompts, area, batch):
                gens = [torch.Generator("cpu").manual_seed(seed * 1000 + i)
                        for i in idxs]
                if any(n for n in ns) and not told_about_negatives:
                    told_about_negatives = True
                    print("note: FLUX.2 takes no negative prompt — the test "
                          "prompts' negatives are ignored", flush=True)
                with torch.no_grad():
                    imgs = pipe(
                        prompt=ps,
                        num_inference_steps=steps, guidance_scale=cfg,
                        width=w, height=h,
                        generator=gens if len(gens) > 1 else gens[0],
                        callback_on_step_end=common.step_end_checker(check),
                    ).images
                for slot, img in zip(idxs, imgs):
                    out[slot] = img
                    if on_image is not None:
                        on_image(slot, img)
        if was_training:
            self.transformer.train()
        return out

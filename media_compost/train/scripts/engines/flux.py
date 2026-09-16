"""FLUX.1 engine: flow-matching transformer, CLIP-L + T5-XXL.

The original FLUX. Same rectified-flow objective as the Chroma and FLUX.2
engines — sample a timestep ``t`` (logit-normal, shifted by
``model_params.flow_shift``), mix ``x_t = (1 - t)·x0 + t·noise``, regress the
transformer's velocity onto ``noise − x0`` — over the FLUX 2×2 packed latent
layout.

Two things are its own, and both are read off the model rather than assumed:

* the conditioning is TWO encoders. T5-XXL supplies the token sequence and
  CLIP-L supplies a single POOLED vector, which rides in a separate argument
  (``pooled_projections``) rather than being concatenated — the pipeline's
  ``encode_prompt`` returns the pair and this engine passes both through.
* FLUX.1 dev is GUIDANCE-DISTILLED: the guidance scale is an input to the
  transformer, not something a sampler applies outside it. A run has to feed
  one, and it has to be the scale images will be generated at, or the model
  is taught the wrong thing at every scale. `transformer.config.guidance_embeds`
  says whether this checkpoint has one (dev does, schnell does not).

Chroma is a FLUX.1-schnell derivative but is NOT this engine: it dropped the
CLIP encoder and the guidance embedding for its own conditioning, which is
why diffusers gives it a pipeline of its own — and why a LoRA from one does
not apply to the other.

EITHER ENCODER MAY CARRY AN ADAPTER (`train_text_encoder`): CLIP-L always
when the switch is on — it is 0.12B parameters and what most FLUX LoRA
tooling means by training the text encoder — and T5-XXL beside it unless
`train_text_encoder_large` is off. T5 is the expensive half (4.76B
parameters, 512 tokens kept for the backward pass), and it is what the
int8 encoder quantization and the encoder-side gradient checkpointing exist
to make fit on a 32 GB card. The CLIP-L adapter travels in the portable file
(diffusers' FLUX loader has a `text_encoder` slot); the T5 adapter has no
slot there and stays in the trainer's own file, which the Evaluate tab reads.
"""

from __future__ import annotations

from . import common
from .common import BaseEngine, T5_LORA_TARGETS, masked_mean, param_group

#: The diffusers pipeline this model generates with. Read by
#: `generate.py` (the Evaluate tab), which builds a pipeline without
#: constructing an engine — so it lives HERE rather than in a second
#: table that a new model can be left out of.
PIPELINE = "FluxPipeline"
#: …and the family this engine serves. FLUX.1 Kontext is the same transformer
#: with the reference picture's latents concatenated onto the sequence, so it
#: is this engine and this architecture group — a Kontext LoRA IS a FLUX.1
#: LoRA. See `common.pipeline_class`; the model's own snapshot picks.
PIPELINES = ("FluxPipeline", "FluxKontextPipeline")

# The joint-stream projections: the image side plus the `add_*` pair that
# carries the text stream through the double blocks.
TRANSFORMER_LORA_TARGETS = [
    "to_q", "to_k", "to_v", "to_out.0", "add_q_proj", "add_k_proj",
    "add_v_proj", "to_add_out",
]


class Engine(BaseEngine):
    # 8 from the VAE, doubled by the 2x2 patchify — see
    # BaseEngine.image_step.
    image_step = 16
    backbone_component = "transformer"
    # ComfyUI's `Flux` branch builds `key_map["lycoris_{}"]` over
    # `flux_to_diffusers(...)`'s own names — the module paths this adapter is
    # attached to — so a LoKr trained here can be written in a naming it
    # reads. FLUX.1 Kontext loads through the same branch.
    lycoris_named = True
    # CLIP-L for the pooled vector and T5-XXL for the sequence. T5 is 4.76B of
    # the 4.88B pair, so the second name is the one that matters.
    text_encoder_components = ("text_encoder", "text_encoder_2")
    # Both may be trained; T5 is the large one and its attention is named
    # the T5 way. See the module docstring.
    trainable_text_encoders = ("text_encoder", "text_encoder_2")
    large_text_encoders = ("text_encoder_2",)
    text_encoder_targets = {"text_encoder_2": tuple(T5_LORA_TARGETS)}

    adapter_targets = tuple(TRANSFORMER_LORA_TARGETS)
    flow_matching = True

    def load(self) -> None:
        cls = common.pipeline_class(self._pipeline_source(), PIPELINE, PIPELINES)
        pipe = self._from_pretrained(cls)
        # What came back, not what was asked for: `cls` is usually the auto
        # loader, so the model itself decided whether this is dev or Kontext.
        cls = common.check_family(pipe, PIPELINES, "FLUX.1")
        # Kept: `encode_prompt` is what knows how the two encoders combine.
        self.pipe = pipe
        self.tokenizer = pipe.tokenizer
        self.text_encoder = pipe.text_encoder          # CLIP-L (pooled)
        self.text_encoder_2 = pipe.text_encoder_2      # T5-XXL (sequence)
        self.vae = pipe.vae
        self.transformer = pipe.transformer
        self.sample_scheduler = pipe.scheduler
        self.pipe_cls = cls

        self.vae.requires_grad_(False)
        # Both encoders start frozen, and stay so in a full finetune — that
        # means the transformer here, exactly as it means the UNet for
        # SD/SDXL. A LoRA run may lay an adapter over either of them
        # (`attach_adapter`, through `trained_text_encoders`).
        self.text_encoder.requires_grad_(False)
        self.text_encoder_2.requires_grad_(False)
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
        self.text_encoder_2.to(self.device)
        self.transformer.to(self.device)
        self.upcast_trainable()

    def _text_encoders(self):
        return [self.text_encoder, self.text_encoder_2]

    def trainable_params(self, lr: float):
        groups = [param_group(self.transformer.parameters(), lr)]
        if self.train_te and self.method == "lora":
            te_lr = float(self.hyper.get("te_lr", 0) or 0) or lr * 0.5
            for te in self.trained_text_encoders().values():
                groups.append(param_group(te.parameters(), te_lr))
        return groups

    # -- latents --------------------------------------------------------------

    # 2x2 patch packing, as in FluxPipeline._pack_latents / _unpack_latents.
    # The static helpers on the pipeline take (and return) their own argument
    # shapes, so the same two lines Chroma writes are written here.
    def _pack(self, lat):
        b, c, h, w = lat.shape
        lat = lat.view(b, c, h // 2, 2, w // 2, 2)
        lat = lat.permute(0, 2, 4, 1, 3, 5)
        return lat.reshape(b, (h // 2) * (w // 2), c * 4)

    def _unpack(self, packed, h, w, c):
        b = packed.shape[0]
        lat = packed.view(b, h // 2, w // 2, c, 2, 2)
        lat = lat.permute(0, 3, 1, 4, 2, 5)
        return lat.reshape(b, c, h, w)

    def _guidance(self, b: int, device):
        """The distilled guidance embedding, or None for a checkpoint without
        one (schnell). See the module docstring."""
        import torch

        if not getattr(self.transformer.config, "guidance_embeds", False):
            return None
        scale = float(self.model_params.get("guidance", 1.0) or 1.0)
        return torch.full([b], scale, device=device, dtype=torch.float32)

    def _encode_prompts(self, captions: list[str]):
        # Gradients only while an encoder is training (`_te_grad`): the
        # pipeline's helper is not itself wrapped in `no_grad`, which is
        # what lets the adapter on T5 or CLIP-L learn through it.
        with self._te_grad():
            embeds, pooled, text_ids = self.pipe.encode_prompt(
                prompt=list(captions), prompt_2=None, device=self.device)
        return embeds.to(self.dtype), pooled.to(self.dtype), text_ids

    def _reference_tokens(self, refs, budget: int, device):
        """One visit's references as `(packed tokens, position ids)`.

        Packed exactly as the target is, with ids whose FIRST coordinate is 1
        rather than 0 — that one number is the whole of how Kontext tells a
        picture it was given from the picture it is making, and the model was
        trained with it set. Several references share it (the pipeline offers
        one), so they are laid end to end and distinguished by position only.
        """
        import torch

        per_sample = [self.encode_refs(one, budget) for one in refs]
        packed, ids = [], None
        for one in per_sample:
            packed.append(torch.cat(
                [self._pack(lat).squeeze(0) for lat in one], dim=0))
        for lat in per_sample[0]:
            part = self.pipe_cls._prepare_latent_image_ids(
                1, lat.shape[2] // 2, lat.shape[3] // 2, device, self.dtype)
            part = part.clone()
            part[..., 0] = 1
            ids = part if ids is None else torch.cat([ids, part], dim=0)
        return torch.stack(packed), ids

    def train_step(self, latents, captions, weights, rng, masks=None,
                   refs=None):
        import torch
        import torch.nn.functional as F

        b, c, lh, lw = latents.shape
        embeds, pooled, text_ids = self._encode_prompts(captions)

        # WHICH NOISE LEVEL this sample trains on — see timesteps.py. The
        # resolution shift rides on the model parameter it always did.
        t = self.flow_position(b, latents.device)
        t_ = t.view(b, 1, 1, 1)

        noise = torch.randn_like(latents)
        noisy = (1.0 - t_) * latents + t_ * noise

        packed = self._pack(noisy)                       # (b, tokens, c*4)
        img_ids = self.pipe_cls._prepare_latent_image_ids(
            b, lh // 2, lw // 2, latents.device, self.dtype)
        # An INSTRUCTION visit's references ride behind the picture being
        # produced. `n_img` is taken BEFORE they are added: it is what the
        # prediction has to be cut back to.
        n_img = packed.shape[1]
        if refs and any(refs):
            ref_tokens, ref_ids = self._reference_tokens(
                refs, (lh * self.latent_scale) * (lw * self.latent_scale),
                latents.device)
            packed = torch.cat([packed, ref_tokens.to(packed.dtype)], dim=1)
            # `img_ids` is (tokens, 3) here, not batched — FLUX shares one set
            # across the batch, which holds because this call's samples share
            # a layout.
            img_ids = torch.cat([img_ids, ref_ids], dim=0)
        with self.autocast():
            pred = self.transformer(
                hidden_states=packed.to(self.dtype),
                # The sampling loop passes `timestep / 1000` for a 0..1000
                # scheduler timestep; ours is already the 0..1 flow position.
                timestep=t.to(self.dtype),
                guidance=self._guidance(b, latents.device),
                pooled_projections=pooled,
                encoder_hidden_states=embeds,
                txt_ids=text_ids,
                img_ids=img_ids,
                return_dict=False,
            )[0]
        pred = self._unpack(pred[:, :n_img], lh, lw, c)

        target = noise - latents
        loss = F.mse_loss(pred.float(), target.float(), reduction="none")
        loss = masked_mean(loss, masks)
        wt = torch.tensor(weights, device=loss.device, dtype=loss.dtype)
        return (loss * wt).mean()

    # Weights: saving, loading and the portable file are BaseEngine's. The
    # portable file carries the transformer's layers and, when trained, the
    # CLIP-L adapter under diffusers' `text_encoder` slot; the T5-XXL adapter
    # (`text_encoder_2`) is not in `portable_text_encoders` — FLUX's loader
    # has no slot for it — and stays in the trainer's own file.

    # -- samples --------------------------------------------------------------

    def generate_samples(self, prompts, seed, steps, cfg, batch=1,
                         on_image=None, check=None):
        """`prompts` are (prompt, negative, width, height); a None size falls
        back to the model's native area.

        `guidance_scale` here is the DISTILLED guidance the transformer takes,
        not a CFG pass — FLUX.1 runs one forward per step. A negative prompt
        is therefore only honoured through the pipeline's `true_cfg_scale`,
        which doubles the cost; the test prompts' negatives are dropped with a
        line in the log, as FLUX.2 does.

        Like the other flow-matching engines this keeps the pipeline's own
        decode: the latents are packed in a layout only the pipeline knows how
        to undo, and its VAE runs at the model dtype, so the MPS cast that
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
                    print("note: FLUX.1 is guidance-distilled and takes no "
                          "negative prompt — the test prompts' negatives are "
                          "ignored", flush=True)
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

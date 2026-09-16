"""Z-Image engine: single-stream flow-matching DiT with a Qwen3 encoder.

Tongyi's Z-Image — a 6B single-stream transformer with a Qwen3 text encoder
and the FLUX VAE, so the base class's `encode_image` (which subtracts the
VAE's `shift_factor` before scaling) is exactly right and the latent cache is
the ordinary `(1, 16, h/8, w/8)`.

Three things are its own, and each is the kind of thing that trains happily
against a distribution the model was never shown:

* THE TIME AXIS RUNS THE OTHER WAY. The transformer is given ``1 - σ`` where
  every other engine here passes ``σ`` (the noise fraction). The pipeline
  writes it as ``(1000 - t) / 1000`` and it is easy to read past.
* SO DOES THE VELOCITY. The pipeline negates the model's output before
  handing it to the scheduler, so what the model itself predicts is
  ``x0 − noise``, not the usual ``noise − x0``. Training on the usual target
  teaches it the exact opposite of what it knows, and the loss curve looks
  perfectly ordinary while it happens.
* THE BATCH IS A LIST. Both the latents and the conditioning arrive as
  per-sample lists — a latent as ``(c, 1, h, w)``, a caption as its own
  variable-length ``(tokens, 2560)`` with the padding already dropped — and
  the model returns a list too. So there is no attention mask to build and no
  padded position to mask out; the ragged batch IS the mask.

The 2×2 patchify happens INSIDE the transformer, so this engine never packs
anything and `latent_scale` stays 8 — but the picture still has to be a
multiple of 16, which the default bucket step of 64 satisfies.
"""

from __future__ import annotations

from . import common
from .common import DIT_LORA_TARGETS, BaseEngine, masked_mean, param_group

#: The diffusers pipeline this model generates with. Read by
#: `generate.py` (the Evaluate tab), which builds a pipeline without
#: constructing an engine — so it lives HERE rather than in a second
#: table that a new model can be left out of.
PIPELINE = "ZImagePipeline"

#: Single-stream: one attention per block, text and image tokens in one
#: sequence, so there is no `add_*` pair to adapt.
TRANSFORMER_LORA_TARGETS = DIT_LORA_TARGETS

#: What the transformer patchifies internally. The picture must be a multiple
#: of this times the VAE's 8, or the patchify reshape fails several frames
#: below with nothing but a shape in the message.
PATCH = 2


class Engine(BaseEngine):
    # 8 from the VAE, doubled by the 2x2 patchify — see
    # BaseEngine.image_step.
    image_step = 16
    backbone_component = "transformer"

    adapter_targets = tuple(TRANSFORMER_LORA_TARGETS)
    flow_matching = True

    def load(self) -> None:
        from diffusers import ZImagePipeline

        pipe = self._from_pretrained(ZImagePipeline)
        # Kept: `_encode_prompt` is the chat template, the tapped hidden layer
        # and the per-caption unpadding, none of which is worth a copy here.
        self.pipe = pipe
        self.tokenizer = pipe.tokenizer
        self.text_encoder = pipe.text_encoder     # Qwen3
        self.vae = pipe.vae
        self.transformer = pipe.transformer
        self.sample_scheduler = pipe.scheduler
        self.pipe_cls = ZImagePipeline

        self.vae.requires_grad_(False)
        # The Qwen3 encoder is conditioning only and stays frozen in BOTH
        # methods, so a "full finetune" here means the transformer — exactly
        # as it means the UNet for SD/SDXL.
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

    def encode_image(self, img):
        """The base class's latent, refusing a size the patchify cannot take.

        Z-Image's VAE is the FLUX one (shift 0.1159, scale 0.3611), so the
        scaling is the base class's; what is added is the guard, because the
        reshape that fails is inside the model and says only "shape [...] is
        invalid for input of size N".
        """
        step = self.step
        w, h = img.size
        if w % step or h % step:
            raise ValueError(
                f"Z-Image needs image sizes that are multiples of {step} px; "
                f"got {w}x{h}. Set the dataset's bucket step to a multiple of "
                f"{step} (64 is the default).")
        return super().encode_image(img)

    def _encode_prompts(self, captions: list[str]):
        """One variable-length embedding per caption, padding already dropped.

        `list(captions)` because the pipeline's helper rewrites its argument
        in place while applying the chat template, and the caller's list is
        the batch the loop is still using.
        """
        import torch

        with torch.no_grad():
            return self.pipe._encode_prompt(prompt=list(captions),
                                            device=self.device)

    def train_step(self, latents, captions, weights, rng, masks=None):
        import torch
        import torch.nn.functional as F

        b = latents.shape[0]
        embeds = [e.to(self.dtype) for e in self._encode_prompts(captions)]

        # WHICH NOISE LEVEL this sample trains on — see timesteps.py. The
        # resolution shift rides on the model parameter it always did.
        t = self.flow_position(b, latents.device)
        t_ = t.view(b, 1, 1, 1)

        noise = torch.randn_like(latents)
        noisy = (1.0 - t_) * latents + t_ * noise

        # A list of (c, 1, h, w), which is what the transformer's ragged
        # batching takes — and what it hands back.
        x = list(noisy.to(self.dtype).unsqueeze(2).unbind(dim=0))
        with self.autocast():
            out = self.transformer(
                x,
                # The other way round from every other engine here: the model
                # counts CLEAN signal, not noise. See the module docstring.
                (1.0 - t).to(self.dtype),
                embeds,
                return_dict=False,
            )[0]
        pred = torch.stack(out, dim=0).squeeze(2)

        # …and its velocity points the other way too.
        target = latents - noise
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

        Z-Image does take a real negative prompt — it runs true CFG, so a
        guided round is two forwards per step. The pipeline owns the decode:
        its VAE runs at the model dtype, so the MPS cast that blackens SDXL
        samples never triggers (see common.decode_samples).
        """
        import torch

        pipe = self.pipe
        pipe.set_progress_bar_config(disable=True)
        area = int(self.minfo.get("area", 1024))
        was_training = self.transformer.training
        self.transformer.eval()
        out = [None] * len(prompts)
        with self.sampling(self.transformer):
            for idxs, ps, ns, w, h in common.sample_groups(prompts, area, batch):
                # One generator per slot, seeded exactly as it would be alone,
                # so a batched sample is the same image as an unbatched one.
                gens = [torch.Generator("cpu").manual_seed(seed * 1000 + i)
                        for i in idxs]
                with torch.no_grad():
                    imgs = pipe(
                        prompt=ps, negative_prompt=ns,
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

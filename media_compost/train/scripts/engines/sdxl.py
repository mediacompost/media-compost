"""SDXL engine: LoRA and full UNet finetune.

Mirrors diffusers' ``train_dreambooth_lora_sdxl.py``: two CLIP text encoders
(concatenated hidden states + pooled embedding), size/crop micro-conditioning
via ``add_time_ids``, epsilon-prediction MSE with optional Min-SNR / noise
offset. Full finetune trains the UNet only (both TEs stay frozen) and really
wants the memory savers on anything under ~40 GB.
"""

from __future__ import annotations

from pathlib import Path

from . import common
from .common import BaseEngine, param_group

#: The diffusers pipeline this model generates with. Read by
#: `generate.py` (the Evaluate tab), which builds a pipeline without
#: constructing an engine — so it lives HERE rather than in a second
#: table that a new model can be left out of.
PIPELINE = "StableDiffusionXLPipeline"


class Engine(BaseEngine):
    # Two of them — CLIP-L and OpenCLIP ViT-bigG — and the second is the big
    # one (0.69B against 0.12B), so naming only the first would quantize the
    # smaller sixth of `aux_gb`.
    text_encoder_components = ("text_encoder", "text_encoder_2")

    #: BOTH of them. `StableDiffusionXLPipeline.save_lora_weights` has a
    #: slot for each (`text_encoder_lora_layers` and
    #: `text_encoder_2_lora_layers`), and `save_portable` below writes both
    #: — so both are in the portable file and `generate._attach_parts` must
    #: not come back for either. Left at the base default (`text_encoder`
    #: alone) it claimed the second one lived only in the trainer's own
    #: file, and loading such an adapter attached it TWICE: once by
    #: diffusers out of the portable file and once by hand, which PEFT
    #: refuses with "Adapter with name l0 already exists".
    portable_text_encoders = ("text_encoder", "text_encoder_2")

    def load(self) -> None:
        import torch
        from diffusers import DDPMScheduler, StableDiffusionXLPipeline

        pipe = self._from_pretrained(StableDiffusionXLPipeline)
        self.tokenizers = [pipe.tokenizer, pipe.tokenizer_2]
        self.text_encoders = [pipe.text_encoder, pipe.text_encoder_2]
        self.vae = pipe.vae
        self.unet = pipe.unet
        self.noise_scheduler = DDPMScheduler.from_config(pipe.scheduler.config)
        self.sample_scheduler = pipe.scheduler

        self.vae.requires_grad_(False)
        # The SDXL fp16 VAE is numerically fragile; encode in fp32.
        self.vae.to(dtype=torch.float32)
        for te in self.text_encoders:
            te.requires_grad_(False)
        if self.method == "lora":
            self.attach_adapter()
        else:
            self.unet.requires_grad_(True)
        if self.hyper.get("gradient_checkpointing"):
            self.unet.enable_gradient_checkpointing()
        # After the adapter is attached and the base is frozen —
        # `apply_fp8` converts exactly the weights that stay frozen.
        fp8 = self.apply_fp8(self.unet)
        if fp8:
            print(f"frozen weights stored as fp8 ({fp8} layers)", flush=True)
        if self.apply_attention_slicing(self.unet):
            print("attention slicing on", flush=True)

        self.vae.to(self.device)
        for te in self.text_encoders:
            te.to(self.device)
        self.unet.to(self.device)
        self.upcast_trainable()

    def _text_encoders(self):
        return self.text_encoders

    def trained_text_encoders(self) -> dict:
        """Both of them, under the names the PIPELINE uses.

        They used to be saved as `te1`/`te2` — a spelling only this engine
        knew, and the one place the seven copies of the weight I/O had already
        drifted apart.
        """
        return {"text_encoder": self.text_encoders[0],
                "text_encoder_2": self.text_encoders[1]}

    def trainable_params(self, lr: float):
        groups = [param_group(self.unet.parameters(), lr)]
        if self.train_te and self.method == "lora":
            te_lr = float(self.hyper.get("te_lr", 0) or 0) or lr * 0.5
            for te in self.text_encoders:
                groups.append(param_group(te.parameters(), te_lr))
        return groups

    def encode_image(self, img):
        import numpy as np
        import torch

        arr = np.asarray(img, dtype=np.float32) / 127.5 - 1.0
        px = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0)
        px = px.to(self.device, dtype=torch.float32)  # fp32 VAE (see load)
        with torch.no_grad():
            lat = self.vae.encode(px).latent_dist.sample()
        return lat * self.vae.config.scaling_factor

    def _encode_prompts(self, captions: list[str]):
        import torch

        te_training = any(p.requires_grad
                          for te in self.text_encoders
                          for p in te.parameters())
        embeds = []
        ctx = torch.enable_grad() if te_training else torch.no_grad()
        with ctx:
            for tok, te in zip(self.tokenizers, self.text_encoders):
                ids = tok(
                    captions, padding="max_length", truncation=True,
                    max_length=tok.model_max_length, return_tensors="pt",
                ).input_ids.to(self.device)
                out = te(ids, output_hidden_states=True)
                # Penultimate hidden state, per SDXL convention.
                embeds.append(out.hidden_states[-2])
            # Pooled conditioning comes from TE2 (a CLIP projection model).
            pooled = out.text_embeds
        return torch.cat(embeds, dim=-1), pooled

    def train_step(self, latents, captions, weights, rng, masks=None):
        import torch

        hidden, pooled = self._encode_prompts(captions)
        noisy, noise, timesteps = self._add_noise(latents, rng)
        b, _, lh, lw = latents.shape
        h, w = lh * 8, lw * 8
        add_time_ids = torch.tensor(
            [[h, w, 0, 0, h, w]] * b, device=self.device, dtype=hidden.dtype
        )
        # Under autocast, so a FULL finetune's fp32 master weights still do
        # their matmuls in `self.dtype` — see BaseEngine.autocast, and the
        # note in `sd.py`: this engine and that one were the two that did not
        # wrap, so a full finetune died at the first forward.
        with self.autocast():
            pred = self.unet(
                noisy, timesteps, encoder_hidden_states=hidden,
                added_cond_kwargs={"text_embeds": pooled,
                                   "time_ids": add_time_ids},
            ).sample
        return self._diffusion_loss(pred, noise, latents, timesteps,
                                    weights, masks)

    # -- weights ------------------------------------------------------------
    #
    # Saving, loading and the full-finetune paths are BaseEngine's. Only the
    # PORTABLE file is written here, because diffusers names a text-encoder
    # layer set per encoder and this model has two.

    def save_portable(self, out: Path) -> None:
        from diffusers import StableDiffusionXLPipeline
        from diffusers.utils import convert_state_dict_to_diffusers

        layers = {"unet_lora_layers": convert_state_dict_to_diffusers(
            self._lora_state(self.unet))}
        if self.train_te:
            layers["text_encoder_lora_layers"] = \
                convert_state_dict_to_diffusers(
                    self._lora_state(self.text_encoders[0]))
            layers["text_encoder_2_lora_layers"] = \
                convert_state_dict_to_diffusers(
                    self._lora_state(self.text_encoders[1]))
        StableDiffusionXLPipeline.save_lora_weights(out, **layers)

    # -- samples --------------------------------------------------------------

    def generate_samples(self, prompts, seed, steps, cfg, batch=1,
                         on_image=None, check=None):
        """`prompts` are (prompt, negative, width, height) — a None size falls
        back to the model's native area, so each slot can have its own.

        `on_image(slot, image)` is called as each image finishes, so the caller
        can write it out while the rest of the round is still rendering.
        `check` is polled once per denoising step (pause/cancel)."""
        import torch
        from diffusers import StableDiffusionXLPipeline

        pipe = StableDiffusionXLPipeline(
            vae=self.vae, text_encoder=self.text_encoders[0],
            text_encoder_2=self.text_encoders[1],
            tokenizer=self.tokenizers[0], tokenizer_2=self.tokenizers[1],
            unet=self.unet, scheduler=self.sample_scheduler,
        )
        pipe.set_progress_bar_config(disable=True)
        area = int(self.minfo.get("area", 1024))
        was_training = self.unet.training
        self.unet.eval()
        out = [None] * len(prompts)
        # Same modules the trainer holds; the VAE goes back where it was.
        with self.sampling(self.unet):
            for idxs, ps, ns, w, h in common.sample_groups(prompts, area, batch):
                # One generator per slot, seeded exactly as it would be alone, so
                # a batched sample is the same image as an unbatched one.
                gens = [torch.Generator("cpu").manual_seed(seed * 1000 + i)
                        for i in idxs]
                with torch.no_grad():
                    # Latents, not images: SDXL's VAE is fp32 here on purpose,
                    # and the pipeline's own decode would cast it down to the
                    # latents' dtype on MPS and hand back black squares. See
                    # common.decode_samples.
                    lat = pipe(
                        ps, negative_prompt=ns,
                        num_inference_steps=steps, guidance_scale=cfg,
                        width=w, height=h,
                        generator=gens if len(gens) > 1 else gens[0],
                        callback_on_step_end=common.step_end_checker(check),
                        output_type="latent",
                    ).images
                imgs = common.decode_samples(pipe, self.vae, lat)
                for slot, img in zip(idxs, imgs):
                    out[slot] = img
                    if on_image is not None:
                        on_image(slot, img)
        if was_training:
            self.unet.train()
        return out

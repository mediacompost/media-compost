"""Stable Diffusion 1.5 engine: LoRA and full UNet finetune.

Follows diffusers' reference ``train_dreambooth_lora.py`` / ``train_text_to_
image.py`` recipes: epsilon-prediction MSE on DDPM-noised latents, optional
Min-SNR weighting and noise offset (model_params), optional CLIP text-encoder
LoRA.
"""

from __future__ import annotations

from pathlib import Path

from . import common
from .common import BaseEngine, param_group

#: The diffusers pipeline this model generates with. Read by
#: `generate.py` (the Evaluate tab), which builds a pipeline without
#: constructing an engine — so it lives HERE rather than in a second
#: table that a new model can be left out of.
PIPELINE = "StableDiffusionPipeline"


class Engine(BaseEngine):
    def load(self) -> None:
        from diffusers import DDPMScheduler, StableDiffusionPipeline

        pipe = self._from_pretrained(StableDiffusionPipeline)
        self.tokenizer = pipe.tokenizer
        self.text_encoder = pipe.text_encoder
        self.vae = pipe.vae
        self.unet = pipe.unet
        self.noise_scheduler = DDPMScheduler.from_config(pipe.scheduler.config)
        self.sample_scheduler = pipe.scheduler

        self.vae.requires_grad_(False)
        self.text_encoder.requires_grad_(False)
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
        self.text_encoder.to(self.device)
        self.unet.to(self.device)
        self.upcast_trainable()

    def _text_encoders(self):
        return [self.text_encoder]

    def trained_text_encoders(self) -> dict:
        return {"text_encoder": self.text_encoder}

    def trainable_params(self, lr: float):
        groups = [param_group(self.unet.parameters(), lr)]
        if self.train_te and self.method == "lora":
            te_lr = float(self.hyper.get("te_lr", 0) or 0) or lr * 0.5
            groups.append(param_group(self.text_encoder.parameters(), te_lr))
        return groups

    def _encode_prompts(self, captions: list[str]):
        import torch

        ids = self.tokenizer(
            captions, padding="max_length", truncation=True,
            max_length=self.tokenizer.model_max_length, return_tensors="pt",
        ).input_ids.to(self.device)
        te_training = any(p.requires_grad
                          for p in self.text_encoder.parameters())
        if te_training:
            return self.text_encoder(ids)[0]
        with torch.no_grad():
            return self.text_encoder(ids)[0]

    def train_step(self, latents, captions, weights, rng, masks=None):
        hidden = self._encode_prompts(captions)
        noisy, noise, timesteps = self._add_noise(latents, rng)
        # Under autocast, so a FULL finetune's fp32 master weights still do
        # their matmuls in `self.dtype` — see BaseEngine.autocast. A no-op for
        # LoRA, where the base is already that dtype.
        #
        # This engine and `sdxl.py` were the two that did NOT wrap, while the
        # five DiT engines all did — and `load()` calls `upcast_trainable()`
        # either way, which for `method != "lora"` takes the WHOLE UNet to
        # fp32. So a full finetune died at the first forward with "expected
        # mat1 and mat2 to have the same dtype", on the two models most likely
        # to be finetuned. Both are `lora_only: False`, so the editor offers
        # the method.
        with self.autocast():
            pred = self.unet(noisy, timesteps,
                             encoder_hidden_states=hidden).sample
        return self._diffusion_loss(pred, noise, latents, timesteps,
                                    weights, masks)

    # -- weights ------------------------------------------------------------
    #
    # Saving, loading and the full-finetune paths are BaseEngine's. Only the
    # PORTABLE file is written here, because diffusers names the text-encoder
    # layer set separately from the UNet's.

    def save_portable(self, out: Path) -> None:
        from diffusers import StableDiffusionPipeline
        from diffusers.utils import convert_state_dict_to_diffusers

        layers = {"unet_lora_layers": convert_state_dict_to_diffusers(
            self._lora_state(self.unet))}
        if self.train_te:
            layers["text_encoder_lora_layers"] = \
                convert_state_dict_to_diffusers(
                    self._lora_state(self.text_encoder))
        StableDiffusionPipeline.save_lora_weights(out, **layers)

    # -- samples --------------------------------------------------------------

    def generate_samples(self, prompts, seed, steps, cfg, batch=1,
                         on_image=None, check=None):
        """`prompts` are (prompt, negative, width, height) — a None size falls
        back to the model's native area, so each slot can have its own.

        `on_image(slot, image)` is called as each image finishes, so the caller
        can write it out while the rest of the round is still rendering.
        `check` is polled once per denoising step (pause/cancel)."""
        import torch
        from diffusers import StableDiffusionPipeline

        pipe = StableDiffusionPipeline(
            vae=self.vae, text_encoder=self.text_encoder,
            tokenizer=self.tokenizer, unet=self.unet,
            scheduler=self.sample_scheduler, safety_checker=None,
            feature_extractor=None, requires_safety_checker=False,
        )
        pipe.set_progress_bar_config(disable=True)
        area = int(self.minfo.get("area", 512))
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
                    # Latents, not images: see common.decode_samples for why
                    # the pipeline must not do the decode itself.
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

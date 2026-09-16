"""Qwen-Image engine: 20B MMDiT, Qwen2.5-VL encoder, editing included.

Serves the whole Qwen-Image family — the plain text-to-image releases and the
Edit ones, which are the same 20B transformer over the same VAE and differ in
what their pipeline puts in front of it. So one engine, one architecture
group, and the class comes off the model itself (`common.pipeline_class`).

The objective is the ordinary rectified-flow one: mix
``x_t = (1 - t)·x0 + t·noise``, regress the velocity onto ``noise − x0``, pass
the flow position as the timestep. What is its own:

* THE POSITIONS ARE SHAPES, not ids. The transformer takes ``img_shapes`` —
  a list per sample of ``(frames, h/2, w/2)``, the TARGET first and then one
  entry per reference picture — and builds the rotary coordinates itself. It
  is the same statement FLUX makes with an id tensor, made shorter.
* THE VAE IS THE QWEN-IMAGE VIDEO VAE, exactly as Krea 2's is: 5-D tensors
  and a per-channel mean and standard deviation rather than one
  `scaling_factor`. A still is one frame.
* THE TEXT ENCODER SEES THE REFERENCES TOO. Qwen2.5-VL is a vision-language
  model and the edit pipelines put an image token in the prompt template per
  reference, so the same pictures reach both halves of the conditioning —
  which is why this engine takes them from `load_refs` once and hands them to
  `encode_prompt` as well as to the VAE.

An EDIT run conditions on the instruction's reference pictures; a plain run
on this same engine passes none and trains as any text-to-image model does.
"""

from __future__ import annotations

from . import common
from .common import DIT_LORA_TARGETS, BaseEngine, masked_mean, param_group

#: The diffusers pipeline this model generates with. Read by
#: `generate.py` (the Evaluate tab), which builds a pipeline without
#: constructing an engine — so it lives HERE rather than in a second
#: table that a new model can be left out of.
PIPELINE = "QwenImagePipeline"
#: …and the family this engine serves: the Edit releases are the same
#: architecture with reference pictures added, so a LoRA carries between them.
PIPELINES = ("QwenImagePipeline", "QwenImageEditPipeline",
             "QwenImageEditPlusPipeline")

#: Single-stream joint attention: text and image tokens share one sequence.
TRANSFORMER_LORA_TARGETS = DIT_LORA_TARGETS + [
    "add_q_proj", "add_k_proj", "add_v_proj", "to_add_out",
]

#: What the transformer patchifies internally, on top of the VAE's 8.
PATCH = 2


class Engine(BaseEngine):
    # 8 from the VAE, doubled by the 2x2 patchify — see
    # BaseEngine.image_step.
    image_step = 16
    backbone_component = "transformer"
    # ComfyUI's `QwenImage` branch builds `key_map["lycoris_{}"]` over its
    # own `diffusion_model.`-stripped keys, which are the diffusers module
    # paths this adapter attaches to.
    lycoris_named = True

    adapter_targets = tuple(TRANSFORMER_LORA_TARGETS)
    flow_matching = True

    def load(self) -> None:

        cls = common.pipeline_class(self._pipeline_source(), PIPELINE, PIPELINES)
        pipe = self._from_pretrained(cls)
        # What came back, not what was asked for: the model itself decided
        # whether this is a plain release or one of the Edit ones.
        cls = common.check_family(pipe, PIPELINES, "Qwen-Image")
        # Kept: its prompt template, its packing and (for the Edit releases)
        # the image tokens it puts in the prompt ARE the model's recipe.
        self.pipe = pipe
        self.tokenizer = pipe.tokenizer
        self.text_encoder = pipe.text_encoder     # Qwen2.5-VL
        self.vae = pipe.vae
        self.transformer = pipe.transformer
        self.sample_scheduler = pipe.scheduler
        self.pipe_cls = cls

        self.vae.requires_grad_(False)
        # The vision-language encoder is conditioning only and stays frozen in
        # BOTH methods, so a "full finetune" here means the transformer —
        # exactly as it means the UNet for SD/SDXL.
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
        return []  # the vision-language encoder is never trained

    def trainable_params(self, lr: float):
        return [param_group(self.transformer.parameters(), lr)]

    # -- latents --------------------------------------------------------------

    def _latent_stats(self, device, dtype):
        """The VAE's per-channel mean and standard deviation, shaped to
        broadcast over ``(b, c, f, h, w)``.

        Not a `scaling_factor`: this VAE's decode is `lat * std + mean` per
        channel, so the encode has to undo exactly that. A scalar here would
        train against a distribution shifted differently in every one of the
        sixteen channels, with nothing in the loss to say so.
        """
        import torch

        cfg = self.vae.config
        mean = torch.tensor(cfg.latents_mean, device=device, dtype=dtype)
        std = torch.tensor(cfg.latents_std, device=device, dtype=dtype)
        return mean.view(1, -1, 1, 1, 1), std.view(1, -1, 1, 1, 1)

    def encode_image(self, img):
        """Pixel image -> the transformer's latent, ``(1, 16, h/8, w/8)``.

        The frame axis the video VAE wants is added here and dropped again, so
        everything above this — the cache, the crop window, the alpha mask —
        sees the same 4-D latent every other engine produces.
        """
        import numpy as np
        import torch

        step = self.step
        w, h = img.size
        if w % step or h % step:
            raise ValueError(
                f"Qwen-Image needs image sizes that are multiples of {step} "
                f"px; got {w}x{h}. Set the dataset's bucket step to a multiple "
                f"of {step} (64 is the default).")
        arr = np.asarray(img, dtype=np.float32) / 127.5 - 1.0
        px = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).unsqueeze(2)
        px = px.to(self.device, dtype=self.vae.dtype)
        with torch.no_grad():
            lat = self.vae.encode(px).latent_dist.sample()
        mean, std = self._latent_stats(lat.device, lat.dtype)
        return ((lat - mean) / std).squeeze(2)

    def _unpack(self, packed, h, w, c):
        """Inverse of the pipeline's `_pack_latents`. Its own `_unpack_latents`
        is written in PIXELS and returns the 5-D video layout, so the loss —
        which is taken in the latent's own `(b, c, h, w)`, the shape the alpha
        mask is built for — needs this instead."""
        b = packed.shape[0]
        lat = packed.view(b, h // PATCH, w // PATCH, c, PATCH, PATCH)
        lat = lat.permute(0, 3, 1, 4, 2, 5)
        return lat.reshape(b, c, h, w)

    def _guidance(self, b: int, device):
        """The distilled guidance embedding, or None for a checkpoint without
        one — asked of the transformer's config, exactly as the pipeline asks
        it."""
        import torch

        if not getattr(self.transformer.config, "guidance_embeds", False):
            return None
        scale = float(self.model_params.get("guidance", 1.0) or 1.0)
        return torch.full([b], scale, device=device, dtype=torch.float32)

    def _encode_prompts(self, captions: list[str], images=None):
        """Prompt embeddings and their mask.

        `images` are one visit's references, and they are passed to the SAME
        `encode_prompt` the pipeline uses when it edits: the template grows an
        image token per reference and the vision-language encoder reads them.
        Leaving them out would train the text side on a prompt the model never
        sees at generation time. Only the Edit pipelines accept the argument,
        which is why it is passed by name and only when there is one.
        """
        import torch

        import inspect

        kwargs = {"prompt": list(captions), "device": self.device}
        if images:
            # Ask the signature rather than tabling which releases edit: only
            # the Edit pipelines take an image, and handing one to a plain
            # release would be a TypeError. Dropping it silently instead is
            # the version to avoid — the model would be trained on a prompt
            # whose reference tokens it never saw.
            if "image" not in inspect.signature(
                    self.pipe.encode_prompt).parameters:
                raise RuntimeError(
                    f"{type(self.pipe).__name__} takes no reference picture "
                    "in its prompt, so it cannot be trained on instructions. "
                    "Pick one of the Qwen-Image Edit releases.")
            kwargs["image"] = images
        with torch.no_grad():
            embeds, mask = self.pipe.encode_prompt(**kwargs)
        return embeds.to(self.dtype), mask

    @staticmethod
    def _pad_prompts(parts):
        """Per-sample prompt encodings stacked into one batch.

        They have to be encoded one at a time when there are references —
        `encode_prompt` applies ONE image list to every prompt it is given, so
        a batch would show every sample every sample's pictures — and each
        then comes out its own length, because the image tokens depend on how
        many references there were and how big they are. So they are padded to
        the longest and the mask is materialised: a sample whose own mask came
        back None (the pipeline's way of saying "every token counts") still
        needs zeros over the padding, or the model attends to positions that
        hold nothing.
        """
        import torch

        width = max(p[0].shape[1] for p in parts)
        embeds, masks = [], []
        for emb, m in parts:
            n = emb.shape[1]
            if n < width:
                emb = torch.nn.functional.pad(emb, (0, 0, 0, width - n))
            embeds.append(emb)
            row = torch.zeros(1, width, device=emb.device, dtype=torch.long)
            row[:, :n] = 1 if m is None else m[:, :n].long()
            masks.append(row)
        return torch.cat(embeds, dim=0), torch.cat(masks, dim=0)

    def train_step(self, latents, captions, weights, rng, masks=None,
                   refs=None):
        import torch
        import torch.nn.functional as F

        b, c, lh, lw = latents.shape
        budget = (lh * self.latent_scale) * (lw * self.latent_scale)
        # Opened ONCE: the same pixels go to the text encoder and the VAE.
        ref_images = [self.load_refs(one, budget) for one in (refs or [])]
        # The pipeline's `encode_prompt` takes ONE list of images for the whole
        # batch — it was written for a single prompt's references. Every sample
        # in this call shares a layout but not its pictures, so the prompts are
        # encoded per sample and stacked.
        if ref_images and any(ref_images):
            parts = [self._encode_prompts([captions[i]], ref_images[i])
                     for i in range(b)]
            embeds, mask = self._pad_prompts(parts)
        else:
            embeds, mask = self._encode_prompts(captions)

        # WHICH NOISE LEVEL this sample trains on — see timesteps.py. The
        # resolution shift rides on the model parameter it always did.
        t = self.flow_position(b, latents.device)
        t_ = t.view(b, 1, 1, 1)

        noise = torch.randn_like(latents)
        noisy = (1.0 - t_) * latents + t_ * noise

        packed = self.pipe._pack_latents(noisy, b, c, lh, lw)
        # The target's grid first; each reference's behind it. This list IS
        # the model's sense of where everything is, so a reference left out of
        # it lands on top of the picture being produced.
        shapes = [(1, lh // PATCH, lw // PATCH)]
        n_img = packed.shape[1]
        if ref_images and any(ref_images):
            per_sample = [[self.encode_image(im) for im in one]
                          for one in ref_images]
            packed = torch.cat([packed, torch.stack([
                torch.cat([self.pipe._pack_latents(
                    lat, 1, lat.shape[1], lat.shape[2], lat.shape[3]).squeeze(0)
                    for lat in one], dim=0)
                for one in per_sample]).to(packed.dtype)], dim=1)
            shapes += [(1, lat.shape[2] // PATCH, lat.shape[3] // PATCH)
                       for lat in per_sample[0]]

        with self.autocast():
            pred = self.transformer(
                hidden_states=packed.to(self.dtype),
                timestep=t.to(self.dtype),
                guidance=self._guidance(b, latents.device),
                encoder_hidden_states=embeds,
                encoder_hidden_states_mask=mask,
                img_shapes=[shapes] * b,
                return_dict=False,
            )[0]
        pred = self._unpack(pred[:, :n_img], lh, lw, c)

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

        An EDIT release is being sampled here without a reference picture,
        which is not what it does at generation time — the sample is still
        worth having as a look at what the run has learnt, and the pipeline
        accepts the call, so this says nothing and renders.
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
                        num_inference_steps=steps, true_cfg_scale=cfg,
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

"""Chroma engine: flow-matching transformer, T5 text encoder.

Chroma (lodestones' FLUX.1-schnell derivative, Apache-2.0) trains with the
rectified-flow objective used by diffusers' FLUX LoRA script: sample a
timestep ``t`` (logit-normal, shifted by ``model_params.flow_shift``), mix
``x_t = (1 - t)·x0 + t·noise``, and regress the transformer's velocity onto
``noise − x0``. Latents are packed into 2×2 patch tokens like FLUX.

NOTE: this engine follows the diffusers ChromaPipeline component layout and
the reference FLUX training recipe, but it has not had a real-hardware smoke
run yet (the model needs ~18 GB of weights) — validate on a GPU box before
relying on it.

T5 MAY CARRY AN ADAPTER (`train_text_encoder`). It is Chroma's only encoder,
so it is also the LARGE one, and `train_text_encoder_large` left off has
nothing to fall back to — `trained_text_encoders` refuses that rather than
training nothing. Its adapter travels in the portable file: diffusers'
Chroma loader keys its one encoder slot `text_encoder`, and that is T5 here.
"""

from __future__ import annotations

from . import common
from .common import BaseEngine, T5_LORA_TARGETS, masked_mean, param_group

#: The diffusers pipeline this model generates with. Read by
#: `generate.py` (the Evaluate tab), which builds a pipeline without
#: constructing an engine — so it lives HERE rather than in a second
#: table that a new model can be left out of.
PIPELINE = "ChromaPipeline"

TRANSFORMER_LORA_TARGETS = [
    "to_q", "to_k", "to_v", "to_out.0", "add_q_proj", "add_k_proj",
    "add_v_proj", "to_add_out",
]


class Engine(BaseEngine):
    # 8 from the VAE, doubled by the 2x2 patchify — see
    # BaseEngine.image_step.
    image_step = 16
    backbone_component = "transformer"
    # T5, the only encoder — trainable, large, and named the T5 way.
    trainable_text_encoders = ("text_encoder",)
    large_text_encoders = ("text_encoder",)
    text_encoder_targets = {"text_encoder": tuple(T5_LORA_TARGETS)}

    adapter_targets = tuple(TRANSFORMER_LORA_TARGETS)
    flow_matching = True

    def load(self) -> None:
        from diffusers import ChromaPipeline

        pipe = self._from_pretrained(ChromaPipeline)
        # Kept so the attention mask below is built by the pipeline's own
        # helper rather than a copy of it (see `_encode_prompts`).
        self.pipe = pipe
        self.tokenizer = pipe.tokenizer
        self.text_encoder = pipe.text_encoder     # T5
        self.vae = pipe.vae
        self.transformer = pipe.transformer
        self.sample_scheduler = pipe.scheduler
        self.pipe_cls = ChromaPipeline

        self.vae.requires_grad_(False)
        # T5 starts frozen and stays so in a full finetune — that means the
        # transformer here, exactly as it means the UNet for SD/SDXL. A LoRA
        # run may lay an adapter over it (`attach_adapter`).
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
        return [self.text_encoder]

    def trainable_params(self, lr: float):
        groups = [param_group(self.transformer.parameters(), lr)]
        if self.train_te and self.method == "lora":
            te_lr = float(self.hyper.get("te_lr", 0) or 0) or lr * 0.5
            for te in self.trained_text_encoders().values():
                groups.append(param_group(te.parameters(), te_lr))
        return groups

    def _encode_prompts(self, captions: list[str]):
        """Chroma's conditioning, exactly as ChromaPipeline builds it.

        Two details that are easy to get wrong, and were: the padded
        embeddings are NOT zeroed, and the transformer is given an attention
        mask covering every text token up to and INCLUDING the first padding
        one (the ``<=`` below — the pipeline's comment says the model requires
        that). Zeroing instead still lets attention see those positions, so a
        run trained that way is conditioned differently from every image it
        will later generate — with nothing in the loss to say so.
        """
        import torch

        tok = self.tokenizer(
            captions, padding="max_length", truncation=True, max_length=512,
            return_tensors="pt",
        )
        ids = tok.input_ids.to(self.device)
        mask = tok.attention_mask.to(self.device)
        # Gradients only while T5 is training (`_te_grad`).
        with self._te_grad():
            embeds = self.text_encoder(ids, output_hidden_states=False,
                                       attention_mask=mask)[0]
        seq_lengths = mask.sum(dim=1)
        idx = torch.arange(mask.size(1), device=self.device)
        idx = idx.unsqueeze(0).expand(len(captions), -1)
        text_mask = (idx <= seq_lengths.unsqueeze(1)).to(dtype=embeds.dtype)
        text_ids = torch.zeros(embeds.shape[1], 3, device=self.device,
                               dtype=embeds.dtype)
        return embeds.to(self.dtype), text_ids, text_mask

    def train_step(self, latents, captions, weights, rng, masks=None):
        import torch
        import torch.nn.functional as F

        b, c, lh, lw = latents.shape
        embeds, text_ids, text_mask = self._encode_prompts(captions)

        # WHICH NOISE LEVEL this sample trains on — see timesteps.py. The
        # resolution shift rides on the model parameter it always did.
        t = self.flow_position(b, latents.device)
        t_ = t.view(b, 1, 1, 1)

        noise = torch.randn_like(latents)
        noisy = (1.0 - t_) * latents + t_ * noise

        packed = self._pack(noisy)                       # (b, tokens, c*4)
        img_ids = self._img_ids(lh, lw, latents.device)
        # The mask spans the JOINT sequence: text tokens as computed, then
        # ones for every image token. The pipeline's helper does the extending.
        attn_mask = self.pipe._prepare_attention_mask(
            b, packed.shape[1], embeds.dtype, text_mask)
        # Under autocast, so a FULL finetune's fp32 master weights still do
        # their matmuls in `self.dtype` — see BaseEngine.autocast. A no-op for
        # LoRA, where the base is already that dtype.
        with self.autocast():
            pred = self.transformer(
                hidden_states=packed.to(self.dtype),
                timestep=t.to(self.dtype),
                encoder_hidden_states=embeds,
                txt_ids=text_ids,
                img_ids=img_ids,
                attention_mask=attn_mask,
                return_dict=False,
            )[0]
        pred = self._unpack(pred, lh, lw, c)

        target = noise - latents
        loss = F.mse_loss(pred.float(), target.float(), reduction="none")
        loss = masked_mean(loss, masks)
        wt = torch.tensor(weights, device=loss.device, dtype=loss.dtype)
        return (loss * wt).mean()

    # 2×2 patch packing, as in FluxPipeline._pack_latents / _unpack_latents.
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

    def _img_ids(self, lh: int, lw: int, device):
        import torch

        ids = torch.zeros(lh // 2, lw // 2, 3, device=device)
        ids[..., 1] = torch.arange(lh // 2, device=device)[:, None]
        ids[..., 2] = torch.arange(lw // 2, device=device)[None, :]
        return ids.reshape(-1, 3).to(self.dtype)

    # Weights: saving, loading and the portable file are BaseEngine's. The
    # portable file carries the transformer's layers and, when trained, the
    # T5 adapter under diffusers' `text_encoder` slot (the default
    # `portable_text_encoders`).

    # -- samples --------------------------------------------------------------

    def generate_samples(self, prompts, seed, steps, cfg, batch=1,
                         on_image=None, check=None):
        """`prompts` are (prompt, negative, width, height) — a None size falls
        back to the model's native area, so each slot can have its own.

        `on_image(slot, image)` is called as each image finishes, so the caller
        can write it out while the rest of the round is still rendering.
        `check` is polled once per denoising step (pause/cancel).

        Chroma keeps the pipeline's own decode: its latents are packed in the
        FLUX layout, so unpacking them here would duplicate pipeline internals
        — and unlike SDXL its VAE runs at the model dtype, so the MPS cast
        that blackens SDXL samples never triggers (see common.decode_samples).
        """
        import torch

        pipe = self.pipe_cls(
            tokenizer=self.tokenizer, text_encoder=self.text_encoder,
            vae=self.vae, transformer=self.transformer,
            scheduler=self.sample_scheduler,
        )
        pipe.set_progress_bar_config(disable=True)
        area = int(self.minfo.get("area", 1024))
        was_training = self.transformer.training
        self.transformer.eval()
        out = [None] * len(prompts)
        # Same modules the trainer holds; the VAE goes back where it was.
        with self.sampling(self.transformer):
            for idxs, ps, ns, w, h in common.sample_groups(prompts, area, batch):
                # One generator per slot, seeded exactly as it would be alone, so
                # a batched sample is the same image as an unbatched one.
                gens = [torch.Generator("cpu").manual_seed(seed * 1000 + i)
                        for i in idxs]
                with torch.no_grad():
                    imgs = pipe(
                        ps, negative_prompt=ns,
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

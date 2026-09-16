"""One real training step through an engine, on a tiny random-weight model.

STANDALONE, and run by `test_engine_smoke.py` in the TRAINING interpreter —
the engines import torch and diffusers, which live in `.venv-training` and are
in no CI job, so `train/scripts/engines/*` had 0% coverage and every
numeric rule in them was guarded by nothing. It imports no project code, like
the trainer scripts themselves and `fake_trainer/`: it is handed the scripts
directory and works from there.

This was a MANUAL procedure: validate a new engine on a tiny random-weight
model built from the real repo's configs, long before — or instead of —
waiting on a multi-GB download. This is that procedure written down, for all
seven engines. Nothing is downloaded.

WHAT IS REAL AND WHAT IS STUBBED, because that is the whole question about a
harness like this:

  * the ENGINE is real — the actual `Engine` class, its actual `train_step`,
    its actual adapter attachment and fp32 upcast.
  * the BACKBONE is real diffusers, constructed small. `attention_head_dim`
    and `norm_num_groups` keep honest values (`axes_dims_rope` has to sum to
    the head dim, which is exactly the sort of thing a shrunk model gets
    wrong); layers and widths are cut to the smallest thing that runs.
  * the PIPELINE HELPERS are real: `_pack_latents`, `_prepare_latent_ids`,
    `_prepare_attention_mask` and friends are diffusers' own functions,
    reached through `_pipe_shim` rather than reimplemented. Getting the
    packing subtly wrong in a test that then "passes" would be worse than no
    test.
  * only TEXT ENCODING is stubbed. A tokenizer and a text encoder are the
    download-heavy half and are not what an engine's `train_step` is being
    asked about; the stub returns tensors of the dtype and rank the real
    encoder produces.

THE SAME MISMATCH DIES TWO WAYS, which is why `--device` exists. On the CPU
torch raises "mat1 and mat2 must have the same dtype" and this reports it as
exit 2; on MPS the same matmul trips a Metal assertion that calls `abort()`,
which no `try` can catch — so the caller aims the deliberate-failure case at
the CPU, and everything else at whatever the machine has. Running it on the
default device SIGABRTed a child twice per suite run and left two crash
reports in `~/Library/Logs/DiagnosticReports` each time.

Exit codes: 0 with a `RESULT ` line on success, 1 for a model with nothing
trainable, 2 for the dtype mismatch. Anything else is a genuine crash and the
caller reports the child's output.
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import inspect
import json
import random
import sys
import types

#: Engines whose backbone is a UNet. The rest are DiTs, which differ in more
#: than size: a transformer instead of a unet, a packed token sequence instead
#: of a 4-D latent, and a flow-matching target.
UNET_ENGINES = ("sd", "sdxl")

#: Real-ish attention head width. `axes_dims_rope` must SUM to it — a tiny
#: model that gets that wrong fails inside the rotary embedding, which is one
#: of the traps this procedure is written around.
HEAD = 16
ROPE3 = (4, 6, 6)
ROPE4 = (4, 4, 4, 4)

BATCH, LH, LW, TXT = 2, 8, 8, 5


def build_unet(engine: str):
    """A tiny UNet of the right SHAPE for the engine under test."""
    from diffusers import UNet2DConditionModel

    extra = {}
    if engine == "sdxl":
        # SDXL conditions on a pooled embedding plus six "time ids"; the
        # projection width is what ties those together, and the engine builds
        # the time ids itself in `train_step`.
        extra = {"addition_embed_type": "text_time",
                 "addition_time_embed_dim": 8,
                 "projection_class_embeddings_input_dim": 8 * 6 + 16,
                 "transformer_layers_per_block": 1}
    return UNet2DConditionModel(
        sample_size=8, in_channels=4, out_channels=4, layers_per_block=1,
        block_out_channels=(32, 64),
        down_block_types=("DownBlock2D", "CrossAttnDownBlock2D"),
        up_block_types=("CrossAttnUpBlock2D", "UpBlock2D"),
        cross_attention_dim=32, norm_num_groups=32, attention_head_dim=8,
        **extra), None


def build_dit(engine: str):
    """A tiny transformer plus the PIPELINE CLASS its engine reaches into.

    TWO layers, not one, for the DiTs: QwenImage's last block does not use its
    text-branch output projection, so a one-block model reports those adapter
    weights as ungradiented and it reads as a broken attachment rather than as
    the architecture.
    """
    import diffusers as d

    if engine == "flux":
        # `guidance_embeds=True` on purpose: it is what makes `_guidance()`
        # return a tensor rather than None, so that branch is exercised.
        return d.FluxTransformer2DModel(
            patch_size=1, in_channels=64, num_layers=2, num_single_layers=1,
            attention_head_dim=HEAD, num_attention_heads=2,
            joint_attention_dim=32, pooled_projection_dim=16,
            guidance_embeds=True, axes_dims_rope=ROPE3), d.FluxPipeline
    if engine == "chroma":
        return d.ChromaTransformer2DModel(
            patch_size=1, in_channels=64, num_layers=2, num_single_layers=1,
            attention_head_dim=HEAD, num_attention_heads=2,
            joint_attention_dim=32, axes_dims_rope=ROPE3,
            approximator_num_channels=16, approximator_hidden_dim=32,
            approximator_layers=1), d.ChromaPipeline
    if engine == "qwenimage":
        return d.QwenImageTransformer2DModel(
            patch_size=2, in_channels=64, out_channels=16, num_layers=2,
            attention_head_dim=HEAD, num_attention_heads=2,
            joint_attention_dim=32, guidance_embeds=False,
            axes_dims_rope=ROPE3), d.QwenImagePipeline
    if engine == "zimage":
        return d.ZImageTransformer2DModel(
            all_patch_size=(2,), all_f_patch_size=(1,), in_channels=16,
            dim=32, n_layers=2, n_refiner_layers=1, n_heads=2, n_kv_heads=2,
            cap_feat_dim=32, axes_dims=[4, 6, 6],
            axes_lens=[128, 64, 64]), d.ZImagePipeline
    if engine == "flux2":
        return d.Flux2Transformer2DModel(
            patch_size=1, in_channels=128, num_layers=2, num_single_layers=1,
            attention_head_dim=HEAD, num_attention_heads=2,
            joint_attention_dim=48, axes_dims_rope=ROPE4,
            guidance_embeds=False), d.Flux2KleinPipeline
    raise SystemExit(f"engine_smoke has no model for {engine!r}")


def _pipe_shim(cls):
    """The pipeline surface `train_step` reaches, backed by diffusers' OWN
    implementations — nothing here reimplements packing or masking.

    A staticmethod fetched off the class is a plain function and can be hung on
    a namespace as-is. Chroma's `_prepare_attention_mask` is an INSTANCE method
    that happens to use nothing from `self`, so it takes a `None`. Copying them
    into a class body instead re-binds the staticmethods as instance methods,
    which fails as "takes 1 positional argument but 2 were given".
    """
    out = {}
    for name in ("_prepare_attention_mask", "_pack_latents",
                 "_prepare_latent_ids", "_prepare_image_ids",
                 "_prepare_latent_image_ids", "_encode_vae_image"):
        raw = inspect.getattr_static(cls, name, None)
        if raw is None:
            continue
        fn = getattr(cls, name)
        out[name] = (fn if isinstance(raw, (staticmethod, classmethod))
                     else functools.partial(fn, None))
    return types.SimpleNamespace(**out)


def stub_text_encoder(engine: str, engine_obj, torch, device, dtype):
    """Text encoding, at the rank and dtype the real encoder returns.

    Each engine's helper has its own contract — `flux` hands back a pooled
    projection as well, `chroma` a mask, `zimage` a LIST (its transformer
    batches raggedly) — and getting one wrong shows up as a shape error rather
    than as a wrong answer, which is why they are spelled out per engine.
    """
    def emb(width, batch=BATCH):
        return torch.randn(batch, TXT, width, device=device, dtype=dtype)

    if engine == "flux":
        engine_obj._encode_prompts = lambda caps: (
            emb(32), torch.randn(BATCH, 16, device=device, dtype=dtype),
            torch.zeros(TXT, 3, device=device, dtype=dtype))
    elif engine == "chroma":
        engine_obj._encode_prompts = lambda caps: (
            emb(32), torch.zeros(TXT, 3, device=device, dtype=dtype),
            torch.ones(BATCH, TXT, device=device, dtype=torch.bool))
    elif engine == "flux2":
        engine_obj._encode_prompts = lambda caps: (
            emb(48), torch.zeros(BATCH, TXT, 4, device=device, dtype=dtype))
    elif engine == "qwenimage":
        engine_obj._encode_prompts = lambda caps, images=None: (
            emb(32), torch.ones(BATCH, TXT, device=device, dtype=torch.int64))
    elif engine == "zimage":
        engine_obj._encode_prompts = lambda caps: [
            torch.randn(TXT, 32, device=device, dtype=dtype)
            for _ in range(BATCH)]
    elif engine == "sdxl":
        engine_obj._encode_prompts = lambda caps: (
            emb(32), torch.randn(BATCH, 16, device=device, dtype=dtype))
    else:
        engine_obj._encode_prompts = lambda caps: emb(32)


#: Latent channel count per engine. FLUX.2 patchifies 2x2 into channels before
#: the cache ever sees a latent, which is the same reason its `latent_scale`
#: is 16 where every other engine's is 8.
LATENT_CHANNELS = {"sd": 4, "sdxl": 4, "flux": 16, "chroma": 16,
                   "qwenimage": 16, "zimage": 16, "flux2": 128}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scripts", required=True)
    ap.add_argument("--engine", required=True)
    ap.add_argument("--method", default="lora")
    ap.add_argument("--device", default="")
    ap.add_argument("--no-autocast", action="store_true",
                    help="drop the wrap, to prove the check can fail")
    ap.add_argument("--text-encoder", action="store_true",
                    help="train the engine's text encoder(s) too, on tiny "
                         "real encoders in place of the stub")
    a = ap.parse_args()

    sys.path.insert(0, a.scripts)
    import torch
    from diffusers import DDPMScheduler

    import engines.common as common
    mod = __import__(f"engines.{a.engine}", fromlist=["Engine"])

    if a.no_autocast:
        common.BaseEngine.autocast = lambda self: contextlib.nullcontext()

    device = a.device or ("mps" if torch.backends.mps.is_available()
                          else "cuda" if torch.cuda.is_available() else "cpu")
    # bf16 ALWAYS, the CPU included: at fp32 `autocast()` is a documented
    # no-op and the mismatch this harness is about cannot arise at all.
    dtype = torch.bfloat16

    torch.manual_seed(1234)
    unet_like = a.engine in UNET_ENGINES
    model, pipe_cls = (build_unet if unet_like else build_dit)(a.engine)
    model = model.to(device, dtype)

    # With `--text-encoder`, gradient checkpointing too: it is what
    # `_prepare_text_encoder` turns on inside the encoder (train mode,
    # dropout zeroed, non-reentrant), and the reentrant default is exactly
    # the setting that drops an adapter's gradients inside a checkpointed
    # block — so the check below has to run WITH it on to mean anything.
    # `load()` is not called here, so the flag reaches nothing else.
    hyper = ({"train_text_encoder": True, "gradient_checkpointing": True}
             if a.text_encoder else {})
    engine = mod.Engine({"method": a.method, "hyper": hyper,
                         "model_params": {}},
                        {"repo": "tiny", "local": False}, device, dtype)
    if unet_like:
        engine.unet = model
        engine.noise_scheduler = DDPMScheduler(num_train_timesteps=1000)
    else:
        engine.transformer = model
        engine.pipe_cls = pipe_cls
        engine.pipe = _pipe_shim(pipe_cls)
    if a.text_encoder:
        encoders = build_text_encoders(a.engine, engine, torch, device, dtype)
    else:
        # This run trains no text encoder, and `upcast_trainable` walks them.
        engine.trained_text_encoders = lambda: {}
        encoders = {}

    # Exactly what `load()` does for the method, and the upcast every engine
    # runs after attaching or unfreezing.
    if a.method == "lora":
        engine.attach_adapter()
    else:
        model.requires_grad_(True)
    engine.upcast_trainable()

    trainable = [(n, p) for n, p in model.named_parameters() if p.requires_grad]
    if not trainable:
        print("FAIL no trainable parameters — the adapter matched nothing")
        return 1
    weight_dtypes = sorted({str(p.dtype) for _, p in trainable})

    torch.manual_seed(99)
    channels = LATENT_CHANNELS[a.engine]
    latents = torch.randn(BATCH, channels, LH, LW, device=device, dtype=dtype)
    if a.text_encoder:
        real_text_encoding(a.engine, engine, torch, device, dtype)
    else:
        stub_text_encoder(a.engine, engine, torch, device, dtype)
    te_trainable = [(f"{part}.{n}", p)
                    for part, te in encoders.items()
                    for n, p in te.named_parameters() if p.requires_grad]
    if a.text_encoder and not te_trainable:
        print("FAIL no trainable text-encoder parameters — the adapter "
              "matched nothing")
        return 1

    try:
        # A `random.Random`, which is what `loop.py` hands an engine — NOT a
        # `torch.Generator`. `_add_noise` calls `rng.getrandbits(31)` to seed a
        # per-device generator everywhere except MPS, where it passes None and
        # never touches the argument. So a torch.Generator here works on MPS
        # and raises AttributeError the moment the same harness is aimed at the
        # CPU: a stub that matches the caller only on the machine it was
        # written on.
        out = engine.train_step(latents, ["a fox"] * BATCH,
                                torch.ones(BATCH, device=device),
                                random.Random(0))
    except RuntimeError as exc:
        # The dtype mismatch, reported rather than crashed out of. On the CPU
        # torch raises this cleanly; on MPS the same thing is a Metal
        # assertion that calls abort(), which is why the negative case is
        # pinned to the CPU by its caller.
        print(f"MISMATCH {exc}")
        return 2
    loss = out[0] if isinstance(out, tuple) else out
    loss.backward()

    no_grad = sorted(n for n, p in trainable if p.grad is None)
    non_finite = sorted(n for n, p in trainable
                        if p.grad is not None
                        and not torch.isfinite(p.grad).all())
    # How many blocks the backbone has, so the caller can tell "the LAST
    # block's text branch is unused" — which is architecture — from "a block
    # in the middle got no gradient", which is a broken attachment.
    blocks = {int(n.split(".")[1]) for n, _ in model.named_parameters()
              if n.startswith("transformer_blocks.") and n.split(".")[1].isdigit()}
    print("RESULT " + json.dumps({
        "engine": a.engine, "method": a.method, "device": device,
        "dtype": str(dtype), "loss": float(loss),
        "loss_finite": bool(torch.isfinite(loss)),
        "trainable": len(trainable), "weight_dtypes": weight_dtypes,
        "without_grad": no_grad, "non_finite_grad": non_finite[:5],
        "last_block": max(blocks) if blocks else None,
        # The text-encoder adapter(s): which parts, how many parameters, and
        # the ones a backward pass never reached.
        "te_parts": sorted(encoders),
        "te_trainable": len(te_trainable),
        "te_without_grad": sorted(n for n, p in te_trainable if p.grad is None),
        "te_param_groups": len(engine.trainable_params(1e-4)) - 1,
    }))
    return 0


def build_text_encoders(engine: str, engine_obj, torch, device, dtype) -> dict:
    """Tiny REAL encoders where `stub_text_encoder` would put tensors.

    What the text-encoder run is asked about is whether the adapter reaches
    the encoder at all — that `T5_LORA_TARGETS` names modules a T5 actually
    has, that CLIP's targets still match its projections, and that a
    gradient makes it back through the transformer, the pipeline-free
    encode below and a checkpointed block into `lora_A`. None of that can be
    asked of a stub, so the encoders are real transformers models built
    from constants: T5's `d_model` is the transformer's
    `joint_attention_dim`, CLIP's `hidden_size` its `pooled_projection_dim`
    (FluxPipeline feeds `pooler_output` straight in). `dropout_rate` is
    deliberately NON-zero on the T5 config, so the run also proves
    `_prepare_text_encoder` zeroes it rather than feeding the transformer a
    noisy prompt.
    """
    import transformers as tf

    def t5():
        return tf.T5EncoderModel(tf.T5Config(
            vocab_size=64, d_model=32, d_kv=HEAD, d_ff=64, num_layers=2,
            num_heads=2, dropout_rate=0.1)).to(device, dtype)

    out = {}
    if engine == "flux":
        out["text_encoder"] = tf.CLIPTextModel(tf.CLIPTextConfig(
            vocab_size=64, hidden_size=16, intermediate_size=32,
            num_hidden_layers=2, num_attention_heads=2,
            max_position_embeddings=TXT)).to(device, dtype)
        out["text_encoder_2"] = t5()
    elif engine == "chroma":
        out["text_encoder"] = t5()
    else:
        raise SystemExit(f"engine_smoke trains no text encoder for {engine!r}")
    for name, te in out.items():
        te.requires_grad_(False)
        setattr(engine_obj, name, te)
    return out


def real_text_encoding(engine: str, engine_obj, torch, device, dtype):
    """The engine's encode helper over the tiny encoders — the same contract
    `stub_text_encoder` fills, but through the real modules, under the
    engine's own `_te_grad()` so the adapter inside them can learn."""
    def ids():
        return torch.randint(0, 64, (BATCH, TXT), device=device)

    if engine == "flux":
        def encode(caps):
            with engine_obj._te_grad():
                embeds = engine_obj.text_encoder_2(ids())[0]
                pooled = engine_obj.text_encoder(ids()).pooler_output
            return (embeds.to(dtype), pooled.to(dtype),
                    torch.zeros(TXT, 3, device=device, dtype=dtype))
        engine_obj._encode_prompts = encode
    elif engine == "chroma":
        def t5_encode(caps):
            mask = torch.ones(BATCH, TXT, device=device, dtype=torch.long)
            with engine_obj._te_grad():
                embeds = engine_obj.text_encoder(ids(), attention_mask=mask)[0]
            return (embeds.to(dtype),
                    torch.zeros(TXT, 3, device=device, dtype=dtype),
                    mask.to(torch.bool))
        engine_obj._encode_prompts = t5_encode


if __name__ == "__main__":
    raise SystemExit(main())

"""DINOv2-small feature vectors — the tag-batch overlay's queue ordering.

The one plugin whose result is a VECTOR: a 384-d unit-norm CLS embedding per
picture, stored in `item_embeddings` and read back by the session's numpy
classifier. The weights are the OFFICIAL `facebook/dinov2-small` release run
directly in torch — no ONNX conversion, no community export to vet — in the
same shape every other torch plugin uses: torch as a plugin dep, lazily
imported in the out-of-process worker, never in the server.

ViT-S/14 was chosen over the tagger-derived alternative (wd_tagger's
pre-threshold probability vector) for speed and RAM — ~0.1–0.3 s/image on CPU
against ViT-L's 1–3 s, ~85 MB of weights against 1.2 GB — and over CLIP
because its official weights load without a conversion step. Its features are
generic-visual rather than tag-aligned; the Magi paper's caveat about DINOv2
concerns drawn-character IDENTITY, not the tag-level semantics a membership
classifier learns.

The space string (`dinov2s-v1`, `media_compost.ui.itemvec.SPACE`) carries
every constant of this recipe — model, dim, dtype, preprocessing. Changing
any of them is a NEW string and a re-index, never a silent mix. The DEVICE
is deliberately not part of it: cuda, mps and cpu produce the same features
to within fp16's noise floor, so a library indexed on one machine reads on
another.

Runs on the accelerator when there is one and BATCHED (`run_batch`, the
worker's true-batch protocol over the job's chunks of 256). The chunk's
pictures reach it PREPARED: the worker decodes the library's files itself
and runs `prepare` beside the decode — in spawned processes on CUDA
(`wants_decode_processes`), on threads elsewhere — so what `run_batch`
receives is a list of uint8 crops the processor's own resize and crop
made; `_vit_embed.embed` finishes them on the device (the processor's
normalize over the batch) and runs the forward as a CUDA graph. The shape
and its measurements are in `_vit_embed.py`; the vectors are identical to
the one-call-per-chunk path's. The model is ~85 MB, so the GPU claim is
no real collision with a training run.
"""

from __future__ import annotations

try:
    from ..framework import (TRANSFORMERS_CONFIG_FILES, ModelSource, ModelSpec,
                            PluginManifest)

    MANIFEST = PluginManifest(
        models=[ModelSpec(id="dinov2_small", task="embed",
                          name="DINOv2 (small)", family="DINOv2",
                          note="Indexes pictures for the tag-batch "
                               "overlay's smart ordering.")],
        sources=[ModelSource(key="dinov2_small", label="DINOv2 (small)",
                             repo="facebook/dinov2-small",
                             url="https://huggingface.co/facebook/dinov2-small",
                             probe="model.safetensors",
                             allow_patterns=TRANSFORMERS_CONFIG_FILES
                             + ("model.safetensors",))],
        deps=("torch", "transformers"),
        url="https://huggingface.co/facebook/dinov2-small",
        source_for_model={"dinov2_small": "dinov2_small"},
    )
except (ImportError, ValueError):
    MANIFEST = None


def load_prep(load_key, ctx):  # pragma: no cover - heavy optional dep
    """The processor alone — what `prepare` takes. Built in every decode
    process (never the model), and once more by `load` for the host's
    single-picture path."""
    import torch
    from transformers import AutoImageProcessor

    src = ctx["sources"]["dinov2_small"]
    local_only = bool(ctx.get("local_files_only", True))
    token = ctx.get("token") or None
    # ONE torch thread in a decode process: sixteen of them each fanning a
    # 512 px resize over the machine's cores would fight one another for
    # nothing (`_vit_embed.single_cpu_thread_on` says the same of the worker).
    torch.set_num_threads(1)
    # THE TORCHVISION IMAGE PROCESSOR, where the env has torchvision: the PIL
    # one costs 50 ms a chunk of 32 on the worker's single thread and the
    # torchvision one 21 (measured, CPU — on the accelerator it is SLOWER,
    # the transfer outweighing the resize), and the vectors agree to five
    # decimals (cosine ≥ 0.99999 over 32 crawl pictures), so the space string
    # stays. Falls back to PIL where torchvision is missing or the installed
    # transformers predates the keyword. It runs per picture beside the
    # decode now (`prepare`), identically.
    try:
        return AutoImageProcessor.from_pretrained(
            src, local_files_only=local_only, token=token, backend="torchvision")
    except (TypeError, ImportError, ValueError):
        return AutoImageProcessor.from_pretrained(
            src, local_files_only=local_only, token=token)


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    import torch
    from transformers import AutoImageProcessor, AutoModel

    from . import _vit_embed as vit

    src = ctx["sources"]["dinov2_small"]
    local_only = bool(ctx.get("local_files_only", True))
    token = ctx.get("token") or None
    processor = load_prep(load_key, ctx)
    model = AutoModel.from_pretrained(
        src, local_files_only=local_only, token=token)
    model.eval()
    torch.set_grad_enabled(False)
    dev = vit.device()
    model = model.to(dev)
    vit.single_cpu_thread_on(dev)
    # The CLS token — the feature the space is built on.
    forward = vit.Forward(model, dev, lambda out: out.last_hidden_state[:, 0, :])
    return (processor, model, dev, forward)


def prepare(processor, image):  # pragma: no cover - heavy optional dep
    """The worker's per-picture hook, beside the decode: the processor's
    work for one picture (`_vit_embed.prepare`). ``processor`` is what
    `load_prep` built."""
    from . import _vit_embed as vit

    return vit.prepare(processor, image)


def wants_decode_processes(handle):  # pragma: no cover - heavy optional dep
    """Decode in processes only where the forward is faster than the
    decode — CUDA (`_vit_embed.wants_decode_processes`)."""
    from . import _vit_embed as vit

    return vit.wants_decode_processes(handle)


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy optional dep
    from . import _vit_embed as vit

    return vit.embed(handle, [image], "dinov2s-v1")[0]


def run_batch(task, model_id, handle, images, options):  # pragma: no cover - heavy optional dep
    from . import _vit_embed as vit

    return vit.embed(handle, images, "dinov2s-v1")

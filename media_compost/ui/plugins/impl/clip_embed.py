"""CLIP ViT-B/32 feature vectors — the tag-batch overlay's second embedder.

The alternative space beside DINOv2 (`dinov2_embed.py`, whose module
docstring carries the shared shape: accelerator when present, true-batched
`run_batch`, results returned RAW for the worker's one `_marshal` wrap).
CLIP's image tower is trained against language, so its features are aligned
with the words people tag by — measurably better on photographic, semantic
distinctions — where DINOv2's are purely visual and stronger on style and
composition. Which one orders a library better is an empirical question per
library, which is exactly why the chooser offers the pair instead of
deciding.

The OFFICIAL `openai/clip-vit-base-patch32` release, vision tower only
(`CLIPVisionModelWithProjection` — the text half never loads), taking the
PROJECTED image embedding: that is the space CLIP's semantics live in, not
the pre-projection hidden state. `allow_patterns` narrows the download to
the pytorch weights + configs — the repo also carries TF and Flax twins of
the same 600 MB.

The space string (`clipb32-v1`) carries every constant of the recipe —
model, dim, projection, preprocessing. Changing any of them is a NEW string
and a re-index, never a silent mix; the device is deliberately not part of
it (cuda/mps/cpu agree to within fp16's noise floor).
"""

from __future__ import annotations

try:
    from ..framework import (TRANSFORMERS_CONFIG_FILES, ModelSource, ModelSpec,
                            PluginManifest)

    MANIFEST = PluginManifest(
        models=[ModelSpec(id="clip_vit_b32", task="embed",
                          name="CLIP (ViT-B/32)", family="CLIP",
                          note="Indexes pictures for the tag-batch "
                               "overlay's smart ordering — language-aligned "
                               "features, an alternative to DINOv2.")],
        sources=[ModelSource(key="clip_vit_b32", label="CLIP (ViT-B/32)",
                             repo="openai/clip-vit-base-patch32",
                             url="https://huggingface.co/openai/clip-vit-base-patch32",
                             # THE ONE SOURCE HERE THAT NAMES A `.bin`, and it
                             # is not an oversight: this repo has no
                             # safetensors at all. It carries
                             # `pytorch_model.bin` plus a `tf_model.h5` and a
                             # `flax_model.msgpack` of the same 605 MB weights,
                             # which are two other frameworks' copies and are
                             # read by nothing here — 1.8 GB down to 609 MB.
                             # (A `*.safetensors` glob stood here matching
                             # nothing; a speculative pattern for a file that
                             # does not exist would silently double the
                             # download the day it did.)
                             probe="pytorch_model.bin",
                             allow_patterns=TRANSFORMERS_CONFIG_FILES
                             + ("pytorch_model.bin",))],
        deps=("torch", "transformers"),
        url="https://huggingface.co/openai/clip-vit-base-patch32",
        source_for_model={"clip_vit_b32": "clip_vit_b32"},
    )
except (ImportError, ValueError):
    MANIFEST = None


def load_prep(load_key, ctx):  # pragma: no cover - heavy optional dep
    """The processor alone — what `prepare` takes. Built in every decode
    process (never the model), and once more by `load` for the host's
    single-picture path."""
    import torch
    from transformers import AutoImageProcessor

    src = ctx["sources"]["clip_vit_b32"]
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
    from transformers import AutoImageProcessor, CLIPVisionModelWithProjection

    from . import _vit_embed as vit

    src = ctx["sources"]["clip_vit_b32"]
    local_only = bool(ctx.get("local_files_only", True))
    token = ctx.get("token") or None
    processor = load_prep(load_key, ctx)
    model = CLIPVisionModelWithProjection.from_pretrained(
        src, local_files_only=local_only, token=token)
    model.eval()
    torch.set_grad_enabled(False)
    dev = vit.device()
    model = model.to(dev)
    vit.single_cpu_thread_on(dev)
    # The projected image embedding — CLIP's own similarity space, not
    # the pre-projection hidden state.
    forward = vit.Forward(model, dev, lambda out: out.image_embeds)
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

    return vit.embed(handle, [image], "clipb32-v1")[0]


def run_batch(task, model_id, handle, images, options):  # pragma: no cover - heavy optional dep
    from . import _vit_embed as vit

    return vit.embed(handle, images, "clipb32-v1")

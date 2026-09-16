"""BLIP-2 captioning (frozen image encoder + OPT via transformers)."""

from __future__ import annotations

try:
    from ..framework import (TRANSFORMERS_CONFIG_FILES, ModelSource, ModelSpec,
                            PluginManifest)

    MANIFEST = PluginManifest(
        models=[ModelSpec(id="blip2", task="caption", name="BLIP-2", family="BLIP-2",
                          note="Salesforce vision-language captioner (frozen encoder + OPT).")],
        sources=[ModelSource(key="blip2", label="BLIP-2",
                             repo="Salesforce/blip2-opt-2.7b",
                             url="https://huggingface.co/Salesforce/blip2-opt-2.7b",
                             probe="model.safetensors.index.json",
                             # A SHARDED checkpoint has no stable single weight
                             # name to probe, so the probe is the safetensors
                             # INDEX: it exists only for this weight set, so a
                             # glob that fetched the wrong format reads as "not
                             # downloaded" rather than as ready.
                             allow_patterns=TRANSFORMERS_CONFIG_FILES
                             + ("model-*.safetensors",))],
        deps=("torch", "transformers"),
        url="https://huggingface.co/Salesforce/blip2-opt-2.7b",
        source_for_model={"blip2": "blip2"},
    )
except (ImportError, ValueError):
    MANIFEST = None


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    import torch
    from transformers import Blip2ForConditionalGeneration, Blip2Processor

    src = ctx["sources"]["blip2"]
    local_only = bool(ctx.get("local_files_only", True))
    token = ctx.get("token") or None
    processor = Blip2Processor.from_pretrained(src, local_files_only=local_only, token=token)
    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    model = Blip2ForConditionalGeneration.from_pretrained(
        src, local_files_only=local_only, token=token, torch_dtype=dtype)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    model.eval()
    return (processor, model, device)


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy optional dep
    import torch

    processor, model, device = handle
    inputs = processor(images=image.convert("RGB"), return_tensors="pt").to(
        device, model.dtype)
    with torch.no_grad():
        ids = model.generate(**inputs, max_new_tokens=64)
    return {"text": processor.batch_decode(ids, skip_special_tokens=True)[0].strip()}

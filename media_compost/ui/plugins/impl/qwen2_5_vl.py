"""Qwen2.5-VL free-form captioning (instruction VLM via transformers)."""

from __future__ import annotations

try:
    from ..framework import (TRANSFORMERS_CONFIG_FILES, ModelSource, ModelSpec,
                            PluginManifest)

    MANIFEST = PluginManifest(
        models=[ModelSpec(id="qwen2_5_vl", task="caption", name="Qwen2.5-VL",
                          family="Qwen2.5-VL",
                          note="Alibaba instruction-tuned VLM; free-form captions.")],
        sources=[ModelSource(key="qwen2_5_vl", label="Qwen2.5-VL",
                             repo="Qwen/Qwen2.5-VL-3B-Instruct",
                             url="https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct",
                             probe="model.safetensors.index.json",
                             # A SHARDED checkpoint has no stable single weight
                             # name to probe, so the probe is the safetensors
                             # INDEX: it exists only for this weight set, so a
                             # glob that fetched the wrong format reads as "not
                             # downloaded" rather than as ready.
                             allow_patterns=TRANSFORMERS_CONFIG_FILES
                             + ("model-*.safetensors",))],
        deps=("torch", "transformers", "accelerate", "qwen_vl_utils"),
        url="https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct",
        source_for_model={"qwen2_5_vl": "qwen2_5_vl"},
    )
except (ImportError, ValueError):
    MANIFEST = None


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

    src = ctx["sources"]["qwen2_5_vl"]
    local_only = bool(ctx.get("local_files_only", True))
    token = ctx.get("token") or None
    processor = AutoProcessor.from_pretrained(src, local_files_only=local_only, token=token)
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        src, local_files_only=local_only, token=token,
        torch_dtype="auto", device_map="auto")
    model.eval()
    return (processor, model)


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy optional dep
    import torch
    from qwen_vl_utils import process_vision_info

    processor, model = handle
    messages = [{"role": "user", "content": [
        {"type": "image", "image": image.convert("RGB")},
        {"type": "text", "text": "Describe this image in a single concise caption."},
    ]}]
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    image_inputs, video_inputs = process_vision_info(messages)
    inputs = processor(text=[text], images=image_inputs, videos=video_inputs,
                       padding=True, return_tensors="pt").to(model.device)
    with torch.no_grad():
        gen = model.generate(**inputs, max_new_tokens=128)
    trimmed = [out[len(inp):] for inp, out in zip(inputs.input_ids, gen)]
    return {"text": processor.batch_decode(
        trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False)[0].strip()}

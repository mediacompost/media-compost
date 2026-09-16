"""JoyCaption captioning (LLaVA-style, Llama 3.1 + SigLIP) with prompt variants."""

from __future__ import annotations

_URL = "https://github.com/fpgaminer/joycaption"

_PROMPTS = {
    "descriptive": "Write a long descriptive caption for this image in a formal tone.",
    "straightforward": (
        "Write a straightforward caption for this image. Begin with the main "
        "subject and medium. Mention pivotal elements and their spatial "
        "relationships. Avoid speculation and subjective judgment."
    ),
    "sd_prompt": "Write a stable diffusion prompt for this image.",
    "midjourney_prompt": "Write a MidJourney prompt for this image.",
}

try:
    from ..framework import (TRANSFORMERS_CONFIG_FILES, ModelSource, ModelSpec,
                            PluginManifest)

    _VARIANTS = [
        ("descriptive", "Descriptive", "A formal, detailed natural-language caption."),
        ("straightforward", "Straightforward",
         "Concise, no-nonsense description of the visible content."),
        ("sd_prompt", "Stable Diffusion Prompt",
         "A comma-separated prompt in image-generator style."),
        ("midjourney_prompt", "MidJourney Prompt", "A prompt in MidJourney style."),
    ]
    MANIFEST = PluginManifest(
        models=[ModelSpec(id=f"joycaption:{k}", task="caption",
                          name=f"JoyCaption — {label}", family="JoyCaption",
                          variant=label, note=note)
                for k, label, note in _VARIANTS],
        sources=[ModelSource(
            key="joycaption", label="JoyCaption",
            repo="fancyfeast/llama-joycaption-beta-one-hf-llava",
            url="https://huggingface.co/fancyfeast/llama-joycaption-beta-one-hf-llava",
            probe="model.safetensors.index.json",
            # Sharded — see blip2 for why the index is the probe.
            allow_patterns=TRANSFORMERS_CONFIG_FILES + ("model-*.safetensors",))],
        deps=("torch", "transformers", "accelerate"),
        url=_URL,
        source_for_model={f"joycaption:{k}": "joycaption" for k, _, _ in _VARIANTS},
    )
except (ImportError, ValueError):
    MANIFEST = None


def load_key(model_id):
    # All prompt variants share one loaded model — key on the family so switching
    # variants reuses the warm worker instead of reloading ~17 GB.
    return "joycaption"


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    from transformers import AutoProcessor, LlavaForConditionalGeneration

    name = ctx["sources"]["joycaption"]
    local_only = bool(ctx.get("local_files_only", True))
    token = ctx.get("token") or None
    proc = AutoProcessor.from_pretrained(name, local_files_only=local_only, token=token)
    mdl = LlavaForConditionalGeneration.from_pretrained(
        name, torch_dtype="bfloat16", device_map="auto",
        local_files_only=local_only, token=token,
    )
    mdl.eval()
    return (proc, mdl)


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy optional dep
    import torch

    proc, mdl = handle
    variant = model_id.split(":", 1)[1] if ":" in model_id else "descriptive"
    prompt = _PROMPTS.get(variant, _PROMPTS["descriptive"])
    convo = [
        {"role": "system", "content": "You are a helpful image captioner."},
        {"role": "user", "content": prompt},
    ]
    convo_str = proc.apply_chat_template(convo, tokenize=False, add_generation_prompt=True)
    inputs = proc(text=[convo_str], images=[image.convert("RGB")],
                  return_tensors="pt").to(mdl.device)
    with torch.no_grad():
        out = mdl.generate(**inputs, max_new_tokens=300, do_sample=False)
    gen = out[0][inputs["input_ids"].shape[1]:]
    return {"text": proc.tokenizer.decode(gen, skip_special_tokens=True).strip()}

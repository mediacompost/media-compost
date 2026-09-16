"""Florence-2 captioning + object-detection (Microsoft), run in a dedicated venv.

Florence-2's bundled remote code is incompatible with the app's transformers, so
it runs out-of-process in a ``florence`` environment (built by
``python -m media_compost.hub.setup_env florence``). Only the load/run
functions execute there; the
manifest and the host-side hooks (``models``/``owns``/``load_key`` …) run in the
main process. Four checkpoints are downloadable; the Settings selector picks the
**active** one, and the action menu offers that checkpoint's four modes.
"""

from __future__ import annotations

import os

# key -> (label, repo)
_CHECKPOINTS = {
    "florence2_base": ("Florence-2 (base-ft)", "microsoft/Florence-2-base-ft"),
    "florence2_large": ("Florence-2 (large-ft)", "microsoft/Florence-2-large-ft"),
    "florence2_base_plain": ("Florence-2 (base)", "microsoft/Florence-2-base"),
    "florence2_large_plain": ("Florence-2 (large)", "microsoft/Florence-2-large"),
}
_HF = "https://huggingface.co/"

# The active checkpoint (host-side state; synced from settings). Only this one is
# offered in the action menus; the others stay downloadable in Settings.
_ACTIVE = "florence2_base"

_TASK = {
    "caption": "<CAPTION>",
    "detailed": "<DETAILED_CAPTION>",
    "more_detailed": "<MORE_DETAILED_CAPTION>",
    "od": "<OD>",
}

# (mode, task, label, note)
_MODES = [
    ("caption", "caption", "Caption", "A one-line caption."),
    ("detailed", "caption", "Detailed caption", "A longer, more detailed caption."),
    ("more_detailed", "caption", "More detailed caption",
     "The most detailed caption Florence-2 offers."),
    ("od", "tag", "Object detection",
     "Detected objects as tags with bounding boxes, plus box-less "
     "scene-level tags derived from the caption."),
]

try:  # host-side metadata (loaded standalone in the worker -> guarded)
    from ..framework import (TRANSFORMERS_CONFIG_FILES, ModelSource, ModelSpec,
                            PluginManifest)

    MANIFEST = PluginManifest(
        models=[],  # dynamic — see models() below (only the active checkpoint)
        sources=[ModelSource(key=k, label=label, repo=repo, url=_HF + repo,
                             probe="model.safetensors",
                             # All four carry a `pytorch_model.bin` of the
                             # same weights (and one a sample notebook);
                             # `trust_remote_code` makes the .py files part
                             # of the model, which the shared tuple covers.
                             allow_patterns=TRANSFORMERS_CONFIG_FILES
                             + ("model.safetensors",))
                 for k, (label, repo) in _CHECKPOINTS.items()],
        deps=(),                # readiness = the dedicated env resolves
        env="florence",
        url=_HF + "microsoft/Florence-2-base-ft",
    )
except (ImportError, ValueError):
    MANIFEST = None


# ---- host-side hooks ------------------------------------------------------

def active() -> str:
    return _ACTIVE


def set_active(key: str) -> None:
    global _ACTIVE
    if key in _CHECKPOINTS:
        _ACTIVE = key


def models():
    """Only the active checkpoint's four modes."""
    label = _CHECKPOINTS[_ACTIVE][0]
    return [ModelSpec(id=f"{_ACTIVE}:{mode}", task=task,
                      name=f"{label} — {vlabel}", family=label,
                      variant=vlabel, note=note)
            for mode, task, vlabel, note in _MODES]


def owns(model_id: str) -> bool:
    return ":" in model_id and model_id.split(":", 1)[0] in _CHECKPOINTS


def source_for_model(model_id: str) -> str:
    return model_id.split(":", 1)[0]


def load_key(model_id: str) -> str:
    # Share one loaded checkpoint across its four modes.
    return model_id.split(":", 1)[0]


# ---- worker-side load / run (dedicated env) -------------------------------

def _patch_compat() -> None:  # pragma: no cover - heavy optional dep
    """Best-effort shims so the model loads on newer transformers too."""
    try:
        from transformers import PretrainedConfig
        for attr in ("forced_bos_token_id", "forced_eos_token_id"):
            if not hasattr(PretrainedConfig, attr):
                setattr(PretrainedConfig, attr, None)
    except Exception:
        pass
    try:
        from transformers.tokenization_utils_base import PreTrainedTokenizerBase
        if not hasattr(PreTrainedTokenizerBase, "additional_special_tokens"):
            def _ast(self):
                m = getattr(self, "_special_tokens_map", None) or {}
                v = m.get("additional_special_tokens")
                return list(v) if v else []
            PreTrainedTokenizerBase.additional_special_tokens = property(_ast)
    except Exception:
        pass


def _device():  # pragma: no cover - heavy optional dep
    """The accelerator this machine has, or the CPU. The model used to be
    pinned to the CPU in float32 ("avoids half-conv errors" — true of the
    CPU, and the whole reason a box with a 5090 in it captioned 1.1
    pictures a second). `MEDIA_COMPOST_CAPTION_DEVICE` pins one by hand."""
    import torch

    forced = (os.environ.get("MEDIA_COMPOST_CAPTION_DEVICE") or "").strip()
    if forced:
        return forced
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) is not None \
            and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _dtype(dev: str):  # pragma: no cover - heavy optional dep
    """float16 on CUDA — the checkpoint's own precision; float32 elsewhere
    (MPS's half-precision convolutions and the CPU's are where the errors
    were)."""
    import torch

    return torch.float16 if dev == "cuda" else torch.float32


def _load_processor(name: str, local_only: bool, token):  # pragma: no cover - heavy optional dep
    from transformers import AutoProcessor

    _patch_compat()
    return AutoProcessor.from_pretrained(
        name, trust_remote_code=True, local_files_only=local_only, token=token)


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    import torch
    from transformers import AutoModelForCausalLM

    _patch_compat()
    name = ctx["sources"][load_key]
    local_only = bool(ctx.get("local_files_only", True))
    token = ctx.get("token") or None
    dev = _device()
    dtype = _dtype(dev)
    # Eager attention matches Florence-2's reference impl and sidesteps SDPA
    # dispatch differences across transformers versions.
    try:
        mdl = AutoModelForCausalLM.from_pretrained(
            name, trust_remote_code=True, attn_implementation="eager",
            torch_dtype=dtype, local_files_only=local_only, token=token)
    except (TypeError, ValueError):
        mdl = AutoModelForCausalLM.from_pretrained(
            name, trust_remote_code=True, torch_dtype=dtype,
            local_files_only=local_only, token=token)
    mdl = mdl.to(dev).to(dtype).eval()
    proc = _load_processor(name, local_only, token)
    print(f"caption: Florence-2 on {dev} ({str(dtype).split('.')[-1]})", flush=True)
    return (mdl, proc, dev, dtype)


def load_prep(load_key, ctx):  # pragma: no cover - heavy optional dep
    """What `prepare` needs — the processor alone, never the model — built
    in every decode process."""
    import torch

    torch.set_num_threads(1)
    return _load_processor(ctx["sources"][load_key],
                           bool(ctx.get("local_files_only", True)),
                           ctx.get("token") or None)


def _input_size(proc):  # pragma: no cover - heavy optional dep
    try:
        sd = proc.image_processor.size
        return int(sd["width"]), int(sd["height"])
    except Exception:  # noqa: BLE001
        return 768, 768


def prepare(proc, image):  # pragma: no cover - heavy optional dep
    """The model's pixels for ONE picture — the 768 px resize and the
    processor's normalize — as a (3, H, W) float32 numpy array, the
    worker's per-picture hook beside the decode. The resize of a full-size
    picture and the processor's own pass were the plugin's first two steps
    on the worker's one thread; here they are the decode's."""
    import numpy as np

    tw, th = _input_size(proc)
    rgb = image.convert("RGB").resize((tw, th))
    return np.asarray(proc.image_processor(images=rgb, return_tensors="np")
                      ["pixel_values"][0], dtype=np.float32)


def wants_decode_processes(handle):  # pragma: no cover - heavy optional dep
    """Processes on CUDA, where a batched generate outruns the decode;
    threads elsewhere."""
    return handle is None or handle[2] == "cuda"


def _generate_batch(handle, pixels, task):  # pragma: no cover - heavy optional dep
    """One generate over a chunk: the same prompt for every picture, so the
    batch has no padding to worry about, and beam search over a batch is
    beam search over each of its rows."""
    import torch

    from PIL import Image

    mdl, proc, dev, dtype = handle
    n = int(pixels.shape[0])
    # The prompt's ids, once: Florence's processor turns the task token
    # into its prompt text and refuses a call without pictures, so a 2 px
    # stand-in is handed over for the text and the row repeated per picture
    # (one prompt, so no padding).
    prompt_ids = proc(text=task, images=Image.new("RGB", (2, 2)),
                      return_tensors="pt")["input_ids"]
    with torch.no_grad():
        ids = mdl.generate(input_ids=prompt_ids.repeat(n, 1).to(dev),
                           pixel_values=pixels.to(dev).to(dtype),
                           max_new_tokens=1024, num_beams=3)
    outs = proc.batch_decode(ids, skip_special_tokens=False)
    # A batch is padded to its longest answer, and `skip_special_tokens`
    # must stay off (the `<loc_…>` tokens the OD mode reads are special
    # tokens too), so the pad token is taken out by name — captioned one
    # picture at a time there was never any.
    pad = getattr(proc.tokenizer, "pad_token", None) or "<pad>"
    outs = [t.replace(pad, "") for t in outs]
    # Boxes come back scaled to `image_size`; asked for a 1000 x 1000 frame
    # they are per-mille of the picture, which `run_batch` reads as fractions
    # — the original size is not needed, and the decode did not send it.
    return [proc.post_process_generation(t, task=task, image_size=(1000, 1000))
            for t in outs]


# Filler words dropped when deriving box-less tags from a caption (Florence-2
# has no native tagging prompt, so scene-level tags come from its caption).
_CAPTION_STOPWORDS = frozenset(
    "a an the of on in at with and or for to from is are was were be being "
    "been this that these those there here it its his her their some "
    "several two three four five many next few over under near by "
    "image picture photo view background foreground front back side".split()
)


def _caption_tags(caption: str, skip: set) -> list:
    """Box-less tag candidates from a caption: lowercase words, minus filler
    and anything the detector already found. Florence-2 offers no tagging
    prompt, so this supplements the boxed OD labels with scene-level tags
    ("beach", "night", …). They land as *pending* tags either way, so the
    review flow filters any stragglers."""
    import re

    out, seen = [], set(skip)
    for word in re.findall(r"[a-zA-Z][a-zA-Z-]+", caption.lower()):
        if len(word) < 3 or word in _CAPTION_STOPWORDS:
            continue
        # Fold trivial plurals onto the singular ("dogs" -> "dog").
        base = word[:-1] if word.endswith("s") and not word.endswith("ss") else word
        if base in seen or base in _CAPTION_STOPWORDS:
            continue
        seen.add(base)
        out.append({"name": base, "box": None})
    return out[:10]


def run_batch(task, model_id, handle, images, options):  # pragma: no cover - heavy optional dep
    """The chunk's captions (or, for the `od` mode, tags with boxes plus
    the caption's box-less words), one generate per prompt for the whole
    chunk. Each entry is a picture, or the array `prepare` made of one."""
    import numpy as np
    import torch

    mdl, proc, dev, dtype = handle
    variant = model_id.split(":", 1)[1] if ":" in model_id else "caption"
    pixels = torch.from_numpy(np.stack([
        im if isinstance(im, np.ndarray) else prepare(proc, im) for im in images]))
    prompt = _TASK.get(variant, "<CAPTION>")
    parsed = _generate_batch(handle, pixels, prompt)
    if variant != "od":
        return [{"text": str(p.get(prompt, "")).strip()} for p in parsed]
    # A second, box-less pass: tags the detector can't produce (scene /
    # setting level) derived from the plain caption.
    try:
        captions = [str(p.get("<CAPTION>", "")).strip()
                    for p in _generate_batch(handle, pixels, "<CAPTION>")]
    except Exception:  # noqa: BLE001 - boxed tags alone are still useful
        captions = [""] * len(parsed)
    out = []
    for p, caption in zip(parsed, captions):
        od = p.get("<OD>", {})
        tags = []
        for label, box in zip(od.get("labels", []), od.get("bboxes", [])):
            x0, y0, x1, y1 = box
            tags.append({"name": str(label),
                         "box": [x0 / 1000, y0 / 1000, (x1 - x0) / 1000, (y1 - y0) / 1000]})
        detected = {"_".join(str(t["name"]).lower().split()) for t in tags}
        if caption:
            tags.extend(_caption_tags(caption, detected))
        out.append({"tags": tags})
    return out


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy optional dep
    return run_batch(task, model_id, handle, [image], options)[0]

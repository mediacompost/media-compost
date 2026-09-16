"""JoyTag Danbooru-style tagging (a ViT vision model, no language model)."""

from __future__ import annotations

import os

_THRESHOLD = 0.4

try:
    from ..framework import ModelSource, ModelSpec, PluginManifest

    MANIFEST = PluginManifest(
        models=[ModelSpec(id="joytag", task="tag", name="JoyTag", family="JoyTag",
                          note="Open Danbooru-style tagger (a ViT vision model).")],
        sources=[ModelSource(key="joytag", label="JoyTag", repo="fancyfeast/joytag",
                             url="https://huggingface.co/fancyfeast/joytag",
                             probe="model.safetensors",
                             allow_patterns=("config.json", "model.safetensors",
                                             "top_tags.txt"))],
        deps=("torch", "timm", "safetensors", "torchvision", "einops"),
        url="https://github.com/fpgaminer/joytag",
        source_for_model={"joytag": "joytag"},
    )
except (ImportError, ValueError):
    MANIFEST = None


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    import sys

    from ..framework import repo_files

    # The three files by name (`repo_files`): a narrowed download is not a
    # snapshot huggingface_hub will hand back offline.
    repo_dir = repo_files(ctx["sources"]["joytag"],
                          ("config.json", "model.safetensors", "top_tags.txt"),
                          ctx)
    # JoyTag ships its model *code* only in its GitHub repo; the HF weights repo
    # has just the weights + top_tags.txt. Prefer a Models.py placed alongside a
    # local clone, else our vendored copy so the published weights work as-is.
    code_file = next((f for f in ("Models.py", "models.py")
                      if os.path.exists(os.path.join(repo_dir, f))), None)
    if code_file is not None:
        if repo_dir not in sys.path:
            sys.path.insert(0, repo_dir)
        Models = __import__(code_file[:-3])
    else:
        from media_compost.ui.vendor import joytag_models as Models
    model = Models.VisionModel.load_model(repo_dir)
    model.eval()
    # encoding is explicit — see wd_tagger: the default is the locale encoding
    # on Windows, and a tag list is not ASCII.
    with open(os.path.join(repo_dir, "top_tags.txt"), encoding="utf-8") as f:
        top_tags = [ln.strip() for ln in f if ln.strip()]
    return (model, top_tags)


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy optional dep
    import torch
    import torchvision.transforms.functional as TVF
    from PIL import Image

    model, top_tags = handle
    size = model.image_size
    rgb = image.convert("RGB")
    dim = max(rgb.size)
    canvas = Image.new("RGB", (dim, dim), (255, 255, 255))
    canvas.paste(rgb, ((dim - rgb.width) // 2, (dim - rgb.height) // 2))
    if dim != size:
        canvas = canvas.resize((size, size), Image.BICUBIC)
    x = TVF.pil_to_tensor(canvas) / 255.0
    x = TVF.normalize(x, mean=[0.48145466, 0.4578275, 0.40821073],
                      std=[0.26862954, 0.26130258, 0.27577711])
    with torch.no_grad():
        preds = model({"image": x.unsqueeze(0)})
        scores = preds["tags"].sigmoid()[0]
    tags = [{"name": name.replace("_", " "), "box": None}
            for i, name in enumerate(top_tags) if float(scores[i]) >= _THRESHOLD]
    return {"tags": tags}

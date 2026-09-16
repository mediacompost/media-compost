"""The accelerator a main-env torch plugin runs on — one answer, so a plugin
cannot be pinned to the CPU by omission again.

A leading underscore, like `_ort.py` (its onnxruntime twin): not a plugin,
never in `registry.PLUGIN_MODULES`. Only main-env plugins may import it (a
dedicated env loads its plugin by file path, without the package —
`florence` and `anime_face_magi` carry their own copy of the rule).

The audit that made it (2026-09): four of the seven picture-to-picture
plugins never named a device at all and ran on the cores everywhere
(`withoutbg` hardcoded the CPU provider, `leres`/`openpose` never called
`.to`), two picked CUDA and nothing else (MPS idle on every Mac), and the
depth pipeline knew CUDA or the CPU. `MEDIA_COMPOST_DEVICE` pins one by hand
for all of them; a plugin's own variable wins where it has one.
"""

from __future__ import annotations

import os


def device(env_var: str = "") -> str:  # pragma: no cover - heavy optional dep
    """``"cuda"``, ``"mps"`` or ``"cpu"`` — the plugin's own override
    (``env_var``), then the general one, then what the machine has."""
    import torch

    for name in (env_var, "MEDIA_COMPOST_DEVICE"):
        forced = (os.environ.get(name) or "").strip() if name else ""
        if forced:
            return forced
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) is not None \
            and torch.backends.mps.is_available():
        return "mps"
    return "cpu"

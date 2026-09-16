"""Base models the user adds themselves — a local folder/checkpoint or an extra
Hugging Face repo.

The built-in registry (``models.py``) names the architectures the trainer has
engines for; this adds *more weights for those same architectures*. A user
model therefore always declares which built-in it is **based on**, and inherits
that entry's engine, native resolution, per-model hyperparameters and size
estimates — only the weights differ.

Stored as JSON FILES in the training directory, one for models and one for
LoRAs, library-wide so every job and both dropdowns see the same list. They
used to be two blobs in the ``settings`` table, which made this the single
exception to "training is file-based and DB-free" — and the one thing standing
between the training package and needing no database at all.

Nothing here touches the trainer: by the time a job runs, its model has
already been resolved to a repo/path in the manifest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import paths as tp
from .models import TrainModelSpec, model_spec

#: The two files, inside the training dir. Each holds ONE object with one
#: list in it, rather than a bare array: `paths.read_json` answers None for
#: anything that is not a dict — deliberately, since every other reader there
#: wants a record and a torn file must read as missing — and an object leaves
#: room to say something else about the list later without a second format.
MODELS_FILE = "models.json"
LORAS_FILE = "loras.json"
MODELS_KEY = "models"
LORAS_KEY = "loras"

# A user model's key is prefixed so it can never collide with a built-in and is
# recognisable on sight in a stored job config.
KEY_PREFIX = "user:"


@dataclass(frozen=True)
class UserModel:
    key: str            # "user:<slug>"
    label: str
    base: str           # a built-in registry key (sd15 / sdxl / chroma …)
    repo: str           # HF repo id, or an absolute local path
    local: bool         # repo is a filesystem path (folder or .safetensors)
    # Native training resolution. 0 = whatever the base declares.
    #
    # It is the ONE thing a user model does not simply inherit, and the reason
    # the "based on" choice is per-PROFILE rather than per-entry: releases that
    # inherit identically differ in nothing else a user model keeps (`resolve`
    # already overrides key, label, repo and note), so offering both was
    # offering the same thing twice to set a number the form can just ask for.
    # It generalizes too — a community SDXL finetune trained at 768 says so
    # here instead of inheriting 1024 and quietly training at the wrong size.
    area: int = 0

    def to_json(self) -> dict:
        return {"key": self.key, "label": self.label, "base": self.base,
                "repo": self.repo, "local": self.local, "area": self.area}


def slug(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")
    return s or "model"


def _load(store: Path, name: str, key: str) -> list:
    """The stored list, or an empty one for anything unreadable.

    `tp.read_json` already answers None for a missing or torn file; a blob of
    the wrong shape is treated the same way, because the alternative is a
    traceback at the top of every models request over a file somebody edited
    by hand.
    """
    raw = tp.read_json(Path(store) / name) or {}
    got = raw.get(key)
    return got if isinstance(got, list) else []


def read(store: Path) -> list[UserModel]:
    """Every user-added model, skipping any whose base no longer exists."""
    out: list[UserModel] = []
    for e in _load(store, MODELS_FILE, MODELS_KEY):
        if not isinstance(e, dict):
            continue
        base = str(e.get("base") or "")
        key, repo = str(e.get("key") or ""), str(e.get("repo") or "")
        if not key or not repo or model_spec(base) is None:
            continue
        try:
            area = int(e.get("area") or 0)
        except (TypeError, ValueError):
            area = 0
        out.append(UserModel(
            key=key, label=str(e.get("label") or key), base=base, repo=repo,
            local=bool(e.get("local")), area=max(0, area),
        ))
    return out


def write(store: Path, models: list[UserModel]) -> None:
    tp.write_json(Path(store) / MODELS_FILE,
                  {MODELS_KEY: [m.to_json() for m in models]})


def unique_key(existing: list[UserModel], label: str) -> str:
    """A key not already taken, derived from the label."""
    taken = {m.key for m in existing}
    base = KEY_PREFIX + slug(label)
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


def resolve(models: list[UserModel], key: str) -> Optional[TrainModelSpec]:
    """A user model as a full ``TrainModelSpec``: its base's engine, native
    size, LoRA-only flag and hyperparameters, pointed at its own weights.

    ``local`` travels with the repo and has to: it says the weights are a path
    on this machine, and dropping it left everything downstream judging a
    ``/models/my-sdxl.safetensors`` as if it were a hub id — the start guard
    refused the run for a download it would never make, and the manifest told
    the trainer to load a single-file checkpoint with ``from_pretrained``."""
    for m in models:
        if m.key != key:
            continue
        base = model_spec(m.base)
        if base is None:
            return None
        from dataclasses import replace

        return replace(base, key=m.key, label=m.label, repo=m.repo,
                       local=m.local, base_key=m.base,
                       default_area=m.area or base.default_area,
                       note=f"{base.label} — {'local' if m.local else m.repo}")
    return None


def refresh(store: Path) -> list[UserModel]:
    """Read the stored models and publish them so ``models.model_spec`` (and
    therefore config validation, the manifest builder and the evaluator) can
    resolve their keys. Call from any request that touches models."""
    models = read(store)
    from .models import set_user_specs

    specs = {}
    for m in models:
        spec = resolve(models, m.key)
        if spec is not None:
            specs[m.key] = spec
    set_user_specs(specs)
    return models


def entries_out(models: list[UserModel]) -> list[dict]:
    """User models in the same JSON shape ``models.registry_out()`` produces,
    so the frontend can treat both alike."""
    from ..hub import cache_sizes
    from .models import _repo_cached, registry_entry

    sizes = cache_sizes()
    out = []
    for m in models:
        spec = resolve(models, m.key)
        if spec is None:
            continue
        e = registry_entry(spec, sizes)
        # A local model is "downloaded" when its path exists; an added HF repo
        # is probed like any other.
        e["cached"] = _local_present(m.repo) if m.local else _repo_cached(m.repo)
        # …and a local one reports no size: its weights are wherever the user
        # put them, and walking somebody else's directory to add a number to a
        # row is not this page's business.
        if m.local:
            e["size"] = 0
        e["user"] = True
        e["base"] = m.base
        e["local"] = m.local
        out.append(e)
    return out


def _local_present(path: str) -> bool:
    import os

    return bool(path) and os.path.exists(path)


# ---- user LoRAs ------------------------------------------------------------
#
# LoRA files that live outside the app: ones downloaded from a hub, or trained
# elsewhere. Same storage as user models — a JSON file, entries keyed by a
# slug — but they name the base model they were trained FOR rather than one
# they are made of, since a LoRA only applies to its own architecture.


@dataclass(frozen=True)
class UserLora:
    key: str
    label: str
    model: str          # the base model key it was trained for
    path: str           # absolute path to a .safetensors file or a folder

    def to_json(self) -> dict:
        return {"key": self.key, "label": self.label, "model": self.model,
                "path": self.path}


def read_loras(store: Path) -> list[UserLora]:
    out = []
    for e in _load(store, LORAS_FILE, LORAS_KEY):
        if not isinstance(e, dict):
            continue
        key, path = str(e.get("key") or ""), str(e.get("path") or "")
        if key and path:
            out.append(UserLora(key=key, label=str(e.get("label") or key),
                                model=str(e.get("model") or ""), path=path))
    return out


def write_loras(store: Path, loras: list[UserLora]) -> None:
    tp.write_json(Path(store) / LORAS_FILE,
                  {LORAS_KEY: [lo.to_json() for lo in loras]})


def loras_out(loras: list[UserLora]) -> list[dict]:
    """With `exists`, because a path typed months ago may be gone."""
    import os

    return [{**lo.to_json(), "exists": os.path.exists(lo.path)}
            for lo in loras]

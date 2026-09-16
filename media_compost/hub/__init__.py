"""Talking to Hugging Face, and to dedicated virtualenvs.

**This is not the library API.** It is the plumbing two other things need —
the app's AI plugins and the trainer — and it lives in the core package for one
reason: they are the only two consumers, they must not drift apart, and neither
can depend on the other. The app cannot own it (the trainer would then need
fastapi and a 2 MB frontend to download a checkpoint), and duplicating it is
precisely the hand-maintained copy this project already has one of, with a test
whose whole job is catching its drift.

**It costs a base install nothing.** Every hub call in here is imported inside
a function, so `import media_compost` never reaches huggingface_hub and a
library-only install carries these modules inert. `[train]` and `[full]` are
what bring huggingface_hub in and make them work.

- `hf` — the token and offline mode, worked out once so the Settings warning,
  the download subprocess and a training run cannot disagree.
- `download` — a model download in its own process, because the sha256 pass
  over a multi-GB blob holds the GIL and would starve the server.
- `pipeline_files` — which files a diffusers pipeline would actually load,
  which is the same question as "is this downloaded" and "what should I fetch".
- `venv` — which interpreter runs a thing, and whether a package imports.
- `cache` — what is in the HF cache, by repo id.
- `setup` — run a package's setup commands, then re-exec.
- `setup_env` — build a dedicated env (run as ``-m media_compost.hub.
  setup_env``; its ``requirements-<env>-env.txt`` files live beside it, so a
  wheel install carries the whole procedure). Deliberately NOT imported here:
  it is only ever an entry point, and it stays pure stdlib so the tests can
  load it by file path.
"""

from __future__ import annotations

from . import cache, download, hf, pipeline_files, setup, venv
from .cache import (cache_sizes, delete_repo, dir_has_model,
                    forget_cache_sizes, repo_cached)
from .setup import SetupRun, restart_process
from .venv import has_module, interpreter_for, python_in

__all__ = [
    "cache", "download", "hf", "pipeline_files", "setup", "venv",
    "repo_cached", "delete_repo", "cache_sizes", "forget_cache_sizes",
    "dir_has_model",
    "interpreter_for", "python_in", "has_module",
    "SetupRun", "restart_process",
]

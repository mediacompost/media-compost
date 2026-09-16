"""The training routes, for a host that wants to serve them.

`import media_compost.train` must never reach this — it imports FastAPI, and a
`[train]`-only install has no web server in it at all. That is what makes
`media-compost-train` usable on a headless box: the CLI and the manager live
one level up, and this is the optional half a host mounts.

The host supplies the three things in `deps.py` through FastAPI's
`dependency_overrides`, so the Train tabs share the very same `Trainer` the
host's own library holds. Two `Trainer`s over one directory would be two
schedulers, which is an incident this project has had twice.
"""

from __future__ import annotations

from .deps import get_current_user, get_library, get_trainer
from .routes import router

__all__ = ["router", "get_trainer", "get_library", "get_current_user"]

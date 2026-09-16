"""Which interpreter runs a thing, and whether a package is importable.

Two consumers need this and neither is the library: the UI's plugins, which run
each model in a worker under some interpreter, and the trainer, which spawns
into a venv of its own. It lives here because a second copy of the Windows rule
below is exactly the kind of duplication that goes stale silently.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from typing import Optional

#: Where CPython puts the interpreter, POSIX first then Windows. **Both are
#: probed, and that is not a preference.** Checking only ``bin/python`` is
#: indistinguishable from "no env here", so on Windows every dedicated-env
#: plugin AND all of training read as un-set-up, with the environment override
#: the only way to say otherwise.
_LAYOUTS = (("bin", "python"), ("Scripts", "python.exe"))


def python_in(venv_dir: str) -> Optional[str]:
    """The interpreter inside a virtualenv directory, or None."""
    for rel in _LAYOUTS:
        cand = os.path.join(venv_dir, *rel)
        if os.path.exists(cand):
            return cand
    return None


def interpreter_for(env: str, root: str = "") -> Optional[str]:
    """The Python executable for a named environment.

    ``main`` is this process's own interpreter. Any other name resolves to the
    ``MEDIA_COMPOST_<ENV>_PYTHON`` override if it points at something, else to
    a ``.venv-<env>`` directory under ``root``. None means the environment is
    not set up, and the caller shows the model (or the trainer) as needing it.

    ``root`` is the CALLER's — there is no single "the backend directory" any
    more. The package that owns an environment is the package that knows where
    it lives, and passing it in is what lets the plugins and the trainer keep
    their venvs apart.
    """
    if env == "main":
        return sys.executable
    override = os.environ.get(f"MEDIA_COMPOST_{env.upper()}_PYTHON", "").strip()
    if override and os.path.exists(override):
        return override
    if not root:
        return None
    return python_in(os.path.join(root, f".venv-{env}"))


def has_module(name: str) -> bool:
    """Whether ``name`` could be imported, without importing it."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False

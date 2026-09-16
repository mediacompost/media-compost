"""What this machine knows about Hugging Face: the token, offline mode, and
the fact that this app does not phone home.

The first two answers have to be the same everywhere — the Settings warning,
the model download subprocess, and the training/evaluation runs that fetch
their base model on first use. They used to be worked out separately, which is
how a run inherited offline mode from the server and died with a forty-line
stack trace.

**Importing this module turns Hugging Face telemetry OFF for the process.** It
is on by default: `huggingface_hub.utils.send_telemetry` posts to
huggingface.co on a background thread, and diffusers and transformers call it
on ordinary paths like `from_pretrained`. Measured here, `HF_HUB_DISABLE_TELEMETRY`
was False in this venv, so every model load and every download was reporting
itself. This app is offline-first and says so on its front page; a library of
somebody's own pictures should not be announcing which models it opens.
An import side effect is unusual and is the right shape here: the setting has
to be in place BEFORE huggingface_hub reads it, which happens at ITS import,
and this module is what every hub-touching path in the app already goes
through for the token. `setdefault`, so somebody who deliberately sets it to 0
is left alone.
"""

from __future__ import annotations

import os

#: Set to "1" to stop `huggingface_hub` reporting usage. Not in `child_env`'s
#: `extra` but in the environment itself, so a child that inherits `os.environ`
#: without going through `child_env` — the plugin host's worker, anything
#: spawned by a library we call — is covered too.
TELEMETRY_ENV = "HF_HUB_DISABLE_TELEMETRY"

os.environ.setdefault(TELEMETRY_ENV, "1")

# Environment variables that carry a Hugging Face token.
TOKEN_ENV = ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN")

# Environment variables that force Hugging Face offline.
OFFLINE_ENV = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE")

# Values of the offline variables that mean "not offline". huggingface_hub
# treats anything else (1, true, yes, …) as on.
_OFF_VALUES = ("", "0", "false", "no", "off")


def token() -> str:
    """The Hugging Face token this machine can use, or "".

    Checks the environment first, then asks huggingface_hub — which also finds
    the token `huggingface-cli login` saved to disk. Missing that fallback made
    the app claim "no access token" while every actual download had one, and
    refuse gated models on that basis.
    """
    for name in TOKEN_ENV:
        v = os.environ.get(name)
        if v:
            return v
    try:
        from huggingface_hub import get_token

        return get_token() or ""
    except Exception:  # noqa: BLE001 - a probe must never break the caller
        return ""


def offline_var() -> str:
    """`"HF_HUB_OFFLINE=1"`-style description of what forces offline, or ""."""
    for name in OFFLINE_ENV:
        v = os.environ.get(name, "")
        if v.strip().lower() not in _OFF_VALUES:
            return f"{name}={v}"
    return ""


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The environment for a subprocess that may have to reach the hub.

    Passes the token along explicitly (the child cannot ask our settings
    endpoint, and a token set through the app's own field lives only in this
    process's environment), and leaves offline mode exactly as it is — callers
    that must not silently bypass it check `offline_var()` and refuse first.
    """
    env = dict(os.environ)
    env.setdefault(TELEMETRY_ENV, "1")
    tok = token()
    if tok:
        for name in TOKEN_ENV:
            env[name] = tok
    if extra:
        env.update(extra)
    return env

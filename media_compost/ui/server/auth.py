"""Caller identity for the multi-user setup.

Authentication itself is handled by an upstream layer (a reverse proxy doing
HTTP Basic auth); this app never verifies credentials. It only needs to learn
*who* the caller is so changes can be attributed and per-user settings scoped.

Two identity sources, in priority order:
  1. A trusted header the proxy sets (``UiConfig.user_header``, e.g. X-Remote-User)
     — used when configured and present.
  2. The username from an ``Authorization: Basic`` header (the password is
     ignored — it was already validated upstream).

When neither yields a name the caller is anonymous (empty username). If
``UiConfig.require_auth`` is on, anonymous requests are rejected with 401.
"""

from __future__ import annotations

import base64
import binascii

from fastapi import Request

from ..config import UiConfig


def _basic_username(header: str) -> str:
    """Username from an ``Authorization: Basic`` header value, or "" if absent/
    malformed. The password half is intentionally discarded."""
    scheme, _, param = header.partition(" ")
    if scheme.lower() != "basic" or not param.strip():
        return ""
    try:
        decoded = base64.b64decode(param.strip(), validate=True).decode(
            "utf-8", "replace"
        )
    except (binascii.Error, ValueError):
        return ""
    user, sep, _ = decoded.partition(":")
    # A well-formed Basic credential always contains a colon; without one we
    # can't tell username from password, so treat it as no identity.
    return user if sep else ""


def resolve_username(request: Request, cfg: UiConfig) -> str:
    """The caller's username per the configured sources, or "" for anonymous.
    Capped to the ``Event.username`` column width (64)."""
    name = ""
    if cfg.user_header:
        name = (request.headers.get(cfg.user_header) or "").strip()
    if not name:
        name = _basic_username(request.headers.get("authorization", ""))
    return name[:64]

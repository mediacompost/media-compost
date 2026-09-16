"""The app's configuration: core's `Config` plus what only a server needs.

The split is by OWNER, not by theme. Core keeps what a library IS — the data
directory, the dedup and edit-detection thresholds, the thumbnail size —
because a script reading a library needs those and nothing else. This subclass
adds what only exists once there is an HTTP server in front: who is calling
(``require_auth`` / ``user_header``, resolved by ``server/auth.py`` from an
upstream proxy), whether this deployment offers training at all, and the
rolling color-reference store the AI actions feed.

A ``UiConfig`` IS a ``Config``, so ``Database(cfg)`` and ``ItemStore(cfg)``
take it unchanged; the app constructs only this class, and core never learns
the fields exist.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from media_compost.config import Config


def _default_require_auth() -> bool:
    # Multi-user deployments put an authenticating reverse proxy in front. When
    # this is on, a request that carries no resolvable username is rejected
    # (401); off (the default) means anonymous access is allowed.
    return os.environ.get("MEDIA_COMPOST_REQUIRE_AUTH", "").strip().lower() in (
        "1", "true", "yes", "on"
    )


def _default_user_header() -> str:
    # Name of a trusted header the upstream auth layer sets to the authenticated
    # username (e.g. "X-Remote-User"). When set, it takes precedence over the
    # Basic-auth username. Empty means "derive the username from Basic auth".
    return os.environ.get("MEDIA_COMPOST_USER_HEADER", "").strip()


def _default_enable_training() -> bool:
    # The Train / Evaluate / Models tabs and the whole training API. Off turns
    # the app into a pure organiser — which is the point on a NAS or a laptop
    # that could never finish a run, where three tabs leading to a machine that
    # cannot do the work are three tabs of false promise.
    #
    # Opt-OUT, not opt-in: a machine that can train is the assumption, and a
    # deployment that cannot says so once at launch.
    return os.environ.get("MEDIA_COMPOST_TRAINING", "").strip().lower() not in (
        "0", "false", "no", "off"
    )


@dataclass(frozen=True)
class UiConfig(Config):
    # Multi-user access (authentication is handled by an upstream proxy; the app
    # only reads the caller's identity). See the two helpers above.
    require_auth: bool = field(default_factory=_default_require_auth)
    user_header: str = field(default_factory=_default_user_header)

    # Whether this deployment offers training at all (see the helper above).
    # The switch lives here rather than on the trainer because it gates the
    # APP's mount of the training routes — `media-compost-train` itself takes
    # no notice of it.
    enable_training: bool = field(default_factory=_default_enable_training)

    @property
    def refs_dir(self) -> Path:
        """Temporary color-reference images for reference-guided AI actions
        (uploaded or copied from items; a small rolling set, not library data).
        Created on demand — not part of ``ensure_dirs``."""
        return self.data_dir / "tmp" / "refs"

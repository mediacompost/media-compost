"""Shared FastAPI dependencies: the library (db + item store + config)."""

from __future__ import annotations

import threading
from typing import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import UiConfig
from media_compost.db import Database
from media_compost.ops import Ctx
from media_compost.storage import ItemStore
from .auth import resolve_username


def training_offered() -> bool:
    """Whether this install can train: the package is importable AND its
    declared requirements are met.

    Both halves, because they answer different questions and one wheel makes
    the first one always true. `MEDIA_COMPOST_TRAINING=0` still forces it off.
    """
    try:
        import media_compost.train
    except ImportError:
        return False
    return media_compost.train.available()


def _trainer_for(data_dir):
    """A `Trainer` over this library, or None when training is not installed."""
    try:
        import media_compost.train
    except ImportError:
        return None
    if not media_compost.train.available():
        return None
    return media_compost.train.Trainer(data_dir)


class Library:
    def __init__(self, cfg: UiConfig | None = None):
        self.config = cfg or UiConfig()
        self.db = Database(self.config)
        self.store = ItemStore(self.config)
        # Shared across import jobs so rotate/flip candidates stay decoded
        # between single-file uploads (the near-dup index itself is the
        # band-key columns now — nothing to prime or share). Guarded by
        # `import_lock` since jobs run on their own threads.
        from media_compost.dedup_index import ThumbLRU

        self.thumb_cache = ThumbLRU()
        self.import_lock = threading.Lock()
        # Guards the lazy singletons below. Unlocked check-then-set let
        # concurrent first requests (a browser poll plus anything else, right
        # after boot) each construct a TrainingManager: every one ran
        # recovery, adopted the live trainer and started a tick thread that
        # OUTLIVED losing the assignment race — three managers then finalized
        # one trainer exit as three "paused" events in the same millisecond.
        self._lazy_lock = threading.Lock()
        self._jobs = None
        self._model_host = None
        self._trainer = None
        self._face_cache = None

    @property
    def jobs(self):
        """The background AI-job queue (created lazily, one per library)."""
        if self._jobs is None:
            from ..jobs import JobQueue

            with self._lazy_lock:
                if self._jobs is None:
                    self._jobs = JobQueue(self)
        return self._jobs

    @property
    def model_host(self):
        """The out-of-process model runner (created lazily, one per library)."""
        if self._model_host is None:
            from ..plugins.host import ModelHost

            with self._lazy_lock:
                if self._model_host is None:
                    self._model_host = ModelHost()
        return self._model_host

    @property
    def face_cache(self):
        """The unnamed-faces clustering cache (see ``facevec.FaceCache``) —
        signature-guarded, so a stale answer is impossible and a repeat visit
        to the Subjects tab costs one aggregate query instead of a re-cluster."""
        if self._face_cache is None:
            from ..facevec import FaceCache

            with self._lazy_lock:
                if self._face_cache is None:
                    self._face_cache = FaceCache()
        return self._face_cache

    @property
    def trainer(self):
        """The training subsystem, when this install has the trainer's deps.

        One of the app's two guarded imports of `media_compost.train` (the
        other is `server/app.py`'s route mount), and a genuine
        optional import even though one wheel means it always resolves today:
        an install whose trainer requirements are unmet must still start and
        serve, and the guard is what a later split into separate
        distributions would need anyway.

        Built under the same lock as everything else here, because
        constructing it runs crash recovery and starts a tick thread — two of
        them racing on first use is the bug that made one trainer exit produce
        three "paused" events in the same millisecond.
        """
        if self._trainer is None:
            with self._lazy_lock:
                if self._trainer is None:
                    tr = _trainer_for(self.config.data_dir)
                    if tr is not None:
                        # A training run takes the card back from an idle
                        # model worker (`ModelHost.release_idle`).
                        tr.release_models = lambda: self.model_host.release_idle()
                    self._trainer = tr
        return self._trainer

    @property
    def training(self):
        """The training-job manager, or None without the extra."""
        tr = self.trainer
        return None if tr is None else tr.jobs

    @property
    def evaluation(self):
        """The evaluation-run manager (LoRA test generations)."""
        tr = self.trainer
        return None if tr is None else tr.evaluation


_library: Library | None = None
_library_lock = threading.Lock()


def get_library() -> Library:
    # Built once, lazily. A plain lru_cache is NOT enough: FastAPI resolves
    # this dependency in a threadpool, and on a cache miss lru_cache does not
    # serialize the wrapped call — so concurrent startup requests would each
    # build their own engine and race create_all() ("table already exists" /
    # "database is locked"). The lock guarantees a single builder.
    #
    # Build a FRESH UiConfig() here rather than reusing core's module-level
    # singleton: `media-compost serve --data-dir=X` sets MEDIA_COMPOST_DATA
    # at runtime, but a config frozen at import time already read the env (as
    # ./data). Reading it now — on the first request, after serve set it —
    # makes --data-dir actually take effect.
    global _library
    if _library is None:
        with _library_lock:
            if _library is None:
                _library = Library(UiConfig())
    return _library


def reset_library() -> None:
    """Drop the cached singleton (used by tests between fixtures)."""
    global _library
    with _library_lock:
        _library = None


def get_current_user(
    request: Request, lib: Library = Depends(get_library)
) -> str:
    """Resolve the caller's username (see ``auth.resolve_username``). Raises 401
    when ``require_auth`` is enabled and the caller is anonymous."""
    user = resolve_username(request, lib.config)
    if not user and lib.config.require_auth:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )
    return user


def get_session(
    request: Request,
    lib: Library = Depends(get_library),
    user: str = Depends(get_current_user),
) -> Iterator[Session]:
    """One Session per request, committed BEFORE the response goes out.

    The commit below is a BACKSTOP, not the commit that normally runs: a
    dependency with ``yield`` is exited only once the response has been SENT
    (the same fact ``files.release`` exists for), so committing here — which
    is what this did, and only this — meant every write endpoint answered
    ``200`` with the new row's id while its transaction was still open.

    A client that read straight back beat the commit. Measured on loopback
    against the real server: of twelve ``POST /api/groups`` calls each
    followed immediately by ``GET /api/groups``, FIVE did not list the group
    the POST had just returned an id for, and a create-then-delete pair
    answered ``404 group not found`` for its own new group about a third of
    the time — while a 50 ms sleep between the two made both vanish. That is
    exactly the shape of a UI that creates something and refetches, so the
    symptom is "it did not appear until I reloaded", intermittently.

    ``_commit_before_responding`` in ``app.py`` is what actually commits now.
    This stays because a session reached outside that middleware's path must
    still be committed by somebody, and a second commit on a session with
    nothing pending is free.
    """
    s = lib.db.session()
    # Stash the caller on the session so history writes (log_event) can attribute
    # the change without every mutating endpoint having to pass a username.
    s.info["username"] = user
    request.state.mc_session = s
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_ctx(
    s: Session = Depends(get_session),
    lib: Library = Depends(get_library),
    user: str = Depends(get_current_user),
) -> Ctx:
    """The service layer's context for one request.

    Layered over ``get_session`` rather than replacing it: FastAPI caches a
    dependency per request, so an endpoint asking for both a ``Session`` and a
    ``Ctx`` gets the SAME session — and the commit/rollback/close cycle stays
    where it already is, which is what keeps the ops layer's "never commit"
    rule true on the web side.

    ``source="web"`` is the History badge for a browser. The CLI and the
    scripting API build their own Ctx with ``source="cli"``, and the jobs
    worker with ``"ai"``.
    """
    return Ctx(session=s, source="web", username=user,
               _store=lib.store, _config=lib.config)

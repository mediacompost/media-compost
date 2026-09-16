"""Training LoRAs and finetunes from a Media Compost library.

Everything for a job lives in `<training dir>/<uid>/` — the record, the config,
the materialized dataset, the metrics, the samples and the checkpoints. **The
library database is never involved.** The dataset is read through the public
Python API (`media_compost.open_library`) and nothing else, which is what lets
this be its own package: it is a consumer of the library, not a part of it.

It is drivable two ways and neither needs the other. `media-compost-train` runs
a job from a terminal, so a headless box with a GPU can train without ever
installing the app; and the app mounts `web/` when the `[train]` extra is
present, which is what puts the Train tabs in the browser.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["Trainer", "available", "requirements", "training_dir"]

#: What `pip install media-compost[train]` is for. Checked by `available()`
#: rather than assumed, because the app has to decide whether to offer the Train
#: tabs at all and "the module imported" is not the same question — everything
#: here ships in one wheel, so the module always imports.
REQUIREMENTS = ("huggingface_hub",)


def requirements() -> list[str]:
    """The declared requirements that are MISSING, if any."""
    from media_compost.hub import has_module

    return [m for m in REQUIREMENTS if not has_module(m)]


def available() -> bool:
    """Whether this machine can actually train.

    Deliberately about the DEPENDENCIES and not about the training venv: the
    button that creates that venv lives in the training UI, so gating the UI on
    it would hide the only way to fix it.
    """
    return not requirements()


def training_dir(data_dir) -> Path:
    """Where a library's training state lives.

    `<data>/training` by default, and `MEDIA_COMPOST_TRAINING_DIR` when
    somebody wants the checkpoints on a different disk from the pictures —
    which, given a run writes tens of gigabytes of them, is a reasonable thing
    to want. It used to be a property on the library's own `Config`; it is here
    because it is the trainer's directory and nothing else reads it.
    """
    override = os.environ.get("MEDIA_COMPOST_TRAINING_DIR", "").strip()
    return Path(override) if override else Path(data_dir) / "training"


class Trainer:
    """The training subsystem over one library.

    Holds the two managers and hands each of them a way to reach the other.
    They genuinely need it — a training run must not start while an Evaluate
    generation holds the GPU, and a finished run should let a queued generation
    go — and they used to reach each other through the SERVER's `Library`,
    which is why training could not be lifted out of the app. This object is
    that one shared thing, with none of the rest of a web server attached.

    Built lazily and under a lock, because constructing a `TrainingManager`
    runs crash recovery and starts a tick thread: two of them racing on first
    use is not a hypothetical, it is the bug that made one trainer exit produce
    three "paused" events in the same millisecond.
    """

    __slots__ = ("data_dir", "dir", "_jobs", "_evaluation", "_lock",
                 "release_models")

    def __init__(self, data_dir):
        import threading

        self.data_dir = Path(data_dir)
        self.dir = training_dir(self.data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._jobs = None
        self._evaluation = None
        self._lock = threading.Lock()
        #: Called before a training run starts, to give the card back: the
        #: host that mounts this trainer sets it to whatever else it keeps
        #: warm (the app's model worker, `ModelHost.release_idle`). A
        #: callable, never an import: the trainer knows nothing of the app.
        self.release_models = None

    def _lease(self) -> None:
        """Only one process runs this library's training scheduler.

        Taken the moment either manager is about to exist — they own tick
        threads that adopt and start queued jobs, and two of them on one
        library is the incident that created `instance.py`. Idempotent per
        process, so the app (which leases at startup) builds its Trainer
        unhindered; a second process gets `LockBusy` naming the first.
        """
        from media_compost import TRAINING_LOCK_NAME, scheduler_lease

        scheduler_lease(self.data_dir, TRAINING_LOCK_NAME)

    @property
    def jobs(self):
        """The job queue and its scheduler."""
        if self._jobs is None:
            with self._lock:
                if self._jobs is None:
                    from .manager import TrainingManager

                    self._lease()
                    self._jobs = TrainingManager(self)
        return self._jobs

    @property
    def evaluation(self):
        """One-off test generations from a trained LoRA."""
        if self._evaluation is None:
            with self._lock:
                if self._evaluation is None:
                    from .evaluate import EvalManager

                    self._lease()
                    self._evaluation = EvalManager(self)
        return self._evaluation

    def library(self):
        """A public-API handle on the library this trains from.

        Its own connection, and through `open_library` rather than anything the
        server owns — that is the whole precondition for living out here.
        """
        from media_compost import open_library

        return open_library(self.data_dir, source="cli")

    def close(self) -> None:
        """Stop the schedulers. The CLI needs this; a server exits instead."""
        for got in (self._jobs, self._evaluation):
            stop = getattr(got, "stop", None)
            if callable(stop):
                try:
                    stop()
                except Exception:  # noqa: BLE001 - shutdown is best effort
                    pass

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<Trainer {self.dir}>"

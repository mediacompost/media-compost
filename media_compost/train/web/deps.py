"""What the training routes need from whoever is hosting them.

Three questions, declared here and answerable without a host: which trainer,
which library, and who is asking. Each has a standalone default, so this
package serves its own routes on a machine where the app is not installed.

**A host injects through `use()`, not through `dependency_overrides`.** That
was the first shape and it is quietly wrong: FastAPI's override map is global
and mutable, and the app's own test suite clears it in teardown — so overrides
installed once at import survive until the first test that tidies up after
itself, and then the training routes silently fall back to a `Trainer` of their
own over the same directory. Two schedulers on one queue is the incident this
project has had twice, and it is not one to leave to the ordering of a test
run.

Declared rather than imported is the other half of the point. A router that
reached into the app's `deps` for `get_library` would make the trainer depend
on the app, and the trainer is meant to be usable from a terminal on a box
where the app is not there at all.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

from fastapi import Request

from .. import Trainer

_lock = threading.Lock()
_standalone: Optional[Trainer] = None

#: Set by a host through `use()`. None means nobody is hosting us.
_trainer_of: Optional[Callable[[], Trainer]] = None
_user_of: Optional[Callable[[Request], str]] = None


def use(*, trainer: Callable[[], Trainer],
        user: Optional[Callable[[Request], str]] = None) -> None:
    """Tell these routes how the host answers their three questions.

    `trainer` must hand back the host's OWN `Trainer` — the point is that both
    halves share one, so the tabs in the browser and anything else driving the
    queue are the same scheduler.
    """
    global _trainer_of, _user_of
    _trainer_of = trainer
    _user_of = user


def get_trainer() -> Trainer:
    """The training subsystem.

    Hosted, this is the host's. Standalone, it is one built over the library
    `Config` points at and kept — a `Trainer` owns tick threads, so one per
    process and not one per request.
    """
    if _trainer_of is not None:
        return _trainer_of()
    global _standalone
    if _standalone is None:
        with _lock:
            if _standalone is None:
                from media_compost import default_data_dir

                _standalone = Trainer(default_data_dir())
    return _standalone


def get_library():
    """A public-API handle on the library, for the length of one request.

    A context manager, so FastAPI closes it: the trainer opens its own
    connection rather than borrowing the app's session, which is what keeps
    `media_compost.ops` and `media_compost.db` out of this package entirely.
    """
    with get_trainer().library() as lib:
        yield lib


def get_current_user(request: Request) -> str:
    """Who is acting, for the History badge.

    Anonymous unless a host resolves it — the trainer authenticates nobody and
    never has. It takes the `Request` so a host CAN: the app reads a trusted
    header or Basic auth off it.
    """
    return _user_of(request) if _user_of is not None else ""

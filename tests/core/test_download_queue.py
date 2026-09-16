"""The download queue: how many run at once, and what waiting looks like.

Driven with stand-ins rather than real downloads — the thing under test is the
scheduler's bookkeeping, and a test that fetched from Hugging Face to check it
would be testing the network.
"""

from __future__ import annotations

import pytest

from media_compost.hub import download as dl


class _FakeProc:
    def __init__(self) -> None:
        self.started = False
        self.alive = False

    def start(self) -> None:
        self.started = True
        self.alive = True

    def is_alive(self) -> bool:
        return self.alive

    def terminate(self) -> None:
        self.alive = False

    def join(self, timeout=None) -> None:
        pass


class _Fake:
    """A `Download` as far as the scheduler is concerned."""

    def __init__(self) -> None:
        self._proc = _FakeProc()
        self._launched = False

    # the two the queue reads back
    queued = property(lambda self: not self._launched)

    def finish(self) -> None:
        self._proc.alive = False


@pytest.fixture(autouse=True)
def _clean_queue():
    dl._running.clear()
    dl._waiting.clear()
    yield
    dl._running.clear()
    dl._waiting.clear()


def test_downloads_past_the_cap_wait_their_turn():
    ds = [_Fake() for _ in range(4)]
    for d in ds:
        dl._schedule(d)
    started = [d._proc.started for d in ds]
    assert started == [True] * dl.MAX_PARALLEL + [False] * (4 - dl.MAX_PARALLEL)
    assert [d.queued for d in ds][dl.MAX_PARALLEL:] == \
        [True] * (4 - dl.MAX_PARALLEL)


def test_a_finished_download_frees_its_slot():
    ds = [_Fake() for _ in range(4)]
    for d in ds:
        dl._schedule(d)
    ds[0].finish()
    # The pump does this on a timer; call the body it runs so the test does
    # not sleep. Scheduling a fifth exercises the same prune.
    with dl._lock:
        dl._running[:] = [r for r in dl._running if r._proc.is_alive()]
        while dl._waiting and len(dl._running) < dl.MAX_PARALLEL:
            dl._launch(dl._waiting.pop(0))
    assert ds[dl.MAX_PARALLEL]._proc.started


def test_cancelling_a_waiting_download_gives_up_its_place():
    """A queued download has no process to terminate, and must not keep the
    slot it was promised — that slot would go to something already gone."""
    ds = [_Fake() for _ in range(4)]
    for d in ds:
        dl._schedule(d)
    waiting = ds[dl.MAX_PARALLEL]
    dl._unqueue(waiting)
    assert waiting not in dl._waiting
    assert len(dl._waiting) == 4 - dl.MAX_PARALLEL - 1


def test_a_queued_download_is_not_mistaken_for_a_dead_one():
    """`status()` reads a non-alive process as a crash. A download that has
    not been LAUNCHED has no process yet, and reporting that as ERROR is how a
    queue would look like a pile of failures."""
    d = dl.Download.__new__(dl.Download)
    d._launched = False
    d._proc = _FakeProc()
    d._status = type("V", (), {"value": dl.RUNNING})()
    d._err = type("A", (), {"value": b""})()
    assert d.status() == dl.RUNNING
    assert d.queued


def test_a_download_child_watches_its_parent():
    """`daemon=True` is not enough — it terminates children from an atexit
    hook, which a SIGKILL, an `os.execv` and a crash all skip. The child has
    to watch the parent instead; this holds the watchdog to being armed before
    anything else in `_run`, since after the fetch starts it is too late."""
    import inspect

    src = inspect.getsource(dl._run)
    assert "_die_with_parent()" in src
    # Before the fetch, not after it: a watchdog armed once bytes are moving
    # is one that was not armed for the window that matters.
    assert src.index("_die_with_parent()") < src.index("snapshot_download")

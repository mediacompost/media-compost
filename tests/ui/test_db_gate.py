"""The library-read gate: one walk at a time, and nothing run for a caller
that has gone.

What this is about is in `server/dbgate.py`'s docstring. The numbers behind
it, measured on a 1M-item library: the ten requests one edit in the
properties panel sets off cost 3.5 s one after another and 16.3 s at once,
and eight page queries the browser had already aborted left the server
unusable for 652 seconds when it ran them anyway — 0.65 s when it dropped
them.

These drive `guarded` directly. The TestClient runs every request to
completion and cannot abort one, so it cannot tell the two behaviours apart,
which is the same reason `test_commit_ordering` calls the middleware itself.

THE SEMAPHORE IS MODULE STATE AND BINDS ITSELF TO THE LOOP THAT FIRST WAITS
ON IT, so every case here makes its own inside its own `asyncio.run` — the
server has exactly one loop and never meets this.
"""

from __future__ import annotations

import asyncio

import pytest

from media_compost.ui.server import dbgate


class _Caller:
    """A request whose caller hangs up after ``gone_after`` polls."""

    def __init__(self, gone_after: int | None = None) -> None:
        self.gone_after = gone_after
        self.asked = 0

    async def is_disconnected(self) -> bool:
        self.asked += 1
        return self.gone_after is not None and self.asked > self.gone_after


def _run(coro_fn):
    """Run one case with a fresh gate bound to that case's loop."""
    async def main():
        dbgate.SLOTS = asyncio.Semaphore(2)
        try:
            return await coro_fn()
        finally:
            free = dbgate.SLOTS._value
            dbgate.SLOTS = asyncio.Semaphore(2)
            assert free == 2, f"a slot was lost on the way out ({free} free)"

    return asyncio.run(main())


def test_the_work_runs_and_its_answer_comes_back():
    ran = []

    def work(x):
        ran.append(x)
        return {"got": x}

    out = _run(lambda: dbgate.guarded(_Caller(), work, 7))
    assert out == {"got": 7} and ran == [7]


def test_a_caller_that_has_already_gone_costs_nothing():
    ran = []
    out = _run(lambda: dbgate.guarded(_Caller(gone_after=0), ran.append, 1))
    assert out.status_code == dbgate.GONE
    assert ran == [], "ran a walk for a caller that had hung up"


def test_a_caller_that_leaves_while_queueing_gives_its_slot_back():
    """The abort usually lands while the request is waiting, which is the
    whole point: it leaves the queue instead of being handed a slot."""
    ran = []

    async def scenario():
        # Hold both slots so the third request has to wait.
        await dbgate.SLOTS.acquire()
        await dbgate.SLOTS.acquire()
        try:
            return await dbgate.guarded(_Caller(gone_after=1), ran.append, 1)
        finally:
            dbgate.SLOTS.release()
            dbgate.SLOTS.release()

    out = _run(scenario)
    assert out.status_code == dbgate.GONE
    assert ran == []


def test_a_live_caller_past_the_wait_is_refused_rather_than_queued_forever():
    """The backstop — reaching it means the gate has not moved AT ALL for
    `QUEUE_WAIT`, which is stuck rather than busy. Both slots are held here
    and nobody gives one back, which is exactly that."""
    ran = []

    async def scenario():
        await dbgate.SLOTS.acquire()
        await dbgate.SLOTS.acquire()
        try:
            return await dbgate.guarded(_Caller(), ran.append, 1)
        finally:
            dbgate.SLOTS.release()
            dbgate.SLOTS.release()

    old = dbgate.QUEUE_WAIT
    dbgate.QUEUE_WAIT = 0.25
    try:
        out = _run(scenario)
    finally:
        dbgate.QUEUE_WAIT = old
    assert out.status_code == 503
    assert out.headers.get("Retry-After") == "1"
    assert ran == []


def test_a_queue_that_is_moving_refuses_nobody_however_deep_it_is():
    """The LAUNCH shape: more walks than slots, every one of them finishing,
    and the tail of the fan-out waiting far longer than `QUEUE_WAIT`.

    Refusing those is what made a big library's first seconds a row of 503s
    — the module docstring has the measurement (96 of 150 refused while the
    gate handed a slot over every 0.27 s, each refusal three more of the same
    walk because the frontend retries a 5xx). The deadline belongs to the
    GATE: it is reset by every handover, so depth alone never refuses.
    """
    import time

    def work(n):
        time.sleep(0.05)
        return n

    async def scenario():
        return await asyncio.gather(*(
            dbgate.guarded(_Caller(), work, n) for n in range(24)))

    old_wait = dbgate.QUEUE_WAIT
    # Far below what the tail of this queue waits (~0.55 s) and well above
    # the gap between two handovers (~0.025 s), which is the whole
    # distinction: slow is not stuck.
    dbgate.QUEUE_WAIT = 0.3
    try:
        out = _run(scenario)
    finally:
        dbgate.QUEUE_WAIT = old_wait
    assert out == list(range(24)), \
        [x for x in out if not isinstance(x, int)]


def test_the_slot_comes_back_however_the_work_ends():
    def boom(_):
        raise ValueError("no")

    with pytest.raises(ValueError):
        _run(lambda: dbgate.guarded(_Caller(), boom, 1))


def test_every_read_that_walks_the_library_goes_through_the_gate():
    """A read added here without the gate is one that races the others, and
    nothing about its own answer says so — the cost lands on every OTHER
    request. Counted off the source, since the five endpoints differ in
    shape: the page query, the facet counts, the scope listing, the section
    runs and the id range."""
    import inspect

    from media_compost.ui.server.routers import items as items_router

    src = inspect.getsource(items_router)
    assert src.count("return await dbgate.guarded(") == 5, \
        "an items read stopped going through the gate, or a new one skipped it"

"""HOW MANY LIBRARY-WIDE READS RUN AT ONCE, and why that is a number at all.

A read that walks the library — a page deep in a million-item view, the
sidebar's Untagged and Ungrouped counts, the grid's section runs — is
hundreds of milliseconds of SQLite. **Those do not overlap.** Measured on the
1M-item library, the ten requests ONE edit in the properties panel sets off
(four grid pages, three facet counts, the group tree, the stats, the
sequences) cost **3.5 s run one after another and 16.3 s run at once** — and
two of the pages were refused on the way, because everything else had made
them miss their deadline. Concurrency here buys nothing and costs 4.7x: one
connection's walk evicts the next one's pages, and fifteen pool connections
scanning a gigabyte at the same time is a machine thrashing, not working.

So they queue HERE, in the event loop where waiting is free, a few at a time.

TWO SLOTS, measured twice over. For deep page walks alone: two in parallel
cost what two in series do (0.98 s against 1.10), three cost MORE (1.74
against 1.65) and six twice as much (6.7 s against 3.3). For the mixed
fan-out one edit fires, five runs each: ONE slot 5.4/6.5/6.6/6.6/4.7 s, TWO
2.2/2.3/2.3/11.7/2.3, THREE 15.3/14.7/9.4. Two is the best of them and one is
the steadier — three is already a loss, and ungated is 34 s.

A REQUEST WHOSE CALLER HAS GONE LEAVES THE QUEUE AT ONCE, and that is what
makes the queue short enough to be worth having. A grid refetch aborts and
re-fires its own pages as the invalidations land, and a scrollbar drag fires
one per position the thumb passes; every one of those is a client that has
stopped waiting. The server used to run them all to completion — it could not
see the abort — and measured on the 1M library, EIGHT aborted page queries
left the server unusable for **652 seconds**, since each refused live request
retried into the same backlog. With the abort honoured the same eight cost
**0.65 s**. What made it possible is that neither middleware in `app.py` is a
`BaseHTTPMiddleware` any more: one of those anywhere in the stack proxies the
receive channel, and no endpoint below it ever sees `http.disconnect`.

THE REFUSAL IS A BACKSTOP NOW, NOT A DRAIN. It used to fire after two seconds,
on the reasoning that a queue that deep was a burst whose senders had moved on
— which was true and is now handled precisely, by letting them leave. What is
left in the queue is callers still waiting for an answer, and answering one of
those 503 costs MORE than making it wait: the frontend retries, and the retry
is the same walk again.

AND THAT IS WHY THE DEADLINE MEASURES A GATE THAT HAS STOPPED, NEVER ONE THAT
IS MERELY SLOW. It used to be a plain per-request stopwatch — wait fifteen
seconds, be refused — which reads as a burst-shedding rule however it is
worded, and on a big library at LAUNCH it is one: the first view costs a walk
per sidebar badge beside the page's own, nothing is memoized yet, the file is
not in the page cache, and the tail of that fan-out is refused for having
waited while the queue drained perfectly well in front of it. Measured on the
1.2M-item library: 150 walks arriving at once, the gate steadily handing over
a slot every ~0.27 s, **96 of them refused** — and each refusal is three more
of the same walk, since the frontend retries a 5xx. So the clock is the GATE's
and it is reset by every handover: a queue that is moving refuses nobody,
however deep it is, and reaching `QUEUE_WAIT` means no read has started or
finished in all that time. That is a wedge, not a burst.

What it cannot tell apart is a wedge and ONE walk that genuinely runs longer
than `QUEUE_WAIT` while every slot is held — which is why the number is minutes
rather than seconds now. Nothing here should take that long, and a read that
does is a bug the 503 is allowed to report.
"""

from __future__ import annotations

import asyncio

from fastapi import Request, Response
from starlette.concurrency import run_in_threadpool

#: How many library-wide reads run at once.
SLOTS = asyncio.Semaphore(2)

#: Seconds the GATE may go without handing a slot over before the reads
#: waiting on it are refused — a backstop, see the module docstring. NOT how
#: long one request may wait: a queue that is moving refuses nobody, however
#: deep it is, and requests whose caller has gone do not wait at all.
QUEUE_WAIT = 120.0

#: How often, while queueing, a waiting request asks whether its caller is
#: still there. A poll, because that is the only shape `is_disconnected`
#: offers; far below the walks it is queueing behind, so it costs nothing.
DISCONNECT_POLL = 0.1

#: The answer to a request whose caller has already gone. Nobody reads it —
#: the socket is closed — so the status is only for a log: 499 is nginx's
#: "client closed request", which is exactly what happened.
GONE = 499

_BUSY = "The server is busy reading the library; try again in a moment."

#: When the gate last moved — the loop clock at the most recent handover, in
#: or out. The waiters read it rather than their own stopwatch, so the
#: deadline is the GATE's: it says how long everything has been stuck, not how
#: long one of them has been patient.
_MOVED_AT = 0.0


def _moved() -> None:
    """A slot changed hands. Called on both sides of every handover — taken
    and given back — since either says the gate is alive."""
    global _MOVED_AT
    _MOVED_AT = asyncio.get_running_loop().time()


def _release() -> None:
    """Give a slot back, and say so."""
    SLOTS.release()
    _moved()


async def _slot_for(request: Request) -> bool:
    """Wait for a slot. True when it is ours, False when the caller hung up
    first; ``asyncio.TimeoutError`` once the GATE has not moved for
    `QUEUE_WAIT` — see the module docstring for why that is the clock."""
    loop = asyncio.get_running_loop()
    seen = _MOVED_AT
    deadline = loop.time() + QUEUE_WAIT
    acquire = asyncio.ensure_future(SLOTS.acquire())
    got = False
    try:
        while True:
            done, _ = await asyncio.wait({acquire}, timeout=DISCONNECT_POLL)
            if done:
                got = True
                _moved()
                return True
            if await request.is_disconnected():
                return False
            if seen != _MOVED_AT:
                # Somebody got in or got out while we waited: the queue is
                # draining, so start the patience over.
                seen = _MOVED_AT
                deadline = loop.time() + QUEUE_WAIT
            if loop.time() >= deadline:
                raise asyncio.TimeoutError
    finally:
        # Leaving without the slot: give back one that arrived in the same
        # breath (`cancel()` cannot undo a finished acquire), and otherwise
        # cancel the wait — `Semaphore.acquire` restores its own count and
        # wakes the next waiter when it is cancelled.
        if not got:
            if acquire.done():
                if not acquire.cancelled() and acquire.exception() is None:
                    _release()
            else:
                acquire.cancel()


async def guarded(request: Request, fn, *args):
    """Run ``fn(*args)`` on the threadpool, a library walk at a time.

    Returns whatever ``fn`` returns, or a `Response` — 499 when the caller
    went away while queueing, 503 once the gate has not moved at all for
    `QUEUE_WAIT`. A handler declared with a ``response_model`` may return
    either; FastAPI passes a Response through untouched.
    """
    if await request.is_disconnected():
        return Response(status_code=GONE)
    try:
        if not await _slot_for(request):
            return Response(status_code=GONE)
    except asyncio.TimeoutError:
        return Response(status_code=503, headers={"Retry-After": "1"},
                        content=_BUSY)
    try:
        # One last look before spending half a second of SQLite on it: the
        # abort usually lands while the request was queueing.
        if await request.is_disconnected():
            return Response(status_code=GONE)
        return await run_in_threadpool(fn, *args)
    finally:
        _release()

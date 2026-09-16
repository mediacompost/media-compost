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
is the same walk again. So the wait is long, and reaching it means something
is stuck rather than busy.
"""

from __future__ import annotations

import asyncio

from fastapi import Request, Response
from starlette.concurrency import run_in_threadpool

#: How many library-wide reads run at once.
SLOTS = asyncio.Semaphore(2)

#: Seconds a read may wait for a slot before it is refused — a backstop, see
#: the module docstring. Requests whose caller has gone do not wait at all.
QUEUE_WAIT = 15.0

#: How often, while queueing, a waiting request asks whether its caller is
#: still there. A poll, because that is the only shape `is_disconnected`
#: offers; far below the walks it is queueing behind, so it costs nothing.
DISCONNECT_POLL = 0.1

#: The answer to a request whose caller has already gone. Nobody reads it —
#: the socket is closed — so the status is only for a log: 499 is nginx's
#: "client closed request", which is exactly what happened.
GONE = 499

_BUSY = "The server is busy reading the library; try again in a moment."


async def _slot_for(request: Request) -> bool:
    """Wait for a slot. True when it is ours, False when the caller hung up
    first; ``asyncio.TimeoutError`` past `QUEUE_WAIT`."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + QUEUE_WAIT
    acquire = asyncio.ensure_future(SLOTS.acquire())
    got = False
    try:
        while True:
            done, _ = await asyncio.wait({acquire}, timeout=DISCONNECT_POLL)
            if done:
                got = True
                return True
            if await request.is_disconnected():
                return False
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
                    SLOTS.release()
            else:
                acquire.cancel()


async def guarded(request: Request, fn, *args):
    """Run ``fn(*args)`` on the threadpool, a library walk at a time.

    Returns whatever ``fn`` returns, or a `Response` — 499 when the caller
    went away while queueing, 503 past `QUEUE_WAIT`. A handler declared with
    a ``response_model`` may return either; FastAPI passes a Response through
    untouched.
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
        SLOTS.release()

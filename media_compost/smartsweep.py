"""The smart-group membership refresher — infrastructure, not an op.

`SmartGroupSweeper` owns its sessions and commits
(which is also why it lives here rather than in `ops/`, whose modules never
commit): the `Database` pokes it after every commit that touched anything,
and it refits smart-group membership shortly after the burst ends — or
inline, in the synchronous mode the test suite's determinism knob selects.
The rules and the rebuild itself are `ops/smartgroups`'s.
"""

from __future__ import annotations

import threading
import weakref
import time
from typing import Optional


class SmartGroupSweeper:
    """The debounced refresher — `Database` pokes it after every commit that
    touched anything, and it refits membership shortly after the burst ends.

    Synchronous mode (the sidecar writer's knob) runs the sweep inline in
    the poke instead, which is what makes tests deterministic; there the
    early-out — no smart groups, no work — is one indexed SELECT per commit.
    """

    #: How long after the last poke the sweep waits — long enough that a
    #: burst (an import committing every few seconds, a paint of quick
    #: assigns) coalesces, short enough that the tree feels live.
    DEBOUNCE = 0.75

    #: …AND NEVER MORE THAN A QUARTER OF THE TIME, however long a sweep
    #: turns out to take. A debounce is a claim about how long to wait for
    #: the burst to end; on its own it says nothing about the sweep's own
    #: cost, and the two only compose while that cost is small. On a 1.1M-item
    #: library one sweep measured 5.8 s, so a 0.75 s debounce meant this
    #: thread was reading the whole library, releasing, and starting again —
    #: continuously, for as long as anything kept writing. An import saw it
    #: as a second process fighting it for the database: measured 9 ms/file
    #: with no smart group against 13–35 ms/file with one, and the WAL pinned
    #: at 75 MB because a read snapshot was almost always open, so SQLite
    #: could never checkpoint it.
    #:
    #: So the wait after a sweep is the greater of the debounce and three
    #: times what that sweep cost, which bounds this thread at a quarter of
    #: the time whatever the library's size. A small library is unaffected —
    #: a sweep there is milliseconds and the debounce still decides — and a
    #: big one converges just as surely, a few seconds later.
    DUTY = 4

    def __init__(self, db, *, sync: bool) -> None:
        #: WEAK, because this thread is a GC ROOT and a strong reference here
        #: would make every library it ever swept immortal — the database, its
        #: engine and its pool. Nothing else holds the pair together: the
        #: Database owns the sweeper (`_smart_sweeper`), so the only cycle is
        #: the one this weakref breaks. The callback wakes the loop when the
        #: library goes, so the thread ends instead of blocking on an event
        #: nobody will ever set again.
        self._db = weakref.ref(db, lambda _ref: self._event.set())
        self._sync = sync
        self._event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        if not sync:
            self._thread = threading.Thread(
                target=self._loop, name="smart-groups", daemon=True)
            self._thread.start()

    def notify(self) -> None:
        if self._sync:
            self.run_once()
        else:
            self._event.set()

    def flush(self) -> None:
        """Run a sweep NOW — the test/shutdown barrier."""
        self._event.clear()
        self.run_once()

    @classmethod
    def wait_after(cls, cost: float) -> float:
        """How long to hold off, given what the last sweep cost.

        The debounce waits for the burst to end; the second term keeps this
        thread off the database for most of the time even when a sweep is
        expensive. Pure, so the rule is stated as a test rather than as a
        sleep nobody can observe.
        """
        return max(cls.DEBOUNCE, cost * (cls.DUTY - 1))

    def _loop(self) -> None:
        cost = 0.0
        while self._db() is not None:
            self._event.wait()
            # The event stays SET through the wait, so a poke arriving during
            # it is not lost — it is exactly what the next round is for.
            time.sleep(self.wait_after(cost))
            self._event.clear()
            began = time.monotonic()
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 — derived data; the next sweep retries
                pass
            cost = time.monotonic() - began

    def run_once(self) -> None:
        from sqlalchemy import select

        from .db import Group
        from .ops import smartgroups
        from .ops.context import Ctx

        db = self._db()
        if db is None:  # the library was dropped; nothing to keep in step
            return
        with db.session() as s:
            if not s.execute(select(Group.id)
                             .where(Group.smart_query.is_not(None))).first():
                return
            # The marker is what stops this sweep's own commit poking the
            # sweeper again (the rebuild's no-change case already writes
            # nothing; this covers the case that DID change rows).
            s.info["smart_sweep"] = True
            if smartgroups.rebuild_all(Ctx(session=s)):
                s.commit()

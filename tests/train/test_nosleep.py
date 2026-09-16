"""KeepAwake's counting rules, with the platform helpers stubbed out.

A regression here is silent and expensive: the assertion quietly not held
costs somebody an overnight training run; one never released keeps a laptop
awake forever. The manager drives this through `set_active` every tick, so
the idempotence and the dead-child respawn are the load-bearing parts.
"""
from __future__ import annotations

import pytest

from media_compost.train.nosleep import KeepAwake


class _Probe(KeepAwake):
    def __init__(self):
        super().__init__()
        self.starts = 0
        self.stops = 0

    def _start(self):
        self.starts += 1

    def _stop(self):
        self.stops += 1


def test_acquire_release_refcount():
    ka = _Probe()
    ka.acquire()
    ka.acquire()
    assert ka.held and ka.starts == 1, "one assertion however many holders"
    ka.release()
    assert ka.held and ka.stops == 0
    ka.release()
    assert not ka.held and ka.stops == 1


def test_release_below_zero_is_harmless():
    ka = _Probe()
    ka.release()
    ka.release()
    assert not ka.held and ka.stops == 0
    ka.acquire()
    assert ka.held and ka.starts == 1


def test_set_active_is_idempotent():
    ka = _Probe()
    ka.set_active(True)
    ka.set_active(True)
    ka.set_active(True)
    assert ka.held and ka.starts == 1, "a poller must not stack assertions"
    ka.set_active(False)
    ka.set_active(False)
    assert not ka.held and ka.stops == 1


def test_set_active_respawns_a_dead_child():
    """A killed caffeinate (or a logind restart) is re-spawned by the next
    tick rather than silently lost."""

    class _Dead:
        def poll(self):
            return 1  # exited

    ka = _Probe()
    ka.set_active(True)
    assert ka.starts == 1
    ka._proc = _Dead()  # the helper died out from under us
    ka.set_active(True)
    assert ka.starts == 2, "the dead child is replaced"
    ka.set_active(False)
    assert ka.stops == 1


def test_keep_awake_holds_and_releases():
    """The helper is spawned while active and gone when released — a training
    run must not be interrupted by idle sleep, and nothing may leak after."""
    from media_compost.train.nosleep import KeepAwake

    k = KeepAwake("test")
    assert not k.held
    k.set_active(True)
    assert k.held
    # On platforms with a helper process it must be alive; where there is
    # none (or the tool is missing) holding is still recorded, just inert.
    if k._proc is not None:
        assert k._proc.poll() is None
    k.set_active(True)          # idempotent
    assert k.held
    k.set_active(False)
    assert not k.held and k._proc is None


def test_keep_awake_respawns_a_dead_helper():
    from media_compost.train.nosleep import KeepAwake

    k = KeepAwake("test")
    k.set_active(True)
    proc = k._proc
    if proc is None:
        pytest.skip("no helper process on this platform")
    proc.kill()
    proc.wait(timeout=5)
    k.set_active(True)          # the poller's every-tick reconcile
    assert k._proc is not None and k._proc.poll() is None
    k.set_active(False)

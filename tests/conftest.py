"""Shared setup for all three suites. Stdlib only — the core suite runs on a
base-only install, so nothing here may import fastapi, torch or the app."""

from __future__ import annotations

import os
import tempfile

import pytest

# Derived-state sweeps (the smart-group sweeper) run synchronously under
# test, so an assertion right after a commit sees the settled state instead
# of racing a debounced daemon thread.
os.environ.setdefault("MEDIA_COMPOST_SYNC_SWEEPS", "1")

# The shipped tag set is installed in EVERY library, enabled — which would put
# its ninety names into every autocomplete answer and every history golden
# the suite holds. Installed DISABLED here (the row exists, nothing reads it),
# so every fixture sees the library it saw before the set existed; the
# tag-set tests enable it by name.

# ---------------------------------------------------------------------------
# NO TEST MAY LOAD REAL WEIGHTS, AND THE SUITE MUST NOT DEPEND ON WHAT THIS
# MACHINE HAPPENS TO HAVE DOWNLOADED.
#
# Several tests drive a real endpoint that ENQUEUES a real job —
# `test_caption_tags` posts `/api/ml/jobs` with `model: florence2_base`, and
# only ever asserts the `skipped` count the enqueue answers with. The job is
# real, though: the queue's worker thread picks it up and the model host
# spawns a plugin worker, which on a machine with the weights in its cache
# loads Florence-2 FOR REAL — measured at 14 GB while loading, settling at
# 1.6 GB, and outliving the test that started it by the host's 60 s idle TTL.
# Two of those at once is 28 GB, which is what made the machine swap. CI never
# saw it: with an empty cache the load fails immediately, which is also why
# this arrived quietly, the day the weights were first downloaded.
#
# So the cache is pointed at a path that does not exist: every load fails the
# way it fails on CI, in milliseconds. Nothing can reach the network as a
# result — every model load here passes `local_files_only=True`
# (`ui/jobs.py`, and each plugin's own default), so an empty cache is a fast
# refusal rather than a download.
#
# Forcing HF_HUB_OFFLINE as well was tried and is WRONG: `_require_fetchable`
# refuses to queue a training run whose weights are neither local nor
# downloadable, so with the cache emptied it refused every job the fake
# trainer exists to drive — eleven failures in `tests/train/test_training.py`
# for a variable that was buying nothing.
#
# A test that wants to exercise cache HANDLING fakes a snapshot in a tmp_path
# and patches `constants.HF_HUB_CACHE`, which is unaffected — the constant is
# what huggingface_hub reads per call, and these variables only decide its
# default.
_HF_SCRATCH = os.path.join(tempfile.gettempdir(), "mc-tests-no-hf-cache")
os.environ.setdefault("HF_HOME", _HF_SCRATCH)
os.environ.setdefault("HF_HUB_CACHE", os.path.join(_HF_SCRATCH, "hub"))

# THE SUITE MAY NOT TAKE THE WHOLE MACHINE.
#
# An import of 32 files or more hashes ahead in a SPAWNED process pool sized
# by the cores (`Importer._PREFETCH_WINDOW`, `_PROCESSES_FROM`), which on a
# 14-core machine is fourteen interpreters — and a dozen files in this suite
# import that many. Measured over the default run: one core most of the time,
# with bursts to TWELVE (twenty python processes at 1,212%), each burst a
# fixture importing its pictures. That is a suite nobody can work beside.
#
# Two workers rather than none: both paths stay exercised — there is still a
# pool, still spawned, still processes past `_PROCESSES_FROM` — and what a
# test proves about hashing ahead is the ORDER and the result, which two
# workers prove exactly as fourteen do (`test_hashing_AHEAD_imports_exactly_
# what_hashing_IN_LINE_does` sets its own window either way). The variable is
# the product's own knob, so this is the deployment answer too: a machine
# that must stay responsive during an import has the same line.
os.environ.setdefault("MEDIA_COMPOST_IMPORT_PREFETCH", "2")

# A test that loads onnxruntime (rapidocr, an ONNX plugin) must not queue
# Microsoft telemetry under the developer's real HOME — the app's own
# processes turn this off at their entries (plugins/worker.py has the story),
# and the suite is one more process that can load the library.
os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")

# ---------------------------------------------------------------------------
# ONE COMPUTE THREAD PER TEST PROCESS.
#
# torch, faiss, numpy and onnxruntime each size their own thread pool from the
# CPU count, so a single worker importing torch opens ten OpenMP threads
# before it has done any work. Under `-n 8` that is eight pools of ten — plus
# the torch CHILD `tests/train/test_engine_smoke.py` spawns per engine, which
# inherits this environment and would otherwise open ten more of its own — on
# a machine with fourteen cores. OpenMP's workers SPIN while they wait, so
# what that costs is not throughput but the scheduler: the desktop stutters
# and the pointer stops moving, which is how this was reported.
#
# Nothing here needs a thread pool. The tensors are tiny by construction (a
# random-weight backbone built from a config, a 2000-element probe), so the
# pools were pure contention: measured over the torch-touching files at
# `-n 8`, capping them takes the run from 2.14 s to 1.44 s and the user time
# from 3.71 s to 3.07 s — FASTER, because the work was never parallel enough
# to pay for the fighting.
#
# `setdefault`, so a deliberate value survives — measuring a kernel is the
# one reason to want the pools back, and `scripts/measure_vram.py` runs in
# its own process anyway.
#
# Set here rather than in a fixture because every one of these libraries
# reads its variable ONCE, when it is imported, and conftest is imported
# before the test modules that import them.
for _var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
             "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

# ---------------------------------------------------------------------------
# AND THE SUITE YIELDS TO THE DESKTOP.
#
# The other half of the same complaint: what makes a machine feel frozen is
# not how much work is being done but who gets the CPU when everything wants
# it, and a test run has nothing to lose by waiting. At `-n 8` this suite is
# eight workers plus the torch child processes they spawn; nice them, and the
# window server (and the editor, and the browser) outrank every one of them.
#
# It costs nothing when the machine is otherwise idle: niceness only decides
# who wins a contended slot, so a run on a quiet machine takes exactly as
# long as it did. Measured over the full `-m ""` run at `-n 8`: 177 s before,
# 179 s after.
#
# ABSOLUTE (`setpriority`), not relative (`nice`): each xdist worker imports
# this file too and already inherits the controller's value, so `os.nice(5)`
# would add five per level and land somewhere nobody chose.
#
# `MEDIA_COMPOST_TEST_NICE` sets another value — 0 turns it off, which is
# what to do if a timing measurement is the point of the run.
if hasattr(os, "setpriority"):                     # POSIX only
    try:
        _nice = int(os.environ.get("MEDIA_COMPOST_TEST_NICE", "5"))
        if _nice:
            os.setpriority(os.PRIO_PROCESS, 0, _nice)
    except (OSError, ValueError):                  # pragma: no cover - policy
        pass


@pytest.fixture(autouse=True)
def _drop_fastapi_callable_caches():
    """Let a test's library go when its test is over.

    FastAPI classifies every dependency callable through three module-level
    ``lru_cache(maxsize=4096)`` tables keyed by ``_CallIdentity``, which holds
    the callable STRONGLY. That is fine for an application, whose callables
    are a fixed set — and it is a leak for a suite, because every test
    installs a fresh ``dependency_overrides[get_library] = lambda: lib``: the
    lambda closes over the library, and 4096 entries per table means nothing
    is ever evicted inside one run. Clearing the override does not help; the
    cache is what holds it.

    Measured over ``tests/ui``: 682 libraries and their SQLite engines still
    resident at the end of a 1353-test run, 3.2 GB in one worker — times
    however many workers, which is what made the machine swap. Three
    ``cache_clear()`` calls per test are the whole cost, and the entries
    they drop are recomputed by one ``inspect`` call each.
    """
    yield
    try:
        from fastapi.dependencies import models as _fa
    except ImportError:  # a base-only install has no fastapi, and needs none
        return
    for name in ("_is_gen_callable_cached", "_is_async_gen_callable_cached",
                 "_is_coroutine_callable_cached"):
        fn = getattr(_fa, name, None)
        if fn is not None and hasattr(fn, "cache_clear"):
            fn.cache_clear()

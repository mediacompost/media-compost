"""Out-of-process model downloads.

A model download (esp. the sha256 verification and blob copy of a multi-GB file)
is CPU-bound and holds the GIL, which starves the web server's request threads —
the model-cache endpoint would hang and the UI would freeze. Running the download
in its own process keeps the server responsive, makes cancellation reliable
(terminate the process), and never blocks shutdown (the process is daemonic).

Progress and status are shared with the parent via multiprocessing primitives.

**How many connections and how many downloads at once** are the two numbers
this module owns, and both were wrong. See :data:`MAX_WORKERS` and
:data:`MAX_PARALLEL`.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import sys
import threading
import time

# ``spawn`` gives the child a clean interpreter (and works uniformly on macOS);
# the Value/Array below are shareable to a spawned child via Process args.
_CTX = mp.get_context("spawn")

# status codes
RUNNING, DONE, ERROR, CANCELED = 0, 1, 2, 3

#: Files fetched at once WITHIN one download — `snapshot_download`'s own
#: default. It was 1 for a year, carried over verbatim from the thread-based
#: implementation this replaced, where a cancel was raised out of the progress
#: bar and needed the files sequential to abort promptly. A cancel is
#: ``proc.terminate()`` now, so the reason was gone and the cost was not:
#: measured against huggingface.co from here, ONE connection moves about
#: 3 MB/s whatever the link can do, so a 4 GB pipeline took twenty minutes to
#: fetch six files one after another.
MAX_WORKERS = 8

#: Whole downloads running at once, ACROSS both model lists — the Settings
#: page and the Train tab keep separate registries and neither could see the
#: other, so "Download all" on one of them while a base model fetched on the
#: other was a dozen processes and eight connections apiece competing for one
#: link, each slower than it would have been alone. Two, because the point of
#: any parallelism here is to fill a pipe that one connection cannot, and
#: `MAX_WORKERS` already does that; a second download is for the case where
#: one repo's files run out before the pipe does.
MAX_PARALLEL = 2


class Download:
    """A single in-flight (or finished) model download running in a subprocess."""

    def __init__(self, repo: str, token: str, allow_patterns: tuple[str, ...] = (),
                 resolve_patterns: bool = False):
        """``allow_patterns`` empty fetches the whole repo.

        ``resolve_patterns`` instead has the CHILD work out which files the
        pipeline needs (`pipeline_files.download_patterns`). That resolution
        is two hub round-trips, and doing it in the caller is what froze the
        server: the base-model endpoint ran it while holding the downloads
        lock, which every Models-page poll also takes, so three simultaneous
        downloads plus a polling page queued every request thread behind a
        network call that can sit until its socket times out.
        """
        self._progress = _CTX.Value("i", -1)
        self._status = _CTX.Value("i", RUNNING)
        self._err = _CTX.Array("c", 400)
        # Bytes fetched / bytes this download has to fetch. Both 0 until the
        # child has asked the hub what it is about to pull.
        self._done = _CTX.Value("q", 0)
        self._total = _CTX.Value("q", 0)
        self._proc = _CTX.Process(
            target=_run,
            args=(repo, token, list(allow_patterns), self._progress, self._status,
                  self._err, self._done, self._total, resolve_patterns),
            daemon=True,
        )
        self._launched = False

    def start(self) -> None:
        """Begin, or QUEUE — see :data:`MAX_PARALLEL`. Never blocks."""
        _schedule(self)

    def cancel(self) -> None:
        # A download still waiting its turn has no process to stop; drop it from
        # the queue instead, or the slot it was promised is handed to a corpse.
        _unqueue(self)
        # Terminate and wait briefly so the child releases its cache files before
        # the caller cleans up the partially-downloaded blobs.
        if self._proc.is_alive():
            self._proc.terminate()
            self._proc.join(timeout=5)
        self._status.value = CANCELED

    def status(self) -> int:
        # A crashed child (e.g. killed) that never set a status reads as ERROR.
        # A download that has not been LAUNCHED yet is waiting its turn, not
        # dead — hence the `_launched` test rather than `pid is not None`,
        # which cannot tell "queued" from "spawned and gone".
        if self._status.value == RUNNING and self._launched \
                and not self._proc.is_alive():
            self._status.value = ERROR
            if not self._err.value:
                self._err.value = b"download process exited unexpectedly"
        return self._status.value

    @property
    def queued(self) -> bool:
        """Accepted, waiting for a slot, no bytes moving yet."""
        return not self._launched and self._status.value == RUNNING

    @property
    def progress(self) -> int:
        return self._progress.value

    @property
    def error(self) -> str:
        return self._err.value.decode("utf-8", "replace")

    @property
    def done_bytes(self) -> int:
        return self._done.value

    @property
    def total_bytes(self) -> int:
        return self._total.value


# ---------------------------------------------------------------------------
# The queue
# ---------------------------------------------------------------------------
#
# One list for the whole process, because the network and the cache are one
# thing however many pages started the downloads. A PUMP THREAD rather than
# pumping from the status poll: a queued download reports as running so the
# pages keep polling, which would be enough while somebody is watching — and
# "start five, close the tab, come back to two finished" is exactly the
# failure that would be blamed on the downloads being slow.

_lock = threading.Lock()
_running: "list[Download]" = []
_waiting: "list[Download]" = []
_pump: "threading.Thread | None" = None


def _launch(d: "Download") -> None:
    """Start the child. Caller holds `_lock`."""
    d._launched = True
    _running.append(d)
    d._proc.start()


def _schedule(d: "Download") -> None:
    global _pump
    with _lock:
        _running[:] = [r for r in _running if r._proc.is_alive()]
        if len(_running) < MAX_PARALLEL:
            _launch(d)
            return
        _waiting.append(d)
        if _pump is None or not _pump.is_alive():
            _pump = threading.Thread(target=_pump_loop, name="hf-downloads",
                                     daemon=True)
            _pump.start()


def _unqueue(d: "Download") -> None:
    with _lock:
        if d in _waiting:
            _waiting.remove(d)


def _pump_loop() -> None:  # pragma: no cover - timing thread
    while True:
        time.sleep(0.5)
        with _lock:
            _running[:] = [r for r in _running if r._proc.is_alive()]
            while _waiting and len(_running) < MAX_PARALLEL:
                _launch(_waiting.pop(0))
            if not _waiting:
                return


def _die_with_parent() -> None:  # pragma: no cover - subprocess
    """Exit if the server that started this download goes away.

    A DOWNLOAD MUST NOT OUTLIVE THE SERVER, and `daemon=True` does not deliver
    that: multiprocessing terminates daemon children from an ATEXIT hook, which
    runs on a clean interpreter exit and not on SIGKILL, not on the `os.execv`
    the setup runner does, and not on a crash. Found the way these things are
    found — a `Qwen-Image-Edit` fetch still pulling six hours and ~3 GB after
    the server that started it had been restarted several times, invisible to
    the app (its `_downloads` map went with the old process, so Cancel had
    nothing to cancel and said "ok"), and quietly eating the whole line every
    measurement in that session was taken over.

    `parent_process()` is the multiprocessing-native answer and covers every
    one of those exits, because it watches the parent rather than trusting it
    to clean up. `os._exit` rather than raising: this is a daemon thread in a
    child whose only job is to stop, and an orderly unwind through
    huggingface_hub's thread pool is exactly what may not happen.
    """
    import multiprocessing
    import threading

    parent = multiprocessing.parent_process()
    if parent is None:
        return

    def watch():
        while True:
            if not parent.is_alive():
                os._exit(1)
            time.sleep(2.0)

    threading.Thread(target=watch, name="parent-watch", daemon=True).start()


def _run(repo, token, allow_patterns, progress, status, err, done, total,
         resolve_patterns=False):  # pragma: no cover - subprocess/network
    _die_with_parent()
    try:
        # A download is inherently online; make sure offline mode is off here
        # regardless of the parent's launch environment.
        os.environ["HF_HUB_OFFLINE"] = "0"
        os.environ["TRANSFORMERS_OFFLINE"] = "0"
        if token:
            os.environ["HF_TOKEN"] = token
            os.environ["HUGGING_FACE_HUB_TOKEN"] = token
        from huggingface_hub import snapshot_download

        if resolve_patterns and not allow_patterns:
            # Here rather than in the caller: it is network I/O, and the
            # caller is a request thread holding a lock the status poll needs.
            # An empty result still means "could not work it out", and the
            # whole repo is the fallback — same contract as before.
            from . import pipeline_files

            allow_patterns = list(pipeline_files.download_patterns(repo, token))

        total.value = _bytes_to_fetch(repo, token, allow_patterns)
        snapshot_download(repo, token=token or None,
                          allow_patterns=list(allow_patterns) or None,
                          tqdm_class=_make_tqdm(progress, done, total),
                          max_workers=MAX_WORKERS)
        progress.value = 100
        if total.value:
            done.value = total.value
        status.value = DONE
    except BaseException as exc:  # noqa: BLE001 - reported to the parent
        try:
            err.value = (str(exc)[:390] or exc.__class__.__name__).encode("utf-8", "replace")
        except Exception:
            pass
        status.value = ERROR
    finally:
        # **LEAVE WITHOUT RUNNING THE INTERPRETER'S SHUTDOWN**, for the reason
        # `_die_with_parent` gives above and this path had not taken: an
        # orderly unwind through huggingface_hub's thread pool is exactly what
        # may not happen. Returning normally hands control to multiprocessing,
        # which ends the child with `sys.exit(code)` — so `Py_Finalize` runs,
        # tears down module state, and then garbage-collects objects whose
        # `__del__` still wants it.
        #
        # Measured, from a real crash report: a Qwen-Image download ran for
        # 7.9 hours, finished, and then SIGSEGV'd in
        # `Py_Exit -> finalize_modules -> gc_collect_main -> slot_tp_finalize
        # -> delta_new` — a finalizer building a `datetime.timedelta` after
        # `_datetime`'s state was already freed, null-dereferencing at 0x10.
        # `hf_xet`'s Rust worker threads (`hf-xet-0..4`, `tracing-appender`)
        # were still live across all of it, which is what makes finalization
        # here a race rather than a formality.
        #
        # Nothing is lost by skipping it: `snapshot_download` has already
        # moved every file into the cache by the time it returns, and the
        # shared values are mmap-backed, so the parent sees them as soon as
        # they are assigned. Only the streams need a push.
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:  # noqa: BLE001 - exiting regardless
            pass
        os._exit(0)


def _bytes_to_fetch(repo, token, allow_patterns) -> int:  # pragma: no cover - network
    """How many bytes this download will actually move, or 0 if unknown.

    Asking the hub for the file sizes up front is what makes the percentage
    mean something: counting *files* rates a 20 KB config the same as a 5 GB
    checkpoint, so a repo sat at "20%" for ten minutes and then jumped. Files
    already complete in the cache are excluded, so a resumed download measures
    what is left rather than restarting the scale — and a partially fetched
    file still counts in full, because its tqdm bar starts at the resume
    offset and would otherwise never reach its total.
    """
    try:
        from fnmatch import fnmatch

        from huggingface_hub import HfApi
        from huggingface_hub.file_download import try_to_load_from_cache

        info = HfApi().model_info(repo, files_metadata=True, token=token or None)
        total = 0
        for sib in info.siblings or []:
            name = sib.rfilename
            if allow_patterns and not any(fnmatch(name, p) for p in allow_patterns):
                continue
            # A str result is a real cached file; the sentinel objects for
            # "not cached" / "known missing" are not.
            hit = try_to_load_from_cache(repo, name, revision=info.sha)
            if isinstance(hit, str):
                continue
            total += int(sib.size or 0)
        return total
    except Exception:  # noqa: BLE001 - progress must never break the download
        return 0


#: The needle `_measures_bytes` looks for. Unbraced on purpose: the real
#: format spells it `{total_fmt:>5}`.
_TOTAL_IN_BAR_FORMAT = "{total_fmt"

#: How often `_make_tqdm`'s bars may write the shared values, in seconds.
_THROTTLE_S = 0.25


def _measures_bytes(bar) -> bool:
    """Does this bar MEASURE the download, or is it a second view of one?

    huggingface_hub 1.x hands a caller's `tqdm_class` TWO byte bars per
    snapshot and feeds both from the same chunk (`http_get` calls `update()`
    and then `update_transfer()` on it): "Downloading bytes" counts what came
    off the network, "Reconstructing" what was written to disk. Sum them and
    every byte is counted twice — so the percentage runs at double speed and,
    clamped to the total, sits at 100% for the whole second half of the
    download. On a 33 GB pipeline that is hours of silence reported as done,
    and it is the thing this predicate exists to prevent.

    The bars arrive ANONYMOUS: `utils.tqdm._create_progress_bar` passes its
    `name=` only to huggingface_hub's own tqdm subclass, and ours descends
    from vanilla tqdm, so the names that would settle it are dropped before we
    see them. What does reach us is the FORMAT, and it carries the difference
    for a reason rather than by luck — transfer bytes have no meaningful
    denominator (dedup and compression make them unpredictable), so that bar
    is deliberately given a format with no total in it.

    A byte bar with no explicit format COUNTS: that is what the per-file bars
    of an older huggingface_hub look like, where summing them was right.
    """
    if getattr(bar, "unit", "") != "B":
        return False
    fmt = getattr(bar, "bar_format", None)
    return not isinstance(fmt, str) or _TOTAL_IN_BAR_FORMAT in fmt


def _make_tqdm(progress, done, total):  # pragma: no cover - subprocess/network
    """A tqdm subclass that reports download progress into shared memory.

    Prefers real bytes (`done`/`total`), and falls back to snapshot_download's
    file-count bar plus the current file's byte fraction when the size lookup
    failed. Only the bars that MEASURE the download are summed — see
    `_measures_bytes`. Throttled to ~4 Hz."""
    import time
    import tqdm as _t

    bars: list = []
    last = [0.0]

    def recompute():
        byte_bars = [b for b in bars if _measures_bytes(b)]
        files_bars = [b for b in bars if getattr(b, "unit", "") != "B" and (b.total or 0)]
        if total.value > 0:
            # Every byte bar's n, including the finished ones (a closed bar
            # keeps n == total), against the size asked for up front.
            fetched = sum(min(b.n, b.total or b.n) for b in byte_bars)
            done.value = min(fetched, total.value)
            progress.value = int(done.value * 100 / total.value)
        elif files_bars:
            fb = files_bars[-1]
            total_files = fb.total or 1
            cur = next((b for b in reversed(byte_bars)
                        if (b.total or 0) and b.n < b.total), None)
            frac = (cur.n / cur.total) if cur else 0.0
            progress.value = int(min(fb.n + frac, total_files) / total_files * 100)
        elif byte_bars:
            # Distinct names on purpose: assigning to `total`/`done` here would
            # make them locals of this whole function and turn the `total.value`
            # test above into an UnboundLocalError on the first bar update.
            seen = sum(b.total or 0 for b in byte_bars)
            got = sum(min(b.n, b.total or b.n) for b in byte_bars)
            progress.value = int(got * 100 / seen) if seen else -1

    class _Bar(_t.tqdm):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            bars.append(self)

        def update(self, n=1):
            r = super().update(n)
            now = time.monotonic()
            if now - last[0] >= _THROTTLE_S:
                last[0] = now
                recompute()
            return r

        def close(self):
            super().close()
            recompute()

    return _Bar

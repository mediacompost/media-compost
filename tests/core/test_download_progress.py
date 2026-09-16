"""The percentage a download reports, driven the way `snapshot_download`
drives it.

The bug this file exists for: huggingface_hub 1.x builds TWO byte bars from a
caller's `tqdm_class` and feeds both from the same chunk, so summing them
counted every byte twice — the bar reached 100% at half the download and sat
there. On FLUX.1 dev (33.7 GB) that was hours reported as finished, which
reads as a hung download rather than a wrong number.

Bars rather than a network fetch: the thing under test is the arithmetic over
what huggingface_hub hands us, and a test that downloaded a model to check it
would be testing the network.
"""

from __future__ import annotations

import io

import pytest

from media_compost.hub import download as dl

# `_make_tqdm` subclasses tqdm, which arrives with huggingface_hub — an
# `[train]`/`[full]` dependency and never a base one. The core suite is the
# suite CI runs on a BASE-ONLY venv (the `core-base` job, which asserts that
# `huggingface_hub` is not even importable there), so on that machine this
# file is about a stack the venv does not have: skipped there, not failed.
pytest.importorskip("tqdm")

# What huggingface_hub gives each of the two bars. Copied rather than imported
# so the test states its own premise — `test_the_bar_formats_are_still_
# huggingface_hubs` is what keeps the copy honest.
TRANSFER_FMT = "{desc}: {bar}| {n_fmt:>5}B{postfix:>12}"
RECONSTRUCT_FMT = "{l_bar}{bar}| {n_fmt:>5}B / {total_fmt:>5}B{postfix:>12}"


class _V:
    """A `multiprocessing.Value` as far as the progress code is concerned."""

    def __init__(self, value: int = 0) -> None:
        self.value = value


class _Snapshot:
    """`snapshot_download`'s progress wiring, in miniature.

    Two parent bars of the caller's class, and per-file downloads that report
    into both through huggingface_hub's private `_AggregatedTqdm` — which is
    NOT the caller's class, so those never reach us as bars of their own.
    """

    def __init__(self, total_bytes: int):
        self.progress, self.done, self.total = _V(-1), _V(0), _V(total_bytes)
        cls = dl._make_tqdm(self.progress, self.done, self.total)
        common = dict(total=0, initial=0, unit="B", unit_scale=True,
                      file=io.StringIO())
        self.transfer = cls(desc="Downloading bytes",
                            bar_format=TRANSFER_FMT, **common)
        self.reconstruct = cls(desc="Reconstructing (incomplete total...)",
                               bar_format=RECONSTRUCT_FMT, **common)

    def begin_file(self, size: int) -> None:
        """`_AggregatedTqdm.__init__`: grow both parents by the file's size."""
        self.transfer.total = (self.transfer.total or 0) + size
        self.reconstruct.total = (self.reconstruct.total or 0) + size

    def chunk(self, n: int, *, written: int | None = None) -> None:
        """One chunk off the wire: `update()` then `update_transfer()`.

        `written` differs from `n` only where the two genuinely disagree — the
        network runs ahead of what has been flushed to disk.
        """
        self.transfer.update(n)
        self.reconstruct.update(n if written is None else written)


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    """The shared values are written at ~4 Hz in production; a test that slept
    for its assertions would be timing the throttle rather than the sum."""
    monkeypatch.setattr(dl, "_THROTTLE_S", 0.0)


def test_a_byte_is_counted_once_however_many_bars_report_it():
    """The headline. Half the bytes in must read as half, not as all of them."""
    s = _Snapshot(total_bytes=1000)
    s.begin_file(1000)
    s.chunk(500)
    assert s.done.value == 500
    assert s.progress.value == 50


def test_the_percentage_reaches_100_only_when_the_bytes_are_all_in():
    """What "stuck at 100%" was: the number arrived long before the download
    did, and then had nowhere left to go."""
    s = _Snapshot(total_bytes=1000)
    s.begin_file(1000)
    seen = []
    for _ in range(10):
        s.chunk(100)
        seen.append(s.progress.value)
    assert seen == [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]


def test_the_percentage_follows_what_reached_the_disk():
    """The two bars are network bytes and written bytes, and the second is the
    honest one — a chunk received is not a chunk stored. It also cannot run
    backwards when the writer catches up."""
    s = _Snapshot(total_bytes=1000)
    s.begin_file(1000)
    s.chunk(400, written=250)   # the network is ahead of the disk
    assert s.progress.value == 25
    s.chunk(0, written=150)     # the writer catches up
    assert s.progress.value == 40


def test_a_bar_with_no_format_of_its_own_still_counts():
    """An older huggingface_hub passed the caller's class to each FILE, with
    no `bar_format` — bars we must go on summing, or the fix for the new
    shape would silently report zero on the old one."""
    progress, done, total = _V(-1), _V(0), _V(1000)
    cls = dl._make_tqdm(progress, done, total)
    for _ in range(2):
        bar = cls(total=500, unit="B", file=io.StringIO())
        bar.update(250)
    assert done.value == 500
    assert progress.value == 50


def test_the_file_count_fallback_survives_the_transfer_bar():
    """With no size lookup (`total == 0`) the file-count bar drives the
    percentage and a byte bar only supplies the current file's fraction.

    This one does NOT fail against the old summing rule — `reversed()` reached
    the reconstruction bar first, so that path was accidentally right. What it
    pins is the DIRECTION of the fix: excluding the wrong bar of the two
    leaves the fallback reading the network's idea of a file it has not
    finished writing, and every assertion above would still pass.
    """
    s = _Snapshot(total_bytes=0)
    files = s.reconstruct.__class__(total=4, unit="it", file=io.StringIO())
    files.update(1)                      # one of four files done
    s.begin_file(1000)
    s.chunk(800, written=500)            # the second file is half written
    assert s.progress.value == int((1 + 0.5) / 4 * 100)


def test_the_bar_formats_are_still_huggingface_hubs():
    """The whole fix rests on the transfer bar being the one with no total in
    its format. If huggingface_hub ever gives them the same format, or drops
    the total from the other, this is where we find out — rather than in a
    download that silently double-counts again."""
    hub = pytest.importorskip("huggingface_hub.utils._xet_progress_reporting")
    assert hub.XET_TRANSFER_BAR_FORMAT == TRANSFER_FMT
    assert hub.XET_BYTES_BAR_FORMAT == RECONSTRUCT_FMT
    assert not dl._measures_bytes(_bar(TRANSFER_FMT))
    assert dl._measures_bytes(_bar(RECONSTRUCT_FMT))


def _bar(fmt: str):
    return type("B", (), {"unit": "B", "bar_format": fmt})()


def test_the_download_child_never_runs_interpreter_shutdown():
    """A download that FINISHES must not then crash the process it ran in.

    Measured, from a real crash report: a Qwen-Image download ran 7.9 hours,
    completed, and SIGSEGV'd on the way out —
    `Py_Exit -> finalize_modules -> gc_collect_main -> slot_tp_finalize ->
    delta_new`, a finalizer building a `datetime.timedelta` after `_datetime`'s
    module state had already been freed, dereferencing null at 0x10. hf_xet's
    Rust worker threads were still live through all of it, which is what makes
    finalization here a race rather than a formality.

    `_run` therefore leaves with `os._exit`, which skips finalization
    altogether — the same reasoning `_die_with_parent` already applies, and
    safe for the same reason: `snapshot_download` has moved every file into
    the cache before it returns, and the shared values are mmap-backed.

    Asserted on the SOURCE because the failure is an interpreter-shutdown
    segfault in a child: there is no exception to catch and no return value to
    check, and a test that spawned a real download would be testing the
    network.
    """
    import ast
    import inspect

    from media_compost.hub import download as dl

    tree = ast.parse(inspect.getsource(dl._run))
    exits = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "_exit"
        and isinstance(n.func.value, ast.Name) and n.func.value.id == "os"
    ]
    assert exits, (
        "download._run returns normally, so multiprocessing ends the child "
        "with sys.exit() and the interpreter finalizes with huggingface_hub's "
        "threads still running — see this test's docstring for the crash")

    # …and in the `finally`, so it covers the failure path too: a child that
    # set ERROR and then segfaulted would report the crash over the reason.
    fn = tree.body[0]
    tries = [n for n in fn.body if isinstance(n, ast.Try)]
    assert tries and any(
        isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "_exit"
        for t in tries for stmt in t.finalbody for n in ast.walk(stmt)), \
        "the os._exit must be in the finally, or only a clean run is covered"

"""One SERVER per library, enforced with an OS-level lock at startup.

Two servers ticking one library was never supported — each process runs its
own training scheduler, background-job worker and model host, so a second
server double-starts training jobs and cross-writes their records. It has
happened in practice (an old `media-compost serve` forgotten on port 8000
grabbed queued jobs the moment a newer server enqueued them), which is why
"never run two servers against one library" is now a startup error instead of
a line of advice.

An OS lock, not a pid file: the kernel drops it the moment the holding
process exits — clean shutdown, crash, SIGKILL, anything — so a stale lock
can never wedge a library, and the descriptor is close-on-exec (Python
default) so the plugin-setup re-exec releases and re-acquires it naturally.
The file's CONTENT (pid / command / start time) is advisory, written only so
the refusal can name the other server; the lock itself is the truth.

``flock`` where there is one, ``msvcrt.locking`` on Windows. That branch used
to be an early ``return`` — "Windows has no flock", so the guard silently did
not exist there and two servers on one library were simply allowed, which is
the failure this module was written for after it happened twice.

Only servers take the SERVER lock (``server/app.py``'s startup hook): CLI
commands — bulk import, merge-library — stay usable next to a running
server, exactly as before.

There is a second lock on the same mechanism, ``migrate.lock``, and it is
taken by ANY process for the length of a schema upgrade. The server lock
cannot stand in for it: it covers server-vs-server only, so a CLI command
opening a stale library would happily migrate underneath a server that is
serving requests out of it. See :func:`library_lock`.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path


class LockBusy(RuntimeError):
    """Someone else holds this library lock. ``holder`` names them if it can."""

    def __init__(self, message: str, holder: str = "") -> None:
        super().__init__(message)
        self.holder = holder


class AnotherServerRunning(LockBusy):
    """A different server process already serves this library."""


#: One lease per SCHEDULER, not one per server. "Only one process may serve
#: this library" and "only one scheduler drains this queue" used to be one
#: lock, and the first claim was incidental — the trainer has a CLI of its
#: own now and may legitimately run beside an app whose training is off.
#: The app takes ``jobs.lock`` always and ``training.lock`` when it offers
#: training; ``media-compost-train`` takes ``training.lock``; two apps still
#: refuse each other on ``jobs.lock``, so nothing that worked before stops.
JOBS_LOCK_NAME = "jobs.lock"
TRAINING_LOCK_NAME = "training.lock"
MIGRATE_LOCK_NAME = "migrate.lock"

# The locked descriptors, kept for the process lifetime (closing one would
# release its lock). Keyed by (data_dir, name) so a lease is idempotent per
# process: the app leases training at startup, and the Trainer it builds
# later finds the lease already held rather than conflicting with itself
# (flock conflicts are per open file description, so a second open+lock in
# the SAME process refuses exactly as another process would).
_held: dict[tuple[str, str], int] = {}


#: The byte this lock is taken on. Deliberately far past any content the file
#: will ever hold: a Windows byte-range lock is MANDATORY, so locking the
#: bytes the advisory JSON lives in would make ``_describe_holder`` unable to
#: read it — the refusal could then not name the server it was refusing for.
_LOCK_OFFSET = 1 << 30


def scheduler_lease(data_dir: Path, name: str) -> None:
    """Hold ``name`` for the life of this process, or raise :class:`LockBusy`.

    A lease, not a lock around a block: a scheduler is a THREAD that lives as
    long as its process, so the exclusion has to as well. Idempotent per
    (process, library, name) — see ``_held`` — and released by the kernel on
    any exit, so a stale file can never wedge a library. A re-exec starts
    fresh and re-acquires naturally (the descriptors are close-on-exec).
    """
    key = (str(data_dir), name)
    if key in _held:
        return
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / name
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0),
                 0o644)
    try:
        _take(fd)
    except OSError:
        holder = _describe_holder(path)
        os.close(fd)
        raise LockBusy(
            f"another process runs this library's {name.removesuffix('.lock')}"
            f" scheduler at {data_dir}{holder} — stop it first, or point this"
            " one at a different library (MEDIA_COMPOST_DATA / --data-dir)",
            holder,
        ) from None
    _write_holder(fd)
    _held[key] = fd


def acquire_server_lock(data_dir: Path) -> None:
    """The APP's leases: the AI job queue always, training when offered is
    the caller's second call. Raises :class:`AnotherServerRunning` so the
    startup refusal keeps its name."""
    try:
        scheduler_lease(data_dir, JOBS_LOCK_NAME)
    except LockBusy as exc:
        raise AnotherServerRunning(
            f"another server is already using the library at {data_dir}"
            f"{exc.holder} — stop that server first, or point this one at a "
            "different library (MEDIA_COMPOST_DATA / --data-dir)",
            exc.holder,
        ) from None


@contextmanager
def library_lock(data_dir: Path, name: str):
    """Hold a named lock on a library for the length of a block.

    The same mechanism :func:`acquire_server_lock` uses — an OS lock the
    kernel drops on any exit, so a stale file can never wedge a library — but
    scoped to a ``with`` rather than to the process, because the thing it
    guards (a schema upgrade) has an end.

    Raises :class:`LockBusy` if somebody else is holding it.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / name
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0),
                 0o644)
    try:
        _take(fd)
    except OSError:
        holder = _describe_holder(path)
        os.close(fd)
        raise LockBusy(f"another process holds {name} for {data_dir}{holder}",
                       holder) from None
    try:
        _write_holder(fd)
        yield
    finally:
        os.close(fd)


def server_is_running(data_dir: Path) -> str | None:
    """``None`` when nobody ELSE serves this library, else a description of who.

    Non-destructive: it takes the server lock and lets go again, so asking
    costs nothing and never leaves the library looking busy. Used to refuse a
    schema upgrade underneath a live server — the one case a migration lock
    cannot express, since the server does not hold that lock while it serves.

    **"Else" is load-bearing.** The server's own startup takes this lock
    BEFORE it opens the library, precisely so two servers cannot race; and a
    `flock` is per open file description, so a second `open()` in the SAME
    process conflicts with the first exactly as another process would. Asking
    the question naively therefore has every server answer "yes, me" and
    refuse to migrate the library it is starting on — which is not a subtle
    failure, it is the server not starting at all. ``_held`` is the local,
    authoritative answer to "am I the server?", and if we are, the upgrade is
    ours to do: the startup hook runs before the first request.

    A caller that goes on to migrate is racing anything that starts a server
    in between; the window is microseconds and the alternative is holding the
    server lock through the whole upgrade, which would make the upgrade itself
    look like a running server to the next process along.
    """
    if any(k == (str(data_dir), JOBS_LOCK_NAME) for k in _held):
        return None
    path = data_dir / JOBS_LOCK_NAME
    if not path.exists():
        return None
    try:
        fd = os.open(path, os.O_RDWR | getattr(os, "O_BINARY", 0))
    except OSError:
        return None
    try:
        _take(fd)
    except OSError:
        return _describe_holder(path).strip() or "another server"
    finally:
        os.close(fd)
    return None


def _write_holder(fd: int) -> None:
    """Record who we are — purely for the message the next process sees."""
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, json.dumps({
        "pid": os.getpid(),
        "command": " ".join(sys.argv),
        "started": round(time.time(), 3),
    }, indent=1).encode("utf-8"))


def _take(fd: int) -> None:
    """Lock ``fd`` exclusively without blocking, or raise OSError.

    Both mechanisms are released by the kernel when the holding process exits
    — however it exits — which is the property the whole guard rests on: a
    stale lock can never wedge a library.
    """
    try:
        import fcntl
    except ImportError:  # Windows
        import msvcrt

        os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
        try:
            # Per-HANDLE on Windows, so a second acquire in this same process
            # conflicts too — which is what makes the guard testable, and is
            # the behaviour flock's per-open-file-description locks have.
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        finally:
            os.lseek(fd, 0, os.SEEK_SET)
        return
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


WRITE_LOCK_NAME = "write.lock"

#: This process's write-lease bookkeeping: data_dir -> (fd, depth). One lease
#: per LIBRARY per process, counted — the lease serializes PROCESSES, and the
#: threads of one process go on sharing it the way they already share the
#: database (WAL + busy_timeout). Counted also makes it reentrant: a script's
#: `lib.transaction()` may hold it while the importer it calls leases per
#: chunk, and the inner releases must not take the outer's lease with them.
_write_held: dict[str, list] = {}
_write_mu = threading.Lock()


def acquire_write_lease(data_dir: Path, timeout: float = 30.0) -> None:
    """Take the library's write lease, WAITING up to ``timeout`` seconds.

    Waiting, not failing: this is the cross-process mirror of SQLite's
    ``busy_timeout`` one layer down — a writer that meets a busy library
    queues rather than errors, because the other side's unit of work is
    seconds at most (everything that takes it commits in chunks precisely so
    write tenancy stays short). Raises :class:`LockBusy` only when the wait
    runs out, naming the holder.
    """
    key = str(data_dir)
    with _write_mu:
        held = _write_held.get(key)
        if held is not None:
            held[1] += 1
            return
        data_dir.mkdir(parents=True, exist_ok=True)
        path = data_dir / WRITE_LOCK_NAME
        fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0),
                     0o644)
        deadline = time.monotonic() + timeout
        pause = 0.005
        while True:
            try:
                _take(fd)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    holder = _describe_holder(path)
                    os.close(fd)
                    raise LockBusy(
                        f"waited {timeout:.0f}s for the write lease on "
                        f"{data_dir}{holder}", holder) from None
                time.sleep(pause)
                pause = min(pause * 2, 0.05)
        _write_holder(fd)
        _write_held[key] = [fd, 1]


def release_write_lease(data_dir: Path) -> None:
    """Give the lease back (outermost holder closes the descriptor)."""
    key = str(data_dir)
    with _write_mu:
        held = _write_held.get(key)
        if held is None:  # pragma: no cover - release without acquire
            return
        held[1] -= 1
        if held[1] <= 0:
            del _write_held[key]
            try:
                os.close(held[0])
            except OSError:  # pragma: no cover - double close is harmless
                pass


@contextmanager
def write_lease(data_dir: Path, timeout: float = 30.0):
    """Hold the write lease for one unit of committed work.

    The unit of the lease is the unit of the COMMIT, and that is the whole
    design: holding it for a 500-file import would block the app for
    minutes, so the importer leases per chunk (the same boundary its commits
    already have), `Library.transaction()` for the block it defers, the jobs
    worker for one result being applied, the editor for one save. Readers
    take nothing — WAL already lets them through.
    """
    acquire_write_lease(data_dir, timeout)
    try:
        yield
    finally:
        release_write_lease(data_dir)


def release_server_lock() -> None:
    """Let go of every lease explicitly (clean shutdown); the kernel would
    anyway on exit."""
    while _held:
        _, fd = _held.popitem()
        try:
            os.close(fd)
        except OSError:  # pragma: no cover - double close is harmless
            pass


def _describe_holder(path: Path) -> str:
    """" (pid 123, started 2026-07-26 14:26: media-compost serve …)" — best
    effort from the advisory file content; "" when unreadable."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    bits = []
    if data.get("pid"):
        bits.append(f"pid {data['pid']}")
    if data.get("started"):
        try:
            bits.append("started " + time.strftime(
                "%Y-%m-%d %H:%M", time.localtime(float(data["started"]))))
        except (TypeError, ValueError):
            pass
    if data.get("command"):
        bits.append(str(data["command"]))
    return f" ({', '.join(bits)})" if bits else ""

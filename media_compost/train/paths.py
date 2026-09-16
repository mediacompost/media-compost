"""Job-folder layout and tolerant JSON file helpers.

A training job is a directory ``training/<uid>/`` in the data dir:

    job.json         manager-owned record (status, progress, timestamps)
    config.json      the TrainingConfig
    manifest.json    materialized dataset (written just before spawn)
    state.json       trainer-owned live state (phase, step, pid, error)
    control.json     manager-owned command for the trainer (pause/cancel)
    metrics.jsonl    trainer-appended loss points
    samples/step-<N>/p<i>.png
    latents/         cached VAE latents
    checkpoints/last/ + checkpoints/step-<N>/
    output/          final weights
    log.txt          trainer stdout+stderr

All JSON writes go through :func:`write_json` (atomic tmp+rename) so a reader
never sees a torn file; readers use :func:`read_json` which returns None on
missing/corrupt content instead of raising.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

def interpreter():
    """The training venv's Python, or None when it has not been set up.

    Its ROOT is the checkout this package sits in — `hub.venv` no longer
    assumes one true directory, because with three package roots there is not
    one. `MEDIA_COMPOST_TRAINING_PYTHON` overrides it either way.
    """
    from media_compost.hub import venv

    return venv.interpreter_for("training", str(REPO))


#: The checkout: media_compost/train/paths.py -> train -> media_compost -> repo
REPO = Path(__file__).resolve().parents[2]


#: The standalone trainer. It may never import `media_compost` — it runs in
#: a torch venv of its own — so it is found by path rather than by import.
#: It rides INSIDE the package (as package-data: `scripts/` has no
#: `__init__.py`, so nothing can import it into the server by accident),
#: because a wheel install has no checkout: it used to live at
#: `<checkout>/training_scripts`, which on a non-editable install resolved
#: to a `<site-packages>/training_scripts` that does not exist, so a
#: wheel-installed server could set the training env up but never spawn a
#: run. Beside THIS file, it resolves wherever the package is installed.
TRAIN_SCRIPTS = Path(__file__).resolve().parent / "scripts"


# Jobs the tick loop cares about; also drives frontend poll-while-active.
ACTIVE_STATUSES = frozenset({"queued", "running", "pausing"})


def new_uid() -> str:
    return uuid.uuid4().hex[:16]


def job_dir(root: Path, uid: str) -> Path:
    """One job's folder inside the training directory.

    Takes the DIRECTORY, not the library's `Config`: where a job's state lives
    is the trainer's business, and reaching through a config object for it was
    the last thing tying these paths to the app's own settings."""
    return Path(root) / uid


def job_path(jd: Path) -> Path:
    return jd / "job.json"


def config_path(jd: Path) -> Path:
    return jd / "config.json"


def manifest_path(jd: Path) -> Path:
    return jd / "manifest.json"


def state_path(jd: Path) -> Path:
    return jd / "state.json"


def control_path(jd: Path) -> Path:
    return jd / "control.json"


def metrics_path(jd: Path) -> Path:
    return jd / "metrics.jsonl"


def events_path(jd: Path) -> Path:
    return jd / "events.jsonl"


def append_event(jd: Path, kind: str, step: int,
                 data: dict | None = None) -> None:
    """One lifecycle event (started/resumed/paused/completed/failed/canceled/
    edited) for the job's timeline. `data` carries the event's specifics —
    an edit's field changes. Append-only; never raises."""
    import time as _time

    try:
        rec = {"kind": kind, "step": int(step), "t": round(_time.time(), 3)}
        if data:
            rec["data"] = data
        with open(events_path(jd), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except (OSError, TypeError, ValueError):
        pass


def samples_dir(jd: Path) -> Path:
    return jd / "samples"


def checkpoints_dir(jd: Path) -> Path:
    return jd / "checkpoints"


def output_dir(jd: Path) -> Path:
    """Where the finished LoRA lands — the job's own result, as opposed to a
    snapshot taken on the way."""
    return jd / "output"


def lock_marker(d: Path) -> Path:
    """"Keep this" — an empty file inside a weight directory.

    A FILE rather than a record, because both sides of the process boundary
    have to read it with no imports: the server's lock and delete endpoints,
    and the trainer's own pruning.
    """
    return d / ".locked"


def is_locked(d: Path) -> bool:
    return lock_marker(d).is_file()


#: Weights that outlived the job that made them. `delete` moves what is
#: LOCKED in here rather than removing it, and registers each as a user LoRA:
#: a lock says "this one stays", and deleting the job is exactly the moment
#: that promise is worth anything.
KEPT_DIRNAME = "kept"


def kept_dir(root: Path) -> Path:
    return Path(root) / KEPT_DIRNAME


def log_path(jd: Path) -> Path:
    return jd / "log.txt"


def append_log(jd: Path, text: str) -> None:
    """Append one plain line to the job's ``log.txt``.

    For the things the *manager* knows and the trainer never sees — how many
    degraded copies each variant produced, for instance. A variant whose tag
    gates matched nothing produces no entries at all, and silence there reads
    as "it is working".
    """
    try:
        with open(log_path(jd), "a", encoding="utf-8") as f:
            f.write(text.rstrip("\n") + "\n")
    except OSError:
        pass


def append_log_banner(jd: Path, kind: str, step: int) -> None:
    """Mark a new run inside the append-only ``log.txt``.

    Every start and resume appends to the same file, so without a marker the
    output of three runs reads as one long stream and the reader cannot tell
    where the crash they are looking for actually happened. The banner is
    written in ANSI (bold cyan, like the trainer's own colored output) so the
    log viewer highlights it, and stays readable as plain text when the file is
    opened outside the app.
    """
    import time as _time

    label = {"started": "training started",
             "resumed": "training resumed"}.get(kind, kind)
    stamp = _time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"── {label} · {stamp} · step {int(step)} " + "─" * 12
    try:
        with open(log_path(jd), "a", encoding="utf-8") as f:
            f.write(f"\n\x1b[1;36m{line}\x1b[0m\n")
    except OSError:
        pass


#: Attempts before a contended file is given up on, and the first pause
#: between them — each retry waits twice as long as the last, so eight
#: attempts span roughly 250 ms in total. Bounded well under one manager
#: tick, and far beyond the sub-millisecond window a single replace leaves:
#: what needs the tail is a BURST, two writers landing on one destination
#: repeatedly, which is the only way real contention here arrives.
_READ_RETRIES = 8
_READ_BACKOFF = 0.002


def _backoff(attempt: int) -> float:
    return _READ_BACKOFF * (2 ** attempt)


def _open_text(path: Path):
    """Open ``path`` for reading in a way that does not block a replacement.

    On POSIX this is just ``open`` — a rename over an open file always works.
    On Windows a handle must explicitly grant FILE_SHARE_DELETE for the file
    to be renamed/replaced while it is open, and CPython's ``open`` grants
    read+write sharing but NOT delete. So an ordinary reader here — the
    manager tick, an API request, the trainer's own poll — makes every
    concurrent ``write_json`` fail with ERROR_ACCESS_DENIED.

    Retrying the write covers a brief overlap, but the reader is the side
    that causes it, so this is where it is actually fixed: open through
    CreateFileW with all three share flags and the writer is never blocked
    in the first place.
    """
    if os.name != "nt":
        return open(path, "r", encoding="utf-8")

    import ctypes
    import msvcrt

    GENERIC_READ = 0x80000000
    FILE_SHARE_ALL = 0x00000001 | 0x00000002 | 0x00000004  # read|write|delete
    OPEN_EXISTING = 3
    INVALID_HANDLE = ctypes.c_void_p(-1).value

    CreateFileW = ctypes.windll.kernel32.CreateFileW
    CreateFileW.restype = ctypes.c_void_p
    handle = CreateFileW(str(path), GENERIC_READ, FILE_SHARE_ALL, None,
                         OPEN_EXISTING, 0, None)
    if handle == INVALID_HANDLE:
        # Raise what the caller already knows how to classify: missing vs
        # locked drive the retry decision above. WinError() with no argument
        # reads GetLastError itself — ctypes.get_last_error() would need the
        # library opened with use_last_error=True and returns 0 here.
        raise ctypes.WinError()
    # open_osfhandle takes ownership: closing the file object closes the
    # handle, so there is no separate CloseHandle path to get wrong.
    fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
    return os.fdopen(fd, "r", encoding="utf-8")


def read_json(path: Path):
    """None on missing, unreadable or torn content — never raises.

    A PermissionError is RETRIED rather than reported as missing. On Windows
    `os.replace` cannot swap a file atomically the way rename(2) does: for a
    moment the destination cannot be opened at all, and a reader landing in
    that window gets ERROR_ACCESS_DENIED. Since every reader here treats
    "unreadable" as "no such job", the effect was a job blinking out of the
    Train list — or a running job briefly reading as gone, which `_finalize`
    would act on — at random, under exactly the load that makes writes
    frequent. Same class of bug as the torn write `write_json` guards against,
    from the other side.
    """
    for attempt in range(_READ_RETRIES):
        try:
            with _open_text(path) as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except PermissionError:
            # Transient only while someone is mid-replace; a genuinely
            # unreadable file exhausts the retries and reports missing.
            if attempt == _READ_RETRIES - 1:
                return None
            time.sleep(_backoff(attempt))
        except (OSError, ValueError):
            return None
    return None


def write_json(path: Path, data) -> None:
    """Atomic write: readers see either the old or the new file, never a mix.

    The temp name carries the THREAD as well as the process. The manager
    writes `job.json` from its tick thread and from request threads, and a
    shared temp name let two of those interleave into it: a shorter record
    written over a longer one left the tail of the old one behind, the file
    stopped being JSON, and the job vanished from the list — every reader here
    treats unparseable as missing.

    The replace is RETRIED for the same reason `read_json` retries its open,
    from the other side: `os.replace` is only atomic-and-always-possible on
    POSIX. On Windows it cannot swap a file that any other handle has open,
    so a concurrent reader — the tick, an API request, the trainer's own
    poll — makes it raise ERROR_ACCESS_DENIED. Unhandled, that propagates
    into whichever thread was recording progress and the write is simply
    LOST: a status the manager believes it stored, a pause that was never
    recorded. Retrying rides out the reader's microseconds-long window; a
    failure that outlasts every attempt still raises, because silently
    dropping a state write is the thing to avoid.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(
        path.suffix + f".tmp{os.getpid()}-{threading.get_ident()}")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    for attempt in range(_READ_RETRIES):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == _READ_RETRIES - 1:
                # The temp file is ours and named after this thread, so
                # nothing will ever pick it up again: drop it rather than
                # leaving a job folder growing one stray per failed write.
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
            time.sleep(_backoff(attempt))


def list_job_dirs(root: Path) -> list[Path]:
    """Every job folder that has a record, unordered."""
    root = Path(root)
    try:
        return [d for d in root.iterdir()
                if d.is_dir() and job_path(d).is_file()]
    except OSError:
        return []

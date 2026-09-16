"""Background worker that runs the queued AI actions one at a time.

One :class:`JobQueue` lives on the :class:`Library` singleton. Callers enqueue
:class:`~media_compost.db.Job` rows and the worker thread picks them up
oldest-first, runs the model out-of-process via the shared
:class:`~media_compost.ui.plugins.host.ModelHost`, applies the result to the
database, and records the outcome on the job. ``_apply_result`` is the
dispatch — one applier per task kind. The flavor, by example:

* **bg_removal** / **watermark_removal** — a new PNG added to the item's source
  files and made the active source (or a new linked item).
* **caption** — a *pending* caption (skipped if the same text already exists).
* **tag** — the tags the item does not already carry, *pending*, placed in
  the item's auto-managed "Pending" group, each optionally carrying a
  detected bounding box (a tag it DOES carry gets a pending copy only when
  the model drew a box, which approval merges into the existing one).
* **depth / pose / canny / lineart** — a control image stored as a
  ``FileArtifact`` under the item's active source file.
* **faces** — detections reconciled into the item's face records
  (``faces.reconcile``), plus suggested names.
* **panels** — each detected panel cropped into its own item linked to the
  page (or collected into a new sequence).

Jobs still queued (or a running one, cooperatively) can be canceled.
"""

from __future__ import annotations

import io
import json
import logging
import os
import sys
import time
import threading
import traceback
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from PIL import Image
from sqlalchemy import func, select

from media_compost import faces as facelib
from media_compost import media
from media_compost import prefs
from media_compost.db import (
    Caption, Face, File, Item, ItemEmbedding, ItemGroup, ItemSubject, ItemTag,
    ItemTagBox, ItemTagGroup, ItemTagPlacement, Job, Relationship, Sequence,
    SequenceItem, Tag, chunked, get_setting, next_file_number, touch_items,
)
from .facevec import SubjectMatcher
from .plugins import registry, tasks
from .plugins.worker import read_image
from media_compost.colorkey import color_signature
from media_compost.dedup import compute_phash_image
from media_compost.fileops import record_edit
from media_compost.itemmeta import index_file_metadata
from media_compost.instance import write_lease
from media_compost.history import log_event
from media_compost.sequences import ensure_container
from media_compost.storage import sha256_bytes


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Cap a stored log so a chatty model run can't bloat the DB.
_MAX_LOG = 200_000

# Job outcomes that finished without error but produced nothing usable (an empty
# caption / an empty tag list). Surfaced as a "warning" status so the task stays
# visible in the Background Tasks list instead of being auto-cleared like a plain
# success.
_WARNING_MESSAGES = {"no caption produced", "no tags produced",
                     "no watermark detected", "no text detected",
                     "no depth produced", "no pose produced",
                     "no canny produced", "no lineart produced",
                     "no panels detected", "no colorization produced",
                     "no upscaled image produced", "no restored image produced",
                     "no descreened image produced"}


class _Tee:
    """Write to several streams at once (keeps the real console output while
    also collecting it into a buffer)."""

    def __init__(self, *streams):
        self._streams = streams

    def write(self, s):  # pragma: no cover - trivial passthrough
        for st in self._streams:
            try:
                st.write(s)
            except Exception:
                pass
        return len(s)

    def flush(self):  # pragma: no cover - trivial passthrough
        for st in self._streams:
            try:
                st.flush()
            except Exception:
                pass


class _RedBuf:
    """Buffer wrapper that wraps each chunk in red ANSI before storing, so
    stderr output is shown red in the log viewer by default."""

    def __init__(self, buf):
        self._buf = buf

    def write(self, s):
        if s:
            self._buf.write(f"\x1b[31m{s}\x1b[0m")
        return len(s)

    def flush(self):
        self._buf.flush()


class _CaptureLog:
    """Capture everything the packages used by a job print or log — stdout,
    stderr and the standard ``logging`` output — into a buffer, while still
    letting it reach the real console. Used to record a job's full log."""

    def __init__(self):
        self.buf = io.StringIO()

    def __enter__(self) -> "_CaptureLog":
        self._out, self._err = sys.stdout, sys.stderr
        sys.stdout = _Tee(self._out, self.buf)
        # stderr is colored red by default in the stored log (the real console
        # still gets the raw text). ANSI codes a package emits itself override
        # this mid-string; the trailing reset closes each chunk.
        sys.stderr = _Tee(self._err, _RedBuf(self.buf))
        self._handler = logging.StreamHandler(self.buf)
        self._handler.setFormatter(
            logging.Formatter("%(levelname)s %(name)s: %(message)s")
        )
        self._root = logging.getLogger()
        self._prev_level = self._root.level
        if self._prev_level == logging.NOTSET or self._prev_level > logging.INFO:
            self._root.setLevel(logging.INFO)
        self._root.addHandler(self._handler)
        return self

    def __exit__(self, *exc):
        self._root.removeHandler(self._handler)
        self._root.setLevel(self._prev_level)
        sys.stdout, sys.stderr = self._out, self._err
        return False

    def add(self, text: str) -> None:
        self.buf.write(text)

    def text(self) -> str:
        return self.buf.getvalue()[-_MAX_LOG:]


class _Applied:
    """The handle of a per-item chunk that was run AND applied on the spot
    (`_run_one_item`): nothing to collect, only whether it landed."""

    errors: list = []

    def __init__(self, msg, failed: bool = False):
        self.msg = msg
        self.failed = failed

    def result(self) -> list:
        return [self.msg]


class _SyncBatch:
    """`ModelHost.submit_paths`'s handle for a host that has no such door: the
    tests' stand-ins, which take pictures through `run_batch` / `run`. The
    pictures are decoded HERE (the host's threads) and the call is made at
    once; `result()` just answers. A path that cannot be read is that slot's
    error, as the worker would say."""

    def __init__(self, queue, job, paths, ctx, max_dim):
        self.errors: list = []
        readable, images = [], []
        for k, p in enumerate(paths):
            try:
                if not p:
                    raise OSError("no stored image")
                images.append(queue._read_image(p, max_dim))
                readable.append(k)
            except Exception as exc:  # noqa: BLE001 - one picture's failure
                self.errors.append((k, str(exc)))
        # The worker's rule, kept on this side too: a batch that fails is
        # retried one picture at a time, and one picture's failure is its
        # own slot — a selection of two hundred must not end on the one
        # picture something could not read.
        out = None
        host = queue.lib.model_host
        batch = getattr(host, "run_batch", None)
        if images and callable(batch):
            try:
                out = list(batch(job.kind, job.model, images, ctx, {}))
                if len(out) != len(images):
                    raise RuntimeError(f"run_batch answered {len(out)} for {len(images)}")
            except Exception as exc:  # noqa: BLE001 - fall back to one at a time
                print(f"batch of {len(images)} failed, retrying one at a time: "
                      f"{exc}", file=sys.stderr)
                out = None
        if out is None:
            out = []
            for k, im in zip(readable, images):
                try:
                    out.append(host.run(job.kind, job.model, im, ctx, {}))
                except Exception as exc:  # noqa: BLE001 - one picture's failure
                    out.append(None)
                    self.errors.append((k, str(exc)))
        self._results: list = [None] * len(paths)
        for k, res in zip(readable, out):
            self._results[k] = res

    def result(self) -> list:
        return self._results


#: Runners for job kinds whose WORK LIVES ABOVE THE QUEUE, keyed by kind.
#:
#: The layering runs one way — `server/` imports the queue, never the other
#: way round (`tests/ui/test_ops_ratchet.py`) — so a job whose work belongs
#: to a router cannot be reached by an import from here. The module that
#: owns the work REGISTERS it instead, which is the same shape the trainer's
#: `release_models` hook has: a callable the app sets, never an import.
#:
#: A runner is ``run(ctx, lib, options, progress=, stopped=) -> str`` and
#: answers with the job's summary message, exactly as the branches above do.
#: The QUEUE builds the `Ctx` and owns the progress and the cancel, so what
#: is registered is the work itself and nothing about being a job.
_RUNNERS: dict[str, "Callable[..., str]"] = {}


def register_runner(kind: str, run) -> None:
    """Name the runner for a job kind whose work lives above the queue.

    Called at import time by the module that owns it, so a job of that kind
    is runnable whenever the app that can enqueue one has been built.
    """
    _RUNNERS[kind] = run


class JobQueue:
    def __init__(self, lib):
        self.lib = lib
        self._cv = threading.Condition()
        self._canceled: set[int] = set()
        #: Running batch jobs asked to stop at their next chunk boundary.
        self._paused: set[int] = set()
        #: Running batch jobs that will still pick up ids appended to them,
        #: and the lock that makes "append" and "decide I am finished" one
        #: decision. See `enqueue(merge=True)`.
        self._mergeable: set[int] = set()
        self._batch_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False

    # ---- public API -------------------------------------------------------

    def enqueue(self, kind: str, model: str, item_ids: list[int],
                into_sequence: bool = False, username: str = "",
                options: dict | None = None,
                merge: bool = False) -> list[int]:
        """Create one queued job per item; return the new job ids.
        ``into_sequence`` is the menu's one extra-output toggle, which only
        ``panels`` offers: it groups the detected panels into a new sequence
        (one per page). ``username`` is the caller, captured now so the
        worker can attribute the result's history event (it runs off-request,
        with no HTTP context). ``options`` (JSON-stored per job) carries action
        extras like the reference image of a reference-guided colorization —
        and this toggle, which is one of them: an extra a single task asks
        for, not a fact every job has.

        ``merge`` appends to the live batch job already doing this exact
        thing instead of making a second one — what an IMPORT wants, since it
        hands its files over in batches and a job per batch is a queue of
        twenty rows for one run. Off by default: a person pressing "Detect
        faces" twice means two tasks, and one silently swallowing the other
        would be a request with nowhere to watch it. Only a BATCH kind can
        merge (a one-item job has no list to append to)."""
        model = registry.resolve_model(kind, model)
        # Honor the toggle only where the task DECLARES it — that
        # declaration is the one list, so a task gaining the option cannot
        # be forgotten here (descreen once was, back when every image task
        # had a switch, and its own silently did nothing).
        task = tasks.task(kind)
        if into_sequence and task is not None and task.sequence_option:
            options = {**(options or {}), "into_sequence": True}
        opts_json = json.dumps(options) if options else ""
        ids: list[int] = []
        with self.lib.db.session() as s:
            # One chunked existence check, not a `s.get` per id — a group can
            # hold tens of thousands of items. Caller order is preserved.
            existing: set[int] = set()
            for chunk in chunked(item_ids):
                existing.update(s.execute(
                    select(Item.id).where(Item.id.in_(chunk))
                ).scalars().all())
            valid = [iid for iid in item_ids if iid in existing]
            if kind in self._EXPAND_SEQ_KINDS:
                valid = self._expand_sequences(s, valid)
            # EVERY MODEL HERE READS A PICTURE, and a film's active file is not
            # one — the job opened it with Pillow and died with whatever Pillow
            # says about an mp4. The menus do not offer these on a video, so a
            # video reaching here came from a script or a stale page; dropping
            # it is the same answer `_expand_sequences` gives a container, and
            # for the same reason. A film's frames are reachable as STILLS,
            # which are ordinary image items.
            valid = self._only_pictures(s, valid)
            if not valid:
                return []
            if merge:
                merged = self._append_to_live_job(
                    s, kind, model, valid, username, opts_json)
                if merged is not None:
                    s.commit()
                    self._ensure_worker()
                    with self._cv:
                        self._cv.notify_all()
                    return [merged]
            # A whole selection runs as ONE job with a progress bar — the
            # model loads once and every item goes through it — instead of a
            # task per image. Every kind, not only the ones whose model call
            # takes a chunk: what a person asked for once is one thing to
            # watch, pause and cancel, whatever the model does inside it.
            if len(valid) > 1 or kind in self._BATCH_ONLY_KINDS:
                job = Job(kind=kind, model=model, item_id=valid[0],
                          item_ids=json.dumps(valid), status="queued",
                          username=username, options=opts_json)
                s.add(job)
                s.flush()
                ids.append(job.id)
            else:
                for iid in valid:
                    job = Job(kind=kind, model=model, item_id=iid,
                              status="queued", username=username,
                              options=opts_json)
                    s.add(job)
                    s.flush()
                    ids.append(job.id)
            s.commit()
        self._ensure_worker()
        with self._cv:
            self._cv.notify_all()
        return ids

    def _append_to_live_job(self, s, kind: str, model: str, ids: list[int],
                            username: str, opts_json: str) -> int | None:
        """Add ``ids`` to the batch job already running or waiting to do this,
        returning its id — or None when there is none to add to.

        The lock is the whole of the correctness here: a job that has just
        read its list for the last time must not be handed more work, so the
        worker DROPS ITSELF from `_mergeable` while holding it, and this
        decision is made while holding it too. Either an append lands before
        that read, or it finds no target and a new job is created; there is
        no window in which items are appended to a job that will never look
        again.
        """
        with self._batch_lock:
            row = s.execute(
                select(Job).where(
                    Job.kind == kind, Job.model == model,
                    Job.username == username, Job.options == opts_json,
                    Job.item_ids.is_not(None),
                    Job.status.in_(("queued", "paused", "running")),
                ).order_by(Job.id.desc()).limit(1)
            ).scalars().first()
            # A RUNNING job counts only while it says it will look again.
            if row is None or (row.status == "running"
                               and row.id not in self._mergeable):
                return None
            try:
                have = [int(x) for x in json.loads(row.item_ids or "[]")]
            except ValueError:
                return None
            seen = set(have)
            fresh = [i for i in ids if i not in seen]
            if fresh:
                row.item_ids = json.dumps(have + fresh)
            return row.id

    def pause(self, job_id: int) -> bool:
        """Hold a job where it is. A queued one simply stops being next; a
        running BATCH job stops at its next chunk boundary, with everything
        it has already done committed and its cursor written down.

        A running single-item job is not pausable and says so: there is no
        boundary inside one model run to stop at, and stopping between "the
        model answered" and "the answer was applied" would throw the
        expensive half away."""
        with self.lib.db.session() as s:
            job = s.get(Job, job_id)
            if job is None:
                return False
            if job.status == "queued":
                job.status = "paused"
                s.commit()
                return True
            if job.status == "running" and self._is_batch(job):
                self._paused.add(job_id)
                # Say so NOW: the loop stops at the next chunk boundary, and a
                # chunk of eight pictures through a detector is long enough
                # that a button with no visible effect reads as a broken one.
                job.message = "Pausing…"
                s.commit()
                return True
        return False

    def resume(self, job_id: int) -> bool:
        """Put a paused job back in the queue, at its own place in the order
        (its id) rather than at the end — it was there before the pause."""
        self._paused.discard(job_id)
        with self.lib.db.session() as s:
            job = s.get(Job, job_id)
            if job is None or job.status != "paused":
                return False
            job.status = "queued"
            job.finished_at = None
            s.commit()
        self._ensure_worker()
        with self._cv:
            self._cv.notify_all()
        return True

    def _is_batch(self, job) -> bool:
        """Does this job run through `_run_item_batch` — i.e. does it have a
        boundary between items to stop at?"""
        return bool(job.item_ids or job.kind in self._BATCH_ONLY_KINDS)

    def enqueue_video_edit(self, item_id: int, options: dict,
                           username: str = "") -> int:
        """Queue a video render — a background task with no model behind it.

        Its own entry point rather than a kind passed to `enqueue`: that one
        resolves a MODEL for the kind and consults the AI task table for the
        new-item toggle, neither of which means anything here. What it shares
        is everything that matters — the same worker, the same row, so the
        render shows up in the background-task list with a progress bar and can
        be cancelled there like any other.
        """
        with self.lib.db.session() as s:
            if s.get(Item, item_id) is None:
                raise ValueError("item not found")
            job = Job(kind="video_edit", model="", item_id=item_id,
                      status="queued", username=username,
                      options=json.dumps(options))
            s.add(job)
            s.flush()
            jid = job.id
            s.commit()
        self._ensure_worker()
        with self._cv:
            self._cv.notify_all()
        return jid

    def enqueue_stills(self, item_id: int, options: dict,
                       username: str = "") -> int:
        """Queue an "every N seconds" run of stills over a film.

        Its own entry point for the same reason `enqueue_video_edit` is: there
        is no model behind it, and what it wants from the queue is the worker,
        the row, the progress bar and the cancel button.
        """
        with self.lib.db.session() as s:
            if s.get(Item, item_id) is None:
                raise ValueError("item not found")
            job = Job(kind="stills", model="", item_id=item_id,
                      status="queued", username=username,
                      options=json.dumps(options))
            s.add(job)
            s.flush()
            jid = job.id
            s.commit()
        self._ensure_worker()
        with self._cv:
            self._cv.notify_all()
        return jid

    def enqueue_estimate(self, options: dict, username: str = "") -> int:
        """Queue an estimate's WRITE over a whole scope.

        THE ONE JOB HERE THAT IS ABOUT NO PICTURE. It walks a search's scope
        a page at a time and never holds the ids — which is what lets it run
        over a million items — so there is nothing to put in `item_id` and
        naming an arbitrary picture would file the job on that picture's
        row. `item_id` is NULL, and every reader of it takes that.
        """
        with self.lib.db.session() as s:
            job = Job(kind="estimate", model="", item_id=None,
                      status="queued", username=username,
                      options=json.dumps(options))
            s.add(job)
            s.flush()
            jid = job.id
            s.commit()
        self._ensure_worker()
        with self._cv:
            self._cv.notify_all()
        return jid

    def cancel(self, job_id: int) -> bool:
        with self.lib.db.session() as s:
            job = s.get(Job, job_id)
            if job is None:
                return False
            if job.status in ("queued", "paused"):
                job.status = "canceled"
                job.finished_at = _now()
                s.commit()
                self._paused.discard(job_id)
                return True
            if job.status == "running":
                # Cooperative: the worker checks this set before applying.
                self._canceled.add(job_id)
                return True
        return False

    def cancel_all(self) -> int:
        """Cancel every active job at once: queued ones are marked canceled
        immediately; running ones are flagged for cooperative cancellation (the
        worker checks the set between steps and before applying). Returns the
        number of jobs affected."""
        n = 0
        with self.lib.db.session() as s:
            for job in s.execute(
                select(Job).where(Job.status.in_(("queued", "paused")))
            ).scalars().all():
                job.status = "canceled"
                job.finished_at = _now()
                n += 1
            running = list(s.execute(
                select(Job.id).where(Job.status == "running")
            ).scalars().all())
            s.commit()
        for jid in running:
            self._canceled.add(jid)
            n += 1
        return n

    # ---- worker -----------------------------------------------------------

    def _ensure_worker(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, name="ml-jobs", daemon=True
        )
        self._thread.start()

    def _next_queued_id(self) -> int | None:
        with self.lib.db.session() as s:
            job = s.execute(
                select(Job).where(Job.status == "queued")
                .order_by(Job.id).limit(1)
            ).scalars().first()
            return job.id if job else None

    def _loop(self) -> None:  # pragma: no cover - exercised via integration
        while self._running:
            jid = self._next_queued_id()
            if jid is None:
                with self._cv:
                    self._cv.wait(timeout=30)
                continue
            self._run_job(jid)

    def _run_job(self, jid: int) -> None:
        with self.lib.db.session() as s:
            job = s.get(Job, jid)
            if job is None or job.status != "queued":
                return
            if jid in self._canceled:
                self._canceled.discard(jid)
                job.status = "canceled"
                job.finished_at = _now()
                s.commit()
                return
            job.status = "running"
            job.started_at = _now()
            s.commit()
        # Do the (potentially slow) work, then record the outcome. All output the
        # model / its packages produce is captured for the "view log" overlay.
        message = ""
        status = "done"
        cap = _CaptureLog()
        try:
            with cap:
                message = self.run_one(jid)
            # A cancel is only honored when run_one actually acted on it (it
            # returns a "canceled…" message and discards the result). If the
            # cancel arrived after the result was already applied, the work
            # exists — the job stays "done" rather than lying "canceled".
            if message.startswith("canceled") and jid in self._canceled:
                status = "canceled"
            elif message.startswith("paused") and jid in self._paused:
                # Held, not finished: the row keeps its cursor and its place
                # in the list, and `resume` puts it back in the queue.
                status = "paused"
            elif message in _WARNING_MESSAGES:
                # Ran fine but produced nothing usable (empty caption / no tags).
                status = "warning"
        except Exception as exc:  # noqa: BLE001 - surfaced on the job row
            status = "failed"
            message = str(exc)[:300] or exc.__class__.__name__
            # The traceback isn't printed to stderr by default; add it to the log
            # in red (it's error output).
            cap.add("\n\x1b[31m" + traceback.format_exc() + "\x1b[0m")
        self._canceled.discard(jid)
        self._paused.discard(jid)
        with self.lib.db.session() as s:
            job = s.get(Job, jid)
            if job is not None:
                job.status = status
                job.message = message
                job.log = cap.text()
                # A paused job has not finished, and stamping it would make
                # every reader that asks "when did this end" answer wrongly.
                if status != "paused":
                    job.finished_at = _now()
                s.commit()

    def _set_progress(self, jid: int, progress: int, message: str = "",
                      done: int | None = None) -> None:
        """Write a job's live progress in its own short transaction, so the
        polling UI sees it while the job's main transaction is still open.

        ``done`` is the batch cursor — how many items are finished — and is
        the same write deliberately: it is committed exactly when the work it
        counts is, so a pause (or a crash) resumes from a number that is true
        rather than one item ahead of itself."""
        with self.lib.db.session() as s:
            job = s.get(Job, jid)
            if job is not None:
                job.progress = max(0, min(100, int(progress)))
                if message:
                    job.message = message
                if done is not None:
                    job.done_count = max(0, int(done))
                s.commit()

    # ---- applying results (its own transaction; testable directly) --------

    def run_one(self, jid: int) -> str:
        """Run a single job's model and apply its result. Returns a summary."""
        paths = self._load_settings()
        with self.lib.db.session() as s:
            job = s.get(Job, jid)
            if job is None:
                raise RuntimeError("job not found")
            # Attribute the result's history event to whoever enqueued the job
            # (log_event reads session.info["username"]); this runs off-request.
            s.info["username"] = job.username or ""
            # A video render has no model to load and no plugin to reach — it
            # is ffmpeg over this item's own file — so it branches out here,
            # above everything that exists to feed a model.
            if job.kind == "video_edit":
                return self._run_video_edit(s, job, jid)
            if job.kind == "stills":
                return self._run_stills(s, job, jid)
            # A kind whose work lives ABOVE the queue runs through its
            # registered runner (see `register_runner`).
            runner = _RUNNERS.get(job.kind)
            if runner is not None:
                return self._run_registered(s, job, jid, runner)
            # Jobs always run offline: a model can only be enqueued once its
            # weights are downloaded, so local_files_only is always safe and
            # avoids any network round-trip at run time. The model runs
            # out-of-process in the shared ModelHost (kept warm across jobs).
            ctx = {"local_files_only": True, "model_paths": paths, "token": ""}
            # A multi-item tag or face job handles the whole selection in one
            # task, running the model over every item with a single warm load
            # (see below).
            if job.item_ids or job.kind in self._BATCH_ONLY_KINDS:
                return self._run_item_batch(s, job, jid, ctx)
            item = s.get(Item, job.item_id)
            if item is None:
                raise RuntimeError("item not found")
            return self._run_one_item(s, job, item, jid, ctx)

    def _run_one_item(self, s, job, item, jid: int, ctx: dict) -> str:
        """Everything ONE item of a model job costs: resolve its per-item
        options, run the model, apply the result.

        Shared by the single-item path and the batch loop, so a job of one
        picture and one of two hundred do exactly the same thing to each of
        them. It commits (through `_apply_result`) and takes the write lease
        around that commit — reentrant, so the batch loop's own lease nests.
        """
        # Panel detection on a *sequence* runs the model on every page and
        # collects all pages' panels into one new sequence (see below).
        if job.kind == "panels" and item.kind == "sequence":
            pages = self._sequence_pages(s, item)
            total = len(pages)
            per_page = []
            for i, page in enumerate(pages):
                # Stop between pages if the job was canceled — nothing has been
                # written yet, so this is a clean cancel with no partial output.
                if jid in self._canceled:
                    return "canceled"
                self._set_progress(
                    jid, int(i * 100 / total) if total else 0,
                    f"Detecting panels — page {i + 1} / {total}")
                # One unreadable/failed page shouldn't sink the whole chapter —
                # log it and treat it as zero panels, keep going.
                try:
                    img = self._active_image(s, page)
                    boxes = self.lib.model_host.run(job.kind, job.model, img, ctx, {}) or []
                except Exception as exc:  # noqa: BLE001 - per-page resilience
                    print(f"panel detection failed for page {page.id}: {exc}",
                          file=sys.stderr)
                    boxes = []
                per_page.append((page, boxes))
            if jid in self._canceled:
                return "canceled"
            self._set_progress(jid, 100, "Collecting panels…")
            with write_lease(self.lib.config.data_dir):
                msg = self._apply_panels_sequence(s, item, per_page, job.model)
                s.commit()
            return msg
        t_start = time.perf_counter()
        image = self._active_image(s, item, self._max_dim(job.kind))
        t_decoded = time.perf_counter()
        options: dict = {}
        # The "use tagged boxes" watermark model skips detection and inpaints
        # the item's own "watermark" tag boxes instead.
        if job.kind == "watermark_removal" and job.model.endswith(":boxes"):
            options["boxes"] = self._watermark_boxes(s, item)
        # TEXT REMOVAL PAINTS OUT WHAT THE LIBRARY HAS READ, and nothing
        # else — the regions in the item's Text tab, at their smallest
        # level. `detect_with` names an OCR engine to READ the page first
        # (the "detect and remove" entries, offered for engines that have
        # not read this file): its result is stored and reconciled like
        # any other reading, so the removal and the Text tab can never
        # disagree about where the text was, and the reading survives the
        # job that asked for it.
        #
        # UNLESS the ":boxes" variant was picked, which is the watermark
        # pair's bargain one subject along: paint out the boxes on the
        # CONFIGURED text tag instead of the reading. Detecting first
        # would be beside the point there — the boxes are what is being
        # asked about — so `detect_with` is not consulted on that path.
        if job.kind == "text_removal":
            if job.model.endswith(":boxes"):
                options["quads"] = self._tag_box_quads(
                    s, item, prefs.read_text_tag(s))
            else:
                engine = str(self._job_options(job).get("detect_with") or "")
                if engine:
                    found = self.lib.model_host.run("ocr", engine, image,
                                                    ctx, {})
                    if jid in self._canceled:
                        return "canceled"
                    with write_lease(self.lib.config.data_dir):
                        self._apply_ocr(s, item, found or [], engine)
                        s.commit()
                options["quads"] = self._text_region_quads(s, item)
        # A reference-guided colorization carries its reference image's id
        # in the job options; resolve it to a path the worker can open.
        if job.kind == "colorize":
            ref = self._job_options(job).get("reference", "")
            if ref:
                path = self.lib.config.refs_dir / os.path.basename(str(ref))
                if path.is_file():
                    options["reference"] = str(path)
        t_model = time.perf_counter()
        result = self.lib.model_host.run(job.kind, job.model, image, ctx, options)
        t_answered = time.perf_counter()
        # A cancel that arrived while the model was running: nothing has
        # been written yet, so drop the result instead of applying it and
        # then claiming "canceled" over freshly created items/files.
        if jid in self._canceled:
            return "canceled"
        # The APPLY is the write unit — the model run above can take
        # minutes and holds no lease; what a concurrent process must not
        # interleave with is the result landing (files + rows + commit).
        with write_lease(self.lib.config.data_dir):
            msg = self._apply_result(s, job, item, result)
        if self._PROFILE:
            # The per-item path's split: decode on this side, the model
            # (its file in, its file back), the apply (the result encoded
            # losslessly and stored, rows, commit).
            t_end = time.perf_counter()
            print(f"[job-profile] {job.kind} item took {(t_end - t_start) * 1000:.0f} ms: "
                  f"decode {(t_decoded - t_start) * 1000:.0f}, "
                  f"model {(t_answered - t_model) * 1000:.0f}, "
                  f"apply {(t_end - t_answered) * 1000:.0f}",
                  file=sys.stderr, flush=True)
        return msg

    def _apply_result(self, s, job, item, result) -> str:
        """Apply one finished model result to the library (no commit cadence
        of its own — the caller holds the write lease and this commits once)."""
        if job.kind == "bg_removal":
            msg = self._apply_bg(s, item, result)
        elif job.kind == "watermark_removal":
            msg = self._apply_watermark(s, item, result)
            # A box-driven removal inpainted the item's own `watermark` tag
            # boxes. With the watermark now gone from the item, flip that tag
            # from a positive to a negative assignment so it no longer claims
            # the item has a watermark.
            if result is not None and job.model.endswith(":boxes"):
                self._flip_watermark_tag_negative(s, item)
        elif job.kind == "text_removal":
            msg = self._apply_text(s, item, result)
        elif job.kind == "upscale":
            msg = self._apply_upscale(s, item, result)
        elif job.kind == "restore":
            msg = self._apply_restore(s, item, result)
        elif job.kind == "colorize":
            msg = self._apply_colorize(s, item, result)
        elif job.kind == "descreen":
            msg = self._apply_descreen(s, item, result)
        elif job.kind == "caption":
            msg = self._apply_caption(s, item, result or "", job.model)
        elif job.kind == "tag":
            msg = self._apply_tags(s, item, result or [], job.model)
        elif job.kind in ("depth", "pose", "canny", "lineart"):
            msg = self._apply_artifact(s, item, result, job.kind, job.model)
        elif job.kind == "panels":
            msg = self._apply_panels(
                s, item, result or [], job.model,
                into_sequence=bool(
                    self._job_options(job).get("into_sequence")))
        elif job.kind == "faces":
            msg = self._apply_faces(s, item, result or [], job.model)
        elif job.kind == "ocr":
            msg = self._apply_ocr(s, item, result or [], job.model)
        elif job.kind == "watermark_detect":
            n = self._apply_watermark_tag(
                s, item, (result or {}).get("regions") or [])
            msg = (f"tagged {n} watermark box(es)" if n
                   else "no watermark found")
        else:
            raise RuntimeError(f"unknown job kind {job.kind!r}")
        s.commit()
        return msg

    def _run_video_edit(self, s, job, jid: int) -> str:
        """Render this item's cutlist into a new video file.

        The progress it reports is ffmpeg's own `out_time` against the length
        the edit will be — the only honest source, since a re-encode's speed
        depends on the material. The cancel is the queue's usual cooperative
        one, checked between ffmpeg's progress lines rather than between
        items: a render is ONE long step, so a cancel that only landed between
        jobs would be a button that does nothing for ten minutes.
        """
        from media_compost.ops.context import Ctx
        from .ops.video import plan_from_options, render_edit

        opts = self._job_options(job)
        plan = plan_from_options(opts)
        ctx = Ctx(session=s, _store=self.lib.store, _config=self.lib.config,
                  source="web", username=job.username or "")
        self._set_progress(jid, 0, "Rendering video…")
        last = [0]

        def on_progress(fraction: float) -> None:
            pct = int(max(0.0, min(1.0, fraction)) * 100)
            # Only on a real change: this fires several times a second and each
            # write is its own transaction.
            if pct != last[0]:
                last[0] = pct
                self._set_progress(jid, pct, "Rendering video…")

        try:
            res = render_edit(ctx, job.item_id, plan,
                              new_item=bool(opts.get("new_item")),
                              on_progress=on_progress,
                              should_cancel=lambda: jid in self._canceled)
        except media.Canceled:
            # Nothing was attached and the part-written file is gone, so this
            # is a clean stop rather than a failure.
            s.rollback()
            return "canceled"
        s.commit()
        return ("Saved as a new item" if res.get("new_item")
                else "Saved as a new file")

    def _run_stills(self, s, job, jid: int) -> str:
        """Take a still every N seconds across a film, or across a range of it.

        COMMITTED PER STILL, which is why the loop is here rather than in
        `ops/video.py`: an op may not commit, and one transaction around a
        run of hundreds would hold the write lock for the whole of it and
        lose every still if the last one failed. Committing as it goes also
        makes the cancel mean the useful thing — what has already been taken
        STAYS, because a still is an item somebody asked for, not a partial
        artifact like a half-rendered video.
        """
        from media_compost.ops.context import Ctx
        from media_compost.ops.errors import OpError
        from .ops.video import capture_frame, every_n_moments

        opts = self._job_options(job)
        ctx = Ctx(session=s, _store=self.lib.store, _config=self.lib.config,
                  source="web", username=job.username or "")
        try:
            times = every_n_moments(
                ctx, job.item_id, every=float(opts.get("every") or 0),
                start=float(opts.get("start") or 0.0),
                end=(None if opts.get("end") in (None, "")
                     else float(opts["end"])))
        except OpError as exc:
            raise RuntimeError(str(exc)) from exc
        total = len(times)
        if not total:
            return "no frames in that range"
        created = adopted = 0
        for i, t in enumerate(times):
            if jid in self._canceled:
                s.commit()
                return "canceled"
            self._set_progress(jid, int(i * 100 / total),
                               f"Taking stills — {i + 1} / {total}")
            _new_id, is_new = capture_frame(ctx, job.item_id, t)
            if is_new:
                created += 1
            else:
                adopted += 1
            # Per still: see the docstring. `_set_progress` opens its own
            # session, so this also keeps that one from queueing behind a
            # transaction that lasts the whole run.
            s.commit()
        if adopted:
            return f"{created} new stills, {adopted} already in the library"
        return f"{created} stills"

    def _run_registered(self, s, job, jid: int, run) -> str:
        """A job kind whose work lives above the queue (`register_runner`).

        The `Ctx` is built HERE, with the same attribution every other job
        gets: what a registered module hands over is the work, not a second
        idea of who is asking. Progress and the cooperative cancel are the
        queue's too, passed in as callables so the work knows nothing about
        being a job.
        """
        from media_compost.ops.context import Ctx
        from media_compost.ops.errors import OpError

        ctx = Ctx(session=s, _store=self.lib.store, _config=self.lib.config,
                  source="web", username=job.username or "")
        try:
            return run(ctx, self.lib, self._job_options(job),
                       progress=lambda pct, msg: self._set_progress(
                           jid, pct, msg),
                       stopped=lambda: jid in self._canceled)
        except OpError as exc:
            raise RuntimeError(str(exc)) from exc

    # A reasonable number of images to hand the model per forward pass in a
    # multi-item tag job: large enough to amortise per-call overhead, small
    # enough to bound memory and keep progress/cancellation responsive.
    #: How many items one model call covers — the GPU batch AND the number
    #: of pictures decoded at once.
    #:
    #: Eight is the default because it is what fits everywhere, and it is the
    #: one number here that cannot be chosen from this side: a batch is VRAM,
    #: and a 32 GB card running a face detector will take four times this
    #: while a laptop's will not. `MEDIA_COMPOST_BATCH_SIZE` is the way to
    #: say so — raising it makes the model's own forward more efficient and
    #: gives the worker's decode threads more to do at once, and getting it wrong is an
    #: out-of-memory error from the model rather than anything subtle.
    _TAG_BATCH = max(1, int(os.environ.get("MEDIA_COMPOST_BATCH_SIZE") or 8))

    #: Kinds whose batch is not that number, because their model is not that
    #: size. `embed` runs a ViT-S/B over pictures already thumbnailed to
    #: 512 px and processed down to ~224², so its whole batch is a rounding
    #: error next to a detector's — and indexing a library is exactly the run
    #: whose cost is per-call overhead rather than per-pixel work.
    #: `MEDIA_COMPOST_EMBED_BATCH` says otherwise.
    #:
    #: `faces` takes sixteen: both detectors are small on a card and their
    #: cost per call is CPU work around the forward (a letterbox, a
    #: post-process, the descriptor call, the pipeline's own round trip), so
    #: a chunk of eight ran the 5090 box at 83 items/s, sixteen at 103 and
    #: thirty-two at 107 — and a chunk is decoded at 2048 px, 16 MB a
    #: picture RGBA, twice over (this chunk and the next prefetched), so
    #: sixteen is half a gigabyte in the worker where thirty-two is one.
    #: `MEDIA_COMPOST_FACES_BATCH` says otherwise.
    #:
    #: `tag` takes sixteen too: the WD tagger is a ViT-L over 448 px inputs
    #: whose forward is the whole cost on a card — 34 items/s at eight, 43
    #: at sixteen, 47 at thirty-two on the 5090 box (the card at 87% by
    #: sixteen) — and a chunk's inputs are 2.4 MB a picture, so thirty-two
    #: would be a real slice of a small card's memory for the last few
    #: percent. `MEDIA_COMPOST_TAG_BATCH` says otherwise.
    _KIND_BATCH = {
        "embed": max(1, int(os.environ.get("MEDIA_COMPOST_EMBED_BATCH") or 256)),
        "faces": max(1, int(os.environ.get("MEDIA_COMPOST_FACES_BATCH") or 16)),
        "tag": max(1, int(os.environ.get("MEDIA_COMPOST_TAG_BATCH") or 16)),
        "caption": max(1, int(os.environ.get("MEDIA_COMPOST_CAPTION_BATCH") or 16)),
    }

    def _batch_for(self, kind: str) -> int:
        """How many items one model call of this kind covers.

        ONE for everything else, which is not a degenerate case but the
        ordinary one: a kind outside `_MODEL_BATCH_KINDS` still runs its
        whole selection as a single JOB, one item at a time through the warm
        host — so its chunk boundary is every item, and that is what the
        progress endpoint means by "the chunk that is running".
        """
        if kind not in self._MODEL_BATCH_KINDS:
            return 1
        return self._KIND_BATCH.get(kind, self._TAG_BATCH)

    #: EVERY kind runs a whole selection as ONE job, and these are the words
    #: each reports in. It used to be five — the kinds whose model call can
    #: cover a chunk of images — and everything else was one job PER ITEM, so
    #: captioning a hundred pictures was a hundred rows in the task list, each
    #: with a progress bar covering a hundredth of the run. "One job" and "one
    #: model call" are two different questions, and only the second has a
    #: per-kind answer (`_MODEL_BATCH_KINDS`); what a person asked for once
    #: should be one thing to watch, pause and cancel.
    #:
    #: Pressing the same action again still makes a SECOND job: `merge` is off
    #: by default and only an import passes it (see `enqueue`).
    _BATCH_KINDS = {"tag": ("Tagging", "tagged"),
                    "faces": ("Detecting faces", "found faces in"),
                    "ocr": ("Reading text", "read text in"),
                    "watermark_detect": ("Detecting watermarks",
                                         "found watermarks in"),
                    "embed": ("Indexing", "indexed"),
                    "caption": ("Captioning", "captioned"),
                    "bg_removal": ("Removing backgrounds",
                                   "removed the background from"),
                    "watermark_removal": ("Removing watermarks",
                                          "removed watermarks from"),
                    "text_removal": ("Removing text", "removed text from"),
                    "upscale": ("Upscaling", "upscaled"),
                    "restore": ("Cleaning artifacts", "cleaned"),
                    "colorize": ("Colorizing", "colorized"),
                    "descreen": ("Removing screen tones", "descreened"),
                    "panels": ("Splitting panels", "split panels from"),
                    "depth": ("Estimating depth", "estimated depth for"),
                    "pose": ("Estimating pose", "estimated pose for"),
                    "canny": ("Generating Canny edges", "generated edges for"),
                    "lineart": ("Estimating line art",
                                "estimated line art for")}

    #: Of those, the kinds whose MODEL CALL covers a chunk of images at once:
    #: they read a picture and write something small back onto it, with no
    #: per-item options to resolve first, so the host's batch entry point can
    #: take eight at a time. Everything else runs item by item inside the same
    #: job — its per-item work is genuinely per item (a watermark removal
    #: reads THIS item's boxes, a text removal THIS item's regions, panels
    #: walks THIS sequence's pages), and the model stays warm across them
    #: either way, which is where the saving actually was.
    #:
    #: `caption` joined them (2026-09): a captioner is a picture in, a
    #: string out, and with the model on a card the generate over a chunk
    #: is what makes it fast — Florence-2 base on the 5090 box captioned
    #: 1.1 pictures a second one at a time on the CPU it was pinned to.
    _MODEL_BATCH_KINDS = frozenset({"tag", "faces", "ocr",
                                    "watermark_detect", "embed", "caption"})

    #: And of THOSE, the kinds a sequence container is expanded into pages
    #: for. Tied to the model-batch set rather than to `_BATCH_KINDS`, which
    #: now holds every kind: `panels` reads every page too and must still
    #: take the container itself, and the image editors have never been
    #: offered on one. `SEQ_OK` in the frontend is this set plus `panels` —
    #: spelled out rather than aliased to `_MODEL_BATCH_KINDS`, because
    #: `caption` batches its model call and is NOT offered on a sequence.
    _EXPAND_SEQ_KINDS = frozenset({"tag", "faces", "ocr",
                                   "watermark_detect", "embed"})

    #: A batch kind whose ONLY path is `_run_item_batch`: it has no branch in
    #: `_apply_result`, and its batch path preprocesses in a way the
    #: single-item path would not (embed downscales to 512 px before the host
    #: IPC). A ONE-ITEM job of such a kind must therefore still be a BATCH
    #: job — as a per-item job it died with "unknown job kind", and had it not
    #: died it would have written a vector under the same `ItemEmbedding`
    #: space string from a different recipe, which that string is supposed to
    #: carry every constant of.
    _BATCH_ONLY_KINDS = frozenset({"embed"})

    def _job_ids(self, jid: int, fallback_item: int = 0) -> list[int]:
        """A batch job's item list, read FRESH in its own short session.

        Its own session because the list GROWS: an import merges each batch
        of files into the job already running (`enqueue(merge=True)`), and
        the worker's long-lived session would go on seeing the list as it
        was when the job started.
        """
        with self.lib.db.session() as s:
            job = s.get(Job, jid)
            raw = job.item_ids if job is not None else None
            try:
                ids = [int(x) for x in json.loads(raw or "[]")]
            except ValueError:
                ids = []
        # A one-item job of a batch-only kind that was ENQUEUED before that
        # rule existed: its `item_ids` is empty, and every other path for it
        # ends in "unknown job kind". The belt to `enqueue`'s brace, so a
        # queue written by an older build drains instead of failing.
        return ids or ([fallback_item] if fallback_item else [])

    def _run_item_batch(self, s, job, jid: int, ctx: dict) -> str:
        """Run one warm model over every item of a multi-item job, reporting
        progress as it goes — in chunks where the kind's model call takes one
        (`_MODEL_BATCH_KINDS`), item by item otherwise. Each chunk is committed
        before the next, so a mid-run cancel keeps the work already done — and
        so does a pause, which is the same boundary used deliberately."""
        fallback = (job.item_id if job.kind in self._BATCH_ONLY_KINDS else 0)
        ids = self._job_ids(jid, fallback)
        gerund, past = self._BATCH_KINDS.get(job.kind, ("Working", "handled"))
        # The suggestion pool — every user-named face, its descriptors, and
        # the claimed-face set — is loaded ONCE for the whole batch instead of
        # per item; `matcher.claim()` keeps it honest as suggestions land.
        matcher = SubjectMatcher.load(s) if job.kind == "faces" else None
        with self._batch_lock:
            self._mergeable.add(jid)
        try:
            return self._batch_loop(s, job, jid, ctx, ids, matcher,
                                    gerund, past, fallback)
        finally:
            with self._batch_lock:
                self._mergeable.discard(jid)

    #: `MEDIA_COMPOST_JOB_PROFILE=1` prints one line per chunk of a batch job
    #: to stderr — how long the main thread waited for the worker's answer,
    #: and the apply-and-commit — the worker adds its own line (what it waited
    #: for the decode, the plugin call) and the embed plugins their processor /
    #: forward split, all under the same variable. It is how the shape of an
    #: indexing run is read on a machine this repository cannot see.
    _PROFILE = bool(os.environ.get("MEDIA_COMPOST_JOB_PROFILE"))

    #: THE PIPELINE IS DRAINED EVERY THIS MANY CHUNKS. While a chunk is in
    #: flight the model host's lock is held, so anything else wanting a model
    #: (the editor's detect-regions, an inpaint) waits; between two chunks
    #: that are both submitted there is no gap at all. Every few chunks the
    #: loop collects and applies what is out, which gives the lock back for
    #: an instant — one bubble of the worker's idle per window, against a
    #: wait bounded by a window's length rather than the job's.
    _PIPELINE_WINDOW = 8

    def _batch_loop(self, s, job, jid, ctx, ids, matcher,
                    gerund, past, fallback) -> str:
        """Item by item until the list runs out — and the list can GROW under
        it, so "how many are there" is asked again at every boundary rather
        than counted once at the start.

        The boundary between two chunks is the one place this job can be
        interrupted, and all three interruptions use it: a cancel stops and
        keeps what is committed, a pause does the same and writes the cursor
        down, and an append (an import's next batch of files) is simply seen
        by the next read.

        THE MODEL NEVER WAITS FOR THE DATABASE, AND THE DECODE NEVER WAITS
        FOR THE MODEL. A chunk is three legs in two processes — decode,
        forward, apply-and-commit — and run in turn they left an RTX 5090 at
        a third and a 32-core box at a fifth (reported): the GPU idle for the
        decode and the commit, the cores idle for the forward, and the
        pictures crossing the boundary as files the host wrote and the
        worker read again. So the loop is a PIPELINE: the worker decodes
        the library's own files (`ModelHost.submit_paths`), told with each
        chunk which paths come NEXT so their decode overlaps this chunk's
        forward; and the host submits chunk N+1 BEFORE it applies chunk N,
        so its writes overlap the worker's forward. At most two chunks are
        out at once. Measured on the 5090 box over the crawl library: see
        the commit that made it.

        THE PER-ITEM KINDS RIDE THE SAME PIPELINE, a chunk of one: their
        picture goes to the worker by path with THAT item's options
        (`_item_options`) and comes back as a file the host reads, and the
        apply — the lossless encode and store of a full-size result, 70 to
        130 ms a picture, the widest leg of every picture-producing kind
        once its model ran on a card — overlaps the next item's model call.
        Two cases stay sequential through `_run_one_item` (`_sequential`):
        panels over a sequence container, which walks the pages itself, and
        a text removal that must READ the page with an OCR engine first — a
        second model, whose worker would replace the inpainter's mid-flight.
        """
        done = int(job.done_count or 0)   # applied and committed
        sent = done                       # handed to the model
        hits = 0
        total = len(ids)
        # (batch length in ids, chunk items, handle): the chunk the model is
        # answering, applied once the NEXT one is on its way.
        pending: tuple[int, list, object] | None = None
        # The next chunk's items and paths, resolved a turn early so they
        # can be named as the worker's prefetch.
        ahead: tuple[list[int], list, list] | None = None
        turns = 0
        while True:
            with self._batch_lock:
                ids = self._job_ids(jid, fallback)
                total = len(ids)
                if sent >= total:
                    # Nothing left AND nothing may be added from here on: the
                    # discard and this decision are one step, or an import
                    # batch landing in between would be lost.
                    self._mergeable.discard(jid)
                    break
            if jid in self._canceled or jid in self._paused:
                break
            width = self._batch_for(job.kind)
            batch_ids = ids[sent:sent + width]
            # This chunk: resolved a turn ago where the list has not moved
            # under it, now otherwise (the first chunk, an append).
            if ahead is not None and ahead[0] == batch_ids:
                chunk, paths = ahead[1], ahead[2]
            else:
                chunk, paths = self._chunk_paths(s, batch_ids)
            sent += len(batch_ids)
            nxt = ids[sent:sent + width]
            ahead = (nxt, *self._chunk_paths(s, nxt)) if nxt else None
            t0 = time.perf_counter()
            handle = self._submit_chunk(s, job, jid, ctx, chunk, paths,
                                        ahead[2] if ahead else [])
            if pending is not None:
                done, hits = self._finish_chunk(s, job, jid, matcher, pending,
                                                done, hits, gerund, total,
                                                t0)
            pending = (len(batch_ids), chunk, handle)
            turns += 1
            if turns % self._PIPELINE_WINDOW == 0:
                # The window's end: nothing in flight for an instant, so a
                # caller waiting on the model host gets its turn.
                done, hits = self._finish_chunk(s, job, jid, matcher, pending,
                                                done, hits, gerund, total,
                                                time.perf_counter())
                pending = None
        if pending is not None:
            # What the model already answered is applied whatever ended the
            # loop — a cancel keeps finished work, a pause resumes after it —
            # except a per-item kind's answer still IN FLIGHT at a cancel,
            # which is dropped (`_finish_item`).
            done, hits = self._finish_chunk(
                s, job, jid, matcher, pending, done, hits, gerund, total,
                time.perf_counter(),
                drop=(jid in self._canceled
                      and job.kind not in self._MODEL_BATCH_KINDS))
        if jid in self._canceled:
            return f"canceled after {past} {hits} of {total} items"
        if jid in self._paused:
            # The word `_run_job` reads to leave the row paused rather than
            # calling an unfinished run "done".
            return f"paused after {past} {hits} of {done} items"
        return f"{past} {hits} of {total} items"

    def _items(self, s, item_ids: list[int]) -> list:
        """The chunk's Item rows in the list's order, one query — a `get`
        per id was a round trip each at 256 a chunk. Deleted ids are simply
        absent."""
        if not item_ids:
            return []
        by_id = {it.id: it for it in s.execute(
            select(Item).where(Item.id.in_(item_ids))).scalars()}
        return [by_id[i] for i in item_ids if i in by_id]

    def _chunk_paths(self, s, item_ids: list[int]) -> tuple[list, list]:
        """(items, paths) for one chunk: where each item's active picture is
        on disk, resolved in ONE query over the chunk's active files rather
        than a `get` of the file and one of the item apiece. An item with no
        stored picture (a container, a file row without bytes) gets None,
        which the worker answers as that slot's error — the run goes on."""
        chunk = self._items(s, item_ids)
        fids = [it.active_file_id for it in chunk if it.active_file_id is not None]
        where: dict[int, str] = {}
        if fids:
            for fid, rel, uid in s.execute(
                    select(File.id, File.path, Item.uid)
                    .join(Item, Item.id == File.item_id)
                    .where(File.id.in_(fids))):
                if rel:
                    where[fid] = str(self.lib.store.file_path(uid, rel))
        return chunk, [where.get(it.active_file_id) for it in chunk]

    def _sequential(self, job, item) -> bool:
        """Whether this item must take the old sequential path
        (`_run_one_item`): the ones whose work is not one model call over
        one picture."""
        if job.kind == "panels" and item.kind == "sequence":
            return True
        if job.kind == "text_removal" and not job.model.endswith(":boxes") \
                and str(self._job_options(job).get("detect_with") or ""):
            return True
        return False

    def _item_options(self, s, job, item) -> dict:
        """The per-item options a single-picture kind sends with ITS
        picture — the same three `_run_one_item` resolves."""
        options: dict = {}
        # The "use tagged boxes" watermark model skips detection and inpaints
        # the item's own "watermark" tag boxes instead.
        if job.kind == "watermark_removal" and job.model.endswith(":boxes"):
            options["boxes"] = self._watermark_boxes(s, item)
        # Text removal paints out what the library has READ (see
        # `_run_one_item` for the whole rule); the ":boxes" variant paints
        # the configured text tag's boxes instead.
        if job.kind == "text_removal":
            if job.model.endswith(":boxes"):
                options["quads"] = self._tag_box_quads(
                    s, item, prefs.read_text_tag(s))
            else:
                options["quads"] = self._text_region_quads(s, item)
        # A reference-guided colorization carries its reference image's id
        # in the job options; resolve it to a path the worker can open.
        if job.kind == "colorize":
            ref = self._job_options(job).get("reference", "")
            if ref:
                path = self.lib.config.refs_dir / os.path.basename(str(ref))
                if path.is_file():
                    options["reference"] = str(path)
        return options

    def _submit_chunk(self, s, job, jid, ctx: dict, chunk: list, paths: list,
                      prefetch: list):
        """Hand one chunk to the model host and return its handle. The real
        host takes PATHS and answers later (`submit_paths`); a host without
        that door (the tests' stand-ins) is fed decoded pictures through its
        `run_batch` right here, behind the same handle.

        A per-item kind's chunk is ONE item: its picture goes out with its
        own options and comes back as a picture (`images=True`), unless it
        is one of the `_sequential` cases — those run and apply right here,
        through `_run_one_item`, and the handle only carries the outcome.
        """
        submit = getattr(self.lib.model_host, "submit_paths", None)
        max_dim = self._max_dim(job.kind)
        if job.kind in self._MODEL_BATCH_KINDS:
            if callable(submit):
                return submit(job.kind, job.model, paths, ctx, max_dim=max_dim,
                              prefetch=prefetch)
            return _SyncBatch(self, job, paths, ctx, max_dim)
        if not chunk:
            return _Applied(None)
        item = chunk[0]
        if not callable(submit) or self._sequential(job, item):
            # A failure here is ONE item's, not the run's: a selection of
            # two hundred must not end on the one picture something could
            # not open, which is the rule the panels page walk already
            # follows.
            try:
                return _Applied(self._run_one_item(s, job, item, jid, ctx))
            except Exception as exc:  # noqa: BLE001 - per-item resilience
                s.rollback()
                print(f"{job.kind} failed for item {item.id}: {exc}",
                      file=sys.stderr)
                return _Applied(None, failed=True)
        try:
            options = self._item_options(s, job, item)
        except Exception as exc:  # noqa: BLE001 - per-item resilience
            s.rollback()
            print(f"{job.kind} failed for item {item.id}: {exc}", file=sys.stderr)
            return _Applied(None, failed=True)
        return submit(job.kind, job.model, paths[:1], ctx, max_dim=max_dim,
                      prefetch=prefetch, options=options, images=True)

    def _finish_item(self, s, job, jid, pending, done, hits, gerund, total,
                     t_wait, drop: bool = False) -> tuple[int, int]:
        """A per-item kind's chunk of one, collected and applied — or, for a
        `_sequential` item, already applied. ``drop``: the answer is
        collected and thrown away — the loop's rule for the item still IN
        FLIGHT when a cancel breaks it (nothing has been written yet, so this
        is a clean cancel with no partial output, as `_run_one_item` keeps
        it). An item finished inside the loop is applied even if a cancel
        landed meanwhile: its model call was over before the next item was
        even sent, and finished work is what a cancel keeps."""
        n, chunk, handle = pending
        t_apply = time.perf_counter()
        if isinstance(handle, _Applied):
            if not handle.failed:
                hits += 1
        else:
            item = chunk[0]
            try:
                results = handle.result()
                errors = getattr(handle, "errors", ())
                if errors:
                    raise RuntimeError(errors[0][1])
                if drop:
                    results = None
                else:
                    t_apply = time.perf_counter()
                    # The APPLY is the write unit — the model run held no
                    # lease; what a concurrent process must not interleave
                    # with is the result landing (files + rows + commit).
                    with write_lease(self.lib.config.data_dir):
                        self._apply_result(s, job, item, results[0])
                    hits += 1
            except Exception as exc:  # noqa: BLE001 - per-item resilience
                s.rollback()
                print(f"{job.kind} failed for item {item.id}: {exc}",
                      file=sys.stderr)
        done += n
        if self._PROFILE:
            t_end = time.perf_counter()
            print(f"[job-profile] {job.kind} item: "
                  f"wait {(t_apply - t_wait) * 1000:.0f} ms, "
                  f"apply {(t_end - t_apply) * 1000:.0f} ms",
                  file=sys.stderr, flush=True)
        self._set_progress(jid, int(done * 100 / total) if total else 100,
                           f"{gerund} — {done} / {total} items", done=done)
        return done, hits

    def _finish_chunk(self, s, job, jid, matcher, pending, done, hits,
                      gerund, total, t_wait, drop: bool = False) -> tuple[int, int]:
        """Collect one chunk's answer and write it down: the apply-and-commit
        under the write lease, then the cursor. Returns (done, hits)."""
        if job.kind not in self._MODEL_BATCH_KINDS:
            return self._finish_item(s, job, jid, pending, done, hits, gerund,
                                     total, t_wait, drop=drop)
        n, chunk, handle = pending
        results = handle.result()
        t_apply = time.perf_counter()
        for k, err in getattr(handle, "errors", ()):
            if k < len(chunk):
                print(f"{job.kind} failed for item {chunk[k].id}: {err}",
                      file=sys.stderr)
        # The apply-and-commit is the write unit; the model batch ran
        # leaseless, exactly like the single-item path.
        with write_lease(self.lib.config.data_dir):
            # The chunk's existing embedding rows in ONE read, for the
            # upsert below: a select per item was a third of what an embed
            # chunk cost after the model had answered.
            rows = (self._embedding_rows(s, [it.id for it in chunk])
                    if job.kind == "embed" else None)
            for it, res in zip(chunk, results):
                if job.kind == "faces":
                    msg = self._apply_faces(s, it, res or [], job.model,
                                            matcher=matcher)
                    if msg != "no faces detected":
                        hits += 1
                elif job.kind == "ocr":
                    # No matcher analogue: a string needs no clustering,
                    # threshold or exemplar pool.
                    msg = self._apply_ocr(s, it, res or [], job.model)
                    if msg != "no text detected":
                        hits += 1
                elif job.kind == "watermark_detect":
                    if self._apply_watermark_tag(
                            s, it, (res or {}).get("regions") or []):
                        hits += 1
                elif job.kind == "embed":
                    if self._apply_embedding(s, it, res, rows):
                        hits += 1
                elif job.kind == "caption":
                    if res is not None:
                        msg = self._apply_caption(s, it, res or "", job.model)
                        if msg not in _WARNING_MESSAGES:
                            hits += 1
                else:
                    msg = self._apply_tags(s, it, res or [], job.model)
                    if not (msg.startswith("no tags") or msg == "tags already present"):
                        hits += 1
            s.commit()
        done += n
        if self._PROFILE:
            t_end = time.perf_counter()
            print(f"[job-profile] {job.kind} chunk of {len(chunk)}: "
                  f"wait {(t_apply - t_wait) * 1000:.0f} ms, "
                  f"apply+commit {(t_end - t_apply) * 1000:.0f} ms",
                  file=sys.stderr, flush=True)
        self._set_progress(jid, int(done * 100 / total) if total else 100,
                           f"{gerund} — {done} / {total} items", done=done)
        return done, hits

    def _run_model_batch(self, kind: str, model: str, images: list, ctx: dict,
                         options: dict | None = None) -> list:
        """Run ``model`` over several images with a single warm load, returning one
        result per image (same order). Uses the ModelHost's batch entry point when
        it exposes one, else warm per-image runs (the model stays resident either
        way)."""
        batch = getattr(self.lib.model_host, "run_batch", None)
        if callable(batch):
            return batch(kind, model, images, ctx, options or {})
        return [self.lib.model_host.run(kind, model, im, ctx, options or {})
                for im in images]

    def _load_settings(self) -> dict:
        """The per-model local path overrides from the settings store."""
        with self.lib.db.session() as s:
            raw = get_setting(s, "model_paths", "")
        try:
            data = json.loads(raw) if raw else {}
        except ValueError:
            data = {}
        return data if isinstance(data, dict) else {}

    def _tag_box_rects(self, s, item: Item, name: str) -> list:
        """Every stored box of ``name`` on ``item``, as (x, y, w, h)."""
        tag = s.execute(select(Tag).where(Tag.name == name)).scalars().first()
        if tag is None:
            return []
        it = s.execute(select(ItemTag).where(
            ItemTag.item_id == item.id, ItemTag.tag_id == tag.id)).scalars().first()
        if it is None:
            return []
        out: list = []
        for p in s.execute(select(ItemTagPlacement).where(
                ItemTagPlacement.item_tag_id == it.id)).scalars().all():
            for b in s.execute(select(ItemTagBox).where(
                    ItemTagBox.placement_id == p.id)).scalars().all():
                if b.x is not None:
                    out.append((b.x, b.y, b.w, b.h))
        return out

    @staticmethod
    def _rect_iou(a, b) -> float:
        ax0, ay0, aw, ah = a
        bx0, by0, bw, bh = b
        ix = max(0.0, min(ax0 + aw, bx0 + bw) - max(ax0, bx0))
        iy = max(0.0, min(ay0 + ah, by0 + bh) - max(ay0, by0))
        inter = ix * iy
        union = aw * ah + bw * bh - inter
        return inter / union if union > 0 else 0.0

    def _add_detected_boxes(self, s, item: Item, name: str,
                            polys: list) -> int:
        """Record detected regions as boxes on ``name``, in the ACTIVE FILE's
        frame — the frame the model read. A region that (nearly) matches a
        box the tag already carries is skipped, so a re-run never piles up
        duplicates; a polygon that is just its own bounding box is stored as
        the plain rectangle it is.
        """
        from media_compost.ops import Ctx, tagassign

        have = self._tag_box_rects(s, item, name)
        # A detector's findings, so the boxes it draws are the machine's —
        # `ai`, like the `detect_*` events written beside them. They were
        # stamped `web`, which read in History as somebody drawing them.
        ctx = Ctx(session=s, _store=self.lib.store, _config=self.lib.config,
                  source="ai", username=str(s.info.get("username") or ""))
        added = 0
        for poly in polys:
            try:
                pts = [(float(q[0]), float(q[1])) for q in poly]
            except (TypeError, ValueError, IndexError):
                continue
            if len(pts) < 3:
                continue
            xs = [q[0] for q in pts]
            ys = [q[1] for q in pts]
            x0, y0 = min(xs), min(ys)
            w, h = max(xs) - x0, max(ys) - y0
            if w <= 0.001 or h <= 0.001:
                continue
            # In the ITEM's reference frame, which is what the stored boxes
            # are in — the dedup must compare like with like.
            rx, ry, rw, rh = tagassign._to_reference_frame(
                ctx, item.active_file_id, x0, y0, w, h)
            if any(self._rect_iou((rx, ry, rw, rh), b) >= 0.85 for b in have):
                continue
            rect_pts = {(x0, y0), (x0 + w, y0), (x0 + w, y0 + h),
                        (x0, y0 + h)}
            is_rect = (len(pts) == 4
                       and all(any(abs(px - qx) < 1e-6 and abs(py - qy) < 1e-6
                                   for qx, qy in rect_pts)
                               for px, py in pts))
            tagassign.add_box(ctx, item.id, name, x=x0, y=y0, w=w, h=h,
                              file_id=item.active_file_id,
                              points=None if is_rect else pts)
            have.append((rx, ry, rw, rh))
            added += 1
        if added:
            touch_items(s, [item.id])
        return added

    def _apply_watermark_tag(self, s, item: Item, regions: list) -> int:
        """The watermark-detect result: each found region becomes a box on
        the CONFIGURED watermark tag (Settings → Tagging) — exactly what the
        box-driven watermark removal consumes."""
        if not regions:
            return 0
        return self._add_detected_boxes(
            s, item, prefs.read_watermark_tag(s), regions)

    def _boxes_on_tag(self, s, item: Item, name: str) -> list:
        """Every box the item carries on the tag called ``name``.

        ONE reader for both box-driven removals: the watermark variant and
        the text one ask the same question of two CONFIGURED names (Settings
        → Tagging), and a second copy of this walk is how the two would come
        to disagree about which placements count.

        An empty ``name`` is "no such setting" and answers nothing — the text
        tag is optional, and a blank name must not fall through to matching
        the tag whose name is the empty string.
        """
        if not name:
            return []
        tag = s.execute(select(Tag).where(
            Tag.name == name)).scalars().first()
        if tag is None:
            return []
        it = s.execute(select(ItemTag).where(
            ItemTag.item_id == item.id, ItemTag.tag_id == tag.id)).scalars().first()
        if it is None:
            return []
        placements = s.execute(select(ItemTagPlacement).where(
            ItemTagPlacement.item_tag_id == it.id)).scalars().all()
        out: list = []
        for p in placements:
            out.extend(s.execute(select(ItemTagBox).where(
                ItemTagBox.placement_id == p.id)).scalars().all())
        return out

    def _watermark_boxes(self, s, item: Item) -> list:
        """The (x, y, w, h fraction) boxes of the CONFIGURED watermark tag
        (Settings → Tagging), for the box-driven watermark-removal variant.

        RECTANGLES even where the box is a polygon: the watermark plugin
        builds its mask from xyxy boxes, and `ItemTagBox`'s rectangle columns
        are that polygon's bounding box by construction — so a shape is
        widened rather than lost. The text variant below keeps the polygon,
        because its plugin takes one.
        """
        return [[b.x, b.y, b.w, b.h]
                for b in self._boxes_on_tag(
                    s, item, prefs.read_watermark_tag(s))]

    def _tag_box_quads(self, s, item: Item, name: str) -> list:
        """The boxes of the tag ``name`` as NORMALIZED POLYGONS — what the
        LaMa regions plugin's mask is drawn from.

        A box drawn round slanted text is stored as a polygon (`points`), and
        an upright rectangle over it paints out the art either side of the
        words — the very reason `_text_region_quads` carries quads rather
        than boxes. So the shape is kept where there is one and the
        rectangle's four corners stand in where there is not.
        """
        import json as _json

        quads: list = []
        for b in self._boxes_on_tag(s, item, name):
            pts = []
            if b.points:
                try:
                    pts = [[float(x), float(y)] for x, y in
                           _json.loads(b.points)]
                except (ValueError, TypeError):
                    pts = []
            quads.append(pts if len(pts) >= 3 else [
                [b.x, b.y], [b.x + b.w, b.y],
                [b.x + b.w, b.y + b.h], [b.x, b.y + b.h]])
        return quads

    #: Coarsest last — how fine a reading is, for `_text_region_quads`.
    _TEXT_LEVELS = ("char", "word", "line", "block")

    def _text_region_quads(self, s, item: Item) -> list:
        """The active file's text, as normalized polygons — the FINEST
        reading there is, at its smallest level.

        Two rules, and both of them are about not painting over the picture.

        **Per branch, the leaves.** A block box is a whole speech bubble and
        inpainting one repaints the art inside it, so where an engine broke
        the block down (RapidOCR gives per-word boxes) the leaves are what
        the mask is built from; a block with no breakdown contributes itself,
        because a coarse mask beats no removal.

        **Across engines, ONE of them — the finest.** Two engines' readings
        are two answers to the same question, and their union is as coarse as
        the coarser one: measured on a page both had read, Magi's block boxes
        covered the very lines RapidOCR had broken into words, so unioning
        threw the word boxes away in all but name. So the engine whose leaves
        reach the smallest LEVEL wins (ties go to the one seen first), and
        hand-drawn regions ride along with it whatever it is — somebody drew
        those on purpose.

        A DISMISSED region contributes nothing, at any level: "not text" is
        an answer, and painting over what somebody said is not text is the
        one thing the flag exists to prevent. A region with no quad falls
        back to its AABB — `quad == ""` means the box IS the shape.
        """
        from media_compost.db import TextRegion
        from media_compost import ocr as ocrlib

        rows = s.execute(
            select(TextRegion).where(
                TextRegion.item_id == item.id,
                TextRegion.file_id == item.active_file_id)
            .order_by(TextRegion.ord, TextRegion.id)
        ).scalars().all()
        kids: dict[int, list] = {}
        for r in rows:
            if r.parent_id is not None:
                kids.setdefault(r.parent_id, []).append(r)

        def shape(r) -> list:
            pts = ocrlib.unpack_quad(r.quad)
            if pts:
                return [[p[0], p[1]] for p in pts]
            return [[r.x, r.y], [r.x + r.w, r.y],
                    [r.x + r.w, r.y + r.h], [r.x, r.y + r.h]]

        def leaves(r) -> list:
            if r.dismissed:
                return []
            live = [c for c in kids.get(r.id, []) if not c.dismissed]
            if not live:
                return [r]
            out: list = []
            for c in live:
                out.extend(leaves(c))
            return out

        def fineness(rs) -> int:
            ranks = [self._TEXT_LEVELS.index(x.level)
                     for x in rs if x.level in self._TEXT_LEVELS]
            return min(ranks) if ranks else len(self._TEXT_LEVELS)

        # Group the top-level regions by the engine that read them (the first
        # credit, `regions.engineOf`'s rule — the same key the Text tab's
        # dropdown groups by, so what is painted out is a reading you can
        # actually select and look at). "" is hand-drawn.
        by_engine: dict[str, list] = {}
        for r in rows:
            if r.parent_id is not None:
                continue
            got = leaves(r)
            if got:
                key = (r.model or "").split(",")[0]
                by_engine.setdefault(key, []).extend(got)

        hand = by_engine.pop("", [])
        best: list = []
        if by_engine:
            best = min(by_engine.values(), key=fineness)
        return [shape(r) for r in best + hand]

    def _flip_watermark_tag_negative(self, s, item: Item) -> None:
        """Flip the item's ``watermark`` tag from a positive to a negative
        assignment (used after a box-driven in-place watermark removal, when the
        item is now watermark-free). No-op if the item has no watermark tag or it
        is already negative. Placements/boxes are left intact."""
        tag = s.execute(select(Tag).where(
            Tag.name == prefs.read_watermark_tag(s))).scalars().first()
        if tag is None:
            return
        it = s.execute(select(ItemTag).where(
            ItemTag.item_id == item.id, ItemTag.tag_id == tag.id
        )).scalars().first()
        if it is None or it.negative:
            return
        it.negative = True
        touch_items(s, [item.id])

    def _active_path(self, s, item: Item):
        """Where the item's active image is on disk. The DB half of
        `_active_image`, split out because a Session is not thread-safe and
        the DECODE is what a batch wants to do on several threads."""
        if item.active_file_id is None:
            raise RuntimeError("item has no active image")
        f = s.get(File, item.active_file_id)
        if f is None or not f.path:
            raise RuntimeError("active file is not a stored image")
        return self.lib.store.path_of(s, f)

    def _active_image(self, s, item: Item, max_dim: int = 0) -> Image.Image:
        return self._read_image(self._active_path(s, item), max_dim)

    #: How big a picture one KIND is worth sending to its model, longest side.
    #: 0 (everything not listed) is the original — a background removal or an
    #: upscale writes a file, so every pixel matters.
    #:
    #: The two listed kinds only ever LOOK at the picture, at a resolution
    #: they fix themselves, and what a big original costs them is the process
    #: boundary: an image crosses it as an uncompressed file, so a 24 MP page
    #: is ~96 MB written and read again per item, which dwarfs the forward.
    #:
    #: * `embed` — the processor resizes to ~224² anyway; 512 is a wide margin.
    #: * `faces` — BOTH detectors work at 640 (InsightFace's `det_size`,
    #:   YOLO's `imgsz`), so the detection itself is unchanged by this. What
    #:   it does touch is the descriptor: InsightFace warps its 112² crop out
    #:   of the array it was handed, so a face under ~6% of the frame's width
    #:   is now upscaled into that crop rather than downscaled. 2048 is the
    #:   generous end of that trade; `MEDIA_COMPOST_FACES_MAX_DIM=0` turns it
    #:   off for a library of very large pictures with very small faces.
    _MAX_DIM = {
        "embed": 512,
        "faces": max(0, int(os.environ.get("MEDIA_COMPOST_FACES_MAX_DIM")
                            or 2048)),
    }

    def _max_dim(self, kind: str) -> int:
        """The cap for one kind. Read the same way on BOTH paths — the batch
        loop and the single-item run — or a face detected alone would get a
        different descriptor from the same face detected in a batch."""
        return self._MAX_DIM.get(kind, 0)

    #: THE ONE DEFINITION of a model job's picture lives in the worker
    #: (`plugins/worker.py: read_image`), because that is where a batch job
    #: decodes now; the single-item path and the tests' stand-in host read
    #: through this name and get the same pixels.
    _read_image = staticmethod(read_image)

    def _add_derived_image(self, s, item: Item, out: Image.Image,
                           transform: str) -> None:
        """Store ``out`` as a new derived file — lossless, in whatever format
        holds it exactly (`media.encode_lossless`) — and make it the item's
        active source.

        THE RESULT LANDS ON THE ITEM THE ACTION RAN ON, always. Every one of
        these actions used to carry a "Create new item for result" toggle
        that put it in an item of its own instead, linked back and carrying a
        copy of the source's groups, tags and captions; the item it was run
        from is where a person looks for what an action did, and a second
        place to look for it (holding a copy of the organizing the original
        already had) is the kind of choice a library is better without.
        """
        ext, data = media.encode_lossless(out)
        digest = sha256_bytes(data)
        # The file this action ran on (for the edit lineage), captured before
        # the item's active file is repointed below.
        source_fid = item.active_file_id
        number = next_file_number(s, item.id)
        rel = self.lib.store.write_file(item.uid, number, ext, data=data)
        ckey, csig = color_signature(out)
        new_file = File(
            item_id=item.id, sha256=digest,
            phash=compute_phash_image(out.convert("RGB")),
            color_key=ckey, color_sig=csig,
            path=rel, number=number,
            width=out.width, height=out.height, bytes=len(data),
            format=ext, is_derived=True,
        )
        s.add(new_file)
        s.flush()
        # Action-generated files carry no imported-filename card (only true
        # imports do); the item name / edit lineage identify them instead —
        # this file is based on the file the action ran on.
        if source_fid is not None:
            source_file = s.get(File, source_fid)
            if source_file is not None:
                record_edit(s, item.id, source_file, new_file, transform)
        item.active_file_id = new_file.id
        index_file_metadata(s, self.lib.store, new_file)
        self.lib.store.drop_thumb(new_file.id)
        touch_items(s, [item.id])

    def _apply_bg(self, s, item: Item, out: Image.Image) -> str:
        self._add_derived_image(s, item, out, "bg")
        return "background removed"

    def _apply_watermark(self, s, item: Item, out) -> str:
        # The detector found no watermark — leave the item untouched.
        if out is None:
            return "no watermark detected"
        self._add_derived_image(s, item, out, "watermark")
        return "watermark removed"

    def _apply_text(self, s, item: Item, out) -> str:
        # Nothing had been read here (or every region was dismissed), so
        # nothing was painted out — the item is untouched, and saying so is
        # the whole answer.
        if out is None:
            return "no text found to remove"
        self._add_derived_image(s, item, out, "text")
        return "text removed"

    def _apply_upscale(self, s, item: Item, out) -> str:
        if out is None:
            return "no upscaled image produced"
        self._add_derived_image(s, item, out, "upscale")
        return "upscaled"

    def _apply_restore(self, s, item: Item, out) -> str:
        if out is None:
            return "no restored image produced"
        self._add_derived_image(s, item, out, "restore")
        return "artifacts removed"

    def _apply_colorize(self, s, item: Item, out) -> str:
        if out is None:
            return "no colorization produced"
        self._add_derived_image(s, item, out, "colorize")
        return "colorized"

    def _apply_descreen(self, s, item: Item, out) -> str:
        if out is None:
            return "no descreened image produced"
        self._add_derived_image(s, item, out, "descreen")
        return "screen tones removed"

    def _job_options(self, job) -> dict:
        """The job's stored options JSON as a dict (empty on absence/garbage)."""
        try:
            data = json.loads(job.options) if job.options else {}
        except ValueError:
            data = {}
        return data if isinstance(data, dict) else {}

    # Human labels for the auxiliary-artifact kinds (used in messages/logs).
    _ARTIFACT_LABEL = {"depth": "depth map", "pose": "pose", "canny": "edge map",
                       "lineart": "line art"}

    def _apply_artifact(self, s, item: Item, out, kind: str, model: str = "") -> str:
        """Store ``out`` (a PIL image) as an auxiliary artifact nested under the
        item's active source file. Produces nothing when the model returned no
        image (e.g. pose found no person)."""
        label = self._ARTIFACT_LABEL.get(kind, kind)
        if out is None:
            return f"no {kind} produced"
        if item.active_file_id is None:
            raise RuntimeError("item has no active image")
        ext, data = media.encode_lossless(out.convert("RGB"))
        digest = sha256_bytes(data)
        active = s.get(File, item.active_file_id)
        rel = self.lib.store.write_artifact(
            item.uid, active.number, kind, ext, data, model
        )
        from media_compost.ops import artifacts as ops_artifacts
        from media_compost.ops.context import ctx_for

        ops_artifacts.create(
            ctx_for(s, "ai", _store=self.lib.store, _config=self.lib.config),
            summary="AI {label} ({model})",
            summary_vars={"label": label, "model": registry.model_label(model)},
            file_id=item.active_file_id, kind=kind, model=model,
            sha256=digest, path=rel, width=out.width, height=out.height,
            bytes=len(data), format=ext,
        )
        return f"{label} added"

    def _panels_for_page(self, s, page: Item, boxes, model: str = "") -> list[int]:
        """Crop each detected panel of one page into its own item, linked from the
        panel back to the page. ``boxes`` are ``[x, y, w, h]`` fractions. For a
        panel whose bounding box overlaps a neighbour's (non-rectangular /
        diagonal panels), the parts of the crop that belong to the other panel are
        erased (transparent) via a nearest-panel-centre assignment over the
        overlap. A panel identical to an existing library file links from that
        item instead of creating a duplicate ("new or existing"). Returns the
        panel item ids, in panel (reading) order."""
        import numpy as np

        boxes = [b for b in (boxes or []) if b and len(b) == 4]
        if not boxes:
            return []
        src = self._active_image(s, page)   # RGBA
        W, H = src.size
        rects = []
        for (bx, by, bw, bh) in boxes:
            x0 = max(0, int(round(bx * W))); y0 = max(0, int(round(by * H)))
            x1 = min(W, int(round((bx + bw) * W))); y1 = min(H, int(round((by + bh) * H)))
            rects.append((x0, y0, x1, y1))
        centers = [((x0 + x1) / 2.0, (y0 + y1) / 2.0) for (x0, y0, x1, y1) in rects]
        base = page.name.rsplit(".", 1)[0]
        made_ids: list[int] = []
        for i, (x0, y0, x1, y1) in enumerate(rects):
            if x1 <= x0 or y1 <= y0:
                continue
            crop = src.crop((x0, y0, x1, y1)).convert("RGBA")
            # Erase overlapping neighbour panels: a crop pixel that also falls in
            # another panel's box and is closer to that panel's centre is masked.
            xs = np.arange(x0, x1) + 0.5
            ys = np.arange(y0, y1) + 0.5
            gx, gy = np.meshgrid(xs, ys)
            cix, ciy = centers[i]
            di2 = (gx - cix) ** 2 + (gy - ciy) ** 2
            mask_out = np.zeros(gx.shape, dtype=bool)
            for j, (jx0, jy0, jx1, jy1) in enumerate(rects):
                if j == i:
                    continue
                inside = (gx >= jx0) & (gx < jx1) & (gy >= jy0) & (gy < jy1)
                if not inside.any():
                    continue
                cjx, cjy = centers[j]
                dj2 = (gx - cjx) ** 2 + (gy - cjy) ** 2
                mask_out |= inside & (dj2 < di2)
            if mask_out.any():
                arr = np.array(crop)
                arr[..., 3][mask_out] = 0
                crop = Image.fromarray(arr, "RGBA")
            ext, data = media.encode_lossless(crop)
            digest = sha256_bytes(data)
            name = f"{base} — panel {i + 1}.{ext}"
            existing = s.execute(
                select(File).where(File.sha256 == digest)
            ).scalars().first()
            if existing is not None:
                target_id = existing.item_id
            else:
                target = Item(name=name)
                s.add(target)
                s.flush()
                rel_path = self.lib.store.write_file(target.uid, 1, ext,
                                                     data=data)
                ckey, csig = color_signature(crop)
                nf = File(item_id=target.id, sha256=digest,
                          phash=compute_phash_image(crop.convert("RGB")),
                          color_key=ckey, color_sig=csig,
                          path=rel_path,
                          number=1, width=crop.width, height=crop.height,
                          bytes=len(data), format=ext, is_derived=True)
                s.add(nf)
                s.flush()
                # A detected panel is action-generated: no imported-filename
                # card (the panel item's own name identifies it).
                target.active_file_id = nf.id
                index_file_metadata(s, self.lib.store, nf)
                self.lib.store.drop_thumb(nf.id)
                # A panel lands in the same groups as its page.
                for gid in s.execute(select(ItemGroup.group_id).where(
                        ItemGroup.item_id == page.id)).scalars().all():
                    s.add(ItemGroup(item_id=target.id, group_id=gid))
                target_id = target.id
            # The link points from the panel item to the originating page.
            dup = s.execute(select(Relationship).where(
                Relationship.from_item_id == target_id,
                Relationship.to_item_id == page.id,
                Relationship.kind == "panel",
            )).scalars().first()
            if dup is None:
                s.add(Relationship(
                    from_item_id=target_id, to_item_id=page.id, kind="panel",
                    meta=json.dumps({"index": i, "box": [round(v, 5) for v in boxes[i]]}),
                ))
            touch_items(s, [target_id])
            made_ids.append(target_id)
        if made_ids:
            touch_items(s, [page.id])
        return made_ids

    def _apply_faces(self, s, item: Item, found, model: str = "",
                     embedder: str = "", matcher: SubjectMatcher | None = None
                     ) -> str:
        """Record a run's faces, keeping every answer a person already gave.

        The detector returns boxes in the file's own frame; the record keeps
        them in the item's, which is the same frame here because a face is
        found in the ACTIVE file. Reconciliation (`faces.reconcile`) decides
        what is a fresh look at a known face and what is new — a face the run
        did not find is never touched, because a detector is not evidence of
        absence.
        """
        # Which SPACE this run's descriptors are in. A plugin may name its own
        # (an embedder that runs over another detector's boxes is the obvious
        # next one); otherwise the detector is also the embedder, which is true
        # of every plugin here today.
        embedder = embedder or next(
            (d["embedder"] for d in (found or []) if d.get("embedder")), model)
        detections = [
            facelib.Detected(
                box=(float(d["box"][0]), float(d["box"][1]),
                     float(d["box"][2]), float(d["box"][3])),
                score=float(d.get("score") or 0.0),
                embedding=(facelib.pack_embedding(d["embedding"])
                           if d.get("embedding") else None),
            )
            for d in (found or [])
        ]
        def on_record() -> list:
            # Which faces a PERSON has said something about, in one query.
            # Scoped to THIS item: the set is only ever tested against this
            # item's faces, and an appearance always lives on the same item as
            # the face it points at (every writer passes `face.item_id`).
            answered_ids = {
                fid for fid, in s.execute(
                    select(ItemSubject.face_id).where(
                        ItemSubject.item_id == item.id,
                        ItemSubject.face_id.is_not(None),
                        (ItemSubject.assigned_by == "user")
                        | ItemSubject.when_date.is_not(None)
                        | ItemSubject.when_age.is_not(None))
                ).all()
            }
            return [
                facelib.Known(
                    id=f.id, box=(f.x, f.y, f.w, f.h), dismissed=f.dismissed,
                    score=f.det_score or 0.0,
                    # An answer is a name given by hand, a dismissal, a face
                    # somebody drew, or a date typed onto one of its
                    # appearances — never a model's suggestion.
                    # `duplicates()` drops the unanswered box of a pair, so a
                    # face missing from this list is one a re-run can silently
                    # delete along with the work on it.
                    answered=(f.id in answered_ids or f.dismissed
                              or f.det_score is None),
                )
                for f in s.execute(
                    select(Face).where(Face.item_id == item.id)
                ).scalars().all()
            ]

        known = on_record()
        plan = facelib.reconcile(known, detections)

        from media_compost.ops.faces import box_edits_of
        edits = box_edits_of(s, list(plan.updated.keys()))
        for face_id, d in plan.updated.items():
            row = s.get(Face, face_id)
            if row is None:
                continue
            # A fresh look at the same face: its geometry and descriptor are
            # this run's, but who it is stays exactly as it was — and a box
            # somebody EDITED stays a person's answer: the run's rectangle
            # goes into the reset record instead, so "Reset the box" always
            # restores the newest detection while the edit survives the run.
            rec = edits.get(face_id)
            if rec is not None:
                rec.x, rec.y, rec.w, rec.h = d.box
            else:
                row.x, row.y, row.w, row.h = d.box
            row.det_score = d.score
            # Two detectors that both find a head agree about it; the merge is
            # the point (one box, not two), so the row remembers both rather
            # than letting whichever ran last claim it.
            seen = [m for m in row.model.split(",") if m]
            if model and model not in seen:
                seen.append(model)
            row.model = ",".join(seen)
            if d.embedding is not None:
                facelib.store_embedding(s, row.id, embedder, d.embedding)
        for d in plan.added:
            face = Face(item_id=item.id, file_id=item.active_file_id,
                        x=d.box[0], y=d.box[1], w=d.box[2], h=d.box[3],
                        det_score=d.score, model=model)
            s.add(face)
            if d.embedding is not None:
                s.flush()
                facelib.store_embedding(s, face.id, embedder, d.embedding)
        s.flush()
        # THAT this detector has now looked at this item, whatever it found.
        # `Face.model` cannot answer that: an item it found nothing in has no
        # face to carry the fact, and that is precisely the item a "skip what
        # is already done" sweep must not run again.
        if model:
            from media_compost.db import ItemFaceRun
            seen = s.execute(select(ItemFaceRun).where(
                ItemFaceRun.item_id == item.id, ItemFaceRun.model == model
            )).scalars().first()
            if seen is None:
                s.add(ItemFaceRun(item_id=item.id, model=model))
        # Rows an earlier run left doubled up on one face: dropped here rather
        # than left for the eye to sort out, since a run is exactly when the
        # library knows the boxes again.
        stale = facelib.duplicates(on_record())
        for face_id in stale:
            row = s.get(Face, face_id)
            if row is not None:
                s.delete(row)
        if stale:
            s.flush()
        named = suggest_subjects(s, item, matcher)
        touch_items(s, [item.id])

        n = len(plan.added)
        total = len(plan.updated) + n
        if total == 0:
            return "no faces detected"
        log_event(
            s, source="ai", action="detect_faces", entity_type="item",
            entity_id=item.id,
            summary=(("Detected 1 face" if total == 1 else "Detected {total} faces")
                     + (", {n} new" if n and plan.updated else "")),
            summary_vars={"total": total, "n": n},
            data={"item_id": item.id, "count": total, "added": n},
        )
        suffix = f", {named} named" if named else ""
        if plan.updated and not n:
            return f"{total} face{'s' if total != 1 else ''}, all known{suffix}"
        return f"{n} new face{'s' if n != 1 else ''}{suffix}"

    def _apply_ocr(self, s, item: Item, found, model: str = "") -> str:
        """Record a run's text regions, keeping every answer a person gave.

        `_apply_faces`' shape over `ocr.reconcile`, plus the tree: the wire
        payload is nested and LIST POSITION IS THE READING ORDER, so `ord` is
        assigned here from position — for matched regions too, since the
        engine's current reading order is its newest statement. (Two engines'
        ord sequences interleave in one sibling space; that is fine, because
        their regions never merge and the display groups by engine.)
        """
        from media_compost import ocr as ocrlib
        from media_compost.db import ItemTextRun, TextRegion

        def as_detected(d) -> ocrlib.Detected:
            quad = d.get("quad")
            return ocrlib.Detected(
                box=(float(d["box"][0]), float(d["box"][1]),
                     float(d["box"][2]), float(d["box"][3])),
                text=str(d.get("text") or ""),
                score=(float(d["score"]) if d.get("score") is not None
                       else None),
                quad=(ocrlib.pack_quad(quad) if quad else ""),
                lang=str(d.get("lang") or ""),
                level=str(d.get("level") or "block"),
                children=tuple(as_detected(c)
                               for c in (d.get("children") or [])),
            )

        detections = [as_detected(d) for d in (found or [])]

        def on_record() -> list:
            # The ACTIVE file's regions only: a reading is a fact about
            # pixels, so another file's reading is another partition and a
            # re-run must never merge with (or orphan the children of) what
            # an earlier file said.
            return [
                ocrlib.Known(
                    id=r.id, box=(r.x, r.y, r.w, r.h), level=r.level,
                    parent_id=r.parent_id,
                    models=frozenset(m for m in (r.model or "").split(",")
                                     if m),
                    text=r.text or "", score=r.score,
                    dismissed=bool(r.dismissed), edited=bool(r.edited),
                )
                for r in s.execute(
                    select(TextRegion).where(
                        TextRegion.item_id == item.id,
                        TextRegion.file_id == item.active_file_id)
                ).scalars().all()
            ]

        known = on_record()
        plan = ocrlib.reconcile(known, detections, model=model)

        # The plan's Detected objects are the run's own (reconcile never
        # copies them), so identity maps them back to their list positions.
        matched = {id(d): rid for rid, d in plan.updated.items()}
        added = {id(d): pid for pid, d in plan.added}
        n_added = 0
        n_top = 0

        def add_tree(parent_id, d: ocrlib.Detected, ord_: int) -> None:
            row = TextRegion(item_id=item.id, file_id=item.active_file_id,
                             parent_id=parent_id, level=d.level, ord=ord_,
                             x=d.box[0], y=d.box[1], w=d.box[2], h=d.box[3],
                             quad=d.quad, text=d.text, score=d.score,
                             lang=d.lang, model=model)
            s.add(row)
            s.flush()
            for i, c in enumerate(d.children):
                add_tree(row.id, c, i)

        def walk(dets, top: bool) -> None:
            nonlocal n_added, n_top
            for i, d in enumerate(dets):
                rid = matched.get(id(d))
                if rid is not None:
                    row = s.get(TextRegion, rid)
                    if row is None:
                        continue
                    if top:
                        n_top += 1
                    # A fresh look at the same region: geometry, quad, score,
                    # lang, order and the model credit are this run's — the
                    # TEXT only where nobody has answered (`plan.retext`).
                    row.x, row.y, row.w, row.h = d.box
                    row.quad = d.quad
                    row.ord = i
                    if d.score is not None:
                        row.score = d.score
                    if d.lang:
                        row.lang = d.lang
                    seen = [m for m in (row.model or "").split(",") if m]
                    if model and model not in seen:
                        seen.append(model)
                    row.model = ",".join(seen)
                    if rid in plan.retext:
                        row.text = d.text
                    walk(list(d.children), False)
                elif id(d) in added:
                    if top:
                        n_top += 1
                        n_added += 1
                    add_tree(added[id(d)], d, i)
                # else: collapsed by merge_detections, or a child under a
                # dismissed match — absorbed, nothing to write.

        walk(detections, True)
        for rid in plan.orphaned:
            row = s.get(TextRegion, rid)
            if row is not None:
                s.delete(row)  # the CASCADE takes its own children with it
        s.flush()
        # THAT this engine has now read this FILE, whatever it found — an
        # item it read nothing in has no region to carry the fact, and that
        # is precisely the item `skip_done` must not run again. Per file:
        # an edited file made active has no run and reads as never-read.
        if model:
            seen_run = s.execute(select(ItemTextRun).where(
                ItemTextRun.item_id == item.id,
                ItemTextRun.file_id == item.active_file_id,
                ItemTextRun.model == model
            )).scalars().first()
            if seen_run is None:
                s.add(ItemTextRun(item_id=item.id,
                                  file_id=item.active_file_id, model=model))
        # Rows an earlier run left doubled up: healed here, like faces.
        stale = ocrlib.duplicates(on_record())
        for rid in stale:
            row = s.get(TextRegion, rid)
            if row is not None:
                s.delete(row)
        if stale:
            s.flush()
        touch_items(s, [item.id])

        # THE OPTIONAL TEXT TAG (Settings → Tagging): a name set there means
        # every OCR run also records its top-level regions as boxes on that
        # tag. Slanted quads travel as polygons; the same near-duplicate
        # dedup as the watermark detector, so a re-run piles nothing up.
        text_tag = prefs.read_text_tag(s)
        if text_tag and n_top:
            polys: list = []
            for r in s.execute(select(TextRegion).where(
                    TextRegion.item_id == item.id,
                    TextRegion.file_id == item.active_file_id,
                    TextRegion.parent_id.is_(None),
                    TextRegion.dismissed.is_(False))).scalars().all():
                quad = ocrlib.unpack_quad(r.quad) if r.quad else []
                polys.append(quad if len(quad) == 4 else [
                    (r.x, r.y), (r.x + r.w, r.y),
                    (r.x + r.w, r.y + r.h), (r.x, r.y + r.h)])
            self._add_detected_boxes(s, item, text_tag, polys)

        if n_top == 0:
            return "no text detected"
        log_event(
            s, source="ai", action="detect_text", entity_type="item",
            entity_id=item.id,
            summary=(("Read 1 text block" if n_top == 1
                      else "Read {total} text blocks")
                     + (", {n} new" if n_added and n_added != n_top else "")),
            summary_vars={"total": n_top, "n": n_added},
            data={"item_id": item.id, "count": n_top, "added": n_added},
        )
        if not n_added:
            return f"{n_top} text block{'s' if n_top != 1 else ''}, all known"
        return f"{n_added} new text block{'s' if n_added != 1 else ''}"

    def _apply_panels(self, s, item: Item, boxes, model: str = "",
                      into_sequence: bool = False) -> str:
        """Single-page panel detection (see ``_panels_for_page``). With
        ``into_sequence`` the page's panels are also grouped into their own new
        sequence (each selected page gets its own)."""
        ids = self._panels_for_page(s, item, boxes, model)
        if not ids:
            return "no panels detected"
        n = len(ids)
        plural = "s" if n != 1 else ""
        if into_sequence:
            seq = self._build_panel_sequence(s, item, ids, 1)
            log_event(
                s, source="ai", action="detect_panels", entity_type="item",
                entity_id=item.id, summary=("Detected 1 panel → new sequence" if n == 1
                            else "Detected {n} panels → new sequence"),
                summary_vars={"n": n} if n != 1 else None,
                data={"item_id": item.id, "count": n, "sequence_id": seq.id},
            )
            return f"{n} panel{plural} → new sequence"
        log_event(
            s, source="ai", action="detect_panels", entity_type="item",
            entity_id=item.id, summary=("Detected 1 panel" if n == 1 else "Detected {n} panels"),
            summary_vars={"n": n} if n != 1 else None,
            data={"item_id": item.id, "count": n},
        )
        return f"{n} panel{plural} linked"

    def _only_pictures(self, s, item_ids: list[int]) -> list[int]:
        """Drop the items whose active file is a VIDEO.

        An item with NO active file is kept: that is a sequence container, and
        `panels` takes one deliberately (it walks the pages itself). What
        cannot be kept is a film, whose active file a model would try to open
        as an image.
        """
        if not item_ids:
            return item_ids
        from media_compost.config import VIDEO_EXTS

        fmt: dict[int, str | None] = {}
        for chunk in chunked(item_ids):
            for iid, active in s.execute(
                select(Item.id, File.format)
                .join(File, File.id == Item.active_file_id, isouter=True)
                .where(Item.id.in_(chunk))
            ).all():
                fmt[iid] = active
        return [iid for iid in item_ids if fmt.get(iid) not in VIDEO_EXTS]

    def _expand_sequences(self, s, item_ids: list[int]) -> list[int]:
        """Replace each sequence with its pages, keeping the order and dropping
        repeats.

        A batch kind reads an item's picture and writes something small back
        onto it, and a container item has no picture of its own — so asking for
        one over a sequence means asking for it over the sequence, page by page.
        `panels` is deliberately NOT one of these: it reads every page too, but
        collects the result into a single new sequence, so it takes the
        container itself and does the walking in `run_one`.

        A page already named alongside its sequence is not detected twice.
        """
        # One chunked (id, kind) sweep instead of a `s.get` per id; only the
        # sequences — rare in any selection — load their Item row, for the
        # page walk. Caller order and the skip rules are unchanged.
        kinds: dict[int, str] = {}
        for chunk in chunked(item_ids):
            kinds.update(s.execute(
                select(Item.id, Item.kind).where(Item.id.in_(chunk))
            ).all())
        out: list[int] = []
        seen: set[int] = set()
        for iid in item_ids:
            kind = kinds.get(iid)
            if kind is None:
                continue
            members = ([p.id for p in self._sequence_pages(s, s.get(Item, iid))]
                       if kind == "sequence" else [iid])
            for mid in members:
                if mid not in seen:
                    seen.add(mid)
                    out.append(mid)
        return out

    def _sequence_pages(self, s, seq_item: Item) -> list[Item]:
        """The ordered member pages of a sequence container item (skipping any
        member that owns no image or is itself a sequence).

        DISTINCT pages, first occurrence's order: a sequence may hold the
        same item at several positions (a book's repeated blank page), and
        every caller here is about running a MODEL over the pages — reading
        the same picture twice is the same answer at twice the price. (The
        batch kinds' `_expand_sequences` dedups across the whole selection
        for the same reason; this covers the panels walk, which takes the
        container and does its own walking.)"""
        seq = s.execute(
            select(Sequence).where(Sequence.item_id == seq_item.id)
        ).scalars().first()
        if seq is None:
            return []
        rows = s.execute(
            select(SequenceItem).where(SequenceItem.sequence_id == seq.id)
            .order_by(SequenceItem.position, SequenceItem.id)
        ).scalars().all()
        pages: list[Item] = []
        seen: set[int] = set()
        for r in rows:
            if r.item_id in seen:
                continue
            seen.add(r.item_id)
            it = s.get(Item, r.item_id)
            if it is not None and it.kind != "sequence" and it.active_file_id is not None:
                pages.append(it)
        return pages

    def _apply_panels_sequence(self, s, seq_item: Item, per_page, model: str = "") -> str:
        """Detect panels across every page of a sequence and collect them all into
        one new sequence, in reading order (page order, then panel order within a
        page). ``per_page`` is ``[(page_item, boxes), …]`` in page order."""
        ordered: list[int] = []
        seen: set[int] = set()
        pages_with_panels = 0
        for page, boxes in per_page:
            ids = self._panels_for_page(s, page, boxes, model)
            if ids:
                pages_with_panels += 1
            for tid in ids:
                if tid not in seen:
                    seen.add(tid)
                    ordered.append(tid)
        if not ordered:
            return "no panels detected"
        seq = self._build_panel_sequence(s, seq_item, ordered, pages_with_panels)
        log_event(
            s, source="ai", action="detect_panels", entity_type="item",
            entity_id=seq_item.id,
            summary="Detected {n} panels across {pages} pages → new sequence",
            summary_vars={"n": len(ordered), "pages": pages_with_panels},
            data={"item_id": seq_item.id, "count": len(ordered), "sequence_id": seq.id},
        )
        return f"{len(ordered)} panels across {pages_with_panels} pages → new sequence"

    def _build_panel_sequence(self, s, source_item: Item, ordered: list[int],
                              pages_with_panels: int) -> Sequence:
        """Collect ``ordered`` panel item ids into a new sequence named after
        ``source_item``, inheriting its groups and linking back to it (mirroring
        how each panel links to its page). Returns the new Sequence."""
        seq = Sequence(name=f"{source_item.name} — panels", kind="manual",
                       source_name=source_item.name)
        s.add(seq)
        s.flush()
        for pos, tid in enumerate(ordered):
            s.add(SequenceItem(sequence_id=seq.id, item_id=tid, position=pos))
            it = s.get(Item, tid)
            if it is not None and it.main_sequence_id is None:
                it.main_sequence_id = seq.id
        s.flush()
        container = ensure_container(s, seq)
        for gid in s.execute(select(ItemGroup.group_id).where(
                ItemGroup.item_id == source_item.id)).scalars().all():
            s.add(ItemGroup(item_id=container.id, group_id=gid))
        if not s.execute(select(Relationship).where(
            Relationship.from_item_id == container.id,
            Relationship.to_item_id == source_item.id,
            Relationship.kind == "panel",
        )).scalars().first():
            s.add(Relationship(
                from_item_id=container.id, to_item_id=source_item.id, kind="panel",
                meta=json.dumps({"panels": len(ordered), "pages": pages_with_panels}),
            ))
        touch_items(s, [container.id, source_item.id])
        return seq

    def _apply_caption(self, s, item: Item, text: str, model: str = "") -> str:
        text = (text or "").strip()
        if not text:
            return "no caption produced"
        dup = s.execute(select(Caption).where(
            Caption.item_id == item.id, Caption.text == text
        )).scalars().first()
        if dup is not None:
            return "caption already present"
        pos = (s.execute(
            select(func.coalesce(func.max(Caption.position), -1))
            .where(Caption.item_id == item.id)
        ).scalar_one()) + 1
        c = Caption(item_id=item.id, text=text, position=pos, pending=True,
                    model=model)
        s.add(c)
        s.flush()
        touch_items(s, [item.id])
        log_event(
            s, source="ai", action="add_caption", entity_type="item",
            entity_id=item.id, summary="AI caption “{text}” (pending)",
            summary_vars={"text": _snippet(text)},
            data={"item_id": item.id, "caption_id": c.id, "text": text},
        )
        return "caption added (pending)"

    def _pending_group(self, s, item: Item, name: str) -> ItemTagGroup:
        """The auto-managed pending group named ``name`` for this item, created
        on demand. Each tag-generation run uses a name derived from its model/
        mode, so results from different models/modes land in separate groups."""
        grp = s.execute(select(ItemTagGroup).where(
            ItemTagGroup.item_id == item.id, ItemTagGroup.system.is_(True),
            ItemTagGroup.name == name,
        )).scalars().first()
        if grp is None:
            pos = s.execute(
                select(func.count()).select_from(ItemTagGroup)
                .where(ItemTagGroup.item_id == item.id)
            ).scalar_one()
            grp = ItemTagGroup(item_id=item.id, name=name,
                               system=True, position=pos)
            s.add(grp)
            s.flush()
        return grp

    @staticmethod
    def _embedding_rows(s, item_ids: list[int]) -> dict:
        """Every stored vector of these items, keyed `(item_id, space)` — the
        chunk-wide read `_apply_embedding` upserts against."""
        if not item_ids:
            return {}
        out = {}
        for row in s.execute(select(ItemEmbedding).where(
                ItemEmbedding.item_id.in_(item_ids))).scalars():
            out[(row.item_id, row.model)] = row
        return out

    def _apply_embedding(self, s, item: Item, res, rows: dict | None = None) -> bool:
        """Upsert one item's feature vector — derived, regenerable data, so
        no history event and never a sidecar key (the face-descriptor rule).
        `file_id` records which pixels the vector describes: the row only
        COUNTS while it matches the item's active file, so an edited picture
        re-indexes instead of answering for pixels it no longer shows."""
        from . import itemvec

        if not isinstance(res, dict):
            return False
        space = str(res.get("space") or "")
        dim = int(res.get("dim") or 0)
        if not space or dim <= 0:
            return False
        # Either spelling of the vector: float16 bytes (base64, what both
        # embed plugins send now — the stored precision exactly) or the
        # older list of floats, packed to the same bytes.
        raw = res.get("vector_f16")
        if isinstance(raw, str) and raw:
            import base64
            try:
                packed = base64.b64decode(raw)
            except ValueError:
                return False
            if len(packed) != dim * 2:
                return False
        else:
            vec = res.get("vector")
            if not vec or len(vec) != dim:
                return False
            packed = itemvec.pack(vec)
        row = (rows.get((item.id, space)) if rows is not None
               else s.execute(
                   select(ItemEmbedding).where(ItemEmbedding.item_id == item.id,
                                               ItemEmbedding.model == space)
               ).scalars().first())
        if row is None:
            row = ItemEmbedding(item_id=item.id, model=space)
            s.add(row)
            if rows is not None:
                rows[(item.id, space)] = row
        row.file_id = item.active_file_id
        row.dim = dim
        row.vector = packed
        return True

    def _apply_tags(self, s, item: Item, results: list, model: str = "") -> str:
        # `results` are plain dicts from the model worker: {"name", "box": [x,y,w,h]
        # | None}. Collect each generated tag with ALL of its boxes: a model may
        # emit the same label several times, each with its own bounding box — keep
        # them all on the one tag instead of dropping the extras.
        by_name: dict[str, list] = {}
        order: list[str] = []
        for r in results:
            raw = (r.get("name") or "").strip()
            if not raw:
                continue
            # Tag names never contain spaces (the app's convention); collapse any
            # whitespace in a model's label into underscores.
            name = "_".join(raw.lower().split())
            if name not in by_name:
                by_name[name] = []
                order.append(name)
            if r.get("box") is not None:
                by_name[name].append(tuple(r["box"]))
        if not order:
            return "no tags produced"
        from media_compost.ops import Ctx, tagassign

        grp = self._pending_group(s, item, f"Pending: {registry.model_label(model)}")
        ctx = Ctx(session=s, _store=self.lib.store, _config=self.lib.config,
                  source="ai", username=str(s.info.get("username") or ""))
        # THE LOOKUPS ARE PER PICTURE, NOT PER TAG, AND SO ARE THE FLUSHES. A
        # tagger answers forty tags a picture, and this used to be three
        # selects and up to two flushes for each — every flush a pass of the
        # session's listeners over everything dirty — 40 ms a picture on the
        # 5090 box, a ceiling of 25 items/s with an instant model. Now: the
        # tags by name in one query, the item's assignments in one, this
        # group's placements in one; the new tags flushed together, the new
        # assignments together, the new placements together.
        by_tag_name: dict[str, Tag] = {}
        for chunk in chunked(order):
            for tag in s.execute(select(Tag).where(Tag.name.in_(chunk))).scalars():
                by_tag_name[tag.name] = tag
        fresh_tags = [Tag(name=n) for n in order if n not in by_tag_name]
        if fresh_tags:
            s.add_all(fresh_tags)
            s.flush()
            for tag in fresh_tags:
                by_tag_name[tag.name] = tag
        its: dict[int, ItemTag] = {}
        for chunk in chunked([by_tag_name[n].id for n in order]):
            for it in s.execute(select(ItemTag).where(
                    ItemTag.item_id == item.id, ItemTag.tag_id.in_(chunk))).scalars():
                its[it.tag_id] = it
        # A placement in THIS run's group is this model's own earlier
        # answer — the one existing assignment a re-run may touch, and then
        # only to refresh its boxes. And which assignments carry any
        # placement at all — the ungrouped instance is implicit.
        placements: dict[int, ItemTagPlacement] = {}
        placed: set[int] = set()
        for chunk in chunked([it.id for it in its.values()]):
            for pl in s.execute(select(ItemTagPlacement).where(
                    ItemTagPlacement.item_tag_id.in_(chunk))).scalars():
                placed.add(pl.item_tag_id)
                if pl.group_id == grp.id:
                    placements[pl.item_tag_id] = pl
        added = 0
        todo: list[tuple[str, ItemTag | None]] = []
        for name in order:
            it = its.get(by_tag_name[name].id)
            placement = None if it is None else placements.get(it.id)
            if it is not None and placement is None:
                # THE ITEM ALREADY SAYS THIS. A bare label adds nothing, so
                # the assignment is left exactly as it is — the rule
                # `_pending_subject_tag` states for a face guess. A BOX is
                # new information, and the only thing approval can merge, so
                # that one gets a pending copy to review.
                if not by_name[name] or it.negative:
                    # A negative assignment is an answer already given, and a
                    # rectangle does not reopen it.
                    continue
                # Keep the tag WHERE IT IS: an ordinary assignment carries no
                # placement row at all (the ungrouped instance is implicit),
                # so a pending copy would not sit beside it — it would BE the
                # tag's only instance, i.e. the tag would move into Pending.
                # Materializing the ungrouped one first is what makes the
                # copy a copy.
                if it.id not in placed:
                    tagassign.ensure_placement(ctx, it.id, None)
                it.pending = True
            todo.append((name, it))
        # New assignments, flushed together for their ids.
        made: dict[str, ItemTag] = {}
        for name, it in todo:
            if it is None:
                made[name] = ItemTag(item_id=item.id, tag_id=by_tag_name[name].id,
                                     negative=False, pending=True)
                s.add(made[name])
        if made:
            s.flush()
        # One placement per tag in this run's pending group: the fresh ones
        # flushed together for their ids, a re-run's refreshed.
        rows: list[tuple[str, ItemTagPlacement, bool]] = []
        for name, it in todo:
            it = it or made[name]
            placement = placements.get(it.id)
            fresh = placement is None
            if fresh:
                placement = ItemTagPlacement(item_tag_id=it.id, group_id=grp.id)
                s.add(placement)
                added += 1
            else:
                # A re-run refreshes the machine-owned placement's boxes rather
                # than appending another identical set — appending grew the row
                # count by one full detection per run, without bound.
                for old in s.execute(select(ItemTagBox).where(
                    ItemTagBox.placement_id == placement.id
                )).scalars().all():
                    s.delete(old)
            rows.append((name, placement, fresh))
        if added:
            s.flush()
        for name, placement, fresh in rows:
            for (x, y, w, h) in by_name[name]:
                s.add(ItemTagBox(placement_id=placement.id, x=x, y=y, w=w, h=h))
            if fresh:
                # Only a NEW assignment is an event; re-confirming what an
                # earlier run already logged would stack un-undoable duplicates.
                log_event(
                    s, source="ai", action="add_tag", entity_type="item",
                    entity_id=item.id, summary="AI tag +{tag} (pending)",
                    summary_vars={"tag": name},
                    data={"item_id": item.id, "tag": name, "negative": False},
                )
        # The sidecar must hear about a re-run too: refreshed boxes and
        # re-flagged pending states are writes even when no placement is new.
        touch_items(s, [item.id])
        if added == 0:
            # Nothing new landed in the group; drop it if it ended up empty.
            if not s.execute(select(ItemTagPlacement).where(
                ItemTagPlacement.group_id == grp.id
            )).first():
                s.delete(grp)
            return "tags already present"
        return f"{added} tag{'s' if added != 1 else ''} added (pending)"


def _snippet(text: str, limit: int = 60) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= limit else t[: limit - 1] + "…"


def suggest_subjects(s, item: Item,
                     matcher: SubjectMatcher | None = None) -> int:
    """Name each unassigned face that looks like someone already known.

    A suggestion is only ever written over another suggestion — a person's
    answer (`assigned_by == "user"`) is never touched, and only their
    answers seed the pool, so one machine mistake cannot breed the next.

    The match ALSO puts the subject's tag on the item, **pending**: the tag
    is what search, training and export read, so a name that assigns
    nothing would be a label with no consequence — and pending is exactly
    the state the AI tagger already uses for "a machine said this, nobody
    has agreed yet". Confirming the face clears the flag; rejecting it
    takes the tag away again. A NAMELESS subject (an unnamed cluster) has
    no tag to assign, which is precisely why naming one later back-fills.

    ``matcher`` is the pool, loaded once per BATCH by the caller (a
    thousand-item run used to rebuild it a thousand times); the single-item
    path builds its own. Rejections stay per item — they already were.

    Returns how many faces were named, for the run's summary.
    """
    if matcher is None:
        matcher = SubjectMatcher.load(s)
    asking = [
        f for f in s.execute(
            select(Face).where(Face.item_id == item.id,
                               Face.dismissed.is_(False))
        ).scalars().all()
        if f.id not in matcher.claimed
    ]
    if not matcher.has_pool or not asking:
        return 0

    vectors = facelib.embeddings_of(s, [f.id for f in asking])
    refused = facelib.rejections_for(s, [f.id for f in asking])
    named = 0
    for face in asking:
        mine = vectors.get(face.id) or {}
        no = refused.get(face.id, frozenset())
        # One space at a time. A face described by two models asks each of
        # them, and the best answer over all of them wins — but no score
        # from one space is ever compared with a score from another.
        best: Optional[facelib.Match] = None
        for space, vector in mine.items():
            hit = matcher.match(space, vector, no)
            if hit is not None and (best is None or hit.score > best.score):
                best = hit
        if best is None:
            continue
        s.add(ItemSubject(item_id=item.id, subject_id=best.subject_id,
                          face_id=face.id, assigned_by="suggested",
                          match_score=best.score))
        s.flush()
        named += 1
        matcher.claim(face.id)
        _pending_subject_tag(s, item, best.subject_id)
    return named

def _pending_subject_tag(s, item: Item, subject_id: int) -> None:
    """Put a matched subject's tag on the item, awaiting review.

    An assignment that is already there is left exactly as it is: a
    confirmed tag must not be demoted to pending because a detector agreed
    with it.

    The bare ``ItemTag`` insert below is deliberate, not a bypass of
    ``ops.tagassign``: a face guess must be a PLACEMENT-LESS pending row —
    no placement in any group — because that shape is how
    ``_recompute_pending`` and the UI's amber marker tell "a machine said
    this and nobody has agreed yet" apart from a tag somebody placed.
    """
    from media_compost.db import Subject

    subject = s.get(Subject, subject_id)
    if subject is None or subject.tag_id is None:
        return
    if s.execute(select(ItemTag).where(
        ItemTag.item_id == item.id, ItemTag.tag_id == subject.tag_id
    )).scalars().first() is not None:
        return
    s.add(ItemTag(item_id=item.id, tag_id=subject.tag_id,
                  negative=False, pending=True))
    s.flush()
    tag = s.get(Tag, subject.tag_id)
    log_event(
        s, source="ai", action="add_tag", entity_type="item",
        entity_id=item.id,
        summary="AI tag +{tag} (pending)",
        summary_vars={"tag": tag.name if tag else subject.tag_id},
        data={"item_id": item.id, "tag": tag.name if tag else "",
              "negative": False},
    )

def suggest_around_faces(s, face_ids: list[int]) -> int:
    """A person just NAMED these faces — offer that answer to the unnamed
    faces that look like them, there and then.

    The clusters the Subjects tab shows are DERIVED at read time over the
    unnamed pool, and the ordinary suggestion pass runs only when a detection
    job applies — so naming one face of a cluster used to leave its
    lookalikes waiting for the next detection run to be told. This is the
    bridge: find the unnamed faces that agree with the newly named ones (the
    same per-space thresholds the clustering reads), then run their ITEMS
    through the ordinary ``suggest_subjects`` pass. The pool now contains the
    new answer, and reusing the pass WHOLESALE is what keeps one matching
    rule — per-space threshold AND the runner-up margin, so a face sitting
    between two lookalikes is still left for a person rather than suggested
    to whichever it happened to cluster nearer. Rejections still veto, and
    only faces carrying no appearance at all are asked, exactly as in a
    detection run.

    Called from the naming ENDPOINTS after a user-naming — never from a
    suggestion being confirmed: only a person's answers seed the pool, and
    suggestions must not breed suggestions.

    The similarity prefilter is one matrix-vector product per embedding
    space (numpy, the ``facevec`` brute path): a single anchor against the
    unnamed pool, the same cost as one row of the clustering the Subjects
    list already computes.
    """
    import numpy as np

    from media_compost.prefs import read_face_match_threshold

    from .facevec import unit

    matcher = SubjectMatcher.load(s)
    if not matcher.has_pool:
        return 0
    anchors = facelib.embeddings_of(s, face_ids)
    if not anchors:
        return 0
    named_set = set(face_ids)
    pool_ids = [fid for fid in s.execute(
        select(Face.id).where(Face.dismissed.is_(False))
    ).scalars().all() if fid not in matcher.claimed and fid not in named_set]
    if not pool_ids:
        return 0
    vectors = facelib.embeddings_of(s, pool_ids)
    setting = read_face_match_threshold(s)

    # Pool vectors grouped by (space, dim) — a vector only ever compares
    # within its own space, at that space's own threshold.
    by_space: dict[tuple[str, int], list[tuple[int, np.ndarray]]] = {}
    for fid, spaces in vectors.items():
        for space, raw in spaces.items():
            if raw and len(raw) % 4 == 0:
                v = unit(raw, len(raw) // 4)
                if v is not None:
                    by_space.setdefault((space, len(raw) // 4), []).append((fid, v))

    hits: set[int] = set()
    for (space, dim), rows in by_space.items():
        anchor_vecs = []
        for spaces in anchors.values():
            raw = spaces.get(space)
            if raw and len(raw) == dim * 4:
                v = unit(raw, dim)
                if v is not None:
                    anchor_vecs.append(v)
        if not anchor_vecs:
            continue
        ids_arr = [fid for fid, _v in rows]
        X = np.stack([v for _fid, v in rows])          # (n, dim)
        A = np.stack(anchor_vecs)                      # (k, dim)
        best = (X @ A.T).max(axis=1)                   # (n,)
        thr = facelib.threshold_for(space, setting)
        for fid, score in zip(ids_arr, best):
            if float(score) >= thr:
                hits.add(fid)
    if not hits:
        return 0

    item_ids = sorted(set(s.execute(
        select(Face.item_id).where(Face.id.in_(list(hits)))
    ).scalars().all()))
    named = 0
    for iid in item_ids:
        item = s.get(Item, iid)
        if item is not None:
            named += suggest_subjects(s, item, matcher)
    return named

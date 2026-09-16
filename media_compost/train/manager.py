"""Training-job lifecycle: file-based store + one trainer subprocess per GPU.

The manager is the ONLY writer of every job's ``job.json`` (all API mutations
funnel through it under one re-entrant lock; the app runs a single uvicorn
worker, so in-process locking is sufficient). Communication with the trainer
process is entirely file-based — ``state.json`` (trainer -> manager),
``control.json`` (manager -> trainer) — which survives server restarts and
the self-re-exec after plugin setup; a daemon tick thread polls every 2 s.

Statuses: draft -> queued -> running -> (pausing -> paused -> queued ...) ->
completed | failed | canceled. One job runs per DEVICE (a job's config names
its GPU, "auto" = the machine's first): the queue fills every free device
from the front, so distinct-GPU jobs run concurrently and same-GPU jobs wait.

Queueing a job never starts it. The queue has an explicit run switch
(``queue_run``/``queue_stop``, persisted in ``training/queue.json``): while
on, finished jobs chain into the next queued one; it switches itself off when
the queue drains, and pausing or canceling a running job by hand switches it
off too — an idle GPU only ever starts working because the user said run.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from media_compost import prune_query
from media_compost.hub import hf
from .nosleep import KeepAwake
from . import gpu as gputil
from . import paths as tp
from .paths import TRAIN_SCRIPTS, interpreter
from . import procs
from .spec import TrainingConfig

_TICK_SECONDS = 2.0
_STATE_FRESH_SECONDS = 60.0   # adopt a found pid only when state is this fresh
_CANCEL_TERM_SECONDS = 30.0   # escalate cancel: control file -> SIGTERM -> KILL



class TrainingError(ValueError):
    """Unknown job."""


class TrainingConflict(RuntimeError):
    """Operation not allowed in the job's current status."""


def _now() -> float:
    return time.time()


class _Prep:
    """A dataset being materialized on its own thread, for one job."""

    def __init__(self, device: str, resume: bool):
        self.device = device
        self.resume = resume
        self.thread: threading.Thread | None = None
        self.manifest: dict | None = None
        self.error: BaseException | None = None
        self.stop = False


class TrainingManager:
    def __init__(self, lib):
        self.ctx = lib          # a `Trainer` — see media_compost.train/__init__
        self.dir = lib.dir
        self._lock = threading.RLock()
        self._cv = threading.Condition(self._lock)
        self._procs: dict[str, subprocess.Popen] = {}  # uid -> child
        self._adopted: dict[str, int] = {}             # uid -> survived pid
        self._on_device: dict[str, str] = {}           # uid -> device id
        self._start_now: set[str] = set()  # explicit one-job starts (no chain)
        # Jobs whose dataset is being materialized right now, on a thread of
        # their own. Building a manifest reads the whole library, and with
        # videos in the dataset it also unpacks them into frames — minutes of
        # work that must NOT run inside the tick, which holds the lock every
        # API call needs. The tick polls these instead and spawns the trainer
        # when one finishes.
        self._preparing: dict[str, _Prep] = {}
        # Set when a run ends, consumed by the loop OUTSIDE the lock: a queued
        # Evaluate generation should start the moment the GPU frees, and that
        # manager has no tick of its own. Pumping it from inside `_finalize`
        # would ask it to ask us back, with our lock held.
        self._gpu_freed = False
        # Hours of GPU work with no user input is exactly what an idle-sleep
        # timer interrupts, so the machine is held awake while anything runs.
        self._awake = KeepAwake("a training job is running")
        self._stop = False
        self._recover()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="mc-training"
        )
        self._thread.start()

    # ---- store ---------------------------------------------------------

    def _dir(self, uid: str) -> Path:
        return tp.job_dir(self.dir, uid)

    def _read(self, uid: str) -> dict:
        rec = tp.read_json(tp.job_path(self._dir(uid)))
        if rec is None:
            raise TrainingError(f"unknown training job {uid}")
        return {**JOB_DEFAULTS, **rec}


    def _write(self, uid: str, rec: dict) -> None:
        rec["updated_at"] = _now()
        tp.write_json(tp.job_path(self._dir(uid)), rec)

    def read_config(self, uid: str) -> dict:
        """A job's config as TODAY's schema reads it.

        Two directions, and a stored config needs both. A config written
        before a setting existed is missing that key, and the editor reads its
        fields directly — so serving the stored dict raw means every new
        setting breaks the editor for every older job. And a config written
        before a field was DROPPED still carries it, which the condition
        models now refuse (`query.CondModel`), so a job whose dataset query
        used one could not be opened at all.

        Both are fixed HERE rather than on disk: the file stays as written
        until something actually saves it.
        """
        self._read(uid)  # 404 on unknown
        stored = tp.read_json(tp.config_path(self._dir(uid))) or {}
        return readable(_fill_defaults(
            stored, TrainingConfig().model_dump(mode="json")))

    def list_jobs(self) -> list[dict]:
        """All job records (with model/method joined in), newest first."""
        out = []
        with self._lock:
            for d in tp.list_job_dirs(self.dir):
                rec = tp.read_json(tp.job_path(d))
                if rec is None:
                    continue
                config = tp.read_json(tp.config_path(d)) or {}
                rec = dict(rec)
                rec["model"] = config.get("model", "")
                rec["method"] = config.get("method", "")
                rec["network"] = _network_of(config)
                out.append(rec)
        out.sort(key=lambda r: r.get("created_at", 0), reverse=True)
        return out

    def get(self, uid: str) -> dict:
        with self._lock:
            rec = dict(self._read(uid))
            config = tp.read_json(tp.config_path(self._dir(uid))) or {}
            rec["model"] = config.get("model", "")
            rec["method"] = config.get("method", "")
            rec["network"] = _network_of(config)
            return rec

    def running_uid(self) -> str | None:
        with self._lock:
            for d in tp.list_job_dirs(self.dir):
                rec = tp.read_json(tp.job_path(d))
                if rec and rec.get("status") in ("running", "pausing"):
                    return rec.get("uid")
        return None

    # ---- lifecycle (API entry points) -----------------------------------

    def _unique_name(self, name: str) -> str:
        """`name`, or the first "name N" nothing else is called.

        A uid is the identity, so two jobs may share a name — and a sidebar
        holding three rows called "Untitled training" is one you cannot read,
        cannot talk about, and cannot pick from. Numbering starts at 2 because
        the one already there IS the unnumbered name.

        Applied to every create, not only to a duplicate: the case that
        prompted it is "save as duplicate" (which reuses the name exactly),
        but typing a name another job already has produces the same unreadable
        list by a different route.
        """
        taken = {j.get("name") for j in self.list_jobs()}
        if name not in taken:
            return name
        n = 2
        while f"{name} {n}" in taken:
            n += 1
        return f"{name} {n}"

    def create(self, name: str, config: TrainingConfig, username: str) -> str:
        uid = tp.new_uid()
        with self._lock:
            jd = self._dir(uid)
            jd.mkdir(parents=True, exist_ok=True)
            tp.write_json(tp.config_path(jd), config.model_dump(mode="json"))
            self._write(uid, {
                "uid": uid,
                "name": self._unique_name(name.strip() or "Untitled training"),
                "username": username,
                "status": "draft",
                "step": 0,
                "total_steps": config.hyper.steps,
                "message": "",
                "phase": "",
                "created_at": _now(),
                "queued_at": None,
                "started_at": None,
                "finished_at": None,
            })
        return uid

    def update(self, uid: str, name: str | None,
               config: TrainingConfig | None) -> None:
        """Change a job's name and/or settings.

        Any job that isn't currently running can be edited — including one
        with a finished or paused run behind it, whose settings then apply
        to the NEXT run (the trainer read its config at spawn; a live change
        of the step count has its own path, `set_steps`). Because that means
        the settings no longer necessarily describe the run its checkpoint
        came from, every edit writes an "edited" event listing what changed,
        old value → new, so the timeline still explains the history.

        PAUSING is on the editable side of that line. The trainer took its
        config at spawn and is now finishing a checkpoint, so an edit reaches
        the next run exactly as it does on a job already paused — and a pause
        can take a minute on a big-batch job, which is a long time to be told
        a job cannot be edited for a reason that has already stopped applying.
        """
        with self._lock:
            rec = self._read(uid)
            if rec["status"] == "running":
                raise TrainingConflict(
                    "a running job can't be edited — pause it first (only "
                    "its total steps can change live)"
                )
            changes: list[dict] = []
            if name is not None:
                new_name = name.strip() or rec["name"]
                if new_name != rec["name"]:
                    changes.append({"field": "name", "old": rec["name"],
                                    "new": new_name})
                rec["name"] = new_name
            if config is not None:
                # Diff against the stored config with today's DEFAULTS filled
                # in: a config written before a setting existed is missing
                # that key, and reporting "gpu: — → auto" on the first edit
                # of an older job is noise about the schema, not about what
                # the user just did.
                stored = tp.read_json(tp.config_path(self._dir(uid))) or {}
                defaults = TrainingConfig().model_dump(mode="json")
                before = _fill_defaults(stored, defaults)
                after = config.model_dump(mode="json")
                changes += _config_changes(before, after)
                tp.write_json(tp.config_path(self._dir(uid)), after)
                rec["total_steps"] = config.hyper.steps
            self._write(uid, rec)
            if changes:
                tp.append_event(self._dir(uid), "edited",
                                int(rec.get("step") or 0),
                                {"changes": changes})

    def enqueue(self, uid: str) -> None:
        """Place a job in the queue. This never starts anything — the queue
        only works while its run switch is on (`queue_run`), so a queued job
        waits until the user says run (or an already-running queue reaches
        it)."""
        with self._cv:
            rec = self._read(uid)
            if rec["status"] not in ("draft", "paused"):
                raise TrainingConflict(f"cannot queue a {rec['status']} job")
            config = TrainingConfig.model_validate(self.read_config(uid))
            reason = config.ready_to_queue()
            if reason:
                raise TrainingConflict(reason)
            rec["status"] = "queued"
            # A job that was placed in the list (dragged, or queued before)
            # keeps its slot; only a job with no position yet goes to the back.
            rec["queued_at"] = rec.get("queued_at") or _now()
            rec["message"] = ""
            self._write(uid, rec)
            self._cv.notify_all()

    # ---- queue run switch --------------------------------------------------

    def _queue_flag_path(self) -> Path:
        return self.dir / "queue.json"

    def queue_active(self) -> bool:
        rec = tp.read_json(self._queue_flag_path())
        return bool(rec and rec.get("active"))

    def _set_queue_active(self, on: bool) -> None:
        tp.write_json(self._queue_flag_path(), {"active": bool(on)})

    def queue_run(self) -> None:
        """Start working through the queue, front job first, filling every
        free device. Stays on so finished jobs chain into the next queued
        one; switches itself off when the queue drains."""
        with self._cv:
            self._set_queue_active(True)
            # The tick thread does the starting (manifest build + spawn can
            # take a while) — waking it makes that immediate, not in 2 s.
            self._cv.notify_all()

    def queue_stop(self) -> None:
        """Stop starting new jobs. Running jobs are not touched."""
        with self._lock:
            self._set_queue_active(False)

    def start_now(self, uid: str, *, preempt: bool = False,
                  run_queue: bool = False) -> None:
        """Run THIS job next.

        Plain, it starts the one job without turning the queue's run switch
        on, so nothing chains after it, and a device busy with another
        training job is refused — that one the user can pause themselves.

        `preempt` PAUSES the job holding the device instead of refusing, and
        `run_queue` leaves the switch on so the rest of the queue follows. The
        pair is what the row's start button does: "run this one, now". The
        order that makes it work is the tick's: `_start_explicit` runs before
        `_maybe_start`, so this job takes the device the moment it frees, and
        the job that was paused — which `_finalize` re-queues at the FRONT,
        because a hand pause means "I want to come back to this" — is next in
        line rather than racing us for the card it just gave up.
        """
        with self._cv:
            rec = self._read(uid)
            if rec["status"] not in ("draft", "paused", "queued"):
                raise TrainingConflict(f"cannot start a {rec['status']} job")
            device = self._device_for(uid)
            if preempt:
                for other, dev in list(self._on_device.items()):
                    if dev == device and other != uid \
                            and self._read(other)["status"] == "running":
                        # Its own lock, not ours: `pause` takes `self._lock`,
                        # and `self._cv` is built on it (RLock), so this is
                        # reentrant rather than a deadlock.
                        self.pause(other)
            # An Evaluate generation on this device is NOT a refusal: the job
            # is accepted and waits, exactly as it would behind another
            # training job, and `_start_explicit` keeps the request pending
            # until the device frees. Refusing here meant "start" simply did
            # nothing while the other tab was busy. (A busy training job below
            # still refuses — that one the user can pause themselves.)
            # …and once the holder has been PAUSED above, the device being
            # busy is no longer a refusal either: its child is on its way out
            # (checkpointing takes seconds), `_on_device` still names it until
            # it exits, and the pending explicit start waits for exactly that.
            if device in self._on_device.values() and not preempt:
                other = next(u for u, d in self._on_device.items()
                             if d == device)
                raise TrainingConflict(
                    f"its GPU ({device}) is busy with "
                    f"“{self._read(other).get('name', other)}” — "
                    "pause that job first, or wait for it")
            if rec["status"] != "queued":
                self.enqueue(uid)
            # To the FRONT, so "start this one" survives a restart that loses
            # the in-memory set below: the queue would then reach it first
            # anyway, which is the same answer by a slower route.
            rec = self._read(uid)
            rec["queued_at"] = self._front_queued_at()
            self._write(uid, rec)
            self._start_now.add(uid)
            if run_queue:
                # `pause` above turned the switch off ("I want this machine
                # back"). Here the user asked for the opposite in the same
                # gesture, so it goes back on and the queue carries on after
                # this job.
                self._set_queue_active(True)
            self._cv.notify_all()

    # ---- queue order ------------------------------------------------------

    def reorder_queue(self, uids: list[str]) -> None:
        """Put the WAITING jobs (queued, paused, draft — everything the app's
        Queued section lists) into this order. `queued_at` is the ordering key
        everywhere — for paused and draft jobs it is purely a position stamp —
        so reordering assigns fresh, evenly spaced stamps in the requested
        order; jobs not named keep their place relative to each other, after
        the named ones."""
        with self._lock:
            queued = {
                rec["uid"]: rec for d in tp.list_job_dirs(self.dir)
                if (rec := tp.read_json(tp.job_path(d))) is not None
                and rec.get("status") in ("queued", "paused", "draft")
            }
            named = [u for u in uids if u in queued]
            rest = sorted((r for u, r in queued.items() if u not in set(named)),
                          key=lambda r: r.get("queued_at") or 0)
            base = _now()
            for i, uid in enumerate(named + [r["uid"] for r in rest]):
                rec = queued[uid]
                rec["queued_at"] = base + i * 0.001
                self._write(uid, rec)

    def pause(self, uid: str) -> None:
        with self._lock:
            rec = self._read(uid)
            if rec["status"] == "queued":
                # Out of the queue and back to what it was: a job with a
                # checkpoint returns to paused (its checkpoint is its value),
                # one without to draft. The position stamp survives, so
                # re-queueing does not silently move it to the end.
                has_ckpt = (tp.checkpoints_dir(self._dir(uid)) / "last").is_dir()
                rec["status"] = "paused" if has_ckpt else "draft"
                self._write(uid, rec)
                return
            if rec["status"] != "running":
                raise TrainingConflict(f"cannot pause a {rec['status']} job")
            tp.write_json(tp.control_path(self._dir(uid)), {"cmd": "pause"})
            self._stop_prep(uid)
            rec["status"] = "pausing"
            self._write(uid, rec)
            # Pausing by hand means "I want this machine back" — the queue
            # must not answer by starting the next job on the freed device.
            self._set_queue_active(False)

    def cancel(self, uid: str) -> None:
        with self._lock:
            rec = self._read(uid)
            status = rec["status"]
            if status in ("draft", "queued", "paused"):
                rec["status"] = "canceled"
                rec["finished_at"] = _now()
                self._write(uid, rec)
                tp.append_event(self._dir(uid), "canceled",
                                int(rec.get("step") or 0))
                return
            if status in ("running", "pausing"):
                tp.write_json(tp.control_path(self._dir(uid)), {"cmd": "cancel"})
                # A job still materializing its dataset has no trainer to read
                # that file — the flag is what stops it, mid-video if need be.
                self._stop_prep(uid)
                rec["cancel_requested_at"] = _now()
                rec["message"] = "canceling…"
                self._write(uid, rec)
                # Unlike pause, cancel does NOT stop the queue: it discards
                # this job ("skip"), and a running queue moves on to the next.
                return
            raise TrainingConflict(f"job is already {status}")

    def set_steps(self, uid: str, steps: int) -> None:
        """Change a job's total steps — including live on a running job, and on
        a completed one (which becomes resumable again: completed jobs keep
        their ``checkpoints/last``, so raising the target lets Resume continue
        the finished run)."""
        with self._lock:
            rec = self._read(uid)
            status = rec["status"]
            jd = self._dir(uid)
            cfgd = readable(tp.read_json(tp.config_path(jd)) or {})
            cfgd.setdefault("hyper", {})["steps"] = steps
            try:
                config = TrainingConfig.model_validate(cfgd)
            except ValueError as exc:  # pydantic bounds (steps >= 1, …)
                raise TrainingConflict(f"invalid step count: {exc}") from exc
            if status in ("running", "pausing", "paused", "completed") \
                    and steps <= int(rec.get("step") or 0):
                raise TrainingConflict(
                    f"total steps must exceed the current step "
                    f"({rec.get('step')})"
                )
            if status in ("running", "pausing"):
                if tp.read_json(tp.control_path(jd)) is not None:
                    raise TrainingConflict(
                        "another command is still pending — try again in a "
                        "few seconds"
                    )
                tp.write_json(tp.control_path(jd),
                              {"cmd": "set_steps", "steps": steps})
            elif status == "completed":
                if not (tp.checkpoints_dir(jd) / "last").is_dir():
                    raise TrainingConflict(
                        "no resumable checkpoint left — duplicate the job "
                        "instead"
                    )
                rec["status"] = "paused"
                rec["finished_at"] = None
                rec["message"] = ""
            elif status not in ("draft", "queued", "paused"):
                raise TrainingConflict(
                    f"cannot change the steps of a {status} job — duplicate "
                    "it instead"
                )
            tp.write_json(tp.config_path(jd), config.model_dump(mode="json"))
            rec["total_steps"] = steps
            self._write(uid, rec)

    def duplicate(self, uid: str, username: str) -> str:
        with self._lock:
            src = self._read(uid)
            config = TrainingConfig.model_validate(self.read_config(uid))
            return self.create(f"{src['name']} (copy)", config, username)

    def delete(self, uid: str) -> int:
        """Remove the job — and KEEP whatever was locked, as the user's own.

        A lock says "this one stays", and deleting the job is the moment that
        promise is worth something: a checkpoint protected from the keep-last
        rule and from its own delete button, thrown away by a click on a
        different row, would be a lock that only held while nothing was
        happening.

        Kept weights move OUT of the job folder (into `kept/`) and are
        registered as user LoRAs, because a job-owned weight set is listed by
        walking the jobs — with the job gone, files left in place would be
        invisible in the LoRAs list and in the Evaluate dropdown, which is a
        subtler way of losing them. Answers how many it kept, so the caller
        can say so.
        """
        with self._lock:
            rec = self._read(uid)
            if rec["status"] in ("running", "pausing"):
                raise TrainingConflict("stop the job before removing it")
            kept = self._keep_locked(uid, rec)
            shutil.rmtree(self._dir(uid), ignore_errors=True)
            return kept

    def _keep_locked(self, uid: str, rec: dict) -> int:
        """Move this job's locked weight dirs into `kept/` and list them."""
        from . import usermodels

        jd = self._dir(uid)
        locked: list[tuple[str, Path]] = []
        out = tp.output_dir(jd)
        if tp.is_locked(out):
            locked.append(("final", out))
        cdir = tp.checkpoints_dir(jd)
        if cdir.is_dir():
            for d in sorted(cdir.iterdir()):
                if d.is_dir() and d.name.startswith("step-") and tp.is_locked(d):
                    locked.append((d.name.replace("step-", "step ").lstrip("0")
                                   or d.name, d))
        if not locked:
            return 0
        keep_root = tp.kept_dir(self.dir)
        keep_root.mkdir(parents=True, exist_ok=True)
        loras = usermodels.read_loras(self.dir)
        name = rec.get("name") or uid
        # Which model these weights fit — off the CONFIG, because the job
        # RECORD carries no model key: `get`/`list_jobs` join it in and this
        # runs on the raw record.
        config = tp.read_json(tp.config_path(jd)) or {}
        model = str(config.get("model") or rec.get("model") or "")
        for what, src in locked:
            dest = keep_root / f"{uid}-{src.name}"
            # A name that is already taken means a previous keep of the same
            # job and snapshot; the newer files win rather than landing beside
            # the old ones under a second name nobody asked for.
            shutil.rmtree(dest, ignore_errors=True)
            try:
                shutil.move(str(src), str(dest))
            except OSError:
                continue
            tp.lock_marker(dest).unlink(missing_ok=True)
            label = f"{name} · {what}"
            existing = [usermodels.UserModel(key=lo.key, label=lo.label,
                                             base="", repo=lo.path, local=True)
                        for lo in loras]
            loras.append(usermodels.UserLora(
                key=usermodels.unique_key(existing, label), label=label,
                model=model, path=str(dest),
            ))
        usermodels.write_loras(self.dir, loras)
        return len(locked)

    # ---- recovery --------------------------------------------------------

    def _recover(self) -> None:
        """Reconcile jobs left running/pausing by a dead or re-exec'd server."""
        for d in tp.list_job_dirs(self.dir):
            rec = tp.read_json(tp.job_path(d))
            if rec is None:
                continue
            # A failure parks a job as paused (see `_finalize`). Records
            # written before that rule still say "failed", which would strand
            # them in the finished list forever — there is no migration
            # mechanism, so normalise them on the way past.
            if rec.get("status") == "failed":
                rec["status"] = "paused"
                rec.pop("finished_at", None)
                self._write(rec.get("uid", d.name), rec)
                continue
            if rec.get("status") not in ("running", "pausing"):
                continue
            uid = rec.get("uid", d.name)
            state = tp.read_json(tp.state_path(d)) or {}
            pid = state.get("pid")
            fresh = (_now() - float(state.get("updated_at") or 0)
                     < _STATE_FRESH_SECONDS)
            if pid and fresh and _pid_alive(int(pid)) \
                    and uid not in self._adopted:
                # The trainer survived the server restart — keep monitoring it.
                self._adopted[uid] = int(pid)
                self._on_device[uid] = self._device_for(uid)
                continue
            has_ckpt = (tp.checkpoints_dir(d) / "last").is_dir()
            tp.append_event(d, "paused" if has_ckpt else "failed",
                            int(rec.get("step") or 0))
            # Interrupted either way, so the job waits in the queue — with a
            # checkpoint it resumes, without one it starts over.
            rec["status"] = "paused"
            rec["phase"] = ""
            rec["phase_note"] = ""
            rec["phase_sub"] = ""
            rec["message"] = (
                "server restarted — resume to continue from the last checkpoint"
                if has_ckpt else "interrupted before the first checkpoint"
            )
            self._write(uid, rec)
        # A restart must not start jobs behind the user's back: unless a live
        # trainer survived (its chain is genuinely mid-run), the queue waits
        # for an explicit run again.
        if not self._adopted and self.queue_active():
            self._set_queue_active(False)

    # ---- tick loop -------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop:
            try:
                self._tick()
            except Exception:  # noqa: BLE001 - the loop must survive anything
                import traceback
                traceback.print_exc()
            if self._gpu_freed:
                self._gpu_freed = False
                try:
                    self.ctx.evaluation.pump()
                except Exception:  # noqa: BLE001 - best effort, never fatal
                    pass
            with self._cv:
                self._cv.wait(timeout=_TICK_SECONDS)

    def _tick(self) -> None:
        with self._lock:
            for uid in list(self._procs):
                self._watch_child(uid)
            for uid in list(self._adopted):
                self._watch_adopted(uid)
            # A dataset thread that has finished is the trainer's cue to spawn.
            for uid in list(self._preparing):
                self._finish_prepare(uid)
            # Reconciled every tick (not only on transitions), so a helper
            # that died or a job adopted after a restart is covered too.
            self._awake.set_active(bool(self._procs or self._adopted))
            if self._start_now:
                self._start_explicit()
            if self.queue_active():
                self._maybe_start()
                # A job whose dataset is still being materialized has no child
                # process yet and is no longer in the queue — counting only
                # those two would read as "drained" and switch the queue off
                # under a run that is about to start.
                if not self._procs and not self._adopted \
                        and not self._preparing and not self._queued_recs():
                    # Drained: the next queued job waits for an explicit run
                    # again rather than starting the moment it is added.
                    self._set_queue_active(False)

    def _watch_child(self, uid: str) -> None:
        proc = self._procs[uid]
        code = proc.poll()
        if code is None:
            self._mirror_state(uid)
            self._escalate_cancel(uid, proc.pid)
            return
        self._finalize(uid, exit_code=code)
        del self._procs[uid]
        self._on_device.pop(uid, None)

    def _watch_adopted(self, uid: str) -> None:
        pid = self._adopted[uid]
        if _pid_alive(pid):
            self._mirror_state(uid)
            self._escalate_cancel(uid, pid)
            return
        self._finalize(uid, exit_code=None)
        del self._adopted[uid]
        self._on_device.pop(uid, None)

    def _mirror_state(self, uid: str) -> None:
        try:
            rec = self._read(uid)
        except TrainingError:
            return
        state = tp.read_json(tp.state_path(self._dir(uid))) or {}
        step = state.get("step")
        changed = False
        if isinstance(step, int) and step != rec.get("step"):
            rec["step"] = step
            changed = True
        phase = state.get("phase") or ""
        note = str(state.get("note") or "")
        sub = str(state.get("sub") or "")
        if (phase != rec.get("phase") or note != rec.get("phase_note")
                or sub != rec.get("phase_sub")):
            rec["phase"] = phase
            rec["phase_note"] = note
            rec["phase_sub"] = sub
            changed = True
        total = state.get("total_steps")
        if isinstance(total, int) and total and total != rec.get("total_steps"):
            rec["total_steps"] = total
            changed = True
        # The cadences as the RUN resolved them — an epoch setting is a step
        # count only once the manifest has said how long a pass is, so the
        # config cannot answer this and the app must not read it.
        for key in ("ckpt_every", "sample_every"):
            v = state.get(key)
            if isinstance(v, int) and v != rec.get(key):
                rec[key] = v
                changed = True
        if changed:
            self._write(uid, rec)

    def _escalate_cancel(self, uid: str, pid: int) -> None:
        """A canceled trainer that ignores control.json gets SIGTERM, then KILL."""
        try:
            rec = self._read(uid)
        except TrainingError:
            return
        asked = rec.get("cancel_requested_at")
        if not asked:
            return
        waited = _now() - float(asked)
        if waited > 2 * _CANCEL_TERM_SECONDS:
            procs.kill(pid)
        elif waited > _CANCEL_TERM_SECONDS:
            procs.terminate(pid)

    def _park_failed(self, uid: str, rec: dict, message: str) -> None:
        """A job that could not START — no training environment, a dataset
        that would not build, a spawn that raised — is parked exactly as a
        run that failed partway is (`_finalize`): PAUSED, out of the queue,
        with the reason as its message and a `failed` event on its timeline.
        It used to be stamped ``failed`` with a finish time, which put it in
        the Finished section where enqueue, start and set-steps all refuse
        it — a dead end nothing but a server restart (`_recover`) undid."""
        tp.append_event(self._dir(uid), "failed", int(rec.get("step") or 0))
        rec["status"] = "paused"
        rec["message"] = message
        rec["phase"] = ""
        rec["phase_note"] = ""
        rec["phase_sub"] = ""
        rec.pop("finished_at", None)
        self._write(uid, rec)

    def _finalize(self, uid: str, exit_code: int | None) -> None:
        try:
            rec = self._read(uid)
        except TrainingError:
            return  # job folder deleted under us
        # Idempotent: a job someone already finalized stays finalized. Three
        # watchers once existed at the same time (see Library._lazy_lock) and
        # each stamped its own "paused" event; whatever observer shows up
        # late from now on finds a terminal status here and stands down.
        if rec.get("status") not in ("running", "pausing"):
            return
        self._gpu_freed = True
        jd = self._dir(uid)
        state = tp.read_json(tp.state_path(jd)) or {}
        phase = state.get("phase")
        if phase in ("completed", "paused", "canceled", "failed"):
            status = phase
        elif rec.get("cancel_requested_at"):
            status = "canceled"
        else:
            status = "failed"
        # A failure is not the end of a job. Whatever went wrong — a model that
        # wasn't downloaded, a setting the trainer rejected, an out-of-memory
        # halfway through — the useful next move is to fix it and carry on, so
        # the job goes back to the QUEUED list as paused rather than into
        # "finished" where it can only be duplicated. The reason is kept as the
        # job's message, and the timeline still records that it failed.
        failed = status == "failed"
        # What HAPPENED, for the timeline — the record's status is a
        # scheduling state and gets remapped below (a failure parks as
        # paused, a hand pause re-enters the queue); the event log must keep
        # saying "paused"/"failed" regardless.
        happened = status
        # A hand-paused job goes back to the FRONT of the queue: pausing is
        # "not now", not "not at all", and the next thing the user does with
        # it is almost always resume — so it waits first in line rather than
        # in the held list. A FAILURE is different (it needs fixing first)
        # and stays out of the queue, as does a restart-interrupted run.
        paused_by_hand = status == "paused" and rec.get("status") == "pausing"
        # Nothing was produced before the first step, so there is no run behind
        # the settings and they stay editable (see `update`).
        step = int(state.get("step") or rec.get("step") or 0)
        if failed:
            status = "paused"
        if paused_by_hand and not failed:
            status = "queued"
            rec["queued_at"] = self._front_queued_at()
        rec["status"] = status
        rec["phase"] = ""
        rec["phase_note"] = ""
        rec["phase_sub"] = ""
        rec.pop("cancel_requested_at", None)
        if failed:
            rec["message"] = state.get("error") or _log_tail(tp.log_path(jd)) \
                or f"trainer exited with code {exit_code}"
            # How far it actually got — the tick mirrors this while running,
            # but a crash can outrun the last mirror, and both the progress
            # display and the "still editable?" rule read it.
            rec["step"] = max(step, int(rec.get("step") or 0))
        elif status == "completed":
            rec["step"] = rec.get("total_steps", rec.get("step", 0))
            rec["message"] = ""
        else:
            rec["message"] = ""
        if status != "paused":
            rec["finished_at"] = _now()
        self._write(uid, rec)
        # The event log keeps the truth: a failed run reads "failed" in the
        # timeline even though the job is parked as paused.
        tp.append_event(jd, happened, step)
        # Frames extracted from videos are scratch, and a job that is OVER
        # keeps none of it. A job that is not over does, checkpoint or no
        # checkpoint: it will be materialized again when it next starts, and
        # the frames are the expensive half of that — `videoframes` re-samples
        # only the films whose stamp no longer matches. (Deleting them here
        # was what made a pause during the extraction, or a run that died
        # before its first checkpoint, cost the whole decode a second time.)
        if status in ("completed", "canceled"):
            shutil.rmtree(jd / "frames", ignore_errors=True)
        # Index whatever latents the run cached. They live in the ITEMS'
        # artifact folders (shared across jobs), so they are recorded against
        # the file they belong to — the trainer writes the bytes but never
        # touches the DB, so this happens here, after it exits.
        try:
            from .dataset import register_latents

            with self._library() as lib:
                register_latents(lib, jd)
        except Exception:  # bookkeeping must never break the lifecycle
            pass

    def _library(self):
        """A public-API handle on the library, for the two things here that
        read or write it: materializing a dataset and indexing the latents a
        run cached.

        Its OWN connection, deliberately. Both run on threads of their own and
        neither belongs to a request; more to the point, going through
        `open_library` is what proves the training side needs nothing from the
        server — which is the whole precondition for it living somewhere else.
        """
        return self.ctx.library()

    def _front_queued_at(self) -> float:
        """A position stamp before every queued job's, so the caller lands at
        the head of the queue."""
        stamps = [r.get("queued_at") or 0.0 for r in self._queued_recs()]
        return (min(stamps) - 1.0) if stamps else _now()

    def _queued_recs(self) -> list[dict]:
        recs = [
            rec for d in tp.list_job_dirs(self.dir)
            if (rec := tp.read_json(tp.job_path(d))) is not None
            and rec.get("status") == "queued"
        ]
        recs.sort(key=lambda r: r.get("queued_at") or 0)
        return recs

    def busy_devices(self) -> set[str]:
        """The scheduling slots training currently occupies. Public because the
        Evaluate manager has to ask before it spawns — the two share the GPU
        and, on unified memory especially, do not queue on their own: they
        collide as an out-of-memory failure."""
        with self._lock:
            return set(self._on_device.values())

    def evaluating_device(self) -> str | None:
        """The device an Evaluate generation is rendering on, or None.

        Reported by the status endpoint so a job queued *because the other tab
        has the GPU* can say so, instead of looking like one that is merely
        next in line behind other training."""
        try:
            return (self.ctx.evaluation.device()
                    if self.ctx.evaluation.rendering() else None)
        except Exception:  # noqa: BLE001 - a probe must not break the status
            return None

    def _occupied(self) -> set[str]:
        """Devices something is already using — a training job, or an Evaluate
        generation, which is on the GPU just as much as a run is. Called with
        our lock held, which is the legal direction (training -> eval)."""
        busy = set(self._on_device.values())
        try:
            if self.ctx.evaluation.rendering():
                busy.add(self.ctx.evaluation.device())
        except Exception:  # noqa: BLE001 - never block a run over this
            pass
        return busy

    def _device_for(self, uid: str) -> str:
        """The scheduling slot a job occupies: its configured device, with
        "auto" resolved to the machine's first one."""
        config = tp.read_json(tp.config_path(self._dir(uid))) or {}
        gpu = str(config.get("gpu") or "auto")
        if gpu != "auto":
            return gpu
        devs = gputil.train_devices()
        return devs[0]["id"] if devs else "cpu"

    def _start_explicit(self) -> None:
        """Start the jobs the user started by hand (`start_now`). A device
        grabbed between the request and this tick just keeps the start
        pending until it frees up; a job dequeued meanwhile is dropped."""
        busy = self._occupied()
        for uid in list(self._start_now):
            try:
                rec = self._read(uid)
            except TrainingError:
                self._start_now.discard(uid)
                continue
            if rec.get("status") != "queued":
                self._start_now.discard(uid)
                continue
            device = self._device_for(uid)
            if device in busy:
                continue
            self._start_now.discard(uid)
            if self._start_job(rec, device):
                busy.add(device)

    def _maybe_start(self) -> None:
        """Fill every free device from the front of the queue. Called only
        while the queue's run switch is on — queueing alone starts nothing.
        A job whose device is busy does not block the queue: the next job
        that fits a free device starts ahead of it."""
        queued = self._queued_recs()
        if not queued:
            return
        busy = self._occupied()
        for rec in queued:
            device = self._device_for(rec["uid"])
            if device in busy:
                continue
            if self._start_job(rec, device):
                busy.add(device)

    def _start_job(self, rec: dict, device: str) -> bool:
        uid = rec["uid"]
        jd = self._dir(uid)

        # An Evaluate generator may be sitting on a loaded model to stay warm.
        # Training needs that memory far more than the next Generate click
        # does, and on unified memory the two do not queue — they collide.
        try:
            self.ctx.evaluation.release_idle()
        except Exception:  # noqa: BLE001 - never block a run over this
            pass
        # And whatever the host keeps warm beside it (the app's AI-model
        # worker, idle for up to its TTL): same reason, same rule.
        release = getattr(self.ctx, "release_models", None)
        if release is not None:
            try:
                release()
            except Exception:  # noqa: BLE001
                pass

        interp = interpreter()
        if not interp:
            self._park_failed(uid, rec, "training environment not set up — "
                                        "run setup from the Train tab")
            return False

        rec["status"] = "running"
        rec["started_at"] = _now()
        rec["message"] = ""
        rec["phase"] = "preparing"
        self._write(uid, rec)

        resume = (tp.checkpoints_dir(jd) / "last").is_dir()
        kind = "resumed" if resume else "started"
        tp.append_event(jd, kind, int(rec.get("step") or 0))
        tp.append_log_banner(jd, kind, int(rec.get("step") or 0))
        if resume and self._dataset_ready(jd):
            # Nothing to materialize — the manifest of the interrupted run is
            # still there, and its frames with it.
            return self._launch(uid, device, resume=True)
        # The dataset is built on its own thread and the device is held
        # meanwhile: reading the library (and unpacking videos into frames)
        # takes anywhere from a moment to minutes, and the tick's lock is what
        # every API call waits on. `resume` travels with it: a finished job
        # continued with more steps has a checkpoint to come back to and no
        # dataset left to train on, and those are two separate questions.
        prep = _Prep(device, resume=resume)
        prep.thread = threading.Thread(
            target=self._prepare, args=(uid, jd, prep), daemon=True,
            name=f"mc-dataset-{uid[:8]}")
        self._preparing[uid] = prep
        self._on_device[uid] = device
        prep.thread.start()
        return True

    def _dataset_ready(self, jd: Path) -> bool:
        """Whether the last run's dataset is still on disk to be resumed onto.

        A resume reuses the manifest rather than building another one, and
        that is only sound while the files it names are there. Every path in a
        manifest is a stored library file except one: a video's frames are
        scratch in the job folder, thrown away when the job finishes — so a
        FINISHED job continued with more steps has a checkpoint to resume from
        and nothing left to train on. Only the frames are asked about; the
        folder exists whenever a run built one, empty or not.
        """
        if not tp.manifest_path(jd).is_file():
            return False
        cfg = tp.read_json(tp.config_path(jd)) or {}
        if not (cfg.get("video") or {}).get("include"):
            return True
        return (jd / "frames").is_dir()

    def _stop_prep(self, uid: str) -> None:
        """Ask a job's dataset thread to stop at the next frame it looks at."""
        prep = self._preparing.get(uid)
        if prep is not None:
            prep.stop = True

    def _prepare(self, uid: str, jd: Path, prep: _Prep) -> None:
        """Materialize a job's dataset. Runs OFF the manager lock; the only
        thing it touches under it is the job record's phase note."""
        from .dataset import build_manifest

        def note(text: str) -> None:
            with self._lock:
                try:
                    rec = self._read(uid)
                except TrainingError:
                    return
                if rec.get("phase_note") != text:
                    rec["phase_note"] = text
                    self._write(uid, rec)

        try:
            # Its OWN handle on the library, through the public API. This runs
            # on a thread of its own, off the manager lock, and the whole
            # point of reading the library this way is that the dataset
            # builder needs nothing of the server's — which is what lets it
            # move into a package of its own.
            with self._library() as lib:
                prep.manifest = build_manifest(
                    lib, tp.read_json(tp.config_path(jd)) or {}, jd,
                    progress=note, should_stop=lambda: prep.stop)
        except BaseException as exc:  # noqa: BLE001 - reported by the tick
            prep.error = exc

    def _finish_prepare(self, uid: str) -> None:
        """Spawn the trainer for a job whose dataset thread has finished."""
        prep = self._preparing[uid]
        if prep.thread is not None and prep.thread.is_alive():
            return
        self._preparing.pop(uid, None)
        try:
            rec = self._read(uid)
        except TrainingError:
            self._on_device.pop(uid, None)
            return
        if prep.error is not None:
            self._park_failed(uid, rec, f"failed to start: {prep.error}")
            self._on_device.pop(uid, None)
            return
        if rec.get("cancel_requested_at") or rec.get("status") != "running":
            # Stopped while the dataset was being built. There is no child to
            # signal and no state.json to read, so this is settled here rather
            # than in `_finalize`: a cancel is done with, a pause goes back to
            # the front of the queue exactly as a hand pause of a running job
            # does — nothing was produced, so there is nothing to resume from.
            self._on_device.pop(uid, None)
            canceled = bool(rec.get("cancel_requested_at"))
            rec.pop("cancel_requested_at", None)
            rec["phase"] = ""
            rec["phase_note"] = ""
            rec["message"] = ""
            if canceled:
                rec["status"] = "canceled"
                rec["finished_at"] = _now()
            else:
                rec["status"] = "queued"
                rec["queued_at"] = self._front_queued_at()
            self._write(uid, rec)
            tp.append_event(self._dir(uid), "canceled" if canceled else "paused",
                            int(rec.get("step") or 0))
            return
        manifest = prep.manifest or {}
        # What the run is actually training on, recorded once — the app can
        # then say so without re-reading a manifest that lists every image
        # with its tags on every poll.
        items = manifest.get("items") or []
        frames = sum(1 for it in items if it.get("video_time") is not None)
        rec["dataset"] = {
            "images": len(items),
            "buckets": len(manifest.get("buckets") or []),
            # How many of those images came out of a film. Written only when
            # there are any — it is the answer to "did my videos make it into
            # this run", which nothing else was saying: a frame has no stored
            # file, so it is the one kind of training image that leaves no
            # trace in the library.
            **({"frames": frames} if frames else {}),
        }
        rec["phase_note"] = ""
        self._write(uid, rec)
        self._launch(uid, prep.device, resume=prep.resume)

    def _launch(self, uid: str, device: str, resume: bool) -> bool:
        """Spawn the trainer for a job whose job dir is ready."""
        jd = self._dir(uid)
        interp = interpreter()
        try:
            # A stale pause/cancel command or state must not leak into the run.
            tp.control_path(jd).unlink(missing_ok=True)
            tp.state_path(jd).unlink(missing_ok=True)
            argv = [interp, str(TRAIN_SCRIPTS / "train.py"), "--job-dir",
                    str(jd)]
            if resume:
                argv.append("--resume")
            # The trainer fetches its base model on first use, so it needs the
            # token this machine has — and it was never handed this env at all
            # (the Popen below simply dropped it, MPS fallback included).
            env = hf.child_env({"PYTORCH_ENABLE_MPS_FALLBACK": "1"})
            # Pin the run to its device. A CUDA card is masked to the one
            # index (the trainer then simply sees "cuda"); everything else is
            # named directly and validated by the trainer's pick_device.
            # An AMD card under ROCm is ALSO a "cuda:N" here (gpu.py says
            # why), and HIP reads its own variable — set both; each vendor's
            # runtime ignores the other's.
            if device.startswith("cuda:"):
                idx = device.split(":", 1)[1]
                env["CUDA_VISIBLE_DEVICES"] = idx
                env["HIP_VISIBLE_DEVICES"] = idx
                env["MEDIA_COMPOST_TRAIN_DEVICE"] = "cuda"
            else:
                env["MEDIA_COMPOST_TRAIN_DEVICE"] = device
            with open(tp.log_path(jd), "ab") as log:
                self._procs[uid] = subprocess.Popen(
                    argv, stdout=log, stderr=subprocess.STDOUT,
                    cwd=str(TRAIN_SCRIPTS), env=env,
                )
            self._on_device[uid] = device
            return True
        except Exception as exc:  # noqa: BLE001 - spawn/manifest failure
            rec = self._read(uid)
            self._park_failed(uid, rec, f"failed to start: {exc}")
            self._procs.pop(uid, None)
            self._on_device.pop(uid, None)
            return False


#: Every key ``job.json`` can hold, with what it means when it is absent.
#:
#: A job folder is written once and read by every build after it, so a key
#: added later is simply MISSING from every job already on disk. That matters
#: here more than it does for ``config.json``, because this record is read
#: with ``rec["status"]`` rather than ``rec.get("status")`` — a missing key is
#: a KeyError that makes the job unreadable, not a default. Filling on READ,
#: the same thing :meth:`Manager.read_config` does and for the same reason,
#: leaves the file exactly as it was written until something saves it.
#:
#: Adding a key here is what makes it safe to start reading that key.
JOB_DEFAULTS: dict = {
    "uid": "",
    "name": "Untitled training",
    "username": "",
    "status": "draft",
    "step": 0,
    "total_steps": 0,
    "message": "",
    "phase": "",
    "phase_note": "",
    "phase_sub": "",
    "model": "",
    "method": "",
    "created_at": 0.0,
    "updated_at": 0.0,
    "queued_at": None,
    "started_at": None,
    "finished_at": None,
}


def _network_of(config: dict) -> str:
    """Which kind of adapter a job trains, for the card that labels it.

    `method` alone can only say "an adapter" now that there are two kinds, so
    a LoKr job was shown as a LoRA. Read from the stored config rather than
    added to `job.json`: it is a fact about the CONFIG, which the editor can
    change, and the record would go stale the first time somebody did.

    Empty for a full finetune (there is no adapter) and for a job saved before
    the setting existed, which is a LoRA — the default the schema gives it.
    """
    if config.get("method", "lora") != "lora":
        return ""
    return str((config.get("hyper") or {}).get("network") or "lora")


def readable(config: dict) -> dict:
    """A STORED config this build can validate: every dataset query's tree
    with the keys today's condition models no longer declare taken out.

    `query.prune_unknown` says why that is right for a file and wrong for a
    request. Exported rather than private because it is the pair of
    `_fill_defaults` — the same problem from the other side — and both belong
    to anything that reads a config some other build wrote.
    """
    queries = config.get("queries")
    if not isinstance(queries, list):
        return config
    out = dict(config)
    out["queries"] = [
        {**qd, "tree": prune_query(qd["tree"])}
        if isinstance(qd, dict) and isinstance(qd.get("tree"), dict) else qd
        for qd in queries
    ]
    return out


def _fill_defaults(stored: dict, defaults: dict) -> dict:
    """`stored` with any key it never had taken from `defaults` (recursively)."""
    out = dict(defaults)
    for key, value in stored.items():
        base = defaults.get(key)
        out[key] = (_fill_defaults(value, base)
                    if isinstance(value, dict) and isinstance(base, dict)
                    else value)
    return out


def _config_changes(before: dict, after: dict, prefix: str = "") -> list[dict]:
    """Flat old→new list of what differs between two job configs.

    Nested dicts recurse into dotted names (`hyper.batch_size`); anything
    else — lists of queries, prompt sets — is compared as a whole and
    summarized, because "3 queries → 4 queries" is what a reader wants from
    a timeline entry, not a JSON diff.
    """
    out: list[dict] = []
    for key in sorted(set(before) | set(after)):
        old_v, new_v = before.get(key), after.get(key)
        if old_v == new_v:
            continue
        name = f"{prefix}{key}"
        if isinstance(old_v, dict) and isinstance(new_v, dict):
            out += _config_changes(old_v, new_v, f"{name}.")
        else:
            out.append({"field": name, "old": _fmt_value(old_v),
                        "new": _fmt_value(new_v)})
    return out


def _fmt_value(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "on" if v else "off"
    if isinstance(v, list):
        return f"{len(v)} entr{'y' if len(v) == 1 else 'ies'}"
    if isinstance(v, dict):
        return f"{len(v)} setting{'' if len(v) == 1 else 's'}"
    text = str(v)
    return text if len(text) <= 60 else text[:59] + "…"


def _pid_alive(pid: int) -> bool:
    return procs.pid_alive(pid)


def _log_tail(path: Path, limit: int = 300) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 4096))
            text = f.read().decode("utf-8", "replace")
        lines = [ln for ln in text.strip().splitlines() if ln.strip()]
        return lines[-1][:limit] if lines else ""
    except OSError:
        return ""

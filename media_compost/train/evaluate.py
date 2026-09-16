"""Evaluation runs: generate images with a base model + stacked LoRAs.

Same file-based philosophy as training jobs, but much lighter: each run is a
folder ``training/_eval/<uid>/`` holding ``spec.json`` (the resolved request,
including the seed actually used), ``state.json`` (written by the generator
process), ``images/p<i>.png`` and ``log.txt``. The generator is
``train/scripts/generate.py`` in the dedicated training env. One generation
runs at a time (GPU-bound); status is derived lazily from ``state.json`` + a
liveness check, so no tick thread is needed.

``training/_eval`` has no ``job.json``, so the training job scan never picks
it up.
"""

from __future__ import annotations

import random
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from media_compost.hub import hf, pipeline_files
from . import gpu as gputil
from . import paths as tp
from . import procs
from .manager import TrainingConflict, TrainingError
from .paths import TRAIN_SCRIPTS, interpreter
from .models import adapter_family, model_spec


def _has_backbone(folder: Path) -> bool:
    """Whether `folder` holds a full finetune's weights.

    A finetune is written as ONE subfolder named after the component it
    replaces (`unet`, `transformer` — `BaseEngine.save_full`), so that is
    what identifies one from the outside. The app cannot ask the engine: the
    engines live in the trainer's own venv and import torch.
    """
    try:
        return any(d.is_dir() and (d / "config.json").is_file()
                   for d in folder.iterdir())
    except OSError:
        return False


def _fits(trained_on: str, base_model: str) -> bool:
    """Whether an adapter trained on `trained_on` may be applied to
    `base_model` — the same network, not the same entry.

    A custom model added on the Models tab is a finetune of a built-in, and
    an adapter is a set of deltas on that built-in's layers: it fits plain
    SDXL, every SDXL finetune, and adapters trained on any of them. Refusing
    anything but an exact key match meant a LoRA trained on a custom model
    could only ever be used with that one entry.
    """
    return adapter_family(trained_on) == adapter_family(base_model)


_EVAL_DIRNAME = "_eval"

# Phases in which a run owns the GPU (everything between spawn and the last
# image); outside them a live process is only keeping its model warm.
_RENDERING_PHASES = ("starting", "loading_model", "loading_loras", "generating")

# Most images one generation may ask for (batches x batch size).
_MAX_IMAGES = 400

# How long a cancelled generator gets to stop on its own before it is killed.
# Long enough for the step callback to notice and unwind, short enough that a
# machine brought to its knees is released promptly.
_CANCEL_GRACE_SECONDS = 5.0


def _now() -> float:
    return time.time()


def _should_offload(spec_m) -> bool:
    """Whether this model's weights are big enough for the machine to need
    them shuttled rather than resident.

    The threshold is a fraction of total RAM rather than a fixed size: the
    same 15 GB model is comfortable on 64 GB and hopeless on 16. Above it,
    residency means swapping, which costs far more than any transfer.

    What offloading costs is worth knowing before moving this number, because
    it is NOT a constant — it is transfer time against per-step compute, so
    the heavier the model the less it matters. Measured here (MPS, bf16,
    512 px, resident -> offloaded):

      FLUX.2, 8 steps:   30.2 -> 36.1 s   peak GPU 16.9 -> 1.1 GB   (+20%)
      Chroma, 6 steps:   62.4 -> 64.9 s                             (+4%)

    So the models this actually fires for are the ones that pay least for it.
    """
    weights = float(getattr(spec_m, "backbone_gb", 0) or 0) + \
        float(getattr(spec_m, "aux_gb", 0) or 0)
    if weights <= 0:
        return False
    try:
        mem = gputil.system_memory()
        total = mem[1] if mem else None
    except Exception:  # noqa: BLE001 - a probe must not decide by crashing
        total = None
    if not total:
        return False
    return weights > total * 0.35


class EvalManager:
    def __init__(self, lib):
        self.ctx = lib          # a `Trainer` — see media_compost.train/__init__
        self.dir = lib.dir
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._proc_uid: str | None = None

    # ---- store ---------------------------------------------------------

    def _root(self) -> Path:
        return self.dir / _EVAL_DIRNAME

    def _dir(self, uid: str) -> Path:
        return self._root() / uid

    def _read_spec(self, uid: str) -> dict:
        spec = tp.read_json(self._dir(uid) / "spec.json")
        if spec is None:
            raise TrainingError(f"unknown evaluation run {uid}")
        return spec

    # ---- LoRA catalog -----------------------------------------------------

    def available_loras(self) -> list[dict]:
        """Every usable LoRA weight set: each completed LoRA job's final
        output, plus its surviving step checkpoints (step=None marks the
        final weights; checkpoints carry their step) — and the LoRAs added
        by hand on the Models tab, which have no job and carry `user_key`
        instead (they were listed there and nowhere else for a while)."""
        from . import usermodels

        out = []
        for lo in usermodels.read_loras(self.dir):
            out.append({"job_uid": "", "user_key": lo.key, "name": lo.label,
                        "model": lo.model, "step": None, "final_step": 0})
        for rec in self.ctx.jobs.list_jobs():
            if rec.get("method") != "lora":
                continue
            jd = tp.job_dir(self.dir, rec["uid"])
            base = {
                "job_uid": rec["uid"],
                "name": rec.get("name", rec["uid"]),
                "model": rec.get("model", ""),
            }
            outdir = jd / "output"
            if rec.get("status") == "completed" and outdir.is_dir() \
                    and any(outdir.iterdir()):
                out.append({**base, "step": None,
                            "final_step": int(rec.get("total_steps") or 0)})
            cdir = tp.checkpoints_dir(jd)
            if cdir.is_dir():
                steps = []
                for d in cdir.iterdir():
                    if d.is_dir() and d.name.startswith("step-"):
                        try:
                            steps.append(int(d.name.split("-", 1)[1]))
                        except ValueError:
                            continue
                for s in sorted(steps, reverse=True):
                    out.append({**base, "step": s, "final_step": 0})
        return out

    def available_finetunes(self) -> list[dict]:
        """Every usable FULL finetune: each finished full-finetune job's
        output, plus its surviving step checkpoints (step=None marks the
        final weights).

        A finetune is not an adapter and cannot be stacked on anything — it
        IS the weights. Which is why it is a list of its own rather than more
        rows in `available_loras`: picking one REPLACES the base model's
        backbone, and picking two is not a thing that means anything.
        """
        out = []
        for rec in self.ctx.jobs.list_jobs():
            # Everything that is not an adapter job, rather than "full"
            # exactly: a record written before the field existed says
            # nothing, and what settles it either way is whether a backbone
            # is actually on disk.
            if rec.get("method") == "lora":
                continue
            jd = tp.job_dir(self.dir, rec["uid"])
            base = {
                "job_uid": rec["uid"],
                "name": rec.get("name", rec["uid"]),
                "model": rec.get("model", ""),
            }
            outdir = jd / "output"
            if rec.get("status") == "completed" and _has_backbone(outdir):
                out.append({**base, "step": None,
                            "final_step": int(rec.get("total_steps") or 0)})
            cdir = tp.checkpoints_dir(jd)
            if cdir.is_dir():
                steps = []
                for d in cdir.iterdir():
                    if not d.is_dir() or not d.name.startswith("step-"):
                        continue
                    # `checkpoints/last` is the resume point and not a step;
                    # a step folder that holds no backbone is a LoRA-shaped
                    # one from a job that was a LoRA job when it wrote it.
                    try:
                        step = int(d.name.split("-", 1)[1])
                    except ValueError:
                        continue
                    if _has_backbone(d):
                        steps.append(step)
                for st in sorted(steps, reverse=True):
                    out.append({**base, "step": st, "final_step": 0})
        return out

    def finetune_path(self, job_uid: str, base_model: str,
                      step: int | None) -> str:
        """The weight directory of a full finetune's output or checkpoint.

        Refused for a base model it does not fit, on the same rule adapters
        use: a finetune of SDXL is SDXL's own layers with different numbers
        in them, so it can stand in for any SDXL — and for nothing else.
        """
        rec = self.ctx.jobs.get(job_uid)  # TrainingError -> 404
        if rec.get("model") and not _fits(rec["model"], base_model):
            raise TrainingConflict(
                f"finetune \"{rec.get('name') or job_uid}\" was trained on "
                f"{rec['model']} — it can't stand in for {base_model}"
            )
        jd = tp.job_dir(self.dir, job_uid)
        d = (tp.checkpoints_dir(jd) / f"step-{step:06d}") if step is not None \
            else (jd / "output")
        if not _has_backbone(d):
            raise TrainingConflict(
                f"finetune \"{rec.get('name') or job_uid}\" has no weights "
                f"at {'step ' + str(step) if step is not None else 'its end'}"
            )
        return str(d)

    def _job_name(self, job_uid: str) -> str:
        try:
            return self.ctx.jobs.get(job_uid).get("name") or job_uid
        except TrainingError:
            return job_uid

    def user_lora_path(self, key: str, base_model: str) -> str:
        """The file or folder a hand-added LoRA points at, for `base_model`."""
        from . import usermodels

        for lo in usermodels.read_loras(self.dir):
            if lo.key != key:
                continue
            if lo.model and not _fits(lo.model, base_model):
                raise TrainingConflict(
                    f"LoRA \"{lo.label}\" is for {lo.model} — it can't be "
                    f"applied to {base_model}")
            if not Path(lo.path).exists():
                raise TrainingConflict(
                    f"LoRA \"{lo.label}\" is missing from {lo.path}")
            return lo.path
        raise TrainingError(f"unknown LoRA {key!r}")

    def lora_path(self, job_uid: str, base_model: str,
                  step: int | None) -> str:
        """Weight dir for a job's final output (step=None) or a checkpoint."""
        rec = self.ctx.jobs.get(job_uid)  # TrainingError -> 404
        if rec.get("model") and not _fits(rec["model"], base_model):
            raise TrainingConflict(
                f"LoRA \"{rec.get('name') or job_uid}\" was trained on "
                f"{rec['model']} — it can't be applied to {base_model}"
            )
        jd = tp.job_dir(self.dir, job_uid)
        if step is not None:
            d = tp.checkpoints_dir(jd) / f"step-{step:06d}"
            if not d.is_dir():
                raise TrainingConflict(
                    f"checkpoint at step {step} no longer exists")
            return str(d)
        outdir = jd / "output"
        if not outdir.is_dir() or not any(outdir.iterdir()):
            raise TrainingConflict(
                f"training job {job_uid} has no finished LoRA output")
        return str(outdir)

    # ---- runs ------------------------------------------------------------

    def list_runs(self) -> list[dict]:
        runs = []
        root = self._root()
        if root.is_dir():
            for d in root.iterdir():
                spec = tp.read_json(d / "spec.json")
                if spec is not None:
                    runs.append(self._with_status(d.name, spec))
        runs.sort(key=lambda r: r.get("created_at", 0), reverse=True)
        self.pump()
        return runs

    def get(self, uid: str) -> dict:
        out = self._with_status(uid, self._read_spec(uid))
        self.pump()
        return out

    def _with_status(self, uid: str, spec: dict) -> dict:
        d = self._dir(uid)
        state = tp.read_json(d / "state.json") or {}
        phase = state.get("phase") or "starting"
        if phase in ("completed", "failed", "canceled"):
            status = phase
        elif phase == "queued":
            # Waiting for its turn: no process yet, which must not be mistaken
            # for one that died.
            status = "queued"
        else:
            pid = state.get("pid")
            with self._lock:
                mine = self._proc is not None and self._proc_uid == uid \
                    and self._proc.poll() is None
            alive = mine or (pid and _pid_alive(int(pid)))
            status = "running" if alive else "failed"
        images = []
        idir = d / "images"
        if idir.is_dir():
            images = sorted(f.name for f in idir.iterdir()
                            if f.suffix == ".png")
        out = dict(spec)
        out.update({
            "uid": uid,
            "status": status,
            "phase": phase if status == "running" else "",
            "error": state.get("error") or "",
            "images": images,
            # Wall time the run took (or has taken so far).
            "elapsed": float(state.get("elapsed") or 0.0),
            # Where the current batch is in its denoising. Deliberately NOT
            # called `steps`: that is already the spec's sampler-step count,
            # which the card shows as a chip, and overwriting it would make a
            # finished run report the last step it happened to reach.
            "cur_step": (int(state.get("step") or 0)
                         if status == "running" else 0),
        })
        return out

    def generate(self, *, model: str, loras: list[dict], prompt: str,
                 negative: str, width: int, height: int, seed: int | None,
                 steps: int, cfg_scale: float, count: int, batch: int = 1,
                 username: str, finetune: Optional[dict] = None) -> str:
        # Publish user-added models first — an Evaluate run may name one, and
        # this manager has no request to have done it.
        from . import usermodels

        usermodels.refresh(self.dir)
        spec_m = model_spec(model)
        if spec_m is None:
            raise TrainingError(f"unknown model {model!r}")
        # An empty prompt is legitimate: the unconditional image is how you see
        # what a LoRA does on its own.
        # The app asks for batches x batch size, so the total is no longer a
        # single-digit affair; the ceiling is here to stop a typo queueing an
        # afternoon of GPU work, not because anything below it is special.
        count = max(1, min(_MAX_IMAGES, int(count)))
        batch = max(1, min(count, min(8, int(batch or 1))))

        interp = interpreter()
        if not interp:
            raise TrainingConflict(
                "training environment not set up — run setup from the Train "
                "tab first")

        # Asked before the lock — see `_training_holds_gpu`.
        blocked = self._training_holds_gpu()
        # Resolved before the lock too: `_job_name` and `lora_path` read the
        # TrainingManager, whose tick calls back into us (`rendering`,
        # `release_idle`) while holding ITS lock. The legal order is
        # training -> eval, so asking training for anything while holding the
        # eval lock is the ABBA deadlock this comment exists to prevent.
        resolved_loras = [
            {
                "job_uid": lo.get("job_uid") or "",
                "user_key": lo.get("user_key") or "",
                # Cards show the training job's name; fall back to the
                # uid only if the job record vanished.
                "name": lo.get("name") or (
                    self._job_name(lo["job_uid"]) if lo.get("job_uid")
                    else lo.get("user_key") or ""),
                # None = the final output; a number = that checkpoint.
                "step": lo.get("step"),
                "weight": float(lo.get("weight", 1.0)),
                "path": (self.user_lora_path(lo["user_key"], spec_m.key)
                         if lo.get("user_key")
                         else self.lora_path(lo.get("job_uid") or "",
                                             spec_m.key, lo.get("step"))),
            }
            for lo in loras
        ]
        # …and the finetune, for the same reason and before the same lock. It
        # is not an adapter: it REPLACES the model's backbone, so it is one
        # entry rather than a list, and the adapters stack on top of it.
        fine: dict = {}
        if finetune and finetune.get("job_uid"):
            fine = {
                "job_uid": finetune["job_uid"],
                "name": finetune.get("name")
                        or self._job_name(finetune["job_uid"]),
                "step": finetune.get("step"),
                "path": self.finetune_path(finetune["job_uid"], spec_m.key,
                                           finetune.get("step")),
            }
        with self._lock:
            uid = tp.new_uid()
            d = self._dir(uid)
            (d / "images").mkdir(parents=True, exist_ok=True)
            spec = {
                "created_at": _now(),
                "username": username,
                "model": spec_m.key,
                "model_info": {
                    "key": spec_m.key,
                    "engine": spec_m.engine,
                    "repo": spec_m.repo,
                    # A user model's repo is a path on this machine, and the
                    # loader needs to be told so — a single-file checkpoint
                    # opens with `from_single_file` and nothing else.
                    "local": bool(spec_m.local),
                    "area": spec_m.default_area,
                    # Load from the cached snapshot when it is complete, so a
                    # generation never asks the hub about files it already has.
                    # A local path has no snapshot — it IS the source.
                    "local_dir": ("" if spec_m.local
                                  else pipeline_files.snapshot_dir_for(
                                      spec_m.repo)),
                    # Keep the components on the CPU and move each to the GPU
                    # only while it runs, when the model is large for this
                    # machine. See _should_offload for what it costs.
                    "offload": _should_offload(spec_m),
                    # A full finetune's weight directory, when one was
                    # picked: the pipeline is built from the base model and
                    # its backbone swapped for what is in here (a finetune
                    # writes the backbone alone, not a whole pipeline).
                    **({"finetune": fine["path"]} if fine else {}),
                },
                "loras": resolved_loras,
                # What that directory IS, for the cards — the model_info
                # entry above is a path, and a path is not a name.
                **({"finetune": fine} if fine else {}),
                "prompt": prompt.strip(),
                "negative": negative.strip(),
                # 0 = automatic -> the model's native size; the resolved value
                # is what gets stored so the card can show it.
                "width": int(width) or spec_m.default_area,
                "height": int(height) or spec_m.default_area,
                # None/absent seed = automatic -> drawn here so it's recorded.
                "seed": int(seed) if seed is not None
                        else random.randrange(2**31),
                "steps": int(steps),
                "cfg": float(cfg_scale),
                "count": count,
                "batch": batch,
            }
            tp.write_json(d / "spec.json", spec)
            # One generation runs at a time (it owns the GPU), but asking for
            # another while one is busy queues it rather than being refused —
            # a queue of prompts is the normal way to use this tab. A training
            # run holds the same GPU, so it queues behind that too.
            if self._busy() or blocked:
                tp.write_json(d / "state.json", {"phase": "queued"})
            else:
                self._spawn(uid)
            return uid

    # ---- queue ---------------------------------------------------------

    def _busy(self) -> bool:
        """A generation is running (called with the lock held)."""
        return self._proc is not None and self._proc.poll() is None

    # ---- the GPU, which the Train tab also wants -------------------------

    def device(self) -> str:
        """The scheduling slot a generation occupies.

        ``generate.py`` takes the machine's first GPU with no pin, which is
        exactly what the training scheduler resolves ``"auto"`` to — so the
        two are comparable, and a training job pinned to a DIFFERENT card is
        genuinely no conflict."""
        devs = gputil.train_devices()
        return devs[0]["id"] if devs else "cpu"

    def rendering(self) -> bool:
        """A generation is actually using the GPU — as opposed to a process
        idling with a warm model, which `release_idle` can simply drop."""
        with self._lock:
            return self._rendering_locked()

    def _rendering_locked(self) -> bool:
        if self._proc is None or self._proc.poll() is not None:
            return False
        for d in self._root().iterdir() if self._root().is_dir() else []:
            state = tp.read_json(d / "state.json") or {}
            if state.get("phase") not in _RENDERING_PHASES:
                continue
            # Only a run OUR live process is writing counts. A crashed run's
            # state.json says "generating" forever (status is derived lazily,
            # never written back), and matching on phase alone made every
            # later warm-idle process read as rendering — which blocked
            # release_idle and parked queued training jobs behind a phantom
            # generation. The generator stamps its pid into every state write,
            # including when it ADOPTS a queued run, so the pid is the tie —
            # plus the run we just spawned, whose first state.json is the
            # manager's own pid-less {"phase": "starting"}.
            if (d.name == self._proc_uid
                    or state.get("pid") == getattr(self._proc, "pid", None)):
                return True
        return False

    def _training_holds_gpu(self) -> bool:
        """Whether a training job occupies the device a generation would use.

        MUST be called without our own lock held. Training holds its lock
        while asking us to `release_idle`, so the one legal order is
        training -> eval; asking the other way round with our lock held is
        how the two threads would wedge each other."""
        try:
            return self.device() in self.ctx.jobs.busy_devices()
        except Exception:  # noqa: BLE001 - never block a generation over this
            return False

    def _spawn(self, uid: str) -> None:
        """Start the generator for a run (called with the lock held)."""
        d = self._dir(uid)
        interp = interpreter()
        if interp is None:
            tp.write_json(d / "state.json", {
                "phase": "failed",
                "error": "training environment not set up",
            })
            return
        argv = [interp, str(TRAIN_SCRIPTS / "generate.py"),
                "--run-dir", str(d)]
        # Same as training: a generation downloads its base model on first
        # use, so pass the token along.
        env = hf.child_env({"PYTORCH_ENABLE_MPS_FALLBACK": "1"})
        tp.write_json(d / "state.json", {"phase": "starting"})
        with open(d / "log.txt", "ab") as log:
            self._proc = subprocess.Popen(
                argv, stdout=log, stderr=subprocess.STDOUT,
                cwd=str(TRAIN_SCRIPTS), env=env,
            )
        self._proc_uid = uid

    def pump(self) -> None:
        """Start the oldest queued run if nothing is running.

        Called from the reads the UI already polls — which is why this manager
        still needs no tick thread — and once more by the training manager the
        moment a run frees the GPU, so a queued generation is not left waiting
        for someone to open the tab.
        """
        blocked = self._training_holds_gpu()   # before the lock, as always
        with self._lock:
            if self._busy() or blocked:
                return
            root = self._root()
            if not root.is_dir():
                return
            waiting = []
            for d in root.iterdir():
                state = tp.read_json(d / "state.json") or {}
                if state.get("phase") != "queued":
                    continue
                spec = tp.read_json(d / "spec.json")
                if spec is not None:
                    waiting.append((spec.get("created_at", 0), d.name))
            if waiting:
                self._spawn(min(waiting)[1])

    def release_idle(self) -> bool:
        """Drop a generator that is only holding its model warm.

        The warm process keeps several GB of GPU memory so the next Generate
        click doesn't reload it — but a training run needs that memory more,
        and on unified memory the two collide as an out-of-memory failure
        rather than a queue. Called before a training job starts.
        """
        with self._lock:
            if self._proc is None or self._proc.poll() is not None:
                return False
            # A run that is actually rendering owns the process and must not
            # be killed; only a warm-idle one is ours to drop.
            if self._rendering_locked():
                return False
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except Exception:  # noqa: BLE001 - it did not go quietly
                # Forgetting a process that is still alive would let the
                # manager spawn a second generator beside it — the GPU
                # collision this method exists to prevent. Kill it, and only
                # let go once it is really gone.
                try:
                    self._proc.kill()
                    self._proc.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    return False
            self._proc = None
            self._proc_uid = None
            return True

    def cancel(self, uid: str) -> None:
        self._read_spec(uid)
        state = tp.read_json(self._dir(uid) / "state.json") or {}
        if state.get("phase") == "queued":
            # Never started, so there is nothing to signal — drop it from the
            # queue and let the next one through.
            tp.write_json(self._dir(uid) / "state.json", {"phase": "canceled"})
            self.pump()
            return
        pid = state.get("pid")
        with self._lock:
            if self._proc is not None and self._proc_uid == uid \
                    and self._proc.poll() is None:
                pid = self._proc.pid
        if pid and _pid_alive(int(pid)):
            procs.terminate(int(pid))
            # SIGTERM only sets a flag the generator checks between denoising
            # steps. Loading a 26 GB model, or decoding a 1024 px latent, sits
            # far longer than that before reaching a check — and the GPU stays
            # pinned the whole time, which is what "cancel did nothing" looks
            # like from the outside. Take it after a short grace.
            threading.Thread(target=self._escalate_kill, args=(int(pid),),
                             daemon=True).start()
        tp.write_json(self._dir(uid) / "state.json",
                      {**state, "phase": "canceled"})

    def _escalate_kill(self, pid: int) -> None:
        """SIGTERM, then SIGKILL if it is still alive. Runs off the request so
        cancelling stays instant from the caller's side."""
        deadline = time.time() + _CANCEL_GRACE_SECONDS
        while time.time() < deadline:
            if not _pid_alive(pid):
                return
            time.sleep(0.25)
        procs.kill(pid)

    def delete(self, uid: str) -> None:
        run = self.get(uid)
        if run["status"] == "running":
            raise TrainingConflict("cancel the generation before removing it")
        if run["status"] == "queued":
            self.cancel(uid)
        shutil.rmtree(self._dir(uid), ignore_errors=True)

    def delete_image(self, uid: str, name: str) -> None:
        """ONE picture out of a run. The Evaluate grid selects per image, so
        removing part of a generation must not take the rest with it; a run's
        `images` is a listing of its folder, so the file going IS the whole
        of it (its cached thumbnails go too). Refused while the generator is
        still writing into that folder. Taking the last image leaves a run
        with nothing to show, which the caller deletes whole instead."""
        run = self.get(uid)
        if run["status"] in ("running", "queued"):
            raise TrainingConflict(
                "cancel the generation before removing its images")
        idir = self._dir(uid) / "images"
        p = idir / name
        if p.is_file():
            p.unlink()
        if idir.is_dir():
            for th in idir.glob(f".thumb-*-{name}.webp"):
                th.unlink(missing_ok=True)


def _pid_alive(pid: int) -> bool:
    return procs.pid_alive(pid)

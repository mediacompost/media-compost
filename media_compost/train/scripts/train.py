"""Training-process entry point.

Runs inside the dedicated ``training`` venv, so it must not import
``media_compost`` — everything it needs
arrives as files in the job dir (``config.json`` + ``manifest.json``) and
everything it reports goes back as files (``state.json``, ``metrics.jsonl``,
``samples/``, ``checkpoints/``). The manager in the server process polls those.

Protocol with the manager:
- ``state.json`` is rewritten atomically with ``{phase, step, total_steps,
  pid, updated_at, error}``. Terminal phases: completed | paused | canceled |
  failed (anything else + a dead process = crash -> failed).
- ``control.json`` may appear with ``{"cmd": "pause"|"cancel"}``; checked once
  per step. Pause saves ``checkpoints/last/`` first; both exit 0.
- SIGTERM is the cancel path for a stuck/unresponsive trainer.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import sys
import threading
import time
from pathlib import Path


class Cancelled(Exception):
    pass


class PauseRequested(Exception):
    pass


def _step_of(path: Path) -> int:
    """The step a `step-000500` snapshot dir holds (0 when unreadable)."""
    try:
        return int(path.name.split("-", 1)[1])
    except (IndexError, ValueError):
        return 0


class JobIO:
    """All file traffic between a trainer and its job dir."""

    def __init__(self, job_dir: Path):
        self.dir = job_dir
        self.total_steps = 0
        # The cadences AS RESOLVED, in steps — set once by the loop and
        # published with every state write, like `total_steps`. They are
        # here because an EPOCH cadence is only a step count once the built
        # manifest has said how long a pass is: the app reading the config
        # instead showed the run counting down to the step figure the epoch
        # setting had overruled, which for a job set to "every 2 epochs" was
        # a number nothing was going to happen at.
        self.ckpt_every = 0
        self.sample_every = 0
        self._term = False
        signal.signal(signal.SIGTERM, self._on_term)

    def _on_term(self, _sig, _frame):
        self._term = True

    # -- inputs --

    def load_config(self) -> dict:
        with open(self.dir / "config.json", encoding="utf-8") as f:
            return json.load(f)

    #: The manifest layouts this trainer knows how to read. The manifest is a
    #: genuine two-process wire format — the backend writes it, this
    #: standalone script (which may never import `media_compost`) reads it —
    #: and a RESUME reads one written by whatever build started the run. It
    #: has carried a `version` since it was introduced and nothing ever looked
    #: at it, so a layout change would have been read as the old one and
    #: trained on quietly wrong data. Add a number here when this side learns
    #: to read a new layout.
    MANIFEST_VERSIONS = (1,)

    def load_manifest(self) -> dict:
        p = self.dir / "manifest.json"
        if not p.exists():
            return {"items": [], "groups": [], "buckets": [], "tag_freq": {}}
        with open(p, encoding="utf-8") as f:
            manifest = json.load(f)
        version = manifest.get("version", 1)
        if version not in self.MANIFEST_VERSIONS:
            raise SystemExit(
                f"this dataset manifest is version {version} and this trainer "
                f"reads {', '.join(str(v) for v in self.MANIFEST_VERSIONS)}. "
                f"It was written by a different build of Media Compost — "
                f"rebuild the dataset (edit the job and start it again) "
                f"rather than resuming this run."
            )
        return manifest

    # -- state / control --

    def write_architecture(self, blocks: list) -> None:
        """The model's block map, derived from the loaded weights. Written
        at load and again once the execution order is known; the app draws
        it."""
        try:
            with open(self.dir / "architecture.json", "w", encoding="utf-8") as f:
                json.dump({"blocks": blocks}, f)
        except OSError:
            pass

    def write_state(self, phase: str, step: int | None = None,
                    error: str = "", note: str = "",
                    sub: str = "") -> None:
        """`note` is a short human line for the phase — "62 / 162 images",
        the model being fetched. The phases before step 1 can take many
        minutes, and without it the app can only say "preparing"."""
        data = {
            "phase": phase,
            "step": step,
            "total_steps": self.total_steps,
            "ckpt_every": self.ckpt_every,
            "sample_every": self.sample_every,
            "pid": os.getpid(),
            "updated_at": time.time(),
            "error": error,
            "note": note,
            # The in-step phase (batch / forward / backward / update).
            "sub": sub,
        }
        # Per THREAD, not just per process: the progress sampler writes this
        # file alongside the training loop, and one shared temp name would let
        # them interleave into a torn file.
        # Imported here, not at module scope: `atomicio` is a sibling resolved
        # off sys.path, and this module is also loaded BY PATH from the tests'
        # fake trainer, where that entry is not set up.
        import atomicio

        tmp = self.dir / f"state.json.tmp{os.getpid()}-{threading.get_ident()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        atomicio.replace(tmp, self.dir / "state.json")

    def check_control(self) -> None:
        """Apply the manager's pending command: raise PauseRequested/Cancelled,
        or adopt a live total-steps change (``set_steps``) in place."""
        if self._term:
            raise Cancelled()
        path = self.dir / "control.json"
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        cmd = data.get("cmd")
        if cmd in ("pause", "cancel"):
            # How long the command sat unnoticed — the file's mtime is when
            # the manager wrote it. Logged so a slow pause can be split into
            # its parts (noticing it, finishing in-flight work, checkpoint).
            try:
                waited = time.time() - os.path.getmtime(path)
                print(f"{cmd} noticed {waited:.1f}s after it was requested",
                      flush=True)
            except OSError:
                pass
        if cmd == "pause":
            raise PauseRequested()
        if cmd == "cancel":
            raise Cancelled()
        if cmd == "set_steps":
            try:
                steps = int(data.get("steps") or 0)
            except (TypeError, ValueError):
                steps = 0
            if steps > 0:
                self.total_steps = steps
            # Consume the command so a later pause/cancel isn't shadowed.
            try:
                os.remove(self.dir / "control.json")
            except OSError:
                pass

    # -- outputs --

    def append_metric(self, step: int, loss: float, lr: float,
                      lo: float | None = None, hi: float | None = None) -> None:
        # A non-finite loss is recorded as null, not as NaN: `json.dumps`
        # writes a bare `NaN` token, which is not JSON, and every reader after
        # it has to guess — the API turned it into `null` and the loss graph
        # crashed on it.
        def _fin(v):
            return round(v, 6) if v is not None and v == v and abs(v) != float("inf") else None
        rec = {"step": step, "loss": _fin(loss), "lr": lr, "t": round(time.time(), 3)}
        # With gradient accumulation, the spread of the micro-batch losses within
        # this step (min/max) feeds the loss graph's accumulation mode.
        if lo is not None and hi is not None:
            rec["lmin"], rec["lmax"] = _fin(lo), _fin(hi)
        with open(self.dir / "metrics.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    def append_eval(self, step: int, series: dict) -> None:
        """One validation round's scores, appended beside the loss points.

        A record deliberately WITHOUT a ``loss`` key — that is what tells the
        metrics endpoint it is a merge record for the step's training point
        rather than a training step of its own (a bare ``"loss": null`` means
        a diverged step, which this is not). Non-finite scores are recorded as
        null for the reason ``append_metric`` gives.
        """
        def _fin(v):
            return round(v, 6) if v is not None and v == v \
                and abs(v) != float("inf") else None
        rec = {"step": step, "t": round(time.time(), 3)}
        for key in ("val", "stable"):
            if key in series:
                rec[key] = _fin(series[key])
        with open(self.dir / "metrics.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    def append_visits(self, step: int, visits: list[dict]) -> None:
        """One line per optimizer step: the images/prompts/crops the step
        trained on, for the training-data inspector. Best-effort — inspection
        data must never break a run."""
        try:
            with open(self.dir / "visits.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"step": step, "visits": visits}) + "\n")
        except OSError:
            pass

    def sample_dir(self, step: int) -> Path:
        d = self.dir / "samples" / f"step-{step:06d}"
        fresh = not d.exists()
        d.mkdir(parents=True, exist_ok=True)
        if fresh:
            # When this round started rendering. The step alone cannot place a
            # round on a clock — a step-0 baseline happens before the first
            # metric exists, and a resumed run revisits steps it already has.
            try:
                with open(d / "meta.json", "w", encoding="utf-8") as f:
                    json.dump({"started": round(time.time(), 3)}, f)
            except OSError:
                pass
        return d

    def checkpoints(self) -> Path:
        d = self.dir / "checkpoints"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def last_checkpoint(self) -> Path | None:
        p = self.checkpoints() / "last"
        return p if p.is_dir() else None

    def publish_last(self, staged: Path) -> None:
        """Atomically replace ``checkpoints/last/`` with a fully written dir."""
        last = self.checkpoints() / "last"
        old = self.checkpoints() / "last.old"
        if old.exists():
            shutil.rmtree(old)
        import atomicio

        if last.exists():
            atomicio.replace(last, old)
        atomicio.replace(staged, last)
        if old.exists():
            shutil.rmtree(old)

    def snapshot_step(self, step: int, keep_last: int, keep_every: int = 0,
                      every: int = 0) -> Path:
        """Dir for a permanent step snapshot; prunes the others.

        Two independent rules, and a snapshot survives if EITHER keeps it:
        the newest ``keep_last`` of them (a window at the end of the run), and
        every ``keep_every``-th one of the cadence (milestones across the
        whole run — cadence 200 with keep_every 5 means every 1000 steps).
        Either can be 0. The snapshot just written is always kept, so the
        newest state is never only in ``last/``.

        A ``.locked`` marker (set from the app) exempts a snapshot from
        pruning entirely — it neither gets removed nor counts against
        ``keep_last``: a lock means "this one stays", not "this one uses a
        slot".
        """
        d = self.checkpoints() / f"step-{step:06d}"
        d.mkdir(parents=True, exist_ok=True)
        snaps = sorted(
            p for p in self.checkpoints().iterdir()
            if p.is_dir() and p.name.startswith("step-")
            and not (p / ".locked").is_file()
        )
        keep: set[Path] = {d}
        if keep_last > 0:
            keep.update(snaps[-keep_last:])
        if keep_every > 0 and every > 0:
            milestone = every * keep_every
            keep.update(p for p in snaps if _step_of(p) % milestone == 0)
        for old in snaps:
            if old not in keep:
                shutil.rmtree(old, ignore_errors=True)
        return d

    def output_dir(self) -> Path:
        d = self.dir / "output"
        d.mkdir(parents=True, exist_ok=True)
        return d


def _explain(error: str, config: dict) -> str:
    """The trainer's wording for a failure — see `failure.explain`.

    Kept as a name here because the exception handler below reads better for
    it, and because the trainer and the Evaluate generator explain the SAME
    failures: they used to do it differently, and a generation that ran out of
    memory got a raw torch dump where a training run got advice.
    """
    import failure

    return failure.explain(error, config, training=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-dir", required=True)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    io = JobIO(Path(args.job_dir))
    io.write_state("starting")
    try:
        config = io.load_config()
        import loop
        loop.run(io, config, resume=args.resume)
    except PauseRequested:
        # The runner already checkpointed before re-raising.
        try:
            total = time.time() - os.path.getmtime(io.dir / "control.json")
            print(f"pause complete {total:.1f}s after it was requested",
                  flush=True)
        except OSError:
            pass
        io.write_state("paused")
        return 0
    except Cancelled:
        io.write_state("canceled")
        return 0
    except Exception as exc:  # noqa: BLE001 - report, then fail
        import traceback
        traceback.print_exc()
        io.write_state("failed",
                       error=_explain(f"{type(exc).__name__}: {exc}",
                                      io.load_config()))
        return 1
    io.write_state("completed", step=io.total_steps)
    return 0


if __name__ == "__main__":
    # Allow sibling imports (loop, compose, engines/) when launched by
    # absolute path from the server process — and then re-enter through the
    # imported module, NOT this __main__ instance: loop does `from train
    # import PauseRequested`, and running main() from __main__ would create a
    # second copy of those classes whose exceptions their handlers can't catch.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import train as _train

    sys.exit(_train.main())

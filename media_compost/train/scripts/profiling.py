"""Where a training step's seconds go — opt-in, written for one question.

A card that reads 100% busy for two seconds and 0% for the next two is a
loop that is not queueing work while the CPU does something, and nothing in
the ordinary log can say WHAT: the step counter moves, the loss moves, the
GPU sits. This is the instrument for that, and it is off unless asked for,
because the honest way to measure a phase is to `synchronize()` at its end —
which is itself a stall, and a run under measurement must not become the thing
it measures for the whole of its length.

    MEDIA_COMPOST_TRAIN_PROFILE=<n>     profile n steps, from step 3

Two readings, both into the job's own folder and its log:

* a WALL-CLOCK split of every profiled step into the loop's phases —
  `compose` (the prompt and its weights, pure Python), `latents` (the cache
  read and crop), `forward`, `backward`, `bookkeeping` (the loss read and
  the inspector rows), `update` (clip, optimizer, EMA) and `after` (metrics,
  checkpoints, the pause check, everything until the next step begins). The
  device is synchronized at every boundary, so a phase's time is the time
  the run actually waited on it.
* a `torch.profiler` trace of the same steps (`profile-trace.json`, Chrome's
  `about:tracing` or Perfetto reads it) and its two summaries — the kernels
  by device time and the operators by CPU time — printed to the log, so the
  question "is the GPU busy with small kernels, or idle?" has an answer in
  numbers rather than a power reading.

Steps 1 and 2 are skipped: the first holds the block-order hooks and the
allocator's warm-up, and neither is what a run looks like.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

ENV = "MEDIA_COMPOST_TRAIN_PROFILE"
FIRST_STEP = 3
PHASES = ("compose", "latents", "forward", "backward", "bookkeeping",
          "update", "after")


class StepProfiler:
    def __init__(self, job_dir: Path, device: str):
        self.dir = Path(job_dir)
        self.device = str(device)
        try:
            self.steps = int(os.environ.get(ENV, "0") or 0)
        except ValueError:
            self.steps = 0
        self.last = FIRST_STEP + self.steps - 1
        self.step = 0
        self.phase = None
        self.t = 0.0
        self.times: dict[int, dict[str, float]] = {}
        #: Per step and phase, the high-water mark of allocated device
        #: memory reached INSIDE that phase (CUDA only) — the answer to
        #: "which phase does the peak sit in".
        self.peaks: dict[int, dict[str, float]] = {}
        #: The highest allocation this profiler has seen anywhere. It RESETS
        #: the allocator's peak at every phase boundary to attribute it, so
        #: the run's own end-of-run `max_memory_allocated` is only the last
        #: stretch — `_report_peak_memory` takes this as its floor.
        self.high = 0.0
        self._prof = None
        self._done = False

    @property
    def enabled(self) -> bool:
        return self.steps > 0

    def _active(self) -> bool:
        return self.enabled and FIRST_STEP <= self.step <= self.last

    def _sync(self) -> None:
        # torch only where there is a device to wait for: on the CPU the
        # clock is the whole answer, and that is what lets the app's own
        # torch-free venv test the split.
        if self.device.startswith("cuda"):
            import torch

            torch.cuda.synchronize()
        elif self.device.startswith("mps"):
            import torch

            torch.mps.synchronize()

    def _peak_gb(self, reset: bool = False) -> float | None:
        """The high-water mark of allocated device memory since the last
        reset, in GB — CUDA only; None elsewhere. Read at every phase
        boundary and reset at each step's start, so the split can say which
        phase the step's peak sits in, not only how long each took."""
        if not self.device.startswith("cuda"):
            return None
        import torch

        gb = torch.cuda.max_memory_allocated() / 1e9
        self.high = max(self.high, gb)
        if reset:
            torch.cuda.reset_peak_memory_stats()
        return gb

    # -- the loop's calls ---------------------------------------------------

    def begin_step(self, step: int) -> None:
        """Close the previous step's `after` phase and open this step."""
        if not self.enabled:
            return
        self.mark(None)           # ends `after` of the step before
        if self.step == self.last and step == self.last + 1:
            self._finish()
        self.step = step
        if step == FIRST_STEP:
            self._start_trace()
        if self._active():
            self.times[step] = {p: 0.0 for p in PHASES}
            self.peaks[step] = {p: 0.0 for p in PHASES}
            self._peak_gb(reset=True)
        self.mark("compose")

    def mark(self, phase: str | None) -> None:
        """`phase` begins now; whatever was running is charged until now."""
        if not self.enabled:
            return
        if not self._active():
            self.phase = phase
            return
        self._sync()
        now = time.perf_counter()
        if self.phase is not None and self.step in self.times:
            self.times[self.step][self.phase] += now - self.t
            peak = self._peak_gb(reset=True)
            if peak is not None:
                self.peaks[self.step][self.phase] = max(
                    self.peaks[self.step][self.phase], peak)
        self.t = now
        self.phase = phase

    def close(self) -> None:
        """A run ending inside the window still reports what it has."""
        if self.enabled and not self._done:
            self.mark(None)
            self._finish()

    # -- the trace --------------------------------------------------------

    def _start_trace(self):
        try:
            import torch
            from torch.profiler import ProfilerActivity, profile

            acts = [ProfilerActivity.CPU]
            if self.device.startswith("cuda"):
                acts.append(ProfilerActivity.CUDA)
            # NO schedule and no `.step()`: a scheduled profiler clears its
            # events at the end of every cycle, so with the window as one
            # cycle the summary tables came out empty. One plain session
            # over the window, entered here and left in `_finish`, keeps
            # every event.
            self._prof = profile(activities=acts, record_shapes=False,
                                 profile_memory=False, with_stack=False)
            self._prof.__enter__()
        except Exception as exc:  # noqa: BLE001 - a diagnostic never fails a run
            print(f"profiler: torch.profiler unavailable ({exc}); wall-clock "
                  f"split only", flush=True)
            self._prof = None

    def _finish(self) -> None:
        self._done = True
        if self._prof is not None:
            try:
                self._prof.__exit__(None, None, None)
                out = self.dir / "profile-trace.json"
                self._prof.export_chrome_trace(str(out))
                print(f"profiler: trace written to {out}", flush=True)
                key = ("self_device_time_total" if self.device.startswith("cuda")
                       else "self_cpu_time_total")
                ka = self._prof.key_averages()
                print("profiler: top operators by device time", flush=True)
                print(ka.table(sort_by=key, row_limit=20), flush=True)
                print("profiler: top operators by CPU time", flush=True)
                print(ka.table(sort_by="self_cpu_time_total", row_limit=20),
                      flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"profiler: could not write the trace ({exc})", flush=True)
            self._prof = None
        self._report()

    def _report(self) -> None:
        rows = [self.times[s] for s in sorted(self.times) if s in self.times]
        if not rows:
            return
        n = len(rows)
        mean = {p: sum(r[p] for r in rows) / n for p in PHASES}
        total = sum(mean.values()) or 1e-9
        print(f"profiler: {n} step(s) measured, {total:.3f} s a step "
              f"(device synchronized at every phase boundary)", flush=True)
        width = max(len(p) for p in PHASES)
        peaks = [self.peaks[s] for s in sorted(self.peaks)]
        for p in PHASES:
            bar = "#" * int(round(40 * mean[p] / total))
            peak = max(r[p] for r in peaks) if peaks else 0.0
            mem = f"  peak {peak:5.1f} GB" if peak else ""
            print(f"profiler:   {p:<{width}}  {mean[p]:7.3f} s  "
                  f"{100 * mean[p] / total:5.1f}%{mem}  {bar}", flush=True)
        gpu = mean["forward"] + mean["backward"] + mean["update"]
        print(f"profiler:   device-side phases {100 * gpu / total:.0f}% of "
              f"the step; the rest is the loop waiting on the CPU or the "
              f"disk", flush=True)

"""Keep the machine awake while a long job runs — cross-platform, no deps.

A training run is hours of GPU work with no user input, which is exactly what
an idle-sleep timer is built to interrupt: the display sleeping is fine, the
SYSTEM sleeping stops the run mid-step and the next thing the user sees is a
job that made no progress overnight.

One process-wide :class:`KeepAwake`, reference-counted, held while anything
is running:

- macOS: ``caffeinate -i -w <our pid>`` as a child. It is part of the base
  system, needs no entitlement, and — because it WATCHES our pid — the
  assertion dies with us even on SIGKILL, where a released-in-atexit API call
  would leak it.
- Linux: ``systemd-inhibit --what=idle --mode=block``, the documented way to
  ask logind; harmless when systemd isn't the session manager (we simply
  don't get one).
- Windows: ``SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)``
  via ctypes, from a dedicated thread that holds the flag for its lifetime
  (the flag is per-thread, so it must not be set from a worker that exits).

Never raises: a machine that won't hold the assertion is a machine that may
sleep, not a reason to fail a training run.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


class KeepAwake:
    """Reference-counted "don't idle-sleep" assertion."""

    def __init__(self, reason: str = "Media Compost is training") -> None:
        self.reason = reason
        self._lock = threading.Lock()
        self._count = 0
        self._proc: subprocess.Popen | None = None
        self._win_stop: threading.Event | None = None

    # -- public ------------------------------------------------------------

    def acquire(self) -> None:
        with self._lock:
            self._count += 1
            if self._count == 1:
                self._start()

    def release(self) -> None:
        with self._lock:
            if self._count == 0:
                return
            self._count -= 1
            if self._count == 0:
                self._stop()

    def set_active(self, active: bool) -> None:
        """Idempotent form for a poller: hold the assertion iff ``active``."""
        with self._lock:
            want = 1 if active else 0
            if self._count == want:
                # A child that died (a killed caffeinate, a logind restart)
                # is re-spawned rather than silently lost.
                if want and self._proc is not None and self._proc.poll() is not None:
                    self._start()
                return
            self._count = want
            if want:
                self._start()
            else:
                self._stop()

    @property
    def held(self) -> bool:
        return self._count > 0

    # -- platform ----------------------------------------------------------

    def _start(self) -> None:
        try:
            if sys.platform == "darwin":
                # -i: prevent idle SLEEP (not display sleep — the screen may
                # still switch off). -w: exit when our pid does.
                self._proc = subprocess.Popen(
                    ["caffeinate", "-i", "-w", str(os.getpid())],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            elif sys.platform.startswith("linux"):
                self._proc = subprocess.Popen(
                    ["systemd-inhibit", "--what=idle", "--mode=block",
                     "--who=Media Compost", f"--why={self.reason}",
                     "sleep", "infinity"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            elif sys.platform == "win32":
                self._start_windows()
        except Exception:  # noqa: BLE001 - never break a run over this
            self._proc = None

    def _stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001 - it is going away regardless
                pass
        if self._win_stop is not None:
            self._win_stop.set()
            self._win_stop = None

    def _start_windows(self) -> None:  # pragma: no cover - Windows only
        import ctypes

        stop = threading.Event()
        self._win_stop = stop

        def hold() -> None:
            kernel32 = ctypes.windll.kernel32
            # The flag lives on THIS thread, so the thread must outlive the
            # assertion — hence a dedicated one rather than the caller's.
            kernel32.SetThreadExecutionState(
                _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED)
            stop.wait()
            kernel32.SetThreadExecutionState(_ES_CONTINUOUS)

        threading.Thread(target=hold, daemon=True,
                         name="mc-keep-awake").start()

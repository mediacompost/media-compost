"""Cross-platform process liveness and termination.

Both long-running child processes here — the trainer and the Evaluate
generator — are supervised the same way: a record on disk carries the pid,
and the manager asks "is that still alive?" on every tick, then escalates a
cancel the child is ignoring.

Both halves are POSIX idioms that do something ELSE on Windows, and one of
them is destructive:

- ``os.kill(pid, 0)`` is the standard liveness probe on POSIX — signal 0 is
  delivered to nothing and only the permission/existence check runs. Windows
  has no signals: CPython's ``os.kill`` maps anything that is not
  ``CTRL_C_EVENT``/``CTRL_BREAK_EVENT`` onto ``TerminateProcess(handle, sig)``,
  so the *probe* terminates the process it is asking about — with exit code 0,
  which the manager then reads as a clean finish. A training run would die on
  the first tick that looked at it.
- ``signal.SIGKILL`` does not exist on Windows at all, so the escalation path
  raises ``AttributeError`` rather than killing anything.

So liveness is asked of the OS directly (``WaitForSingleObject`` with a zero
timeout — a process object stays unsignalled exactly while it runs, which
avoids the ``STILL_ACTIVE``/exit-code-259 ambiguity ``GetExitCodeProcess``
has), and the two escalation steps collapse onto ``TerminateProcess``.

That collapse is a real, deliberate degradation: on Windows a cancel skips
"ask nicely" and goes straight to a hard kill. The graceful path is
``control.json``, which the trainer polls and which works identically on every
platform — the signal was only ever the backstop for a child that has stopped
reading it. What is lost is the SIGTERM handler in ``train.py`` running before
the process dies, i.e. one last checkpoint on an already-unresponsive trainer.
"""

from __future__ import annotations

import os
import signal
import sys

_WINDOWS = sys.platform == "win32"


def pid_alive(pid: int) -> bool:
    """Whether ``pid`` names a live process. Never signals it."""
    if pid <= 0:
        return False
    if _WINDOWS:
        return _win_alive(pid)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def terminate(pid: int) -> None:
    """Ask ``pid`` to stop (SIGTERM). On Windows this is a hard kill."""
    _signal(pid, signal.SIGTERM)


def kill(pid: int) -> None:
    """Stop ``pid`` outright (SIGKILL). On Windows, same as terminate."""
    _signal(pid, getattr(signal, "SIGKILL", signal.SIGTERM))


def _signal(pid: int, sig: int) -> None:
    if pid <= 0:
        return
    try:
        os.kill(pid, sig)
    except (OSError, SystemError, PermissionError):
        pass


def _win_alive(pid: int) -> bool:  # pragma: no cover - Windows only
    import ctypes

    SYNCHRONIZE = 0x00100000
    WAIT_TIMEOUT = 0x00000102

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(SYNCHRONIZE, False, int(pid))
    if not handle:
        # No handle: either gone, or a process we may not synchronize on.
        # Ask again for the weakest right there is before calling it dead.
        return _win_exists(pid)
    try:
        return kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
    finally:
        kernel32.CloseHandle(handle)


def _win_exists(pid: int) -> bool:  # pragma: no cover - Windows only
    """Fallback when the process cannot be opened for SYNCHRONIZE: ask for the
    weakest right there is. Access-denied still proves it exists."""
    import ctypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    ERROR_ACCESS_DENIED = 5

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,
                                  False, int(pid))
    if handle:
        kernel32.CloseHandle(handle)
        return True
    return kernel32.GetLastError() == ERROR_ACCESS_DENIED

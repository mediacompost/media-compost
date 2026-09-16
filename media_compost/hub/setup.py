"""Run a package's setup commands, then re-exec the process.

The "Run setup" button behind an AI action and behind the training environment
are the same machine: a fixed list of shell commands, run in order with their
output streamed to the UI, and on success a re-exec so freshly installed
packages and freshly created venvs are actually seen.

**Commands never come from a request.** Callers pass a list they own — a
plugin manifest's, or the trainer's own — and `cwd` is likewise the caller's,
because after the split there is no single directory that `scripts/` hangs off.

Two placeholders: ``{python}`` is the interpreter running the server, and
``{pip}`` is how pip is driven for its environment (:func:`pip_spec` — plain
``-m pip``, or ``uv pip`` where the venv was made by uv and has none).

BOTH ARRIVE SHELL-QUOTED (:func:`quote`), because the commands run through a
shell and an interpreter path routinely contains a space: the default Windows
install locations are under ``Program Files`` and under a user profile that
is a person's full name, and a checkout under ``My Projects`` is the same
thing on a Mac. Unquoted, the shell reads the first word as the program and
the rest as arguments, so every "Run setup" on such a machine failed with the
shell's own confusing complaint about a path that had been cut at its space.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import threading


def quote(arg: str) -> str:
    """One argument, safe to drop into a ``shell=True`` command line.

    Two shells, two grammars: ``shlex.quote`` is POSIX ``/bin/sh``, and on
    Windows the shell is ``cmd.exe``, where the quoting rules are MSVCRT's —
    which is exactly what :func:`subprocess.list2cmdline` writes. Neither
    quotes a path that needs no quoting, so the common case is unchanged and
    the logs read as they always did.
    """
    if os.name == "nt":
        return subprocess.list2cmdline([arg])
    return shlex.quote(arg)


#: How to invoke pip for an interpreter's environment, memoized per path —
#: the probe is a subprocess and every setup command line would repeat it.
_PIP_SPEC: dict[str, str] = {}


def pip_spec(python: str) -> str:
    """What ``{pip}`` expands to for ``python``'s environment.

    ``<python> -m pip`` when that environment has pip — the default, true of
    every venv the stdlib creates, and deliberately still the first choice
    when uv is also installed: having uv on PATH must not change behavior
    for anyone. A venv made by ``uv venv`` ships NO pip, and there the
    fallback is ``uv pip --python <python>``, which installs into an
    environment from outside. With neither, the pip form is returned anyway
    so the failure is pip's own clear "No module named pip" rather than a
    silently skipped step.
    """
    if python not in _PIP_SPEC:
        import shutil

        probe = subprocess.run([python, "-m", "pip", "--version"],
                               capture_output=True)
        if probe.returncode != 0 and shutil.which("uv"):
            _PIP_SPEC[python] = f"uv pip --python {quote(python)}"
        else:
            _PIP_SPEC[python] = f"{quote(python)} -m pip"
    return _PIP_SPEC[python]


class SetupRun:
    def __init__(self, key: str, commands: list[str], cwd: str):
        self.key = key
        self.commands = commands
        self.cwd = cwd
        self.log = ""
        self.running = True
        self.ok = False
        self.error = ""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            for raw in self.commands:
                cmd = raw.replace("{python}", quote(sys.executable))
                if "{pip}" in cmd:
                    cmd = cmd.replace("{pip}", pip_spec(sys.executable))
                self.log += f"$ {cmd}\n"
                proc = subprocess.Popen(
                    cmd, shell=True, cwd=self.cwd,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                )
                assert proc.stdout is not None
                for line in proc.stdout:
                    self.log += line
                    self.log = self.log[-200_000:]
                proc.wait()
                if proc.returncode != 0:
                    self.error = f"command failed (exit {proc.returncode})"
                    self.log += f"\n✗ {self.error}\n"
                    return
            self.ok = True
            self.log += "\n✓ Setup finished — restarting…\n"
            threading.Thread(target=restart_process, daemon=True).start()
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            self.error = str(exc)[:300]
            self.log += f"\n✗ {self.error}\n"
        finally:
            self.running = False


def restart_argv(orig_argv: list[str]) -> list[str]:
    """The interpreter arguments a setup restart re-execs with.

    Built from ``sys.orig_argv`` — the interpreter's ORIGINAL argv, in which a
    ``-m pkg.module`` launch survives verbatim. Rebuilding from ``sys.argv``
    cannot get that right: there the ``-m`` is already resolved to the module's
    FILE, and exec'ing that file loses the package context — a server started
    as ``python -m media_compost.cli serve`` came back as ``python …/cli.py
    serve`` and died on its first relative import, so "Restarting…" ended with
    no server at all. (The earlier rebuild special-cased only ``__main__.py``,
    i.e. ``python -m uvicorn``, whose file-path form shadows stdlib
    ``logging``; ``orig_argv`` covers every spelling at once.)

    ``--open`` is stripped: a setup restart must NEVER re-open the browser —
    whoever pressed the button is already looking at a tab (that is where the
    button is), and whoever ran ``serve --open`` from a terminal asked for one
    tab, not one per setup."""
    return [a for a in orig_argv[1:] if a != "--open"]


def restart_process() -> None:  # pragma: no cover - replaces the process
    """Re-exec in place (same launch command) so new packages are seen.

    No fd cleanup: Python opens sockets close-on-exec (PEP 446), so a listening
    socket does not survive the exec and the fresh bind succeeds. (Closing fds
    here instead crashes uvloop — the main thread is still polling them, and
    libuv aborts on the closed kqueue fd before execv.)"""
    import sys as _sys
    import time as _time

    _time.sleep(1.0)   # let the status response reach the client
    argv = restart_argv(_sys.orig_argv)
    os.execv(_sys.executable, [_sys.executable] + argv)

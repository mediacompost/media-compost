"""The setup runner's placeholder contract: `{python}` and `{pip}`.

`hub/setup.py` is what every "Run setup" button goes through, and `{pip}` is
what lets a uv-made venv — which ships no pip — run the same commands.
Stdlib only, like everything in hub: the core suite runs on a base-only
install.
"""

from __future__ import annotations

import os
import shlex
import shutil
import sys
from pathlib import Path

import pytest

from media_compost.hub import setup as hub_setup


def test_pip_spec_prefers_pip_and_falls_back_to_uv(tmp_path, monkeypatch):
    """pip first — uv on PATH must not change behavior for an env that has
    pip — uv only where the env has none, and the pip form with neither, so
    the failure is pip's own clear error."""
    monkeypatch.setattr(hub_setup, "_PIP_SPEC", {})
    assert hub_setup.pip_spec(sys.executable) == f"{sys.executable} -m pip"

    if sys.platform == "win32":
        return  # the fake pip-less interpreter below is a shell script

    fake = tmp_path / "python"
    fake.write_text("#!/bin/sh\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setattr(shutil, "which",
                        lambda name: "/opt/uv" if name == "uv" else None)
    assert hub_setup.pip_spec(str(fake)) == f"uv pip --python {fake}"

    fake2 = tmp_path / "python2"
    fake2.write_text("#!/bin/sh\nexit 1\n")
    fake2.chmod(0o755)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert hub_setup.pip_spec(str(fake2)) == f"{fake2} -m pip"


# ---- a path with a space in it ---------------------------------------------
#
# These commands run through a SHELL, and the interpreter path is interpolated
# into the line. The default Windows install locations sit under `Program
# Files` and under a user profile named after a person, so a space in that
# path is the ordinary case rather than an exotic one — and unquoted, the
# shell reads the line as a program name cut at the first space. Every "Run
# setup" on such a machine failed, naming a path that does not exist.


def test_a_spaced_interpreter_path_is_quoted(monkeypatch, tmp_path):
    monkeypatch.setattr(hub_setup, "_PIP_SPEC", {})
    spaced = str(_spaced_python(tmp_path))
    spec = hub_setup.pip_spec(spaced)
    assert spec.endswith(" -m pip")
    # The whole path is ONE shell word — the test that fails on the bug.
    assert shlex.split(spec)[0] == spaced


def test_a_path_needing_no_quoting_is_left_alone():
    """The logs are read by people, so the common case must not grow quotes."""
    assert hub_setup.quote("/usr/bin/python3") == "/usr/bin/python3"


def test_a_spaced_interpreter_actually_runs_its_command(monkeypatch, tmp_path):
    """End to end through the real runner: the command has to EXECUTE, which
    is what the quoting buys and what nothing else here would notice."""
    monkeypatch.setattr(hub_setup, "restart_process", lambda: None)
    monkeypatch.setattr(hub_setup, "_PIP_SPEC", {})
    monkeypatch.setattr(sys, "executable", str(_spaced_python(tmp_path)))

    run = hub_setup.SetupRun(
        "t", ["{python} -c \"print('ran')\""], cwd=str(tmp_path))
    run._thread.join(timeout=120)
    assert run.ok, run.log
    assert "ran" in run.log


def _spaced_python(tmp_path: Path) -> Path:
    """A real, working interpreter reachable by a path containing a space."""
    if sys.platform == "win32":
        pytest.skip("the link below is a POSIX symlink")
    d = tmp_path / "a dir with spaces"
    d.mkdir()
    link = d / "python"
    link.symlink_to(sys.executable)
    return link


def test_setup_run_expands_both_placeholders(monkeypatch):
    """`{python}` becomes the running interpreter and `{pip}` its pip
    invocation, and the expanded command is what the streamed log shows.
    `restart_process` is stubbed out — the real one re-execs THIS process."""
    monkeypatch.setattr(hub_setup, "restart_process", lambda: None)
    monkeypatch.setattr(hub_setup, "_PIP_SPEC", {})

    run = hub_setup.SetupRun(
        "t", ["{python} -c \"print('py ok')\"", "{pip} --version"], cwd=".")
    run._thread.join(timeout=120)
    assert not run.running
    assert run.ok, run.log
    assert "py ok" in run.log
    assert f"$ {sys.executable} -m pip --version" in run.log


def test_the_restart_reuses_the_original_launch_command_less_open():
    """`restart_argv` keeps a `-m pkg.module` launch VERBATIM and strips only
    `--open`. It reads `sys.orig_argv` because `sys.argv[0]` has already
    resolved the -m to the module's FILE — exec'ing that file loses the
    package context, which is how `python -m media_compost.cli serve` said
    "Restarting…" and then died on cli.py's first relative import."""
    assert hub_setup.restart_argv(
        ["/py", "-m", "media_compost.cli", "serve", "--open", "--port", "80"],
    ) == ["-m", "media_compost.cli", "serve", "--port", "80"]
    # A console-script launch (shebang: interpreter + script path) survives too.
    assert hub_setup.restart_argv(
        ["/py", "/venv/bin/media-compost", "serve"],
    ) == ["/venv/bin/media-compost", "serve"]


def test_a_dash_m_relaunch_actually_comes_back():
    """End to end: the argv `restart_argv` builds for a `-m media_compost.cli`
    launch starts a process that LIVES — the old rebuild produced one that
    crashed on import before reaching any command."""
    import subprocess

    argv = hub_setup.restart_argv(
        [sys.executable, "-m", "media_compost.cli", "--help"])
    out = subprocess.run([sys.executable] + argv,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert "serve" in out.stdout


# ---- telemetry --------------------------------------------------------------


def test_importing_the_hub_package_turns_hf_telemetry_off():
    """OFF BY THE TIME huggingface_hub CAN READ IT, which is at its import.

    `send_telemetry` posts to huggingface.co on a background thread and
    diffusers/transformers call it on ordinary paths like `from_pretrained`;
    it is ON unless `HF_HUB_DISABLE_TELEMETRY` says otherwise. This app is
    offline-first, so the answer is no — and the place it is answered has to
    be one every hub-touching path already goes through, which is the package
    itself (`hub/__init__` imports `hf`, so any submodule import runs it).

    Checked in a CHILD process: this one has imported the hub long ago and
    would pass whatever the code said.
    """
    import subprocess

    out = subprocess.run(
        [sys.executable, "-c",
         "import os;"
         " from media_compost.hub import cache;"
         " print(os.environ.get('HF_HUB_DISABLE_TELEMETRY'))"],
        capture_output=True, text=True, check=True,
        env={k: v for k, v in os.environ.items()
             if k != "HF_HUB_DISABLE_TELEMETRY"},
    )
    assert out.stdout.strip() == "1", out.stderr


def test_a_deliberate_setting_is_left_alone():
    """`setdefault`, not `=`: somebody who has turned it back on means it."""
    import subprocess

    out = subprocess.run(
        [sys.executable, "-c",
         "import os;"
         " from media_compost.hub import hf;"
         " print(os.environ.get('HF_HUB_DISABLE_TELEMETRY'))"],
        capture_output=True, text=True, check=True,
        env={**os.environ, "HF_HUB_DISABLE_TELEMETRY": "0"},
    )
    assert out.stdout.strip() == "0", out.stderr


def test_a_child_that_reaches_the_hub_is_told_too():
    """`hf.child_env()` carries it, for a subprocess that does not import our
    package at all — the trainer, the download worker, a dedicated venv."""
    from media_compost.hub import hf

    assert hf.child_env().get("HF_HUB_DISABLE_TELEMETRY") == "1"

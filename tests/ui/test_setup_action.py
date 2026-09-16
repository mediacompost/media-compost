"""Setting an AI action up is ONE command, and the button runs that command.

The command is `-m media_compost.ui.plugins.setup_action` — a module in the
package, never a checkout-relative file: a wheel install has no `scripts/`
directory, and `scripts/setup_action.py` (gone now) is exactly what every
"Run setup" failed on there with a missing-file error.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from media_compost.ui.plugins import registry
from media_compost.ui.server.routers import ml as ml_router

ARGV = [sys.executable, "-m", "media_compost.ui.plugins.setup_action"]


def test_the_setup_button_runs_the_script_and_nothing_else():
    """The whole point of the script: the panel behind "Run setup" is a Run
    and a log because there is ONE command behind it, and it is the same
    command somebody would type. If this grows a second entry, the button and
    the terminal have started doing different things."""
    recorded = {}

    class _Fake:
        def __init__(self, key, commands, cwd):
            recorded["key"] = key
            recorded["commands"] = commands
            self.running = True
            self.ok = False
            self.error = ""
            self.log = ""

    old = ml_router._SetupRun
    ml_router._SetupRun = _Fake
    try:
        ml_router._setups.clear()
        ml_router.run_setup("canny")
    finally:
        ml_router._SetupRun = old
        ml_router._setups.clear()

    assert recorded["commands"] == [
        "{python} -m media_compost.ui.plugins.setup_action canny"]


def test_every_action_the_script_lists_is_one_it_can_set_up():
    """`--list` is what a person reads to find the argument; a key printed
    there that the script then rejects is the worst kind of help."""
    out = subprocess.run(ARGV + ["--list"],
                         capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr
    keys = [ln.split()[0] for ln in out.stdout.splitlines() if ln.strip()]
    assert keys, out.stdout
    for key in keys:
        assert registry.plugin_by_key(key) is not None, key
    assert {p.key for p in registry.plugins()} == set(keys)


def test_an_unknown_action_says_so_rather_than_doing_nothing():
    out = subprocess.run(ARGV + ["no_such_plugin"],
                         capture_output=True, text=True, timeout=180)
    assert out.returncode != 0
    assert "--list" in (out.stderr + out.stdout)


@pytest.mark.parametrize("key", [p.key for p in registry.plugins()])
def test_the_script_plans_something_for_every_action(key):
    """Setup is offered for every plugin now (`setup_key` is unconditional),
    so every plugin must have something for the script to do — packages,
    weights from the hub, its own fetcher, or a warm-up load."""
    plug = registry.plugin_by_key(key)
    from media_compost.ui.plugins import framework as fw

    has_step = bool(fw.setup_commands(plug.manifest)) \
        or bool(plug.manifest.sources) \
        or callable(getattr(plug.module, "fetch_weights", None)) \
        or bool(plug.models())
    assert has_step, f"{key} has no setup step at all"

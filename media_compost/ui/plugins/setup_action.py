#!/usr/bin/env python3
"""Set up ONE AI action, end to end: packages, environment, weights.

    python -m media_compost.ui.plugins.setup_action insightface_faces
    python -m media_compost.ui.plugins.setup_action --list

This is what the "Run setup" button runs, so the button and the terminal do
exactly the same thing — the app's setup panel is one button and a log,
because there is one command behind it. It is a MODULE in the package rather
than a file in ``scripts/`` because a wheel install has no checkout: the
button used to run ``scripts/setup_action.py``, which the wheel never
shipped, so on any non-editable install every setup failed with a
missing-file error.

**ONE PARAMETERISED SCRIPT, NOT ONE FILE PER ACTION.** Thirty scripts would
be thirty copies of the same four steps, drifting apart the moment one of them
learns something (which CUDA index, how pip is driven in a uv-made venv, that
the weights must come after the packages). This repo has already paid for
that lesson once: three `setup-<env>-env.sh` files were the implementation of
the env setup until they drifted from the `requirements-<env>-env.txt` files
that claimed to mirror them, and the answer was one cross-platform
`setup_env.py` with the shell scripts as thin wrappers. The per-action script
is `setup_action.py <key>`, and the key is the argument.

The four steps, in order, because each needs the one before it:

1. **Packages and environment.** `framework.setup_commands` already produces
   these and already owns the platform differences: a dedicated-env plugin
   routes to `setup_env.py <env>` (which picks the CUDA / ROCm / CPU torch
   index for this machine), a main-env plugin gets a `pip install` plus, when
   torch is among its dependencies, `setup_env.py torch` LAST — after
   everything that could drag a CPU build back in over it.
2. **Weights from Hugging Face**, for every source the plugin declares —
   through the same `pipeline_files` narrowing the Download button uses, so
   this fetches the files the pipeline loads and not the whole repo.
3. **Weights the plugin fetches itself** (`fetch_weights()`): InsightFace's
   buffalo_l pack and the OpenComic graphs live on their own releases.
4. **A WARM-UP RUN** for everything else — the models that download on first
   use from inside a library (torch.hub for the Zhang colorizer,
   controlnet_aux, ultralytics). There is no download function to call, so the
   only way to fetch them now is to load the model once, which is what the
   first real run would otherwise do while somebody waited at a progress bar
   with no explanation. `load()` is the step that fetches; the `run()` after
   it is a sanity check and is allowed to fail (some tasks need options a
   dummy picture cannot supply), which it says rather than failing the setup.

Steps 3 and 4 run in the plugin's OWN interpreter — a dedicated-env plugin's
weights are fetched by the library installed in that env, not by ours.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from media_compost.hub import setup as hub_setup
from media_compost.ui.plugins import framework as fw
from media_compost.ui.plugins import registry

# The warm-up and fetch-weights steps below load a model in the plugin's own
# interpreter with THIS process's environment, and an ONNX plugin's first
# session starts onnxruntime's Microsoft telemetry unless told not to — the
# full story is in plugins/worker.py, which covers the ordinary job path.
os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")

# Where subcommands run from: the checkout, or site-packages for an installed
# wheel — the same answer the venv lookup uses, so a `setup_env` invoked below
# creates its venv where `interpreter_for` will find it.
ROOT = fw.repo_root()


def _say(msg: str) -> None:
    print(msg, flush=True)


def _run(cmd: str) -> None:
    """One shell command, from the repo root, streaming to our own output."""
    _say(f"\n$ {cmd}")
    rc = subprocess.call(cmd, shell=True, cwd=ROOT)
    if rc != 0:
        raise SystemExit(f"failed ({rc}): {cmd}")


def _expand(cmd: str) -> str:
    """`{python}` / `{pip}`, the way the runner expands them.

    `pip_spec` is what knows that a venv made by uv may carry no pip and has
    to be driven with `uv pip --python`; asking it here rather than writing
    `-m pip` is what keeps uv supported and never required.

    Both go through `hub_setup.quote`, for the reason that module's docstring
    gives: these run through a shell, and an interpreter path with a space in
    it — the ordinary Windows case — would otherwise be read as a program
    name cut at its first space.
    """
    return cmd.format(python=hub_setup.quote(sys.executable),
                      pip=hub_setup.pip_spec(sys.executable))


# A picture to hand a model that has never been loaded. Small on purpose: the
# point is to make the library fetch its weights, not to compute anything.
_WARMUP = """
import importlib, sys, traceback
from PIL import Image

m = importlib.import_module({module!r})
h = m.load({load_key!r}, {{}})
print("loaded", {load_key!r}, flush=True)
try:
    m.run({task!r}, {model_id!r}, h, Image.new("RGB", (64, 64), "white"), {{}})
    print("ran once", flush=True)
except Exception:
    # The weights are what this was for, and `load` already fetched them. A
    # task that cannot be driven by a blank 64x64 picture with no options is
    # not a setup failure.
    traceback.print_exc()
    print("the warm-up run did not complete — the weights are downloaded, "
          "which is what this step is for", flush=True)
"""


def _warm_up(plug, python: str) -> None:
    model = plug.models()[0]
    code = _WARMUP.format(module=plug.module.__name__,
                          load_key=plug.load_key(model.id),
                          task=model.task, model_id=model.id)
    _say(f"\n$ warm up {model.id} (downloads weights that arrive on first use)")
    rc = subprocess.call([python, "-c", code], cwd=ROOT)
    if rc != 0:
        raise SystemExit(f"failed ({rc}): warming up {model.id}")


def _fetch_weights(plug, python: str) -> None:
    code = (f"import importlib; importlib.import_module({plug.module.__name__!r})"
            ".fetch_weights()")
    _say(f"\n$ fetch {plug.key}'s own weights")
    rc = subprocess.call([python, "-c", code], cwd=ROOT)
    if rc != 0:
        raise SystemExit(f"failed ({rc}): fetching {plug.key}'s weights")


def _download_sources(plug, token: str) -> None:
    from media_compost.hub import pipeline_files, repo_cached
    from huggingface_hub import snapshot_download

    for src in plug.manifest.sources:
        if repo_cached(src.repo, src.probe or "config.json"):
            _say(f"\n{src.repo}: already downloaded")
            continue
        pats = list(src.allow_patterns) or list(
            pipeline_files.download_patterns(src.repo, token))
        _say(f"\n$ download {src.repo}")
        snapshot_download(src.repo, token=token or None,
                          allow_patterns=pats or None,
                          max_workers=8)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("action", nargs="?", help="the plugin key (see --list)")
    ap.add_argument("--list", action="store_true",
                    help="print every action key and exit")
    ap.add_argument("--no-weights", action="store_true",
                    help="install the packages, download nothing")
    ap.add_argument("--no-packages", action="store_true",
                    help="download the weights, install nothing")
    args = ap.parse_args(argv)

    if args.list:
        for p in registry.plugins():
            _say(f"{p.key:24} {p.manifest.env:10} "
                 f"{', '.join(m.id for m in p.models())}")
        return 0
    if not args.action:
        ap.error("name an action, or pass --list")

    plug = registry.plugin_by_key(args.action)
    if plug is None:
        raise SystemExit(f"unknown action {args.action!r} — try --list")

    _say(f"Setting up {plug.key} ({plug.manifest.env} environment)")

    if not args.no_packages:
        for cmd in fw.setup_commands(plug.manifest):
            _run(_expand(cmd))

    if args.no_weights:
        _say("\nPackages done; weights skipped (--no-weights).")
        return 0

    from media_compost.hub import hf

    _download_sources(plug, hf.token())

    # The plugin's interpreter, resolved AFTER its environment was built.
    python = fw.interpreter_for(plug.manifest.env) or sys.executable
    if callable(getattr(plug.module, "fetch_weights", None)):
        _fetch_weights(plug, python)
    elif not plug.manifest.sources and plug.models():
        # Nothing declared and nothing to call: the weights arrive when the
        # model is first loaded, so load it.
        _warm_up(plug, python)

    _say(f"\n{plug.key} is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

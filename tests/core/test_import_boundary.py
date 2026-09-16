"""What a plain `import media_compost` is allowed to drag in.

The library, the CLI and `media_compost.hub` must import with every heavy
optional dependency absent. That is the whole promise of the split: `pip
install media-compost` is a library you can read and write, not a web server
with a machine-learning stack attached.

It is a RATCHET, and it has to be, because the failure is invisible from the
code. One module-level `import torch` in a file that used to defer it costs a
base install nothing observable — everything still works on the developer's
machine, where torch is installed — and is discovered by somebody on a NAS
whose `pip install` pulled two gigabytes and then failed to build a wheel.

`hub` is the interesting case and the reason this test exists now: it holds the
Hugging Face plumbing, and it lives in the core package precisely because its
two consumers (the app's plugins and the trainer) must not each carry a copy.
It is allowed to be there only for as long as it stays inert without its extra.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

#: Everything a base install must not need. `fastapi`/`uvicorn` belong to the
#: app, the rest to the AI actions and the trainer.
HEAVY = ("huggingface_hub", "fastapi", "uvicorn", "starlette", "torch",
         "torchvision", "transformers", "faiss", "cv2", "onnxruntime",
         "ultralytics", "insightface", "diffusers")

_PROGRAM = textwrap.dedent("""
    import sys

    BANNED = %r

    class Block:
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in BANNED:
                raise ImportError("BLOCKED: " + name)
            return None

    sys.meta_path.insert(0, Block())

    import media_compost
    import media_compost.cli
    from media_compost import hub
    from media_compost.hub import cache, download, hf, pipeline_files, setup, venv

    # Inert, not broken: every one of these answers rather than raising.
    assert cache.repo_cached("nobody/nothing") is False
    assert cache.cache_sizes() == {}
    assert hf.token() == ""
    assert venv.interpreter_for("main") is not None
    assert venv.interpreter_for("nosuchenv", "/nowhere") is None

    leaked = sorted({m.split(".")[0] for m in sys.modules} & set(BANNED))
    assert not leaked, "these were imported anyway: " + repr(leaked)
    print("OK")
""")


def _run(program: str) -> subprocess.CompletedProcess:
    """In a CHILD, because the check is about what `import` does the FIRST
    time. This process has already imported half of these, so a meta-path hook
    installed here would sit above a populated `sys.modules` and prove
    nothing."""
    return subprocess.run([sys.executable, "-c", program],
                          capture_output=True, text=True)


def test_the_library_the_cli_and_hub_import_with_the_heavy_deps_blocked():
    got = _run(_PROGRAM % (HEAVY,))
    assert got.returncode == 0, got.stderr[-3000:]
    assert got.stdout.strip().endswith("OK")


def test_the_block_actually_blocks():
    """The guard above is only worth anything if it can fail. Without this, a
    typo in the hook would make every future version of that test pass."""
    got = _run(_PROGRAM % (("json",),) + "\nimport json\n")
    assert got.returncode != 0


#: The app and the trainer: subpackages of one distribution, but the layering
#: still points one way — core may name them in the odd COMMENT (the `jobs`
#: table, the config split) and never in an import.
SUBPACKAGES = ("media_compost.ui", "media_compost.train")


def test_core_imports_neither_the_app_nor_the_trainer():
    """Checked as AST over the source rather than by importing, because a
    deferred `from media_compost.ui import` in a rare branch is exactly what
    an import graph misses — and with the app and trainer as SUBPACKAGES the
    walker resolves relative spellings too, or `from .ui import x` would read
    as core's own. ONE crossing is sanctioned and is not an import at all:
    `serve` in `cli.py` hands uvicorn the app as the STRING
    "media_compost.ui.server.app:app" — a runtime reference, deferred behind
    the [full] refusal, which is what lets the one CLI carry the app's command
    while a base install stays eight dependencies. The other direction is
    somebody else's test: the trainer holds itself to the public API in
    `tests/train/test_import_contract.py`, and the app may import core
    freely by design."""
    from tests.importwalk import REPO, imported_names

    package = REPO / "media_compost"
    bad = []
    for path in sorted(package.rglob("*.py")):
        if path.relative_to(package).parts[0] in ("ui", "train"):
            continue
        for name in sorted(imported_names(path)):
            if any(name == s or name.startswith(s + ".") for s in SUBPACKAGES):
                bad.append(f"{path.relative_to(REPO)}: {name}")
    assert not bad, ("core imports the app or the trainer:\n  "
                     + "\n  ".join(bad))


def test_the_walker_sees_the_spellings_a_subpackage_allows():
    """The guard above is only worth anything if the walker resolves what can
    cross the boundary now: a relative import, and a from-import binding a
    subpackage as an alias."""
    from tests.importwalk import REPO, imported_names

    got = imported_names(REPO / "media_compost" / "db.py",
                         source=("from .ui import server\n"
                                 "from . import train\n"
                                 "from media_compost import ui\n"
                                 "from media_compost import open_library\n"))
    assert "media_compost.ui" in got
    assert "media_compost.ui.server" in got
    assert "media_compost.train" in got
    assert "media_compost.open_library" not in got  # attribute, not a module

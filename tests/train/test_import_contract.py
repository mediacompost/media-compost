"""What the trainer is allowed to reach for.

**The public API and `media_compost.hub`. Nothing else.** Not `ops`, not `db`,
not `searchctx`, not the app. That rule is the whole reason the trainer is a
subpackage with a stated boundary rather than a folder inside the server, and
it is worth a test because every breach of it is a one-line convenience that
works perfectly on the machine that wrote it.

Checked as TEXT rather than by importing and inspecting (see
`tests/importwalk.py`), because an import graph only shows what a run happened
to reach — a deferred `from ..db import` inside a rarely-taken branch is
exactly the kind of thing that hides there. And that spelling is live now:
while the trainer was a sibling top-level package a relative import could not
escape it, but as `media_compost.train` the walker has to resolve relative
imports or miss the most natural way of writing the breach.
"""

from __future__ import annotations

from tests.importwalk import REPO, imported_names

PACKAGE = REPO / "media_compost" / "train"

#: The package ROOT, and only the root: `media_compost` re-exports the whole
#: published surface, so anything worth using is reachable from it. Naming a
#: submodule is how you reach past the API by accident.
ALLOWED_EXACT = frozenset({"media_compost"})

#: Subtrees allowed whole. `media_compost.hub` is the Hugging Face and
#: virtualenv plumbing, which lives in core precisely because the app's
#: plugins need the same thing and neither may depend on the other; the
#: trainer's OWN tree is where its relative imports resolve. `media_compost.ui`
#: is what falls through: the app reaches the trainer through one guarded
#: import, and nothing goes the other way.
ALLOWED_TREES = ("media_compost.hub", "media_compost.train")


def _modules():
    return sorted(PACKAGE.rglob("*.py"))


def _offends(name: str) -> bool:
    if name.split(".")[0] != "media_compost":
        return False
    if name in ALLOWED_EXACT:
        return False
    return not any(name == ok or name.startswith(ok + ".")
                   for ok in ALLOWED_TREES)


def test_the_trainer_uses_the_public_api_and_the_hub_and_nothing_else():
    bad = {}
    for path in _modules():
        got = sorted(n for n in imported_names(path) if _offends(n))
        if got:
            bad[str(path.relative_to(REPO))] = got
    assert not bad, (
        "these reach past the public API:\n"
        + "\n".join(f"  {f}: {', '.join(names)}" for f, names in bad.items())
        + "\n\nIf one of them is genuinely needed, the answer is usually to "
          "publish it from `media_compost` — not to widen this list.")


def test_the_check_can_fail():
    """A guard that cannot fail is decoration."""
    assert _offends("media_compost.db")
    assert _offends("media_compost.ops.items")
    assert _offends("media_compost.ui.server.app")
    assert not _offends("media_compost")
    assert not _offends("media_compost.hub.cache")
    assert not _offends("media_compost.train.manager")
    assert not _offends("fastapi")


def test_the_walker_resolves_the_spellings_that_cross_the_boundary():
    """As a sibling package a relative import could not escape the trainer;
    as a subpackage `from ..db import Item` names core, and `from
    media_compost import db` binds the db SUBMODULE. Both must read as what
    they are — and an attribute of the public API must not."""
    got = imported_names(PACKAGE / "dataset.py",
                         source=("from ..db import Item\n"
                                 "from media_compost import db, open_library\n"
                                 "from . import manager\n"))
    assert "media_compost.db" in got
    assert "media_compost.train.manager" in got
    assert "media_compost.open_library" not in got
    assert sorted(n for n in got if _offends(n)) == ["media_compost.db"]


SCRIPTS = REPO / "media_compost" / "train" / "scripts"

#: The scripts' own subtree, as the path-based walker spells it. The walker
#: resolves a relative import from the file's LOCATION, not from the
#: `__init__.py` chain — so `from . import common` in `engines/sd.py` reads
#: as `media_compost.train.scripts.engines.common` here, while at runtime
#: (the scripts dir on the trainer's own sys.path) it is `engines.common`
#: and never touches `media_compost` at all. Self-reference is exactly what
#: standalone allows.
_SELF = "media_compost.train.scripts"


def _reaches_project(name: str) -> bool:
    if name.split(".")[0] != "media_compost":
        return False
    return not (name == _SELF or name.startswith(_SELF + "."))


def test_the_training_scripts_import_no_project_code():
    """`train/scripts/` (the trainer) is STANDALONE: it runs in the dedicated
    training venv, where no media-compost distribution is installed at all —
    so an import of ANY project package would work on a dev checkout and die
    on a real install. (It LIVES inside `media_compost/train/` now — as
    package data, so a wheel carries it — which changes nothing about the
    contract: physical nesting creates no imports, and this test reads the
    source.) That is also why `atomicio.py` and `pipeline_opts.py` are
    deliberate copies of core code (the latter parity-tested from core's side
    in `tests/core/test_pipeline_files.py`)."""
    # The move is exactly how this guard can rot: rglob over a directory that
    # no longer exists yields nothing and the test passes forever.
    assert (SCRIPTS / "train.py").is_file(), f"trainer not at {SCRIPTS}"
    bad = {}
    for path in sorted(SCRIPTS.rglob("*.py")):
        got = sorted(n for n in imported_names(path) if _reaches_project(n))
        if got:
            bad[str(path.relative_to(SCRIPTS.parent))] = got
    assert not bad, (
        "train/scripts/ must not import project code — it runs in a venv "
        "where none of it is installed:\n"
        + "\n".join(f"  {f}: {', '.join(names)}" for f, names in bad.items())
    )


def test_the_standalone_check_can_fail():
    """A guard that cannot fail is decoration — and this one already rotted
    once: after the scripts moved, the old checkout-root path made the rglob
    yield nothing and the test passed as a no-op."""
    assert _reaches_project("media_compost.db")
    assert _reaches_project("media_compost")
    assert not _reaches_project(_SELF + ".engines.common")
    assert not _reaches_project("torch")
    got = imported_names(SCRIPTS / "engines" / "sd.py")
    assert any(n.startswith(_SELF) for n in got), (
        "the walker no longer resolves the engines' relative imports into "
        "the scripts' subtree — _SELF is stale")
    assert not any(_reaches_project(n) for n in got)


def test_importing_the_trainer_does_not_import_a_web_framework():
    """`media_compost.train` is usable from a terminal on a box with no server
    installed, so its top level must not reach `web/`. The routes are the
    optional half a host mounts."""
    import subprocess
    import sys
    import textwrap

    got = subprocess.run([sys.executable, "-c", textwrap.dedent("""
        import sys

        class Block:
            def find_spec(self, name, path=None, target=None):
                if name.split(".")[0] in ("fastapi", "starlette"):
                    raise ImportError("BLOCKED: " + name)
                return None

        sys.meta_path.insert(0, Block())

        import media_compost.train
        import media_compost.train.cli
        from media_compost.train import manager, evaluate, dataset, models

        assert media_compost.train.available() in (True, False)
        print("OK")
    """)], capture_output=True, text=True)
    assert got.returncode == 0, got.stderr[-3000:]
    assert got.stdout.strip().endswith("OK")

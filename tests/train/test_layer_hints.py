"""The layer names the adapter's two filter fields offer.

`media_compost/train/layers.py` is a TABLE, and a table beside the thing it
describes is the shape this repo keeps deleting — so it is held to the
engines from both ends:

* the PROJECTIONS are the engines' own `adapter_targets`, read out of the
  engine source (the app's venv has no torch, so this READS rather than
  imports — `test_engine_contract.py`'s own trick);
* the STACKS are checked against a real module tree, where `.venv-training`
  exists: `engine_smoke.py` builds the architecture from its actual config in
  a couple of seconds and downloads nothing, so "does `down_blocks` name
  anything" is a question that can simply be asked.

Between them a hint cannot be a name the model does not have, and a
projection cannot drift from what the adapter attaches to.
"""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

import pytest

from media_compost.hub.venv import interpreter_for
from media_compost.train import layers
from media_compost.train.models import REGISTRY

REPO = Path(__file__).resolve().parents[2]
ENGINES_DIR = REPO / "media_compost" / "train" / "scripts" / "engines"
ENGINES = sorted({m.engine for m in REGISTRY})


def _literal_list(tree: ast.Module, name: str,
                  known: dict[str, list[str]]) -> list[str] | None:
    """A module-level list of plain strings, or None. `DIT_LORA_TARGETS + [...]`
    resolves one level, which is how qwenimage spells its own."""
    def value(node: ast.AST) -> list[str] | None:
        if isinstance(node, (ast.List, ast.Tuple)):
            if all(isinstance(e, ast.Constant) and isinstance(e.value, str)
                   for e in node.elts):
                return [e.value for e in node.elts]        # type: ignore[misc]
            return None
        if isinstance(node, ast.Name):
            return known.get(node.id)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = value(node.left), value(node.right)
            return None if left is None or right is None else left + right
        return None

    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return value(node.value)
    return None


def _common() -> dict[str, list[str]]:
    tree = ast.parse((ENGINES_DIR / "common.py").read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for name in ("UNET_LORA_TARGETS", "DIT_LORA_TARGETS"):
        got = _literal_list(tree, name, out)
        if got is not None:
            out[name] = got
    return out


COMMON = _common()


def _targets_of(engine: str) -> list[str]:
    """What the engine attaches an adapter to — its own list, or the base
    class's `adapter_targets` where it declares none."""
    tree = ast.parse((ENGINES_DIR / f"{engine}.py").read_text(encoding="utf-8"))
    own = _literal_list(tree, "TRANSFORMER_LORA_TARGETS", COMMON)
    return own if own is not None else COMMON["UNET_LORA_TARGETS"]


def test_the_engine_source_was_readable():
    """The two derivations below are silent if the parse gave nothing."""
    assert COMMON.get("UNET_LORA_TARGETS"), COMMON
    assert COMMON.get("DIT_LORA_TARGETS"), COMMON


@pytest.mark.parametrize("engine", ENGINES)
def test_every_registry_engine_offers_hints(engine: str):
    """A model added with no row here offers nothing at all — a field that
    silently stops helping rather than a failure."""
    assert layers.hints_for(engine), f"no layer hints for {engine!r}"


@pytest.mark.parametrize("engine", ENGINES)
def test_the_projections_are_the_engines_own_targets(engine: str):
    """The half of the table that CAN be derived, so it is."""
    assert list(layers._TARGETS[engine]) == _targets_of(engine)


@pytest.mark.parametrize("engine", ENGINES)
def test_a_stack_is_never_also_a_projection(engine: str):
    """The two halves stay separate: a name in both would be offered twice,
    and a projection listed as a stack would escape the check above."""
    both = set(layers._STACKS[engine]) & set(layers._TARGETS[engine])
    assert not both, both


# ---- against a real module tree --------------------------------------------

_HARNESS_DIR = Path(__file__).resolve().parent
_SCRIPTS = REPO / "media_compost" / "train" / "scripts"

_DUMP = """
import json, sys
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
import engine_smoke as es
out = {}
for engine in sys.argv[3].split(","):
    build = es.build_unet if engine in es.UNET_ENGINES else es.build_dit
    model, _ = build(engine)
    out[engine] = [n for n, _ in model.named_modules() if n]
print("NAMES " + json.dumps(out))
"""


@pytest.fixture(scope="module")
def module_names() -> dict[str, list[str]]:
    """Every engine's module paths, from ONE child process.

    One rather than seven: the child's cost is importing torch and diffusers
    (two to four seconds), and building the backbones is the cheap part — the
    same reason `test_engine_smoke.py` caches its runs. Seven spawns of that
    is a measurable share of a parallel `-m ""` run, and this is a question
    they can all answer together.
    """
    exe = interpreter_for("training", str(REPO))
    if not exe:
        pytest.skip("no .venv-training — building a backbone needs torch")
    got = subprocess.run(
        [exe, "-c", _DUMP, str(_HARNESS_DIR), str(_SCRIPTS), ",".join(ENGINES)],
        capture_output=True, text=True, timeout=900)
    assert got.returncode == 0, got.stderr[-2000:]
    line = next(ln for ln in got.stdout.splitlines() if ln.startswith("NAMES "))
    return json.loads(line[len("NAMES "):])


@pytest.mark.slow
@pytest.mark.parametrize("engine", ENGINES)
def test_every_hint_names_something_in_the_real_model(
        engine: str, module_names: dict[str, list[str]]):
    """Each hint must MATCH a module path — the same substring test
    `adapters.name_matches` applies. A hint matching nothing would be a chip
    that narrows the adapter to no layers at all, which is the one failure
    the layer filter exists to refuse loudly."""
    names = module_names[engine]
    missing = [h for h in layers.hints_for(engine)
               if not any(h in n for n in names)]
    assert not missing, f"{engine}: hints that name nothing: {missing}"

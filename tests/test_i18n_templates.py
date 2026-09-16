"""Every user-visible backend TEMPLATE has an entry in the frontend catalog.

Two kinds of backend text reach the UI raw: an ``OpError``'s message (rendered
from ``err.message`` in overlay footers) and a history event's ``summary``
(the History tab). Both now travel as templates (``ops/errors.py``,
``history.log_event``), and the frontend translates them by looking the
template up in its catalog — so a template with no entry silently shows
English, which is invisible in English and exactly how the Train tab once
shipped untranslated.

The harvest is ``ast`` over the real source: every string literal inside a
``summary=`` keyword (ternaries included — a conditional template contributes
both arms) and every literal inside the first argument of a raise of the four
error classes. The catalog is read as TEXT, the same trick the retired
``recommend.i18n.test.ts`` used: a key is a double-quoted literal followed by
a colon, and ``json.dumps`` produces exactly that form.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "media_compost"
CATALOGS = [
    ROOT / "frontend" / "src" / "app" / "locales" / "de.ts",
    ROOT / "frontend" / "src" / "train" / "locales" / "de.ts",
]

ERROR_CLASSES = {"Invalid", "Refused", "NotFound", "Conflict", "OpError"}

#: Templates that never reach the UI and owe no entry. The Python API's
#: script-facing errors (library/) are excluded wholesale below; these are
#: point exemptions inside wired modules.
EXEMPT_PREFIXES = (
    # `library/importing.py` logs through the Python API for scripts; its
    # sibling in cli.py shares the template, which IS in the catalog — one
    # entry covers both.
)


def _templates(node: ast.AST) -> list[str] | None:
    """The COMPLETE templates an expression can evaluate to.

    A ternary contributes both arms, a concatenation the cross product of its
    sides — because ``("Detected 1 face" if …) + (", {n} new" if …)`` builds
    its runtime key by composition, and harvesting the arms separately would
    demand catalog entries for fragments no lookup ever sees. ``None`` means
    the expression is genuinely dynamic (an f-string, a name, a call) and the
    site keeps its English fallback rather than owing entries.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        body, orelse = _templates(node.body), _templates(node.orelse)
        if body is None and orelse is None:
            return None
        return (body or []) + (orelse or [])
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _templates(node.left), _templates(node.right)
        if left is None or right is None:
            return None
        # An optional suffix arrives as `+ ("…" if cond else "")`; the empty
        # arm composes to the bare left side, which is itself a real key.
        return [a + b for a in left for b in right]
    return None


def harvest() -> set[str]:
    templates: set[str] = set()
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND).as_posix()
        if rel.startswith(("library/", "testing")):
            continue  # the Python API speaks to scripts, not to the UI
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # A Migration's `summary=` is CLI/log text, not a UI sentence.
                fn = node.func
                cname = fn.id if isinstance(fn, ast.Name) else (
                    fn.attr if isinstance(fn, ast.Attribute) else "")
                if cname == "Migration":
                    continue
                for kw in node.keywords:
                    if kw.arg == "summary":
                        templates.update(_templates(kw.value) or [])
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                fn = node.exc.func
                name = fn.id if isinstance(fn, ast.Name) else (
                    fn.attr if isinstance(fn, ast.Attribute) else "")
                if name in ERROR_CLASSES and node.exc.args:
                    templates.update(_templates(node.exc.args[0]) or [])
            if (isinstance(node, ast.FunctionDef)
                    and node.name.endswith("_summary")):
                # A summary built in a HELPER is a Name at its `summary=` site
                # and invisible above — `ops/captions.py:_refs_summary` was
                # found showing English in seven languages exactly this way.
                # The convention: such a helper is named `*_summary` and every
                # branch returns its template as a literal, bare or as the
                # first element of a `(template, vars)` tuple.
                for ret in ast.walk(node):
                    if not isinstance(ret, ast.Return) or ret.value is None:
                        continue
                    value = ret.value
                    if isinstance(value, ast.Tuple) and value.elts:
                        value = value.elts[0]
                    templates.update(_templates(value) or [])
    # A template is a sentence; the odd surviving one-worder is a default.
    return {t for t in templates if len(t.split()) >= 2}


def test_every_backend_template_has_a_catalog_entry():
    text = "".join(p.read_text(encoding="utf-8") for p in CATALOGS)
    missing = sorted(
        t for t in harvest()
        # ensure_ascii=False, or the curly quotes in half the messages
        # serialize as “ and never match the literal catalog text.
        if f"{json.dumps(t, ensure_ascii=False)}:" not in text
        and not t.startswith(EXEMPT_PREFIXES)
    )
    assert missing == [], (
        f"{len(missing)} backend template(s) with no catalog entry:\n"
        + "\n".join(missing[:40]))


def test_every_task_label_has_a_catalog_entry():
    """The AI-action task labels ("Detect text", "Split comic panels") reach
    the UI as ``t(a.label)`` with a VARIABLE, so the frontend's coverage
    extractor cannot see them and nothing fails when one is missing — the
    button silently reads English in seven languages. This is the ratchet:
    every ``tasks.py`` label is held to a catalog entry by hand, the same
    silent-by-construction failure the strict-request-model test exists for.
    """
    tree = ast.parse(
        (BACKEND / "ui" / "plugins" / "tasks.py").read_text(encoding="utf-8"))
    labels: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "Task"):
            continue
        # Task(kind, label, icon, result, ...) — the label is positional.
        if len(node.args) >= 2:
            labels.update(_templates(node.args[1]) or [])
    assert labels, "the harvest went vacuous — did tasks.py change shape?"
    text = "".join(p.read_text(encoding="utf-8") for p in CATALOGS)
    missing = sorted(t for t in labels
                     if f"{json.dumps(t, ensure_ascii=False)}:" not in text)
    assert missing == [], (
        f"{len(missing)} task label(s) with no catalog entry:\n"
        + "\n".join(missing))

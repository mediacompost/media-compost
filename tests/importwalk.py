"""Resolve a Python file's imports to ABSOLUTE dotted names.

The boundary tests (`tests/core/test_import_boundary.py`,
`tests/train/test_import_contract.py`) read source rather than importing,
because an import graph only shows what a run happened to reach — a deferred
import inside a rarely-taken branch is exactly what it misses. Stdlib only:
the core suite runs on a base-only install.

Three spellings normalize to one name space:

- ``import x.y``                     -> ``x.y``
- ``from x.y import z``              -> ``x.y``, plus ``x.y.z`` when ``z``
  is a MODULE rather than an attribute
- ``from ..y import z`` (relative)   -> resolved against the file's own
  package, then treated as above

The last two exist because of the subpackage layout. While the library, the
app and the trainer were sibling top-level packages, a relative import could
not cross a boundary and ``from media_compost import x`` could only name the
public API — so the old tests ignored both. As subpackages of one
``media_compost``, ``from ..db import Item`` names core and ``from
media_compost import db`` binds the db SUBMODULE; skipping either would blind
a boundary test to the one honest spelling of the reach it refuses. Whether
an alias is a module is answered by the tree (``<repo>/x/y/z.py`` or a
``z/`` directory exists), so an attribute like ``open_library`` is never
flagged.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _is_module(dotted: str) -> bool:
    p = REPO.joinpath(*dotted.split("."))
    return p.is_dir() or p.with_suffix(".py").is_file()


def imported_names(path: Path, source: str | None = None) -> set[str]:
    """Every module ``path`` imports, as absolute dotted names.

    ``source`` overrides reading the file, so a can-fail test can feed
    synthetic spellings while keeping a real path for package resolution.
    """
    rel = path.resolve().relative_to(REPO)
    # The slice is the same for a module and a package __init__: dropping the
    # last part yields the package relative imports resolve against.
    pkg = list(rel.with_suffix("").parts)[:-1]

    out: set[str] = set()
    text = source if source is not None else path.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(text, str(path))):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level > len(pkg):
                continue  # beyond the top — a runtime error, not a reach
            base = pkg[: len(pkg) - node.level + 1] if node.level else []
            mod = base + (node.module.split(".") if node.module else [])
            if not mod:
                continue
            out.add(".".join(mod))
            for a in node.names:
                cand = ".".join(mod + [a.name])
                if _is_module(cand):
                    out.add(cand)
    return out

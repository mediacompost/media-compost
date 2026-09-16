"""Numeric VALUE tags — the ``<name>:<number><unit>`` convention.

Any tag whose BASENAME is a number with an optional unit is a value tag:
``people:3``, ``height:172cm``, ``height:1.72m``, ``quality:7``. Nothing
changes about assigning one — they are ordinary tags, typed in any tag field,
imported, exported, implied — and parsing is DERIVATION, not storage: no new
column, no migration, a restored library's tags parse the same way. This
module is the one definition of what the convention reads.

Mirrored on the frontend by ``frontend/src/shared/tagvalue.ts`` (in
``shared/`` because both ``query/`` and ``app/`` read it), the way
``partialdate.py`` / ``subjects/when.ts`` and ``tagname.py`` / ``tags.ts``
are — both sides pure, and ``tests/golden/value_corpus.json`` is what keeps
them equal, asserted by BOTH pytest and ``node --test``.

**Number format.** Dot decimal is canonical (``1.72m``); a COMMA decimal is
also READ (``1,72m``), because an imported or restored tag can hold one — but
comma is the separator in every multi-tag entry field, so the UI nudges
toward dot or integer-with-smaller-unit forms (``172cm``) and the query
serializer always writes the canonical spelling.

**Units.** A free suffix. The metric length and mass families CONVERT
(``1.72m`` ≡ ``172cm``, ``1.5kg`` ≡ ``1500g``) so one namespace can mix
spellings; an unknown unit compares only against the same unit; no unit
compares as a plain number. A unitless LITERAL ignores units entirely — it
compares every value's number as written (``VALUE:height>=100`` reads
``height:172cm`` as 172), so a namespace tagged in one consistent unit
searches without spelling the unit out; a unitless tag VALUE still only
answers to unitless or unitless-literal comparisons. No imperial tables and
no unit editor: a suffix the app does not know still works within itself.
"""

from __future__ import annotations

import re
from typing import Iterable, NamedTuple, Optional

#: The convertible families, each unit as a factor to the family's base.
FAMILIES: dict[str, dict[str, float]] = {
    "length": {"mm": 0.001, "cm": 0.01, "m": 1.0, "km": 1000.0},
    "mass": {"mg": 1e-6, "g": 0.001, "kg": 1.0},
}
_UNIT_FAMILY: dict[str, tuple[str, float]] = {
    u: (fam, f) for fam, units in FAMILIES.items() for u, f in units.items()
}

# A number (dot OR comma decimal) followed by a free unit suffix. The suffix
# is letters and the handful of symbols a unit is written with — a digit in
# it would make `1.2m2` ambiguous, so there is none.
_VALUE = re.compile(r"(-?\d+(?:[.,]\d+)?)([a-z%°µ]*)")


class TagValue(NamedTuple):
    value: float
    unit: str


def parse(basename: str) -> Optional[TagValue]:
    """The value a tag basename holds, or None for an ordinary word.

    Total over any string, like everything in ``tagname.py``: a name from an
    old sidecar can hold anything, and anything that is not the convention
    simply reads as no value.
    """
    m = _VALUE.fullmatch(basename)
    if not m:
        return None
    return TagValue(float(m.group(1).replace(",", ".")), m.group(2))


def space(unit: str) -> str:
    """Which values a unit may be compared against.

    A convertible unit answers its FAMILY name, so ``m`` and ``cm`` share a
    space; an unknown unit answers itself prefixed (``u:px``), so it compares
    only against its own spelling; no unit answers ``""`` — a plain number,
    comparable only against other plain numbers.
    """
    if not unit:
        return ""
    fam = _UNIT_FAMILY.get(unit)
    return fam[0] if fam else "u:" + unit


def canon(v: TagValue) -> tuple[str, float]:
    """The value in its space's base unit — ``172cm`` and ``1.72m`` canon to
    the same ``("length", 1.72)``."""
    fam = _UNIT_FAMILY.get(v.unit)
    return (space(v.unit), v.value * fam[1] if fam else v.value)


_EPS = 1e-9


def _cmp(a: float, op: str, b: float, tol: float) -> bool:
    """The numeric comparison, `query._num_cmp`'s rules: `tol` (half the last
    typed decimal place) makes `=` a half-open window ``[b-tol, b+tol)``."""
    if op in ("=", "!=") and tol > 0:
        inside = (b - tol) <= a < (b + tol)
        return inside if op == "=" else not inside
    if op == "=":
        return abs(a - b) < _EPS
    if op == "!=":
        return abs(a - b) >= _EPS
    if op == ">":
        return a > b
    if op == ">=":
        return a >= b - _EPS
    if op == "<":
        return a < b
    if op == "<=":
        return a <= b + _EPS
    return False


def matches(basename: str, op: str, value: float, unit: str,
            tol: float = 0.0) -> bool:
    """Whether one tag basename satisfies ``op value unit``.

    The literal's ``tol`` is in the literal's OWN unit (half the last decimal
    place it was typed to), so it converts with it.
    """
    v = parse(basename)
    if v is None:
        return False
    if not unit:
        # A unitless literal IGNORES units: the value's own number, as
        # written — `height:172cm` reads as 172, `height:1.72m` as 1.72 —
        # so a namespace tagged in one consistent unit searches without the
        # unit spelled out. (A unit-carrying literal still compares only
        # within its space.)
        return _cmp(v.value, op, value, tol)
    sp, a = canon(v)
    lsp, b = canon(TagValue(value, unit))
    if sp != lsp:
        return False
    fam = _UNIT_FAMILY.get(unit)
    return _cmp(a, op, b, tol * fam[1] if fam else tol)


def matching_names(names: Iterable[str], ns: str, op: str, value: float,
                   unit: str, tol: float = 0.0) -> set[str]:
    """Every tag name in ``names`` that is in namespace ``ns`` and whose
    basename satisfies the comparison — the ONE resolution both the
    evaluator and the SQL compiler read (`searchctx.load_value_sets`)."""
    prefix = ns + ":"
    return {n for n in names
            if n.startswith(prefix)
            and matches(n[len(prefix):], op, value, unit, tol)}

"""A GROUP PATH — the address a search names a group by.

`Group.name` is not unique in the table and never has been: two branches may
each hold a "2024". What is unique is a LEVEL (`ops.groups.unique_sibling_name`),
so the FULL PATH from the root is what identifies one — ``GROUP:Trips/2024``
— and a bare ``GROUP:2024`` is the ROOT-level group of that name and nothing
else (owner 2026-09, reversing the tail rule of the same month: a value with
no ``/`` used to mean every group carrying the name, and a path the END of a
group's own path, so ``GROUP:abc`` beside a ``foo/abc`` found both).

THE RULE, in one place because three readers need exactly the same answer
(the compiled SQL clause, the evaluator's per-item sets, and the query
builder's dropdown, which commits the full path):

* the value is split on ``/`` and compared WHOLE against a group's own path
  from the root — the same number of segments, each equal;
* the WHOLE value is also tried against the joined path. That is not
  tidiness: a group really called "a/b" would otherwise stop matching
  `GROUP:a/b`, and this costs nothing but a string compare. There is no
  escape syntax for a "/" in a name, deliberately — a second escaping layer
  over `escapeName` (which the query string already applies) is a mirrored
  rule in two languages and a corpus, for a character almost no folder name
  carries.

Comparison is case-insensitive and ignores the whitespace around a segment,
like every other name match in the search.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Optional

SEP = "/"


def split(value: str) -> list[str]:
    """A condition's value as path segments, coarsest FIRST. Empty segments
    are dropped, so a stray "Trips//2024" and a leading "/" read as what
    they obviously mean."""
    return [seg for seg in
            (part.strip().lower() for part in (value or "").split(SEP)) if seg]


def path_of(gid: int, names: Mapping[int, str],
            parent: Mapping[int, Optional[int]]) -> list[str]:
    """One group's path, coarsest FIRST and lowercased. Cycle-safe: a loop
    (which the API refuses but a restored folder need not) stops at the
    first repeat rather than hanging."""
    out: list[str] = []
    seen: set[int] = set()
    cur: Optional[int] = gid
    while cur is not None and cur not in seen:
        seen.add(cur)
        out.append((names.get(cur) or "").strip().lower())
        cur = parent.get(cur)
    out.reverse()
    return out


def joined(segments: Iterable[str]) -> str:
    return SEP.join(segments)


def wanted(value: str) -> tuple[str, str]:
    """The two spellings a value is matched by: its segments rejoined (so
    case and stray separators do not matter), and the whole value as typed
    — for a name that holds a "/" of its own."""
    return joined(split(value)), (value or "").strip().lower()


def hit(value: str, paths) -> bool:
    """Does any of these joined paths answer the value?"""
    want, whole = wanted(value)
    return bool(want) and (want in paths or whole in paths)


def matching_ids(value: str, names: Mapping[int, str],
                 parent: Mapping[int, Optional[int]]) -> set[int]:
    """Every group the condition value names — the one at that exact path."""
    want, whole = wanted(value)
    if not want:
        return set()
    out: set[int] = set()
    for gid in names:
        p = joined(path_of(gid, names, parent))
        if p == want or p == whole:
            out.add(gid)
    return out

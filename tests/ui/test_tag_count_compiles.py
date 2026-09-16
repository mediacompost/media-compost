"""`INFO:tag_count` — the one intrinsic whose value is RESOLVED.

It counts a tag an implication brings, a group grants or a sequence member
carries, so the rows an item assigns are only half the answer — and a
condition that cannot compile drops the WHOLE query to the residue, which
materializes every candidate the rest of it admits and evaluates it in
Python. Measured on a 1.5M-item library, `INFO:tag_count>=3`:

    47 s   with an implication in the library (no superset for `>=`)
    0.025 s  with none — the direct count IS the effective one

The CORRECTNESS of the superset is `test_search_equivalence`'s job, and it
did its job: the first version weakened `=` to `<=` while passing the
tolerance through, and the random trees found the three items it lost.
"""

from __future__ import annotations

import pytest

from media_compost import prefilter, query as q
from media_compost.db import (Database, Group, GroupTag, Item, Sequence,
                              SequenceItem, Tag, TagImplication)
from media_compost.ui.config import UiConfig


@pytest.fixture
def lib(tmp_path):
    db = Database(UiConfig(data_dir=tmp_path / "data"))
    with db.session() as s:
        s.add_all([Tag(name="a"), Tag(name="b"),
                   Item(uid="i1", name="one", kind="image")])
        s.commit()
    return db


def _compiled(s, op="=", value=1):
    tree = q.Group(op="and", children=[
        q.MetaCond(name="tag_count", mtype="numeric", op=op, value=value)])
    clause, residue = prefilter.compile_query(s, tree)
    return clause, residue


def test_a_plain_library_compiles_it_EXACTLY(lib):
    """Nothing here can make the effective count differ from the direct one,
    so the direct count IS the answer and the residue never runs."""
    with lib.session() as s:
        clause, residue = _compiled(s, ">=", 3)
        assert clause is not None
        assert residue is None, "an exact compile must leave no residue"


@pytest.mark.parametrize("what", ["implication", "group tag", "sequence"])
def test_ANY_of_the_three_makes_it_inexact(lib, what):
    """Each of the three is enough on its own — and each is a catalog-sized
    EXISTS, so asking is microseconds."""
    with lib.session() as s:
        if what == "implication":
            s.add(TagImplication(tag_id=1, implies_id=2))
        elif what == "group tag":
            g = Group(name="G")
            s.add(g)
            s.flush()
            s.add(GroupTag(group_id=g.id, tag_id=1, negative=False))
        else:
            seq = Sequence(name="S", kind="comic")
            s.add(seq)
            s.flush()
            s.add(SequenceItem(sequence_id=seq.id, item_id=1, position=0))
        s.commit()
    with lib.session() as s:
        _clause, residue = _compiled(s, ">=", 3)
        assert residue is not None, f"a {what} makes the two differ"


def test_the_upper_bounded_operators_still_NARROW(lib):
    """Effective >= direct always, so `effective <= N` implies `direct <= N`
    — a sound superset that the residue then re-checks over the candidates
    rather than over the library. `=` takes the weaker half of its pair;
    `>=` has no upper bound at all (one tag can imply any number)."""
    with lib.session() as s:
        s.add(TagImplication(tag_id=1, implies_id=2))
        s.commit()
    with lib.session() as s:
        for op in ("<=", "<", "="):
            clause, residue = _compiled(s, op, 2)
            assert clause is not None, op
            assert residue is not None, f"{op} is a superset, not exact"
        for op in (">=", ">", "!="):
            clause, residue = _compiled(s, op, 2)
            assert clause is None, op

"""`INFO:file_count` — how many SOURCE files an item holds.

The rule is the Sources list: every ``files`` row of the item, the derived
saves and the near-dup alternatives included, artifacts excluded (they hang
off a file rather than being one). An ordinary picture answers 1, a picture
something folded into answers 2, and a sequence CONTAINER answers 0 — it
borrows a member's file and owns none.

What these tests actually guard is that the SQL clause and the Python
evaluator agree. The compiled clause is exact, so an ordinary search never
reaches the evaluator at all; a condition OR'd with an inexact one (a
``tag_count``, which can only be answered by resolving effective tags) keeps
the whole group as RESIDUE, and that is the path a missing
``nums["file_count"]`` would silently answer 0 on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from media_compost.db import File, Item, Sequence, SequenceItem
from media_compost.importer import Importer, ImportOptions
from media_compost.testing import search_items
from media_compost.ui.config import UiConfig
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library


def q_files(op: str, value) -> dict:
    return {"type": "meta", "name": "file_count", "mtype": "numeric",
            "op": op, "value": value}


def q_tag_count(op: str, value) -> dict:
    """An INEXACT condition: `tag_count` needs effective resolution, so the
    compiler refuses it and whatever it is OR'd with runs as residue."""
    return {"type": "meta", "name": "tag_count", "mtype": "numeric",
            "op": op, "value": value}


def q_or(*children) -> dict:
    return {"type": "group", "op": "or", "neg": False,
            "children": list(children)}


@pytest.fixture
def client(tmp_path: Path, images: Path):
    """The standard duplicate folder: one item with two files (the original
    plus the downscaled near-dup folded in as an alternative) and one with a
    single file."""
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths(
            [images], ImportOptions(folders_as_groups=False))
        s.commit()
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        c.lib = lib
        yield c
    app.dependency_overrides.clear()


def _by_files(client) -> dict[int, int]:
    with client.lib.db.session() as s:
        out: dict[int, int] = {}
        for it in s.query(Item).all():
            out[it.id] = s.query(File).filter_by(item_id=it.id).count()
        return out


def _ids(page) -> list[int]:
    return sorted(i["id"] for i in page["items"])


def test_the_fixture_has_one_of_each(client):
    assert sorted(_by_files(client).values()) == [1, 2]


def test_file_count_finds_the_item_a_near_dup_folded_into(client):
    counts = _by_files(client)
    two = [iid for iid, n in counts.items() if n == 2]
    one = [iid for iid, n in counts.items() if n == 1]

    assert _ids(search_items(client, q_files("=", 2))) == sorted(two)
    assert _ids(search_items(client, q_files("=", 1))) == sorted(one)
    assert _ids(search_items(client, q_files(">=", 1))) == sorted(one + two)
    assert search_items(client, q_files("=", 0))["total"] == 0
    assert _ids(search_items(client, q_files("!=", 1))) == sorted(two)


def test_the_residue_path_answers_the_same(client):
    """The evaluator's answer, forced by an OR with an inexact condition.

    Without the count in `QueryCtx.nums` every item here reads as 0 files,
    so this returns nothing at all while the exact search above still works.
    """
    two = sorted(iid for iid, n in _by_files(client).items() if n == 2)
    # `tag_count >= 999` matches nothing, so the OR is exactly the file
    # condition — answered by the evaluator rather than by SQL.
    page = search_items(client, q_or(q_files("=", 2), q_tag_count(">=", 999)))
    assert _ids(page) == two
    both = sorted(_by_files(client))
    assert _ids(search_items(
        client, q_or(q_files(">=", 1), q_tag_count(">=", 999)))) == both


def test_a_sequence_container_has_no_file_of_its_own(client):
    """It borrows a member's active file, so it owns none — and both paths
    have to say so."""
    with client.lib.db.session() as s:
        members = s.query(Item).all()
        cont = Item(uid="fc-seq", name="Chapter", kind="sequence",
                    active_file_id=members[0].active_file_id)
        s.add(cont)
        s.flush()
        seq = Sequence(uid="fc-seq-1", name="Chapter", kind="comic",
                       item_id=cont.id)
        s.add(seq)
        s.flush()
        for pos, m in enumerate(members):
            s.add(SequenceItem(sequence_id=seq.id, item_id=m.id,
                               position=pos + 1))
        s.commit()
        cont_id = cont.id

    assert _ids(search_items(client, q_files("=", 0),
                             hide_sequenced=False)) == [cont_id]
    assert _ids(search_items(client, q_or(q_files("=", 0),
                                          q_tag_count(">=", 999)),
                             hide_sequenced=False)) == [cont_id]


def test_the_catalog_offers_it(client):
    entries = {e["name"]: e for e in
               client.get("/api/metadata/catalog").json()}
    assert entries["file_count"]["mtype"] == "numeric"
    assert entries["file_count"]["count"] > 0


def test_the_clause_compiles_exactly(client, monkeypatch):
    """A plain `file_count` search is answered in SQL and never reaches the
    evaluator — without the compiler's own branch it would quietly fall back
    to the residue path, correct and a scan slower."""
    import media_compost.ops.search as search_mod

    def boom(*a, **k):
        raise AssertionError("residue evaluator ran for an exact tree")

    monkeypatch.setattr(search_mod, "evaluate_residue", boom)
    two = sorted(iid for iid, n in _by_files(client).items() if n == 2)
    assert _ids(search_items(client, q_files("=", 2))) == two

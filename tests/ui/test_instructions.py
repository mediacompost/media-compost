"""Instructions: a caption with an ordered list of the pictures it was made from.

An instruction sits on the item it PRODUCED and its refs are the inputs — the
shape an edit/instruction image model trains on. It is a ``Caption`` row with
``kind="instruction"``, which is what buys it the whole of caption ops,
history, revert, meta tags, sidecars and the Python API unchanged.

What is genuinely new, and what these tests are about, is that the two kinds
must never be mistaken for one another: two lists, two counts, two query
keywords, two training sources. (The full sidecar round trip is covered by
``test_sidecar.test_import_folder_round_trip``, whose rich library now carries
an instruction.)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from media_compost.ui.config import UiConfig
from media_compost.db import CaptionRef
from media_compost.importer import Importer, ImportOptions
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library
from media_compost.testing import make_image, search_items


@pytest.fixture
def three(tmp_path: Path):
    """Three visibly distinct pictures — an instruction needs a target and at
    least two sources to have an order worth getting wrong."""
    src = tmp_path / "three"
    src.mkdir()
    for seed in (11, 22, 33):
        make_image(src / f"{seed}.png", seed=seed)
    return src


@pytest.fixture
def client(tmp_path: Path, three: Path):
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths([three], ImportOptions())
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        c.lib = lib
        yield c
    app.dependency_overrides.clear()


def _items(client) -> list[int]:
    return [i["id"] for i in client.get("/api/items").json()["items"]]


def _add(client, item_id: int, text: str, kind: str = "caption") -> int:
    r = client.post(f"/api/items/{item_id}/captions",
                    json={"text": text, "kind": kind})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _refs(client, item_id: int, ids: list[int]):
    return client.put(f"/api/items/{item_id}/captions/{_refs.cap}/refs",
                      json={"item_ids": ids})


def _captions(client, item_id: int) -> list[dict]:
    return client.get(f"/api/items/{item_id}").json()["captions"]


def _one(client, item_id: int, cap_id: int) -> dict:
    return [c for c in _captions(client, item_id) if c["id"] == cap_id][0]


def _set_refs(client, item_id: int, cap_id: int, ids: list[int]):
    return client.put(f"/api/items/{item_id}/captions/{cap_id}/refs",
                      json={"item_ids": ids})


def q_caption(mode="has", tags=(), kind="caption"):
    return {"type": "caption", "mode": mode, "caption_kind": kind,
            "caption_tags": [{"name": n, "exclude": x} for n, x in tags]}


def q_meta(name, op, value):
    return {"type": "meta", "name": name, "mtype": "numeric", "op": op,
            "value": value}


# ---- the two lists ---------------------------------------------------------


def test_the_two_kinds_are_two_lists(client):
    a, b = _items(client)[:2]
    cap = _add(client, a, "a dog")
    ins = _add(client, a, "make it snow", "instruction")
    rows = {c["id"]: c["kind"] for c in _captions(client, a)}
    assert rows == {cap: "caption", ins: "instruction"}
    _set_refs(client, a, ins, [b])
    assert [r["item_id"] for r in _one(client, a, ins)["refs"]] == [b]
    # A caption never grows references from its neighbour's edit.
    assert _one(client, a, cap)["refs"] == []


def test_refs_keep_the_order_they_were_given(client):
    a, b, c = _items(client)[:3]
    ins = _add(client, a, "combine these", "instruction")
    _set_refs(client, a, ins, [c, b])
    assert [r["item_id"] for r in _one(client, a, ins)["refs"]] == [c, b]
    # The whole list IS the payload, so reordering is the same call — and a
    # reorder that keeps every id must not trip the unique (caption, item) key.
    _set_refs(client, a, ins, [b, c])
    assert [r["item_id"] for r in _one(client, a, ins)["refs"]] == [b, c]


def test_a_reference_carries_what_a_row_needs_to_show_it(client):
    a, b = _items(client)[:2]
    ins = _add(client, a, "make it snow", "instruction")
    _set_refs(client, a, ins, [b])
    ref = _one(client, a, ins)["refs"][0]
    other = client.get(f"/api/items/{b}").json()
    assert ref["item_uid"] == other["uid"]
    assert ref["name"] == other["name"]
    assert ref["file_id"] == other["active_file_id"]


def test_an_instruction_may_not_reference_its_own_item(client):
    a = _items(client)[0]
    ins = _add(client, a, "make it snow", "instruction")
    r = _set_refs(client, a, ins, [a])
    assert r.status_code == 400
    assert "own item" in r.json()["detail"]


def test_a_plain_caption_takes_no_references(client):
    a, b = _items(client)[:2]
    cap = _add(client, a, "a dog")
    assert _set_refs(client, a, cap, [b]).status_code == 400


def test_deleting_a_referenced_item_leaves_no_orphan_row(client):
    a, b = _items(client)[:2]
    ins = _add(client, a, "make it snow", "instruction")
    _set_refs(client, a, ins, [b])
    client.post("/api/items/delete", json={"item_ids": [b]})
    with client.lib.db.session() as s:
        assert s.query(CaptionRef).count() == 0
    assert _one(client, a, ins)["refs"] == []


# ---- search ----------------------------------------------------------------


def test_caption_and_instruction_never_match_each_other(client):
    a, b = _items(client)[:2]
    _add(client, a, "a dog")
    _add(client, b, "make it snow", "instruction")
    caps = search_items(client, q_caption())["items"]
    instr = search_items(client, q_caption(kind="instruction"))["items"]
    assert [i["id"] for i in caps] == [a]
    assert [i["id"] for i in instr] == [b]


def test_the_meta_tag_filter_works_on_both_lists(client):
    a = _items(client)[0]
    ins = _add(client, a, "make it snow", "instruction")
    client.post(f"/api/items/{a}/captions/{ins}/tags", json={"name": "edit"})
    hit = search_items(client, q_caption(kind="instruction",
                                         tags=[("edit", False)]))
    assert [i["id"] for i in hit["items"]] == [a]
    miss = search_items(client, q_caption(kind="instruction",
                                          tags=[("edit", True)]))
    assert miss["total"] == 0


def test_the_two_counts_are_counted_apart(client):
    a = _items(client)[0]
    _add(client, a, "a dog")
    _add(client, a, "and another")
    _add(client, a, "make it snow", "instruction")
    assert [i["id"] for i in
            search_items(client, q_meta("caption_count", "=", 2))["items"]] == [a]
    assert [i["id"] for i in
            search_items(client, q_meta("instruction_count", "=", 1))["items"]] == [a]
    # And only this item has one at all.
    assert search_items(client, q_meta("instruction_count", ">=", 1))["total"] == 1


def test_the_query_string_says_INSTRUCTION(client):
    parsed = client.post("/api/query/parse", json={"q": "INSTRUCTION:en"}).json()
    node = parsed["tree"]["children"][0]
    assert node["type"] == "caption"
    assert node["caption_kind"] == "instruction"
    assert parsed["canonical"] == "INSTRUCTION:en"


# ---- history ---------------------------------------------------------------


def _latest(client, action: str) -> dict:
    events = client.get("/api/history", params={"limit": 20}).json()["events"]
    return next(e for e in events if e["action"] == action)


def test_the_log_says_which_edit_to_the_references_it_was(client):
    """One op covers adding, removing and reordering, so the summary has to
    tell them apart — it used to report the COUNT AFTERWARDS whatever
    happened, so reordering three pictures read "Gave an instruction 3
    reference images": a sentence about the state, describing the wrong
    action, and indistinguishable from the entry that first attached them.
    """
    a, b, c = _items(client)[:3]
    ins = _add(client, a, "combine these", "instruction")

    def said(refs: list[int]) -> str:
        _set_refs(client, a, ins, refs)
        return _latest(client, "set_caption_refs")["summary"]

    assert said([b, c]) == "Gave an instruction 2 reference images"
    # Same pictures, new order — the case that read worst.
    assert said([c, b]) == "Reordered an instruction's 2 reference images"
    assert said([c]) == "Removed 1 reference image from an instruction"
    # One out and one in at once: neither half is the story, so it says the
    # result instead.
    assert said([b]) == "Changed an instruction's reference images to 1 picture"
    assert said([b, c]) == "Added 1 reference image to an instruction"
    assert said([]) == "Cleared an instruction's reference images"


def test_reverting_a_reference_edit_puts_the_old_order_back(client):
    a, b, c = _items(client)[:3]
    ins = _add(client, a, "combine these", "instruction")
    _set_refs(client, a, ins, [b, c])
    _set_refs(client, a, ins, [c])
    ev = _latest(client, "set_caption_refs")
    r = client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    assert r.json()["reverted"] == [ev["id"]], r.text
    assert [r["item_id"] for r in _one(client, a, ins)["refs"]] == [b, c]


def test_reverting_a_deletion_restores_the_kind_and_the_order(client):
    a, b, c = _items(client)[:3]
    ins = _add(client, a, "combine these", "instruction")
    _set_refs(client, a, ins, [c, b])
    client.delete(f"/api/items/{a}/captions/{ins}")
    assert _captions(client, a) == []
    ev = _latest(client, "remove_caption")
    r = client.post("/api/history/revert", json={"event_ids": [ev["id"]]})
    assert r.json()["reverted"] == [ev["id"]], r.text
    back = _captions(client, a)[0]
    assert back["kind"] == "instruction"
    assert [r["item_id"] for r in back["refs"]] == [c, b]


def test_a_plain_caption_still_logs_exactly_what_it_always_did(client):
    """`kind` and `refs` ride on the event only when they say something, so a
    description's history entry is byte-identical to what older builds wrote —
    which is what keeps the golden log a record of insertions."""
    a = _items(client)[0]
    cap = _add(client, a, "a dog")
    add_ev = _latest(client, "add_caption")
    assert set(add_ev["data"]) == {"item_id", "caption_id", "text"}
    client.delete(f"/api/items/{a}/captions/{cap}")
    rm_ev = _latest(client, "remove_caption")
    assert "kind" not in rm_ev["data"] and "refs" not in rm_ev["data"]


# ---- the item dict's own shape ---------------------------------------------


def test_the_item_dict_names_the_references_by_uid_in_order(client):
    from media_compost.db import Item
    from media_compost.itemdict import item_to_dict

    a, b, c = _items(client)[:3]
    ins = _add(client, a, "combine these", "instruction")
    _set_refs(client, a, ins, [c, b])
    want = [client.get(f"/api/items/{i}").json()["uid"] for i in (c, b)]
    with client.lib.db.session() as s:
        side = item_to_dict(s, s.get(Item, a))
    entry = [x for x in side["captions"] if x["kind"] == "instruction"][0]
    assert entry["refs"] == want          # uids, in order — never DB ids

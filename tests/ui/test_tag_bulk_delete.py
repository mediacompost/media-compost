"""The Tags list's bulk delete: one transaction for a whole selection, with
the SAME events a sequence of single deletions writes — which is what keeps
History readable and the Undo toast able to put everything back.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from media_compost.db import Event, Tag, TagImplication, TagMetaTag
from media_compost.importer import ImportOptions, Importer
from media_compost.ui.config import UiConfig
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library


@pytest.fixture
def client_lib(tmp_path: Path, images: Path):
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths([images], ImportOptions())
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c, lib
    app.dependency_overrides.clear()


def _build_twin(client, prefix: str, item_id: int) -> list[int]:
    """One tag with everything a deletion snapshots — an assignment, an
    implication each way, an alias, a meta tag and a SUBJECT record (whose
    deletion now cascades from the tag's, so the parity covers the cascade
    too) — plus the two tags around it.
    Returns [alias, kid, main] ids, deletion order."""
    main = client.post("/api/tags", json={
        "name": f"{prefix}_main", "comment": "kept words"}).json()
    kid = client.post("/api/tags", json={"name": f"{prefix}_kid"}).json()
    up = client.post("/api/tags", json={"name": f"{prefix}_up"}).json()
    assert client.post(f"/api/tags/{main['id']}/implies",
                       json={"name": f"{prefix}_up"}).status_code == 200
    assert client.post(f"/api/tags/{kid['id']}/implies",
                       json={"name": f"{prefix}_main"}).status_code == 200
    alias = client.post("/api/tags", json={
        "name": f"{prefix}_al", "alias_of": f"{prefix}_main"}).json()
    assert client.post(f"/api/tags/{main['id']}/meta-tags",
                       json={"name": "special"}).status_code == 200
    # The display name carries the prefix so `_norm` can fold it away.
    assert client.post("/api/subjects", json={
        "display_name": f"{prefix}_person", "tag": f"{prefix}_main",
    }).status_code == 200
    assert client.post(f"/api/tags/assign/item/{item_id}", json={
        "tag": f"{prefix}_main", "negative": False}).status_code == 200
    del up
    return [alias["id"], kid["id"], main["id"]]


def _norm(prefix: str, events: list[dict]) -> list[tuple]:
    """An event, with everything twin-specific normalized away: row ids differ
    between the two halves by construction, names differ by their prefix."""
    out = []
    for e in events:
        data = dict(e["data"])
        for k in ("tag_id", "subject_id"):
            data.pop(k, None)
        text = repr(sorted(data.items())).replace(f"{prefix}_", "x_")
        out.append((e["action"], text))
    return out


def _events_by_ids(client, ids: list[int]) -> list[dict]:
    got = {e["id"]: e for e in client.get(
        "/api/history", params={"limit": 500}).json()["events"]}
    return [got[i] for i in ids]


def test_bulk_delete_writes_the_single_deletes_events(client_lib):
    client, lib = client_lib
    item_id = client.get("/api/items").json()["items"][0]["id"]
    ones = _build_twin(client, "one", item_id)
    blks = _build_twin(client, "blk", item_id)

    single: list[int] = []
    for tid in ones:
        res = client.delete(f"/api/tags/{tid}")
        assert res.status_code == 200
        single.extend(res.json()["event_ids"])
    res = client.post("/api/tags/bulk-delete", json={"tag_ids": blks})
    assert res.status_code == 200
    bulk = res.json()["event_ids"]

    a = _norm("one", _events_by_ids(client, single))
    b = _norm("blk", _events_by_ids(client, bulk))
    assert a == b  # same actions, same payloads, same order

    with lib.db.session() as s:
        left = s.execute(select(Tag.name).where(
            Tag.name.like("blk_%"))).scalars().all()
        assert left == ["blk_up"]  # what implies survives; the rest is gone


def test_bulk_delete_reverts_whole(client_lib):
    client, lib = client_lib
    item_id = client.get("/api/items").json()["items"][0]["id"]
    ids = _build_twin(client, "one", item_id)
    res = client.post("/api/tags/bulk-delete", json={"tag_ids": ids})
    events = res.json()["event_ids"]
    assert client.post("/api/history/revert",
                       json={"event_ids": events}).status_code == 200
    with lib.db.session() as s:
        main = s.execute(select(Tag).where(
            Tag.name == "one_main")).scalar_one()
        # The assignment, the implications both ways, the alias and the meta
        # tag all came back — the revert restores the SHAPE.
        alias = s.execute(select(Tag).where(Tag.name == "one_al")).scalar_one()
        assert alias.alias_of_id == main.id
        kid = s.execute(select(Tag).where(Tag.name == "one_kid")).scalar_one()
        up = s.execute(select(Tag).where(Tag.name == "one_up")).scalar_one()
        edges = {(e.tag_id, e.implies_id) for e in s.execute(
            select(TagImplication)).scalars()}
        assert (kid.id, main.id) in edges and (main.id, up.id) in edges
        metas = s.execute(select(TagMetaTag.name).where(
            TagMetaTag.tag_id == main.id)).scalars().all()
        assert metas == ["special"]
    detail = client.get(f"/api/items/{item_id}").json()
    assert any(tg["name"] == "one_main" for tg in detail["tags"])


def test_bulk_delete_skips_an_alias_whose_target_went_first(client_lib):
    client, lib = client_lib
    main = client.post("/api/tags", json={"name": "gone"}).json()
    alias = client.post("/api/tags", json={
        "name": "gone_too", "alias_of": "gone"}).json()
    # Target FIRST: the alias cascades away with it, so its own id is the
    # no-op a single delete of a missing tag is — one delete_tag event, not
    # two, and the one names the alias in its snapshot.
    res = client.post("/api/tags/bulk-delete",
                      json={"tag_ids": [main["id"], alias["id"]]})
    assert res.status_code == 200
    events = _events_by_ids(client, res.json()["event_ids"])
    dels = [e for e in events if e["action"] == "delete_tag"]
    assert len(dels) == 1
    assert dels[0]["data"]["aliases"] == [{"name": "gone_too", "comment": ""}]
    with lib.db.session() as s:
        assert s.execute(select(Tag).where(
            Tag.name.in_(["gone", "gone_too"]))).scalars().all() == []


def test_deleting_an_identity_tag_takes_the_record_with_it(client_lib):
    """Deleting a subject's, place's or event's identity tag deletes the
    RECORD too — through the record op, so the event is the record's own and
    reverts. The alternative was SET NULL, which is how a select-all "clean
    up the tag dump" once silently orphaned every record in a real library;
    a record without its tag is a state nothing may produce."""
    from media_compost.db import Location, Occasion, Subject

    client, lib = client_lib
    assert client.post("/api/subjects", json={
        "display_name": "Ada"}).status_code == 200
    assert client.post("/api/places", json={
        "name": "Adaville"}).status_code == 200
    assert client.post("/api/events", json={
        "display_name": "Ada Con"}).status_code == 200
    with lib.db.session() as s:
        ids = {name: s.execute(select(Tag).where(
            Tag.name == name)).scalar_one().id
            for name in ("subject:ada", "place:adaville", "event:ada_con")}

    # The SINGLE delete cascades…
    res = client.delete(f"/api/tags/{ids['subject:ada']}")
    assert res.status_code == 200
    with lib.db.session() as s:
        assert s.execute(select(Subject).where(
            Subject.display_name == "Ada")).scalars().first() is None
        assert s.execute(select(Tag).where(
            Tag.name == "subject:ada")).scalars().first() is None
    # …and reverting the batch brings BOTH back, re-linked.
    assert client.post("/api/history/revert",
                       json={"event_ids": res.json()["event_ids"]}
                       ).status_code == 200
    with lib.db.session() as s:
        sub = s.execute(select(Subject).where(
            Subject.display_name == "Ada")).scalars().first()
        tag = s.execute(select(Tag).where(
            Tag.name == "subject:ada")).scalars().first()
        assert sub is not None and tag is not None
        assert sub.tag_id == tag.id

    # The BULK sweep cascades the same way, place and event included.
    res = client.post("/api/tags/bulk-delete", json={
        "tag_ids": [ids["place:adaville"], ids["event:ada_con"]]})
    assert res.status_code == 200
    with lib.db.session() as s:
        assert s.execute(select(Location).where(
            Location.name == "Adaville")).scalars().first() is None
        assert s.execute(select(Occasion).where(
            Occasion.display_name == "Ada Con")).scalars().first() is None
    assert client.post("/api/history/revert",
                       json={"event_ids": res.json()["event_ids"]}
                       ).status_code == 200
    with lib.db.session() as s:
        loc = s.execute(select(Location).where(
            Location.name == "Adaville")).scalars().first()
        occ = s.execute(select(Occasion).where(
            Occasion.display_name == "Ada Con")).scalars().first()
        assert loc is not None and occ is not None
        assert loc.tag_id == s.execute(select(Tag).where(
            Tag.name == "place:adaville")).scalar_one().id
        assert occ.tag_id == s.execute(select(Tag).where(
            Tag.name == "event:ada_con")).scalar_one().id

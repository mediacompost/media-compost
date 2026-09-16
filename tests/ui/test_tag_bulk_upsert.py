"""The CSV import's batch endpoint: create-or-update per row, one transaction,
the dialog's keep rule server-side — and the same events the single calls
write, which is what keeps every row revertible.
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from media_compost.db import Event, Tag
from media_compost.ui.config import UiConfig
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library


@pytest.fixture
def client_lib(tmp_path: Path):
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c, lib
    app.dependency_overrides.clear()


def test_bulk_upsert_creates_updates_and_reports_refusals(client_lib):
    client, lib = client_lib
    # An existing tag with its own words, to hold the keep rule against.
    assert client.post("/api/tags", json={
        "name": "kept", "comment": "mine"}).status_code == 200

    res = client.post("/api/tags/bulk-upsert", json={"rows": [
        {"name": "alpha", "comment": "a", "count": 12},
        {"name": "beta"},
        {"name": "kept", "comment": "theirs", "count": 7},
        {"name": "bad name"},          # a space — refused, not fatal
        {"name": "alpha"},                 # a second row for the same tag
    ], "count_meta": "tumblr"})
    assert res.status_code == 200
    rows = res.json()["rows"]

    assert rows[0]["created"] and rows[0]["id"]          # alpha
    assert rows[1]["created"]                            # beta
    assert not rows[2]["created"] and rows[2]["error"] is None  # kept
    assert rows[3]["error"]                              # the refused name
    assert not rows[4]["created"] and rows[4]["id"] == rows[0]["id"]  # dup

    with lib.db.session() as s:
        alpha = s.execute(select(Tag).where(Tag.name == "alpha")).scalar_one()
        # The duplicate row folded into the first occurrence's tag.
        assert alpha.comment == "a"
        from media_compost.db import TagMetaTag

        def counted(tag):
            return {(m.name, m.count) for m in s.execute(
                select(TagMetaTag).where(TagMetaTag.tag_id == tag.id)
            ).scalars().all()}
        # The count landed on the NAMED meta tag's assignment — which the
        # batch also assigns, since a count is a fact about an assignment.
        assert counted(alpha) == {("tumblr", 12)}
        kept = s.execute(select(Tag).where(Tag.name == "kept")).scalar_one()
        # `keep` (the default): the library's own comment stands, gaps fill.
        assert kept.comment == "mine"
        assert counted(kept) == {("tumblr", 7)}
        # No row was made for the refused name.
        assert s.execute(select(Tag).where(Tag.name == "bad name")
                         ).scalar_one_or_none() is None
        # A creation logs the event a single create logs — that is what makes
        # the batch revertible row by row.
        actions = [e.action for e in s.execute(select(Event)).scalars()]
        assert actions.count("create_tag") == 3  # kept, alpha, beta

    # `update`: the file is the newer answer where it says something.
    res = client.post("/api/tags/bulk-upsert", json={
        "rows": [{"name": "kept", "comment": "theirs"}],
        "existing": "update"})
    assert res.status_code == 200
    with lib.db.session() as s:
        kept = s.execute(select(Tag).where(Tag.name == "kept")).scalar_one()
        assert kept.comment == "theirs"

    # `replace`: the tag MATCHES the row, so a field the row carries empty is
    # cleared — the half a switch could never say.
    res = client.post("/api/tags/bulk-upsert", json={
        "rows": [{"name": "kept", "comment": ""}],
        "existing": "replace"})
    assert res.status_code == 200
    with lib.db.session() as s:
        kept = s.execute(select(Tag).where(Tag.name == "kept")).scalar_one()
        assert kept.comment == ""
    # A field the row does not CARRY is not a clear: the batch cannot tell it
    # from "the caller did not mention it", so the dialog sends the empties.
    client.post("/api/tags/bulk-upsert", json={
        "rows": [{"name": "kept", "comment": "only this"}], "existing": "update"})
    client.post("/api/tags/bulk-upsert", json={
        "rows": [{"name": "kept"}], "existing": "replace"})
    with lib.db.session() as s:
        kept = s.execute(select(Tag).where(Tag.name == "kept")).scalar_one()
        assert kept.comment == "only this"
    # And the clearing goes through `update`, so it is the ordinary
    # `comment_tag` event — logged and revertible like a hand edit.
    with lib.db.session() as s:
        ev = [json.loads(e.data) if isinstance(e.data, str) else e.data
              for e in s.execute(select(Event)).scalars()
              if e.action == "comment_tag"]
        cleared = [e for e in ev if e.get("comment") == ""]
        assert cleared and cleared[-1].get("old_comment") == "theirs"
    # A `description` on a row is not a field any more (a tag has none of its
    # own) — a strict body refuses it by name rather than dropping it.
    assert client.post("/api/tags/bulk-upsert", json={
        "rows": [{"name": "kept", "description": "x"}]}).status_code == 422


def test_bulk_upsert_marks_every_named_tag_once(client_lib):
    client, lib = client_lib
    # An existing tag, already carrying the mark — it must not gain a second
    # row or a second event.
    client.post("/api/tags", json={"name": "already"})
    for _ in range(2):  # idempotent single add, to seed the pair
        pass
    client.post("/api/tags/bulk-upsert", json={
        "rows": [{"name": "already"}], "meta_tags": ["danbooru"]})
    res = client.post("/api/tags/bulk-upsert", json={
        "rows": [{"name": "fresh"}, {"name": "already"}, {"name": "fresh"}],
        "meta_tags": ["danbooru", ""]})  # the trailing comma's empty entry
    assert res.status_code == 200
    with lib.db.session() as s:
        from media_compost.db import TagMetaTag

        pairs = s.execute(select(TagMetaTag.name, TagMetaTag.tag_id)).all()
        # One mark per tag, however many rows named it or batches ran.
        assert len(pairs) == 2 and all(n == "danbooru" for n, _ in pairs)
        marks = [e for e in s.execute(select(Event)).scalars()
                 if e.action == "add_link_tag"]
        assert len(marks) == 2  # "already" once, "fresh" once


def test_bulk_upsert_count_modes(client_lib):
    """The count dropdown: the count's own conflict policy, reading nothing
    else — the overwrite switch governs the text columns and not this — per (tag, meta) ASSIGNMENT now. An unset count
    (0) always takes the file's number — there is nothing to compare — and
    a second meta tag's figure sits beside the first untouched."""
    client, lib = client_lib

    def counts(meta="tumblr"):
        from media_compost.db import TagMetaTag
        with lib.db.session() as s:
            return {t.name: n for t, n in s.execute(
                select(Tag, TagMetaTag.count)
                .join(TagMetaTag, TagMetaTag.tag_id == Tag.id)
                .where(TagMetaTag.name == meta)).all()}

    client.post("/api/tags/bulk-upsert", json={
        "rows": [{"name": "a", "count": 100},
                 {"name": "b", "count": 100},
                 {"name": "c", "count": 100}],
        "count_meta": "tumblr", "count_mode": "replace"})
    assert counts() == {"a": 100, "b": 100, "c": 100}
    # min keeps the smaller, max the larger, replace the file's — with
    # overwrite OFF throughout, which the keep rule would have read as
    # "never touch a set count".
    client.post("/api/tags/bulk-upsert", json={
        "rows": [{"name": "a", "count": 40}],
        "count_meta": "tumblr", "count_mode": "min"})
    client.post("/api/tags/bulk-upsert", json={
        "rows": [{"name": "b", "count": 40}],
        "count_meta": "tumblr", "count_mode": "max"})
    client.post("/api/tags/bulk-upsert", json={
        "rows": [{"name": "c", "count": 40}],
        "count_meta": "tumblr", "count_mode": "replace"})
    client.post("/api/tags/bulk-upsert", json={
        "rows": [{"name": "fresh", "count": 40}],
        "count_meta": "tumblr", "count_mode": "min"})
    assert counts() == {"a": 40, "b": 100, "c": 40, "fresh": 40}
    # No mode is `keep`, and `keep` is the whole rule: a number already
    # stored is left alone — the OVERWRITE switch is about the text columns
    # and is not read here, which is what retired the dropdown's old
    # "Keep it, unless overwriting" entry.
    client.post("/api/tags/bulk-upsert", json={
        "rows": [{"name": "a", "count": 7}], "count_meta": "tumblr"})
    assert counts()["a"] == 40
    client.post("/api/tags/bulk-upsert", json={
        "rows": [{"name": "a", "count": 7}],
        "count_meta": "tumblr", "overwrite": True})
    assert counts()["a"] == 40
    client.post("/api/tags/bulk-upsert", json={
        "rows": [{"name": "a", "count": 7}],
        "count_meta": "tumblr", "count_mode": "keep", "overwrite": True})
    assert counts()["a"] == 40
    # …and a gap is still filled, whatever the mode says.
    client.post("/api/tags/bulk-upsert", json={
        "rows": [{"name": "gap", "count": 7}],
        "count_meta": "tumblr", "count_mode": "keep"})
    assert counts()["gap"] == 7
    # ANOTHER site's dump lands beside the first, per assignment — the whole
    # reason the offset moved off the tag.
    client.post("/api/tags/bulk-upsert", json={
        "rows": [{"name": "a", "count": 300}],
        "count_meta": "twitter", "count_mode": "replace"})
    assert counts()["a"] == 40 and counts("twitter") == {"a": 300}
    # And NO count_meta stores nothing: the count is only the minimum's
    # input then, exactly as the dialog's "Don't store" always meant.
    client.post("/api/tags/bulk-upsert", json={
        "rows": [{"name": "loose", "count": 9}]})
    from media_compost.db import TagMetaTag
    with lib.db.session() as s:
        loose = s.execute(select(Tag).where(Tag.name == "loose")).scalar_one()
        assert s.execute(select(TagMetaTag).where(
            TagMetaTag.tag_id == loose.id)).scalars().first() is None


def test_bulk_upsert_takes_per_row_meta_tags(client_lib):
    """The meta-assignments file rides the same batch: a row's own marks are
    applied beside the file-wide ones, once per (tag, name)."""
    client, lib = client_lib
    res = client.post("/api/tags/bulk-upsert", json={
        "rows": [
            {"name": "hero", "meta_tags": ["character", "main character"]},
            {"name": "extra", "meta_tags": ["character"]},
            {"name": "hero", "meta_tags": ["character"]},  # said twice: once
        ],
        "meta_tags": ["danbooru"],
    })
    assert res.status_code == 200
    with lib.db.session() as s:
        from media_compost.db import TagMetaTag

        hero = s.execute(select(Tag).where(Tag.name == "hero")).scalar_one()
        extra = s.execute(select(Tag).where(Tag.name == "extra")).scalar_one()
        pairs = {(tid, n) for n, tid in s.execute(
            select(TagMetaTag.name, TagMetaTag.tag_id)).all()}
        assert pairs == {
            (hero.id, "character"), (hero.id, "main character"),
            (hero.id, "danbooru"),
            (extra.id, "character"), (extra.id, "danbooru"),
        }
        marks = [e for e in s.execute(select(Event)).scalars()
                 if e.action == "add_link_tag"]
        assert len(marks) == 5


def test_bulk_upsert_creation_reverts_like_a_single_create(client_lib):
    client, lib = client_lib
    client.post("/api/tags/bulk-upsert", json={"rows": [{"name": "undoable"}]})
    with lib.db.session() as s:
        ev = s.execute(select(Event).where(Event.action == "create_tag")
                       ).scalars().one()
    assert client.post("/api/history/revert",
                       json={"event_ids": [ev.id]}).status_code == 200
    with lib.db.session() as s:
        assert s.execute(select(Tag).where(Tag.name == "undoable")
                         ).scalar_one_or_none() is None

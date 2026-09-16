"""`GET /api/tags/names` — the autocomplete source, and the one thing it may
never be: a read that scales with the library.

It runs once per KEYSTROKE, so it is filled in two stages (the prefix bucket
from an index, then the substring scan only for what is left) with the counts
correlated rather than aggregated. That is three ways for the answer to
change while looking identical on the ten-tag library every other test uses,
so this file holds the endpoint to a REFERENCE implementation — the single
ranked statement it replaced — over a catalog built to make the stages
disagree if they can.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select

from media_compost.db import Item, ItemTag, Tag, TagMetaTag
from media_compost.ui.config import UiConfig
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library


def reference(lib: Library, needle: str, limit: int) -> list[str]:
    """The ranked names, as ONE statement — the shape the endpoint had before
    it was split into a prefix seek and a substring scan.

    Kept whole and deliberately naive (the whole-table count aggregate
    included): its job is to be obviously right, not fast.
    """
    with lib.db.session() as s:
        counts = (select(ItemTag.tag_id, func.count().label("cnt"))
                  .where(ItemTag.negative.is_(False))
                  .group_by(ItemTag.tag_id).subquery())
        elsewhere = (select(TagMetaTag.tag_id,
                            func.max(TagMetaTag.count).label("mx"))
                     .group_by(TagMetaTag.tag_id).subquery())
        positive = func.coalesce(counts.c.cnt, 0)
        highest = func.coalesce(elsewhere.c.mx, 0)
        lname = func.lower(Tag.name)
        target = func.coalesce(Tag.alias_of_id, Tag.id)
        stmt = (select(Tag.name)
                .join(counts, counts.c.tag_id == target, isouter=True)
                .join(elsewhere, elsewhere.c.tag_id == target, isouter=True))
        if needle:
            stmt = stmt.where(func.instr(lname, needle) > 0).order_by(
                (lname == needle).desc(), func.instr(lname, needle),
                positive.desc(), highest.desc(), Tag.name)
        else:
            stmt = stmt.order_by(positive.desc(), highest.desc(), Tag.name)
        return list(s.execute(stmt.limit(limit)).scalars())


#: Names chosen so every branch has something to be wrong about: an exact
#: name whose count is NOT the highest (`ball` against `ball_pit`), a prefix
#: bucket bigger than some limits and smaller than others, substring-only
#: matches that must sort after every prefix one however they are counted,
#: equal counts that only the meta figure or the name can separate, and
#: characters a LIKE pattern would have read as wildcards.
NAMES = [
    "ball", "ball_pit", "ballroom", "ballad", "balloon", "ball_gown",
    "football", "basketball", "oddball", "the_ball", "ball_",
    "100%_ball", "ball%pit", "under_score_ball", "BallCase",
    "beach", "beachball", "beach_ball", "bee", "belt",
    "ünicorn", "ünique", "very_ünique",
]


@pytest.fixture(scope="module")
def names_lib(tmp_path_factory):
    """A catalog with the shapes above, counted so the ranking has work to do."""
    cfg = UiConfig(data_dir=tmp_path_factory.mktemp("names") / "data")
    lib = Library(cfg)
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        # Items to hang the counts on — inserted directly, since what is
        # being measured is the ranking rather than the import.
        with lib.db.session() as s:
            s.execute(insert(Item), [
                {"uid": f"n{n:04d}", "name": f"i{n}", "kind": "image"}
                for n in range(12)])
            s.commit()
            ids = list(s.execute(select(Item.id).order_by(Item.id)).scalars())
        for i, name in enumerate(NAMES):
            assert c.post("/api/tags", json={"name": name}).status_code == 200
            # A count that repeats often, so ties are the common case.
            for iid in ids[: i % 4]:
                c.post(f"/api/tags/assign/item/{iid}",
                       json={"tag": name, "negative": False})
        # An alias, which answers with its target's count.
        c.post("/api/tags", json={"name": "ball_alias", "alias_of": "ball_pit"})
        # A meta count, which breaks a tie the library's own count cannot.
        tid = next(t["id"] for t in c.get("/api/tags").json()
                   if t["name"] == "ballad")
        c.post(f"/api/tags/{tid}/meta-tags", json={"name": "tumblr",
                                                   "count": 900})
        yield c, lib
    app.dependency_overrides.clear()
    deps.reset_library()


NEEDLES = ["b", "ba", "bal", "ball", "ball_", "balloon", "beach", "be",
           "%", "_", "100%", "ünique", "ü", "case", "zzz", ""]


@pytest.mark.parametrize("needle", NEEDLES)
@pytest.mark.parametrize("limit", [1, 2, 3, 5, 6, 7, 50])
def test_the_two_stages_answer_what_one_ranked_statement_would(
        names_lib, needle, limit):
    """The whole contract: same rows, same order, whatever the split.

    The interesting `limit`s are the ones AROUND the prefix bucket's size —
    below it the substring stage never runs, above it the two concatenate,
    and exactly at it is where an off-by-one lives.
    """
    client, lib = names_lib
    got = [r["name"] for r in
           client.get(f"/api/tags/names?q={needle}&limit={limit}").json()]
    assert got == reference(lib, needle.lower(), limit)


def test_a_wildcard_in_the_fragment_is_a_CHARACTER(names_lib):
    """`%` and `_` are ordinary characters in a tag name, and the endpoint
    reads them as such — the substring stage matches with `instr` and the
    prefix stage with a range, so neither can interpret a pattern."""
    client, _ = names_lib
    assert [r["name"] for r in client.get("/api/tags/names?q=%25").json()] \
        == ["100%_ball", "ball%pit"]
    # A bare `_` would be "any character" to LIKE, i.e. nearly the catalog.
    assert all("_" in r["name"] for r in
               client.get("/api/tags/names?q=_&limit=50").json())


def test_the_prefix_bucket_comes_first_however_it_is_counted(names_lib):
    """Rule (2): a name that STARTS with the fragment beats one that merely
    contains it, whatever their counts — which is what makes the prefix
    bucket a stage of its own rather than an optimisation over the order."""
    client, _ = names_lib
    names = [r["name"] for r in
             client.get("/api/tags/names?q=ball&limit=50").json()]
    starts = [n for n in names if n.lower().startswith("ball")]
    assert names[:len(starts)] == starts, names


def test_an_exact_name_leads_its_own_bucket(names_lib):
    """`ball` before `ball_pit`, which has more pictures: the person has
    finished typing the name, so it is not a ranking question."""
    client, _ = names_lib
    rows = client.get("/api/tags/names?q=ball&limit=50").json()
    assert rows[0]["name"] == "ball"

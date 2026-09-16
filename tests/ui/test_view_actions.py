"""The right sidebar with NOTHING selected: actions over the whole view.

The sidebar is where an action on a set of items lives, and "the set I am
looking at" is a set — so with nothing selected it offers the AI actions, the
group memberships and hide/trash over everything the grid is showing. What
these hold is the half that cannot be seen: the ids never reach the browser
(a view can be the whole library), the scope is the grid's OWN search body so
the two cannot mean different things, and every write is chunked.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from media_compost.db import Event, Item, ItemFaceRun, ItemGroup, Job, TrashedItem
from media_compost.importer import Importer, ImportOptions
from media_compost.testing import make_image
from media_compost.ui.config import UiConfig
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library


@pytest.fixture
def client_lib(tmp_path: Path):
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    src = tmp_path / "src"
    src.mkdir()
    paths = [make_image(src / f"img{i}.png", seed=i * 13 + 1) for i in range(4)]
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths(
            paths, ImportOptions(folders_as_groups=False))
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c, lib
    app.dependency_overrides.clear()


def _ids(lib) -> list[int]:
    with lib.db.session() as s:
        return list(s.execute(select(Item.id).order_by(Item.id)).scalars())


def _scope(**over) -> dict:
    body = {"query": None, "groups": "", "sort": "import_desc"}
    body.update(over)
    return body


def test_the_view_is_the_grids_own_scope(client_lib):
    """The endpoints inherit `ItemSearchRequest`, so "everything here" means
    exactly what the grid is showing — a flat copy of the scope flags would be
    a second place to keep every one of them in step."""
    client, lib = client_lib
    i1, i2, i3, i4 = _ids(lib)
    client.post(f"/api/tags/assign/item/{i1}", json={"tag": "tagged_one"})
    client.post("/api/items/trash", json={"item_ids": [i3]})

    # Untagged: the tagged one drops out, the trashed one was never in.
    r = client.post("/api/items/view/hide",
                    json=_scope(untagged=True, hide=True)).json()
    assert r == {"count": 2, "total": 2}
    with lib.db.session() as s:
        hidden = set(s.execute(
            select(Item.id).where(Item.hidden.is_(True))).scalars())
    assert hidden == {i2, i4}


def test_hiding_reports_what_CHANGED_and_what_it_was_aimed_at(client_lib):
    """Over a view the two differ routinely — the op skips an item already in
    that state — and a caller that only ever saw the first number could not
    say so."""
    client, lib = client_lib
    i1 = _ids(lib)[0]
    client.post("/api/items/hide", json={"item_ids": [i1], "hidden": True})

    r = client.post("/api/items/view/hide",
                    json=_scope(show_hidden=True, hide=True)).json()
    assert r == {"count": 3, "total": 4}


def test_group_membership_over_a_view_goes_both_ways(client_lib):
    client, lib = client_lib
    gid = client.post("/api/groups", json={"name": "Everything"}).json()["id"]

    added = client.post("/api/items/view/groups",
                        json=_scope(add=[gid], remove=[])).json()
    assert added == {"count": 4, "total": 4}
    with lib.db.session() as s:
        assert s.execute(select(ItemGroup).where(
            ItemGroup.group_id == gid)).scalars().all().__len__() == 4

    removed = client.post("/api/items/view/groups",
                          json=_scope(add=[], remove=[gid])).json()
    assert removed["count"] == 4
    with lib.db.session() as s:
        assert s.execute(select(ItemGroup).where(
            ItemGroup.group_id == gid)).scalars().all() == []

    # Neither list is a request that means anything; it answers rather than
    # resolving a scope for nothing.
    assert client.post("/api/items/view/groups",
                       json=_scope(add=[], remove=[])).json() == {
        "count": 0, "total": 0}


def test_trashing_a_view_is_the_ordinary_trash(client_lib):
    """Reversible, which is what makes it offerable over a scope nobody has
    enumerated — and its per-item events are the same ones the id-list
    endpoint writes, so History and revert learn nothing new."""
    client, lib = client_lib
    i1 = _ids(lib)[0]
    client.post(f"/api/tags/assign/item/{i1}", json={"tag": "keeper"})

    r = client.post("/api/items/view/trash", json=_scope(untagged=True)).json()
    assert r == {"count": 3, "total": 3}
    with lib.db.session() as s:
        assert set(s.execute(select(TrashedItem.item_id)).scalars()) \
            == set(_ids(lib)) - {i1}
        actions = [e.action for e in s.execute(
            select(Event).where(Event.entity_type == "item")).scalars()]
    assert actions.count("trash_item") == 3


def test_there_is_no_whole_view_permanent_delete(client_lib):
    """Deliberately absent: trashing is reversible and erasing a library's
    worth of pictures should stay the Trash's own button, where what is about
    to go can be looked at first."""
    from media_compost.ui.server.routers import items as items_router

    client, _ = client_lib
    paths = {r.path for r in items_router.router.routes}
    assert "/api/items/view/delete" not in paths
    assert client.post("/api/items/view/delete",
                       json=_scope()).status_code in (404, 405)


def test_enqueue_view_runs_over_the_whole_view(client_lib, monkeypatch):
    client, lib = client_lib
    i1, i2, i3, i4 = _ids(lib)
    client.post("/api/items/hide", json={"item_ids": [i2], "hidden": True})
    client.post("/api/items/trash", json={"item_ids": [i3]})
    monkeypatch.setattr(lib.jobs, "_ensure_worker", lambda: None)

    r = client.post("/api/ml/enqueue-view", json=_scope(
        task_kind="faces", model="anime_face_magi"))
    assert r.json() == {"queued": 2, "skipped": 0}     # i1 + i4
    with lib.db.session() as s:
        job = s.execute(select(Job).order_by(Job.id.desc())).scalars().first()
        assert sorted(json.loads(job.item_ids)) == sorted([i1, i4])


def test_enqueue_view_skips_what_the_model_has_already_seen(client_lib,
                                                            monkeypatch):
    """Over a whole library, re-running what a model has already seen is the
    difference between minutes and hours — which is why the sidebar sends
    `skip_done` for the kinds that record a per-item run."""
    client, lib = client_lib
    i1, i2, i3, i4 = _ids(lib)
    monkeypatch.setattr(lib.jobs, "_ensure_worker", lambda: None)
    with lib.db.session() as s:
        s.add(ItemFaceRun(item_id=i1, model="anime_face_magi"))
        s.commit()

    r = client.post("/api/ml/enqueue-view", json=_scope(
        task_kind="faces", model="anime_face_magi", skip_done=True))
    assert r.json() == {"queued": 3, "skipped": 1}


def test_an_unknown_kind_is_refused_by_name(client_lib):
    client, _ = client_lib
    assert client.post("/api/ml/enqueue-view",
                       json=_scope(task_kind="nope")).status_code == 400


def test_a_view_action_is_a_WRITE_and_says_so(client_lib):
    """Default-deny is what keeps `READ_ONLY_POSTS` safe, and every one of
    these mutates — none of them may end up on that list."""
    from media_compost.ui.server.build import writes

    for path in ("/api/items/view/groups", "/api/items/view/hide",
                 "/api/items/view/trash", "/api/ml/enqueue-view"):
        assert writes("POST", path), path


def test_every_view_write_is_chunked(client_lib, monkeypatch):
    """One transaction over a million items is minutes of held write lock and
    a rollback nobody wanted. `viewscope.chunks` is the one place that list
    becomes transactions, so the bound holds for every one of them."""
    from media_compost.ui.server import viewscope

    client, lib = client_lib
    gid = client.post("/api/groups", json={"name": "Chunky"}).json()["id"]
    monkeypatch.setattr(viewscope, "VIEW_CHUNK", 3)
    seen: list[int] = []
    real = viewscope.chunks
    monkeypatch.setattr(viewscope, "chunks",
                        lambda ids: [seen.append(len(c)) or c
                                     for c in real(ids)])

    assert client.post("/api/items/view/groups",
                       json=_scope(add=[gid], remove=[])).json()["count"] == 4
    assert seen == [3, 1]


def test_every_view_action_resolves_through_the_ONE_resolution(client_lib,
                                                               monkeypatch):
    """The `QueryCtx` lesson in a second shape: a whole-view write that
    resolved its own scope would be a second definition of what the grid is
    showing, and the two would drift in exactly the flags nobody thinks about
    (hidden items, sequence containers, the trash). Asserted by BEHAVIOUR —
    a grep for the argument list is a test about spelling, and the four
    routers that already had a copy of it each spelled it differently."""
    from media_compost.ui.server import viewscope
    from media_compost.ui.server.routers import groups as groups_router
    from media_compost.ui.server.routers import items as items_router
    from media_compost.ui.server.routers import ml as ml_router

    client, lib = client_lib
    gid = client.post("/api/groups", json={"name": "One"}).json()["id"]
    monkeypatch.setattr(lib.jobs, "_ensure_worker", lambda: None)

    calls: list[str] = []
    real = viewscope.view_ids

    def counting(s, lib_, body):
        calls.append(type(body).__name__)
        return real(s, lib_, body)

    # Patched on the MODULE and on every importer of it: `from .. import
    # viewscope` binds the module, so one patch reaches them all — but a
    # router that had imported the function itself would not be covered, and
    # that is exactly the drift this test exists to catch.
    for mod in (viewscope, groups_router, items_router, ml_router):
        monkeypatch.setattr(getattr(mod, "viewscope", mod), "view_ids",
                            counting, raising=True)

    client.post("/api/items/view/groups", json=_scope(add=[gid], remove=[]))
    client.post("/api/items/view/hide", json=_scope(hide=True))
    client.post("/api/items/view/trash", json=_scope(show_hidden=True))
    client.post("/api/ml/enqueue-view",
                json=_scope(task_kind="faces", model="anime_face_magi"))
    client.post(f"/api/groups/{gid}/assign-view", json=_scope())

    assert calls == ["ViewGroupMembership", "ViewVisibility", "ViewTrash",
                     "EnqueueView", "GroupAssignView"]


def test_no_view_model_SHADOWS_a_field_of_the_search_body_it_inherits():
    """The trap that cost this feature a debugging round, made a ratchet.

    A model inheriting `ItemSearchRequest` re-declaring one of its field
    names does not conflict — it OVERRIDES, silently. `EnqueueView.kind`
    (the job kind) landed on top of the search body's `kind` (the ITEM kind
    the view is filtered to), so `kind="faces"` read as "the view of items
    whose kind is faces" and the endpoint answered 200 with `queued: 0` —
    indistinguishable from an empty view. Hence `task_kind`, and `hide`
    rather than `hidden`.
    """
    from media_compost.ui.server import schemas

    base = set(schemas.ItemSearchRequest.model_fields)
    offenders: dict[str, set[str]] = {}
    for name in dir(schemas):
        model = getattr(schemas, name)
        if not (isinstance(model, type)
                and issubclass(model, schemas.ItemSearchRequest)
                and model is not schemas.ItemSearchRequest):
            continue
        # ITS OWN annotations, not `model_fields` — that one holds the
        # inherited names too, so every subclass would read as an offender.
        # And the rule is ABSOLUTE rather than "a different type": the field
        # that started this was `kind: str` over `kind: str`, identical in
        # every way except what it MEANT, so any test comparing annotations
        # would have passed it.
        clashes = set(vars(model).get("__annotations__", {})) & base
        if clashes:
            offenders[name] = clashes
    assert offenders == {}, offenders

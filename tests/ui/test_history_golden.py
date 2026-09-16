"""The golden event stream — the frozen record of what the library logs.

## Why this exists

The service-layer extraction moves ~8,800 lines of mutation logic out of the
routers and into `media_compost/ops/`. Every one of those moves is supposed to
be behaviour-preserving, and "supposed to be" is not a test. This file is the
test: one scripted scenario drives the API through every revertible action,
snapshots the History rows it produced, reverts them all in reverse, and hashes
the library that comes back.

**An extraction commit that changes `golden/history_events.json` is, by
definition, not an extraction.** That is the whole contract. Regenerate the
file only when you have deliberately changed what the log says, and say so in
the commit message.

## What it catches that ordinary tests do not

- **Action renames.** `history._REVERT`/`_REDO` are keyed by literal strings,
  so a rename silently disables Undo for every event already in every existing
  library (`tests/test_ops_actions.py` guards the set; this guards their use).
- **Event-count drift.** An extraction that logs one event where two were
  logged — or two where one was — changes what the History tab shows and what a
  revert puts back, without failing any assertion about final state.
- **Ordering drift.** `HistoryView.tsx` groups *consecutive* rows of the same
  action and source, so reordering two events changes what the user reads.
- **Payload-key drift.** Every `_revert_*` handler reads `data` by key. Drop or
  rename one and the revert stops working — silently, because the handlers
  return False and the UI just stops offering the button.

## What is deliberately NOT pinned

Values inside `data`, and ids inside summaries. Those move with the fixture
(import order, autoincrement) and pinning them would make this a test of
SQLite's rowid allocator. Keys, order, action, source, entity type and the
shape of the summary are what the revert layer and the UI actually depend on.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from media_compost.ui.config import UiConfig
from media_compost.importer import Importer, ImportOptions
from media_compost.ops import actions
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library
from media_compost.testing import make_image

GOLDEN = Path(__file__).parent / "golden" / "history_events.json"

# Set to regenerate. Do this only when you MEANT to change what the log says.
UPDATE = bool(os.environ.get("MEDIA_COMPOST_UPDATE_GOLDEN"))

# Actions this scenario deliberately does not reach, each for a reason. Keeping
# the list here (rather than just not asserting) is what makes a NEW uncovered
# action fail instead of quietly joining them.
UNCOVERED = {
    # Needs a real detector and a model download; not revertible by design
    # (a detection's faces are evidence, not an edit).
    actions.DETECT_FACES,
    # Same: needs Magi, and produces items a revert cannot un-generate.
    actions.DETECT_PANELS,
    # Same family: an OCR run's regions are evidence, and dismissing or
    # correcting a wrong one are the actions that exist for that. The applier
    # has its own coverage in `tests/ui/test_ml_jobs.py`.
    actions.DETECT_TEXT,
    # The bulk provenance ops are the Python API's crawl batch — no web
    # route writes them, so the WEB scenario cannot reach them. Their events
    # and reverts are driven end to end in
    # `tests/core/test_import_bytes.py`.
    actions.ADD_SOURCES_BULK,
    actions.ADD_TAGS_BULK,
    # Written by the AI job applier when a control image is stored.
    actions.ADD_ARTIFACT,
    # Permanent by definition — there is nothing to revert to.
    actions.DELETE_ITEM,
    actions.DELETE_FILE,
    # NOT permanent any more: a deletion takes the whole subtree and carries
    # a snapshot of it, so it reverts. It stays out of THIS scenario because
    # the groups it builds are named by everything after them, and a delete
    # in the middle of it would be a scenario about the delete. Its own end
    # to end coverage — the subtree, the tree shape, the tags, the members,
    # and the cap past which the event carries no snapshot — is
    # `tests/ui/test_api.py` and `tests/core/test_group_delete_bake.py`.
    actions.DELETE_GROUP,
    # A video render: minutes of ffmpeg over a real film, and not revertible
    # by design (the way back from a rendered file is to make another one
    # active, which the item's own Source list already offers). Its own
    # end-to-end coverage is `tests/test_video_edit.py`, which renders a
    # generated two-second clip.
    actions.EDIT_VIDEO,
    # Rankings have their own end-to-end coverage in
    # `tests/ui/test_rankings.py`, including the judgment revert.
    # `delete_ranking` is not revertible by design (the judgments cascade
    # with it).
    actions.CREATE_RANKING,
    actions.EDIT_RANKING,
    actions.DELETE_RANKING,
    actions.JUDGE_RANKING,
    # Not revertible by design (a set's entries cascade with it, like a
    # ranking's judgments), and a set deleted here would leave its own
    # `create_tag_set` un-undoable in the whole-stream pass. Covered end to
    # end in tests/ui/test_tag_sets.py.
    actions.DELETE_TAG_SET,
    # Covered end to end in tests/ui/test_subject_boxes.py — the sweep there
    # drives the draw, the replace, the clear and every revert.
    actions.SET_APPEARANCE_BOX,
    # Same shape one level down; covered in tests/ui/test_face_outline.py.
    actions.SET_FACE_OUTLINE,
    # Covered end to end in tests/ui/test_faces_history_audit.py, revert
    # included — needs a face whose box was hand-edited, which the scenario's
    # faces are not.
    actions.RESET_FACE_BOX,
    # Covered end to end in tests/ui/test_subjects.py, revert included — the
    # sidebar's drag-reorder, which the scenario has no list to perform.
    actions.REORDER_APPEARANCES,
    # Covered end to end in tests/ui/test_placement_signs.py, revert
    # included.
    actions.SET_PLACEMENT_SIGN,
    actions.DISMISS_RANKING_ITEM,
    actions.UNDISMISS_RANKING_ITEM,
    actions.REMOVE_RANKING_ITEM,
    # A ranking's pools: covered in tests/ui/test_rankings.py too, and
    # `delete_ranking_pool` is not revertible (its judgments cascade).
    actions.CREATE_RANKING_POOL,
    actions.EDIT_RANKING_POOL,
    actions.DELETE_RANKING_POOL,
    actions.REORDER_RANKING_POOLS,
    # Written BY reverting; the scenario's revert pass produces these and they
    # are checked there rather than in the forward stream.
    actions.REVERT,
    # It DELETES the event stream, which is the thing this file exists to
    # snapshot — a step here would empty the golden and then assert on what
    # was left of it. Not revertible either, for the same reason: the entries
    # a revert would read, including its own, are what it removed. Its
    # coverage is `tests/test_history.py`'s three clear-history cases.
    actions.CLEAR_HISTORY,
    # Item-level metadata. Deliberately NOT driven here: this scenario's whole
    # value is that its `events` list does not move, and every step added to it
    # moves that list forever. Their forward writes, both undos, both redos and
    # a folder round trip are covered in `tests/ui/test_metadata_pins.py` — the
    # same split `tests/ui/test_tags_history_audit.py` makes for its own tab.
    # (They also need a two-file item whose files DISAGREE, which is a fixture
    # of its own rather than a step in this one.)
    actions.PIN_METADATA,
    actions.UNPIN_METADATA,
    actions.MUTE_METADATA,
    actions.UNMUTE_METADATA,
}


# ---- fixture ---------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path):
    """A library as a finished AI job would leave it.

    Two distinct images, plus the three things a generation run leaves for
    review: a pending tag in its auto-managed group, a pending caption, and a
    suggested appearance. Those are seeded HERE rather than mid-scenario for a
    reason the round-trip test depends on: rows written straight to the DB
    carry no History event, so nothing can ever undo them — seeded mid-run they
    would show up as un-revertible residue and hide a real one. Approving them
    is what the scenario drives, and approving is ordinary data editing.
    """
    src = tmp_path / "src"
    src.mkdir()
    # Distinct seeds => distinct hashes => two items, no dedup surprises.
    make_image(src / "one.png", seed=11)
    make_image(src / "two.png", seed=22)
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths(
            [src], ImportOptions(folders_as_groups=False)
        )
        s.commit()
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        c.lib = lib  # type: ignore[attr-defined]
        c.pending = _seed_pending(c)  # type: ignore[attr-defined]
        yield c
    app.dependency_overrides.clear()


# ---- normalization ---------------------------------------------------------

_ID_IN_SUMMARY = re.compile(r"#\d+")
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?")
_UID = re.compile(r"\b[0-9a-f]{32}\b")
_SHA = re.compile(r"\b[0-9a-f]{64}\b")


def _summary(text: str) -> str:
    """Item ids move with the fixture; the sentence around them does not."""
    return _ID_IN_SUMMARY.sub("#N", text or "")


def _scrub(value, uids: dict[str, str] | None = None):
    """Make a payload comparable across runs.

    Three things in it are freshly generated every time and say nothing about
    behaviour: wall-clock timestamps, item uids (`db._new_uid` is random), and
    the content hashes of files whose pixels were generated per run. Uids are
    mapped through `uids` rather than blanked, so a payload that references
    ANOTHER item by uid still shows whether it points at the right one.
    """
    if isinstance(value, str):
        text = _ISO.sub("<ts>", value)
        text = _SHA.sub("<sha>", text)
        if uids is not None:
            text = _UID.sub(lambda m: uids.get(m.group(0), "<uid?>"), text)
        else:
            text = _UID.sub("<uid>", text)
        return text
    if isinstance(value, list):
        return [_scrub(v, uids) for v in value]
    if isinstance(value, dict):
        return {k: _scrub(v, uids) for k, v in value.items()}
    return value


def _shape(event: dict) -> dict:
    """One row of the golden: everything the revert layer and the History view
    depend on, and nothing that moves with the fixture."""
    data = event.get("data") or {}
    return {
        "action": event["action"],
        "source": event["source"],
        "entity_type": event.get("entity_type") or "",
        "data_keys": sorted(data.keys()),
        "summary": _summary(event.get("summary") or ""),
    }


def _state_blocks(lib) -> dict:
    """Every item's full dict (`itemdict.item_to_dict` — the merge transfer
    format), keyed by a STABLE label.

    Ordered by (name, id) and not by uid: a uid is random per run, so ordering
    by it would shuffle the labels and make every comparison meaningless.
    """
    from sqlalchemy import select

    from media_compost import itemdict
    from media_compost.db import Item

    with lib.db.session() as s:
        cat = itemdict.ItemDictCatalog(s)
        items = s.execute(
            select(Item).order_by(Item.name, Item.id)
        ).scalars().all()
        uids = {it.uid: f"<item:{it.name}>" for it in items}
        return {uids[it.uid]: _scrub(itemdict.item_to_dict(s, it, catalog=cat),
                                     uids)
                for it in items}


def _residue(lib, before_hash: str) -> set[str]:
    """What did not come back, as labels rather than a hash mismatch.

    ``"+item"`` / ``"-item"`` for an item the revert left behind or lost; a
    block name (``"tags"``, ``"subjects"``, …) for a shared item whose payload
    differs. Naming them is what makes a failure actionable — a bare "the hash
    changed" says nothing about which handler is wrong.
    """
    if _state_hash(lib) == before_hash:
        return set()
    blocks = _state_blocks(lib)
    pristine = _PRISTINE.get(before_hash, {})
    out: set[str] = set()
    if set(blocks) - set(pristine):
        out.add("+item")
    if set(pristine) - set(blocks):
        out.add("-item")
    for uid in set(blocks) & set(pristine):
        now, was = blocks[uid], pristine[uid]
        for key in set(now) | set(was):
            if now.get(key) != was.get(key):
                out.add(key)
    return out


#: Pristine snapshots, keyed by their own hash, so `_residue` can say what
#: changed without the caller having to thread the payload through.
_PRISTINE: dict[str, dict] = {}


def _state_hash(lib) -> str:
    """A digest of everything the library says about itself.

    Built from the item dict, because `itemdict.item_to_dict` is already
    the project's own answer to "everything about this item" — files, sources,
    artifacts, tags with their boxes and placements, groups, captions, faces,
    appearances, links and sequence membership. Reusing it means this hash
    cannot drift from the thing the app considers an item's full state.
    """
    blob = _state_blocks(lib)
    text = json.dumps(blob, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(text.encode()).hexdigest()
    _PRISTINE.setdefault(digest, blob)
    return digest


# ---- the scenario ----------------------------------------------------------


def _run_scenario(c: TestClient, *, destructive: bool = True) -> None:
    """Drive the API through every revertible action, in a fixed order.

    Written as one function rather than a table so each step can use the ids
    the previous ones produced. Ordering is part of what is pinned, so do not
    reorder to be tidy — a reordered stream is a changed golden.

    ``destructive=False`` stops before the tail that deletes tags, subjects,
    places and events and merges the two items away. That tail is genuinely
    unrevertible in reverse: reverting `merge_item` recreates the source item
    with a NEW id, so the earlier events naming the OLD id can no longer find
    what they refer to. That is a property of the log, not a defect — an id is
    not an identity across a delete — so the round-trip test runs the
    non-destructive part and the golden pins the whole thing.
    """
    items = c.get("/api/items").json()["items"]
    a, b = items[0]["id"], items[1]["id"]

    # -- the tag catalog ----------------------------------------------------
    c.post("/api/tags", json={"name": "portrait"})               # create_tag
    c.post("/api/tags", json={"name": "poodle"})
    c.post("/api/tags", json={"name": "dog"})
    c.post("/api/tags", json={"name": "doggy"})
    tags = {t["name"]: t["id"] for t in c.get("/api/tags").json()}
    c.patch(f"/api/tags/{tags['portrait']}",
            json={"comment": "a face, close up"})                # comment_tag
    # The per-meta counts that replaced the tag-level offset: a fresh
    # assignment carrying one (the count rides the add event), then a change
    # on it, which is its own action.
    c.post(f"/api/tags/{tags['portrait']}/meta-tags",
           json={"name": "tumblr", "count": 900})                # add_link_tag
    c.post(f"/api/tags/{tags['portrait']}/meta-tags",
           json={"name": "tumblr", "count": 950})                # set_meta_count
    # KEPT OUT OF THE AUTOCOMPLETE, one tag and one whole namespace. Neither
    # is a deletion — the tag assigns, searches, counts and is listed as
    # before — and both undo.
    c.post("/api/tags/hidden", json={"names": ["doggy"]})        # set_tag_hidden
    c.put("/api/tags/hidden-namespaces",
          json={"namespaces": ["artist"]})              # set_hidden_namespaces
    # THE LONG FORM, back on the tag itself — the library is a tag set now
    # and exports as one.
    c.patch(f"/api/tags/{tags['doggy']}",
            json={"description": "Dogs, at any size."})           # describe_tag
    # WHERE THE LIBRARY FILES IT. The category is the library's own set's,
    # which this call makes along with the set the first time.
    libcat = c.post("/api/tags/categories",
                    json={"name": "Animals"}).json()   # create_tag_set_category
    c.post("/api/tags/category",
           json={"tag_ids": [tags["doggy"], tags["poodle"]],
                 "category_id": libcat["id"]})                # set_tag_category
    c.patch(f"/api/tags/{tags['portrait']}", json={"name": "portrait_shot"})  # rename_tag
    c.post(f"/api/tags/{tags['poodle']}/implies", json={"name": "dog"})  # add_tag_implication
    c.delete(f"/api/tags/{tags['poodle']}/implies/dog")           # remove_tag_implication
    c.patch(f"/api/tags/{tags['doggy']}", json={"alias_of": "dog"})  # set_alias

    # -- assignment ---------------------------------------------------------
    c.post(f"/api/tags/assign/item/{a}", json={"tag": "portrait_shot"})   # add_tag
    c.post(f"/api/tags/assign/item/{a}", json={"tag": "blurry",
                                               "negative": True})
    c.delete(f"/api/tags/assign/item/{a}/blurry")                 # remove_tag
    c.post("/api/tags/quick-assign", json={"item_ids": [b],
                                           "positive": ["portrait_shot"],
                                           "negative": [], "remove": False})

    # -- per-item tag groups ------------------------------------------------
    tg = c.post(f"/api/tags/item/{a}/groups", json={"name": "Hers"}).json()
    c.patch(f"/api/tags/groups/{tg['id']}", json={"name": "Her side"})
    c.post(f"/api/tags/groups/{tg['id']}/tags", json={"name": "de"})  # add_tag_group_tag
    c.delete(f"/api/tags/groups/{tg['id']}/tags/de")             # remove_tag_group_tag
    c.post(f"/api/tags/item/{a}/move-instance",
           json={"name": "portrait_shot", "from_group_id": None,
                 "to_group_id": tg["id"]})                        # move_tag_group
    doomed = c.post(f"/api/tags/item/{a}/groups", json={"name": "Spare"}).json()
    c.delete(f"/api/tags/groups/{doomed['id']}")                  # delete_tag_group

    # -- library groups -----------------------------------------------------
    g = c.post("/api/groups", json={"name": "Trips", "icon": "folder"}).json()
    c.post(f"/api/items/{a}/groups/{g['id']}")                    # add_to_group
    c.delete(f"/api/items/{a}/groups/{g['id']}")                  # remove_from_group
    c.post(f"/api/tags/assign/group/{g['id']}", json={"tag": "travel"})  # add_group_tag
    c.delete(f"/api/tags/assign/group/{g['id']}/travel")          # remove_group_tag

    # -- captions -----------------------------------------------------------
    cap = c.post(f"/api/items/{a}/captions", json={"text": "a dog"}).json()
    cid = cap.get("id") or c.get(f"/api/items/{a}").json()["captions"][0]["id"]
    c.patch(f"/api/items/{a}/captions/{cid}", json={"text": "a small dog"})
    c.post(f"/api/items/{a}/captions/{cid}/tags", json={"name": "en"})
    c.delete(f"/api/items/{a}/captions/{cid}/tags/en")
    c.delete(f"/api/items/{a}/captions/{cid}")                    # remove_caption

    # -- instructions (a caption with an ordered list of source items) -------
    ins = c.post(f"/api/items/{a}/captions",
                 json={"text": "make it snow", "kind": "instruction"}).json()
    iid_ = ins["id"]
    c.put(f"/api/items/{a}/captions/{iid_}/refs",
          json={"item_ids": [b]})                                 # set_caption_refs
    c.put(f"/api/items/{a}/captions/{iid_}/refs", json={"item_ids": []})
    c.delete(f"/api/items/{a}/captions/{iid_}")

    # -- meta tags (the link_tags namespace) --------------------------------
    c.post("/api/link-tags/create", json={"name": "scan"})        # create_meta_tag
    c.post("/api/link-tags/update", json={"name": "scan",
                                          "comment": "from a scanner"})
    c.post("/api/link-tags/update",
           json={"name": "scan",
                 "description": "Anything that came off a flatbed."})
    c.post("/api/link-tags/update", json={"name": "scan", "new_name": "scanned"})
    c.post("/api/link-tags/delete", json={"name": "scanned"})     # delete_meta_tag

    # -- relationships ------------------------------------------------------
    rel = c.post("/api/relationships",
                 json={"from_item_id": a, "to_item_id": b,
                       "kind": "manual", "meta": {}}).json()
    c.post(f"/api/relationships/{rel['id']}/tags", json={"name": "same_scene"})
    c.delete(f"/api/relationships/{rel['id']}/tags/same_scene")
    c.delete(f"/api/relationships/{rel['id']}")                   # remove_link

    # -- item lifecycle -----------------------------------------------------
    c.patch(f"/api/items/{a}", json={"taken_at": 20190400000000})  # set_taken
    c.post(f"/api/items/{a}/rotate", json={"dir": "right"})        # rotate_item
    c.post("/api/items/hide", json={"item_ids": [b], "hidden": True})
    c.post("/api/items/hide", json={"item_ids": [b], "hidden": False})
    c.post("/api/items/trash", json={"item_ids": [b]})             # trash_item
    c.post("/api/items/restore", json={"item_ids": [b]})           # restore_item

    # -- files --------------------------------------------------------------
    files = c.get(f"/api/items/{a}").json()["files"]
    fid = files[0]["id"]
    # `url=`, not `name=` + a stray `is_url` — that spelling was silently
    # dropped, so the scenario had been adding a plain FILENAME that happened
    # to look like a URL. Bodies refuse unknown fields now, which surfaced it.
    src = c.post(f"/api/files/{fid}/names",
                 json={"url": "https://example.com/one.png"})
    names = c.get(f"/api/items/{a}").json()["files"][0]["names"]
    nid = names[-1]["id"]
    c.patch(f"/api/files/{fid}/names/{nid}",
            json={"name": "https://example.com/1.png"})            # rename_source
    c.delete(f"/api/files/{fid}/names/{nid}")                      # remove_source

    # -- subjects and appearances -------------------------------------------
    sub = c.post("/api/subjects", json={"display_name": "Alice",
                                        "comment": "the tall one",
                                        "since_date": 19900614}).json()
    sid = _first_id(sub, c, "/api/subjects", "Alice")
    c.patch(f"/api/subjects/{sid}", json={"display_name": "Alice Meyer"})
    c.patch(f"/api/subjects/{sid}", json={"comment": "the taller one"})
    c.patch(f"/api/subjects/{sid}", json={"since_date": 19900615})
    c.post(f"/api/tags/groups/{tg['id']}/subjects",
           json={"subject_id": sid})                          # add_tag_group_subject
    c.delete(f"/api/tags/groups/{tg['id']}/subjects/{sid}")   # remove_tag_group_subject
    c.post("/api/subjects/appearances",
           json={"item_id": a, "subject_id": sid})                 # add_appearance
    apid = _appearance_id(c, a)
    if apid:
        c.patch(f"/api/subjects/appearances/{apid}",
                json={"when": {"age": 12}})                        # edit_appearance
        c.delete(f"/api/subjects/appearances/{apid}")              # remove_appearance

    # -- reviewing what a model left behind ----------------------------------
    # The rows were seeded by the fixture (see its docstring); these are the
    # same three endpoints the review UI calls.
    pend = c.pending  # type: ignore[attr-defined]
    c.post(f"/api/ml/placements/{pend['placement_id']}/approve")   # approve_tag
    c.post(f"/api/ml/captions/{pend['caption_id']}/approve")       # approve_caption
    c.patch(f"/api/subjects/appearances/{pend['appearance_id']}",
            json={"confirm": True})                                # confirm_appearance

    # -- faces --------------------------------------------------------------
    f1 = c.post("/api/faces", json={"item_id": a, "x": .1, "y": .1,
                                    "w": .2, "h": .2}).json()
    f2 = c.post("/api/faces", json={"item_id": a, "x": .5, "y": .5,
                                    "w": .2, "h": .2}).json()
    ids = [row["id"] for row in c.get(f"/api/faces/item/{a}").json()]
    c.patch(f"/api/faces/{ids[0]}", json={"x": .12, "y": .12,
                                          "w": .2, "h": .2})       # move_face
    c.post(f"/api/faces/{ids[0]}/subject", json={"subject_id": sid})  # name_face
    c.delete(f"/api/faces/{ids[0]}/subject/{sid}")                 # unname_face
    c.post("/api/faces/name-cluster",
           json={"face_ids": ids, "subject_id": sid})              # name_faces
    c.post("/api/faces/split", json={"face_ids": [ids[1]]})        # split_faces

    # Splitting minted a NAMELESS subject to hold the stray, which is the only
    # way this scenario reaches `name_subject`. It has to be found in the DB:
    # the Subjects list deliberately hides a subject with neither tag nor name,
    # because its cluster row below already is it. Named here, before
    # merge-clusters folds the faces back and takes the empty identity away.
    nameless = _nameless_subject_id(c)
    assert nameless, "splitting a face should have minted a nameless subject"
    # A NAME and an identity TAG are two different claims and two different
    # events: `rename_subject` and `name_subject`.
    c.patch(f"/api/subjects/{nameless}", json={"display_name": "Bob"})
    c.patch(f"/api/subjects/{nameless}", json={"tag": "subject:bob"})  # name_subject

    c.post("/api/faces/merge-clusters", json={"face_ids": ids})    # merge_faces
    # THE OTHER ANSWER to "who is this" — somebody with no name — and the way
    # back out of it, which is the same verb.
    c.post("/api/faces/unnamed-cluster",
           json={"face_ids": ids})                            # set_cluster_unnamed
    c.post("/api/faces/unnamed-cluster",
           json={"face_ids": ids, "unnamed": False})
    # …and "not this person", said of two whole clusters — the lookalike
    # strip's ✕. Two faces of one merged cluster are one identity, so the
    # second side is the face split off above.
    c.post("/api/faces/not-matching",
           json={"face_ids": [ids[0]],
                 "other_face_ids": [ids[1]]})                 # clusters_differ
    c.patch(f"/api/faces/{ids[1]}", json={"dismissed": True})      # dismiss_face
    c.delete(f"/api/faces/{ids[1]}")                               # delete_face

    # -- detected text ------------------------------------------------------
    # Two hand-drawn blocks, each with a line under it, driven through every
    # revertible text action. Detection itself (`detect_text`) is UNCOVERED,
    # like the other model runs. The DELETED block is the last-created one,
    # so its revert restores the subtree under the SAME rowids — the same
    # fact the faces block above leans on (SQLite hands back max+1).
    t_rows = c.post("/api/ocr", json={"item_id": a, "x": .1, "y": .1,
                                      "w": .4, "h": .1,
                                      "text": "first block"}).json()  # add_text
    t1 = t_rows[0]["id"]
    c.post("/api/ocr", json={"item_id": a, "x": .1, "y": .1,
                             "w": .2, "h": .1, "text": "first",
                             "level": "line", "parent_id": t1})       # add_text
    c.patch(f"/api/ocr/{t1}", json={"text": "first block, corrected"})  # edit_text
    c.patch(f"/api/ocr/{t1}", json={"x": .12, "y": .1, "w": .4, "h": .1,
                                    "quad": [[.12, .1], [.52, .12],
                                             [.52, .2], [.12, .18]]})   # move_text
    c.patch(f"/api/ocr/{t1}", json={"dismissed": True})             # dismiss_text
    c.patch(f"/api/ocr/{t1}", json={"dismissed": False})            # dismiss_text
    t2_rows = c.post("/api/ocr", json={"item_id": a, "x": .1, "y": .5,
                                       "w": .4, "h": .1,
                                       "text": "second"}).json()      # add_text
    t2 = next(r["id"] for r in t2_rows if r["text"] == "second")
    c.post("/api/ocr", json={"item_id": a, "x": .1, "y": .5,
                             "w": .2, "h": .1, "text": "se",
                             "level": "line", "parent_id": t2})       # add_text
    c.post(f"/api/ocr/item/{a}/order",
           json={"region_ids": [t2, t1]})                           # reorder_text
    # Deleting the block CASCADEs its line away; the event carries the whole
    # subtree, which is what its revert restores from.
    c.request("DELETE", f"/api/ocr/{t2}")                           # delete_text

    # WHERE it was taken, said by hand: a pair, then back to the file, then
    # "there is none" — the three states, in the order somebody meets them.
    c.patch(f"/api/items/{a}", json={"lat": 35.6812, "lon": 139.7671})
    c.patch(f"/api/items/{a}", json={"clear_coords": True})
    c.patch(f"/api/items/{a}", json={"no_coords": True})              # set_coords

    # -- places -------------------------------------------------------------
    pl = c.post("/api/places", json={"tag": "",
                                     "lat": 35.6, "lon": 139.7}).json()
    pid = _first_id(pl, c, "/api/places", None)
    c.patch(f"/api/places/{pid}", json={"name": "Tokyo"})          # edit_place
    c.patch(f"/api/places/{pid}", json={"tag": "place:tokyo"})       # name_place
    # A place INSIDE another: the column is the tree and the implication is
    # what it means, so this writes an `add_tag_implication` as well.
    up = c.post("/api/places", json={"tag": "place:japan"}).json()
    upid = next(r["id"] for r in up if r["tag"] == "place:japan")
    c.patch(f"/api/places/{pid}", json={"parent_id": upid})
    c.patch(f"/api/places/{pid}", json={"clear_parent": True})
    c.post("/api/events/dismiss-place", json={"item_id": a,
                                              "location_id": pid})
    # The file's OWN place, refused. Keyed on the item alone (the suggested
    # place need not exist), so any item can say no.
    c.post("/api/events/dismiss-file-place", json={"item_id": a})

    # -- events -------------------------------------------------------------
    ev = c.post("/api/events", json={"tag": "", "display_name": "Comic-Con",
                                     "comment": "", "start_date": 20140705,
                                     "end_date": 20140710,
                                     "place_ids": []}).json()
    eid = _first_id(ev, c, "/api/events", "Comic-Con")
    # The comment is the identity TAG's, so it logs `comment_tag`; the span is
    # what makes this an `edit_event`.
    c.patch(f"/api/events/{eid}", json={"comment": "the big one",
                                        "end_date": 20140711})     # edit_event
    c.post("/api/events/dismiss-event", json={"item_id": a,
                                              "occasion_id": eid})

    # -- a group edited, moved and duplicated --------------------------------
    # What a group SAYS and where it SITS are two verbs; the duplicate is a
    # third, and its undo takes the whole copy back down.
    c.patch(f"/api/groups/{g['id']}",
            json={"name": "Journeys", "icon": "map"})              # edit_group
    shelf = c.post("/api/groups", json={"name": "Albums"}).json()
    c.post(f"/api/groups/{g['id']}/move",
           json={"new_parent_id": shelf["id"]})                    # move_group
    c.post(f"/api/groups/{g['id']}/duplicate", json={})            # duplicate_group

    # -- sequences -----------------------------------------------------------
    seq = c.post("/api/sequences",
                 json={"name": "Chapter 1", "item_ids": [a, b]}).json()
    sq = seq["id"]
    members = [m["id"] for m
               in c.get(f"/api/sequences/{sq}").json()["members"]]
    c.patch(f"/api/sequences/{sq}", json={"name": "Chapter One"})
    c.post(f"/api/sequences/{sq}/reorder",
           json={"member_ids": list(reversed(members))})
    # Creating the sequence already made it b's main one, so the change here
    # is to clear it and put it back — both arms of the same verb.
    c.patch(f"/api/items/{b}/main-sequence", json={"sequence_id": None})
    c.patch(f"/api/items/{b}/main-sequence", json={"sequence_id": sq})
    # One member out (the sequence survives), then the sequence itself.
    c.post(f"/api/sequences/{sq}/remove", json={"member_ids": members[:1]})
    c.delete(f"/api/sequences/{sq}")

    # -- tag boxes, drawn on their own ---------------------------------------
    # The annotator's own edits: they touch no assignment, so nothing else in
    # this scenario puts one in the log.
    box = c.post(f"/api/tags/assign/item/{a}/box",
                 json={"tag": "portrait_shot",
                       "box": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}}).json()
    c.patch(f"/api/tags/box/{box['id']}",
            json={"x": 0.3, "y": 0.3, "w": 0.2, "h": 0.2})
    c.delete(f"/api/tags/box/{box['id']}")

    # -- an editor save -------------------------------------------------------
    # A rotate saved INTO the item: it adds a file and makes it active, which
    # is the shape whose undo is "put the previous file back".
    src = next(f["id"] for f in c.get(f"/api/items/{a}").json()["files"]
               if f["active"])
    c.post(f"/api/items/{a}/edit",
           json={"source_file_id": src, "rotate": 90})            # edit_image

    # -- a link reversed ------------------------------------------------------
    # An `edit` link, because that is the kind whose flip re-roots the cluster
    # — the case a plain "flip it again" undo would get wrong.
    rev = c.post("/api/relationships",
                 json={"from_item_id": a, "to_item_id": b,
                       "kind": "edit", "meta": {}}).json()
    c.post(f"/api/relationships/{rev['id']}/flip")                 # flip_link

    # -- a tag set, edited every way the UI can ------------------------------
    # An imported tag LIST kept apart from the library's tags: every write is
    # its own op and event, and every one but the delete reverts. The set is
    # left ENABLED here on purpose — nothing after this block assigns a name
    # it knows, so the assignment door stays out of the stream.
    tset = c.post("/api/tag-sets", json={"name": "Scenario set"}).json()   # create_tag_set
    c.patch(f"/api/tag-sets/{tset['id']}",
            json={"description": "for the golden"})                     # edit_tag_set
    tcat = c.post(f"/api/tag-sets/{tset['id']}/categories",
                  json={"name": "people"}).json()                       # create_tag_set_category
    tsub = c.post(f"/api/tag-sets/{tset['id']}/categories",
                  json={"name": "count", "parent_id": tcat["id"]}).json()
    c.patch(f"/api/tag-sets/{tset['id']}/categories/{tsub['id']}",
            json={"name": "how_many"})                                  # edit_tag_set_category
    c.post(f"/api/tag-sets/{tset['id']}/categories/{tsub['id']}/move",
           json={"parent_id": None, "index": 0})                        # move_tag_set_category
    c.post(f"/api/tag-sets/{tset['id']}/categories/{tsub['id']}/move",
           json={"parent_id": tcat["id"], "index": 0})
    tent = c.post(f"/api/tag-sets/{tset['id']}/entries",
                  json={"name": "scenario_1girl", "description": "one",
                        "category_id": tsub["id"],
                        "aliases": ["scenario_1female"]}).json()       # create_tag_set_entry
    c.patch(f"/api/tag-sets/{tset['id']}/entries/{tent['id']}",
            json={"description": "exactly one", "count": 5})            # edit_tag_set_entry
    # THE LABELS A TAG SET PUTS ON ITS OWN NAMES — its meta tags. The
    # rename has to carry the entries that wear one, and the delete has to
    # take their claims with it, so both are exercised over an entry that
    # carries it.
    tmeta = c.post(f"/api/tag-sets/{tset['id']}/meta-tags",
                   json={"name": "scenario_character",
                         "comment": "somebody"}).json()                 # create_tag_set_meta
    c.patch(f"/api/tag-sets/{tset['id']}/entries/{tent['id']}",
            json={"meta": ["scenario_character"]})
    c.patch(f"/api/tag-sets/{tset['id']}/meta-tags/{tmeta[-1]['id']}",
            json={"name": "scenario_person"})                           # edit_tag_set_meta
    c.delete(f"/api/tag-sets/{tset['id']}/meta-tags/{tmeta[-1]['id']}")  # delete_tag_set_meta
    c.put(f"/api/tag-sets/{tset['id']}/enabled", json={"enabled": False})  # set_tag_set_enabled
    c.put(f"/api/tag-sets/{tset['id']}/enabled", json={"enabled": True})
    c.post(f"/api/tag-sets/{tset['id']}/duplicate",
           json={"name": "Scenario copy"})                              # duplicate_tag_set
    c.post(f"/api/tag-sets/{tset['id']}/entries/bulk",
           json={"rows": [{"name": "scenario_2girls",
                           "category": ["people", "how_many"]},
                          {"name": "scenario_solo"}]})                  # import_tag_set
    c.delete(f"/api/tag-sets/{tset['id']}/entries/{tent['id']}")        # delete_tag_set_entry
    c.delete(f"/api/tag-sets/{tset['id']}/categories/{tsub['id']}")     # delete_tag_set_category

    # -- a second import, through the API ------------------------------------
    # The fixture seeds by calling the Importer directly, which logs nothing.
    # This is the run that produces the `import` event.
    extra = _extra_source(c)
    job = c.post("/api/import/paths",
                 json={"paths": [str(extra)],
                       "folders_as_groups": False}).json()
    _await_import(c, job["id"])

    # -- merges, deletes and splits (destructive; last) ----------------------
    if not destructive:
        return
    c.post(f"/api/tags/{tags['doggy']}/merge", json={"into": "dog",
                                                     "keep_alias": True})
    c.delete(f"/api/tags/{tags['dog']}")                            # delete_tag
    c.delete(f"/api/subjects/{sid}")                                # delete_subject
    c.delete(f"/api/places/{pid}")                                  # delete_place
    c.delete(f"/api/events/{eid}")                                  # delete_event
    c.post("/api/items/merge", json={"source_id": b, "target_id": a})  # merge_item
    merged = c.get(f"/api/items/{a}").json()
    assert len(merged["files"]) > 1, "the merge should have folded b's file in"
    # Whichever file is NOT already active — `update_item` only logs when the
    # id actually changes, so picking files[1] blindly can log nothing.
    other = next(f for f in merged["files"] if not f["active"])
    c.patch(f"/api/items/{a}",
            json={"active_file_id": other["id"]})                    # set_active_file
    c.post(f"/api/files/{other['id']}/split")                        # split_item


def _first_id(created, c: TestClient, path: str, name: str | None):
    """These routers answer with the whole refreshed LIST, not the new row."""
    rows = created if isinstance(created, list) else c.get(path).json()
    if isinstance(rows, dict):
        rows = rows.get("rows") or rows.get("items") or []
    if name is None:
        return rows[-1]["id"]
    for r in rows:
        if r.get("display_name") == name or r.get("tag") == name:
            return r["id"]
    return rows[-1]["id"]


def _appearance_id(c: TestClient, item_id: int):
    subs = c.get(f"/api/items/{item_id}").json().get("subjects") or []
    for s in subs:
        for ap in s.get("appearances") or []:
            return ap["id"]
    return None


def _nameless_subject_id(c: TestClient):
    """A subject with neither tag nor display name. The Subjects list hides
    these on purpose, so the API cannot answer this question."""
    from sqlalchemy import select

    from media_compost.db import Subject

    with c.lib.db.session() as s:  # type: ignore[attr-defined]
        return s.execute(
            select(Subject.id).where(Subject.tag_id.is_(None),
                                     Subject.display_name == "")
        ).scalars().first()


def _seed_pending(c: TestClient) -> dict:
    """Write the three things an AI job leaves behind for review.

    Through the ORM rather than by running a model: the scenario's subject is
    the APPROVAL path, which is library data editing and in scope; generation
    needs multi-GB weights and is out.
    """
    from sqlalchemy import select

    from media_compost.db import (
        Caption, Item, ItemSubject, ItemTag, ItemTagGroup, ItemTagPlacement,
        Subject, Tag,
    )

    with c.lib.db.session() as s:  # type: ignore[attr-defined]
        item_id = s.execute(select(Item.id).order_by(Item.id)).scalars().first()
        guess = Tag(name="ai_guess")
        who = Tag(name="subject:nina")
        s.add_all([guess, who])
        s.flush()
        subject = Subject(tag_id=who.id, display_name="Nina")
        it = ItemTag(item_id=item_id, tag_id=guess.id, negative=False,
                     pending=True)
        # The auto-managed group a generation run files its guesses into.
        grp = ItemTagGroup(item_id=item_id, name="Pending (tagger)",
                           position=0, system=True)
        s.add_all([subject, it, grp])
        s.flush()
        pl = ItemTagPlacement(item_tag_id=it.id, group_id=grp.id)
        cap = Caption(item_id=item_id, text="a machine wrote this",
                      position=99, pending=True, model="tagger")
        ap = ItemSubject(item_id=item_id, subject_id=subject.id,
                         assigned_by="suggested", match_score=0.87)
        # A guess puts its subject's tag on the picture PENDING (see
        # `jobs._pending_subject_tag`). Seeding the appearance without it would
        # be a state no run produces, and confirming would then look as though
        # it invented the tag.
        who_tag = ItemTag(item_id=item_id, tag_id=who.id, negative=False,
                          pending=True)
        s.add_all([pl, cap, ap, who_tag])
        s.commit()
        return {"placement_id": pl.id, "caption_id": cap.id,
                "appearance_id": ap.id}


def _await_import(c: TestClient, job_id: str, timeout: float = 30.0) -> dict:
    """`POST /api/import/paths` answers immediately and imports on a thread, so
    its History entry lands after the response. Wait for it, or the golden
    would record a different number of events depending on machine speed."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = c.get(f"/api/import/{job_id}").json()
        if job.get("status") != "running":
            return job
        time.sleep(0.02)
    raise AssertionError(f"import job {job_id} never finished")


def _extra_source(c: TestClient) -> Path:
    """A third image on disk, outside the library, for the API import step."""
    src = Path(c.lib.config.data_dir).parent / "extra"  # type: ignore[attr-defined]
    src.mkdir(exist_ok=True)
    path = src / "three.png"
    if not path.exists():
        make_image(path, seed=33)
    return path


# ---- the tests -------------------------------------------------------------


def _stream(c: TestClient) -> list[dict]:
    rows = c.get("/api/history?limit=500").json()["events"]
    # The API pages newest-first; the golden reads in the order things happened.
    return [_shape(e) for e in reversed(rows)]


def test_the_event_stream_matches_the_golden(client):
    _run_scenario(client)
    stream = _stream(client)
    payload = {"events": stream,
               "state_hash": _state_hash(client.lib)}

    if UPDATE:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        pytest.skip(f"golden written to {GOLDEN} — review the diff and commit it")

    # A MISSING golden is a failure, not an invitation to write one. It used
    # to fall into the branch above (`UPDATE or not GOLDEN.exists()`), which
    # made the file self-healing: delete it, or fail to commit it, and the run
    # quietly recorded whatever the code did that day and went green. The
    # other two goldens in this suite already blow up on a missing file; this
    # is the one that recorded 87 events and could regenerate itself.
    assert GOLDEN.exists(), (
        f"{GOLDEN} is missing. It is the record of what the History log says, "
        f"so a run cannot supply it — restore the file from git, or, if the "
        f"log genuinely has to change, regenerate with "
        f"MEDIA_COMPOST_UPDATE_GOLDEN=1 and say why in the commit.")
    want = json.loads(GOLDEN.read_text(encoding="utf-8"))
    got = payload
    if got["events"] != want["events"]:
        # A readable failure: the first row that differs, not a 400-line dump.
        for i, (g, w) in enumerate(zip(got["events"], want["events"])):
            assert g == w, (
                f"event #{i} changed.\n  golden: {w}\n  now:    {g}\n"
                "If you MEANT to change what the log says, regenerate with "
                "MEDIA_COMPOST_UPDATE_GOLDEN=1 and say so in the commit."
            )
        assert len(got["events"]) == len(want["events"]), (
            f"the scenario logged {len(got['events'])} events, the golden has "
            f"{len(want['events'])}"
        )
    assert got["state_hash"] == want["state_hash"], (
        "the scenario ended with a different library than the golden records"
    )


def test_the_scenario_reaches_every_revertible_action(client):
    """The coverage check. Without it the golden silently stops guarding an
    action the moment somebody adds one."""
    _run_scenario(client)
    seen = {e["action"] for e in _stream(client)}
    missing = (actions.ALL - UNCOVERED) - seen
    assert not missing, (
        f"the golden scenario never triggers: {sorted(missing)}. Add a step to "
        "_run_scenario, or list the action in UNCOVERED with a reason."
    )


def test_reverting_the_whole_stream_puts_the_library_back(client):
    """Every logged action reverts, and reverting all of them in reverse order
    returns the library to what the import left behind.

    This is the strongest single statement the History layer can make, and it
    is exactly what the extraction must not break: the revert handlers read
    `data` by key, so a payload the ops layer spells differently fails here
    rather than in production six months later.

    Runs the non-destructive part of the scenario — see `_run_scenario`.
    """
    before = _state_hash(client.lib)
    _run_scenario(client, destructive=False)
    rows = client.get("/api/history?limit=500").json()["events"]

    refused = []
    for e in rows:  # newest first — the order an Undo button walks
        if e["action"] in actions.NOT_REVERTIBLE:
            continue
        res = client.post("/api/history/revert",
                          json={"event_ids": [e["id"]]}).json()
        if e["id"] not in (res.get("reverted") or []):
            refused.append(e["action"])

    assert sorted(refused) == sorted(KNOWN_UNREVERTIBLE), (
        f"the set of un-undoable actions changed.\n"
        f"  expected: {sorted(KNOWN_UNREVERTIBLE)}\n"
        f"  got:      {sorted(refused)}\n"
        "A NEW entry is a regression. A MISSING one means somebody fixed the "
        "bug — delete it from KNOWN_UNREVERTIBLE and regenerate the golden."
    )

    # And the library really came back. ONE residue is expected, and it is by
    # design: `_revert_import` TRASHES what an import created rather than
    # deleting it, because the undo is itself reversible and permanently
    # destroying files somebody may have edited since is not what an Undo
    # button should do. The item is therefore still present, in the Trash.
    #
    # Anything else here is a revert that reported success without putting the
    # library back — which is the failure this whole test exists to catch, and
    # which four separate handlers were doing before it was written.
    diff = _residue(client.lib, before)
    assert diff == {"+item"}, (
        f"reverting every event left the library changed in: {sorted(diff)}. "
        "Only the trashed import is expected; anything else is a revert that "
        "claimed to work and did not."
    )


#: Actions that refuse to undo in a reverse walk. Pinned rather than
#: tolerated, so the set cannot grow quietly and shrinking it (i.e. fixing one)
#: fails loudly enough to be noticed.
#:
#: Empty, and it should stay that way: every action the log can write can be
#: undone, and undoing the whole stream in reverse is the strongest statement
#: the History layer makes.
KNOWN_UNREVERTIBLE: list[str] = []

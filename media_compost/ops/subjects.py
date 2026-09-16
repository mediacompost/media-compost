"""Subjects — who or what a picture is OF — and their appearances.

A subject is **extra data on a tag** (see :class:`db.Subject`), so almost
nothing here is new machinery: putting a subject on an item is assigning its
identity tag, and search, counts, facets and training learn nothing new. What
this module owns is the identity itself — the display name, the since-date —
plus the one thing a tag cannot express: a subject with no name yet, which is
what a face cluster is. What it is IN A LINE, and at length, are the TAG's
(`tagcatalog.describe`): kept here as well, the two would drift, and every
list showing "the comment" would have to pick one.

An **appearance** (`ItemSubject`) is one row per "this person is in this
picture", optionally at one face. Several per item is the point: the same
character twice on a page, at two ages.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from .. import partialdate as pdate
from ..db import (
    Item, ItemSubject, ItemSubjectBox, ItemTag, Subject, Tag, chunked,
    touch_items,
)
from . import actions, naming, tagcatalog
from .context import Ctx
from .errors import Conflict, Invalid, NotFound, Refused

# ---- helpers ----------------------------------------------------------------


def label(subject: Subject) -> str:
    """What to call the subject in an event summary."""
    return subject.display_name or f"unnamed subject #{subject.id}"


def items_of_subject(ctx: Ctx, subject_id: int) -> set[int]:
    """Items this subject is known to be in OTHER than through its tag — its
    faces. Empty for a subject created by hand, which makes the back-fill below
    a no-op, exactly as it should be."""
    return set(ctx.session.execute(
        select(ItemSubject.item_id)
        .where(ItemSubject.subject_id == subject_id)
    ).scalars().all())


def _free_identity(s, wanted: str) -> str:
    """``wanted``, unless another SUBJECT already answers to it."""
    row = s.execute(select(Tag).where(Tag.name == wanted)).scalars().first()
    if row is None:
        return wanted
    taken = s.execute(
        select(Subject.id).where(Subject.tag_id == row.id)).first()
    return naming.free_slug(s, wanted) if taken else wanted


def mint_tag(ctx: Ctx, subject: Subject, name: str) -> tuple[Tag, list[int]]:
    """Give an unnamed subject its identity tag, and put that tag on every item
    the subject is already known to be in.

    The back-fill is what makes naming a face cluster worth doing: one action
    turns "this person, 34 times" into a tag on 34 items. The items it actually
    wrote come back with the tag, because undoing the naming must remove those
    assignments and only those.
    """
    s = ctx.session
    tag = s.execute(select(Tag).where(Tag.name == name)).scalars().first()
    if tag is None:
        tag = Tag(name=name)
        s.add(tag)
        s.flush()
    subject.tag_id = tag.id
    s.flush()
    # One chunked sweep for the items already carrying the tag, instead of a
    # SELECT per item — the back-fill can cover a whole library's worth.
    items = sorted(items_of_subject(ctx, subject.id))
    have: set[int] = set()
    for chunk in chunked(items):
        have.update(s.execute(select(ItemTag.item_id).where(
            ItemTag.item_id.in_(chunk), ItemTag.tag_id == tag.id
        )).scalars().all())
    added: list[int] = [iid for iid in items if iid not in have]
    s.add_all([ItemTag(item_id=iid, tag_id=tag.id, negative=False)
               for iid in added])
    if added:
        s.flush()
        touch_items(s, added)
    return tag, added


# ---- the identity -----------------------------------------------------------


def create(ctx: Ctx, display_name: str, *, comment: str = "",
           since_date: Optional[int] = None, tag: str = "") -> Subject:
    s = ctx.session
    name = display_name.strip()
    if since_date is not None and since_date and not pdate.is_valid(since_date):
        raise Invalid("invalid date", code="invalid_date")
    subject = Subject(display_name=name, since_date=since_date or None)
    s.add(subject)
    s.flush()
    # A subject with a name gets its tag now; one without stays unnamed until
    # somebody names it (that is what a face cluster is).
    wanted = tag.strip() or (naming.prefixed(s, "subject", name) if name else "")
    if wanted:
        # AN EXISTING TAG IS ADOPTED — the rule a place already follows, and
        # for the same reason: a subject IS extra data on a tag, so naming one
        # `alice` when the library already has an `alice` should make THAT tag
        # her identity rather than mint `alice_2` beside it and leave the two
        # meaning the same thing. `free_slug` still answers where the tag is
        # already somebody ELSE's identity, which is the case it exists for —
        # two people of one name.
        mint_tag(ctx, subject, _free_identity(s, wanted))
    # The comment goes on the TAG (`tagcatalog.describe`), so a subject
    # created with no name — a face cluster — is refused words it has nowhere
    # to put.
    tagcatalog.describe(ctx, subject.tag_id,
                        comment=comment.strip() if comment else None)
    ctx.log(action=actions.CREATE_SUBJECT, entity_type="subject",
            entity_id=subject.id, summary="Created subject {name}",
            summary_vars={"name": label(subject)},
            data={"subject_id": subject.id, "display_name": name,
                  "since_date": subject.since_date,
                  "tag_id": subject.tag_id})
    return subject


def update(ctx: Ctx, subject_id: int, *, display_name: Optional[str] = None,
           comment: Optional[str] = None,
           since_date: Optional[int] = None,
           tag: Optional[str] = None) -> Subject:
    s = ctx.session
    subject = s.get(Subject, subject_id)
    if subject is None:
        raise NotFound("subject not found", code="subject_not_found")

    if display_name is not None:
        old = subject.display_name
        new = display_name.strip()
        if new != old:
            subject.display_name = new
            ctx.log(action=actions.RENAME_SUBJECT, entity_type="subject",
                    entity_id=subject.id,
                    summary="Renamed subject {old} → {new}",
                    summary_vars={"old": old or "(unnamed)", "new": new},
                    data={"subject_id": subject.id, "old_name": old,
                          "name": new})
    # What it IS, in a line — on the tag. `describe` refuses a subject with
    # no tag, which is the one case there is nowhere to put it.
    tagcatalog.describe(ctx, subject.tag_id, comment=comment)
    if since_date is not None:
        old_d = subject.since_date
        new_d = since_date or None
        if new_d is not None and not pdate.is_valid(new_d):
            raise Invalid("invalid date", code="invalid_date")
        if new_d != old_d:
            subject.since_date = new_d
            ctx.log(action=actions.DATE_SUBJECT, entity_type="subject",
                    entity_id=subject.id,
                    summary=("{name} exists since {date}" if new_d
                             else "Cleared the date on {name}"),
                    summary_vars={"name": label(subject),
                                  "date": pdate.format_en(new_d) if new_d else ""},
                    data={"subject_id": subject.id, "since_date": new_d,
                          "old_since_date": old_d})
    if tag is not None:
        _set_identity_tag(ctx, subject, tag)
    s.flush()
    return subject


def _set_identity_tag(ctx: Ctx, subject: Subject, tag: str) -> None:
    """Mint, rename or leave alone the subject's identity tag."""
    s = ctx.session
    wanted = tag.strip()
    current = s.get(Tag, subject.tag_id) if subject.tag_id else None
    if wanted and current is None:
        # A tag that already exists is ADOPTED rather than refused: that is
        # how a face cluster is named after a tag the library already has, and
        # how a subject whose tag was deleted is pointed back at the tag that
        # came back. The one thing still refused is a tag somebody ELSE is,
        # since a tag has at most one identity.
        taken = s.execute(select(Tag).where(Tag.name == wanted)).scalars().first()
        if taken is not None and s.execute(select(Subject).where(
            Subject.tag_id == taken.id, Subject.id != subject.id
        )).scalars().first() is not None:
            raise Conflict("{tag} is already another subject's tag",
                           {"tag": wanted}, code="tag_taken_by_subject")
        minted, backfilled = mint_tag(ctx, subject, wanted)
        ctx.log(action=actions.NAME_SUBJECT, entity_type="subject",
                entity_id=subject.id,
                summary=(f"Named subject {label(subject)} ({minted.name})"
                         + (f", on {len(backfilled)} items" if backfilled else "")),
                data={"subject_id": subject.id, "tag_id": minted.id,
                      "name": minted.name, "backfilled": backfilled})
    elif wanted and current is not None and wanted != current.name:
        # Renaming the identity tag is an ordinary tag rename, so it logs the
        # tag's own revertible event.
        tagcatalog.update(ctx, current.id, name=wanted)


def delete_subject(ctx: Ctx, subject_id: int, *,
                   with_tag: bool = False):
    """Delete the identity, keeping its tag — the tag is an ordinary one and
    the pictures are still of something. ``with_tag`` deletes that too.
    Returns the delete event, so `tagcatalog`'s identity cascade can hand it
    to the caller's Undo."""
    s = ctx.session
    subject = s.get(Subject, subject_id)
    if subject is None:
        raise NotFound("subject not found", code="subject_not_found")
    tag_id = subject.tag_id
    ev = ctx.log(
        action=actions.DELETE_SUBJECT, entity_type="subject",
        entity_id=subject.id, summary="Deleted subject {name}",
        summary_vars={"name": label(subject)},
        # The tag by NAME as well as by id. A revert may run after the tag's
        # own deletion has been reverted, and THAT recreates the row — under a
        # fresh id, since a deleted rowid is gone. Re-linking by id then left
        # the identity pointing at nothing, which reads as a subject whose tag
        # vanished. Names are what a reference across a delete has to be.
        data={"subject_id": subject.id, "display_name": subject.display_name,
              "since_date": subject.since_date,
              "tag_id": tag_id,
              "tag_name": (s.get(Tag, tag_id).name if tag_id else "")},
    )
    s.delete(subject)
    s.flush()
    if with_tag and tag_id is not None:
        tagcatalog.delete_tag(ctx, tag_id)
    return ev


def merge(ctx: Ctx, subject_id: int, into_id: int, *,
          keep_alias: bool = True) -> list[int]:
    """Fold one subject into another: the faces move, and the identity tags
    merge through the ordinary tag merge (assignments, implications, group tags
    and aliases — already recorded per item, so the whole thing reverts).

    Returns the event ids, so a caller can offer an Undo straight after.
    """
    from ..db import FaceRejection

    s = ctx.session
    src = s.get(Subject, subject_id)
    dst = s.get(Subject, into_id)
    if src is None or dst is None:
        raise NotFound("subject not found", code="subject_not_found")
    if src.id == dst.id:
        raise Refused("cannot merge a subject into itself", code="merge_self")

    events: list[int] = []
    # Every appearance of the one becomes an appearance of the other. A face
    # that was BOTH would then say the same person twice, so the duplicate goes.
    theirs = {
        (r.item_id, r.face_id) for r in s.execute(
            select(ItemSubject).where(ItemSubject.subject_id == dst.id)
        ).scalars().all()
    }
    for row in s.execute(
        select(ItemSubject).where(ItemSubject.subject_id == src.id)
    ).scalars().all():
        if (row.item_id, row.face_id) in theirs:
            s.delete(row)
        else:
            row.subject_id = dst.id
    # Refusals move as well — but a face already refused for BOTH would then
    # hold the same fact twice, which the unique key forbids, so the duplicate
    # is dropped rather than remapped.
    already = {r.face_id for r in s.execute(
        select(FaceRejection).where(FaceRejection.subject_id == dst.id)
    ).scalars().all()}
    for row in s.execute(
        select(FaceRejection).where(FaceRejection.subject_id == src.id)
    ).scalars().all():
        if row.face_id in already:
            s.delete(row)
        else:
            row.subject_id = dst.id
    s.flush()

    if src.tag_id is not None:
        if dst.tag_id is None:
            # The target has no tag of its own: take the source's rather than
            # merging into nothing.
            dst.tag_id, src.tag_id = src.tag_id, None
        else:
            dst_tag = s.get(Tag, dst.tag_id)
            events += [e.id for e in tagcatalog.merge(
                ctx, src.tag_id, dst_tag.name, keep_alias=keep_alias)]
            src.tag_id = None
    ev = ctx.log(
        action=actions.DELETE_SUBJECT, entity_type="subject", entity_id=src.id,
        summary="Merged subject {source} → {target}",
        summary_vars={"source": label(src), "target": label(dst)},
        data={"subject_id": src.id, "display_name": src.display_name,
              "since_date": src.since_date,
              "tag_id": None, "merged_into": dst.id},
    )
    s.delete(src)
    s.flush()
    # The subject's own event LAST: reverting walks the list backwards, and the
    # subject has to exist again before its tag's assignments can come back.
    events.append(ev.id)
    return events


# ---- appearances ------------------------------------------------------------


def add_appearance(ctx: Ctx, item_id: int, *,
                   subject_id: Optional[int] = None, display_name: str = "",
                   face_id: Optional[int] = None) -> ItemSubject:
    """Somebody is in this picture — optionally at a particular face.

    A subject may appear several times in one item (the same character twice
    on a page, at two ages), so this ADDS a row rather than setting a flag.
    Assigning the tag is part of it: the tag is what search reads.
    """
    # Imported here, not at module scope: `ops.faces` imports THIS module for
    # `mint_tag`, so a top-level import either way is a cycle.
    from . import faces as ops_faces

    s = ctx.session
    item = s.get(Item, item_id)
    if item is None:
        raise NotFound("item not found", code="item_not_found")
    subject = s.get(Subject, subject_id) if subject_id else None
    created = False
    if subject is None:
        if not display_name.strip():
            raise Invalid("name the subject or choose an existing one",
                          code="subject_unnamed")
        subject = Subject(display_name=display_name.strip())
        s.add(subject)
        s.flush()
        mint_tag(ctx, subject,
                 naming.free_slug(s, naming.prefixed(s, "subject",
                                                     display_name)))
        created = True
    row = ops_faces.appear(ctx, item.id, subject, face_id)
    ctx.log(action=actions.ADD_APPEARANCE, entity_type="item",
            entity_id=item.id,
            summary="{name} is in this picture",
            summary_vars={"name": label(subject)},
            data={"item_id": item.id, "subject_id": subject.id,
                  "appearance_id": row.id, "face_id": face_id,
                  "created_subject": created})
    return row


def edit_appearance(ctx: Ctx, appearance_id: int, *,
                    when_date: Optional[int] = None,
                    when_age: Optional[int] = None,
                    set_when: bool = False,
                    face_id: Optional[int] = None,
                    confirm: bool = False) -> ItemSubject:
    """Date one appearance, move it onto (or off) a face, or agree with it."""
    from . import faces as ops_faces  # see the note in `add_appearance`

    s = ctx.session
    row = s.get(ItemSubject, appearance_id)
    if row is None:
        raise NotFound("no such appearance", code="appearance_not_found")
    if confirm and row.assigned_by == "suggested":
        # Agreeing with a guess. The score goes with the flag — it described
        # how sure the machine was, and nobody is guessing any more — and the
        # tag it put on the picture stops being pending, which is what lets
        # search, training and export see it at last.
        was, score = row.assigned_by, row.match_score
        row.assigned_by, row.match_score = "user", None
        s.flush()
        subject = s.get(Subject, row.subject_id)
        # A guess normally comes WITH its pending tag, so confirming only
        # clears the flag. `tag_added` is the other case — nothing had put the
        # tag there — and it is the difference between an undo that flags the
        # tag pending again and one that has to take it off entirely.
        tag_added = (ops_faces.assign_subject_tag(ctx, row.item_id, subject)
                     if subject is not None else False)
        touch_items(s, [row.item_id])
        ctx.log(action=actions.CONFIRM_APPEARANCE, entity_type="item",
                entity_id=row.item_id,
                summary="Agreed that {name} is here",
                summary_vars={"name": label(subject)},
                data={"item_id": row.item_id, "appearance_id": row.id,
                      "old_assigned_by": was, "old_match_score": score,
                      "tag_added": tag_added})
    old = {"date": row.when_date, "age": row.when_age, "face_id": row.face_id}
    if set_when:
        if when_date and not pdate.is_valid(when_date):
            raise Invalid("invalid date", code="invalid_date")
        row.when_date, row.when_age = when_date or None, when_age
    if face_id is not None:
        row.face_id = face_id or None
    s.flush()
    now = {"date": row.when_date, "age": row.when_age, "face_id": row.face_id}
    if now != old:
        touch_items(s, [row.item_id])
        ctx.log(action=actions.EDIT_APPEARANCE, entity_type="item",
                entity_id=row.item_id,
                summary="Changed where and when {name} is here",
                summary_vars={"name": label(s.get(Subject, row.subject_id))},
                data={"item_id": row.item_id, "appearance_id": row.id,
                      **now, "old_date": old["date"], "old_age": old["age"],
                      "old_face_id": old["face_id"]})
    return row


def reorder_appearances(ctx: Ctx, item_id: int, ids: list[int]) -> None:
    """The sidebar's drag-reorder: the given appearances take positions in
    the order given. One event for the lot, and the revert restores every
    old position; an order that moved nothing logs nothing."""
    s = ctx.session
    rows = {r.id: r for r in s.execute(select(ItemSubject).where(
        ItemSubject.item_id == item_id)).scalars().all()}
    wanted = [i for i in ids if i in rows]
    if not wanted:
        return
    def order_now() -> list[int]:
        return [r.id for r in sorted(rows.values(),
                                     key=lambda r: (r.position, r.id))]
    old_order = order_now()
    old_pos = {r.id: r.position for r in rows.values()}
    for idx, aid in enumerate(wanted):
        rows[aid].position = idx
    s.flush()
    if order_now() == old_order:
        return
    touch_items(s, [item_id])
    ctx.log(action=actions.REORDER_APPEARANCES, entity_type="item",
            entity_id=item_id,
            summary="Reordered who is in this picture",
            data={"item_id": item_id,
                  "old_positions": {str(k): v for k, v in old_pos.items()},
                  "ids": wanted})


def set_appearance_box(ctx: Ctx, appearance_id: int, *,
                       x: Optional[float] = None, y: Optional[float] = None,
                       w: Optional[float] = None, h: Optional[float] = None,
                       clear: bool = False, points=None) -> ItemSubject:
    """Draw, replace or clear one appearance's SUBJECT BOX.

    The outline saying where in the picture the subject is — the whole
    figure, where the face box says the head. At most one per appearance
    (drawing again replaces it), fractions of the item's reference frame like
    every box here. ``points`` refines it to a POLYGON: the four columns then
    hold its bounding box (`ItemTagBox.points`' rule), derived here so the
    two cannot drift. Logged with the old shape, so the revert can put back
    what it replaced — or the absence it replaced.
    """
    import json as _json

    from .tagassign import poly_bbox

    s = ctx.session
    row = s.get(ItemSubject, appearance_id)
    if row is None:
        raise NotFound("no such appearance", code="appearance_not_found")
    pts_json = _json.dumps([[float(p[0]), float(p[1])] for p in points]) \
        if points else None
    bb = poly_bbox(pts_json)
    if bb is not None:
        x, y, w, h = bb
    else:
        pts_json = None
    if not clear and None in (x, y, w, h):
        raise Invalid("a box needs all four sides", code="box_incomplete")
    box = s.execute(select(ItemSubjectBox).where(
        ItemSubjectBox.item_subject_id == row.id)).scalars().first()
    old = ({"x": box.x, "y": box.y, "w": box.w, "h": box.h,
            **({"points": box.points} if box.points else {})}
           if box is not None else None)
    if clear:
        if box is None:
            return row  # clearing nothing is nothing to log
        s.delete(box)
    elif box is not None:
        box.x, box.y, box.w, box.h = float(x), float(y), float(w), float(h)
        box.points = pts_json
    else:
        s.add(ItemSubjectBox(item_subject_id=row.id, x=float(x), y=float(y),
                             w=float(w), h=float(h), points=pts_json))
    s.flush()
    subject = s.get(Subject, row.subject_id)
    touch_items(s, [row.item_id])
    ctx.log(action=actions.SET_APPEARANCE_BOX, entity_type="item",
            entity_id=row.item_id,
            summary=("Cleared the box around {name}" if clear
                     else "Drew a box around {name}"),
            summary_vars={"name": label(subject)},
            data={"item_id": row.item_id, "appearance_id": row.id,
                  "old": old,
                  "new": (None if clear
                          else {"x": float(x), "y": float(y),
                                "w": float(w), "h": float(h),
                                **({"points": pts_json} if pts_json
                                   else {})})})
    return row


def remove_appearance(ctx: Ctx, appearance_id: int) -> int:
    """Take one appearance off; returns the item it was on.

    The subject's TAG goes with the last of them: "not in this picture" is
    what removing the only appearance means, and leaving the tag behind would
    keep the person in every search that found them here.
    """
    s = ctx.session
    row = s.get(ItemSubject, appearance_id)
    if row is None:
        raise NotFound("no such appearance", code="appearance_not_found")
    item_id, subject_id = row.item_id, row.subject_id
    # `appearance_id` so the restore can put the row back under its own id —
    # the `add_appearance` / `edit_appearance` reverts behind this one look it
    # up by exactly that (see `history._restore_appearance`).
    was = {"date": row.when_date, "age": row.when_age, "face_id": row.face_id,
           "assigned_by": row.assigned_by, "match_score": row.match_score,
           "appearance_id": row.id}
    s.delete(row)
    s.flush()
    subject = s.get(Subject, subject_id)
    left = s.execute(select(ItemSubject).where(
        ItemSubject.item_id == item_id,
        ItemSubject.subject_id == subject_id)).scalars().first()
    removed_tag = False
    if left is None and subject is not None and subject.tag_id is not None:
        tag_row = s.execute(select(ItemTag).where(
            ItemTag.item_id == item_id,
            ItemTag.tag_id == subject.tag_id)).scalars().first()
        if tag_row is not None:
            s.delete(tag_row)
            removed_tag = True
    s.flush()
    touch_items(s, [item_id])
    ctx.log(action=actions.REMOVE_APPEARANCE, entity_type="item",
            entity_id=item_id,
            summary=(f"{label(subject) if subject else 'Somebody'} "
                     "is not in this picture"),
            data={"item_id": item_id, "subject_id": subject_id,
                  "tag_removed": removed_tag, **was})
    return item_id

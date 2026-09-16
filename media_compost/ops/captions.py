"""Captions on an item, and the meta tags a caption carries.

A caption's tags live in the SAME namespace as a link's and a per-item tag
group's (``LinkTag`` names, used by :class:`RelationshipTag` and
:class:`CaptionTag` alike) — the app calls them "meta tags": labels about the
annotation, not about the image. They never reach the item's tags, search or
training prompts, and that separation is the whole point of them.

A caption has a KIND. "caption" describes the picture; "instruction" says how
it was made from other pictures, and carries those pictures as an ordered list
(:class:`CaptionRef`) — the training data an edit/instruction model needs. It
is one row type because everything a caption already has is what an
instruction needs too: meta tags, provenance, history, revert, sidecars, the
Python API and the training caption filter. What is NOT shared is which of
them a run trains on: the two are two lists in the app and two mutually
exclusive training sources, or an instruction read as a description trains the
model on a lie.
"""

from __future__ import annotations

from sqlalchemy import delete, func, select

from ..db import (LIB_META, Caption, CaptionRef, CaptionTag, Item, LinkTag,
                  touch_items)
from . import actions
from .context import Ctx
from .errors import Invalid, NotFound, Refused

#: The two kinds a caption row may be. "caption" is what an unset column reads
#: as, so it is the default everywhere.
KINDS = ("caption", "instruction")


def snippet(text: str, limit: int = 80) -> str:
    """A single-line, length-capped quote of a caption for history summaries."""
    t = " ".join((text or "").split())
    return t if len(t) <= limit else t[: limit - 1] + "…"


def caption_tags(session, caption_id: int) -> list[str]:
    return list(session.execute(
        select(CaptionTag.name)
        .where(CaptionTag.caption_id == caption_id)
        .order_by(CaptionTag.name)
    ).scalars().all())


def caption_refs(session, caption_id: int) -> list[int]:
    """An instruction's reference items, IN ORDER (item ids).

    Ordered by position then id, like every other ordered membership here, so
    two rows that share a position still come out the same way twice.
    """
    return list(session.execute(
        select(CaptionRef.item_id)
        .where(CaptionRef.caption_id == caption_id)
        .order_by(CaptionRef.position, CaptionRef.id)
    ).scalars().all())


def _caption_or_404(ctx: Ctx, item_id: int, caption_id: int) -> Caption:
    c = ctx.session.get(Caption, caption_id)
    if c is None or c.item_id != item_id:
        raise NotFound("caption not found", code="caption_not_found")
    return c


# ---- the caption itself -----------------------------------------------------


def add(ctx: Ctx, item_id: int, text: str, *,
        kind: str = "caption") -> Caption:
    s = ctx.session
    if kind not in KINDS:
        raise Invalid("unknown caption kind {kind}", {"kind": repr(kind)},
                      code="bad_caption_kind")
    if not s.get(Item, item_id):
        raise NotFound("item not found", code="item_not_found")
    # Position runs over the item's captions of BOTH kinds. The two lists are
    # read separately and each renders in position order regardless, so one
    # counter is one fewer thing to keep in step.
    pos = s.execute(
        select(func.coalesce(func.max(Caption.position), -1)).where(
            Caption.item_id == item_id
        )
    ).scalar_one() + 1
    c = Caption(item_id=item_id, text=text, position=pos, kind=kind)
    s.add(c)
    s.flush()
    touch_items(s, [item_id])
    what = "instruction" if kind == "instruction" else "caption"
    # `kind` rides along only when it says something. A plain caption's event
    # is then byte-identical to the one this build has always written, which is
    # what keeps `golden/history_events.json` a record of insertions rather
    # than of every key that has ever been added beside them; the readers all
    # take a missing kind as "caption".
    data = {"item_id": item_id, "caption_id": c.id, "text": text}
    if kind != "caption":
        data["kind"] = kind
    ctx.log(action=actions.ADD_CAPTION, entity_type="item", entity_id=item_id,
            summary=("Added instruction “{text}”" if what == "instruction"
                     else "Added caption “{text}”"),
            summary_vars={"text": snippet(text)}, data=data)
    return c


def edit(ctx: Ctx, item_id: int, caption_id: int, text: str) -> Caption:
    s = ctx.session
    c = s.get(Caption, caption_id)
    if not c or c.item_id != item_id:
        raise NotFound("caption not found", code="caption_not_found")
    old_text = c.text
    was_pending = bool(c.pending)
    was_edited = bool(c.edited)
    c.text = text
    # Saving an edit to a machine-generated caption counts as approving it; keep
    # its model provenance but mark it edited so the UI can note that.
    if c.pending or c.model:
        c.edited = True
    c.pending = False
    touch_items(s, [item_id])
    ctx.log(action=actions.EDIT_CAPTION, entity_type="item",
            entity_id=item_id, summary="Edited caption to “{text}”",
            summary_vars={"text": snippet(text)},
            data={"item_id": item_id, "caption_id": caption_id,
                  "text": text, "old_text": old_text,
                  "was_pending": was_pending, "was_edited": was_edited})
    return c


def remove(ctx: Ctx, item_id: int, caption_id: int) -> bool:
    s = ctx.session
    c = s.get(Caption, caption_id)
    if c is None or c.item_id != item_id:
        return False
    # The event records the caption's whole SHAPE, not just its text: a revert
    # must restore the meta tags, provenance, flags, position, kind and — for
    # an instruction — its ordered references too, or undo hands back a bare
    # hand-written caption at the end of the list, or a sentence pointing at
    # nothing.
    kind = c.kind or "caption"
    data = {"item_id": item_id, "text": c.text, "position": c.position,
            "pending": bool(c.pending), "model": c.model or "",
            "edited": bool(c.edited), "tags": caption_tags(s, caption_id)}
    # Both only when they say something — see `add` on why a plain caption's
    # event stays exactly what it has always been.
    if kind != "caption":
        data["kind"] = kind
        refs = caption_refs(s, caption_id)
        if refs:
            data["refs"] = refs
    s.execute(delete(Caption).where(
        Caption.id == caption_id, Caption.item_id == item_id
    ))
    touch_items(s, [item_id])
    what = "instruction" if kind == "instruction" else "caption"
    ctx.log(action=actions.REMOVE_CAPTION, entity_type="item",
            entity_id=item_id,
            summary=("Removed instruction “{text}”" if what == "instruction"
                     else "Removed caption “{text}”"),
            summary_vars={"text": snippet(data["text"])},
            data=data)
    return True


def approve(ctx: Ctx, caption_id: int) -> bool:
    """Accept a machine-written caption as it stands.

    Editing one approves it too (see `edit`); this is the button for the case
    where it needed no changing. Only a caption that WAS pending logs an
    event — approving an approved one is a no-op worth no History row — but
    the item is touched either way, which is what the endpoint has always done.
    """
    s = ctx.session
    c = s.get(Caption, caption_id)
    if c is None:
        raise NotFound("caption not found", code="caption_not_found")
    was_pending = bool(c.pending)
    c.pending = False
    touch_items(s, [c.item_id])
    if was_pending:
        ctx.log(action=actions.APPROVE_CAPTION, entity_type="item",
                entity_id=c.item_id,
                summary="Approved AI caption “{text}”",
                summary_vars={"text": snippet(c.text)},
                data={"item_id": c.item_id, "caption_id": c.id})
    return was_pending


# ---- the reference images of an instruction ---------------------------------


def _refs_summary(
        old: list[int], new: list[int]) -> tuple[str, dict[str, object] | None]:
    """What this edit to an instruction's reference list actually did.

    `set_refs` is one op for adding, removing and reordering — which is right,
    since they are one edit to one ordered list — but it left the history
    saying only how many references there are afterwards. Reordering three
    pictures read "Gave an instruction 3 reference images", i.e. a sentence
    about the state that describes the wrong action entirely: nothing was
    given, and the entry was indistinguishable from the one that first
    attached them.

    The comparison is against the OLD list, which the op already has in hand,
    so this costs nothing and says the one thing the reader wants.

    Returns ``(template, vars)`` — a summary built in a HELPER is invisible
    to the ``summary=`` keyword harvest, so `tests/test_i18n_templates.py`
    reads the return statements of ``*_summary`` functions instead; each
    branch returns its template as a literal for exactly that reason.
    """
    if not new:
        return "Cleared an instruction's reference images", None
    added = [i for i in new if i not in set(old)]
    removed = [i for i in old if i not in set(new)]
    if not old:
        if len(new) == 1:
            return "Gave an instruction 1 reference image", None
        return "Gave an instruction {n} reference images", {"n": len(new)}
    if not added and not removed:
        # Same pictures, different order — the case that read worst.
        if len(new) == 1:
            return "Reordered an instruction's 1 reference image", None
        return ("Reordered an instruction's {n} reference images",
                {"n": len(new)})
    if added and not removed:
        if len(added) == 1:
            return "Added 1 reference image to an instruction", None
        return ("Added {n} reference images to an instruction",
                {"n": len(added)})
    if removed and not added:
        if len(removed) == 1:
            return "Removed 1 reference image from an instruction", None
        return ("Removed {n} reference images from an instruction",
                {"n": len(removed)})
    # Both at once: say the result, since neither half is the story.
    if len(new) == 1:
        return "Changed an instruction's reference images to 1 picture", None
    return ("Changed an instruction's reference images to {n} pictures",
            {"n": len(new)})


def set_refs(ctx: Ctx, item_id: int, caption_id: int,
             item_ids: list[int]) -> list[int]:
    """Set an instruction's reference images to exactly this list, in order.

    ONE op for adding, removing and reordering, taking the FULL desired order
    the way :func:`ops.sequences.reorder_members` does. Three ops would be
    three history event shapes and three reverts for what is one edit to one
    ordered list; one op means the undo is simply "put the old order back".

    Ids that name no item are dropped silently (the caller is a drop target
    working from a grid that may have moved on), duplicates collapse to their
    first appearance, and a reference to the instruction's OWN item is refused
    — a picture is not one of its own sources.
    """
    s = ctx.session
    c = _caption_or_404(ctx, item_id, caption_id)
    if (c.kind or "caption") != "instruction":
        raise Refused("only an instruction carries reference images",
                      code="not_an_instruction")
    seen: set[int] = set()
    wanted: list[int] = []
    for iid in item_ids:
        iid = int(iid)
        if iid in seen:
            continue
        if iid == item_id:
            raise Refused("an instruction cannot reference its own item",
                          code="instruction_self_ref")
        if s.get(Item, iid) is None:
            continue
        seen.add(iid)
        wanted.append(iid)
    old = caption_refs(s, caption_id)
    if wanted == old:
        return old
    s.execute(delete(CaptionRef).where(CaptionRef.caption_id == caption_id))
    # Flushed before the new rows go in, or the unique (caption_id, item_id)
    # fires on a reorder that keeps every id.
    s.flush()
    for pos, iid in enumerate(wanted):
        s.add(CaptionRef(caption_id=caption_id, item_id=iid, position=pos))
    s.flush()
    touch_items(s, [item_id])
    summary, summary_vars = _refs_summary(old, wanted)
    ctx.log(action=actions.SET_CAPTION_REFS, entity_type="item",
            entity_id=item_id, summary=summary, summary_vars=summary_vars,
            data={"item_id": item_id, "caption_id": caption_id,
                  "refs": wanted, "old_refs": old})
    return wanted


# ---- meta tags on a caption -------------------------------------------------


def add_meta_tag(ctx: Ctx, item_id: int, caption_id: int,
                 name: str) -> list[str]:
    """Add a meta tag to a caption (idempotent). Returns the caption's tags."""
    s = ctx.session
    _caption_or_404(ctx, item_id, caption_id)
    name = " ".join((name or "").split())[:64]
    if not name:
        raise Invalid("empty tag", code="empty_meta_tag")
    exists = s.execute(
        select(CaptionTag).where(CaptionTag.caption_id == caption_id,
                                 CaptionTag.name == name)
    ).scalar_one_or_none()
    if exists is None:
        s.add(CaptionTag(caption_id=caption_id, name=name))
    # Persist the NAME too, exactly as the link side does: a meta tag survives
    # its last use, so the autocomplete list doesn't lose it.
    if s.execute(select(LinkTag).where(LinkTag.name == name, LIB_META)
                 ).scalar_one_or_none() is None:
        s.add(LinkTag(name=name))
    touch_items(s, [item_id])
    ctx.log(action=actions.ADD_CAPTION_TAG, entity_type="item",
            entity_id=item_id,
            summary="Added meta tag “{name}” to a caption",
            summary_vars={"name": name},
            data={"item_id": item_id, "caption_id": caption_id, "name": name})
    s.flush()
    return caption_tags(s, caption_id)


def remove_meta_tag(ctx: Ctx, item_id: int, caption_id: int,
                    name: str) -> list[str]:
    """Remove a meta tag from a caption. The name itself stays in the
    catalog (it may still carry a comment, or be used elsewhere)."""
    s = ctx.session
    _caption_or_404(ctx, item_id, caption_id)
    row = s.execute(
        select(CaptionTag).where(CaptionTag.caption_id == caption_id,
                                 CaptionTag.name == name)
    ).scalar_one_or_none()
    if row is not None:
        s.delete(row)
        touch_items(s, [item_id])
        ctx.log(action=actions.REMOVE_CAPTION_TAG, entity_type="item",
                entity_id=item_id,
                summary="Removed meta tag “{name}” from a caption",
                summary_vars={"name": name},
                data={"item_id": item_id, "caption_id": caption_id,
                      "name": name})
        s.flush()
    return caption_tags(s, caption_id)

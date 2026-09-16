"""Generated artifacts stored beside a source file.

Depth maps, pose overlays, Canny edges, line art — and cached training latents,
which are the same table but a different kind of thing: a latent is a CACHE of
pixels, so deleting one costs the next run one re-encode and nothing else.

**That difference is what splits creation into two tiers.** `create_one` is the
state change and says nothing; `create` is the operation a model's output is,
and writes the one event the History shows. A cache uses the first — see its
docstring for why silence is the right default there rather than an oversight —
and `cache_name` is what lets it find its own bytes again afterwards.

Deleting one out from under a RUNNING trainer is the exception, because it
reads those files every step. Whether a trainer is running is something only
the server knows, so it is a parameter rather than a lookup — the ops layer has
no business reaching for a `TrainingManager`, and a script that is not the
server has no trainer to protect.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from .. import fileops
from ..db import File, FileArtifact, Item, touch_items
from ..storage import _norm_ext, _slug
from . import actions
from .context import Ctx
from .errors import Conflict, NotFound


def cache_name(file_number: int, kind: str, key: str = "",
               ext: str = "bin") -> str:
    """The item-folder-relative name an artifact of one file WOULD have.

    ``artifacts/<file-number>-<kind>[-<key>].<ext>``, and DETERMINISTIC:
    `ItemStore.write_artifact` appends ``-2``/``-3`` when a name is taken,
    which is right for several depth maps of one file and wrong twice over for
    a CACHE — regenerating would pile up copies instead of replacing, and
    nothing could find the file again by its key. So a cache addresses itself,
    and the same three arguments always name the same bytes.

    The ``key`` is whatever makes one cached rendering different from another
    (a model, a bucket size, a degradation's drawn values); it is slugged like
    the kind, so a caller may compose one out of pieces without worrying about
    which characters survive.
    """
    stem = f"{file_number}-{_slug(kind)}"
    if key:
        stem += f"-{_slug(key)}"
    return f"artifacts/{stem}.{_norm_ext(ext)}"


def find(ctx: Ctx, file_id: int, *, kind: str = "", model: str = "",
         path: str = "") -> Optional[FileArtifact]:
    """The recorded artifact of a file matching every field given, or None."""
    stmt = select(FileArtifact).where(FileArtifact.file_id == file_id)
    if kind:
        stmt = stmt.where(FileArtifact.kind == kind)
    if model:
        stmt = stmt.where(FileArtifact.model == model)
    if path:
        stmt = stmt.where(FileArtifact.path == path)
    return ctx.session.execute(stmt.order_by(FileArtifact.id)).scalars().first()


def create_one(ctx: Ctx, *, file_id: int, kind: str, path: str,
               sha256: str = "", width: int = 0, height: int = 0,
               bytes: int = 0, format: str = "", model: str = "",
               parent_id: Optional[int] = None,
               stale: bool = False) -> FileArtifact:
    """Record bytes already stored at ``path`` as an artifact of ``file_id``.

    The state change, logging NOTHING — `create` below is the logged
    operation. A CACHE goes through this tier deliberately, and the reasons
    are worth writing down because "log everything" is the usual default:
    `add_artifact` is already in `actions.NOT_REVERTIBLE`, so the event could
    never be acted on; the events log is append-only and unbounded, and a
    materialization over a large library writes two latents per picture plus
    one per degraded copy, i.e. six figures of history saying a cache warmed;
    and the DELETION side is already silent, so logging the creation is the
    asymmetry rather than the other way round.
    """
    f = ctx.session.get(File, file_id)
    if f is None:
        raise NotFound("file not found", code="file_not_found")
    art = FileArtifact(
        file_id=file_id, item_id=f.item_id, kind=kind, model=model or "",
        sha256=sha256 or "", path=path, width=width or 0, height=height or 0,
        bytes=bytes or 0, format=format or "", parent_id=parent_id,
        stale=bool(stale),
    )
    ctx.session.add(art)
    # Flushed because callers read the id back — the logged tier below puts it
    # in the event, and a nested artifact needs it as its `parent_id`.
    ctx.session.flush()
    touch_items(ctx.session, [f.item_id])
    return art


def create(ctx: Ctx, *, summary: str,
           summary_vars: Optional[dict] = None, **fields) -> FileArtifact:
    """`create_one` plus the one event that says a model produced something."""
    art = create_one(ctx, **fields)
    ctx.log(action=actions.ADD_ARTIFACT, entity_type="item", entity_id=art.item_id,
            summary=summary, summary_vars=summary_vars,
            data={"item_id": art.item_id, "artifact_id": art.id,
                  "kind": art.kind})
    return art


def _refuse_cache_while_training(kind: str) -> None:
    """The one refusal a cache deletion carries — see `delete_artifact`."""
    # TWO whole templates, not a slotted English phrase — a slot holding
    # untranslatable text is the fragment-concatenation disease one layer
    # down. Both expand to exactly the bytes the f-string produced.
    raise Conflict(
        ("a training job is running — cached latents can be deleted "
         "once it has finished or been paused") if kind == "latent" else
        ("a training job is running — cached degraded copies can be "
         "deleted once it has finished or been paused"),
        code="training_running")


def delete_kind(ctx: Ctx, kind: str, model: Optional[str] = None, *,
                training_running: bool = False,
                limit: int = 500) -> tuple[int, int, bool]:
    """Delete every artifact of one ``kind`` (and ``model``), in one batch.

    Answers ``(deleted, freed_bytes, more)``. BATCHED rather than exhaustive
    because the caller is what owns the transaction: a library with a warmed
    latent cache holds tens of thousands of these rows, and one transaction
    around all of them is a long-held write lock and a rollback nobody wanted
    — the same reasoning `quick_assign_view` chunks for. `more` is how the
    caller knows to come round again.

    ``model=None`` means every model of that kind; ``model=""`` means the
    rows that name none, which is a real answer (a Canny edge map has no
    model worth the name) and not the same question.
    """
    s = ctx.session
    stmt = select(FileArtifact).where(FileArtifact.kind == kind)
    if model is not None:
        stmt = stmt.where(FileArtifact.model == model)
    rows = list(s.execute(stmt.order_by(FileArtifact.id)
                          .limit(limit + 1)).scalars().all())
    more = len(rows) > limit
    rows = rows[:limit]
    if not rows:
        return 0, 0, False
    if kind in fileops.DERIVED_CACHE_KINDS and training_running:
        _refuse_cache_while_training(kind)
    freed = 0
    # The item folder is where the bytes are, so the uid is needed per row —
    # loaded in ONE query rather than a `session.get` per artifact, which is
    # the difference between a batch and a thousand point lookups.
    uids = dict(s.execute(
        select(Item.id, Item.uid)
        .where(Item.id.in_({a.item_id for a in rows}))).all())
    for a in rows:
        uid = uids.get(a.item_id)
        if a.path and uid:
            ctx.store.remove_file(uid, a.path)
        freed += int(a.bytes or 0)
        s.delete(a)
    # The sidecar lists an item's artifacts, so every item that lost one is
    # derived-stale until it is rewritten.
    touch_items(s, {a.item_id for a in rows})
    return len(rows), freed, more


def delete_artifact(ctx: Ctx, artifact_id: int, *,
                    training_running: bool = False) -> bool:
    s = ctx.session
    a = s.get(FileArtifact, artifact_id)
    if a is None:
        raise NotFound("artifact not found", code="artifact_not_found")
    # A latent is a cache: deleting it costs the next run one re-encode, and
    # `LatentSource.prepare` rebuilds whatever is missing. A degraded copy is
    # the same kind of thing one step earlier — the next materialization
    # re-encodes it. Deleting either out from under a RUNNING trainer is a
    # different matter (it reads these files every step), so that is refused
    # while a job is under way.
    if a.kind in fileops.DERIVED_CACHE_KINDS and training_running:
        _refuse_cache_while_training(a.kind)
    if a.path:
        item = s.get(Item, a.item_id)
        if item is not None:
            ctx.store.remove_file(item.uid, a.path)
    s.delete(a)
    return True

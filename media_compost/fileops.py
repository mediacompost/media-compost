"""Shared file-level operations that both the importer and the API use.

Currently :func:`make_oriented_file` (bakes a whole-image orientation into a new
source file), the rotate helpers, and :func:`record_edit` (edit-lineage
bookkeeping). File numbers are assigned eagerly at creation via
:func:`media_compost.db.next_file_number` — they name the on-disk file.
"""

from __future__ import annotations

import io
from typing import Optional

from PIL import Image
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.orm import Session

from . import media, orient
from .db import File, FileArtifact, Item, chunked, next_file_number
from .colorkey import color_signature
from .dedup import compute_phash_image
from .itemmeta import index_file_metadata
from .storage import ItemStore, sha256_bytes


def _item_uid(session: Session, item_id: int) -> str:
    return session.get(Item, item_id).uid


def make_oriented_file(
    session: Session,
    store: ItemStore,
    src: File,
    rotation: int,
    mirrored: bool,
    *,
    replace: Optional[File] = None,
) -> File:
    """Create (or overwrite ``replace``) a stored File holding ``src``'s pixels
    re-oriented by ``(rotation, mirrored)`` relative to the item's first file.

    The pixels are always derived from ``src`` (the base image), so repeated
    rotations never compound recompression. Saved LOSSLESSLY — WebP where it
    holds the picture exactly, PNG where it does not (`media.encode_lossless`;
    a 16-bit or CMYK source is precisely the case that must not be handed to
    WebP, which converts it silently). When
    ``replace`` is given, that existing derived file is repointed in place (so a
    re-rotate updates one file instead of accumulating new ones); otherwise a new
    derived File is added. Returns the resulting File.
    """
    uid = _item_uid(session, src.item_id)
    with Image.open(store.file_path(uid, src.path)) as im:
        out = orient.apply_orientation(im, rotation, mirrored)
        # Materialize before the source handle closes.
        out.load()
    ext, data = media.encode_lossless(out)
    digest = sha256_bytes(data)
    phash = compute_phash_image(out.convert("RGB"))
    ckey, csig = color_signature(out)
    rotation = int(rotation or 0) % 360
    mirrored = bool(mirrored)
    if replace is not None:
        old_rel = replace.path
        rel = store.write_file(uid, replace.number, ext, data=data)
        if old_rel and old_rel != rel:
            store.remove_file(uid, old_rel)
        replace.sha256 = digest
        replace.phash = phash
        replace.color_key, replace.color_sig = ckey, csig
        replace.path = rel
        replace.width, replace.height = out.width, out.height
        replace.bytes = len(data)
        replace.format = ext
        replace.rotation = rotation
        replace.mirrored = mirrored
        replace.derived_from_file_id = src.id
        replace.is_derived = True
        session.flush()
        # An IN-PLACE rewrite: this file's bytes are different bytes now, so
        # what it says about itself has to be re-read. Nothing lands in
        # `session.new` here, which is exactly why per-file metadata is written
        # at the call sites rather than by a flush listener.
        index_file_metadata(session, store, replace)
        store.drop_thumb(replace.id)
        drop_derived_caches(session, store, replace.id)
        return replace
    number = next_file_number(session, src.item_id)
    rel = store.write_file(uid, number, ext, data=data)
    f = File(
        item_id=src.item_id, sha256=digest, phash=phash,
        color_key=ckey, color_sig=csig, path=rel,
        number=number,
        width=out.width, height=out.height, bytes=len(data), format=ext,
        is_derived=True, derived_from_file_id=src.id,
        rotation=rotation, mirrored=mirrored,
    )
    session.add(f)
    session.flush()
    index_file_metadata(session, store, f)
    store.drop_thumb(f.id)
    return f


#: Artifact kinds that are a pure function of the source file's PIXELS, and so
#: are thrown away rather than kept when those pixels change. Both are caches
#: the next training run rebuilds; neither is anything the user made.
DERIVED_CACHE_KINDS = ("latent", "degraded")


def drop_derived_caches(session: Session, store: ItemStore, file_id: int) -> int:
    """Forget a file's cached latents and degraded copies. Returns how many.

    A latent is the VAE's encoding of this file's PIXELS, and a degraded copy is
    those pixels put through a codec — so the moment they change (a rotation, an
    edit written back over the same file) both describe an image that no longer
    exists, and a training run reading them would train on the old one. They are
    only caches: the next run rebuilds what is missing.

    This is also why neither can be treated like the other artifacts. A depth map
    or a pose overlay is an image and gets ROTATED to match. A latent is a tensor,
    and asking Pillow to open one raises. A degraded copy is PIL-openable, which
    is the dangerous one: left to the generic rotate path it would be re-saved as
    a PNG, silently re-encoding away the very artifacts it exists to hold, under
    a name that still claims a JPEG quality it no longer has.
    """
    rows = session.execute(select(FileArtifact).where(
        FileArtifact.file_id == file_id,
        FileArtifact.kind.in_(DERIVED_CACHE_KINDS),
    )).scalars().all()
    for art in rows:
        if art.path:
            store.remove_file(_item_uid(session, art.item_id), art.path)
    if rows:
        # One bulk DELETE rather than a `session.delete` per row: a degraded
        # copy's latents point at it with an ON DELETE CASCADE, so the database
        # removes them the moment their parent goes — and the ORM then warns
        # that its own per-row deletes matched fewer rows than it expected. The
        # statement form makes the cascade the only rule, and there is nothing
        # in the session left holding the dead rows.
        for chunk in chunked([a.id for a in rows]):
            session.execute(
                sa_delete(FileArtifact).where(FileArtifact.id.in_(chunk)))
        session.expire_all()
    return len(rows)


def rotate_file_artifacts(
    session: Session,
    store: ItemStore,
    from_file_id: int,
    to_file_id: int,
    rotation: int,
) -> None:
    """Rotate every artifact hanging off ``from_file_id`` by ``rotation``
    (clockwise degrees) and move it onto ``to_file_id`` (pass the same id to
    rotate in place).

    Used by the rotate action: a control-image artifact (depth/pose/canny/line
    art) is generated in the source's orientation, so when the image is rotated
    the artifact is rotated to match — keeping it aligned rather than stale.
    Multiples of 90° are a lossless pixel transform, so this never degrades the
    artifact even across repeated rotations.
    """
    rotation = int(rotation or 0) % 360
    drop_derived_caches(session, store, from_file_id)
    # The cache kinds are excluded HERE as well, not just dropped above. The
    # drop leaves nothing for this query to find, but that is an ordering the
    # next edit could quietly undo — and what it would let through is a
    # degraded JPEG re-saved as a PNG under a name still claiming its quality.
    arts = session.execute(
        select(FileArtifact).where(
            FileArtifact.file_id == from_file_id,
            FileArtifact.kind.notin_(DERIVED_CACHE_KINDS),
        )
    ).scalars().all()
    to_file = session.get(File, to_file_id)
    for art in arts:
        uid = _item_uid(session, art.item_id)
        if rotation and art.path:
            with Image.open(store.file_path(uid, art.path)) as im:
                out = orient.apply_orientation(im, rotation, False)
                out.load()
            # IN PLACE, so the bytes have to keep the format the path already
            # names — writing WebP under a `.png` name is a file that lies
            # about itself, and the artifact keeps its path here.
            data = media.encode_matching(out, art.format)
            store.write_bytes_at(uid, art.path, data)
            art.sha256 = sha256_bytes(data)
            art.width, art.height = out.width, out.height
            art.bytes = len(data)
        if to_file_id != from_file_id:
            # Moving between files renames the artifact on disk (its filename
            # embeds the owning file's number).
            old_rel = art.path
            if old_rel and to_file is not None:
                data = store.file_path(uid, old_rel).read_bytes()
                art.path = store.write_artifact(
                    uid, to_file.number, art.kind, art.format or "png",
                    data, art.model
                )
                store.remove_file(uid, old_rel)
            art.file_id = to_file_id
    if arts:
        session.flush()


def record_edit(
    session: Session,
    item_id: int,
    parent_file: File,
    new_file: File,
    action: str,
) -> None:
    """Record ``new_file`` as an edit of ``parent_file`` (same item) via
    ``action``: point it at the parent and extend the parent's edit chain by one
    step. File numbers are assigned at creation, so the chain always records
    real numbers."""
    import json as _json

    steps = _json.loads(parent_file.edit_chain) if parent_file.edit_chain else []
    steps.append({"from": parent_file.number, "to": new_file.number, "action": action})
    new_file.edit_chain = _json.dumps(steps)
    new_file.derived_from_file_id = parent_file.id
    session.flush()


def rotate_active_file(
    session: Session,
    store: ItemStore,
    active: File,
    delta: int,
    *,
    in_place: bool,
) -> File:
    """Rotate ``active``'s pixels by ``delta`` clockwise degrees.

    ``in_place`` overwrites ``active`` (used when it's an edited/derived file);
    otherwise a new derived File is created from it (used when ``active`` is a
    pristine imported original, so the original is preserved). Rotation is a
    lossless 90°-multiple transform, so rotating the active bytes never
    compounds recompression. Returns the resulting File.
    """
    uid = _item_uid(session, active.item_id)
    with Image.open(store.file_path(uid, active.path)) as im:
        out = orient.apply_orientation(im, int(delta) % 360, False)
        out.load()
    ext, data = media.encode_lossless(out)
    digest = sha256_bytes(data)
    phash = compute_phash_image(out.convert("RGB"))
    ckey, csig = color_signature(out)
    new_rotation = (int(active.rotation or 0) + int(delta)) % 360
    if in_place:
        old_rel = active.path
        rel = store.write_file(uid, active.number, ext, data=data)
        if old_rel and old_rel != rel:
            store.remove_file(uid, old_rel)
        active.sha256 = digest
        active.phash = phash
        active.color_key, active.color_sig = ckey, csig
        active.path = rel
        active.width, active.height = out.width, out.height
        active.bytes = len(data)
        active.format = ext
        active.rotation = new_rotation
        session.flush()
        # In-place: different bytes under the same row, so re-read what they
        # say. See make_oriented_file's twin of this line.
        index_file_metadata(session, store, active)
        store.drop_thumb(active.id)
        drop_derived_caches(session, store, active.id)
        return active
    number = next_file_number(session, active.item_id)
    rel = store.write_file(uid, number, ext, data=data)
    f = File(
        item_id=active.item_id, sha256=digest, phash=phash,
        color_key=ckey, color_sig=csig, path=rel,
        number=number,
        width=out.width, height=out.height, bytes=len(data), format=ext,
        is_derived=True, derived_from_file_id=active.id,
        rotation=new_rotation, mirrored=bool(active.mirrored),
    )
    session.add(f)
    session.flush()
    index_file_metadata(session, store, f)
    store.drop_thumb(f.id)
    return f


def copy_rotated_artifacts(
    session: Session,
    store: ItemStore,
    from_file_id: int,
    to_file_id: int,
    rotation: int,
) -> None:
    """Create rotated *copies* of ``from_file_id``'s artifacts on ``to_file_id``,
    leaving the originals in place — used when a rotation branches to a new file
    so both the preserved source and the rotated derivative carry aligned
    control images."""
    rotation = int(rotation or 0) % 360
    to_file = session.get(File, to_file_id)
    if to_file is None:
        return
    # The rotated copy must not inherit the source's caches: they encode the
    # unrotated pixels, a latent is not an image to rotate anyway, and a
    # degraded copy re-saved as a PNG here would lose the very artifacts it
    # exists to hold. Excluded in the query too — see rotate_file_artifacts.
    drop_derived_caches(session, store, from_file_id)
    for art in session.execute(
        select(FileArtifact).where(
            FileArtifact.file_id == from_file_id,
            FileArtifact.kind.notin_(DERIVED_CACHE_KINDS),
        )
    ).scalars().all():
        uid = _item_uid(session, art.item_id)
        if not art.path:
            continue
        sha, w, h = art.sha256, art.width, art.height
        if rotation:
            with Image.open(store.file_path(uid, art.path)) as im:
                out = orient.apply_orientation(im, rotation, False)
                out.load()
            ext, data = media.encode_lossless(out)
            sha = sha256_bytes(data)
            w, h = out.width, out.height
        else:
            data = store.file_path(uid, art.path).read_bytes()
            ext = (art.format or "png")
        path = store.write_artifact(uid, to_file.number, art.kind, ext,
                                    data, art.model)
        session.add(FileArtifact(
            file_id=to_file_id, item_id=art.item_id, kind=art.kind, model=art.model,
            sha256=sha, path=path, width=w, height=h, bytes=len(data), format=ext,
            stale=art.stale,
        ))
    session.flush()

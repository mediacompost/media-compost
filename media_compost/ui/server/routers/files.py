"""Serve full images and lazily-generated thumbnails."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session


from media_compost import media
from media_compost.config import VIDEO_EXTS
from media_compost.db import (
    File,
)
from media_compost.ops import Ctx, files as ops_files
from ..schemas import RequestModel
from ..deps import Library, get_ctx, get_library, get_session

router = APIRouter(prefix="/api/files", tags=["files"])


def _content_etag(f: File) -> str:
    """A strong ETag keyed on the file's content hash. SQLite reuses file rowids
    after a deletion (e.g. rotating back to 0° drops the derived rotation file),
    so caching a thumbnail/image by id alone can later serve a *different* file's
    bytes. Keying on the content sha, and revalidating (see the ``no-cache``
    responses below), means a reused id or a rotate-in-place never serves a stale
    or wrong-item image from the browser cache.

    The ``-2`` suffix is a one-time cache-buster: a window existed where stale
    per-id thumbnails were served under fresh sha-keyed ETags (a rebuilt DB over
    leftover thumbs), poisoning browser caches in a way revalidation could never
    heal — the wrong bytes carried the *right* ETag. Bumping the version makes
    every old entry miss once and refetch clean bytes."""
    return f'"{f.sha256}-2"'


# Cache but always revalidate: an unchanged sha returns a cheap 304, a changed
# one (reused id / edited bytes) returns fresh content.
_REVALIDATE = "no-cache"


def _stored_path(lib: Library, s: Session, f: File):
    """Absolute path of the file's bytes in its item folder, or 404."""
    if not f.path:
        raise HTTPException(404, "file has no stored bytes")
    path = lib.store.path_of(s, f)
    if not path.exists():
        raise HTTPException(404, "file missing on disk")
    return path


def release(s: Session) -> None:
    """Hand the SQLite connection back BEFORE the bytes go out.

    A dependency with ``yield`` is exited only once the response has been
    SENT, so a ``Session`` opened for a file handler stays open — holding one
    of the engine pool's connections — for as long as the transfer takes. For
    an image that is milliseconds. For a film it is the whole download, and a
    ``<video>`` that is being scrubbed abandons partial requests faster than
    they finish: the pool is 5 connections plus 10 overflow, so a couple of
    dozen seeks exhaust it and EVERY later request — the grid, the item, the
    settings — blocks for the 30 s pool timeout and then fails. That reads
    exactly as it was reported: the picture stops updating and the whole
    server appears to freeze.

    So every handler here reads its row, works out its path, and lets the
    session go. The generator's later ``commit()``/``close()`` are then no-ops
    on a session with nothing pending, which is what these read-only handlers
    always were. The same applies to anything SLOW between the query and the
    response, ffprobe included.

    The flag is for `app._commit_before_responding`, which commits every other
    request's session on the way out: committing one of these would check a
    pool connection back out to write nothing, undoing exactly what the
    ``close()`` above bought.
    """
    s.info["released"] = True
    s.close()


@router.get("/{file_id}")
def get_file(file_id: int, request: Request,
             s: Session = Depends(get_session),
             lib: Library = Depends(get_library)):
    """Serve the file's full bytes as stored. A file's bytes are already in their
    final orientation (a rotated source file holds rotated pixels), so nothing is
    transformed here."""
    f = s.get(File, file_id)
    if not f:
        raise HTTPException(404, "file not found")
    etag = _content_etag(f)
    if request.headers.get("if-none-match") == etag:
        release(s)
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": _REVALIDATE})
    path = _stored_path(lib, s, f)
    release(s)
    return FileResponse(path, headers={"ETag": etag, "Cache-Control": _REVALIDATE})


@router.get("/{file_id}/subtitle/{stream}")
def get_subtitle(file_id: int, stream: int,
                 s: Session = Depends(get_session),
                 lib: Library = Depends(get_library)):
    """One embedded subtitle stream, converted to WebVTT so the annotator's
    ``<video>`` can display it (browsers don't render embedded ASS/SRT)."""
    f = s.get(File, file_id)
    if not f:
        raise HTTPException(404, "file not found")
    path = _stored_path(lib, s, f)
    # ffmpeg demuxes a whole subtitle stream here — seconds on a long film, and
    # nothing about it needs the database.
    release(s)
    try:
        vtt = media.extract_subtitle_vtt(path, stream)
    except media.MediaError:
        raise HTTPException(404, "subtitle stream not available")
    return Response(vtt, media_type="text/vtt",
                    headers={"Cache-Control": _REVALIDATE})


@router.get("/{file_id}/thumb")
def get_thumb(file_id: int, request: Request, s: Session = Depends(get_session),
              lib: Library = Depends(get_library)):
    f = s.get(File, file_id)
    if not f:
        raise HTTPException(404, "file not found")
    thumb = lib.store.thumb_path(f.id, f.sha256)
    # THE THUMBNAIL'S OWN ETAG, not the file's. A thumbnail is derived, so the
    # file's content hash is normally the honest key for it — until somebody
    # REPLACES it (picking which frame represents a film), where the bytes on
    # disk change while the file they came from does not. `File.thumb_rev` is
    # what says so; without it the browser revalidated, was told 304, and went
    # on showing the frame that had just been rejected.
    etag = f'{_content_etag(f)[:-1]}-{int(f.thumb_rev or 0)}"'
    if request.headers.get("if-none-match") == etag:
        release(s)
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": _REVALIDATE})
    missing = not thumb.exists()
    path = _stored_path(lib, s, f) if missing else None
    is_video = f.format in VIDEO_EXTS
    duration = f.duration or 0.0
    fid, sha = f.id, f.sha256
    # Generating a video thumbnail runs ffmpeg; the row has already said
    # everything the generation needs.
    release(s)
    if missing and path is not None:
        # Still image: thumbnail the stored bytes directly. Videos need a
        # representative frame extracted first.
        if is_video:
            # Downscaled by ffmpeg: a thumbnail is all this frame is for, so
            # there is nothing to gain from encoding, piping and decoding a
            # 1920x1080 one just to resize it here.
            im = media.extract_frame(path, duration / 2,
                                     max_dim=lib.config.thumb_size)
            thumb = lib.store.ensure_thumb_from_image(fid, sha, im)
        else:
            thumb = lib.store.ensure_thumb(fid, sha, path)
    return FileResponse(
        thumb, media_type="image/webp",
        headers={"ETag": etag, "Cache-Control": _REVALIDATE},
    )


@router.delete("/{file_id}")
def delete_file(file_id: int, ctx: Ctx = Depends(get_ctx)):
    """Remove one file version of an item, along with its bytes, its artifacts
    and its thumbnail."""
    ops_files.delete_file(ctx, file_id)
    return {"ok": True}


class RenameFileName(RequestModel):
    name: str


@router.patch("/{file_id}/names/{name_id}")
def rename_file_name(file_id: int, name_id: int, body: RenameFileName,
                     ctx: Ctx = Depends(get_ctx)):
    """Rename one of a source file's source infos (a filename or a URL)."""
    ops_files.rename_source(ctx, file_id, name_id, body.name)
    return {"ok": True}


@router.delete("/{file_id}/names/{name_id}")
def delete_file_name(file_id: int, name_id: int,
                     ctx: Ctx = Depends(get_ctx)):
    """Remove one of a source file's source infos."""
    ops_files.remove_source(ctx, file_id, name_id)
    return {"ok": True}


class AddSource(RequestModel):
    # Exactly one of: a filename (+ optional relative path), or a web URL.
    name: Optional[str] = None
    url: Optional[str] = None
    # ISO access date/time for a URL source (defaults to now).
    accessed_at: Optional[str] = None


@router.post("/{file_id}/names")
def add_file_name(file_id: int, body: AddSource,
                  ctx: Ctx = Depends(get_ctx)):
    """Add a source to a file: either a filename+path or a web URL."""
    fn = ops_files.add_source(ctx, file_id, name=body.name, url=body.url,
                              accessed_at=body.accessed_at)
    return {"ok": True, "id": fn.id}


class SplitFiles(RequestModel):
    # The files to move out together, all of one item. Several leave as ONE new
    # item — a file each is the same call repeated, which is what the row's own
    # button does.
    file_ids: list[int]


@router.post("/split")
def split_files(body: SplitFiles, ctx: Ctx = Depends(get_ctx)):
    """Split several file versions of one item out into a single new entry."""
    return {"ok": True, "item_id": ops_files.split_files(ctx, body.file_ids)}


@router.post("/{file_id}/split")
def split_file(file_id: int, ctx: Ctx = Depends(get_ctx)):
    """Split one file version out into its own new image entry."""
    return {"ok": True, "item_id": ops_files.split(ctx, file_id)}

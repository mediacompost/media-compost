"""Serve and delete auxiliary file artifacts (depth maps, pose overlays, and
the cached training latents).

An artifact is generated *from* a source file (see
:class:`~media_compost.db.FileArtifact`); it is shown nested under that file in
the Source list. These endpoints serve its bytes (from the item's ``artifacts/``
folder) and delete it (row + bytes).

A cached latent is safe to delete — the next run re-encodes whatever it is
missing — but not while a run is *using* it, so deleting one is refused while
training is under way.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from media_compost.db import FileArtifact
from media_compost.ops import Ctx, artifacts as ops_artifacts
from ..deps import Library, get_ctx, get_library, get_session
from .files import release

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


def _serves_as_image(a: FileArtifact) -> str:
    """The media type to serve an artifact with.

    A latent is a torch tensor, not an image: served as one it would be a
    broken image rather than a download.
    """
    if a.kind == "latent":
        return "application/octet-stream"
    return f"image/{a.format or 'png'}"


@router.get("/{artifact_id}")
def get_artifact(artifact_id: int, request: Request,
                 s: Session = Depends(get_session),
                 lib: Library = Depends(get_library)):
    a = s.get(FileArtifact, artifact_id)
    if a is None or not a.path:
        raise HTTPException(404, "artifact not found")
    path = lib.store.path_of(s, a)
    if not path.exists():
        raise HTTPException(404, "artifact file missing")
    # "-2" mirrors the files router's one-time cache-buster (see _content_etag
    # there): artifact ids were also reassigned by a DB rebuild.
    etag = f'"{a.sha256}-2"'
    media_type = _serves_as_image(a)
    # The connection goes back before the bytes go out — see `files.release`
    # for what holding one across a transfer costs.
    release(s)
    if request.headers.get("if-none-match") == etag:
        from fastapi.responses import Response
        return Response(status_code=304, headers={"ETag": etag})
    return FileResponse(
        path, media_type=media_type,
        headers={"ETag": etag, "Cache-Control": "no-cache"},
    )


@router.delete("/{artifact_id}")
def delete_artifact(artifact_id: int, ctx: Ctx = Depends(get_ctx),
                    lib: Library = Depends(get_library)):
    """Delete a generated artifact (or a cached latent) and its bytes."""
    ops_artifacts.delete_artifact(
        ctx, artifact_id,
        training_running=bool(lib.training.running_uid()))
    return {"ok": True}

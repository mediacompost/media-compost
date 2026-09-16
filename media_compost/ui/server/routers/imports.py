"""Import endpoint: multipart uploads or server-side paths, run as a job."""

from __future__ import annotations

import itertools
import shutil
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from media_compost.importer import Importer, ImportOptions, ImportStats
from ..deps import Library, get_current_user, get_library
from ..schemas import ImportJobOut, ImportOptionsIn

router = APIRouter(prefix="/api/import", tags=["import"])

# Folder imports routinely exceed Starlette's default 1000-file / 1000-field
# multipart caps, so we parse the form ourselves with much higher ceilings.
_MAX_UPLOAD_FILES = 200_000

# In-memory job registry (single-process local app). It OUTLIVES THE PAGE
# that started the import — which is the point: a reload throws the browser's
# own task list away (the File objects live in memory for the session), and
# without a record on this side an import that failed while nobody was
# watching would simply vanish. `GET /api/import/jobs` is that record.
_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()

#: How many finished import jobs to remember. The list is a record of what
#: happened, not a log: an unbounded dict in a server that runs for weeks is
#: a leak, and nobody scrolls past the last few imports anyway.
_KEEP_FINISHED = 40

#: Monotonic, so the list can be ordered newest-first. NOT `len(_JOBS)`,
#: which goes backwards as finished rows are forgotten.
_SEQ = itertools.count()


def _register(job_id: str, label: str, total: int) -> None:
    """Record a starting import, and forget the oldest finished ones."""
    with _LOCK:
        _JOBS[job_id] = {"status": "running", "stats": {}, "message": "",
                         "total": total, "label": label, "seq": next(_SEQ),
                         "started": time.time()}
        finished = sorted((j["seq"], k) for k, j in _JOBS.items()
                          if j["status"] != "running")
        for _, key in finished[:max(0, len(finished) - _KEEP_FINISHED)]:
            _JOBS.pop(key, None)


def _forget(job_id: str) -> None:
    """Drop a registered run that never became one — a request refused before
    it started is a caller's mistake, not an import that failed."""
    with _LOCK:
        _JOBS.pop(job_id, None)


def _describe(job_id: str, label: str, total: int) -> None:
    """Name a run once the request has said what it is carrying."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            job["label"] = label
            job["total"] = total


def _fail(job_id: str, message: str) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            job["status"] = "error"
            job["message"] = message


def _label_for(paths: list[Path], total: int) -> str:
    """What to call this run in a list nobody has the file names for: the one
    thing that was dropped, or how many there were."""
    if len(paths) == 1:
        return paths[0].name
    return f"{total or len(paths)} files"


def _queue_face_detection(lib: Library, model: str, item_ids: list[int],
                          username: str) -> None:
    """Detect faces on what was just imported, as one background job.

    Detection is a model run, not part of reading a file, so it belongs in the
    job queue rather than inside the importer — which is also what makes it
    cancellable and what lets the CLI import without a worker at all. Videos
    and sequences are dropped: the detector is handed one image, and a
    container item has none of its own.
    """
    from media_compost.db import Item

    if not model or not item_ids:
        return
    with lib.db.session() as s:
        images = [iid for iid in item_ids
                  if (it := s.get(Item, iid)) is not None and it.kind == "image"]
    if images:
        lib.jobs.enqueue("faces", model, images, username=username,
                         merge=True)


def embedder_ids(value: "str | list[str] | None") -> list[str]:
    """The embedders an import was asked to index with.

    ONE spelling of that answer, because the request arrives two ways: the
    multipart form sends the comma-separated string `ignore_kinds` already
    uses, and the JSON body may send a list. A bare id is the one-element
    list every caller written before multi-selection sent, so nothing that
    asked for one embedder means anything different now. Order is the
    caller's, less blanks and repeats — two jobs for one space would index
    the same pictures twice.
    """
    if not value:
        return []
    parts = value.split(",") if isinstance(value, str) else list(value)
    out: list[str] = []
    for p in parts:
        p = str(p).strip()
        if p and p not in out:
            out.append(p)
    return out


def _queue_embed_indexing(lib: Library, models: "str | list[str]",
                          item_ids: list[int], username: str) -> None:
    """Index what was just imported for the tag batch's smart ordering — the
    same shape as the face run above: a model run over the created images,
    queued AFTER the import as one cancellable background job. Videos and
    containers are dropped for the same reason (an embedder reads a
    picture).

    ONE JOB PER EMBEDDER, and that is the model rather than a convenience:
    each space is indexed on its own and never mixed, so "index with DINOv2
    and CLIP" is two runs over the same pictures. They merge into whatever
    run of their own kind and model is already live (`merge=True`), which is
    what keeps an import that uploads in batches to one row per embedder.
    """
    from media_compost.db import Item

    keys = embedder_ids(models)
    if not keys or not item_ids:
        return
    with lib.db.session() as s:
        images = [iid for iid in item_ids
                  if (it := s.get(Item, iid)) is not None and it.kind == "image"]
    if images:
        for key in keys:
            lib.jobs.enqueue("embed", key, images, username=username,
                             merge=True)


def _run_job(job_id: str, lib: Library, paths: list[Path],
             options: ImportOptions, cleanup: Path | None, username: str = "",
             detect_faces: str = "",
             index_embeddings: "str | list[str]" = ""):
    def on_progress(stats: ImportStats, name: str):
        with _LOCK:
            _JOBS[job_id]["stats"] = stats.as_dict()
            _JOBS[job_id]["message"] = name

    try:
        # Serialize imports (they contend on the single SQLite writer anyway) so
        # the shared thumb cache is only touched by one job at a time.
        with lib.import_lock, lib.db.session() as s:
            # Attribute the import's history event to the caller (captured at
            # request time; this runs on a background thread).
            s.info["username"] = username
            imp = Importer(
                s, lib.store, lib.config, on_progress=on_progress,
                shared_thumbs=lib.thumb_cache,
            )
            stats = imp.import_paths(paths, options)
            # One coarse history entry per import run (imports are bulk; per-file
            # rows would swamp the log). Skip a run that changed nothing.
            # A run that created nothing but TAGGED existing items (the
            # tags_existing default over a re-import) is an entry too — its
            # assignments were invisible and unrevertible without one.
            from media_compost.importer import import_event
            ev = import_event(stats, options.parent_group_id)
            if ev is not None:
                from media_compost.history import log_event
                if stats.imported or stats.added_alternative:
                    # This route's own summary shape, kept as it was.
                    parts = [f"{stats.imported} new"]
                    if stats.added_alternative:
                        parts.append(f"{stats.added_alternative} alternative")
                    if stats.skipped_duplicate:
                        parts.append(f"{stats.skipped_duplicate} duplicate")
                    ev = {**ev, "summary": "Imported " + ", ".join(parts),
                          "summary_vars": None}
                log_event(s, source="web", **ev)
            # Always commit: the periodic per-file commit only fires every 200
            # files, so a smaller import's items (and a re-import's touched dates /
            # group assignments) live only in this session and are otherwise lost
            # when it closes.
            s.commit()
        # THE IMPORT IS OVER HERE, and says so before anything else is
        # queued. The follow-up runs are separate background tasks with their
        # own row and their own progress bar, so an import that waited for
        # them — or that reported "running" while one of them held the
        # writer — would be reporting somebody else's work as its own. That
        # is exactly what a browser uploading in batches of 200 saw: each
        # batch's status sat on "running" behind the previous batch's
        # detection run, so the whole import advanced one detector's pace.
        with _LOCK:
            _JOBS[job_id]["stats"] = stats.as_dict()
            _JOBS[job_id]["status"] = "done"
    except Exception as exc:  # noqa: BLE001
        with _LOCK:
            _JOBS[job_id]["status"] = "error"
            _JOBS[job_id]["message"] = str(exc)
        return
    finally:
        if cleanup and cleanup.exists():
            shutil.rmtree(cleanup, ignore_errors=True)
    # `merge=True`: an import hands its files over in batches, and one
    # detection job per batch is twenty rows for one run. They fold into the
    # job already doing this, which is what makes the progress bar cover the
    # whole import rather than a two-hundredth of it.
    try:
        _queue_face_detection(lib, detect_faces,
                              list(stats.imported_item_ids), username)
        _queue_embed_indexing(lib, index_embeddings,
                              list(stats.imported_item_ids), username)
    except Exception as exc:  # noqa: BLE001 - the import itself succeeded
        print(f"import: could not queue the follow-up runs: {exc}",
              file=sys.stderr)


def _as_bool(v: object, default: bool) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _as_int(v: object, default: int) -> int:
    """A form field that is a number. Anything that is not one — an empty
    field, a stray word — is the default rather than a 400: the multipart
    body is built by the browser field by field, and a minimum nobody typed
    is no minimum."""
    try:
        return max(0, int(str(v).strip()))
    except (TypeError, ValueError):
        return default


def _as_float(v: object, default: float) -> float:
    """The same, for a threshold in megapixels — which is a decimal."""
    try:
        return max(0.0, float(str(v).strip()))
    except (TypeError, ValueError):
        return default


async def _stage_upload(uf: UploadFile, dest: Path) -> None:
    """Copy one upload to disk off the event loop (spooled reads are blocking)."""
    def _copy() -> None:
        uf.file.seek(0)
        with open(dest, "wb") as out:
            shutil.copyfileobj(uf.file, out, length=1024 * 1024)
    await run_in_threadpool(_copy)


@router.post("", response_model=ImportJobOut)
async def start_import(request: Request, lib: Library = Depends(get_library),
                       user: str = Depends(get_current_user)):
    """Upload files (multipart) and import them in the background.

    The form is parsed manually so we can raise Starlette's default caps — a
    single folder drop can carry many thousands of files.

    **The run is REGISTERED before the body is read**, which is earlier than
    it looks like it needs to be: reading the form IS the upload (Starlette
    spools every part to disk before this returns), so a page reloaded
    mid-import dies exactly here — and a failure with no row to land on is a
    run that vanishes with the page that started it. The row is named once
    the request has said what it carries, forgotten again if the request was
    simply refused, and marked failed if anything else goes wrong.
    """
    job_id = uuid.uuid4().hex
    _register(job_id, "Import", 0)
    try:
        return await _start_upload(job_id, request, lib, user)
    except HTTPException:
        _forget(job_id)
        raise
    except Exception as exc:  # noqa: BLE001 - recorded, then re-raised
        _fail(job_id, str(exc) or exc.__class__.__name__)
        raise


async def _start_upload(job_id: str, request: Request, lib: Library,
                        user: str) -> ImportJobOut:
    form = await request.form(
        max_files=_MAX_UPLOAD_FILES, max_fields=_MAX_UPLOAD_FILES
    )
    uploads = [f for f in form.getlist("files") if isinstance(f, UploadFile)]
    if not uploads:
        raise HTTPException(400, "no files uploaded")

    parent_raw = form.get("parent_group_id")
    parent_group_id = (
        int(parent_raw) if parent_raw not in (None, "", "null") else None
    )
    def _tag_list(key: str) -> list[str]:
        return [t for t in str(form.get(key) or "").split(",") if t.strip()]

    options = ImportOptions(
        parent_group_id=parent_group_id,
        new_group=_as_bool(form.get("new_group"), False),
        new_group_name=str(form.get("new_group_name") or ""),
        folders_as_groups=_as_bool(form.get("folders_as_groups"), True),
        recursive=_as_bool(form.get("recursive"), True),
        archives_as_groups=_as_bool(form.get("archives_as_groups"), False),
        sequence_grouping=str(form.get("sequence_grouping") or "both"),
        archive_sequences=_as_bool(form.get("archive_sequences"), False),
        min_megapixels=_as_float(form.get("min_megapixels"), 0.0),
        min_short_edge=_as_int(form.get("min_short_edge"), 0),
        min_long_edge=_as_int(form.get("min_long_edge"), 0),
        min_aspect=_as_float(form.get("min_aspect"), 0.0),
        max_aspect=_as_float(form.get("max_aspect"), 0.0),
        ignore_kinds=tuple(
            k for k in str(form.get("ignore_kinds") or "").split(",")
            if k in ("image", "video", "sequence", "archive")),
        tags_existing=_as_bool(form.get("tags_existing"), True),
        tags=_tag_list("tags"),
        tags_image=_tag_list("tags_image"),
        tags_video=_tag_list("tags_video"),
        tags_sequence=_tag_list("tags_sequence"),
    )
    detect_faces = str(form.get("detect_faces") or "").strip()
    index_embeddings = str(form.get("index_embeddings") or "").strip()

    staging = Path(tempfile.mkdtemp(prefix="mc_upload_"))
    total = 0
    try:
        for uf in uploads:
            # Preserve any relative path the browser sent (webkitRelativePath).
            rel = (uf.filename or "file").lstrip("/")
            dest = staging / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            await _stage_upload(uf, dest)
            total += 1
    except BaseException:
        # Nothing owns the staged bytes until the thread below is started —
        # a client that goes away mid-upload would otherwise leave the whole
        # partial drop in the temp directory forever.
        shutil.rmtree(staging, ignore_errors=True)
        raise

    # Import the staging dir's *contents*, not the dir itself, so the temp
    # folder name never becomes a group: dropped subfolders map to groups and
    # loose files land under the chosen parent.
    roots = sorted(staging.iterdir())
    _describe(job_id, _label_for(roots, total), total)
    threading.Thread(
        target=_run_job,
        args=(job_id, lib, roots, options, staging, user, detect_faces,
              index_embeddings),
        daemon=True,
    ).start()
    return ImportJobOut(id=job_id, status="running", stats={}, total=total)


@router.post("/paths", response_model=ImportJobOut)
def import_paths(body: ImportOptionsIn, lib: Library = Depends(get_library),
                 user: str = Depends(get_current_user)):
    """Import server-side paths (for local/CLI-style use)."""
    if not body.paths:
        raise HTTPException(400, "no paths given")
    paths = [Path(p) for p in body.paths]
    total = 0
    for p in paths:
        if p.is_dir():
            total += sum(1 for f in p.rglob("*") if f.is_file())
        elif p.is_file():
            total += 1
    job_id = uuid.uuid4().hex
    _register(job_id, _label_for(paths, total), total)
    options = ImportOptions(
        parent_group_id=body.parent_group_id,
        new_group=body.new_group,
        new_group_name=body.new_group_name,
        folders_as_groups=body.folders_as_groups,
        recursive=body.recursive,
        archives_as_groups=body.archives_as_groups,
        sequence_grouping=body.sequence_grouping,
        archive_sequences=body.archive_sequences,
        min_megapixels=body.min_megapixels,
        min_short_edge=body.min_short_edge,
        min_long_edge=body.min_long_edge,
        min_aspect=body.min_aspect,
        max_aspect=body.max_aspect,
        ignore_kinds=tuple(body.ignore_kinds),
        tags=body.tags,
        tags_image=body.tags_image,
        tags_video=body.tags_video,
        tags_sequence=body.tags_sequence,
    )
    threading.Thread(
        target=_run_job,
        args=(job_id, lib, paths, options, None, user, body.detect_faces,
              body.index_embeddings),
        daemon=True,
    ).start()
    return ImportJobOut(id=job_id, status="running", stats={}, total=total)


@router.get("/jobs")
def list_import_jobs():
    """Every import this SERVER knows about — which is not the same set the
    page knows about.

    The browser owns the import it started (it holds the files), so this list
    is what is left when that page goes away: a reload during an import loses
    the task, and a run that then failed would have nowhere to be seen. The
    frontend shows the rows it does not already own, and a failed one stays
    until it is cleared by hand.

    DECLARED BEFORE ``/{job_id}``: that route matches any single segment, so
    a listing added under it would be read as a job called "jobs".
    """
    with _LOCK:
        rows = sorted(_JOBS.items(), key=lambda kv: kv[1].get("seq", 0),
                      reverse=True)
        return {"jobs": [
            {"id": jid, "status": j["status"], "stats": j.get("stats", {}),
             "message": j.get("message", ""), "total": j.get("total", 0),
             "label": j.get("label", ""), "started": j.get("started", 0.0)}
            for jid, j in rows
        ]}


@router.post("/jobs/{job_id}/clear")
def clear_import_job(job_id: str):
    """Forget one finished import. A running one is refused — there would be
    nothing to report its outcome to."""
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            raise HTTPException(404, "job not found")
        if job["status"] == "running":
            raise HTTPException(400, "cannot clear a running import")
        _JOBS.pop(job_id, None)
    return {"ok": True}


@router.get("/{job_id}", response_model=ImportJobOut)
def job_status(job_id: str):
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        return ImportJobOut(
            id=job_id, status=job["status"], stats=job.get("stats", {}),
            message=job.get("message", ""), total=job.get("total", 0),
        )

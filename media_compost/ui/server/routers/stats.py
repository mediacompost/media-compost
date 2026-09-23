"""Library-wide stats (item / file counts and total stored bytes), and the
STORAGE breakdown behind Settings → Storage.

The breakdown is DB aggregates for everything the library records — a file
and an artifact each carry their own byte count, so "what is this library
made of" is two GROUP BYs rather than a walk of a hundred thousand folders —
and a directory walk only for what no row describes: the thumbnail cache, the
database itself, the training runs.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, literal, select, union_all
from sqlalchemy.orm import Session

from media_compost import fileops
from media_compost.db import (File, FileArtifact, Group, Item, ItemTag, Tag,
                              TrashedItem, is_locked_error)
from media_compost.instance import write_lease
from media_compost.ops import Ctx, artifacts as ops_artifacts, files as ops_files
from ..deps import (Library, get_ctx, get_current_user, get_library,
                    get_session)
from ..schemas import (LibraryStats, StorageArtifactRow, StorageOut,
                       StoragePruneJobOut, StoragePruneOut,
                       StoragePruneRequest, StorageRow)

router = APIRouter(prefix="/api/library", tags=["library"])


def _disk_space(path) -> tuple[int, int]:
    """``(free, total)`` bytes of the volume holding ``path``.

    Reported as free-to-*this user* (``shutil.disk_usage().free``), not the
    root reserve, since that is what an import can actually use. Both 0 when
    the path can't be stat'd — the caller shows nothing rather than a scary
    "0 B free"."""
    import shutil

    try:
        usage = shutil.disk_usage(path)
        return int(usage.free), int(usage.total)
    except OSError:
        return 0, 0


#: The last answer, and what the library looked like when it was given.
#: One entry — a process serves one library — and no lock: the worst a race
#: can do is compute the same numbers twice.
_STATS_CACHE: dict[str, object] = {}


def _library_revision(s: Session, lib: Library) -> tuple:
    """A token that changes whenever ANYTHING in the library may have.

    `Database.revision` — the one definition (its docstring is where the two
    halves and the per-connection trap are written down) — plus the data
    directory, since this cache is a module global and a token alone cannot
    say which library it was taken from.

    It used to read `PRAGMA data_version` here itself, a copy of the same
    two lines, and the copy carried the same bug: SQLite's counter is per
    CONNECTION, so after any write the writing connection and the rest
    answered differently and the token flapped from one request to the next.
    Measured on this endpoint, a pool of six connections and two writes:
    EIGHT recomputes in twelve reads, of eight aggregates over the whole
    library. Deliberately not a clock: it is compared for equality, never
    ordered, so there is no window in which a stale answer is "recent
    enough".
    """
    return (str(lib.config.data_dir), *lib.db.revision(s))


def _pending_counts(s: Session, visible) -> tuple[int, int, int, int]:
    """(tags, captions, faces, any) — the four Pending figures in ONE pass.

    Asked as four `count(*) FROM items WHERE <exists>` they were four scans
    of the library, and the "any" one could not use an index at all (an OR of
    three EXISTS has no single index to drive it): 183 ms of the endpoint's
    600. Read from the PENDING SIDE instead — the three partial indexes are
    tiny by construction, since what is pending is what nobody has reviewed
    yet — the four numbers are one grouped pass over them: 39 ms.

    `count(DISTINCT)` per source rather than a sum, because an item with two
    pending tags is one pending item; the union carries a source marker so
    the three and their union come out of the same rows.
    """
    from media_compost.db import Caption, Face, ItemSubject

    src = union_all(
        select(ItemTag.item_id.label("id"), literal(1).label("src"))
        .where(ItemTag.pending.is_(True)),
        select(Caption.item_id, literal(2))
        .where(Caption.pending.is_(True)),
        select(ItemSubject.item_id, literal(3))
        .select_from(ItemSubject)
        .join(Face, Face.id == ItemSubject.face_id)
        .where(ItemSubject.assigned_by == "suggested",
               Face.dismissed.is_(False)),
    ).subquery()
    per = [func.count(func.distinct(
        case((src.c.src == n, src.c.id), else_=None))) for n in (1, 2, 3)]
    row = s.execute(
        select(func.count(func.distinct(src.c.id)), *per)
        .select_from(src)
        .join(Item, Item.id == src.c.id)
        .where(visible)
    ).one()
    return int(row[1]), int(row[2]), int(row[3]), int(row[0])


@router.get("/stats", response_model=LibraryStats)
def library_stats(s: Session = Depends(get_session),
                  lib: Library = Depends(get_library)):
    """The sidebar's figures.

    CACHED on `_library_revision`: these are eight aggregates over the whole
    library — 0.6 s on a million items, and the sidebar asks for them on
    every load and after every write anything invalidates. The cache is not a
    TTL: it is keyed on a token that moves the moment anything changes, so
    the answer is either this library's or it is recomputed. What it buys is
    the ordinary case, where a browsing session asks the same question over
    and over and the library has not moved.
    """
    key = _library_revision(s, lib)
    hit = _STATS_CACHE.get("key")
    if hit == key and "value" in _STATS_CACHE:
        return _STATS_CACHE["value"]
    # Category counts reflect what the grid shows: trashed and hidden items are
    # excluded (they live in their own Trash / Hidden views).
    trashed_sub = select(TrashedItem.item_id)
    visible = Item.hidden.is_(False) & ~Item.id.in_(trashed_sub)
    # ONE pass for the total and the three kind figures: the count and the
    # GROUP BY were two scans of the same rows asking the same WHERE.
    total, images, videos, sequences = s.execute(
        select(func.count(),
               func.sum(case((Item.kind == "image", 1), else_=0)),
               func.sum(case((Item.kind == "video", 1), else_=0)),
               func.sum(case((Item.kind == "sequence", 1), else_=0)))
        .select_from(Item).where(visible)
    ).one()
    files = s.execute(select(func.count()).select_from(File)).scalar_one()
    total_bytes = s.execute(
        select(func.coalesce(func.sum(File.bytes), 0))
    ).scalar_one()
    # NEVER a trashed item — `ops/items.trash_one` clears the flag now, so
    # this is the belt for a library that already holds both states: a badge
    # counting a picture the Hidden view does not show is a number nothing
    # can make agree with the list under it.
    hidden = s.execute(
        select(func.count()).select_from(Item)
        .where(Item.hidden.is_(True), ~Item.id.in_(trashed_sub))
    ).scalar_one()
    pending_tags_n, pending_captions_n, pending_faces_n, pending = \
        _pending_counts(s, visible)
    groups = s.execute(select(func.count()).select_from(Group)).scalar_one()
    tags = s.execute(select(func.count()).select_from(Tag)).scalar_one()
    free, disk_total = _disk_space(lib.config.data_dir)
    out = LibraryStats(
        items=int(total or 0), files=files, bytes=int(total_bytes),
        images=int(images or 0),
        videos=int(videos or 0),
        sequences=int(sequences or 0),
        hidden=int(hidden),
        pending=pending,
        pending_tags=pending_tags_n,
        pending_captions=pending_captions_n,
        pending_faces=pending_faces_n,
        groups=groups, tags=tags,
        data_dir=str(lib.config.data_dir),
        phash_threshold=int(lib.config.phash_threshold),
        disk_free=free, disk_total=disk_total,
    )
    _STATS_CACHE["key"], _STATS_CACHE["value"] = key, out
    return out


# ---- storage ----------------------------------------------------------------


#: Where the Evaluate tab writes its runs, under ``<data>/training``. The
#: trainer's own name for it is `media_compost.train.evaluate._EVAL_DIRNAME`,
#: spelled again here because the app reaches the trainer through one guarded
#: import and nowhere else; `tests/ui/test_storage.py` holds the two equal.
EVAL_DIRNAME = "_eval"
#: …and where a deleted job's LOCKED weights go to live on as the user's own
#: adapters (`media_compost.train.paths.KEPT_DIRNAME`, held equal the same way).
KEPT_DIRNAME = "kept"

#: The job states the Storage page's delete takes: a job that is over. A draft,
#: a queued, paused or running job is work somebody has not finished with, and
#: a bulk delete from Settings is not the place to decide otherwise.
FINISHED_JOB_STATES = ("completed", "failed", "canceled")


def _dir_bytes(path: Path, skip: tuple[Path, ...] = ()) -> tuple[int, int]:
    """``(files, bytes)`` under ``path``, following no symlinks, and not
    descending into any directory in ``skip`` (one that has a row of its
    own).

    `os.scandir` rather than `Path.rglob` + `stat`: the entry a directory
    listing already returns carries the size on every platform this runs on,
    so a tree costs one syscall per entry instead of two. A directory that
    cannot be read contributes what was readable — this is a page saying
    roughly where the disk went, not an audit.
    """
    files = total = 0
    stack = [path]
    while stack:
        at = stack.pop()
        try:
            with os.scandir(at) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if Path(entry.path) not in skip:
                                stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            files += 1
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return files, total


def _db_bytes(db_path: Path) -> tuple[int, int]:
    """The database and the two files SQLite keeps beside it. The WAL is not
    a rounding error — it is routinely tens of megabytes on a busy library,
    and a breakdown that leaves it out has to explain a gap."""
    files = total = 0
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        try:
            total += p.stat().st_size
            files += 1
        except OSError:
            continue
    return files, total


@router.get("/storage", response_model=StorageOut)
def library_storage(s: Session = Depends(get_session),
                    lib: Library = Depends(get_library)):
    """What is using the library's disk, by type of item and of artifact."""
    cfg = lib.config
    items = [
        StorageRow(key=kind or "other", count=int(n), bytes=int(b or 0))
        for kind, n, b in s.execute(
            select(Item.kind, func.count(File.id),
                   func.coalesce(func.sum(File.bytes), 0))
            .join(Item, Item.id == File.item_id)
            .group_by(Item.kind)
            .order_by(func.coalesce(func.sum(File.bytes), 0).desc())
        ).all()
    ]
    artifacts = [
        StorageArtifactRow(
            kind=kind, model=model or "", count=int(n), bytes=int(b or 0),
            cache=kind in fileops.DERIVED_CACHE_KINDS)
        for kind, model, n, b in s.execute(
            select(FileArtifact.kind, FileArtifact.model, func.count(),
                   func.coalesce(func.sum(FileArtifact.bytes), 0))
            .group_by(FileArtifact.kind, FileArtifact.model)
            .order_by(func.coalesce(func.sum(FileArtifact.bytes), 0).desc())
        ).all()
    ]
    trashed_n, trashed_b = s.execute(
        select(func.count(File.id), func.coalesce(func.sum(File.bytes), 0))
        .join(TrashedItem, TrashedItem.item_id == File.item_id)
    ).one()

    other: list[StorageRow] = []
    # NOTHING HERE MAY CONTAIN ANYTHING ELSE HERE, or the total is a sum of
    # overlapping walks: `refs_dir` lives INSIDE `tmp`, so the two rows first
    # written reported the same five files twice, under two names. One row
    # per directory, and `tmp` is the one that contains the other.
    # THE EVALUATE TAB'S PICTURES LIVE INSIDE THE TRAINING FOLDER, and a
    # library that had never trained anything reported all of them as
    # "Training runs". They are their own row, and the training walk steps
    # over them — the rule above, applied the other way round.
    # …and so do the adapters kept from deleted jobs: they are the user's own
    # now, and a row that could not drop to nothing after every job was
    # deleted would read as a delete that did not work.
    training = Path(cfg.data_dir) / "training"
    evaluated = training / EVAL_DIRNAME
    kept = training / KEPT_DIRNAME
    for key, path, skip in (("thumbnails", cfg.thumbs_dir, ()),
                            ("training", training, (evaluated, kept)),
                            ("evaluate", evaluated, ()),
                            ("kept", kept, ()),
                            ("scratch", cfg.data_dir / "tmp", ()),
                            ("backups", cfg.backup_dir, ())):
        count, size = _dir_bytes(Path(path), skip)
        if count:
            other.append(StorageRow(key=key, count=count, bytes=size))
    count, size = _db_bytes(cfg.db_path)
    if count:
        other.append(StorageRow(key="database", count=count, bytes=size))
    other.sort(key=lambda r: r.bytes, reverse=True)

    free, total = _disk_space(cfg.data_dir)
    return StorageOut(
        data_dir=str(cfg.data_dir), items=items, artifacts=artifacts,
        other=other,
        trashed=StorageRow(key="trashed", count=int(trashed_n),
                           bytes=int(trashed_b or 0)),
        disk_free=free, disk_total=total,
    )


# One batch of a bulk artifact delete. Bounded for the reason
# `ops.artifacts.delete_kind` is: the transaction around it is the caller's,
# and a warmed latent cache is tens of thousands of rows.
_ARTIFACT_CHUNK = 500


@router.delete("/storage/artifacts")
def delete_storage_artifacts(kind: str = Query(...),
                             model: str | None = Query(None),
                             ctx: Ctx = Depends(get_ctx),
                             s: Session = Depends(get_session),
                             lib: Library = Depends(get_library)):
    """Delete every artifact of one type — the Storage page's row action.

    ``model`` absent means every model of that kind; ``model=""`` means the
    rows naming none. Written in COMMITTED CHUNKS, like the view-wide quick
    assign: one transaction over a whole latent cache is a long-held write
    lock, and a failure halfway through should keep the space it has already
    given back.
    """
    # `lib.training` is None without the training extra — and an install with
    # no trainer is exactly the one most likely to be clearing space. There is
    # then nothing to protect a cache from.
    manager = lib.training
    running = bool(manager.running_uid()) if manager is not None else False
    deleted = freed = 0
    while True:
        n, bytes_freed, more = ops_artifacts.delete_kind(
            ctx, kind, model, training_running=running,
            limit=_ARTIFACT_CHUNK)
        deleted += n
        freed += bytes_freed
        s.commit()
        if not more:
            break
    return {"ok": True, "deleted": deleted, "bytes": freed}


@router.delete("/storage/backups")
def delete_storage_backups(lib: Library = Depends(get_library)):
    """Throw away the copies the schema upgrades left behind — the Storage
    page's row action.

    A backup is the way back from a bad upgrade, so two things are true of
    this and neither is decoration. It deletes only files matching
    ``migrations.BACKUP_GLOB``, never the folder's contents: that directory is
    the app's, but a sweep that guessed would take whatever somebody had put
    beside them. And it is offered at all because the automatic pruning only
    runs after a SUCCESSFUL upgrade (`prune_backups`) — a library that has not
    migrated since keeps every copy it ever made, with nothing in the app able
    to say so, let alone give the space back.
    """
    from media_compost import migrations

    deleted = freed = 0
    for p in migrations.list_backups(lib.config.backup_dir):
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        try:
            p.unlink()
        except OSError:
            # Left behind rather than reported as gone: the page re-reads the
            # folder, so whatever survived is still on the next render.
            continue
        deleted += 1
        freed += size
    return {"ok": True, "deleted": deleted, "bytes": freed}


@router.delete("/storage/thumbnails")
def delete_storage_thumbnails(ctx: Ctx = Depends(get_ctx),
                              s: Session = Depends(get_session),
                              lib: Library = Depends(get_library)):
    """Empty the thumbnail cache — the Storage page's row action.

    Every thumbnail is made again the next time it is shown
    (`ItemStore.ensure_thumb`), so this costs time and nothing else — save a
    film's hand-picked frame, which lives only here and goes back to the
    default one (`ops.files.forget_chosen_thumbs` says so to the browsers).
    A `tmp…` name is a thumbnail being written right now (`_write_thumb`
    renames it into place), and is left for its writer to finish.
    """
    deleted = freed = 0
    root = Path(lib.config.thumbs_dir)
    for shard in (root.iterdir() if root.is_dir() else ()):
        if not shard.is_dir():
            continue
        for p in shard.iterdir():
            if p.name.startswith("tmp") or not p.is_file():
                continue
            try:
                size = p.stat().st_size
                p.unlink()
            except OSError:
                continue
            deleted += 1
            freed += size
    ops_files.forget_chosen_thumbs(ctx)
    s.commit()
    return {"ok": True, "deleted": deleted, "bytes": freed}


def _training_dirs(lib: Library) -> tuple[Path, Path, Path]:
    training = Path(lib.config.data_dir) / "training"
    return training, training / EVAL_DIRNAME, training / KEPT_DIRNAME


@router.delete("/storage/evaluate")
def delete_storage_evaluate(lib: Library = Depends(get_library)):
    """Delete every Evaluate result — the Storage page's row action, and the
    same delete the Evaluate grid's Remove makes, run over all of them.

    A generation that is RUNNING is left alone (its folder is being written,
    and the single delete refuses it too) and counted in ``skipped``; a queued
    one is taken off the queue first, as the single delete does.
    """
    ev = lib.evaluation
    if ev is None:
        raise HTTPException(404, "training is not offered by this server")
    _, evaluated, _ = _training_dirs(lib)
    before = _dir_bytes(evaluated)[1]
    deleted = skipped = 0
    for run in ev.list_runs():
        if run.get("status") == "running":
            skipped += 1
            continue
        try:
            ev.delete(run["uid"])
        except Exception:  # noqa: BLE001 — it started running meanwhile
            skipped += 1
            continue
        deleted += 1
    return {"ok": True, "deleted": deleted, "skipped": skipped,
            "bytes": max(0, before - _dir_bytes(evaluated)[1])}


@router.delete("/storage/training")
def delete_storage_training(lib: Library = Depends(get_library)):
    """Delete every FINISHED training job — completed, failed or canceled —
    through the job list's own delete, so a locked checkpoint survives as one
    of the user's adapters exactly as it does from there (``kept`` says how
    many). Drafts and queued, paused or running jobs are left and counted in
    ``skipped``. ``bytes`` is what the jobs' own row gave back, which is less
    than the folders held wherever weights moved to the kept adapters.
    """
    manager = lib.training
    if manager is None:
        raise HTTPException(404, "training is not offered by this server")
    training, evaluated, kept_dir = _training_dirs(lib)
    skip = (evaluated, kept_dir)
    before = _dir_bytes(training, skip)[1]
    deleted = skipped = kept = 0
    for job in manager.list_jobs():
        if job.get("status") not in FINISHED_JOB_STATES:
            skipped += 1
            continue
        try:
            kept += manager.delete(job["uid"])
        except Exception:  # noqa: BLE001 — it was restarted meanwhile
            skipped += 1
            continue
        deleted += 1
    return {"ok": True, "deleted": deleted, "skipped": skipped, "kept": kept,
            "bytes": max(0, before - _dir_bytes(training, skip)[1])}


# ---- pruning files by rule --------------------------------------------------

# One batch of a prune. Same bargain as `_ARTIFACT_CHUNK`: the transaction is
# this endpoint's, and a rule aimed at a crawl's thumbnails can match six
# figures of files.
_PRUNE_CHUNK = 500


def _prune_rule(body: StoragePruneRequest) -> ops_files.PruneRule:
    return ops_files.PruneRule(
        keep_active=body.keep_active, keep_edited=body.keep_edited,
        min_megapixels=float(body.min_megapixels),
        min_short_edge=int(body.min_short_edge),
        min_long_edge=int(body.min_long_edge),
        kind=body.kind)


@router.post("/storage/file-prune/preview", response_model=StoragePruneOut)
def preview_file_prune(body: StoragePruneRequest,
                       s: Session = Depends(get_session)):
    """What the rule would remove. A READ-ONLY POST — it carries a rule in its
    body and writes nothing, so it is named in `build.READ_ONLY_POSTS` or a
    page left open across a deploy gets a 409 for every keystroke."""
    files, size, items = ops_files.prune_preview(s, _prune_rule(body))
    return StoragePruneOut(files=files, bytes=size, items=items)


# The prune runs in the background, so its state lives in the process rather
# than in the request — the imports registry's shape (`routers/imports._JOBS`),
# for the same reasons: a library-wide task belongs to no item, so it is not a
# `Job` row (whose `item_id` is not nullable), and this is a single-process app.
_PRUNE_RUNS: dict[str, dict] = {}
_PRUNE_MU = threading.Lock()


def _prune_run(job_id: str, lib: Library, rule: ops_files.PruneRule,
               username: str) -> None:
    """Remove every file the rule matches, in COMMITTED CHUNKS.

    The chunking is what keeps write tenancy short and what makes a failure
    halfway through keep the space already given back — the same shape the
    artifact delete above and the view-wide quick assign both take. What each
    chunk additionally takes is the WRITE LEASE, for its own commit and no
    longer: that is the documented unit (`instance.write_lease`), and this
    path had been writing without one at all, so a prune and a concurrent
    crawler import met only at SQLite's own lock.

    A "database is locked" is retried on a fresh snapshot rather than failing
    the run, exactly as `Library._do` does it: pysqlite begins transactions
    deferred, so a chunk that READ and then met another process's commit at
    its first write is refused immediately whatever `busy_timeout` says. The
    rollback IS the fresh snapshot, and a chunk re-run from scratch is a
    chunk run once — the refused attempt committed nothing.
    """
    files = size = items = 0
    attempts = 4
    try:
        while True:
            with _PRUNE_MU:
                if _PRUNE_RUNS[job_id]["cancel"]:
                    _PRUNE_RUNS[job_id]["status"] = "cancelled"
                    return
            for attempt in range(attempts):
                with lib.db.session() as s:
                    # Attribute the deletions to whoever pressed the button:
                    # this runs on a background thread, outside the request.
                    s.info["username"] = username
                    ctx = Ctx(session=s, source="web", username=username,
                              _store=lib.store, _config=lib.config)
                    try:
                        with write_lease(lib.config.data_dir):
                            n, freed, gone, more = ops_files.prune(
                                ctx, rule, limit=_PRUNE_CHUNK)
                            s.commit()
                    except Exception as exc:  # noqa: BLE001
                        s.rollback()
                        if attempt < attempts - 1 and is_locked_error(exc):
                            time.sleep(0.05 * (2 ** attempt))
                            continue
                        raise
                break
            files += n
            size += freed
            items += gone
            with _PRUNE_MU:
                _PRUNE_RUNS[job_id].update(files=files, bytes=size, items=items)
                if not more:
                    _PRUNE_RUNS[job_id]["status"] = "done"
                    return
    except Exception as exc:  # noqa: BLE001
        with _PRUNE_MU:
            _PRUNE_RUNS[job_id]["status"] = "error"
            _PRUNE_RUNS[job_id]["message"] = str(exc)


def _prune_out(job_id: str, run: dict) -> StoragePruneJobOut:
    return StoragePruneJobOut(
        id=job_id, status=run["status"], files=run["files"],
        bytes=run["bytes"], items=run["items"], total=run["total"],
        message=run["message"])


@router.post("/storage/file-prune", response_model=StoragePruneJobOut)
def run_file_prune(body: StoragePruneRequest,
                   user: str = Depends(get_current_user),
                   s: Session = Depends(get_session),
                   lib: Library = Depends(get_library)):
    """Start a prune and answer at once with the run to poll.

    Removing 3 GB is minutes of work, and as one held-open request that is
    indistinguishable from a hang: nothing to show, nothing to cancel, and a
    browser or proxy timeout loses the answer while the deletions carry on.

    The preview runs HERE, on the request's own session and before the thread
    exists, because `total` is what makes a percentage possible — and because
    anything wrong with the rule is then a 400 the caller can read rather
    than a run that fails a moment later. It is the same pair of aggregates
    the page is already showing.
    """
    rule = _prune_rule(body)
    total, _, _ = ops_files.prune_preview(s, rule)
    job_id = uuid.uuid4().hex
    with _PRUNE_MU:
        # One at a time: two prunes would race for the same rows, and the
        # second would spend its chunks finding what the first had removed.
        for other, run in _PRUNE_RUNS.items():
            if run["status"] == "running":
                return _prune_out(other, run)
        _PRUNE_RUNS[job_id] = {"status": "running", "files": 0, "bytes": 0,
                               "items": 0, "total": int(total),
                               "message": "", "cancel": False}
    threading.Thread(target=_prune_run, args=(job_id, lib, rule, user),
                     daemon=True).start()
    with _PRUNE_MU:
        return _prune_out(job_id, _PRUNE_RUNS[job_id])


@router.get("/storage/file-prune/{job_id}", response_model=StoragePruneJobOut)
def file_prune_status(job_id: str):
    with _PRUNE_MU:
        run = _PRUNE_RUNS.get(job_id)
        if run is None:
            raise HTTPException(404, "no such prune")
        return _prune_out(job_id, run)


@router.delete("/storage/file-prune/{job_id}",
               response_model=StoragePruneJobOut)
def cancel_file_prune(job_id: str):
    """Stop after the chunk in flight. What is committed stays removed — the
    bytes are already gone, and a prune that undid its own finished chunks
    would have to put files back that nothing holds any more."""
    with _PRUNE_MU:
        run = _PRUNE_RUNS.get(job_id)
        if run is None:
            raise HTTPException(404, "no such prune")
        if run["status"] == "running":
            run["cancel"] = True
        return _prune_out(job_id, run)

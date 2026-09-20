"""Training jobs: file-based job store + one out-of-process trainer.

Thin HTTP layer over ``training.manager.TrainingManager`` (all lifecycle rules
live there); metrics/samples/logs are read straight from the job folder. See
``training/__init__.py`` for the storage layout.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse

from pathlib import Path


from media_compost.hub import pipeline_files
from media_compost.hub.download import ERROR as DL_ERROR, RUNNING as DL_RUNNING
from media_compost.hub.download import Download as ModelDownload
from .. import Trainer
from .. import gpu, paths as tp, usermodels
from ..manager import TrainingConflict, TrainingError
from ..models import registry_out
from .deps import get_current_user, get_library, get_trainer
from .schemas import (
    EvalFinetuneOut, EvalFinetunesOut,
    EvalLoraOut, EvalLorasOut, EvalRunIn, EvalRunOut, EvalRunsOut,
    SystemDeviceOut, TrainCheckpointOut, TrainCheckpointsOut, TrainEventOut,
    TrainEventsOut, TrainingJobDetailOut, TrainingJobIn, TrainingJobOut,
    TrainSettingChange,
    TrainingJobsOut, TrainLoraSourceOut, TrainLoraSourcesOut,
    TrainMetricPoint, TrainMetricsOut, TrainModelIn, TrainModelsOut,
    TrainCheckpointLockIn, TrainQueueOrderIn,
    TrainArchitectureOut, TrainDeviceOut, TrainSampleOut, TrainSampleRound,
    TrainSamplesOut, TrainStatusOut, TrainStepsIn,
    TrainVisitOut, TrainVisitsOut,
    DegradePreviewIn,
    QueriesPreviewIn,
    QueriesPreviewOut,
    QueryPreviewOut,
)
from media_compost.hub.setup import SetupRun

router = APIRouter(prefix="/api/train", tags=["train"])

_SAMPLE_NAME = re.compile(r"^p\d+\.png$")
_MAX_METRIC_POINTS = 2000
_LOG_TAIL_BYTES = 200_000


def _job_out(rec: dict) -> TrainingJobOut:
    return TrainingJobOut(
        uid=rec.get("uid", ""),
        name=rec.get("name", ""),
        username=rec.get("username", ""),
        status=rec.get("status", "draft"),
        step=int(rec.get("step") or 0),
        total_steps=int(rec.get("total_steps") or 0),
        message=rec.get("message", ""),
        phase=rec.get("phase", ""),
        phase_note=rec.get("phase_note", ""),
        phase_sub=rec.get("phase_sub", ""),
        ckpt_every=int(rec.get("ckpt_every") or 0),
        sample_every=int(rec.get("sample_every") or 0),
        dataset=rec.get("dataset") or {},
        model=rec.get("model", ""),
        method=rec.get("method", ""),
        network=rec.get("network", ""),
        created_at=rec.get("created_at"),
        queued_at=rec.get("queued_at"),
        started_at=rec.get("started_at"),
        finished_at=rec.get("finished_at"),
    )


def _wrap(fn):
    """Map manager exceptions to HTTP statuses."""
    try:
        return fn()
    except TrainingError as exc:
        raise HTTPException(404, str(exc))
    except TrainingConflict as exc:
        raise HTTPException(409, str(exc))


# ---- status / gpu -----------------------------------------------------------


def user_store(tr: Trainer = Depends(get_trainer)) -> Path:
    """Where the user's own models and LoRAs are kept — two JSON files in the
    training dir, which is what leaves this subsystem with no database at all.
    """
    return tr.dir


@router.get("/status", response_model=TrainStatusOut)
def status(tr: Trainer = Depends(get_trainer),
           store: Path = Depends(user_store)):
    # `hub.hf` is the single answer to what forces Hugging Face offline.
    # The app's ML router keeps a snapshot of the same thing, cleared by
    # its own endpoint — which unsets the variables, so a live read agrees.
    from media_compost.hub import hf

    # Publish the user's models so every key-based lookup (config validation,
    # the manifest builder, the evaluator) can resolve them for this process.
    user = usermodels.refresh(store)
    models = registry_out() + usermodels.entries_out(user)
    for m in models:
        m.update(_download_state(m["key"]))
    from media_compost.hub import hf

    return TrainStatusOut(
        env_ready=tp.interpreter() is not None,
        running_uid=tr.jobs.running_uid(),
        evaluating_device=tr.jobs.evaluating_device(),
        devices=[TrainDeviceOut(**d) for d in gpu.train_devices()],
        models=models,
        env_offline=hf.offline_var(),
        token_available=bool(hf.token()),
        # Whether attention slicing is usable here at all — it returns
        # NaN on MPS, so the trainer refuses it there and the editor's
        # memory estimate must not count a saving that never happens.
        slices_attention=sys.platform != "darwin",
    )


# In-flight base-model downloads, keyed by registry key. Same machinery the
# Settings model cache uses (a subprocess reporting progress through shared
# memory) — a base model is just a bigger repo.
_dl_lock = threading.Lock()
_downloads: dict[str, ModelDownload] = {}


def _download_state(key: str) -> dict:
    """What the Models tab needs to draw one row's download state."""
    with _dl_lock:
        d = _downloads.get(key)
    if d is None:
        return {}
    st = d.status()
    if st == DL_RUNNING:
        # `queued` is accepted-but-waiting: a slot is capped per process, so a
        # row can be legitimately "downloading" with nothing moving yet, and a
        # spinner at 0% for ten minutes reads as a download that has hung.
        return {"downloading": True, "queued": d.queued,
                "progress": max(0, d.progress),
                "done_bytes": d.done_bytes, "total_bytes": d.total_bytes}
    if st == DL_ERROR:
        return {"download_error": d.error}
    return {}


def _repo_for(key: str, store: Path) -> str:
    """The Hugging Face repo a registry key names, or "" for a local model."""
    usermodels.refresh(store)
    from ..models import model_spec

    spec = model_spec(key)
    if spec is None:
        raise HTTPException(404, f"unknown model {key!r}")
    for m in usermodels.read(store):
        if m.key == key and m.local:
            raise HTTPException(400, "that model is a local path — nothing to download")
    return spec.repo


@router.post("/models/{key:path}/download")
def download_base_model(key: str, store: Path = Depends(user_store)):
    """Fetch a base model's weights into the Hugging Face cache.

    Resumes by construction: `snapshot_download` continues from the partial
    blobs an interrupted attempt left behind, so "download" and "resume" are
    the same call.
    """
    # `hub.hf` is the single answer to what forces Hugging Face offline.
    # The app's ML router keeps a snapshot of the same thing, cleared by
    # its own endpoint — which unsets the variables, so a live read agrees.
    from media_compost.hub import hf
    from media_compost.hub import hf

    repo = _repo_for(key, store)
    if hf.offline_var():
        raise HTTPException(
            400, "downloads are disabled — your environment forces Hugging Face "
                 "offline; enable downloads first")
    token = hf.token()
    with _dl_lock:
        d = _downloads.get(key)
        if d is not None and d.status() == DL_RUNNING:
            return {"ok": True, "status": "downloading"}
        # Only the files the pipeline loads. Fetching the whole repo meant
        # 43 GB for a model whose weights are 4 GB — every variant, the .bin
        # duplicates, and the root single-file checkpoints.
        #
        # `resolve_patterns` has the CHILD work that out. It used to be
        # `pipeline_files.download_patterns(repo, token)` right here, inside
        # this lock — two hub round-trips under the same lock `_download_state`
        # takes for EVERY model row on EVERY status poll. Starting three
        # downloads at once therefore serialized three network calls and
        # parked every polling request behind them; since these endpoints are
        # sync, each blocked request holds a threadpool thread, and the whole
        # server stopped answering. Nothing in here touches the network now.
        d = ModelDownload(repo, token, resolve_patterns=True)
        _downloads[key] = d
    d.start()
    return {"ok": True, "status": "downloading"}


@router.post("/models/{key:path}/cancel-download")
def cancel_base_model_download(key: str):
    """Stop a running download. The bytes already fetched stay in the cache,
    so the row becomes "partial" and the same button resumes it."""
    with _dl_lock:
        d = _downloads.pop(key, None)
    if d is not None:
        d.cancel()
    return {"ok": True}


@router.delete("/models/{key:path}/cache")
def delete_base_model_cache(key: str, store: Path = Depends(user_store)):
    """Remove a base model's weights from the Hugging Face cache — whole or
    half-downloaded. Only the weights: the model stays in the list."""
    from media_compost.hub.cache import delete_repo

    repo = _repo_for(key, store)
    with _dl_lock:
        d = _downloads.pop(key, None)
    if d is not None:
        d.cancel()          # release the files before removing them
    delete_repo(repo)
    return {"ok": True}


@router.get("/models", response_model=TrainModelsOut)
def list_models(store: Path = Depends(user_store)):
    return TrainModelsOut(models=usermodels.entries_out(usermodels.refresh(store)))


@router.post("/models", response_model=TrainModelsOut)
def add_model(body: TrainModelIn, store: Path = Depends(user_store)):
    """Add a base model. The architecture it is based on decides which engine
    trains it, so an unknown base is refused rather than silently accepted."""
    from ..models import model_spec

    repo = body.repo.strip()
    # The name is optional: an unnamed model is listed under what identifies
    # it anyway — the Hugging Face id, or the file/folder name for a local one
    # (its full path is already shown underneath).
    label = body.label.strip()
    if not label:
        label = Path(repo).stem if body.local else repo
    if not repo:
        raise HTTPException(400, "A repo id or local path is required")
    if model_spec(body.base) is None or body.base.startswith(usermodels.KEY_PREFIX):
        raise HTTPException(400, f"Unknown base architecture {body.base!r}")
    if body.local and not Path(repo).exists():
        raise HTTPException(400, f"No such path: {repo}")
    existing = usermodels.read(store)
    if any(m.repo == repo and m.base == body.base for m in existing):
        raise HTTPException(409, "That model is already in the list")
    existing.append(usermodels.UserModel(
        key=usermodels.unique_key(existing, label), label=label,
        base=body.base, repo=repo, local=bool(body.local),
        area=int(body.area or 0),
    ))
    usermodels.write(store, existing)
    return TrainModelsOut(models=usermodels.entries_out(usermodels.refresh(store)))


@router.patch("/models/{key:path}", response_model=TrainModelsOut)
def edit_model(key: str, body: TrainModelIn, store: Path = Depends(user_store)):
    """Change an added model's name, weights, base architecture or size.

    THE KEY NEVER CHANGES, whatever the name becomes: every job that has been
    configured with this model stores `user:<slug>`, and re-deriving the slug
    from a corrected label would strand all of them on a model that no longer
    exists. The key is an identity, the label is what it is called.
    """
    from ..models import model_spec

    existing = usermodels.read(store)
    if not any(m.key == key for m in existing):
        raise HTTPException(404, "No such model")
    repo = body.repo.strip()
    if not repo:
        raise HTTPException(400, "A repo id or local path is required")
    if model_spec(body.base) is None or body.base.startswith(usermodels.KEY_PREFIX):
        raise HTTPException(400, f"Unknown base architecture {body.base!r}")
    if body.local and not Path(repo).exists():
        raise HTTPException(400, f"No such path: {repo}")
    if any(m.key != key and m.repo == repo and m.base == body.base
           for m in existing):
        raise HTTPException(409, "That model is already in the list")
    label = body.label.strip() or (Path(repo).stem if body.local else repo)
    out = [usermodels.UserModel(
               key=key, label=label, base=body.base, repo=repo,
               local=bool(body.local), area=int(body.area or 0))
           if m.key == key else m
           for m in existing]
    usermodels.write(store, out)
    return TrainModelsOut(models=usermodels.entries_out(usermodels.refresh(store)))


@router.get("/user-loras", response_model=TrainModelsOut)
def list_user_loras(store: Path = Depends(user_store)):
    return TrainModelsOut(models=usermodels.loras_out(usermodels.read_loras(store)))


@router.post("/user-loras", response_model=TrainModelsOut)
def add_user_lora(body: TrainModelIn, store: Path = Depends(user_store)):
    """Register a LoRA file that lives outside the app. `base` is the model it
    was trained for — a LoRA only applies to its own architecture."""
    from ..models import model_spec

    path = body.repo.strip()
    if not path:
        raise HTTPException(400, "A path is required")
    if not Path(path).exists():
        raise HTTPException(400, f"No such path: {path}")
    if model_spec(body.base) is None:
        raise HTTPException(400, f"Unknown base model {body.base!r}")
    existing = usermodels.read_loras(store)
    if any(lo.path == path for lo in existing):
        raise HTTPException(409, "That LoRA is already in the list")
    label = body.label.strip() or Path(path).stem
    keys = [usermodels.UserModel(key=lo.key, label=lo.label, base="",
                                 repo=lo.path, local=True) for lo in existing]
    existing.append(usermodels.UserLora(
        key=usermodels.unique_key(keys, label), label=label,
        model=body.base, path=path,
    ))
    usermodels.write_loras(store, existing)
    return TrainModelsOut(models=usermodels.loras_out(existing))


@router.patch("/user-loras/{key:path}", response_model=TrainModelsOut)
def edit_user_lora(key: str, body: TrainModelIn,
                   store: Path = Depends(user_store)):
    """Change a registered LoRA's name, file or the model it was trained for.

    Its key survives a rename for the same reason a model's does: an
    evaluation run names the LoRA by key.
    """
    from ..models import model_spec

    existing = usermodels.read_loras(store)
    if not any(lo.key == key for lo in existing):
        raise HTTPException(404, "No such LoRA")
    path = body.repo.strip()
    if not path:
        raise HTTPException(400, "A path is required")
    if not Path(path).exists():
        raise HTTPException(400, f"No such path: {path}")
    if model_spec(body.base) is None:
        raise HTTPException(400, f"Unknown base model {body.base!r}")
    if any(lo.key != key and lo.path == path for lo in existing):
        raise HTTPException(409, "That LoRA is already in the list")
    label = body.label.strip() or Path(path).stem
    out = [usermodels.UserLora(key=key, label=label, model=body.base,
                               path=path)
           if lo.key == key else lo
           for lo in existing]
    usermodels.write_loras(store, out)
    return TrainModelsOut(models=usermodels.loras_out(out))


@router.delete("/user-loras/{key:path}", response_model=TrainModelsOut)
def delete_user_lora(key: str, store: Path = Depends(user_store)):
    kept = [lo for lo in usermodels.read_loras(store) if lo.key != key]
    usermodels.write_loras(store, kept)
    return TrainModelsOut(models=usermodels.loras_out(kept))


@router.delete("/models/{key:path}", response_model=TrainModelsOut)
def delete_model(key: str, store: Path = Depends(user_store)):
    """Remove a user model. Jobs that already reference it keep their stored
    config — they just can't be re-queued until the model is added back."""
    kept = [m for m in usermodels.read(store) if m.key != key]
    usermodels.write(store, kept)
    return TrainModelsOut(models=usermodels.entries_out(usermodels.refresh(store)))


@router.get("/gpu", response_model=list[SystemDeviceOut])
def gpu_stats(tr: Trainer = Depends(get_trainer)):
    """Live system stats: one entry per GPU, plus CPU, RAM and the disk of
    the volume the library (and its training runs) lives on."""
    return [SystemDeviceOut(**d) for d in gpu.sample(tr.data_dir)]


@router.post("/gpu/recheck", response_model=list[SystemDeviceOut])
def gpu_recheck(tr: Trainer = Depends(get_trainer)):
    """Ask the probes that gave up to try once more, and sample.

    Only `powermetrics` gives up (see `gpu.clear_denied`): its refusal is
    latched so the poll cannot re-ask on its own, and the one thing that
    changes the answer is somebody adding the sudoers rule the hint names.
    This is that somebody saying they have — a restart for a configuration
    change made a moment ago is a strange thing to ask for.
    """
    gpu.clear_denied()
    return [SystemDeviceOut(**d) for d in gpu.sample(tr.data_dir)]


# ---- job CRUD ---------------------------------------------------------------


@router.get("/jobs", response_model=TrainingJobsOut)
def list_jobs(tr: Trainer = Depends(get_trainer)):
    return TrainingJobsOut(
        jobs=[_job_out(r) for r in tr.jobs.list_jobs()],
        queue_active=tr.jobs.queue_active(),
    )


@router.post("/queue/run")
def queue_run(tr: Trainer = Depends(get_trainer)):
    """Start working through the queue (queueing a job never starts it)."""
    tr.jobs.queue_run()
    return {"ok": True}


@router.post("/queue/stop")
def queue_stop(tr: Trainer = Depends(get_trainer)):
    """Stop starting new jobs; running jobs are untouched."""
    tr.jobs.queue_stop()
    return {"ok": True}


@router.post("/degrade/preview")
def degrade_preview(body: DegradePreviewIn,
                    lib=Depends(get_library)):
    """One picture put through a variant, so it can be judged by eye.

    ``end`` picks which END of the variant's ranges to render — "low" is the
    gentlest thing the run can produce and "high" the harshest. Deliberately
    not a random draw from the middle: what a person needs to see before
    committing a run is the two extremes, and a sample from between answers
    neither question, nor the same way twice.

    Downscaled first. A degradation is judged on texture, which survives a
    preview-sized picture, while a full-resolution h265 round-trip per
    keystroke would not survive the user's patience.
    """
    import io

    from PIL import Image

    from .. import degrade as dg

    try:
        item = lib.items[body.item_id]
    except KeyError:
        raise HTTPException(404, "no such item") from None
    path = item.path
    if path is None or not path.is_file():
        raise HTTPException(404, "the item has no stored picture")
    v = body.variant
    drawn = dg.Drawn(
        method=v.method, subsampling=v.subsampling, resample=v.resample,
        codec=v.codec,
        # A HARSHER picture is a LOWER jpeg quality and a LOWER scale, but a
        # HIGHER crf — the codec's number counts the other way round, and
        # reading past that is how a preview shows the opposite of its label.
        passes=v.passes.hi if body.end == "high" else v.passes.lo,
        quality=v.quality.lo if body.end == "high" else v.quality.hi,
        crf=v.crf.hi if body.end == "high" else v.crf.lo,
        scale=v.scale.lo if body.end == "high" else v.scale.hi,
    )
    clean = body.end == "clean"
    try:
        with Image.open(path) as im:
            im.load()
            im = im.convert("RGB")
            if im.width > body.width:
                im.thumbnail((body.width, body.width * 4), Image.LANCZOS)
            # The clean picture takes the same downscale and the same PNG
            # write, and nothing else — so what differs between the three
            # pictures is the degradation and only the degradation.
            out = im if clean else dg.apply(im, drawn)
    except dg.DegradeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(422, "the picture could not be read") from exc
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return Response(content=buf.getvalue(), media_type="image/png",
                    headers={"X-Degrade-Key": "original" if clean
                             else dg.key(drawn)})


@router.post("/queries/preview", response_model=QueriesPreviewOut)
def queries_preview(body: QueriesPreviewIn, lib=Depends(get_library)):
    """What each query in the editor actually contributes to a run.

    It exists for ONE warning: a regularization query whose every picture is
    also matched by a training query contributes nothing, because a training
    query wins (`dataset.regularization_ids`). The run reports that in its log
    — long after somebody has queued it and walked away — and the editor is
    where it can still be fixed.

    The precedence is imported rather than restated, which is the whole point
    of answering this server-side: a warning that could disagree with what the
    run does is worse than no warning.

    The scope is `build_manifest`'s (every kind, hidden items included), or the
    preview would count a different set from the one the job trains on. It
    materializes ids, as the manifest builder does, because a set difference
    needs the sets; that is a real cost on a large library, paid on an editor
    keystroke rather than at job start, and it is why this is one request for
    the whole list rather than one per query.
    """
    from ..dataset import regularization_ids, selection_scope

    queries = body.config.queries
    scope = selection_scope(body.config)
    matched = [sorted(lib.query(q.tree, **scope).ids()) for q in queries]
    reg = regularization_ids(queries, matched)
    out = []
    for q, ms in zip(queries, matched):
        contributes = len(reg.intersection(ms)) if q.regularize else len(ms)
        out.append(QueryPreviewOut(matched=len(ms), contributes=contributes))
    return QueriesPreviewOut(queries=out)


@router.post("/jobs", response_model=TrainingJobDetailOut)
def create_job(body: TrainingJobIn, tr: Trainer = Depends(get_trainer),
               user: str = Depends(get_current_user)):
    uid = tr.jobs.create(body.name, body.config, user)
    return get_job(uid, tr)


@router.get("/jobs/{uid}", response_model=TrainingJobDetailOut)
def get_job(uid: str, tr: Trainer = Depends(get_trainer)):
    rec = _wrap(lambda: tr.jobs.get(uid))
    config = tr.jobs.read_config(uid)
    return TrainingJobDetailOut(**_job_out(rec).model_dump(), config=config)


@router.put("/jobs/{uid}", response_model=TrainingJobDetailOut)
def update_job(uid: str, body: TrainingJobIn,
               tr: Trainer = Depends(get_trainer)):
    _wrap(lambda: tr.jobs.update(uid, body.name, body.config))
    return get_job(uid, tr)


@router.delete("/jobs/{uid}")
def delete_job(uid: str, tr: Trainer = Depends(get_trainer)):
    """Remove the job. `kept` is how many LOCKED weight sets survived it —
    they move into the user's own LoRA list rather than going with the job."""
    kept = _wrap(lambda: tr.jobs.delete(uid))
    return {"ok": True, "kept": int(kept or 0)}


# ---- actions ----------------------------------------------------------------


def _job_local_path(tr: "Trainer", uid: str) -> str:
    """The job's own `local_path`, or "" — read defensively, because a job
    whose config cannot be read is a different failure with its own error."""
    try:
        return str((tr.jobs.read_config(uid) or {}).get("local_path") or "")
    except Exception:
        return ""


def _require_fetchable(key: str, store: Path, local_path: str = "") -> None:
    """Refuse to start a run that would have to download while downloads are off.

    Without this the run starts, the trainer's `from_pretrained` hits offline
    mode inside the subprocess, and the user gets a forty-line stack trace
    ending in "an error occurred while trying to fetch metadata from the Hub"
    — with no hint that their own environment switched downloads off.

    `local_path` is the JOB's own answer to where its weights come from, and
    it has to be asked: a config carrying one loads from that path and
    downloads NOTHING (`dataset.build_manifest` puts it in the manifest's
    `repo` and marks it `local`), so judging it by the model key's hub repo
    refused a run that needed no hub at all — on the queue route as well as
    the start one, which is a job that cannot be moved OR started, with a
    400 nothing in the app was showing.

    The MODEL can be that answer too, and for the same reason: a user model
    added as a path carries `local`, and `repo_state` says "none" for
    anything that is not a hub id — so a custom SDXL checkpoint sitting on
    the disk was refused as one still to be downloaded.
    """
    from media_compost.hub import hf
    from ..models import model_spec, repo_state

    offline = hf.offline_var()
    if not offline:
        return
    if local_path.strip():
        return
    usermodels.refresh(store)
    spec = model_spec(key)
    if spec is None or spec.local:
        return
    if repo_state(spec.repo) == "ready":
        return
    raise HTTPException(
        400, f"{spec.label} still has to be downloaded, but downloads are "
             f"switched off ({offline}) — enable them first")


@router.post("/jobs/{uid}/queue")
def queue_job(uid: str, tr: Trainer = Depends(get_trainer),
              store: Path = Depends(user_store)):
    job = _wrap(lambda: tr.jobs.get(uid))
    _require_fetchable(job.get("model", ""), store,
                       _job_local_path(tr, uid))
    _wrap(lambda: tr.jobs.enqueue(uid))
    return {"ok": True}


@router.post("/jobs/{uid}/start")
def start_job(uid: str, preempt: bool = False, run_queue: bool = False,
              tr: Trainer = Depends(get_trainer),
              store: Path = Depends(user_store)):
    """Run this one job right away.

    Plain, it runs the one job and nothing chains after it — the detail
    pane's Start. `preempt=1&run_queue=1` is the job row's: pause whatever
    holds the device, put this at the front, and leave the queue running so
    the rest follows.
    """
    job = _wrap(lambda: tr.jobs.get(uid))
    _require_fetchable(job.get("model", ""), store,
                       _job_local_path(tr, uid))
    _wrap(lambda: tr.jobs.start_now(uid, preempt=preempt, run_queue=run_queue))
    return {"ok": True}


@router.post("/jobs/{uid}/pause")
def pause_job(uid: str, tr: Trainer = Depends(get_trainer)):
    _wrap(lambda: tr.jobs.pause(uid))
    return {"ok": True}


@router.post("/jobs/{uid}/cancel")
def cancel_job(uid: str, tr: Trainer = Depends(get_trainer)):
    _wrap(lambda: tr.jobs.cancel(uid))
    return {"ok": True}


@router.post("/jobs/{uid}/steps")
def set_steps(uid: str, body: TrainStepsIn,
              tr: Trainer = Depends(get_trainer)):
    """Change total steps — live for a running job (the trainer adopts the new
    target between steps), and on paused/completed jobs to continue training
    past the original end."""
    _wrap(lambda: tr.jobs.set_steps(uid, body.steps))
    return {"ok": True}


@router.post("/jobs/{uid}/duplicate", response_model=TrainingJobDetailOut)
def duplicate_job(uid: str, tr: Trainer = Depends(get_trainer),
                  user: str = Depends(get_current_user)):
    new_uid = _wrap(lambda: tr.jobs.duplicate(uid, user))
    return get_job(new_uid, tr)


# ---- run artifacts (metrics / samples / log) ----------------------------------


def _job_dir(uid: str, tr: Trainer):
    _wrap(lambda: tr.jobs.get(uid))  # 404 on unknown
    return tp.job_dir(tr.dir, uid)


@router.get("/jobs/{uid}/metrics", response_model=TrainMetricsOut)
def metrics(uid: str, after: int = 0, tr: Trainer = Depends(get_trainer)):
    """Loss points with step > ``after``. A full fetch (after=0) is downsampled
    to ~2000 points; incremental fetches return everything new."""
    # Keyed by step, last write wins: a resumed run re-appends the steps
    # between its last checkpoint and the pause point.
    by_step: dict[int, TrainMetricPoint] = {}
    diverged = 0
    try:
        with open(tp.metrics_path(_job_dir(uid, tr)), encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue  # torn tail line of an in-flight append
                step = int(d.get("step") or 0)
                # A record with NO "loss" key is a validation round's scores
                # (`JobIO.append_eval`) — merged onto the step's training
                # point, which is already in `by_step` because the trainer
                # appends the step's own metric before it validates. An
                # explicit `"loss": null` is different: that is a diverged
                # step, and it stays counted as one.
                if "loss" not in d:
                    at = by_step.get(step)
                    if at is not None and step > after:
                        v, s = d.get("val"), d.get("stable")
                        if v is not None:
                            at.val = float(v)
                        if s is not None:
                            at.stable = float(s)
                    continue
                loss = d.get("loss")
                if loss is None:
                    diverged += 1     # a diverged step, or an old run's NaN
                    continue
                loss = float(loss)
                if loss != loss or loss in (float("inf"), float("-inf")):
                    diverged += 1
                    continue
                if step > after:
                    lmin, lmax = d.get("lmin"), d.get("lmax")
                    by_step[step] = TrainMetricPoint(
                        step=step, loss=loss,
                        lr=float(d.get("lr") or 0), t=float(d.get("t") or 0),
                        lmin=float(lmin) if lmin is not None else None,
                        lmax=float(lmax) if lmax is not None else None,
                    )
    except OSError:
        pass
    points = [by_step[s] for s in sorted(by_step)]
    last = points[-1].step if points else after
    if after <= 0 and len(points) > _MAX_METRIC_POINTS:
        stride = len(points) / _MAX_METRIC_POINTS
        sampled = [points[int(i * stride)]
                   for i in range(_MAX_METRIC_POINTS)]
        if sampled[-1].step != points[-1].step:
            sampled.append(points[-1])
        # The validation points survive the stride: they are sparse (one per
        # cadence, against one training point per step), so a plain stride
        # would drop most of the very series the sampling exists to protect.
        have = {p.step for p in sampled}
        sampled.extend(p for p in points
                       if (p.val is not None or p.stable is not None)
                       and p.step not in have)
        sampled.sort(key=lambda p: p.step)
        points = sampled
    return TrainMetricsOut(points=points, last_step=last,
                           diverged=diverged)


@router.get("/jobs/{uid}/visits", response_model=TrainVisitsOut)
def visits(uid: str, step: int = -1, tr: Trainer = Depends(get_trainer)):
    """The images/prompts/crops one optimizer step trained on (the data
    inspector). ``step`` defaults to the latest recorded step; the returned
    ``steps`` list is every step with data, so the UI can page through them."""
    by_step: dict[int, list[dict]] = {}
    path = _job_dir(uid, tr) / "visits.jsonl"
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue  # torn tail line of an in-flight append
                by_step[int(d.get("step") or 0)] = d.get("visits") or []
    except OSError:
        pass
    steps = sorted(by_step)
    if step in by_step:
        want = step
    elif steps and step >= 0:
        # Scrubbing lands on a step that wasn't recorded (metrics are downsampled
        # relative to visits, or vice versa) — snap to the NEAREST one, not the
        # latest, or the graph marker jumps to the end of the run.
        want = min(steps, key=lambda s: abs(s - step))
    else:
        want = steps[-1] if steps else 0
    rows = [TrainVisitOut(**v) for v in by_step.get(want, [])]
    return TrainVisitsOut(step=want, steps=steps, visits=rows)


@router.get("/jobs/{uid}/samples", response_model=TrainSamplesOut)
def samples(uid: str, tr: Trainer = Depends(get_trainer)):
    jd = _job_dir(uid, tr)
    # Prompt entries are {prompt, negative} pairs (plain strings in configs
    # from before per-pair negatives).
    prompts = [
        p if isinstance(p, str) else (p or {}).get("prompt", "")
        for p in (tr.jobs.read_config(uid).get("sampling") or {})
        .get("prompts") or []
    ]
    out: list[TrainSampleOut] = []
    rounds: list[TrainSampleRound] = []
    root = tp.samples_dir(jd)
    clock = _step_clock(jd)
    if root.is_dir():
        for d in sorted(root.iterdir()):
            if not d.is_dir() or not d.name.startswith("step-"):
                continue
            try:
                step = int(d.name.split("-", 1)[1])
            except ValueError:
                continue
            t, secs = _clock_at(clock, step)
            # When the round actually ran beats when the step's metric was
            # written: the two differ by the whole sampling pause, and a step-0
            # baseline has no metric at all. Rounds from before `meta.json`
            # fall back to the directory's own timestamp.
            meta = tp.read_json(d / "meta.json") or {}
            started = meta.get("started")
            if not started:
                try:
                    started = d.stat().st_mtime
                except OSError:
                    started = 0.0
            t = float(started) or t
            done = 0
            for f in sorted(d.iterdir()):
                if not _SAMPLE_NAME.match(f.name):
                    continue
                idx = int(f.name[1:-4])
                done += 1
                out.append(TrainSampleOut(
                    step=step, name=f.name,
                    prompt=prompts[idx] if idx < len(prompts) else "",
                    t=t, train_seconds=round(secs, 1),
                ))
            # The round exists as soon as the trainer opens its folder, which
            # is what lets the app show it (with placeholders) while it is
            # still rendering. `expected` comes from the round itself — the
            # config's prompt list may have been edited since.
            try:
                expected = int(meta.get("expected") or 0)
            except (TypeError, ValueError):
                expected = 0
            rounds.append(TrainSampleRound(
                step=step, t=t, train_seconds=round(secs, 1),
                expected=expected or done, done=done,
            ))
    return TrainSamplesOut(samples=out, rounds=rounds)


@router.post("/queue-order")
def reorder_queue(body: TrainQueueOrderIn, tr: Trainer = Depends(get_trainer)):
    """Reorder the queued jobs (drag-and-drop in the sidebar)."""
    tr.jobs.reorder_queue(body.uids)
    return {"ok": True}


@router.get("/jobs/{uid}/architecture", response_model=TrainArchitectureOut)
def job_architecture(uid: str, tr: Trainer = Depends(get_trainer)):
    """The trained model's top-level blocks, as the trainer read them off the
    loaded weights. Absent until the job has started once — there is no model
    to describe before that, and describing it from the registry would be a
    picture of what we assume rather than of what is being trained."""
    jd = _job_dir(uid, tr)
    data = tp.read_json(jd / "architecture.json") or {}
    return TrainArchitectureOut(blocks=data.get("blocks") or [])


@router.get("/jobs/{uid}/events", response_model=TrainEventsOut)
def job_events(uid: str, tr: Trainer = Depends(get_trainer)):
    """Lifecycle events (started/resumed/paused/completed/failed/canceled)
    for the job's timeline, each with the cumulative training time reached."""
    jd = _job_dir(uid, tr)
    clock = _step_clock(jd)
    out: list[TrainEventOut] = []
    try:
        with open(tp.events_path(jd), encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                    kind = str(d.get("kind") or "")
                    step = int(d.get("step") or 0)
                    t = float(d.get("t") or 0)
                except (TypeError, ValueError):
                    continue
                _, secs = _clock_at(clock, step)
                data = d.get("data") or {}
                changes = [
                    TrainSettingChange(field=str(c.get("field") or ""),
                                       old=str(c.get("old") or ""),
                                       new=str(c.get("new") or ""))
                    for c in (data.get("changes") or [])
                    if isinstance(c, dict)
                ]
                out.append(TrainEventOut(
                    kind=kind, step=step, t=t,
                    train_seconds=round(secs, 1), changes=changes,
                    added=int(data.get("added") or 0),
                    removed=int(data.get("removed") or 0)))
    except OSError:
        pass
    return TrainEventsOut(events=out)



# Grid tiles are ~150 px wide; a sample can be 1024x1024, and a browser decodes
# every one of them at full size (4 MB of bitmap each) for a thumbnail. During
# a run that memory is exactly what the machine has least of, so the timeline
# asks for a downscaled copy and only the lightbox loads the real thing.
_THUMB_WIDTHS = (320, 640)


def _thumb_of(path: Path, width: int) -> Path | None:
    """A cached WebP no wider than `width`, or None if it can't be made."""
    if width not in _THUMB_WIDTHS:
        return None
    out = path.with_name(f".thumb-{width}-{path.stem}.webp")
    try:
        if out.is_file() and out.stat().st_mtime >= path.stat().st_mtime:
            return out
        from PIL import Image

        with Image.open(path) as im:
            im.load()
            if im.width <= width:
                return None            # already small — serve the original
            im = im.convert("RGB")
            im.thumbnail((width, width * 4), Image.LANCZOS)
            tmp = out.with_suffix(".tmp")
            im.save(tmp, "WEBP", quality=88)
            os.replace(tmp, out)
        return out
    except Exception:                  # noqa: BLE001 - a thumbnail is optional
        return None


@router.get("/jobs/{uid}/frames/{rel:path}")
def video_frame(uid: str, rel: str, tr: Trainer = Depends(get_trainer)):
    """One frame this run extracted from a video, by the name its visit
    carries — what the Training-data inspector shows where a stored picture
    would have a thumbnail.

    The name comes out of a file the TRAINER wrote, which is this server's own
    scratch and still not a reason to open whatever it says: the path is
    resolved and required to land inside this job's frames folder, so no
    amount of `..` reaches anything else. The frames are deleted when a job
    is over, so a 404 here is ordinary and the inspector draws its empty box.
    """
    root = (_job_dir(uid, tr) / "frames").resolve()
    try:
        path = (root / rel).resolve()
        path.relative_to(root)
    except (OSError, ValueError):
        raise HTTPException(404, "no such frame") from None
    if not path.is_file():
        raise HTTPException(404, "no such frame")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/jobs/{uid}/samples/{step}/{name}")
def sample_image(uid: str, step: int, name: str, w: int = 0,
                 tr: Trainer = Depends(get_trainer)):
    if not _SAMPLE_NAME.match(name):
        raise HTTPException(404, "no such sample")
    path = tp.samples_dir(_job_dir(uid, tr)) / f"step-{step:06d}" / name
    if not path.is_file():
        raise HTTPException(404, "no such sample")
    thumb = _thumb_of(path, w) if w else None
    if thumb is not None:
        return FileResponse(thumb, media_type="image/webp")
    return FileResponse(path, media_type="image/png")


# Metric gaps longer than this are treated as "not training" (a pause, a
# server restart, a crash) and excluded from the cumulative training time.
_ACTIVE_GAP_SECONDS = 300.0


def _step_clock(jd) -> dict[int, tuple[float, float]]:
    """step -> (wall-clock t, cumulative ACTIVE training seconds), from the
    metrics log. Consecutive-step gaps beyond the threshold don't count."""
    out: dict[int, tuple[float, float]] = {}
    cum = 0.0
    prev_t: float | None = None
    try:
        with open(tp.metrics_path(jd), encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                    step, t = int(d.get("step") or 0), float(d.get("t") or 0)
                except (TypeError, ValueError):
                    continue
                if t <= 0:
                    continue
                if prev_t is not None:
                    dt = t - prev_t
                    if 0 < dt < _ACTIVE_GAP_SECONDS:
                        cum += dt
                prev_t = t
                out[step] = (t, cum)  # resume replays: last write wins
    except OSError:
        pass
    return out


def _clock_at(clock: dict[int, tuple[float, float]], step: int) -> tuple[float, float]:
    """The (t, train_seconds) at the given step, falling back to the nearest
    earlier metric (samples/checkpoints land exactly on metric steps; step-0
    baselines predate the first metric)."""
    if step in clock:
        return clock[step]
    best = None
    for s, val in clock.items():
        if s <= step and (best is None or s > best[0]):
            best = (s, val)
    return best[1] if best else (0.0, 0.0)


def _resume_step(cdir, rec: dict) -> int | None:
    """The step `checkpoints/last` holds, or None when there is none.

    The trainer writes a `step.json` beside it precisely so this stays
    readable here: the step also lives in `trainer_state.pt`, which only the
    training venv can open. A checkpoint from before that (or a torn write)
    falls back to the job's own step count.
    """
    last = cdir / "last"
    if not last.is_dir():
        return None
    data = tp.read_json(last / "step.json") or {}
    try:
        return int(data["step"])
    except (KeyError, TypeError, ValueError):
        step = int(rec.get("step") or 0)
        return step if step > 0 else None


def _dir_size(path) -> int:
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


@router.get("/jobs/{uid}/checkpoints", response_model=TrainCheckpointsOut)
def checkpoints(uid: str, tr: Trainer = Depends(get_trainer)):
    """All cadence snapshots, including ones already pruned by keep-last-N
    (inferred from the checkpoint interval, so the timeline can still mark
    where they were saved)."""
    jd = _job_dir(uid, tr)
    rec = tr.jobs.get(uid)
    config = tr.jobs.read_config(uid)
    on_disk: dict[int, int] = {}
    cdir = tp.checkpoints_dir(jd)
    if cdir.is_dir():
        for d in cdir.iterdir():
            if d.is_dir() and d.name.startswith("step-"):
                try:
                    on_disk[int(d.name.split("-", 1)[1])] = _dir_size(d)
                except ValueError:
                    continue
    steps = set(on_disk)
    # The resume point: what a pause (or the cadence) last wrote to
    # `checkpoints/last`. It is a real, downloadable checkpoint — the one a
    # paused job continues from — reported with `resume: true` so the
    # timeline can offer "Keep as checkpoint" rather than list it as one.
    resume_step = _resume_step(cdir, rec)
    if resume_step is not None:
        steps.add(resume_step)
        on_disk.setdefault(resume_step, _dir_size(cdir / "last"))
    every = int((config.get("hyper") or {}).get("checkpoint_every") or 0)
    if every > 0:
        # Cadence snapshots are written at every interval multiple the run
        # completed before its (current) end — pruned ones included, so the
        # timeline can still mark where they were saved.
        reached = int(rec.get("step") or 0)
        total = int(rec.get("total_steps") or 0)
        steps.update(s for s in range(every, reached + 1, every) if s < total)
    clock = _step_clock(jd)
    out = []
    for s in sorted(steps):
        t, secs = _clock_at(clock, s)
        out.append(TrainCheckpointOut(
            step=s, exists=s in on_disk, size=on_disk.get(s, 0),
            locked=(cdir / f"step-{s:06d}" / ".locked").is_file(),
            resume=(s == resume_step),
            snapshot=(cdir / f"step-{s:06d}").is_dir(),
            t=t, train_seconds=round(secs, 1)))
    return TrainCheckpointsOut(checkpoints=out)


@router.get("/jobs/{uid}/output/download")
def download_output(uid: str, tr: Trainer = Depends(get_trainer)):
    """A finished job's LoRA output as a zip archive.

    The Models tab lists a job's final result beside its step checkpoints —
    it is the same kind of thing, a weight set to start from or take
    elsewhere — so it needs the same download. It has no delete or lock: the
    output belongs to the job, and removing it means removing the job."""
    rec = tr.jobs.get(uid)
    d = _job_dir(uid, tr) / "output"
    if not d.is_dir() or not any(d.iterdir()):
        raise HTTPException(404, "this job has no finished output")
    return _zip_dir(d, f"{rec.get('name') or uid}-final")


@router.get("/jobs/{uid}/checkpoints/{step}/download")
def download_checkpoint(uid: str, step: int,
                        tr: Trainer = Depends(get_trainer)):
    """The snapshot directory as a zip archive."""
    cdir = tp.checkpoints_dir(_job_dir(uid, tr))
    rec = tr.jobs.get(uid)
    d = cdir / f"step-{step:06d}"
    if not d.is_dir() and _resume_step(cdir, rec) == step:
        d = cdir / "last"      # the resume point, downloadable like the rest
    if not d.is_dir():
        raise HTTPException(404, "no such checkpoint")
    return _zip_dir(d, f"{rec.get('name') or uid}-step-{step}")


def _zip_dir(d, name: str):
    """A directory as a temp zip, deleted once the response is sent."""
    import tempfile
    import zipfile

    from starlette.background import BackgroundTask

    name = name.replace("/", "_")
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as zf:
            for f in sorted(d.rglob("*")):
                if f.is_file():
                    zf.write(f, f.relative_to(d))
        tmp.close()
    except BaseException:
        tmp.close()
        os.unlink(tmp.name)
        raise
    return FileResponse(
        tmp.name, media_type="application/zip",
        filename=f"{name}.zip",
        background=BackgroundTask(os.unlink, tmp.name),
    )


@router.delete("/jobs/{uid}/checkpoints/{step}")
def delete_checkpoint(uid: str, step: int,
                      tr: Trainer = Depends(get_trainer)):
    import shutil

    cdir = tp.checkpoints_dir(_job_dir(uid, tr))
    rec = tr.jobs.get(uid)
    # The resume point is never deletable: it is the state "continue this
    # job" reads, and a job whose last checkpoint is gone can only start over.
    if _resume_step(cdir, rec) == step and not (
            cdir / f"step-{step:06d}").is_dir():
        raise HTTPException(
            409, "this is the job's resume point — deleting it would leave "
                 "nothing to continue from")
    d = cdir / f"step-{step:06d}"
    if not d.is_dir():
        raise HTTPException(404, "no such checkpoint")
    if (d / ".locked").is_file():
        raise HTTPException(409, "this checkpoint is locked — unlock it first")
    shutil.rmtree(d, ignore_errors=True)
    return {"ok": True}


@router.post("/jobs/{uid}/checkpoints/{step}/keep")
def keep_checkpoint(uid: str, step: int, tr: Trainer = Depends(get_trainer)):
    """Turn the resume point into a permanent checkpoint.

    The resume point is a moving target — the next pause or cadence write
    replaces it — so "I want to keep this state" means copying it into a
    step snapshot of its own. It is created LOCKED: keeping it is the whole
    point, and an unlocked copy would be a candidate for keep-last-N
    pruning the moment the next snapshot lands.
    """
    import shutil

    cdir = tp.checkpoints_dir(_job_dir(uid, tr))
    rec = tr.jobs.get(uid)
    if _resume_step(cdir, rec) != step:
        raise HTTPException(404, "no resume point at that step")
    dest = cdir / f"step-{step:06d}"
    if dest.is_dir():
        raise HTTPException(409, "there is already a checkpoint at that step")
    tmp = cdir / f".keep-{step:06d}"
    shutil.rmtree(tmp, ignore_errors=True)
    # Copy, then rename: a half-copied directory must never look like a
    # finished snapshot (the trainer prunes and the app lists by name).
    shutil.copytree(cdir / "last", tmp)
    (tmp / ".locked").touch()
    os.replace(tmp, dest)
    return {"ok": True}


@router.post("/jobs/{uid}/checkpoints/{step}/lock")
def lock_checkpoint(uid: str, step: int, body: TrainCheckpointLockIn,
                    tr: Trainer = Depends(get_trainer)):
    """Protect a snapshot: locked checkpoints can't be deleted and the
    trainer's keep-last-N pruning skips them (they don't count against N
    either — a lock means "this one stays", not "this one uses up a slot")."""
    d = tp.checkpoints_dir(_job_dir(uid, tr)) / f"step-{step:06d}"
    if not d.is_dir():
        raise HTTPException(404, "no such checkpoint")
    marker = d / ".locked"
    if body.locked:
        marker.touch()
    else:
        marker.unlink(missing_ok=True)
    return {"ok": True}


@router.post("/jobs/{uid}/output/lock")
def lock_output(uid: str, body: TrainCheckpointLockIn,
                tr: Trainer = Depends(get_trainer)):
    """Protect a job's finished LoRA. Unlike a checkpoint it has no delete
    button of its own — what a lock buys here is surviving the DELETION OF
    THE JOB, which is otherwise the one thing that takes it away."""
    d = tp.output_dir(_job_dir(uid, tr))
    if not d.is_dir() or not any(d.iterdir()):
        raise HTTPException(404, "this job has no finished output")
    marker = tp.lock_marker(d)
    if body.locked:
        marker.touch()
    else:
        marker.unlink(missing_ok=True)
    return {"ok": True}


@router.get("/jobs/{uid}/log")
def job_log(uid: str, tr: Trainer = Depends(get_trainer)):
    path = tp.log_path(_job_dir(uid, tr))
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - _LOG_TAIL_BYTES))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        text = ""
    return {"log": text}


# ---- evaluation (LoRA test generations) ----------------------------------------


@router.get("/loras", response_model=TrainLoraSourcesOut)
def lora_sources(tr: Trainer = Depends(get_trainer)):
    """LoRA weight sets a NEW job can start from (config.init_lora): every
    finished job's output and its surviving step checkpoints, each with the
    on-disk path the trainer loads."""
    out: list[TrainLoraSourceOut] = []
    for lo in tr.evaluation.available_loras():
        if not lo.get("job_uid"):
            continue  # a hand-added LoRA: no job, no checkpoints, no lock
        try:
            path = tr.evaluation.lora_path(lo["job_uid"], lo["model"],
                                            lo["step"])
        except (TrainingError, TrainingConflict):
            continue
        jd = tp.job_dir(tr.dir, lo["job_uid"])
        # A job's finished OUTPUT locks too. It used to be the one weight set
        # on this page with no lock — the very one people keep, and the only
        # one deleting the job took with it whatever they had said.
        locked = tp.is_locked(
            tp.checkpoints_dir(jd) / f"step-{lo['step']:06d}"
            if lo["step"] is not None else tp.output_dir(jd))
        out.append(TrainLoraSourceOut(
            job_uid=lo["job_uid"], name=lo["name"], model=lo["model"],
            step=lo["step"], final_step=lo.get("final_step") or 0, path=path,
            locked=locked,
        ))
    return TrainLoraSourcesOut(loras=out)


@router.get("/eval/loras", response_model=EvalLorasOut)
def eval_loras(tr: Trainer = Depends(get_trainer)):
    """Completed LoRA jobs whose weights can be stacked in the Evaluate tab."""
    return EvalLorasOut(loras=[EvalLoraOut(**lo)
                               for lo in tr.evaluation.available_loras()])


@router.get("/eval/finetunes", response_model=EvalFinetunesOut)
def eval_finetunes(tr: Trainer = Depends(get_trainer)):
    """Full finetunes whose weights can stand in for a base model's in the
    Evaluate tab — a finished job's output and its surviving checkpoints.

    A finetune is not an adapter, so it is its own list and its own row: it
    replaces the backbone rather than stacking on it, and there is exactly
    one of it.
    """
    return EvalFinetunesOut(finetunes=[EvalFinetuneOut(**f)
                                       for f in tr.evaluation.available_finetunes()])


@router.get("/eval/runs", response_model=EvalRunsOut)
def eval_runs(tr: Trainer = Depends(get_trainer)):
    return EvalRunsOut(runs=[EvalRunOut(**r)
                             for r in tr.evaluation.list_runs()])


@router.post("/eval/runs", response_model=EvalRunOut)
def eval_generate(body: EvalRunIn, tr: Trainer = Depends(get_trainer),
                  store: Path = Depends(user_store),
                  user: str = Depends(get_current_user)):
    _require_fetchable(body.model, store)
    uid = _wrap(lambda: tr.evaluation.generate(
        model=body.model,
        finetune=body.finetune.model_dump() if body.finetune else None,
        loras=[lo.model_dump() for lo in body.loras],
        prompt=body.prompt,
        negative=body.negative,
        width=body.width,
        height=body.height,
        seed=body.seed,
        steps=body.steps,
        cfg_scale=body.cfg,
        count=body.count,
        batch=body.batch,
        username=user,
    ))
    return EvalRunOut(**tr.evaluation.get(uid))


@router.get("/eval/runs/{uid}", response_model=EvalRunOut)
def eval_run(uid: str, tr: Trainer = Depends(get_trainer)):
    return EvalRunOut(**_wrap(lambda: tr.evaluation.get(uid)))


@router.post("/eval/runs/{uid}/cancel")
def eval_cancel(uid: str, tr: Trainer = Depends(get_trainer)):
    _wrap(lambda: tr.evaluation.cancel(uid))
    return {"ok": True}


@router.delete("/eval/runs/{uid}")
def eval_delete(uid: str, tr: Trainer = Depends(get_trainer)):
    _wrap(lambda: tr.evaluation.delete(uid))
    return {"ok": True}


@router.delete("/eval/runs/{uid}/images/{name}")
def eval_delete_image(uid: str, name: str, tr: Trainer = Depends(get_trainer)):
    if not _SAMPLE_NAME.match(name):
        raise HTTPException(404, "no such image")
    _wrap(lambda: tr.evaluation.delete_image(uid, name))
    return {"ok": True}


@router.get("/eval/runs/{uid}/images/{name}")
def eval_image(uid: str, name: str, w: int = 0,
               tr: Trainer = Depends(get_trainer)):
    if not _SAMPLE_NAME.match(name):
        raise HTTPException(404, "no such image")
    _wrap(lambda: tr.evaluation.get(uid))
    path = tr.dir / "_eval" / uid / "images" / name
    if not path.is_file():
        raise HTTPException(404, "no such image")
    thumb = _thumb_of(path, w) if w else None
    if thumb is not None:
        return FileResponse(thumb, media_type="image/webp")
    return FileResponse(path, media_type="image/png")


# ---- training-env setup -------------------------------------------------------

_setup_lock = threading.Lock()
_setup: SetupRun | None = None


@router.post("/setup")
def run_setup():
    """Create ``.venv-training`` via ``-m media_compost.hub.setup_env`` —
    a module rather than a checkout file, so a wheel install can run it too.
    On success the server restarts itself; the client polls /api/health and
    reloads (same flow as the ML plugin setup).

    Through ``{python}`` rather than ``bash``, for the reason
    ``framework.setup_commands`` gives: the runner's shell is ``cmd.exe`` on
    Windows and need not have a bash at all."""
    global _setup
    with _setup_lock:
        if _setup is not None and _setup.running:
            raise HTTPException(409, "setup already running")
        _setup = SetupRun("training",
                          ["{python} -m media_compost.hub.setup_env training"],
                          str(tp.REPO))
    return {"ok": True}


@router.get("/setup")
def setup_status():
    with _setup_lock:
        run = _setup
    if run is None:
        return {"running": False, "ok": False, "error": "", "log": ""}
    return {"running": run.running, "ok": run.ok, "error": run.error,
            "log": run.log}

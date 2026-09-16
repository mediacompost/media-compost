"""FastAPI application: JSON API under /api plus the built SPA (if present)."""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import func, select
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers, MutableHeaders

from media_compost import __version__, instance
from ..config import UiConfig
from media_compost.db import SCHEMA_VERSION, Database
from media_compost.ops.errors import OpError
from . import build as build_info
from .auth import resolve_username
from .deps import Library, get_current_user, get_library
from .routers import (
    artifacts,
    captions,
    editor,
    estimate,
    events,
    files,
    groups,
    history,
    imports,
    items,
    metadata,
    ml,
    ocr,
    places,
    query,
    rankings,
    relationships,
    sequences,
    settings,
    faces,
    stats,
    subjects,
    tags,
    taggrid,
    tagsets,
    tagsort,
    video,
)

# The DISTRIBUTION's version, read rather than typed — this used to be a
# literal and sat at 0.1.0 through every release of the package, which is the
# fate of any number a second file has to remember to bump. It is still NOT
# what says which build a browser tab is running: see `build.py`.
app = FastAPI(title="Media Compost", version=__version__)

# Dev convenience: the Vite dev server (5173) calls the API cross-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
    # The build header travels BOTH ways, and a cross-origin reader cannot see
    # a response header unless it is exposed — without this the dev-server
    # frontend could send its build but never read the server's.
    expose_headers=[build_info.HEADER],
)

for r in (groups, items, files, artifacts, tags, captions, imports, editor,
          stats, sequences, relationships, video, history, ml, settings,
          metadata, subjects, places, events, faces, ocr, query, rankings,
          estimate, taggrid, tagsort, tagsets):
    app.include_router(r.router)


@app.exception_handler(OpError)
def _op_error(request, exc: OpError) -> JSONResponse:
    """Turn a service-layer refusal back into the HTTP answer it used to be.

    The ops layer raises :class:`~media_compost.ops.errors.OpError` so the
    logic is callable from a script; this is the one place that knows those
    refusals have status codes. The body is `{"detail": …}` and the status is
    `exc.status`, which is byte-for-byte what `HTTPException` produced when the
    same check lived inline in the router — so no client changes, and the
    response snapshots in `tests/test_ops_errors.py` hold across the whole
    extraction.

    `detail_key`/`detail_vars` ride BESIDE it, additively: the unfilled
    template and its slot values, which is what lets the UI show the refusal
    in its own language (look the template up, fill the same slots) while
    `detail` stays the interpolated English every existing client and test
    reads. Omitted entirely for the plain case where the message IS the key
    and there is nothing to fill — most refusals — since the frontend falls
    back to looking `detail` itself up.
    """
    body: dict = {"detail": exc.message}
    if exc.vars:
        body["detail_key"] = exc.key
        body["detail_vars"] = {k: str(v) for k, v in exc.vars.items()}
    return JSONResponse(body, status_code=exc.status)


def _mount_training() -> bool:
    """Mount the trainer's routes, if this install has a trainer.

    One of the app's TWO guarded imports of `media_compost.train` — this one
    mounts the web half; `deps.py`'s `Library.trainer` constructs the
    `Trainer` itself. Two conditions, and
    they are different questions: the package has to be importable AND its
    `[train]` requirements met — everything ships in one wheel, so the
    import alone is always true and would gate nothing. `enable_training=0`
    is the explicit off switch on top.

    Mounted or absent, rather than mounted-and-refused. The middleware this
    replaced included the router unconditionally and 404'd its paths, to keep
    the OpenAPI surface one shape; with the routes in a package that may not
    be installed, "one shape" is no longer a promise that can be kept, and an
    endpoint that exists to say no is worse than one that is not there.
    """
    from .deps import training_offered

    if not UiConfig().enable_training or not training_offered():
        return False
    from media_compost.train.web import deps as train_deps
    from media_compost.train.web import router as train_router

    # The trainer DECLARES what it needs from a host; this is the host
    # answering. Not through `dependency_overrides`: that map is global and
    # this app's own tests clear it in teardown, so an override installed here
    # at import would survive only until the first tidy-up — after which the
    # training routes would quietly build a second `Trainer` over the same
    # directory. Two schedulers on one queue is exactly the incident
    # `instance.py` exists because of.
    train_deps.use(
        trainer=lambda: _resolve_library().trainer,
        user=lambda request: resolve_username(request, UiConfig()),
    )
    app.include_router(train_router)
    return True


def _resolve_library() -> Library:
    """The library, the way the DEPENDENCY resolves it — override included.

    Calling `get_library()` straight would read the process singleton and
    ignore the one a test (or any other injector) put in place, which is the
    same trap the training middleware documented before it.
    """
    return app.dependency_overrides.get(get_library, get_library)()


TRAINING = _mount_training()


@app.on_event("startup")
def _one_server_per_library() -> None:
    """Refuse to start against a library another server already serves.

    Two servers on one library double-start training jobs and cross-write
    their records (each process has its own schedulers — see instance.py).
    Tests inject their own Library through ``dependency_overrides`` before
    the client starts, which is also the honest signal to stand down: they
    are not a second server on somebody's library.
    """
    if get_library in app.dependency_overrides:
        return
    instance.acquire_server_lock(UiConfig().data_dir)
    # And the TRAINING scheduler's lease, when this deployment offers it:
    # holding it from startup (rather than when the Trainer is first built)
    # is what stops `media-compost-train run` starting a second scheduler
    # mid-session. Idempotent, so the lazily-built Trainer re-leases as a
    # no-op. When training is off or not installed, the lease stays free for
    # the trainer's own CLI to take beside this very server.
    if TRAINING:
        try:
            instance.scheduler_lease(UiConfig().data_dir,
                                     instance.TRAINING_LOCK_NAME)
        except instance.LockBusy as exc:
            raise instance.AnotherServerRunning(str(exc), exc.holder) from None
    # And that this build can read it at all. Opening the database here means
    # a version mismatch stops the server from starting, rather than 500ing
    # the first request that happens to need the library.
    Database(UiConfig())


@app.on_event("shutdown")
def _let_go_of_the_library() -> None:
    # Resolved the way the dependency is (override included), like the
    # middleware above.
    try:
        resolve = app.dependency_overrides.get(get_library, get_library)
        db = resolve().db
        # A poke made just before shutdown would otherwise die with the
        # sweeper's daemon thread mid-debounce; membership is derived, so
        # this is politeness rather than correctness — the next sweep after
        # reopen would catch it too.
        if db._smart_sweeper is not None:
            db.smart_sweeper.flush()
    except Exception:  # noqa: BLE001 - shutdown must not fail on derived data
        pass
    instance.release_server_lock()


@app.get("/api/health")
def health(lib: Library = Depends(get_library)):
    """Up, and what this deployment offers.

    `training` is a launch-time fact rather than a setting — a machine that
    cannot finish a run says so once, and the UI drops the three tabs that
    would otherwise promise work it cannot do. The training ROUTES are refused
    too (below): hiding a tab is not the same as turning something off.

    `schema_version` costs one field and makes "which format is this library"
    answerable without a shell. By the time anything can call this the server
    has opened the library, so it is always the current number — a library
    that needed upgrading has been upgraded, and one that could not be read
    stopped the process.
    """
    return {
        "ok": True,
        "training": TRAINING,
        "schema_version": SCHEMA_VERSION,
    }


@app.get("/api/build")
def build_state():
    """Which build this process serves, which one is on disk, and what to do.

    The banner asks this ONCE, when it has already learned from a response
    header that the two disagree. The question it answers is the one the
    banner could not answer before: is a RELOAD enough?

    * The page is old and the process is current — an ordinary rebuild while
      the tab sat there. Reloading fixes it.
    * The FILES are newer than the process — `pip install -U`, a rebuild, a
      swapped volume. The tab reloads into the new bundle and then talks to a
      server still running the old code, so reloading alone fixes nothing and
      the banner has been telling people to do the one thing that cannot
      work. `restart_required` says so, and `/api/restart` is the way out.

    `busy` is what a restart would interrupt. Training is deliberately NOT in
    it: a run is its own process and `TrainingManager._recover` adopts it
    again on the way back up.
    """
    return {
        "build": build_info.build_id(_FRONTEND),
        "disk": build_info.disk_build_id(_FRONTEND),
        "restart_required": build_info.restart_required(_FRONTEND),
        "busy": _restart_would_interrupt(),
    }


def _restart_would_interrupt() -> dict[str, int]:
    """What is in flight that a re-exec would take with it.

    Best effort by construction — it is used to WARN, never to decide — so a
    failure to count answers zero rather than blocking the way out of a stale
    page.
    """
    jobs = 0
    imports = 0
    try:
        from .routers import imports as imports_router
        from media_compost.db import Job
        # Through the dependency, override included — `get_library()` straight
        # reads the process singleton and ignores what a test injected.
        lib = _resolve_library()
        with lib.db.session() as s:
            jobs = int(s.execute(
                select(func.count()).select_from(Job)
                .where(Job.status.in_(("queued", "running")))).scalar() or 0)
        imports = sum(1 for j in imports_router._JOBS.values()
                      if j.get("status") == "running")
    except Exception:  # noqa: BLE001 - a count must never stand in the way
        pass
    return {"jobs": jobs, "imports": imports}


@app.post("/api/restart")
def restart(force: bool = False):
    """Re-exec this server so it runs the code that is now on disk.

    Narrow on purpose. It refuses unless the bundle on disk has actually moved
    on from this process, so it is not a "bounce my server" button somebody
    can lean on — it exists to finish an update the app has already detected.
    A second refusal covers work in flight (`force` overrides), because a
    re-exec takes running jobs and imports with it.

    The restart happens on a thread AFTER the reply, which is the setup
    runner's own shape (`hub/setup.py`): the client needs the answer in order
    to know to start polling `/api/health`.
    """
    if not build_info.restart_required(_FRONTEND):
        raise HTTPException(
            status_code=409,
            detail="This server is already running the version on disk.")
    busy = _restart_would_interrupt()
    if not force and (busy["jobs"] or busy["imports"]):
        raise HTTPException(status_code=409, detail={
            "message": "Work is still running; restarting would stop it.",
            "busy": busy,
        })
    # Imported here rather than at module scope: the hub package sets the
    # Hugging Face environment on import, and a server that never restarts
    # should not pay for it.
    from media_compost.hub.setup import restart_process
    threading.Thread(target=restart_process, daemon=True).start()
    return {"restarting": True}


@app.get("/api/whoami")
def whoami(user: str = Depends(get_current_user),
           lib: Library = Depends(get_library)):
    """The caller's resolved username ("" = anonymous) and whether the server
    requires authentication. Lets the UI show who is acting."""
    return {"username": user, "require_auth": lib.config.require_auth}


class _CommitBeforeResponding:
    """Commit the request's session while the caller is still waiting.

    THE COMMIT USED TO HAPPEN AFTER THE RESPONSE WAS SENT, and that is not a
    subtlety about durability — it is a wrong answer to the next question.
    `get_session` is a dependency with ``yield``, and FastAPI exits those only
    once the response has gone out (the same fact `files.release` exists for),
    so a write endpoint replied ``200`` with the new row's id while its
    transaction was still open. A client reading straight back — which is what
    every mutation-then-refetch does — could beat it.

    Measured on loopback against the real server before this existed: twelve
    ``POST /api/groups`` calls, each followed at once by ``GET /api/groups``,
    and FIVE did not list the group whose id the POST had just returned;
    create-then-delete answered ``404 group not found`` for its own new group
    in about a third of runs. Sleeping 50 ms between the two made both
    disappear, which is what says it is this and not the database — a second
    session on a second connection sees a committed row every time (0 in 40).

    Only on the way OUT, and only when the response is not an error: a
    handler that raised has already been rolled back by the dependency, and
    an `OpError` mapped to 4xx by the handler above must not commit whatever
    it managed to write first. A session `files.release` already handed back
    is left alone — those handlers are read-only by construction, and taking
    a pool connection again just to commit nothing is the cost that helper
    exists to avoid.

    THE COMMIT GOES TO THE THREADPOOL, never straight onto the event loop.
    A commit is a blocking SQLite write, and under contention it waits up to
    ``busy_timeout`` — 30 seconds — which, run here, is the WHOLE SERVER
    holding its breath: this coroutine runs on the loop, so every other
    request (``/api/health`` included) queues behind it. Worse, the write
    that holds the lock cannot finish either, because ITS commit needs the
    same blocked loop — a mutual wait only the timeout breaks. Found as "a
    big tag CSV import freezes the server, and reloading loads nothing":
    four concurrent writers kept the loop almost permanently inside a
    contended commit. Measured before/after on that import: the server went
    from 30-second ``/api/health`` timeouts at 0% CPU to answering in
    milliseconds throughout.

    PURE ASGI, NOT ``@app.middleware("http")``, AND THAT IS LOAD-BEARING FOR
    SOMETHING ELSE ENTIRELY. The decorator wraps the app in Starlette's
    `BaseHTTPMiddleware`, which proxies the request's receive channel through
    a stream of its own — and a proxied channel never delivers
    ``http.disconnect`` downstream, so no endpoint below one can tell that its
    caller has hung up. ONE such middleware anywhere in the stack is enough to
    blind the whole application. `routers/items.query_items` needs that signal
    (a grid refetch aborts its own in-flight pages several times over, and the
    server used to run every abandoned one to completion — see the gate's own
    note), which is why both of this app's middlewares are written this way.
    Measured with a probe that closed the socket mid-request: under the
    decorator the endpoint ran to completion every time; as pure ASGI it saw
    the disconnect within ~250 ms.

    The commit happens on ``http.response.start`` — before the status line
    goes out, which is the "while the caller is still waiting" above.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        state = scope.setdefault("state", {})

        async def commit_then_send(message) -> None:
            if message["type"] == "http.response.start":
                s = state.get("mc_session")
                if s is not None and message["status"] < 400 \
                        and not s.info.get("released"):
                    await run_in_threadpool(s.commit)
            await send(message)

        await self.app(scope, receive, commit_then_send)


# Serve the built frontend if it has been bundled next to the package.
_FRONTEND = Path(__file__).resolve().parent.parent / "_web_dist"


class _FrontendBuild:
    """Tell every API caller which build this is, and refuse a WRITE from a
    frontend running a different one.

    A tab left open across an update is running JavaScript this process no
    longer serves. Its reads are mostly harmless and its writes are not: a
    field that still exists but has changed meaning is accepted, validated and
    stored as something else, which is the one failure `extra="forbid"` cannot
    see. So a mismatched build is refused on anything that WRITES and allowed
    on anything that reads — the stale tab goes on rendering, rather than
    turning into a wall of errors, and the banner it shows has something to be
    a banner over. Note that is not the same as "allowed on GET": the search
    endpoint is a POST, and blocking it left the grid stuck on "Loading…".

    The header rides on EVERY api response, including this refusal, so the
    frontend learns of the mismatch from the first reply it gets rather than
    from the first write it attempts. That is the half that does the work; the
    refusal is the backstop for the write that races it.

    Absent header = allowed, always. The CLI, a script, `curl` and a dev-server
    frontend have no bundle to be stale, and the Python API never comes through
    here at all.

    PURE ASGI for the reason `_CommitBeforeResponding` states at length: one
    `BaseHTTPMiddleware` anywhere in the stack stops every endpoint below it
    from ever seeing that its caller has hung up.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        ours = build_info.build_id(_FRONTEND)
        path = scope["path"]
        if not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return
        if (path not in build_info.STALE_ALLOWED
                and build_info.writes(scope["method"], path)
                and build_info.is_stale(
                    Headers(scope=scope).get(build_info.HEADER, ""), ours)):
            refusal = JSONResponse(
                {"detail": "This page is running an older version of Media "
                           "Compost than the server. Reload to continue."},
                status_code=409,
                headers={build_info.HEADER: ours},
            )
            await refusal(scope, receive, send)
            return
        if not ours:
            await self.app(scope, receive, send)
            return

        async def stamp_then_send(message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[build_info.HEADER] = ours
            await send(message)

        await self.app(scope, receive, stamp_then_send)


# The two middlewares are added here rather than by decorator, and the ORDER is
# the one the decorators gave them: `add_middleware` inserts at the front, so
# the last one added is the outermost. `_FrontendBuild` refuses a stale write
# before anything else runs; `_CommitBeforeResponding` sits inside it.
app.add_middleware(_CommitBeforeResponding)
app.add_middleware(_FrontendBuild)
if _FRONTEND.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=_FRONTEND / "assets"),
        name="assets",
    )

    # index.html must NEVER be cached: its whole job is to name the current
    # hashed bundle, and a browser that keeps its own copy goes on loading
    # yesterday's JavaScript after a rebuild — a change that "didn't take"
    # with no sign of why. The bundles themselves are content-hashed, so they
    # can be cached freely.
    _NO_STORE = {"Cache-Control": "no-cache, no-store, must-revalidate"}

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        # An unmatched /api/ path is a MISSING ENDPOINT, not a deep link.
        # Falling through to the SPA answers a JSON client 200 with a page of
        # HTML, which is the least debuggable possible reply — and it is what
        # `/api/train/*` started doing the moment those routes became a
        # package that might not be installed, where before a middleware
        # refused them explicitly.
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "not found"}, status_code=404)
        # THE PATH IS UNTRUSTED AND IS NOT A SUFFIX. `_FRONTEND / full_path`
        # reads like "a file inside the bundle" and is not: pathlib joins
        # `..` segments happily, and an ABSOLUTE right operand replaces the
        # left entirely — so `GET /../../../../etc/passwd` served /etc/passwd
        # and `GET //etc/passwd` served it in one hop, to anyone who could
        # reach the port. The percent-encoded spellings arrive decoded, so
        # refusing a literal ".." in the URL is not the guard either; the
        # only honest test is where the path actually LANDS. Resolve it and
        # require the answer to still be inside the bundle — which also
        # covers the Windows spellings (`..\..\x`, `C:/Windows/...`) and a
        # symlink out of `_web_dist`, none of which a textual check sees.
        if full_path:
            candidate = (_FRONTEND / full_path).resolve()
            if candidate.is_relative_to(_FRONTEND) and candidate.is_file():
                headers = _NO_STORE if candidate.name == "index.html" else None
                return FileResponse(candidate, headers=headers)
        return FileResponse(_FRONTEND / "index.html", headers=_NO_STORE)

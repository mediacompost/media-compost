"""Out-of-process model host.

Runs plugin models in a worker subprocess and keeps a **single** loaded model
resident, mirroring the old in-process ``_ModelCache`` at process level:

* consecutive jobs on the **same** model reuse the warm worker (no reload);
* a job for a **different** model stops the current worker and spawns a new one
  (in that plugin's environment);
* after ``ttl`` seconds idle the worker is stopped (`DEFAULT_TTL`).

The worker's stdout/stderr are echoed to the host's live ``sys.stdout`` so the
job-log capture (``jobs._CaptureLog``, active during ``run_one``) records the
model's output just as it did when inference ran in-process.
"""

from __future__ import annotations

import json
import os
import queue
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

from media_compost.hub import hf

from . import framework as fw
from . import registry

_WINDOWS = sys.platform == "win32"

#: How long to wait for a freshly spawned worker to connect back (Windows).
#: Generous — the child is a cold Python interpreter, sometimes in a dedicated
#: venv on a spinning disk — but bounded, so a worker that dies before
#: connecting fails the load instead of hanging the job queue forever.
_CONNECT_TIMEOUT = 60.0

#: How long an idle worker keeps its model loaded, in seconds. MEASURED
#: (M4 Max, warm disk): bringing a model up through the host costs 1-7 s
#: (spawn, imports, weights: the face detector 1 s, the taggers 1-2, the
#: depth and embed models 5-7, Florence 5, Magi 4-5), and on CUDA a
#: compiled upscaler loses its 25 s warm-up with the worker. At the old
#: 60 s a person working at a human pace, one action a couple of minutes
#: apart, paid that on every click. Ten minutes keeps the model through a
#: session of work; an idle worker's memory is given back to a training
#: run on demand (`ModelHost.release_idle`). `MEDIA_COMPOST_MODEL_TTL`
#: overrides, in seconds.
DEFAULT_TTL = 600.0


def default_ttl() -> float:
    raw = (os.environ.get("MEDIA_COMPOST_MODEL_TTL") or "").strip()
    if raw:
        try:
            return max(1.0, float(raw))
        except ValueError:
            pass
    return DEFAULT_TTL


def _spawn_posix(interp: str, env: dict):
    """Hand the worker one end of a socketpair through fd inheritance.

    Nothing is bound and nothing is listening, so the channel is reachable
    only by the two processes holding it — which is why this stays the POSIX
    path rather than everything moving to the loopback one below.
    """
    parent, child = socket.socketpair()
    env = dict(env)
    env["MC_WORKER_FD"] = str(child.fileno())
    try:
        proc = subprocess.Popen(
            [interp, fw.worker_path()], env=env, pass_fds=(child.fileno(),),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
    except Exception:
        parent.close()
        child.close()
        raise
    child.close()  # the child holds its inherited copy
    return proc, parent


def _spawn_windows(interp: str, env: dict):
    """Same channel, but the worker CONNECTS BACK over loopback.

    ``pass_fds`` is not merely unsupported on Windows, it is refused outright
    (``subprocess`` asserts on it), so the POSIX path does not degrade there —
    it raises before the worker is ever launched, and *every* AI action fails
    with "pass_fds not supported on Windows". Windows has no fd inheritance
    for sockets in the POSIX sense; the sanctioned alternative,
    ``socket.share()``, needs the child's pid before the child exists.

    So the host listens on an ephemeral 127.0.0.1 port and the worker dials
    in. Two things keep that honest:

    * the listener is bound to loopback only and is CLOSED after one accept,
      so the port exists for the length of one spawn;
    * the worker must present a single-use token before the socket is used
      for anything. A local process that beat the worker to the accept
      supplies no valid token and is dropped — it can waste a spawn, which
      surfaces as a failed model load, but it cannot talk to the host.
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(_CONNECT_TIMEOUT)
        token = secrets.token_hex(16)
        env = dict(env)
        env["MC_WORKER_PORT"] = str(listener.getsockname()[1])
        env["MC_WORKER_TOKEN"] = token
        proc = subprocess.Popen(
            [interp, fw.worker_path()], env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        try:
            parent = _accept_worker(listener, proc, token)
        except Exception:
            proc.kill()
            raise
        return proc, parent
    finally:
        listener.close()


def _accept_worker(listener, proc, token: str):
    """Accept the one connection whose first line is ``token``."""
    deadline = time.monotonic() + _CONNECT_TIMEOUT
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("model worker did not connect back in time")
        listener.settimeout(remaining)
        try:
            conn, _ = listener.accept()
        except socket.timeout:
            if proc.poll() is not None:
                raise RuntimeError(
                    f"model worker exited before connecting "
                    f"(exit {proc.returncode})") from None
            raise RuntimeError("model worker did not connect back in time") \
                from None
        # Read the greeting byte-at-a-time: anything buffered past the newline
        # would be protocol traffic, and a makefile would swallow it.
        conn.settimeout(_CONNECT_TIMEOUT)
        got = b""
        try:
            while not got.endswith(b"\n") and len(got) < 128:
                chunk = conn.recv(1)
                if not chunk:
                    break
                got += chunk
        except OSError:
            got = b""
        if secrets.compare_digest(got.decode("utf-8", "replace").strip(), token):
            conn.settimeout(None)
            return conn
        conn.close()  # not our worker — keep waiting for the real one


def _failure(resp: dict) -> str:
    """The worker's error as the sentence the job row should show. The
    worker sends the traceback's last 1 500 characters, and the job message
    keeps 300 of whatever it is handed — which for a deep stack was a row
    of carets (`^^`) and nothing else. The whole text goes to the job LOG
    (live stdout, captured there); the exception carries the traceback's
    last line, the one that names the error."""
    text = str(resp.get("error") or "model run failed")
    print(text, flush=True)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # Skip caret lines and the frame lines a traceback ends on.
    for ln in reversed(lines):
        if ln and not set(ln) <= {"^", "~", " "} and not ln.startswith("File "):
            return ln[:300]
    return (lines[-1] if lines else text)[:300]


class _Worker:
    """A live worker subprocess loaded with one model."""

    def __init__(self, proc, sock, load_key, tmpdir):
        self.proc = proc
        self.key = load_key
        self._sock = sock
        self._tmpdir = tmpdir
        self._n = 0
        self._rf = sock.makefile("r", encoding="utf-8", newline="\n")
        self._wf = sock.makefile("w", encoding="utf-8", newline="\n")
        # Pump the child's merged stdout/stderr to our live stdout so the job-log
        # capture picks it up. Daemon thread; ends when the pipe closes.
        self._log = threading.Thread(target=self._pump_log, daemon=True)
        self._log.start()
        # THE WORKER'S ANSWERS ARE DRAINED ON A THREAD OF THEIR OWN, so the
        # worker's write never waits for this side to read. The batch loop
        # writes its next request BEFORE reading the last answer, and a
        # socket is two buffers: with the worker blocked writing a 256 KB
        # answer and the host blocked writing a 60 KB request, neither reads
        # and both wait forever. Linux's Unix-socket buffers (~200 KB) hid
        # it; macOS's are 8 KB and it deadlocked on the second chunk.
        self._answers: queue.SimpleQueue = queue.SimpleQueue()
        self._reader = threading.Thread(target=self._pump_answers, daemon=True)
        self._reader.start()

    def _pump_log(self) -> None:
        try:
            for line in self.proc.stdout:  # text mode
                sys.stdout.write(line)
        except Exception:  # noqa: BLE001 - best effort logging
            pass

    def _pump_answers(self) -> None:
        try:
            for line in self._rf:
                self._answers.put(line)
        except Exception:  # noqa: BLE001 - the socket closed under us
            pass
        self._answers.put(None)   # EOF: the worker is gone

    def _send(self, obj) -> None:
        self._wf.write(json.dumps(obj) + "\n")
        self._wf.flush()

    def _recv(self) -> dict:
        line = self._answers.get()
        if line is None:
            self._answers.put(None)   # every later reader hears it too
            raise RuntimeError("model worker exited unexpectedly")
        return json.loads(line)

    def _rpc(self, obj) -> dict:
        self._send(obj)
        return self._recv()

    def send_paths(self, task: str, model_id: str, paths, max_dim: int,
                   prefetch, options: dict | None = None,
                   images: bool = False) -> None:
        """Write one `run_paths` request and return at once — the answer is
        read by `recv_batch`, in request order (the socket is a queue).
        ``images``: the plugin answers with PICTURES (the per-item kinds —
        a removal, an upscale, a depth map), so each slot is given a file
        in this worker's scratch directory to write its result to, the way
        `run` does; `recv_batch` reads them back and unlinks them."""
        req = {"op": "run_paths", "task": task, "model_id": model_id,
               "paths": [str(p) if p else "" for p in paths],
               "max_dim": int(max_dim),
               "prefetch": [str(p) for p in prefetch if p],
               "options": options or {}}
        if images:
            self._n += 1
            req["outs"] = [os.path.join(self._tmpdir, f"out{self._n}_{k}.{_IPC_EXT}")
                           for k in range(len(paths))]
        self._send(req)

    def recv_batch(self) -> tuple[list, list]:
        """The next batch answer: (results in input order, [(index, error)]).
        A slot that failed — unreadable file, a run that raised — is None
        in the results and named in the errors."""
        resp = self._recv()
        if not resp.get("ok"):
            raise RuntimeError(_failure(resp))
        out, errors = [], []
        for k, res in enumerate(resp["results"]):
            if "error" in res:
                out.append(None)
                errors.append((k, str(res["error"])))
            elif "image" in res:
                p = res["image"]
                if not p:
                    out.append(None)   # the plugin's own "nothing to do"
                    continue
                from PIL import Image
                im = Image.open(p)
                im.load()   # pixels fully read, so the file below can go
                self._unlink(p)
                out.append(im)
            elif "tags" in res:
                out.append(res["tags"])
            elif "text" in res:
                out.append(res["text"])
            else:
                out.append(res.get("value"))
        return out, errors

    def load(self, imp: dict, load_key: str, ctx: dict) -> None:
        resp = self._rpc({"op": "load", "import": imp, "load_key": load_key, "ctx": ctx})
        if not resp.get("ok"):
            raise RuntimeError(_failure(resp))

    @staticmethod
    def _unlink(*paths: str) -> None:
        # The scratch PNGs used to live until the warm worker was stopped — a
        # batch job over thousands of items left one full-size PNG per image
        # (both directions) on disk for the life of the worker.
        for p in paths:
            try:
                os.unlink(p)
            except OSError:
                pass

    def run(self, task: str, model_id: str, image, options: dict | None = None):
        self._n += 1
        inp = os.path.join(self._tmpdir, f"in{self._n}.{_IPC_EXT}")
        out = os.path.join(self._tmpdir, f"out{self._n}.{_IPC_EXT}")
        _write_ipc(image, inp)
        try:
            resp = self._rpc({"op": "run", "task": task, "model_id": model_id,
                              "image": inp, "out": out, "options": options or {}})
            if not resp.get("ok"):
                raise RuntimeError(_failure(resp))
            res = resp["result"]
            if "image" in res:
                p = res["image"]
                if not p:
                    return None
                from PIL import Image
                im = Image.open(p)
                im.load()   # pixels fully read, so the file below can go
                self._unlink(p)
                return im
            if "text" in res:
                return res["text"]
            if "tags" in res:
                return res["tags"]
            return res.get("value")
        finally:
            self._unlink(inp, out)

    def run_batch(self, task: str, model_id: str, images, options: dict | None = None):
        """Run ``task`` over several images in one request. The worker uses the
        plugin's ``run_batch`` if it defines one (a true batched forward pass),
        else loops its ``run`` — either way over the one resident model. Returns a
        list of results (tags/text) in input order."""
        self._n += 1
        paths = []
        for k, im in enumerate(images):
            p = os.path.join(self._tmpdir, f"in{self._n}_{k}.{_IPC_EXT}")
            _write_ipc(im, p)
            paths.append(p)
        try:
            resp = self._rpc({"op": "run_batch", "task": task,
                              "model_id": model_id,
                              "images": paths, "options": options or {}})
        finally:
            self._unlink(*paths)
        if not resp.get("ok"):
            raise RuntimeError(_failure(resp))
        out = []
        for res in resp["results"]:
            if "tags" in res:
                out.append(res["tags"])
            elif "text" in res:
                out.append(res["text"])
            else:
                out.append(res.get("value"))
        return out

    def stop(self) -> None:
        try:
            self._rpc({"op": "quit"})
        except Exception:  # noqa: BLE001
            pass
        for close in (self._rf.close, self._wf.close, self._sock.close):
            try:
                close()
            except Exception:  # noqa: BLE001
                pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            try:
                self.proc.kill()
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(self._tmpdir, ignore_errors=True)


#: THE IPC IMAGE FORMAT — uncompressed TIFF, not PNG.
#:
#: Every image handed to a model crosses a process boundary as a temp file,
#: and a batch job crosses it once per item: at 1M items the format is hours
#: of wall clock. Measured on 1.9 MP pictures, one round trip (encode, write,
#: read, decode) of the RGBA images `jobs._active_image` produces:
#:
#:     PNG          28.2 ms encode + 6.7 ms decode = 34.9 ms   0.71 MB
#:     TIFF raw      2.7 ms encode + 0.4 ms decode =  3.1 ms   7.68 MB
#:
#: It is the ENCODER, not the bytes: PNG is deflate over four channels of
#: photographic noise, and uncompressed TIFF is a memcpy with a header — the
#: same reason `media.iter_video_frames` puts frames on its pipe as BMP.
#:
#: BMP was the obvious choice for that precedent and is WRONG here: Pillow
#: writes an RGBA image to BMP as RGB, silently, so every plugin would start
#: receiving images with the alpha channel quietly gone. TIFF round-trips
#: every mode that can reach this (1, L, P, RGB, RGBA, LA, I;16, F, CMYK)
#: byte for byte, and like PNG it needs nothing a dedicated env's Pillow
#: might lack — which is why the format was PNG rather than WebP.
#:
#: The file is ~10x bigger and that is the trade: it is written and read once
#: on local disk (a tmpfs on most Linux boxes) and unlinked immediately, and
#: the measurements above are of real files, so the I/O is already in them.
_IPC_FORMAT = "TIFF"
_IPC_EXT = "tif"


def _write_ipc(image, path: str) -> None:
    """One image out to the worker. `compression="raw"` is what makes it a
    memcpy — Pillow's TIFF default is uncompressed already, but saying so is
    what stops a future default from quietly making this PNG again."""
    image.save(path, _IPC_FORMAT, compression="raw")


class Inflight:
    """A `run_paths` request the worker is answering — `ModelHost.submit_paths`'s
    handle. `result()` blocks for the answer; until then the host's lock is
    HELD by the submitting thread (an RLock, so the same thread may submit
    the next chunk before collecting this one, and must be the one to
    collect). Answers come back in request order: collecting a later handle
    first collects the earlier ones on its way."""

    def __init__(self, host, worker):
        self._host = host
        self._worker = worker
        self._results: list | None = None
        self.errors: list = []
        self._exc: BaseException | None = None
        self._done = False

    def _settle(self) -> None:
        if self._done:
            return
        self._done = True
        try:
            self._results, self.errors = self._worker.recv_batch()
        except BaseException as exc:  # noqa: BLE001 - re-raised by result()
            self._exc = exc
        finally:
            self._host._collected(self)

    def result(self) -> list:
        """One result per submitted path, None where that picture failed
        (`errors` says why)."""
        self._host._collect_up_to(self)
        if self._exc is not None:
            raise self._exc
        return self._results or []


class ModelHost:
    """Single-slot out-of-process model runner with an idle TTL."""

    def __init__(self, resolve=None, ttl: float | None = None):
        self._resolve = resolve or registry.plugin_for
        self._ttl = default_ttl() if ttl is None else ttl
        self._lock = threading.RLock()
        self._worker: _Worker | None = None
        self._timer: threading.Timer | None = None
        self._last_used = 0.0
        # `submit_paths` requests not yet collected, in request order.
        self._inflight: list[Inflight] = []

    def submit_paths(self, task: str, model_id: str, paths, ctx: dict | None = None,
                     max_dim: int = 0, prefetch=(), options: dict | None = None,
                     images: bool = False) -> Inflight:
        """Send one chunk of the library's OWN files to the worker and return
        at once — the batch-job path. The worker decodes them on its threads
        (`worker.read_image`, downscaled to ``max_dim``) and starts on
        ``prefetch``, the chunk the caller expects to send next, before it
        runs this one; the caller applies the PREVIOUS chunk's answer
        meanwhile, and collects this one with `Inflight.result()`.

        The host's lock is acquired here and released when the handle is
        collected, on the SAME thread; a second submit before collecting is
        allowed (the socket queues it) and is how the pipeline stays full.
        Another caller waits for every outstanding handle — the batch loop
        drains its pipeline every few chunks so that wait stays short.
        """
        self._lock.acquire()
        try:
            self._cancel_timer()
            plugin = self._resolve(model_id)
            if plugin is None:
                raise RuntimeError(f"no plugin provides model {model_id!r}")
            key = plugin.load_key(model_id)
            if self._worker is None or self._worker.key != key:
                self._stop_worker()
                self._worker = self._spawn(plugin, key, ctx or {})
            worker = self._worker
            worker.send_paths(task, model_id, paths, max_dim, prefetch, options,
                              images=images)
        except BaseException:
            self._lock.release()
            raise
        handle = Inflight(self, worker)
        self._inflight.append(handle)
        return handle

    def _collect_up_to(self, handle: Inflight) -> None:
        """Read answers in order until ``handle``'s is in."""
        for h in list(self._inflight):
            h._settle()
            if h is handle:
                break

    def _collected(self, handle: Inflight) -> None:
        """One handle settled: it leaves the queue and gives its lock back.
        A worker that died mid-answer is dropped so the next call respawns
        rather than writing into a closed socket."""
        if handle in self._inflight:
            self._inflight.remove(handle)
        if handle._exc is not None and self._worker is handle._worker \
                and handle._worker.proc.poll() is not None:
            self._stop_worker()
        self._last_used = time.monotonic()
        self._arm_timer()
        self._lock.release()

    def run(self, task: str, model_id: str, image, ctx: dict | None = None,
            options: dict | None = None):
        """Run ``task`` with ``model_id`` on ``image`` (PIL), returning the
        plugin's result (a PIL image, text, or a tag list). ``options`` are
        per-run inputs forwarded to the plugin's ``run`` (e.g. explicit boxes)."""
        with self._lock:
            self._cancel_timer()
            plugin = self._resolve(model_id)
            if plugin is None:
                raise RuntimeError(f"no plugin provides model {model_id!r}")
            key = plugin.load_key(model_id)
            if self._worker is None or self._worker.key != key:
                self._stop_worker()
                self._worker = self._spawn(plugin, key, ctx or {})
            worker = self._worker
            try:
                return worker.run(task, model_id, image, options)
            finally:
                self._last_used = time.monotonic()
                self._arm_timer()

    def run_batch(self, task: str, model_id: str, images, ctx: dict | None = None,
                  options: dict | None = None):
        """Run ``task`` with ``model_id`` over several PIL images using one warm
        model load, returning a list of results in input order. Falls back to warm
        per-image runs if the worker can't batch (a plugin without ``run_batch``,
        or a batch shape the model rejects)."""
        if not images:
            return []
        with self._lock:
            self._cancel_timer()
            plugin = self._resolve(model_id)
            if plugin is None:
                raise RuntimeError(f"no plugin provides model {model_id!r}")
            key = plugin.load_key(model_id)
            if self._worker is None or self._worker.key != key:
                self._stop_worker()
                self._worker = self._spawn(plugin, key, ctx or {})
            worker = self._worker
            try:
                try:
                    return worker.run_batch(task, model_id, images, options)
                except RuntimeError:
                    # The worker is still alive but couldn't batch — retry each
                    # image individually on the same resident model.
                    return [worker.run(task, model_id, im, options) for im in images]
            finally:
                self._last_used = time.monotonic()
                self._arm_timer()

    def shutdown(self) -> None:
        with self._lock:
            self._cancel_timer()
            self._stop_worker()

    # ---- internals --------------------------------------------------------

    def _spawn(self, plugin, load_key: str, ctx: dict) -> _Worker:
        interp = fw.interpreter_for(plugin.env)
        if interp is None:
            raise RuntimeError(
                f"model {load_key!r} needs the '{plugin.env}' environment, "
                f"which isn't set up (see model help)"
            )
        # Resolve the plugin's sources (local-path overrides vs default repos) and
        # the offline/token flags into the ctx the worker's load() receives.
        worker_ctx = {
            "local_files_only": bool(ctx.get("local_files_only", True)),
            "token": ctx.get("token", "") or "",
            "sources": fw.resolve_sources(plugin.manifest, ctx.get("model_paths") or {}),
        }
        # main env -> import the plugin by dotted name (package available);
        # a dedicated env -> by file path (the package may not be installed).
        imp = ({"module": plugin.module.__name__} if plugin.env == "main"
               else {"file": plugin.file})
        tmpdir = tempfile.mkdtemp(prefix="mc-worker-")
        env = dict(os.environ)
        # The worker imports transformers/diffusers, which report usage to
        # huggingface.co unless told not to. `hub.hf` turns it off for THIS
        # process on import, and the child inherits that — but only if
        # something has imported the hub package by now, and a plugin job need
        # not have. Said again here, where the child is actually made.
        env.setdefault(hf.TELEMETRY_ENV, "1")
        # onnxruntime's own telemetry (a Microsoft 1DS client, every platform
        # since 1.29). worker.py sets this for itself too — said again where
        # the child is actually made, like the HF variable above.
        env.setdefault("ORT_DISABLE_TELEMETRY", "1")
        try:
            proc, parent = (_spawn_windows if _WINDOWS else _spawn_posix)(
                interp, env)
        except Exception:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise
        worker = _Worker(proc, parent, load_key, tmpdir)
        try:
            worker.load(imp, load_key, worker_ctx)
        except Exception:
            worker.stop()
            raise
        return worker

    def release_idle(self) -> bool:
        """Drop the worker if it is only holding its model warm — called
        before a training run starts, which needs the card more than the
        next click does (the Evaluate generator has the same hook,
        `evaluate.EvalManager.release_idle`). A worker mid-call, or with
        answers still to collect, is left alone; True when one was
        stopped."""
        if not self._lock.acquire(blocking=False):
            return False
        try:
            if self._worker is None or self._inflight:
                return False
            self._cancel_timer()
            self._stop_worker()
            return True
        finally:
            self._lock.release()

    def _arm_timer(self) -> None:
        self._cancel_timer()
        t = threading.Timer(self._ttl, self._evict)
        t.daemon = True
        t.start()
        self._timer = t

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _evict(self) -> None:
        with self._lock:
            # Only evict if genuinely idle for the whole TTL (guards against a
            # timer that fired while a fresh run had just re-armed it).
            if time.monotonic() - self._last_used >= self._ttl - 0.05:
                self._stop_worker()
            self._timer = None

    def _stop_worker(self) -> None:
        if self._worker is not None:
            self._worker.stop()
            self._worker = None

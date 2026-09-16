#!/usr/bin/env python
"""Persistent out-of-process model worker.

Launched by :class:`media_compost.ui.plugins.host.ModelHost` with a plugin's chosen
Python interpreter. It loads **one** model and serves ``run`` requests, keeping
the model resident until the host stops it — so consecutive jobs on the same
model don't reload multi-GB weights.

It is intentionally self-contained (stdlib + Pillow only, never importing the
rest of ``media_compost``) so a plugin's dedicated venv needs only the plugin's
own deps, not the whole project. The plugin module is imported here either by
dotted name (main env) or by file path (a dedicated env without the package).

Protocol: newline-delimited JSON over the socket ``_channel()`` returns — an
inherited socketpair fd on POSIX, a token-authenticated loopback connection
back to the host on Windows. Images are passed by file path, never inline.
``stdout``/``stderr`` are left for the model's own logging (the host captures
them into the job log); the protocol never uses them.

    load  {"op":"load","import":{"module"|"file":...},"load_key":str,"ctx":{}}
    run   {"op":"run","task":str,"model_id":str,"image":path,"out":path,"options":{}}
    run_batch {"op":"run_batch",...,"images":[path,...],"options":{}}
    run_paths {"op":"run_paths",...,"paths":[path,...],"max_dim":int,
               "prefetch":[path,...],"options":{},"outs":[path,...]?}
    quit  {"op":"quit"}

``run_batch`` takes images the host WROTE for it (one uncompressed file per
picture); ``run_paths`` takes the library's own files and decodes them here,
on threads, downscaled to ``max_dim`` by `read_image` — the batch-job path,
where the host's copy was the widest leg of every chunk. ``prefetch`` names
the paths the host expects to send NEXT: they start decoding before this
request's plugin call, so the next chunk is ready when it is asked for. A
plugin may declare ``prepare(prep_handle, image)``: its per-picture CPU
work (a vision model's resize-and-normalize), run beside the decode, whose
result is what its ``run_batch`` / ``run`` then receive in place of the
picture. ``load_prep(load_key, ctx)`` builds ``prep_handle`` — light, never
the model — because with `prepare` the decode runs in PROCESSES
(`_DECODE_PROCS`), each of which imports the plugin and calls it; the
result must therefore be a numpy array (it travels through shared
memory). ``wants_decode_processes(handle)`` may answer False to keep the
decode on threads (the embed plugins do off CUDA, where the forward is
the bound). The
host may write the next ``run_paths`` before reading this one's answer;
answers go back in request order. A picture that cannot be read answers
``{"error": ...}`` in its slot and the rest of the batch goes on.

``load_key`` is the identity of the *weights* to load (several menu models may
share one — e.g. JoyCaption prompt variants); the full ``model_id`` is passed to
``run`` so the plugin can pick the variant without reloading.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import socket
import sys
import time
import traceback

# onnxruntime grew a Microsoft 1DS telemetry client on EVERY platform at 1.29
# (it was Windows-only ETW before, which is what the last audit recorded): the
# first InferenceSession quietly creates "~/Library/Application Support/
# Microsoft/DeveloperTools/.onnxruntime/" — an offline event queue plus a
# persisted device id — and flushes it to mobile.events.data.microsoft.com
# later, which is how it surfaced as a firewall alert minutes after a
# background-removal job. Nothing here phones home, so it is off — HERE,
# before any plugin import, because four plugins reach onnxruntime (withoutbg
# and wd_tagger directly, rapidocr and insightface through their own
# libraries) and this loop is the one process every model job runs in.
# Verified: with the variable set, that directory is never created at all.
# `setdefault`: a deliberate 0 is somebody's decision.
os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")


def _import_plugin(imp: dict):
    """Import the plugin module by dotted name (main env) or by file path."""
    mod = imp.get("module")
    if mod:
        return importlib.import_module(mod)
    path = imp["file"]
    name = "mc_plugin_" + os.path.basename(path).rsplit(".", 1)[0]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _channel() -> socket.socket:
    """The socket the host talks to us on.

    Two transports, chosen by which variables the host set (see
    ``host._spawn_posix`` / ``_spawn_windows``):

    * ``MC_WORKER_FD`` — POSIX: one end of a socketpair, inherited.
    * ``MC_WORKER_PORT`` + ``MC_WORKER_TOKEN`` — Windows, which cannot
      inherit an fd this way: dial back to the host's loopback listener and
      present the token as the first line. The token is what identifies us as
      the process the host just spawned; the host drops anything else.
    """
    port = os.environ.get("MC_WORKER_PORT")
    if port:
        sock = socket.create_connection(("127.0.0.1", int(port)))
        token = os.environ.get("MC_WORKER_TOKEN", "")
        sock.sendall((token + "\n").encode("utf-8"))
        return sock
    return socket.socket(fileno=int(os.environ["MC_WORKER_FD"]))


_PROFILE = bool(os.environ.get("MEDIA_COMPOST_JOB_PROFILE"))


def read_image(path, max_dim: int = 0):
    """Open, shrink to `max_dim`, THEN convert — in that order on purpose.

    THE ONE DEFINITION of what a model job's picture is: the host's own
    single-item path (`jobs.JobQueue._read_image`) and the batch path that
    decodes here both call it, so a face detected alone gets the same pixels
    as one detected in a chunk, and a vector indexed on either side lands in
    the same space.

    `thumbnail()` asks the decoder for a DRAFT of a JPEG (DCT scaling: a
    picture decoded at 1/2, 1/4 or 1/8 of its size costs that fraction),
    and a `convert()` before it forces the full decode first and throws
    the draft away. The old order did exactly that. Measured over 120
    crawl pictures (median 1.6 MP): 16.6 → 12.2 ms each, and the gain
    grows with the picture. What it costs the VECTOR is nothing that
    matters: the same picture embeds to cosine ≥ 0.99976 (median 1.0)
    of its old vector, against 0.78 for the nearest OTHER picture and the
    0.998 the manga pages measure between different pages — so the space
    string stays. Modes Pillow will not resample cleanly (a palette, a
    bilevel) are converted first; nothing else is.

    NOT tightened further, on measurement (2026-09, 512 crawl pictures on
    the 5090 box): `thumbnail` drafts at TWICE the target (`reducing_gap`),
    so a 1.6 MP JPEG still decodes in full and the resize is half the cost.
    Drafting at 1x (`reducing_gap=1.0`, or an explicit `draft()` first) is
    0.78 ms a picture on 32 threads against 1.27 — and the vectors move:
    1st percentile cosine 0.995, worst 0.984, the band the cached
    thumbnail was rejected at. The pixels are the recipe.
    """
    from PIL import Image

    im = Image.open(path)
    if max_dim and max(im.size) > max_dim:
        if im.mode not in ("RGB", "RGBA", "L", "LA"):
            im = im.convert("RGBA")
        im.thumbnail((max_dim, max_dim))
    return im.convert("RGBA")


#: Threads decoding a chunk's pictures. Pillow's decoders release the GIL,
#: so this scales with the cores — measured on the 5090 box (16 cores, 32
#: threads): 12.3 ms a picture serial, 1.27 on 32 threads, and no better on
#: 64. The cap keeps a 128-thread box from opening 128 files at once for
#: nothing; `MEDIA_COMPOST_DECODE_THREADS` says otherwise.
_DECODE_THREADS = max(1, int(os.environ.get("MEDIA_COMPOST_DECODE_THREADS")
                             or min(32, max(4, os.cpu_count() or 4))))

#: PROCESSES decoding a chunk's pictures, for a plugin that declares
#: `prepare` — the per-picture CPU work (a vision model's resize-and-
#: normalize) whose result is COMPACT enough to pickle back. Threads leave
#: half the machine idle: what holds the GIL between Pillow's C calls and
#: inside the processor is enough that 32 threads on the 5090 box ran the
#: CPU at 38% and 1.7 ms a picture, where 16 processes ran it at 95% and
#: 1.25 (decode + prepare, 2 000 crawl pictures; the switch interval and
#: Pillow's block size changed nothing). Physical cores, not threads: 32
#: processes were no faster than 16 on that box, and each carries torch.
#: 0 = threads for every plugin. `MEDIA_COMPOST_DECODE_PROCS` says otherwise.
_DECODE_PROCS = max(0, int(os.environ.get("MEDIA_COMPOST_DECODE_PROCS")
                           or min(16, max(2, (os.cpu_count() or 4) // 2))))

#: Pictures per process-pool task. One task per picture would spawn a
#: process per picture queued; eight lets a chunk of 32 use four processes
#: and a chunk of 256 the whole pool (the pool spawns on demand).
_PROC_GROUP = max(1, int(os.environ.get("MEDIA_COMPOST_DECODE_GROUP") or 8))

# ---- the process pool's side ----------------------------------------------
# These run in the CHILD (spawned, so `__main__` here is `__mp_main__` — the
# worker script re-imported without running `main()`): the plugin is
# imported again, its `load_prep` builds the light handle `prepare` takes (a
# processor, never the model), and `_decode_group` does a group's pictures.

_PREP: tuple = (None, None)   # (plugin, prep handle) in a child

#: THE CHILD KEEPS ITS LAST BLOCKS OPEN. On Windows a shared-memory segment
#: lives only as long as a handle to it does — there is no `unlink`, the
#: last close frees it — so a block the child let go of as its function
#: returned was gone before the worker opened it by name. Linux keeps a
#: segment until it is unlinked and never showed this. The worker reads a
#: group within a chunk or two of its answer, so a short ring of recent
#: blocks (32 groups, ~40 MB at most) covers it; what falls off the ring the
#: worker has long since copied out and unlinked.
_KEEP_BLOCKS: "collections.deque" = None   # type: ignore[assignment]


def _child_main(imp: dict, load_key: str, ctx: dict, tasks, results) -> None:
    """A decode process: import the plugin, build its light handle, then
    pull groups off ``tasks`` and push each answer onto ``results`` until
    told to stop (None) — with NO thread in the worker between a child and
    its next group. `concurrent.futures.ProcessPoolExecutor` hands out work
    from a manager thread and keeps workers+1 groups queued, and that
    thread shares the worker's GIL with the forward: every child measured
    idle at once for 100–440 ms at chunk boundaries (5090 box), a quarter
    of their time. Here the worker queues a whole chunk at prefetch and
    reads the answers when it needs them."""
    global _PREP
    import multiprocessing
    import threading

    # A CHILD MUST NOT OUTLIVE THE WORKER: the worker stops its children on
    # a clean exit, but the host kills a worker that hangs, and a child
    # blocked on its queue would then sit forever, torch and all.
    parent = multiprocessing.parent_process()
    if parent is not None:
        def _watch():
            parent.join()
            os._exit(0)
        threading.Thread(target=_watch, daemon=True).start()
    try:
        plugin = _import_plugin(imp)
        load_prep = getattr(plugin, "load_prep", None)
        _PREP = (plugin, load_prep(load_key, ctx) if callable(load_prep) else None)
    except BaseException as exc:  # noqa: BLE001 - reported, then out
        results.put(("init", False, f"{exc.__class__.__name__}: {exc}"[-500:]))
        return
    results.put(("init", True, os.getpid()))
    while True:
        task = tasks.get()
        if task is None:
            return
        task_id, paths, max_dim = task
        try:
            results.put((task_id, True, _decode_group(paths, max_dim)))
        except BaseException as exc:  # noqa: BLE001 - the group's failure
            results.put((task_id, False, f"{exc.__class__.__name__}: {exc}"[-500:]))


def _decode_group(paths: list, max_dim: int) -> tuple:
    """A group's pictures: (shm name or None, [(True, shape, dtype) |
    (False, error)]) — one unreadable file is its own slot, never the
    group's.

    THE PIXELS GO BACK THROUGH SHARED MEMORY, the pipe carries the name. A
    pool result travels through one pipe the worker's manager thread drains
    under the worker's GIL: a child that has a 1.2 MB group to send waits
    for that thread, which waits for the main thread's forward, and the
    children measured 35% idle for it (5090 box, 8000 pictures). A block
    the child fills and the worker maps is a handle on the pipe and a
    memcpy on each side. Every array of a group is a prepared numpy array
    (`prepare`), laid end to end; the worker unlinks the block once read.
    """
    import numpy as np
    from multiprocessing import shared_memory

    plugin, prep_handle = _PREP
    _t0 = time.perf_counter()
    got = []
    for p in paths:
        try:
            if not p:
                raise OSError("no stored image")
            arr = np.ascontiguousarray(
                plugin.prepare(prep_handle, read_image(p, max_dim)))
            got.append((True, arr))
        except Exception as exc:  # noqa: BLE001 - one picture's failure
            got.append((False, f"{p}: {exc}"[-500:]))
    total = sum(a.nbytes for ok, a in got if ok)
    name = None
    if total:
        global _KEEP_BLOCKS
        if _KEEP_BLOCKS is None:
            import collections
            _KEEP_BLOCKS = collections.deque(maxlen=32)
        shm = shared_memory.SharedMemory(create=True, size=total)
        off = 0
        for ok, a in got:
            if ok:
                shm.buf[off:off + a.nbytes] = a.tobytes()
                off += a.nbytes
        name = shm.name
        # Held open here (see `_KEEP_BLOCKS`); the ring's `maxlen` closes the
        # oldest as a new one is appended.
        if len(_KEEP_BLOCKS) == _KEEP_BLOCKS.maxlen:
            try:
                _KEEP_BLOCKS[0].close()
            except Exception:  # noqa: BLE001
                pass
        _KEEP_BLOCKS.append(shm)
    out = [(True, a.shape, a.dtype.str) if ok else (False, a) for ok, a in got]
    if _PROFILE and paths:
        print(f"[job-profile] decode process: {(time.perf_counter() - _t0) * 1000:.0f} ms "
              f"for {len(paths)} pid={os.getpid()} t0={_t0:.4f} t1={time.perf_counter():.4f}",
              file=sys.stderr, flush=True)
    return name, out


def _open_group(result: tuple) -> list:
    """The worker's side of `_decode_group`: the group's arrays copied out
    of the block, which is then released. Each entry (True, array) or
    (False, error)."""
    import numpy as np
    from multiprocessing import shared_memory

    name, out = result
    if name is None:
        return out
    shm = shared_memory.SharedMemory(name=name)
    try:
        off = 0
        arrays = []
        for entry in out:
            if entry[0]:
                _, shape, dtype = entry
                n = int(np.prod(shape)) * np.dtype(dtype).itemsize
                arrays.append((True, np.frombuffer(shm.buf[off:off + n],
                                                   dtype=dtype).reshape(shape).copy()))
                off += n
            else:
                arrays.append(entry)
        return arrays
    finally:
        shm.close()
        try:
            shm.unlink()
        except FileNotFoundError:
            pass


def _decode(path: str, max_dim: int, prep):
    """One decode-thread job: the picture, then the plugin's own per-picture
    preparation where it declares one (`prepare(prep_handle, image)`) — the
    resize-and-normalize a vision model wants done on the CPU, which on the
    main thread was STARVED: 32 decode threads holding the GIL stretched an
    embed chunk's 150 ms of processor work to 450 (measured, 5090 box). Done
    here it is one more step of the same thread's work, and the main thread
    is left with a stack, an upload and the forward."""
    if not path:
        raise OSError("no stored image")
    im = read_image(path, max_dim)
    return prep(im) if prep is not None else im


class _Cell:
    """One path's place in a pool answer: a thread future, or a process
    group's task id and the index into its list. `result()` raises for a
    picture that failed, as a thread future would."""

    __slots__ = ("future", "task_id", "index")

    def __init__(self, future=None, task_id=None, index: int = -1):
        self.future = future
        self.task_id = task_id
        self.index = index


class _ProcPool:
    """Spawned decode processes pulling groups from one queue and pushing
    answers to another — see `_child_main`. `submit` queues a group and
    answers its task id; `wait` reads answers until the wanted ids are in;
    `get` hands one back (opened from shared memory once)."""

    def __init__(self, n: int, imp: dict, load_key: str, ctx: dict):
        import multiprocessing

        mp = multiprocessing.get_context("spawn")
        self.tasks = mp.Queue()
        self.results = mp.Queue()
        self.procs = [mp.Process(target=_child_main, daemon=True,
                                 args=(imp, load_key, ctx, self.tasks, self.results))
                      for _ in range(n)]
        for proc in self.procs:
            proc.start()
        self._next = 0
        self._done: dict = {}
        self._alive = 0
        # THE FIRST CHILD MUST REPORT IN, so a plugin that cannot import in
        # a child, or an interpreter that cannot spawn, fails here — once,
        # into threads — rather than hanging the first chunk. The rest
        # report as they come up; a child that fails to start is one
        # process fewer, and a pool with none left raises on wait.
        self._await_init(first=True)

    def _await_init(self, first: bool) -> None:
        import queue as _queue

        while True:
            try:
                kind, ok, value = self.results.get(timeout=120 if first else 0)
            except _queue.Empty:
                if first:
                    raise RuntimeError("no decode process came up")
                return
            if kind != "init":
                # An answer arriving before every child reported: keep it.
                self._done[kind] = (ok, value)
                continue
            if not ok:
                print(f"decode process failed to start: {value}",
                      file=sys.stderr, flush=True)
                if first and self._alive == 0 and not any(
                        p.is_alive() for p in self.procs):
                    raise RuntimeError(value)
            else:
                self._alive += 1
            if first:
                first = False
                if self._alive:
                    return

    def submit(self, paths: list, max_dim: int) -> int:
        self._next += 1
        self.tasks.put((self._next, list(paths), max_dim))
        return self._next

    def wait(self, task_ids) -> None:
        wanted = set(task_ids) - set(self._done)
        while wanted:
            if not any(p.is_alive() for p in self.procs):
                raise RuntimeError("every decode process is gone")
            kind, ok, value = self.results.get()
            if kind == "init":
                self._alive += 1 if ok else 0
                continue
            self._done[kind] = (ok, value)
            wanted.discard(kind)

    def get(self, task_id: int) -> list:
        """The group's opened answer; the entry is replaced by the opened
        list on first read so the block is released exactly once."""
        ok, value = self._done[task_id]
        if not ok:
            raise OSError(value)
        if not isinstance(value, list):
            value = _open_group(value)
            self._done[task_id] = (True, value)
        return value

    def forget(self, task_ids) -> None:
        for t in task_ids:
            self._done.pop(t, None)

    def close(self) -> None:
        for _ in self.procs:
            try:
                self.tasks.put(None)
            except Exception:  # noqa: BLE001 - best effort
                pass
        for proc in self.procs:
            proc.join(timeout=2)
            if proc.is_alive():
                proc.kill()


class _Decoder:
    """The worker's decode pool plus the pictures decoding AHEAD.

    `take` hands back one cell per path — the one already running where
    the host's previous request named it in ``prefetch``, a fresh submit
    otherwise — and `prefetch` starts the next request's decodes so they
    overlap this request's plugin call. Keyed by (path, max_dim): the same
    file wanted at another size is another decode. A prefetched picture the
    next request does not ask for (a list that moved under the job) is
    dropped at the next `prefetch`, so nothing accumulates.

    The pool is THREADS, or PROCESSES for a plugin with `prepare` (see
    `_DECODE_PROCS`), decided once at `bind` from what the worker loaded;
    a process pool that cannot start (no spawnable interpreter, a plugin
    that will not import in a child) falls back to threads with a line on
    stderr rather than failing the job.
    """

    def __init__(self):
        self._pool = None
        self._procs = False
        self._ahead: dict = {}
        self._prep = None
        self._bound: tuple | None = None
        self._starting: list | None = None   # [thread, pool | None, error]

    def prebind(self, plugin, imp: dict, load_key: str, ctx: dict) -> None:
        """Before the model loads: start the decode processes NOW, on a
        thread, so their own start (sixteen interpreters importing torch,
        ~3 s on the 5090 box) runs under the model's load instead of in
        front of the first chunk. Only where the plugin may want them
(a plugin whose answer needs the handle is asked again at `bind`, and
        one that answers no there gets a pool it never uses, closed there)."""
        if not callable(getattr(plugin, "prepare", None)) or _DECODE_PROCS <= 0:
            return
        # A plugin that never wants processes says so before it has a
        # handle (`wants_decode_processes(None)` — the face detectors), and
        # is spared sixteen interpreters importing its libraries for nothing.
        wants = getattr(plugin, "wants_decode_processes", None)
        if callable(wants):
            try:
                if not wants(None):
                    return
            except Exception:  # noqa: BLE001 - "cannot say yet" = start it
                pass
        import threading

        self._bound = (imp, load_key, ctx)
        holder: list = [None, None, None]

        def _start():
            try:
                holder[1] = _ProcPool(_DECODE_PROCS, imp, load_key, ctx)
            except Exception as exc:  # noqa: BLE001 - reported at use
                holder[2] = exc
        holder[0] = threading.Thread(target=_start, daemon=True)
        holder[0].start()
        self._starting = holder

    def bind(self, plugin, handle, imp: dict, load_key: str, ctx: dict) -> None:
        """What was loaded: decides threads or processes and, on threads,
        the in-process `prepare` (with its own light handle). A plugin
        with `prepare` gets PROCESSES unless it says not to — its
        `wants_decode_processes(handle)`, for the embed plugins "is the
        model on CUDA": on MPS and the CPU the forward is the bound and
        seven interpreters importing torch buy nothing."""
        prepare = getattr(plugin, "prepare", None)
        if callable(prepare):
            load_prep = getattr(plugin, "load_prep", None)
            prep_handle = (load_prep(load_key, ctx) if callable(load_prep)
                           else handle)
            self._prep = lambda im: prepare(prep_handle, im)
            wants = getattr(plugin, "wants_decode_processes", None)
            self._procs = _DECODE_PROCS > 0 and (
                bool(wants(handle)) if callable(wants) else True)
            self._bound = (imp, load_key, ctx)
        else:
            self._prep = None
            self._procs = False
        if not self._procs and self._starting is not None:
            # Started ahead and not wanted after all: let it finish coming
            # up, then stop it — a child half-started must not be orphaned.
            starting, self._starting = self._starting, None
            starting[0].join()
            if starting[1] is not None:
                starting[1].close()

    def _make_pool(self):
        from concurrent.futures import ThreadPoolExecutor
        if self._procs:
            try:
                if self._starting is not None:
                    starting, self._starting = self._starting, None
                    starting[0].join()
                    if starting[2] is not None:
                        raise starting[2]
                    return starting[1]
                return _ProcPool(_DECODE_PROCS, *self._bound)
            except Exception as exc:  # noqa: BLE001 - threads are always right
                print(f"decode: process pool unavailable, using threads: "
                      f"{exc}", file=sys.stderr, flush=True)
                self._procs = False
        return ThreadPoolExecutor(max_workers=_DECODE_THREADS,
                                  thread_name_prefix="decode")

    def _submit_all(self, keys: list) -> list:
        """Cells for (path, max_dim) keys not yet decoding, in order."""
        if self._pool is None:
            self._pool = self._make_pool()
        if not self._procs:
            return [_Cell(future=self._pool.submit(_decode, p, md, self._prep))
                    for p, md in keys]
        # Groups share a max_dim (one request has one), so grouping by it is
        # a formality that keeps the task's signature honest.
        by_dim: dict = {}
        for p, md in keys:
            by_dim.setdefault(md, []).append(p)
        made: dict = {}
        for md, paths in by_dim.items():
            for i in range(0, len(paths), _PROC_GROUP):
                group = paths[i:i + _PROC_GROUP]
                tid = self._pool.submit(group, md)
                for k, p in enumerate(group):
                    made[(p, md)] = _Cell(task_id=tid, index=k)
        return [made[key] for key in keys]

    def take(self, paths, max_dim: int) -> list:
        out: list = [None] * len(paths)
        missing = []
        for k, p in enumerate(paths):
            cell = self._ahead.pop((p, max_dim), None)
            if cell is not None:
                out[k] = cell
            else:
                missing.append((k, (p, max_dim)))
        if missing:
            for (k, _), cell in zip(missing, self._submit_all(
                    [key for _, key in missing])):
                out[k] = cell
        return out

    def prefetch(self, paths, max_dim: int) -> None:
        wanted = [(p, max_dim) for p in paths]
        wanted_set = set(wanted)
        for key in list(self._ahead):
            if key not in wanted_set:
                cell = self._ahead.pop(key)
                if cell.future is not None:
                    cell.future.cancel()
        fresh = []
        seen = set()
        for key in wanted:
            if key not in self._ahead and key not in seen:
                seen.add(key)
                fresh.append(key)
        for key, cell in zip(fresh, self._submit_all(fresh)):
            self._ahead[key] = cell

    def wait(self, cells: list) -> None:
        """Block until every cell's answer is in — ONE wait for the chunk,
        not one per picture: a blocking `result()` gives the GIL away and
        asks for it back, and under the decode threads every ask is a
        queue."""
        futs = {c.future for c in cells if c.future is not None}
        if futs:
            from concurrent.futures import wait as _wait
            _wait(futs)
        tids = {c.task_id for c in cells if c.task_id is not None}
        if tids:
            self._pool.wait(tids)

    def result(self, cell: _Cell):
        if cell.future is not None:
            return cell.future.result()
        ok, value = self._pool.get(cell.task_id)[cell.index]
        if not ok:
            raise OSError(value)
        return value

    def release(self, cells: list) -> None:
        """The chunk is read: its groups' answers may go."""
        if self._procs and self._pool is not None:
            self._pool.forget({c.task_id for c in cells if c.task_id is not None})

    def close(self) -> None:
        if self._pool is not None:
            if self._procs:
                self._pool.close()
            else:
                self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None


def _run_paths(plugin, handle, req: dict, decoder: _Decoder) -> list:
    """One `run_paths` request: this chunk's pictures off the decoder, the
    next chunk's started, the plugin run over what could be read. Answers
    one entry per path, in order — a marshalled result, or
    ``{"error": …}`` for a picture that failed to decode or whose own run
    failed, so a selection of a million is never sunk by one file."""
    paths = list(req.get("paths") or [])
    max_dim = int(req.get("max_dim") or 0)
    outs = list(req.get("outs") or [])
    cells = decoder.take(paths, max_dim)
    # The NEXT chunk starts decoding now, before this one's plugin call,
    # which is the overlap this op exists for.
    decoder.prefetch(req.get("prefetch") or [], max_dim)
    _t0 = time.perf_counter()
    decoder.wait(cells)
    imgs: list = []
    slots: list = [None] * len(paths)
    for k, (p, cell) in enumerate(zip(paths, cells)):
        try:
            imgs.append((k, decoder.result(cell)))
        except Exception as exc:  # noqa: BLE001 - one picture's failure
            slots[k] = {"error": f"{p}: {exc}"[-500:]}
    decoder.release(cells)
    _t1 = time.perf_counter()
    opts = req.get("options") or {}
    task, model_id = req["task"], req["model_id"]
    batch = [im for _, im in imgs]
    results = None
    fn = getattr(plugin, "run_batch", None)
    if callable(fn) and batch:
        try:
            results = list(fn(task, model_id, handle, batch, opts))
            if len(results) != len(batch):
                raise RuntimeError(
                    f"run_batch answered {len(results)} for {len(batch)}")
        except Exception as exc:  # noqa: BLE001 - fall back to one at a time
            print(f"batch of {len(batch)} failed, retrying one at a time: "
                  f"{exc}", file=sys.stderr, flush=True)
            results = None
    if results is None:
        results = []
        for _, im in imgs:
            try:
                results.append(plugin.run(task, model_id, handle, im, opts))
            except Exception as exc:  # noqa: BLE001 - one picture's failure
                results.append({"error": str(exc)[-500:]})
    for (k, _), res in zip(imgs, results):
        if isinstance(res, dict) and "error" in res:
            slots[k] = res
            continue
        try:
            # A picture result needs a file to go to — the host names one per
            # slot when it expects pictures (`outs`); without one it is this
            # slot's failure, not the batch's.
            slots[k] = _marshal(res, outs[k] if k < len(outs) else None)
        except Exception as exc:  # noqa: BLE001 - one picture's failure
            slots[k] = {"error": f"result: {exc}"[-500:]}
    if _PROFILE:
        print(f"[job-profile] worker {task}: decode-wait {(_t1 - _t0) * 1000:.0f} ms, "
              f"plugin {(time.perf_counter() - _t1) * 1000:.0f} ms for {len(paths)}",
              file=sys.stderr, flush=True)
    return slots


def main() -> int:
    sock = _channel()
    rf = sock.makefile("r", encoding="utf-8", newline="\n")
    wf = sock.makefile("w", encoding="utf-8", newline="\n")

    def send(obj) -> None:
        wf.write(json.dumps(obj) + "\n")
        wf.flush()

    plugin = None
    handle = None
    decoder = _Decoder()
    for line in rf:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception as exc:  # noqa: BLE001
            send({"ok": False, "error": f"bad request: {exc}"})
            continue
        op = req.get("op")
        try:
            if op == "quit":
                decoder.close()
                send({"ok": True})
                break
            if op == "load":
                plugin = _import_plugin(req["import"])
                decoder.prebind(plugin, req["import"], req["load_key"],
                                req.get("ctx") or {})
                handle = plugin.load(req["load_key"], req.get("ctx") or {})
                decoder.bind(plugin, handle, req["import"], req["load_key"],
                             req.get("ctx") or {})
                send({"ok": True})
                continue
            if op == "run":
                from PIL import Image

                img = Image.open(req["image"])
                img.load()
                result = plugin.run(req["task"], req["model_id"], handle, img,
                                    req.get("options") or {})
                send({"ok": True, "result": _marshal(result, req.get("out"))})
                continue
            if op == "run_batch":
                from PIL import Image

                # ON THREADS: Pillow's decoders release the GIL, and a batch
                # of 32 read one file at a time was ~11 ms of the worker's
                # single thread per chunk while the GPU waited — the same
                # reason the host decodes its originals on threads.
                from concurrent.futures import ThreadPoolExecutor

                def _load(p):
                    im = Image.open(p)
                    im.load()
                    return im
                paths = list(req["images"])
                _t0 = time.perf_counter()
                if len(paths) > 1:
                    with ThreadPoolExecutor(max_workers=min(8, len(paths))) as ex:
                        imgs = list(ex.map(_load, paths))
                else:
                    imgs = [_load(p) for p in paths]
                _t1 = time.perf_counter()
                opts = req.get("options") or {}
                fn = getattr(plugin, "run_batch", None)
                if callable(fn):
                    results = fn(req["task"], req["model_id"], handle, imgs, opts)
                else:
                    # No batched forward pass — loop the plugin's single-image run
                    # on the one resident model (still avoids reloading weights).
                    results = [plugin.run(req["task"], req["model_id"], handle, im, opts)
                               for im in imgs]
                if _PROFILE:
                    # The host's `MEDIA_COMPOST_JOB_PROFILE` split, from this
                    # side of the boundary: what reading the files cost and
                    # what the plugin did with them.
                    print(f"[job-profile] worker {req['task']}: load {(_t1 - _t0) * 1000:.0f} ms, "
                          f"plugin {(time.perf_counter() - _t1) * 1000:.0f} ms for {len(imgs)}",
                          file=sys.stderr, flush=True)
                # Batch results are text/tags only (image outputs aren't batched),
                # so no per-result output path is needed.
                send({"ok": True, "results": [_marshal(r, None) for r in results]})
                continue
            if op == "run_paths":
                send({"ok": True,
                      "results": _run_paths(plugin, handle, req, decoder)})
                continue
            send({"ok": False, "error": f"unknown op {op!r}"})
        except BaseException as exc:  # noqa: BLE001 - report any failure upstream
            send({"ok": False, "error": "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__))[-1500:]})
    return 0


def _marshal(result, out_path):
    """Turn a plugin ``run`` result into a JSON-serializable payload. An image
    result is written to ``out_path`` (a PNG) and referenced by path; text/tags
    go inline."""
    if result is None:
        return {"image": None}
    if isinstance(result, dict):
        if "image" in result:
            im = result["image"]
            if im is None:
                return {"image": None}
            # UNCOMPRESSED TIFF, the same interchange the host writes its
            # inputs in and for the same reason — see `_IPC_FORMAT` in
            # `host.py`. Nothing coordinates the two beyond this comment:
            # Pillow sniffs the format from the CONTENT, so each side only
            # has to write something the other can read.
            im.save(out_path, "TIFF", compression="raw")
            return {"image": out_path}
        if "text" in result:
            return {"text": result["text"]}
        if "tags" in result:
            return {"tags": result["tags"]}
    return {"value": result}


if __name__ == "__main__":
    sys.exit(main())

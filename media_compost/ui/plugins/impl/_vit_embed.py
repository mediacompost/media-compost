"""What the two embed plugins share: the device pick, the per-picture
preprocessing the worker runs on its decode threads, the forward as a CUDA
graph where there is one, and the packing of a chunk's vectors for the wire.

A leading underscore, like `_echo.py`: not a plugin, never in
`registry.PLUGIN_MODULES`. Imported by the main-env embed plugins only, so
it may use a relative import the way they do.

WHY A CUDA GRAPH. The worker decodes AND preprocesses the next chunk on
threads while this one is in the model (`worker._decode`), and an eager
forward is hundreds of kernel launches from Python, each one giving the GIL
away and asking for it back: under 32 threads busy with Pillow and the
processor it took 263 ms for what takes 84 alone (5090 box, 256 pictures).
Captured once per batch shape and replayed, the forward is ONE call — and
its pixels are bit-identical to eager's, so the space string stays. MPS and
the CPU have no graphs and run eager.
"""

from __future__ import annotations

import base64
import sys


def device() -> str:  # pragma: no cover - heavy optional dep
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) is not None \
            and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def single_cpu_thread_on(dev: str) -> None:  # pragma: no cover - heavy optional dep
    """On an accelerator the CPU's job is the preprocessing, on the worker's
    decode threads (`prepare`), and torch's intra-op pool fights them: every
    per-picture resize fanned out over 16 OpenMP threads under 32 Python
    threads already busy, and a chunk's upload measured 232 ms against 19
    with one (5090 box). The forward is on the accelerator, where the CPU
    side is kernel launches. A CPU forward keeps the pool."""
    import torch

    if dev != "cpu":
        torch.set_num_threads(1)


def wants_decode_processes(handle) -> bool:  # pragma: no cover - heavy optional dep
    """Whether the worker should decode in PROCESSES rather than threads.
    Only on CUDA: there the forward is 0.35 ms a picture and the decode
    (1.7 on threads, 1.25 in processes, 5090 box) is the bound. On MPS the
    forward is 3.1 ms a picture and on the CPU more, so threads already
    outrun it, and the processes' own start (interpreters importing torch)
    is seconds a job for nothing — measured on an M4 Max: 198 items/s on
    threads, 180 with processes, over 3 000 pictures. Asked before the
    model is loaded (``handle`` None) the answer is "start them": the
    device is not known yet and the spawn hides under the load."""
    return handle is None or handle[2] == "cuda"


def prepare(processor, image):  # pragma: no cover - heavy optional dep
    """The processor's work for ONE picture, as a NUMPY array the worker
    hands `embed` in place of the picture. The worker calls this beside the
    decode (in a decode process, or on the decode thread), so the CPU half
    of a chunk runs on every core and the main thread keeps the GIL for the
    forward: batched on the main thread, an embed chunk's processor took
    450 ms under 32 decode threads where it takes 150 alone.

    THE RESIZE AND THE CROP, NOT THE NORMALIZE: a (3, 224, 224) uint8, the
    processor's own `resize` and `center_crop` in its own order, and its
    `rescale_and_normalize` runs in `finish` over the whole chunk on the
    device — the same float32 subtract-and-divide, so the pixels are
    bit-identical to the processor's one call (verified: vectors equal at
    the stored precision). 150 KB a picture instead of 602: the array comes
    back from a decode PROCESS through a pipe the worker's main process
    drains under its GIL, and at 256 a chunk the float32 form cost the
    forward its overlap (458 items/s, against 468 on threads, 5090 box).
    A processor without torchvision's parts (the PIL fallback) returns its
    whole float32 answer instead, and `finish` leaves that alone."""
    if getattr(processor, "rescale_and_normalize", None) is None \
            or not getattr(processor, "do_center_crop", False):
        return processor(images=[image.convert("RGB")],
                         return_tensors="pt")["pixel_values"][0].numpy()
    import numpy as np
    import torch

    t = torch.from_numpy(np.array(image.convert("RGB"))).permute(2, 0, 1).contiguous()
    if processor.do_resize:
        t = processor.resize(image=t, size=processor.size,
                             resample=processor.resample)
    t = processor.center_crop(t, processor.crop_size)
    return t.numpy()


def finish(processor, pixels):  # pragma: no cover - heavy optional dep
    """`prepare`'s other half, over the chunk: the processor's rescale-and-
    normalize on the device, for a uint8 batch; a float batch is already
    the processor's whole answer."""
    import torch

    if pixels.dtype != torch.uint8:
        return pixels
    return processor.rescale_and_normalize(
        pixels, processor.do_rescale, processor.rescale_factor,
        processor.do_normalize, processor.image_mean, processor.image_std)


class Forward:
    """``forward(pixels) -> (B, D) features on the device`` — the model call
    behind a CUDA graph per batch shape where the device has them, eager
    otherwise. ``take`` picks the feature out of the model's output."""

    #: Graphs kept, by batch size. A job's chunks are one size but its last,
    #: and an appended import's can vary: two covers the run, and a third
    #: shape evicts the oldest rather than growing a pool per shape.
    KEEP = 2
    #: Below this a graph is not worth its capture (three warm-up forwards
    #: plus the capture itself) — the eager call is already short.
    MIN_BATCH = 16

    def __init__(self, model, dev: str, take):
        self.model = model
        self.dev = dev
        self.take = take
        self._graphs: dict = {}
        self._graphs_off = dev != "cuda"

    def _eager(self, pixels):
        return self.take(self.model(pixel_values=pixels))

    def _capture(self, pixels):  # pragma: no cover - CUDA only
        import torch

        static_in = pixels.clone()
        # Warm up on a side stream (cuBLAS workspaces, allocator), then
        # capture: the torch recipe, verbatim.
        s = torch.cuda.Stream()
        s.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(s):
            for _ in range(3):
                self._eager(static_in)
        torch.cuda.current_stream().wait_stream(s)
        g = torch.cuda.CUDAGraph()
        with torch.cuda.graph(g):
            static_out = self._eager(static_in)
        return static_in, static_out, g

    def __call__(self, pixels):
        import torch

        n = int(pixels.shape[0])
        if self._graphs_off or n < self.MIN_BATCH:
            return self._eager(pixels)
        entry = self._graphs.get(n)
        if entry is None:
            try:
                entry = self._capture(pixels)
            except Exception as exc:  # noqa: BLE001 - eager is always right
                print(f"embed: CUDA graph capture failed, running eager: "
                      f"{exc}", file=sys.stderr, flush=True)
                self._graphs_off = True
                torch.cuda.synchronize()
                return self._eager(pixels)
            if len(self._graphs) >= self.KEEP:
                del self._graphs[next(iter(self._graphs))]
            self._graphs[n] = entry
        static_in, static_out, g = entry
        static_in.copy_(pixels)
        g.replay()
        return static_out


def pack(feats, space: str) -> list:  # pragma: no cover - heavy optional dep
    """A chunk's features → one RAW result dict per row, unit-normalized,
    as FLOAT16 BYTES, base64 — the precision the library STORES the vector
    at (`itemvec.pack`), so nothing is lost, and a fifth of the JSON: 384
    floats as text were 8 KB a picture and ~0.14 ms to write and read again
    per image across the process boundary; 768 bytes are ~0.005.

    Returned RAW: the worker's `_marshal` wraps any dict without an
    image/text/tags key as {"value": …} and the host unwraps exactly one
    layer — a plugin wrapping here too double-bagged it once, and
    `_apply_embedding` then found no "vector" and skipped EVERY item
    ("indexed 0 of 378", with nothing anywhere saying why).

    ONE normalize and ONE copy for the chunk: the direction is the feature
    and the classifier's cosine arithmetic expects rows of length 1; a
    per-row loop of tensor ops on the main thread is a hundred GIL
    hand-offs under the decode threads (a zero row stays zero, as before).
    """
    import torch

    vecs = torch.nn.functional.normalize(feats.float(), dim=1)
    rows = vecs.to(torch.float16).cpu().numpy()
    dim = int(rows.shape[1])
    return [{"vector_f16": base64.b64encode(row.tobytes()).decode("ascii"),
             "dim": dim, "space": space} for row in rows]


def embed(handle, images, space: str) -> list:  # pragma: no cover - heavy optional dep
    """One batched forward → one result dict per image, in input order. Each
    entry is a picture, or a tensor `prepare` already made of one — the
    batch path hands over the latter; the single-item path and a host
    without the prepare hook the former."""
    import os as _os
    import time as _time

    import torch

    import numpy as np

    processor, model, dev, forward = handle
    _prof = bool(_os.environ.get("MEDIA_COMPOST_JOB_PROFILE"))
    _t0 = _time.perf_counter()
    # One stack, one copy in: `np.stack` of the chunk's arrays is a memcpy
    # and `from_numpy` shares it.
    pixels = finish(processor, torch.from_numpy(np.stack([
        im if isinstance(im, np.ndarray) else prepare(processor, im)
        for im in images])).to(dev))
    _t1 = _time.perf_counter()
    feats = forward(pixels)
    out = pack(feats, space)
    if _prof:
        # `pack`'s copy to the CPU is what waited for the forward, so the
        # split is taken after it.
        print(f"[job-profile] embed worker: stack+upload {(_t1 - _t0) * 1000:.0f} ms, "
              f"forward {(_time.perf_counter() - _t1) * 1000:.0f} ms for {len(images)} on {dev}",
              file=sys.stderr, flush=True)
    return out

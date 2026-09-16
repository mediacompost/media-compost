"""Tiled super-resolution: a picture of any size through a model whose
memory grows with the pixel count.

A leading underscore, like `_accel.py`: not a plugin, never in
`registry.PLUGIN_MODULES`. Shared by the two upscale plugins.

WHY. Both upscalers used to feed the whole picture through the model at
once. Swin2SR's attention is per 8x8 window, but its activations are still
per pixel and deep (six stages of six blocks at 180 channels), so an
ordinary 1.6 MP picture already wanted more than 16 GB at x2 — and the two
platforms then failed differently: Linux raised an out-of-memory error per
picture (11 of 20 crawl pictures on a 32 GB card, quietly skipped by the
job), Windows never raised, since WDDM spills the card into system memory,
and one picture took minutes at "100 %" with a 75 GB working set.

HOW. A super-resolution model is LOCAL: an output pixel depends on a
neighbourhood of a few dozen input pixels (the receptive field), never on
the picture as a whole. So the picture is cut into tiles that OVERLAP by
`overlap` pixels, each tile is upscaled on its own, and only the tile's
INTERIOR — everything at least `overlap / 2` away from a cut, out to the
picture's own edges — is pasted into the result. A pixel in the interior
sees the same neighbourhood it would in the whole picture, so the tiled
result is the untiled one to within the model's own numerical noise
(`tests/ui/test_upscale_tiling.py` holds it exact for a local operator;
the real models are compared in `research/performance-work.md`). Memory is
bounded by the tile, whatever the picture.

Tiles of one shape go through the model TOGETHER (`batch`): every interior
tile has exactly `tile` x `tile` pixels, so a batched forward is one launch
for several tiles — where a card is idle between small launches this is the
throughput lever; the edge tiles, which differ in shape, go in their own
smaller groups.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Sequence

#: Defaults, MEASURED (5090 box, 5070 Ti, M4 Max; `research/performance-
#: work.md`, tenth pass). TILE 512: the forward's cost per pixel is flat
#: from 256 up and a bigger tile means fewer seams. OVERLAP 96 (48 px of
#: context on each side of a cut): against the untiled forward on a
#: textured picture, 32 left 1-5% of the pixels more than one 8-bit step
#: off (max 17-127 of 255), 64 still 0.3-1% for the x4 models (max 12-15;
#: the real-world Swin2SR's and the RRDB net's receptive fields reach past
#: 32 px), 96 leaves at most 0.16% (max 4-5) — and the differences at 64
#: were NOT confined to a band at the seam, the mark of missing context
#: rather than rounding. Pixels processed: 1.51x the picture at 96
#: against 1.31x at 64, ~13% of the time. BATCH by the card
#: (`default_batch`): two 512 px tiles per forward is within 5% of the
#: untiled speed at 6-8 GB peak (four is 3% faster at twelve; one is
#: 10-20% slower at three to five) — but only a 20 GB card gets the pair
#: (a 16 GB one under Windows spilled). Overridable by environment for
#: a measurement or a small card; `MEDIA_COMPOST_UPSCALE_TILE=0` turns
#: tiling off.
DEFAULT_TILE = 512
DEFAULT_OVERLAP = 96
DEFAULT_BATCH = 2


@dataclass(frozen=True)
class Tile:
    """One tile: the input rectangle the model sees (`x0..x1`, `y0..y1`,
    overlap included) and the interior kept from its output (`ix0..ix1`,
    `iy0..iy1`), both in INPUT pixels; the output rectangles are these
    times the scale."""
    x0: int
    y0: int
    x1: int
    y1: int
    ix0: int
    iy0: int
    ix1: int
    iy1: int

    @property
    def w(self) -> int:
        return self.x1 - self.x0

    @property
    def h(self) -> int:
        return self.y1 - self.y0


def _cuts(length: int, tile: int, overlap: int,
          grid: int = 1) -> list[tuple[int, int, int, int]]:
    """Along one axis: ``(start, end, keep_from, keep_to)`` per tile.

    Tiles start every ``tile - overlap`` pixels (rounded down to a
    multiple of ``grid``); the last one is pulled back to end exactly at
    ``length`` (so it overlaps its neighbour by MORE, never less). The
    interior boundary between two neighbours is the middle of their
    overlap, so every kept pixel is at least ``overlap // 2`` from the cut
    on its side — the context a local model needs.

    ``grid`` > 1 keeps EVERY tile origin on a multiple of it — what a
    windowed net needs (below) — and then ``length`` and ``tile`` must be
    multiples of it too, or the pulled-back last tile would start off the
    grid: the caller pads the picture up to the grid first
    (`run_on_device(pad=)`).
    """
    if grid > 1 and (length % grid or tile % grid):
        raise ValueError("with a grid, the picture and the tile must be "
                         "multiples of it (pad the picture first)")
    if length <= tile:
        return [(0, length, 0, length)]
    step = tile - overlap
    if grid > 1:
        step -= step % grid
    if step <= 0:
        raise ValueError("overlap must be smaller than the tile")
    starts: list[int] = []
    pos = 0
    while True:
        if pos + tile >= length:
            starts.append(length - tile)
            break
        starts.append(pos)
        pos += step
    out = []
    for i, s in enumerate(starts):
        e = s + tile
        keep_from = 0 if i == 0 else (starts[i - 1] + tile + s) // 2
        keep_to = length if i == len(starts) - 1 else (e + starts[i + 1]) // 2
        out.append((s, e, keep_from, keep_to))
    return out


def plan(width: int, height: int, tile: int, overlap: int,
         grid: int = 1) -> list[Tile]:
    """Every tile of a ``width`` x ``height`` picture, in raster order.

    A TILE ORIGIN MUST SIT WHERE THE NET'S WINDOWS DO. A Swin net
    partitions its input into windows anchored at the input's origin (8 px
    for Swin2SR, shifted by 4 every other block), so a tile that starts
    off that grid is partitioned differently from the whole picture and
    its output differs EVERYWHERE, not at the seams: MEASURED (5090 box,
    M4 Max, 5070 Ti — identical), the real-world Swin2SR at 512 px tiles
    on a 1200 x 900 picture had 12% of the pixels more than one 8-bit step
    off (max 62), because the bottom row of tiles was pulled back to start
    at y = 388; the 128 px test tiles had happened to start on multiples
    of 8 and passed. With ``grid=8`` every origin is on the grid and the
    same picture is within one step on 99.99% of its pixels. Convolutional
    nets (Real-ESRGAN) have no grid.
    """
    xs = _cuts(width, tile, overlap, grid)
    ys = _cuts(height, tile, overlap, grid)
    return [Tile(x0, y0, x1, y1, kx0, ky0, kx1, ky1)
            for (y0, y1, ky0, ky1) in ys
            for (x0, x1, kx0, kx1) in xs]


def default_batch(total_bytes: int | None) -> int:
    """Tiles per forward for a device holding ``total_bytes``: two on a
    20 GB card, else one; unknown = one.

    A 512 px pair peaks at 6 GB allocated for Swin2SR x2, 7.4-8.4 for the
    x4 checkpoints — and on a 16 GB card under Windows that was already
    too much: the driver (WDDM) shares the card with the desktop and
    spills silently, and the real-world x4 model took 10.9 s a picture
    in pairs against 6.0 one at a time (a 12 MP picture 381 s). The pair
    buys ~15% on a card with room; one at a time is safe everywhere."""
    if total_bytes is None:
        return 1
    return DEFAULT_BATCH if total_bytes >= 20 * 2**30 else 1


def device_memory(dev: str) -> int | None:  # pragma: no cover - heavy dep
    """What ``dev`` can hold, in bytes: the card's memory, the Mac's
    recommended working set, None for the CPU (no bound to speak of, and
    the batch buys nothing there)."""
    try:
        import torch

        if dev.startswith("cuda"):
            idx = int(dev.split(":")[1]) if ":" in dev else 0
            return int(torch.cuda.get_device_properties(idx).total_memory)
        if dev == "mps":
            return int(torch.mps.recommended_max_memory())
    except Exception:  # noqa: BLE001 - a probe, never a failure
        return None
    return None


def settings(dev: str = "", tile: int | None = None,
             overlap: int | None = None) -> tuple[int, int, int]:
    """``(tile, overlap, batch)`` from the environment, else the defaults
    with the batch sized to ``dev``. ``tile`` and ``overlap`` are the
    net's own defaults where it needs other than `DEFAULT_TILE` /
    `DEFAULT_OVERLAP` (the receptive field is per net;
    `upscale_esrgan._X2PLUS`); the environment still wins."""
    def _int(name: str, default: int) -> int:
        raw = (os.environ.get(name) or "").strip()
        try:
            return int(raw) if raw else default
        except ValueError:
            return default
    batch = default_batch(device_memory(dev) if dev else None)
    return (_int("MEDIA_COMPOST_UPSCALE_TILE",
                 DEFAULT_TILE if tile is None else tile),
            _int("MEDIA_COMPOST_UPSCALE_OVERLAP",
                 DEFAULT_OVERLAP if overlap is None else overlap),
            _int("MEDIA_COMPOST_UPSCALE_BATCH", batch))


def upscale(image, scale: int, forward: Callable[[Sequence], Sequence],
            tile: int = DEFAULT_TILE, overlap: int = DEFAULT_OVERLAP,
            batch: int = DEFAULT_BATCH, empty: Callable | None = None,
            grid: int = 1):
    """``image`` (H x W x C) upscaled ``scale`` times through ``forward``,
    which takes a list of same-shaped H x W x C tiles and returns their
    upscaled counterparts (each ``scale`` times larger; the result carries
    the forward's dtype).

    ARRAY-AGNOSTIC: ``image`` and the forward's answers may be numpy arrays
    or torch tensors — anything sliced by ``[y0:y1, x0:x1]`` and assigned
    the same way — and ``empty(shape, like)`` allocates the result beside
    ``like`` (numpy by default). So a plugin can keep the WHOLE picture on
    the device: upload once, cut tiles there, paste there, download once —
    per-tile host round trips were half the cost of the fast model.

    ``tile <= 0`` sends the whole picture through in one call.
    """
    h, w = image.shape[:2]
    if tile <= 0:
        return forward([image])[0]
    if empty is None:
        import numpy as np

        def empty(shape, like):
            return np.empty(shape, dtype=like.dtype)
    tiles = plan(w, h, tile, overlap, grid)
    out = None
    # Same-shaped tiles are forwarded together; the groups keep raster
    # order within themselves so the caller's batches are predictable.
    groups: dict[tuple[int, int], list[Tile]] = {}
    for t in tiles:
        groups.setdefault((t.h, t.w), []).append(t)
    for _shape, members in groups.items():
        for i in range(0, len(members), max(1, batch)):
            chunk = members[i:i + max(1, batch)]
            results = forward([image[t.y0:t.y1, t.x0:t.x1] for t in chunk])
            for t, res in zip(chunk, results):
                if out is None:
                    out = empty(tuple((h * scale, w * scale)) + tuple(res.shape[2:]), res)
                sy, sx = (t.iy0 - t.y0) * scale, (t.ix0 - t.x0) * scale
                ey, ex = (t.iy1 - t.y0) * scale, (t.ix1 - t.x0) * scale
                out[t.iy0 * scale:t.iy1 * scale,
                    t.ix0 * scale:t.ix1 * scale] = res[sy:ey, sx:ex]
    return out


def to_uint8(nchw):  # pragma: no cover - heavy dep
    """A model's N x 3 x H x W float answer in [0, 1] -> N x H x W x 3
    uint8, ON THE DEVICE, PER TILE. The result buffer of a x4 upscale of a
    12 MP picture is 2.3 GB as float32 and a second copy of that for the
    conversion at the end — on a 16 GB card under Windows that was the
    spill; as bytes it is 0.55 GB and there is no copy. Same rounding as
    before (clamp, x255, round half to even), just earlier."""
    import torch

    return (nchw.float().clamp(0, 1).mul_(255.0).round_()
            .to(torch.uint8).permute(0, 2, 3, 1))


def run_on_device(image, dev: str, scale: int, forward, tile: int,
                  overlap: int, batch: int, grid: int = 1,
                  pad: Callable | None = None):  # pragma: no cover - heavy dep
    """A PIL picture -> the upscaled PIL picture, the whole thing resident
    on ``dev``: one upload of the uint8 picture, tiles cut and pasted
    there — as BYTES (`to_uint8`), so the result of a x4 upscale of a big
    picture is a quarter of the float buffer it was — one download of the
    finished 8-bit result. Upload contiguous (a strided host-to-device
    copy goes element by element).

    ``pad(tensor)`` (H x W x 3 uint8 on the device -> the same, padded)
    is applied to the WHOLE picture before it is tiled, and the result is
    cropped back to ``scale`` x the original: a windowed net's own
    padding rule, so that the picture the tiles are cut from is exactly
    the one the untiled forward would see (`plan`'s grid).
    """
    import numpy as np
    import torch
    from PIL import Image

    arr = np.ascontiguousarray(np.asarray(image.convert("RGB")))
    h, w = arr.shape[:2]
    with torch.inference_mode():
        src = torch.from_numpy(arr).to(dev)
        if pad is not None:
            src = pad(src)
        out = upscale(src, scale, forward, tile=tile, overlap=overlap,
                      batch=batch, grid=grid,
                      empty=lambda shape, like: torch.empty(
                          shape, dtype=like.dtype, device=like.device))
        out = out[:h * scale, :w * scale]
        if out.dtype != torch.uint8:      # a forward that answers in floats
            out = out.mul(255.0).round_().clamp_(0, 255).to(torch.uint8)
        out8 = out.contiguous().cpu().numpy()
    return Image.fromarray(out8)


#: Full-tile batches a worker runs eagerly before it compiles the network
#: for that shape: the compile pays for itself only over a job of several
#: pictures (below).
COMPILE_AFTER = 8


def wants_compile(dev: str) -> bool:
    """Whether to `torch.compile` the network on ``dev``: CUDA with a
    triton to build kernels (never on Windows, where there is none by
    default, never on MPS). `MEDIA_COMPOST_UPSCALE_COMPILE=0` turns it
    off, `=1` forces it."""
    raw = (os.environ.get("MEDIA_COMPOST_UPSCALE_COMPILE") or "").strip()
    if raw:
        return raw not in ("0", "false", "no")
    if not dev.startswith("cuda"):
        return False
    import importlib.util

    return importlib.util.find_spec("triton") is not None


def _compile(net):  # pragma: no cover - heavy dep; patched by the test
    import torch

    return torch.compile(net, dynamic=False)


class LazyCompiled:
    """The network, compiled for the FULL tile's shape once a job has
    shown it is worth it — eager for everything else, and eager again if
    the compiled one ever fails.

    MEASURED (5090 box): `torch.compile` makes the Swin2SR forward 1.66x
    and the RRDB net's 1.75x faster at one fixed shape (a pair of 512 px
    tiles: 990 -> 596 ms and 100 -> 57 ms), outputs within 0.1 and 0.75
    of an 8-bit step. It costs 25 s / 6 s the first time a process sees a
    shape (4 s / 0.6 s with inductor's disk cache warm) and dynamo went
    DYNAMIC after a handful of distinct shapes and then failed on this
    model's padding arithmetic ("CantSplit") — so only the full tile's
    shape is ever compiled (`dynamic=False`; a batch of one and of two are
    two graphs), an odd-sized small picture stays eager, and a worker
    runs `COMPILE_AFTER` full-tile batches eagerly first: a single
    1200 x 900 picture (three pairs, 1.2 s to gain) never pays the 25 s.
    """

    def __init__(self, net: Any, dev: str, tile: int):
        self.net = net
        self.tile = tile
        self.enabled = wants_compile(dev)
        self.compiled: Any = None
        self.seen = 0

    def is_full(self, tiles) -> bool:
        return all(t.shape[0] == self.tile and t.shape[1] == self.tile
                   for t in tiles)

    def pick(self, tiles) -> Any:
        """The network to run ``tiles`` through."""
        if not self.enabled or not self.is_full(tiles):
            return self.net
        self.seen += 1
        if self.seen < COMPILE_AFTER:
            return self.net
        if self.compiled is None:
            try:
                self.compiled = _compile(self.net)
                print(f"upscale: compiling the network for {self.tile} px "
                      "tiles (first call is slow)", flush=True)
            except Exception as exc:  # noqa: BLE001 - eager is always there
                self.give_up(exc)
                return self.net
        return self.compiled

    def give_up(self, exc: Exception) -> None:
        """A compiled call failed: back to eager for good, saying why."""
        self.enabled = False
        self.compiled = None
        print(f"upscale: torch.compile unusable here ({str(exc)[:200]}); "
              "running eagerly", flush=True)

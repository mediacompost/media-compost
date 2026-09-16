"""The on-disk shape of a cached VAE latent. numpy + zlib only — no torch.

A latent cache entry is a permanent artifact of the library file it was encoded
from (see ``dataset._latents``), one per file x base model x bucket, doubled by
the flipped copy and again by a masked run's ``-am`` marker, so a library that
has trained a few models at a few resolutions holds thousands of them and they
are never evicted except when the pixels under them change.

They are stored **compressed and losslessly**. Measured over the 1324 real
entries in the demo library, re-encoded and read back through the trainer's own
writer: **55.91 MB of files becomes 40.76 MB, 27.1% saved** (chroma 67.4%,
sd15 67.7%, FLUX.2 Klein 71.2%, sdxl 79.3% of their payloads). That library is
mostly line art; photographs will land a few points worse, and how compressible
a latent is at all is a fact about the model's VAE as much as about the picture.

**What it costs is CPU on the read path and nothing else.** Per latent at each
model's native area, decode against a plain load: sd15 512² +0.10 ms, sdxl
1024² +0.31, chroma/FLUX.1 1024² +1.29, Qwen-Image 1328² +2.12, FLUX.2 Klein
1024² +2.57 - so at batch 4 x accumulation 2, between 0.8 and 21 ms a step,
against the ~7 s a step Qwen-Image measures on an M4 Max. Peak RSS rises by at
most 4.9 MB (one decompressed buffer plus its copy) and does NOT grow with the
run: 500 reads and 4 reads peak the same. Writing costs 0.4-14.8 ms a latent,
paid once per entry in the caching phase, which is dominated by the VAE encode.
**The smaller file buys almost nothing back on disk** - a cold read past the
page cache is 0.011-0.065 ms at these sizes, so the 27% is 0.002-0.037 ms and
the trade is honestly CPU-for-bytes rather than a wash.

**LOSSLESS is the whole point, and the lossy alternatives were measured and
rejected**: the latent is the regression TARGET, and halving the file with
int8-plus-scale (42.4 dB) or fp8 e4m3 (31.4 dB) costs 5x and 25x the error of
the fp16 -> bf16 cast the trainer already makes on the way to the device
(55.2 dB). What that buys is a slightly worse LoRA with nothing anywhere saying
so, which is exactly the failure a cache may not have.

**The BYTE-SHUFFLE is worth 4.7 points**: fp16 values sit in
about +-4, so the high byte of every one of them carries a handful of distinct
exponents while the low byte is nearly random. Interleaved, the compressor sees
one alternating stream and finds little; split into a plane of high bytes
followed by a plane of low bytes, the redundant half compresses on its own.
(Over the same entries: 77.3% without it, 72.6% with.)

**Level 1, deliberately.** Measured on SDXL latents, zlib levels 1/3/6/9 keep
78.3 / 77.9 / 77.1 / 77.0% at 73 / 62 / 43 / 31 MB/s — so every level above the
first pays a shrinking amount of caching time for a rounding error of a saving.
Inflating is ~450-550 MB/s whichever level wrote it, so the choice costs the
read path nothing.

zlib rather than zstd because it is in the standard library, and
the trainer is standalone: it may not import ``media_compost``, and a
new package in the training env for 3 points would have to be installed before
any older env could read a cache written by a newer one.

**THE PAYLOAD MUST NOT REACH ``torch.save`` AS ``bytes``, and this cost the
whole feature once.** ``torch.save`` pickles at **protocol 2** by default,
which has no opcode for ``bytes`` at all: Python 3 falls back to storing it as
a latin-1 STRING, so every byte above 0x7f becomes two - and compressed data is
about half such bytes. Measured over the 1324 real entries: raw 55.35 MB,
packed-as-bytes **60.10 MB**, i.e. compression that made the cache 8.6% BIGGER,
while the payloads themselves were a genuine 72.6%. The caller therefore hands
``z`` to ``torch.save`` as a uint8 TENSOR (40.76 MB, 73.6%), which the zip
container stores as its own raw record and no pickle protocol can touch.
``pickle_protocol=4`` fixes it too and half a point better (40.47 MB), and is
rejected: it is a keyword on every save that anybody may forget, guarding a
failure whose only symptom is files quietly growing.

So ``z`` goes OUT as ``bytes`` and comes back IN as anything ``zlib`` reads -
``decode`` is deliberately indifferent, which is what keeps this module free of
torch.
"""

from __future__ import annotations

import zlib

import numpy as np

# Only the FORMAT is a promise; this is the writer's choice and may move.
LEVEL = 1


def encode(arr: np.ndarray) -> dict:
    """One array as the record ``decode`` reads back.

    The shape and dtype travel with the bytes because zlib is given a flat
    buffer and cannot say what it was.
    """
    arr = np.ascontiguousarray(arr)
    return {
        "z": zlib.compress(_shuffle(arr), LEVEL),
        "shape": list(arr.shape),
        "dtype": arr.dtype.str,          # '<f2' - byte order included
    }


def decode(rec: dict) -> np.ndarray:
    """The array back, bit for bit.

    ``rec["z"]`` may be anything ``zlib`` reads — bytes, a memoryview, a numpy
    array — because the caller stores it as a tensor and unwraps it there (see
    the module docstring).
    """
    dtype = np.dtype(rec["dtype"])
    flat = _unshuffle(zlib.decompress(rec["z"]), dtype)
    return flat.reshape(tuple(rec["shape"]))


def _shuffle(arr: np.ndarray) -> bytes:
    """All the first bytes of every value, then all the second, and so on.

    A transpose of the (values, bytes-per-value) view — which makes it and
    ``_unshuffle`` visibly each other's inverse. Written for any itemsize
    rather than hardcoding fp16's two: the mask is stored the same way, and an
    engine whose latents are not fp16 must not silently get a corrupt entry.
    """
    planes = arr.view(np.uint8).reshape(-1, arr.dtype.itemsize)
    return planes.T.tobytes()          # `tobytes` reads in C order, so: by plane


def _unshuffle(buf: bytes, dtype: np.dtype) -> np.ndarray:
    """The inverse of ``_shuffle``: the planes interleaved back into values.

    A COLUMN AT A TIME rather than the transpose this is the inverse of.
    `np.ascontiguousarray(planes.T)` says it in one obvious line and is **3.8x
    slower** — measured on a 1 MB FLUX.2 Klein latent, 1.033 ms against 0.271,
    which is a third of the whole decode. The transpose is a general strided
    gather; a plane is one contiguous read into one strided write, which is
    the shape numpy is fast at. (The other direction shows no such gap - 0.273
    against 0.291 - so ``_shuffle`` keeps the readable spelling.)

    Either way it COPIES, which is required rather than tidy: a `frombuffer`
    array is read-only, and `torch.from_numpy` on one warns about it — once
    per latent per step, into the training log.
    """
    n = dtype.itemsize
    planes = np.frombuffer(buf, dtype=np.uint8).reshape(n, -1)
    out = np.empty((planes.shape[1], n), dtype=np.uint8)
    for i in range(n):
        out[:, i] = planes[i]
    return out.view(dtype).reshape(-1)

"""Making a picture look worse, on purpose.

A training run can carry a list of degradation *variants* (``spec.DegradeVariant``)
— JPEG re-encoding, a video-codec round-trip, resolution loss — and each one adds
an EXTRA sample beside the clean picture rather than replacing it. This module is
the whole of what a variant does to pixels, plus the two pure functions that
decide *which* pixels: :func:`draw` and :func:`key`.

**Every numeric parameter is a range**, and the value in force is drawn from it.
A dataset where every degraded picture sits at exactly q30 teaches the model one
artifact strength; one spanning a range teaches it the axis.

**The draw happens here and not in the trainer**, once per ``(file, variant, i)``
and seeded on exactly that, for three reasons that all point the same way: the
trainer runs in a Pillow-only venv with no ffmpeg and cannot produce these
pixels at all; a cached artifact has to be one fixed thing, so a range can never
be a cache key; and seeding per FILE makes the dataset span the range
continuously instead of every picture landing on the same ladder of N steps.
Determinism is what lets a re-run reuse the cache rather than draw fresh values.

**The file's seed is its SHA256, not its row id.** Both are per-file and both
are stable within one library, which is all the paragraph above asks for — but
a row id is a fact about an INSERTION ORDER, and that is the wrong thing for a
value baked into a filename. The same picture in two libraries drew two
different qualities; re-importing a library from its folders redrew every one
of them; and a golden that recorded the drawn names could only hold while
nothing was inserted before it (which is exactly how
`tests/train/test_training_manifest_golden.py` came to fail the moment its
module was split across xdist workers). The content hash is the same picture's
seed everywhere, forever, which is what "deterministic" was reaching for.

:func:`key` names the drawn values, never the variant's name, tags or weight —
none of those is a property of the pixels, so editing them must not throw the
cache away, while moving a range end must.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from typing import Any

from PIL import Image

from media_compost import MediaUnreadable, codec_roundtrip

#: Pillow's `subsampling` argument, by the name the config uses.
_SUBSAMPLING = {"4:4:4": 0, "4:2:2": 1, "4:2:0": 2}

_RESAMPLE = {
    "nearest": Image.NEAREST,
    "bilinear": Image.BILINEAR,
    "bicubic": Image.BICUBIC,
    "lanczos": Image.LANCZOS,
}


class DegradeError(Exception):
    """A variant that cannot run on this machine (a missing encoder)."""


@dataclass(frozen=True)
class Drawn:
    """One variant with every range resolved to a value."""

    method: str
    passes: int
    quality: int = 0
    subsampling: str = "4:2:0"
    codec: str = "h264"
    crf: int = 0
    scale: float = 1.0
    resample: str = "bilinear"


def _rand(seed_parts: tuple[Any, ...]) -> float:
    """A stable float in [0, 1) for a tuple of ids.

    A hash rather than ``random.Random``: this has to give the same answer in a
    later process, on another machine and after a Python upgrade, because the
    files it names are already on disk. ``random``'s stream is documented as
    stable but its *seeding* of arbitrary objects is not, and nothing here
    needs a sequence — only one number per draw.
    """
    raw = "\x1f".join(str(p) for p in seed_parts).encode("utf-8")
    digest = hashlib.sha256(raw).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def _pick_int(rng: float, lo: int, hi: int) -> int:
    return lo if hi <= lo else lo + int(rng * (hi - lo + 1))


def _pick_float(rng: float, lo: float, hi: float) -> float:
    return lo if hi <= lo else lo + rng * (hi - lo)


def ranges_key(variant) -> str:
    """The variant's *shape* — what the draws depend on.

    Only the method and the ranges it actually reads: two variants agreeing on
    these share every draw, and a variant whose tags or weight changed keeps
    its cache. This is the seed component, not the filename.
    """
    m = variant.method
    if m == "jpeg":
        body = (f"jpeg-{variant.quality.lo}:{variant.quality.hi}"
                f"-{variant.subsampling}")
    elif m == "video":
        body = f"{variant.codec}-{variant.crf.lo}:{variant.crf.hi}"
    elif m == "resize":
        body = (f"resize-{variant.scale.lo:.4f}:{variant.scale.hi:.4f}"
                f"-{variant.resample}")
    else:  # pragma: no cover - the Literal keeps this unreachable
        body = m
    return f"{body}-x{variant.passes.lo}:{variant.passes.hi}"


def file_seed(sha256: str, file_id: int) -> str:
    """What identifies a file to :func:`draw`: its CONTENT, where there is one.

    ``sha256`` is the picture itself, so the same bytes draw the same values in
    every library, across a re-import and across a rebuild from item folders.
    That is what the row id could not do, and the row id is what a drawn value
    baked into a filename must not depend on.

    An EMPTY hash falls back to the row id rather than to a constant: a sidecar
    restore writes ``sha256=fe.get("sha256") or ""`` for a file whose folder did
    not record one, and seeding every such file identically would put them all
    on the same rung of the ladder — the one failure the per-file seed exists to
    avoid. Rare, and it degrades to exactly the old behaviour rather than to a
    wrong one.
    """
    return sha256 or f"id:{file_id}"


def draw(variant, seed: str | int, i: int = 0) -> Drawn:
    """Resolve ``variant``'s ranges for one file's ``i``-th variation.

    ``seed`` is :func:`file_seed`'s answer. It is typed loosely because
    ``_rand`` stringifies whatever it is given, and a caller that still passes
    an int gets the values this drew before the hash — which is what keeps the
    fallback above honest rather than special.
    """
    shape = ranges_key(variant)
    n = _pick_int(_rand((seed, shape, i, "passes")),
                  variant.passes.lo, variant.passes.hi)
    if variant.method == "jpeg":
        return Drawn(method="jpeg", passes=n, subsampling=variant.subsampling,
                     quality=_pick_int(_rand((seed, shape, i, "quality")),
                                       variant.quality.lo, variant.quality.hi))
    if variant.method == "video":
        return Drawn(method="video", passes=n, codec=variant.codec,
                     crf=_pick_int(_rand((seed, shape, i, "crf")),
                                   variant.crf.lo, variant.crf.hi))
    return Drawn(method="resize", passes=n, resample=variant.resample,
                 scale=_pick_float(_rand((seed, shape, i, "scale")),
                                   variant.scale.lo, variant.scale.hi))


def key(drawn: Drawn) -> str:
    """The cache key: what is actually in the file, said in one filesystem-safe
    token.

    No dots — the same string names a file and is split back out of one, and
    the latent cache's name is already parsed on ``-``. So a scale of 0.52
    writes ``052``.
    """
    if drawn.method == "jpeg":
        sub = drawn.subsampling.replace(":", "")
        body = f"jpeg-q{drawn.quality}-s{sub}"
    elif drawn.method == "video":
        body = f"{drawn.codec}-crf{drawn.crf}"
    else:
        body = f"resize-{round(drawn.scale * 100):03d}-{drawn.resample}"
    return body if drawn.passes <= 1 else f"{body}-x{drawn.passes}"


def output_format(drawn: Drawn) -> str:
    """The extension the degraded picture is stored under.

    A JPEG variant keeps the real compressed bytes — they *are* the artifact,
    and re-wrapping them losslessly would only cost disk. Everything else has
    already been decoded back to pixels, so it goes in a PNG.
    """
    return "jpg" if drawn.method == "jpeg" else "png"


def _jpeg_once(img: Image.Image, quality: int, subsampling: str) -> Image.Image:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=int(quality),
                            subsampling=_SUBSAMPLING.get(subsampling, 2))
    buf.seek(0)
    out = Image.open(buf)
    out.load()
    return out.convert("RGB")


def _resize_once(img: Image.Image, scale: float, resample: str) -> Image.Image:
    """Down and back UP — resolution *loss*, not a smaller picture.

    Keeping the size identical is what lets the degraded entry share its
    source's bucket and its bounding boxes untouched, so nothing downstream has
    to learn that this one picture is a different shape.
    """
    filt = _RESAMPLE.get(resample, Image.BILINEAR)
    w, h = img.size
    small = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
    return img.convert("RGB").resize(small, filt).resize((w, h), filt)


def apply(img: Image.Image, drawn: Drawn) -> Image.Image:
    """``img`` put through ``drawn``, ``passes`` times over."""
    out = img.convert("RGB")
    for _ in range(max(1, drawn.passes)):
        if drawn.method == "jpeg":
            out = _jpeg_once(out, drawn.quality, drawn.subsampling)
        elif drawn.method == "video":
            try:
                out = codec_roundtrip(out, drawn.codec, drawn.crf)
            except MediaUnreadable as exc:
                raise DegradeError(str(exc)) from exc
        else:
            out = _resize_once(out, drawn.scale, drawn.resample)
    return out


def encode(img: Image.Image, drawn: Drawn) -> bytes:
    """The stored bytes for a degraded picture.

    A JPEG variant's LAST pass is written straight out at its own quality
    rather than re-encoded, so the file holds exactly the pixels the trainer
    will read — a JPEG decoded and re-saved is a second generation nobody
    asked for.
    """
    out = img.convert("RGB")
    buf = io.BytesIO()
    if drawn.method == "jpeg":
        for _ in range(max(0, drawn.passes - 1)):
            out = _jpeg_once(out, drawn.quality, drawn.subsampling)
        out.save(buf, "JPEG", quality=int(drawn.quality),
                 subsampling=_SUBSAMPLING.get(drawn.subsampling, 2))
    else:
        apply(out, drawn).save(buf, "PNG")
    return buf.getvalue()

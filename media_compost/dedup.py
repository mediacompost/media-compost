"""Deduplication primitives: exact (sha256) and perceptual (pHash) matching.

The perceptual hash is a 256-bit imagehash pHash (16x16), stored in the DB as a
hex string and compared as an int (Hamming distance). Two images are candidates
for merging when that distance is at or below ``Config.phash_threshold``; before
they are actually merged a secondary pixel check (:func:`verify_match`) must also
agree, which reduces false-positive merges of structurally similar but different
images.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import imagehash
import numpy as np
from PIL import Image

# imagehash hash_size (16 => 16x16 = 256 bits). Kept in sync with
# 256 == 16*16; exposed here so pure helpers stay
# config-free.
HASH_SIZE = 16


#: What a transparent pixel is composited onto before anything looks at it.
#:
#: MID-GREY, and the choice is the whole point: over WHITE a white logo
#: disappears again and over BLACK a black one does, while against grey both
#: leave structure behind. An OPAQUE picture is untouched by the compositing,
#: which is what keeps every hash this app has already stored for one exactly
#: as it was.
_ALPHA_BG = (128, 128, 128)


def flatten_alpha(im: Image.Image) -> Image.Image:
    """Composite ``im`` over `_ALPHA_BG`, so what alpha hides is still SEEN.

    `convert("RGB")` and `convert("L")` DISCARD the alpha channel — they do not
    composite — so a picture whose shape lives only in its alpha came out a
    flat rectangle of whatever RGB happened to sit under the transparency.
    A white-on-transparent logo (an X, a watermark, a sticker) became a
    UNIFORM WHITE SQUARE: one distinct colour, no structure at all.

    That is the degenerate-pHash case this module's own docstring warns about,
    reached by accident. Measured on a 512x512 white X: its hash came out
    `8000…0000`, which is Hamming **0** from a pure white frame and from a
    flat grey one — so it matched the blank moments (a fade, a title card,
    letterboxing) of every film in the library, and the frame-link path takes
    a pHash hit and an aspect ratio without a pixel check. Hence "the logo is
    a frame of this video", over and over.

    Applied to BOTH the hash and the verifier's grayscale, because the two
    were blind in the same way and either alone still lets a wrong match
    through.
    """
    if im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info:
        rgba = im.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (*_ALPHA_BG, 255))
        return Image.alpha_composite(bg, rgba)
    return im


def compute_phash_image(im: Image.Image, hash_size: int = HASH_SIZE) -> str:
    """Return the perceptual hash of a PIL image as a hex string."""
    return str(imagehash.phash(flatten_alpha(im).convert("RGB"),
                               hash_size=hash_size))


def compute_phash(path: Path, hash_size: int = HASH_SIZE) -> str:
    """Return the perceptual hash of an image file as a hex string."""
    with Image.open(path) as im:
        return compute_phash_image(im, hash_size=hash_size)


def phash_to_int(hexstr: str) -> int:
    """Parse a stored hex pHash into an int for fast bit comparison."""
    return int(hexstr, 16)


def hamming(a: int, b: int) -> int:
    return int(a ^ b).bit_count()


def find_similar(
    candidate_phash: int,
    existing: list[tuple[int, int]],
    threshold: int,
) -> int | None:
    """Return the file_id of the closest existing file within ``threshold``.

    ``candidate_phash`` and the second element of each ``existing`` pair are
    *ints* (parse hex with :func:`phash_to_int`). Returns None if none are within
    the threshold.
    """
    best_id: int | None = None
    best_dist = threshold + 1
    for file_id, ph in existing:
        if ph is None:
            continue
        d = hamming(candidate_phash, ph)
        if d < best_dist:
            best_dist = d
            best_id = file_id
    return best_id if best_dist <= threshold else None


def norm_gray(im: Image.Image, size: int = 32) -> list[float]:
    """The 32x32 normalized grayscale vector :func:`verify_match` compares.

    Public because it is the whole of what the near-duplicate verifier needs
    from the INCOMING side of a comparison — so a prefetch can compute it off
    the decoded picture and drop the pixels (`importer.PreparedImage.gray32`),
    and the serial import never re-decodes a multi-megabyte file to answer a
    question about 1024 gray values."""
    small = flatten_alpha(im).convert("L").resize((size, size), Image.BILINEAR)
    return [p / 255.0 for p in small.tobytes()]


# --- rotate/flip detection (the importer's whole-image "edit" detection) ---
#
# We no longer do crop-resistant hashing (it produced too many false positives).
# The only derived-image relationship detected on import is a *whole-image*
# reorientation: one of the eight dihedral transforms (four rotations, each with
# an optional mirror), i.e. the 90/180/270° rotations, the horizontal/vertical
# flips, and their combinations. Those are found purely by a cheap pixel check
# over small cached grayscale thumbnails.

# Side length of the square grayscale thumbnail used for the orientation-invariant
# pixel check. Cached per file so verification never re-decodes a candidate.
CANON_SIZE = 48


def canon_thumb(im: Image.Image) -> "np.ndarray":
    """A square 48x48 grayscale float array (0..1) for fast pixel comparison.

    Squaring the aspect ratio makes a 90° rotation comparable to the original via
    a plain array rotate (see :func:`whole_image_edit`)."""
    return (
        np.asarray(
            flatten_alpha(im).convert("L")
            .resize((CANON_SIZE, CANON_SIZE), Image.BILINEAR),
            dtype=np.float32,
        )
        / 255.0
    )


def whole_image_edit(
    a: "np.ndarray", b: "np.ndarray", mse_bound: float
) -> Optional[str]:
    """Classify whether ``b`` is a *whole-image* reorientation of ``a`` — the
    same picture rotated and/or flipped (optionally also rescaled/recompressed).

    Compares ``a`` against all eight dihedral orientations of ``b`` (four
    rotations × optional mirror) and, when the best mean-squared error is within
    ``mse_bound``, returns a label: ``"same"`` (identity/rescale, no
    reorientation), ``"rotate"`` (a 90/180/270° turn) or ``"flip"`` (a mirror,
    possibly combined with a rotation). Returns ``None`` when no orientation
    matches — i.e. the two are simply different pictures.
    """
    best_mse = float("inf")
    best_label: Optional[str] = None
    for k in range(4):
        rot = np.rot90(b, k)
        for mirrored, arr in ((False, rot), (True, np.fliplr(rot))):
            diff = a - arr
            mse = float(np.mean(diff * diff))
            if mse < best_mse:
                best_mse = mse
                best_label = "flip" if mirrored else ("rotate" if k else "same")
    return best_label if best_mse <= mse_bound else None


def norm_rgb(im: Image.Image, size: int = 32) -> list[float]:
    """The 32x32 normalized RGB vector :func:`verify_match` compares — three
    channels where :func:`norm_gray` had one, because grayscale is COLOUR
    BLIND in exactly the place the verifier is trusted most: a solid red and
    a solid blue whose grays coincide measured 0.010 under the 0.020 bound
    and merged, while their RGB distance is 0.335. Measured over fifty crawl
    images, the same picture re-encoded is within 0.00001 and at a third the
    size and JPEG q70 within 0.00008 — 250x under the bound — so nothing the
    near-dup rule means to fold moves, and what a gray vector waved through
    cannot pass. Public for the same reason as `norm_gray`: the prefetch
    computes it off the decoded picture and drops the pixels."""
    small = flatten_alpha(im).convert("RGB").resize((size, size),
                                                    Image.BILINEAR)
    return [p / 255.0 for p in small.tobytes()]


def verify_match(a: Image.Image, b: Image.Image, mse_bound: float) -> bool:
    """Confirm two images are the same picture (not just similar structure).

    Downscales both to 32x32 RGB and compares normalized mean-squared error;
    returns True when it is at or below ``mse_bound``. Cheap and robust to
    small edits/recompression while rejecting genuinely different images that
    happen to share a perceptual hash neighborhood — including ones a
    GRAYSCALE compare could not tell apart (see :func:`norm_rgb`).
    """
    return verify_vec(norm_rgb(a), b, mse_bound)


def verify_vec(va: "list[float]", b: Image.Image, mse_bound: float) -> bool:
    """:func:`verify_match` with the incoming side already a :func:`norm_rgb`
    vector — what the importer's prefetch hands across a process boundary."""
    vb = norm_rgb(b)
    n = len(va)
    if n == 0 or len(vb) != n:
        return False
    mse = sum((x - y) * (x - y) for x, y in zip(va, vb)) / n
    return mse <= mse_bound


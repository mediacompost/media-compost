"""What colour a picture IS, for ordering and browsing — never for matching.

Two values per raster file, both derived from the same one pass over a
downscaled copy:

``color_key``
    A 16-bit **sortable** key. Ordering by it numerically reads as a gradient:
    black → grey → white, then red → orange → brown → yellow → green → teal →
    blue → purple → pink, and within each of those by hue, then lightness,
    then chroma. It is *not* a hash — two different pictures of the same
    orange sunset land next to each other and that is the whole point.

``color_sig``
    A 56-bit colour PRESENCE hash: one bit per fixed (hue, lightness) bucket
    the picture spends more than a threshold share of itself in. Compared by
    Hamming distance, so "these two have similar palettes" is a bit count.

**Neither may be read by dedup.** `dedup.py` / `dedup_index.py` decide what
counts as a duplicate, and they do it with the 256-bit perceptual hash plus
`dedup.verify_match`. Colour is a browsing aid: two unrelated photographs of
the same blue sky are the same colour and are not the same picture. Wiring
either of these into matching would change what the library considers a
duplicate without anything saying so — which is why they live here, in a
module dedup does not import, rather than beside `compute_phash_image`.

The band is packed into the key's HIGH bits, which is what lets the grid group
by colour with `color_key >> 12` — no `CASE`, and the tag set defined once,
here, rather than a second time in SQL.

**Colour says little about line art, and that is not a bug.** Measured over
this library's own demo set, 31 of 39 pictures land in white or grey — they
are manga pages, and a manga page IS a white page with ink on it. Palette
similarity between two of them is near-meaningless there (30% of unrelated
pairs fall inside the same-picture radius, against 0.34% on colour-diverse
content). The colour SORT still earns its place on such a library — ordering
white by lightness is ordering pages by how much ink is on them — but
`COLORLIKE:` is a tool for photographs. Do not "fix" it against a manga
sample.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image

# ---- the tag set ---------------------------------------------------------

#: The fixed colour bands, in the order they sort. The index IS the value the
#: grid groups by (``color_key >> BAND_SHIFT``); the frontend holds the
#: matching name and swatch. Twelve, deliberately: a browsing tag set that
#: somebody scans in one glance, not a colour space.
BANDS = (
    "black", "grey", "white",
    "red", "orange", "brown", "yellow", "green", "teal", "blue",
    "purple", "pink",
)
BAND_SHIFT = 12

#: Chroma below this is no hue at all — the pixel is on the grey axis and its
#: hue is whatever rounding noise says. In OKLab units.
ACHROMATIC_C = 0.035

#: Lightness cuts between black / grey / white, in OKLab L. sRGB 25% grey is
#: about 0.40 and 75% about 0.79, so these sit either side of "clearly dark"
#: and "clearly light" rather than splitting the range in thirds.
DARK_L = 0.38
LIGHT_L = 0.80

#: OKLCh hue of sRGB red, in degrees. Subtracted from every hue so the wheel
#: STARTS at red and the gradient reads red → orange → … → pink, rather than
#: starting wherever the +a axis happens to fall (magenta).
RED_ORIGIN_DEG = 29.23

#: Upper bound of each chromatic band, in red-origin degrees. Read in order;
#: a hue at or past the last one has wrapped back into red.
_HUE_CUTS = (
    (15.0, "red"),
    (50.0, "orange"),
    (95.0, "yellow"),
    (145.0, "green"),
    (200.0, "teal"),
    (265.0, "blue"),
    (310.0, "purple"),
    (345.0, "pink"),
)

#: Brown is the one band that is not a hue: it is dark orange-to-yellow. So it
#: is a lightness cut INSIDE that hue range rather than a slice of the wheel,
#: which is also why it sorts between orange and yellow rather than beside
#: them.
BROWN_HUE = (15.0, 95.0)
BROWN_MAX_L = 0.55


# ---- sRGB -> OKLab ----------------------------------------------------------

def _srgb_to_oklab(rgb: np.ndarray) -> np.ndarray:
    """``(N, 3)`` sRGB in 0..1 to ``(N, 3)`` OKLab (Ottosson's matrices)."""
    c = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    r, g, b = c[:, 0], c[:, 1], c[:, 2]
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = np.cbrt(l), np.cbrt(m), np.cbrt(s)
    return np.stack([
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    ], axis=1)


def _hue_deg(a: float, b: float) -> float:
    """Hue in degrees, rotated so sRGB red is 0."""
    return (math.degrees(math.atan2(b, a)) - RED_ORIGIN_DEG) % 360.0


def _band_for(light: float, chroma: float, hue: float) -> int:
    """Which of :data:`BANDS` a mean colour falls in."""
    if chroma < ACHROMATIC_C:
        if light < DARK_L:
            return BANDS.index("black")
        return BANDS.index("grey" if light < LIGHT_L else "white")
    if BROWN_HUE[0] <= hue < BROWN_HUE[1] and light < BROWN_MAX_L:
        return BANDS.index("brown")
    for cut, name in _HUE_CUTS:
        if hue < cut:
            return BANDS.index(name)
    return BANDS.index("red")  # wrapped past pink


# ---- the key ----------------------------------------------------------------

#: Longest side the image is reduced to before any of this. The answer is one
#: colour for the whole picture, so resolution buys nothing but time.
SAMPLE_PX = 48


def _pack_key(light: float, chroma: float, hue: float) -> int:
    """``(band << 12) | sub`` — 16 bits.

    ``sub`` orders WITHIN the band and means different things per band, which
    is the point of putting the band on top: an achromatic band has no hue to
    order by and wants every bit it can get for the lightness ramp, while a
    chromatic one wants hue first.
    """
    band = _band_for(light, chroma, hue)
    lo = max(0.0, min(1.0, light))
    if band <= BANDS.index("white"):
        sub = min(0xFFF, int(lo * 0xFFF))            # lightness, 12 bits
    else:
        h6 = min(63, int(hue / 360.0 * 64))          # hue, ~5.6 deg
        l4 = min(15, int(lo * 16))
        c2 = min(3, int(min(chroma, 0.32) / 0.08))
        sub = (h6 << 6) | (l4 << 2) | c2
    return (band << BAND_SHIFT) | sub


def band_of(color_key: int) -> int:
    """The band index packed into a key — the same thing the SQL grouping
    expression computes, for tests and callers that already hold a key."""
    return color_key >> BAND_SHIFT


# ---- the presence signature -------------------------------------------------

#: Bucket layout for :data:`color_sig`: 8 greys by lightness, then 12 hues x 4
#: lightness levels. 56 bits, NOT 64 — SQLite's INTEGER is signed, so a set
#: top bit would have to be stored as a negative number, and a 56-bit value is
#: simply always positive.
SIG_GREYS = 8
SIG_HUES = 12
SIG_LEVELS = 4
SIG_BITS = SIG_GREYS + SIG_HUES * SIG_LEVELS

#: A bucket is "present" once it holds this share of the picture. Above the
#: uniform share (1/56), so a picture sets far fewer bits than it has buckets.
#:
#: MEASURED, not guessed. Swept over 1/32 … 1/512 against 60 synthetic
#: multi-colour scenes, each compared with a resized + contrast-shifted copy
#: of itself: at 1/32 the same picture lands within 2 bits (p90) while
#: different pictures sit at a median of 6, and 0.34% of unrelated pairs fall
#: inside that radius. Every looser threshold sets more bits and separates
#: WORSE (1/64 → 1.13%, 1/256 → 1.30%), because a bucket holding a trace of a
#: colour is noise, not palette.
SIG_MIN_SHARE = 1.0 / 32.0


def _pack_sig(lab: np.ndarray) -> int:
    """Set a bit per bucket the picture spends :data:`SIG_MIN_SHARE` in."""
    light = np.clip(lab[:, 0], 0.0, 1.0)
    chroma = np.hypot(lab[:, 1], lab[:, 2])
    hue = (np.degrees(np.arctan2(lab[:, 2], lab[:, 1])) - RED_ORIGIN_DEG) % 360.0

    grey = chroma < ACHROMATIC_C
    idx = np.where(
        grey,
        np.minimum(SIG_GREYS - 1, (light * SIG_GREYS).astype(np.int64)),
        SIG_GREYS
        + np.minimum(SIG_HUES - 1, (hue / 360.0 * SIG_HUES).astype(np.int64)) * SIG_LEVELS
        + np.minimum(SIG_LEVELS - 1, (light * SIG_LEVELS).astype(np.int64)),
    )
    counts = np.bincount(idx, minlength=SIG_BITS)
    need = max(1, int(len(light) * SIG_MIN_SHARE))
    sig = 0
    for bit in np.nonzero(counts >= need)[0]:
        sig |= 1 << int(bit)
    return sig


def color_signature(im: Image.Image) -> tuple[int, int]:
    """``(color_key, color_sig)`` for one image — the pair stored on `File`.

    One function returning both because they are one pass over the same
    pixels, and because a caller that computed only one of them would leave a
    file half-described with nothing to say which half.

    The key's hue comes from averaging ``a`` and ``b`` directly, which is a
    CHROMA-WEIGHTED CIRCULAR mean for free: a grey pixel contributes
    ``(0, 0)`` and so drags the hue nowhere, which is why a red car on grey
    asphalt files under red rather than under grey. Averaging the hue ANGLE
    instead would be wrong twice — it weights a washed-out pixel as heavily as
    a saturated one, and it has no sane answer across the 0°/360° wrap.

    The cost is that opposed hues partly cancel, so the MORE CHROMATIC half
    wins: half saturated red and half cyan reads as red, because in OKLab red
    is the more chromatic of the two (0.220 against 0.125) and sRGB holds no
    colour that opposes saturated red at equal chroma — the closest leaves a
    residual of 0.089. Full cancellation to neutral therefore only happens for
    a genuinely balanced pair. That is a defensible answer for a ONE-colour
    summary, since the saturated half is what the eye takes the picture to be,
    and the signature is where both halves are recorded regardless.
    """
    small = im.convert("RGB").copy()
    small.thumbnail((SAMPLE_PX, SAMPLE_PX), Image.Resampling.BILINEAR)
    arr = np.asarray(small, dtype=np.float64).reshape(-1, 3) / 255.0
    if arr.size == 0:
        return 0, 0
    lab = _srgb_to_oklab(arr)
    mean_l = float(lab[:, 0].mean())
    mean_a = float(lab[:, 1].mean())
    mean_b = float(lab[:, 2].mean())
    key = _pack_key(mean_l, math.hypot(mean_a, mean_b), _hue_deg(mean_a, mean_b))
    return key, _pack_sig(lab)


def sig_distance(a: int, b: int) -> int:
    """Hamming distance between two colour signatures."""
    return int(a ^ b).bit_count()

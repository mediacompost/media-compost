"""THE FURTHER THE HASHES ARE APART, THE MORE THE PIXELS MUST AGREE.

`Config.verify_mse` is the rule and `Config` is where the two numbers live;
what makes it worth a test file of its own is that the failure it exists to
stop is SILENT in both directions — a near-duplicate that quietly stops
folding, or two different pictures quietly becoming one item — and neither
shows up as an error anywhere.

The numbers below are the measurement the config comments record, in the
three shapes that actually drove it: a translated manga page (must NOT fold),
a degenerate picture's own re-encode (MUST fold, and lands at the same
Hamming distance as the translated page), and an ordinary re-encode.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from media_compost import dedup
from media_compost.config import Config


# The three measured pairs, as (Hamming distance, MSE). Every one of them is
# a real reading recorded in `Config`'s own comments:
#   * the reported false fold  — one chapter page in Japanese and in English
#   * the second false fold    — the same, another page of the same chapter
#   * the degenerate re-save   — `tests/ui/test_metadata_pins.py`'s fixture,
#                                ONE picture saved twice at JPEG q95
#   * the worst genuine        — the harshest re-encode measured that the
#     re-encode                  hash still nominates at Hamming <= 6
TRANSLATED_PAGE = (10, 0.00396)
TRANSLATED_PAGE_2 = (10, 0.00125)
DEGENERATE_RESAVE = (10, 0.0000027)
WORST_NEAR_REENCODE = (6, 0.000753)


def _folds(cfg: Config, distance: int, mse: float) -> bool:
    """What the near-dup rule answers for a candidate at ``distance``."""
    return distance <= cfg.phash_threshold and mse <= cfg.verify_mse(distance)


def test_a_translated_page_does_not_fold_onto_the_original():
    """The report this rule was written for: same artwork, different speech
    bubbles. Both measured pairs sit at Hamming exactly 10 — inside the
    threshold — so only the pixel bound can turn them away."""
    cfg = Config()
    assert not _folds(cfg, *TRANSLATED_PAGE)
    assert not _folds(cfg, *TRANSLATED_PAGE_2)


def test_a_degenerate_picture_still_folds_onto_its_own_re_encode():
    """And this is why the NOMINATOR was left alone. A flat picture re-saved
    at JPEG q95 lands 10 bits away too — the documented pHash degeneracy — so
    lowering `phash_threshold` to 8 would have thrown this fold away with the
    two above. Its pixels are what tell it apart: 0.0000027 against 0.00125,
    a factor of 450."""
    cfg = Config()
    assert DEGENERATE_RESAVE[0] == TRANSLATED_PAGE[0], (
        "the whole point: the hash cannot separate these two")
    assert _folds(cfg, *DEGENERATE_RESAVE)


def test_an_ordinary_re_encode_keeps_the_wider_bound():
    """Inside the band the hash is confident about, the check stays tolerant
    — that is what lets a rescaled, recompressed copy fold at all."""
    cfg = Config()
    assert _folds(cfg, *WORST_NEAR_REENCODE)
    assert cfg.verify_mse(WORST_NEAR_REENCODE[0]) == cfg.dedup_verify_mse


def test_the_bound_tightens_exactly_once_and_never_loosens():
    cfg = Config()
    bounds = [cfg.verify_mse(d) for d in range(0, cfg.phash_threshold + 1)]
    assert bounds == sorted(bounds, reverse=True), "it may only ever tighten"
    assert len(set(bounds)) == 2, "one near band and one far band"
    assert cfg.verify_mse(cfg.dedup_verify_near) == cfg.dedup_verify_mse
    assert cfg.verify_mse(cfg.dedup_verify_near + 1) == cfg.dedup_verify_mse_far


def test_the_far_bound_sits_between_the_two_measurements_it_is_anchored_to():
    """0.001 is not a tuned number: it is between the worst a genuine
    re-encode measures where the hash is still confident and the nearest
    false fold. If either constant moves, that has to stay true or the rule
    has stopped meaning what its comment says."""
    cfg = Config()
    assert WORST_NEAR_REENCODE[1] < cfg.dedup_verify_mse_far < TRANSLATED_PAGE_2[1]


def test_a_caller_with_no_distance_gets_the_widest_bound():
    """`verify_mse(0)` is the conservative reading — used where the caller
    genuinely cannot say how far the candidate was nominated from."""
    cfg = Config()
    assert cfg.verify_mse(0) == max(cfg.dedup_verify_mse,
                                    cfg.dedup_verify_mse_far)


# ---- the rule end to end, on real pixels ------------------------------------

def _resave(im: Image.Image, **kw) -> Image.Image:
    b = io.BytesIO()
    im.convert("RGB").save(b, "JPEG", **kw)
    b.seek(0)
    return Image.open(b)


def _flat_picture() -> Image.Image:
    """`test_metadata_pins`' fixture: a nearly-flat field with sparse stripes,
    which is exactly the content whose pHash is noise."""
    im = Image.new("RGB", (240, 180), (10, 20, 30))
    for x in range(240):
        for y in range(0, 180, 30):
            im.putpixel((x, y + (15 + x // 6) % 30),
                        ((x * 7) % 256, 159, (x * 3) % 256))
    return im


def _measure(a: Image.Image, b: Image.Image) -> tuple[int, float]:
    d = dedup.hamming(dedup.phash_to_int(dedup.compute_phash_image(a)),
                      dedup.phash_to_int(dedup.compute_phash_image(b)))
    va, vb = dedup.norm_rgb(a), dedup.norm_rgb(b)
    return d, sum((x - y) ** 2 for x, y in zip(va, vb)) / len(va)


@pytest.mark.parametrize("quality", [95, 80, 60])
def test_a_re_encode_of_a_flat_picture_folds_however_far_its_hash_drifts(quality):
    """The end-to-end form of the degenerate case. The hash may wander a long
    way on content like this — that is the point — and the pixels do not, so
    the pair folds at whichever bound the distance selects."""
    cfg = Config()
    original = _flat_picture()
    distance, mse = _measure(original, _resave(original, quality=quality))
    assert mse < cfg.dedup_verify_mse_far, (
        f"re-encoding must not move the pixels ({mse:.7f})")
    if distance <= cfg.phash_threshold:
        assert _folds(cfg, distance, mse)

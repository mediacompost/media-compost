"""The degradation module: drawing a value from a range, naming it, applying it.

The interesting half is `draw`/`key` — the rules that decide whether a cached
artifact is found again or silently regenerated. The pixel half is checked for
the property each method exists for, not for exact bytes: a JPEG encoder's
output is not something to pin.
"""

from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from media_compost import codec_roundtrip, encoder_available
from media_compost.train import degrade
from media_compost.train.spec import DegradeVariant, FloatRange, IntRange


def _picture(w: int = 200, h: int = 140) -> Image.Image:
    """Fine detail on flat ground — what compression destroys first."""
    img = Image.new("RGB", (w, h), (250, 250, 250))
    d = ImageDraw.Draw(img)
    for x in range(0, w, 3):
        d.line([(x, 0), (x, h)], fill=(10, 10, 200))
    d.ellipse([w // 5, h // 5, w * 4 // 5, h * 4 // 5], outline=(220, 20, 20),
              width=3)
    return img


def _variant(**kw) -> DegradeVariant:
    kw.setdefault("tags", ["x"])
    return DegradeVariant(**kw)


def _energy(img: Image.Image) -> float:
    """Mean absolute difference between neighbouring pixels — high on the
    original's fine stripes, lower once a codec has smeared them."""
    px = img.convert("L").load()
    w, h = img.size
    return sum(abs(px[x, y] - px[x + 1, y])
               for y in range(h) for x in range(w - 1)) / float(w * h)


# ---- drawing -------------------------------------------------------------


def test_a_draw_is_deterministic_and_inside_the_range():
    v = _variant(quality=IntRange(lo=20, hi=60))
    for fid in (1, 7, 4242):
        a, b = degrade.draw(v, fid), degrade.draw(v, fid)
        assert a == b, "a re-run must find the cache, not draw again"
        assert 20 <= a.quality <= 60


def test_draws_spread_across_the_range_rather_than_clumping():
    """Seeded per FILE, so the dataset spans the range — every picture landing
    on the same value would teach one artifact strength."""
    v = _variant(quality=IntRange(lo=1, hi=100))
    got = sorted(degrade.draw(v, fid).quality for fid in range(200))
    assert len(set(got)) > 50
    assert got[0] < 15 and got[-1] > 85
    # Roughly uniform: each quarter of the range gets a real share.
    quarters = [sum(1 for q in got if lo <= q <= hi)
                for lo, hi in ((1, 25), (26, 50), (51, 75), (76, 100))]
    assert all(n > 25 for n in quarters), quarters


def test_variations_of_one_file_differ():
    v = _variant(quality=IntRange(lo=1, hi=100), variations=4)
    drawn = {degrade.draw(v, 5, i).quality for i in range(4)}
    assert len(drawn) >= 3


def test_a_range_of_one_is_a_fixed_value():
    v = _variant(quality=IntRange(lo=30, hi=30))
    keys = {degrade.key(degrade.draw(v, fid)) for fid in range(50)}
    assert keys == {"jpeg-q30-s420"}


def test_the_same_PICTURE_draws_the_same_value_in_any_library():
    """The point of seeding on the content hash rather than the row id.

    Both are per-file and both are stable within one library, which is all the
    determinism the cache asks for — but a row id is a fact about an INSERTION
    ORDER, and this value is baked into a filename. Seeded on the id, the same
    photograph in two libraries degraded differently, a rebuild from item
    folders redrew every one, and a golden recording the drawn names held only
    while nothing was inserted before it (which is exactly how the manifest
    golden failed the day its module was split across xdist workers).
    """
    v = _variant(quality=IntRange(lo=1, hi=100))
    sha = "b" * 64
    # Same bytes, wildly different row ids — one library's 3 is another's 900.
    assert (degrade.draw(v, degrade.file_seed(sha, 3))
            == degrade.draw(v, degrade.file_seed(sha, 900)))
    # …and two different pictures still land in different places, or the
    # dataset would sit on one rung of the ladder.
    spread = {degrade.draw(v, degrade.file_seed(f"{i:064x}", 1)).quality
              for i in range(200)}
    assert len(spread) > 50


def test_a_file_with_no_hash_falls_back_to_its_id_rather_than_to_a_constant():
    """A sidecar restore writes `sha256=fe.get("sha256") or ""` for a folder
    that recorded none. Seeding every such file identically would put them all
    on the same rung — the one failure the per-file seed exists to avoid — so
    the fallback is the id, which is exactly the old behaviour."""
    v = _variant(quality=IntRange(lo=1, hi=100))
    seeds = {degrade.file_seed("", fid) for fid in range(200)}
    assert len(seeds) == 200, "an empty hash must not collapse to one seed"
    spread = {degrade.draw(v, degrade.file_seed("", fid)).quality
              for fid in range(200)}
    assert len(spread) > 50


# ---- the cache key -------------------------------------------------------


def test_the_key_ignores_what_is_not_a_property_of_the_pixels():
    """Renaming a variant, or changing its tags or weight, must not throw the
    cache away."""
    a = _variant(name="mild", weight=0.25, tags=["jpeg_artifacts"],
                 quality=IntRange(lo=20, hi=60))
    b = _variant(name="harsh", weight=1.0, tags=["low_quality"],
                 remove_tags=["masterpiece"], require_tags=["photo"],
                 quality=IntRange(lo=20, hi=60))
    assert degrade.ranges_key(a) == degrade.ranges_key(b)
    assert degrade.draw(a, 9) == degrade.draw(b, 9)


def test_moving_a_range_end_changes_the_key():
    base = _variant(quality=IntRange(lo=20, hi=60))
    wider = _variant(quality=IntRange(lo=20, hi=61))
    keys = lambda v: {degrade.key(degrade.draw(v, f)) for f in range(60)}
    assert keys(base) != keys(wider)


def test_a_key_is_one_filesystem_safe_token():
    """It names a file and is split back out of one on '-', and the latent
    cache's own name is parsed the same way — so no dots, no separators of its
    own."""
    for v in (_variant(quality=IntRange(lo=7, hi=7)),
              _variant(method="video", crf=IntRange(lo=31, hi=31)),
              _variant(method="resize", scale=FloatRange(lo=0.52, hi=0.52)),
              _variant(quality=IntRange(lo=7, hi=7),
                       passes=IntRange(lo=3, hi=3))):
        k = degrade.key(degrade.draw(v, 1))
        assert k and "." not in k and "/" not in k and " " not in k
        assert k == k.strip("-")
    assert degrade.key(degrade.draw(
        _variant(method="resize", scale=FloatRange(lo=0.52, hi=0.52)), 1)
    ) == "resize-052-bilinear"
    assert degrade.key(degrade.draw(
        _variant(quality=IntRange(lo=7, hi=7), passes=IntRange(lo=3, hi=3)), 1)
    ) == "jpeg-q7-s420-x3"


def test_the_stored_format_follows_the_method():
    jpeg = degrade.draw(_variant(), 1)
    assert degrade.output_format(jpeg) == "jpg"   # the real compressed bytes
    assert degrade.output_format(degrade.draw(_variant(method="resize"), 1)) == "png"


# ---- the pixels ----------------------------------------------------------


def test_jpeg_quality_is_the_axis_it_claims_to_be():
    img = _picture()
    low = degrade.encode(img, degrade.draw(
        _variant(quality=IntRange(lo=5, hi=5)), 1))
    high = degrade.encode(img, degrade.draw(
        _variant(quality=IntRange(lo=95, hi=95)), 1))
    assert len(low) < len(high) / 2
    assert _energy(degrade.apply(img, degrade.draw(
        _variant(quality=IntRange(lo=5, hi=5)), 1))) < _energy(img)


def test_passes_compound():
    img = _picture()
    once = degrade.apply(img, degrade.draw(
        _variant(quality=IntRange(lo=30, hi=30)), 1))
    many = degrade.apply(img, degrade.draw(
        _variant(quality=IntRange(lo=30, hi=30),
                 passes=IntRange(lo=8, hi=8)), 1))
    assert list(once.getdata()) != list(many.getdata())


def test_resize_is_resolution_loss_and_not_a_smaller_picture():
    """The degraded entry shares its source's bucket and bounding boxes, which
    only holds while the size does."""
    img = _picture(201, 141)
    out = degrade.apply(img, degrade.draw(
        _variant(method="resize", scale=FloatRange(lo=0.25, hi=0.25)), 1))
    assert out.size == img.size
    assert _energy(out) < _energy(img)


@pytest.mark.parametrize("codec", ["h264", "h265"])
def test_a_codec_roundtrip_keeps_the_frame_and_softens_it(codec):
    if not encoder_available(codec):
        pytest.skip(f"this ffmpeg has no {codec} encoder")
    img = _picture(201, 141)          # odd on both axes: yuv420p refuses those
    out = degrade.apply(img, degrade.draw(
        _variant(method="video", codec=codec, crf=IntRange(lo=45, hi=45)), 1))
    assert out.size == img.size
    assert _energy(out) < _energy(img)


def test_a_missing_encoder_is_a_sentence_and_not_a_traceback():
    v = _variant(method="video", crf=IntRange(lo=30, hi=30))
    drawn = degrade.draw(v, 1)
    object.__setattr__(drawn, "codec", "h999")
    with pytest.raises(degrade.DegradeError, match="unknown codec"):
        degrade.apply(_picture(), drawn)


def test_a_jpeg_variant_stores_its_own_last_pass():
    """`encode` writes the final JPEG at its own quality rather than decoding
    and re-saving it — that would be one generation more than asked for."""
    img = _picture()
    drawn = degrade.draw(_variant(quality=IntRange(lo=40, hi=40)), 1)
    import io

    stored = Image.open(io.BytesIO(degrade.encode(img, drawn)))
    assert stored.format == "JPEG"
    assert list(stored.convert("RGB").getdata()) == \
        list(degrade.apply(img, drawn).getdata())

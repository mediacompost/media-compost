"""The colour key and signature — ordering and browsing, never matching."""

from PIL import Image

from media_compost.colorkey import (
    BANDS,
    SIG_BITS,
    band_of,
    color_signature,
    sig_distance,
)

# One unambiguous swatch per band, in the order the bands are meant to sort.
SWATCHES = [
    ("black", (10, 10, 10)),
    ("grey", (128, 128, 128)),
    ("white", (245, 245, 245)),
    ("red", (220, 30, 30)),
    ("orange", (240, 140, 20)),
    ("brown", (110, 70, 30)),
    ("yellow", (240, 230, 40)),
    ("green", (40, 180, 60)),
    ("teal", (20, 180, 180)),
    ("blue", (40, 60, 220)),
    ("purple", (130, 40, 200)),
    ("pink", (240, 90, 180)),
]


def _flat(rgb, size=64):
    return Image.new("RGB", (size, size), rgb)


def test_every_band_has_a_swatch_that_lands_in_it():
    for want, rgb in SWATCHES:
        key, _ = color_signature(_flat(rgb))
        assert BANDS[band_of(key)] == want, f"{rgb} should be {want}"


def test_the_key_sorts_into_the_gradient_the_bands_declare():
    """Ordering by the raw key IS the reading order of BANDS — that is the
    whole reason the band lives in the key's high bits."""
    keys = [(color_signature(_flat(rgb))[0], name) for name, rgb in SWATCHES]
    assert [name for _, name in sorted(keys)] == [n for n, _ in SWATCHES]


def test_the_key_fits_sixteen_bits():
    for _, rgb in SWATCHES:
        key, _ = color_signature(_flat(rgb))
        assert 0 <= key < 1 << 16


def test_a_signature_is_positive_and_fits_a_signed_column():
    """56 bits, not 64: SQLite's INTEGER is signed, and a set top bit would
    have to be stored as a negative number."""
    for _, rgb in SWATCHES:
        _, sig = color_signature(_flat(rgb))
        assert 0 <= sig < 1 << SIG_BITS
        assert sig < 1 << 63


def test_the_dominant_hue_wins_over_the_larger_grey_area():
    """A red car on grey asphalt is a red picture. Averaging a/b is a
    chroma-weighted circular mean, so grey pixels drag the hue nowhere."""
    im = _flat((128, 128, 128))
    px = im.load()
    for x in range(64):
        for y in range(50, 64):  # ~22% of the picture
            px[x, y] = (210, 30, 30)
    key, _ = color_signature(im)
    assert BANDS[band_of(key)] == "red"


def test_opposed_hues_partly_cancel_and_the_more_chromatic_half_wins():
    """The documented cost of a one-colour summary. Half saturated red and
    half cyan reads as RED — in OKLab red carries chroma 0.220 against cyan's
    0.125, and sRGB holds nothing that opposes saturated red at equal chroma.
    The signature records both halves either way."""
    im = _flat((128, 128, 128))
    px = im.load()
    for x in range(64):
        for y in range(64):
            px[x, y] = (220, 30, 30) if x < 32 else (30, 200, 200)
    key, sig = color_signature(im)
    assert BANDS[band_of(key)] == "red"
    red_sig = color_signature(_flat((220, 30, 30)))[1]
    cyan_sig = color_signature(_flat((30, 200, 200)))[1]
    assert sig & red_sig, "the red half should still be recorded"
    assert sig & cyan_sig, "the cyan half should still be recorded"


def test_a_resized_recompressed_picture_keeps_its_signature():
    im = _flat((128, 128, 128))
    px = im.load()
    for i, (_, rgb) in enumerate(SWATCHES[3:9]):  # a multi-colour scene
        for x in range(i * 10, i * 10 + 10):
            for y in range(64):
                px[x, y] = rgb
    _, a = color_signature(im)
    _, b = color_signature(im.resize((32, 32)))
    assert sig_distance(a, b) <= 4


def test_unlike_palettes_are_further_apart_than_a_resize():
    scene = _flat((128, 128, 128))
    px = scene.load()
    for x in range(64):
        for y in range(64):
            px[x, y] = (230, 120, 40) if y < 32 else (200, 90, 20)
    forest = _flat((40, 110, 50))
    _, sun = color_signature(scene)
    _, sun_small = color_signature(scene.resize((32, 32)))
    _, tree = color_signature(forest)
    assert sig_distance(sun, tree) > sig_distance(sun, sun_small)


def test_dedup_does_not_read_the_colour_columns():
    """The boundary the module docstring insists on, asserted rather than
    hoped for: what counts as a duplicate must not quietly become a question
    about colour."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "media_compost"
    for name in ("dedup.py", "dedup_index.py"):
        src = (root / name).read_text(encoding="utf-8")
        assert "color_key" not in src
        assert "color_sig" not in src
        assert "colorkey" not in src

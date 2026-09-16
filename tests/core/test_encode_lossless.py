"""What format a picture this app RENDERS is written in.

`media.encode_lossless` is the one answer for a PDF page, a still cut out of a
film, a rotation, an editor save and every AI job's output. Two things it must
never do, and only one of them announces itself:

* WebP **silently converts** what it cannot hold. A 16-bit depth map saved
  "losslessly" comes back with its 0-65520 range crushed to 0-255 and a CMYK
  scan comes back a different colour, with nothing raised and nothing logged.
  So the gate is a list of modes known to SURVIVE, and this is the test that
  keeps that list honest.
* WebP has a hard 16383 px limit per side, which a 4x upscale of a large
  picture really does reach. Past it libwebp raises, so the fallback has to
  cover size as well as mode.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image, ImageChops

from media_compost import media


def _round_trip(img: Image.Image) -> tuple[str, Image.Image]:
    ext, data = media.encode_lossless(img)
    with Image.open(io.BytesIO(data)) as back:
        back.load()
        return ext, back.copy()


@pytest.mark.parametrize("mode", ["RGB", "RGBA", "L", "LA"])
def test_the_modes_webp_holds_go_to_webp_and_come_back_exact(mode: str):
    rng = np.random.default_rng(11)
    bands = len(Image.new(mode, (1, 1)).getbands())
    arr = rng.integers(0, 256, size=(40, 30, bands), dtype=np.uint8)
    img = Image.fromarray(arr.squeeze(), mode=mode) if bands > 1 \
        else Image.fromarray(arr[..., 0], mode=mode)

    ext, back = _round_trip(img)
    assert ext == "webp"
    # Greyscale is widened to RGB on the way in — that changes no value, which
    # is the whole reason it is allowed through.
    assert ImageChops.difference(
        img.convert(back.mode), back).getbbox() is None, mode


@pytest.mark.parametrize("mode", ["I;16", "P", "1"])
def test_a_mode_webp_would_MANGLE_stays_png(mode: str):
    img = Image.new(mode, (16, 16))
    ext, _data = media.encode_lossless(img)
    assert ext == "png", f"{mode} must not be handed to WebP"


@pytest.mark.parametrize("mode", ["CMYK", "F"])
def test_a_mode_PNG_cannot_hold_either_goes_to_tiff(mode: str):
    """The last rung. PNG refuses these outright — the old code, which only
    ever called `save(buf, "PNG")`, raised on them — and neither may be handed
    to WebP, which would take them and change them."""
    img = Image.new(mode, (16, 16))
    ext, data = media.encode_lossless(img)
    assert ext == "tiff"
    with Image.open(io.BytesIO(data)) as back:
        assert back.mode == mode


def test_sixteen_bit_values_survive_the_round_trip():
    """The concrete case: a depth artifact. Through WebP this loses 8 bits of
    every sample and says nothing at all."""
    arr = (np.arange(64 * 64, dtype=np.uint16).reshape(64, 64) * 16)
    img = Image.fromarray(arr)
    assert img.mode.startswith("I")

    ext, back = _round_trip(img)
    assert ext == "png"
    assert np.array_equal(np.array(back), arr)
    # ...and this is what the WebP path would have done with it.
    buf = io.BytesIO()
    img.save(buf, "WEBP", lossless=True)
    with Image.open(io.BytesIO(buf.getvalue())) as lost:
        assert np.array(lost).max() <= 255 < arr.max()


def test_a_picture_too_wide_for_webp_falls_back_rather_than_raising():
    wide = Image.new("RGB", (media.WEBP_MAX_DIM + 1, 4))
    ext, data = media.encode_lossless(wide)
    assert ext == "png" and data
    # One pixel narrower is fine, which is what makes the limit the reason.
    assert media.encode_lossless(
        Image.new("RGB", (media.WEBP_MAX_DIM, 4)))[0] == "webp"


def test_encode_matching_keeps_the_format_a_path_already_names():
    """Rewriting a file AT ITS OWN PATH: WebP bytes under a `.png` name would
    be a file that lies about itself."""
    img = Image.new("RGB", (8, 8), (1, 2, 3))
    assert media.encode_matching(img, "png")[:8] == b"\x89PNG\r\n\x1a\n"
    assert media.encode_matching(img, "webp")[:4] == b"RIFF"
    # A mode WebP cannot hold cannot honour a `.webp` request either; it falls
    # back rather than quietly mangling the picture.
    deep = Image.fromarray(np.zeros((8, 8), dtype=np.uint16))
    assert media.encode_matching(deep, "webp")[:8] == b"\x89PNG\r\n\x1a\n"

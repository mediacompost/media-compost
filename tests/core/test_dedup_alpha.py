"""A picture whose shape lives in its ALPHA is not a blank rectangle.

`convert("RGB")` and `convert("L")` DISCARD alpha rather than compositing it,
so a white-on-transparent logo used to reach the hasher as one flat colour —
the degenerate-pHash case `dedup`'s own docstring warns about, reached by
accident. Its hash came out `8000…0000`, Hamming ZERO from a blank frame, and
since the frame-link path matches on a pHash and an aspect ratio with no pixel
check, the logo was recorded as a frame of every film that fades to white.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from media_compost.dedup import (compute_phash_image, hamming, norm_gray,
                                 phash_to_int, verify_match)


def _x_logo(size: int = 512) -> Image.Image:
    """A white X on a fully transparent ground: the RGB channel is white
    EVERYWHERE, so the shape exists only in alpha."""
    im = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    d = ImageDraw.Draw(im)
    w = size // 10
    d.line((size // 8, size // 8, size - size // 8, size - size // 8),
           fill=(255, 255, 255, 255), width=w)
    d.line((size - size // 8, size // 8, size // 8, size - size // 8),
           fill=(255, 255, 255, 255), width=w)
    return im


def test_a_transparent_logo_is_not_a_frame_of_every_film():
    logo = phash_to_int(compute_phash_image(_x_logo()))
    for name, flat in (
        ("white", Image.new("RGB", (1920, 1080), (255, 255, 255))),
        ("black", Image.new("RGB", (1920, 1080), (0, 0, 0))),
        ("grey", Image.new("RGB", (1920, 1080), (128, 128, 128))),
    ):
        # Nowhere near the near-dup threshold (10), where it used to be 0.
        d = hamming(logo, phash_to_int(compute_phash_image(flat)))
        assert d > 32, f"the logo still looks like a {name} frame (hamming {d})"


def test_the_verifier_sees_alpha_too():
    """Belt and braces: the pixel check is what stands between a wrong
    nomination and a wrong merge, and it was blind in the same way."""
    logo = _x_logo()
    white = Image.new("RGB", (512, 512), (255, 255, 255))
    assert not verify_match(logo, white, 0.02)
    # The logo against ITSELF still verifies — the fix must not make a
    # picture stop matching its own copy.
    assert verify_match(logo, _x_logo(), 0.02)


def test_the_shape_survives_whatever_colour_it_is_drawn_in():
    """Compositing over mid-grey rather than white or black is the whole
    reason both of these work: over white the white logo vanishes again, and
    over black the black one does."""
    for fill in ((255, 255, 255, 255), (0, 0, 0, 255)):
        im = Image.new("RGBA", (256, 256), (*fill[:3], 0))
        d = ImageDraw.Draw(im)
        d.rectangle((64, 64, 192, 192), fill=fill)
        gray = norm_gray(im)
        assert max(gray) - min(gray) > 0.2, (
            f"a {fill[:3]} shape on transparency came out flat")


def test_an_OPAQUE_picture_is_untouched():
    """The compositing must be a no-op without alpha, or every pHash already
    stored for an ordinary picture would quietly stop meaning what it meant —
    and there is nothing that recomputes them."""
    im = Image.new("RGB", (320, 240))
    px = im.load()
    for y in range(240):
        for x in range(320):
            px[x, y] = ((x * 3) % 256, (y * 5) % 256, (x ^ y) % 256)
    before = compute_phash_image(im), norm_gray(im)
    # Same pixels, reached through the alpha path and back.
    same = im.convert("RGBA").convert("RGB")
    assert (compute_phash_image(same), norm_gray(same)) == before


def test_the_verifier_is_not_colour_blind():
    """Two solid fills whose GRAYS coincide are different pictures, and the
    verifier must say so: the grayscale compare measured 0.010 for this pair
    — under the 0.020 bound, a silent merge — while RGB measures 0.335.
    Found live: with the near-dup path checking every nominated candidate,
    three different solid-colour GPS test photos folded onto one item."""
    red = Image.new("RGB", (100, 100), (200, 10, 30))    # gray ~69
    blue = Image.new("RGB", (100, 100), (10, 30, 200))   # gray ~43
    teal = Image.new("RGB", (100, 100), (5, 90, 90))     # gray ~65
    assert not verify_match(red, blue, 0.02)
    assert not verify_match(red, teal, 0.02)
    assert not verify_match(blue, teal, 0.02)
    # And the same picture re-encoded still folds, with room to spare.
    import io

    buf = io.BytesIO()
    red.save(buf, "JPEG", quality=70)
    assert verify_match(red, Image.open(buf), 0.0005)

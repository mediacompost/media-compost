"""Alpha handling for masked training. Pillow only — no torch, no numpy.

Kept out of the engines so it can be unit-tested from the main backend venv
(like ``compose.py``), and because both the caching and the uncached path need
exactly the same treatment: whatever the VAE encodes must match the mask that
weights the loss.
"""

from __future__ import annotations

from PIL import Image, ImageFilter

# Fill passes, coarse to fine. Each pass blurs the whole image and keeps only
# the result inside the hole, so opaque colour creeps further in every time;
# starting wide and narrowing gives a smooth, low-frequency fill.
_FILL_RADII = (48, 24, 12, 6, 3)


def has_alpha(img: Image.Image) -> bool:
    return img.mode in ("RGBA", "LA") or (
        img.mode == "P" and "transparency" in img.info
    )


def split_alpha(img: Image.Image) -> tuple[Image.Image, Image.Image | None]:
    """``(rgb, alpha)`` — alpha is None for a fully opaque image.

    The RGB half has its transparent region **filled with a smooth extension
    of the opaque edge colours** rather than left as whatever bytes happened to
    sit under the alpha (usually black). The VAE has no notion of transparency
    and its receptive field reaches across the boundary, so a hard edge there
    is encoded into the object's own latents — a halo the mask cannot remove,
    because masking only silences the loss, not the encoder.
    """
    if not has_alpha(img):
        return img.convert("RGB"), None
    rgba = img.convert("RGBA")
    alpha = rgba.getchannel("A")
    if alpha.getextrema()[0] == 255:       # nothing actually transparent
        return rgba.convert("RGB"), None
    return fill_transparent(rgba), alpha


def fill_transparent(rgba: Image.Image) -> Image.Image:
    """Extend the opaque colours into the transparent region (RGBA -> RGB)."""
    rgba = rgba.convert("RGBA")
    alpha = rgba.getchannel("A")
    # Treat half-transparent pixels as known: they still carry real colour.
    known = alpha.point(lambda v: 255 if v >= 128 else 0).convert("L")
    rgb = rgba.convert("RGB")

    # Seed the hole with the average opaque colour, so the first blur has
    # something neutral to work from instead of the undefined bytes.
    seed = Image.new("RGB", rgb.size,
                     _mean_opaque(rgb, known) or (128, 128, 128))
    out = Image.composite(rgb, seed, known)
    for r in _FILL_RADII:
        out = Image.composite(rgb, out.filter(ImageFilter.GaussianBlur(r)), known)
    return out


def _mean_opaque(rgb: Image.Image, known: Image.Image):
    """Average colour over the opaque pixels, or None when there are none."""
    from PIL import ImageStat

    stat = ImageStat.Stat(rgb, mask=known)
    try:
        return tuple(int(v) for v in stat.mean)
    except ZeroDivisionError:             # fully transparent image
        return None


def latent_mask(alpha: Image.Image, lw: int, lh: int) -> list[float]:
    """Alpha downsampled to latent resolution as a flat row-major list of 0..1.

    ``Image.BOX`` is an area average, which is the right reduction here: one
    latent cell covers an 8×8 pixel block, so its weight should be the
    *fraction* of that block that was visible. Edges therefore go soft over one
    latent cell — fine for a subject, and the reason this cannot mask anything
    thinner than ~8 px.
    """
    small = alpha.convert("L").resize((max(1, lw), max(1, lh)), Image.BOX)
    return [v / 255.0 for v in small.tobytes()]   # mode "L" = one byte/pixel

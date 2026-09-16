"""Screen-tone removal (classical DSP — no model download).

Converts manga screentones (halftone dots, hatching) into smooth greyscale
gradients: find the halftone frequency as a *local peak* sticking out of the
FFT's radial spectrum, low-pass the page just past that frequency, then
composite the original line art (dark strokes that survive a morphological
opening — isolated tone dots don't) back on top so lines and solid blacks stay
crisp. Pages without a detectable halftone pattern (e.g. small panels whose
tones already reduced to dither) only get a gentle smoothing pass.

Pure OpenCV/NumPy, so — like the Canny plugin — it needs no weights and is
ready immediately.
"""

from __future__ import annotations

try:
    from ..framework import ModelSpec, PluginManifest

    MANIFEST = PluginManifest(
        models=[
            ModelSpec(id="descreen", task="descreen", name="Screen-tone removal",
                      family="Descreen (FFT)",
                      note="Halftone dots / hatching → smooth grayscale; keeps line art crisp."),
        ],
        sources=[],            # no weights to download
        deps=("cv2", "numpy"),
        url="https://github.com/natethegreate/Screentone-Remover",
    )
except (ImportError, ValueError):
    MANIFEST = None


def load(load_key, ctx):  # pragma: no cover - exercised via the worker
    return None              # stateless — no model to hold


def _estimate_pitch(gray) -> float:  # pragma: no cover - numeric helper
    """Halftone dot pitch (px) from the FFT radial spectrum, or 0 if none.

    A halftone pattern puts an isolated *local peak* at its dot frequency on
    top of the smoothly decaying structure spectrum. Scan the plausible pitch
    band (~2–12 px) for the local maximum that most exceeds the running-median
    trend; a page without screentones has no such bump (the spectrum decays
    monotonically) and returns 0 — the caller then only smooths gently.
    """
    import cv2
    import numpy as np

    h, w = gray.shape
    side = min(512, h, w)
    y0, x0 = (h - side) // 2, (w - side) // 2
    crop = gray[y0:y0 + side, x0:x0 + side].astype(np.float32)
    crop -= cv2.GaussianBlur(crop, (0, 0), 8)          # high-pass: texture only
    win = cv2.createHanningWindow((side, side), cv2.CV_32F)
    mag = np.abs(np.fft.fftshift(np.fft.fft2(crop * win)))
    cy = cx = side // 2
    yy, xx = np.ogrid[:side, :side]
    r = np.hypot(yy - cy, xx - cx).astype(np.int32)
    prof = np.bincount(r.ravel(), mag.ravel()) / np.maximum(1, np.bincount(r.ravel()))
    sm = np.convolve(prof, np.ones(5) / 5.0, mode="same")
    lo = max(6, side // 12)                             # pitch ≤ 12 px
    hi = side // 2 - 4                                  # pitch ≥ ~2 px
    if hi - lo < 8:
        return 0.0
    half = 15
    best_r, best_ratio = 0, 0.0
    for i in range(lo, hi):
        if not (sm[i] > sm[i - 1] and sm[i] >= sm[i + 1]):
            continue                                    # not a local maximum
        w0, w1 = max(0, i - half), min(len(sm), i + half + 1)
        trend = float(np.median(sm[w0:w1]))
        ratio = float(sm[i]) / (trend + 1e-6)
        if ratio > best_ratio:
            best_ratio, best_r = ratio, i
    if best_ratio < 1.6:                                # no bump → no halftone
        return 0.0
    return side / float(best_r)


def run(task, model_id, handle, image, options):  # pragma: no cover - via worker
    import cv2
    import numpy as np
    from PIL import Image

    rgba = image.convert("RGBA")
    alpha = np.asarray(rgba)[:, :, 3]
    gray = np.asarray(rgba.convert("L")).astype(np.float32)

    pitch = _estimate_pitch(gray)
    # Low-pass just past the tone frequency (gentle default when no halftone
    # was detected), then an edge-preserving bilateral pass to firm region
    # boundaries back up.
    sigma = 1.3 if pitch <= 0 else min(3.0, max(1.0, pitch * 0.5))
    smooth = cv2.GaussianBlur(gray, (0, 0), sigma)
    smooth = cv2.bilateralFilter(smooth, 0, 24, sigma * 1.6)

    # Line mask: dark strokes that survive an opening sized to the tone dots.
    # Isolated dots vanish under the opening; contiguous strokes and solid
    # blacks remain. Feather the mask so the composite has no hard seams.
    k = min(7, max(3, int(round((pitch if pitch > 0 else 3) * 0.8)) | 1))
    dark = (gray < 112).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    lines = cv2.morphologyEx(dark, cv2.MORPH_OPEN, kernel)
    lines = cv2.dilate(lines, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    mask = np.clip(cv2.GaussianBlur(lines.astype(np.float32), (0, 0), 1.0), 0.0, 1.0)

    # Where line art lives, keep the darker of original/smooth (crisp strokes);
    # elsewhere take the descreened gradient.
    out = smooth * (1.0 - mask) + np.minimum(gray, smooth) * mask
    out8 = np.clip(out + 0.5, 0, 255).astype(np.uint8)

    result = Image.fromarray(out8, mode="L").convert("RGBA")
    result.putalpha(Image.fromarray(alpha, mode="L"))
    if image.mode not in ("RGBA", "LA", "P"):
        result = result.convert("RGB")
    return {"image": result}

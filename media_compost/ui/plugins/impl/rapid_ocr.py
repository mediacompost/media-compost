"""Text reading (OCR) with RapidOCR — PP-OCR models on onnxruntime.

The general-purpose engine, and the OCR task's DEFAULT: Magi v3's OCR reads
English comics only (measured — a Japanese page returns nothing, see its
docstring), so the engine that reads every script this library actually
holds goes first. Runs on **onnxruntime**, not torch (like InsightFace), so
it installs small and stays out of the training environment's way.
Apache-2.0, fully local.

Coverage: the default **Multilingual** model is PP-OCRv6's single multi
recogniser — Chinese (simplified and traditional), Japanese, English and some
fifty Latin-script languages (German, French, Spanish, Portuguese, …) in ONE
set of weights. Korean and Cyrillic are not in it, so those ship as their own
variants on PP-OCRv5's per-script mobile models; a further script (Arabic,
Devanagari, Thai, Greek, …) is one line in ``_PARAMS`` the day somebody needs
it.

What it returns is richer than a box per block, and all of it is kept: the
unit is the LINE, as a four-point QUAD (rotated text reads as the
parallelogram it is), with a per-line confidence — and ``return_word_box=True``
yields the individual WORDS inside each line, each with its own box and
confidence. The result therefore emits ``level="line"`` regions with
``level="word"`` children and no invented "block" wrapper: a hierarchy is
only as deep as the engine actually goes.

Verified against rapidocr 3.x: ``engine(img, return_word_box=True)`` returns
``boxes`` (N, 4, 2) pixel quads, ``txts``, ``scores``, and ``word_results``
as one tuple of ``(word, confidence, [[x, y] × 4])`` triples PER LINE
(``(("", 1.0, None),)`` when nothing was found — every field is ``None`` on a
blank image).
"""

from __future__ import annotations

try:
    from ..framework import ModelSpec, PluginManifest

    MANIFEST = PluginManifest(
        models=[
            ModelSpec(
                id="rapidocr_multi", task="ocr",
                name="Text (RapidOCR)", family="Text detection",
                variant="Multilingual",
                note="Reads Chinese, Japanese, English and most Latin-script "
                     "languages, with per-word boxes and confidences."),
            ModelSpec(
                id="rapidocr_korean", task="ocr",
                name="Text (RapidOCR)", family="Text detection",
                variant="Korean",
                note="Korean text — a script the multilingual model does "
                     "not cover."),
            ModelSpec(
                id="rapidocr_cyrillic", task="ocr",
                name="Text (RapidOCR)", family="Text detection",
                variant="Cyrillic",
                note="Russian and other Cyrillic-script text — a script the "
                     "multilingual model does not cover."),
        ],
        # No HF source: RapidOCR fetches its own models into its package's
        # `models/` dir on first use (InsightFace's pattern) — so readiness is
        # deps + weights_ready(), and the Settings page offers a real
        # Download via fetch_weights().
        sources=[],
        deps=("rapidocr", "onnxruntime"),
        url="https://github.com/RapidAI/RapidOCR",
    )
except (ImportError, ValueError):
    MANIFEST = None


def load_key(model_id):
    # Each variant is its own recogniser weights, so each gets its own warm
    # worker — sharing one would reload the recogniser per call.
    return model_id


def _engine_params() -> dict:  # pragma: no cover - heavy optional dep
    """RapidOCR's onnxruntime engine on the card where there is one. Its
    defaults are `use_cuda: false` / `use_dml: false` — three sessions
    (detect, classify, recognise) on the cores, 317 ms a picture on the
    5090 box with the card at 0% — and the CUDA provider needs the preload
    the tagger and the face detector need (`_ort.providers`), for the same
    reason. Readings are the same on either (measured)."""
    from . import _ort

    providers, _ = _ort.providers()
    first = providers[0] if providers else "CPUExecutionProvider"
    if first == "CUDAExecutionProvider":
        return {"EngineConfig.onnxruntime.use_cuda": True}
    if first == "DmlExecutionProvider":
        return {"EngineConfig.onnxruntime.use_dml": True}
    return {}


def _params(model_id):  # pragma: no cover - heavy optional dep
    """RapidOCR constructor params per variant.

    The multilingual model is PP-OCRv6's single multi recogniser (the
    package default). Korean and Cyrillic are not in its language set, so
    they resolve to PP-OCRv5 per-script mobile recognisers — which need the
    version AND the model type said out loud, or the resolver looks for a
    "small" build that script does not have.
    """
    from rapidocr import LangRec, ModelType, OCRVersion

    # The engine's answer FIRST: `_ort.providers` preloads CUDA's libraries
    # before anything opens a session.
    engine = _engine_params()
    base = {"Global.log_level": "error", **engine}
    if model_id == "rapidocr_korean":
        return {**base, "Rec.lang_type": LangRec.KOREAN,
                "Rec.ocr_version": OCRVersion.PPOCRV5,
                "Rec.model_type": ModelType.MOBILE}
    if model_id == "rapidocr_cyrillic":
        return {**base, "Rec.lang_type": LangRec.CYRILLIC,
                "Rec.ocr_version": OCRVersion.PPOCRV5,
                "Rec.model_type": ModelType.MOBILE}
    return base


#: The `lang` a variant may honestly stamp on a region: only the
#: single-language recogniser knows what script its answer is in.
_REGION_LANG = {"rapidocr_korean": "ko"}


def _models_dir():
    from pathlib import Path

    import rapidocr

    return Path(rapidocr.__file__).parent / "models"


def weights_ready() -> bool:
    """Whether any RapidOCR models are on disk. Import-GUARDED rather than
    import-free (InsightFace's probe never imports): RapidOCR keeps its
    models inside its own package, so there is no path to probe until the
    package is installed — and "not installed" is a correct False here,
    since `deps_ok` already reports the missing package separately."""
    try:
        d = _models_dir()
    except Exception:
        return False
    return d.is_dir() and any(d.glob("*.onnx"))


def fetch_weights() -> None:  # pragma: no cover - network
    """Construct each offered variant once and let RapidOCR self-download its
    models, so the first detection run is not a multi-minute silent stall."""
    from rapidocr import RapidOCR

    for spec in (MANIFEST.models if MANIFEST else []):
        RapidOCR(params=_params(spec.id))
    if not weights_ready():
        raise RuntimeError(f"no models landed in {_models_dir()}")


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    from rapidocr import RapidOCR

    return RapidOCR(params=_params(load_key))


def _norm_quad(points, w, h):  # pragma: no cover - heavy optional dep
    """Pixel points -> fraction points, clamped."""
    return [[round(min(1.0, max(0.0, float(x) / w)), 6),
             round(min(1.0, max(0.0, float(y) / h)), 6)] for x, y in points]


def _aabb(points):  # pragma: no cover - heavy optional dep
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x, y = min(xs), min(ys)
    return [x, y, round(max(xs) - x, 6), round(max(ys) - y, 6)]


def _upright(points, box):  # pragma: no cover - heavy optional dep
    """Whether the quad IS its bounding box — then it is omitted, so an
    upright region never carries a second copy of its own rectangle."""
    x, y, bw, bh = box
    corners = [[x, y], [x + bw, y], [x + bw, y + bh], [x, y + bh]]
    return all(abs(p[0] - c[0]) < 5e-4 and abs(p[1] - c[1]) < 5e-4
               for p, c in zip(points, corners))


def _word_children(entry, w, h, lang):  # pragma: no cover - heavy optional dep
    """One line's `word_results` entry -> word dicts. Defensive about shape:
    a version drift here should degrade to lines-only, not fail the run."""
    out = []
    try:
        for word in entry or ():
            text = str(word[0]).strip()
            points = word[2]
            if not text or points is None or len(points) != 4:
                continue
            quad = _norm_quad(points, w, h)
            child = {"level": "word", "box": _aabb(quad), "text": text,
                     "score": round(float(word[1]), 4)}
            if lang:
                child["lang"] = lang
            if not _upright(quad, child["box"]):
                child["quad"] = quad
            out.append(child)
    except (TypeError, ValueError, IndexError):
        return []
    return out


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy optional dep
    """Text as a BARE LIST of line regions with word children (a dict result
    would be misread by the worker's marshalling: a top-level "text" key is
    a caption). Boxes are fractions of the frame; list order is the engine's
    reading order."""
    import numpy as np

    rgb = image.convert("RGB")
    w, h = rgb.size
    if not w or not h:
        return []
    arr = np.asarray(rgb)
    try:
        res = handle(arr, return_word_box=True)
    except TypeError:
        # An engine build without word boxes still yields the lines.
        res = handle(arr)
    if res is None or not res.txts:
        return []
    lang = _REGION_LANG.get(model_id, "")
    words = list(getattr(res, "word_results", ()) or ())
    out = []
    for i, text in enumerate(res.txts):
        text = str(text).strip()
        if not text:
            continue
        quad = _norm_quad(res.boxes[i], w, h)
        box = _aabb(quad)
        if box[2] <= 0.001 or box[3] <= 0.001:
            continue
        line = {"level": "line", "box": box, "text": text,
                "score": round(float(res.scores[i]), 4)}
        if lang:
            line["lang"] = lang
        if not _upright(quad, box):
            line["quad"] = quad
        children = _word_children(words[i], w, h, lang) if i < len(words) else []
        # A line's single word is the line said twice — keep the hierarchy
        # only where it says something.
        if len(children) > 1:
            line["children"] = children
        out.append(line)
    return out

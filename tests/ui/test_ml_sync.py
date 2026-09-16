"""The editor's three SYNCHRONOUS model endpoints.

`/api/ml/apply`, `/api/ml/detect-regions` and `/api/ml/inpaint` are the ones
the image editor calls while somebody is looking at a picture — an interactive
operation, not a queued job — and none of them had a test of any kind. They
are also the routes with the most refusals per line: a kind the editor cannot
apply, a model nobody has set up, a reference the caller forgot, an upload
that is not an image, a model that answers nothing. Every one of those is a
sentence the editor puts in front of a person, and every one was unasserted.

The models themselves need heavy optional dependencies that are not installed
here (that is what `registry.available` is answering), so the MODEL is faked —
the host's `run` is monkeypatched, exactly as `test_ml_jobs.py` feeds synthetic
results to `_apply_*`. What is under test is the routing, the refusals and the
shape on the wire, which is the whole of what these three add over the job
queue.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from media_compost.ui.config import UiConfig
from media_compost.ui.plugins import registry
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library


@pytest.fixture
def client_lib(tmp_path: Path):
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c, lib
    app.dependency_overrides.clear()


def _png(size=(32, 24), fill=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, fill).save(buf, "PNG")
    return buf.getvalue()


def _mask(size=(32, 24)) -> bytes:
    """What the editor paints: opaque white on a transparent canvas."""
    im = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(im).rectangle([4, 4, 12, 12], fill=(255, 255, 255, 255))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _serve(monkeypatch, lib, result, *, kind="upscale", model="fake_model",
           needs_reference=False, available=True):
    """Put one fake model behind the registry and the warm host.

    Returns the list every call's `(kind, model, options)` lands in, so a test
    can assert what the route actually asked the model for — which is where
    the reference plumbing and the `detect_only` option live.
    """
    from media_compost.ui.plugins.framework import ModelSpec

    spec = ModelSpec(id=model, task=kind, name="Fake", family="Fake",
                     needs_reference=needs_reference)
    monkeypatch.setattr(registry, "resolve_model", lambda k, m="": model)
    monkeypatch.setattr(registry, "default_model", lambda k: model)
    monkeypatch.setattr(registry, "spec_for", lambda m: spec)
    monkeypatch.setattr(registry, "available", lambda m: available)
    seen: list[tuple] = []

    def run(task, model_id, img, ctx, options=None):
        seen.append((task, model_id, options or {}))
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(lib.model_host, "run", run)
    return seen


# ---- /api/ml/apply ----------------------------------------------------------


def test_apply_returns_the_models_png(client_lib, monkeypatch):
    client, lib = client_lib
    out = Image.new("RGB", (64, 48), (10, 200, 10))
    seen = _serve(monkeypatch, lib, out)
    r = client.post("/api/ml/apply",
                    files={"image": ("buf.png", _png(), "image/png")},
                    data={"kind": "upscale"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    # The BYTES are the point: the editor draws them straight into its buffer,
    # so a JSON envelope or a re-encode would be a different contract.
    got = Image.open(io.BytesIO(r.content))
    assert got.size == (64, 48)
    assert got.convert("RGB").getpixel((0, 0)) == (10, 200, 10)
    assert seen and seen[0][0] == "upscale"


@pytest.mark.parametrize("kind", sorted(
    {"upscale", "restore", "colorize", "descreen", "bg_removal"}))
def test_every_editor_appliable_kind_is_routed(client_lib, monkeypatch, kind):
    """The editor's Image menu offers exactly these five; a kind that stopped
    routing would be a menu entry that silently 400s."""
    client, lib = client_lib
    _serve(monkeypatch, lib, Image.new("RGB", (8, 8)), kind=kind)
    r = client.post("/api/ml/apply",
                    files={"image": ("buf.png", _png(), "image/png")},
                    data={"kind": kind})
    assert r.status_code == 200, r.text


def test_a_kind_the_editor_cannot_apply_is_refused(client_lib, monkeypatch):
    """`tag` and `caption` are real tasks and are NOT image-in/image-out, so
    they must not reach the host at all."""
    client, lib = client_lib
    seen = _serve(monkeypatch, lib, Image.new("RGB", (8, 8)))
    for kind in ("tag", "caption", "panels", "nonsense"):
        r = client.post("/api/ml/apply",
                        files={"image": ("buf.png", _png(), "image/png")},
                        data={"kind": kind})
        assert r.status_code == 400, (kind, r.text)
        assert "cannot be applied" in r.json()["detail"]
    assert seen == [], "a refused kind still ran a model"


def test_a_model_that_is_not_set_up_is_a_409(client_lib, monkeypatch):
    client, lib = client_lib
    _serve(monkeypatch, lib, Image.new("RGB", (8, 8)), available=False)
    r = client.post("/api/ml/apply",
                    files={"image": ("buf.png", _png(), "image/png")},
                    data={"kind": "upscale"})
    assert r.status_code == 409
    assert "set it up" in r.json()["detail"]


def test_an_upload_that_is_not_an_image_says_so(client_lib, monkeypatch):
    client, lib = client_lib
    _serve(monkeypatch, lib, Image.new("RGB", (8, 8)))
    r = client.post("/api/ml/apply",
                    files={"image": ("buf.png", b"not a png", "image/png")},
                    data={"kind": "upscale"})
    assert r.status_code == 400
    assert "readable image" in r.json()["detail"]


def test_a_model_that_produced_nothing_is_a_422(client_lib, monkeypatch):
    client, lib = client_lib
    _serve(monkeypatch, lib, None)
    r = client.post("/api/ml/apply",
                    files={"image": ("buf.png", _png(), "image/png")},
                    data={"kind": "upscale"})
    assert r.status_code == 422


def test_a_model_that_raised_is_reported_rather_than_leaking_a_traceback(
        client_lib, monkeypatch):
    client, lib = client_lib
    _serve(monkeypatch, lib, RuntimeError("the worker died: " + "x" * 900))
    r = client.post("/api/ml/apply",
                    files={"image": ("buf.png", _png(), "image/png")},
                    data={"kind": "upscale"})
    assert r.status_code == 500
    # Truncated: the message goes into a toast, and a 900-character worker
    # traceback is not something to put in one.
    assert len(r.json()["detail"]) <= 400
    assert "the worker died" in r.json()["detail"]


def test_a_reference_guided_model_refuses_to_run_without_one(client_lib,
                                                             monkeypatch):
    client, lib = client_lib
    seen = _serve(monkeypatch, lib, Image.new("RGB", (8, 8)),
                  kind="colorize", needs_reference=True)
    r = client.post("/api/ml/apply",
                    files={"image": ("buf.png", _png(), "image/png")},
                    data={"kind": "colorize"})
    assert r.status_code == 400
    assert "reference" in r.json()["detail"]
    # …and an id naming nothing in the refs store is the same refusal, not a
    # crash deep inside the model.
    r = client.post("/api/ml/apply",
                    files={"image": ("buf.png", _png(), "image/png")},
                    data={"kind": "colorize", "reference": "no-such-ref"})
    assert r.status_code == 400
    assert seen == [], "a model ran without the reference it requires"


def test_a_reference_reaches_the_model_as_a_PATH(client_lib, monkeypatch):
    """The refs store is a rolling directory of PNGs and the worker takes a
    filename — so what the route resolves an id into is the half worth
    pinning."""
    client, lib = client_lib
    seen = _serve(monkeypatch, lib, Image.new("RGB", (8, 8)),
                  kind="colorize", needs_reference=True)
    ref = client.post("/api/ml/refs",
                      files={"image": ("ref.png", _png(fill=(0, 0, 250)),
                                       "image/png")})
    assert ref.status_code == 200, ref.text
    rid = ref.json()["id"]
    r = client.post("/api/ml/apply",
                    files={"image": ("buf.png", _png(), "image/png")},
                    data={"kind": "colorize", "reference": rid})
    assert r.status_code == 200, r.text
    assert len(seen) == 1
    path = Path(seen[0][2]["reference"])
    assert path.is_file(), path
    assert path.is_absolute()


# ---- /api/ml/detect-regions -------------------------------------------------


def test_watermark_detection_passes_the_regions_straight_back(client_lib,
                                                              monkeypatch):
    client, lib = client_lib
    regions = [[[0.1, 0.1], [0.4, 0.1], [0.4, 0.2], [0.1, 0.2]]]
    seen = _serve(monkeypatch, lib, {"regions": regions},
                  kind="watermark_removal")
    r = client.post("/api/ml/detect-regions",
                    files={"image": ("buf.png", _png(), "image/png")},
                    data={"kind": "watermark"})
    assert r.status_code == 200, r.text
    assert r.json() == {"regions": regions}
    # `detect_only` is what makes the watermark plugin answer with boxes
    # instead of inpainting the picture — the whole difference between this
    # route and a removal job.
    assert seen[0][2].get("detect_only") is True
    assert seen[0][0] == "watermark_removal"


def test_text_detection_goes_to_an_OCR_ENGINE(client_lib, monkeypatch):
    """Not a detector of its own: there is ONE idea of where the text on a
    page is, and it is the reading the Text tab shows."""
    client, lib = client_lib
    seen = _serve(monkeypatch, lib, [], kind="ocr")
    client.post("/api/ml/detect-regions",
                files={"image": ("buf.png", _png(), "image/png")},
                data={"kind": "text"})
    assert seen[0][0] == "ocr"


def test_an_ocr_reading_comes_back_as_its_LEAF_polygons(client_lib,
                                                        monkeypatch):
    """A block box is a whole speech bubble; selecting one would select the
    art inside it. So the tree is walked to its leaves — and a leaf's `quad`
    wins over its `box`, because slanted text draws its quad."""
    client, lib = client_lib
    quad = [[0.5, 0.5], [0.7, 0.52], [0.7, 0.6], [0.5, 0.58]]
    tree = [{
        "box": [0.0, 0.0, 1.0, 1.0],            # the block: must NOT appear
        "children": [
            {"box": [0.1, 0.1, 0.2, 0.05]},     # a line, box only
            {"box": [0.5, 0.5, 0.2, 0.1], "quad": quad},  # …and one slanted
        ],
    }]
    _serve(monkeypatch, lib, tree, kind="ocr")
    r = client.post("/api/ml/detect-regions",
                    files={"image": ("buf.png", _png(), "image/png")},
                    data={"kind": "text"})
    got = r.json()["regions"]
    assert len(got) == 2, got
    # The box-only leaf became a rectangle wound the same way a quad is.
    # Flattened before comparing: `approx` refuses a nested structure, and
    # x + w is float addition — 0.1 + 0.2 is not 0.3.
    flat = [v for point in got[0] for v in point]
    assert flat == pytest.approx([0.1, 0.1, 0.3, 0.1, 0.3, 0.15, 0.1, 0.15])
    assert got[1] == quad


def test_an_unknown_detection_kind_is_refused(client_lib, monkeypatch):
    client, lib = client_lib
    seen = _serve(monkeypatch, lib, {"regions": []})
    r = client.post("/api/ml/detect-regions",
                    files={"image": ("buf.png", _png(), "image/png")},
                    data={"kind": "faces"})
    assert r.status_code == 400
    assert "unknown detection kind" in r.json()["detail"]
    assert seen == []


def test_detection_with_no_engine_set_up_is_a_409(client_lib, monkeypatch):
    client, lib = client_lib
    _serve(monkeypatch, lib, [], kind="ocr", available=False)
    r = client.post("/api/ml/detect-regions",
                    files={"image": ("buf.png", _png(), "image/png")},
                    data={"kind": "text"})
    assert r.status_code == 409
    assert "not available" in r.json()["detail"]


def test_a_detector_answering_nothing_is_an_empty_list_not_an_error(
        client_lib, monkeypatch):
    """A page with no text is the ordinary case, and the editor renders the
    answer directly — so it has to be a list rather than a 4xx."""
    client, lib = client_lib
    _serve(monkeypatch, lib, None, kind="ocr")
    r = client.post("/api/ml/detect-regions",
                    files={"image": ("buf.png", _png(), "image/png")},
                    data={"kind": "text"})
    assert r.status_code == 200 and r.json() == {"regions": []}


# ---- /api/ml/inpaint --------------------------------------------------------


def test_inpaint_refuses_a_checkpoint_it_does_not_have(client_lib):
    from media_compost.ui import inpaint as inpaint_mod

    client, _lib = client_lib
    assert set(inpaint_mod.LAMA_MODELS) == {"big_lama", "anime_lama"}
    r = client.post("/api/ml/inpaint",
                    files={"image": ("buf.png", _png(), "image/png"),
                           "mask": ("mask.png", _mask(), "image/png")},
                    data={"model": "no_such_lama"})
    assert r.status_code == 400
    assert "unknown inpainting model" in r.json()["detail"]


def test_inpaint_without_torch_says_what_to_install(client_lib):
    """The honest failure on a machine with no weights: a sentence naming
    Settings → Models, not a traceback out of `get_lama`."""
    client, _lib = client_lib
    r = client.post("/api/ml/inpaint",
                    files={"image": ("buf.png", _png(), "image/png"),
                           "mask": ("mask.png", _mask(), "image/png")})
    # Either it ran (a dev box with the weights) or it refused in words.
    assert r.status_code in (200, 400)
    if r.status_code == 400:
        assert "Settings" in r.json()["detail"]


def test_inpaint_binarizes_the_mask_and_keeps_the_sources_alpha(client_lib,
                                                                monkeypatch):
    """The two rules the route owns rather than the model: the editor paints
    OPAQUE WHITE on a TRANSPARENT canvas, so the alpha channel is the mask
    (not its luminance, which is white everywhere it is painted and black
    where it is clear); and inpainting does not change transparency, so an
    RGBA source keeps the alpha it arrived with."""
    from media_compost.ui import inpaint as inpaint_mod

    client, _lib = client_lib
    seen: list = []

    def fake_lama(lama, rgb, mask):
        seen.append((rgb.copy(), mask.copy()))
        return Image.new("RGB", rgb.size, (7, 7, 7))

    monkeypatch.setattr(inpaint_mod, "get_lama", lambda **kw: object())
    monkeypatch.setattr(inpaint_mod, "run_lama", fake_lama)

    src = Image.new("RGBA", (32, 24), (9, 9, 9, 128))
    buf = io.BytesIO()
    src.save(buf, "PNG")
    r = client.post("/api/ml/inpaint",
                    files={"image": ("buf.png", buf.getvalue(), "image/png"),
                           "mask": ("mask.png", _mask(), "image/png")},
                    data={"model": "big_lama"})
    assert r.status_code == 200, r.text
    assert len(seen) == 1
    _rgb, mask = seen[0]
    assert mask.mode == "L"
    # Binary: every pixel is one end or the other, never a grey the model
    # would read as "half masked".
    assert set(mask.tobytes()) <= {0, 255}
    assert mask.getpixel((8, 8)) == 255 and mask.getpixel((30, 22)) == 0

    out = Image.open(io.BytesIO(r.content))
    assert out.mode in ("RGBA", "LA")
    assert out.getpixel((0, 0))[3] == 128, "the source's alpha was dropped"


def test_a_mask_of_another_size_is_resized_to_the_picture(client_lib,
                                                          monkeypatch):
    """The editor can hand over a mask drawn at the display resolution; a
    size mismatch must not reach the model, where it fails as a shape error."""
    from media_compost.ui import inpaint as inpaint_mod

    client, _lib = client_lib
    seen: list = []
    monkeypatch.setattr(inpaint_mod, "get_lama", lambda **kw: object())
    monkeypatch.setattr(inpaint_mod, "run_lama",
                        lambda lama, rgb, mask: (seen.append((rgb.size,
                                                              mask.size)),
                                                 Image.new("RGB", rgb.size))[1])
    r = client.post("/api/ml/inpaint",
                    files={"image": ("buf.png", _png((64, 48)), "image/png"),
                           "mask": ("mask.png", _mask((32, 24)), "image/png")},
                    data={"model": "big_lama"})
    assert r.status_code == 200, r.text
    assert seen == [((64, 48), (64, 48))]

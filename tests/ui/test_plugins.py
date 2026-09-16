"""Plugin framework + registry integrity.

Grows as models are migrated to plugins; for now it validates the fixed task set,
the registry accessors, and that every registered plugin's manifest imports with
no heavy ML dependency and is internally consistent.
"""

from __future__ import annotations

import fnmatch
import inspect

from media_compost.ui.plugins import registry, tasks


def test_fixed_tasks():
    kinds = tasks.task_kinds()
    assert kinds == {"bg_removal", "watermark_removal", "text_removal", "tag", "caption",
                     "depth", "pose", "canny", "lineart", "panels", "upscale",
                     "restore", "colorize", "descreen", "faces", "ocr",
                     "embed", "watermark_detect"}
    for t in tasks.TASKS:
        assert t.result in ("image", "caption", "tags", "artifact", "items",
                            "faces", "ocr", "vector", "boxes")
        assert t.label and t.icon


def test_registry_accessors_consistent():
    registry.reset()
    all_kinds = tasks.task_kinds()
    seen_ids: set[str] = set()
    for plug in registry.plugins():
        for spec in plug.models():
            # Every model targets a known fixed task and has a unique id.
            assert spec.task in all_kinds, f"{spec.id} -> unknown task {spec.task}"
            assert spec.id not in seen_ids, f"duplicate model id {spec.id}"
            seen_ids.add(spec.id)
            # A model's declared source key (if any) must exist.
            key = plug.source_key_for(spec.id)
            if key:
                assert registry.source_for(key) is not None
        # Sources declare their own key + a cache probe.
        for src in plug.manifest.sources:
            assert src.key and src.probe

    # Union of models across tasks == every registered model id.
    union = {m.id for k in all_kinds for m in registry.models_for(k)}
    assert union == seen_ids


def test_plugin_for_and_sources():
    registry.reset()
    for src in registry.all_sources():
        assert registry.source_for(src.key) is src
    for plug in registry.plugins():
        for spec in plug.models():
            assert registry.plugin_for(spec.id) is plug


def test_canny_plugin_produces_edge_image():
    """The Canny plugin runs with no model download and returns an RGB image."""
    import numpy as np
    import pytest
    from PIL import Image

    pytest.importorskip("cv2")   # optional AI dep (requirements-ai.txt)
    from media_compost.ui.plugins.impl import canny

    img = Image.fromarray((np.random.rand(80, 100, 3) * 255).astype("uint8"))
    handle = canny.load("canny", {})
    out = canny.run("canny", "canny", handle, img, {})["image"]
    assert out.size == (100, 80) and out.mode == "RGB"


def test_yolo_pose_renders_openpose_skeleton_on_black():
    """The pose plugin renders an OpenPose control image (colored skeleton on a
    black background) from COCO-17 keypoints."""
    import numpy as np

    from media_compost.ui.plugins.impl import yolo_pose

    # A synthetic standing person (17 COCO keypoints, all confident).
    person = [
        (100, 40, 0.9), (95, 35, 0.9), (105, 35, 0.9), (90, 38, 0.9), (110, 38, 0.9),
        (80, 80, 0.9), (120, 80, 0.9), (70, 120, 0.9), (130, 120, 0.9),
        (65, 160, 0.9), (135, 160, 0.9), (85, 160, 0.9), (115, 160, 0.9),
        (83, 220, 0.9), (117, 220, 0.9), (82, 280, 0.9), (118, 280, 0.9),
    ]
    canvas = yolo_pose._draw_openpose((200, 300), [person])
    arr = np.asarray(canvas)
    assert canvas.mode == "RGB"
    # Mostly black, but the skeleton drew some colored pixels.
    assert (arr.sum(2) == 0).sum() > arr.shape[0] * arr.shape[1] * 0.5
    assert (arr.sum(2) > 0).sum() > 100


def test_zero_byte_incomplete_blob_is_ignored(tmp_path, monkeypatch):
    """A 0-byte `.incomplete` leftover must not mark a repo as still-downloading
    (the MiDaS symptom); a non-empty one still does."""
    import huggingface_hub.constants as hfc

    from media_compost.hub import cache as hubcache

    repo = "Intel/dpt-hybrid-midas"
    blobs = tmp_path / hubcache._repo_dirname(repo) / "blobs"
    blobs.mkdir(parents=True)
    (blobs / "aaaa").write_bytes(b"complete weights")
    monkeypatch.setattr(hfc, "HF_HUB_CACHE", str(tmp_path))

    # Only a 0-byte incomplete -> ignored.
    (blobs / "9599.a62946ff.incomplete").write_bytes(b"")
    assert hubcache._has_incomplete_blobs(repo) is False

    # A non-empty incomplete -> genuine partial download.
    (blobs / "bbbb.cc.incomplete").write_bytes(b"half a file")
    assert hubcache._has_incomplete_blobs(repo) is True

def test_text_detection_is_script_agnostic():
    """Text removal runs EasyOCR detection-only (CRAFT), which is shared across
    all languages — the Reader's language list only selects the (unused)
    recognizer. Render non-English text (umlauts + CJK) and require the
    detector to find it. Skipped when easyocr / its weights / a CJK font are
    unavailable (heavy optional dep)."""
    import os

    import pytest

    easyocr = pytest.importorskip("easyocr")
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    if not os.path.isfile(os.path.expanduser("~/.EasyOCR/model/craft_mlt_25k.pth")):
        pytest.skip("EasyOCR detector weights not downloaded")

    # One font per script (a single font rarely covers Hangul AND Han glyphs;
    # text rendered as tofu boxes would test nothing). macOS system fonts.
    def _font(*cands):
        for cand in cands:
            try:
                return ImageFont.truetype(cand, 48)
            except OSError:
                continue
        return None

    samples = [
        ("Straßenüberführung", _font("/System/Library/Fonts/Helvetica.ttc")),
        ("今天天气很好", _font("/System/Library/Fonts/STHeiti Medium.ttc",
                        "/System/Library/Fonts/PingFang.ttc")),
        ("안녕하세요", _font("/System/Library/Fonts/AppleSDGothicNeo.ttc")),
    ]
    samples = [(t, f) for t, f in samples if f is not None]
    if not samples:
        pytest.skip("no suitable system fonts found")

    reader = easyocr.Reader(["en"], gpu=False, recognizer=False,
                            download_enabled=False, verbose=False)
    rng = np.random.default_rng(7)
    for text, font in samples:
        bg = rng.integers(90, 170, (200, 640, 3), dtype=np.uint8)
        im = Image.fromarray(bg, "RGB")
        ImageDraw.Draw(im).text((30, 70), text, fill=(250, 250, 250), font=font)
        horizontal, free = reader.detect(np.asarray(im))
        rects = horizontal[0] if horizontal else []
        quads = free[0] if free else []
        assert len(rects) + len(quads) > 0, f"no detection for {text!r}"


def test_descreen_flattens_halftone_and_keeps_lines():
    """The descreen plugin melts a halftone dot grid into a smooth grey while a
    thick line-art stroke stays dark and crisp."""
    import numpy as np
    import pytest
    from PIL import Image

    pytest.importorskip("cv2")   # optional AI dep (requirements-ai.txt)
    from media_compost.ui.plugins.impl import descreen

    # Synthetic screened page: ~25% coverage dot grid (3px dots at 6px pitch)
    # plus a solid 8px vertical stroke.
    w = h = 384
    src = np.full((h, w), 255, np.uint8)
    for y in range(0, h, 6):
        for x in range(0, w, 6):
            src[y:y + 3, x:x + 3] = 0
    src[:, 180:188] = 0
    out = descreen.run("descreen", "descreen", None,
                       Image.fromarray(src, "L"), {})["image"]
    g = np.asarray(out.convert("L")).astype(np.float32)

    region = g[40:140, 20:120]                  # dots only, away from the line
    orig = src[40:140, 20:120].astype(np.float32)
    assert orig.std() > 90                      # sanity: input really is dotted
    assert region.std() < 20                    # tones melted into a flat grey
    assert 130 < region.mean() < 230            # ~25% ink → light-mid grey
    assert g[:, 182:186].mean() < 90            # the stroke stayed dark


def test_opencomic_descreen_flattens_halftone():
    """The OpenComic NCNN descreen model melts a halftone grid into smooth grey
    while keeping a solid stroke dark. Skipped until ncnn is installed and the
    weights are cached (they auto-download on first real use)."""
    import numpy as np
    import pytest
    from PIL import Image

    pytest.importorskip("ncnn")
    from pathlib import Path

    from media_compost.ui.plugins.impl import descreen_opencomic as oc

    stem = oc._FILES["opencomic_descreen_compact"]
    cache = Path.home() / ".cache" / "media-compost" / "opencomic"
    if not (cache / (stem + ".bin")).is_file():
        pytest.skip("OpenComic weights not cached")

    w = h = 256
    src = np.full((h, w), 255, np.uint8)
    for y in range(0, h, 6):
        for x in range(0, w, 6):
            src[y:y + 3, x:x + 3] = 0
    src[:, 120:128] = 0
    net = oc.load("opencomic_descreen_compact", {})
    out = oc.run("descreen", "opencomic_descreen_compact", net,
                 Image.fromarray(src, "L").convert("RGB"), {})["image"]
    g = np.asarray(out.convert("L")).astype(np.float32)
    region = g[40:120, 20:100]
    assert region.std() < 30                    # tones melted
    assert g[:, 122:126].mean() < 90            # the stroke stayed dark


def test_setup_commands_route_torch_through_the_index_step():
    """PyPI's Windows torch wheel is CPU-only, so a synthesized main-env
    setup must not `pip install torch` — the pair is split out of the pip
    line and appended as `setup_env torch` (which owns the index
    decision), LAST, so nothing installed before it can drag a CPU build
    back in over it. The step is `-m media_compost.hub.setup_env`, never a
    checkout-relative file: a wheel install has no `scripts/` directory,
    and a file path there is exactly what broke every setup on one."""
    from media_compost.ui.plugins.framework import PluginManifest, setup_commands

    torchy = PluginManifest(models=[], deps=("torch", "transformers",
                                             "torchvision"))
    got = setup_commands(torchy)
    assert got == ["{pip} install transformers",
                   "{python} -m media_compost.hub.setup_env torch"]

    plain = PluginManifest(models=[], deps=("rapidocr", "cv2"))
    assert setup_commands(plain) == [
        "{pip} install rapidocr opencv-python-headless"]

    # onnxruntime is the same trap on every platform (PyPI's wheel has no
    # GPU provider; the CUDA build is another package that must REPLACE
    # it), so it goes through its own setup_env mode, after the pip line
    # — where a dependency of the rest could drag the CPU wheel back —
    # and before torch.
    ort = PluginManifest(models=[], deps=("onnxruntime", "cv2", "torch"))
    assert setup_commands(ort) == [
        "{pip} install opencv-python-headless",
        "{python} -m media_compost.hub.setup_env onnxruntime",
        "{python} -m media_compost.hub.setup_env torch"]
    ort_only = PluginManifest(models=[], deps=("onnxruntime",))
    assert setup_commands(ort_only) == [
        "{python} -m media_compost.hub.setup_env onnxruntime"]

    torch_only = PluginManifest(models=[], deps=("torch",))
    assert setup_commands(torch_only) == [
        "{python} -m media_compost.hub.setup_env torch"]

    dedicated = PluginManifest(models=[], deps=("torch",), env="magi")
    assert setup_commands(dedicated) == [
        "{python} -m media_compost.hub.setup_env magi"]

    explicit = PluginManifest(models=[], deps=("torch",),
                              setup=("echo custom",))
    assert setup_commands(explicit) == ["echo custom"]


def _load_setup_env():
    """`media_compost/hub/setup_env.py` is standalone (pure stdlib) — the
    tests load it by file path like the trainer's scripts to hold that."""
    import importlib.util
    from pathlib import Path

    path = (Path(__file__).resolve().parents[2]
            / "media_compost" / "hub" / "setup_env.py")
    spec = importlib.util.spec_from_file_location("mc_setup_env", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_setup_env_torch_mode_installs_from_the_chosen_index(monkeypatch):
    """`setup_env.py torch` repairs an EXISTING env: plain install first (a
    no-op when torch is present; brings torch's own deps otherwise), then the
    `--index-url --force-reinstall --no-deps` pass exactly when this machine
    needs a non-PyPI index. Driven with MEDIA_COMPOST_TORCH_INDEX, the same
    override the venv flow honours."""
    mod = _load_setup_env()

    calls: list[list[str]] = []
    monkeypatch.setattr(mod, "run", lambda cmd: calls.append(
        [str(c) for c in cmd]))
    monkeypatch.setattr(mod, "verify_cuda", lambda py: None)
    monkeypatch.setattr(mod, "pip_cmd", lambda py: [str(py), "-m", "pip"])

    monkeypatch.setenv("MEDIA_COMPOST_TORCH_INDEX",
                       "https://example.invalid/whl/cu999")
    assert mod.setup_main_torch("PY") == 0
    assert calls[0] == ["PY", "-m", "pip", "install", "torch", "torchvision"]
    assert calls[1] == ["PY", "-m", "pip", "install", "--index-url",
                        "https://example.invalid/whl/cu999",
                        "--force-reinstall", "--no-deps",
                        "torch", "torchvision"]

    calls.clear()
    monkeypatch.setenv("MEDIA_COMPOST_TORCH_INDEX", "none")
    assert mod.setup_main_torch("PY") == 0
    assert calls == [["PY", "-m", "pip", "install", "torch", "torchvision"]]


def test_setup_env_onnxruntime_mode_picks_the_build_for_the_machine(
        monkeypatch):
    """`setup_env.py onnxruntime`: with an NVIDIA driver, `onnxruntime-gpu`
    with its CUDA-runtime and cuDNN extras; without one the plain wheel.
    BOTH names are uninstalled first (they are one package directory under
    two names, and a CPU wheel installed over the GPU one — what a plain
    `pip install` of a plugin's deps did — leaves a half-overwritten
    package pip still calls satisfied); the uninstalls may fail (nothing
    installed yet) without stopping the install. A healthy install of the
    wanted build is left alone."""
    mod = _load_setup_env()

    calls: list[tuple[list[str], bool]] = []
    monkeypatch.setattr(mod, "run", lambda cmd, check=True: calls.append(
        ([str(c) for c in cmd], check)))
    monkeypatch.setattr(mod, "verify_ort", lambda py: True)
    monkeypatch.setattr(mod, "pip_cmd", lambda py: [str(py), "-m", "pip"])
    monkeypatch.setattr(mod, "ort_state", lambda py: (
        ["onnxruntime"], ["CPUExecutionProvider"]))

    monkeypatch.setattr(mod, "wants_ort_gpu", lambda: True)
    assert mod.setup_main_onnxruntime("PY") == 0
    assert calls == [
        (["PY", "-m", "pip", "uninstall", "-y", "onnxruntime"], False),
        (["PY", "-m", "pip", "uninstall", "-y", "onnxruntime-gpu"], False),
        (["PY", "-m", "pip", "install", "onnxruntime-gpu[cuda,cudnn]"], True)]

    # The GPU build present but half-overwritten (no providers): repaired.
    calls.clear()
    monkeypatch.setattr(mod, "ort_state", lambda py: (
        ["onnxruntime-gpu"], None))
    assert mod.setup_main_onnxruntime("PY") == 0
    assert [c[0][-1] for c in calls] == [
        "onnxruntime", "onnxruntime-gpu", "onnxruntime-gpu[cuda,cudnn]"]

    # Healthy: nothing runs.
    calls.clear()
    monkeypatch.setattr(mod, "ort_state", lambda py: (
        ["onnxruntime-gpu"], ["CUDAExecutionProvider",
                              "CPUExecutionProvider"]))
    assert mod.setup_main_onnxruntime("PY") == 0
    assert calls == []

    # No driver: the plain wheel, replacing a GPU build left behind.
    monkeypatch.setattr(mod, "wants_ort_gpu", lambda: False)
    assert mod.setup_main_onnxruntime("PY") == 0
    assert [c[0][-1] for c in calls] == [
        "onnxruntime", "onnxruntime-gpu", "onnxruntime"]
    calls.clear()
    monkeypatch.setattr(mod, "ort_state", lambda py: (
        ["onnxruntime"], ["CPUExecutionProvider"]))
    assert mod.setup_main_onnxruntime("PY") == 0
    assert calls == []

    # `uv pip uninstall` never asks and rejects `-y`.
    monkeypatch.setattr(mod, "pip_cmd", lambda py: ["uv", "pip", "--python",
                                                    str(py)])
    assert mod.uninstall_cmd("PY") == ["uv", "pip", "--python", "PY",
                                       "uninstall"]


def test_ort_nvidia_dll_dirs_finds_every_wheel_directory_holding_a_dll(
        tmp_path):
    """Windows: cuDNN loads its sub-libraries by NAME through the process
    search path, so every DLL directory of the `nvidia` wheels must be put
    on it (`_ort._add_nvidia_dll_dirs`) — `nvidia/cudnn/bin` and the
    nested `nvidia/cu13/bin/x86_64` alike, each once, nothing without a
    DLL in it."""
    from media_compost.ui.plugins.impl import _ort

    root = tmp_path / "nvidia"
    (root / "cudnn" / "bin").mkdir(parents=True)
    (root / "cudnn" / "bin" / "cudnn64_9.dll").write_bytes(b"")
    (root / "cudnn" / "bin" / "cudnn_cnn64_9.dll").write_bytes(b"")
    (root / "cu13" / "bin" / "x86_64").mkdir(parents=True)
    (root / "cu13" / "bin" / "x86_64" / "cublas64_13.dll").write_bytes(b"")
    (root / "cu13" / "include").mkdir()
    (root / "cu13" / "include" / "cublas.h").write_bytes(b"")
    got = _ort.nvidia_dll_dirs([str(root)])
    assert got == [str(root / "cu13" / "bin" / "x86_64"),
                   str(root / "cudnn" / "bin")]
    assert _ort.nvidia_dll_dirs([]) == []


def test_repo_files_resolves_a_narrowed_download_file_by_file(tmp_path,
                                                             monkeypatch):
    """`framework.repo_files` asks the hub for each named file — never
    `snapshot_download`, which offline REFUSES the narrowed snapshot the
    app's own setup leaves behind (huggingface_hub 1.x
    `IncompleteSnapshotError`) — and hands back their one directory; a
    local folder is returned as is."""
    import huggingface_hub

    from media_compost.ui.plugins.framework import repo_files

    snap = tmp_path / "snap"
    snap.mkdir()
    asked: list[tuple] = []

    def fake(repo, name, local_files_only=False, token=None):
        asked.append((repo, name, local_files_only, token))
        (snap / name).write_bytes(b"x")
        return str(snap / name)

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", fake)
    got = repo_files("a/b", ("model.onnx", "tags.csv"),
                     {"local_files_only": True, "token": ""})
    assert got == str(snap)
    assert asked == [("a/b", "model.onnx", True, None),
                     ("a/b", "tags.csv", True, None)]
    assert repo_files(str(tmp_path), ("x",), {}) == str(tmp_path)


def test_no_plugin_loads_through_snapshot_download():
    """A load must resolve its files by NAME (`framework.repo_files` or
    `hf_hub_download`): the app fetches every source narrowed by
    `allow_patterns`, and an offline `snapshot_download` refuses exactly
    that. RAM++'s `fetch_weights` is the one caller, online by nature."""
    from pathlib import Path

    impl = Path(__file__).resolve().parents[2] / "media_compost" / "ui" \
        / "plugins" / "impl"
    offenders = sorted(p.name for p in impl.glob("*.py")
                       if "snapshot_download(" in p.read_text(encoding="utf-8")
                       and p.name != "ram_plus.py")
    assert offenders == []


def test_setup_env_ort_state_reads_the_running_interpreter():
    """The probe asks the TARGET interpreter; here that is this one, which
    has no onnxruntime by contract (the main venv is model-free) — or
    whatever it has, reported consistently."""
    import sys

    mod = _load_setup_env()
    names, providers = mod.ort_state(sys.executable)
    assert isinstance(names, list)
    if not names:
        assert providers is None
    assert mod.ort_state("/nonexistent/python") == ([], None)


def test_setup_env_wants_the_gpu_onnxruntime_only_where_a_wheel_exists(
        monkeypatch):
    """An NVIDIA driver on Linux or Windows; never macOS (no CUDA build),
    never without the driver."""
    import sys

    mod = _load_setup_env()
    monkeypatch.setattr(mod, "has_nvidia", lambda: True)
    monkeypatch.setattr(sys, "platform", "linux")
    assert mod.wants_ort_gpu()
    monkeypatch.setattr(sys, "platform", "win32")
    assert mod.wants_ort_gpu()
    monkeypatch.setattr(sys, "platform", "darwin")
    assert not mod.wants_ort_gpu()
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(mod, "has_nvidia", lambda: False)
    assert not mod.wants_ort_gpu()


def test_setup_env_pip_cmd_prefers_pip_and_falls_back_to_uv(tmp_path,
                                                            monkeypatch):
    """pip stays the first choice — uv on PATH must not change behavior for
    an env that has pip — and `uv pip --python <py>` steps in only where the
    env has none (a venv made by `uv venv`). With neither, the pip form
    comes back so the failure is pip's own clear error."""
    import shutil
    import sys

    mod = _load_setup_env()
    assert mod.pip_cmd(sys.executable) == [sys.executable, "-m", "pip"]

    if sys.platform == "win32":
        return  # the fake pip-less interpreter below is a shell script

    fake = tmp_path / "python"
    fake.write_text("#!/bin/sh\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setattr(shutil, "which",
                        lambda name: "/opt/uv" if name == "uv" else None)
    assert mod.pip_cmd(fake) == ["uv", "pip", "--python", str(fake)]

    fake2 = tmp_path / "python2"
    fake2.write_text("#!/bin/sh\nexit 1\n")
    fake2.chmod(0o755)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert mod.pip_cmd(fake2) == [str(fake2), "-m", "pip"]


# ---- telemetry --------------------------------------------------------------


def test_every_process_that_can_load_onnxruntime_turns_its_telemetry_off():
    """onnxruntime grew a Microsoft 1DS telemetry client on every platform at
    1.29 (Windows-only ETW before): the first InferenceSession creates an
    offline event queue plus a persisted device id under "~/Library/
    Application Support/Microsoft/DeveloperTools/.onnxruntime/" and flushes it
    to mobile.events.data.microsoft.com — reported as a firewall alert minutes
    after a background-removal job. Four plugins reach onnxruntime (withoutbg
    and wd_tagger directly, rapidocr and insightface through their own
    libraries), so the OFF is at the process entries rather than per plugin:
    the worker loop every job runs in, the setup warm-up's own process, and
    the host's spawn env (said again where the child is made, like the HF
    variable beside it)."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "media_compost"
    line = 'os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")'
    for rel in ("ui/plugins/worker.py", "ui/plugins/setup_action.py"):
        assert line in (root / rel).read_text(encoding="utf-8"), rel
    assert 'env.setdefault("ORT_DISABLE_TELEMETRY", "1")' in (
        root / "ui/plugins/host.py").read_text(encoding="utf-8")


def test_onnxruntime_still_honours_the_off_switch(tmp_path):
    """The variable is onnxruntime's, not ours, so this drives the real thing
    where it is installed: a session under a sandboxed HOME with the switch
    set must create NO Microsoft telemetry directory — measured without it,
    one 65-byte identity model's session writes the event store and the
    device id. If a future onnxruntime renames or drops the variable, the
    directory appears and this fails loudly. (The unset direction is
    deliberately not driven: it would queue real telemetry and may dial out.)
    """
    import base64
    import subprocess
    import sys

    import pytest

    pytest.importorskip("onnxruntime")
    model = tmp_path / "tiny.onnx"
    model.write_bytes(base64.b64decode(
        "CA06NwoQCgF4EgF5IghJZGVudGl0eRIBdFoPCgF4EgoKCAgBEgQKAggBYg8KAXkSCgoI"
        "CAESBAoCCAFCBAoAEBE="))
    home = tmp_path / "home"
    home.mkdir()
    code = (
        "import onnxruntime as ort, numpy as np\n"
        f"s = ort.InferenceSession({str(model)!r},"
        " providers=['CPUExecutionProvider'])\n"
        "s.run(None, {'x': np.zeros(1, dtype=np.float32)})\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=120,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin",
             "ORT_DISABLE_TELEMETRY": "1"},
    )
    assert out.returncode == 0, out.stderr
    written = [str(p.relative_to(home)) for p in home.rglob("*") if p.is_file()]
    assert not any("Microsoft" in p or "onnxruntime" in p for p in written), \
        written


def test_A_PLUGINS_OWN_WEIGHTS_COUNT_TOWARD_ITS_SOURCE_ROWS_READINESS(monkeypatch):
    """A source is not always the whole of a model's weights.

    RAM++ declares its checkpoint and then pulls a BERT tokenizer from a second
    repo, from inside the `ram` package — so a fresh install read "Downloaded"
    off the checkpoint probe alone and the first tagging run went to the
    network, which on an offline machine is not a surprise but a failure (and
    `jobs.py` promises those runs never touch the network). `weights_ready()`
    is the hook that says otherwise, and it was consulted ONLY for plugins with
    no sources at all — so RAM++ could not have used it, and
    `colorize_mangav2`, which had written one, was never asked.
    """
    registry.reset()
    plug = registry.plugin_for_source("ram_plus")
    assert plug is not None and plug.key == "ram_plus"
    assert registry.plugin_can_fetch("ram_plus"), \
        "a plugin whose weights are not all in its sources must be able to fetch them"

    monkeypatch.setattr(plug.module, "weights_ready", lambda: False)
    assert registry.source_weights_ready("ram_plus") is False
    monkeypatch.setattr(plug.module, "weights_ready", lambda: True)
    assert registry.source_weights_ready("ram_plus") is True

    # A source whose plugin says nothing is ready by that measure, and an
    # unknown key must not read as "not ready" — every other source row
    # depends on this answering True.
    assert registry.source_weights_ready("wd_tagger") is True
    assert registry.source_weights_ready("nope") is True


def test_ram_plus_declares_the_tokenizer_repo_it_loads():
    """The constant `fetch_weights` prefetches must be the one `load()` asks
    for — the whole bug was a repo named nowhere but inside a third-party
    package."""
    from media_compost.ui.plugins.impl import ram_plus

    src = inspect.getsource(ram_plus.load)
    assert "text_encoder_type=_TEXT_ENCODER" in src
    src = inspect.getsource(ram_plus.fetch_weights)
    assert "_TEXT_ENCODER" in src and "_TOKENIZER_FILES" in src
    # The probe may never be stricter than the fetch, or the row sits on a
    # Download button that pressing Download can never turn green.
    assert "_TOKENIZER_FILES" in inspect.getsource(ram_plus.weights_ready)


def test_a_chained_fetch_runs_the_second_half_and_reports_the_first(monkeypatch):
    """The Download button on such a row has to finish BOTH halves."""
    from media_compost.hub.download import DONE, ERROR, RUNNING
    from media_compost.ui.plugin_fetch import ChainedFetch

    class Fake:
        def __init__(self, st=RUNNING):
            self.st, self.started, self.canceled = st, False, False
            self.progress, self.error = 42, ""
            self.done_bytes, self.total_bytes = 7, 9

        def start(self): self.started = True
        def status(self): return self.st
        def cancel(self): self.canceled = True

    first, second = Fake(), Fake()
    c = ChainedFetch(first, second)
    c.start()
    assert first.started and not second.started
    # While the first runs, the row shows the first's bytes and percentage.
    assert c.status() == RUNNING and c.progress == 42 and c.total_bytes == 9
    # The first finishing is NOT the whole download.
    first.st = DONE
    assert c.status() == RUNNING, "reporting DONE here forgets the second half"
    c._chain()                      # what the watcher thread does
    assert second.started
    assert c.status() == RUNNING
    second.st = DONE
    assert c.status() == DONE
    # A failed first half never starts the second.
    a, b = Fake(ERROR), Fake()
    c2 = ChainedFetch(a, b)
    c2._chain()
    assert not b.started


def test_EVERY_SOURCE_SAYS_WHICH_FILES_IT_NEEDS():
    """`allow_patterns` unset means the WHOLE repo, and that is nearly always
    wrong for a repo that is not a diffusers pipeline.

    `pipeline_files.download_patterns` narrows only by `model_index.json`, so a
    plain transformers or ONNX repo with nothing declared is fetched entire.
    Measured against the real listings: `lllyasviel/Annotators` 10.6 GB for the
    849 MB LeReS loads, `Salesforce/blip2-opt-2.7b` 30.5 GB because it carries
    `.bin` shards beside `.safetensors` ones, `Ultralytics/YOLO11` 728 MB for a
    6.3 MB pose model, `deepghs/anime_face_detection` 502 MB for 22.5.

    Declared even where the repo is one file today: a repo grows — YOLO11 was
    one model once and is fifteen now — and an undeclared source starts
    over-fetching the day that happens, silently.
    """
    registry.reset()
    missing = [s.key for s in registry.all_sources() if not s.allow_patterns]
    assert missing == [], f"these sources would fetch their whole repo: {missing}"


def test_A_SOURCES_PROBE_IS_ONE_OF_THE_FILES_IT_FETCHES():
    """The two fields are one statement, and a probe outside the patterns is
    the RAM++ failure in a new hat.

    `allow_patterns` says what to get and `probe` says whether it arrived, so a
    probe of `config.json` beside a weight glob that matches nothing reads
    "Downloaded" over a model with no weights. Naming a fetched file makes a
    wrong glob read as "not downloaded" — loud, and in the direction somebody
    can act on.
    """
    registry.reset()
    for s in registry.all_sources():
        assert any(fnmatch.fnmatch(s.probe, p) for p in s.allow_patterns), \
            f"{s.key}: probe {s.probe!r} is not among {s.allow_patterns}"


def test_a_probe_names_weights_rather_than_a_config_file():
    """…and specifically a WEIGHT file, or the probe proves nothing.

    Config and tokenizer files are the first things fetched and the last things
    that can go missing. The two sharded checkpoints are the exception the rule
    allows: there is no stable single weight name to probe, so they name the
    safetensors INDEX — which exists only for that weight set, so a glob that
    fetched the wrong format still reads as not downloaded.
    """
    registry.reset()
    weightish = (".pth", ".pt", ".bin", ".safetensors", ".onnx", ".ckpt",
                 ".jit.pt", ".zip", ".msgpack")
    for s in registry.all_sources():
        if s.probe.endswith(".index.json"):
            continue
        assert s.probe.endswith(weightish), \
            f"{s.key}: probe {s.probe!r} is not a weight file"


def test_one_source_key_is_declared_the_same_way_everywhere():
    """`big_lama` is declared by BOTH the watermark and text-removal plugins.

    `all_sources` de-duplicates by key and keeps the first, so two declarations
    that disagree make the answer depend on registry order — which files get
    fetched, and which file marks it downloaded.
    """
    registry.reset()
    seen: dict[str, tuple] = {}
    for plug in registry.plugins():
        for s in plug.manifest.sources:
            fields = (s.repo, s.probe, tuple(s.allow_patterns))
            if s.key in seen:
                assert seen[s.key] == fields, \
                    f"{s.key} is declared two different ways"
            seen[s.key] = fields


def test_scunet_size_rules_are_pure_and_say_where_a_picture_runs(monkeypatch):
    """`restore_scunet` runs UNTILED (owner decision), so two pure rules
    decide a picture's fate before any pixel moves: the memory cap
    (`max_pixels`, from the device's memory and the measured bytes a
    pixel costs) and the Apple-silicon correctness limit (`needs_cpu`:
    the MPS forward is wrong past a padded input of 2^22 pixels, measured
    against the CPU — see the plugin's docstring)."""
    from media_compost.ui.plugins.impl import restore_scunet as sc

    monkeypatch.delenv("MEDIA_COMPOST_RESTORE_MAX_PIXELS", raising=False)
    assert sc.max_pixels(None, False) is None                 # the CPU: no bound
    cap32 = sc.max_pixels(16 * 2**30, False)
    cap16 = sc.max_pixels(16 * 2**30, True)
    assert 2_500_000 < cap32 < 3_200_000                       # ~5.1 GB a megapixel
    assert cap16 > cap32 * 1.7                                # fp16 nearly doubles it
    assert sc.max_pixels(2**30, False) == 0                   # a card with no room
    monkeypatch.setenv("MEDIA_COMPOST_RESTORE_MAX_PIXELS", "0")
    assert sc.max_pixels(16 * 2**30, False) is None
    monkeypatch.setenv("MEDIA_COMPOST_RESTORE_MAX_PIXELS", "123456")
    assert sc.max_pixels(16 * 2**30, False) == 123456

    assert sc.padded_pixels(1200, 900) == 1216 * 960
    assert sc.padded_pixels(2560, 1600) == 2**22 - 98304      # measured exact
    assert not sc.needs_cpu("mps", 2560, 1600)
    assert sc.needs_cpu("mps", 2560, 1664)                    # measured wrong
    assert sc.needs_cpu("mps", 2400, 1800)
    assert not sc.needs_cpu("cuda", 4000, 3000)               # a card is not MPS
    assert not sc.needs_cpu("cpu", 4000, 3000)

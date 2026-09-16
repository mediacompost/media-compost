"""`media_compost/hub/setup_env.py`'s index routing — the part a wrong answer
makes SILENT: torch installs fine from the wrong index and trains on the CPU
at a pace that reads as a hang. The module is standalone (pure stdlib), and
is loaded by file path like the trainer scripts to hold that property.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load():
    p = REPO / "media_compost" / "hub" / "setup_env.py"
    spec = importlib.util.spec_from_file_location("setup_env_under_test", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_override_wins_and_none_forces_pypi(monkeypatch):
    mod = _load()
    monkeypatch.setenv("MEDIA_COMPOST_TORCH_INDEX", "https://example.test/whl")
    assert mod.torch_index_url() == "https://example.test/whl"
    monkeypatch.setenv("MEDIA_COMPOST_TORCH_INDEX", "none")
    assert mod.torch_index_url() == ""


def test_amd_linux_routes_to_the_rocm_index(monkeypatch):
    """PyPI's Linux torch wheel is the CUDA build — on an AMD box it installs
    fine and `torch.cuda.is_available()` answers False, i.e. silent CPU
    training. The routing is what prevents that."""
    mod = _load()
    monkeypatch.delenv("MEDIA_COMPOST_TORCH_INDEX", raising=False)
    monkeypatch.setattr(mod, "has_nvidia", lambda: False)
    monkeypatch.setattr(mod, "has_amd_rocm", lambda: True)
    assert mod.torch_index_url() == mod.ROCM_INDEX
    assert "rocm" in mod.ROCM_INDEX


def test_nvidia_wins_a_mixed_linux_box(monkeypatch):
    """With an NVIDIA driver present the plain PyPI wheel already carries
    CUDA on Linux — one torch build drives one vendor."""
    mod = _load()
    monkeypatch.delenv("MEDIA_COMPOST_TORCH_INDEX", raising=False)
    monkeypatch.setattr(mod, "has_nvidia", lambda: True)
    monkeypatch.setattr(mod, "has_amd_rocm", lambda: True)
    if mod.os.name != "nt":  # the Windows+NVIDIA branch answers cu128 first
        assert mod.torch_index_url() == ""


def test_has_amd_rocm_is_linux_only(monkeypatch):
    """There are no stable ROCm torch wheels for Windows or macOS — answering
    True elsewhere would route pip at an index with nothing usable on it."""
    mod = _load()
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(mod.os.path, "exists", lambda p: True)
    assert mod.has_amd_rocm() is False
    monkeypatch.setattr(sys, "platform", "linux")
    assert mod.has_amd_rocm() is True


def test_has_amd_rocm_needs_kfd_or_cli(monkeypatch):
    mod = _load()
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(mod.os.path, "exists", lambda p: False)
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    assert mod.has_amd_rocm() is False
    monkeypatch.setattr(mod.shutil, "which",
                        lambda name: "/usr/bin/rocm-smi"
                        if name == "rocm-smi" else None)
    assert mod.has_amd_rocm() is True


def _fake_env(tmp_path, *, faiss=True, torch=True):
    dirs = {}
    if faiss:
        d = tmp_path / "faiss"
        (d / ".dylibs").mkdir(parents=True)
        (d / ".dylibs" / "libomp.dylib").write_bytes(b"faiss-omp")
        dirs["faiss"] = str(d)
    if torch:
        d = tmp_path / "torch"
        (d / "lib").mkdir(parents=True)
        (d / "lib" / "libomp.dylib").write_bytes(b"torch-omp")
        dirs["torch"] = str(d)
    return dirs


def test_dedupe_libomp_points_faiss_at_torchs_runtime(tmp_path, monkeypatch):
    """torch and faiss-cpu each bundle a libomp.dylib, and two OpenMP runtimes
    in one process crash it at the first parallel region — the app loads both
    IN-process (the faiss face matcher, the warm LaMa inpainter), so one
    Inpaint call took the server down. The repair makes faiss's copy a symlink
    to torch's: dyld loads a library once per resolved path, so one runtime."""
    mod = _load()
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    dirs = _fake_env(tmp_path)
    assert mod.dedupe_libomp("unused", dirs) is True
    link = Path(dirs["faiss"]) / ".dylibs" / "libomp.dylib"
    assert link.is_symlink()
    assert link.resolve() == (Path(dirs["torch"]) / "lib" / "libomp.dylib")
    # The original is kept beside the link for a hand-repair.
    assert (link.parent / "libomp.dylib.orig").read_bytes() == b"faiss-omp"
    # Idempotent: a second run changes nothing (a faiss REINSTALL puts a real
    # file back, which is why the repair runs on every `setup_env torch`).
    assert mod.dedupe_libomp("unused", dirs) is False


def test_dedupe_libomp_stands_down_without_both_libraries(tmp_path,
                                                          monkeypatch):
    mod = _load()
    monkeypatch.setattr(mod.sys, "platform", "darwin")
    assert mod.dedupe_libomp("unused", _fake_env(tmp_path, torch=False)) is False
    assert mod.dedupe_libomp("unused", _fake_env(tmp_path, faiss=False)) is False
    # Not macOS: two libgomp copies do not collide the way libomp does, and
    # symlinking into site-packages there would be surgery with no patient.
    monkeypatch.setattr(mod.sys, "platform", "linux")
    assert mod.dedupe_libomp("unused", _fake_env(tmp_path / "l")) is False

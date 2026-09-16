"""What the onnxruntime plugins share: which execution providers to ask for
on this machine, and the preload that makes CUDA's actually loadable.

A leading underscore, like `_echo.py` and `_vit_embed.py`: not a plugin,
never in `registry.PLUGIN_MODULES`. Imported by the main-env onnxruntime
plugins (`insightface_faces`, `wd_tagger`) — one answer to "is it on the
GPU" for both, where the tagger used to hardcode the CPU provider and the
face detector asked for CUDA and silently got the CPU.
"""

from __future__ import annotations

import os

#: GPU execution providers, best first. Only the ones a discrete accelerator
#: actually drives: TensorRT is left out (it builds an engine on first run —
#: minutes of silence in the middle of a job) and so is CoreML, which on
#: these models' dynamic shapes falls back node by node and has been
#: reported to hang; the Mac's answer here is the CPU provider.
GPU_PROVIDERS = ("CUDAExecutionProvider",       # NVIDIA
                 "ROCMExecutionProvider",       # AMD
                 "MIGraphXExecutionProvider",   # AMD, newer runtime
                 "DmlExecutionProvider")        # Windows, any vendor


#: The `os.add_dll_directory` handles, kept for the life of the process —
#: dropping one removes the directory from the search path again.
_DLL_DIRS: list = []


def nvidia_dll_dirs(roots) -> list[str]:
    """Every directory under the `nvidia` namespace package (the pip
    wheels: `nvidia/cudnn/bin`, `nvidia/cu13/bin/x86_64`, …) that holds a
    DLL, in a stable order. Pure, for the test; `roots` are the package's
    `submodule_search_locations`."""
    import glob

    seen: list[str] = []
    for root in roots:
        for f in sorted(glob.glob(os.path.join(root, "**", "*.dll"),
                                  recursive=True)):
            d = os.path.dirname(f)
            if d not in seen:
                seen.append(d)
    return seen


def _add_nvidia_dll_dirs() -> None:  # pragma: no cover - Windows only
    """WINDOWS: cuDNN LOADS ITS OWN SUB-LIBRARIES BY NAME, AND THE LOADER
    DOES NOT LOOK BESIDE THE CALLER. `preload_dlls` gets `cudnn64_9.dll`
    and the engines in by full path, but the first convolution makes cuDNN
    `LoadLibrary("cudnn_cnn64_9.dll")` — searched in the application
    directory, System32 and PATH, never in the directory the calling DLL
    came from — and the session answers "Invalid handle. Cannot load
    symbol cudnnCreateConvolutionDescriptor" and CUDNN_STATUS_NOT_
    SUPPORTED_SUBLIBRARY_UNAVAILABLE on every picture (the background
    remover on the Windows box; the face detector's convolutions took
    another path and hid it). So every DLL directory of the `nvidia`
    wheels goes on the search path first, both ways Windows looks: the
    per-process directory list and PATH."""
    import importlib.util

    spec = importlib.util.find_spec("nvidia")
    if spec is None or not spec.submodule_search_locations:
        return
    for d in nvidia_dll_dirs(list(spec.submodule_search_locations)):
        try:
            _DLL_DIRS.append(os.add_dll_directory(d))
        except OSError:
            continue
        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")


def preload() -> None:  # pragma: no cover - heavy optional dep
    """THE CUDA LIBRARIES MAY BE PIP PACKAGES, NOT A SYSTEM INSTALL — the
    `nvidia-*` wheels torch pulls in, which live under site-packages where
    the dynamic loader never looks. Without this, `onnxruntime-gpu` lists
    `CUDAExecutionProvider` as AVAILABLE, the session constructor fails to
    load it ("libcublasLt.so.13: cannot open shared object file", once per
    model, in red) and quietly makes a CPU session: measured on the 5090
    box, 5 items/s with the log claiming CUDA. `preload_dlls` is
    onnxruntime's own answer (1.21+): it dlopens the pip-installed CUDA and
    cuDNN libraries first, so the provider finds them already loaded.
    Windows needs the directories on the search path as well
    (`_add_nvidia_dll_dirs`), or cuDNN's lazily loaded halves are not."""
    import onnxruntime as ort

    if os.name == "nt" and not _DLL_DIRS:
        _add_nvidia_dll_dirs()
    fn = getattr(ort, "preload_dlls", None)
    if callable(fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - a system install needs none
            print(f"onnxruntime preload_dlls: {exc}", flush=True)


def providers():  # pragma: no cover - heavy optional dep
    """(providers, ctx_id) for this machine — the GPU where there is one.

    `MEDIA_COMPOST_ORT_PROVIDERS` is the way out for a machine whose GPU
    runtime is broken (or for pinning one deliberately): a comma-separated
    list of provider names, `cpu` for the CPU alone. `ctx_id` is what
    insightface's `prepare` wants beside the list (-1 = CPU).
    """
    import onnxruntime as ort

    preload()
    have = list(ort.get_available_providers())
    override = (os.environ.get("MEDIA_COMPOST_ORT_PROVIDERS") or "").strip()
    if override:
        if override.lower() == "cpu":
            return ["CPUExecutionProvider"], -1
        named = [p.strip() for p in override.split(",") if p.strip()]
        # Only what this runtime actually has: an unknown name is a ValueError
        # out of the session constructor, i.e. a plugin that cannot load.
        picked = [p for p in named if p in have]
        return (picked or []) + ["CPUExecutionProvider"], (0 if picked else -1)
    for name in GPU_PROVIDERS:
        if name in have:
            return [name, "CPUExecutionProvider"], 0
    return ["CPUExecutionProvider"], -1


def say_cpu_only(what: str) -> None:  # pragma: no cover - heavy optional dep
    """Why a machine with a GPU in it is running ``what`` on the CPU.

    The stock `onnxruntime` wheel carries no GPU provider at all — the same
    trap as PyPI's CPU-only torch on Windows, and just as silent: everything
    installs, everything runs, and the run is ten times slower with nothing
    in the log naming the cause. Printed only where a GPU is visible, so an
    ordinary CPU machine says nothing.
    """
    import shutil

    tool = ("nvidia-smi" if shutil.which("nvidia-smi")
            else "rocm-smi" if shutil.which("rocm-smi") else "")
    if not tool:
        return
    print(f"{what}: running on the CPU — this onnxruntime build has no GPU "
          "execution provider. Run the model's setup again (it installs "
          "`onnxruntime-gpu` where an NVIDIA driver is found; by hand: "
          "`python -m media_compost.hub.setup_env onnxruntime`), or a ROCm "
          f"build, into the same environment to use the card {tool} "
          "reports.", flush=True)


def session_providers(sessions) -> list:  # pragma: no cover - heavy optional dep
    """What the sessions actually RUN on — a provider that failed to load
    leaves a session on the CPU with the requested list still reading
    "CUDA"."""
    got = set()
    for s in sessions:
        try:
            got.update(s.get_providers())
        except Exception:  # noqa: BLE001
            pass
    return sorted(got)

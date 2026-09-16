#!/usr/bin/env python3
"""Create one of the dedicated Python environments (training / florence / magi).

This is what the app's in-UI "Run setup" buttons execute, on every platform —
as ``{python} -m media_compost.hub.setup_env <env>``, which resolves wherever
the package is installed, and the ONLY spelling: the ``scripts/setup_env.py``
and ``setup-<env>-env.sh`` wrappers this replaced are gone. It LIVES inside
the package (with the ``requirements-<env>-env.txt`` files beside it) because
a wheel install has no checkout: the button used to run a file under
``scripts/``, which the wheel never shipped, so on any non-editable install
every setup failed with a missing-file error. Pure stdlib on purpose — the
tests load it by file path, and nothing about building a venv needs more.

**It replaced three bash scripts, and the reason is not Windows alone.** Each
`setup-<env>-env.sh` hardcoded `$VENV/bin/python`, which does not exist on
Windows (CPython writes `Scripts\\python.exe` there) — so the button ran, the
venv got created, and every `pip install` after it failed. But the scripts had
also drifted from the `requirements-<env>-env.txt` files that claim to mirror
them: the magi script installs `ultralytics` — the detector half of the
"Illustrated faces" model, without which that plugin cannot run — and the
requirements file listing "the equivalent" never mentioned it. Two lists of
packages, one of them wrong, is the failure this file exists to end.

So the requirements files are now the SINGLE source of truth for what goes
into an env, this script is the single source of truth for how, and the three
`.sh` files are four-line wrappers kept so existing docs and muscle memory
still work.

Usage:  python -m media_compost.hub.setup_env <training|florence|magi> [PYTHON]
  PYTHON  interpreter to build the venv from (default: the one running this).
          Useful when the default Python is a version a pinned transformers
          cannot run — e.g. `... setup_env magi /usr/bin/python3.11`.

        python -m media_compost.hub.setup_env torch [PYTHON]
  The second form creates no venv: it installs — or repairs — the torch pair
  in an EXISTING environment (PYTHON's, default the one running this), from
  the index this machine needs. It is what the app's "Run setup" runs LAST
  for a main-env model that needs torch, and the repair step
  requirements-ai.txt points a Windows + NVIDIA install at.

        python -m media_compost.hub.setup_env onnxruntime [PYTHON]
  Likewise for onnxruntime: PyPI's `onnxruntime` is CPU-only everywhere, so
  a machine with an NVIDIA driver gets `onnxruntime-gpu[cuda,cudnn]` (the
  CUDA runtime and cuDNN come as pip packages with it), any other the plain
  wheel. What "Run setup" runs for a main-env model that needs onnxruntime.

The Hugging Face cache is shared across environments, so weights downloaded
once (or via Settings → Models) are reused here — no second download.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# THIS SCRIPT'S OWN HELP KILLED IT ON WINDOWS. The docstring above is the
# usage text, and it holds an arrow and several em-dashes; the standard
# streams there default to the LOCALE encoding, cp1252 on a Western install,
# so `setup_env.py --help` died inside argparse's own `print_help` with
# UnicodeEncodeError on → — before doing anything, on the one script
# whose entire reason for existing is that it works on every platform.
# `errors="replace"` rather than forcing UTF-8: a genuine cp1252 console
# cannot show those characters however they are encoded, and forcing it turns
# "cannot display" into mojibake on everything else. Wrapped, because a
# stream that cannot be reconfigured must not become a new way to fail.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")  # type: ignore[union-attr]
    except (AttributeError, OSError, ValueError):
        pass

ENVS = ("training", "florence", "magi")

# Where the venvs go: the directory holding the `media_compost` package — the
# checkout in an editable install, site-packages for an installed wheel. The
# SAME answer `plugins/framework.repo_root()` computes, deliberately: a venv
# created anywhere else is one `interpreter_for` will never find.
# (`MEDIA_COMPOST_<ENV>_PYTHON` stays the override for any layout this cannot
# serve.) The requirements files live BESIDE this file, inside the package,
# so a wheel carries them (they are `[tool.setuptools.package-data]`).
REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def venv_python(root: Path) -> Path:
    """The interpreter inside a venv, whichever layout this platform uses.

    Mirrors ``plugins/framework.interpreter_for`` — the app probes both, so
    creating one under a name it will not look for is a silent no-op."""
    for rel in (("bin", "python"), ("Scripts", "python.exe")):
        cand = root.joinpath(*rel)
        if cand.exists():
            return cand
    # Not created yet: name the layout this platform is about to produce.
    return root / ("Scripts" if os.name == "nt" else "bin") / (
        "python.exe" if os.name == "nt" else "python")


def has_nvidia() -> bool:
    return shutil.which("nvidia-smi") is not None


def has_amd_rocm() -> bool:
    """A ROCm-capable AMD compute stack: the kernel's compute interface
    (``/dev/kfd``, which ROCm cannot run without) or the ROCm CLI. Linux
    only — there are no stable ROCm torch wheels for Windows or macOS, so
    elsewhere this must answer False rather than route pip at an index with
    nothing usable on it."""
    if not sys.platform.startswith("linux"):
        return False
    return os.path.exists("/dev/kfd") or shutil.which("rocm-smi") is not None


#: Newest stable ROCm index for the same reason cu128 below: RDNA4 (RX
#: 9000-series) has no kernels in older builds. Bump alongside torch.
ROCM_INDEX = "https://download.pytorch.org/whl/rocm7.1"


def torch_index_url() -> str:
    """The extra pip index torch should come from, or "" for plain PyPI.

    On Linux the default PyPI `torch` wheel already carries CUDA. On **Windows
    it does not** — PyPI serves the CPU-only build there, so a plain
    `pip install torch` yields an env where `torch.cuda.is_available()` is
    False and a training run silently falls back to the CPU (hours per step
    instead of seconds, with nothing in the log saying why). The CUDA wheels
    live on download.pytorch.org, so on a Windows host with an NVIDIA driver
    present we point at the cu128 index — cu128 rather than an older one
    because Blackwell (RTX 50-series, sm_120) has no kernels in cu126 and
    fails at the first matmul with "no kernel image is available".

    **The Linux wheel carrying CUDA is the same trap for AMD in a different
    spelling**: it installs fine on an AMD box and `torch.cuda.is_available()`
    answers False (the ROCm build drives AMD GPUs through the torch.cuda
    API), so training silently falls back to the CPU there too. The ROCm
    wheels live on download.pytorch.org as well, so a Linux host with an AMD
    compute stack and no NVIDIA driver is pointed at the ROCm index. NVIDIA
    wins a mixed box: one torch build drives one vendor.

    Override with MEDIA_COMPOST_TORCH_INDEX. "none" forces PLAIN PYPI, which
    is what a Windows box wants for CPU-only — but on LINUX plain PyPI is the
    CUDA build, so "none" there is not a CPU-only install: it pulls the whole
    nvidia-* wheel set (cuDNN alone is 650 MB) onto a machine that may have no
    GPU at all. **A CPU-only Linux install is the CPU INDEX, named in full:**

        MEDIA_COMPOST_TORCH_INDEX=https://download.pytorch.org/whl/cpu

    That is worth knowing before building one of these environments inside a
    container: a GPU-less image otherwise carries several GB of CUDA
    libraries nothing can load."""
    override = os.environ.get("MEDIA_COMPOST_TORCH_INDEX", "").strip()
    if override:
        return "" if override.lower() == "none" else override
    if os.name == "nt" and has_nvidia():
        return "https://download.pytorch.org/whl/cu128"
    if has_amd_rocm() and not has_nvidia():
        return ROCM_INDEX
    return ""


def _wants(reqs: Path, pkg: str) -> bool:
    """Whether a requirements file asks for ``pkg`` (bare name, any line)."""
    for line in reqs.read_text(encoding="utf-8").splitlines():
        name = line.split("#")[0].strip().split("[")[0]
        name = name.split("==")[0].split(">=")[0].split("@")[0].strip()
        if name.lower() == pkg.lower():
            return True
    return False


def _wants_torch(reqs: Path, py: Path) -> bool:
    """Whether this env ends up with torch — declared, or pulled in by
    something that was. Asking the ENV rather than only the file matters:
    the magi requirements never name torchvision, `ultralytics` does."""
    if _wants(reqs, "torch"):
        return True
    proc = subprocess.run(
        [str(py), "-c", "import importlib.util as u;"
         "print(bool(u.find_spec('torch')))"],
        capture_output=True, text=True)
    return "True" in (proc.stdout or "")


def verify_cuda(py: Path) -> None:
    """Say plainly whether the env that was just built can see the GPU.

    A CPU-only torch does not fail — it trains, at a pace that reads as a
    hang, with nothing in the log naming the cause. Since this script is
    what chose the index, it is what should report the outcome."""
    code = ("import torch;"
            "print('torch', torch.__version__,"
            "'| cuda', torch.cuda.is_available(),"
            "'|', torch.cuda.get_device_name(0)"
            " if torch.cuda.is_available() else 'CPU only')")
    proc = subprocess.run([str(py), "-c", code], capture_output=True, text=True)
    out = (proc.stdout or proc.stderr).strip()
    print(out)
    if "+cpu" in out and has_nvidia():
        print("WARNING: this machine has an NVIDIA driver but the installed "
              "torch is the CPU build — training will be extremely slow. "
              "Set MEDIA_COMPOST_TORCH_INDEX to a CUDA wheel index and "
              "re-run.")
    # ROCm presents AMD GPUs through torch.cuda, so "cuda False" on an AMD
    # box means the GPU is unreachable — either the wrong wheel (PyPI's
    # Linux torch is the CUDA build, with no "+rocm" in its version) or a
    # driver/permission problem underneath a right one.
    if has_amd_rocm() and not has_nvidia() and "cuda True" not in out:
        if "rocm" not in out:
            print("WARNING: this machine has an AMD ROCm stack but the "
                  "installed torch is not a ROCm build (PyPI's Linux wheel "
                  "carries CUDA) — training will run on the CPU, extremely "
                  f"slowly. Set MEDIA_COMPOST_TORCH_INDEX={ROCM_INDEX} and "
                  "re-run.")
        else:
            print("WARNING: torch is a ROCm build but cannot see the GPU — "
                  "check the amdgpu driver, and that this user is in the "
                  "'render' and 'video' groups.")


def run(cmd: list[str], check: bool = True) -> None:
    print("$ " + " ".join(str(c) for c in cmd), flush=True)
    proc = subprocess.run([str(c) for c in cmd], cwd=str(REPO))
    if check and proc.returncode != 0:
        raise SystemExit(f"command failed (exit {proc.returncode})")


#: Memoized per interpreter path — the probe is a subprocess, and one env
#: setup drives pip several times.
_PIP_CMD: dict[str, list[str]] = {}


def pip_cmd(py: str | Path) -> list[str]:
    """How to drive pip for the environment at ``py``, as an argv prefix.

    ``py -m pip`` when the env has pip — true of every venv this script
    creates (the stdlib venv module seeds one), and deliberately still the
    first choice when uv is also installed: uv on PATH must not change
    behavior. A venv made by ``uv venv`` ships NO pip — the main venv in
    torch mode is where that happens — and there the fallback is
    ``uv pip --python <py>``, which installs into an env from outside. With
    neither, the pip form is returned anyway so the failure is pip's own
    clear "No module named pip". Mirrors ``media_compost/hub/setup.py:
    pip_spec`` — this script is standalone and cannot import it.
    """
    key = str(py)
    if key not in _PIP_CMD:
        probe = subprocess.run([key, "-m", "pip", "--version"],
                               capture_output=True)
        if probe.returncode != 0 and shutil.which("uv"):
            _PIP_CMD[key] = ["uv", "pip", "--python", key]
        else:
            _PIP_CMD[key] = [key, "-m", "pip"]
    return list(_PIP_CMD[key])


def uninstall_cmd(py: str | Path) -> list[str]:
    """``pip uninstall -y`` for the environment at ``py`` — the ``-y`` only
    where the prefix is pip's: ``uv pip uninstall`` never asks and rejects
    the flag."""
    cmd = pip_cmd(py) + ["uninstall"]
    return cmd if cmd[0] == "uv" else cmd + ["-y"]


def _package_dirs(py: str | Path, names: tuple[str, ...]) -> dict[str, str]:
    """Where each of ``names`` is installed in ``py``'s environment — asked of
    THAT interpreter, because this function runs from whatever env drives the
    setup and the target is the one being repaired."""
    import json

    probe = ("import importlib.util as u, json; " +
             "print(json.dumps({n: (s.submodule_search_locations or [None])[0]"
             " if (s := u.find_spec(n)) else None for n in %r}))" % (names,))
    try:
        out = subprocess.run([str(py), "-c", probe],
                             capture_output=True, text=True)
    except OSError:  # an interpreter that cannot run is an env to leave alone
        return {}
    if out.returncode != 0:
        return {}
    return {k: v for k, v in json.loads(out.stdout).items() if v}


def dedupe_libomp(py: str | Path,
                  dirs: dict[str, str] | None = None) -> bool:
    """ONE OpenMP runtime per process, on macOS. Returns True on a change.

    torch and faiss-cpu each BUNDLE their own ``libomp.dylib``
    (``torch/lib/``, ``faiss/.dylibs/``), and two LLVM OpenMP runtimes in one
    process die at the first parallel region after the second one initializes
    — libomp's own duplicate check aborts, and ``KMP_DUPLICATE_LIB_OK`` is NOT
    the answer: measured here, it converts the abort into a segfault. The app
    loads both IN-process by design (facevec's faiss matcher, the editor's
    warm LaMa inpainter), so on a ``[full]`` install with the AI actions set
    up, one Inpaint call took the whole server down with it.

    dyld loads a library once per RESOLVED path, so replacing faiss's copy
    with a symlink to torch's collapses the two into one runtime — verified in
    both import orders, exercising both a faiss search and a torch inference.
    torch's copy is the one kept: its kernels are what the runtime is sized
    for, and faiss runs on any LLVM libomp. The original stays beside the link
    as ``libomp.dylib.orig`` so a hand-repair can put it back; a faiss
    reinstall replaces the link with a fresh real file, which is why this runs
    on every ``setup_env torch`` rather than once.
    """
    if sys.platform != "darwin":
        return False
    dirs = dirs if dirs is not None else _package_dirs(py, ("faiss", "torch"))
    if "faiss" not in dirs or "torch" not in dirs:
        return False
    faiss_omp = Path(dirs["faiss"]) / ".dylibs" / "libomp.dylib"
    torch_omp = Path(dirs["torch"]) / "lib" / "libomp.dylib"
    if not torch_omp.is_file() or not faiss_omp.exists():
        return False
    if faiss_omp.is_symlink():
        return False
    faiss_omp.replace(faiss_omp.with_suffix(".dylib.orig"))
    faiss_omp.symlink_to(os.path.relpath(torch_omp, faiss_omp.parent))
    print("(pointed faiss's bundled libomp at torch's — two OpenMP runtimes "
          "in one process crash it)")
    return True


def setup_main_torch(py: str) -> int:
    """Install — or repair — the torch pair in an EXISTING environment.

    The venv modes below create a dedicated env and route torch through the
    right index; this does the same two torch steps for an env that already
    exists (above all, the app's own). It is the command
    `plugins/framework.setup_commands` appends for a main-env model whose
    deps include torch, and the repair `requirements-ai.txt` documents.

    The plain install goes first: a no-op when torch is already present, and
    otherwise it brings torch's own dependencies from PyPI — which the index
    install below deliberately skips (`--no-deps`; download.pytorch.org
    carries only the torch packages). The index force-reinstall then goes
    LAST, after everything the caller installed before it, so no dependency
    of the rest (ultralytics → torchvision is the measured one) can drag a
    CPU build back in over it. Same reasoning, same flags as the venv flow.
    """
    run(pip_cmd(py) + ["install", "torch", "torchvision"])
    index = torch_index_url()
    if index:
        print(f"(installing torch from {index})")
        run(pip_cmd(py) + ["install", "--index-url", index,
            "--force-reinstall", "--no-deps", "torch", "torchvision"])
    dedupe_libomp(py)
    print()
    verify_cuda(Path(py))
    return 0


#: The onnxruntime wheel that carries the CUDA execution provider, with the
#: extras that bring the CUDA 13 runtime and cuDNN as pip packages (the
#: build's own `Provides-Extra`; `cudnn` pulls cuBLAS with it). Without the
#: extras the provider is LISTED as available and fails to load at session
#: time — measured on the 5090 box: "libcublasLt.so.13: cannot open shared
#: object file", once per model, and a CPU session behind it.
ORT_GPU_SPEC = "onnxruntime-gpu[cuda,cudnn]"


def wants_ort_gpu() -> bool:
    """Whether this machine should get the CUDA onnxruntime build: an NVIDIA
    driver on Linux or Windows. Nothing else has a working wheel — there is
    no macOS build, and the ROCm build is not on PyPI (a machine with one
    installs it by hand; the plugins pick it up through `_ort.providers`)."""
    return has_nvidia() and not sys.platform.startswith("darwin")


def ort_state(py: str | Path) -> tuple[list[str], list[str] | None]:
    """Which of the two onnxruntime distributions ``py``'s environment
    holds, and the providers the import actually offers (None = the module
    does not import or is half-overwritten: `pip install onnxruntime` over
    `onnxruntime-gpu` — what a plain `pip install` of a plugin's deps used
    to do — writes both names over ONE package directory, and uninstalling
    either removes files the other still claims, leaving pip "satisfied"
    and `import onnxruntime` without `__version__`)."""
    import json

    probe = (
        "import json\n"
        "from importlib.metadata import distributions\n"
        "names = sorted({(d.metadata['Name'] or '').lower() "
        "for d in distributions()} & {'onnxruntime', 'onnxruntime-gpu'})\n"
        "try:\n"
        "    import onnxruntime as o\n"
        "    p = [o.__version__] + list(o.get_available_providers())\n"
        "except Exception:\n"
        "    p = None\n"
        "print(json.dumps([names, p]))\n")
    try:
        out = subprocess.run([str(py), "-c", probe], capture_output=True,
                             text=True)
    except OSError:
        return [], None
    if out.returncode != 0:
        return [], None
    names, p = json.loads(out.stdout.strip().splitlines()[-1])
    return names, (p[1:] if p else None)


def setup_main_onnxruntime(py: str) -> int:
    """Install — or repair — onnxruntime in an EXISTING environment, the
    GPU build where the machine can drive it.

    PyPI's `onnxruntime` is CPU-only, on every platform, the same trap as
    its CPU-only Windows torch: everything installs, everything runs, and
    the face detector, the tagger, the OCR and the background remover run
    ten times slower with nothing in the log naming the cause (before
    `_ort.say_cpu_only`, nothing at all). The two wheels are ONE package
    directory under two names (`ort_state`), so BOTH are removed before
    the wanted one goes in — the only repair for the half-overwritten
    state, and the reason the CPU branch is not a bare `pip install`
    either: it is also the fix for a GPU build left on a machine whose
    card has since gone. A healthy install of the wanted build is left
    alone, so the four plugins naming this dependency cost nothing after
    the first.
    """
    gpu = wants_ort_gpu()
    dist = "onnxruntime-gpu" if gpu else "onnxruntime"
    names, providers = ort_state(py)
    healthy = (names == [dist] and providers is not None
               and (not gpu or "CUDAExecutionProvider" in providers))
    if healthy:
        print(f"({dist} already installed: {providers})")
    else:
        if gpu:
            print(f"(NVIDIA driver found: installing {ORT_GPU_SPEC})")
        for name in ("onnxruntime", "onnxruntime-gpu"):
            run(uninstall_cmd(py) + [name], check=False)
        run(pip_cmd(py) + ["install", ORT_GPU_SPEC if gpu else "onnxruntime"])
    print()
    return 0 if verify_ort(Path(py)) else 1


def verify_ort(py: Path) -> bool:
    """Say which execution providers the installed onnxruntime offers — the
    line a user reads to know whether the GPU build landed."""
    out = subprocess.run(
        [str(py), "-c",
         "import onnxruntime as o; print('onnxruntime', o.__version__, "
         "o.get_device(), o.get_available_providers())"],
        capture_output=True, text=True)
    if out.returncode != 0:
        print("onnxruntime: not importable after install:\n"
              + out.stderr.strip()[-800:])
        return False
    print(out.stdout.strip())
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("env", choices=ENVS + ("torch", "onnxruntime"))
    ap.add_argument("python", nargs="?", default=sys.executable,
                    help="interpreter to build the venv from (torch mode: "
                         "the environment to install into)")
    args = ap.parse_args()

    if args.env == "torch":
        return setup_main_torch(args.python)
    if args.env == "onnxruntime":
        return setup_main_onnxruntime(args.python)

    venv = REPO / f".venv-{args.env}"
    reqs = HERE / f"requirements-{args.env}-env.txt"
    if not reqs.is_file():
        raise SystemExit(f"missing requirements file: {reqs}")

    print(f"Creating {args.env} environment at: {venv} (using {args.python})")
    run([args.python, "-m", "venv", str(venv)])

    py = venv_python(venv)
    if not py.exists():
        raise SystemExit(f"venv created but no interpreter at {py}")

    run(pip_cmd(py) + ["install", "--upgrade", "pip"])

    run(pip_cmd(py) + ["install", "-r", str(reqs)])

    # torch LAST, and from its own index REPLACING PyPI for that one install
    # (--index-url, not --extra-index-url). Two separate traps:
    #
    # With an EXTRA index pip picks the highest version across all of them,
    # and PyPI's CPU-only Windows wheel is routinely NEWER than the newest
    # CUDA build on download.pytorch.org — so an extra index silently yields
    # `+cpu` torch, the exact failure this exists to prevent.
    #
    # And it has to come after the requirements, not before: any package that
    # depends on torchvision — `ultralytics` in the magi env — makes pip fetch
    # torchvision from PyPI, which drags ITS matching CPU torch in over the
    # CUDA one already installed. Going last, nothing can pull it back.
    #
    # --no-deps because download.pytorch.org carries only torch packages; the
    # shared dependencies are already present from the install above.
    index = torch_index_url()
    if index and _wants_torch(reqs, py):
        print(f"(installing torch from {index})")
        run(pip_cmd(py) + ["install", "--index-url", index,
            "--force-reinstall", "--no-deps", "torch", "torchvision"])

    # 8-bit optimizers (the "AdamW (8-bit)" memory saver) need bitsandbytes:
    # install where an NVIDIA driver or a ROCm stack is present, skip
    # elsewhere (macOS/MPS). On AMD, whether the installed build actually
    # supports ROCm depends on the wheel — the trainer PROBES it with one
    # tiny 8-bit step before trusting it and falls back to plain AdamW with
    # a printed reason, so a CUDA-only wheel here costs only the download.
    if args.env == "training":
        if has_nvidia() or has_amd_rocm():
            run(pip_cmd(py) + ["install", "bitsandbytes"])
        else:
            print("(no NVIDIA driver or ROCm stack found — skipping "
                  "bitsandbytes; 8-bit AdamW unavailable)")

    print()
    verify_cuda(py)
    print()
    print(f"Done. Media Compost will auto-detect {venv}.")
    if args.env == "training":
        print("Base-model weights download on a job's first run into the "
              "shared Hugging Face cache and are reused afterwards.")
    else:
        print("Download this model's weights from the app's Settings → Models "
              "panel (they land in the shared Hugging Face cache).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

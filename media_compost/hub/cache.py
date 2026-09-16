"""What is in the Hugging Face cache, and getting rid of it.

Everything here takes a **repo id**, not a plugin's `ModelSource`. That is the
one deliberate change from where this code came from: the old signatures took a
manifest object for its `.repo` and `.probe` fields alone, and the trainer —
which has no plugins — already worked around it by constructing a throwaway
`ModelSource` just to ask whether a base model was downloaded. A function that
its second caller has to lie to is asking for plainer arguments.

Every hub import is inside a function, so importing this module costs nothing
and a base install can carry it without huggingface_hub anywhere in sight.
"""

from __future__ import annotations

import os

from .venv import has_module

#: What marks a repo as present when nothing more specific is said.
DEFAULT_PROBE = "config.json"


def dir_has_model(path: str) -> bool:
    """Whether a local directory looks like it holds weights."""
    if not path or not os.path.isdir(path):
        return False
    if os.path.exists(os.path.join(path, DEFAULT_PROBE)):
        return True
    try:
        return any(f.endswith((".safetensors", ".bin", ".onnx", ".pth", ".pt"))
                   for f in os.listdir(path))
    except OSError:
        return False


def _repo_dirname(repo: str) -> str:
    return "models--" + repo.replace("/", "--")


def _has_incomplete_blobs(repo: str) -> bool:
    """True if the repo's cache holds a *non-empty* partially-downloaded
    ``.incomplete`` blob (an interrupted download leaves the probe file but
    incomplete weights).

    **Zero-byte** ``.incomplete`` files are ignored: they are spurious
    leftovers of a download that registered a temp file but wrote nothing (an
    aborted fetch of a duplicate weight format like ``model.safetensors`` when
    ``pytorch_model.bin`` is already there). Counting those would keep an
    otherwise-complete model stuck on "not downloaded", with a re-download
    unable to clear it — the exact MiDaS symptom.
    """
    try:
        from huggingface_hub.constants import HF_HUB_CACHE

        blobs = os.path.join(HF_HUB_CACHE, _repo_dirname(repo), "blobs")
        for f in os.listdir(blobs):
            if not f.endswith(".incomplete"):
                continue
            try:
                if os.path.getsize(os.path.join(blobs, f)) > 0:
                    return True
            except OSError:
                continue
        return False
    except OSError:
        return False
    except Exception:  # noqa: BLE001 - hub error -> assume complete
        return False


def repo_cached(repo: str, probe: str = DEFAULT_PROBE,
                local_path: str = "") -> bool:
    """Whether these weights are present — at a local-path override, or fully
    in the Hugging Face cache (probe file downloaded, no blob half-fetched)."""
    if local_path:
        return dir_has_model(local_path)
    if not repo or not has_module("huggingface_hub"):
        return False
    try:
        from huggingface_hub import try_to_load_from_cache

        if not isinstance(try_to_load_from_cache(repo, probe), str):
            return False
        return not _has_incomplete_blobs(repo)
    except Exception:  # noqa: BLE001 - hub error -> treat as not cached
        return False


def delete_repo(repo: str) -> bool:
    """Remove a repo's downloaded weights from the Hugging Face cache."""
    try:
        from huggingface_hub import scan_cache_dir

        info = scan_cache_dir()
        hashes = [rev.commit_hash for r in info.repos if r.repo_id == repo
                  for rev in r.revisions]
        if hashes:
            info.delete_revisions(*hashes).execute()
            forget_cache_sizes()
            return True
    except Exception:  # noqa: BLE001 - best effort
        pass
    return False


#: How long a size scan is reused. `scan_cache_dir` stats every blob in the
#: cache — measured at 31–46 ms over 149 GB in 49 repos, which is nothing once
#: and is not nothing on an endpoint the Models page polls every 1.2 seconds
#: while a download runs, over a cache that download is writing into. A figure
#: two seconds stale is a figure nobody can see is stale; a delete clears it
#: outright, which is the one change that must show at once.
SIZES_TTL = 2.0

_sizes: "tuple[float, dict] | None" = None


def forget_cache_sizes() -> None:
    """Drop the memo — after anything that changes what is on disk."""
    global _sizes
    _sizes = None


def cache_sizes(max_age: float = SIZES_TTL) -> dict:
    """``repo_id`` -> total on-disk bytes, from one scan. Empty when
    huggingface_hub is unavailable. One call answers for every model in a
    list, where a per-repo rescan would be a directory walk apiece."""
    global _sizes
    if not has_module("huggingface_hub"):
        return {}
    import time

    now = time.monotonic()
    if _sizes is not None and now - _sizes[0] < max_age:
        return _sizes[1]
    try:
        from huggingface_hub import scan_cache_dir

        info = scan_cache_dir()
        out = {r.repo_id: int(r.size_on_disk) for r in info.repos}
    except Exception:  # noqa: BLE001 - hub error -> no sizes
        return {}
    _sizes = (now, out)
    return out

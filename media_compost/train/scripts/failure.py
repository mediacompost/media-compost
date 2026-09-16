"""Turn a run's exception into something that names the way out.

An out-of-memory dump says what the run WANTED — "MPS allocated: 88.03 GiB" —
and nothing about which settings decide that. The knobs are named here with
the values the job actually used, in the order that helps most, so the message
is actionable rather than a number to search for.

Shared by the trainer and the Evaluate generator because they fail the same
way and used to explain it differently: `train.py` had this and `generate.py`
wrote a bare `f"{type(exc).__name__}: {exc}"`, so an OOM during a generation
was a raw torch dump.

Stdlib only — `train/scripts/` (the trainer) is standalone.
"""
from __future__ import annotations

#: Every spelling the backends use. MPS and CUDA word it differently, and
#: matching only one of them is how half the cases fall through to the raw
#: dump this module exists to replace.
_OOM = ("out of memory", "outofmemory", "cuda oom", "can't allocate",
        "cannot allocate", "memory fraction")


def is_oom(error: str) -> bool:
    low = (error or "").lower()
    return any(s in low for s in _OOM)


def _memory_tips(config: dict, *, training: bool) -> list[str]:
    hyper = (config or {}).get("hyper") or {}
    buckets = (config or {}).get("buckets") or {}
    batch = int(hyper.get("batch_size", 1) or 1)
    accum = int(hyper.get("grad_accum", 1) or 1)
    # THE LARGEST SIZE THE RUN TRAINS AT, since a batch holds one bucket
    # and the OOM was one of them. 0 (the model's own size) stays 0 —
    # this module is handed a config dict and no model registry, so it
    # cannot resolve it, and the advice below reads a zero as "big".
    sizes = [int(r or 0) for r in (buckets.get("resolutions") or [])]
    res = 0 if 0 in sizes else max(sizes or [0])
    tips: list[str] = []

    # A CAP THE JOB SET ITSELF COMES FIRST. Since runs can carry
    # `memory_budget_gb`, an OOM may be the run obeying an instruction rather
    # than the hardware running out — and no amount of advice about batch size
    # helps with that. Naming it first is what stops the person tuning the
    # wrong thing.
    budget = float(hyper.get("memory_budget_gb", 0) or 0)
    if budget > 0:
        tips.append(f"this job caps itself at {budget:g} GB "
                    "(Memory budget) — raise it or set it to 0 to use "
                    "whatever the device has")

    if training:
        if batch > 1:
            tips.append(
                f"lower the batch size (it was {batch}) and raise gradient "
                f"accumulation to match — {batch}x{accum} trains the same "
                f"effective batch as 1x{batch * accum} while holding a "
                "fraction of the activations")
        if not bool(hyper.get("gradient_checkpointing")):
            tips.append("switch gradient checkpointing on — the single "
                        "biggest saving here, at roughly 20-30% slower steps")
    if res == 0 or res >= 1024:
        tips.append("train at a lower resolution (768 px needs about half of "
                    "what 1024 px does)" if training else
                    "generate at a lower resolution")
    if str(hyper.get("quantization", "none")) == "none":
        tips.append("quantize the backbone to int8 — it roughly halves the "
                    "weights of a DiT, which is what makes the big models fit")
    elif not hyper.get("offload_text_encoder"):
        tips.append("offload the text encoder, which takes its weights off "
                    "the device entirely")
    if not tips:
        tips.append("lower the batch size or the resolution")
    return tips


def explain(error: str, config: dict | None = None, *,
            training: bool = True) -> str:
    """`error` with an actionable paragraph appended, where we recognise it."""
    error = error or ""
    if is_oom(error):
        tips = _memory_tips(config or {}, training=training)
        return (error + "\n\nMemory is decided by batch size x pixels x "
                "whether activations are kept: " + "; ".join(tips) + ".")
    low = error.lower()
    if "illegal memory access" in low:
        # Almost never the model: a poisoned CUDA context comes from a driver
        # and wheel that disagree, or from an allocator returning something
        # the runtime did not expect.
        return (error + "\n\nAn illegal memory access is a CUDA-level fault "
                "rather than a problem with this job: check that the torch "
                "build matches the installed driver "
                "(`python -m media_compost.hub.setup_env torch` reinstalls "
                "the pair), and that no other process is using the card.")
    if "no kernel image is available" in low:
        return (error + "\n\nThis torch build has no kernels for this GPU — "
                "on a Blackwell card (RTX 50-series) that means a wheel older "
                "than CUDA 12.8. Reinstall with "
                "`python -m media_compost.hub.setup_env torch`.")
    return error

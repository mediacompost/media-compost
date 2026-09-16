"""A ceiling on what a run may allocate, so an oversized job FAILS rather than
takes the machine down with it.

**This is about unified memory above all.** On a discrete card the failure mode
of an oversized run is a CUDA OOM: an exception, at a knowable moment, which
ends one job. On Apple silicon the GPU allocates out of the same RAM as
everything else, and `torch.mps.recommended_max_memory()` is a RECOMMENDATION
that sits ABOVE physical memory — so nothing stops a run growing into swap, and
what the user sees is not an error but a desktop that stops responding, with the
measurement or the training run lost anyway.

`scripts/measure_vram.py` has capped itself this way from the beginning, for
exactly this reason. The trainer and the Evaluate generator did not, which is
the odd half: the script that measures one step was protected and the thing that
runs for hours was not.

Stdlib + torch only — `train/scripts/` (the trainer) is standalone and may not import
`media_compost`.
"""
from __future__ import annotations

import os

#: Fraction of UNIFIED memory a run may claim when the job names no figure.
#:
#: **THERE IS NO DISCRETE DEFAULT, DELIBERATELY.** On a card with its own VRAM
#: an oversized run already fails correctly: the allocator asks cudaMalloc, it
#: refuses, torch raises OutOfMemoryError — catchable, at a knowable moment,
#: and the machine is untouched because that memory is shared with nothing. A
#: cap there could only refuse a run that would have FIT, in the last few
#: percent, and buys no protection in exchange.
#:
#: Unified memory is the case that needs one, because the equivalent overshoot
#: is not an error at all: `recommended_max_memory()` sits above physical RAM,
#: so the run pages, and what the user sees is a machine that stops responding
#: — losing the run and everything else they were doing. 0.9 leaves the system
#: a real margin while still letting a job use most of the machine.
UNIFIED_FRACTION = 0.9

#: `MEDIA_COMPOST_MEM_FRACTION` overrides both, and "none" disables the cap —
#: an escape hatch for a machine where the default is wrong, without needing a
#: job edit.
ENV_OVERRIDE = "MEDIA_COMPOST_MEM_FRACTION"


def is_unified_memory(device: str) -> bool:
    """Does this device allocate out of the machine's own RAM?

    Asked of torch rather than assumed from the backend name: an INTEGRATED
    CUDA device (Jetson, and some laptop parts) is unified too, and treating it
    as discrete would hand it 95% of all the memory there is — which is the
    paging failure this module exists to prevent, on the backend least expected
    to have it.
    """
    import torch

    if device.startswith("mps"):
        return True
    if device.startswith("cuda"):
        try:
            idx = torch.device(device).index or 0
            return bool(getattr(torch.cuda.get_device_properties(idx),
                                "is_integrated", 0))
        except Exception:      # noqa: BLE001 — an unknown card is treated as
            return True        # unified, i.e. the CAUTIOUS default
    return True


def device_memory_gb(device: str) -> float:
    import torch

    try:
        if device.startswith("cuda"):
            idx = torch.device(device).index or 0
            return torch.cuda.get_device_properties(idx).total_memory / 1e9
        if device.startswith("mps"):
            return torch.mps.recommended_max_memory() / 1e9
    except Exception:          # noqa: BLE001 - a probe must never end a run
        return 0.0
    return 0.0


def default_fraction(device: str) -> float:
    """The default share, or 0 where no cap is wanted (a discrete card)."""
    return UNIFIED_FRACTION if is_unified_memory(device) else 0.0


def arm(device: str, budget_gb: float = 0.0) -> float:
    """Cap this process's allocations. Returns the cap in GB, or 0 if none.

    `budget_gb` is the job's own figure; 0 means "work it out from the device".
    Never raises: a missing knob must not stop a run that would have worked.
    """
    import torch

    override = os.environ.get(ENV_OVERRIDE, "").strip().lower()
    if override in ("none", "off", "0"):
        return 0.0

    total = device_memory_gb(device)
    if total <= 0:
        return 0.0
    fraction = default_fraction(device)
    if override:
        try:
            fraction = float(override)
        except ValueError:
            pass
    cap = budget_gb if budget_gb > 0 else total * fraction
    # 0 means "no cap wanted here" — a discrete card with no figure asked for.
    # Its own OOM is the better error: it fires exactly when the memory really
    # is gone rather than at a fraction somebody guessed.
    if cap <= 0:
        return 0.0
    # A job may ask for MORE than torch recommends — on MPS that is the only
    # way to reach the machine's real RAM — but the fraction still has to be a
    # fraction of what the device reports.
    frac = max(0.05, cap / total)
    try:
        if device.startswith("cuda"):
            idx = torch.device(device).index or 0
            torch.cuda.set_per_process_memory_fraction(frac, idx)
        elif device.startswith("mps"):
            torch.mps.set_per_process_memory_fraction(frac)
        else:
            return 0.0
    except Exception as exc:   # noqa: BLE001
        print(f"could not arm the memory cap: {exc}", flush=True)
        return 0.0
    return round(cap, 1)

"""WHICH NOISE LEVELS a run trains on.

Every training step picks one point on the journey between a clean picture and
pure noise, adds that much noise, and asks the model to undo it. Which points
get picked is not a detail: the two ends of that journey teach different
things.

* **High noise** (near pure noise) is where the picture's LAYOUT is decided —
  what is where, how big, what the overall shape and colour of the image is.
  There is nothing but a vague shape to work with, so that is all it can be
  about.
* **Low noise** (nearly clean) is where DETAIL and TEXTURE are decided — edges,
  surfaces, small features. The composition is already fixed.

So a run that spends most of its steps near one end teaches mostly what that
end is responsible for. That is a real lever — a style is largely texture, a
character's proportions are largely layout — and until now each model family
simply had one hardcoded answer.

THE TWO FAMILIES START FROM DIFFERENT PLACES
--------------------------------------------
The older models (SD, SDXL) pick EVENLY across the range. The flow-matching
models (Chroma, FLUX, Z-Image, Qwen-Image) pick from a bell curve centred on
the middle, so they mostly train the middle of the journey and rarely the
extremes — that is what their published recipes do, and it is why those models
learn as efficiently as they do.

`"default"` means "whatever this model family does", and it is what every run
did before this module existed — bit for bit, not merely in distribution. The
other strategies are the same for both families, so a setting means the same
thing whichever model it is used with:

* ``default``      — the model family's own, as above.
* ``uniform``      — evenly across the whole range.
* ``logit_normal`` — a bell curve, whose centre and width are settings. The
  flow models' own default is this at centre 0, width 1.
* ``cosmap``       — a cosine mapping that leans towards higher noise.

The list itself is NOT repeated here. It is a `Literal` on
`TrainingConfig.timesteps` in `spec.py`, which is what validates a stored job
and what the TS type mirrors; a third copy in this module was written once and
then read by nothing, which is how a fourth spelling gets added to two of them.

WHAT IS PURE HERE AND WHAT IS NOT
---------------------------------
`apply_shift` and `describe` are arithmetic and are unit-tested from the app's
own venv. `draw` needs torch, because the draw has to happen on the training
device with the run's own generator. It keeps the DEFAULT paths on exactly the
call they always made, so switching this setting on is the only thing that can
change a run's random stream.
"""

from __future__ import annotations

import math


def apply_shift(t, shift: float):
    """Bend a position towards higher noise by ``shift``.

    ``shift`` 1 changes nothing; above it, the same draw lands at a higher
    noise level. It exists because a bigger picture has more to decide about
    its layout, so the larger the training resolution the more of the run
    should be spent up there — which is why the flow models make it a
    per-model setting (``model_params.flow_shift``) rather than a constant.

    Pure arithmetic, so the identical expression serves a Python float in a
    test and a whole batch of positions as a tensor.
    """
    if shift == 1.0:
        return t
    return (t * shift) / (1.0 + (shift - 1.0) * t)


def resolve(strategy: str, flow: bool) -> str:
    """``"default"`` turned into the concrete strategy for this model family.

    ``flow`` says which family — the newer flow-matching models centre their
    draws, the older ones spread them evenly.
    """
    strategy = str(strategy or "default")
    if strategy != "default":
        return strategy
    return "logit_normal" if flow else "uniform"


def is_family_default(strategy: str, flow: bool, mean: float, std: float) -> bool:
    """Whether this setting is EXACTLY what the family did before the setting
    existed — same distribution and same draw.

    The callers branch on it so an untouched job keeps its random stream to
    the bit, rather than merely its distribution. A different stream is not
    wrong, but it means "I changed nothing" and "the run came out differently"
    can both be true at once, which is the kind of thing that costs an
    afternoon.
    """
    if str(strategy or "default") == "default":
        return True
    if flow:
        return strategy == "logit_normal" and mean == 0.0 and std == 1.0
    return strategy == "uniform"


def draw(strategy: str, n: int, *, flow: bool, device, generator=None,
         mean: float = 0.0, std: float = 1.0, shift: float = 1.0):
    """``n`` noise positions in [0, 1), as a tensor on ``device``.

    0 is a clean picture and 1 is pure noise. The flow engines use the value
    directly; the epsilon engines multiply it up into their discrete timestep
    range.
    """
    import torch

    kind = resolve(strategy, flow)
    if kind == "logit_normal":
        z = torch.randn(n, device=device, generator=generator)
        t = torch.sigmoid(mean + std * z)
    elif kind == "cosmap":
        # The CosMap schedule: u -> 1 - 1/(tan(pi/2 * u) + 1). It spends more
        # of its draws at higher noise than an even spread without abandoning
        # the low end the way a hard shift does.
        u = torch.rand(n, device=device, generator=generator)
        t = 1.0 - 1.0 / (torch.tan(math.pi / 2.0 * u) + 1.0)
    else:
        t = torch.rand(n, device=device, generator=generator)
    return apply_shift(t, shift)


def describe(strategy: str, flow: bool, mean: float, std: float,
             shift: float) -> str:
    """One line for the run's log saying what it will actually train on.

    Worth printing because this is invisible everywhere else: two runs with
    different settings here produce the same loss curve shape and the same
    everything, and differ only in what the model ended up good at.
    """
    kind = resolve(strategy, flow)
    if kind == "uniform":
        what = "evenly across all noise levels"
    elif kind == "cosmap":
        what = "leaning towards higher noise (composition)"
    else:
        where = ("the middle" if mean == 0 else
                 "higher noise (composition)" if mean > 0 else
                 "lower noise (detail)")
        what = f"a bell curve centred on {where}"
        if std != 1.0:
            what += f", width {std:g}"
    if shift and shift != 1.0:
        what += f", shifted {shift:g}x towards higher noise"
    return f"noise levels: {what}"

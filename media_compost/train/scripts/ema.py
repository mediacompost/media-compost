"""An exponential moving average of the weights being trained.

WHAT IT IS
----------
Training moves the weights a little on every step, and each of those steps is
noisy — it is computed from a handful of images, and a different handful would
have pulled somewhere slightly different. The weights at step 1400 are
therefore not reliably better than the weights at step 1200; some of the
difference between them is just which pictures came up.

An exponential moving average keeps a second, smoothed copy of the weights
alongside the real ones. After every step it slides a little way from where it
was towards where training has just got to::

    average = average * decay + current * (1 - decay)

With a decay of 0.999 each step moves the average one thousandth of the way,
so it ends up reflecting roughly the last thousand steps rather than the last
one. The training itself is completely unaffected — the average is written to,
never read from, until the moment weights are saved.

WHAT IT BUYS
------------
The saved result stops depending on exactly which step the run happened to
stop at. Two things follow from that, and both are about not having to be
lucky:

* picking a checkpoint matters less, because the quality curve across them is
  flatter;
* overshooting the step count hurts less, because the average lags the raw
  weights and so degrades more slowly once a run starts overfitting.

WHAT IT COSTS
-------------
One extra copy of everything being trained, in full precision. For a LoRA that
is tens of megabytes and is not worth thinking about. For a full finetune it
is another whole model, which is why the editor's memory estimate counts it.

THE WARM-UP IS NOT OPTIONAL
---------------------------
A fresh average starts out equal to the weights at step 0 — which for a LoRA
is random noise. At a fixed decay of 0.999 it would take a couple of thousand
steps for that noise to fade out of it, so a 1000-step run would save an
average that is still substantially the random initialisation, and the result
would be *worse* than no averaging at all. `effective_decay` therefore ramps
the decay in from 0, so the average tracks the weights closely at the start
and only becomes a long average once there is enough history to average over.

Only `effective_decay` and the shape rules are pure; the tensor work needs
torch, so it is imported inside the methods (this module is loaded by file
path from the app's own torch-free venv to test the arithmetic).
"""

from __future__ import annotations

import contextlib


def effective_decay(decay: float, step: int) -> float:
    """The decay to use at ``step``, ramped in from the start of the run.

    ``(1 + step) / (10 + step)`` rises from 0.09 at the first step through
    0.99 at step 990 and approaches 1, so the average is a short one while the
    run is short and lengthens as history accumulates — capped by the decay
    that was asked for, which is what it settles at.

    Pure: `tests/train/test_ema.py` pins the whole curve, because the failure
    this prevents (an average still holding the random initialisation at the
    end of a short run) is invisible in a loss graph.
    """
    step = max(0, int(step))
    return min(float(decay), (1.0 + step) / (10.0 + step))


class Ema:
    """The averaged copy of a run's trainable parameters.

    Built from the same parameter list the optimizer is given, so what is
    averaged is exactly what is trained — an adapter for a LoRA run, the whole
    backbone for a full finetune.
    """

    def __init__(self, params, decay: float):
        import torch

        self.decay = float(decay)
        self.params = [p for p in params if p.requires_grad]
        # fp32 whatever the parameters are: the whole point is to accumulate
        # differences far smaller than a step, and at bf16 an update of one
        # thousandth of the gap would round away to nothing — the same reason
        # the trained parameters themselves are kept as fp32 masters.
        with torch.no_grad():
            self.shadow = [p.detach().clone().float() for p in self.params]
        self.step = 0

    def update(self) -> None:
        """Slide the average towards the current weights. Called once per
        OPTIMIZER step — never per micro-batch, which would weight a run with
        gradient accumulation differently from one without."""
        import torch

        self.step += 1
        d = effective_decay(self.decay, self.step)
        with torch.no_grad():
            for shadow, param in zip(self.shadow, self.params):
                shadow.mul_(d).add_(param.detach().float(), alpha=1.0 - d)

    @contextlib.contextmanager
    def applied(self):
        """The averaged weights IN the model for the duration, then back.

        A swap rather than a second model: the pipeline that renders samples
        and the code that saves weights both read the live modules, so this is
        what lets both see the average without either of them knowing it
        exists. The originals are restored in a `finally`, so an interrupted
        save or a cancelled sample round cannot leave the run training from
        its own average — which would compound every step after it.
        """
        import torch

        with torch.no_grad():
            backup = [p.detach().clone() for p in self.params]
            for param, shadow in zip(self.params, self.shadow):
                param.copy_(shadow.to(param.dtype))
        try:
            yield
        finally:
            with torch.no_grad():
                for param, saved in zip(self.params, backup):
                    param.copy_(saved)

    def state_dict(self) -> dict:
        return {"step": self.step, "decay": self.decay,
                "shadow": [s.cpu() for s in self.shadow]}

    def load_state_dict(self, state: dict) -> bool:
        """Restore a resumed run's average. False (and unchanged) when the
        saved shape does not match what this run trains — a job resumed after
        its rank or its layer filter was edited, where carrying the old
        average over would silently mix two different adapters."""
        import torch

        shadow = state.get("shadow") or []
        if len(shadow) != len(self.shadow):
            return False
        if any(a.shape != b.shape for a, b in zip(shadow, self.shadow)):
            return False
        with torch.no_grad():
            for mine, saved in zip(self.shadow, shadow):
                mine.copy_(saved.to(mine.device))
        self.step = int(state.get("step") or 0)
        return True


@contextlib.contextmanager
def maybe_applied(ema):
    """`ema.applied()` when there is one, and nothing when there is not — so
    every call site is one `with` rather than a branch around the save it
    guards."""
    if ema is None:
        yield
        return
    with ema.applied():
        yield

"""Half-precision master weights, made exact by carrying what the rounding
drops — Kahan (compensated) summation.

A full finetune keeps fp32 master weights and does its matmuls in bf16. On
SDXL that is 10.2 GB of weights plus 10.2 GB of gradients, against ~2 GB of
frozen aux and Adafactor's ~0.05 GB of state — on that model the weights ARE
the run. Halving them is worth having, and plain bf16 masters do not work: a
training step is far below one bf16 ulp, so rounded to nearest EVERY update
vanishes and the weight never moves. Measured over a real (tiny) SDXL UNet,
300 AdamW steps at lr 1e-4, 46.5% of the weights never moved at all.

THE CARRY IS WHAT MAKES IT WORK. One extra buffer per parameter, the same
width as the parameter, holding the low-order bits the last write threw away;
the next update adds them back before rounding. Nothing is lost — only
deferred until it is large enough to change the stored value. Measured on the
same UNet:

    fp32 masters (the default)          loss 1.066 -> 0.470
    bf16 + Kahan summation              loss 1.066 -> 0.471

i.e. the run learns what it would have learned, in two thirds of the memory
(2 bytes of weight + 2 of gradient + 2 of carry, against fp32's 4 + 4).

WHAT WAS TRIED FIRST AND IS NOT HERE. Stochastic rounding — round up or down
at the probability the remainder says, so the expectation is exact — also
makes bf16 masters move, at 4 bytes a parameter rather than 6. It was shipped
for a day and replaced, for two measured reasons.

It injects NOISE, and the noise grows as the learning rate falls: the spread
over independent runs of the same 2000 steps was 7.4% of the progress made at
lr 1e-3, 22.5% at 1e-4, 67.1% at 1e-5 and 277.7% at 1e-6. A cosine schedule
spends its whole tail down there, which is the same shape as the failure
`upcast_trainable`'s docstring records for a bf16 LoRA adapter. On the real
UNet it reached 0.529 where fp32 reached 0.470 and this reaches 0.471.

And the obvious implementation of it is BIASED. `x.to(bf16)` rounds to
NEAREST, so for an `x` in the upper half of an interval the "lower"
neighbour lands above it, the fraction goes negative, the clamp makes it zero
and the value always rounds up: measured +40.0% of an ulp at 0.6 of the way
into an interval, +25.0% at 0.75. Harmless where the update is far below half
an ulp — which is the regime it was written for, and why it trained at all —
and +47.7% of the progress made for fp16 masters at lr 1e-3. Textbook
stochastic rounding takes the neighbour toward ZERO; the bug is one line, and
Kahan needs no such rounding at all.

The literature had settled this before either was written: "Revisiting
BFloat16 Training" (arXiv 2010.06192) reports Kahan ahead of stochastic
rounding by 0.2% top-1 on ResNet-50/ImageNet, and PyTorch ships the same
idea as torchdistx's `AnyPrecisionAdamW`.

EIGHT-BIT MASTERS ARE NOT A SETTING ANYWHERE HERE, and were measured before
being refused: fp8 e4m3's ulp at |w|=1 is 7.6e-2, so a step at lr 1e-4 is
758x smaller than the smallest change the format can hold. Stochastic
rounding gets its MEAN right there too, at a spread of 85% of the progress
made — a random walk with a faint drift. Do not revisit without new numbers.

WHERE THE fp32 GOES. The optimizer's own arithmetic still wants full
precision, so each parameter is widened to fp32 FOR ITS OWN STEP and written
back through the carry. One tensor at a time: the transient buffer is the
largest parameter in the model (a few MB), not the model (gigabytes), which
is the whole point. The inner optimizer is stepped with its `param_groups`
narrowed to that one parameter — its state is keyed by the parameter object,
so stepping one at a time is exactly what stepping them together does for
every optimizer whose update is per-parameter. It is NOT that for Prodigy,
which derives one learning rate across all of them; `spec.py` refuses that
pair by name rather than letting it quietly mean something else.
"""
from __future__ import annotations


class KahanMasters:
    """An optimizer that keeps its parameters at half precision.

    Wraps another optimizer rather than reimplementing one: every fallback
    and every memory constant the editor knows about goes on meaning what it
    meant, and Adafactor's factored state, AdamW's moments and bitsandbytes'
    8-bit state are all still that optimizer's own business.
    """

    def __init__(self, inner, dtype):
        self.inner = inner
        self.dtype = dtype
        #: The Kahan carry per parameter, keyed by its position in the flat
        #: parameter list — an INDEX rather than `id(p)`, because this rides
        #: in the checkpoint and object identity does not survive a restart.
        self.carry: dict[int, object] = {}
        # `loop.py` reads these off the optimizer it is given.
        self.param_groups = inner.param_groups
        self.state = inner.state
        self.defaults = getattr(inner, "defaults", {})

    # -- the parameter list, in one order --------------------------------

    def _params(self) -> list:
        return [p for group in self.inner.param_groups for p in group["params"]]

    # -- the optimizer protocol the loop uses ----------------------------

    def zero_grad(self, *a, **kw):
        self.inner.zero_grad(*a, **kw)

    def state_dict(self):
        """The inner optimizer's state, plus the carry.

        The carry is part of the run's state: dropping it at a resume loses
        at most one ulp per weight, which is nothing — but it is free to keep
        and a resumed run should be the run it was. Nested rather than merged
        so the inner dict is untouched, whatever optimizer produced it.
        """
        return {"inner": self.inner.state_dict(), "carry": dict(self.carry)}

    def load_state_dict(self, sd):
        # A checkpoint written before the carry existed — or by a build that
        # stored the inner optimizer's state directly — is still a valid
        # optimizer state; it simply starts with an empty carry.
        if isinstance(sd, dict) and "inner" in sd and "carry" in sd:
            self.inner.load_state_dict(sd["inner"])
            params = self._params()
            self.carry = {i: c.to(params[i].data.dtype, copy=True)
                          for i, c in sd["carry"].items()
                          if isinstance(i, int) and i < len(params)}
        else:
            self.inner.load_state_dict(sd)
            self.carry = {}

    def step(self, closure=None):
        import torch

        idx = -1
        for group in self.inner.param_groups:
            for p in group["params"]:
                idx += 1
                if p.grad is None:
                    continue
                if p.dtype is torch.float32:
                    # Nothing to widen: an fp32 parameter takes the ordinary
                    # step. (Nothing puts one here today, but a mixed set is
                    # not a reason to skip it.)
                    self._step_one(group, p)
                    continue
                narrow, grad = p.data, p.grad
                before = narrow.to(torch.float32)
                # The transient fp32 pair, for this parameter alone.
                p.data, p.grad = before.clone(), grad.to(torch.float32)
                try:
                    self._step_one(group, p)
                    self._write_back(idx, narrow, before, p.data)
                finally:
                    p.data, p.grad = narrow, grad

    def _write_back(self, idx: int, narrow, before, after) -> None:
        """Store `after` in the parameter's own width, carrying the
        difference the rounding drops.

        `total` is what this step MEANT to add — the optimizer's update plus
        whatever the previous write could not represent. `applied` is what
        the store actually moved. The remainder is kept for next time, which
        is the whole of Kahan summation: a hundred updates each a tenth of an
        ulp move the weight on the tenth step rather than never.
        """
        import torch

        carry = self.carry.get(idx)
        if carry is None:
            carry = self.carry[idx] = torch.zeros_like(narrow)
        total = (after - before) + carry.to(torch.float32)
        new = (before + total).to(self.dtype)
        applied = new.to(torch.float32) - before
        carry.copy_((total - applied).to(self.dtype))
        narrow.copy_(new)

    def _step_one(self, group, p):
        """The inner optimizer's step, for one parameter.

        Its `param_groups` are narrowed rather than its state touched: the
        state is keyed by the parameter OBJECT, so it is found and updated
        exactly as it would be in a whole-model step, and every per-group
        setting (lr, weight decay, the schedule's writes into `group["lr"]`)
        travels with the copy.
        """
        saved = self.inner.param_groups
        one = dict(group)
        one["params"] = [p]
        self.inner.param_groups = [one]
        try:
            self.inner.step()
        finally:
            self.inner.param_groups = saved

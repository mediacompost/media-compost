"""The LoKr export in the naming other tools read.

`train/scripts/lycoris.py` is a RENAME plus a scale correction, and both
halves fail quietly if they are wrong: a mis-named key is dropped by the
loader (an adapter that "does nothing") and a mis-scaled one is applied at
the wrong strength (a training run that "came out weak"). So the rule is
pinned here rather than left to a look at the output.

The module is pure and takes its tensor constructor as an argument, which is
what lets most of this run in the app's venv where torch does not exist. The
one test that needs torch says so and skips.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]
                       / "media_compost" / "train" / "scripts"))

import lycoris  # noqa: E402


class _Fake:
    """The one thing `convert` asks of a tensor: a shape, and a product."""

    def __init__(self, shape, scale=1.0):
        self.shape = shape
        self.scale = scale

    def __mul__(self, other):
        return _Fake(self.shape, self.scale * other)


def _state(**params):
    return {"base_model.model.transformer_blocks.0.attn.to_q.%s" % name: value
            for name, value in params.items()}


def test_the_key_is_comfyuis_own_rule():
    """Verbatim from `comfy/lora.py`: `lycoris_` + the module path with its
    dots flattened. Nothing else in that map would match."""
    assert lycoris.lycoris_key("transformer_blocks.0.attn.to_q") \
        == "lycoris_transformer_blocks_0_attn_to_q"
    assert lycoris.lycoris_key("single_transformer_blocks.11.proj_out") \
        == "lycoris_single_transformer_blocks_11_proj_out"


def test_the_peft_prefix_is_dropped():
    """`base_model.model.` is PEFT's wrapper, not part of the model's own
    path — left on, every key names a module the loader has never heard of."""
    path, param = lycoris.split_key(
        "base_model.model.transformer_blocks.0.attn.to_q.lokr_w1")
    assert (path, param) == ("transformer_blocks.0.attn.to_q", "lokr_w1")


def test_a_decomposed_factor_carries_an_alpha():
    """ComfyUI applies `alpha / dim` with `dim` the decomposed rank, so the
    alpha written is whatever makes that equal PEFT's own `alpha / rank` —
    the configured alpha, whenever `dim` is the configured rank."""
    out = lycoris.convert(
        _state(lokr_w1=_Fake((32, 32)), lokr_w2_a=_Fake((40, 8)),
               lokr_w2_b=_Fake((8, 40))),
        scaling=4.0 / 8, tensor=float)
    base = "lycoris_transformer_blocks_0_attn_to_q"
    assert out["%s.alpha" % base] == pytest.approx(4.0)
    # And nothing is baked: the factors travel as they are.
    assert out["%s.lokr_w1" % base].scale == 1.0


def test_two_whole_factors_bake_the_scale_instead():
    """With neither factor decomposed ComfyUI has no `dim` and applies 1.0,
    so the only place left to say the scaling is in the numbers. PEFT stores
    a layer that way whenever it is small relative to the rank."""
    out = lycoris.convert(
        _state(lokr_w1=_Fake((8, 8)), lokr_w2=_Fake((8, 8))),
        scaling=4.0 / 8, tensor=float)
    base = "lycoris_transformer_blocks_0_attn_to_q"
    assert "%s.alpha" % base not in out
    assert out["%s.lokr_w1" % base].scale == pytest.approx(0.5)
    assert out["%s.lokr_w2" % base].scale == 1.0, "once, not twice"


def test_w1_decomposed_is_the_first_dim_comfyui_reads():
    """Its rule is `w1_b` first, then `w2_b`. Reading them the other way
    round picks a different rank wherever the two differ."""
    params = {"lokr_w1_a": _Fake((32, 4)), "lokr_w1_b": _Fake((4, 32)),
              "lokr_w2_a": _Fake((40, 8)), "lokr_w2_b": _Fake((8, 40))}
    assert lycoris.alpha_dim(params) == 4


def test_nothing_but_lokr_parameters_travels():
    """A state dict may carry more than the adapter (PEFT's bookkeeping, a
    base weight); a key nobody asked for is a key the loader reports as
    unloaded, which is what "lora key not loaded" spam is made of."""
    state = _state(lokr_w1=_Fake((8, 8)), lokr_w2=_Fake((8, 8)))
    state["base_model.model.transformer_blocks.0.attn.to_q.base_layer.weight"] \
        = _Fake((8, 8))
    out = lycoris.convert(state, scaling=1.0, tensor=float)
    assert sorted(out) == [
        "lycoris_transformer_blocks_0_attn_to_q.lokr_w1",
        "lycoris_transformer_blocks_0_attn_to_q.lokr_w2",
    ]


def test_the_export_reproduces_pefts_own_delta_exactly():
    """THE NUMERIC PROOF, run through ComfyUI's algorithm rather than past it.

    Everything above is about names and bookkeeping; this builds a real LoKr,
    asks PEFT what the adapter's weight delta is, then rebuilds that delta
    from the exported file the way `comfy/weight_adapter/lokr.py` does. Both
    storage shapes are covered — one layer big enough that PEFT decomposes a
    factor, one small enough that it does not — because they take the two
    different scaling paths.

    Measured when this was written: max |difference| 0.0 for both.
    """
    torch = pytest.importorskip("torch", reason="the trainer's venv has torch")
    pytest.importorskip("peft")
    import torch.nn as nn
    from peft import LoKrConfig, get_peft_model
    from peft.utils import get_peft_model_state_dict

    class Model(nn.Module):
        def __init__(self):
            super().__init__()
            self.transformer_blocks = nn.ModuleList([nn.Module()])
            block = self.transformer_blocks[0]
            block.attn = nn.Module()
            block.attn.to_q = nn.Linear(1280, 1280, bias=False)
            block.attn.to_out = nn.Linear(64, 64, bias=False)

    rank, alpha = 8, 4.0
    model = get_peft_model(Model(), LoKrConfig(
        r=rank, alpha=alpha, target_modules=["to_q", "to_out"]))
    for name, param in model.named_parameters():
        if "lokr" in name:  # PEFT zeroes one factor; a zero delta proves nothing
            with torch.no_grad():
                param.copy_(torch.randn_like(param) * 0.1)

    exported = lycoris.convert(get_peft_model_state_dict(model),
                               scaling=alpha / rank, tensor=torch.tensor)

    def comfy_delta(base: str) -> "torch.Tensor":
        """`comfy/weight_adapter/lokr.py: calculate_weight`, transcribed."""
        w1 = exported.get(base + ".lokr_w1")
        if w1 is None:
            w1 = exported[base + ".lokr_w1_a"] @ exported[base + ".lokr_w1_b"]
        w2 = exported.get(base + ".lokr_w2")
        if w2 is None:
            w2 = exported[base + ".lokr_w2_a"] @ exported[base + ".lokr_w2_b"]
        dim = None
        for name in ("lokr_w1_b", "lokr_w2_b"):
            if base + "." + name in exported:
                dim = exported[base + "." + name].shape[0]
                break
        scale = (float(exported[base + ".alpha"]) / dim
                 if base + ".alpha" in exported and dim is not None else 1.0)
        return torch.kron(w1, w2) * scale

    blocks = model.base_model.model.transformer_blocks[0]
    for path, module in (("transformer_blocks.0.attn.to_q", blocks.attn.to_q),
                         ("transformer_blocks.0.attn.to_out",
                          blocks.attn.to_out)):
        theirs = comfy_delta(lycoris.lycoris_key(path))
        mine = module.get_delta_weight("default")
        assert theirs.reshape(mine.shape).allclose(mine, atol=1e-6), path

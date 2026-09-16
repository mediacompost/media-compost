"""A LoKr adapter in the naming OTHER tools read.

A LoKr trained here used to leave this app only by being retrained somewhere
else. Not because the ecosystem cannot express one — ComfyUI has shipped a
LoKr weight adapter for years — but because of the NAMES: the trainer writes
PEFT's parameter names, and PEFT is not what those tools read.

This is the third file a LoKr checkpoint gets, beside the trainer's own copy
and (for a LoRA) the diffusers-layout one. It exists because the gap was
never the format:

    base_model.model.transformer_blocks.0.attn.to_q.lokr_w2_a   (PEFT)
    lycoris_transformer_blocks_0_attn_to_q.lokr_w2_a            (LyCORIS)

THE TARGET IS COMFYUI'S OWN KEY MAP, and the rule is quoted from it rather
than guessed: for the diffusers-named transformers (`comfy/lora.py`, the
Flux and QwenImage branches among others) it builds

    key_map["lycoris_{}".format(key[:-len(".weight")].replace(".", "_"))]

over the model's own module paths — which are exactly the paths the adapter
is attached to here, because the adapter is attached to the diffusers
transformer. The parameter suffixes need no translation at all: PEFT and
LyCORIS both spell them `lokr_w1`, `lokr_w2`, `lokr_w1_a/_b`, `lokr_w2_a/_b`
and `lokr_t2`, which is what makes this a rename rather than a conversion.

THE SCALE IS THE PART THAT CAN GO WRONG QUIETLY, and it is where the two
sides genuinely differ. PEFT applies `alpha / r` itself
(`make_kron(w1, w2, scaling)`). ComfyUI instead reads an `alpha` tensor from
the file and applies `alpha / dim`, where `dim` is the rank of whichever
factor was stored DECOMPOSED (`w1_b.shape[0]`, else `w2_b.shape[0]`) — and
where neither is, it has no `dim` and applies 1.0. So:

* a module with a decomposed factor gets an `alpha` of `scaling * dim`,
  which is our own alpha whenever `dim` is the configured rank; and
* a module with both factors stored whole — PEFT does that for layers small
  relative to the rank — gets the scaling BAKED into `lokr_w1` and no alpha
  key, because there is no other way to say it in that file.

Getting this wrong would not fail: it would apply the adapter at the wrong
strength, which reads as a bad training run.

Pure and torch-free at import: `tensor_scale` is the only thing that touches
a tensor and it takes the constructor as an argument, so
`tests/train/test_lycoris.py` drives the whole naming and scaling rule from
the app's venv, where torch does not exist.
"""

from __future__ import annotations

from collections import defaultdict

#: The file this writes. Named for the layout, like its two neighbours
#: (`adapter_weights` = PEFT's, `pytorch_lora_weights` = diffusers').
LYCORIS_FILE = "lycoris_weights.safetensors"

#: What `get_peft_model_state_dict` puts in front of every module path.
PEFT_PREFIX = "base_model.model."

#: The parameter names that make up a LoKr. Both sides spell them the same;
#: anything else in the state dict is not ours to rename.
LOKR_PARAMS = ("lokr_w1", "lokr_w2", "lokr_w1_a", "lokr_w1_b",
               "lokr_w2_a", "lokr_w2_b", "lokr_t2")


def lycoris_key(module_path: str) -> str:
    """The key ComfyUI looks a module up by: `lycoris_` + the path, flattened.

    Verbatim from `comfy/lora.py`: `"lycoris_{}".format(key.replace(".", "_"))`
    over the model's own module names.
    """
    return "lycoris_" + module_path.replace(".", "_")


def split_key(key: str) -> "tuple[str, str]":
    """A PEFT state-dict key as `(module path, parameter name)`."""
    path, _, param = key.rpartition(".")
    if path.startswith(PEFT_PREFIX):
        path = path[len(PEFT_PREFIX):]
    return path, param


def group_modules(state: dict) -> "dict[str, dict]":
    """The state dict as `{module path: {parameter: value}}`, LoKr only."""
    out: "dict[str, dict]" = defaultdict(dict)
    for key, value in state.items():
        path, param = split_key(key)
        if param in LOKR_PARAMS:
            out[path][param] = value
    return dict(out)


def alpha_dim(params: dict) -> "int | None":
    """ComfyUI's `dim`: the rank of the decomposed factor, or None.

    Its rule exactly — `w1_b` first, then `w2_b`, and no alpha scaling at all
    when neither is present.
    """
    for name in ("lokr_w1_b", "lokr_w2_b"):
        value = params.get(name)
        if value is not None:
            return int(value.shape[0])
    return None


def bake_target(params: dict) -> str:
    """Which factor a scaling with nowhere to go is multiplied into.

    `kron(c·w1, w2) == c·kron(w1, w2)`, so either whole factor would do; w1
    is the smaller of the two in every split PEFT picks, which keeps the
    rounding it costs to the fewest values.
    """
    return "lokr_w1" if "lokr_w1" in params else "lokr_w1_a"


def convert(state: dict, *, scaling: float, tensor) -> dict:
    """PEFT LoKr weights → the LyCORIS-named file's contents.

    ``scaling`` is what PEFT applies internally (alpha ÷ rank); ``tensor`` is
    `torch.tensor`, passed in so this module imports nothing.
    """
    out: dict = {}
    for path, params in group_modules(state).items():
        base = lycoris_key(path)
        dim = alpha_dim(params)
        baked = None if dim is not None else bake_target(params)
        for name, value in params.items():
            out["%s.%s" % (base, name)] = value * scaling if name == baked \
                else value
        if dim is not None:
            # `alpha / dim` is what ComfyUI will apply, so this is the number
            # that makes that equal our own scaling — the configured alpha
            # whenever `dim` is the configured rank, which is the usual case.
            out["%s.alpha" % base] = tensor(float(scaling * dim))
    return out

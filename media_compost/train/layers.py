"""WHICH LAYERS a run may name, per architecture.

The adapter section's two filter fields (`hyper.layer_include` /
`layer_exclude`) are SUBSTRINGS of a module path — `transformer_blocks.12.
attn.to_q` — so what somebody types is a block, a stack of blocks, or a
single projection. Nothing was ever offered to type, and a module path is not
something anybody knows off the top of their head.

**The names are a fact about the ARCHITECTURE, not about the checkpoint.**
That is what makes a static table right rather than a compromise: a custom
model declares which architecture it is (that is what picks its engine, its
hyperparameters and its memory profile), so a community SDXL finetune has
SDXL's module names, and a table keyed by ENGINE covers every model the
registry can hold — including ones added later, and including ones whose
weights have not been downloaded.

The alternative was to read the names off the model. It is possible — the
tiny random-weight backbones `tests/train/engine_smoke.py` builds from the
real configs take a couple of seconds and download nothing — but it needs the
training venv and a subprocess per look, to answer a question whose answer
cannot vary between two checkpoints of one architecture.

WHAT IS IN THE TABLE is what a person would want to name: the STACKS (the
halves of a UNet, the two block lists of a joint-stream DiT) and the
attention SELECTORS that mean something (`attn1` is self-attention, `attn2`
is where the prompt gets in). The projections — `to_q` and its siblings — are
the engine's own `adapter_targets` and are added from there, so this file
never restates them.

The lists are NOT translated, for the reason a query keyword is not: they are
literal text the field matches against, and a translated `down_blocks` would
match nothing.
"""

from __future__ import annotations

#: The projections each engine attaches to — a copy of the engines' own
#: `adapter_targets`, which live in `train/scripts/` where the app (no torch)
#: cannot import them. `tests/train/test_layer_hints.py` reads the engine
#: source and holds these equal, so the copy cannot drift.
_TARGETS: dict[str, tuple[str, ...]] = {
    "sd": ("to_q", "to_k", "to_v", "to_out.0"),
    "sdxl": ("to_q", "to_k", "to_v", "to_out.0"),
    "zimage": ("to_q", "to_k", "to_v", "to_out.0"),
    "chroma": ("to_q", "to_k", "to_v", "to_out.0", "add_q_proj", "add_k_proj",
               "add_v_proj", "to_add_out"),
    "flux": ("to_q", "to_k", "to_v", "to_out.0", "add_q_proj", "add_k_proj",
             "add_v_proj", "to_add_out"),
    "flux2": ("to_q", "to_k", "to_v", "to_out.0", "add_q_proj", "add_k_proj",
              "add_v_proj", "to_add_out"),
    "qwenimage": ("to_q", "to_k", "to_v", "to_out.0", "add_q_proj",
                  "add_k_proj", "add_v_proj", "to_add_out"),
}

#: The STACKS and selectors, read off the real module trees (the dump in
#: `test_layer_hints.py` is what keeps them honest).
_STACKS: dict[str, tuple[str, ...]] = {
    # A UNet: the two halves and the middle, then the two attentions —
    # `attn1` is the picture attending to itself, `attn2` is where the prompt
    # gets in, which is the one distinction worth naming on this family.
    "sd": ("down_blocks", "mid_block", "up_blocks", "attn1", "attn2"),
    "sdxl": ("down_blocks", "mid_block", "up_blocks", "attn1", "attn2"),
    # Joint-stream DiTs: two block lists, the double then the single.
    "chroma": ("transformer_blocks", "single_transformer_blocks"),
    "flux": ("transformer_blocks", "single_transformer_blocks"),
    "flux2": ("transformer_blocks", "single_transformer_blocks"),
    # One list, and its text branch is the `add_*` projections above.
    "qwenimage": ("transformer_blocks",),
    # Z-Image names its stack `layers`, with two refiners before it.
    "zimage": ("layers", "noise_refiner", "context_refiner"),
}


def hints_for(engine: str) -> list[str]:
    """The layer names to offer for ``engine``, stacks before projections.

    Empty for an engine with no entry — a model added without a row here
    simply offers nothing, rather than offering another architecture's names.
    """
    return [*_STACKS.get(engine, ()), *_TARGETS.get(engine, ())]

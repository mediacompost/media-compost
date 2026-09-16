"""How an adapter is named on disk, and which layers it attaches to.

`train/scripts/adapters.py` imports nothing at module level, so — like
`compose.py`, `images.py` and `latentio.py` — it is loaded by file path and
exercised from the main backend venv, which has no torch. The two halves
tested here are exactly the two that need none: the key naming that decides
whether a checkpoint can be read back at all, and the layer filter, which is
string work over module paths.
"""

from __future__ import annotations

import importlib.util

import pytest

from media_compost.train.paths import TRAIN_SCRIPTS


def _adapters():
    p = TRAIN_SCRIPTS / "adapters.py"
    spec = importlib.util.spec_from_file_location("adapters_under_test", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


adapters = _adapters()


# ---- the key naming ---------------------------------------------------------
#
# A checkpoint that cannot be split back into its components is a checkpoint
# that cannot be resumed from, and the failure is silent: the parts simply do
# not match the modules and nothing is restored.


def test_a_state_dict_survives_the_round_trip():
    parts = {
        "transformer": {"base_model.model.blocks.0.attn.to_q.lora_A.weight": 1,
                        "base_model.model.blocks.0.attn.to_q.lora_B.weight": 2},
        "text_encoder": {"base_model.model.layers.3.self_attn.q_proj.lora_A.weight": 3},
    }
    assert adapters.group_state(adapters.flatten_state(parts)) == parts


def test_a_parameter_name_may_hold_any_number_of_dots():
    """The split is from the LEFT and once — a component name has no dot, a
    PEFT parameter name has many, so there is exactly one place to divide."""
    parts = {"unet": {"a.b.c.d.e.lora_A.weight": 1}}
    flat = adapters.flatten_state(parts)
    assert list(flat) == ["unet.a.b.c.d.e.lora_A.weight"]
    assert adapters.group_state(flat) == parts


# ---- the layer filter -------------------------------------------------------

PATHS = [
    "down_blocks.0.attentions.0.transformer_blocks.0.attn1.to_q",
    "down_blocks.0.attentions.0.transformer_blocks.0.attn1.to_k",
    "down_blocks.0.attentions.0.transformer_blocks.0.attn1.to_out.0",
    "mid_block.attentions.0.transformer_blocks.0.attn1.to_q",
    "up_blocks.1.attentions.0.transformer_blocks.0.attn1.to_q",
    "conv_in",                      # not a target name
    "time_embedding.linear_1",      # not a target name
]
TARGETS = ["to_q", "to_k", "to_v", "to_out.0"]


def test_no_filter_selects_every_targeted_projection():
    got = adapters.select_layers(PATHS, TARGETS, [], [])
    assert got == PATHS[:5]
    assert "conv_in" not in got


def test_include_narrows_to_named_blocks():
    got = adapters.select_layers(PATHS, TARGETS, ["mid_block"], [])
    assert got == ["mid_block.attentions.0.transformer_blocks.0.attn1.to_q"]


def test_exclude_wins_over_include():
    got = adapters.select_layers(PATHS, TARGETS, ["blocks"], ["down_blocks"])
    assert all("down_blocks" not in p for p in got)
    assert "mid_block.attentions.0.transformer_blocks.0.attn1.to_q" in got


def test_a_target_is_matched_at_a_PATH_BOUNDARY_not_as_a_substring():
    """`to_out.0` must not be matched by `...to_out.01`, and a projection
    named `custom_to_q` is not `to_q`. Suffix matching on a whole segment is
    what PEFT itself does, so the enumerated list agrees with what PEFT would
    have selected for the unfiltered case."""
    paths = ["block.custom_to_q", "block.to_q"]
    assert adapters.select_layers(paths, ["to_q"], [], []) == ["block.to_q"]


def test_a_bare_path_equal_to_the_target_counts():
    assert adapters.select_layers(["to_q"], ["to_q"], [], []) == ["to_q"]


@pytest.mark.parametrize("needles", [[], [""], ["   "]])
def test_a_blank_filter_entry_matches_nothing(needles):
    """An empty row left in the editor must not become "match everything",
    which is what a naive `any(n in name)` over `[""]` would do."""
    assert not adapters.name_matches("down_blocks.0.attn.to_q", needles)

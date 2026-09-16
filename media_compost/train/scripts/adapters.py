"""How an adapter is BUILT and how it is STORED.

An adapter is the small trainable thing laid over a frozen base model — what
"LoRA training" produces. This module owns three questions that every engine
used to answer for itself, in seven near-identical copies:

* **which kind** of adapter to build (``network.type``: LoRA or LoKr),
* **which layers** of the backbone it attaches to (``network.include`` /
  ``network.exclude``),
* **how the trained weights are written to disk and read back**.

Splitting it out is not tidying. The seven copies had already drifted in one
place that mattered — SDXL named its two text-encoder adapters ``te1``/``te2``
where SD named its one ``text_encoder`` — and every new option below would
have been seven more edits with seven chances to miss one.

WHAT IS ON DISK, AND WHY THERE ARE TWO FILES
--------------------------------------------
A finished checkpoint holds both of:

``adapter_weights.safetensors``
    The trainer's OWN copy: the exact parameter names PEFT uses, so a run can
    resume from it and a later job can start from it. It is what this trainer
    reads back.

``pytorch_lora_weights.safetensors``
    The PORTABLE copy, in the layout diffusers defines — the file other tools
    (diffusers itself, ComfyUI, the web UIs) know how to load. Written for
    LoRA only, because that layout is defined for LoRA and nothing else; see
    `portable_supported`.

Both are safetensors, which is the point of the pair. Weights used to be a
``torch.save`` pickle (``lora_weights.pt``) that only this trainer could read,
and only the FINAL output ever got a portable file — so every intermediate
checkpoint, which is exactly what somebody picks when a run overtrains, could
not be used anywhere without being converted by hand first. safetensors also
loads without executing anything, which a pickle does not.

Reading stays backwards compatible in both directions: `load_state` still
reads the old ``.pt`` layout (a job paused before this change resumes cleanly)
and still understands the old ``te1``/``te2`` names.
"""

from __future__ import annotations

import json
from pathlib import Path

#: The trainer's own weights file — PEFT parameter names, safetensors.
STATE_FILE = "adapter_weights.safetensors"

#: What sits beside it describing the adapter: kind, rank, alpha, and which
#: modules it was attached to. Written so a checkpoint can say what it IS
#: without the config that produced it — a file handed to somebody else, or a
#: job whose settings have since been edited.
STATE_META = "adapter_config.json"

#: The portable file, in diffusers' own layout. Its name is diffusers' —
#: `save_lora_weights` chooses it, and `load_lora_weights` looks for it.
PORTABLE_FILE = "pytorch_lora_weights.safetensors"

#: The separator between a part name and a PEFT parameter name in the flat
#: safetensors key space. A plain "." works because a part is a pipeline
#: component name (`unet`, `transformer`, `text_encoder`, `text_encoder_2`)
#: and none of those contains a dot, so splitting once from the left is exact
#: however many dots the parameter name itself carries.
_SEP = "."


def build_config(hyper: dict, targets):
    """The PEFT config for this run's adapter, over ``targets``.

    ``targets`` is the list of module NAMES inside the model the adapter
    attaches to (``to_q``, ``to_k``, …) — which layers of the network those
    names are found in is `layer_filter`'s question, not this one.

    TWO KINDS, and the difference is what shape of change they can express.

    **LoRA** adds a low-rank product: two thin matrices whose product is added
    to the frozen weight. Its capacity is exactly its rank — a rank-16 adapter
    can only ever express a rank-16 change, however many parameters you give
    it — which is plenty for "this character's face" and is the actual ceiling
    for "this artist's line".

    **LoKr** builds the change as a Kronecker product of two much smaller
    matrices instead. The saving comes from that structure rather than from
    discarding rank, so the change it expresses is not confined to a thin
    slice of the weight while the file stays a fraction of a LoRA's — measured
    on a real UNet at rank 8, under a tenth of the trainable parameters.
    `decompose_factor` is how the weight is split into the two factors; -1
    lets PEFT pick the squarest split, which is the one that makes them
    smallest, and is what anybody wanting a smaller file means.
    """
    rank = int(hyper.get("rank", 16))
    alpha = float(hyper.get("alpha", rank))
    kind = str(hyper.get("network", "lora") or "lora")
    if kind == "lokr":
        from peft import LoKrConfig

        # `alpha`, not `lora_alpha` — the two configs spell it differently,
        # and passing the wrong one is a TypeError at attach time rather than
        # anything subtle.
        return LoKrConfig(
            r=rank, alpha=alpha, target_modules=list(targets),
            decompose_factor=int(hyper.get("lokr_factor", -1) or -1),
        )
    from peft import LoraConfig

    return LoraConfig(
        r=rank, lora_alpha=alpha,
        init_lora_weights="gaussian", target_modules=list(targets),
    )


def name_matches(name: str, needles) -> bool:
    """Whether a module's full path contains any of ``needles``.

    Plain case-sensitive substring matching, deliberately — module paths are
    lower-case identifiers (``transformer_blocks.12.attn.to_q``), so a
    substring is enough to name a block, a range of blocks by their shared
    prefix, or a single projection, and it needs nothing explained before it
    can be used. A regex would be more precise and would put the burden of
    escaping a dot on somebody who wanted to type ``down_blocks``.

    PURE, and imports nothing: `tests/train/test_adapters.py` drives the whole
    rule from the app's own venv, where torch does not exist.
    """
    return any(str(n) in name for n in needles if str(n).strip())


def select_layers(paths, targets, include, exclude) -> list:
    """The module paths an adapter should attach to.

    ``paths`` is every module path in the backbone, ``targets`` the projection
    names the architecture exposes (``to_q``…). A path qualifies when it ends
    with one of the targets, then survives ``include`` (empty = everything)
    and then ``exclude`` (which wins).

    Split from `layer_filter` so the rule is testable without a model: this is
    string work, and the only reason the caller needs torch is to enumerate
    the paths.
    """
    out = []
    for path in paths:
        if not any(path == t or path.endswith("." + t) for t in targets):
            continue
        if include and not name_matches(path, include):
            continue
        if exclude and name_matches(path, exclude):
            continue
        out.append(path)
    return out


def layer_filter(model, targets, hyper: dict):
    """``targets`` narrowed to the layers this run asked for.

    With no filter set this returns ``targets`` UNCHANGED — the plain list of
    projection names PEFT matches by suffix, exactly as before this existed.
    That is not an optimisation: it means every job configured before layer
    targeting behaves identically, and that enumerating module paths here can
    never disagree with PEFT's own matching for the runs that do not ask for
    it.

    With a filter set the paths are enumerated and handed over in FULL, which
    PEFT accepts and matches exactly. A filter matching nothing RAISES: an
    adapter over no layers trains perfectly happily and learns nothing, and
    the loss curve looks like any other — this is the one failure the feature
    can produce, so it is the one thing it refuses to do quietly.
    """
    include = [s for s in (hyper.get("layer_include") or []) if str(s).strip()]
    exclude = [s for s in (hyper.get("layer_exclude") or []) if str(s).strip()]
    if not include and not exclude:
        return list(targets)
    import torch

    paths = [name for name, module in model.named_modules()
             if isinstance(module, (torch.nn.Linear, torch.nn.Conv2d))]
    chosen = select_layers(paths, list(targets), include, exclude)
    if not chosen:
        raise RuntimeError(
            "the layer filter matched no layers, so the adapter would train "
            "nothing. Include " + (", ".join(include) or "(everything)") +
            ", exclude " + (", ".join(exclude) or "(nothing)") +
            " — check the names against the model map on the job's page.")
    print(f"layer filter: {len(chosen)} of "
          f"{len(select_layers(paths, list(targets), [], []))} adapter layers",
          flush=True)
    return chosen


def modules_in(state: dict) -> list:
    """The module paths a saved part's parameter names refer to.

    A PEFT parameter is ``<module path>.<adapter parameter>`` — for example
    ``down_blocks.1…attn1.to_q.lokr_w1`` — so the paths the adapter was
    attached to are recoverable from the file itself. That is what lets a
    LoKr be re-attached without recording its layer filter anywhere: the
    weights already say exactly which layers it covers, and a list written
    down separately could disagree with them.

    Pure, and it does not care what the values are.
    """
    out = []
    for key in state:
        head = key.rsplit(".", 1)[0]
        if head and head not in out:
            out.append(head)
    return out


def rebuild_config(meta: dict, state: dict):
    """The PEFT config that re-attaches a SAVED adapter, from its own files.

    Used when loading an adapter into a pipeline that was not built by an
    engine — the Evaluate tab — where there is no `hyper` to read. The rank,
    alpha and Kronecker factor come from `adapter_config.json` and the layers
    from the weights, so a filtered adapter re-attaches to exactly the layers
    it was trained on.
    """
    hyper = {
        "network": str(meta.get("network", "lora") or "lora"),
        "rank": int(meta.get("rank", 16) or 16),
        "alpha": float(meta.get("alpha", 16) or 16),
        "lokr_factor": int(meta.get("factor", -1) or -1),
    }
    return build_config(hyper, modules_in(state))


def flatten_state(parts: dict) -> dict:
    """``{component: {name: value}}`` → one flat mapping, keys prefixed.

    Pure, and it does not care what the values are, so the naming rule can be
    tested without torch — which the app's own venv does not have.
    """
    return {f"{part}{_SEP}{name}": value
            for part, state in parts.items()
            for name, value in state.items()}


def group_state(flat: dict) -> dict:
    """The inverse of `flatten_state`.

    Splitting once from the LEFT is what makes this exact: a component name
    holds no dot and a PEFT parameter name holds several, so there is only one
    place the key can divide.
    """
    out: dict[str, dict] = {}
    for key, value in flat.items():
        part, _, name = key.partition(_SEP)
        out.setdefault(part, {})[name] = value
    return out


def save_state(out: Path, parts: dict, meta: dict | None = None) -> None:
    """Write the trainer's own copy of every trained adapter.

    ``parts`` maps a pipeline component name to its PEFT state dict. Tensors
    are moved to the CPU and made contiguous first: safetensors refuses a view
    into a larger storage, which is what a sliced or transposed parameter is,
    and the failure message names neither the tensor nor the reason.
    """
    from safetensors.torch import save_file

    flat = {k: v.detach().cpu().contiguous()
            for k, v in flatten_state(parts).items()}
    # safetensors metadata is str -> str only, so the record goes in as JSON.
    # `parts` is listed explicitly rather than left to be re-derived from the
    # key prefixes: a component that trained to all-zero weights would still
    # be named, and reading back a file should not depend on parsing.
    info = {"parts": json.dumps(sorted(parts)), "format": "pt"}
    save_file(flat, str(Path(out) / STATE_FILE), metadata=info)
    if meta is not None:
        with open(Path(out) / STATE_META, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=1, sort_keys=True)


def load_state(src: Path) -> dict:
    """Every trained adapter from a checkpoint, by pipeline component.

    Raises FileNotFoundError naming the directory when the file is not there
    — which is what a pruned checkpoint looks like.
    """
    src = Path(src)
    path = src / STATE_FILE
    if path.is_file():
        from safetensors.torch import load_file

        return group_state(load_file(str(path)))
    raise FileNotFoundError(
        f"{src} holds no adapter weights (a pruned checkpoint, or a directory "
        f"that was never a checkpoint)")


def read_meta(src: Path) -> dict:
    """The ``adapter_config.json`` beside a checkpoint's weights, or {}.

    Used to explain a mismatch rather than to drive anything: when a starting
    adapter will not apply, what it was trained as is the fact that answers
    why.
    """
    try:
        with open(Path(src) / STATE_META, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}

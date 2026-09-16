"""RAM++ (Recognize Anything Plus) open-vocabulary tagging via the `ram` package."""

from __future__ import annotations

import os

_CKPT = "ram_plus_swin_large_14m.pth"

#: THE SECOND REPO THIS MODEL NEEDS, AND THE ONE NOBODY DECLARED.
#: `RAM_plus.__init__` ends with ``init_tokenizer(text_encoder_type)``, i.e.
#: ``BertTokenizer.from_pretrained("bert-base-uncased")`` — a Hugging Face
#: call made from inside the `ram` package, over a repo the manifest never
#: mentions. So a fresh install read "Downloaded" (the checkpoint probe was
#: there), and the first tagging run went to the network for ~700 KB of
#: tokenizer — which is not merely a surprise: `jobs.py` promises that a job
#: "always runs offline", and that promise reaches only our own
#: `hf_hub_download` below. On a machine with no network the first RAM++ run
#: did not download, it FAILED, in `init_tokenizer`, with the Settings row
#: still green. The two hooks below are how a plugin says "my weights are not
#: all in my sources" (InsightFace's pack is the other one).
_TEXT_ENCODER = "bert-base-uncased"

#: What `from_pretrained` actually pulls for this repo — verified against a
#: cache it had populated by itself. The list is spelled out rather than
#: fetched by calling `from_pretrained` here so that `fetch_weights` and
#: `weights_ready` agree BY CONSTRUCTION: a probe stricter than the fetch is a
#: row stuck on "Download" that pressing Download can never turn green.
_TOKENIZER_FILES = ("vocab.txt", "tokenizer.json", "tokenizer_config.json")

try:
    from ..framework import ModelSource, ModelSpec, PluginManifest

    MANIFEST = PluginManifest(
        models=[ModelSpec(id="ram_plus", task="tag", name="RAM++", family="RAM++",
                          note="Recognize Anything Plus; thousands of open English tags.")],
        sources=[ModelSource(key="ram_plus", label="RAM++ (Recognize Anything)",
                             repo="xinyu1205/recognize-anything-plus-model",
                             url="https://huggingface.co/xinyu1205/recognize-anything-plus-model",
                             probe=_CKPT,
                             # The 479 MB `ram_plus_tag_embedding_*.pth` beside
                             # it is read only by stage="train_from_scratch";
                             # at eval the embeddings come out of the
                             # checkpoint itself.
                             allow_patterns=(_CKPT,))],
        deps=("torch", "ram", "torchvision", "fairscale"),
        url="https://huggingface.co/xinyu1205/recognize-anything-plus-model",
        source_for_model={"ram_plus": "ram_plus"},
        # Explicit: the "ram" import comes from the recognize-anything GitHub
        # repo — a synthesized "pip install ram" would grab an unrelated
        # package. The torch pair goes through setup_env.py's torch mode,
        # LAST — the git install drags its own torch in from PyPI (CPU-only
        # on Windows), and the index install has to have the final word.
        setup=(
            "{pip} install pillow fairscale",
            "{pip} install git+https://github.com/xinyu1205/recognize-anything.git",
            "{python} -m media_compost.hub.setup_env torch",
        ),
    )
except (ImportError, ValueError):
    MANIFEST = None


def _find_pruneable_heads_and_indices(heads, n_heads, head_size, already_pruned_heads):  # pragma: no cover
    """Vendored copy of transformers' old head-pruning helper (removed in 5.x),
    from huggingface/transformers, **Apache-2.0** (see
    THIRD-PARTY-NOTICES.md). RAM's BERT imports it but never calls it at
    inference."""
    import torch
    mask = torch.ones(n_heads, head_size)
    heads = set(heads) - already_pruned_heads
    for head in heads:
        head = head - sum(1 if h < head else 0 for h in already_pruned_heads)
        mask[head] = 0
    mask = mask.view(-1).contiguous().eq(1)
    index = torch.arange(len(mask))[mask].long()
    return heads, index


def _transformers_compat() -> None:  # pragma: no cover - heavy optional dep
    """Back-fill symbols the `ram` package imports from transformers.modeling_utils
    that newer transformers moved or removed, so `import ram` works on 5.x."""
    import transformers.modeling_utils as mu
    try:
        import transformers.pytorch_utils as pu
    except ImportError:
        pu = None
    fallbacks = {"find_pruneable_heads_and_indices": _find_pruneable_heads_and_indices}
    for name in ("apply_chunking_to_forward", "find_pruneable_heads_and_indices",
                 "prune_linear_layer"):
        if hasattr(mu, name):
            continue
        src = pu if pu is not None and hasattr(pu, name) else None
        val = getattr(src, name) if src is not None else fallbacks.get(name)
        if val is not None:
            setattr(mu, name, val)

    # RAM's init_tokenizer reads tokenizer.additional_special_tokens_ids, which
    # transformers 5.x removed (extra special tokens moved from the
    # "additional_special_tokens" entry of _special_tokens_map to the
    # _extra_special_tokens list). Restore both accessors as properties.
    from transformers.tokenization_utils_base import PreTrainedTokenizerBase

    if not hasattr(PreTrainedTokenizerBase, "additional_special_tokens"):
        def _ast(self):
            extra = getattr(self, "_extra_special_tokens", None)
            if extra:
                return [str(t) for t in extra]
            m = getattr(self, "_special_tokens_map", None) or {}
            v = m.get("additional_special_tokens")
            return [str(t) for t in v] if v else []
        PreTrainedTokenizerBase.additional_special_tokens = property(_ast)
    if not hasattr(PreTrainedTokenizerBase, "additional_special_tokens_ids"):
        def _ast_ids(self):
            return self.convert_tokens_to_ids(self.additional_special_tokens)
        PreTrainedTokenizerBase.additional_special_tokens_ids = property(_ast_ids)

    # RAM's vendored bert.py ends __init__ with the old-style init_weights()
    # instead of post_init(); on 5.x init_weights -> tie_weights reads
    # self.all_tied_weights_keys, which only post_init sets. Compute it lazily.
    from transformers import PreTrainedModel
    if (hasattr(PreTrainedModel, "get_expanded_tied_weights_keys")
            and not getattr(PreTrainedModel.init_weights, "_mc_ram_shim", False)):
        _orig_init_weights = PreTrainedModel.init_weights

        def _init_weights(self):
            if not hasattr(self, "all_tied_weights_keys"):
                try:
                    self.all_tied_weights_keys = self.get_expanded_tied_weights_keys(
                        all_submodels=False)
                except Exception:  # noqa: BLE001 - nothing to tie
                    self.all_tied_weights_keys = {}
            return _orig_init_weights(self)

        _init_weights._mc_ram_shim = True
        PreTrainedModel.init_weights = _init_weights

    # 5.x also dropped ModuleUtilsMixin.get_head_mask, which RAM's bert.py
    # calls each forward (always with head_mask=None at inference). Vendored
    # from old transformers.
    from transformers.modeling_utils import ModuleUtilsMixin
    if not hasattr(ModuleUtilsMixin, "get_head_mask"):
        def _get_head_mask(self, head_mask, num_hidden_layers,
                           is_attention_chunked=False):
            if head_mask is None:
                return [None] * num_hidden_layers
            if head_mask.dim() == 1:
                head_mask = head_mask[None, None, :, None, None]
                head_mask = head_mask.expand(num_hidden_layers, -1, -1, -1, -1)
            elif head_mask.dim() == 2:
                head_mask = head_mask[:, None, :, None, None]
            head_mask = head_mask.to(dtype=next(self.parameters()).dtype)
            if is_attention_chunked:
                head_mask = head_mask.unsqueeze(-1)
            return head_mask
        ModuleUtilsMixin.get_head_mask = _get_head_mask


def weights_ready() -> bool:
    """Whether the text tokenizer is cached — asked on every Settings poll, so
    it imports nothing heavier than the hub cache probe (and answers False
    where huggingface_hub is absent, which is also when nothing here can run).
    """
    from media_compost.hub import repo_cached

    return all(repo_cached(_TEXT_ENCODER, f) for f in _TOKENIZER_FILES)


def fetch_weights() -> None:  # pragma: no cover - network
    """Pull the tokenizer up front, so the first tagging run needs no network."""
    from huggingface_hub import snapshot_download

    snapshot_download(_TEXT_ENCODER, allow_patterns=list(_TOKENIZER_FILES))
    if not weights_ready():
        raise RuntimeError(f"{_TEXT_ENCODER} tokenizer did not land in the cache")
    # Then load it once, best effort. This is not a second download: what it
    # adds are the `.no_exist` markers for the optional files this repo does
    # not carry (special_tokens_map.json and friends), which is what lets a
    # later load resolve entirely from the cache with the hub unreachable.
    try:
        from transformers import BertTokenizer

        BertTokenizer.from_pretrained(_TEXT_ENCODER)
    except Exception:  # noqa: BLE001 - the files are down, which is the point
        pass


def load(load_key, ctx):  # pragma: no cover - heavy optional dep
    import torch

    _transformers_compat()
    from ram import get_transform
    from ram.models import ram_plus as ram_plus_model

    src = ctx["sources"]["ram_plus"]
    if os.path.isdir(src):
        ckpt = os.path.join(src, _CKPT)
    else:
        from huggingface_hub import hf_hub_download
        ckpt = hf_hub_download(src, _CKPT,
                               local_files_only=bool(ctx.get("local_files_only", True)),
                               token=ctx.get("token") or None)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    # `text_encoder_type` is named rather than defaulted so the repo
    # `fetch_weights` prefetches is provably the one this load asks for.
    model = ram_plus_model(pretrained=ckpt, image_size=384, vit="swin_l",
                           text_encoder_type=_TEXT_ENCODER)
    model.eval().to(device)
    transform = get_transform(image_size=384)
    return (model, transform, device)


def run(task, model_id, handle, image, options):  # pragma: no cover - heavy optional dep
    import torch
    from ram import inference_ram

    model, transform, device = handle
    x = transform(image.convert("RGB")).unsqueeze(0).to(device)
    with torch.no_grad():
        res = inference_ram(x, model)
    english = res[0] if isinstance(res, (list, tuple)) else res
    tags = [{"name": t.strip(), "box": None}
            for t in str(english).split("|") if t.strip()]
    return {"tags": tags}

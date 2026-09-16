"""Shared engine plumbing: LoRA attachment, checkpoints, epsilon-loss helpers.

An engine wraps one base model family for ``loop.py``. The contract:

    e = Engine(config, model_info, device, dtype)
    e.load()
    lat = e.encode_image(pil)                    # scaled VAE latent, cpu ok
    e.after_latent_cache(cached=True)            # may free the VAE
    groups = e.trainable_params(lr)              # optimizer param groups
    loss = e.train_step(latents, captions, weights, rng)
    e.save_weights(dir); step = e.load_checkpoint(dir, optimizer)
    e.save_output(dir); e.generate_samples(...)
    e.stop_text_encoder_training()

Heavy imports stay inside methods.
"""

from __future__ import annotations

import contextlib
import os
import random
from pathlib import Path


def _model_index(src: str) -> dict | None:
    """A local snapshot's parsed ``model_index.json``, or None for a repo id
    (nothing is on disk to read, so every optional component is named)."""
    import json

    path = Path(src) / "model_index.json"
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def pipeline_class(src: str, default: str, family: tuple[str, ...] = ()):
    """The diffusers pipeline class to load ``src`` with.

    One engine can serve a whole FAMILY — FLUX.2 is Klein (Qwen3 encoder, no
    guidance embedding) and dev (Mistral, distilled guidance) over the same
    transformer, the same latent packing and the same LoRA targets, differing
    only in which pipeline class carries which text encoder. Grouping them
    under one engine is what puts them in one architecture group in the app,
    and it needs the class to be per MODEL rather than per engine.

    For a family this hands the question to **diffusers' own auto-resolution**
    (`DiffusionPipeline.from_pretrained` reads the source's
    `model_index.json` and returns the class it names) rather than reading
    that file here. Reading it ourselves was the first version and it is
    wrong in exactly the case that matters: a repo nobody has downloaded yet
    has no `model_index.json` on disk to read, so every not-yet-fetched
    model would have loaded as the engine's DEFAULT — FLUX.2 dev trained with
    Klein's Qwen3 prompt path. `from_pretrained` fetches the manifest as part
    of the download it is doing anyway. Call `check_family` on the result:
    auto-resolution answers what the model IS, not whether this engine can
    train it.

    ``default`` is still the answer for a single-file checkpoint (no manifest
    exists) and for an engine that serves exactly one pipeline, which is why
    those keep behaving exactly as they did before this existed.
    """
    import diffusers

    if family and not str(src).endswith((".safetensors", ".ckpt")):
        return diffusers.DiffusionPipeline
    return getattr(diffusers, default)


def check_family(pipe, family: tuple[str, ...], engine: str):
    """Refuse a pipeline this engine does not train, by name.

    The failure guarded against is silent: a FLUX.2 engine handed some other
    diffusers pipeline would run its own conditioning and packing against a
    model that wants neither, and produce a loss curve like any other.
    """
    name = type(pipe).__name__
    if family and name not in family:
        raise RuntimeError(
            f"these weights load as {name}, which the {engine} engine does "
            f"not train (it serves {', '.join(family)}). Check the model's "
            f"architecture in the Models tab.")
    return type(pipe)


UNET_LORA_TARGETS = ["to_q", "to_k", "to_v", "to_out.0"]
#: A CLIP text encoder's attention projections — what a text-encoder adapter
#: attaches to on SD, SDXL and FLUX.1's CLIP-L.
TE_LORA_TARGETS = ["q_proj", "k_proj", "v_proj", "out_proj"]
#: The same four on a T5 encoder (Chroma's T5, FLUX.1's T5-XXL), whose
#: attention names them `q`/`k`/`v`/`o`. PEFT matches a target against the END
#: of a module path (`...SelfAttention.q`), so the one-letter names are exact:
#: `wo`, the FFN's output projection, does not end in `.o`. The FFN
#: (`wi_0`/`wi_1`/`wo`) is deliberately left out, as it is on CLIP: an
#: adapter over the attention alone is the smaller, safer change, and the
#: text encoder is the half of a run that drifts first.
T5_LORA_TARGETS = ["q", "k", "v", "o"]
#: The attention projections a single-stream DiT exposes (Z-Image, Krea 2).
#: The joint-stream ones (FLUX, Chroma) add the `add_*` pair for the text
#: side; see those engines' own TRANSFORMER_LORA_TARGETS.
DIT_LORA_TARGETS = ["to_q", "to_k", "to_v", "to_out.0"]


def step_end_checker(check):
    """A diffusers ``callback_on_step_end`` that runs ``check()`` (the
    trainer's control poll) once per denoising step, so a pause or cancel
    interrupts a sample render instead of waiting out the whole round —
    a round is minutes of GPU time. ``None`` in, ``None`` out."""
    if check is None:
        return None

    def cb(pipeline, i, t, callback_kwargs):
        check()
        return callback_kwargs

    return cb


def sample_groups(prompts, area, batch):
    """Group sample prompts into pipeline calls.

    Yields ``(indices, prompts, negatives, width, height)``. Only prompts of
    the SAME size can travel in one call, so a set with mixed sizes batches
    within each size; the indices come back so every image keeps its own slot
    (and its own seed) whatever the grouping was.
    """
    batch = max(1, int(batch or 1))
    by_size: dict[tuple, list[int]] = {}
    resolved = []
    for i, (prompt, negative, width, height) in enumerate(prompts):
        w, h = int(width or area), int(height or area)
        resolved.append((prompt, negative or "", w, h))
        by_size.setdefault((w, h), []).append(i)
    for (w, h), idxs in by_size.items():
        for start in range(0, len(idxs), batch):
            chunk = idxs[start:start + batch]
            yield (chunk,
                   [resolved[i][0] for i in chunk],
                   [resolved[i][1] for i in chunk],
                   w, h)


def decode_samples(pipe, vae, latents):
    """PIL images from sample latents, decoded with the VAE in ITS OWN dtype.

    The pipeline's own decode ends with

        elif latents.dtype != self.vae.dtype:
            if torch.backends.mps.is_available():
                self.vae = self.vae.to(latents.dtype)

    — and it means it: on Apple silicon it casts the VAE we handed it down to
    the latents' dtype and keeps it that way. Ours is deliberately fp32
    (SDXL's overflows in 16 bits) and belongs to the trainer, which goes on
    encoding images with it for the rest of the run. Decoding here casts the
    latents up instead, and leaves the VAE alone.

    The non-finite check is here because a NaN decode is otherwise invisible:
    `(images * 255).astype("uint8")` turns every NaN into 0 and the round is
    written out as black squares with nothing in the log but a numpy warning.

    AND IT TURNS AUTOCAST OFF, which is the same sentence one level up: "in
    its own dtype" is not something casting the latents can deliver on its
    own, because an AMBIENT autocast casts every conv inside the VAE too.
    `sampling()` wraps a full finetune's whole sample block — the denoising
    needs it, the decode must not have it — and this VAE is deliberately
    fp32 precisely because SDXL's overflows in sixteen bits. Without this
    line a full SDXL finetune rendered a round of flat GREY squares: the
    decode ran in bf16, and the check above only catches non-finite values,
    not a picture quietly turned to mush.
    """
    import torch

    vae_dtype = next(vae.parameters()).dtype
    lat = latents.to(dtype=vae_dtype)
    # Mirrors diffusers' own unscaling (VAEs that publish latent statistics
    # use them; the rest just divide by the scaling factor).
    mean = getattr(vae.config, "latents_mean", None)
    std = getattr(vae.config, "latents_std", None)
    shift = float(getattr(vae.config, "shift_factor", 0.0) or 0.0)
    if mean is not None and std is not None:
        mean_t = torch.tensor(mean).view(1, 4, 1, 1).to(lat.device, lat.dtype)
        std_t = torch.tensor(std).view(1, 4, 1, 1).to(lat.device, lat.dtype)
        lat = lat * std_t / vae.config.scaling_factor + mean_t + shift
    else:
        # Mirror of `encode_image`: undo the scale, then put the shift back.
        lat = lat / vae.config.scaling_factor + shift
    with torch.no_grad(), torch.autocast(
            device_type=str(lat.device).split(":")[0], enabled=False):
        # One image at a time even when the group holds several: decoding is
        # the last step before an image exists, so this is what lets a batched
        # round appear image by image instead of all at once — and it keeps a
        # 1024² batch from allocating every decode at the same moment.
        image = torch.cat([vae.decode(lat[i:i + 1], return_dict=False)[0]
                           for i in range(lat.shape[0])])
    if not torch.isfinite(image).all():
        # Silent black images are the worst possible failure here: the run
        # looks healthy and every sample is a black square. Say it once.
        print("warning: the VAE decoded non-finite values — samples for this "
              "round will be black", flush=True)
        image = torch.nan_to_num(image)
    return pipe.image_processor.postprocess(image.detach().float(),
                                            output_type="pil")



# Names differ between architectures, so the kind is a hint for colour only —
# anything unrecognised is drawn as a plain block rather than guessed at.
def _block_kind(name: str) -> str:
    n = name.lower()
    if "down" in n or "encoder" in n:
        return "down"
    if "up" in n or "decoder" in n:
        return "up"
    if "mid" in n:
        return "mid"
    if "block" in n:
        return "stack"
    if "embed" in n or "time" in n or "pos" in n:
        return "embed"
    return "other"


def _is_stack(name: str, module) -> bool:
    """Whether a child is a repeated stack of identical blocks (its length is
    then worth showing) rather than one thing."""
    kids = list(module.children())
    if len(kids) < 2:
        return False
    kinds = {type(k).__name__ for k in kids}
    return len(kinds) <= 2 and ("block" in name.lower() or "layers" in name.lower())


def _check_bitsandbytes(device, mode: str) -> None:
    """Refuse up front when bitsandbytes cannot actually run on this GPU.

    ROCm reads as "cuda", so the device gate above passes on AMD — where the
    stock bitsandbytes wheel may be a CUDA-only build that imports fine and
    dies deep inside ``from_pretrained`` with a loader trace naming nothing.
    One tiny quantize now turns that into a sentence. Runs on NVIDIA too:
    microseconds, and a broken install fails the same honest way there."""
    import torch
    try:
        import bitsandbytes as bnb
        bnb.functional.quantize_4bit(torch.zeros(4096, 1, device=device))
    except ImportError as exc:
        raise RuntimeError(
            f"{mode} quantization needs bitsandbytes, which is not installed "
            "in the training environment — re-run the training setup, or "
            "turn quantization off.") from exc
    except Exception as exc:  # noqa: BLE001 - CUDA-only build on ROCm, etc.
        raise RuntimeError(
            f"{mode} quantization needs bitsandbytes, and the installed "
            f"build cannot run on this GPU ({exc}). Turn quantization "
            "off.") from exc


def _across(obj, device):
    """``obj`` with every tensor in it moved to ``device``, shape preserved.

    A text encoder returns a tensor, a tuple, or a transformers ``ModelOutput``
    — which is an OrderedDict subclass that engines index as ``[0]`` — so the
    move has to keep the CONTAINER as well as its contents: rebuilding a
    ModelOutput as a dict would break every ``[0]``, and returning it
    untouched would leave CPU tensors in a GPU graph.
    """
    import torch

    if isinstance(obj, torch.Tensor):
        return obj.to(device)
    if isinstance(obj, (list, tuple)):
        moved = [_across(x, device) for x in obj]
        return type(obj)(moved) if not isinstance(obj, tuple) else tuple(moved)
    if isinstance(obj, dict):
        # In PLACE, which is what keeps a ModelOutput a ModelOutput. Its
        # __setitem__ updates the attribute too, so `.last_hidden_state` and
        # `[0]` stay the same object.
        for k, v in list(obj.items()):
            obj[k] = _across(v, device)
        return obj
    return obj


class _CpuEncoder:
    """A frozen text encoder that lives on the CPU and is called from the GPU.

    See `BaseEngine.offload_text_encoders`. NOT an ``nn.Module``: wrapping one
    would register the inner encoder as a submodule, and then any later
    ``.to(device)`` on the engine's module graph would quietly haul 16 GB back
    onto the card — undoing the offload with nothing to show for it. Plain
    delegation keeps it where it was put.
    """

    def __init__(self, inner, out_device):
        self.inner = inner
        self.out_device = out_device

    def __call__(self, *args, **kwargs):
        import torch

        with torch.no_grad():
            out = self.inner(*_across(list(args), "cpu"),
                             **_across(dict(kwargs), "cpu"))
        return _across(out, self.out_device)

    def to(self, *args, **kwargs):
        """Refuse to be moved, and say nothing about it.

        The point of the offload is that these weights are NOT on the card,
        and a pipeline or an engine that later places its components would
        otherwise haul 16 GB back with one `.to(device)` — leaving the run
        exactly as it was before the setting, with nothing to show that the
        setting did anything. A dtype-only `.to(torch.bfloat16)` is still
        honoured, because that is not a move.
        """
        import torch

        keep = [a for a in args if isinstance(a, torch.dtype)]
        if "dtype" in kwargs:
            keep.append(kwargs["dtype"])
        if keep:
            self.inner.to(*keep)
        return self

    @property
    def device(self):
        """Where the WEIGHTS are. A pipeline helper that builds its ids on
        this puts them on the CPU, which is where they are wanted anyway —
        the proxy would have moved them there itself."""
        return next(self.inner.parameters()).device

    # Everything else — `.parameters()`, `.config`, `.dtype`, `.gradient_
    # checkpointing_enable()` — belongs to the encoder underneath.
    def __getattr__(self, name):
        return getattr(self.inner, name)


class BaseEngine:
    #: Pixels per latent cell, i.e. how much of the image one cell of what
    #: `encode_image` returns covers. 8 for every VAE here; FLUX.2 is 16,
    #: because its engine patchifies 2x2 into channels before the cache sees
    #: it. The loop uses this wherever it converts between pixels and latent
    #: cells — rounding a cover size, and taking a crop window out of a
    #: cached latent — so an engine that gets it wrong crops the wrong
    #: rectangle rather than failing loudly.
    latent_scale = 8

    #: The multiple every image handed to `encode_image` has to be, in pixels.
    #: `latent_scale` wherever the VAE is the only thing that downsamples, and
    #: TWICE it wherever something patchifies 2x2 on top of it — which is
    #: every DiT here except FLUX.2, whose engine folds that patchify into
    #: `latent_scale` and so needs nothing extra.
    #:
    #: It exists because REFERENCE pictures are sized by this code rather than
    #: by a bucket: `load_refs` rounds each one to its own aspect, and rounding
    #: to `latent_scale` produced an 88x48 reference for a model that patchifies
    #: — an odd latent dimension, which fails inside a reshape several frames
    #: down with nothing but a shape in the message.
    image_step = 0

    #: The pipeline component holding the frozen base weights — what
    #: quantization applies to, and the only one it applies to (see
    #: `_quant_config`). "unet" for the UNet models, "transformer" for the
    #: DiT ones. It is the pipeline's OWN name for the component, not the
    #: engine's attribute, because it is used as a `quant_mapping` key that
    #: diffusers resolves against `model_index.json`.
    backbone_component = "unet"

    #: The pipeline's own names for the text encoder(s) — what
    #: `quantize_text_encoder` applies to, and the same kind of `quant_mapping`
    #: key `backbone_component` is. Most models have one; SDXL and FLUX.1 have
    #: two, and BOTH have to be named or the pair is half quantized and the
    #: estimate is wrong by whichever half was missed.
    #:
    #: DERIVED from what the engine takes off the pipeline, and
    #: `tests/train/test_training.py` checks it against exactly that — a list
    #: kept by hand would silently go stale the first time an engine gained an
    #: encoder.
    text_encoder_components: tuple[str, ...] = ("text_encoder",)

    #: WHICH of those an adapter may be laid over when `train_text_encoder`
    #: is on — the base `trained_text_encoders` reads these off `self` by
    #: name. Empty means the engine trains no encoder (FLUX.2, Z-Image,
    #: Qwen-Image: a language model as the conditioning, left alone). SD and
    #: SDXL predate this and override `trained_text_encoders` directly.
    trainable_text_encoders: tuple[str, ...] = ()
    #: The LARGE sequence encoder(s) among them — the T5-XXL of FLUX.1 and
    #: Chroma, ~4.8B parameters against CLIP-L's 0.12B. `hyper.
    #: train_text_encoder_large` (default on) says whether they train too;
    #: off, only the small pooled encoder(s) do, which is what most FLUX
    #: LoRA tooling means by training the text encoder and costs a fraction
    #: of a gigabyte where T5 costs several.
    large_text_encoders: tuple[str, ...] = ()
    #: Per component, the module names its adapter attaches to. A component
    #: not named here takes the CLIP set (`TE_LORA_TARGETS`).
    text_encoder_targets: dict[str, tuple[str, ...]] = {}
    #: Which trained encoders the PORTABLE file (diffusers' own layout) can
    #: carry. diffusers names one text-encoder slot per pipeline loader —
    #: `text_encoder` (and `text_encoder_2` for SDXL) — and an encoder outside
    #: that list stays in the trainer's own file, which the Evaluate tab still
    #: reads (`generate._attach_parts`). FLUX.1's T5-XXL is the case: its
    #: loader has a slot for the CLIP adapter and none for T5.
    portable_text_encoders: tuple[str, ...] = ("text_encoder",)

    #: The module NAMES inside the backbone that an adapter attaches to — the
    #: attention projections this architecture exposes. The UNet pair is the
    #: default; the DiT engines override it (a joint-stream transformer adds
    #: the `add_*` projections that carry the text side).
    #:
    #: It is a class attribute rather than a module-level constant each engine
    #: reads for itself because `attach_adapter` is now shared: the one thing
    #: an engine still has to say about its adapter is this list.
    adapter_targets: tuple[str, ...] = tuple(UNET_LORA_TARGETS)

    #: Whether this model is a FLOW-MATCHING one (Chroma, the FLUX family,
    #: Z-Image, Qwen-Image) rather than an epsilon-prediction one (SD, SDXL).
    #:
    #: Declared rather than sniffed because the two families differ in which
    #: noise levels they train on by DEFAULT — evenly for the older ones, and
    #: centred on the middle for these — and `timesteps.resolve` needs to know
    #: which "the model's own" means. Every other difference between them is
    #: already expressed by the engine simply doing something else.
    flow_matching = False

    def __init__(self, config: dict, minfo: dict, device: str, dtype):
        self.config = config
        self.hyper = config.get("hyper", {})
        self.model_params = config.get("model_params", {})
        self.minfo = minfo
        self.repo = minfo.get("repo", "")
        self.local = bool(minfo.get("local"))
        self.device = device
        self.dtype = dtype
        self.method = config.get("method", "lora")
        self.train_te = bool(self.hyper.get("train_text_encoder"))
        # A config written before the switch existed has no key; True is what
        # "train the text encoder" meant everywhere else, and no such config
        # had the switch on for a model with a large encoder — those refused
        # the toggle outright.
        self.train_te_large = bool(
            self.hyper.get("train_text_encoder_large", True))
        self.vae = None
        # Prompt prefetching for a CPU-side encoder — see `prefetch_prompts`.
        # The engine's own `_encode_prompts` is kept under a second name
        # and the instance answers through the cache first; an engine
        # without one (none today) simply has nothing to wrap.
        self._cpu_encoders: list[str] = []
        self._prompt_cache: dict = {}
        self._prompt_pool = None
        raw = getattr(type(self), "_encode_prompts", None)
        if raw is not None:
            self._encode_prompts_now = raw.__get__(self)
            self._encode_prompts = self._encode_prompts_ahead

    # -- helpers ----------------------------------------------------------

    def autocast(self):
        """Mixed precision for the backbone's forward: fp32 master weights,
        `self.dtype` compute.

        A LoRA run does not need it — the frozen base already IS `self.dtype`
        and only the small adapter is upcast. **PEFT DOES NOT DO THAT UPCAST
        FOR US, whatever this docstring used to say**: `autocast_adapter_dtype`
        lives on the `PeftModel` paths (`get_peft_model`, `load_adapter`), and
        `_attach_lora` goes through diffusers' `add_adapter`, which calls
        `inject_adapter_in_model` — that never reaches `cast_adapter_dtype`.
        Attached to a bf16 model the adapter comes back bf16. What upcasts it
        is the explicit `p.requires_grad -> p.data.float()` loop each engine's
        own `load()` runs AFTER the attach, and those seven four-line blocks
        are load-bearing rather than belt-and-braces: measured on a real LoRA
        at this repo's default lr of 1e-4, an AdamW step is about lr in size
        while one bf16 ulp at a gaussian-init |w| of 0.05 is 1.2e-4, so the
        update lands below the resolution of the weight it is applied to.
        Left in bf16, 87% of per-element steps changed nothing, 55% of
        `lora_A` never moved at all, and 2500 steps reached 14% of the fp32
        arm's progress — with an ordinary-looking loss curve and nothing in
        the log to say so. The cosine schedule makes it worse at the tail,
        where lr falls to where NO step lands. diffusers ships the same
        operation as `training_utils.cast_training_params`, which is what its
        official LoRA scripts call after `add_adapter`.

        A FULL finetune does need the autocast: every parameter is trainable,
        so the fp32 upcast in `load()` takes the whole backbone with it, and a
        forward that casts its inputs to bf16 then dies with "expected mat1
        and mat2 to have the same dtype, but got: struct c10::BFloat16 !=
        float".

        Training the backbone in plain bf16 instead would avoid that and is
        the wrong trade: bf16 carries about three decimal digits, so the small
        updates a long finetune is made of round away against a weight of
        order 1. fp32 master weights with bf16 matmuls is the standard recipe
        and costs only the weights themselves.

        A no-op at fp32, and on any device without autocast support.
        """
        import contextlib

        import torch

        if self.dtype == torch.float32:
            return contextlib.nullcontext()
        device_type = str(self.device).split(":")[0]
        try:
            return torch.autocast(device_type=device_type, dtype=self.dtype)
        except (RuntimeError, ValueError):  # pragma: no cover - device-dependent
            return contextlib.nullcontext()

    def _quant_config(self):
        """Quantization config for the frozen weights, or None.

        Quantizing only makes sense with LoRA (the base stays frozen, the
        adapter trains in full precision on top — QLoRA).

        **TWO BACKENDS, PICKED BY DEVICE.** bitsandbytes needs an NVIDIA GPU or
        an AMD one under ROCm and is what CUDA uses, unchanged. Everywhere else
        — which in practice means Apple silicon — int8 goes through
        `optimum-quanto`, which runs on MPS and is measured to work: FLUX.2
        Klein's transformer 7.75 -> 3.88 GB, Qwen-Image trainable at 37.5 GB
        where bf16 needs 57.7 and will not load at all. nf4 stays
        bitsandbytes-only and still raises rather than quietly training
        unquantized at a memory budget somebody planned around.

        int4 exists in quanto and is deliberately NOT offered: `.to("mps")`
        takes ~390 s for a 3.9B backbone packing the weights (measured;
        `from_pretrained` is 2.6 s of that), it needs ninja and a C++
        toolchain, and the cost scales with parameter count.
        """
        mode = str(self.hyper.get("quantization", "none") or "none")
        backend = self._quant_backend(mode)
        if backend is None:
            return None
        try:
            from diffusers.quantizers import PipelineQuantizationConfig
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise RuntimeError(
                "This diffusers version cannot quantize a pipeline — update "
                "the training environment to use quantization.") from exc

        cuda = backend == "bitsandbytes"
        backbone_cfg = {"bitsandbytes": self._bnb_config,
                        "quanto": self._quanto_config,
                        "torchao": self._torchao_config}[backend](mode)

        # A PIPELINE takes a PipelineQuantizationConfig; a bare
        # BitsAndBytesConfig is the per-MODEL form and `from_pretrained`
        # rejects it outright ("`quantization_config` must be an instance of
        # `PipelineQuantizationConfig`"). Passing the bare one is what made
        # every int8/nf4 run fail at load — which is exactly the setting that
        # lets Chroma and FLUX.2 fit on a 16 GB card, so those two models
        # could not be trained there at all.
        mapping = {self.backbone_component: backbone_cfg}

        # THE TEXT ENCODER IS OPTIONAL AND ITS OWN SETTING, because the two
        # shrink different terms of the estimate: the backbone is `backbone_gb`
        # and the encoders are most of `aux_gb`. Folding them together would
        # make the displayed figure wrong for whichever the user did not want.
        # It is frozen exactly as the backbone is — and, exactly as with
        # the backbone, an adapter may still train OVER the quantized
        # weights (QLoRA on the encoder): PEFT lays its LoRA layers over a
        # bitsandbytes `Linear8bitLt`/`Linear4bit`, a torchao int8 Linear
        # and quanto's `QLinear` (a `torch.nn.Linear` subclass, so the
        # default dispatch takes it), and every one of those passes a
        # gradient to its input, which is all a frozen layer between two
        # adapters has to do. That is what lets T5-XXL train on a 32 GB card.
        if self.hyper.get("quantize_text_encoder"):
            for name in self.text_encoder_components:
                mapping[name] = self._text_encoder_quant_config(mode, backend)
        return PipelineQuantizationConfig(quant_mapping=mapping)

    def _quant_backend(self, mode: str) -> str | None:
        """`"bitsandbytes"` | `"quanto"` | `"torchao"` | None — which library,
        or nothing.

        PURE, and imports nothing, so the rules can be tested from the
        torch-free venv the app's own tests run in. None means "no quantized
        load": either it was not asked for, or fp8 handles it later in
        `apply_fp8`, which converts weights in place rather than at load.
        """
        if mode == "none":
            return None
        if self.method != "lora":
            raise RuntimeError(
                "Quantization only applies to LoRA training — the base weights "
                "must stay frozen. Switch the method to LoRA or turn it off.")
        if mode == "fp8":
            return None   # not a load-time scheme; see `apply_fp8`
        if str(self.device).startswith("cuda"):
            # INT8 IS QUANTO ON CUDA TOO, and nf4 stays bitsandbytes. Measured
            # on an RTX 5090, Chroma at 512 px, batch 1, checkpointing on:
            #
            #   bf16 (no quantization)     0.524 s/step   peak 28.7 GB
            #   nf4, bitsandbytes          0.561          peak 16.0
            #   int8, quanto               0.611          peak 19.9
            #   int8, bitsandbytes         0.774          peak 29.4
            #   int8, bitsandbytes, no outlier decomposition
            #                              0.555          peak 29.3
            #
            # bitsandbytes' int8 SAVES NOTHING: its weights are 9 GB against
            # the bf16 18, and the run peaks HIGHER than bf16. `MatMul8bitLt`
            # keeps what its backward needs as plain attributes on the
            # autograd context (`ctx.tensors`) rather than through
            # `save_for_backward`, so gradient checkpointing — which drops
            # saved tensors through a hook on exactly that call — cannot
            # touch them, and every one of the 433 int8 layers holds an
            # activation-sized tensor through the whole forward: ~10 GB at
            # 512 px, ~40 GB at 1024, where the same run at bf16 holds 1 GB
            # and 3. That is what "quantization RAISES the memory on CUDA"
            # was. The 4-bit path (`MatMul4Bit`) saves only its weight and
            # is fine, which the table shows. quanto's int8 is a plain
            # weight-only quantization with nothing kept per layer, and it
            # is what the non-CUDA path has always used.
            # `MEDIA_COMPOST_INT8_BACKEND=bitsandbytes` puts the old path
            # back for a comparison.
            if mode == "int8":
                forced = os.environ.get("MEDIA_COMPOST_INT8_BACKEND", "").lower()
                if forced != "bitsandbytes":
                    if self._have("diffusers", "QuantoConfig"):
                        return "quanto"
                    if self._have("diffusers", "TorchAoConfig") \
                            and self._have("torchao", "__version__"):
                        return "torchao"
            return "bitsandbytes"
        if mode != "int8":
            raise RuntimeError(
                f"{mode} quantization needs bitsandbytes, which requires an "
                f"NVIDIA or AMD (ROCm) GPU (this machine trains on "
                f"'{self.device}'). Use int8, which runs here, or turn "
                f"quantization off.")
        # QUANTO FIRST, TORCHAO AS THE SUCCESSOR — and the order is a
        # measurement, not a preference. Both give the identical saving on
        # MPS (FLUX.2 Klein's transformer 7.75 -> 3.88 GB either way, and
        # 8.48 GB resting with the text encoder in too), but quanto is
        # **24% faster a step** — 8.38 s against 10.43 s through this engine.
        #
        # torchao is here because diffusers' `QuantoConfig` is deprecated for
        # removal in 1.0 while `TorchAoConfig` is not, so the day that lands
        # this keeps working without anyone editing it. It is NOT a declared
        # dependency: merely importable, torchao adds warnings to every
        # training log, quantized or not.
        return "quanto" if self._have("diffusers", "QuantoConfig") else "torchao"

    @staticmethod
    def _have(module: str, name: str) -> bool:
        import importlib

        try:
            return hasattr(importlib.import_module(module), name)
        except ImportError:
            return False

    def _bnb_config(self, mode: str, transformers_form: bool = False):
        """The CUDA path.

        ``transformers_form`` picks the same settings out of the OTHER
        library's class — see `_text_encoder_quant_config`, which is the only
        caller that wants it.
        """
        _check_bitsandbytes(self.device, mode)
        import torch

        if transformers_form:
            from transformers import BitsAndBytesConfig
        else:
            from diffusers import BitsAndBytesConfig

        if mode == "int8":
            # LLM.int8's outlier decomposition: activation columns above
            # this magnitude leave the int8 path and multiply in fp16
            # against an fp16 slice of the weight kept per layer. 6.0 is
            # the library's default; 0 turns the decomposition off, which
            # is a memory and speed experiment (`MEDIA_COMPOST_INT8_THRESHOLD`)
            # until it is measured — see `_cast_quantized_inputs`.
            try:
                threshold = float(os.environ.get(
                    "MEDIA_COMPOST_INT8_THRESHOLD", "6.0") or 6.0)
            except ValueError:
                threshold = 6.0
            return BitsAndBytesConfig(load_in_8bit=True,
                                      llm_int8_threshold=threshold)
        return BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=(self.dtype if self.dtype != torch.float32
                                    else torch.bfloat16),
        )

    def _quanto_config(self, mode: str):
        """The preferred non-CUDA path — int8, which `_quant_backend` has
        already established is the only mode that gets here.

        The deprecation warning is SILENCED at this one call site, not
        globally: diffusers marks `QuantoConfig` for removal in 1.0, there is
        nothing the person running the job can do about it, and a warning
        printed once a run into a log they read for loss values is noise. The
        fallback in `_quant_backend` is what actually answers the deprecation.
        """
        import warnings

        try:
            from diffusers import QuantoConfig
        except ImportError as exc:
            raise RuntimeError(
                "int8 quantization on this device needs optimum-quanto — "
                "install it into the training environment "
                "(`pip install optimum-quanto`) or turn quantization off."
            ) from exc
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*QuantoConfig.*")
            return QuantoConfig(weights_dtype="int8")

    def _torchao_config(self, mode: str):
        """The successor path, used when diffusers has dropped QuantoConfig.

        Measured to give the same saving and to train cleanly on MPS, at about
        24% more time a step — which is why it is the fallback rather than the
        default. See `_quant_backend`.
        """
        try:
            from diffusers import TorchAoConfig
            from torchao.quantization import Int8WeightOnlyConfig
        except ImportError as exc:
            raise RuntimeError(
                "int8 quantization on this device needs optimum-quanto or "
                "torchao — install one into the training environment "
                "(`pip install optimum-quanto`) or turn quantization off."
            ) from exc
        return TorchAoConfig(Int8WeightOnlyConfig())

    def _text_encoder_quant_config(self, mode: str, backend: str):
        """The same scheme for a text encoder, in the form ITS library takes.

        A text encoder is a `transformers` model, and the two libraries do not
        agree on the spelling: quanto's diffusers config takes
        `weights_dtype=` while its transformers one takes `weights=`, and
        handing one to the other raises `'QuantoConfig' object has no
        attribute 'weights'`. torchao is the tidier of the two — both sides
        take the same `quant_type=`. `PipelineQuantizationConfig` accepts
        either library's config per component, which is what lets one mapping
        carry a diffusers config for the backbone and a transformers one here.

        **BITSANDBYTES IS THE SAME TRAP AND THIS SAID IT WAS NOT.** The line
        here read `return self._bnb_config(mode)  # transformers reads bnb
        configs too`, and it does not: `diffusers.BitsAndBytesConfig` and
        `transformers.BitsAndBytesConfig` are two classes in two modules, and
        transformers type-CHECKS its own — so the load died with "Found
        `quant_method=bitsandbytes` but `quantization_config` is not a
        `BitsAndBytesConfig`", a message that reads like the config is missing
        rather than imported from next door. That is every CUDA machine, for
        every model, whenever `quantize_text_encoder` is on with int8 or nf4 —
        which is exactly the pair that makes the biggest models fit a small
        card, so the setting was broken precisely where it is needed.
        Found by measuring: an nf4 sweep with `quantize_text_encoder` on runs
        this same code and could not load a single model.
        """
        import warnings

        if backend == "bitsandbytes":
            return self._bnb_config(mode, transformers_form=True)
        if backend == "torchao":
            from torchao.quantization import Int8WeightOnlyConfig
            from transformers import TorchAoConfig

            return TorchAoConfig(quant_type=Int8WeightOnlyConfig())
        from transformers import QuantoConfig as TransformersQuantoConfig

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*QuantoConfig.*")
            return TransformersQuantoConfig(weights="int8")

    def _pipeline_source(self) -> str:
        """Where the pipeline is loaded FROM — the resolved snapshot directory
        when the cache is complete, else the repo id (see `_from_pretrained`).
        Split out because `pipeline_class` needs the same answer before the
        load, to read the snapshot's own `model_index.json`."""
        return self.minfo.get("local_dir") or self.repo

    def _from_pretrained(self, pipeline_cls):
        """Load the pipeline from the HF repo, a local diffusers folder, or a
        single .safetensors checkpoint."""
        import torch  # noqa: F401

        # Imported HERE, not at module scope. `pipeline_opts` is a sibling
        # resolved off sys.path (the entry points insert the scripts dir),
        # so a top-level import breaks every caller that loads this file
        # directly — which is how the pure helpers below are unit-tested from
        # the main venv. Same reason the heavy imports are in-method.
        import pipeline_opts

        kwargs = {"torch_dtype": self.dtype}
        quant = self._quant_config()
        if quant is not None:
            kwargs["quantization_config"] = quant
        if self.local and self.repo.endswith(".safetensors"):
            return pipeline_cls.from_single_file(self.repo, **kwargs)
        # A resolved snapshot directory beats the repo id: loading by id makes
        # diffusers ask the hub what the revision holds, which with no network
        # turns into "model is not cached locally" even when every file the
        # pipeline loads is cached. Empty unless the cache is complete.
        src = self._pipeline_source()
        # Every component the DOWNLOAD skipped has to be disabled here too, or
        # diffusers builds one from model_index.json and looks for files that
        # were never fetched — see pipeline_opts.py beside this. Scoped
        # to what this pipeline actually declares, so the load does not warn
        # about kwargs the class has never heard of.
        kwargs.update(pipeline_opts.disabled_kwargs(_model_index(src)))
        if quant is None:
            # No quantized layer to hook — the encoder may still be, but
            # `quantize_text_encoder` rides the same config, so there is
            # nothing to cast when the config is None.
            return self._park_text_encoders(
                pipeline_cls.from_pretrained(src, **kwargs))
        # The QUANTIZER announces its own deprecation from inside the load,
        # where `_quanto_config` cannot reach it. Same reasoning as there: the
        # person reading this log for loss values can do nothing about
        # diffusers' 1.0 plans, and `_quant_backend` already has the answer.
        # Scoped to the quantized load, so nothing else is muffled.
        import warnings

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*Quanto.*")
            pipe = pipeline_cls.from_pretrained(src, **kwargs)
        self._cast_quantized_inputs(pipe)
        return self._park_text_encoders(pipe)

    #: The quantized Linear classes, by NAME so nothing here imports the
    #: library that defines them: bitsandbytes' two, and quanto's.
    _QUANTIZED_LINEARS = ("Linear8bitLt", "Linear4bit", "QLinear")

    def _cast_quantized_inputs(self, pipe) -> int:
        """Hand every quantized layer its input in the COMPUTE dtype.

        MEASURED, on an RTX 5090, Chroma at 512 px: the int8 run spent 31%
        of its GPU time in `cutlass_80_simt_sgemm` — a single-precision GEMM
        on the SIMT cores, which the bf16 run never touches — and peaked at
        32.7 GB where the same run at bf16 peaked at 28.7. So the int8 load
        was SLOWER and BIGGER than the weights it replaced, and the quantized
        text encoder the same.

        The mechanism: the backbone runs under `autocast()` (which the fp32
        adapter masters need — see `upcast_trainable`), and autocast keeps
        the norms in fp32, so a quantized Linear is handed fp32 activations.
        A quantized Linear is a custom autograd Function, not an autocast-
        aware op: bitsandbytes reads the INPUT's dtype as the dtype of its
        arithmetic, so the backward dequantizes each weight into an fp32
        copy and multiplies in fp32 (the `MatMul8bitLt: inputs will be cast
        from torch.float32` lines in the log say it at every layer), and
        the saved fp32 activations are twice the size the bf16 run keeps.
        `Linear4bit` dequantizes `.to(A.dtype)` for the same reason.

        One forward pre-hook per quantized module casts floating inputs to
        `self.dtype` — the dtype every plain Linear in the same forward
        already sees, so nothing about the maths changes except that it runs
        on the tensor cores in the precision the run asked for. Installed on
        the whole pipeline, so a quantized encoder gets it too.
        """
        import torch

        dtype = self.dtype
        if dtype == torch.float32:
            return 0

        def cast(_module, args):
            return tuple(a.to(dtype) if torch.is_tensor(a)
                         and a.is_floating_point() and a.dtype != dtype else a
                         for a in args)

        n = 0
        for name in getattr(pipe, "components", {}) or {}:
            comp = getattr(pipe, name, None)
            if not isinstance(comp, torch.nn.Module):
                continue
            for m in comp.modules():
                if type(m).__name__ in self._QUANTIZED_LINEARS:
                    m.register_forward_pre_hook(cast)
                    n += 1
        if n:
            print(f"quantized layers take {str(dtype).split('.')[-1]} inputs "
                  f"({n} layers)", flush=True)
        return n

    def _park_text_encoders(self, pipe):
        """Wrap the encoders BEFORE anything places them on the device.

        `from_pretrained` returns a pipeline on the CPU, and each engine then
        moves its components across. Wrapping here — rather than after
        `load()` — means the encoder is never moved at all, because the
        proxy's `to()` ignores a device: the engine's own
        `self.text_encoder.to(self.device)` becomes a no-op it does not have
        to know about.

        DOING IT AFTERWARDS IS TOO LATE FOR THE MODELS THAT NEED IT. Measured:
        Chroma at nf4 rests at ~6 GB with its T5-XXL parked, which fits this
        card easily — but loading it first put 6 GB of backbone and 9.7 GB of
        encoder on the GPU at once and died there, before any offload could
        run. The peak that matters is the load's, not the step's.
        """
        if not self.hyper.get("offload_text_encoder") \
                or self.hyper.get("train_text_encoder"):
            return pipe
        for name in self.text_encoder_components:
            te = getattr(pipe, name, None)
            if te is None or isinstance(te, _CpuEncoder):
                continue
            try:
                setattr(pipe, name, _CpuEncoder(te, self.device))
            except Exception:  # noqa: BLE001 - a read-only property
                pass
        return pipe

    def attach_adapter(self) -> None:
        """Freeze the base and lay this run's adapter over it.

        ONE implementation for every engine, where there used to be seven —
        which is what makes an option like the network type or the layer
        filter a change in one place rather than seven. Each engine says only
        WHICH module names its architecture exposes (`adapter_targets`); the
        rest — the config, the filter, the seeding, the fp32 upcast — is the
        same everywhere and is here.

        It does NOT upcast: `upcast_trainable` does, and every engine calls it
        at the very end of `load()` — after the modules have been moved to the
        device, which is where that has always happened and where a full
        finetune (which attaches no adapter at all) also needs it.
        """
        import adapters

        backbone = getattr(self, self.backbone_component)
        backbone.requires_grad_(False)
        targets = adapters.layer_filter(
            backbone, self.adapter_targets, self.hyper)
        backbone.add_adapter(adapters.build_config(self.hyper, targets))
        # Gated here and not in `trained_text_encoders`, which answers "which
        # encoders COULD this engine train" — `upcast_trainable` asks it that
        # way, and a list that emptied itself when the switch was off would
        # make an untrained encoder's frozen weights look like a fourth case.
        trained = self.trained_text_encoders() if self.train_te else {}
        for name, te in trained.items():
            # The layer filter is deliberately NOT applied here: it names
            # blocks of the IMAGE backbone, and a text encoder's layers are a
            # different thing with different names — a filter written for one
            # would silently match nothing in the other, i.e. train no text
            # encoder at all while the switch said it was on.
            targets = list(self.text_encoder_targets.get(name, TE_LORA_TARGETS))
            te.add_adapter(adapters.build_config(self.hyper, targets))
            self._prepare_text_encoder(name, te)
        self._init_from_existing_adapter()

    def _prepare_text_encoder(self, name: str, te) -> None:
        """Put a trained encoder into the state its adapter needs.

        THREE THINGS, and the first two exist because of the third. A
        transformers model checkpoints its layers only in TRAIN mode
        (`if self.gradient_checkpointing and self.training`), and
        `from_pretrained` hands every component back in eval mode — which
        is how the encoders have always been trained here, deliberately: no
        dropout, so what the transformer is conditioned on is what it will
        be conditioned on at generation. T5-XXL ships `dropout_rate: 0.1`,
        so `train()` alone would start feeding it noisy prompts. Its
        dropout modules are zeroed first, which makes the two modes
        numerically identical — CLIP's are 0 already — and THEN the encoder
        goes into train mode, so checkpointing can take. `use_reentrant=
        False` is the spelling that lets a checkpointed block reach an
        adapter inside it without `enable_input_require_grads`; the
        reentrant default silently drops those gradients when the block's
        input does not itself require them, which a frozen embedding table's
        output never does.

        What it buys is the same trade the backbone makes: T5-XXL at 512
        tokens keeps several GB of activations per prompt for its backward,
        and checkpointing leaves the layer inputs plus one block of it.
        """
        import torch

        for m in te.modules():
            if isinstance(m, torch.nn.Dropout):
                m.p = 0.0
        te.train()
        if self.hyper.get("gradient_checkpointing") \
                and hasattr(te, "gradient_checkpointing_enable"):
            try:
                te.gradient_checkpointing_enable(
                    gradient_checkpointing_kwargs={"use_reentrant": False})
            except (TypeError, ValueError):  # an older transformers
                te.gradient_checkpointing_enable()
            print(f"gradient checkpointing on the {name} adapter too",
                  flush=True)

    def _te_grad(self):
        """The context to encode a prompt in: gradients while an encoder is
        still training, `no_grad` otherwise — including after `te_stop`
        has frozen it again, which is what makes the second half of such a
        run as cheap as a run that never trained one."""
        import contextlib

        import torch

        if self.train_te and any(
                p.requires_grad
                for te in self.trained_text_encoders().values()
                for p in te.parameters()):
            return contextlib.nullcontext()
        return torch.no_grad()

    def upcast_trainable(self) -> None:
        """Every TRAINED parameter becomes an fp32 master. Called at the end
        of each engine's `load()`, for both methods.

        This is not belt-and-braces. PEFT does NOT upcast an adapter attached
        through diffusers' `add_adapter` (`autocast_adapter_dtype` lives on
        the `PeftModel` paths, and this goes through `inject_adapter_in_model`
        instead), so on a bf16 base the adapter comes back bf16 — where,
        measured at this repo's default learning rate, an optimizer step is
        smaller than one bf16 ulp of the weight it applies to: 87% of
        per-element updates changed nothing, 55% of `lora_A` never moved at
        all, and 2500 steps reached 14% of the fp32 arm's progress, with an
        ordinary-looking loss curve. diffusers ships the same operation as
        `training_utils.cast_training_params`.

        For a FULL finetune it takes the whole backbone with it, which is what
        `autocast()` then exists to make a forward pass out of — UNLESS
        `hyper.bf16_masters` is on, which is the setting that says "keep them
        narrow and round the updates at random instead" and halves both the
        weights and their gradients. It is refused for a LoRA
        (`spec.py` says why: the adapter's upcast is what makes an adapter
        learn), so this can key on the flag alone.
        """
        import torch

        if self.dtype == torch.float32:
            return
        if self.hyper.get("bf16_masters"):
            return
        for module in {id(m): m for m in (
                [getattr(self, self.backbone_component)]
                + list(self.trained_text_encoders().values()))}.values():
            for p in module.parameters():
                if p.requires_grad:
                    p.data = p.data.float()

    def _init_from_existing_adapter(self) -> None:
        """Seed the fresh adapter with an existing one (``config.init_lora``),
        so a run continues from another job's result instead of from noise.

        Takes a CHECKPOINT DIRECTORY — the trainer's own weights file inside
        it is what gets read, in whichever of the two layouts it is in. It
        runs after every adapter has been attached, so it can restore a
        text-encoder adapter as readily as the backbone's, which the version
        it replaced could not: that one knew the two names `unet` and
        `text_encoder` and silently ignored everything else, so a resumed SDXL
        run lost both of its encoder adapters (they are saved as
        `text_encoder`/`text_encoder_2`) and every DiT engine's `transformer`
        was ignored outright — the seeding did nothing at all there.
        """
        raw = str(self.config.get("init_lora", "") or "").strip()
        if not raw:
            return
        import adapters

        path = Path(raw)
        # A path naming the weights FILE still works: that is what the app
        # showed as the thing to point at for as long as it was a pickle.
        if path.is_file():
            path = path.parent
        try:
            state = adapters.load_state(path)
        except (FileNotFoundError, ValueError) as exc:
            raise RuntimeError(f"Starting adapter not found: {raw} ({exc})") from exc
        modules = self.adapter_modules()
        applied = []
        for name, module in modules.items():
            if name not in state:
                continue
            try:
                self._load_lora_state(module, state[name])
            except Exception as exc:  # rank/target/kind mismatch
                meta = adapters.read_meta(path)
                was = (f" It was saved as {meta.get('network', 'lora')} rank "
                       f"{meta.get('rank')} for {meta.get('base_model')}."
                       if meta else "")
                raise RuntimeError(
                    f"Could not apply the starting adapter to {name}: {exc}."
                    f"{was} Match the network type, the rank and the layer "
                    f"targeting of the job it came from.") from exc
            applied.append(name)
        if not applied:
            raise RuntimeError(
                f"The starting adapter in {raw} has nothing this run trains: "
                f"it holds {', '.join(sorted(state)) or 'nothing'} and this "
                f"run trains {', '.join(sorted(modules))}. It was most likely "
                f"trained for a different base model.")
        print(f"initialised {', '.join(applied)} from {path}")

    def encode_image(self, img):
        """Pixel image -> scaled latent (1, c, h/8, w/8) on the device."""
        import numpy as np
        import torch

        arr = np.asarray(img, dtype=np.float32) / 127.5 - 1.0
        px = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0)
        px = px.to(self.device, dtype=self.vae.dtype)
        with torch.no_grad():
            lat = self.vae.encode(px).latent_dist.sample()
        # The FLUX-family VAEs (Chroma's included) centre their latents with a
        # `shift_factor` as well as scaling them — their decode is
        # `lat / scaling + shift`, so the encode has to subtract it. SD and
        # SDXL declare no shift, so this is a no-op there; leaving it out
        # trained Chroma against a distribution offset by 0.1159, which
        # nothing in the loss would have reported.
        shift = float(getattr(self.vae.config, "shift_factor", 0.0) or 0.0)
        return (lat - shift) * self.vae.config.scaling_factor

    @property
    def step(self) -> int:
        """`image_step`, or `latent_scale` where an engine declares none."""
        return int(self.image_step or self.latent_scale)

    def load_refs(self, refs: list[dict], budget: int) -> list:
        """One visit's REFERENCE pictures, opened and sized for the model.

        Split from `encode_refs` for the engines whose TEXT encoder is also
        shown the references — Qwen-Image-Edit's is a vision-language model
        and its prompt template holds an image token per reference — so the
        very same pixels reach both halves of the conditioning.
        """
        from PIL import Image

        import compose

        out = []
        for r in refs:
            with Image.open(r["path"]) as im:
                im = im.convert("RGB")
                w, h = compose.ref_size(im.width, im.height, budget,
                                        self.step)
                out.append(im.resize((w, h), Image.LANCZOS))
        return out

    def encode_refs(self, refs: list[dict], budget: int) -> list:
        """One visit's REFERENCE pictures as latents, in this engine's layout.

        An instruction's references are the pictures the edit was made FROM,
        and every model here conditions on them the same way: encode, pack,
        concatenate onto the noisy latent's own tokens. What differs is only
        the packing and the position ids, which is why this stops at
        `encode_image` — each engine's own, so a reference goes through
        exactly the normalisation its target does.

        They are encoded JOB-LOCALLY and never cached. The shared latent cache
        is keyed by (file number, model, bucket, flip), and a reference is
        bucketed by its own aspect at the target's budget, cropped not at all
        and flipped not at all — so "reuse" would silently be a different
        encoding of the same file. `budget` is the target's pixel count, which
        is what makes a reference cost the model about as much as the picture
        it is being asked to produce.
        """
        return [self.encode_image(im) for im in self.load_refs(refs, budget)]

    def apply_fp8(self, module) -> int:
        """Store this module's FROZEN weights as 8-bit floats.

        Not 8-bit compute: torch cannot train in fp8 without a framework like
        transformer-engine, and diffusers does not. What this does is what the
        wider ecosystem means by "fp8" for LoRA training — keep the frozen base
        weights at one byte each and upcast per matmul, halving the largest
        resident thing in the run for a cast on every forward.

        Only Linear layers whose weight is frozen: the adapter must keep
        training in full precision, so this MUST run after the LoRA is attached
        and the base is frozen. Returns how many layers were converted.

        The precision cost is real — an e4m3 round trip moves a weight by up to
        ~4% — which is why it is a memory lever, not a default.
        """
        if str(self.hyper.get("quantization", "none") or "none") != "fp8":
            return 0
        import torch
        import torch.nn.functional as F

        if self.method != "lora":
            raise RuntimeError(
                "8-bit float weights only apply to LoRA training — a full "
                "finetune updates the base weights, which cannot be stored "
                "at one byte each. Switch the method or turn it off.")
        fp8 = torch.float8_e4m3fn
        try:
            torch.zeros(1, dtype=fp8, device=self.device)
        except Exception as exc:  # noqa: BLE001 - the probe IS the answer
            raise RuntimeError(
                f"8-bit float weights are not available on '{self.device}' "
                f"({exc}). They need an NVIDIA GPU of the Ada/Hopper "
                "generation or newer — Apple silicon has no fp8 type at all. "
                "Turn base-model precision back to full."
            ) from exc

        def patched(mod):
            # Bound to the module, so the fp8 copy stays the stored one and the
            # upcast exists only for the duration of the call.
            def forward(x):
                bias = None if mod.bias is None else mod.bias.to(x.dtype)
                return F.linear(x, mod.weight.to(x.dtype), bias)
            return forward

        n = 0
        for m in module.modules():
            if not isinstance(m, torch.nn.Linear):
                continue
            w = m.weight
            if w is None or w.requires_grad or w.dtype == fp8:
                continue
            m.weight.data = w.data.to(fp8)
            m.forward = patched(m)
            n += 1
        return n

    def apply_attention_slicing(self, module) -> bool:
        """Slice attention when it is worth it, and say whether it was applied.

        Attention is the memory in a diffusion step: computed whole, it holds a
        score matrix per head for every latent position. Modern PyTorch computes
        it with fused kernels that never build that whole matrix, so the DEFAULT
        (unsliced) path is already fast and memory-efficient on both CUDA and
        MPS. Slicing walks the computation in chunks — lower peak VRAM for ~10%
        more time — which is only worth it on CUDA when a run is memory-bound and
        won't otherwise fit; there "on" is honoured. On CUDA "auto"/"off" leave
        the fast fused path in place.

        On MPS the setting is a no-op, and that is now MEASURED rather than
        precautionary. Slicing there produces NaN: run through this very engine
        at 1024 with real SDXL weights (torch 2.13 / diffusers 0.39), the loss
        is `nan` and all 1120 LoRA gradients are NaN at **batch 1 as well as
        batch 2**, against a finite 0.00076 with slicing off. It does save what
        it promises — 38.9 -> 25.1 GB peak — and the saving is worthless,
        because every step it produces is NaN. An earlier check of the isolated
        `SlicedAttnProcessor` found nothing wrong, which is why the engine test
        matters: a UNet runs attention at several resolutions with
        cross-attention and the added-conditioning path beside it, and the
        module in isolation is not that. The editor disables the control on
        Apple silicon accordingly.
        """
        mode = str(self.hyper.get("attention_slicing", "auto"))
        if self.device == "mps":
            if mode == "on":
                print("attention slicing not applied on MPS: the default fused "
                      "attention path already keeps memory low here",
                      flush=True)
            return False
        want = mode == "on"
        if not want or not hasattr(module, "set_attention_slice"):
            return False
        try:
            module.set_attention_slice(1)
            self._sliced = True
            return True
        except (NotImplementedError, ValueError):
            return False   # a backbone that cannot slice is not an error

    @contextlib.contextmanager
    def unsliced_attention(self, module):
        """Attention slicing OFF for the duration — sampling only.

        Measured on this project's SDXL engine (MPS, bf16): with
        `set_attention_slice(1)` the sampling pipeline returns NaN latents and
        every image decodes to a black square — which is exactly what the
        trainer's log showed ("invalid value encountered in cast" from
        diffusers' uint8 conversion). The same call renders normally unsliced.
        Training keeps its slicing: that is where the 28 GB → 16 GB saving
        matters, and its loss curve is unaffected — a sample is one image at a
        time, next to a resident model that already dwarfs it.
        """
        sliced = getattr(self, "_sliced", False)
        if sliced and hasattr(module, "set_attention_slice"):
            try:
                module.set_attention_slice(None)
            except (NotImplementedError, ValueError):
                sliced = False
        try:
            yield
        finally:
            if sliced:
                try:
                    module.set_attention_slice(1)
                except (NotImplementedError, ValueError):
                    pass

    @contextlib.contextmanager
    def sampling(self, backbone):
        """Everything a sample round needs around it: the VAE back on the
        device, attention slicing off, and — for a FULL finetune — the same
        autocast the training forward runs under.

        THE AUTOCAST IS THE ONE THAT WAS MISSING, and it is why a full
        finetune could not sample at all. `upcast_trainable` takes the whole
        backbone to fp32 for such a run (every parameter is trainable), while
        the text encoders stay frozen at `self.dtype` — so the pipeline builds
        its conditioning in bf16, `prepare_latents` follows `prompt_embeds`
        into bf16, and the fp32 backbone is handed both with nothing casting
        anything: `RuntimeError: mat1 and mat2 must have the same dtype, but
        got BFloat16 and Float`. `train_step` had the wrap and the sample
        round did not, and with `sampling.at_start` on that round is the
        first thing a run does — so a full finetune died before its first
        step. Reproduced against a real (tiny) UNet at
        `tests/train/test_engine_math.py`.
        NOT for a LoRA run, where the backbone already IS `self.dtype` and the
        only fp32 weights are the adapter's. Autocast there would compute the
        adapter delta in bf16 where PEFT's own forward upcasts the activation
        to fp32 for it — a real, if small, change to every sample image ever
        rendered, in exchange for nothing.

        The three used to be spelled out at each engine's own call site, which
        is seven copies of one list and seven chances to leave one out — as
        this is a note about exactly that.
        """
        with contextlib.ExitStack() as stack:
            stack.enter_context(self.vae_for_sampling())
            stack.enter_context(self.unsliced_attention(backbone))
            # …and not with `bf16_masters` on: the backbone is already
            # `self.dtype` there, so this is a LoRA-shaped run as far as
            # dtypes go and the wrap would only cast the (absent) fp32
            # weights it exists for.
            if self.method != "lora" and not self.hyper.get("bf16_masters"):
                stack.enter_context(self.autocast())
            yield

    @contextlib.contextmanager
    def vae_for_sampling(self):
        """Decode with the VAE on the compute device, then put it back.

        `after_latent_cache` parks the VAE on the CPU once the latents are
        cached — it is only needed for samples after that. Sampling used to
        move it to the GPU and leave it there, quietly undoing that saving for
        the rest of the run. Nothing is copied either way: the sampling
        pipeline wraps the very modules being trained, so a sample always
        reflects the current weights and costs no second set of them.
        """
        import torch

        if self.vae is None:
            yield
            return
        try:
            was = next(self.vae.parameters()).device
        except StopIteration:      # no parameters — nothing to move
            was = torch.device(self.device)
        self.vae.to(self.device)
        try:
            yield
        finally:
            if was.type != torch.device(self.device).type:
                self.vae.to(was)

    def after_latent_cache(self, cached: bool) -> None:
        # With every latent cached the VAE is only needed again for samples;
        # keep it on CPU to free VRAM.
        if cached and self.vae is not None:
            self.vae.to("cpu")

    def offload_text_encoders(self) -> list[str]:
        """Park the FROZEN text encoder(s) on the CPU and encode there.

        The encoders are most of `aux_gb` — 16.8 GB of Qwen-Image's 57.7,
        9.9 of FLUX.1's 33.7 — and a frozen one is read once per step to turn
        a caption into an embedding. Nothing about that has to happen on the
        GPU. This is the same trade `after_latent_cache` already makes for the
        VAE, which is parked the moment every latent is cached; the encoder
        could not be, because a prompt is composed fresh per visit (tags are
        shuffled, captions dropped out) and so cannot be cached per item.

        WHY A WRAPPER AND NOT A MOVE. Every engine builds its ids on
        `self.device` and calls `self.text_encoder(ids, ...)`, so a module
        merely moved to CPU raises a device mismatch in six different
        engine-specific encode helpers. The proxy moves whatever it is handed
        down to the CPU and whatever comes back up to the compute device, so
        no engine changes at all — and a new engine gets it without knowing
        it exists.

        Returns the component names it moved, so a caller can say so.
        """
        import torch

        if not self.hyper.get("offload_text_encoder"):
            return []
        # Training the encoder means gradients through it and an optimizer
        # over its parameters; doing that on the CPU is not an offload, it is
        # a different (and far slower) run. `TrainingConfig._check` refuses
        # the pair, so this is the backstop rather than the rule.
        if self.hyper.get("train_text_encoder"):
            return []

        # BOTH SPELLINGS, because neither alone finds every engine's encoders.
        # SD/SDXL override `_text_encoders()` and keep a LIST with no
        # `text_encoder` attribute at all; Chroma, FLUX and Z-Image set the
        # named attributes and leave the base `_text_encoders()` returning [].
        # Asking one way reports "nothing offloaded" for whichever half it is
        # not — the parking itself is unaffected, since that happens on the
        # pipeline before the engine takes its references, but a report that
        # says nothing happened is how a working setting looks broken.
        already = [te for te in self._text_encoders()
                   if isinstance(te, _CpuEncoder)]
        seen = {id(te) for te in already}
        for name in self.text_encoder_components:
            te = getattr(self, name, None)
            if isinstance(te, _CpuEncoder) and id(te) not in seen:
                already.append(te)
                seen.add(id(te))
        moved: list[str] = [f"{len(already)} encoder(s)"] if already else []
        for name in self.text_encoder_components:
            te = getattr(self, name, None)
            if te is None or isinstance(te, _CpuEncoder):
                continue
            te.to("cpu")
            proxy = _CpuEncoder(te, self.device)
            setattr(self, name, proxy)
            # AND ON THE PIPELINE, which is not belt and braces. Half the
            # engines encode through the pipeline's own helper —
            # `self.pipe.encode_prompt(...)` in flux2 and zimage — so a proxy
            # installed only on the engine is bypassed, and the raw module,
            # now on the CPU, meets ids the pipeline built on the GPU:
            # "Expected all tensors to be on the same device", raised from
            # inside `torch.embedding`.
            if getattr(self, "pipe", None) is not None:
                try:
                    setattr(self.pipe, name, proxy)
                except Exception:  # noqa: BLE001 - a read-only property
                    pass
            moved.append(name)
        if moved and torch.cuda.is_available():
            torch.cuda.empty_cache()
        self._cpu_encoders = list(moved)
        return moved

    def prefetches_prompts(self) -> bool:
        """Whether `prefetch_prompts` does anything — it does exactly when
        an encoder is on the CPU, the one case where encoding a prompt is
        time the card spends idle."""
        return bool(self._cpu_encoders)

    def prefetch_prompts(self, captions: list[str]) -> None:
        """Encode the NEXT micro-batch's prompts on the CPU, in a thread,
        while the card is busy with this one.

        An offloaded encoder turns every prompt into a CPU forward that the
        loop waits for with the card idle — measured at 1.3 s a step for
        T5-XXL at 512 tokens on a 16-core desktop, against 0.3 s for the
        same pass on the card. The loop hands the next micro-batch's
        captions in here before it queues this one's forward; the
        encoder runs on a worker thread (torch releases the GIL inside its
        kernels, and the proxy already moves the answer to the device),
        and `_encode_prompts_ahead` collects the result when the engine's
        own `train_step` asks for those exact captions. A miss — an
        instruction run's per-layout split, a caption list the loop never
        announced — falls through to the ordinary synchronous path, so
        the cache can only ever save time. One worker: the CPU forward
        is memory-bound and two of them would share the same bandwidth.
        """
        if not self._cpu_encoders or not hasattr(self, "_encode_prompts_now"):
            return
        key = tuple(captions)
        if key in self._prompt_cache:
            return
        if self._prompt_pool is None:
            from concurrent.futures import ThreadPoolExecutor

            self._prompt_pool = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="prompt-prefetch")
        self._prompt_cache[key] = self._prompt_pool.submit(
            self._encode_prompts_now, list(captions))

    def _encode_prompts_ahead(self, captions, *args, **kwargs):
        """What `self._encode_prompts` resolves to: the prefetched answer
        for exactly these captions when there is one, else the engine's
        own encode, run here and now."""
        if args or kwargs or not self._cpu_encoders:
            return self._encode_prompts_now(captions, *args, **kwargs)
        fut = self._prompt_cache.pop(tuple(captions), None)
        if fut is not None:
            return fut.result()
        return self._encode_prompts_now(captions)

    def stop_text_encoder_training(self) -> None:
        for te in self._text_encoders():
            for p in te.parameters():
                p.requires_grad_(False)
            # Back to eval, which with its dropout zeroed changes nothing the
            # numbers can see — it only stops a checkpointed encoder
            # recomputing blocks for a backward pass that no longer reaches it.
            te.eval()

    # -- epsilon-prediction loss (SD family) --------------------------------

    def _diffusion_loss(self, model_pred, noise, latents, timesteps, weights,
                        masks=None):
        """Weighted MSE against the scheduler's target, with optional Min-SNR
        rebalancing (model_params.min_snr_gamma) and optional per-cell masking
        (``masks``: a (b, 1, h, w) weight map from the alpha channel)."""
        import torch
        import torch.nn.functional as F

        sched = self.noise_scheduler
        if sched.config.prediction_type == "v_prediction":
            target = sched.get_velocity(latents, noise, timesteps)
        else:
            target = noise
        loss = F.mse_loss(model_pred.float(), target.float(), reduction="none")
        loss = masked_mean(loss, masks)                  # per-sample

        gamma = float(self.model_params.get("min_snr_gamma", 0) or 0)
        if gamma > 0:
            snr = _snr(sched, timesteps)
            w = torch.clamp(snr, max=gamma) / (snr + 1e-8)
            if sched.config.prediction_type == "v_prediction":
                w = w + 1.0
            loss = loss * w
        wt = torch.tensor(weights, device=loss.device, dtype=loss.dtype)
        return (loss * wt).mean()

    # -- which noise levels to train on -------------------------------------

    def noise_cfg(self) -> dict:
        return self.config.get("noise") or {}

    def timestep_strategy(self) -> str:
        return str(self.noise_cfg().get("timesteps", "default") or "default")

    def logit_mean(self) -> float:
        return float(self.noise_cfg().get("logit_mean", 0.0) or 0.0)

    def logit_std(self) -> float:
        return float(self.noise_cfg().get("logit_std", 1.0) or 1.0)

    def noise_summary(self) -> str:
        """One line for the log saying which noise levels this run trains on.

        Printed because the setting is invisible in every other way: two runs
        that differ only here produce the same loss curve and the same
        everything, and differ in what the model ends up good at.
        """
        import timesteps

        return timesteps.describe(
            self.timestep_strategy(), self.flow_matching,
            self.logit_mean(), self.logit_std(),
            float(self.model_params.get("flow_shift", 3.0) or 3.0)
            if self.flow_matching else 1.0)

    def flow_position(self, b: int, device):
        """A batch of flow positions in [0, 1) — 0 clean, 1 pure noise.

        The five flow-matching engines drew this with four identical lines
        each; it is one line each now, and `timesteps.py` is where the choice
        of which noise levels to train on lives.

        The resolution shift stays a MODEL parameter (`flow_shift`), because
        how far to lean towards composition depends on how big the pictures
        are, which is a property of the model's own native size.
        """
        import timesteps

        shift = float(self.model_params.get("flow_shift", 3.0) or 3.0)
        mean, std = self.logit_mean(), self.logit_std()
        strategy = self.timestep_strategy()
        if timesteps.is_family_default(strategy, True, mean, std):
            # BIT-IDENTICAL to what this always did. `torch.randn` on the
            # device with no generator is exactly the call the five engines
            # made, so an untouched job keeps its random stream and not merely
            # its distribution.
            import torch

            u = torch.sigmoid(torch.randn(b, device=device))
            return timesteps.apply_shift(u, shift)
        return timesteps.draw(strategy, b, flow=True, device=device,
                              mean=mean, std=std, shift=shift)

    def _add_noise(self, latents, rng: random.Random):
        import torch

        import timesteps

        sched = self.noise_scheduler
        b = latents.shape[0]
        total = sched.config.num_train_timesteps
        noise = torch.randn_like(latents)
        offset = float(self.model_params.get("noise_offset", 0) or 0)
        if offset:
            noise = noise + offset * torch.randn(
                (b, latents.shape[1], 1, 1), device=latents.device,
                dtype=latents.dtype,
            )
        strategy = self.timestep_strategy()
        mean, std = self.logit_mean(), self.logit_std()
        if timesteps.is_family_default(strategy, False, mean, std):
            # Again bit-identical: the same `randint` on the same generator.
            steps = torch.randint(
                0, total, (b,),
                device=latents.device,
                generator=torch.Generator(latents.device.type).manual_seed(
                    rng.getrandbits(31)
                ) if latents.device.type != "mps" else None,
            ).long()
        else:
            # A position in [0, 1) scaled into the scheduler's own discrete
            # range. `clamp` because 1.0 is not a valid index — the position
            # is half-open at 1 but floating point does not promise that after
            # a shift.
            pos = timesteps.draw(strategy, b, flow=False,
                                 device=latents.device, mean=mean, std=std)
            steps = (pos * total).long().clamp(0, total - 1)
        noisy = sched.add_noise(latents, noise, steps)
        return noisy, noise, steps

    # -- checkpoints ---------------------------------------------------------

    def _lora_state(self, model):
        from peft.utils import get_peft_model_state_dict

        return get_peft_model_state_dict(model)

    def _load_lora_state(self, model, state) -> None:
        from peft.utils import set_peft_model_state_dict

        set_peft_model_state_dict(model, state)

    def trained_text_encoders(self) -> dict:
        """The text encoders carrying an adapter, by PIPELINE COMPONENT name.

        Read off `trainable_text_encoders`, less the large ones when
        `train_text_encoder_large` is off — so empty for every engine that
        declares none (FLUX.2, Z-Image, Qwen-Image). SD and SDXL override it.

        The names matter: they are what a saved checkpoint is keyed by, and
        the portable file's own prefixes. SDXL used to write `te1`/`te2` here
        while SD wrote `text_encoder`, so two engines named one thing two ways

        REFUSES, rather than quietly training nothing, when the switch leaves
        no encoder: Chroma's T5 is its only one, so "train the text encoder"
        with the large one left out is a contradiction the editor never
        offers (it hides the switch where there is no small encoder beside)
        and a script can still write.
        """
        names = [n for n in self.trainable_text_encoders
                 if self.train_te_large or n not in self.large_text_encoders]
        if self.trainable_text_encoders and not names and self.train_te:
            raise RuntimeError(
                "train_text_encoder is on with the large encoder left out, "
                "and this model has no other text encoder to train — turn "
                "train_text_encoder_large back on, or train_text_encoder off.")
        return {n: getattr(self, n) for n in names
                if getattr(self, n, None) is not None}

    def portable_parts(self) -> list[str]:
        """The parts the PORTABLE file carries — the backbone, plus the
        trained encoders diffusers' loader for this pipeline has a slot for.
        Written into the checkpoint's metadata so the Evaluate tab knows
        which parts it must attach from the trainer's own file instead."""
        parts = [self.backbone_component]
        if self.method == "lora" and self.train_te:
            parts += [n for n in self.trained_text_encoders()
                      if n in self.portable_text_encoders]
        return parts

    def adapter_modules(self) -> dict:
        """Every module this run trains an adapter on, by component name.

        ONE definition, used by saving, by loading and by the EMA — so a
        component can never be saved and then not restored, which is the shape
        the per-engine copies of this made easy to get wrong.
        """
        parts = {self.backbone_component: getattr(self, self.backbone_component)}
        if self.method == "lora" and self.train_te:
            parts.update(self.trained_text_encoders())
        return parts

    def adapter_state(self) -> dict:
        return {name: self._lora_state(module)
                for name, module in self.adapter_modules().items()}

    def adapter_meta(self) -> dict:
        """What this adapter IS, written beside its weights.

        A checkpoint outlives the settings that produced it — a job's config
        can be edited, and a file can be handed to somebody else — so the
        facts needed to make sense of it travel with it.
        """
        return {
            "network": str(self.hyper.get("network", "lora") or "lora"),
            "rank": int(self.hyper.get("rank", 16)),
            "alpha": float(self.hyper.get("alpha", 16)),
            # Needed to RE-ATTACH a LoKr (`adapters.rebuild_config`), which is
            # how the Evaluate tab loads one: get it wrong and the factors
            # come out a different shape. Harmless for a LoRA, which ignores
            # it. The layers are not recorded — they are read back off the
            # weights, which cannot disagree with themselves.
            "factor": int(self.hyper.get("lokr_factor", -1) or -1),
            "base_model": str(self.minfo.get("key") or ""),
            "engine": str(self.minfo.get("engine") or ""),
            "parts": sorted(self.adapter_modules()),
            # …and which of those the portable file holds. Whatever is NOT
            # in this list (FLUX.1's T5-XXL adapter) lives only in the
            # trainer's own file, and a loader reading the portable one
            # has to come back for it — `generate._attach_parts`.
            "portable_parts": sorted(self.portable_parts()),
        }

    # -- saving -------------------------------------------------------------
    #
    # Three verbs, and the split is what a reader needs rather than what a
    # caller asks for: `save_full` writes a finetuned model, `save_portable`
    # writes the adapter in the layout OTHER tools read, and `save_weights`
    # (a checkpoint) writes whichever applies plus the trainer's own copy.
    # Engines supply the first two; the rest is one implementation here.

    def save_portable(self, out: Path) -> None:
        """The adapter in diffusers' own layout — the file other tools load.

        The backbone's layers, plus a `<component>_lora_layers` set for
        every trained encoder in `portable_text_encoders` — the slots the
        pipeline's own `save_lora_weights` takes. SD and SDXL override it
        (they predate `pipe_cls` and name their pipeline class outright);
        the flow-matching engines take this one. An encoder OUTSIDE the
        list — FLUX.1's T5-XXL — is left out here on purpose: its loader
        has no slot to read it back into, and a file that carries keys the
        loader drops is a file that lies about what it applies.
        """
        from diffusers.utils import convert_state_dict_to_diffusers

        layers = {
            f"{self.backbone_component}_lora_layers":
                convert_state_dict_to_diffusers(
                    self._lora_state(getattr(self, self.backbone_component))),
        }
        for name in self.portable_parts():
            if name != self.backbone_component:
                layers[f"{name}_lora_layers"] = convert_state_dict_to_diffusers(
                    self._lora_state(getattr(self, name)))
        self.pipe_cls.save_lora_weights(out, **layers)

    def save_weights(self, out: Path) -> None:
        """A checkpoint: everything needed to resume, and everything needed to
        USE the result.

        Both are written at every checkpoint rather than only at the end. A
        run that overtrains is salvaged by picking an earlier checkpoint, and
        before this those held only a pickle no other tool could open — so the
        one weight set somebody actually wanted needed converting by hand.
        """
        if self.method != "lora":
            self.save_full(out)
            return
        # Imported here, not at module scope: `adapters` is a sibling resolved
        # off sys.path (the entry points insert the scripts dir), and this
        # file is also loaded directly by the tests. Same reason as
        # `pipeline_opts` in `_from_pretrained`.
        import adapters

        adapters.save_state(out, self.adapter_state(), self.adapter_meta())
        if self.portable_supported():
            self.save_portable(out)
        if self.lycoris_supported():
            self.save_lycoris(out)

    def save_output(self, out: Path) -> None:
        """The finished artifact. A checkpoint minus the trainer's own copy —
        which is why it is the same two calls in the same order."""
        if self.method == "lora":
            if self.portable_supported():
                self.save_portable(out)
            if self.lycoris_supported():
                self.save_lycoris(out)
        else:
            self.save_full(out)

    #: Whether the tools that read adapters map THIS architecture's own
    #: module paths under `lycoris_`. It is a per-architecture fact, not a
    #: per-format one, which is why it is declared rather than derived:
    #: ComfyUI's `comfy/lora.py` builds
    #: `key_map["lycoris_{}".format(path.replace(".", "_"))]` for the
    #: diffusers-named transformers (the Flux and QwenImage branches among
    #: them) and NOT for the SD/SDXL UNet, which it maps as `lora_unet_` over
    #: the ldm names — a different mapping this app does not reproduce.
    #:
    #: Default False, deliberately: the cost of claiming it wrongly is a file
    #: that loads with every key rejected, which reads as a broken adapter
    #: rather than as a wrong prefix. Turn it on for an engine only after
    #: reading that engine's branch in `comfy/lora.py`.
    lycoris_named = False

    def lycoris_supported(self) -> bool:
        """Whether to write the LyCORIS-named copy — LoKr on such an engine.

        A LoRA does not need one: `pytorch_lora_weights.safetensors` is the
        layout everything reads, and writing the same weights twice under two
        namings is two files to keep in step for no gain.
        """
        return (self.lycoris_named and self.method == "lora"
                and str(self.hyper.get("network", "lora") or "lora") == "lokr")

    def save_lycoris(self, out: Path) -> None:
        """The LoKr in LyCORIS' naming — see `lycoris.py` for the whole rule.

        The BACKBONE only. The `lycoris_` map covers the transformer's own
        module paths; a text encoder's adapter is named another way again
        (ComfyUI keys CLIP and T5 adapters through its own clip loader), so
        FLUX.1's encoder adapters stay in the trainer's own file.
        """
        import torch
        from safetensors.torch import save_file

        import lycoris

        rank = int(self.hyper.get("rank", 16))
        alpha = float(self.hyper.get("alpha", rank) or rank)
        state = self._lora_state(getattr(self, self.backbone_component))
        data = lycoris.convert(state, scaling=alpha / max(rank, 1),
                               tensor=torch.tensor)
        if not data:
            return
        # safetensors wants contiguous CPU tensors, and these come straight
        # off the model — on the GPU, and a scaled one is a fresh tensor
        # while an untouched one is still the parameter itself.
        save_file({k: v.detach().to("cpu").contiguous()
                   for k, v in data.items()}, str(out / lycoris.LYCORIS_FILE))

    def portable_supported(self) -> bool:
        """Whether a diffusers-layout file can be written for this adapter.

        LoRA yes, LoKr no: `save_lora_weights` writes the layout diffusers
        DEFINES, and that layout has an A matrix and a B matrix per module —
        there is nowhere in it to put a Kronecker factor. Writing one anyway
        would produce a file that loads without error and applies nothing,
        which is worse than not writing it. A LoKr checkpoint is still a
        complete safetensors adapter (`adapters.STATE_FILE`); what it is not
        is a diffusers LoRA.
        """
        return str(self.hyper.get("network", "lora") or "lora") == "lora"

    def _load_weights(self, ckpt_dir: Path) -> None:
        if self.method != "lora":
            self.load_full(ckpt_dir)
            return
        import adapters

        state = adapters.load_state(ckpt_dir)
        for name, module in self.adapter_modules().items():
            if name in state:
                self._load_lora_state(module, state[name])

    def load_checkpoint(self, ckpt_dir: Path, optimizer, ema=None) -> int:
        import torch

        state = torch.load(ckpt_dir / "trainer_state.pt", weights_only=False,
                           map_location="cpu")
        try:
            optimizer.load_state_dict(state["optimizer"])
        except ValueError:
            print("optimizer state incompatible — starting optimizer fresh")
        torch.set_rng_state(state["torch_rng"])
        self._load_weights(ckpt_dir)
        # The averaged weights, read here rather than in the loop so a resume
        # is ONE read of this file. A run that has just been switched to
        # averaging finds nothing and starts its average from where it is,
        # which is the honest thing for it to do.
        if ema is not None and state.get("ema"):
            if not ema.load_state_dict(state["ema"]):
                print("the saved weight average does not fit what this run "
                      "trains — starting the average again from here",
                      flush=True)
        return int(state["step"])

    # -- architecture map --------------------------------------------------

    def backbone(self):
        """The module being trained — UNet or transformer, engine-specific."""
        return getattr(self, "unet", None) or getattr(self, "transformer", None)

    def architecture(self) -> list[dict]:
        """The model's own shape, read off the loaded weights.

        Nothing here knows what an SDXL or a Chroma looks like: it walks the
        backbone's immediate children and sums the parameters under each. A
        model this app has never seen therefore draws itself correctly, and a
        model whose blocks are renamed upstream does not silently draw the old
        picture.

        The order is the order they RUN in, once a forward pass has been seen
        (`record_block_order` records it). Declaration order is not it —
        diffusers' UNet declares `mid_block` after `up_blocks`, while the data
        goes down → mid → up — and guessing from the names would be exactly
        the built-in assumption this avoids.
        """
        root = self.backbone()
        if root is None:
            return []
        out: list[dict] = []
        for name, child in root.named_children():
            params = sum(p.numel() for p in child.parameters())
            if not params:
                continue
            kids = list(child.children())
            stack = _is_stack(name, child)
            entry = {
                "name": name,
                "params": int(params),
                # The repeated stacks (`down_blocks`, `transformer_blocks`) are
                # containers; their length is the depth worth showing.
                "count": len(kids) if stack else 0,
                "kind": _block_kind(name),
            }
            if stack:
                # The stack's own inner shape: one entry per repeated block,
                # each with its own size (a UNet's down blocks are far from
                # equal — the deepest holds most of the parameters).
                entry["children"] = [
                    {"name": f"{name}.{i}",
                     "params": int(sum(q.numel() for q in k.parameters()))}
                    for i, k in enumerate(kids)
                ]
            out.append(entry)
        seen = getattr(self, "_order", [])
        if seen:
            out.sort(key=lambda b: (seen.index(b["name"]) if b["name"] in seen
                                    else len(seen)))
        return out

    def record_block_order(self) -> None:
        """Record the order the backbone's top-level blocks execute in, so the
        architecture map can be drawn in that order rather than in declaration
        order (diffusers' UNet declares `mid_block` after `up_blocks`, while
        the data goes down → mid → up).

        One pre-forward hook per top-level child, each appending to a list on
        first sight — and `stop_block_order()` unhooks them all once the loop
        has seen a pass, so a run carries no instrumentation past its first
        step. Forward only: a backward hook makes torch warn on every module
        whose inputs need no gradient (every frozen block of a LoRA run), and
        that lands in the user's training log.
        """
        import torch

        root = self.backbone()
        if root is None:
            return
        self._order: list[str] = []
        self._order_hooks: list = []

        def make_hook(top: str):
            def hook(_m, _inp):
                if top not in self._order:
                    self._order.append(top)
            return hook

        for name, child in root.named_children():
            if not any(True for _ in child.parameters()):
                continue
            # A ModuleList is never called itself — the model indexes into it
            # — so hooking the list would never fire, and the two biggest
            # parts of a UNet (`down_blocks`, `up_blocks`) would never be
            # placed. Its first entry stands for the list: the order asked
            # about is the order of the top-level names.
            try:
                target = child
                if isinstance(child, torch.nn.ModuleList):
                    if not len(child):
                        continue
                    target = child[0]
                self._order_hooks.append(
                    target.register_forward_pre_hook(make_hook(name)))
            except Exception:      # noqa: BLE001 - instrumentation is optional
                return

    def stop_block_order(self) -> None:
        """Remove the order hooks. The order is a property of the model, so
        one pass answers it for good — and the rest of the run then executes
        with nothing of ours in the forward path at all."""
        for handle in getattr(self, "_order_hooks", []):
            try:
                handle.remove()
            except Exception:  # noqa: BLE001 - already gone, fine
                pass
        self._order_hooks = []

    # engine-specific:
    def load(self):  # pragma: no cover - abstract
        raise NotImplementedError

    def _text_encoders(self) -> list:
        return []

    def save_full(self, out: Path) -> None:
        """Write a finetuned base model (the `method == "full"` artifact)."""
        getattr(self, self.backbone_component).save_pretrained(
            out / self.backbone_component)

    def load_full(self, ckpt_dir: Path) -> None:
        """Read one back INTO THE LIVE MODULE rather than swapping the module
        out, so the optimizer's parameter references survive a resume."""
        module = getattr(self, self.backbone_component)
        saved = type(module).from_pretrained(ckpt_dir / self.backbone_component)
        module.load_state_dict(saved.state_dict())
        del saved


def _snr(scheduler, timesteps):
    import torch

    alphas_cumprod = scheduler.alphas_cumprod.to(timesteps.device)
    a = alphas_cumprod[timesteps]
    return a / torch.clamp(1.0 - a, min=1e-8)


def masked_mean(loss, masks):
    """Per-sample mean of a (b, c, h, w) loss, optionally weighted per cell.

    A weighted MEAN, not a sum: the unmasked path averages over every element,
    so anything else here would silently rescale the gradient with the size of
    the visible region and make the learning rate mean different things for
    different images.
    """
    dims = list(range(1, loss.ndim))
    if masks is None:
        return loss.mean(dim=dims)
    w = masks.to(loss.dtype).expand_as(loss)
    return (loss * w).sum(dim=dims) / w.sum(dim=dims).clamp(min=1e-8)


def param_group(params, lr: float) -> dict:
    """An optimizer param group the loop's scheduler can rescale."""
    return {"params": [p for p in params if p.requires_grad],
            "lr": lr, "initial_lr": lr}

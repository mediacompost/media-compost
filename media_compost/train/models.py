"""Registry of trainable base models.

Adding a model = one ``TrainModelSpec`` here + one engine module in
``media_compost/train/scripts/engines/`` (named by ``engine``). The registry —
including each model's extra hyperparameter ``FieldSpec``s and size-estimate
constants — is served to the frontend via ``GET /api/train/status``, so the
editor renders model-specific fields data-driven with no hardcoded UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from media_compost.hub import cache_sizes, pipeline_files
from media_compost.train import layers


@dataclass(frozen=True)
class FieldSpec:
    """One model-specific hyperparameter, rendered generically by the editor."""

    name: str
    type: str            # "int" | "float" | "bool" | "choice"
    default: object
    label: str
    hint: str            # one-line user-facing explanation
    details: str = ""    # long form, shown by the editor's "?" button
    min: Optional[float] = None
    max: Optional[float] = None
    choices: tuple[str, ...] = ()


# Min-SNR + noise offset apply to the epsilon-prediction diffusion models
# (SD 1.5 / SDXL); flow-matching models (Chroma) get a timestep-shift knob.
_DIFFUSION_PARAMS = (
    FieldSpec(
        name="min_snr_gamma", type="float", default=0.0, min=0.0, max=20.0,
        label="Min-SNR gamma",
        hint="Rebalances loss across noise levels; 5 is the common value, "
             "0 disables. Usually speeds up convergence and stabilizes colors.",
        details=(
            "Training picks a random amount of noise for every image it looks "
            "at, from barely noisy to pure static. Those cases are not equally "
            "hard, and by default the easy, barely-noisy ones dominate the "
            "loss \u2014 so much of the training signal is spent on detail the "
            "model already handles.\n\n"
            "Min-SNR caps how much weight any single noise level can claim, "
            "which shifts effort toward the harder, noisier steps where "
            "composition and color are decided. In practice runs converge "
            "sooner and colors come out less washed. 5 is the value from the "
            "paper and a safe choice; 0 turns the rebalancing off."
        ),
    ),
    FieldSpec(
        name="noise_offset", type="float", default=0.0, min=0.0, max=0.3,
        label="Noise offset",
        hint="Lets the model learn very dark/bright images; 0.05–0.1 typical, "
             "0 off. Too high washes out contrast.",
        details=(
            "Stable Diffusion never quite reaches pure black or pure white: "
            "its noise schedule leaves a little of the original average "
            "brightness in place, so the model is never asked to invent an "
            "image's overall light level. Prompts for a night scene or a "
            "white-on-white product shot come back stubbornly mid-gray.\n\n"
            "Noise offset adds a small amount of extra brightness noise during "
            "training so the model does learn to set that level itself. "
            "0.05–0.1 is the usual range; too much and everything it "
            "generates drifts toward heavy contrast."
        ),
    ),
)


def _flow_params(model: str) -> tuple[FieldSpec, ...]:
    """The timestep-shift knob, worded for one model family.

    Every flow-matching model here takes this setting and it means the same
    thing in all of them; only the first word of the explanation differs. A
    factory rather than one copy per model — but the text it produces is
    byte-identical to what the two hand-written copies said, because the
    German map is keyed by the English source and a reworded sentence is an
    untranslated one.
    """
    return (
        FieldSpec(
            name="flow_shift", type="float", default=3.0, min=0.5, max=8.0,
            label="Timestep shift",
            hint="Shifts flow-matching training toward high-noise steps; "
                 "higher emphasizes composition over fine texture. "
                 "1–3 typical at 1024 px.",
            details=(
                f"{model} is a flow-matching model: instead of predicting "
                "noise it learns a straight path from noise to image, and "
                "training samples positions along that path. Timestep "
                "shift decides where those samples cluster.\n\n"
                "Higher values pull them toward the noisy end, where the "
                "overall layout of the image is decided — which is "
                "what you want at higher resolutions, since there are "
                "more pixels but no more composition. Lower values spend "
                "more of the run on fine texture. 1–3 is the usual "
                "range at 1024 px."
            ),
        ),
    )


def _guidance_param() -> FieldSpec:
    """The training guidance scale, for a GUIDANCE-DISTILLED model only.

    FLUX.1 dev and Kontext were distilled so that the guidance scale is an
    input to the transformer rather than something the sampler applies around
    it (`transformer.config.guidance_embeds`, which is what the engines read
    — this field is only consulted when the model has one). Training has to
    feed one, and the value it feeds is the scale the model will be best at
    afterwards. 1.0 is what the LoRA community settled on: it keeps the
    adapter out of the guidance behaviour the base already has.
    """
    return FieldSpec(
        name="guidance", type="float", default=1.0, min=0.0, max=10.0,
        label="Training guidance",
        hint="The guidance scale baked into training. 1 leaves the base "
             "model's own guidance behavior alone, which is what you "
             "usually want.",
        details=(
            "This model is guidance-distilled: where an ordinary model is "
            "steered by running it twice per step, once with the prompt and "
            "once without, this one was taught to do that in a single pass "
            "— so the strength of the steering is a number it takes as "
            "input rather than something applied around it.\n\n"
            "Training therefore has to pick one, and it is the scale the "
            "result is tuned for. 1 asks it to keep doing whatever the base "
            "model already does at each scale, which is what you want when "
            "you are teaching it a subject or a style. Higher values train "
            "the adapter for one particular strength of steering, at the "
            "cost of the others."
        ),
    )


@dataclass(frozen=True)
class TrainModelSpec:
    key: str
    label: str
    engine: str          # train/scripts/engines/<engine>.py
    repo: str
    default_area: int    # native training resolution (pixel area = area²)
    lora_only: bool = False
    # The BUILT-IN this entry is a variant of, "" for a built-in itself.
    # Only a user model has one (`usermodels.resolve` carries over what the
    # user declared it is based on), and it is what makes two entries
    # ADAPTER-COMPATIBLE: a LoRA trained on an SDXL finetune fits plain SDXL
    # and every other SDXL finetune, because they are the same network with
    # different numbers in it. See `adapter_family`.
    base_key: str = ""
    # Whether `repo` is a FILESYSTEM PATH — a diffusers folder or a single
    # .safetensors checkpoint — rather than a Hugging Face repo id. Never true
    # of a built-in: it is what `usermodels.resolve` carries over from the
    # model the user added, and it is the difference between weights that are
    # already here and weights that have to be fetched. Everything that would
    # otherwise ask the hub about them reads it: the guard refusing a run that
    # needs a download while downloads are off, the manifest's own `local`
    # flag (which is what makes the trainer call `from_single_file`), and the
    # snapshot-directory lookup, which has no answer for a path.
    local: bool = False
    # Whether the repo is GATED on Hugging Face — a licence to accept and a
    # token to download with. Declared per spec rather than probed, exactly as
    # the AI plugins' manifests declare theirs: gating is a property of the
    # repo that only a person can check, and asking the hub would mean a
    # network call to draw a chip. Its only effects are that chip and the
    # "set a token" hint beside it — a wrong flag never refuses anything, and
    # the download itself reports the real error.
    #
    # Not derivable from anything nearby, which is why it is a field: FLUX.2
    # Klein 4B is open (Apache-2.0) and the 9B beside it is gated, so neither
    # the family nor the org answers it.
    gated: bool = False
    # Whether this checkpoint is IMAGE-CONDITIONED: it takes one or more
    # reference pictures beside the prompt and produces an edited result, which
    # is what an INSTRUCTION is training data for. Per SPEC and not per engine
    # on purpose — an editing checkpoint usually shares its architecture (and
    # so its engine module) with a plain text-to-image one, and a table of
    # "which engines edit" is the second table this file keeps deleting.
    edit: bool = False
    # …and whether editing is what it is FOR. Both flags are true of the
    # Qwen-Image Edit releases and FLUX.1 Kontext: their pipelines take a
    # reference picture as the subject of the call, and a run that trains them
    # on plain captions is teaching the text-to-image half of a model nobody
    # uses that way. `edit` alone is true of FLUX.2 Klein, a generator that
    # ALSO takes references — training that on tags is the ordinary thing to
    # do, which is why this cannot be one flag.
    #
    # It decides a DEFAULT and a sentence in the editor, never a refusal:
    # training an editing checkpoint text-to-image is unusual, not impossible,
    # and the run would work.
    edit_only: bool = False
    default_lr: float = 1e-4
    note: str = ""
    # Size-estimate constants for the editor's checkpoint estimate:
    # LoRA file ≈ lora_mb_per_rank * rank; full weights ≈ full_gb.
    #
    # `full_gb` is what a full finetune's checkpoint COSTS ON DISK, which is
    # the backbone at FP32 — twice its bf16 size. The trainable weights are
    # upcast to fp32 master copies at load (see BaseEngine.autocast) and
    # `save_pretrained` writes them as they are, so a bf16 figure here
    # under-reports every full-finetune checkpoint by half. Measured: a
    # FLUX.2 Klein finetune writes 14.4 GB against a 7.8 GB bf16 backbone.
    lora_mb_per_rank: float = 1.0
    full_gb: float = 0.0
    # Memory-estimate constants, all in GB at bf16/fp16 (the estimator scales
    # them for fp32 and for quantization):
    #   backbone_gb  the network being trained (UNet / transformer)
    #   aux_gb       text encoder(s) + VAE, resident but usually frozen
    #   act_gb       activations per image at `default_area`, WITHOUT gradient
    #                checkpointing — the term that scales with batch and pixels
    #   ckpt_factor  what fraction of act_gb survives gradient checkpointing
    # Weights come from the published parameter counts (e.g. SDXL: 2.6B UNet,
    # 0.12B + 0.69B text encoders, 0.08B VAE). `act_gb` and `ckpt_factor` are
    # MEASURED on this project's own engines — a forward+backward at batch 1
    # and batch 2, taking the slope — because the published figures are far
    # off on Apple Silicon: SDXL costs ~30 GB per image at 1024 here, not the
    # ~6 GB a CUDA box with memory-efficient attention needs. Re-measure
    # rather than guess, and expect CUDA to come in well under these.
    backbone_gb: float = 0.0
    aux_gb: float = 0.0
    act_gb: float = 0.0
    ckpt_factor: float = 0.2
    #   act_gb_cuda / ckpt_factor_cuda   the same two, MEASURED ON CUDA. 0
    #                means "not measured here", and the MPS pair is used.
    #
    # They are separate constants rather than one fudge factor because the gap
    # is not a constant: measured on an RTX 5070 Ti (bf16, this project's own
    # engines, batch-slope method), activations came in 8.5x under the MPS
    # figure for SD 1.5, 3.8x for SDXL, 2.7x for FLUX.2 and 1.7x for Chroma.
    # The cause is fused/flash attention, which CUDA has and MPS does not: it
    # never materializes the N x N attention matrix, so what survives is
    # roughly linear in tokens instead of quadratic — and how much of a model's
    # activation budget IS attention differs per architecture. One scale factor
    # would be wrong for three of the four.
    #
    # `ckpt_factor` diverges too, and in the same direction: with attention
    # already cheap there is less left for gradient checkpointing to recompute
    # away, EXCEPT that the DiT models turn out to recompute much more of
    # themselves (0.047-0.0625 measured vs the 0.30-0.32 on MPS).
    #
    # **THE EDITOR SCALES `act_gb` LINEARLY WITH THE PIXEL COUNT, AND THAT IS
    # AN APPROXIMATION IT UNDER-SHOOTS AT HIGH RESOLUTION.**
    # `estimateVram` multiplies by `(res/native)^2` — i.e. an exponent of 1 on
    # the AREA — where the real one is fitted from readings at several sizes.
    # Measured on MPS, torch 2.13, this project's engines:
    #
    #     sd15   256/384/512 px -> 0.52 / 1.98 / 7.87 GB   exponent 1.95
    #     sdxl   256/384/512/768 -> 1.05 / 2.04 / 4.06 / 13.7   exponent 1.17
    #
    # Neither is 1, and sd15's is nearly 2 — the N x N attention matrix is
    # quadratic in the token count and the token count is the area, so where
    # attention is not fused the whole term is quadratic in PIXELS. Nor is one
    # exponent right across the range: SDXL's local slope is ~1.0 up to 512 px
    # and ~1.5 from 512 to 768, which is what an attention term overtaking a
    # linear feature-map term looks like.
    #
    # So the exponent is a CONSTANT LIKE THE OTHERS, per model and per
    # backend, and for the same reason: it is a fact about an architecture on
    # a piece of hardware, and one number cannot be right for both. `act_exp`
    # is the MPS figure and `act_exp_cuda` the CUDA one; `estimateVram` raises
    # the area ratio to it.
    #
    # **1.0 IS THE DEFAULT AND IT MEANS "NOBODY HAS MEASURED THIS"**, which is
    # also exactly the old behaviour — so a model with no figure estimates
    # today what it estimated before, and adding one is a strict improvement
    # rather than a change of shape. It matters only away from
    # `default_area`, where `act_gb` is defined and the ratio is 1 whatever
    # the exponent: a run at the model's own resolution is unaffected by any
    # of this.
    #
    # Measure it by fitting the slope through readings at several sizes at a
    # fixed batch. Fitting one power law across
    # the whole range is itself an approximation — the exponent RISES with
    # resolution as the quadratic attention term overtakes the linear one — so
    # prefer readings that bracket the sizes people actually train at.
    #
    # **THE VALUE IS THE LARGEST THAT DOES NOT UNDER-PREDICT A MEASURED
    # POINT**, which is not the same as the fitted slope and is the rule every
    # entry here follows. `act_gb` is anchored at `default_area` and the
    # common move is DOWNWARDS — to make a run fit — and there a lower
    # exponent predicts more. So the fit is an upper bound to check against
    # rather than the number to paste: SDXL fits 1.17-1.49 depending on the
    # range, and 1.2 is what its 256 px reading permits; Z-Image fits 1.31 and
    # takes 1.25. Over-predicting below native is the direction that merely
    # wastes a little headroom; under-predicting is the one that tells
    # somebody a job fits when it does not.
    #
    # **MEASURE IT NEAR THE NATIVE SIZE OR NOT AT ALL.** The per-image cost
    # has a part that is pixels and a part that is not: the TEXT conditioning
    # is a fixed sequence (Chroma pads T5 to 512 tokens whatever the picture
    # is) and it scales with the BATCH, so the batch-1 -> batch-2 slope
    # collects it in full at every resolution. Far below native that term is
    # most of the reading and the fit degenerates — Chroma measured 10.5 GB an
    # image at 192 px and 12.95 at 256, which is an "exponent" of 0.365, i.e.
    # a statement about T5 rather than about area. That is why only the two
    # UNet models carry one here: their CLIP encoders are small enough (77
    # tokens) for the pixel term to dominate, and both were fitted over a
    # range reaching their own resolution. A model that can only be measured
    # at 256 px on the hardware to hand keeps 1.0 and waits for a bigger card.
    act_exp: float = 1.0
    act_exp_cuda: float = 0.0
    #   act_const_share / act_quad_share (+ the _cuda twins)
    #                HOW `act_gb` SPLITS, as fractions of itself at the native
    #                area. Whatever is left over is the LINEAR share.
    #
    # **THIS REPLACES THE EXPONENT WHERE IT HAS BEEN MEASURED**, and it is the
    # completion of the note above rather than a contradiction of it: that
    # note says the per-image cost "has a part that is pixels and a part that
    # is not", and then declines to fit an exponent because the two cannot be
    # separated by one. Three terms separate them, and each is a thing the
    # hardware does — a fixed conditioning sequence, per-image-token work, and
    # a MATERIALIZED N x N attention matrix. Fitting all three against area
    # sweeps on an RTX 5090 and an M4 Max (RMSE against the measurements):
    #
    #                     linear (old)   affine   quadratic
    #   sdxl  [cuda]          6.4%        1.2%      1.4%
    #   klein [cuda]         27.7%        0.3%       —
    #   sdxl  [mps]          30.3%       37.6%      0.1%
    #
    # So the QUADRATIC term is a fact about the BACKEND: a fused attention
    # kernel never allocates that matrix, which is why CUDA is affine and MPS
    # is not. Do not copy an MPS quad share onto the CUDA twin.
    #
    # Both default to 0, which is the plain linear rule — and where BOTH are 0
    # the estimator falls back to `act_exp` above rather than to linear, so an
    # unmeasured model keeps whatever superlinear guard it already had.
    act_const_share: float = 0.0
    act_quad_share: float = 0.0
    act_const_share_cuda: float = 0.0
    act_quad_share_cuda: float = 0.0
    #   lora_params_m_per_rank   TRAINABLE parameters, in millions per rank.
    #
    # What the optimizer holds state for, and NOT the same question as
    # `lora_mb_per_rank`, which sizes the FILE a run writes. The estimate used
    # to derive one from the other and was wrong twice over: it reads an fp32
    # file size as bf16 (doubling the count), and the constant itself is off
    # by up to 5x in BOTH directions — against measured counts at rank 16 it
    # implies 44.8M parameters for SDXL's real 23.2M and 20.8M for FLUX.2
    # Klein's 3.9M, while understating Chroma and Qwen-Image. 0 means
    # unmeasured, and the old derivation is kept for those.
    lora_params_m_per_rank: float = 0.0
    #   te_act_gb_cuda   what training the TEXT ENCODER adds, measured on CUDA.
    #
    # A twin for the same reason `act_gb` has one: the encoder's forward is
    # kept for its backward, and whether attention is fused decides how much
    # that is. SDXL measured 1.3 GB on MPS against 0.364 on an RTX 5090 —
    # so the shared figure is not wrong, it is the MPS one, and lowering it
    # would drop every Apple estimate on CUDA's evidence. 0 falls back.
    te_act_gb_cuda: float = 0.0
    #   int8_scale / int8_te_scale   what fraction of the backbone, and of the
    #                text encoders, SURVIVES int8 quantization.
    #
    # **0.5 IS ONLY TRUE OF A MODEL THAT IS ALL LINEAR**, and that is the DiTs.
    # The estimate used a flat half, which is right for Chroma, FLUX, Z-Image
    # and Qwen-Image — every one of them measures 100% Linear — and wrong for
    # the two UNets, because quanto (and bitsandbytes, and torchao) convert
    # `Linear` layers and a UNet is mostly `Conv2d`. Measured on an M4 Max:
    # SD 1.5's UNet 1.72 -> 1.45 GB, i.e. 0.84 and not 0.5, so the estimate
    # promised a saving twice what the run makes — in the direction that says
    # a job fits when it does not.
    #
    # The text encoders are their own number because they are their own
    # architecture: transformer blocks are Linear, but the embedding table is
    # not, and on the small CLIP encoders it is a large share of the weights.
    # **NOT ONE OF THEM MEASURES 0.5** — 0.56 and 0.57 for the Qwen3 encoders
    # of FLUX.2 Klein and Z-Image, 0.64 for Chroma's T5-XXL and for SDXL's
    # CLIP pair, 0.78 for SD 1.5's single small CLIP. So the default is 0.6,
    # above every DiT reading rather than a round number below all of them:
    # this factor makes the estimate SMALLER, and one that is too small says a
    # job fits when it does not.
    int8_scale: float = 0.5
    int8_te_scale: float = 0.6
    #   nf4_scale / nf4_te_scale   the same two for nf4, and they are NOT 0.25.
    #
    # The estimate used the theoretical quarter, the way it once used a flat
    # half for int8, and nothing quantized to it. Measured on an RTX 5070 Ti
    # (bitsandbytes, torch 2.11+cu128) as resting weights after a real load,
    # with `backbone_gb`/`aux_gb` known from the safetensors headers to 0.03 GB
    # so the backbone term subtracts cleanly:
    #
    #   SD 1.5   1.78 GB resting -> 0.81      SDXL   4.05 -> 0.41
    #
    # and the DiTs measured DIRECTLY, by parking the text encoder on the CPU
    # (`offload_text_encoder`) so the resting figure is the backbone plus only
    # the 0.16 GB VAE:
    #
    #   Chroma  5.29 -> 0.288   FLUX.1  6.98 -> 0.287   Klein  2.37 -> 0.285
    #
    # Three architectures inside 1% of each other, which is what says this is
    # a property of the SCHEME on an all-Linear model rather than of any one
    # of them. An earlier round put Chroma and FLUX.1 at ~0.35 and ~0.33; that
    # was arithmetic, not measurement — their readings still carried a
    # quantized encoder and the backbone was backed out through an assumed
    # encoder scale, which turned out to be the wrong one. Offloading removed
    # the need to assume anything.
    #
    # Same split as int8 and for the same reason — the quantizer converts
    # `Linear`, a DiT is all of it and a UNet is mostly `Conv2d` — but nf4
    # lands FURTHER from its theoretical floor than int8 does from a half,
    # because bitsandbytes keeps per-block scales and leaves more of the model
    # unconverted. The default is 0.29, just above all three DiT readings:
    # this factor makes the estimate SMALLER, and one that is too small says a
    # job fits when it does not. Only the two UNets override it.
    #
    # `nf4_te_scale` rests on ONE reading — 0.35, for FLUX.2 Klein's Qwen3
    # encoder, from the difference between its two runs — so the default sits
    # above it by the margin `int8_te_scale`'s does, and is the number here
    # most worth re-measuring on a card that can hold an encoder at bf16.
    nf4_scale: float = 0.29
    nf4_te_scale: float = 0.4
    act_gb_cuda: float = 0.0
    # EVERY DiT's CUDA CHECKPOINTING FACTOR WAS ABOUT HALF WHAT IT SHOULD BE,
    # and they were all corrected together in 2026-08 because they were all
    # wrong the same way: derived by scaling a slope rather than measured.
    # Read at 384 px on an RTX 5070 Ti (nf4, text encoder on the CPU, and for
    # the largest models with VRAM paging to system RAM — see below):
    #
    #   Chroma 0.047 -> 0.124   FLUX.1 0.05 -> 0.128   Klein 4B 0.0625 -> 0.133
    #   Klein 9B 0.05 -> 0.115  Qwen 0.05 -> 0.105     Z-Image 0.05 -> 0.065
    #
    # Every one MORE than doubles except Z-Image's, and every one moves in the
    # direction that costs memory rather than promising it: the editor was
    # telling people checkpointing leaves 5% of their activations when it
    # leaves 10-13%.
    #
    # A factor is a RATIO of two readings at ONE resolution, which is why
    # these are usable where `act_gb_cuda` is not — nothing is extrapolated.
    # Where two resolutions were taken they agree (Klein 0.131/0.133 at
    # 256/384, Qwen 0.093/0.105); Z-Image is the exception and FALLS with
    # size (0.100 at 256), so its 384 reading is the one recorded and its
    # native figure may be lower still.
    ckpt_factor_cuda: float = 0.0
    #   te_act_gb    what training the TEXT ENCODER adds, per image — its
    #                forward is then kept for the backward pass. MEASURED the
    #                same way. **0 means the engine does not train a text
    #                encoder at all** (the flow-matching models don't), which
    #                is also how the editor knows to disable the setting
    #                rather than offer one that does nothing.
    te_act_gb: float = 0.0
    #   te_pooled_act_gb   the same term with the LARGE encoder left frozen
    #                (`train_text_encoder_large` off) — only the small pooled
    #                encoder(s) training. **0 means there is no such option**:
    #                the model has no large encoder (SD, SDXL) or no small
    #                one beside it (Chroma, whose T5 is its only encoder),
    #                and the editor hides the switch. FLUX.1 is the one model
    #                with both, and its figure is CLIP-L's, i.e. SD 1.5's
    #                (the same encoder at the same 77 tokens).
    te_pooled_act_gb: float = 0.0
    #   te_params_m_per_rank   millions of TRAINABLE parameters per rank the
    #                text-encoder adapter(s) add, for the optimizer term —
    #                `lora_params_m_per_rank`'s twin. Arithmetic, not a
    #                measurement: layers x four attention projections x
    #                (in + out). CLIP-L 12 x 4 x 1536 = 0.074M, OpenCLIP bigG
    #                32 x 4 x 2560 = 0.328M, T5-XXL 24 x 4 x 8192 = 0.786M.
    #                0 falls back to the old flat 1.3x on the backbone's term,
    #                which under-counts T5 (it is larger than the FLUX
    #                transformer's own adapter) — so every model that trains
    #                an encoder carries the figure.
    te_params_m_per_rank: float = 0.0
    #   te_pooled_params_m_per_rank   …and with the large encoder left out.
    te_pooled_params_m_per_rank: float = 0.0
    params: tuple[FieldSpec, ...] = ()


REGISTRY: tuple[TrainModelSpec, ...] = (
    TrainModelSpec(
        key="sd15",
        label="Stable Diffusion 1.5",
        engine="sd",
        repo="stable-diffusion-v1-5/stable-diffusion-v1-5",
        default_area=512,
        default_lr=1e-4,
        note="Smallest and fastest to train; 512 px. Good for first "
             "experiments and small LoRAs.",
        lora_mb_per_rank=1.2,
        # fp32 on disk, i.e. 2x the 1.7 GB bf16 UNet — derived from the rule
        # the FLUX.2 measurement established, not measured here.
        full_gb=3.4,
        # Measured (MPS, bf16, LoRA r16, 512 px): 2.1 GB resident, 8.5 GB per
        # image, 53% of that still spent with checkpointing on.
        backbone_gb=1.7, aux_gb=0.4, act_gb=8.5, ckpt_factor=0.53,
        # int8 leaves 0.87 of this UNet, not the 0.5 the estimate used to
        # assume for everything: quantizers convert `Linear` and SD 1.5's UNet
        # is overwhelmingly `Conv2d`. Measured on an M4 Max — 2.15 GB resident
        # at bf16 against 1.88 at int8, i.e. the backbone 1.72 -> 1.45.
        int8_scale=0.87,
        # Its ONE small CLIP encoder is the most embedding-heavy of the
        # lot, so int8 leaves 0.78 of it (2.15 -> 1.79 GB resident with
        # both quantized).
        int8_te_scale=0.78,
        # nf4 leaves MORE of this one than int8 does of most models: 1.78 GB
        # resting with the backbone quantized, against 2.17 at bf16, so 0.81
        # of a UNet that is mostly Conv2d survives a scheme whose theoretical
        # figure is 0.25. The editor promised 0.82 GB and the run wants 1.80.
        nf4_scale=0.81,
        # How activations grow with the PIXEL COUNT, fitted over 256/384/512
        # px on an M4 Max (torch 2.13): 0.52 / 1.98 / 7.87 GB an image, which
        # is an exponent of 1.95 — and 1.77 on a repeat run. 1.8 is the
        # conservative end of that pair, and conservative is what matters
        # BELOW the native size, where a lower exponent predicts more: at
        # 256 px it says 0.74 GB against the 0.52 measured. Nearly quadratic
        # because nothing here fuses attention, and the N x N score matrix is
        # quadratic in a token count that IS the area.
        # **NOT LOWERED, ON PURPOSE.** An area sweep on an M4 Max measured
        # 0.48 / 1.48 / 4.30 GB an image at 256 / 384 / 512 px, so `act_gb`
        # of 8.5 over-states this model's own resolution by about a factor of
        # two and `act_exp` of 1.8 over-states the curve with it (+98% at
        # native). Both are left alone: torch exposes no peak for MPS, so the
        # figure is SAMPLED from a thread every 4 ms and a spike between two
        # samples is simply missed — a reading that comes out LOWER than the
        # constant is exactly what a missed spike looks like. Raising a
        # constant on that evidence is sound (SDXL's `act_gb` moved 30 -> 37.1
        # here); lowering one is how the editor comes to promise that a job
        # fits when it does not. The CUDA side of this model IS a true peak
        # and is measured: 1.14 at native, linear in area to within 6%.
        act_exp=1.8,
        # RTX 5070 Ti, bf16, 512 px: 3.0/4.0/6.0 GB at batch 1/2/4 without
        # checkpointing (slope 1.0/image, intercept 2.0 = the weights), and
        # 2.3/3.0 GB at batch 1/4 with it (slope 0.233 -> factor 0.23).
        # Re-measured 2026-08 on an RTX 5070 Ti (16 GB, torch 2.11.0+cu128,
        # Windows): 1.07 GB/image and 0.241, at
        # this model's OWN native 512 px so nothing is extrapolated, and
        # identical on a repeat run — CUDA reports a true peak, so a second
        # reading reproduces to the digit rather than merely agreeing. Both
        # move UP, which is the safe direction for a number whose job is to
        # answer "will this fit".
        act_gb_cuda=1.14, ckpt_factor_cuda=0.241,
        # +0.06 GB measured for its one small CLIP encoder.
        te_act_gb=0.06,
        te_params_m_per_rank=0.074,
        params=_DIFFUSION_PARAMS,
        lora_params_m_per_rank=0.199,
        act_exp_cuda=1.0,
    ),
    TrainModelSpec(
        key="sdxl",
        label="SDXL 1.0",
        engine="sdxl",
        repo="stabilityai/stable-diffusion-xl-base-1.0",
        default_area=1024,
        default_lr=1e-4,
        note="1024 px, two text encoders. The standard choice for quality "
             "LoRAs; full finetune needs a large GPU.",
        lora_mb_per_rank=5.6,
        # fp32 on disk, i.e. 2x the 5.1 GB bf16 UNet — derived, see sd15.
        full_gb=10.2,
        # Measured (MPS, bf16, LoRA r16, 1024 px): 7.5 GB resident, 30 GB per
        # image, and checkpointing cuts the step to 8% of that.
        #
        # `aux_gb` counts the VAE at fp32, not bf16, because that is what this
        # engine loads: `sdxl.py:load` does `self.vae.to(dtype=torch.float32)`
        # — the fp16 SDXL VAE is numerically fragile — so the 0.083B VAE costs
        # 0.33 GB here and not 0.17. With the two encoders' 0.81B at bf16 that
        # is 1.95, and a re-measure on torch 2.13 read 7.20 GB resident
        # against the 6.90 the old 1.8 predicted.
        backbone_gb=5.1, aux_gb=1.95, act_gb=37.1, ckpt_factor=0.08,
        # 0.59, measured the same way (7.05 GB resident at bf16 against 4.97 at
        # int8). Between SD 1.5's 0.87 and a DiT's 0.50 because SDXL's UNet
        # carries far more attention — which is Linear — than SD 1.5's does.
        # Two UNets, two answers: this is why the figure is per model.
        int8_scale=0.59,
        # CLIP-L plus OpenCLIP ViT-bigG: 0.64 (7.05 -> 4.26 GB).
        int8_te_scale=0.64,
        # 4.05 GB resting against 7.33 at bf16 -> 0.41. Half again as much
        # survives here as in SD 1.5, which is the same ordering int8 gives
        # (0.59 against 0.87): SDXL carries far more attention, and attention
        # is Linear, which is the part a quantizer converts.
        nf4_scale=0.41,
        # Fitted over 256/384/512/768 px on an M4 Max (torch 2.13):
        # 1.05 / 2.04 / 4.06 / 13.7 GB an image, exponent 1.17 — and 1.21,
        # 1.27 and 1.49 on the two-point fits of repeat runs.
        #
        # ONE POWER LAW DOES NOT FIT THE WHOLE RANGE, and this is the model
        # that shows it: the local slope is ~1.0 up to 512 px and ~1.5 from
        # 512 to 768, a quadratic attention term overtaking a linear
        # feature-map one. **1.2 is chosen rather than the steeper near-native
        # 1.5 because the estimate is anchored at 1024 and the common move is
        # DOWNWARDS, where a lower exponent predicts more.** Against the
        # measurements: at 768 px it says 14.9 GB and the machine used 13.65;
        # at 512 it says 5.2 and the machine used 4.06. The steeper 1.5 would
        # say 12.7 and 3.75 — under the truth at both, which is the direction
        # that tells somebody a job fits when it does not.
        #
        # The same 768 px reading carried up to 1024 lands at 32.2 GB against
        # the 30.0 constant, which is the best evidence anyone has that the
        # native figure is right; it could not be re-measured directly, since
        # batch 2 at 1024 does not fit 64 GB (the original 30.0 was taken when
        # MPS was still allowed to page past physical memory).
        act_exp=1.2,
        # RTX 5070 Ti, bf16, 1024 px: 14.8/22.6 GB at batch 1/2 without
        # checkpointing (slope 7.8/image, intercept 7.0 against the 7.2 the
        # weights+optimizer terms predict — those hold on CUDA), and 7.6/8.2
        # with it (slope 0.6 -> factor 0.077, i.e. the MPS 0.08 was right).
        # CORROBORATED, not re-measured, 2026-08 on a 16 GB 5070 Ti: batch 2
        # at 1024 does not fit that card (the readings above peak at 22.6 GB,
        # so whatever took them had more memory than this one), and the run
        # stepped down to 512 px for 2.07 GB/image. Carried back up that is
        # 7.04 GB at the fitted exponent and 8.27 at the editor's 1.0 — a
        # bracket around 7.8, so the constant stands. Its own exponent could
        # NOT be fitted here: 384-512 px gives 0.884, below 1, which measures
        # the fixed text-conditioning cost rather than the area, so
        # `act_exp_cuda` stays 0 (meaning "nobody has measured this").
        act_gb_cuda=7.77, ckpt_factor_cuda=0.093,
        # +1.3 GB measured (peak 10.14 -> 11.45 at 1024, batch 1, checkpointed):
        # its second encoder is OpenCLIP ViT-bigG, which is not small.
        te_act_gb=1.3,
        te_params_m_per_rank=0.401,
        params=_DIFFUSION_PARAMS,
        te_act_gb_cuda=0.364,
        act_const_share_cuda=0.012,
        lora_params_m_per_rank=1.451,
        act_const_share=0.024,
        act_quad_share=0.858,
    ),
    TrainModelSpec(
        key="chroma",
        label="Chroma1 HD",
        engine="chroma",
        repo="lodestones/Chroma1-HD",
        default_area=1024,
        # Full finetune offered: ~101 GB with an 8-bit optimizer, inside
        # the line drawn at the FLUX.2 Klein 4B entry. `full_gb` is the
        # backbone at fp32, i.e. 2x its bf16 size.
        default_lr=3e-4,
        note="The 1024 px release: Chroma1 Base given a high-resolution "
             "finetune, so it holds detail and composition at 1024 and is "
             "the one to train on unless you are working smaller.",
        full_gb=35.6,
        lora_mb_per_rank=4.0,
        # MEASURED on MPS, bf16, LoRA r16, on this project's own engine, after
        # the weights were finally downloaded: 25.70 GB resident after load
        # (the transformer's shards are 17.8 GB of it, the rest is T5-XXL and
        # the VAE). Per image WITH gradient checkpointing: 4.1 GB at 512 px
        # (batch-1 -> batch-2 slope) and ~40 GB at 1024 px, its native size —
        # where batch 1 alone peaks at 66 GB and a 64 GB machine is already
        # swapping.
        #
        # The old numbers were SDXL's scaled by parameter count and said 10 GB
        # for that case: four times under, on the model least able to afford
        # it. As with FLUX.2 what is pinned here is the PRODUCT
        # act_gb * ckpt_factor at the native resolution; splitting it is
        # extrapolation.
        # aux CORRECTED 2026-08 from 7.9: the 25.70 GB resting figure above was
        # short. T5-XXL's encoder is 4.76B parameters and the VAE 0.083B, i.e.
        # 9.69 GB at bf16, and a re-measure on torch 2.13 read 27.60 GB
        # resident — both agree, and this is now derived from the safetensors
        # headers so it cannot drift again.
        backbone_gb=17.8, aux_gb=9.7, act_gb=133.0, ckpt_factor=0.30,
        # T5-XXL: int8 leaves 0.64 of it (27.5 -> 15.08 GB resident
        # with the backbone quantized too). The backbone itself is the
        # DiT default 0.50, measured at 0.506.
        int8_te_scale=0.64,
        # RTX 5070 Ti, bf16 + nf4, 256 px: 19.8/24.6 GB at batch 1/2 without
        # checkpointing — slope 4.8/image, x16 for the area to 1024 = 76.8.
        # With checkpointing at 384 px the slope is 0.5/image (3.6 scaled),
        # so the factor is 0.047. Measured quantized because it will not fit
        # a 16 GB card otherwise; the intercept then carries ~2.4 GB of
        # bitsandbytes overhead the weights term does not model.
        act_gb_cuda=32.24, ckpt_factor_cuda=0.087,
        # TRAINING T5. The CUDA figure is MEASURED (RTX 5090, torch
        # 2.13+cu130, 2026-09): nf4 backbone at 256 px, batch 1, no
        # checkpointing, the in-step peak with the T5 adapter training less
        # the same run without it — 27.5 against 20.1 GB, 7.4 GB a prompt
        # (T5 is padded to 512 tokens, so the area does not enter), 7.2 with
        # the adapter's own optimizer state taken out. The derivation that
        # stood here said 5.0 — low, the direction that promises a fit the
        # card cannot deliver. The MPS figure stays DERIVED (the unfused
        # 64 x 512 x 512 scores per layer on top, SDXL's own MPS/CUDA ratio
        # of 3.6x): `measure_vram.py --area 128` on a 64 GB M4 Max ran out
        # of its budget on the encoder term — its batch-2 slope with T5
        # uncheckpointed wants ~60 GB beside an int8 backbone, and the
        # script must not page — so it needs a bigger Mac, and the row in
        # `research/vram_measurements.csv` records the attempt (te empty).
        # Both are the no-checkpointing
        # figure, like `act_gb` — the estimate applies `ckpt_factor` to
        # them when checkpointing is on, since the engine checkpoints a
        # trained encoder too (measured checkpointed at 512 px: +0.3 GB).
        te_act_gb=12.0, te_act_gb_cuda=7.2,
        te_params_m_per_rank=0.786,
        params=_flow_params("Chroma"),
        act_const_share_cuda=0.104,
        act_quad_share_cuda=0.059,
        lora_params_m_per_rank=1.634,
    ),
    TrainModelSpec(
        key="chroma_base",
        label="Chroma1 Base",
        engine="chroma",
        repo="lodestones/Chroma1-Base",
        default_area=512,
        # Full finetune offered: ~101 GB with an 8-bit optimizer, inside
        # the line drawn at the FLUX.2 Klein 4B entry. `full_gb` is the
        # backbone at fp32, i.e. 2x its bf16 size.
        default_lr=3e-4,
        note="The 512 px release HD was finetuned from. Trains faster and "
             "cheaper at 512, and is the better start if your images are "
             "small or you want the un-finetuned base to build on.",
        full_gb=35.6,
        lora_mb_per_rank=4.0,
        # The same architecture and the same weights count as HD — Base is
        # what HD was finetuned FROM, so every memory constant is shared;
        # only the native resolution differs, and `default_area` carries
        # that. See the HD entry for how these were measured.
        # aux CORRECTED 2026-08 from 7.9: the 25.70 GB resting figure above was
        # short. T5-XXL's encoder is 4.76B parameters and the VAE 0.083B, i.e.
        # 9.69 GB at bf16, and a re-measure on torch 2.13 read 27.60 GB
        # resident — both agree, and this is now derived from the safetensors
        # headers so it cannot drift again.
        backbone_gb=17.8, aux_gb=9.7, act_gb=133.0, ckpt_factor=0.30,
        # T5-XXL: int8 leaves 0.64 of it (27.5 -> 15.08 GB resident
        # with the backbone quantized too). The backbone itself is the
        # DiT default 0.50, measured at 0.506.
        int8_te_scale=0.64,
        # RTX 5070 Ti, bf16 + nf4, 256 px: 19.8/24.6 GB at batch 1/2 without
        # checkpointing — slope 4.8/image, x16 for the area to 1024 = 76.8.
        # With checkpointing at 384 px the slope is 0.5/image (3.6 scaled),
        # so the factor is 0.047. Measured quantized because it will not fit
        # a 16 GB card otherwise; the intercept then carries ~2.4 GB of
        # bitsandbytes overhead the weights term does not model.
        act_gb_cuda=10.22, ckpt_factor_cuda=0.092,
        # T5 training: the same encoder as Chroma1 HD, same measurement.
        te_act_gb=12.0, te_act_gb_cuda=7.2,
        te_params_m_per_rank=0.786,
        params=_flow_params("Chroma"),
        act_const_share_cuda=0.328,
        act_quad_share_cuda=0.012,
        lora_params_m_per_rank=1.634,
    ),
    # ---- DERIVED activation constants: read this once ---------------------
    #
    # The two DiT models above were measured on this project's own engines.
    # The seven that follow — every entry below marked "derived" — could not
    # be: between them they weigh several hundred gigabytes, four of the
    # repos are gated, and none of them fits the hardware this was written
    # on. Refusing to ship them until someone can measure would be the worse
    # trade: the estimate exists to answer "will this fit", and a model with
    # `act_gb=0` shows no estimate at all.
    #
    # So they are INTERPOLATED between the two measured DiT points, which is
    # the honest version of the arithmetic: Chroma at 8.9B needs 133 GB per
    # image on MPS and FLUX.2 Klein at 3.9B needs 85, so activations run at
    # about 9.6 GB per billion parameters plus a large architecture-
    # independent term (the attention matrix, which MPS materializes and
    # whose size depends on the token count rather than the weights). The
    # same two points on CUDA — 76.8 and 32 — give 8.96 GB per billion, on a
    # much smaller base. Gradient checkpointing measured 0.30/0.32 on MPS and
    # 0.047/0.0625 on CUDA, so 0.30 and 0.05 are used here.
    #
    # `backbone_gb` and `aux_gb` are NOT estimates: they are the components'
    # own weight files at bf16, read off each repo. It is only the two
    # activation terms that are modelled, and they are the soft ones anyway
    # (see the field comments above). Re-measure per model when the hardware
    # to do it turns up, and replace one entry at a time.
    TrainModelSpec(
        key="flux1_dev",
        label="FLUX.1 dev",
        engine="flux",
        repo="black-forest-labs/FLUX.1-dev",
        gated=True,
        default_area=1024,
        # Full finetune offered: ~134 GB with an 8-bit optimizer, the
        # closest to the line drawn at the FLUX.2 Klein 4B entry — an H200
        # and nothing smaller. `full_gb` is the backbone at fp32.
        default_lr=1e-4,
        note="The original FLUX: a 12B flow-matching transformer with CLIP-L "
             "and T5-XXL. Gated — accept the license on Hugging Face first. "
             "Most existing LoRA advice on the internet is written for this.",
        # Derived from the two measured points; see the note above.
        full_gb=47.6,
        lora_mb_per_rank=4.7,
        # 23.80 GB of transformer, 9.52 + 0.25 of text encoders and 0.17 of
        # VAE, read off the repo. 11.9B parameters.
        backbone_gb=23.8, aux_gb=9.9, act_gb=162.0, ckpt_factor=0.30,
        act_gb_cuda=29.84, ckpt_factor_cuda=0.095,
        # TRAINING THE ENCODERS — MEASURED on CUDA the way Chroma's is (RTX
        # 5090, nf4, 256 px, batch 1, no checkpointing): both encoders
        # 30.5 against 22.0 GB plain, 8.5 GB a prompt, 8.3 without the
        # adapters' optimizer state; CLIP-L alone 23.1, i.e. 1.0 GB — far
        # more than SD 1.5's 0.06 for the same encoder, because FLUX's
        # `encode_prompt` runs BOTH encoders inside one grad-enabled call
        # once either trains. The MPS figure is Chroma's derivation plus
        # that.
        te_act_gb=13.0, te_act_gb_cuda=8.3,
        te_pooled_act_gb=1.0,
        te_params_m_per_rank=0.860, te_pooled_params_m_per_rank=0.074,
        params=_flow_params("FLUX.1") + (_guidance_param(),),
        act_const_share_cuda=0.111,
        lora_params_m_per_rank=1.634,
    ),
    TrainModelSpec(
        key="flux1_kontext",
        label="FLUX.1 Kontext dev",
        engine="flux",
        repo="black-forest-labs/FLUX.1-Kontext-dev",
        gated=True,
        default_area=1024,
        edit=True, edit_only=True,
        default_lr=1e-4,
        note="FLUX.1 dev taught to edit: it takes a picture beside the "
             "prompt and produces the change asked for. Gated. Train it on "
             "instructions — the pictures an instruction names are what it "
             "is shown.",
        # The same transformer as FLUX.1 dev, weight for weight, so every
        # constant is shared with it — including the full-finetune line.
        lora_mb_per_rank=4.7,
        full_gb=47.6,
        backbone_gb=23.8, aux_gb=9.9, act_gb=162.0, ckpt_factor=0.30,
        act_gb_cuda=29.84, ckpt_factor_cuda=0.095,
        te_act_gb=13.0, te_act_gb_cuda=8.3,
        te_pooled_act_gb=1.0,
        te_params_m_per_rank=0.860, te_pooled_params_m_per_rank=0.074,
        params=_flow_params("FLUX.1") + (_guidance_param(),),
        act_const_share_cuda=0.111,
        lora_params_m_per_rank=1.634,
    ),
    TrainModelSpec(
        key="flux2_klein",
        label="FLUX.2 Klein (base, 4B)",
        engine="flux2",
        repo="black-forest-labs/FLUX.2-klein-base-4B",
        default_area=1024,
        # NOT lora_only: the engine implements a full finetune of the
        # transformer (the Qwen3 encoder stays frozen either way, exactly as
        # SD/SDXL's "full" means the UNet).
        #
        # WHICH MODELS GET THE CHOICE IS ONE LINE, DRAWN AT AN H200's 141 GB,
        # and it is written here rather than guessed per entry. A full
        # finetune costs weights + aux + 8x the backbone for the optimizer
        # (halved by 8-bit Adam, which is bitsandbytes and therefore CUDA
        # only) + activations, at batch 1 with checkpointing at the model's
        # native size. That is, plain / 8-bit: Klein 4B 79 / 48, Z-Image
        # 122 / 72, Chroma 172 / 101, Klein 9B 184 / 112, FLUX.1 dev
        # 229 / 134 — all within 141 GB with the 8-bit optimizer. The five
        # Qwen-Image releases are not, and are `lora_only`: a 20B backbone is
        # past the line before the optimizer even starts. (The figures that
        # used to sit here for Krea 2, 252 / 147, and FLUX.2 dev, 643 / 385,
        # are the reason those two were `lora_only` too — both are gone now,
        # and the arithmetic is kept because it is how the line is drawn.)
        # Move the line in
        # ONE place when the hardware moves, and note that off CUDA the
        # 8-bit column does not apply: the plain figures are what an Apple
        # machine pays.
        # `full_gb` is the transformer's own weight.
        #
        # FLUX.2 is image-conditioned — its pipeline takes reference pictures
        # beside the prompt — so it can be trained on INSTRUCTIONS.
        edit=True,
        default_lr=1e-4,
        note="4B flow-matching transformer with a Qwen3 text encoder "
             "(Apache-2.0, not gated). Far smaller than Chroma for the same "
             "family; the text encoder is most of the weight.",
        lora_mb_per_rank=2.6,
        # Measured: the run above wrote 14.4 GB of sharded transformer.
        full_gb=14.4,
        # MEASURED on MPS, bf16, LoRA r16, on this project's own engine, as
        # the batch-1 -> batch-2 slope. 14.88 GB resident after load (the
        # transformer's own safetensors is 7.75 GB of it, so ~7.1 GB is the
        # Qwen3 encoder + VAE). Per image WITH gradient checkpointing:
        # 2.1 GB at 512 px, 13.5 at 768, 27.1 at 1024. Without it, 15 GB at
        # 512 px — and at 1024 px it does not fit 64 GB at batch 1 at all,
        # which is the finding rather than a gap in the measurement.
        #
        # So what is measured here is the PRODUCT act_gb * ckpt_factor = ~27,
        # the configuration anyone actually runs at this resolution. Splitting
        # it is not: `act_gb` is extrapolated from the 512 px unchecked figure
        # (activations grow faster than the 4x token count — attention is
        # quadratic in it) and `ckpt_factor` follows. Re-measure on CUDA,
        # where flash attention changes the quadratic term entirely.
        # aux CORRECTED 2026-08 from 7.1, the same way Chroma's was: the Qwen3
        # encoder is 4.02B parameters and the VAE 0.083B = 8.21 GB at bf16, and
        # a re-measure on torch 2.13 read 15.98 GB resident against the 14.88
        # above. The parameter count and the fresh measurement agree to 20 MB.
        backbone_gb=7.8, aux_gb=8.2, act_gb=85.0, ckpt_factor=0.32,
        # Its Qwen3 encoder: 0.56 (16.0 -> 8.47 GB).
        int8_te_scale=0.56,
        # RTX 5070 Ti, bf16 + nf4, 256 px: 12.6/14.6 GB at batch 1/2 without
        # checkpointing — slope 2.0/image, x16 for the area to 1024 = 32.
        #
        # `ckpt_factor_cuda` re-measured 2026-08 and MORE THAN DOUBLED, from
        # 0.0625 to 0.133: 0.131 at 256 px and 0.133 at 384 (the second with
        # the text encoder on the CPU, which is what made the larger size
        # fit). A checkpointing factor is a RATIO of two readings at ONE
        # resolution, so unlike `act_gb_cuda` it needs no extrapolation to be
        # usable — and these two are flat across a 2.25x change in area,
        # where Z-Image's fall with it. The old figure came from scaling a
        # 512 px slope rather than measuring one, and it promised half the
        # memory checkpointing actually leaves.
        #
        # `act_gb_cuda` is NOT re-measured and stays derived. Every reading a
        # 16 GB card can take is at 256-384 px, and the fitted exponent there
        # is 0.43 — far below 1, so it is describing fixed cost rather than
        # area, and carrying it to 1024 gives 7.8 GB/image at that exponent
        # against 60 at the editor's 1.0. Nothing to choose between.
        act_gb_cuda=16.08, ckpt_factor_cuda=0.122,
        params=_flow_params("FLUX.2"),
        act_const_share_cuda=0.112,
        lora_params_m_per_rank=0.246,
    ),
    TrainModelSpec(
        key="flux2_klein_9b",
        label="FLUX.2 Klein (base, 9B)",
        engine="flux2",
        repo="black-forest-labs/FLUX.2-klein-base-9B",
        gated=True,
        default_area=1024,
        # Full finetune offered: ~112 GB with an 8-bit optimizer, inside
        # the line drawn at the 4B entry above. `full_gb` is the backbone
        # at fp32.
        edit=True,
        default_lr=1e-4,
        note="The larger Klein release: 9B, with a bigger Qwen3 encoder "
             "beside it. The same architecture as the 4B, so a setting that "
             "works on one works on the other — it simply needs the memory. "
             "Gated, unlike the 4B: accept the license on Hugging Face first.",
        # Derived; see the note above the FLUX.1 entry.
        full_gb=36.4,
        lora_mb_per_rank=4.1,
        # 18.16 GB of transformer and 16.38 + 0.17 beside it, read off the
        # repo — this release pairs with an 8B encoder where the 4B has a 4B
        # one, which is why `aux_gb` more than doubles for a 2.3x transformer.
        backbone_gb=18.2, aux_gb=16.6, act_gb=135.0, ckpt_factor=0.30,
        # RTX 5070 Ti 2026-08: LOADS at 5.33 GB resting with nf4 and the text
        # encoder on the CPU — confirming `backbone_gb` (18.16 off the repo's
        # own headers) and putting `nf4_scale` at 0.285, in line with the
        # seven other DiTs. It cannot take a STEP there: what is left of a
        # 16 GB card after the backbone is not enough for a 9B transformer's
        # activations at any size on the ladder, so both figures below remain
        # derived. This is the first time the model has been on a CUDA box at
        # all — the earlier attempt could not even read its headers, the repo
        # being gated and the CLI having no token.
        act_gb_cuda=27.45, ckpt_factor_cuda=0.105,
        params=_flow_params("FLUX.2"),
        act_const_share_cuda=0.112,
        lora_params_m_per_rank=0.524,
    ),
    TrainModelSpec(
        key="zimage",
        label="Z-Image",
        engine="zimage",
        repo="Tongyi-MAI/Z-Image",
        default_area=1024,
        # NOT lora_only, and it is the only one of the seven added later where
        # that is true — the same arithmetic that admits FLUX.2 Klein 4B and
        # keeps Chroma out. Its 6.2B transformer costs, at bf16 with 8-bit
        # Adam, gradient checkpointing and batch 1 at 1024 px on CUDA:
        # 12.3 weights + 8.2 aux + 49.2 optimizer + 2.7 activations = ~72 GB.
        # That fits a 96 GB card with room, where Chroma comes to ~101 and
        # Klein 9B to ~112. Plain AdamW doubles the optimizer term to ~122 GB,
        # so the 8-bit optimizer is not optional at this size — and it is
        # bitsandbytes, i.e. CUDA only.
        default_lr=1e-4,
        note="6B single-stream transformer with a Qwen3 text encoder "
             "(Apache-2.0, not gated). The cheapest of the modern "
             "transformers to train, and the smallest thing here that still "
             "follows a long prompt properly.",
        # Derived; see the note above the FLUX.1 entry.
        lora_mb_per_rank=3.3,
        # fp32 on disk, i.e. 2x the 12.3 GB bf16 backbone — the rule the
        # FLUX.2 Klein measurement established.
        full_gb=24.6,
        # 12.31 GB of transformer and 8.04 + 0.17 beside it, read off the
        # repo. 6.2B parameters.
        backbone_gb=12.3, aux_gb=8.2, act_gb=107.0, ckpt_factor=0.30,
        # Its Qwen3 encoder: 0.57 (20.5 -> 10.81 GB).
        int8_te_scale=0.57,
        # Measured on an M4 Max (torch 2.13) at 384 and 512 px: 8.53 and
        # 18.14 GB an image, a fit of 1.312 — which carried up to 1024 px
        # gives 111.8 GB against the 107.0 constant above, and is the best
        # corroboration that figure has. 1.25 rather than the fit itself, by
        # the rule the exponents here follow: the largest value that does not
        # UNDER-predict a measured point (the bound is 1.28 from both
        # readings), because the estimate is anchored at 1024 and the common
        # move is downwards. The base and Turbo measured 18.14 and 18.13 —
        # the same model, as everything else about this pair says.
        act_exp=1.25,
        act_gb_cuda=34.72, ckpt_factor_cuda=0.068,
        params=_flow_params("Z-Image"),
        act_const_share_cuda=0.007,
        lora_params_m_per_rank=1.044,
    ),
    TrainModelSpec(
        key="zimage_turbo",
        label="Z-Image Turbo",
        engine="zimage",
        repo="Tongyi-MAI/Z-Image-Turbo",
        default_area=1024,
        # Full finetune offered for the same reason as the base — same engine,
        # same size, same arithmetic. Whether it is a good idea is a different
        # question the note answers: rewriting every weight of a few-step
        # distilled checkpoint is the surest way to lose the distillation you
        # picked it for.
        default_lr=1e-4,
        note="The few-step distilled release, for generating in a handful of "
             "steps instead of fifty. Train on it when that is what you will "
             "generate with; otherwise the base above learns more cleanly.",
        # The same architecture and the same parameter count as the base —
        # Turbo is that model distilled, so every constant is shared. Its
        # weights are stored at fp32 on the hub (24.6 GB rather than 12.3),
        # which is a download size and not a memory one: the trainer loads
        # both at bf16.
        lora_mb_per_rank=3.3, full_gb=24.6,
        backbone_gb=12.3, aux_gb=8.2, act_gb=107.0, ckpt_factor=0.30,
        # Its Qwen3 encoder: 0.57 (20.5 -> 10.81 GB).
        int8_te_scale=0.57,
        # Measured on an M4 Max (torch 2.13) at 384 and 512 px: 8.53 and
        # 18.14 GB an image, a fit of 1.312 — which carried up to 1024 px
        # gives 111.8 GB against the 107.0 constant above, and is the best
        # corroboration that figure has. 1.25 rather than the fit itself, by
        # the rule the exponents here follow: the largest value that does not
        # UNDER-predict a measured point (the bound is 1.28 from both
        # readings), because the estimate is anchored at 1024 and the common
        # move is downwards. The base and Turbo measured 18.14 and 18.13 —
        # the same model, as everything else about this pair says.
        act_exp=1.25,
        act_gb_cuda=34.72, ckpt_factor_cuda=0.068,
        params=_flow_params("Z-Image"),
        act_const_share_cuda=0.007,
        lora_params_m_per_rank=1.044,
    ),
    TrainModelSpec(
        key="qwen_image",
        label="Qwen-Image",
        engine="qwenimage",
        repo="Qwen/Qwen-Image",
        default_area=1024,
        
        lora_only=True,
        default_lr=1e-4,
        note="20B transformer with a Qwen2.5-VL text encoder (Apache-2.0, not "
             "gated). Unusually good at rendering TEXT inside a picture, "
             "and heavy to match.",
        # Derived; see the note above the FLUX.1 entry. 20.4B parameters, so
        # a full finetune is ~230 GB even with an 8-bit optimizer — well past
        # the line drawn at the FLUX.2 Klein 4B entry.
        lora_mb_per_rank=6.2,
        # 40.86 GB of transformer and 16.58 + 0.25 beside it, read off the
        # repo. Every release in this family is the same size.
        backbone_gb=40.9, aux_gb=16.8, act_gb=243.0, ckpt_factor=0.30,
        # **`act_gb_cuda` IS THE ONE FIGURE HERE STILL DERIVED**, and it is a
        # hardware limit rather than an oversight. Every other model in this
        # registry was measured at its own resolution on an RTX 5090;
        # Qwen-Image could not be, either way round:
        #
        #   bf16, oversubscribed into system RAM — about 41 GB of weights with
        #   the text encoder offloaded, plus activations, against 89 GB of RAM.
        #   It ran 45 minutes without finishing one configuration and then met
        #   the kernel's OOM killer. A 128 GB machine would manage it.
        #
        #   int8, inside real VRAM — fast, and it stops at 256 px: the slope
        #   method needs batch 2, and twice the activations on top of 20.9 GB
        #   of quantized weights does not fit in 32 GB. int8 also INFLATES
        #   activations (measured x1.62 on SD 1.5 and x1.52 on FLUX.2 Klein at
        #   one resolution), so it is not a bf16 reading either.
        #
        # Turning that 256 px int8 number into a native bf16 constant needs two
        # chained guesses — an int8-to-bf16 ratio borrowed from other models and
        # a shape borrowed from other DiTs — and what they give is ~16 GB, LOWER
        # than Chroma's measured 32.24 for a backbone more than twice the size.
        # That is how you can tell it is wrong. So 180 stays: derived, almost
        # certainly too high (every other derived figure here was 53-652% over),
        # and too high is the direction that refuses a job rather than stranding
        # one.
        #
        # WHAT THE int8 RUN DOES SETTLE, because it is not nothing: the WEIGHT
        # side and the parameter count. `backbone_gb * int8_scale` predicts
        # 20.45 GB against a measured 20.90 resting — the 0.45 being the VAE,
        # which --offload-te leaves on the card — so both are confirmed rather
        # than assumed. And `lora_params_m_per_rank` is quantization-INDEPENDENT
        # (a LoRA attaches to the same modules whatever the frozen weights are
        # stored as), so 47.19M at rank 16 is a real measurement and is used.
        act_gb_cuda=180.0, ckpt_factor_cuda=0.105,
        params=_flow_params("Qwen-Image"),
        lora_params_m_per_rank=2.949,
    ),
    TrainModelSpec(
        key="qwen_image_2512",
        label="Qwen-Image 2512",
        engine="qwenimage",
        repo="Qwen/Qwen-Image-2512",
        default_area=1024,
        
        lora_only=True,
        default_lr=1e-4,
        note="The December refresh of the base model — same architecture and "
             "size, retrained. The one to start from unless you have a "
             "reason to match the original.",
        # Derived; see the note above the FLUX.1 entry. 20.4B parameters, so
        # a full finetune is ~230 GB even with an 8-bit optimizer — well past
        # the line drawn at the FLUX.2 Klein 4B entry.
        lora_mb_per_rank=6.2,
        # 40.86 GB of transformer and 16.58 + 0.25 beside it, read off the
        # repo. Every release in this family is the same size.
        backbone_gb=40.9, aux_gb=16.8, act_gb=243.0, ckpt_factor=0.30,
        act_gb_cuda=180.0, ckpt_factor_cuda=0.105,
        params=_flow_params("Qwen-Image"),
        lora_params_m_per_rank=2.949,
    ),
    TrainModelSpec(
        key="qwen_image_edit",
        label="Qwen-Image Edit",
        engine="qwenimage",
        repo="Qwen/Qwen-Image-Edit",
        default_area=1024,
        edit=True, edit_only=True,
        lora_only=True,
        default_lr=1e-4,
        note="The editing release: it takes a picture beside the prompt and "
             "produces the change asked for. Train it on instructions "
             "— one reference picture each.",
        # Derived; see the note above the FLUX.1 entry. 20.4B parameters, so
        # a full finetune is ~230 GB even with an 8-bit optimizer — well past
        # the line drawn at the FLUX.2 Klein 4B entry.
        lora_mb_per_rank=6.2,
        # 40.86 GB of transformer and 16.58 + 0.25 beside it, read off the
        # repo. Every release in this family is the same size.
        backbone_gb=40.9, aux_gb=16.8, act_gb=243.0, ckpt_factor=0.30,
        act_gb_cuda=180.0, ckpt_factor_cuda=0.105,
        params=_flow_params("Qwen-Image"),
        lora_params_m_per_rank=2.949,
    ),
    TrainModelSpec(
        key="qwen_image_edit_2509",
        label="Qwen-Image Edit 2509",
        engine="qwenimage",
        repo="Qwen/Qwen-Image-Edit-2509",
        default_area=1024,
        edit=True, edit_only=True,
        lora_only=True,
        default_lr=1e-4,
        note="The September editing refresh, and the first that takes SEVERAL "
             "reference pictures — so an instruction naming two sources "
             "trains as what it is.",
        # Derived; see the note above the FLUX.1 entry. 20.4B parameters, so
        # a full finetune is ~230 GB even with an 8-bit optimizer — well past
        # the line drawn at the FLUX.2 Klein 4B entry.
        lora_mb_per_rank=6.2,
        # 40.86 GB of transformer and 16.58 + 0.25 beside it, read off the
        # repo. Every release in this family is the same size.
        backbone_gb=40.9, aux_gb=16.8, act_gb=243.0, ckpt_factor=0.30,
        act_gb_cuda=180.0, ckpt_factor_cuda=0.105,
        params=_flow_params("Qwen-Image"),
        lora_params_m_per_rank=2.949,
    ),
    TrainModelSpec(
        key="qwen_image_edit_2511",
        label="Qwen-Image Edit 2511",
        engine="qwenimage",
        repo="Qwen/Qwen-Image-Edit-2511",
        default_area=1024,
        edit=True, edit_only=True,
        lora_only=True,
        default_lr=1e-4,
        note="The November editing refresh, and the newest of the three. Same "
             "architecture as the others, so a LoRA carries between them.",
        # Derived; see the note above the FLUX.1 entry. 20.4B parameters, so
        # a full finetune is ~230 GB even with an 8-bit optimizer — well past
        # the line drawn at the FLUX.2 Klein 4B entry.
        lora_mb_per_rank=6.2,
        # 40.86 GB of transformer and 16.58 + 0.25 beside it, read off the
        # repo. Every release in this family is the same size.
        backbone_gb=40.9, aux_gb=16.8, act_gb=243.0, ckpt_factor=0.30,
        act_gb_cuda=180.0, ckpt_factor_cuda=0.105,
        params=_flow_params("Qwen-Image"),
        lora_params_m_per_rank=2.949,
    ),
)


# User-added models, resolved to full specs and published here by
# ``usermodels.refresh(session)``. A module cache rather than a lookup with a
# session because `model_spec` is called from everywhere that already knows
# only a key — config validation, the manifest builder, the evaluator — and
# threading a session through all of them to read one settings row would be a
# worse trade than refreshing this whenever a request touches the list.
_USER_SPECS: dict[str, "TrainModelSpec"] = {}


def set_user_specs(specs: dict[str, "TrainModelSpec"]) -> None:
    global _USER_SPECS
    _USER_SPECS = dict(specs)


def model_spec(key: str) -> Optional[TrainModelSpec]:
    for m in REGISTRY:
        if m.key == key:
            return m
    return _USER_SPECS.get(key)


def repo_state(repo: str) -> str:
    """``"ready"`` | ``"partial"`` | ``"none"`` for a base model's weights.

    "partial" matters: an interrupted download leaves real bytes in the cache
    that `snapshot_download` will resume from, so the UI should offer to
    continue rather than start over — and should not claim the model is
    missing when several gigabytes of it are already there.
    """
    if not repo or repo.endswith(".safetensors"):
        return "none"
    # What the pipeline would load, which is the only standard that matters:
    # a repo carries every variant and a pile of single-file checkpoints
    # `from_pretrained` never opens, so demanding the whole snapshot called
    # SDXL "partly downloaded" while it was generating images from that very
    # cache. Falls through to the snapshot probe for a repo with no
    # `model_index.json` cached (nothing fetched yet, or not a pipeline repo).
    state = pipeline_files.local_state(repo)
    if state is not None:
        return state
    # The import is its OWN try, and that is the bug it fixes rather than a
    # style choice: with both in one block, a missing huggingface_hub raises
    # ImportError, Python then EVALUATES the first except clause to see if it
    # matches, and `LocalEntryNotFoundError` is an unbound local because the
    # import that would have bound it is the thing that failed. The result is
    # an UnboundLocalError raised from the except clause itself — which the
    # `except Exception` below cannot catch, because it is not raised inside
    # the try. So the "a probe must never break the page" guard was bypassed
    # on exactly the installs it exists for: no hub, no torch, Train tab
    # showing setup — and /api/train/status 500s instead.
    try:
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import LocalEntryNotFoundError
    except ImportError:
        return "none"
    try:
        # Cheap — it stats the snapshot, it does not read any weights.
        snapshot_download(repo, local_files_only=True)
        return "ready"
    except LocalEntryNotFoundError as exc:
        # IncompleteSnapshotError SUBCLASSES LocalEntryNotFoundError, so it has
        # to be recognised first — otherwise a half-fetched model reads as one
        # that was never started, and the UI offers "download" for something
        # that only needs finishing.
        if "incomplete" in f"{type(exc).__name__} {exc}".lower():
            return "partial"
        return "none"
    except Exception:  # noqa: BLE001 - a probe must never break the page
        return "none"


def _repo_cached(repo: str) -> bool:
    """Whether a base model's weights are already in the Hugging Face cache.

    Reuses the hub cache probe (a downloaded config file and no half-fetched
    blob) the plugin framework also delegates to, so "downloaded" means the
    same thing here as it does on the Settings models page.
    `model_index.json` is the diffusers pipeline manifest every one of these
    repos has.
    """
    from media_compost.hub.cache import repo_cached

    if not repo or repo.endswith(".safetensors"):
        return False
    try:
        return repo_cached(repo, probe="model_index.json")
    except Exception:  # noqa: BLE001 - never let a cache probe break the page
        return False


def registry_entry(m: TrainModelSpec, sizes: Optional[dict] = None) -> dict:
    """One model as the JSON both dropdowns and the job editor consume.

    ``sizes`` is ONE ``hub.cache_sizes()`` scan for the whole list — a
    per-entry call would be a walk of the cache per row. Passing none means
    "do not report a size", which is what the editor's dropdown wants; only
    the Models page asks.
    """
    state = repo_state(m.repo)
    return {
        "cached": state == "ready",
        "partial": state == "partial",
        # On-disk bytes of the downloaded weights, 0 when they are not in the
        # Hugging Face cache — a local path is somebody else's directory and
        # measuring it would be an unbounded walk of a folder we did not fill.
        "size": int((sizes or {}).get(m.repo, 0)) if state == "ready" else 0,
        "key": m.key,
        "label": m.label,
        # The built-in it is a variant of, "" for a built-in — the app reads
        # it to know which adapters fit (see `adapter_family`), so it is sent
        # for EVERY entry rather than only for the user models that have one.
        "base": m.base_key,
        # The ARCHITECTURE, which is what the Models tab groups by: several
        # entries can be the same one (Chroma's two releases), and a user
        # model is whichever built-in it declared itself based on.
        "engine": m.engine,
        # …and, from the same fact, the layer names the adapter section's two
        # filter fields can offer. Per ENGINE rather than per checkpoint, so
        # a user model based on SDXL gets SDXL's names — see `layers.py`.
        "layer_hints": layers.hints_for(m.engine),
        "repo": m.repo,
        "default_area": m.default_area,
        "lora_only": m.lora_only,
        "gated": m.gated,
        # Whether the editor may offer "Instructions" as a caption source…
        "edit": m.edit,
        # …and whether it should be the one it starts on.
        "edit_only": m.edit_only,
        "default_lr": m.default_lr,
        "note": m.note,
        "lora_mb_per_rank": m.lora_mb_per_rank,
        "backbone_gb": m.backbone_gb,
        "aux_gb": m.aux_gb,
        "act_gb": m.act_gb,
        # Also the "does this model have a trainable text encoder" signal the
        # editor reads (0 = none) — without it every model looked like it had
        # none and the Train-text-encoder toggle was wrongly disabled.
        "te_act_gb": m.te_act_gb,
        # The large-encoder switch's two halves: what training only the small
        # encoder costs (0 = the switch does not apply to this model), and
        # the adapter's parameter counts for the optimizer term.
        "te_pooled_act_gb": m.te_pooled_act_gb,
        "te_params_m_per_rank": m.te_params_m_per_rank,
        "te_pooled_params_m_per_rank": m.te_pooled_params_m_per_rank,
        "ckpt_factor": m.ckpt_factor,
        # The CUDA pair, 0 where it has not been measured for this model.
        "act_gb_cuda": m.act_gb_cuda,
        "ckpt_factor_cuda": m.ckpt_factor_cuda,
        # How activations scale with the PIXEL COUNT. 1.0 = the linear rule
        # the editor applied before anyone measured one; 0 on the CUDA side
        # means "not measured", which falls back to the MPS figure exactly as
        # `act_gb_cuda` does.
        "act_exp": m.act_exp,
        "act_exp_cuda": m.act_exp_cuda,
        # What int8 actually leaves of the backbone and of the text encoders —
        # 0.5 for an all-Linear DiT, more for a UNet. See TrainModelSpec.
        "int8_scale": m.int8_scale,
        "int8_te_scale": m.int8_te_scale,
        # And for nf4, which reaches nowhere near its theoretical 0.25.
        "nf4_scale": m.nf4_scale,
        "nf4_te_scale": m.nf4_te_scale,
        "full_gb": m.full_gb,
        "user": False,
        "params": [
            {
                "name": p.name, "type": p.type, "default": p.default,
                "label": p.label, "hint": p.hint, "details": p.details,
                "min": p.min, "max": p.max, "choices": list(p.choices),
            }
            for p in m.params
        ],
    }


def adapter_family(key: str) -> str:
    """Which weights an adapter trained on `key` can be applied to.

    The built-in registry key, which for a user model is the one it declared
    itself based on. Two models share a family when they are the same network
    — an SDXL finetune and plain SDXL — and an adapter is exactly a set of
    deltas on that network's layers, so it fits any of them.

    NOT the engine: `flux2_klein` and its 9B sibling share an engine and are
    two different transformers, and an adapter for one loads into the other
    with every key rejected. An unknown key is its own family, so nothing is
    silently declared compatible with anything.
    """
    spec = model_spec(key)
    return (spec.base_key or spec.key) if spec is not None else key


def registry_out() -> list[dict]:
    """The built-in registry as JSON for ``GET /api/train/status``."""
    sizes = cache_sizes()
    return [registry_entry(m, sizes) for m in REGISTRY]

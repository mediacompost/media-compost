"""Training-job configuration schema.

``TrainingConfig`` is the single validated shape for a job's ``config.json``.
It is embedded verbatim in the API (create/update/detail), so backend and
frontend share one wire format. Dataset selection reuses the app's query
condition tree (``query.Group``) unchanged — the manager re-evaluates it with
the same evaluator the item grid uses when the job starts.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from media_compost import QueryGroup as Group
from .models import model_spec


class DatasetQuery(BaseModel):
    """One weighted pool of training items.

    ``tree`` is the parsed condition tree (None = whole library); ``search`` is
    the serialized query string, stored only so the frontend can round-trip the
    builder UI. ``weight`` is the relative probability of drawing a sample from
    this pool (a weight-2 pool is drawn from twice as often as a weight-1 one).
    """

    tree: Optional[Group] = None
    search: str = ""
    weight: float = Field(default=1.0, gt=0, le=1000)
    # A REGULARIZATION pool: pictures that are here to remind the model what
    # it already knows, not to teach it something new.
    #
    # The failure it exists to prevent is the characteristic one of training a
    # subject or a style — the model generalises the new thing onto the whole
    # class it belongs to. Train one character and every woman starts looking
    # like her; train one artist and the model loses the others. Showing it
    # ordinary examples of the same class alongside, with ordinary prompts,
    # is what holds the class in place.
    #
    # Two things follow, and both are automatic: such an entry NEVER carries
    # the trigger word (that word is for the new thing, and putting it here
    # would teach it to mean the ordinary thing), and its loss is scaled by
    # `TrainingConfig.reg_strength`. An item that is also in an ordinary pool
    # is NOT a regularization entry — being asked for by name wins.
    regularize: bool = False


class Hyperparams(BaseModel):
    steps: int = Field(default=2000, ge=1, le=1_000_000)
    # How long the run is, said the other way: full passes over the dataset.
    # 0 keeps `steps` as the length. Resolved to steps by the TRAINER, not
    # here — a pass is as long as the manifest is, and the manifest knows
    # things the editor cannot (a film's frames, a degraded copy, an item
    # contributing one entry per caption), so the count only exists once the
    # dataset has been materialized. The editor shows an estimate.
    epochs: int = Field(default=0, ge=0, le=10_000)
    lr: float = Field(default=1e-4, gt=0, le=1.0)
    lr_scheduler: Literal[
        "constant", "cosine", "linear", "constant_with_warmup"
    ] = "cosine"
    warmup_steps: int = Field(default=0, ge=0)
    batch_size: int = Field(default=1, ge=1, le=64)
    grad_accum: int = Field(default=1, ge=1, le=256)
    # WHICH KIND OF ADAPTER (ignored for a full finetune).
    #
    # "lora" adds a low-rank product to each targeted weight, so its capacity
    # is exactly its rank. "lokr" builds the change as a Kronecker product of
    # two much smaller matrices: the saving comes from that structure rather
    # than from discarding rank, so it is not confined to a thin slice of the
    # weight and the file is a fraction of the size — under a tenth at rank 8,
    # measured on a real UNet.
    #
    # A LoKr result is NOT a diffusers LoRA: that file layout has a place for
    # two matrices and nowhere to put a Kronecker factor, so no portable file
    # is written for one (see `BaseEngine.portable_supported`).
    network: Literal["lora", "lokr"] = "lora"
    # How a weight is split into the two Kronecker factors. -1 lets the
    # library pick the squarest split, which is the one that makes the factors
    # smallest — what anybody choosing LoKr for the size is after. LoKr only.
    lokr_factor: int = Field(default=-1, ge=-1, le=512)
    # WHICH LAYERS the adapter attaches to. Empty = every attention projection
    # the architecture exposes, which is what every run did before this
    # existed and is what an unset filter still means, exactly.
    #
    # Each entry is a plain substring matched against a module's full path
    # (`down_blocks.3.attentions.0…`), so one entry names a block, a family of
    # blocks by their shared prefix, or a single projection. `exclude` wins.
    #
    # Why it is worth having: training only part of the network is how a style
    # is learned without disturbing composition and anatomy, and it cuts the
    # trainable parameters (and so the optimizer state and the step time) with
    # it. The trainer REFUSES a filter that matches nothing — an adapter over
    # no layers trains happily and learns nothing, with an ordinary-looking
    # loss curve — and prints how many layers it kept.
    #
    # Applied to the image backbone ONLY. A text encoder's layers have
    # different names, so a filter written for one would silently match
    # nothing in the other.
    layer_include: list[str] = Field(default_factory=list)
    layer_exclude: list[str] = Field(default_factory=list)
    # LoRA-only (ignored for full finetune).
    rank: int = Field(default=16, ge=1, le=256)
    alpha: float = Field(default=16.0, gt=0, le=1024)
    precision: Literal["bf16", "fp16", "fp32"] = "bf16"
    seed: int = 42

    # Checkpoints: a permanent snapshot every N steps. Two INDEPENDENT
    # retention rules, and a snapshot survives if EITHER wants it —
    # ``checkpoint_keep`` newest ones (a window at the end of the run) and
    # every ``checkpoint_keep_every``-th one (milestones across the whole of
    # it). Keeping the last 5 of a 200-step cadence AND every 5th (i.e. every
    # 1000 steps) is the case the union exists for; 0 switches a rule off.
    # The newest snapshot always survives, and the resumable
    # ``checkpoints/last/`` is maintained besides and counts against neither.
    checkpoint_every: int = Field(default=500, ge=0)
    # The same cadence said in EPOCHS, which is what somebody thinking in
    # passes over their pictures wants ("keep one per epoch"). 0 leaves
    # ``checkpoint_every`` in charge; above 0 it wins, and the TRAINER
    # resolves it once the manifest says how many steps a pass takes — the
    # same reason ``epochs`` above is resolved there and not here.
    checkpoint_epochs: int = Field(default=0, ge=0, le=10_000)
    checkpoint_keep: int = Field(default=2, ge=0, le=50)
    checkpoint_keep_every: int = Field(default=0, ge=0, le=50)

    # Text-encoder training (LoRA only). Guarded against the classic
    # overtraining failure: its own (lower) learning rate, and it stops after
    # ``te_stop_ratio`` of the total steps while the backbone keeps training.
    # SD and SDXL train their CLIP encoder(s); FLUX.1 trains CLIP-L and
    # T5-XXL, Chroma its T5. The engines that condition on a language model
    # (FLUX.2, Z-Image, Qwen-Image) train none and the editor disables the
    # switch there (`te_act_gb == 0` in the registry).
    train_text_encoder: bool = False
    te_lr: float = Field(default=0.0, ge=0, le=1.0)  # 0 = lr * 0.5
    te_stop_ratio: float = Field(default=0.5, gt=0, le=1.0)
    # Whether the LARGE sequence encoder trains too, where a model has one
    # beside a small pooled encoder — FLUX.1's T5-XXL next to its CLIP-L.
    # Off, only CLIP-L trains: a fraction of a gigabyte, and what most FLUX
    # LoRA tooling means by "train the text encoder". On, T5's adapter
    # trains as well — several GB of activations per prompt at 512 tokens,
    # which is what the encoder-side gradient checkpointing and int8
    # quantization are for. Ignored by a model with no such pair: SD/SDXL
    # have no large encoder, and on Chroma T5 is the ONLY encoder, so the
    # engine refuses the off state rather than training nothing.
    train_text_encoder_large: bool = True

    # WEIGHT AVERAGING. Keep a smoothed second copy of everything being
    # trained — after each step it slides one `1 - ema_decay` of the way from
    # where it was towards where training has got to — and save THAT as the
    # checkpoints, the final result and the test samples. Training itself is
    # untouched; the average is written to and never read from until weights
    # are saved.
    #
    # What it buys is not having to be lucky about where a run stopped: the
    # quality curve across checkpoints flattens, and overtraining shows up
    # more slowly because an average lags. What it costs is one extra copy of
    # the trained parameters in full precision — nothing for a LoRA, a whole
    # second model for a full finetune, which the editor's estimate counts.
    #
    # The decay is the fraction of the old average kept per step, so 0.999
    # means the result reflects roughly the last thousand steps. The trainer
    # ramps it in from zero over the first steps (`ema.effective_decay`), or a
    # short run would save an average still holding its random initialisation.
    ema: bool = False
    ema_decay: float = Field(default=0.999, ge=0.5, lt=1.0)

    # Memory savers.
    gradient_checkpointing: bool = False
    # WHAT TURNS GRADIENTS INTO WEIGHT CHANGES, and mostly a memory choice.
    #
    # `adamw` keeps two running statistics the size of what is being trained;
    # `adamw_8bit` stores those at one byte each (bitsandbytes — NVIDIA, or
    # AMD under ROCm); `adafactor` replaces them with per-row and per-column
    # summaries, which is a far bigger saving and the only one that runs on
    # every backend, Apple silicon included.
    #
    # `prodigy` is the odd one out: it is not about memory but about the
    # learning rate, which it works out for itself from how far the weights
    # have travelled. With it, `lr` stops being a step size and becomes a
    # MULTIPLIER on what it found, so 1.0 is the neutral value — which is why
    # the editor sets it when this optimizer is picked, and why the trainer
    # warns when it is far from 1.
    optimizer: Literal["adamw", "adamw_8bit", "adafactor", "prodigy"] = "adamw"
    cache_latents: bool = True
    # HALF-PRECISION MASTER WEIGHTS, for a FULL FINETUNE — the one place the
    # weights are the run. A full run keeps fp32 masters (every parameter is
    # trainable, so `upcast_trainable` takes the whole backbone up) and does
    # its matmuls in bf16; on SDXL that is 10.2 GB of weights plus 10.2 GB of
    # gradients, against ~2 GB of frozen aux and Adafactor's ~0.05 GB of
    # state. This halves both.
    #
    # It needs KAHAN (compensated) SUMMATION to work at all, and that is not
    # a detail: a training step is far below one bf16 ulp, so rounded to
    # nearest every update vanishes and the weight never moves — measured
    # over a real (tiny) SDXL UNet at 300 AdamW steps, 46.5% of the weights
    # never moved at all. Carrying the remainder into the next update loses
    # nothing, only defers it: 0.471 against fp32 masters' 0.470 over those
    # same steps. The cost is the CARRY, a third buffer the width of the
    # weights, so the saving is a third rather than a half — which is why
    # the estimate takes 2 bytes a parameter off and not 4. Stochastic
    # rounding was the first answer and is gone; `scripts/kahan.py` has the
    # numbers that replaced it.
    bf16_masters: bool = False
    # Load the FROZEN base weights quantized and train the LoRA on top
    # (QLoRA-style). fp8 and int8 roughly halve the base-model memory, nf4
    # quarters it at some quality cost. Two different mechanisms: fp8 is a
    # plain torch dtype (Ada/Hopper NVIDIA GPUs; Apple silicon has no fp8 type
    # at all), int8/nf4 need bitsandbytes — NVIDIA, or AMD under ROCm when
    # the installed build supports it (the trainer probes rather than
    # assumes). The trainer refuses each where it cannot run instead of
    # silently training unquantized at a memory budget the user planned
    # around.
    quantization: Literal["none", "fp8", "int8", "nf4"] = "none"
    # Quantize the TEXT ENCODER(s) as well, in the same scheme. Its own switch
    # rather than part of the one above because the two shrink different terms
    # of the estimate — the backbone is `backbone_gb`, the encoders are most of
    # `aux_gb` — and on the big models the encoder is not a rounding error:
    # 16.8 GB of Qwen-Image's 57.7, 9.7 of Chroma's 27.5. Measured on an M4
    # Max, it takes a Qwen-Image LoRA run from 37.5 GB resident to 30.3.
    #
    # Off by default: it is the frozen weights the PROMPT is read with, so it
    # trades a little conditioning fidelity for memory, and a run that already
    # fits should not pay that silently.
    quantize_text_encoder: bool = False
    # Keep the FROZEN text encoder(s) on the CPU and embed each prompt there,
    # so their weights never occupy VRAM at all. The same trade the VAE
    # already gets for free — `after_latent_cache` parks it the moment every
    # latent is cached — which the encoder cannot have, because a prompt is
    # composed fresh per visit (tags shuffled, captions dropped) and so cannot
    # be cached per item the way a latent can.
    #
    # It is the LARGER saving of the two encoder settings and the more
    # complete: quantizing leaves a third of the weights resident, this leaves
    # none. What it costs is one CPU forward per step, which is memory-bound
    # rather than compute-bound at these batch sizes — measured on this
    # machine, see `docs/training.md`. Cannot be combined with training the
    # encoder, which is what `_check` refuses: gradients and an optimizer on
    # the CPU is not an offload, it is a much slower run.
    offload_text_encoder: bool = False
    # Compute attention in slices instead of all at once. Measured here: it
    # roughly halves a step's memory (SDXL 28 -> 16 GB, SD 1.5 5.7 -> 3.3 GB
    # per image) for ~10% more time on MPS, where nothing fuses attention
    # anyway. "auto" turns it on exactly there — on CUDA it would defeat the
    # fused kernels that make attention cheap in the first place.
    attention_slicing: Literal["auto", "on", "off"] = "auto"
    # A CEILING on what the run may allocate, in GB. 0 means "decide from the
    # device", and on a DISCRETE card that decision is to impose none.
    #
    # The two overshoots differ in kind. A card with its own VRAM already fails
    # correctly: cudaMalloc refuses, torch raises OutOfMemoryError, one job ends
    # and the machine is untouched — verified, a 60 GB request on a 32 GB card
    # raises catchably and leaves CUDA usable. A cap there could only refuse a
    # run that would have FIT, so there is not one.
    #
    # UNIFIED memory is the case that needs a ceiling, because the equivalent
    # overshoot is not an error at all: `recommended_max_memory()` sits ABOVE
    # physical RAM, so the run pages, and what happens is a machine that stops
    # responding — losing the run plus everything else the person was doing.
    # There the default is 0.9 of what the device reports.
    #
    # A figure above the device's own total is allowed deliberately: on a Mac
    # that is the only way to reach the machine's real RAM, and somebody who
    # types one has said what they mean.
    memory_budget_gb: float = Field(default=0.0, ge=0.0, le=4096.0)


#: How many sizes one run may train at. Each is another bucket family,
#: another entry per picture, another latent cache and another pass over
#: the dataset per epoch, so past a handful the number nobody is tracking is
#: how long an epoch became. The EDITOR holds a copy of this
#: (`frontend/src/train/util.ts`), so the list stops offering another size
#: rather than letting Save answer 400.
MAX_RESOLUTIONS = 5


def normalize_resolutions(values) -> list[int]:
    """The stored shape of the size list: whole numbers in range, no
    duplicates, smallest first, never empty.

    ONE DEFINITION, called by the validator and by the legacy fold — which
    produces the new key's value and therefore owes it the new key's shape,
    since `manager.read_config` hands the editor a plain dict and never
    builds the model. Nothing downstream may care whether 768 was named
    twice or in which order: the order fixes every index in the run's
    manifest and therefore what the trainer's seeded sampler draws.

    NAMING NOTHING IS NAMING THE MODEL'S OWN SIZE (the 0). An empty list
    would be a run that trains at no size at all, which is not a thing to
    let anybody save.
    """
    kept = sorted({int(r) for r in values if 0 <= int(r) <= 4096})
    return kept or [0]


class BucketConfig(BaseModel):
    #: THE SIZES THIS RUN TRAINS AT — a set, with no first among them.
    #:
    #: Each is a pixel BUDGET rather than a shape: the area is the number
    #: squared, and `make_buckets` spends it on the aspect ratios the
    #: pictures actually have. Each opens its own family of those buckets,
    #: and every picture contributes ONE ENTRY at each size it is big enough
    #: for (`dataset.Resolutions`).
    #:
    #: What it buys: a model that has only ever seen a subject at 1024 draws
    #: it as a 1024 composition, and asking for 640 gives a cropped or
    #: doubled version of the same framing. Training the same pictures at
    #: several sizes teaches the subject apart from the canvas it was learnt
    #: on. It is also the cheap way to keep small pictures in a
    #: high-resolution run — under `skip_upscale` a picture joins only the
    #: sizes it is big enough for, so a 700 px scan trains at 512 and sits
    #: out 1024 instead of being dropped from the run.
    #:
    #: **0 IS A MEMBER, AND IT MEANS THE MODEL'S OWN SIZE** — 1024 for SDXL,
    #: 512 for SD 1.5 — resolved by `TrainingConfig.resolutions()`, which is
    #: the only place that knows the model. It is the default, so a fresh
    #: job follows whatever model it is pointed at; and it stays a sentinel
    #: rather than being resolved on read, so changing a job's model still
    #: moves it.
    #:
    #: THERE IS NO FIRST AMONG THEM. One size was the run's own for a day,
    #: and nothing was ever true of it that was not true of the others — the
    #: trainer reads a per-entry bucket index and never the manifest's
    #: `resolution`, `skip_upscale` is asked per size, the frames are
    #: extracted against the LARGEST, the memory estimate reads the largest,
    #: and a test sample with no size of its own falls back to the model's
    #: native area rather than to any of this.
    resolutions: list[int] = Field(default_factory=lambda: [0])
    bucket_step: int = Field(default=64, ge=8, le=256)
    max_aspect: float = Field(default=2.0, ge=1.0, le=4.0)
    random_crop: bool = True  # False = center crop
    # NEVER UPSCALE: leave out any picture smaller than the bucket it would be
    # fitted to. Enlarging invents detail that was never photographed or drawn,
    # and a model taught on it learns the interpolation — soft edges and mushy
    # texture — as what the subject looks like. ON by default: the failure it
    # prevents is silent (a run that trains happily and produces a slightly
    # mushy model), while the failure it causes announces itself — the run
    # reports how many pictures it dropped, and the fix is to lower the base
    # resolution or turn this off.
    #
    # This default is also the FILL for a config that predates the key
    # (`read_config` → `_fill_defaults`), so flipping it changed what such a
    # job trains on. That was accepted deliberately rather than kept as a
    # second, older default: one setting with two answers depending on when
    # the job was made is the drift nobody can predict from the editor.
    skip_upscale: bool = True
    flip_p: float = Field(default=0.0, ge=0.0, le=0.5)
    # Tags that veto mirroring for the images that carry them, whatever
    # `flip_p` says: text, logos, a character whose scar is on one side. It
    # lets a dataset use flipping for the images it helps without hand-sorting
    # out the handful it would corrupt.
    no_flip_tags: list[str] = []
    # The same veto, one level up: any tag the LIBRARY marks with one of these
    # meta tags. A library that has said `noflip` once, on the tags it is true
    # of, never has to list them here again — and a tag added later carries
    # the rule with it. Resolved to names at manifest time (`dataset.py`), so
    # the trainer sees a per-entry flag and knows nothing about meta tags.
    no_flip_meta_tags: list[str] = []
    # Masked training: weight each latent cell's loss by how visible it was in
    # the source image's alpha channel, so a cut-out subject is learned without
    # its (absent) surroundings. Weights aren't spatial — what this masks is the
    # LOSS, not the parameters. `alpha_bg_weight` is what a fully transparent
    # cell still counts for: 0 ignores it entirely, 1 is the unmasked default.
    # A small non-zero value is the usual choice — it keeps some signal about
    # what plausibly surrounds the subject.
    alpha_mask: bool = False
    alpha_bg_weight: float = Field(default=0.1, ge=0.0, le=1.0)
    # MASKED REGIONS: down-weight the loss inside the bounding boxes of the
    # named tags — a watermark, a caption strip, a censor bar — so the run can
    # train on pictures that carry one without teaching the model to draw it.
    # The boxes are the ordinary tag boxes the annotator draws (a subject's
    # detected faces stand in where a tag has none), resolved per item when
    # the dataset is materialized; the trainer only ever sees rectangles.
    #
    # This masks the LOSS, exactly as the alpha mask above does — the pixels
    # still reach the encoder, so the cached latents are unchanged and shared
    # with unmasked runs. The two masks multiply where both apply.
    mask_loss_tags: list[str] = Field(default_factory=list)
    # The same rule, one level up: every tag the LIBRARY marks with one of
    # these meta tags. Stated once in the Tags tab, it covers tags added
    # after this job was written. Resolved to names at manifest time.
    mask_loss_meta_tags: list[str] = Field(default_factory=list)
    # What a masked cell still counts for: 0 hides the region entirely, a
    # small value keeps a whisper of it. 1 is the unmasked loss.
    mask_loss_weight: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _normalize_resolutions(self) -> "BucketConfig":
        # Settled here so the config on disk, the editor and the run cannot
        # disagree about it (`normalize_resolutions` says what the shape is).
        kept = normalize_resolutions(self.resolutions)
        # Counted AFTER the dedupe, because the cap is about how many sizes
        # the run actually trains at — a list naming 768 twice is one.
        if len(kept) > MAX_RESOLUTIONS:
            raise ValueError(
                f"at most {MAX_RESOLUTIONS} resolutions (this names "
                f"{len(kept)}) — each one is another full pass over the "
                "dataset per epoch")
        self.resolutions = kept
        return self

    @model_validator(mode="after")
    def _normalize_mask(self) -> "BucketConfig":
        # Weighting the background at 1 IS the unmasked loss, so settle that
        # here rather than in the trainer: masked runs feed the encoder
        # different pixels and therefore use a separate latent cache, and the
        # manifest builder must not send a no-op run down that path — it would
        # fill those cache entries with unfilled pixels for the next real
        # masked job to reuse.
        if self.alpha_bg_weight >= 1.0:
            self.alpha_mask = False
        # A masked-region weight of 1 IS the unmasked loss — settle it here
        # for the same reason, so the manifest builder never resolves boxes
        # for a rule that cannot change anything.
        if self.mask_loss_weight >= 1.0:
            self.mask_loss_tags = []
            self.mask_loss_meta_tags = []
        return self


class VideoConfig(BaseModel):
    """Videos as training images. OFF by default — a video item is not one
    picture, and a run that silently unpacked films into thousands of frames
    would be nothing like the dataset its queries describe.

    With it on, every matched video is sampled while the dataset is
    materialized: the frames are written into the job's own folder, trained on
    as ordinary images, and deleted with the run. Each frame carries the
    video's untimed tags plus the timed ones whose range covers its moment,
    and whichever of its captions this config says describe a frame rather
    than the film.
    """

    include: bool = False
    # One frame every `every` `unit`s. Seconds is the natural interval — time
    # ranges are in seconds and a frame rate varies between files — but a short
    # clip is easier to think about in frames.
    every: float = Field(default=1.0, gt=0, le=3600)
    unit: Literal["seconds", "frames"] = "seconds"
    # Drop a sampled frame that repeats one already kept from the same video.
    # A held shot is one picture however long it is on screen, and without this
    # a title card can outweigh everything the film actually shows.
    dedupe: bool = True
    # WHAT A FRAME DOES WITH THE FILM'S CAPTIONS. A caption sits on the video
    # item, so a frame can only inherit ALL of them or none — and plenty of
    # captions describe the film rather than any one moment of it ("a fight
    # scene set to music", "episode three, the beach"). Training a still
    # against one teaches the model to draw what a sentence says happens over
    # minutes. A tag has time ranges to say when it holds; a caption has not,
    # so this is where a film says which of its captions describe its frames.
    #
    # "inherit" is what a frame has always done. "none" leaves every frame
    # captionless, which costs nothing on a tags run and means the film
    # contributes no frames at all on a captions run — a frame with nothing to
    # say is left out rather than trained on an empty prompt, exactly as an
    # uncaptioned picture is.
    captions: Literal["inherit", "none"] = "inherit"
    # …and WHICH of them, by META TAG, exactly as `CaptionConfig` picks the
    # run's captions. Applied ON TOP of that filter rather than instead of it:
    # the run-wide lists say which captions this run may train on at all and
    # these say which of those a FRAME inherits, so a caption the run excludes
    # can never come back through a film. Empty include = every caption that
    # got this far; exclude wins; matching is case-insensitive.
    caption_include_meta_tags: list[str] = Field(default_factory=list)
    caption_exclude_meta_tags: list[str] = Field(default_factory=list)


#: Where a query's weight is spent. Both mean the same ratio; they differ in
#: what they spend it on — see `compose.Sampler`.
WeightMode = Literal["sampling", "loss"]


class ValueRule(BaseModel):
    """One prompt rule over VALUE tags: where ``<namespace>`` is
    ``<op> <value><unit>``, write ``<text>``.

    A raw ``height:172cm`` token teaches nothing a text encoder can read, so
    a matching value tag is REPLACED by the rule's text at prompt composition
    (``keep_raw`` keeps the raw tag alongside for whoever wants it). Ranges
    may overlap; the FIRST matching rule wins, so the list's order is part of
    the configuration. A value tag no rule matches passes through unchanged —
    visible behavior, never silent dropping.

    Resolved at manifest time (`dataset._value_map`) into a finished
    tag-name → text map, so the trainer never learns what a value is —
    the `MetaTagResolver` pattern. Comparison is exact (no typed-decimals
    tolerance): a rule is configuration, not a search someone typed, and
    ranges are what the ordered operators are for.
    """

    namespace: str = ""
    op: Literal["=", "!=", ">", ">=", "<", "<="] = ">="
    value: float = 0.0
    unit: str = ""
    text: str = ""
    keep_raw: bool = False


class CaptionConfig(BaseModel):
    # "instructions" trains an EDIT model: the prompt is one of the item's
    # instructions and the item's own picture is the result the model must
    # produce from the instruction's reference images.
    #
    # It is a value of this one enum rather than a flag beside it, because that
    # is what makes the exclusion true by construction: an instruction run
    # selects only `kind == "instruction"` and every other source only
    # `kind == "caption"`, so no run can mix a description with an imperative
    # — which is the whole reason the two are separate kinds.
    # "none" is the TRIGGER ALONE: no tags, no caption, nothing the item
    # says about itself — which is how a trigger is taught to mean the
    # pictures rather than to modify what a prompt already said. It is also
    # the only source under which every selected picture is in the run
    # whatever it carries, since there is nothing it could be missing.
    source: Literal["captions", "tags", "both", "instructions",
                    "none"] = "tags"
    trigger: str = ""
    # Which of an item's captions may be used, by META TAG (the link/caption
    # namespace, not the item's own tags). An item usually has several captions
    # — a short one and a long one, a German translation, a machine draft — and
    # these pick the ones this run trains on. Empty include = every caption
    # qualifies; exclude wins over include; matching is case-insensitive.
    # Applied when the dataset is materialized, so the trainer only ever sees
    # the captions that survived. Applies to instructions too: they carry the
    # same meta tags, and "an item has several and this run wants one kind of
    # them" is exactly the problem this solves.
    # What an item with SEVERAL captions does with them.
    #
    # "random" is one visit, a different caption drawn each time — the whole
    # set is seen across a long run, and an item counts once however many
    # captions it has.
    #
    # "each" is one visit PER caption, so every caption is used every pass —
    # and an item with ten of them is therefore seen ten times, which is
    # usually an accident of tooling (a machine draft, a manual rewrite, a
    # translation) rather than a statement that the picture matters ten times
    # as much.
    #
    # "each_shared" is that with the accident removed: every caption still
    # gets its visit, and the visits SPLIT one item's worth of gradient
    # between them, so a ten-caption item teaches as much as a one-caption
    # item — just about ten different ways of saying it.
    caption_repeat: Literal["random", "each", "each_shared"] = "random"
    include_meta_tags: list[str] = Field(default_factory=list)
    exclude_meta_tags: list[str] = Field(default_factory=list)
    # Tags that are never dropped by the random pick — but only when the item
    # actually HAS the tag (e.g. "watermark" is always in the prompt of
    # watermarked images, and never forced onto clean ones).
    always_tags: list[str] = Field(default_factory=list)
    exclude_tags: list[str] = Field(default_factory=list)
    # THE SAME TWO, NAMED BY WHAT THE LIBRARY SAYS ABOUT A TAG rather than by
    # the tag. A meta tag put on the tag set once ("noprompt", "always")
    # then applies to every tag carrying it, including ones made later.
    #
    # They are UNIONED with the lists above at manifest time, not a second
    # mechanism: `dataset.py` resolves each to tag names and the trainer's
    # `compose` reads one list per rule, exactly as it always has.
    always_tag_meta_tags: list[str] = Field(default_factory=list)
    exclude_tag_meta_tags: list[str] = Field(default_factory=list)
    # Prompt rules over VALUE tags (`height:172cm`): first match wins, order
    # is part of the configuration, an unmatched value tag passes through
    # unchanged. See `ValueRule`.
    value_rules: list[ValueRule] = Field(default_factory=list)
    # Whole per-item TAG GROUPS to ignore, named by the group's meta tag. A tag
    # is dropped only when EVERY placement of it sits in an excluded group — a
    # tag that is also ungrouped, or in a group that was not excluded, is still
    # on the item by a route the user did not exclude. Ancestors that were only
    # implied by dropped tags go with them, or the exclusion half-works.
    exclude_tag_group_meta_tags: list[str] = Field(default_factory=list)
    # Random pick per visit: at least min_tags (when available), at most
    # max_tags (0 = all remaining). Re-picked fresh every time an item is drawn.
    min_tags: int = Field(default=0, ge=0)
    max_tags: int = Field(default=0, ge=0)
    balance: Literal["none", "inverse_freq"] = "none"
    # Where a tag's rarity is measured: within the selected images, or over
    # every item the run's scope COULD have selected.
    freq_base: Literal["dataset", "library"] = "dataset"
    # HOW A PICKED TAG IS WRITTEN into the prompt: its name (what every run
    # did), its COMMENT — the one-line note beside the name in the tags list,
    # "one girl in the picture" for `1girl` — or the name with the comment in
    # brackets after it. A comment is what the tag MEANS in words a text
    # encoder can read; a tag with no comment is written as its name whatever
    # this says. Only the PROMPT changes: matching, balancing, the loss weight
    # and the boxes stay keyed on the name, the alias substitution's rule.
    # Resolved at manifest time into a tag → comment map (`dataset.
    # _tag_comments`), so the trainer never reads the library.
    tag_text: Literal["name", "comment", "both"] = "name"

    loss_weight_by_freq: bool = False
    shuffle: bool = True
    dropout: float = Field(default=0.0, ge=0.0, le=0.5)
    # How often a picked tag is WRITTEN as one of its aliases instead of its
    # canonical name. A library's aliases are the other words for one thing
    # ("cat" / "kitty" / "feline"), and a model trained only on the canonical
    # name answers only to that word at generation time. 0 keeps every prompt
    # on the canonical names, which is what every run did before this existed.
    #
    # Rolled PER TAG PER VISIT, so the same item drawn twice reads differently
    # and the model sees the whole tag set spread across the run rather than
    # one alias per tag chosen once.
    alias_p: float = Field(default=0.0, ge=0.0, le=1.0)
    # Prompt formatting: booru-style tags carry underscores, but text encoders
    # were trained on natural language — writing them out with spaces is the
    # usual choice. Matching (always/exclude lists) stays on the raw names.
    underscores_to_spaces: bool = True
    separator: str = Field(default=", ", max_length=8)
    # Lay the picked tags out by the TAG GROUP they sit in, one block per group,
    # instead of one flat comma list. A group is usually about one thing in the
    # picture (Alice's hair and dress), and a flat list leaves the model to
    # guess which adjective belongs to whom.
    group_tags: bool = False
    # What each block is labelled with. "none" by default: plenty of libraries
    # name groups for the person tagging, not for the model. "subject" uses the
    # subjects the group is ABOUT, which is usually the thing you would type at
    # generation time ("Alice") where the group's own name is bookkeeping
    # ("front figure"). A group with no subjects gets no label rather than a
    # silent fallback to its name — the choice said what to write.
    group_label: Literal["none", "group", "subject"] = "none"
    # Between blocks. A newline by default — that is what makes them read as
    # separate statements rather than a longer list.
    group_separator: str = Field(default="\n", max_length=8)
    # Drop a picked tag that is a whole-word part of ANOTHER picked (or
    # guaranteed) tag — "shirt" next to "white shirt" — and draw a different
    # random tag in its place, so prompts never teach the generic tag and its
    # specific variant as one clump.
    skip_partial_tags: bool = True


class IntRange(BaseModel):
    """A closed range a value is drawn from.

    ``lo == hi`` is a fixed value, which is what makes "one number" a special
    case of the general shape rather than a second shape to support everywhere.
    The ends are sorted rather than refused: the editor renders two fields side
    by side, and typing the bigger one first is a keystroke, not a mistake.
    """

    lo: int = 0
    hi: int = 0

    @model_validator(mode="after")
    def _order(self) -> "IntRange":
        if self.lo > self.hi:
            self.lo, self.hi = self.hi, self.lo
        return self


class FloatRange(BaseModel):
    lo: float = 0.0
    hi: float = 0.0

    @model_validator(mode="after")
    def _order(self) -> "FloatRange":
        if self.lo > self.hi:
            self.lo, self.hi = self.hi, self.lo
        return self


class DegradeVariant(BaseModel):
    """One way of making a picture look worse, as an EXTRA training sample.

    A degraded picture never replaces its original: the clean entry keeps its
    full sampling weight and each variant adds a further entry beside it. The
    dataset gains rows rather than trading them, so no run can quietly train on
    fewer good pictures than were selected.

    Every numeric parameter is a range the value is drawn from. A dataset where
    every degraded picture sits at exactly q30 teaches one artifact strength;
    one spanning a range teaches the axis.
    """

    name: str = ""       # UI label only; never part of the cache key
    method: Literal["jpeg", "video", "resize"] = "jpeg"
    # How often this variant's entry is drawn RELATIVE to the clean entry,
    # which always keeps 1.0. 0.25 = one degraded visit per four clean ones.
    # Not a probability: it ADDS exposure rather than taking it from the
    # original.
    weight: float = Field(default=0.25, ge=0.0, le=4.0)
    # Always in this entry's prompt — never subject to the random tag pick, the
    # min/max cap, `exclude_tags`, or caption dropout.
    tags: list[str] = Field(default_factory=list)
    # Taken OFF this entry when the item carries them: the quality claims the
    # degraded copy no longer supports ("masterpiece", "absurdres"). Only ever
    # this entry — the clean one keeps every one of them. Per variant and not
    # per run, because the methods take different claims away: `resize`
    # destroys resolution while `jpeg` leaves it alone and destroys fidelity.
    remove_tags: list[str] = Field(default_factory=list)
    # Which pictures this variant may touch at all. Empty `require` means every
    # picture; otherwise the item must carry at least ONE of them. `skip` wins
    # over `require` — the direction CaptionConfig's include/exclude pair sets.
    require_tags: list[str] = Field(default_factory=list)
    skip_tags: list[str] = Field(default_factory=list)
    # The same three, by what the LIBRARY says about a tag rather than by the
    # tag. Resolved to names at manifest time and unioned with the lists above,
    # so every rule keeps exactly one implementation.
    remove_tag_meta_tags: list[str] = Field(default_factory=list)
    require_tag_meta_tags: list[str] = Field(default_factory=list)
    skip_tag_meta_tags: list[str] = Field(default_factory=list)
    # How many separately-drawn entries each image gets for this variant. 1 =
    # one value per picture (the dataset still spans the range, because the
    # draw is per file); higher spreads one picture across the range, at a
    # directly proportional cache cost.
    #
    # It does NOT change how often the variant is drawn: `weight` is SPLIT
    # across the variations. Otherwise a knob about variety and disk would
    # silently retune the training mix.
    variations: int = Field(default=1, ge=1, le=8)
    # Re-apply the whole thing N times — a re-save of a re-save.
    passes: IntRange = Field(default_factory=lambda: IntRange(lo=1, hi=1))
    # jpeg
    quality: IntRange = Field(default_factory=lambda: IntRange(lo=20, hi=60))
    subsampling: Literal["4:4:4", "4:2:2", "4:2:0"] = "4:2:0"
    # video
    codec: Literal["h264", "h265"] = "h264"
    crf: IntRange = Field(default_factory=lambda: IntRange(lo=26, hi=38))
    # resize — down and back UP. It is resolution *loss*, not a smaller
    # picture: keeping the size identical is what lets the entry share its
    # source's bucket and bounding boxes untouched.
    scale: FloatRange = Field(default_factory=lambda: FloatRange(lo=0.35, hi=0.75))
    resample: Literal["nearest", "bilinear", "bicubic", "lanczos"] = "bilinear"

    @model_validator(mode="after")
    def _bounds(self) -> "DegradeVariant":
        for field, rng, lo, hi in (
            ("passes", self.passes, 1, 10),
            ("quality", self.quality, 1, 100),
            ("crf", self.crf, 0, 63),
            ("scale", self.scale, 0.05, 1.0),
        ):
            if rng.lo < lo or rng.hi > hi:
                raise ValueError(f"{field} must stay within {lo}–{hi}")
        both = sorted(set(self.tags) & set(self.remove_tags))
        if both:
            # Incoherent, so refuse rather than rank one over the other.
            raise ValueError(f"{both} is both added and removed")
        return self


class DegradeConfig(BaseModel):
    variants: list[DegradeVariant] = Field(default_factory=list)

    @model_validator(mode="after")
    def _normalize(self) -> "DegradeConfig":
        # A weightless variant is off; an UNTAGGED one is an unmarked bad
        # picture in the dataset, which is the one outcome this must never
        # produce. Dropped rather than refused, so a half-written row in the
        # editor does not block a save. (The BucketConfig._normalize_mask
        # precedent: a setting that would do nothing normalizes itself off, so
        # the manifest builder never goes down the extra-entries path for it.)
        self.variants = [v for v in self.variants if v.weight > 0 and v.tags]
        return self


class NoiseConfig(BaseModel):
    """WHICH NOISE LEVELS a run trains on.

    Every step picks one point between a clean picture and pure noise, adds
    that much noise, and asks the model to undo it. The two ends teach
    different things — high noise decides LAYOUT (there is nothing but a vague
    shape to work with), low noise decides DETAIL and TEXTURE (the composition
    is already fixed) — so where a run spends its steps decides what it is
    mostly teaching.

    "default" is the model family's own choice and is what every run did
    before this existed, bit for bit (see `timesteps.is_family_default`): the
    older models pick evenly, the flow-matching ones from a bell curve centred
    on the middle. The other strategies mean the same thing for both families.
    """

    timesteps: Literal["default", "uniform", "logit_normal", "cosmap"] = \
        "default"
    # Where the bell curve's centre sits, for "logit_normal". 0 is the middle
    # of the range; positive leans towards high noise (composition) and
    # negative towards low noise (detail). ~±1 is a substantial lean.
    logit_mean: float = Field(default=0.0, ge=-4.0, le=4.0)
    # How wide it is. Smaller concentrates the run on a narrow band around the
    # centre; larger spreads it towards both extremes.
    logit_std: float = Field(default=1.0, gt=0.0, le=4.0)


class ValidationConfig(BaseModel):
    """A loss the run cannot flatter.

    The training loss is drawn from the pictures being trained on, at random
    noise levels, so it is noisy by construction and it keeps falling for as
    long as the model memorizes — it cannot say when a run starts overfitting.
    Two extra series answer that, both scored with the PLAIN per-sample loss
    (no frequency weighting, no query weights, no regularization scaling) and
    a fixed seed, so every round asks exactly the same question:

    * ``holdout`` images are HELD OUT of training entirely — never visited,
      never in any pool — and scored at the cadence. That is the validation
      loss: it falls while the model generalizes and turns when it starts
      memorizing.
    * ``stable_items`` are ordinary TRAINING images, scored the same fixed
      way. That is the "stable training loss": the training curve with the
      sampling noise removed, readable where the per-step loss is a cloud.

    ``every_n_steps`` 0 switches the whole thing off, which is what every
    run did before this existed — byte for byte.
    """

    every_n_steps: int = Field(default=0, ge=0)
    # Whole IMAGES (an item's degraded copies and extra caption entries go
    # with it — a picture half in training and half in validation would leak).
    # Clamped at materialization so a small dataset is never eaten: at most
    # half the eligible images are held out, and the job log says how many.
    holdout: int = Field(default=16, ge=0, le=10_000)
    stable_items: int = Field(default=0, ge=0, le=10_000)
    # Seeds the noise, the timesteps, the crops and the prompt picks of every
    # evaluation round — fixed, or the series measures the dice rather than
    # the model. Separate from ``hyper.seed`` so extending a run's steps
    # never changes what the validation rounds ask.
    seed: int = 42


class SamplePrompt(BaseModel):
    """One test-sample slot: a prompt with its OWN negative prompt, and
    optionally its own size (0 = use the section's shared size, which in turn
    falls back to the training resolution). Per-prompt sizes let one run check
    a portrait character and a wide scene in the same timeline."""
    prompt: str = ""
    negative: str = ""
    width: int = Field(default=0, ge=0, le=4096)
    height: int = Field(default=0, ge=0, le=4096)


class SampleConfig(BaseModel):
    every_n_steps: int = Field(default=0, ge=0)  # 0 = off
    # The same cadence said in EPOCHS — the checkpoint cadence's rule one
    # section along, and for the same reason: "one round of samples per pass
    # over my pictures" is a rhythm that carries between datasets where a
    # step count does not. 0 leaves ``every_n_steps`` in charge; above 0 it
    # wins, and the TRAINER resolves it once the manifest says how many
    # steps a pass takes — a pass is as long as the manifest is, and only
    # the manifest knows a film's frames or an item contributing one entry
    # per caption. Sampling is OFF only when both are 0.
    every_n_epochs: int = Field(default=0, ge=0, le=10_000)
    # Also render the prompts BEFORE the first step (an untrained baseline at
    # step 0 to compare training progress against).
    at_start: bool = False
    prompts: list[SamplePrompt] = Field(default_factory=list)
    seed: int = 42
    steps: int = Field(default=25, ge=1, le=150)
    cfg: float = Field(default=6.0, ge=0.0, le=30.0)
    # How many sample prompts are rendered in one pipeline call. Only prompts
    # of the SAME size can share a call, so a set with mixed sizes batches
    # within each size.
    batch: int = Field(default=1, ge=1, le=8)
    width: int = Field(default=0, ge=0, le=4096)   # 0 = model default
    height: int = Field(default=0, ge=0, le=4096)


class TrainingConfig(BaseModel):
    model: str = "sdxl"  # key into models.REGISTRY
    # Optional local weights: a diffusers folder or a single .safetensors
    # checkpoint. When set it replaces the registry's HF repo.
    local_path: str = ""
    method: Literal["lora", "full"] = "lora"
    # Start from an existing adapter instead of a fresh one: the path of a
    # CHECKPOINT DIRECTORY (picked from a finished job in the UI) holding the
    # trainer's own weights file. Ignored for full finetunes. It has to match
    # the run's network type, rank and layer targeting — the trainer says so
    # by name when it does not.
    init_lora: str = ""
    # Which GPU runs the job: "auto" (the machine's first device) or an id
    # from the Train tab's device list ("cuda:1", "mps", "cpu"). One job runs
    # per device — the queue starts a job only when its device is free.
    gpu: str = Field(default="auto", pattern=r"^(auto|cpu|mps|cuda:\d+)$")
    hyper: Hyperparams = Field(default_factory=Hyperparams)
    queries: list[DatasetQuery] = Field(default_factory=list)
    # What a query's weight buys. "sampling" spends it on VISITS — a weight-2
    # query's pictures are seen twice as often, so it costs the run steps that
    # the other pictures do not get. "loss" spends it on the GRADIENT: every
    # picture is seen exactly once a pass and a weighted one simply counts for
    # more. Same ratio, and the second is the one that does not trade coverage
    # for emphasis.
    weight_mode: WeightMode = "sampling"
    # HOW MUCH a regularization entry counts, as a multiplier on its loss.
    # 1.0 gives it the same say as a training picture, which is the classic
    # setting; lower makes it a gentler reminder. It has nothing to say when
    # no pool is marked `regularize`, and the editor only shows it then.
    #
    # Separate from a pool's `weight`, which decides how OFTEN its pictures
    # are visited: how often and how much are different questions, and a reg
    # set is usually wanted often but quietly.
    reg_strength: float = Field(default=1.0, ge=0.0, le=10.0)
    buckets: BucketConfig = Field(default_factory=BucketConfig)
    noise: NoiseConfig = Field(default_factory=NoiseConfig)
    captions: CaptionConfig = Field(default_factory=CaptionConfig)
    video: VideoConfig = Field(default_factory=VideoConfig)
    degrade: DegradeConfig = Field(default_factory=DegradeConfig)
    sampling: SampleConfig = Field(default_factory=SampleConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    # Values for the model's registry-declared extra fields (models.FieldSpec).
    model_params: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> "TrainingConfig":
        spec = model_spec(self.model)
        if spec is None:
            raise ValueError(f"unknown model {self.model!r}")
        # THE 0 AND THE NUMBER IT RESOLVES TO ARE ONE SIZE, and this is the
        # only level that can tell — `BucketConfig` is handed no model, so
        # its own normalizer sees two different members. `resolutions()`
        # dedupes on read either way, so the run was never wrong; what this
        # settles is the STORED list, which is what the cap counts and what
        # the editor draws. The 0 survives and the number goes: the sentinel
        # is the more general answer, and it is what the picker writes.
        sizes = self.buckets.resolutions
        if 0 in sizes and spec.default_area in sizes:
            self.buckets.resolutions = [r for r in sizes
                                        if r != spec.default_area]
        if self.method == "full" and spec.lora_only:
            raise ValueError(
                f"{spec.label} is too large to finetune fully — it can "
                f"be trained as an adapter (LoRA or LoKr) only")
        # Refused here rather than at materialization: it is decidable from the
        # config alone, so the editor's save says no instead of the run dying
        # hours later with a prompt the model has no reference image for.
        if self.captions.source == "instructions" and not spec.edit:
            raise ValueError(
                f"{spec.label} cannot train on instructions — it is not an "
                f"image-editing model"
            )
        if (self.captions.min_tags and self.captions.max_tags
                and self.captions.min_tags > self.captions.max_tags):
            raise ValueError("min_tags must not exceed max_tags")
        # Degrading the TARGET of an edit while its reference pictures stay
        # pristine teaches the model to ADD compression artifacts to an edit —
        # the same reason flip and random crop are not offered for these runs.
        # Refused here rather than at materialization: it is decidable from the
        # config alone.
        if self.captions.source == "instructions" and self.degrade.variants:
            raise ValueError(
                "an instruction run cannot degrade its pictures — the "
                "degradation would apply to the result and not to the "
                "references it is made from"
            )
        # HALF-PRECISION MASTERS ARE A FULL-FINETUNE SETTING, and refused
        # elsewhere rather than ignored, because a setting that quietly did
        # nothing would be worse than one that says why.
        #
        # WHETHER IT COULD WORK IS NOT THE QUESTION ANY MORE. It could:
        # Kahan summation is what makes half-precision masters learn at all
        # (`scripts/kahan.py` — nothing is lost, only deferred until it is
        # large enough to change the stored value), and it would apply to an
        # adapter's weights exactly as it does to a backbone's. The
        # STOCHASTIC ROUNDING this refusal used to cite is gone with the
        # design that needed it.
        #
        # What settles it is the size. The saving is 2 bytes a TRAINABLE
        # parameter, and an adapter's trainable set is the adapter: at rank
        # 16 that is 6 MB on SD 1.5, 44 on SDXL, 90 on Qwen-Image — 24, 177
        # and 360 at rank 64 — against runs this same editor estimates in
        # tens of gigabytes. A tenth of a percent of a run is not worth a
        # second code path through the one component the run is about.
        if self.hyper.bf16_masters and self.method == "lora":
            raise ValueError(
                "half-precision master weights are for a full finetune — a "
                "LoRA's trained weights are the adapter, and halving those "
                "saves tens of megabytes out of tens of gigabytes"
            )
        # …and there is nothing to halve at fp32: the masters ARE the compute
        # dtype there, so the setting would silently mean "train at bf16".
        if self.hyper.bf16_masters and self.hyper.precision == "fp32":
            raise ValueError(
                "half-precision master weights need a 16-bit compute "
                "precision — at fp32 there is no second copy to shrink"
            )
        # Prodigy derives ONE learning rate across every parameter, so the
        # per-parameter step this needs (see `kahan.py`: the fp32 buffer
        # is one tensor rather than the model, which is the entire saving)
        # would hand it a different problem each time. Refused by name rather
        # than left to produce a plausible-looking curve.
        if self.hyper.bf16_masters and self.hyper.optimizer == "prodigy":
            raise ValueError(
                "Prodigy works its learning rate out across all the "
                "parameters at once, so it cannot be stepped one at a time — "
                "pick another optimizer, or turn half-precision masters off"
            )
        # QUANTIZATION AND A FULL FINETUNE ARE A CONTRADICTION, not a gap in
        # the backends. A quantized weight is STORED at one byte (or half of
        # one) and dequantized per matmul; it is not a trainable parameter and
        # there is no gradient path back to the stored value — bitsandbytes'
        # `Params4bit`, quanto's and torchao's QLinear are all built that way,
        # on every device. QLoRA works precisely BECAUSE the quantized base is
        # frozen and a separate full-precision adapter carries the learning. A
        # full finetune trains every backbone weight, which is exactly the set
        # quantization would freeze — so the pair describes a run in which
        # nothing can learn, and it would not fail, it would train an
        # ordinary-looking loss curve over an unchanged model.
        #
        # The editor has always said so and disabled the row; this is the
        # backstop for a stored config or a script, which reached the loader
        # instead and quantized the very weights the optimizer was about to
        # be handed.
        if self.method != "lora" and self.hyper.quantization != "none":
            raise ValueError(
                "a full finetune trains the base weights, so there is "
                "nothing to quantize — quantization freezes exactly what "
                "this run is meant to update. Train a LoRA to quantize the "
                "base, or turn quantization off"
            )
        # A quantized text encoder MAY be trained: its own weights stay
        # frozen at one byte, and the adapter trains in full precision over
        # them — the same QLoRA the backbone has always been. It used to be
        # refused here, which is exactly what kept T5-XXL training off any
        # card under 48 GB. (Offloading is still refused below: a quantized
        # encoder is on the card, an offloaded one is not.)
        if self.hyper.quantize_text_encoder and self.hyper.quantization == "none":
            raise ValueError(
                "text-encoder quantization needs a quantization scheme — set "
                "the base model quantization, or turn this off"
            )
        # Same shape of refusal, same section of the editor: an encoder on the
        # CPU cannot be the encoder being trained. Gradients and an optimizer
        # over 5-16 GB of parameters on the CPU is not an offload, it is a
        # different and far slower run — and one nobody asked for by ticking
        # a box labelled "keep this off the GPU".
        if self.hyper.offload_text_encoder and self.hyper.train_text_encoder:
            raise ValueError(
                "a text encoder kept on the CPU cannot be trained — turn off "
                "either text-encoder offloading or text-encoder training"
            )
        return self

    def resolutions(self) -> list[int]:
        """EVERY size this run trains at, smallest first, resolved.

        The 0 the config may hold is the model's own size — which only this
        level knows, since `BucketConfig` is handed no model — and it is
        folded in here rather than on read, so pointing a job at a different
        model still moves it. Deduped afterwards: a list naming both 0 and
        1024 against an SDXL job names one size twice.
        """
        native = model_spec(self.model).default_area
        return sorted({r or native for r in self.buckets.resolutions})

    def resolution(self) -> int:
        """The run's size, for the one place that still wants a single
        number: `manifest["resolution"]`, which is written for whoever reads
        a manifest and which the trainer does not consult (it batches by a
        per-entry bucket index).

        The LARGEST, because that is the one the run costs what it costs
        for — the peak memory, the slowest step — and because with one
        resolution it is that resolution, which is what keeps every manifest
        recorded before the sizes became a list byte-identical.
        """
        return self.resolutions()[-1]

    def ready_to_queue(self) -> Optional[str]:
        """None when the config can be queued, else a human-readable reason."""
        if not self.queries:
            return "add at least one item query (the training data)"
        if not any(not q.regularize for q in self.queries):
            return ("at least one query has to be training images — a run of "
                    "nothing but regularization images has nothing to learn")
        if (self.sampling.every_n_steps or self.sampling.every_n_epochs) \
                and not any(p.prompt.strip()
                            for p in self.sampling.prompts):
            return "test sampling is on but no prompts are set"
        return None

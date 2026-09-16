"""The wire models for the training routes.

They were the tail of the app's `server/schemas.py`, imported there at module
level — which made the FastAPI schema module hard-depend on the whole training
subsystem, in a build where training may not be installed at all.

`RequestModel` is declared here rather than borrowed from the app: after the
UI is carved into its own package, importing it would make the trainer depend
on the app, which is the one thing this split exists to prevent.

Two base classes is a risk worth naming: the rule they encode was learned the
hard way. Pydantic IGNORES an unknown key by default, so a caller spelling a
body field wrong gets the field's default and a 200 — on `POST
/api/items/query` that once meant a request for "the portraits" was answered
with the whole library. `tests/train/test_request_models_are_strict.py` walks
these routes and holds every body model to it, so the rule is enforced rather
than remembered.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class RequestModel(BaseModel):
    """A model that is a REQUEST BODY, and therefore refuses unknown fields."""

    model_config = {"extra": "forbid"}


from ..spec import DegradeVariant, TrainingConfig

class TrainingJobOut(BaseModel):
    uid: str
    name: str
    username: str = ""
    # draft | queued | running | pausing | paused | completed | failed | canceled
    status: str
    step: int = 0
    total_steps: int = 0
    message: str = ""
    # Trainer-reported phase while running (preparing | caching_latents |
    # training | sampling | …); "" otherwise.
    phase: str = ""
    # A short line about that phase — "62 / 162" while latents are cached, the
    # model repo while it loads. The phases before step 1 can run for many
    # minutes; this is what the app has to show for them.
    phase_note: str = ""
    # The in-step phase while training: batch | forward | backward | update.
    phase_sub: str = ""
    # The checkpoint and sample cadences AS THE RUN RESOLVED THEM, in steps;
    # 0 until it has started once (and for a run that does not do that thing).
    # The config cannot answer this: a cadence set in EPOCHS becomes a step
    # count only when the built manifest says how long a pass is, and the
    # config's step field is the one the epoch setting overruled.
    ckpt_every: int = 0
    sample_every: int = 0
    # What the run trains on, recorded when its dataset was materialized:
    # {"images": n, "buckets": n} plus "frames" where any of them came out of
    # a film. Empty until a job has started once.
    dataset: dict = {}
    model: str = ""
    method: str = ""
    # WHICH KIND of adapter, when the method is one: "lora" | "lokr". Empty for
    # a full finetune. `method` alone can only say "an adapter" now that there
    # are two kinds, and a card that read it labelled every LoKr job a LoRA.
    network: str = ""
    # Unix timestamps (the training store is file-based; no ORM dates).
    created_at: Optional[float] = None
    queued_at: Optional[float] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None


class TrainingJobsOut(BaseModel):
    jobs: list[TrainingJobOut]
    # Whether the queue's run switch is on (jobs chain when one finishes).
    # Rides on the jobs list because the two are polled together.
    queue_active: bool = False


class TrainingJobDetailOut(TrainingJobOut):
    config: TrainingConfig


class TrainingJobIn(RequestModel):
    name: str = ""
    config: TrainingConfig


class QueriesPreviewIn(RequestModel):
    """The config being edited, to be told what each of its queries adds.

    The whole config rather than just the queries, because the SCOPE a query
    is resolved in depends on the rest of it — `video.include` and whether
    captions come from instructions decide whether films are in — and a
    preview counting a different set from the run is a preview about nothing.
    """
    config: TrainingConfig


class QueryPreviewOut(BaseModel):
    """One query's answer, positionally matching the list that was sent.

    `matched` is what the query finds on its own — the figure already beside
    the query. `contributes` is what it adds to the RUN, which differs for a
    regularization query only: an item an ordinary query also matches is a
    training picture, so it is not a reminder. For an ordinary query the two
    are equal, and it is sent anyway rather than left null, because a client
    reading one field for both kinds cannot get the pairing wrong.
    """
    matched: int
    contributes: int


class QueriesPreviewOut(BaseModel):
    queries: list[QueryPreviewOut]


class DegradePreviewIn(RequestModel):
    """Render one degradation variant over one item's picture.

    ``end`` is which end of the variant's ranges to show — "high" is the
    harshest thing the run can produce, "low" the gentlest. The two extremes
    are what a person needs before committing a run; a draw from the middle
    answers neither, and not the same way twice.

    ``clean`` is the picture itself, degraded by nothing. It comes from HERE
    rather than from the item's own file so that it goes through the same
    downscale as the other two: a comparison is only worth looking at when
    the pictures differ in the one thing being judged.
    """
    item_id: int
    variant: DegradeVariant
    end: Literal["clean", "low", "high"] = "high"
    width: int = Field(default=512, ge=64, le=2048)


class TrainMetricPoint(BaseModel):
    step: int
    loss: float
    lr: float = 0.0
    t: float = 0.0
    # Min/max of the step's micro-batch losses (gradient accumulation only);
    # absent when the step had a single micro-batch.
    lmin: float | None = None
    lmax: float | None = None
    # The validation round scored at this step, when the run has one: the
    # held-out loss and the stable training loss (fixed entries, fixed seed,
    # plain per-sample loss). Absent on every other step.
    val: float | None = None
    stable: float | None = None


class TrainVisitOut(BaseModel):
    file_id: int | None = None
    # Set when the image was a frame extracted from a video: the second of the
    # film it came from. Such a frame has no file_id (it is scratch, not a
    # stored file), so this is what names it in the inspector.
    video_time: float | None = None
    # …and where that frame is, under the job's own `frames` folder, so the
    # inspector can show the picture rather than an empty box. Empty once the
    # run is over and its scratch has been reclaimed, and on runs from before
    # the trainer recorded it.
    frame: str = ""
    prompt: str = ""
    flip: bool = False
    # Crop rect as fractions of the original (un-flipped) image: [x, y, w, h].
    crop: list[float] | None = None
    img: list[int] = []      # original [w, h]
    bucket: list[int] = []   # bucket [w, h] in pixels
    loss: float | None = None


class TrainVisitsOut(BaseModel):
    step: int
    # The optimizer steps that have inspection data (sorted), so the UI can page.
    steps: list[int] = []
    visits: list[TrainVisitOut] = []


class TrainMetricsOut(BaseModel):
    points: list[TrainMetricPoint]
    # Highest step in ``points``; pass back as ?after= for incremental polls.
    last_step: int = 0
    # Steps whose loss was not a usable number (a diverged run writes null;
    # runs from before that wrote a bare NaN). They are left out of `points`
    # — this is what says they existed.
    diverged: int = 0


class TrainSampleOut(BaseModel):
    step: int
    name: str      # file name inside the step folder (p00.png …)
    prompt: str = ""
    # Wall-clock time (unix) the step was reached and the cumulative training
    # duration (seconds, paused gaps excluded) at that point; 0 when unknown.
    t: float = 0
    train_seconds: float = 0


class TrainArchitectureChild(BaseModel):
    """One repeated block inside a stack ("down_blocks.1"), with its own
    size — a UNet's down blocks are far from equal."""
    name: str
    params: int = 0
    # Accumulated forward compute in this block (ms), measured with GPU
    # timing events; 0 until the run has trained (or on devices that can't
    # time without synchronizing).
    ms: float = 0


class TrainArchitectureBlock(BaseModel):
    """One top-level block of the trained model, read off its weights."""
    name: str
    params: int = 0
    # How many identical blocks the stack holds (0 = not a stack).
    count: int = 0
    kind: str = "other"
    # Accumulated forward compute (ms; a stack reports its children's sum).
    ms: float = 0
    # The stack's inner blocks, when it is one.
    children: list[TrainArchitectureChild] = []


class TrainArchitectureOut(BaseModel):
    blocks: list[TrainArchitectureBlock] = []


class TrainSampleRound(BaseModel):
    """One sampling round, listed from the moment it starts rendering — with
    `expected` images and `done` of them written so far, so the app can show
    the round (and what is still coming) before the first image exists."""

    step: int
    t: float = 0
    train_seconds: float = 0
    expected: int = 0
    done: int = 0


class TrainSamplesOut(BaseModel):
    samples: list[TrainSampleOut]
    rounds: list[TrainSampleRound] = []


class TrainQueueOrderIn(RequestModel):
    """The queued jobs, in the order they should run."""
    uids: list[str] = []


class TrainStepsIn(RequestModel):
    steps: int


class TrainCheckpointOut(BaseModel):
    step: int
    # False = this cadence snapshot existed once but was auto-pruned by the
    # keep-last-N setting (still shown as a point in the timeline).
    exists: bool
    size: int = 0  # bytes on disk (0 when pruned)
    # Locked checkpoints can't be deleted (409) and the trainer's keep-last-N
    # pruning skips them. The marker is a `.locked` file in the snapshot dir.
    locked: bool = False
    # True for the run's RESUME POINT (`checkpoints/last`) — the state a
    # pause left behind. Downloadable like any other, never deletable: it is
    # what "continue this job" reads.
    resume: bool = False
    # Whether a permanent snapshot exists at this step (`step-NNNNNN/`). A
    # resume point without one can be turned into a checkpoint.
    snapshot: bool = False
    t: float = 0
    train_seconds: float = 0


class TrainCheckpointLockIn(RequestModel):
    locked: bool


class TrainCheckpointsOut(BaseModel):
    checkpoints: list[TrainCheckpointOut]


class TrainSettingChange(BaseModel):
    """One field an edit changed, as the timeline shows it."""
    field: str
    old: str
    new: str


class TrainEventOut(BaseModel):
    # started | resumed | paused | completed | failed | canceled | edited
    kind: str
    step: int
    t: float
    train_seconds: float = 0
    # "edited" only: which settings changed, old → new.
    changes: list[TrainSettingChange] = []


class TrainEventsOut(BaseModel):
    events: list[TrainEventOut]


class GpuStatOut(BaseModel):
    key: str
    label: str
    value: float
    unit: str
    #: What the HARDWARE says the ceiling is, where it says one — the Train
    #: footer draws a bar against it. DECLARED HERE OR IT DOES NOT TRAVEL: a
    #: response model filters what the endpoint returns, so `gpu.sample()` was
    #: reporting `max` correctly and every stat still arrived without one.
    #: None means no bar, which is the honest answer for a temperature on a
    #: driver that reports margins rather than absolute thresholds.
    max: float | None = None


class SystemDeviceOut(BaseModel):
    """One stats box in the Train tab: a GPU (one per physical GPU), the CPU,
    or RAM. ``label`` is the device/model name shown as the box title."""
    key: str
    label: str
    stats: list[GpuStatOut]
    # Why a figure is missing, as a KEY the frontend words ("powermetrics":
    # macOS gates temperature/power/fan behind root). Never a sentence — the
    # words belong in the catalogs with every other translated string.
    hint: str = ""


class TrainModelIn(RequestModel):
    """A base model the user adds: extra weights for one of the built-in
    architectures, from a local path or a Hugging Face repo."""
    label: str
    base: str            # a built-in registry key (sd15 / sdxl / chroma)
    repo: str            # HF repo id, or an absolute local path
    local: bool = False
    # Native training resolution; 0 takes the base architecture's own.
    area: int = Field(default=0, ge=0, le=4096)


class TrainModelsOut(BaseModel):
    models: list[dict]   # user-added entries, in registry_out()'s shape


class TrainDeviceOut(BaseModel):
    """A device a training job can be pinned to (``training.gpu.train_devices``)."""

    id: str      # torch device string: "cuda:0", "mps", "cpu"
    label: str   # human name: "NVIDIA GeForce RTX 4090", "Apple M4 Pro"


class TrainStatusOut(BaseModel):
    env_ready: bool
    running_uid: Optional[str] = None
    # The device an Evaluate generation is rendering on, when one is. Training
    # and Evaluate share the GPU, so a job pinned to it waits — this is what
    # lets the Train tab say "waiting for the GPU" instead of leaving a queued
    # job looking like it is merely next in line.
    evaluating_device: Optional[str] = None
    # The machine's trainable devices, for the job editor's GPU dropdown.
    devices: list[TrainDeviceOut] = []
    # training.models.registry_out(): model entries incl. per-model FieldSpecs
    # and a `cached` flag (weights already in the Hugging Face cache).
    models: list[dict]
    # Non-empty (e.g. "HF_HUB_OFFLINE=1") when downloads are switched off in
    # the environment, so Train/Evaluate can say why a model can't be fetched.
    env_offline: str = ""
    # Whether a Hugging Face token is set for this server session — gated
    # weights need one, and every download is faster with one.
    token_available: bool = False
    # True where "auto" attention slicing resolves to on (Apple Silicon, whose
    # MPS backend has no fused attention kernel). The trainer runs on this
    # machine, so the server's platform is the trainer's platform, and the
    # memory estimate needs the same answer the engine will reach.
    slices_attention: bool = False


# ---- evaluation (LoRA test generations) ----

class EvalLoraIn(BaseModel):
    job_uid: str = ""   # a LoRA training job …
    user_key: str = ""  # … or a LoRA added by hand on the Models tab
    # None = the job's final output; a number = that step's checkpoint.
    step: Optional[int] = None
    name: str = ""
    weight: float = 1.0


class EvalFinetuneIn(RequestModel):
    """A full finetune to generate WITH, in place of the base model's own
    weights. One or none — a finetune is the network, not a layer on it."""
    job_uid: str
    # None = the job's finished output; a number = that step checkpoint.
    step: Optional[int] = None


class EvalRunIn(RequestModel):
    model: str
    # The full finetune whose weights stand in for the base model's, if any.
    finetune: Optional[EvalFinetuneIn] = None
    loras: list[EvalLoraIn] = []
    prompt: str
    negative: str = ""
    # 0 = automatic (the model's native size).
    width: int = 0
    height: int = 0
    # None = automatic (a random seed is drawn and recorded on the run).
    seed: Optional[int] = None
    steps: int = 25
    cfg: float = 6.0
    count: int = 1      # images per run (same prompt, seed+i)
    batch: int = 1      # images generated in one pipeline call


class EvalRunOut(BaseModel):
    uid: str
    status: str          # queued | running | completed | failed | canceled
    phase: str = ""      # loading_model | loading_loras | generating | …
    error: str = ""
    created_at: float = 0
    username: str = ""
    model: str = ""
    # The full finetune the run generated with, if any: {job_uid, name, step,
    # path}. Absent on every run that used the base model's own weights.
    finetune: dict = {}
    loras: list[dict] = []
    prompt: str = ""
    negative: str = ""
    width: int = 0
    height: int = 0
    seed: int = 0        # the seed actually used (auto seeds are recorded)
    steps: int = 0
    cfg: float = 0
    count: int = 1
    batch: int = 1
    images: list[str] = []
    # Wall time of the run in seconds (0 until the trainer reports one).
    elapsed: float = 0
    # Denoising step reached in the batch being rendered (0 when not running).
    # `steps` above is what was ASKED for; this is where it has got to.
    cur_step: int = 0


class EvalRunsOut(BaseModel):
    runs: list[EvalRunOut]


class EvalLoraOut(BaseModel):
    job_uid: str = ""
    # A LoRA added by hand on the Models tab: its key, and no job at all.
    user_key: str = ""
    name: str
    model: str
    # None = the job's final output; a number = a surviving step checkpoint.
    step: Optional[int] = None
    # The final output's trained step count (0 on checkpoint entries).
    final_step: int = 0


class EvalLorasOut(BaseModel):
    loras: list[EvalLoraOut]


class EvalFinetuneOut(BaseModel):
    """One full finetune that can stand in for a base model's weights."""
    job_uid: str
    name: str
    model: str
    # None = the job's final output; a number = a surviving step checkpoint.
    step: Optional[int] = None
    # The final output's trained step count (0 on checkpoint entries).
    final_step: int = 0


class EvalFinetunesOut(BaseModel):
    finetunes: list[EvalFinetuneOut]


class TrainLoraSourceOut(BaseModel):
    """An existing LoRA a new job can be initialized from (train.init_lora)."""
    job_uid: str
    name: str
    model: str
    step: Optional[int] = None   # None = the job's final output
    # The final output's trained step count (0 on checkpoint entries), so the
    # picker can name the step a finished job stopped at instead of "final".
    final_step: int = 0
    # Absolute path of the weight directory, stored in the job's config.
    path: str
    # Step checkpoints only: protected from deletion and auto-pruning.
    locked: bool = False


class TrainLoraSourcesOut(BaseModel):
    loras: list[TrainLoraSourceOut]

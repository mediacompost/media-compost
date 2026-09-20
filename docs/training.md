# Training

The Train tab trains image-generation models (adapters — LoRA or LoKr — or full finetunes for some models) directly on the images in your library.

## Overview

Training runs on your own machine, on the library you have already organized: you describe the dataset with the same queries the [search bar](search.md) uses, pick a base model, and the app handles prompts, sampling, checkpoints, and progress.

- **Methods:** adapter training (LoRA or LoKr) for all models; every model except the Qwen-Image releases can also be finetuned in full — SD 1.5 on a large consumer card, SDXL and the large flow-matching transformers on server-class CUDA cards with the 8-bit optimizer.
- **Built-in base models:** SD 1.5 and SDXL; Chroma1 HD and Chroma1 Base (8.9B); FLUX.1 dev and FLUX.1 Kontext dev; FLUX.2 Klein (4B and 9B); Z-Image and Z-Image Turbo; and the Qwen-Image family (Qwen-Image, Qwen-Image 2512, and three Edit releases — 20B, adapters only). Some repos are gated on Hugging Face (the FLUX.1 pair, Klein 9B) — their rows say so, and downloading them needs an accepted license and a token. The model pickers list releases that share an architecture together, because those are the ones a LoRA carries between.
- **Your own weights:** other weights for the same architectures, and existing LoRAs, are added once in the [Models tab](#the-models-tab) and then appear in every model picker.
- **Starting point:** a job can start from an existing adapter instead of from scratch — picked from any finished job's final weights or step checkpoints for the same base model, or a path typed by hand (the rank must match). Each entry in the picker is named by the step it holds, with a filled circle for a finished result and a hollow one for an intermediate checkpoint.

Training is fully optional. The core app installs none of the large ML libraries; the trainer runs in a separate, dedicated Python environment. Without that environment the library works normally and the Train and Evaluate tabs show a one-click setup banner. Because the trainer is a separate process, the app stays responsive during a run — and a run survives a server restart: the restarted server finds the live trainer and keeps watching it, and only a run whose process actually died is parked as paused, resumable from its last checkpoint.

Everything about a job lives in `training/<job-id>/` inside the data directory (checkpoints, metrics, samples, final weights in `output/`). Removing a job deletes that folder; the library database is not involved. (`MEDIA_COMPOST_TRAINING_DIR` relocates the whole `training/` folder — for a library on a small disk whose runs should land on a big one.)

## Creating a job

Creating a job opens a multi-page editor: **Model**, **Optimization**, **Memory & speed**, **Dataset**, **Prompt**, **Checkpoints**, and **Samples**. Nearly every parameter carries a one-line explanation, and most also have a circled "?" that opens a longer plain-language explanation in a popover next to the field. Numeric fields with a natural step have steppers (click, hold, or press ↑/↓); the learning rates, which have none, are typed. "Automatic" or "off" values show as empty fields with placeholder text rather than a magic `0`, and optional features (step snapshots, test sampling) are toggles that reveal their settings when switched on.

### Dataset queries

The dataset is defined by item queries — the same condition trees as the [search bar](search.md) — each with a **weight** and a live match count in the editor. With more than one query, a **Query weight** setting decides what a weight buys: *seen more often* (a weight-2 query's pictures get twice the visits, which come out of the rest of the run) or *counted for more* (every picture is visited the same, and the weighted ones simply count for more in each update — emphasis without costing anything else coverage). See [Datasets](#datasets) below for how the dataset is built and augmented.

### The prompt

The Prompt page decides what every training example is asked against. Prompts are composed fresh on every visit to an image, from captions and/or tags — or from **instructions**, which is a different kind of run:

- **Source** — tags, captions, caption + tags, or instructions. **Caption + tags trains an item twice per pass** — once under its caption, once under its tags — rather than gluing a sentence to a tag list, so either way of asking finds the picture. An item with nothing to say in a mode sits that mode out: a captions run trains only on the captioned items, and an item captioned but untagged still contributes its caption. If none of the matched items has the text the source needs, starting says exactly that. The whole **Tag selection** section is shown only while the prompt actually contains tags (Tags or Caption + tags) — for a captions or instruction run those settings would do nothing, so they are not offered.
- **Instructions** — offered only for a base model that can **edit**, i.e. whose pipeline takes reference pictures beside the prompt: FLUX.1 Kontext dev, FLUX.2 Klein, and the Qwen-Image Edit releases. Each image then trains as the **result** of one of its [instructions](item-properties.md), with that instruction's reference images as the input; an item carrying several has one drawn per visit, text and references together. Items with no instruction are not in the run, and if none of the matched items has one, starting says so rather than training on empty prompts. The prompt is the trigger word and the instruction, and nothing else — an edit model's prompt is a sentence telling it what to do, so a tag list after it would teach the model that the list is part of what was asked for. The whole **Tag selection** section therefore disappears, and so do **random crop**, **horizontal flip**, **video frames** and **degraded copies**: the first three move the target away from the reference pictures it is supposed to match, and degrading the result while its references stay pristine would teach the model to add artifacts. Switching to a model that cannot edit turns the setting back off, and saving a job that keeps it is refused with the model named. A model that exists **only** to edit (FLUX.1 Kontext, the Qwen-Image Edit releases) starts on Instructions when picked, and choosing another source there shows a note that it trains the half of the model nobody generates with — it works, and is never refused.
- **Caption selection** — its own section whenever captions (or instructions) are part of the source, titled "Instruction selection" for an instruction run: an include list narrows to the captions carrying one of the named [meta tags](tags.md), an exclude list drops the ones carrying one, and excluding wins. An item whose captions are all filtered out counts as having none. The section also decides what **an item with several captions** means: one drawn at random per visit (the default — the whole set is seen across the run and the item counts once), every caption once each per pass (ten descriptions mean ten visits), or every caption *sharing one item's weight* — each caption still gets its visit, and together they carry one picture's worth of gradient.
- **Trigger word** — a word included in every prompt.
- **Always-include list** — tags the random pick can never drop. They are included at a random position whenever the image actually has the tag (e.g. `watermark`), and never forced onto images without it.
- **Exclude list** — tags never included.
- **Every list of tags here also takes meta tags.** Beside the always-include and exclude lists sits the same rule named by what the library *says about* a tag rather than by the tag: any tag marked with one of the given [meta tags](tags.md#meta-tags-on-a-tag) is always included, or always excluded. Never flipping works the same way, and so do a degraded variant's remove / only / never lists. What it buys is that the rule is stated once, in the Tags tab, on the tags it is true of — a tag added to the library later carries it automatically, where a list of names in a job's settings goes stale the day somebody adds one.
- **Skip tag groups** — meta tags naming whole [tag groups](tags.md) to ignore. A "Notes" group holding `to redraw` and `bad scan` is useful in the library and wrong in a prompt; the tags stay on the items. A tag placed in an excluded group *and* somewhere else survives, and a broader tag that was only implied by dropped tags is dropped with them — excluding a group holding `poodle` does not leave `dog` behind.
- **Random min–max tag count** — how many tags each visit picks.
- **Inverse-frequency tag picking** — rare tags surface as often as common ones; frequency measured in the training data or across the whole library.
- **Loss weighting by tag rarity** — the other half of evening out the tag distribution.
- **Skip partially matching tags** (on by default) — when a picked tag is a whole-word part of another picked or guaranteed tag (`shirt` next to `white shirt`), the generic one is replaced by a different random tag, so the pair is never taught as one clump.
- **Shuffle** and **caption dropout**.
- **Write tags as an alias** — a chance, rolled per tag on every visit, of writing a picked tag as one of its [aliases](tags.md) instead of its canonical name, so the model also learns to answer to the other words for the thing. Only the prompt text changes: matching, balancing, bounding boxes and the always/exclude lists keep using the canonical name, and a tag with no aliases is always written as itself.
- **Formatting** — underscores→spaces (on by default, so `red_fox` trains as `red fox`; matching still uses the raw names) and a configurable tag separator.
- **Group tags by tag group** (off by default) — lays the picked tags out one block per [tag group](tags.md) instead of one flat list, so what belongs to the same thing in the picture stays together (ungrouped tags lead, describing the scene the groups sit in; a tag in two groups is written under the first only). Each block can optionally be headed by the group's name or by the subjects it is about, and the separator between blocks is configurable (a newline by default).

Prompt fields here and in [Evaluate](evaluate.md) autocomplete your library's tags as you type.

### Model and optimization settings

The Model page leads with the job's name, then the base model — with the download warnings that are about it — and the LoRA settings; Optimization holds how long and how fast to learn (length and learning rate, batch and seed, plus any model-specific settings); Memory & speed holds what the job runs on and what *fits*: the GPU, precision and quantization, and the memory savers. The options include:

| Setting | What it does |
| --- | --- |
| Run length | In steps, or in **epochs** — full passes over the dataset, each visiting every entry exactly once in a fresh shuffled order. The exact step count is worked out when the run starts, because only the built dataset knows how many entries it holds (video frames, degraded copies, and per-caption entries all count), and appears in the job's log |
| Adapter type | **LoRA** (compatible everywhere) or **LoKr** — see below |
| Rank / alpha | Size and strength of the adapter |
| Learning-rate schedule | Including warmup |
| Batch size / gradient accumulation | Together they set the effective batch |
| Precision | bf16 where the GPU supports it |
| Text-encoder training | Guarded: its own learning rate, with an automatic stop partway through the run. SD and SDXL train their CLIP encoders; FLUX.1 trains CLIP-L and, unless **Include the large encoder** is off, T5-XXL; Chroma trains its T5. The T5 adapter costs several GB of activations per prompt — pair it with gradient checkpointing and, on a 32 GB card, with the text-encoder quantization below |
| Gradient checkpointing | The largest single memory saving, at roughly 20–30% slower steps |
| Optimizer | **AdamW** (the safe default), **AdamW (8-bit)** — the two running statistics stored at one byte each, NVIDIA/AMD only — **Adafactor**, which replaces the larger statistic with a per-row and per-column summary (saves considerably more, runs on every GPU including Apple silicon where it is the only saving available, usually wants a slightly higher learning rate), or **Prodigy**, which works the learning rate out for itself — see below |
| Latent caching | Encodes images once instead of every step |
| Base-model quantization | Loads the frozen weights as fp8, int8, or 4-bit NF4 so large models fit in little VRAM while the adapter trains in full precision. Adapter training only — a full finetune trains the base weights, so there is nothing to freeze. fp8 needs a GPU with the data type (NVIDIA Ada/Hopper and newer); int8 runs everywhere through quanto — on NVIDIA too, since bitsandbytes' int8 keeps an activation-sized tensor per layer that gradient checkpointing cannot free and peaked HIGHER than bf16 on Chroma; NF4 is bitsandbytes and CUDA-only. Unsupported combinations stop with a clear message naming the device instead of silently falling back. |
| Quantize the text encoder | A second switch beside the backbone's, deliberately separate — the encoders are most of the rest of the weights, and one flag shrinking both would make the memory estimate wrong for whoever wanted only one. Needs a quantization scheme picked. Combines with text-encoder training: the adapter trains over the quantized weights, as it does over the quantized base model. |
| Keep the text encoder on the CPU | The larger of the two encoder savings: the encoder runs on the CPU, one batch ahead of the card, and only its output crosses to the GPU — so it costs nothing while the processor keeps up with a step (T5-XXL takes about 1.3 s a prompt on a 16-core desktop; a 1024 px step hides that, a 512 px one does not). Does not combine with text-encoder training either. |
| Attention slicing | CUDA-only memory lever. Off (fused kernels) by default — the default path is already fast and memory-efficient; On (save VRAM) lowers peak memory for about 10% more time. On Apple Silicon the On option is marked unsupported. |
| Weight averaging | Saves a smoothed version of the weights rather than whatever the last step produced — see below |
| Checkpoint cadence | In steps or in epochs, with keep-last-N and keep-every-Nth limits and a live disk-size estimate |

A value this machine cannot run is disabled inside its own control and marked **Unsupported**, with the reason in its tooltip — the row stays usable at the values every machine handles, and a setting that does not apply at all (quantizing a full finetune) is disabled as a whole.

### Adapter type: LoRA or LoKr

Both add a small trainable layer over the frozen base model, and both leave the
base untouched — they differ in the *shape* of change they can express, and in
what can read the resulting file. [Adapter type](#adapter-type) below is the
full comparison, and it is the same text the editor shows.

Starting a job from an existing adapter requires a match: a LoKr run cannot
continue from a LoRA and vice versa, and the trainer says which it found rather
than failing obscurely.

### Prodigy: not choosing a learning rate

The learning rate is the one setting here that genuinely has to be found rather than reasoned out. The right value depends on the model, on how many images there are and on what is being taught, so a rate that suits one job is wrong for the next — and the only way to find it is to run, look, and run again.

**Prodigy** (Optimizer, on the Memory & speed page) removes that. It measures how far the weights have travelled from where they started and derives a rate from that as the run goes, so the rate comes out of the run instead of being guessed in advance. That is worth most when you are queueing several jobs at once: without it, a bad rate is only visible after the run.

Three things to know:

- **The learning rate becomes a multiplier.** With Prodigy selected, the field on the Optimization page scales what Prodigy found instead of setting a step size, and **1** means "as found". Picking Prodigy sets it to 1 for you, and switching away puts the model's default back — as long as the field still holds the value the other side implies; a rate you edited by hand is left alone in both directions. If you edit it to something far from 1 the run says so in its log, because the failure is otherwise silent — a rate of 1e-4 here means a ten-thousandth of what Prodigy worked out, and the run trains almost not at all.
- **Early samples look untrained.** Prodigy starts its estimate at nearly zero and works it up over a few hundred steps. Judge a Prodigy run from about a fifth of the way in, not from the first sample round.
- **It uses a little more memory** than AdamW — it keeps Adam's two statistics plus a copy of the starting weights. The estimate accounts for it.

The learning-rate schedule still applies and composes correctly: cosine decay decays what Prodigy found.

### Choosing which layers to train

By default an adapter attaches to every attention layer in the image model. **Only these layers** and **Except these layers** (Model page, Adapter section) narrow that down. Each field takes a comma-separated list of *parts of a layer's name*; a layer qualifies if its name contains one of the words in the first field and none of the words in the second.

Two reasons to bother:

- **Different parts of the network do different jobs.** The later ones carry more of what a picture looks like and the earlier ones more of how it is put together, so training only part of the network is how a style is learned without also disturbing composition and anatomy.
- **Less to train.** Fewer layers means a smaller adapter, less optimizer memory and faster steps.

The names come from the model itself, and the job's page draws a map of them once a run has started. For SD and SDXL they look like `down_blocks`, `mid_block`, `up_blocks`; for the newer transformer models, `transformer_blocks` and `single_transformer_blocks`. You can be as coarse or as fine as you like — `up_blocks` takes a whole third of a UNet, `transformer_blocks.12` takes one block, `to_k` takes one kind of projection everywhere.

Leaving both fields empty behaves *exactly* as before the setting existed, so no job configured earlier changes behaviour.

Two guards, because the failure this can produce is silent:

- A filter that matches **no layers** stops the run with a message naming what you asked for. An adapter attached to nothing trains perfectly happily and learns nothing, and its loss curve looks like any other.
- The run's log says how many layers were kept out of how many were available, so a filter that matched far less than you meant is visible in the first few lines.

The filter applies to the image model only. A text encoder's layers have different names, so a filter written for one would silently match nothing in the other; text-encoder training is unaffected by it.

### Noise levels: what the run is mostly teaching

Every training step takes a picture, adds some amount of noise to it, and asks the model to undo that. How much noise is picked fresh each time — and the two extremes teach completely different things:

- At **high noise** there is barely a picture left, so all the model can learn is **layout**: what is where, how big, the overall shape and colour.
- At **low noise** the composition is already settled, and what is left to learn is **detail and texture** — edges, surfaces, small features.

So where a run spends its steps decides what it is mostly about. A style is largely texture; a character's proportions are largely layout. **Train on** (Optimization page) is that choice:

| Option | What it does |
| --- | --- |
| The model's own (recommended) | What this model family has always done, and the right answer unless you have a reason. The older models (SD, SDXL) spread evenly; the newer ones concentrate on the middle, which is what their published recipes do and part of why they train efficiently |
| Evenly across all levels | A flat spread across the whole range |
| A bell curve I can aim | The newer models' behaviour made adjustable — see below |
| Leaning towards layout | Leans towards higher noise without abandoning the low end |

With the bell curve, two more settings appear. **Aim at** moves its centre: 0 is the middle, positive leans towards layout, negative towards detail. ±0.5 is noticeable, ±1 is strong, and beyond ±2 the run largely stops seeing one end at all. **Spread** is how wide it is: 1 is standard, smaller concentrates the run on a narrow band around the aim, larger reaches both extremes. If unsure, leave the spread at 1 and move the aim — the aim changes what the run learns, the spread changes how single-minded it is about it.

None of these makes a run better or worse in general; they move what it ends up good at. The run's log says which it chose, in words, because this is invisible everywhere else — two runs differing only here have the same loss curve and differ only in the result.

Leaving this at **The model's own** reproduces earlier runs exactly, down to the random draws — not merely the same distribution. Explicitly picking a family's own default (the bell curve at 0 and 1 on a newer model, or Evenly on SD/SDXL) is treated the same way, so naming what was already happening does not change the run.

### Weight averaging

Every training step moves the weights a little, and every one of those moves is noisy — it is computed from a handful of images, and a different handful would have pulled somewhere slightly different. So the weights at step 1400 are not reliably better than the weights at step 1200: part of the difference between them is just which pictures came up.

**Average the weights** (Optimization page) keeps a second, smoothed copy of the weights alongside the real ones and slides it a little way towards the current weights after every step. That smoothed copy is what gets saved — as the checkpoints, as the finished result, and as what the test samples are rendered from. Training itself is untouched; the average is written to and never read from until weights are saved.

Two things follow, and both are about not having to be lucky:

- **Picking a checkpoint matters less.** The quality difference between neighbouring checkpoints shrinks, so there is less to lose by taking the wrong one.
- **Overshooting hurts less.** An average lags behind, so a run that trains past its best point degrades gradually instead of falling off.

The **averaging window** is how much of the existing average is kept at each step. 0.999 reflects roughly the last 1000 steps and suits runs of a few thousand; on a short run that window is longer than the run itself and the average never catches up, so drop to 0.99 (about 100 steps) there. Keep the window well under the run's total length.

The start of a run is handled for you: a fresh average begins equal to the untrained weights, so the run keeps it short at first and lengthens it as training proceeds. Without that, a short run would save an average that still substantially held its own random starting point — and the result would be worse than not averaging at all.

What it costs is one extra full-precision copy of whatever is being trained. For a LoRA that is negligible; for a full finetune it is a second whole model, and the memory estimate counts it.

Pausing and resuming keeps the average. Switching averaging on mid-run starts the average from wherever the run has got to, which is the only honest thing it can do.

### GPU selection

Each job can be pinned to a GPU (Memory & speed page, **Device** section, default *Automatic* — the machine's first). One job runs per GPU: the queue treats every GPU as a lane, so on a multi-GPU machine jobs pinned to different GPUs train side by side, jobs sharing a GPU take turns, and a job whose GPU is busy never blocks a job whose GPU is free.

### The memory estimate

The editor's footer carries a running GPU-memory estimate ("about 14 GB of GPU memory") that moves as the settings do. Hovering breaks it into **weights** (the model, text encoders, and VAE, resident throughout), **optimizer** (what is being trained plus its gradients and optimizer moments — the dominant term of a full finetune), and **activations** (what a forward/backward keeps, and the part gradient checkpointing trades away). When the total exceeds what the machine has, the footer says so outright.

Read the estimate as "this much, with headroom", not as a ceiling to fill: it is the working set a run needs at once, and the peak a GPU driver reports in an out-of-memory message can be well above it. The editor also warns before a run that usually dies: a batch size above 2 with gradient checkpointing off shows a note next to the field.

### Test prompts

Test prompts live in their own section of the Samples page, between Test samples and Validation — one compact numbered row per prompt, with a field for the prompt and one for its own negative prompt. Rows are removable and reorderable by dragging their handle. A prompt can be given its own size (a per-row aspect-ratio button reveals a width × height pair with the same preset menu); otherwise it uses the section's shared Size, which itself falls back to the training resolution.

Sampling is switched on with a toggle; the interval appears once it is on, measured either in **steps** or in **epochs** — the same choice the [checkpoint cadence](#checkpoints) and the run's own length offer, and setting all three the same way is what makes a sample, its checkpoint and a pass over your pictures line up in the timeline. An epoch cadence is turned into a step count when the run starts (only the built dataset knows how long a pass is), and the job's log says what it came out as. An optional **untrained baseline at step 0** renders before training starts, to compare progress against. Test sampling has its own **batch size**: with more than one prompt, that many render in one call, shortening the interruption to training at the cost of memory. Only prompts of the same size share a call, and every prompt keeps its own seed, so a batched sample is identical to an unbatched one.

The current prompt list can be saved from the **Prompts** menu (*Save current prompts*), renamed and deleted in that list, and clicking a saved set *adds* its prompts to the current list (duplicates skipped), so several sets can be combined. Sets live in the browser, not in the job.

### Presets

The editor's footer carries a **Presets** menu: save the current settings, load a preset (replacing every setting, but not the job's name), rename in place, remove with an ✕. One preset can carry a **star**: new jobs start from it instead of from the app's defaults. A preset saved before a setting existed gains that setting at its default, and one naming a model that is no longer installed falls back to a current one.

## The queue

Jobs appear in sections — **running** on top (one per GPU), then **Up next** (the queue), then **Drafts** (jobs never run, plus runs paused out of the queue), then **finished**. Each row shows the job's name, model and method, status, progress (`step / total steps` — shown for queued and draft jobs too), and when the job last did anything ("5 minutes ago", "yesterday").

The queue is a plan, not a pile — **queueing never starts anything**:

- Nothing runs just because it was queued: the queue works through jobs only after you press **Run** in the Up next header (or a row's **Start**, below). While the queue runs, a finished job chains into the next; the run switch turns itself off when the queue drains.
- While a job is running, the **Running** header shows **Pause** instead: it checkpoints and stops every running job (on a multi-GPU machine that can be several), and the queue stops with it.
- **Rows drag** between the sections as well as within the queue — only the handle starts a drag, an insertion line marks where a row will land. Dragging a job into Up next queues it at that slot; dragging a queued row out puts it on hold.
- **Drafts are ordered newest-first or by hand**, chosen in that section's header once it holds more than one job. Under **Manual order** the rows drag within Drafts exactly as the queue's do, and a job dropped in from Up next lands at the slot it was dropped on. Switching to manual writes the order that is on screen, so the list never reshuffles into one you did not arrange.
- Each row carries the verbs that MOVE the job between the lists, and only those: **start now**, **add to the queue** (for a paused job this resumes from its last checkpoint when its turn comes) and **remove from the queue**, which returns the job to what it was — paused if it has a checkpoint, draft otherwise — and keeps its position for later. Deleting a job is not one of them: it is asked for from the selection bar or from the open job's own header (below), so the one irreversible action here does not sit a few pixels from the pause button on rows that look alike.
- **Every waiting row (draft, paused, or queued) also carries Start**, and it means "this one, now": the job goes to the front of the queue, whatever is running on its GPU is paused (and re-queued right behind it), and the queue is left running so the rest follows — or is started, if it was off.
- Starting a single job without touching the queue — nothing chains after it — is offered on the job's **detail pane**: **Start** on a draft or queued job, **Resume** on a paused one. It is refused up front when the job's GPU is busy with another training job (unlike the row's Start, which pauses it and takes its place).
- **Pausing a running job puts it back at the front of the queue** (with the queue switched off, so nothing restarts by itself). A job that *failed* stays out of the queue — it needs fixing first.
- Rows can also be **multi-selected** (⌘/Ctrl adds and removes, shift extends), with a bar under the list offering Remove for the whole pick — running jobs are left out of its count, since they cannot be removed. The detail pane follows the same selection: exactly one row picked shows that job, and several show a placeholder saying how many are picked.

A running job offers pause and nothing else — pausing keeps everything the run has earned. Pause it first, then remove it if that is what you meant. **Removing asks first**, naming the job and what goes with it (checkpoints, test samples, and the trained result), because the folder is gone for good — except anything [locked](#locking), which is kept in the LoRAs list.

Removing is offered in three places, all asking that same question: the selection bar, a **Delete** button beside **Edit** in the open job's header (not shown while it runs), and **Clear** in the **Finished** header, which takes every finished job at once.

Training also has a command line: the **`media-compost-train`** script manages the same jobs and queue headlessly (create, queue, steps, log, watch, setup, …). The scheduler is a thread and lives only as long as a process holding it, which is why `create --start` only *queues*: **`media-compost-train run`** is the command that actually works through the queue on a headless box (Ctrl-C pauses the running job rather than killing it). It refuses to run beside an app server that offers training itself — one scheduler per library — but runs fine beside one whose training is switched off.

## Running jobs

While any job is running or pausing, the Train tab's icon in the header carries a small accent dot, so leaving the tab does not mean losing track of the run. The machine is also kept awake while a job runs — only system idle-sleep is prevented; the display may still switch off.

### Phases and progress

The run's phases are drawn as one short line above the loss graph: **Prepare → Train → the interludes still to come → Done**, each phase saying how many steps away it is ("in 120 steps" — counted against the cadence the run actually resolved, so a checkpoint or sample interval set in epochs counts down to the right step). Phases the run cannot enter (no sampling, no checkpoints) are not drawn. The active phase's dot is a ring that fills: the Train dot follows the step's own batch × accumulation passes, so even a minutes-long big-batch step visibly advances, and the Sample dot fills with the images of the round it is rendering. When the run finishes, the Done dot fills with a checkmark.

The phase is sampled once a second and says where the training loop is, not where the GPU is — read it as a guide rather than a stopwatch.

More progress detail while a job runs:

- Before the first step, the job says what it is doing: the model being loaded, "62 / 162" as images are encoded into the latent cache.
- Inside a step, the row and detail header show a **fractional step** ("341.25 / 2000"), counted from how many of the batch's images are through the forward and backward passes.
- Under the progress bar, a pace line gives what a step currently costs (`1.4 s / step`), about how long is left at that pace, the latest loss, and how many images the run trains on. The rate follows the last handful of steps, leaves out long gaps (pauses, sampling rounds, restarts), and says when something other than training is happening — a sampling round, a checkpoint — since that is why the pace just dropped.
- A slim strip below the progress draws the model being trained, one tile per block, sized by parameter count. Hover any block to see its name and size. The picture is read off the loaded weights, so an unfamiliar model draws itself correctly. There is deliberately no "which block is running now" highlight.

Live **system stats** sit in a collapsible footer at the bottom of the sidebar: one box per GPU (utilization, memory, and — where the platform reports them — temperature, power, and fan), a combined CPU + RAM box, and a Disk row showing free space on the volume the library and its training runs live on. On Apple Silicon the temperature/power/fan sensors appear only where passwordless `sudo powermetrics` is allowed.

### Pausing and resuming

Pause checkpoints the run at the pause position and stops the trainer; resume continues from the last checkpoint. Pausing is fast:

- The request is checked between the passes inside a step, not once per step, so even a big-batch job pauses within roughly half a micro-batch plus a few seconds.
- A pause that arrives before any new step finished skips writing the checkpoint entirely — the one on disk already holds that state.
- Sample rounds check once per denoising step; finished images of an interrupted round are kept, the rest re-render on resume, and a mid-round pause still checkpoints the step that just finished.
- Every pause logs its own timing breakdown in the job's log, so a slow pause is diagnosable rather than a mystery.

**A resume asks the dataset query again.** The library goes on being used while a job waits, and the run's dataset is a list of the files that matched when it was built: merge two files of an item, delete one, or trash the picture and the file the run was told to train on is not there any more. Rather than reopening a list that has gone stale, a resume re-evaluates the query and builds the dataset from the library as it is now. Where that answer differs from the last one, the timeline says so — **Dataset changed**, with how many items came and went — because a run that quietly continues on a different set of pictures is worse than one that says it did. Nothing changed means no entry. Extracted video frames are kept between builds (they are cached per film), so the rebuild is usually quick.

A picture that goes **while a run is going** is skipped rather than fatal: the trainer drops what it cannot open from that run's pools, names it in the log, and carries on with the rest. Only losing *every* image ends the run.

### Editing a job

Every job has **Edit** in its detail header, and every job that is not currently running takes the changes, which apply to its next run — a job that is still *pausing* already counts (a running one must be paused first; only its total step count can change live). Saving is **Save**, which leaves the job in whatever section it is in, with **Save as duplicate** beside it to start a fresh job from the settings instead. Each edit writes a "Settings changed" entry into the timeline listing exactly what changed, old value → new. A running job's editor still opens — seeing what a run was set to is how you decide what the next one should be — and its one save is **Save as new job**. A new job never takes a name another job already has: the second becomes "name 2", so duplicating twice still gives rows you can tell apart.

The **total step count stays editable** ("Edit steps" next to the progress — "Extend steps" on a finished job): a running job adopts the new target between steps, and raising the steps of a finished job makes it resumable again — training continues from its last checkpoint, with the learning-rate schedule re-stretched to the new total.

Job names, parameter labels, hints, and help text are selectable, so they can be pasted into searches and chats.

### Failures

**A failure is never "finished".** Whatever went wrong — a model that was not downloaded, a rejected setting, an out-of-memory partway through — the job is parked as **paused** (under Drafts, out of the queue — it needs fixing first), with the reason kept as its message and the failure recorded in its timeline. Resume continues from the last checkpoint; the same applies to a run interrupted by a server restart.

A failed job is editable like any other job that is not running: fix what caused it and start it again instead of copying a run that never happened.

Two failures explain themselves specially:

- **Divergence:** if the loss is NaN for three steps in a row, the job stops with a message naming the likely causes instead of training on nothing to the last step. Unusable steps are left out of the loss graph, which then says the run diverged.
- **Out of memory:** the message names the settings that decide memory, with this job's own values — lower the batch size and raise accumulation, switch gradient checkpointing on, or train at a lower resolution.

A failed job's error and the training log are selectable for copying into a search or bug report. The log shows the trainer's output in its terminal colors, and every start and resume writes a timestamped separator line, so several attempts in one file stay tellable apart.

### Profiling a slow run

A card that reads busy half the time is a loop that is waiting on something between kernels, and the ordinary log cannot say what. Start the server (or `media-compost-train run`) with `MEDIA_COMPOST_TRAIN_PROFILE=5` and the next run measures five steps, from step 3: the job's log then carries a wall-clock split of each step into the loop's phases (composing the prompt, reading the cached latents, forward, backward, the optimizer update, and everything between steps) with the device synchronized at every boundary, followed by the trainer's kernel and operator tables, and `profile-trace.json` in the job's folder opens in Chrome's tracing page or Perfetto. A step whose device-side phases add up to nearly all of it is bound by the GPU; one with seconds in "forward" on a run whose encoder sits on the CPU is paying that encoder's pass every step. The log also prints, once the model is loaded, what each component's weights occupy on the device — so a quantized load that did not shrink is visible before the first step rather than deduced from an out-of-memory error inside it.

## Samples

With test sampling on, the prompts render every N steps into the job's timeline (plus the optional step-0 baseline). Samples are rendered by the model being trained itself, so a sample reflects the current state of training and costs no extra model memory.

- A round appears in the timeline **the moment it starts rendering**: one tile per prompt as dark placeholders, each image replacing its placeholder as it lands, with a "3 / 8" count in the round's header. While a job is sampling, the timeline refreshes faster so the tiles fill in live.
- A round is ordered against the other timeline events by the time it started rendering, so it sits where it actually happened.
- A round that was already rendered is **not rendered again** on resume — replayed steps would produce identical images. Change a prompt, size, seed, or sampler setting and the round re-renders, because then it would not.
- A pause never leaves a half-rendered round behind: a resume finishes it first, before training continues.

Clicking a sample opens a quick-look lightbox whose subtitle names the prompt as well as the step. ←/→ browse all samples; **↑/↓ jump to the same prompt at the previous/next sampled step** — the quickest way to watch one prompt evolve over the run. Escape, Space, or clicking the backdrop closes it.

## Checkpoints

Checkpoints save at the cadence set on the Checkpoints page — every N steps, or every N epochs (full passes over the dataset; the equivalent step count is worked out at run start and printed in the job's log) — and appear in the timeline. A checkpoint still on disk shows its file size with **download** (as a zip) and **delete** buttons; an auto-pruned one leaves the timeline.

### Retention

Two independent rules decide what stays, and a snapshot survives if *either* keeps it:

- **Keep the last N** — a rolling window at the end of the run.
- **Keep one in every N** — milestones that stay for good.

Keeping the last 5 of a 200-step cadence *and* every 5th gives you the recent stretch to compare plus a milestone every 1000 steps. Either number can be 0 to switch that rule off. The newest snapshot always survives, and the disk estimate under the field counts the union of the two rules (with the cadence in epochs and the run's length in steps there is no count to give, so it says what one snapshot costs instead).

### Locking

Checkpoints can be **locked** — in the timeline's checkpoint chip and in the Models tab's LoRAs list. A locked snapshot cannot be deleted (the control disappears until unlocked), and pruning skips it entirely: it neither gets removed nor counts against the keep-last-N window. A job's **finished result** can be locked the same way, from the LoRAs list.

The lock survives restarts, travels with a copied job folder — and outlives the job itself: removing a job moves its locked checkpoints and locked result out of the job's folder and keeps them as entries of their own in the LoRAs list, and the removal confirmation says so.

### What is in a checkpoint

Every checkpoint — and the finished result — holds the same two weight files, both in the `.safetensors` format:

- **`pytorch_lora_weights.safetensors`** is the one other tools read. It is the layout diffusers defines, which is what ComfyUI, the web UIs and diffusers itself load, so a checkpoint can be dropped straight into them with nothing to convert.
- **`adapter_weights.safetensors`** is this app's own copy, in the parameter names the training library uses. It is what a run resumes from and what another job starts from when you point **Start from an existing adapter** at a checkpoint. Beside it, `adapter_config.json` records what the adapter *is* — network type, rank, alpha, base model — so a checkpoint still explains itself after the job's settings have been edited or the file has been passed to somebody else.

Both are written at **every** checkpoint, not only at the end of the run. That matters because picking an earlier checkpoint is the usual cure for a run that trained too long, and those intermediate weights are exactly the ones you want to be able to use.

Downloading a checkpoint gives you a zip of the whole folder, so it contains both.


> **A LoKr checkpoint carries a different second file.** The diffusers layout has a place for a LoRA's two matrices and nowhere to put a Kronecker factor, so writing one for a LoKr would produce a file that loads without complaint and applies nothing. Instead, where the architecture allows it, a LoKr gets **`lycoris_weights.safetensors`** — the same weights under the names ComfyUI looks LoKr layers up by, so the result can be used outside this app after all.
>
> "Where the architecture allows it" means FLUX.1, FLUX.1 Kontext and the Qwen-Image releases: those are the models whose layers ComfyUI addresses that way. On SD 1.5 and SDXL it names them differently again (`lora_unet_` over the model's own layer names, not the diffusers ones), and for Chroma, FLUX.2 and Z-Image this app has not verified how they are addressed — so no such file is written there, and a LoKr trained on them works in [Evaluate](evaluate.md) and as the starting point of another job but has nothing to hand over.

### The resume point

Pausing writes the run's position to disk so it can continue, but that resume point is **not a checkpoint**: the trainer overwrites it at every pause and checkpoint round, and it is not shown in the timeline. The one exception: a job paused at a step that has no checkpoint offers **"Keep as checkpoint"**, which copies the pause state into a permanent snapshot at that step — created locked, so pruning can never take it.

## The loss graph and metrics

Clicking a job opens its detail pane with a **loss graph** (raw + smoothed, log-Y toggle, hover readout, vertical gridlines at round step numbers) and a vertical timeline (newest first) mixing sample rounds, checkpoint saves, and lifecycle events — every entry stamped with its wall-clock time and the net training duration reached at that point (time spent paused is excluded).

Graph features:

- A **metric switcher** (Loss / LR / Speed) plots the learning-rate schedule or the throughput instead. The noisy series (loss, speed) get a smoothing toggle (on by default); the learning rate is never smoothed.
- A **"bars" mode**, offered for jobs with gradient accumulation, draws one vertical min/max bar per step with a tick at the step mean. When bars no longer fit the run, a **range slider** appears below the axis — drag its body to pan, drag either tip to zoom. Hovering a bar reads out the step, mean loss, and micro-batch min–max range.
- Both modes draw faint **epoch-boundary lines** (one pass over the dataset), shown only when sparse enough to read.
- Steps with no usable loss (a diverged run) are left out, and the graph says the run diverged rather than implying training never started.

The **Data** button opens the training-data inspector: for one optimizer step, exactly the images and prompts that step trained on. A smoothed loss graph at the top can be clicked or dragged to scrub between steps; each row shows the source thumbnail with the random crop drawn on top and any flip applied, the prompt used, and chips for cropped/flipped/image size/bucket size and the step's loss. A video frame has no thumbnail and is labeled with the moment it came from.

## Datasets

When a job starts, its dataset is materialized from the queries before training begins — the job shows "preparing" during this phase, and pausing or canceling stops it there.

### Regularization images

Training a subject or a style has one characteristic failure: the model generalises the new thing onto the whole class it belongs to. Train one character and every woman starts looking like her. Train one artist and the model quietly loses the others. The model has no way to tell "this is what Alice looks like" from "this is what people look like" — it only ever sees Alice.

**Regularization images** are the fix, and they are just another query. Tick **Regularization** on a query and its pictures become reminders: examples of the same *kind* of thing, with ordinary prompts, shown alongside the training pictures so the model's existing idea of the class stays anchored.

Two things happen automatically to such a pool:

- **They never get the trigger word.** That word is for the new thing; putting it on the reminders would teach it to mean the ordinary thing, which is the opposite of the point.
- **Their loss is scaled** by **How much reminders count** (the Regularization section, which appears once a pool is marked). 1 gives a reminder the same say as a training picture and is the usual setting. Lower it if the run is reluctant to learn what you are training; raise it if what you are training keeps leaking into everything else of the same kind.

Choosing the pictures is the part that matters. They should be the same kind of thing you are training but **not** the thing itself — training a character, the reminders are other characters; training one artist's style, they are other art of the same medium. Your own library is usually the best source, which is why this is a query rather than a folder to prepare.

Three rules keep it honest:

- **A picture matched by an ordinary query is a training picture**, whatever else also matches it. Being asked for by name wins — otherwise a broad reminder query ("everything") would quietly demote the very pictures the run is about and strip their trigger word.
- Because of that, a reminder query that overlaps your training query entirely contributes **nothing**. The job's log says so when it happens, since the run would otherwise train perfectly well and simply not be regularized.
- A job cannot be **all** reminders — there would be nothing to learn — and it says so before it can be queued.

The run's log reports how many entries were regularization ones, what they count, and that the trigger was dropped from them.

### Bucketing, crops, and flips

Images are bucketed by aspect ratio at constant pixel area, with center or **random crops** and optional horizontal flips. **Never upscale** (on by default) leaves out any image smaller than the bucket it would be fitted to instead of enlarging it — decided while the dataset is built, before anything is encoded, and the run says how many it dropped. Random crops are **bounding-box aware**: when a tag in the visit's composed prompt has a [bounding box](annotation-editor.md) on the image, the crop is constrained so at least ~90% of the box stays inside; conflicting boxes split the difference, and flipped visits mirror the boxes first. A prompted subject is never cropped away from under its tag.

**A run can train at more than one size.** **Resolutions** is a multi-select of them, with no first among them: pick as many as you like from the common ladder, or add any other through *Another size…*. The model's own size is a row of that ladder wearing a **default** mark — the one a fresh job starts at, and one that follows the model if you change which model the job trains. Each size is a full family of buckets; every image joins each one it is big enough for, so the same picture is learnt at several scales rather than together with the one canvas it happened to be on. It is also what keeps small pictures in a high-resolution run: **Never upscale** is asked per size, so a 700-pixel scan dropped from a 1024 run trains at 512 instead once you add it. Each size is another pass over the dataset per epoch and another cached latent per image, and the batches at the largest decide the peak memory — which is what the VRAM estimate is measured against. Two or three an octave apart is the usual shape; at most five.

**A [subject](subjects-and-faces.md)'s tag falls back to that subject's detected faces** when it carries no box of its own — the detector has already answered "where in this picture is Alice". It is only a fallback: a drawn box may mean the whole person rather than the head, so a tag that has one keeps it, and a dismissed face counts for nothing.

**Flipping can be vetoed per image by tag**: name the tags that mark pictures mirroring would ruin (text, a logo, a character whose scar is on one side) and an image carrying any of them is never mirrored, while the rest of the dataset keeps the augmentation.

### Video frames

Videos are skipped unless you switch on **Train on video frames** (Dataset page). With it on, every video the queries match is sampled while the dataset is materialized — one frame every N seconds (or every Nth frame), each trained on as an ordinary image and deleted with the run. A frame carries the video's untimed tags plus the timed ones whose range covers its moment (a tag dropped that way takes what it implies with it), and a single-moment tag reaches the nearest sampled frame. **Repeated frames are dropped** by default — a shot held for five seconds is one picture, not five. A video's frames each count as items of the pool they came from, so pool weights apply as expected. Building a dataset this way takes minutes, so it runs as the job's preparing phase, naming the video being unpacked.

### Degraded copies

The Dataset page's **Degradation** section teaches a model what artifacts look like — for restoration training, or to make a tag like `jpeg artifacts` mean something. Each **variant** describes one way of making a picture worse: JPEG re-encoding (quality and chroma-subsampling), video-codec compression (H.264/H.265 by CRF), or a resize down and back up — resolution loss at the same size, so the copy shares its source's bucket and bounding boxes — optionally re-applied for several passes. Every numeric parameter is a *range* the actual strength is drawn from, once per picture, and the drawn copies are cached so a re-run reuses them. A variant card names its method in its header, and its refinements — **Tags**, **Which pictures**, and a **Preview** — are folds that start closed. The preview renders as soon as it is opened and again whenever a setting settles: the original beside the gentlest and harshest ends of the range, side by side in one row, each a click from full size, with **Another picture** drawing a different image out of the dataset — a photograph and a line drawing come out of the same settings looking nothing alike.

A degraded picture is an **extra** training entry, never a replacement: the clean picture keeps its full weight, and the variant's weight says how often its copy is drawn relative to it (0.25 = one degraded visit per four clean ones). Per variant, tags can be **added** to the copy's prompt (guaranteed — never dropped by the random pick, the caps, or dropout; a variant with no tag is skipped outright, since the copy would otherwise be an unmarked bad picture in the dataset) and quality claims **removed** from it (`masterpiece` comes off the mangled copy; the clean entry keeps every tag), and tag gates limit which pictures a variant touches at all. **Cached variations per picture** spreads one picture across the range at a proportional disk cost — the variant's weight is split across the variations, so raising the variety never retunes the training mix, and the editor's footer states the resulting clean/degraded mix outright.

### Masked training

**Masked training** (off by default) uses a cut-out image's alpha channel as a **loss mask**: the visible subject counts fully toward each update while the transparent region counts only for a configurable background weight (0.1 by default; 0 ignores it entirely, 1 is the same as masking off). It applies only to images that carry transparency. What is masked is the loss, not the model — it stops a cut-out's empty background being learned as part of the subject.

Two things to know: the mask works at latent resolution (one cell covers 8×8 pixels — 16×16 for FLUX.2), so its edges go soft and it cannot isolate anything thinner than that; and the transparent area is filled with a smooth extension of the subject's edge colors before encoding, so the alpha boundary itself is not baked into the subject.

## Base model downloads

A training job (or an [Evaluate](evaluate.md) generation) downloads its base model on first use. If downloads are switched off in the environment, starting one is **refused up front with the reason** rather than dying minutes later in a stack trace. The job editor shows the same environment warnings as the Models page — an offline banner with a one-click **Enable downloads** button, and a missing Hugging Face token card with the token field right there — whenever the selected model still has to be fetched, so a job is never queued against a model that cannot arrive.

Once a model's files are all cached, training and generating work with Hugging Face offline — the run loads from the cached files directly, without asking the hub anything.

## Apple Silicon

Training and evaluation run on the machine's GPU where there is one: an NVIDIA card via CUDA, an Apple Silicon GPU via Metal (MPS), else the CPU. On a Mac:

- bf16 precision is probed before use and the run falls back to fp32 if the GPU cannot do it; fp16 is never used there.
- Apple Silicon has no 8-bit float type, so fp8 quantization is unavailable (probed on the actual device, so it will light up by itself if that ever changes), and NF4 is refused too (it is CUDA-only). int8 quantization *works* — it goes through quanto there instead of bitsandbytes. The 8-bit optimizer needs CUDA (or ROCm) and falls back to plain AdamW with a line in the log saying so.
- Attention slicing stays off — the trainer already uses efficient default attention there, and the On option is marked unsupported in the editor.

Every run's log opens with the device and precision it settled on (`device: mps, dtype: bfloat16`), so "did it use the GPU?" is answerable without guessing.

## The Models tab

The **Models** tab (beside Train and Evaluate) manages the weights available for training and generation. It works like the [Settings models page](settings.md#actions) — the same download states, split buttons, and environment warnings.

### Base models

The tab lists the built-in models **grouped by architecture** (SD 1.5, SDXL, Chroma, FLUX.1, FLUX.2, Z-Image, Qwen-Image — the same grouping the model dropdowns use), with your own models nested under the built-in each one is **based on**: other weights for the same architectures, either a Hugging Face repo or a local path (a diffusers folder or a `.safetensors` checkpoint). Adding opens a dialog (the page's top-right button, or a row's pencil to edit an existing entry — editing keeps the model's identity, so jobs configured with it keep working). The **Based on** dropdown offers every built-in, in the same architecture groups as the list itself, and decides the engine, native resolution, and hyperparameters. Whether you typed a repo id or a path is read off the text itself — `owner/repo` and nothing else is a repo — and the form says back which it read; a missing local path or a duplicate is refused with the reason. The name is optional — an unnamed model is listed under its Hugging Face id or its file/folder name. Entries live in `training/models.json` and `training/loras.json` in the data directory — files like everything else about training, not database rows.

A model too large to finetune fully carries a **No full finetune** chip, and that method is not offered for it (the Qwen-Image releases) — it can still be trained as either adapter type. Rows show the state of the weights: **Downloaded** (with the size on disk), **Partly downloaded**, or a plain Download button. "Downloaded" means the files this model actually needs are here — fp16 variants, `.bin` duplicates, and stand-alone checkpoints the trainer never opens are neither required nor fetched, which is why download figures are a few GB rather than tens. A **gated** model's row says so, and its download waits for an accepted license and a Hugging Face token.

Each state offers the matching actions through a split button: **Download**, **Resume** an interrupted download (bytes already fetched are kept, never re-fetched), and in the chevron's menu **Cancel download** for one in progress and **Delete download** / **Discard partial download** for what is on disk. A running download reports real bytes — "3.2 GB of 7.1 GB" beside the percentage. While downloads are switched off in the environment, the page shows a warning banner and an **Enable downloads** button, and the buttons are dimmed until then.

A local model shows **On disk** or **Path missing** instead — its weights are wherever you put them.

User models appear in the model dropdowns of both Train and Evaluate. Removing one asks first — and when the app downloaded weights for it, asks separately whether to delete those from the cache too, since the list entry is the only handle on them (a local model is never offered that: the app did not download its weights). Removal leaves existing jobs' stored settings alone; those jobs simply can't be re-queued until it is added back.

### LoRAs

The **LoRAs** sub-tab lists every LoRA on this machine — files you added by path (downloaded or trained elsewhere) and the weight sets this library's own training produced (each job's finished result and its surviving step checkpoints) — **grouped by the architecture they fit** rather than by where they came from, which is what the page is read to answer. The heading is the coarse answer; the row's own model name is the exact one. **What actually fits is narrower than the heading**: an adapter is a set of deltas on one network's layers, so it loads onto the weights it was trained on and onto your own models declared to be based on them — an SDXL finetune and plain SDXL are the same network — but not onto a sibling release that is a different transformer (FLUX.2 Klein 4B and 9B, Chroma1 HD and Chroma1 Base). The pickers in [Evaluate](evaluate.md) and the job editor offer exactly what fits. Added files are edited through the same dialog as base models; a path that has since disappeared is flagged, and removing an added entry only forgets it, never deletes the file.

Job-produced step checkpoints carry download and delete buttons (a checkpoint can be [locked](#locking) against deletion and pruning). A finished result can be downloaded and locked but not deleted there; it belongs to the job — and if locked, it survives the job's deletion as an entry of its own (see [Locking](#locking)).

## Turning training off

Training can be disabled entirely at launch, which hides the Train, Evaluate, and Models tabs and turns the app into a pure organizer — useful on a NAS or a machine that could never finish a run. See [Turning training off](installation.md#turning-training-off) for the setting.

## Every setting explained

Each of these is also the text behind that setting's ⓘ in the job editor —
literally: the app compiles this page's wording into itself
(`scripts/gen_field_help.py`), so what you read here and what the editor
shows you cannot drift apart.

--8<-- "training/fields/base-model.md"

--8<-- "training/fields/adapter.md"

--8<-- "training/fields/length-learning-rate.md"

--8<-- "training/fields/batch-seed.md"

--8<-- "training/fields/noise-levels.md"

--8<-- "training/fields/weight-averaging.md"

--8<-- "training/fields/device.md"

--8<-- "training/fields/precision-quantization.md"

--8<-- "training/fields/memory-savers.md"

--8<-- "training/fields/query-weight.md"

--8<-- "training/fields/regularization.md"

--8<-- "training/fields/resolutions.md"

--8<-- "training/fields/crops-flips.md"

--8<-- "training/fields/videos.md"

--8<-- "training/fields/transparency.md"

--8<-- "training/fields/masked-regions.md"

--8<-- "training/fields/source.md"

--8<-- "training/fields/instruction-selection.md"

--8<-- "training/fields/tag-selection.md"

--8<-- "training/fields/value-rules.md"

--8<-- "training/fields/degraded-copies.md"

--8<-- "training/fields/checkpoints.md"

--8<-- "training/fields/test-samples.md"

--8<-- "training/fields/validation.md"

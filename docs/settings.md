# Settings

The Settings overlay holds library-wide preferences and the AI model manager; changes save immediately, with no confirm button.

Open it with the gear button in the top-right corner. A page sidebar on the left switches between the five pages described below — **General**, **Tagging**, **Faces**, **Actions**, and **Storage**; the last-visited page is remembered across opens. (There was once a page called **Behaviors**, holding the tag namespaces and the face-match threshold; the namespaces live on Tagging now and the threshold on Faces. The Actions page was called **Models**. An address still naming either lands on the right page.) Opening Settings via a model **Download** or **Set up** chip in an item's Actions menu jumps straight to the Actions page with that model's card highlighted.

## General

General leads with Language & Region — it decides how every other page reads, and it is what you set once on a fresh install.

### Language & Region

- **Language** — the UI language: English, German, Japanese, Simplified Chinese, Korean, Spanish, Brazilian Portuguese, or French. The whole app is localizable, including the Train, Evaluate, and Models tabs down to their long help texts and the parameter names the model registry supplies; untranslated strings fall back to English. (The one deliberate exception is the [image editor](image-editor.md), whose Photoshop tag set stays English.) Numbers and dates follow the chosen language too — month names, decimal separators and digit grouping come from the app language, not the browser's. On the default date pattern a CJK language reads best with **YYYY/MM/DD** picked as the date format.
- **Date format** — a dropdown of common patterns, each labelled with a live example against an unambiguous sample date (August 19 of the current year, so the day can't be mistaken for a month: `19 Aug 2026`, `19.08.2026`, `2026-08-19`).
- **24-hour time** — a toggle switch.

### Double-click an item

A bordered list pairs each media kind with a dropdown choosing what a double-click does:

- **Images:** Quick Look preview, Annotate tags, Open image editor, or Do nothing
- **Videos:** Quick Look preview, Annotate tags, Open video editor, or Do nothing

Sequences always open in the grid regardless. See the [image editor](image-editor.md), [annotation editor](annotation-editor.md), and [video editor](video-editor.md) for what each opens.

Changes apply immediately across the app. The double-click and Language & Region choices are personal — kept per user in a shared [deployment](installation.md#multi-user-access) — while everything else is library-wide: the Tagging page, the Faces page, the Actions page's model paths and its Florence-2 checkpoint, and both of the switches that hide a piece of the UI ("Hide actions that need setting up" and "Hide the Faces tab"). Whether a deployment offers a thing at all is not a matter of taste.

## Tagging

The Tagging page holds the settings that end in a tag: the prefix on a tag the app invents, and the tags a detector's findings land on. (How alike two faces must be before the app puts a person's tag on a picture by itself is the [Faces page](#faces) below — it is the one number the face work turns on.)

### Prefixes

Three rows — a **default tag prefix** for **subjects**, **places**, and **events** — defaulting to `subject:`, `place:`, and `event:`. Whatever you type here is put in front of tag names the app *invents* when it creates a tag for a new [subject](subjects-and-faces.md), [place](places.md), or [event](events.md), so each kind lives in its own namespace (`subject:albert_einstein`, `place:berlin_hauptbahnhof`) and a plain `berlin` meaning something else can exist beside it. A tag you type yourself is never changed. An example beside each field shows what will actually be minted. The field applies the tag field's own rule as you type — whitespace becomes underscores, and lowercase, since every tag the app mints from a typed name is lowercase.

These are library-wide settings rather than personal ones, since they decide what the shared tag catalog looks like. Search keywords are UPPERCASE (see [Search](search.md)), so a prefix is never mistaken for one.

### Detection

Two rows name the tags a detector's findings become boxes on. **Tag for detected watermarks** (default `watermark`; an empty field falls back to it, since the removal needs a name to read) is where the watermark detector's regions land as boxes — the same boxes the box-driven **Use tagged boxes** removal consumes, so detect-then-remove is one workflow under one name, and after an in-place removal the tag flips to negative. **Tag for detected text** is optional — empty means the OCR engines record text regions only; set, every reading also puts its regions on that tag as boxes, slanted ones as polygons. Both are read by the actions and by the [image editor](image-editor.md), so a library that calls its watermarks `logo` needs nothing else changed.


## Faces

The [Faces tab](subjects-and-faces.md)'s own page.

**Hide the Faces tab** — off by default. On, the tab leaves the header: absent rather than greyed, since a tab you cannot press reads as a broken app while a tab that is not there reads as a deployment that does not do that. Hiding it while you are standing on it moves you to the Library. It hides the **tab** and nothing else — detection still runs, its findings still land, Pending → Faces still fills, and the annotator still asks who somebody is — which is why the threshold below stays live with the tab away. Library-wide, like the switch on the Actions page.

### Naming

**Minimum face similarity** — how alike a detected face and a known person's faces must be before the app names one by itself. Higher is stricter: fewer names, fewer wrong ones; each suggestion waits for review under Pending → Faces. A reset button beside the slider returns the default — **90%** — dimmed while already at it, rather than hidden (a control that comes and goes as you drag the slider beside it cannot be aimed at). The default sits well above the band a detector's own faces were measured to separate in, because a wrong merge is a cluster to pull apart by hand while a miss is one extra "name all 6" click. It applies library-wide, like the tag prefixes; a value outside the valid range falls back to the default. See [Subjects and faces](subjects-and-faces.md) for how suggestions are reviewed.

## Actions

The Actions page manages the AI models behind background removal, watermark removal, tagging, captioning, and the other AI actions — it is named for what it is there to make work. It shows any warnings first, then the AI-actions toggle with a **Set up all (N)** button beside it (one run over every action still needing setup, with one restart at the end), then a bordered section per model category, one row per model.

### Warnings

- **Downloads switched off** — if the launch environment forces Hugging Face offline (`HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, or `HF_DATASETS_OFFLINE` set to anything but `0`/`false`/`no`/`off`), a warning box explains that downloads will fail and offers an **Enable downloads** button that unsets it in the running process, so downloads work without a restart. The warning disappears once every model is downloaded.
- **No Hugging Face token** — the access token is never stored on disk: it is read from the environment (`HF_TOKEN` / `HUGGING_FACE_HUB_TOKEN`) or from the token `hf auth login` saved, and passed on to everything that reaches the hub, including training and evaluation runs. When no token is set and any model still needs downloading, a warning appears with an inline field to set one into the running server's environment for this session only (lost on restart; the durable way is `hf auth login` in a terminal, or a launch-time environment variable). Unauthenticated fetches are rate-limited and much slower — noticeable on multi-gigabyte models. None of the AI models on this page is gated; a few of the *training* base models are, and those refuse to download without a token at all.

The [Train tab's Models page](training.md) shows the same two warnings; they describe the machine, not one page's model list.

### AI actions

**Hide actions that need setting up** — off (the default), an AI action that still needs a download or setup is offered in an item's Actions menu with a chip saying so, which is how you find out it exists; on, only actions ready to run appear. The Actions page always shows everything, which is why the toggle sits at the top of it, beside the rows it hides.

### Model rows

Each section's heading carries its own **Download all** (with a count), starting every download in that section that can begin right now — skipping models already downloaded or downloading, local-path overrides, models still needing setup, and (for Hugging Face downloads) gated models without a token and everything while downloads are blocked; a model that fetches its own weights from outside the hub is subject to neither gate. The button is hidden when its section has nothing left to start.

The list is grouped by what the models do — Background removal, Upscaling, Artifact removal, Colorization, Screen-tone removal, Captioning, Tagging, Control images, and **Classification** (the DINOv2 and CLIP embedders that index pictures for the [one-by-one tagging](rankings.md#tag-items-one-by-one) session's smart ordering) — with the shared capabilities in sections of their own: **Text** (the OCR engines that drive Select text, panel detection, and the YOLO11x watermark detector that also drives the editor's Select watermark — a page's panels, its speech, and the logo stamped over it are all things found on the page itself, and the same Magi weights serve panels and OCR), **Face detection** (the two face detectors), and **Inpainting** (the big-lama and anime-lama inpainters behind watermark and text removal, which also power the editor's Inpaint tool).

Each row names one model family — withoutBG, the LaMa inpainters, the taggers and captioners (JoyCaption, JoyTag, WD Tagger, RAM++, BLIP-2, Qwen2.5-VL, Florence-2), the face detectors, the OCR engines, the colorizers, upscalers and the rest — with a link to its model page and a split button on the right:

- The main part reads **Download** when the model isn't present, **Waiting…** while it is queued behind the two downloads that may run at once, shows a live **percentage** (with the byte figures under the model's name) while downloading, and reads **Downloaded** once present. A model whose packages or environment aren't installed shows **Set up** instead, whether or not its weights are already there (the button opens the setup overlay). The button is dimmed, with an "Access token required" or "Enable downloads first" note under the name, when a hub download is blocked.
- The chevron opens a state-dependent menu: **Cancel download** while running, **Use local path** (the main part becomes a text field for a downloaded model directory; **Use downloaded model** switches back) when idle, or **Delete download** (with the on-disk size noted under it) when weights are cached and idle. When the model's packages are missing, the menu also offers **Setup instructions**.

Not every row is a Hugging Face download. A plugin that fetches its own weights from elsewhere — InsightFace pulls its face pack from its own release, the neural screen-tone removers fetch their graphs from GitHub — is listed too: its Download works regardless of offline mode and tokens, since it never goes near the hub, and its menu offers neither a local path nor a delete, because the weights live outside the cache. A row with nothing to fetch at all (Canny, the FFT descreen) reads **Ready**. Most rows carry a small "N GB VRAM" chip — the minimum GPU memory to *run* the model, not its download size.

Cancelling a download deletes its partially fetched files, so a row never wrongly reads Downloaded from the small config file that arrives early. A model counts as downloaded only when its cache is complete — a non-empty half-fetched file still reads as not downloaded (a 0-byte leftover from an aborted optional file is ignored).

Per-model local paths are persisted per library.

### Florence-2 checkpoint

Florence-2 ships four checkpoints (base and large, each plain and fine-tuned), but only one is active at a time. A checkpoint dropdown in the single Florence-2 card's header picks which one; only the selected checkpoint is downloadable and offered in the action menus.

### Running setup from the app

Enabling a model is **one button**. **Run setup** executes
`python -m media_compost.ui.plugins.setup_action <action>` on the server: it
installs the packages,
builds the dedicated environment if that model needs one, picks the torch
build this machine wants (CUDA / ROCm / CPU), and then downloads the weights —
including the ones that normally arrive silently on first use, which it
triggers by loading the model once. The combined output streams into a live
log, and on success the server restarts itself and the page reloads once it is
back, so everything freshly installed is detected without touching a terminal.
A failed step stops the run and shows the error with a **Retry setup** button.
One setup runs at a time — a second model's is refused while any is running —
and reopening the overlay mid-run resumes the live log.

The same command works in a terminal — `python -m
media_compost.ui.plugins.setup_action insightface_faces`, and
`--list` prints every action's key. It is one command rather than one per
action deliberately: thirty copies of the same four steps drift apart the
moment one of them learns something. The overlay also links to the model's
own card, for anyone who would rather drive their own environment.

Some models need a dedicated Python environment because their bundled code
conflicts with the app's dependencies — Florence-2 is one (setup builds it, or
point at your own with `MEDIA_COMPOST_FLORENCE_PYTHON`). The Hugging Face cache
is shared, so its weights are downloaded like every other model's.

### Downloads as background tasks

Active downloads also appear in the Background Tasks list (bottom-left), each with the model name, live percentage, and a cancel button, alongside AI jobs. A job that succeeds cleanly is auto-removed; one that ran without error but produced nothing usable (an empty caption or tag list) stays as a yellow warning, and failed or canceled jobs remain until cleared. Multi-step jobs report live progress (e.g. "page N / M" for panel detection on a sequence). The panel header carries a **⋯ menu** with the two bulk verbs, each shown only while it has something to act on: **Clear all** removes every finished row — AI jobs, your own import tasks, and finished imports the server is still holding a record of, such as one that failed while nobody was watching — and **Cancel all** stops every running and pending task at once (AI jobs, model downloads, and imports). A finished task's row carries a **⋮ menu** with **Show items in library** (switches to All Items and selects everything the task covered — the way to a *failed* task's items, whose row click shows the error instead of selecting), **View item progress** (for a task covering several items), **View full log**, and **Remove from list**.

A task over **many items** — tagging, face detection, text reading, watermark detection, indexing — carries two more controls while it is active: a **list** button opening its **item list** (every item it covers, marked *done*, *running* or *pending*) and a **pause**. A queued task can always be paused; a running one only where it has a boundary between items to stop at, so a single-item job (a background removal, an upscale, a video render) shows no pause button — there is nothing inside one model run to stop at. A paused task keeps everything it has done, holds its place, and goes back into the queue at that place when the same button (turned round) resumes it.

### What the models do

- **Captioning** — JoyCaption in four modes (Descriptive, Straightforward, Stable Diffusion Prompt, MidJourney Prompt), Florence-2's caption modes, BLIP-2, and Qwen2.5-VL. A generated caption records the model that produced it ("generated by …"), and editing one keeps that provenance while marking it edited.
- **Tagging** — JoyTag (an open Danbooru-style tagger), WD Tagger (a booru tagger on ONNX, no custom model code), RAM++ (thousands of open English labels), and Florence-2 object detection, which also yields bounding boxes plus box-less scene-level tags (e.g. "beach", "night") derived from a second caption pass.
- **Background removal** — withoutBG (open ONNX weights).
- **Watermark removal** — detects watermarks and logos with a purpose-trained YOLO11x model and inpaints them with LaMa, producing a cleaned image or reporting "no watermark detected". When the item already carries boxes on the **watermark tag** (whichever name Settings → Tagging holds), a second variant — **Use tagged boxes (skip detection)** — inpaints exactly those boxes; after an in-place removal it flips that tag from positive to negative, since the item is now watermark-free.
- **Text** — two OCR engines read a page into an editable tree of text regions: RapidOCR (ONNX, per-word boxes) and Magi v3 (comic-aware, English only). Text removal inpaints exactly those regions with LaMa — detect-and-remove is one job, and the reading is kept. It has the watermark side's second variant too: **Use tagged boxes (skip the reading)** paints out the boxes on the **text tag** instead, offered while a text tag is configured and this item carries boxes on it. Both variants read the name from Settings → Tagging, so a library that calls its watermarks `logo` and its text `speech` needs nothing else changed.
- **Faces** — two detectors, InsightFace for photographs and Illustrated faces (YOLOv8 + Magi) for drawn art, each with its own descriptor space for clustering and name suggestions.
- **Pixels and structure** — upscaling, restoration, colorization (including automatic and reference-guided manga colorizers), screen-tone removal, ControlNet-style control images (depth, pose, canny, lineart), and panel detection that cuts a comic page into linked items.
- **Classification** — DINOv2 and CLIP embedders that index pictures (from the import overlay, or the [one-by-one tagging](rankings.md#tag-items-one-by-one) chooser's Index remaining) so a tagging session can order its queue by likeness.

JoyTag's model code ships only in its GitHub repository, not with its Hugging Face weights, so a copy is bundled with the app; the downloaded weights work as-is (its local path can optionally point at a repository clone to use its own code instead).

An AI job runs from the downloaded weights — nothing is fetched at run time, which is why there is no per-model offline toggle. A model is offered only once all of its requirements are met — until then it shows as needing Set up rather than failing mid-run. In an item's Actions menu, a model that isn't ready is not clickable and instead shows a **Set up**, **Download**, or **Set token** chip mirroring the Settings cards; clicking one opens Settings on that model's card.

Every model is a self-contained plugin that runs out of process; a worker keeps the last-used model resident for about ten minutes so consecutive jobs reuse it rather than paying the seconds it takes to spawn an interpreter and read the weights back. A training run takes the card back — starting one releases an idle model at once.

## Storage

The Storage page answers where the library's disk went — the question nothing else could: why a library is 200 GB when its pictures are 60. Every row is a **type**, not a file (which single picture is big is the grid's question — sort by size there):

- A **summary bar** at the top divides the whole library into colored segments — pictures, videos, artifacts, training runs, database, thumbnails, and the rest — with a legend, and reads the segment under the pointer. The library's folder path and the free space on its volume sit beside it.
- **Items** — the source files by kind of item (pictures, videos, sequences), with file counts and sizes. A line notes how much of it belongs to items in the trash — emptying it gives that back.
- **Generated artifacts** — one row per artifact kind and model: cached **training latents** (per base model), control images (line art, edge maps, depth, pose), and the like — each with a **Delete** button that removes every artifact of that type. A cached training latent is safe to delete any time: the next run that needs it re-encodes it. Anything else here means running its model again. (A latent cache a *running* training job is using is protected.)
- **Everything else** — training runs, backups from schema upgrades (with a **Delete** of their own), the database (including its WAL), thumbnails (a regenerable cache), and scratch files.

The numbers come from the database for anything the library records and from a directory walk for the rest, so the page is a fair account rather than an audit.

### Remove files by rule

The rows above delete a *type*; the **Remove files…** button in the Items section header opens a dialog that deletes **files of items** by a rule, which is the other common reason a library is twice the size it should be — an item carrying four versions of one picture because the same folder was imported at four sizes, or a crawl that kept a thumbnail beside every original. Until now the only way to remove one was the Sources list, one file at a time.

The rule is a matcher with guards, and it is applied to **every file of every item**, not only the one on show:

- **Remove when** — a **Media kind** (images and videos, images only, videos only) and three thresholds, **Resolution under** (megapixels), **Shortest edge under** and **Longest edge under** (pixels), are the matcher — the [import overlay](import.md)'s filters read the other way round. All are minimums, so a file below *any* set one is removed — setting more is stricter. Leave one empty and it does not apply; leave all empty and the rule is "everything the guards do not keep". A file whose dimensions are unknown is never matched by a threshold: the rule cannot tell whether it is small, and this delete cannot be undone.
- **Keep** — **The active file** and **Edited files** are the guards. The first spares the version the library shows for each item whatever its size; the second spares anything an editor or a model produced from another file.

The line above the button previews the rule live — how many files, how many bytes, and **how many items would be left with no file at all**. Those items are deleted with their last file: their bytes are already gone, so a trashed copy could only ever be restored into a picture that no longer exists. That figure is the one to read before pressing Remove, and it is what turns amber when a rule aimed at duplicates is about to remove pictures. A rule with no threshold *and* no guard matches every file in the library; it is allowed, and the preview says so in amber.

Removing a file takes the artifacts generated from it as well, and both counts include the Trash. The removal runs on the server in committed chunks — the dialog counts down what is freed, offers **Stop**, and the run outlives the dialog if you close it.

## Training models

Base models and LoRAs for training live in a **Models** tab beside Train and Evaluate — not in the Settings overlay — but they are managed with the same download states, split buttons, and warnings as the models page here. See [The Models tab](training.md#the-models-tab) in the training documentation.

# Evaluate

The Evaluate tab generates test images from a base model with your trained adapters stacked on it, so you can try out training results without leaving the app.

## Choosing a model and adapters

The base model and the adapters sit in one section, because an adapter only means anything in relation to its base model:

- The **model** is picked in two rows. **Model** is the architecture — SDXL, Chroma, FLUX.2 Klein — the same grouping the Models tab and the job editor use. **Weights** is what stands in for its backbone: the built-in releases, your own models based on one of them from the [Models tab](training.md#the-models-tab), and full finetunes (a job and one of its saved steps), each under its own heading, with a one-line description per entry ("1024 px, two text encoders…"). A finetune replaces the base model's weights rather than stacking on them, and adapters stack on whatever is picked here.
- Only adapters **trained on the selected base model** are offered — a finished job's result, any job's kept step checkpoints, whether LoRA or LoKr, and the LoRA files added by hand on the [Models tab](training.md#the-models-tab) for that model — each with its own **weight** (strength).

If the selected model's weights still have to be downloaded, a warning appears as the first row of the Model section, directly under its title: an offline banner naming the environment variable responsible, with a one-click **Enable downloads** button — or, when downloads work but no token is set, a missing Hugging Face token card with the token field right there. Both are about the selected model only — once a model is downloaded, neither offline mode nor a missing token can stop the run, so neither is mentioned.

## Prompt and settings

- **Prompt** and an optional **negative prompt**. Prompt fields autocomplete your library's tags as you type.
- **Size** — starts at the model's native resolution (refilled when you switch models), with a menu of grouped presets (the standard SDXL bucket sizes and common SD 1.5 sizes) next to the width/height inputs.
- **Seed** — defaults to random: a new seed is drawn the moment you click Generate and shown in the seed field, grayed out while random mode is on. Turn the toggle off to reuse or edit a seed.
- **Sampler steps** and **CFG scale**. The CFG row says what the setting costs: anything above 1 makes the model run twice per sampler step (once with the prompt, once without), roughly doubling the time. At 1 or below the second pass is skipped, but the models here are trained to lean on guidance and the picture changes completely without it — treat it as a quality dial that happens to cost time.
- **How much to generate** is one row: **batches × batch size** (up to 50 × 8), with the resulting image count spelled out beside it. A larger batch needs proportionally more memory at the same moment and is only faster where there is bandwidth to spare; more batches simply take longer. The images are unaffected either way — seeds run seed, seed+1, … across the whole set, so an image comes out identical however it was grouped.

The **Generate** button is pinned to the bottom of the column, so it stays reachable however far down you have scrolled, with the same collapsible system-stats footer as the Train tab below it.

## Results

The results are a **contact sheet**: runs made in one sitting — anything up to half an hour apart — share one grid of images under a session header naming when the sitting started, with the number of runs and a **Clear** button that deletes the whole session (images included) after one confirmation. Sessions stack newest first, and the pictures are the page rather than the smallest part of a column of cards.

- **The grid selects like the library's**: a click picks a picture, ⌘/Ctrl adds and removes, shift extends over the reading order, and a click on the only picked one — or on the grid's background — puts it down. A **selection bar** floats at the foot of the grid whenever there is anything in it — Select all, Deselect, **Info** — the preview over the selection, what Space does — and **Remove**, which deletes the picked pictures one by one (a run whose every picture is picked, or a failed run's empty slot, goes whole) after one confirmation; a generation still running is left out of the count.
- **Double-click, Enter or Space opens the lightbox** (the same one as training samples) over the picked picture, with ←/→ stepping through the **selection** when several are picked and through the run's images (the batch) when one is, a button beside the ✕ that opens the full-size file in a new tab, and, as its footer, **that picture's settings card** — the prompt, parameter chips (model, adapters and weights, size, **this picture's seed** — the run's seed plus its position, which is what the generator used — steps, CFG scale), its position in the batch (`3 / 8`), status, total time (counting from the start, so model loading is included), and a **Stop** button while it runs. The prompt and each chip are clickable and put that value back into the form for the next generation, closing the lightbox; **Use all settings** puts every one of them back at once. The card carries no ✕ and no delete button of its own here (the lightbox has a ✕, and removing is the selection bar's). The grid tiles load downscaled copies; the lightbox fetches the original.
- **A run with no picture yet still gets a tile** — running, queued, failed, or cancelled before anything rendered — because the grid is the only place a run appears. Its preview is the settings card **alone** — the same double-click, Enter or Space, with nothing to draw above the card.
- A **running** run shows its live phase in that card (loading model / loading loras / generating, with the sampler step of the batch being rendered and how many images are done), and its images-to-come appear as dashed placeholders that fill in as they land, so the grid takes its final shape as soon as the run starts.

**Cancelling stops the work**: the process is asked to stop at its next sampler step, with a hard kill a few seconds later if it has not. A cancelled run stays in the grid, labeled as cancelled, keeping whatever images it had finished — or saying it was cancelled before any image was generated.

Runs live under `training/_eval/` in the data directory and can be removed with their images once they are no longer running; they are never imported into the library.

## How generation runs

Generations run in the same separate training environment as [training](training.md), one at a time, and the model **stays loaded between generations**: after a run finishes, the generator waits a short while and takes the next queued generation itself if it uses the same model and adapters, so only the first click pays for the loading time. A queued generation for a different model ends that wait immediately and loads the right one.

A model whose weights are large for this machine is not held on the GPU all at once: its parts are moved there only while each one runs, so peak GPU memory stays small and the machine does not start swapping. Whether that applies is decided per model against the machine's system memory (its weights past about a third of it). It costs some transfer time and changes nothing about the images.

## Sharing the GPU with training

Training and Evaluate never use the same GPU at once — on unified memory in particular they would collide as an out-of-memory failure rather than queue on their own. So:

- A generation asked for while a training job holds that GPU is **queued** — its card says it is waiting for the training run — and starts by itself the moment the job pauses or finishes, whether or not the tab is open.
- A training job whose GPU is mid-generation is **accepted and waits** — its card says it is waiting for the generation — and starts itself once the GPU is free.
- A generator merely holding its model warm is not a conflict: starting a training job simply drops the warm model, since training needs the memory more.
- The scheduling is per **device**: a job pinned to a different GPU than the one a generation would use is no conflict at all, and starts (or generates) regardless — though the two cards' waiting lines do not read the device and may say "waiting" over a job on another card.

While anything is generating or waiting, the Evaluate tab's icon carries a small dot — the same quiet indicator the Train tab uses for a running job.

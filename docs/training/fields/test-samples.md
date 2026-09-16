## Test samples

### Generate test samples

Renders your test prompts with the model as it currently stands and files the results in the job’s timeline, so you can watch the concept appear — and notice it going wrong — while the run is still going.

This is what makes a long run recoverable: overfitting is obvious in the samples long before the loss curve says anything useful, and every sample sits next to the checkpoint from the same step, so a good-looking sample points directly at the file to keep.

### Cadence measured in

A step is a fixed amount of work and an epoch is one pass over every training image, so the two cadences drift apart as a dataset grows — “every 250 steps” is most of a small run and a fraction of a big one, while “every epoch” means the same thing in both. It is the choice the checkpoint cadence and the run’s own length already offer, and setting all three the same way is what makes a sample, its checkpoint and a pass over your pictures line up in the timeline.

How many steps an epoch takes is worked out when the run starts, because only the built dataset knows how many entries it has — a film’s frames, a degraded copy and an item contributing one entry per caption all count.

### Generate every

Rendered after this many full passes over the dataset. The equivalent step count is printed in the job’s log when the run starts, so a glance there says what the cadence came out as for this particular dataset.

Sampling interrupts training while it renders, so on a large dataset one round per epoch may be further apart than you want and on a tiny one it may be a pause every few seconds — the log’s step figure is what tells you which.

### Generate every (steps)

Rendered every this many steps, whatever the dataset is. 250–500 is a good rhythm: often enough to catch a concept going wrong, rare enough that the pauses do not dominate the run.

### Baseline before training

Renders the same prompts once before training starts, using the untouched base model.

Without that reference it is genuinely hard to tell what your training did versus what the model could already do — especially for styles, where the base model often has an opinion of its own. It costs one sampling pass at the very beginning.

### Batch size

Sampling interrupts training to render your test prompts, so the time it takes is time not spent training. Rendering several at once amortises the fixed cost of a pipeline call, at the price of holding that many images in memory during a moment when the model, the optimizer state and the latents are already resident — which is exactly when memory is tightest. Raise it only if sampling is a noticeable pause and you have headroom.

The images are unaffected: each prompt keeps its own seed, so a batched sample is identical to an unbatched one.

### Sampler steps

Denoising steps used to render each test image (unrelated to training steps). 20–30 is plenty for a preview; more mostly costs time, and sampling pauses training while it runs.

### CFG scale

How hard the sampler is pushed toward the prompt. Low values (2–4) drift free and look soft; high values (12+) follow the words rigidly and tend to over-saturate. 5–8 suits most models.

For test samples what matters is keeping it FIXED for the whole run — you are comparing steps against each other, so every other variable should stay put.

### Sample seed

The noise every test image starts from. Holding it fixed means two samples of the same prompt at different steps begin from exactly the same starting point, so any difference between them is training — not a different roll of the dice.

That is what makes the timeline readable as progress. Change it only if a particular seed happens to produce a misleading image for every step.

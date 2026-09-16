## Batch & seed

### Batch size

How many images are averaged into a single weight update. Bigger batches give a smoother, less noisy training signal and run faster per image, but memory use grows almost linearly — this is usually the first thing to hit an out-of-memory error.

On consumer hardware batch 1–4 is normal. If you want the stability of a bigger batch without the memory, leave this at 1 and raise gradient accumulation instead: it produces the same averaged update, just spread over several passes.

### Gradient accumulation

Runs N batches back to back, adds up their gradients, and only then updates the weights — mathematically close to training with an N× larger batch, but only one batch is ever in memory.

The cost is time: each update now takes N passes, so a step is N× slower. Effective batch = batch size × accumulation; that product is what to compare between setups.

### Seed

One number that seeds every random choice this job makes: which images are drawn in which order, which crop of each, which tags are picked, and the noise used for the test samples.

Re-running with the same seed and the same settings reproduces the run — that is what makes it possible to change one parameter and know the difference you see came from that parameter and not from luck. Change it deliberately when you want a genuinely different draw from the same dataset.

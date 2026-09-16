## Length & learning rate

### Length measured in

A STEP is one batch pushed through the model and one update of the weights — a fixed amount of work whatever the dataset holds. An EPOCH is one pass over every training image, so the same number means a longer run on a bigger set and the model sees each picture the same number of times either way.

Epochs are usually the easier thing to reason about: “each image about ten times” transfers between datasets, where “3000 steps” does not. The exact step count is worked out when the run starts, because only then is it known how many entries the dataset has — a film contributes its frames, a degraded copy is an extra sample, and an item can contribute one per caption.

### Epochs

How many times the run works through every training image. Each pass visits every entry exactly once, in a fresh random order.

What counts as an entry is the dataset after it has been built, not the number of pictures you selected: a video contributes one entry per kept frame, a degradation variant adds an extra sample beside the clean picture, and with “every caption” an item contributes one entry per caption. That is why the step count appears when the run starts rather than here.

### Total steps

One step = one batch of images pushed through the model, followed by one update of the weights. What matters is roughly steps × batch size relative to your dataset size: with 30 images and batch 1, 3000 steps means the model sees every image about 100 times.

Too few steps and the concept never 'sticks' — samples still look like the base model. Too many and the LoRA memorises the training images: prompts start reproducing backgrounds and poses you never asked for, and unrelated prompts get contaminated. Since test samples are rendered along the way and every checkpoint can be used, it is safer to train a bit too long and pick an earlier checkpoint than to stop too early.

### Learning rate multiplier

The Prodigy optimizer measures how far the weights have moved from where they started and derives a learning rate from that, so the rate is not something you set here — it comes out of the run.

What this field does is scale the answer. 1 accepts it as found and is what you want almost always. Below 1 is a brake, worth reaching for if the run overshoots and samples come out burnt; above 1 pushes harder, which is occasionally useful on a very small dataset.

Prodigy needs a few hundred steps to work its estimate up from nearly nothing, so early samples in a Prodigy run look untrained even when everything is fine. Judge it from about a fifth of the way in, not from the first sample round.

### Learning rate

How far the weights move on every update. It is the single most sensitive setting here.

Too high and training diverges: samples turn into over-saturated, high-contrast mush ('deep fried'), often within a few hundred steps. Too low and nothing visibly changes no matter how long you wait. Typical values: 1e-4 for a LoRA, 1e-5 or lower for a full finetune (which touches every weight and needs far gentler updates).

Learning rate and total steps trade off against each other — halving the rate roughly doubles the steps needed. If early samples look burnt, halve it; if they look identical to the baseline after a third of the run, double it.

If finding this number is the part you would rather not do, the Prodigy optimizer (Memory & speed) works it out for itself.

### LR schedule

Shapes the learning rate over the run instead of holding it fixed.

Cosine starts at the full rate and eases down to zero: big strokes early to learn the concept, fine strokes late to settle the details — the safe default. Linear decay does the same in a straight line. Constant keeps full speed throughout, which learns fastest but tends to still be 'wobbling' when the run ends. Constant + warmup ramps up over the first steps, then holds; the ramp protects the delicate text encoder from a hard first hit.

### Warmup steps

Instead of hitting the model with the full learning rate from step one, warmup ramps it up from near zero over the first N steps.

The first updates are the most dangerous ones: the optimizer has no history to smooth them out yet, and a hard first push can knock the model somewhere it never fully recovers from. Ramping in avoids that. A few hundred steps, or roughly 5% of the run, is typical — and it matters most when the text encoder is being trained or the learning rate is on the high side. With a cosine schedule on a plain LoRA you can usually leave it empty.

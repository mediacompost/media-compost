## Checkpoints

### Keep step snapshots

With this off, the job keeps only the rolling checkpoint it needs to resume after a pause — when the run ends you get exactly one result, whatever the final step happened to look like.

With it on, a permanent snapshot is written at a fixed cadence, and every one of them can be generated with in the Evaluate tab. Since the ideal number of steps is impossible to know up front, this is how you avoid guessing: train past the point you think is right and pick the snapshot that actually looks best.

### Cadence measured in

A step is a fixed amount of work and an epoch is one pass over every training image, so the two cadences drift apart as a dataset grows — “every 500 steps” is most of a small run and a fraction of a big one, while “every epoch” means the same thing in both.

How many steps an epoch takes is worked out when the run starts, because only the built dataset knows how many entries it has. That is also why the disk estimate below can only be given when the run's length is set in epochs too.

### Checkpoint every

Every snapshot is a usable model file: the Evaluate tab can generate with any of them, so you can compare one pass against another and keep whichever looks best.

Counted in passes, the cadence follows the dataset: add pictures and the snapshots stay one-per-pass rather than quietly becoming more frequent than a pass. The trainer prints what it works out to in steps, so the timeline and the log still agree about what a checkpoint is.

### Checkpoint every

Every snapshot is a usable model file: the Evaluate tab can generate with any of them, so you can compare step 1000 against step 2500 and keep whichever looks best. This is the main defense against overfitting — you do not have to guess the right number of steps up front, you just pick the checkpoint that looks right afterwards.

Snapshots cost disk space (the estimate is shown below), which is what the keep-limit is for.

### Keep the last

When a new snapshot is written the oldest of these is deleted, so the window never grows. A LoRA snapshot is small (tens of MB) and you can comfortably keep a dozen; a full finetune snapshot is the size of the whole model, so two or three is already a lot of disk. The resumable checkpoint is kept outside this limit and never counts against it.

### Also keep one in

Milestones that stay for good, spread across the whole run: with a cadence of 200 steps and one in 5, the snapshots at 1000, 2000, 3000 … are never deleted. This is what lets you compare an early style against a late one after the run is over, and it combines with the window above — a snapshot is kept when either rule wants it. 0 turns it off.

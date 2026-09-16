## Memory savers

### Gradient checkpointing

Normally every intermediate result of the forward pass is kept in memory because the backward pass needs it. With gradient checkpointing most of them are thrown away and recomputed on demand instead.

That cuts memory use substantially — often the difference between a run that fits and one that crashes — at the cost of roughly a quarter more time per step. Turn it on when you hit out-of-memory errors, or from the start for full finetunes and large models.

### Attention slicing

Attention is where a diffusion step's memory goes: computed in one piece it holds a score matrix per attention head for every position in the image, growing with the square of the resolution.

Modern PyTorch computes attention with fused kernels that never build that whole matrix, so on an NVIDIA GPU the default is already both fast and memory-efficient — leave this off. Turn it on only when a run is memory-bound and won't fit otherwise: slicing walks the computation in chunks so only one exists at a time, lowering peak VRAM for roughly 10% more time per step.

On Apple silicon the trainer uses the efficient default attention and does not slice, so the setting is fixed off there.

### Optimizer

The optimizer is what actually turns gradients into weight changes. It does that using running statistics it keeps for every weight being trained — and those statistics are memory, which for a full finetune is usually most of what the run needs.

AdamW is the standard choice and the safest. It keeps two statistics per trained weight, so a full finetune pays for the model roughly three times over: the weights themselves, plus two more of the same size.

AdamW (8-bit) stores those two statistics at one byte each instead of four. It is a smaller saving than it sounds, because the weights and their gradients do not shrink, and it needs an NVIDIA or AMD (ROCm) GPU — elsewhere the run says so and uses plain AdamW.

Adafactor replaces the larger of the two statistics with a per-row and a per-column summary of it, which is a fraction of the size. It saves considerably more than the 8-bit variant and it runs on every GPU, including Apple silicon — where it is the only memory saving available at all, since the 8-bit variant cannot run there. What it costs is a little stability: it usually wants a slightly higher learning rate than AdamW, so if a run learns nothing after a few hundred steps, raise the rate before changing anything else.

Prodigy is a different kind of answer. It measures how far the weights have travelled from where they started and works the learning rate out from that as it goes, which removes the one setting here that genuinely has to be found by trial: the right rate depends on the model, the dataset size and what is being taught, so a value that suits one job is wrong for the next. With it selected, the learning rate on the Optimization page becomes a multiplier on what it finds, and 1 means 'as found'. It uses a little more memory than AdamW, and it needs a few hundred steps to work its estimate up — so early samples look untrained even when the run is fine.

For LoRA training the memory differences are a rounding error, since only the small adapter has optimizer state. Leave it on AdamW for a first run; reach for Prodigy when you are tired of guessing the rate, and for Adafactor when a full finetune will not fit.

### Cache latents

The model does not work on pixels. Every image is first compressed by the VAE into a small 'latent' — and since the training images never change, doing that once and keeping the result is pure profit.

So before the run starts, every image is encoded once and written to disk. Training then reads latents instead of JPEGs, which is faster per step, and the VAE can be dropped from memory entirely for the rest of the run. Random crops still vary from visit to visit — they happen on the latent, in steps of 8 pixels, which is far finer than the crop jitter itself.

The cost is disk space and a few minutes up front. The cache is reused across runs on the same files.

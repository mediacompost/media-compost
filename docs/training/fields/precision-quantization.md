## Precision & quantization

### Precision

How many bits each number uses while training. bf16 (16-bit 'brain float') keeps the same range as full precision with less accuracy per number — half the memory, no practical quality loss, and the modern default on any GPU that supports it.

fp32 is full precision: twice the memory and slower, used automatically as a fallback where bf16 is unavailable. fp16 also uses 16 bits but has a much smaller range and tends to overflow into NaNs during training — fine for inference, avoid it here.

### Half-precision master weights

Only for a full finetune, and only there because that is the one run where the trained weights ARE the memory. A full finetune keeps a full-precision copy of every weight it trains, plus a gradient the same size — on SDXL that is 10 GB and 10 GB, against about 2 GB for everything frozen and, with Adafactor, almost nothing for the optimizer's own statistics. This stores them at 16 bits instead of 32.

It works by carrying what the rounding drops. That is not a detail: a training step is far smaller than the smallest change a 16-bit weight can represent, so stored the ordinary way every single update would vanish and the model would never move — measured on a real (small) model over 300 steps, 47% of the weights never moved at all. Keeping the remainder in a third buffer and adding it back to the next update means nothing is lost, only deferred until it is large enough to change the stored value: a hundred updates each a tenth of a step's worth move the weight on the tenth, rather than never.

What it costs is that third buffer, the same width as the weights — so the saving is a third of the memory rather than a half. What it does not cost is quality: over the same 300 steps the loss fell to 0.470 with full-precision weights and 0.471 with these. An earlier version rounded the updates up or down at random instead, which is smaller still (no third buffer) and measurably worse: it learns by an average that is right and an individual step that is wrong, so the loss reached only 0.53, and the noise grows as the learning rate falls — which is exactly what a cosine schedule does for the whole second half of a run.

It cannot be used with Prodigy, which works its learning rate out across all the weights at once and so cannot be stepped one at a time.

### Base model quantization

The base model is by far the largest thing in memory, and during LoRA training it never changes — only the small adapter does. Quantization stores those frozen weights at lower precision while the adapter keeps training in full precision on top (the approach known as QLoRA). It is the WEIGHTS that shrink, not the arithmetic: every matmul still runs at the precision set above, on values converted back as they are used.

8-bit float (fp8) and 8-bit (int8) both roughly halve the base model's memory for a small quality cost — an fp8 round trip moves a weight by a few percent. They differ in what they need: fp8 is a plain data type your GPU either has or hasn't (NVIDIA's Ada and Hopper generations and newer; Apple silicon has no fp8 type at all). int8 runs everywhere — through bitsandbytes on NVIDIA, and through quanto on Apple silicon, where it is what makes the largest models trainable at all. 4-bit (NF4) quarters the weights and is what makes very large models trainable on consumer NVIDIA cards, at a more visible cost in fidelity; it needs bitsandbytes too.

On hardware that cannot do what you picked, the run stops with a clear message rather than silently using full precision and blowing the memory budget you planned around.

### Quantize the text encoder

The base model is not the only large thing held in memory: the text encoder that reads your prompt is frozen in exactly the same way, and on the biggest models it is a substantial share of the total — around 17 GB of Qwen-Image's 58, or 10 of Chroma's 28.

Quantizing it applies the scheme chosen above to those weights too. Measured on Apple silicon, a Qwen-Image LoRA run goes from about 37 GB to 30 with this on, which is the difference between needing a 48 GB machine and a 36 GB one.

What it costs is a little fidelity in how the prompt is read, which is why it is off by default — a run that already fits has no reason to pay it. It can be combined with training the text encoder: the adapter trains in full precision over the quantized weights, exactly as it does over the quantized base model, which is what makes T5-XXL trainable on a 32 GB card.

### Keep the text encoder on the CPU

The row above makes the text encoder smaller; this one takes it off the graphics card altogether. Its weights stay in ordinary system memory and each prompt is turned into an embedding there, so the encoder occupies no VRAM at all — where quantizing it leaves roughly a third of it resident.

Measured on an RTX 5070 Ti at 4-bit, this takes Chroma from 9.6 GB to 5.3 and FLUX.1 from 11.4 to 7.0, which was enough to train FLUX.2 Klein at a resolution that did not previously fit.

What it costs is one pass over the encoder per step, on the processor instead of the graphics card — and the next batch's prompt is encoded while the current one trains, so the card only waits where the processor is slower than a whole step. Measured on a 16-core desktop, T5-XXL takes about 1.3 seconds a prompt: a 1024-pixel step on an RTX 5090 hides that entirely, a 512-pixel step (half a second) does not. It cannot be combined with training the text encoder, which would mean doing that training on the processor.

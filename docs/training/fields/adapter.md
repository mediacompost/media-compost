## Adapter

### Adapter type

Both add a small trainable layer over the frozen model; they differ in the shape of change they can express.

A LoRA adds a 'low-rank' change: two thin matrices whose product is added to each targeted weight. Its capacity is exactly its rank — a rank-16 adapter can only ever make a rank-16 change, however long you train it. That is ample for a character, an object, a colour palette. It trains a little faster, it is the format every tool reads, and it carries better between related checkpoints: a LoRA trained on one finetune of a model usually still works on another.

LoKr builds the change as a Kronecker product of two much smaller matrices instead. The saving comes from that structure rather than from throwing rank away, so the change is not confined to a thin slice of the weight while the file stays a small fraction of a LoRA's — under a tenth of the trainable parameters at rank 8. LyCORIS, whose method this is, suggests reaching for it when a LoRA 'does not learn well enough', and it is generally the better fit for styles and broad visual qualities, where a LoRA's rank ceiling is what you meet first. Its own caveats are the mirror image: slightly slower to train, and a very small LoKr transfers less well if you later swap the base model for a different finetune.

What each can be USED by differs, and it is the file rather than the method. A LoRA is written in the layout every tool reads. A LoKr cannot be: that layout has a place for two matrices and nowhere to put a Kronecker factor. What it gets instead is a copy named the way ComfyUI names LoKr layers, and that works for the models whose layers ComfyUI addresses that way — FLUX.1, FLUX.1 Kontext and the Qwen-Image releases. On the others (SD 1.5, SDXL, Chroma, FLUX.2, Z-Image) a LoKr stays here: it works in the Evaluate tab and as the starting point of another job, but there is no file to hand over. On those, pick LoRA if the result has to leave this app.

### Rank

An adapter does not rewrite the model — it adds a small 'side channel' to certain layers, and rank is how wide that channel is: how much new information the adapter can hold.

Low ranks (4–8) are plenty for a style or a colour palette and are very hard to overfit. Mid ranks (16–32) suit characters and objects with consistent details. High ranks (64+) mostly grow the file and the overfitting risk without helping, unless you are teaching a genuinely broad new domain.

It means slightly different things to the two adapter types. For a LoRA it is the hard ceiling on the change: a rank-16 adapter can only ever make a rank-16 change. For a LoKr it bounds only part of the structure, so a LoKr is not confined the way a LoRA is and its file grows far more slowly as you raise it — which is why the size estimate below is a figure for LoRA and a comparison for LoKr.

### Alpha

The adapter's output is multiplied by alpha ÷ rank before being added to the model, so alpha sets how loudly the adapter speaks at a given capacity. It works the same way for both adapter types.

The usual convention is alpha = rank, which makes the scale factor 1 and keeps behaviour comparable when you change rank. Setting alpha to half the rank is a common way to soften an adapter that comes out too strong. It interacts with the learning rate — halving alpha has a similar effect to halving the rate — so change one at a time.

### Kronecker factor

LoKr expresses a weight's change as one small matrix combined with another. This number decides where the weight is cut into those two parts.

Left empty, the split is chosen to make the two parts as close to square as possible, which is where they are SMALLEST. Moving it either way grows the file, and the two directions are not the same thing: a low factor (4–8) pushes the weight into the second part, which is where the adapter's capacity is — that is the LyCORIS recipe for a LoKr that is not learning enough. A factor far above the square split grows the first, dense part instead, which costs size for nothing.

Measured on a 1280-wide layer at rank 8, against the same layer's LoRA: automatic 0.08x, factor 8 0.13x, factor 4 0.25x, factor 128 0.81x.

There is rarely a reason to set it. If a LoKr adapter is not learning enough, raise the rank first, then try a low factor.

### Train text encoder

The text encoder turns your prompt into the numbers the image model is conditioned on. Training it too lets the run attach meaning to a brand-new token — the classic reason to enable this is a made-up trigger word for a person or character.

It is also the fastest way to damage a model: an over-trained text encoder starts ignoring the rest of the prompt, and everything you generate drifts toward the training set. That is why it runs at a lower learning rate and stops partway through the run. For styles you rarely need it — the image side alone learns those well.

Which encoder that is depends on the model. Stable Diffusion and SDXL train their CLIP encoders. FLUX.1 trains CLIP-L and, unless the switch below leaves it out, T5-XXL; Chroma trains its T5, which is its only encoder. The models whose prompt is read by a language model (FLUX.2, Z-Image, Qwen-Image) offer no encoder training. A T5 adapter is expensive to train — several GB of activations per prompt — so on a card under 48 GB pair it with gradient checkpointing and, if that is not enough, with the text-encoder quantization further down: the adapter trains over the quantized weights exactly as it does over the quantized base model.

### Include the large encoder

FLUX.1 reads a prompt with two encoders: CLIP-L, which produces one summary vector, and T5-XXL, which produces the sequence the transformer attends to word by word. This switch says whether the second one trains as well.

CLIP-L is small (0.12B parameters) and cheap, and training it alone is what most FLUX LoRA tools mean by 'train the text encoder'. T5-XXL is forty times larger and keeps several GB of activations per prompt for its backward pass, but it is the encoder that carries the meaning of a word through the whole prompt — so it is the one to train when a trigger word or a new concept has to be understood in context rather than merely recognised.

Leave it on unless memory is the problem. On a 32 GB card, pair it with gradient checkpointing and 8-bit quantization of the text encoder; a 48 GB card runs it at full precision. The switch is only shown for models that have both kinds of encoder.

### Text encoder LR

A separate, gentler learning rate for the text encoder. It is far more fragile than the image side: the same rate that trains the image model nicely will overshoot here and start dissolving the model’s grasp of ordinary words.

Leaving this empty uses half the main rate, which is the usual convention. If prompts start behaving oddly — words being ignored, everything drifting toward the training set — this is the first number to cut.

### Stop TE after

At this fraction of the run the text encoder is frozen and only the image side keeps training. 0.5 means the first half trains both, the second half trains the image model alone.

The reasoning: the association between your trigger word and the concept is learned early, while visual detail keeps improving for much longer. Freezing early locks in the word without letting the encoder keep drifting toward the training captions.

### Only these layers

By default the adapter attaches to every attention layer in the image model. This narrows that to the layers whose name contains one of the words you list.

Why you might: different parts of the network do different jobs. The later ones carry more of what a picture LOOKS like, and the earlier ones more of how it is put together — so training only part of the network is how a style is learned without also disturbing composition and anatomy. It also makes the adapter smaller and each step faster, since there is less to train.

The names come from the model itself, and the chevron at the end of the field lists the ones worth knowing for the architecture you picked — clicking one adds or removes it, and a tick marks the ones the field already holds. For SD and SDXL they are down_blocks, mid_block and up_blocks, plus attn1 (the picture attending to itself) and attn2 (where the prompt gets in); for the newer transformer models, transformer_blocks and single_transformer_blocks. The field stays free text, because you can be as coarse or as fine as you like: 'up_blocks' takes a whole third of a UNet, 'transformer_blocks.12' takes one block, 'to_k' takes one kind of projection everywhere. The job's page draws a map of the whole model once a run has started.

If what you type matches no layers at all, the run stops and says so rather than training an adapter attached to nothing — which would otherwise look exactly like a normal run that learned nothing.

### Except these layers

The same kind of list, subtracting instead of selecting. A layer whose name matches anything here is left out even if the field above selected it.

It is the easier way to say 'everything except' — excluding 'down_blocks' is shorter and stays correct if the model gains a block, where listing every other block by hand does not.

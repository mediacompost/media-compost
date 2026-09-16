## Base model

### Model

The pretrained model this job starts from. Everything trained here is a modification of it, so its strengths and its blind spots carry over: an anime-trained base stays anime-flavoured, a photographic one stays photographic.

SD 1.5 is small, fast and forgiving — the easiest place to start and the one that fits the least hardware. SDXL is the mainstream quality choice at 1024 px and needs noticeably more memory. Everything below them is a flow-matching transformer: they follow a long prompt far better and they are all much hungrier, because the text encoder is a language model that has to stay resident whatever else you economise on — which is why the largest of them are offered as a LoRA only. Among those, the smallest one that fits your card is usually the right answer, and the estimate under these settings says which those are.

The choice also fixes what the result is compatible with afterwards: an SDXL LoRA only works with SDXL models. Releases that share an architecture are listed together, and those are the ones a LoRA carries between.

### Method

An adapter leaves the base model untouched and trains a small add-on (a few dozen MB) that is layered on top at generation time. It is quick, fits ordinary hardware, can be mixed with other adapters and dialled up or down by weight — and it is enough for styles, characters, objects and most concepts. There are two kinds, LoRA and LoKr, and the Adapter section below picks between them; LoRA is the one to start with.

A full finetune rewrites every weight of the model. It produces a multi-gigabyte model of its own, needs far more VRAM, far more images and much lower learning rates, and it can forget things it used to know. Reach for it only when you are moving the model into a genuinely different domain, not to teach it one more subject.

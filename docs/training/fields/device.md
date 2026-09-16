## Device

### GPU

Which GPU this job runs on. The queue treats every GPU as its own lane: it starts the first waiting job whose GPU is free, so two jobs pinned to different GPUs train side by side while jobs sharing one GPU take turns.

Automatic means the machine's first GPU — on a single-GPU machine there is nothing to choose.

## Videos

### Train on video frames

A video is not one picture, so it is normally left out of a dataset — which is why this is off by default.

With it on, every video the queries match is sampled at the interval below and each kept frame becomes an ordinary training image. A frame carries the video's untimed tags plus the timed ones whose range covers its moment, so a tag that only holds for one stretch of a film only teaches the frames from that stretch.

The frames live in the job's own folder and are thrown away when the run ends. They are re-extracted whenever the dataset is rebuilt, so a run that starts fresh always samples the video as it is now.

### One frame every

A film is tens of thousands of near-identical pictures, and training on all of them would teach the model one scene very thoroughly and everything else not at all.

Seconds is the natural unit: time ranges on tags are in seconds, and frame rates differ between files. Counting in frames is there for short clips where you know the rate and want a fixed stride.

### Drop repeated frames

Sampling at a fixed interval treats a still title card and a fast action scene alike, and a held shot then arrives in the dataset once per interval it lasts — outweighing everything the film actually shows.

With this on, a frame that looks like one already kept from the same video is dropped. The comparison is the same perceptual hash the importer uses to spot duplicate images, so “the same picture” means here what it means everywhere else in the library.

### The film's captions

A caption sits on the video, so a frame can only take all of them or none — a tag has time ranges to say when it holds, and a caption has not.

That matters because plenty of captions describe the film rather than any one moment of it: “a fight scene set to music”, “episode three, the beach”. Training a still against one of those teaches the model to draw what a sentence says happens over minutes.

With inheriting off, frames carry no caption text. On a tags run that costs nothing; on a captions run it means the film contributes no frames at all, because a frame with nothing to build a prompt from is left out rather than trained against an empty one.

### Frames only inherit captions tagged

The finer answer to the same question: rather than take all of a film's captions or none, label the ones that describe a moment and name that label here.

These lists narrow what the run's own caption selection already allows — they never widen it, so a caption the run excludes cannot come back through a film.

### Frames never inherit captions tagged

Usually the easier half to maintain: name the few kinds of caption that are about the film — a plot summary, an episode note, a line about the soundtrack — and leave everything else to reach the frames.

Excluding wins over including, so a caption carrying both an included and an excluded tag is not inherited.

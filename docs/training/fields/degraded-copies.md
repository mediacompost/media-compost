## Degraded copies

### Visits per clean visit

The clean picture is always in the dataset — a degraded copy is an extra sample, never a replacement, and every clean picture keeps the same weight as every other one.

What this sets is the ratio between the two. It cannot conjure steps: a run has a fixed number of them, so degraded samples take their stated share. The mix below says what that works out to.

### Cached variations per picture

The value inside a range is drawn once per picture and kept, so the degraded copy can be cached instead of re-encoded every epoch. With one variation the dataset still covers the whole range — each picture simply sits at its own point on it.

Raise this to give a single picture several strengths to be seen at. It multiplies the number of cached files directly, which the count under the list tracks.

### Add tags

These are what make the degradation trainable rather than just harmful. The model sees the same picture twice — once clean, once spoiled and carrying these words — and learns them as the difference.

They are added to the prompt unconditionally, because every rule that could drop them would leave a bad picture in the dataset with nothing saying so.

### Remove tags if present

A copy that has been through a codec is not 'masterpiece' any more, and leaving the word on it teaches the model that the word means nothing.

Tags are removed before the random pick, so the freed slot is filled by another tag rather than lost — and any tag that was only implied by a removed one goes with it, or removing 'masterpiece' while 'high quality' stays removes nothing at all.

### Remove tags marked

The list above, named by what the library says about a tag. Any tag marked with one of these meta tags comes off this sample.

What it is for is that the claims a degraded copy no longer supports are a CATEGORY, not a list: 'masterpiece', 'absurdres', 'high quality', 'official art' and whatever the next dump adds are all "a claim about the picture's quality". Marking them once means every variant of every job drops them, and the same mark can then say something different per method — a 'resolution_claim' mark belongs on a resize variant's list, a 'fidelity_claim' on a JPEG one.

### Only pictures whose tags are marked

The line above by mark rather than by name: a picture is degraded only if it carries a tag the library marks this way.

Checked against the picture's effective tags, so a tag it only carries by implication counts too. With both lists empty, every picture is fair game.

### Never pictures tagged

Checked against the picture's effective tags, so a tag it only carries by implication counts too, and a picture that is skipped costs no encoding, no cached file and no disk at all — the check happens before anything is made.

### Never pictures whose tags are marked

The veto by mark, and it wins over both lines above exactly as the named list does.

The pair is what makes a degrading run safe on a mixed library: mark the pictures that are already poor — a 'low_quality' or 'rescan' mark on the tags that say so — and no variant can ever degrade one of them further, however broadly the "only pictures" side is drawn.

## Crops & flips

### Max aspect ratio

Images are not squashed to a square. They are sorted into 'buckets' of different shapes but equal pixel area, and each image trains at the bucket closest to its own proportions.

This cap limits how extreme those shapes get. At 2 the widest bucket is 2:1 and the tallest 1:2; anything more extreme is cropped into the nearest allowed shape. Raising it preserves very wide or very tall images at the cost of more buckets (and slightly less efficient batching).

### Random crop

After an image is fitted to its bucket there is usually a little slack on one axis. With random crop that slack is spent differently every time the image comes up, so the model sees slightly different framings of the same picture — cheap variety that helps small datasets generalise.

Crops are bounding-box aware: if a tag in the composed prompt has a box on the image, the crop is steered to keep that box inside the frame, so a prompted subject is never cropped away from under its own tag. Turn it off when exact framing matters (logos, text).

### Horizontal flip probability

Chance that a visit sees the image mirrored left-to-right. It doubles the apparent variety of a small dataset for free, and tag bounding boxes are mirrored along with the pixels.

Leave it at 0 whenever left and right carry meaning: text, logos, asymmetric clothing or hairstyles, characters with a scar or an eyepatch on one side. For generic photographic subjects 0.3–0.5 is a common choice.

### Never flip images tagged

Flipping is free variety for most pictures and quietly destructive for some: mirrored text is unreadable, a logo becomes a different logo, and a character whose scar or parting is on one side learns to have it on both.

Rather than pick one setting for the whole dataset, name the tags that mark those images. An image carrying any of them is never mirrored — not in the cache, not on any visit — while the rest of the dataset keeps the augmentation.

### Never flip images whose tags are marked

The same veto, said once in the library instead of tag by tag here. Any tag the Tags tab marks with one of these meta tags switches mirroring off for every picture carrying that tag.

It is worth the indirection for the reason a list of names goes stale: “text”, “logo”, “signature”, “left-handed”, a dozen characters with an eyepatch — the list in a job's settings is right the day it is written and wrong the next time somebody adds a tag it should have held. Marking the tags themselves puts the fact where the tag is, so a tag added later carries it into every run automatically, and a job written before that tag existed still does the right thing.

Both lists apply: a picture is left unmirrored if it carries a tag named above OR a tag marked here.

## Transparency

### Use alpha as a loss mask

Only images that carry an alpha channel are affected, and only the LOSS is masked — weights are not spatial, so nothing here trains “part of” the model. What changes is how much each part of the picture is allowed to correct it: the visible subject counts fully, the transparent region counts for the background weight below.

The point is to stop the model learning the emptiness. Left unmasked, a cut-out’s background is just a large flat area the model dutifully learns to reproduce, and the subject ends up welded to it.

Two things worth knowing. The mask is applied in latent space, where one cell covers 8×8 pixels, so it goes soft at the edges and cannot isolate anything thinner than that — hair and whiskers are not maskable this way. And because the image encoder reaches across the alpha boundary, the transparent region is filled with a smooth extension of the subject’s edge colors before encoding, rather than left black; without that, the hard edge would be baked into the subject’s own latents where no mask can remove it.

### Background weight

A hard 0 is tempting and usually too strong: the model then never sees a single example of what belongs around your subject, and generations put it in front of whatever the base model invents — often badly matched, because nothing ever taught it how the subject meets a background.

A small weight keeps that signal without letting the empty area dominate the update. It also softens the latent-space edge problem: the fill is an approximation, and weighting it down rather than off means a slightly wrong fill costs you a little accuracy instead of nothing at all.

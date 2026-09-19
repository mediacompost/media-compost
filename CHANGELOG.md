# Changelog

## Unreleased

### Features

- The image editor's ✕ asks what Escape asks: with a second picture open,
  whether to close the window or only this tab. It closed the window outright,
  so the same control meant "close everything" to the mouse and "which of
  them?" to the keyboard.
- The wand's properties bar carries **Inpaint**, like the select and text
  tools': a patch of sky, a speech balloon's inside or a logo's background is
  picked up in one click, and painting it out no longer means changing tools.
- The library grid's **Show sequenced** toggle is now **Fold sequences**, on by
  default: a sequence's members give way to the sequence itself where both
  would be in the view, and stay where it would not — in a group holding the
  pages but not the chapter, or with sequences unticked in the media kinds.
- Shift + an arrow key in the preview leaves a sequence for the item beside
  it, instead of turning its pages one at a time.

### Fixes

- Inpainting reads the selection as an alpha, so a **feathered** selection
  fades the fill in instead of ending at a line. It was binarised at the
  halfway point on its way to the model, which threw the feather away — and
  softening the selection's edge is the app's own answer to a visible inpaint
  seam, so the remedy did nothing. An anti-aliased ellipse or lasso got a
  stepped edge for the same reason.
- The inpainted area no longer sits at a slightly different tone. LaMa
  regenerates the whole picture, and its rendering of the part it was not
  asked to invent comes back one to three levels off, differently per channel,
  so a fill dropped into a sky, a wall or a screentone gave itself away. The
  pixels around the hole measure that offset and it is taken off the fill: the
  step across the seam falls from a mean of 1.70 levels to 0.41 on flat colour
  and from 1.29 to 0.76 on smooth areas of real photographs.
- A picture larger than 2048 px is inpainted downscaled, and the downscaled
  mask now covers every pixel the full-resolution one does. A
  nearest-neighbour downscale *samples* the mask, which left a hairline of
  unfilled hole hugging the seam — the one place a wrong pixel shows.
- Every inpainted pixel came back half a level dark: the model's answer was
  truncated to whole levels rather than rounded, one direction over the whole
  fill.
- The image editor takes the keyboard back when you press on the picture.
  Typing in a properties-bar field — the wand's Grow, either Tolerance box, a
  brush size, a crop ratio — left the caret there for the rest of the session,
  whatever you did on the canvas afterwards, and every shortcut stands down
  over a field: Space stopped panning, M and W stopped switching tools, ⌘Z
  stopped undoing and Delete stopped filling.
- A sequence's repeated page is stepped where it stands: with the same picture
  at two positions, the grid's and the preview's arrow keys went to the item
  after its OTHER position.
- The sidebar's Quick Assign button reads a set's GROUPS as well as its tags:
  a set holding a group showed "Remove from N selected" before it had ever
  been applied, and the press then wrote only the tags.

## 1.0.1

- The project page on PyPI carries the README as its description.

## 1.0.0

First release

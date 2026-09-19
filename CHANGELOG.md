# Changelog

## Unreleased

### Features

- The image editor's **Image** menu lists **Remove artifacts**, **Remove
  screen tones** and **Remove background** beside Upscale and Colorize,
  instead of under a **Remove** of their own.
- The image editor's ✕ asks what Escape asks: with a second picture open,
  close the window or only this tab. It closed the window outright.
- The wand's properties bar carries **Inpaint**, like the select and text
  tools'.
- The library grid's **Show sequenced** toggle is now **Fold sequences**, on
  by default: a sequence's members give way to the sequence itself where both
  would be in the view, and stay where it would not.
- Shift + an arrow key in the preview leaves a sequence for the item beside
  it, instead of turning its pages one at a time.

### Fixes

- Inpainting reads the selection as an alpha, so a **feathered** selection
  fades the fill in instead of ending at a line, and an anti-aliased ellipse
  or lasso no longer gets a stepped edge. The mask was binarised at the
  halfway point on its way to the model.
- An inpainted area no longer sits at a slightly different tone: LaMa's own
  tone bias is measured on the pixels around the hole and taken off the fill.
- A picture larger than 2048 px is inpainted downscaled, and the downscaled
  mask now covers every pixel the full-resolution one does — a hairline of
  hole was left unfilled along the seam.
- Every inpainted pixel came back half a level dark: the model's answer was
  truncated rather than rounded.
- The image editor takes the keyboard back when you press on the picture.
  Typing in a properties-bar field left the caret there for the rest of the
  session, and every shortcut stands down over a field — Space stopped
  panning, M and W stopped switching tools, ⌘Z stopped undoing.
- A sequence's repeated page is stepped where it stands: with the same
  picture at two positions, the grid's and the preview's arrow keys went to
  the item after its other position.
- The sidebar's Quick Assign button reads a set's groups as well as its tags:
  a set holding a group showed "Remove from N selected" before it had ever
  been applied.

## 1.0.1

- The project page on PyPI carries the README as its description.

## 1.0.0

First release

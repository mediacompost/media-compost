# Changelog

## Unreleased

- Opening a big library no longer answers the first views with "The server is
  busy reading the library": the queue that keeps library-wide reads from
  racing each other used to refuse anything that had waited fifteen seconds,
  which on a cold million-item library is most of what a first load fires —
  and a refusal costs more than the wait, since the page asks again. It now
  refuses only a queue that has stopped moving altogether.
- The sidebar's **Untagged**, **Ungrouped** and **Trash** counts are
  remembered until the library changes, the way the grid's own total already
  was. They scanned the whole library on every ask, including all three at
  once after every edit.
- The image editor's **Image** menu has a **Blur…**: a gaussian blur of the
  picture on one slider, previewed live and applied as one undoable step, and
  confined to the selection where there is one.
- And a **Sharpen…** beside it: an unsharp mask on an Amount and a Radius,
  previewed live the same way. **Remove artifacts** in that menu takes a new
  glyph, the old one being what sharpening looks like.
- The image editor opens on the tool it was last left on, across pictures and
  across sessions, instead of on the hand tool every time.
- A colour picked with the image editor's pipette now shows up in the colour
  picker's **Recent** row, like one chosen in the picker itself. A drag
  records the colour it ended on, not every colour it crossed.
- The image editor's **Image** menu has an **Apply background color**: it
  puts the background swatch's colour behind the picture, so a cut-out's
  transparency becomes that colour and everything opaque is left alone. With
  a selection it fills only there, and with the background colour still
  transparent it asks for one first.
- The colour picker lifts itself off the bottom of the window instead of
  running past it, which in a short window took its Done button with it.
- The wand no longer answers with a grid of disconnected single pixels when
  its **Grow** is set: growing a mask ran one pass per bit of the amount, at
  that bit's own offset, so a grow of 8 over a speckle the wand had found
  stamped nine copies eight pixels apart instead of padding it. Grow and
  Shrink selection had it too — 2, 4, 8, 16 and 32 were the pure cases, and a
  find big enough to close the gaps hid the rest.
- The paint-bucket cursor points where the paint lands: its hotspot was the
  bucket's own corner, so the bucket sat over the pointer and the fill
  started down and to the right of where it was aimed. (The other tools'
  cursors were checked with it — the wand was already at the tip of its
  wand, the loupes at the centre of the lens.)

## 1.1.0

- The library grid's **Show sequenced** toggle is now **Fold sequences**, on
  by default: a sequence's members give way to the sequence itself where both
  would be in the view, and stay where it would not.
- Shift + an arrow key in the preview leaves a sequence for the item beside
  it, instead of turning its pages one at a time.
- The wand's properties bar carries **Inpaint**, like the select and text
  tools'.
- The image editor's **Image** menu lists **Remove artifacts**, **Remove
  screen tones** and **Remove background** beside Upscale and Colorize,
  instead of under a **Remove** of their own.
- The image editor's ✕ asks what Escape asks: with a second picture open,
  close the window or only this tab. It closed the window outright, so one
  press discarded every other open picture's window without asking while the
  keyboard route asked.
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

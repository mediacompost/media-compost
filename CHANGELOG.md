# Changelog

## Unreleased

- A training job no longer fails because a picture it trains on was edited
  away underneath it. Merging or deleting a file, or trashing the item,
  used to leave the run's dataset naming a path that is not there, and the
  job ended on a file-not-found — at the next resume, or partway through
  the run. Now: **a resume asks the dataset query again**, so the run
  continues against the library as it is, and where that answer differs the
  job's timeline says **Dataset changed** with how many items came and went.
  A picture that goes while a run is going is skipped with a line in the
  log; only losing every one of them ends the run.
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
- **Bookmarks.** Right-clicking an item in the library offers *Add
  bookmark* — a picture to come back to — and the card wears a ribbon while
  it is marked. Beside the sort and grouping controls, a bookmarks dropdown
  appears as soon as there is one: it lists the marks the current view
  holds, with a thumbnail and a ✕ each, and picking one selects the picture
  and scrolls the grid to it.
- The dropdown chevrons over the library grid are one grey again: the sort
  and Group by drew theirs muted while the bookmarks, quick-actions and
  media-kind buttons let theirs inherit the button's text colour, so one row
  of controls carried three different greys. `shared/Chevron` is the one
  drawing now.
- The library sidebar's tab strip has three answers instead of a switch:
  **Icon and name**, **Icon only** and **Name only**, under *Tabs show* in
  the ⋯ menu. The old **Icons only** tick had no name for its off position
  and no room for the third one; a setting already on carries over.
- The library sidebar's preview, collapsed, is now a row: a small square
  thumbnail on the left with the item's name beside it, instead of a
  full-width preview squashed to 80 px with the name on its own line
  underneath. The thumbnail opens Quick Look; the chevron beside the name
  expands it again. A selection with no picture of its own gets a tile too —
  a sequence's glyph, or a stack for several items — so the header keeps its
  shape whatever is selected, and the sidebar no longer jumps as you move
  through the grid.
- The image editor's **Image** menu has an **Apply background color**: it
  puts the background swatch's colour behind the picture, so a cut-out's
  transparency becomes that colour and everything opaque is left alone. With
  a selection it fills only there, and with the background colour still
  transparent it asks for one first.
- The colour picker points at the swatch it belongs to: an arrow on its
  edge, iPad-style, since the two swatches sit one above the other and the
  panel was the same panel either way.
- It also lifts itself off the bottom of the window instead of running past
  it, which in a short window took its Done button with it.
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

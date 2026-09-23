# Changelog

## Unreleased

- **Right-click a job in the Train tab's list** for a menu of everything
  that can be done to it: start or resume now, queue, pause, edit, log,
  download the result, delete.
- **New training job sits at the foot of the Train tab's job list**, where
  the Evaluate tab keeps Generate, so it no longer scrolls away.
- **Settings → Storage can empty more.** Thumbnails (made again as they are
  shown), every Evaluate result, and every finished training job each have a
  Delete button. Adapters kept from deleted jobs have a row of their own.
- **The Evaluate sidebar is shorter.** Its explanations are behind **?**
  marks, as in the training job editor, and the ones that said nothing are
  gone.
- **The Evaluate grid can be grouped by session, model, adapters or
  prompt**, from the new group-by dropdown above it.
- **The Evaluate grid's section headings no longer have a Clear button.**
  To remove a group, drag a box over it and press **Remove**.
- **The Evaluate grid behaves like the library's.** Drag a box from the
  background to select, pick a size with S/M/L, and every picture sits in a
  square card like the library's.
- **Settings → Storage shows the Evaluate tab's pictures as their own
  row.** They used to be counted as Training runs.
- **The Evaluate grid's selection bar can cancel.** With a slot of a
  queued or running generation picked, it offers **Cancel** beside Remove.
- **Tag counts read 0 in several places and are back**: the suggestions
  under the Train and Evaluate prompts (which also rank by them), the tag
  CSV export's count columns, and the merge and edit dialogs' tag lists.
- **Selections stay smooth when zoomed in, especially in Safari.** With
  a selection on screen every frame used to pay for redrawing its outline,
  and zoomed in a drag redrew it on every mouse move. Dragging out a new
  selection over an old one no longer slows down the longer the drag runs.
- **A blurred selection's outline sits outside it.** The marching ants
  used to be blurred along with the selection's edge; now they run just
  outside every selected pixel, however faintly selected, and the dimming
  shows how soft the edge is.
- **Keep original no longer leaves a trace behind.** Moving or
  transforming a blurred selection used to leave a grey veil where the
  original was, and a round one a thin outline; the original now stays
  exactly as it was.
- **The image editor remembers every tool's settings** — brush, eraser
  and blur sizes and hardness, both colours, the blur strength, the
  marquee shape, the selection modes, the crop ratio and Keep original.
- **Shortcuts keep working after you touch a slider, a button or a
  dropdown** in the editor's properties bar.
- **Hold Alt/Option with the brush or the fill tool to pick a colour**
  off the picture, as in Photoshop. A quick tap of Alt switches nothing.
- **The tag lists that ship with Media Compost are rows of the tag set
  list now, not entries of its Add menu.** Booru, Characters, Photography,
  Cinematography and Documents and screens are in every library, wearing a
  *Built-in* chip and **switched off** — a hundred thousand names is not
  something to put in everybody's tag fields uninvited — and switching one
  on is what writes its entries, so a library never pays for a list nobody
  wants and opening one never costs what the big file weighs. A built-in
  is read-only (no rename, no entry, no category, no delete) and
  **Duplicate** is the copy that is not; it exports like any other set,
  switched on or not; and whether it is offered at all, where it sits in
  the list and its two advice switches stay yours. Pressing a template in
  the Add menu used to make a copy frozen at the file it came from, which
  is a set nobody could keep up to date.
- **And when a new version ships a different version of one of those
  lists, the row says so.** A built-in you have switched on grows an
  **Update available** chip and an **Update** entry at the top of its ⋯
  menu. Nothing rewrites it on its own: that would be a hundred thousand
  rows written while you wait for the window to open, on a launch you only
  meant to be a launch. (Updating replaces the set's entries with the ones
  this build ships, and cannot be undone — what it replaces is the
  previous release's file.) A set you made from one of the old templates
  becomes the built-in on the next open, keeping its entries, its switch
  and its place, and reads as behind so the update is yours to press.
- The tag set **Properties** dialog no longer has a **Hidden** switch. It
  was the same state as the switch at the end of every row of the tag set
  list, one fact with two controls and one of them behind a dialog.

- Evaluate no longer shows half-drawn pictures. A generated image was
  written straight into the run's folder, which the app lists while the
  generation is still going — so a 1024 px PNG, which takes about 40 ms and
  grows in steps, could be fetched mid-write and drawn as the top of the
  picture with white below (the browser decodes a truncated PNG happily,
  and the thumbnailer, which does not, silently falls back to serving the
  raw file). Pictures are now written through a temporary name and renamed
  into place, so one is either there complete or not there at all — the
  rule the trainer's own test samples have followed since they met the same
  thing.
- **A finished training run always has a checkpoint and a sample round at
  its last step.** A cadence is arithmetic — 250 steps every 100 saves at
  100 and 200 — so the state anybody actually wants, the one the run ended
  on, was the only one with no entry in the timeline. Both are written at
  the end now, whatever the cadences worked out to, and neither is repeated
  where the cadence already landed there. The result is saved first, so a
  pause arriving during the closing sample round costs nothing but the
  pictures still to come. With checkpointing switched off nothing extra is
  written: the run's result is then the only copy, which is what switching
  it off asks for.
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

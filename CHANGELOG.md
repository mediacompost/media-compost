# Changelog

## 1.2.0

- Bookmarks: right-click an item to bookmark it; a bookmarks dropdown beside
  the sort controls lists the ones in the current view and jumps to them.
- The tag lists that ship with Media Compost are built-in tag sets. Booru,
  Characters, Photography, Cinematography and Documents and screens are in
  every library, read-only and switched off; switching one on fills it.
  Duplicate makes an editable copy.
- A built-in set shows "Update available" when a new version ships a newer
  list, and updates only when you press Update (this can't be undone). A set
  made from one of the old templates becomes the built-in.
- A built-in tag set has a Make editable button, which adds an editable
  copy, switches it on in place of the built-in and opens it.
- The image editor's Image menu has Blur… and Sharpen…, previewed live and
  confined to the selection if there is one.
- The Image menu also has Apply background color, which fills a cut-out's
  transparency with the background swatch's colour.
- Right-click a job in the Train tab's list for everything that can be done
  to it: start, queue, pause, edit, log, download, delete.
- A finished training run always has a checkpoint and a sample round at its
  last step, whatever the cadences worked out to.
- The Evaluate grid can be grouped by session, model, adapters or prompt.
- The Evaluate grid's selection bar can cancel a queued or running
  generation.
- Settings → Storage can empty more: thumbnails, Evaluate results and
  finished training jobs each have a Delete button.
- The Faces page remembers how you left it, across page switches and
  reloads.
- The image editor remembers every tool's settings, and opens on the tool
  you last used.
- Hold Alt/Option with the brush or the fill tool to pick a colour off the
  picture.
- Colours picked with the pipette show up in the colour picker's Recent row.
- Faces is part of the Tags tab now, behind a Tags / Faces switch. The top
  bar's Faces button and the `/faces` address are gone, and so is Settings →
  Faces → "Hide the Faces tab".
- The Evaluate grid works like the library's: drag to select, S/M/L sizes,
  square cards. Its section headings lose their Clear button (select and
  Remove instead).
- The Evaluate sidebar is shorter: its explanations are behind ? marks.
- Settings → Storage lists the Evaluate tab's pictures as their own row.
- New training job sits at the foot of the Train tab's list, so it no longer
  scrolls away.
- The library sidebar's collapsed preview is a row: a small thumbnail with
  the item's name beside it.
- The library sidebar's tabs can show Icon and name, Icon only or Name only
  (⋯ → Tabs show).
- The tag set Properties dialog no longer has a Hidden switch; the switch on
  the set's row does the same.
- The colour picker points at the swatch it belongs to, and no longer runs
  off the bottom of a short window.
- The dropdown chevrons over the library grid are all the same grey.
- A training job no longer fails when a picture in its dataset is merged,
  deleted or trashed. A resume re-runs the dataset query, and the timeline
  notes "Dataset changed".
- Opening a big library no longer answers "The server is busy reading the
  library".
- Selections stay smooth when zoomed in, especially in Safari.
- Tag counts that read 0 are back in the Train and Evaluate prompt
  suggestions, the tag CSV export and the merge and edit dialogs.
- Evaluate no longer shows half-drawn pictures.
- Keep original no longer leaves a grey veil or outline behind a moved
  blurred or round selection.
- Shortcuts keep working after you touch a slider, button or dropdown in the
  image editor's properties bar.
- The wand's Grow, and Grow and Shrink selection, no longer turn a small
  find into a grid of scattered pixels.
- A blurred selection's marching ants run outside the selection instead of
  being blurred with it.
- The sidebar's Untagged, Ungrouped and Trash counts no longer rescan the
  library on every edit.
- The paint-bucket cursor points where the paint lands.

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

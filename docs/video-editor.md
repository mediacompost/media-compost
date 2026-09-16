# Video Editor

The video editor cuts and transforms a film — trim, remove, rearrange, rotate, crop, resize, change the frame rate — and **nothing touches the file until you save**: every edit is a change to a *cutlist* (which parts of the source, in which order, make up the video on screen), previewed live and rendered into a new file only when you press Save.

## Opening the video editor

Select a video item and click **Edit video** in the sidebar (or use the grid's context menu). The editor is the **Edit** half of the item window — an overlay over the library, with a **mode switch** at the left of the header flipping between **Edit** and **Annotate**. Leaving Edit with unrendered cuts asks first, since a cutlist nobody has rendered is lost when you go.

**Tagging is not done here** — switch to [Annotate](annotation-editor.md) for timed tags, tag ranges, faces, and stills. The annotator's playback chrome is all here too: the floating play/step/timecode controls over the picture, the media bar (speed, volume, subtitles, audio tracks) bottom-left, and the zoom cluster bottom-right. The window plays **the edit**, not the file — removed stretches are skipped, and a gap plays as black.

## The timeline

The bottom panel shows the assembly as a **track of blocks, one per piece**, on a zoomable timeline:

- The **scroll/zoom bar** above the ruler shows the whole film with the playhead marked; drag it to pan, and drag its **edges** to zoom the view. Zoom buttons sit at its left, the scroll wheel pans (`⌘/Ctrl` + wheel zooms around the pointer), and the ruler's steps go down to single frames.
- **Drag a block's edge to trim** that end — a pill names the exact frame as you go, and a trim can also drag a piece back *out*, restoring material that was cut away.
- **Drag a block's body to move it.** The film closes up behind the lift; dropped on material, the piece is **inserted** at the nearest join and everything after it shifts along — dropped on black (or past the end), it lands exactly there, taking that stretch of black's place. Material is never overwritten by a drag. While it moves, both of its edges **snap** to the other pieces' edges, the playhead, and the start, so two clips can be butted together at any zoom.
- **Gaps are ordinary pieces**: drop a piece past the end and the distance is padded with black (drawn hatched on the track). There is no separate "insert gap" button — placing a piece where you want it is how black is made. A gap at the very end is dropped, since a video doesn't end later because its last clip moved earlier.
- **Click a block to select it** (⌘/Ctrl adds and removes, Shift extends); `Delete` / `Backspace` — or the **Remove** button below — takes the selected pieces out. The edit can never be emptied: a removal that would take every piece is refused.
- The **marked range** lives on a lane under the ruler — drag an empty stretch to pull one out; its start, end, and body drag, an edge scrubs the video so the range is picked by the frame, and a plain click on the empty lane clears it.

## The clip actions

Under the track, the actions are grouped by what they act on:

- **At the playhead** — **Split** cuts the piece under the playhead in two there (the output is unchanged; you now have two blocks to move or remove separately), and **Paste** inserts what was cut or copied.
- **Marked range** — **Trim** keeps only the range, **Remove** takes it out, **Cut** and **Copy** put it on the clipboard. The group shows the range's timecodes and the ✕ that clears it.
- **Selected pieces** — the same **Remove / Cut / Copy**, acting on the blocks you picked; the group appears while something is picked.

The clipboard survives switching tabs, so a scene cut from one film can be pasted into another. `⌘/Ctrl+X`, `C`, `V` cut, copy, and paste (preferring the marked range when both a range and a selection exist); `⌘/Ctrl+Z` undoes and `⌘/Ctrl+Shift+Z` redoes, `⌘/Ctrl+S` saves (renders), `Escape` steps down through what is open before it starts closing, and the in/out fields at the row's right end edit as timecodes. The transport's keys are the [annotator's](annotation-editor.md#annotating-a-video): `Space`/`K` play, `←`/`→` a frame (`Shift` a second), `J`/`L` shuttle, `Home`/`End` the ends — all of them, like the timecode pill and the In/Out buttons, in the **edit's** time, so a removed stretch is never something you can land in.

## Rotate, crop, resize, frame rate

The **Video** menu (floating over the picture beside Undo/Redo) offers **Rotate left / right**, **Crop…** (drag a rectangle over the picture, then Apply), **Resize…**, and **Frame rate…**. Everything except the frame rate previews live on the picture — a resize even shows the exact squash or stretch the render will apply.

What is pending shows in a **capsule at the picture's top right** — the rotation, the cropped size, the output size, the new rate — and its ✕ puts the picture back. Undo and redo move the capsule too. Rotating a quarter turn carries a pending crop and resize along with it, so they keep meaning the same region and shape.

## Saving — the render

**Save** renders the edit into a **new file on this item**: the new file becomes the item's active file and the source file is kept intact as a prior version — a cut is never destructive. The Save chevron offers:

- **Save to a new item** — the result becomes a standalone item, linked back to the original as its edit and carrying its tags (with their time ranges), captions, subjects, and links. When the render finishes, the new item opens in a tab beside the original. This is how a *clip* is made: trim to the range you want and save it as a new item.
- **Revert to saved** — puts the whole file back, discarding the cutlist and the picture changes.

The render runs as a **background job** with a progress bar and a Stop button. Closing the window doesn't stop it — the job stays in the background-task list, and reopening the editor finds it again and puts the progress back up. One render runs per item at a time.

Details of the render:

- When the edit touches no pixels, contains no black (a gap has no compressed frames to copy), and every cut starts on a keyframe, the pieces are **copied** from the source without re-encoding — seconds, whatever the length. Anything else re-encodes, which is what makes the cuts frame-accurate.
- The render keeps the **audio track the file marks as default** (not whichever track happens to have the most channels), and never carries the source's chapter markers — they name moments of a film that no longer exists once it is cut.

## Stills and timed tags

For frame-accurate tagging work on a video, switch to the [annotation editor](annotation-editor.md):

- **Take still** captures the current frame whole as an image item linked back to the film, with duplicate detection so the same frame is never stored twice — and a still can also be taken **every N seconds**, bounded by a marked range.
- A film's own tags carry **time ranges** rather than bounding boxes — present in some stretches, pointedly absent in others — edited on the annotator's timeline.

See [Annotating a video](annotation-editor.md#annotating-a-video) for the details.

## See also

- [Annotation editor](annotation-editor.md) — timed tags, stills, and face annotation
- [Image editor](image-editor.md) — cropping and retouching captured frames
- [Item properties](item-properties.md) — where edited versions and linked items appear

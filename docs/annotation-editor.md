# Annotation Editor

The annotation editor is where you draw and edit **tag bounding boxes** on images — and timed tags on videos — with every change saved immediately.

## Opening the annotator

The annotator is one half of the **item window**, an overlay that opens over the library. The window's address is a parameter on the view behind it (`?item=<ids>&mode=annotate`), so reloading or bookmarking brings it back. A **mode switch** at the left of the header flips the current tab between **Annotate** and **Edit** — the [image editor](image-editor.md) for a picture, the [video editor](video-editor.md) for a film.

Open it with:

- The **Annotate** button at the top of an item's [Tags](item-properties.md#tags-tab) section — the Subjects, Places, Events, Captions, and Text lists each have one too, and those open the annotator on the matching sidebar tab.
- A tag's **bounding-box icon** in the Tags list — the annotator opens with that tag row selected, so its boxes start out highlighted.
- The grid's context menu with several items selected — the window then shows **one tab per item** across the top (the same tab strip as the [image editor](image-editor.md)), and `←`/`→` step between the tabs while a picture is on screen (on a film those keys belong to the transport). With a single item the strip is hidden — the header's ✕ is the way out. A film's tab notes where it is parked (`clip.mp4@1:23`).

For an item that belongs to a **sequence** (a comic chapter, a PDF), a pager floats over the picture's top right — `3 / 24` with ‹ › buttons — stepping through the sequence page by page. Turning a page replaces the current tab rather than opening new ones, so a chapter read end to end is still one tab. When the item is in several sequences, clicking the counter picks which one to walk.

Unlike the image editor there is **no save button** — every change is applied immediately, and **undo/redo** (`⌘/Ctrl+Z`, `⌘/Ctrl+Shift+Z`, or the buttons floating over the picture's top left) step through the changes, reversing them on the server too.

`Escape` first steps down through whatever is open — a menu, a pending box, the add-tag field, a rename — and only then closes the window. With several tabs open it asks first — **Close all**, **Close tab**, or **Cancel** — since closing the window takes every tab with it.

A tab whose item is a **sequence container** has no Edit half — the mode switch's Edit segment is disabled with a note, since there is no single file to edit.

## Layout

The media sits over a theme-following transparency checkerboard inside a solid viewport, with a **zoom cluster** at the bottom right and a **theme menu** in the header (**Default** follows the app live; **Light**/**Dark** hold this window at that mode — remembered across sessions).

- Zoom with the scroll wheel (pivoting on the cursor when the image overflows the view) or the zoom controls; the cluster shows the percentage and a fit ↔ actual-size toggle. **100% means one image pixel per device pixel**, so it is true actual size on HiDPI displays.
- Pan by holding `Space` and dragging, or with the middle mouse button.
- The header shows the item's name with its dimensions underneath, and a **file chip** (`#N`) that lists the item's files — picking one changes which file is shown, while boxes are remapped rather than moved (they live in the item's reference frame).
- The right **sidebar is resizable** — drag its left edge; the width is remembered.

## The sidebar

The sidebar is a set of **tabs**, one row of icons at the top: **Stills** (films only), **Tags**, **Subjects**, **Places**, **Events**, **Captions**, and **Text** (images only). A click switches to a tab; **⌘/Ctrl-click** keeps several open at once, stacked in that order. Which tabs are open is remembered **per item**, so a film keeps its Stills view while a still you opened from it shows its own lists.

The lists are the library sidebar's own — the same tag panel, people, places, events, and captions — so everything can be edited without leaving the annotator. A **selection bar** at the bottom of the sidebar counts what is picked and carries the matching actions (Remove, Select all); a removal made there offers an **Undo** right where you did it.

Tag rows carry small markers when a tag is a person, place, or event — clicking one jumps to the tab that edits that half of it and flashes the row.

### The tag list

**The tag list's row selection is the box selection**: selecting a box on the canvas selects its tag row, and selecting rows shows their boxes fully while every other box drops to a thin, faint outline for context. With nothing selected, all boxes draw fully. **Show all boxes**, next to the Tags heading, clears the selection. Boxes carrying a selected tag get a brighter "hot" ring, so you can see what a new box would join.

## Drawing and editing boxes

There is no Add/Edit mode — the gesture says which you meant:

- **Dragging** on the image draws a new box — including over existing boxes, which are draw-through until selected.
- **Clicking** selects the topmost box under the pointer (`Shift`-click toggles). Clicking again at the same spot **cycles selection down through overlapping boxes**, so a completely covered box is still reachable; clicking the box that is already the only one selected puts it down again, and a click on nothing clears the selection.
- **`⌥`/`Alt`-drag** sweeps out a **marquee** that selects every box it touches (`Shift` keeps the current selection).
- Only a **selected** box takes the pointer: move it by dragging its body, resize with the corner handles.
- **`Delete`** (or `Backspace`) removes the selected boxes — undoable like any other edit.

A hint bar at the bottom left spells out the gestures.

### Polygons

A **box ｜ polygon** switch in the canvas bar (remembered across sessions) picks the shape a drag makes. In polygon mode the corners are laid **click by click**: finish on the first corner, with `Enter`, or with a double-click; `Backspace` takes the last corner back and `Escape` cancels the draft. A rectangle is a polygon with four corners as far as editing goes — in polygon mode a selected rectangle shows its corners, and dragging one converts it; small midpoint dots insert a corner, and a picked corner is removed with `Delete` (the box itself goes only when it has no corner picked). Every reader that wants a rectangle — training crops, the sidebar's box indicator, the preview — gets the polygon's bounding box, so a shape costs nothing downstream.

- A new box takes **whatever tag rows are selected in the sidebar** (several rows = a box carrying several tags).
- With nothing selected, drawing **prompts for a tag name** before the box is committed. The prompt has an **Add** and a cancel (×) button, and the box stays adjustable while it waits — drag its body or corner handles — so a slightly-off drag doesn't have to be redrawn. `Escape` discards it.
- A new box lands in the **tag group** of the selected row (Ungrouped when nothing is selected). Each tag on a box shows a small **group pill**; clicking it moves that tag to a different group — Ungrouped, an existing group, or a new one.

### Box labels and tags

- Each box draws in its tag's **own color**, derived from the tag name — the same tag is always the same color, so boxes are identifiable without reading labels. The **label chip** is shown only for the selected box.
- A box can carry **several tags**: the **+** control on its label adds another tag to the same box. The label bar sits above the box and flips below it near the top edge.
- **Double-click** a label chip to rename its tag. Remove a tag from a box with the × on its chip; removing the last tag deletes the box.
- Every tag field is the same **autocomplete** as the sidebar's "Add a tag…" — usage-sorted, arrow-key navigable, with a "Create …" row for new names. Spaces typed into any tag field become underscores.

Boxes are stored in the item's **reference frame** (its original image), so a box stays aligned when the image is cropped or another file version is active. A box may fall partly outside a cropped file's frame — that's allowed.

## Faces (the Subjects tab)

On a picture, opening the **Subjects** tab shows a second layer over the image: the faces found on this item, each drawn as an **oval outline** (a head is not rectangular) with a row centred underneath — the person's name, or **"Who is this?"**.

- Clicking the name chip opens a name field in its place, already focused with the existing name selected, plus a ✓ and a ✕ beside it. **Naming a face puts that subject's tag on the item.** A model's guess shows with a percentage until you confirm or reject it.
- The button beside the name is the one way to be rid of a face, and it depends on where the face came from: on a **detected** face it **dismisses** — the detector stops offering the same false positive again — while on a face **drawn by hand** it simply **deletes** it.
- **Dragging on the picture draws a face by hand** — it carries no detector score, and no later detection run can take it away.
- Faces select like boxes — click to pick, and picking an oval highlights the matching crop in the Subjects list (and the other way round). A **picked** face moves by dragging and resizes by its four corner handles, detected ones included: the first hand edit of a detected face keeps the detector's own rectangle aside, so a re-run refreshes that record rather than your edit, and the sidebar's ⋯ menu offers **Reset the box**.
- A **face ｜ person** switch beside the box ｜ polygon one picks what a drag draws: a face, or a **whole-figure outline** for a person. An outline lands on the people rows picked in the sidebar (or, with nobody picked, waits under a "Who is this?" field); it is drawn as a rectangle or polygon, moves and resizes once picked, carries the name and a ✕ underneath, and is what a training crop keeps in frame for that person when they have no box of their own. In outline mode the face ovals recede, and in face mode the outlines do, so one layer never competes with the other.
- **Detect faces** sits at the top of the Subjects list, with a tick on the detectors that have already run on this item.
- Name suggestions put whoever you named most recently first; the order is remembered in the browser.

See [Subjects and Faces](subjects-and-faces.md) for the full face workflow.

## Reading text (the Text tab)

On a picture, the **Text** tab shows what an OCR engine has read — blocks, lines, and words, drawn as green outlines on the image while the tab is open. Run an engine from the top of the list; when several engines have read the file, a dropdown picks whose reading is shown (remembered per item). Lines can be corrected in the list — a correction is never overwritten by a re-run — and **dragging a rectangle on the picture adds a text box of your own** to transcribe into. A picked region's box moves and resizes on the canvas (a slanted reading keeps its slant), and an `⌥`/`Alt`-drag sweeps up several regions at once.

## Annotating a video

For a video, the playback controls float over the bottom of the picture: play/pause, frame-step, and ±5 s jumps in one pill, with the full timecode beside them — editable to seek. The keyboard drives the same transport: `Space` or `K` plays and pauses, `←`/`→` step a frame (`Shift` a second), `,`/`.` step a frame too, `J`/`L` shuttle backwards and forwards at growing speed, `Home`/`End` jump to the ends. Below the canvas sits the **timeline panel**, resizable by dragging its top edge.

- **Speed, volume, and subtitles** sit in a small floating media bar in the video's bottom-left corner. The subtitles menu lists every track (embedded ASS/SRT tracks are converted so the player can render them, aligned the way a desktop player shows them); an **audio-track** button appears when the file has several audio tracks. Where the browser cannot switch audio tracks (only Safari can), the other tracks are greyed out with a note saying why. A button whose setting is off the default is drawn in the accent color.
- The timecodes are full SMPTE (`HH:MM:SS:FF`) and **editable one field at a time**: click a field, type digits, `↑`/`↓` step it, `←`/`→` move between fields, `Enter` seeks. The in/out fields at the timeline panel's right end edit the same way.
- The timeline has its own **scroll/zoom bar** above the ruler: it shows the whole film with the playhead marked, drags to pan, and its **edges drag to zoom** the view; zoom buttons sit at its left, `⌘/Ctrl` + scroll wheel zooms around the pointer, and the ruler's steps go down to single frames.
- The **marked range** lives on a lane under the ruler: drag an empty stretch to pull out a new range; its start, end, and body are draggable, and dragging an end scrubs the video to that edge so the range is picked by the frame — the playhead stays where the drag put it. A plain click on the empty lane clears the range.

### Timed tags

**A film's own tags carry time, never geometry** — a tag applies to the whole film, to a range, or to a single frame. There are no bounding boxes on a moving picture; anything picture-shaped is a **still** instead (below).

Every timed tag gets a **track of its own** on the timeline, always — its stretches drawn as blocks you can take hold of: drag a block's **body** to move the stretch, its **edges** to trim it, **click** it to select — a block's selection is its sidebar row's, because they are the same stretch of film — and **double-click** it to flip its sign. Still marks ride on the ruler above the tracks.

On the Tags tab, the film's whole-item tags come first, then **At this frame** — every tag whose range covers the current frame, where adding a tag tags the current range or frame.

- **A timed tag gets one row per time range**, each with its own sign: the row's dot flips just that stretch between present (green) and pointedly absent (red), and removing the row removes just that stretch — or the tag, when it was the last one. Each row spells its range out in timecodes.
- **Two ranges of one tag can never overlap**, whatever their signs — an edit that lands on another range takes the ground: one it covers disappears, one it straddles keeps the pieces either side.
- The "At this frame" and "Stills" headers carry **‹ ›** buttons that jump to the previous/next frame where the answer changes — where the set of tags changes, or a still was taken — so a film can be swept without scrubbing blind.
- Subjects, places, and events are timed the same way — each **is** a tag — and their sidebar rows spell out the stretches they cover.

### Add range / Subtract range

The row under the timeline shows the marked range (with a ✕ to clear it) and offers **Add range** and **Subtract range** for the rows selected in the sidebar — tags, or people, places, and events:

- **Add** makes every selected tag cover that stretch as well; touching or overlapping stretches fuse into one.
- **Subtract** cuts the stretch out of what they cover; a tag left covering nothing at all is removed from the film.
- Adding to a whole-film tag ties it down to that range; subtracting from one does nothing.
- The range and the selection both stay in place afterwards, so the same range can be applied to another tag or the opposite operation done with one click.

### Stills

The **Stills** tab (films only, and their first tab) lists **the whole film's stills** — every frame somebody kept — so it answers "which frames have I already taken". Two ways to fill it:

- **Take still** captures the current frame **whole** as an ordinary image item that links back to the film. A still carries tags, tag groups, and bounding boxes with exactly the machinery any imported picture has, and it can be trained on, exported, and deduplicated like any other image. It also **inherits the film's tags at that moment**.
- **Every N seconds** queues a background job that samples the film at a fixed interval — bounded by the **marked range** when one is set, so a scene can be sampled on its own. The interval hides behind the small tune button beside it, and the reply says how many stills the run will take.

A frame can only be taken once — the button reads **"Frame already taken"** when it exists. Every capture runs through the library's duplicate check: an image already in the library is **adopted** as this film's still at this moment, and one image can be the film's still at several timestamps.

There is no cropping here — to keep part of a frame, take the still and crop it in the [image editor](image-editor.md); the crop links back to the still (crop → still → film).

- A still's row is **selected exactly while the playhead is at its moment** — a still *is* a moment of the film, so there is no second selection to manage. A single click **seeks** to that moment; a **double-click opens the still in its own tab** of this window, where it gets the full annotator — every tab, every box tool. Hovering a row shows a pencil (open) and a bin (remove); removing asks first, since a still is an item and goes to the Trash with everything tagged on it.
- Stills also show as small ticks on the timeline's ruler; clicking one seeks to it.

Each film tab resumes at the frame you left it — while the window is open, and again on the next open, since the position is remembered in the browser. If this browser can't play the file (for example Safari with an MKV), a short notice replaces the frame; whole-item tagging and metadata still work.

## See also

- [Item properties](item-properties.md) — the tags panel this sidebar mirrors
- [Tags](tags.md) · [Subjects and Faces](subjects-and-faces.md)
- [Video editor](video-editor.md) — cutting and rendering a film
- [Image editor](image-editor.md) — pixel editing and cropping

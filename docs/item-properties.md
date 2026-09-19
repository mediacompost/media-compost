# Item Properties (Right Sidebar)

The right sidebar shows everything about the items you have selected in the grid — their name, files, metadata, tags, captions, links, and the actions you can run on them.

## Selection basics

- With **nothing selected**, the panel is about **everything in the view** — see [Actions over the whole view](#actions-over-the-whole-view) below. The [Quick Assign](#quick-assign) bar stays available at the bottom.
- **Back / Forward** buttons at the top navigate through your previous selections, browser-style. Following a link (for example a row in the Links section) counts as a navigation, so Back returns you to the selection you came from. Making a fresh manual selection clears the forward history.
- The **Pin** button locks the current selection: you can keep browsing groups and changing filters while the pinned items stay shown in the sidebar, but you cannot change the selection until you unpin.

## Preview and name

For a single image or video, a **preview** sits above the tabs, pinned so the sections scroll under it. Hovering it reveals:

- **Rotate left / right** (top right) — turns the item 90° at a time. The picture turns at once on screen while the server bakes a turned copy losslessly: an imported original is never rewritten — the turned version is added as a new, edited source file and made active — while a file that is already an edit is rewritten in place. A rotation is logged and reverts.
- **Quick Look** (top left, an eye) — opens the full-size preview, same as pressing `Space`.
- A **chevron** (bottom left) that collapses the preview and brings it back. You can also **drag the preview's bottom edge** to any height; both the height and the collapsed state are remembered.

Below the preview is the item's **editable name**, which wraps onto as many lines as it needs — a long file name is shown whole, never cut off. The item's type, dates, dimensions, and other facts live in the [Info tab](#info-tab). Sequences show no preview (they own no single file).

## Tabs

A tab strip groups the panel's sections:

- A **single click** switches to a tab.
- **⌘/Ctrl-click** toggles a tab without closing the others, so several can be open at once; their sections stack in tab order.
- The open tabs persist across selections and reloads. **Actions** is the default tab.
- Tab buttons wrap onto extra rows in a narrow panel. Most tabs carry a **count badge** (source files, tags, subjects, places, events, captions, instructions, groups + links, text blocks; the Sequence badge counts the sequences a member item belongs to, or the members when a sequence itself is selected).
- **A badge turns amber when something under it is a machine's claim waiting for an answer** — a pending tag under Tags, a suggested person under Subjects, a pending caption under Captions or Instructions — so the strip says where the work is without opening each tab.
- A **⋯ button** at the end of the strip lists every tab. Its eye icons **hide** tabs you never use from the strip (a hidden tab still opens from this menu, and the ⋯ button carries the sum of the hidden tabs' counts), and an **Icons only** setting drops the tabs' names so ten tabs fit one row.

The tabs are: **Sequence** (only for sequence-related selections), **Ranking** (only while a [ranking](rankings.md)'s view is open), **Actions**, **Files**, **Info**, **Links**, **Groups**, **Tags**, **Subjects**, **Places**, **Events**, **Captions**, **Instructions**, and **Text**.

## Actions tab

What you can *do* with the selection:

- **Edit image / Edit video** — opens the [image editor](image-editor.md) or [video editor](video-editor.md) in its own window.
- **Annotate** — opens the [annotation editor](annotation-editor.md), directly below the edit button.
- **Merge into one item** — shown with exactly two items selected: all files, groups, tags, and captions of the second item are folded into the first, and the second item is removed.
- **Create sequence (N)** — shown with two or more items selected; groups them into a new ordered sequence in selection order.
- **Hide/Show** and **Move to trash** — or **Restore** and a permanent **Delete** when the selected items are in the Trash. (The panel asks the *items*, not the open view: a pinned selection of live pictures browsed into the Trash view is never offered the permanent delete.)

### Edit section (still images)

Collapsible AI actions that add their result as a new source file on the item:

- **Remove background**.
- **Remove watermark** and **Remove text** — two buttons, both inpainting the region from its surroundings. Each has two ways in, and they are symmetric. The *reading-driven* one detects (watermark) or paints out what the [Text tab](#text-tab) holds (text) — for a file nothing has read yet, the menu instead offers a **detect and remove** entry per reading engine, which reads the page (keeping the result in the Text tab) and then removes it in one job. The *tag-driven* one — **Use tagged boxes** — paints out the boxes this item carries on the tag [Settings → Tagging](settings.md#tagging) names for watermarks or for text, and is offered only while the item actually has boxes on that tag (a text tag is optional, so with none configured the text variant never appears). An image with no watermark reports "no watermark detected" and changes nothing.
- **Upscale image** — super-resolution with two photo models that clean as they enlarge (Real-ESRGAN 2×, sharper and inventive; Swin2SR 4× real-world, smoother and faithful) and a Real-ESRGAN 4× model tuned for anime and line art.
- **Clean artifacts** — at the original size: FBCNN removes JPEG block and ringing artifacts; SCUNet removes sensor noise together with compression artifacts (and sharpens a little; it is trained for photographs, not drawings). SCUNet processes the whole picture at once, about 5 GB of graphics memory per megapixel (half that in fp16), so a picture too big for the card is skipped with a note in the job; on Apple silicon a picture past about 4 megapixels runs on the CPU instead, which is slower but correct.
- **Colorize** — automatic photo colorization (Colorful Colorization), automatic manga colorization (Manga Colorization v2, the recommended manga model), and an **example-based** manga model that transfers the palette of a reference image you pick. Choosing the example-based model opens a **reference picker** with recently used references and an upload tile; you can also drag an image onto it, and hover a thumbnail for a ✕ that removes it. The menu's **Add as color reference** entry snapshots the selected item into that list, so a colored page can serve as the reference for other pages. References are temporary app data, not library items.
- **Remove screen tones** — converts manga screentones into smooth greyscale gradients, with the same models the [image editor](image-editor.md)'s Remove menu offers (the neural OpenComic descreen pair and the download-free FFT filter).

Every one of these adds its result to the item it ran on, as a new source file that becomes the item's active one — the earlier version stays in the [Files tab](#files-tab-source), so the run is undone by making it active again. (Brightness/contrast lives in the [image editor](image-editor.md).)

### Detect section

Actions that *find* something in the picture rather than altering it, offered for still images — and for a selected **sequence** whose members are all still images, where the job runs page by page as one background task with a progress bar:

- **Split comic panels** — detects the panels of a comic or manga page and turns each panel into its own item, cropped from the page and linked back to it. Panels land in the same groups as their page; a panel that exactly matches an existing image links from that item instead of creating a duplicate. A **Place panels in a sequence** toggle (on by default) also gathers the panels into a new sequence linked back to the page — on a sequence, all pages' panels form one new sequence ("&lt;sequence&gt; — panels") in reading order. Overlapping, non-rectangular panels are separated cleanly — each crop keeps only its own content.
- **Detect faces** — the detected faces land in the [Subjects tab](#subjects-tab). The menu ticks a detector that has already run over the item.
- **Detect text** — reads the picture with an OCR engine; the result lands in the [Text tab](#text-tab). The menu ticks an engine that has already read the file.
- **Detect watermarks** — finds logos and watermarks and records them as boxes on the tag [Settings → Tagging](settings.md#tagging) names for them, which is what the box-driven **Use tagged boxes** removal then paints out.

### Generate section

Control-image estimators whose results are stored as artifacts under the item's source file (see [Files tab](#files-tab-source)):

- **Estimate depth** — Depth Anything V2, MiDaS, ZoeDepth, and LeReS.
- **Estimate pose** — OpenPose skeletons rendered from YOLO11 keypoints, plus a full body + hands + face variant.
- **Estimate Edges** — Canny (no download needed) and line art in one menu.

Each menu lists its models with their download or setup state, and every action queues a background job.

Note that **Generate caption** and **Generate tags** are not in the Actions tab — they sit at the top of the [Captions](#captions-tab) and [Tags](#tags-tab) sections.

## Files tab (Source)

A radio list of the item's source files; the selected radio is the item's **active file** — the source of its thumbnail, preview, and exports. Each entry shows the file's format, dimensions, and size. A file captured from a video reads "Video frame @ &lt;time&gt;" (or a clip's time range). Edited or derived versions are labelled *edited* and always link back to the file they came from.

Each row offers:

- A **preview** button that opens Quick Look on that specific file (the overlay has an open-raw-file button).
- A **⋯ menu**. When the item has more than one source, it also offers to **delete** the version or to **split it out** into its own new item (for images that were merged by mistake). A split-off item links back to the item it came from and inherits its groups, tags, and captions.
- A **Sources** button (compass icon) beside the preview button, carrying **how many sources the file has**. It opens an overlay listing the filenames the file was imported under (with their relative import paths) and any web URLs (with access times); sources can be added, edited, and removed there, with file paths listed first and then URLs. The count is the reason to press it — where a picture came from, and from how many places, is the one thing on the row that has a number. There is one door and it depends on what is behind it: a file with no sources yet wears no button and keeps a **Sources** entry in its ⋯ menu instead, so recording a first one is still reachable.

### Picking several files

Once an item has more than one source file, each row grows a **tick box** beside its radio, and the picks are acted on from the sidebar's selection bar:

- **Delete** removes every picked file. It asks first, naming what goes and warning that the stored bytes go for good — there is no History revert for a delete. If other files were edited from one being deleted, the question says so, and notes that the deleted file is also what a re-import of the same picture matches against: import the original again later and it may arrive as a **new item** rather than joining this one.
- **Split** moves every picked file into **one** new item — not one item each, which is the opposite of what picking three of them meant. The new item links back to the one they came from and inherits its groups, tags, and captions; the moved files are renumbered #1, #2 … in the order they had here, and an edit lineage among them is kept (a lineage half-left-behind is cleared, since it would point at a file that is no longer there).

The tick is its own target rather than the row's click, because clicking a file row already means something else here — it makes that file the item's active one. **⇧** on a box extends the run from the last one pressed. Neither verb is offered for a pick of *every* file: an item with no files at all is not a thing, so with all of them ticked the bar simply does not show them.

A split is **revertible from [History](history.md)**: the files go back onto the original item with their numbers, their bytes, their artifacts and their lineage, and the split-off item disappears — but only while that item still holds just the files the split moved, so one you have since built on is left alone.

### Artifacts and latents

Nested under each file:

- **Generated artifacts** — the ControlNet-style control images (depth map, pose skeleton, Canny edges, line art) produced by the Generate actions, each with buttons to open it in a new tab or remove it.
- **Training latent** rows — cached tensors encoded for training, named by model, bucket size, and variant. You can remove them to reclaim disk (a later run re-encodes what it needs) — except while a training job is running, when the delete is refused with that reason.

Each file row also says when it was added (or edited); the item's own dates are in the Info tab.

## Info tab

All of an item's metadata:

- The first row is the item's **ID** (its stable uid), with hover buttons to filter the grid to that item and to copy the uid.
- **Images**: width, height, resolution, format, pixel mode, and what the file says about itself — the indexed EXIF, XMP and IPTC fields, the same set a search can reach.
- **Videos**: width, height, resolution, format, length, frame rate, and bitrate, plus the container's own metadata.
- **Sequences**: uid, type, item count, and import/modification dates.
- The item's **Type**, **First import**, **Last import**, and **Modified** (its last library change) dates also live here.

**Metadata is per file, and the item answers with its active file's.** A row reads "from file N"; when the item's other source files say something different, an **Other files say** section lists it. Hover buttons decide what the item keeps: **Keep this for the item** pins a value from any file (a pin sits beside the active file's answer, and is what a merge carries across), **Stop keeping** unpins it, **Ignore this for the item** mutes one of the active file's answers, and **Use this again** unmutes it. Search reads the active file's values less the muted ones, plus the pins.

**Nearly every row is filterable**: hovering reveals a button that adds a matching condition to the [query builder](search.md). Numeric and text rows default to equals, and date rows compare the full capture date. Rows the search catalog has no name for carry no button — a sequence's member count, and the Modified stamp. EXIF dates are formatted per your date and time preferences. Long values (such as the uid) wrap onto their own line instead of being truncated.

### Tracks (videos)

For a video, a **Tracks** section lists the file's video, audio, and subtitle streams — codec, dimensions, frame rate, bitrate, channels, sample rate, and language, in selectable rows. A stream's name (for example a "Signs" subtitle track) leads its header; a ✓ marks streams enabled by default, and a stream noticeably shorter than the longest track shows its own duration. Attachment and data streams are hidden behind a "Show N …" toggle.

## Links tab

An item's relationships, in two sections:

- **Links** — items derived *from* this one: rotations, editor-saved edits, a video's clips and frames, comic panels, and manually added derivatives.
- **Linked by** — items this one derives from (for example the original it was edited from).

Each row shows the linked item's thumbnail, its name with the link's meta tags under it (a still's row names its moment in the film), and **Go to this item** / **Preview** buttons; clicking the row selects that item. The row's **⋯ menu** offers **Merge into this item**, **Merge into linked item**, **Swap link direction**, and **Remove link**.

Links can carry any number of **meta tags** — free-form chips added with an autocomplete field. Meta tags are a separate namespace from item tags, managed in the [Tags tab's Meta mode](tags.md).

**To add a link, drag items from the grid onto a section** — onto Links for an outgoing edge, onto Linked by for an incoming one. Invalid drops (the item itself, already-linked items, cycles) are rejected or skipped with a brief note.

With **several items selected**, the tab aggregates: each row is an item any of the selection links to (or from), and eight pictures linked to one page are one row. The per-relationship ⋯ actions stay single-item.

## Groups tab

The groups the selection belongs to, with an autocomplete field to add it to a group. Typing a name that matches no group offers to **create** it and add the selection in one step. Groups are removed with the trash button on their row. With several items selected, groups that are not common to all of them appear in a separate section with buttons to add or remove them from the whole selection.

## Tags tab

Everything the picture is labelled with, as a **tags list** with **Annotate** and **Generate tags** buttons at the top. Who is in the picture, where it was taken, and what was happening live in the [Subjects](#subjects-tab), [Places](#places-tab-and-events-tab), and [Events](#places-tab-and-events-tab) tabs of their own.

### The tags list

- Each tag row starts with a **colored dot**: green for positive, red for negative, yellow for mixed across a multi-selection. **The dot is the toggle** — clicking it flips the tag between positive and negative.
- The number of selected images carrying the tag follows its name; tags sort alphabetically. A ✕ removes a tag (or, in a group, that instance of it).
- Selecting tag rows highlights, in the grid, every item carrying all of the selected tags; removing the whole selection is the [selection bar](#the-selection-bar-and-the-undo-bar)'s **Remove N** button.
- Tags are added with the autocomplete search field; a special entry creates a brand-new tag. Spaces in tag names become underscores.
- A tag with a **bounding box** shows a box icon after its name — hover it to preview the highlighted area, click it to open the [annotation editor](annotation-editor.md) on that tag. A video tag with **time ranges** shows a clock icon; hovering lists the ranges as timecodes, clicking opens the annotator.
- A tag that is a **subject**, **place**, or **event** carries a small person, pin, or calendar icon after its name (hover for the display name and comment, or the formatted address, or the event's span). Clicking one opens the tab where that half of the tag is edited and flashes its row. A **face icon** follows the person icon when a detector found that person here — hover to see the picture with their face boxes drawn on; click to land on the crops.

### Tag groups (single item)

For a single item, direct tags are organized into **groups**: an **Ungrouped** default plus any named groups. The same tag can live in several groups as separate instances (it still counts once for search). Each group has its own add-tag field, an editable name, and optional **meta tags** labelling the grouping itself (these never become tags of the item). Rows have a drag handle; dragging selected rows onto a group card moves them, and a drop zone below all groups **creates a new group** from the drop — that is how groups are created.

Indirect tags appear below in read-only sections: one per contributing library group, a **Tag hierarchy** section for tags implied by other tags (each labelled with the tag that entails it, for example "← poodle"), and a **Sequence contents** section for a sequence's member tags. An indirect tag the item also assigns directly is greyed — the direct assignment wins. In the **Tag hierarchy** section a row's ✕ does not remove anything: it assigns that tag **negatively**, since the entailment stands and what you are saying is that this picture is an exception to it.

Each instance in a group carries its own sign: the same tag can be positive in one group and negative in another, and the dot on a grouped row flips that instance alone, while the item's tag as a whole reads negative only when every instance is.

### Pending tags

Machine-generated tags land in an **auto-managed pending group** per generation run, named after the model that produced it. Its header has accept-all (✓) and dismiss-all (×) buttons; accepting a tag moves it to Ungrouped, and approving is recorded in [History](history.md) as a revertible change. When an accepted pending instance joins a group that already holds the tag, their bounding boxes are merged.

### Multiple items

With several items selected, the panel aggregates the tags and keeps the per-item tag groups: the ungrouped rows first, then a section per group name found across the selection (pending machine groups last, in amber). A row on only some of the selection carries a signed count chip — "2+", "2−", or "2+ 1−" when the signs disagree — and a ✓ that gives the tag to the rest; Flip and the grid highlight act on the name, and removing a grouped row takes that instance off each selected item.

## Subjects tab

Who is in the picture — the people and the detected faces, one list from both ends.

- Each **person row** shows the subject's display name, their comment (what tells two people of one name apart), and (when set) a date subtitle — the year of the picture or the subject's age in it. Row actions (set the date or age, edit the subject, jump to the subjects list, search for every picture they are in, remove them from this item) live in a **⋯ menu**; **Add a subject…** autocompletes the catalog and can create a new subject on the spot. Subject autocompletes list whoever you named most recently first.
- **Detect faces** at the top offers the two detectors — **Illustrated faces (YOLOv8 + Magi)** for drawn art and **Photographic faces (InsightFace)** — and stays offered once faces exist: running the other detector over the same picture is normal in a mixed library, and a re-run never loses work.
- Each **face row** is a small crop with who it is, which detector found it, and how sure it was; hovering outlines the face in the whole picture. A face can be **several people at once** (a character and their actor), each with an age of its own; the ✚ after the row's title adds another name.
- A face the detector **recognizes** waits for your confirmation with an amber outline, a tick, and a cross; its guessed name is put on the picture as a *pending* tag until you decide. Dating a guess accepts it.
- A **detected** face's way out is "Not a face" — a dismissal that is remembered, so the same false positive is not offered again; dismissed faces sit greyed behind a link at the bottom, where they can be restored or deleted for good. A face **drawn by hand** (in the annotator) is instead deleted, which reverts.

See [Subjects and Faces](subjects-and-faces.md) for the full behavior. With several items selected, the tab aggregates like the Groups tab: a person on some of the selection shows an "n / N" count and a ✓ that adds them to the rest.

## Places tab and Events tab

**Places** and **Events** rows work like subject rows, with their own ⋯ menus — see [Places](places.md) and [Events](events.md). Both tabs also offer **suggestions**: a picture carrying an event's tag is offered its venues, and a picture whose capture date falls inside an event's span is offered the event — accepting writes an ordinary tag, declining is remembered. With several items selected, both aggregate like the Subjects tab.

The Events tab is headed by the **Date taken** row: the item's capture date, with a subtitle naming an automatic source ("from the file's EXIF data" or "from the event below"). Its ⋯ menu offers **Set/Change the date** (a year is enough — precision is whatever you type), **It has no date** (an answer of its own: a scanned print carries the scanner's date, and this is how that date is removed rather than replaced), and **Automatic**, ticked while nothing overrides the file and the events — picking it clears an override.

## The selection bar and the undo bar

The subject, place, and event rows share **one selection** across their tabs (they are all tag assignments, and the one action they share is taking them off): click picks a row, ⌘/Ctrl adds and removes, Shift extends across section boundaries, and clicking the only picked row puts it down again. Near the bottom of the sidebar floats a **selection bar**: empty, it reads "None selected" with **Select all**; with rows picked, **Remove N** sits at the left (plus **Accept N** when machine guesses are picked — removing a guess also records the refusal) and **Deselect** at the right. Every selectable list in the panel — tags, groups, captions, instructions, links, sequence members, text blocks — reports to the same bar; it shows whichever list currently has rows picked.

A removal made from the bar — or from a row's own ✕ or ⋯ menu — offers itself back in an **undo bar** above it, with one button that flips between Undo and Redo. Everything it reverts is also in [History](history.md).

## Captions tab

Shown only for a single selected item: the item's captions, with a **Generate caption** button at the top. Every caption carries its own **meta tags** as small chips under the text — click a chip's ✕ to remove it, or the dashed **+ tag** chip to add one. Meta tags label the annotation (its language, origin, purpose) rather than the image, and the query builder's Caption condition can filter by them.

**While a caption is being written the picture is shown large over the grid**, because a caption is usually about a detail. It **zooms** — the wheel, a drag to pan, and the same zoom cluster the rest of the app uses — and an **✕** puts it away when the grid is what you want instead; it comes back the next time a caption field is focused.

**⌘/Ctrl+F searches the caption being edited.** The browser's own find cannot see inside a text box, so this one is the app's: it highlights every match, says which one you are on, steps through them with ⏎ and ⇧⏎ (or the arrows), and **Replace** / **All** rewrite one or every match. What is selected when you press it becomes the search term. Escape closes the bar and puts the caret back in the caption.

## Instructions tab

The same list of the other kind, also for a single item. A caption says what the picture **is**; an **instruction** says how it was **made from other pictures** — "make it snow" — and carries an ordered list of them. It lives on the **result**, because that is the picture an [edit model](training.md) has to produce from the instruction and its inputs.

- Under each instruction's text sits a strip of **numbered thumbnails**. **Drop items from the grid** onto it to add them (the item itself, and anything already referenced, are skipped with a short note); **drag a thumbnail** to reorder — the order is what the model is shown, so every thumbnail says where it sits; a corner ✕ removes one.
- Every change is one History entry, so the sidebar's undo bar offers it straight back.
- Instructions carry the same **meta tags** captions do, and the query builder's **Instruction** condition asks the same questions of this list.
- There is no "Generate instruction" button: only you know what was done.
- **The two lists never mix.** Each caption is in exactly one of them, each tab counts only its own, `CAPTION:` never matches an instruction and `INSTRUCTION:` never matches a caption, and a training run builds its prompts from one kind or the other.

Instructions are a library-side list: the [annotation editor](annotation-editor.md) has no Instructions tab and no Links tab, because both are about the item's place among *other* items — which is a question you ask in front of a grid you can drag from.

## Text tab

What the picture **says** — the text an OCR engine read off it, as editable blocks with their lines. A **Detect text** button at the top runs the engines that have not read this file: **RapidOCR** (per-word boxes; three variants — multilingual for Chinese/Japanese/English and most Latin scripts, plus Korean and Cyrillic models) and **Manga (English)**, the Magi OCR engine (comic-aware, English only). Corrections you type survive a re-run, and where several engines have read the file, a dropdown picks which reading is shown. A reading belongs to the file it was read from, so an edited or switched active file reads as never-read. The blocks are what **Remove text** paints out.

## Sequence tab

Shown only when the selection is sequence-related, and listed first when present.

- For a **member item**, it shows every sequence the selection belongs to, each as a collapsible block with an editable name and a button to open the sequence in the grid. Members are listed in order and numbered; clicking members mirrors the grid's selection behavior (plain, `Shift`, `⌘/Ctrl`, press-and-drag). Hovering a member shows a thumbnail preview at its own aspect ratio. Members are reordered by dragging their handle and removed with the hover remove button. A **Sort sequence** button below the list reorders all members by name, ascending or descending.
- For a selected **sequence item**, the tab lists that sequence's own members. A sequence inherits the tags of the items it contains (shown like group-inherited tags) and can carry tags of its own.
- Every sequence records how it came to be as its **kind** — `archive` (built from an imported archive), `pdf` (a PDF's pages), `gif` (an animated GIF's frames), or `manual` (made in the app, or by a panel split). The kind is provenance only; all sequences work identically, but a re-import recognizes its own sequences by it. (An older library may still hold `video` sequences from a removed import option.)

## Ranking tab

Shown while a [ranking](rankings.md)'s view is open in the Library, and about the picture picked in it: where it stands — one row per pool, reading `7 / 9` against that ranking's scale — and how many comparisons put it there. Under them two verbs that deliberately do not read alike:

- **Not applicable** sets the picture aside on this axis. Its comparisons are kept and the button turns into **Rate it after all**, so it is reversible.
- **Remove from this ranking** deletes every comparison the picture was part of and refits without it. It names the count and asks first — this is the one thing about a ranking [History](history.md) cannot undo.

The same verbs are offered at two other sizes: over a whole **selection** (the tab, with several pictures picked) and over **everything in the view** (the panel with nothing selected). A picture that has not been placed yet says so instead of showing a standing.

For large selections (more than 200 items), the tag, group, and sequence details are hidden and only Quick Assign remains, to keep the sidebar responsive.

## Actions over the whole view

With nothing selected the sidebar does not go blank — it becomes about the set you are looking at. It names the scope first — a heading and the exact number of items.

Under it:

- **Edit** — the same result-adding actions the Actions tab has (remove background, watermark or text, upscale, clean artifacts, colorize, remove screen tones), each with its model menu and the count it will run over.
- **Generate** — Generate tags, Generate caption, and the control images (depth, pose, edges).
- **Detect** — faces, text, watermarks. For the kinds that record a per-item run (faces and text), the items that model has already been run over are left out: over a whole library that is the difference between minutes and hours, and the reply says how many were skipped.
- **Groups** — pick a group and **Add** or **Remove** every item in the view.
- Then **Hide** and **Move to trash**, each asking how many first.

Everything here applies to the **whole view**, not to the pictures on screen. The ids never reach the browser — a view can be the entire library — so what travels is the grid's own search scope, and the server resolves it and writes in committed batches. That also means "everything here" cannot drift from what the grid is showing: the two send the same request.

A whole-view **permanent delete** is deliberately not offered. Hiding and trashing are reversible, which is what makes them safe over a scope nobody has enumerated; erasing a library's worth of pictures stays the Trash's own **Empty Trash** button, where what is about to go can be looked at first.

In the **Trash**, and for a view with nothing in it, the plain "Nothing selected" placeholder is shown instead — every one of these actions means something else in there, and the Trash's own whole-view action is the Empty Trash bar at the foot of the panel.

## Quick Assign

A separate section at the bottom of the sidebar holding a list of prepared **sets** — each a mix of tags to assign as **positive**, tags to mark as **negative**, and **groups** to file the items into — ready to be stamped onto items:

- **Every row is a set and its own editor**: chips in one alphabetically sorted list, an autocomplete field to add, a close button on each chip, a ✕ to delete the set. The field adds **groups as well as tags** — an empty field browses the group tree, and a typed fragment offers the matching groups before the tags. A group has no negative form, so a set's groups are only ever added. The **+** button in the section header adds a set; there is always at least one, sets and their numbers survive a reload, and the section is resizable at its top edge (the list scrolls past the cap).
- **Up to nine sets carry a number key** (1–9). The badge at the start of a row shows the set's number (or "–" for none); clicking it opens a dropdown to change it — picking a taken number swaps the two sets, and the list keeps itself sorted by number, moving the renumbered set (now selected) into place.
- **Clicking a row selects that set** (clicking again deselects). The selected set is what the assign button, **Shift+Q** and the click-to-assign mode stamp.
- **The button** applies the selected set to the current selection (shortcut: **Shift+Q**). When every selected item already carries the full set, it becomes a red **Remove** button that strips the set instead; with nothing selected in the grid it applies to the **whole current view**, saying so ("Apply to all N in view"). With **no set selected** it reads "Quick assign…" and opens the overlay below.
- **Q opens the quick-assign overlay**: every numbered set under its key, over a dimmed library. Rows are coloured for the current selection — **green** when every selected item carries the whole set (the digit then removes it), **yellow** on a partial match (the chips the selection already carries are greyed out). Pressing **1–9** stamps that set; with nothing selected the overlay works on the whole view. **A bare digit also works without the overlay**, over a selection only. (For free-form tagging from the keyboard, see the **T** quick-tag overlay in [Library](library.md).)
- The **⋯ menu** in the header holds two switches: **Enabled** — the master switch that makes every quick-assign surface inert (the shortcuts, the digits, the mode and the button; the section greys out) — and **Assign on click**, the *mode*: clicking an image in the grid stamps the selected set onto it directly instead of selecting it. Items carrying the full selected set show a small badge on their thumbnail; clicking the badge removes the set. Both are remembered across sessions.
- Whether an item "already carries the set" is judged against its **direct** tags and its group memberships — tags inherited from a group don't count and aren't removed. Everything that answers that question reads the whole set: the button's green Remove state, the overlay's row colours, the thumbnail badge and the greyed-out chips.

## See also

- [Tags](tags.md) — the tag catalog, aliases, implications, and meta tags
- [Subjects and Faces](subjects-and-faces.md) · [Places](places.md) · [Events](events.md)
- [Search](search.md) — the query builder the metadata filter buttons feed
- [Library](library.md) — the grid the sidebar describes

# Import

This page explains how to get files into the library through the web app, what happens to them during import, and how duplicates, videos, and archives are handled.

## Opening the import overlay

There are three ways to start an import:

- Press the **import button** (an upload icon) to the right of the "Library" header in the left sidebar.
- On an empty library, the grid's own **Import files** button.
- **Drop files onto the window.** The overlay pops up as soon as a file drag enters the window (only from the Library tab, and only when nothing else is open); it closes again automatically if the drag leaves the window or is cancelled without dropping.

The overlay has two columns: the **drop zone** and the files waiting to go on the left, and the import options on the right.

## Staging files

**Dropping files does not start the import.** Files collect under **Files**, where you can:

- Remove a single file with its ✕, or clear the whole list. Rows select like the grid's (click, Shift, Cmd/Ctrl), and a **Remove N** button takes the picked ones out together.
- See anything the app cannot read staged greyed out and struck through, labelled *Not supported* — it is left out of the run.
- Add more files at any time — drop them anywhere in the window (the dimmed backdrop around the modal is a drop target too) or use the system file picker. Dropping the same folder twice adds nothing the second time.

**A dropped folder is read before it is staged, and the drop zone says so while it happens.** Walking a big folder takes seconds during which nothing else on screen moves, so the zone stays lit the way it is under a drag, its icon becomes a spinner, and the line under it counts the files found so far. A number going up is the one thing nobody reads as "stuck".

The **Import N files** button in the footer starts the import — so you can still review the options after the files arrive. Pressing Import closes the overlay; from that moment the import runs in the background.

**The overlay always offers the command line, folded away.** A browser import uploads every byte to the server and stages it on disk before the importer reads a file; [`media-compost import`](cli.md#media-compost-import) reads the files where they lie. So between the drop zone and the file list sits a folded line — *Import from terminal (faster)* — that opens to the **exact command for the settings on screen**: the library folder, the parent group, the grouping switches, the minimums, the type filter and the tags, each spelled out only where it differs from the command's own default. Everything in it is quoted for a shell, so a folder, group or tag name with a space (or a quote, or anything else) is safe as printed.

The **paths are placeholders** — `/path/to/…`, named after what was dropped — because a browser is never told where a dropped file came from, only each file's path relative to what was dropped. They sit **last**, in their own colour, and **Copy leaves them out**: what lands on the clipboard is the command up to the paths, ready for the real ones. Face detection and indexing are app-only background tasks, so the panel says so rather than quietly leaving them out of the command.

## Import options

The options are grouped by the question each answers:

| Group | Option | What it does |
|---|---|---|
| Where it goes | Add to group | A dropdown choosing a parent group for the imported items. Resets each time to the group currently selected in the sidebar (if exactly one is), or none. |
| Where it goes | Put them in a new group | A switch that makes a group *inside* the one above, holding just this import, with an optional name (the default is the date and time, to the minute). Lazy like a folder's group: a run that imports nothing leaves no empty group behind, and re-running the same import lands in the same box. |
| Ignore | Add a filter | The rules are added **one at a time** from a menu offering whatever is not on the card yet, and the row disappears once everything is. Six rules: **Resolution under** (megapixels), **Shortest edge under** and **Longest edge under** (pixels) — three minimums a file must clear; **Aspect ratio under** / **Aspect ratio over** — a shape range as **width ÷ height** (1 is square, 0.5 twice as tall as wide, 2 twice as wide as tall), either end on its own; and **Ignored file types** — a multi-select of whole types to leave alone: images, videos, sequences (a PDF, an animated GIF, a comic archive) or archives (a zip that scatters into items). Removing a rule clears its value, so a row that is gone has stopped filtering. |
| Tags | Add tags | Tags for everything the run creates — an ordinary tag field with chips, autocomplete and a +/− flip for a negative assignment. |
| Tags | Tags by type | A disclosure with three more fields, tagging only the **images**, **videos** or **sequences** the run creates, on top of the ones above. |
| Tags | Also tag skipped items | On by default: a duplicate the import recognized gets the tags too. Every tag a run puts on is recorded on its History entry — a re-import that only tagged existing pictures gets one of its own — so the lot reverts in one step. |
| Grouping | Folders become groups | Recreates the dropped folder structure as groups. |
| Grouping | Archives become groups | Puts an archive's extracted files into a group named after it. **Off by default.** |
| Grouping | Archives become sequences | Builds an ordered sequence from a non-comic archive's images (comic archives always become sequences). |
| Grouping | Sequences join groups as | Which half of a sequence lands in the run's groups: the sequence and its items, the sequence only, or the items only. |
| Detect | Detect faces | Runs face detection over every imported picture as a background task, with a model picker that appears once it is on. |
| Detect | Index for smart ordering | Indexes every imported picture as a background task, so the [tagging sessions](rankings.md) can order their queue by likeness without an indexing wait. Its picker takes **more than one embedder**: the spaces are indexed independently and never mixed, so asking for both DINOv2 and CLIP is two runs over the same pictures rather than a third kind of likeness. At least one stays picked — the switch above the picker is what turns indexing off. |

The aspect range is **orientation-aware**: a 2000×100 banner and a 100×2000 column are opposite answers, not the same shape, so "no panoramas" (`Aspect ratio over 2`) leaves tall pictures alone. It is ANDed with the minimums like everything else in this card.

**The three minimums are the Storage page's [file-prune rule](settings.md#remove-files-by-rule) read the other way round** — the same three thresholds, in the same words, with the same rules: an empty field is "not set", a file must clear **every** one that is set, and a file nothing could measure is never left out (the run cannot say whether it is small). The two edge thresholds ask different questions and neither implies the other: the short edge is about a thumbnail (small however it is shaped), the long edge about a picture that is small in the direction it is widest.

A **sequence is kept whole**: it is imported when *any* of its pages clears the minimums, so one big page brings the small ones with it — a chapter with holes in it is not what a page filter was asked for — and a book with no page over them is left out entirely (no pages, no sequence, no group). The **file types** are four buckets that partition what an import can be handed, so every source falls in exactly one; a *page* of a book is never judged by them (ignoring images would otherwise hollow out a comic), while a plain archive's members are items of their own and answer for themselves.

The filters run before anything else happens to a file, so what they turn away is not stored, not folded into a near-duplicate, not counted as a duplicate that refreshes some existing item's dates, and not deleted from where it came by a move-import. Such a file is **ignored**, which is its own outcome: "the library already has this" (skipped), "this app cannot read it" (skipped as unsupported) and "you told me not to take it" are three different answers, and the background task counts the ignored ones on a line of their own.

Face detection runs as one background task after the import itself has finished — nobody is named automatically; the detected faces wait in the [Faces tab](subjects-and-faces.md#the-faces-tab) and under **Pending → Faces**. The row stays switched off and explains itself when no detector is installed. **One task for the whole import, not one per uploaded batch**: an import hands its files over a few hundred at a time, and each batch's new pictures fold into the detection task already running — so the progress bar covers the run rather than a two-hundredth of it. Indexing behaves the same way. Neither holds the import up: the import reports itself finished before the queue is touched, so the files keep flowing while the detector works through what has arrived.

**A sequence is two things, and you say which of them joins the groups.** A comic archive, a PDF or an animated GIF comes in as one sequence holding the items inside it — pages, or a GIF's frames — and **Sequences join groups as** picks between *the sequence and its items*, *the sequence only* and *the items only*. Each keeps its own level whichever you pick: the items go where the archive's contents go, and the sequence to the level the archive file itself sits at — falling back to the archive's own group when that level has none, so a book dropped on its own is never left out of the group its own items are in.

**Archives become groups** is **off** by default: a comic archive already comes in as a sequence, which is the thing that holds its items in order and the thing the library shows, so a group around the same items is a second container saying less — and a folder of forty chapters made forty of them.

**The footer offers a reset** whenever anything on the screen is off its default (the toggles are remembered between imports, so after a while it is genuinely hard to say what is still set). It puts every setting back, the parent group included, and disappears once there is nothing left to undo.

**A row whose model is not installed carries a Set up button**, right there in the row — the same affordance the library sidebar's actions use. It opens Settings → Actions with that model's own card highlighted, so the row is one click from being usable rather than a sentence naming a page to go and find. The app shows one dialog at a time, so this closes the import overlay; **the staged files are kept** and are still there when it is reopened.

The toggles, the filters and the model pickers are remembered across reopens and page reloads; the parent group and the whole Tags card reset each time — a "batch1" typed last month riding next month's import is the one thing a remembered field must not do.

With "Archives become groups" on, an archive's extracted images go into the archive's own group, and the sequence item it produces is placed one level up — at the same level as the archive file itself. Where that level has no group of its own (an archive dropped at the top of an import), the sequence joins the archive's own group rather than none at all.

## Background import tasks

**Everything staged becomes one import background task per press of Import.** The task appears in the left sidebar's **Background Tasks** panel with a live percentage, a cancel control, and a **view-files** button that opens a per-file list with each file's import status (uploading, processing, done, or the error). A file that landed on an item you cannot see — one in the Trash, or hidden — is flagged there, and the task row counts how many did ("N out of sight"). Videos take a while to process, since every frame is examined.

Pressing Import closes the overlay, and closing it never cancels anything — the import keeps running as a background task. Cancelling the task from the panel aborts its in-flight upload and holds its remaining files; a cancelled task can be **resumed** from the same row, and picks up with the files it had not sent.

Large imports upload in **batches** — many files per request — so a 2000-file import is a handful of requests, with the grid refreshing once per batch. If a batch's upload fails at the transport level, it is split in half and retried, so only the genuinely bad files end up flagged as errors.

**An import survives the page that started it.** The browser owns the task list — it is holding the files — so reloading during an import throws that list away, but the server keeps its own record of every run. Any import the page no longer owns appears in the panel by the name of what was dropped: a still-running one with its count, and a **failed** one with its reason, which stays there until it is dismissed with its ✕. A run that finished cleanly is not listed, exactly as a finished model task is not.

## Supported formats

- **Images**
- **Videos**
- **Archives**: `.zip`, `.7z`, and comic-book archives `.cbz` / `.cbr`
- **PDFs** — see below
- **Animated GIFs** — see below (a single-frame GIF is simply an image)

Archives are extracted automatically during import, and every supported format inside one imports — pictures, GIFs, PDFs, videos, comic archives, and archives nested inside archives — each handled exactly as it would be on its own. A group made for a folder gets a folder icon; one made for an archive, a PDF or an animated GIF gets an archive icon.

## Deduplication

Files are only imported if they are not already in the library; groups are assigned regardless, so re-importing lets you re-organize without creating copies.

- **Exact duplicates** (byte-identical files) are skipped. A re-import refreshes the item's last-imported date, so it floats to the top of a newest-first sort.
- **Near-duplicates** — images that are visually the same but not identical (for example the same image at a different resolution) — are added as an **alternative source file** of the existing item. Edited files are compared against both their original and edited versions.
- **Frames of a film are exempt from that fold.** Consecutive frames of a video are near-duplicates by construction, so where either side of a match is a frame of a film — the incoming picture matched the library's frame index, or the existing item is already linked to a video as one of its frames — only an **exact pixel match** merges (a PNG and a WebP of the same screenshot are still one picture). Every other screenshot becomes an item of its own, linked to the film at its timestamp, instead of piling up as "alternative" files of one item.

When a near-duplicate arrives, it becomes the item's **active file** if it is higher quality than the current one: a clearly higher resolution wins outright, and at about the same resolution a lossless format (PNG, BMP, TIFF) or more bytes per pixel wins. This never overrides your own edit: if the active file is an edited or derived version, it stays active regardless of an incoming higher-quality import. A byte-identical re-import never changes the active file.

To avoid collapsing images that merely look alike, a near-duplicate match found by perceptual hash is confirmed by a **secondary pixel comparison** before the images are merged; if they don't actually match, the incoming image becomes a new item.

**The further apart the two hashes are, the better the pixels have to agree.** At the edge of the neighbourhood the hash has almost stopped being evidence, so the pixel check carries the decision on its own. This is what keeps manga pages that are the *same artwork with the speech bubbles translated* from folding onto one item, while a nearly blank page — whose hash wanders a long way on nothing more than a re-save — still folds onto its own re-encode, because its pixels barely move at all.

## Reorientation detection

During import each new image is checked for being a **reorientation** of an existing item — a 90/180/270° rotation, a horizontal or vertical flip, or a combination (all eight orientations are compared, using a direct pixel comparison on small grayscale thumbnails, so different-but-similar photos are never linked). Crops are not detected.

When a reorientation is confirmed, the incoming file is **folded into the matched item as an alternative source file**, with the transform it arrived in (its rotation, and whether it is mirrored) recorded on the file — the same fold a near-duplicate takes, so one picture stored upright and sideways stays one item rather than two linked ones. Because the match is pixel-verified, different-but-similar photos are never folded. Reorientation detection always runs on import — there is no per-import opt-out.

## Video import

A video imports as a single video item; its length, frame rate, and bitrate are recorded (a byte-identical video already in the library is recognized and not stored twice). Instead of turning every frame into an image item:

- **Every frame is examined** and compared against the images already in the library. When a frame matches an existing image, the frame is saved — losslessly, at full resolution — as an **alternative source file** of that image (its Source section reads "Video frame @ ‹time›"), and a **frame link** with the timestamp is recorded from the image to the video.
- Every frame's perceptual hash is kept in an index, so a **screenshot imported later** is recognized too and linked back to the video at its timestamp(s) — one timestamp per appearance, so a shot that comes back later in the film gets two.
- A frame only matches an image whose aspect ratio is roughly the same (within ~15%), and every match is pixel-verified before anything is merged.

A video never becomes a sequence: a sequence is something read in order — a GIF's frames, a book's pages — and the frames a film happens to match in the library are a scattered subset of it, not a reading order. The frame references and links are the record. New frame images can be captured later from the [video editor](video-editor.md).

## Comic archives

Comic-book archives (`.cbz` / `.cbr`) import like any other archive, but their pages are additionally marked as an ordered, numbered **sequence** in natural page order, named after the archive — regardless of the "Archives become sequences" setting. Re-importing the same archive (same name and the same pages in the same order) does not create a second sequence; the existing sequence's import date is refreshed instead.

## PDFs

A PDF imports as a book of pictures: every page is rendered and ingested as an ordinary image item — with the same deduplication, hashing, and thumbnails as any picture — and the pages **always** become an ordered sequence named after the file, like a comic archive and for the same reason: a PDF is a thing read in order. Pages are stored **losslessly** (as lossless WebP), so nothing is ever thrown away from a document's only copy. "Archives become groups" applies to PDFs too, putting the pages into a group named after the file.

## Animated GIFs

An animated GIF imports as a **run of pictures, not a film**: every frame is composited (the GIF's own disposal rules applied, so a frame is what a viewer would show at that moment), stored **losslessly**, and ingested as an ordinary image item — with the same deduplication, hashing and thumbnails any picture gets — and the frames **always** become a sequence named after the file, in play order. "Archives become groups" applies to it too, putting the frames into a group named after the file.

Frames that are identical dedup onto **one item held at several positions**, so a GIF that holds a drawing on screen for a second costs one picture rather than a dozen copies of it.

This is why a GIF is never a video item: no browser plays a GIF in a `<video>` element, so as a film it was an item whose preview overlay, [annotator](annotation-editor.md) and [video editor](video-editor.md) all showed nothing. As frames it is an ordinary book of pictures, taggable, searchable and trainable like any other. A **single-frame** GIF is just a picture and keeps its own bytes untouched.

## Other details

- A group is only created for a folder or archive if at least one importable file actually ends up in it — empty folders never spawn a group.
- On the server, near-duplicate matching is a probe of indexed hash columns in the database itself — for stored files and for video frames alike — so there is nothing to prime before the first file, nothing held in memory that could go stale when the library changes out-of-band, and an import into a million-item library starts as fast as one into an empty one. Reorientation candidates come out of the same probe, confirmed against a bounded cache of decoded thumbnails.

## Bulk import from the command line

For very large batches, import directly on the server with the command-line tool or the Python package instead of the browser — see [CLI](cli.md) and [Python API](python-api.md).

# Library

This page covers browsing and managing your library: the group tree on the left, the item grid in the center, selection, previews, and the Hidden and Trash areas.

## The group tree

The left sidebar shows a tree of all groups in the library, ordered alphabetically. **Selecting a group shows everything in it and in the groups under it**, and a search for `GROUP:` that group ([Search](search.md#group)) finds exactly the same items; `GROUPONLY:` is the group itself without its children. Once there is a group, a **filter box** sits under the fixed entries: it keeps the matching groups and their ancestors, opens the branches they are in for as long as the filter lasts, and leaves the selection alone; Escape or its ✕ clears it.

A group is either an ordinary one — things are put in it — or a **smart group**, whose members are whatever a search finds: it is made from the add-group menu (**Smart group**, or **Smart group from this search** while the view is narrowed, which seeds the rule from the search and the sidebar filters), wears a small filter mark after its name, refreshes itself after every change to the library, and takes no drops and no manual membership — a rule is what it is. Every add-group entry opens the group dialog first; nothing is created until its Create button.

### Organizing groups

- **Nest** a group by dragging it onto another group. Each group has at most one parent, so nesting moves it there. **A drag is always a move** — there is no copy target hidden inside a hovered row and no modifier that turns one into the other. Duplicating is the context menu's **Duplicate**, which works the same everywhere. A move raises an **Undo** bar under the tree, whose one button then flips between Undo and Redo — a group dropped on the wrong row is put back where it was without going to [History](history.md).
- **A level cannot hold two groups of one name.** A group arriving at a level that already has its name — dragged, created, duplicated or renamed — takes a number ("Trips 2") rather than being refused, so the drop always lands. Two different branches may still each hold a "2024"; that is what a [group path](search.md#group) in a search is for.
- **Move to top level** by dropping a group onto **All Items** — or onto the **Move to the top level** row that appears under the tree while a nested group is being dragged, since All Items may be scrolled out of reach.
- Drop **items from the grid** onto a group to add that group to them. The drop target highlights while you drag over it; cancelling the drag (for example with `Escape`) clears the highlight. While items are dragged, a **New group from these items** row appears under the tree: dropping there opens the group dialog with those items as its starting members.

Right-clicking a group opens a context menu (a right-click on a selected group acts on the whole group selection; on an unselected one, on that group alone):

- **Edit group** (one group) — its name, icon (the default is a folder), color, its parent, the tags the group assigns to its items, and — for a smart group only — its search. The dialog opens with the **name focused and selected**: a group being created arrives holding a placeholder meant to be typed over, and an existing one is most often opened to be renamed. The **parent picker searches** — a field at the top of its dropdown matching on a group's whole path, so a parent's name finds everything under it, and each match prints its ancestors (`Photos › Holiday`) in place of the indentation a filtered tree no longer has. The arrows walk the list, Enter picks, and Escape clears the search before it closes the dropdown. It is the same picker the import overlay's **Where it goes** and the whole-view panel's Groups section use, so all three search.
- **Group these…** (several groups) — a new group holding the picked ones, made in the same dialog.
- **Merge into "‹name›"** (several groups) — the others' items and subgroups move into the group you right-clicked, which keeps its own name, icon and tags; the emptied groups are deleted. Three primitives, so it reverts step by step in History.
- **Duplicate group(s)** — an independent copy beside the original (its own identity, the same items, subtree, granted tags and smart rule), named so it can be told from it.
- **Delete group(s)** — the group and everything inside it, after asking; the items stay in the library. Where the group has subgroups a second verb, **Delete group, keep subgroups**, moves them up to its parent instead.
- The **Edit / Detect / Generate** actions — the same sections the right sidebar's [Actions tab](item-properties.md#edit-section-still-images) offers, run over everything in the group's subtree (hidden and trashed items excepted). Only models ready to run are listed; anything still needing setup or a download stays a sidebar affair. Detect faces and Detect text skip items that model has already seen, and the menu reports how many were queued. Remove text carries the sidebar's **read it, then remove** pairing — one entry per reading engine, which reads each page (keeping the result in the Text tab) and removes what it finds in one job.

If a deleted group assigns tags (or any group in a multi-select delete does), a prompt first asks whether to assign those tags directly to all items in the group — so the items keep the tags they were inheriting instead of silently losing them. The fixed entries have menus of their own too: the same actions over everything in that view, and, on the Trash, **Empty Trash**.

### Fixed entries

Above the group tree are fixed entries:

- **All Items** — the full library; selecting it clears any media-kind filter. Indented beneath it as collapsible children (they fold away with All Items' chevron):
  - **Images**, **Videos**, **Sequences** — narrow the grid to that kind (the breadcrumb reads, for example, "All Items › Sequences").
  - **Pending** — items with unapproved AI results, shown when non-empty. It has its own **Tags**, **Captions**, and **Faces** subgroups (each shown only while it has at least one item) that narrow the view to items with pending tags, pending captions, or faces a detector named by itself. An item can be in more than one of them.
  - **Untagged** — items carrying no tags at all.
  - **Ungrouped** — items in no group.
- **Rankings** — shown once the library has one. It is where a [ranking](rankings.md) is met: the row itself lists the rankings as cards, and it expands to a row per ranking (and, past one, to that ranking's pools). Picking one makes the grid that ranking's placed pictures, best first, in sections by its own buckets. Its own menu holds **New ranking…**; each ranking's holds **Rate on this ranking**, **Assign ratings**, **Edit…** and **Delete**.
- **Hidden** — shown when non-empty; see [Hidden](#hidden).
- **Trash** — shown only while it holds items or while the Trash view itself is open; see [Trash](#trash).

Trash, Hidden and Rankings are each their own breadcrumb root; Pending reads "All Items › Pending › Tags". Switching from a media-kind entry to any group (or Ungrouped/Trash) clears the media-kind filter.

The Library header holds the add-group button and the import button (an upload icon) that opens the [import overlay](import.md).

### Statistics footer

At the bottom of the sidebar, a footer shows the item count on one line. Clicking it expands a statistics panel with a fuller breakdown — counts of images, videos, sequences, groups, and tags, the total source-file count and stored size, the **free space** on the volume the library lives on, and the absolute path to the library's data directory.

The free-space figure is colored once it runs short — amber for low, red for critical — and while it is in either state, a warning icon with the remaining space stays on the collapsed summary line, so a filling disk is visible without opening the panel. The judgement is made in gigabytes, with the volume percentage only adding urgency while the absolute figure is already small, so a large disk with plenty left never nags.

## The item grid

The content area shows a grid of items for the current selection in the tree. Each card has a large preview and, below it, the item's name (names need not be unique), image size in pixels, and resolution in megapixels. Thumbnails of images with transparency are shown over a checkerboard pattern that follows the light/dark theme.

The grid scrolls infinitely — more items load as you scroll — and only the cards near the viewport stay mounted, so memory stays bounded even for very large libraries.

### Badges

| Badge | Where | Meaning |
|---|---|---|
| Document icon with a count | Top-right | The item has more than one source file (active + alternates). |
| Duration | Bottom-right | A video's length. |
| Folder icon with a count | Bottom-right | A sequence's member count; the sequence thumbnail is a 2×2 mosaic of its first four members, and its member count (rather than dimensions) is shown below. |
| `3 / 24` | Bottom-right | The item's position and length in its sequence — its first (main) sequence normally, or the currently open one while a sequence is being viewed. |
| Quick Assign badge | On the preview | The item already carries the full **selected** Quick Assign set (whenever one is selected — clicking the badge removes the set). |
| Tag-match indicator | On the card | When tags are selected in the right sidebar's Tags list, every item carrying all of them — directly or inherited from a group — is marked. |

### Breadcrumbs and the view download

Above the grid, a breadcrumbs bar shows the path of the selected group (or "N groups selected"), "Sequences" when browsing sequence cards, or "Sequences › ‹name›" when a sequence is open. At its right end sits the item count and, whenever the view holds at least one item, a **download icon**.

The download exports **the whole current view** — every item the filters match, not just the loaded pages — as ZIP archives built entirely in the browser. Each item contributes one entry, `<uid>.jpg` (or the active file's actual format), named after its uid — a stable, library-independent identity.

**The media and nothing else.** The archives carry no metadata: no tags, no groups, no captions, no links. There is no built-in metadata export, and there is deliberately not going to be one — whatever shape it took would be somebody's guess at what you needed, frozen. The [Python API](python-api.md) is the answer instead: `open_library()` reads everything the app does, so a dozen lines write exactly the export you want, in exactly the format the thing you are feeding expects.

Above 200 items the download asks first — it fetches every file in the view. The archive is split at about 1 GB (or 60,000 entries) — each part downloads as the next starts, so memory stays near one file at a time — and the button shows live progress and the part number while running, turning into a cancel button.

### Sorting, filters, and grid toggles

Next to the toolbar is a sort control — one menu button naming the field: **Imported** (the default), **Modified** (tags/captions/etc. changed), **Date Taken**, **Name**, **Color**, **Resolution** or **Random**. Picking the already-selected field again flips its direction, which is remembered per field. "Imported" keys off the item's last-imported date, refreshed by every re-import, so a re-imported item floats back to the top. **Random** deals a shuffled order and has no direction; a dice button beside the control deals a new one. In a sequence view the grid is fixed to the sequence's own order, so the sort control is disabled.

**Date taken** is when the picture was taken: what somebody typed for the item, otherwise the file's own EXIF capture date. It deliberately does *not* fall back to the span of the events the picture carries, the way a `TAKEN:` search does — a span is a range rather than a point, and sorting by it would drop a whole event's undated pictures onto one instant. **Colour** orders by the overall colour of each picture: greys first from dark to light, then a hue wheel through red, orange, brown, yellow, green, teal, blue, purple and pink. Under both, items with no answer at all — nothing dating them, or a video, which carries no colour — sort **last in both directions**, because "nobody knows" is not a point on the scale.

The item's own **coordinates** live in the sidebar's Places tab, above the places it carries, and follow the same three-state rule the capture date does: what somebody typed wins, the file's own GPS answers when nobody has, and "it has no coordinates" is an answer of its own — which is how a wrong fix off a borrowed camera is removed rather than merely replaced. They are drawn on a small world map (click it for a larger one) whose outline ships with the app — the marker is plotted from the numbers, with no map service involved.

### Grouping the grid into sections

Beside the sort is a **Group by** dropdown, whose choices follow the sort: a date sort groups by **Day**, **Month** or **Year**, Name by **First letter**, Resolution by **Megapixels**, Colour by **Colour** band, and a [ranking](rankings.md)'s view by **Rating** — its sections are the standings' own buckets ("Score 9", "Score 8", …), which is the one view that arrives grouped. (This is not decoration — a group is always a coarsening of the axis the grid is already sorted on, which is what makes each section a contiguous stretch of the order.) Sections get a header with the group's name and how many items are in it, and a colour section carries its swatch. Once you scroll past a header, a small pill pins the current section's name to the top-left of the grid so you always know where you are; it steps aside whenever a real header is on screen.

Beside the dropdown, a **Jump to** button opens the section index. For date groupings it stacks year › month however fine the sections themselves are — grouping a decade by day is thousands of sections, and a flat list of those is exactly what the index is for — while first letters, megapixel bands and colours list flat with their counts. Picking one scrolls the grid to that section and flashes its header.

Changing the grouping returns the grid to the top. Everything else behaves as it always did: the marquee, the arrow keys, Cmd/Ctrl+A and the selection all work across section boundaries as though the sections were not there.

At the right end of the same row:

- A **media-kind control** — a multi-select dropdown of images / videos / sequences. With none or all three checked, the grid shows all kinds and the button reads "All media"; otherwise it lists the checked kinds.
- Below the kinds, the same menu holds two grid toggles:
  - **Fold sequences** — on by default: a sequence's members give way to the sequence itself wherever both would be in the view, so a chapter shows as one card instead of as its own card and all of its pages. The members stay wherever the sequence would not be there to stand for them: a group holding the pages but not the chapter lists the pages, and so does the grid with sequences unticked in the media kinds above. Inside a sequence's own view it does nothing.
  - **Show hidden** — overlays hidden items into the current view, each marked with a crossed-out eye beside its name; they remain excluded from every category count.
- The **grid-size control** (S/M/L) sits at the far right.

The [query builder](search.md) fills the full width of the content area on its own row above these controls.

### Selecting items

- **Click** — select a single item.
- **Cmd/Ctrl+Click** — toggle one item in or out of the selection (on macOS a Ctrl+click does this too rather than opening the menu).
- **Shift+Click** — extend the selection to that item, by position in the view — the range is right even when the other end has scrolled far out of the loaded pages.
- **Click and drag** — box selection; with Shift, Cmd or Ctrl held it adds to the selection instead of replacing it.
- **Arrow keys** move the cursor through the grid (across section boundaries as though they were not there); with Shift they extend the selection.
- **Cmd/Ctrl+A** — select every loaded grid item (except while typing in a text field).
- **Escape** clears the selection.
- **Delete / Backspace** — only while exactly one ordinary group is picked in the sidebar, where it means *not in here*: it asks, then takes the selected items out of that group. Nowhere else does the key do anything — a smart group's membership is a rule, and outside a group's view there is nothing it could mean The [context menu](#right-click-context-menu) carries the same verb on the same views, named after the group.

### The quick-actions menu

The **lightning bolt** beside the media-kind control is the keyboard made findable: one menu listing what the grid's shortcuts do, each row naming its key, and each row that cannot run right now saying why instead of going missing. Rules separate it into runs:

- **Preview** (`Space`) — the [Quick Look](#quicklook-preview) over the selection, where its key can be read off.
- **Quick tag…** (`T`), **Quick caption…** (`C`) and **Quick assign…** (`Q`) — the three keyboard overlays. T means the whole view when nothing is selected; C and Q want a selection.
- **Remove watermark** (`W`) — the first ready watermark remover over the selected images, run immediately — and **Last used** (`L`), the model action you ran last from a context menu, over the selection again, its row named after what it would run. These two touch pixels or run a model, which is why they stand apart.
- **Rate items…** and **Assign ratings…** — the rating axis, and what is spent on it. With no [ranking](rankings.md) yet, *Rate items…* makes one rather than refusing, and starts on it.
- **Tag items one by one…** and **Tag items in a grid…** — the two ways of going through pictures for a tag.

The three full-window sessions have no shortcut of their own; this menu is where they open. See [Rankings and batch sessions](rankings.md).

### Quick tag from the keyboard (T)

Press **T** (not while typing) to open a Spotlight-style **quick tag** field over a dimmed library. A whole edit is typed as one line — `cat -dog !bird` adds `cat` (a `+cat` says the same), removes `dog`, and assigns `bird` negatively — with per-word autocomplete; **Enter** applies the lot and closes, **Escape** throws it away. A preview above the field shows which pictures it is about. **With nothing selected it means the whole current view** — every item the filters match, loaded or not, which can be the entire library — so "tag everything I am looking at" is the same gesture.

### QuickLook preview

Press **Space** (with a selection present in the current view and not typing) to open a large QuickLook-style preview, à la macOS Finder: a full-resolution image — or, for a video, the video itself, which autoplays with playback controls — centered over a dimmed backdrop, with the item name below it. A mute icon follows the name when the item is a video with no audio track; for a multi-item selection, the position and ←/→ (or ↑/↓) arrows step through the selection — and through a sequence's pages first, when the entry is a sequence — then on through the grid. Press Space again, `Escape`, or click the backdrop to close. A picture **zooms** with the wheel and the +/− cluster (100% is one picture pixel per screen pixel) and drags to pan; a video keeps the pointer for its own transport.

A toggle in the top-right (or **Tab**) opens a **side panel** listing the item's tags (organized by tag group, including the pending group) and its captions; hovering a tag's bounding-box indicator draws that tag's boxes over the big preview. The panel opens **the way you last left it** — it is a mode, not a step — and it answers a machine's claims where it finds them: a pending tag can be approved or dismissed on the row, a guessed person accepted or rejected, and every tag carries the **?** that opens what a [tag set](tag-sets.md) says about it. A fourth header button **shows the item in the library**, narrowing the grid to it — the way there from a preview opened over something that is not the grid; over one of the [batch sessions](rankings.md) it opens a **new window** at that address instead, since the library underneath is covered and closing the session for one picture would throw its work away.

### Double-click

Double-clicking an item does what the [Settings → General](settings.md) double-click preferences say, configurable per media kind. By default both an image and a video open a Quick Look preview; an image can instead open the [annotation editor](annotation-editor.md), the [image editor](image-editor.md), or nothing, and a video the [annotation editor](annotation-editor.md), the [video editor](video-editor.md), or nothing. Double-clicking a **sequence** always opens it like a folder, regardless of the preferences. The **Edit** button in the right sidebar always opens the image editor for an image (or the video editor for a video).

Annotating and editing happen in **one item window** — an overlay over the library, with a tab per item and a mode switch in its header between **Annotate** and **Edit**, remembered per tab. Opening items replaces the window's tabs; closing it (its ✕, or `Escape`) returns you exactly where you were.

### Right-click context menu

Right-clicking a grid item opens a context menu:

- **Edit image / Edit video** — opens the editor for the clicked item (disabled for sequences). With multiple items targeted it reads **Edit images (N)** and opens every image of the selection as tabs of one editor window, the clicked one active.
- **Annotate** — opens the [annotator](annotation-editor.md); with multiple items targeted it reads **Annotate (N)** and opens them as tabs (disabled for sequences).
- **Preview** — Quick Look of the targets.
- **Pin** — the clicked picture big over the **grid pane** alone, the sidebars untouched; its ✕ or `Escape` puts it away. It is the same look the sidebar's caption editor puts up while a caption is being written, not the full-window preview.
- **Last used** — the model action you ran last, over the targets again (the same row the grid's **L** key is). It is offered only while there is one to repeat and the targets are a kind it applies to.
- **Find similar colors** — for a single image, writes a `COLORLIKE:` query into the [search bar](search.md), narrowing whatever you are looking at; being an ordinary condition, more can then be edited onto it.
- **Rate on ‹ranking›** — one row per [ranking](rankings.md), starting a rating session on that axis over the view, with the targets first.
- **Actions** — the right sidebar's [Edit / Detect / Generate](item-properties.md#edit-section-still-images) sections in menu form, in the same grouping and order; hovering an action opens its models beside it, and picking one queues the run over the targets. Only models ready to run are listed. Remove text carries the sidebar's **read it, then remove** pairing — one entry per reading engine.
- **Copy labels and links** — one row that copies everything the targets carry: tags (with their per-item tag groups, by name; pending machine tags are skipped), subjects, places, events, groups, captions, instructions, and links. **Copy id(s)** copies the items' uids.
- **Paste all (N)**, plus a row per kind (**Paste tags**, **Paste subjects**, …) — each appears only while something of that kind is in the clipboard, with a **Clear the clipboard** row after them; the clipboard lives for the session. Pasting tags recreates the tag-group structure: existing tag groups are matched by name, missing ones are created.
- **Remove from “‹group›”** — only while exactly one ordinary group is picked in the sidebar, where it is the `Delete` key's own verb made findable: it asks, then takes the targets out of that group. They stay in the library and in every other group. A special scope (All Items, Ungrouped, the Trash) names no group and offers nothing, and a smart group's membership is a rule the row could not change.
- **Hide/Show** and **Move to trash** (in the Trash view: a permanent **Delete**, which asks first).

When the clicked item is part of the current selection, the actions target all selected items (the menu shows the count); when it is not, the clicked item alone is the target and the selection is left untouched.

## Sequences

Each sequence is a **first-class item**: it appears in All Items and groups alongside images and videos, and can be searched, tagged, and grouped like any item.

- **Single-click** selects it — its member list, tags, and groups appear in the right sidebar, along with **Open** and **Remove** buttons.
- **Double-click** opens it: the grid shows the sequence's members in order and the breadcrumb reads "All Items › Sequences › ‹name›" (clicking "Sequences" returns to the sequence list).
- **Remove** deletes the sequence but keeps the images it contained.
- Sequences can't be merged (they own no files).

## Empty grid

When the grid has nothing to show, it offers the way out: with a query set it reads "No items match this query." and offers **Clear the query**; with no query it reads "Nothing here yet." and offers **Import files**, which opens the import overlay. The Trash and the sequences list keep their own wording and offer neither.

## Hidden

Items can be hidden via a checkbox in the right sidebar (for the current selection). A hidden item stays in the library but is excluded from the grid and from every category count — yet it remains reachable through relationships (a link to a hidden item still resolves and shows it in the right sidebar). As soon as at least one item is hidden, a root-level **Hidden** category appears in the left sidebar (just above the Trash) with a count; selecting it lists all hidden items so they can be inspected or un-hidden. Hiding is non-destructive and is recorded in — and revertible from — the [History](history.md).

## Trash

Deleting items moves them to the **Trash** rather than erasing them; they are hidden from all normal listings until restored. Selecting the Trash in the left sidebar shows its items. In the Trash:

- Items cannot be edited — no renaming, file picking, or changes to tags, groups, or captions. The properties are read-only, and the Groups section shows the groups the item will be restored to.
- Selected items can be **restored** (back to those groups, skipping any that no longer exist) or **permanently deleted**.
- In place of the Quick Assign section, the Trash shows an **Empty Trash** button that permanently deletes every trashed item.

# Getting Started

This page introduces the core concepts of Media Compost and takes you on a quick tour of the app.

## What Media Compost is

Media Compost organizes and annotates images and videos with tags and captions for AI training. It deduplicates images automatically, can extract images from video frames, and lets you connect items into ordered sequences and directional relationships. Once your library is organized, you can search it with the [query builder](search.md), edit items in the [image editor](image-editor.md), and use the results for [training](training.md).

If you have not installed the app yet, start with [Installation](installation.md).

## Items

Everything in the library is an **item**. There are three kinds:

- **Image** — a single picture. An item can hold several source files (for example the same image at different resolutions); one of them is the active file.
- **Video** — a single video file. Frames captured from a video become regular image items of their own, extracted at creation and linked to the film at their moment — deleting the video later never affects them.
- **Sequence** — an ordered list of items, such as a comic's pages, a PDF's pages or an animated GIF's frames. Sequences are first-class items: they can be tagged, grouped, and searched like any other item.

Items can also be connected by directional **relationships** — for example an image and its edit, or a video and a clip cut from it.

## Library and groups

The library is an unstructured collection of files — there are no folders. Instead, you assign **groups** to items:

- An item can belong to any number of groups.
- Groups can contain other groups, forming a tree.
- Tags can be assigned to items and to groups. A tag assigned to a group is inherited by everything inside it — items and subgroups alike.
- A **negative tag assignment** on a child removes a tag it would otherwise inherit from a group.

See [Library](library.md) for browsing and managing groups and items, and [Tags](tags.md) for the tagging system.

## The three-pane layout

The main window has three areas:

- **Left sidebar** — the group tree. Select one or more groups to narrow the view; items in subgroups are included.
- **Content area (center)** — a grid of the items in the current selection, or the whole library when nothing is selected.
- **Right sidebar** — properties of the items selected in the grid: tags, captions, groups, files, and more. See [Item Properties](item-properties.md).

## Theme

The top bar holds a theme switcher in its top-right corner: a button with a menu to choose between light, dark, and system appearance (system follows your operating system's setting live). Dark is the default until you make a choice, and your choice is remembered across sessions.

## How the library is stored on disk

Every item owns its own folder under the library's data directory, at `items/<uid[:2]>/<uid>/` (sharded by the first two characters of its stable uid), holding:

- `files/<number>.<ext>` — the item's source files, named by their stable per-item file number (#1, #2, …; numbers are assigned when a file is stored and never reused within the item).
- `artifacts/<file-number>-<kind>[-<model>].<ext>` — generated control images (depth, pose, canny, line art), named after the source file they were derived from.

The **database (`media.db`) is the one record** — tags, groups, captions, faces, everything. Two libraries fold together with the CLI's `merge-library`, which reads the other library's own database and copies its file bytes across; `prune-storage` makes the disk agree with the database again after anything goes sideways.

Settings and saved searches live only in the database. Thumbnails (`thumbs/`) are a regenerable cache outside the item folders.

## Every view has a URL

Where you are in the app is reflected in the address bar, so reloading returns you to the same place:

- Every tab is a path of its own: `/library`, `/tags`, `/history`, `/train`, `/evaluate`, `/models`. The bare root redirects to `/library`, and the Tags tab's other two lists are a second path segment (`/tags/links` for the meta tags, `/tags/tagsets` for a tag set, which adds `?set=` for the set that is open), as is its Faces page (`/tags/faces`). The three retired sub-tab addresses (`/tags/subjects`, `/tags/places`, `/tags/events`) still land on the tag list narrowed to that kind.
- The item window (annotating or editing an item) is an overlay over whatever view is behind it, so it rides in query parameters — `?item=<ids>&mode=annotate|edit`, plus `?tab=` for its active tab — and closing it leaves exactly the address you opened it from. Its older addresses (`/item/…`, `/editor/…`, `/annotator/…`) still open it.
- What is open on top of a tab is a query parameter — the settings overlay and its page (`/train?settings=actions`), the group being edited, or the selected training job (`/train?job=…`).
- On the library, the selected category (`?cat=…` — a group, Ungrouped, Untagged, Hidden, Trash, Pending with its sub-kind (`pending-tags`, `pending-captions`, `pending-faces`), a sequence, or a [ranking](rankings.md) and its pool), the media-kind filter (`?kinds=image,video`), and the search (`?q=…`) are in the URL as well.

Every one of these is a real URL that can be bookmarked or sent to someone. Because each move is a history entry, the browser's **Back** button works the way it looks like it should: it closes an overlay or returns to the tab you came from, without leaving the app. Typing in the search box replaces the current history entry rather than adding one per keystroke. The import overlay is the one exception that is not in the URL — its content is a queue of dropped files that a reload could not bring back.

## Where to go next

- [Import](import.md) — get files into the library.
- [Library](library.md) — browse, select, and manage items and groups.
- [Search](search.md) — find items with the query builder.
- [Settings](settings.md) — language, appearance, and behavior preferences.

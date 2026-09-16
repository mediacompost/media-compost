# History

The History tab keeps a chronological log of everything that changed your library, and lets you revert most of those changes.

Open it from the top header, beside Library, Tags and Faces.

## What gets logged

The log records library modifications, newest first, including:

- Tagging and untagging items, however the tag was applied
- Adding, editing, and removing captions
- Non-destructive rotations
- Adding and removing group memberships, creating and deleting groups
- Trashing, restoring, and deleting items
- Every face action — naming, drawing, moving, dismissing, and deleting faces, and merging or splitting clusters
- Edits to [subjects](subjects-and-faces.md), [places](places.md), and [events](events.md), including dismissed suggestions and the capture-date override
- Detected-text corrections
- Imports

Each entry records when it happened, its source (`web` for the app, `cli` for the [command line](cli.md) and the [Python API](python-api.md) — both local processes against the library — and `ai` for a background AI job), and a human-readable description. Clicking a row picks it for reverting; an entry about an item carries a hover button that jumps to that item in the [Library](library.md).

Entries are grouped by day. Dates and times follow your Language & Region preferences from [Settings](settings.md).

## Reading the log

Similar actions performed in quick succession are collapsed into a single summary row ("Tagged 5 items"). Expand the row to see the individual events, so a burst of edits stays one line without hiding anything.

A caption edit entry has a diff button: expanding it shows the full new text with the changes highlighted — removed words struck through in red, added words in green.

## Reverting entries

Select one or more entries (individually, or a whole collapsed group at once) and revert them. Reverting works wherever the action is invertible, including:

- Tag assignments and removals
- Caption add, remove, and edit
- Approving a pending tag or caption
- Creating a tag (only while it isn't assigned to any item yet) or an alias, renaming a tag, changing or removing an alias
- Adding or removing a tag implication; editing a tag's comment or description; setting a meta-tag assignment's count; a box drawn, moved or deleted in the annotator; the sign of one tag instance
- Tagging or untagging a library group
- The whole meta-tag namespace — create, rename, comment, describe, delete (a deleted meta tag comes back on every link, caption, tag group, and tag it was on)
- Deleting a tag
- Group membership changes; creating, editing, moving, duplicating and deleting a group (a deletion comes back with its whole subtree)
- Merging or splitting items — reverting a merge recreates the source item with its files, tags, groups, links, and original import dates (tags the merge dropped for disagreeing signs, and per-item tag groupings, are not restored); reverting a split folds the files back and removes the split-off item, as long as that item still holds only the files the split moved. The revert puts back what the split moved, not just the rows: the files return with their original numbers, their stored bytes, their generated artifacts and their edit lineage
- Sequences — creating, renaming, reordering, taking pages out of and removing one, and an item's choice of main sequence
- Hiding and showing items, rotations, pinning or muting a metadata value
- Rankings — creating and editing one, every judgement, and taking an item out of one
- Switching an item's active source file; adding, renaming, or removing a source name
- Adding or removing a link between items (reverting a removal restores the link with its link tags)
- Every face action — naming and unnaming, drawing, moving, dismissing, and deleting a face, editing or resetting a detected face's box, merging and splitting clusters; a subject's appearances (adding, dating, reordering, outlining). A revert restores the exact shape of what it undoes: a rejected guess comes back as a guess, not as your answer
- Creating, renaming, editing and deleting subjects, places, and events (a subject's date, an event's span), commenting on their identity tags — and dismissing a suggested place or event
- Setting, changing, or clearing the capture date — and the item's own coordinates
- Detected-text corrections
- Trashing and restoring items (the Trash offers the same restore)
- An import — reverting one moves the items it created into the Trash
- An image-editor save, and a link flipped the other way round

A reverted entry is shown struck through and cannot be reverted again.

A few things are recorded but deliberately not revertible: permanent deletions (emptying the Trash, deleting a source file, deleting a ranking with all its judgements), a detection *run* — faces, text, or panels (its results are evidence rather than an edit — dismissing a wrong one is the action that exists for that), a generated artifact, a saved video render (the way back from one is the item's own Source list), and clearing the log itself. A group deletion big enough that its snapshot would not fit — past twenty thousand direct members — is also left final.

## Redo: reverting a revert

The revert itself is a log entry, and reverting *it* performs the original action once more — that is how redo works. The chain can be walked as far as you like: each step flips which way the action stands, with the superseded revert shown struck through.

Redo is offered only where replaying the original action has been written down as safe — tagging, captions, group memberships, the tag catalog's edits, approvals, hiding, rotations, the coordinates and a handful more. Where it has not (creating a subject, a place or an event, splitting or merging items, an import, a face action, a judgement, the capture date), the revert is final and shows no button; some of those would hand out new ids on a replay, and the rest simply have no replay written yet.

## Undo without opening the tab

You rarely need to come here for a slip you just made. A removal made in the sidebar — a tag, a person, a place, an event, a caption, a text region — raises an **Undo** bar right where you are, in the Library and in the annotator alike; a group dragged somewhere in the tree offers the move back the same way; and a deletion in the [Tags tab](tags.md) raises a toast whose one button flips between Undo and Redo for as long as it stays open. Every one of them reverts exactly the log entries this tab shows.

## Filtering to specific items

With at least one item selected in the Library, a history button in the right sidebar's header (*Show this selection's changes in the History tab*) switches to the History tab showing only the changes that touched the selection — among the entries the tab has loaded, which is the newest few hundred unless more pages were loaded first. A chip reading *Filtered to selected items* indicates the filter is active; clicking it clears the filter and returns to the full log.

## Who made a change

When the library is shared by several people behind an authenticating proxy (see [Multi-user access](installation.md#multi-user-access)), each entry shows a small username chip naming who made the change. Runs by different users are never grouped together. On a single-user (anonymous) install, no chip appears.

## Clearing the log

The log is append-only and unbounded by design — the entries are what reverting reads. **Clear history** empties it, after asking: the library itself is untouched, but everything already done becomes permanent, since a revert needs the entry it would undo. One entry is left behind saying that the log was cleared and how many entries went.

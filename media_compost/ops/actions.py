"""Every History action string, once.

``history._REVERT`` and ``history._REDO`` are dictionaries keyed by these
literals, and ``_REDO`` even pairs handlers across two of them
(``"add_tag" -> _revert_remove_tag``). So a rename here is not a refactor: it
breaks every event **already written into every existing library**, and it
breaks it silently — ``is_revertible`` simply starts returning False, the
History tab quietly stops offering the Undo button, and nothing raises.

Hence one module of constants, a test that pins the whole set
(``tests/test_ops_actions.py``), and one rule: **adding an action means adding
a constant here and a case in ``_REVERT`` or in ``NOT_REVERTIBLE`` below.**

Values are the strings as they already exist on disk. Do not change them.

**THE FOUR POOL ACTIONS WERE RENAMED ONCE, AND THAT IS NOT A PRECEDENT**
(owner 2026-09, rung v35). ``create_ranking_league`` and the three beside it
became ``…_pool``: a league is a tier metaphor, and these are parallel
populations sharing one scale, which is the single thing about them somebody
has to understand. The rule above stood, so the rung DELETED the events the
rename invalidates — narrowly, those four actions plus any ranking event whose
payload carries a ``league_id`` — rather than leaving rows that promise an Undo
they cannot honour.

What made that affordable is that there were no real libraries yet, which is a
fact about one month and not about this rule. The usual answer is the one the
four session names, ``Occasion`` and ``Location.address`` all take: move the
word a person reads and leave the string on disk alone. See
``docs/compatibility.md``.
"""

from __future__ import annotations

# ---- items ------------------------------------------------------------------
ADD_TO_GROUP = "add_to_group"
DELETE_ITEM = "delete_item"
MERGE_ITEM = "merge_item"
REMOVE_FROM_GROUP = "remove_from_group"
RESTORE_ITEM = "restore_item"
ROTATE_ITEM = "rotate_item"
SET_ACTIVE_FILE = "set_active_file"
SET_HIDDEN = "set_hidden"
SET_TAKEN = "set_taken"
SET_COORDS = "set_coords"
# Item-level metadata. PIN promotes one file's answer onto the item, MUTE takes
# one of the active file's answers away — the two directions, so both need a
# verb of their own and its own undo (see `ops/metadata.py`).
PIN_METADATA = "pin_metadata"
UNPIN_METADATA = "unpin_metadata"
MUTE_METADATA = "mute_metadata"
UNMUTE_METADATA = "unmute_metadata"
SPLIT_ITEM = "split_item"
TRASH_ITEM = "trash_item"

# ---- files ------------------------------------------------------------------
ADD_ARTIFACT = "add_artifact"
ADD_SOURCE = "add_source"
ADD_SOURCES_BULK = "add_sources_bulk"
ADD_TAGS_BULK = "add_tags_bulk"
DELETE_FILE = "delete_file"
REMOVE_SOURCE = "remove_source"
RENAME_SOURCE = "rename_source"

# ---- the tag catalog --------------------------------------------------------
ADD_TAG_IMPLICATION = "add_tag_implication"
COMMENT_TAG = "comment_tag"
#: A tag kept out of the AUTOCOMPLETE, or put back. The tag itself is
#: untouched — it assigns, searches and counts as it always did.
SET_TAG_HIDDEN = "set_tag_hidden"
#: The same for a whole NAMESPACE, which is a setting rather than rows
#: (a namespace has no table); the event carries the WHOLE list either
#: way, since that is what a revert has to put back.
SET_HIDDEN_NAMESPACES = "set_hidden_namespaces"
#: THE LONG FORM on a tag. Written until 2026-09, when a tag stopped having a
#: description of its own (rung v17 — a description was a TAG SET's), and
#: written again from 2026-09: the LIBRARY IS A SET now, the first pill in
#: the Tags tab, and it exports as a template that would otherwise carry no
#: prose (rung v27 put the column back). The STRING is the same one the old
#: events used, and `_revert_describe_tag` reads the same payload, so an
#: event written before the removal reverts again rather than staying dead.
DESCRIBE_TAG = "describe_tag"
#: WHERE THE LIBRARY FILES A TAG — one or many at once, since the gesture is
#: a drag of a selection onto a category. The event carries each tag's
#: PREVIOUS category, because they need not have shared one.
SET_TAG_CATEGORY = "set_tag_category"
# NOTE: "offset_tag" was written here until the tag-level count offset became
# a count per META-TAG assignment (`set_meta_count`). The string is gone from
# every table, so an old library's offset_tag events simply stop offering
# Undo — which is honest: the column their revert wrote is gone.
SET_META_COUNT = "set_meta_count"
CREATE_TAG = "create_tag"
DELETE_TAG = "delete_tag"
REMOVE_TAG_IMPLICATION = "remove_tag_implication"
RENAME_TAG = "rename_tag"
SET_ALIAS = "set_alias"

# ---- tag assignment ---------------------------------------------------------
ADD_GROUP_TAG = "add_group_tag"
ADD_TAG = "add_tag"
ADD_TAG_GROUP_SUBJECT = "add_tag_group_subject"
ADD_TAG_GROUP_TAG = "add_tag_group_tag"
APPROVE_TAG = "approve_tag"
CREATE_TAG_GROUP = "create_tag_group"
DELETE_TAG_GROUP = "delete_tag_group"
MOVE_TAG_GROUP = "move_tag_group"
RENAME_TAG_GROUP = "rename_tag_group"
REMOVE_GROUP_TAG = "remove_group_tag"
REMOVE_TAG = "remove_tag"
REMOVE_TAG_GROUP_SUBJECT = "remove_tag_group_subject"
REMOVE_TAG_GROUP_TAG = "remove_tag_group_tag"

# ---- library groups ---------------------------------------------------------
CREATE_GROUP = "create_group"
DELETE_GROUP = "delete_group"
# What the group SAYS (its name, icon, colour, smart rule) and where it SITS
# are two different edits, so they are two verbs: an undo of a rename must not
# also drag the group back out of the folder it was moved into afterwards.
EDIT_GROUP = "edit_group"
MOVE_GROUP = "move_group"
DUPLICATE_GROUP = "duplicate_group"

# ---- sequences --------------------------------------------------------------
CREATE_SEQUENCE = "create_sequence"
DELETE_SEQUENCE = "delete_sequence"
RENAME_SEQUENCE = "rename_sequence"
# The whole order, as one action with one revert — `set_caption_refs`'
# reasoning: add, remove and reorder are one edit to one list.
REORDER_SEQUENCE = "reorder_sequence"
REMOVE_SEQUENCE_MEMBERS = "remove_sequence_members"
SET_MAIN_SEQUENCE = "set_main_sequence"

# ---- tag boxes --------------------------------------------------------------
# A box drawn, moved or removed on its own. A box also travels inside a
# placement snapshot (see `_revert_remove_tag`), which is what puts one back
# when the ASSIGNMENT is undone; these three are the annotator's own edits,
# which touch no assignment and so had nothing to undo.
ADD_TAG_BOX = "add_tag_box"
EDIT_TAG_BOX = "edit_tag_box"
DELETE_TAG_BOX = "delete_tag_box"

# ---- captions ---------------------------------------------------------------
ADD_CAPTION = "add_caption"
ADD_CAPTION_TAG = "add_caption_tag"
APPROVE_CAPTION = "approve_caption"
EDIT_CAPTION = "edit_caption"
REMOVE_CAPTION = "remove_caption"
REMOVE_CAPTION_TAG = "remove_caption_tag"
# An instruction's reference images, set as one ordered list — so adding,
# removing and reordering are one action with one revert.
SET_CAPTION_REFS = "set_caption_refs"

# ---- subjects and appearances ----------------------------------------------
ADD_APPEARANCE = "add_appearance"
CONFIRM_APPEARANCE = "confirm_appearance"
CREATE_SUBJECT = "create_subject"
DATE_SUBJECT = "date_subject"
DELETE_SUBJECT = "delete_subject"
EDIT_APPEARANCE = "edit_appearance"
SET_APPEARANCE_BOX = "set_appearance_box"
SET_FACE_OUTLINE = "set_face_outline"
SET_PLACEMENT_SIGN = "set_placement_sign"
NAME_SUBJECT = "name_subject"
REMOVE_APPEARANCE = "remove_appearance"
REORDER_APPEARANCES = "reorder_appearances"
RENAME_SUBJECT = "rename_subject"

# ---- faces ------------------------------------------------------------------
ADD_FACE = "add_face"
CLUSTERS_DIFFER = "clusters_differ"
DELETE_FACE = "delete_face"
DETECT_FACES = "detect_faces"
DISMISS_FACE = "dismiss_face"
MERGE_FACES = "merge_faces"
MOVE_FACE = "move_face"
NAME_FACE = "name_face"
NAME_FACES = "name_faces"
RESET_FACE_BOX = "reset_face_box"
SET_CLUSTER_UNNAMED = "set_cluster_unnamed"
SPLIT_FACES = "split_faces"
UNNAME_FACE = "unname_face"

# ---- text (OCR) -------------------------------------------------------------
ADD_TEXT = "add_text"
DELETE_TEXT = "delete_text"
DETECT_TEXT = "detect_text"
DISMISS_TEXT = "dismiss_text"
EDIT_TEXT = "edit_text"
MOVE_TEXT = "move_text"
REORDER_TEXT = "reorder_text"

# ---- places -----------------------------------------------------------------
CREATE_PLACE = "create_place"
DELETE_PLACE = "delete_place"
DISMISS_FILE_PLACE = "dismiss_file_place"
DISMISS_PLACE = "dismiss_place"
EDIT_PLACE = "edit_place"
NAME_PLACE = "name_place"

# ---- events (the UI's word; the model is `Occasion`) ------------------------
CREATE_EVENT = "create_event"
DELETE_EVENT = "delete_event"
DISMISS_EVENT = "dismiss_event"
EDIT_EVENT = "edit_event"

# ---- rankings ---------------------------------------------------------------
CREATE_RANKING = "create_ranking"
EDIT_RANKING = "edit_ranking"
#: Deleting a ranking takes its judgments and score tags with it. NOT
#: revertible — see `NOT_REVERTIBLE`.
DELETE_RANKING = "delete_ranking"
JUDGE_RANKING = "judge_ranking"
DISMISS_RANKING_ITEM = "dismiss_ranking_item"
UNDISMISS_RANKING_ITEM = "undismiss_ranking_item"
#: Take an item out of a ranking: its judgments deleted (snapshotted in the
#: event, so the revert puts them back) and the standings refit.
REMOVE_RANKING_ITEM = "remove_ranking_item"
#: A ranking's POOLS — the populations it is computed over. Deleting one
#: takes its judgments with it and is NOT revertible, `delete_ranking`'s
#: reason one level down.
CREATE_RANKING_POOL = "create_ranking_pool"
EDIT_RANKING_POOL = "edit_ranking_pool"
# NOTE: "set_ranking_pool_enabled" was written here until rung v31 —
# one pool's score assignments shown or hidden. A ranking materializes
# nothing now and the column is gone, so an old library's events under that
# string simply stop offering Undo, which is honest: the flag their revert
# wrote does not exist. The `offset_tag` precedent, one subsystem along.
DELETE_RANKING_POOL = "delete_ranking_pool"
REORDER_RANKING_POOLS = "reorder_ranking_pools"

# ---- meta tags (the `link_tags` namespace) ----------------------------------
COMMENT_META_TAG = "comment_meta_tag"
DESCRIBE_META_TAG = "describe_meta_tag"
CREATE_META_TAG = "create_meta_tag"
DELETE_META_TAG = "delete_meta_tag"
RENAME_META_TAG = "rename_meta_tag"

# ---- video ------------------------------------------------------------------
#: A saved cutlist render. NOT revertible — see `NOT_REVERTIBLE`.
EDIT_VIDEO = "edit_video"

# ---- relationships ----------------------------------------------------------
ADD_LINK = "add_link"
ADD_LINK_TAG = "add_link_tag"
REMOVE_LINK = "remove_link"
REMOVE_LINK_TAG = "remove_link_tag"
# Reversing a link's direction. Not its own inverse: on an `edit` link the
# flip re-roots the cluster and may drop a now-redundant edge, so the event
# carries what moved and what went.
FLIP_LINK = "flip_link"

# ---- the image editor -------------------------------------------------------
# One save. Its undo depends on what it produced, which the event says: a
# save INTO the item puts the previous active file back, a save that made a
# new item sends that item to the Trash.
EDIT_IMAGE = "edit_image"

# ---- whole runs -------------------------------------------------------------
DETECT_PANELS = "detect_panels"
IMPORT = "import"
REVERT = "revert"

# ---- tag sets ---------------------------------------------------------------
# An imported tag list (`db.TagSet`) is edited through its own ops; every one
# of them logs and every one but the delete reverts. `import_tag_set` is the
# `delete_group` shape: revertible only while its event carries an `undo`
# block (a bulk under `ops/tagsets.UNDO_ENTRIES_MAX`).
CREATE_TAG_SET = "create_tag_set"
EDIT_TAG_SET = "edit_tag_set"
SET_TAG_SET_ENABLED = "set_tag_set_enabled"
#: Thousands of rows cascade with it — see `NOT_REVERTIBLE`.
DELETE_TAG_SET = "delete_tag_set"
DUPLICATE_TAG_SET = "duplicate_tag_set"
IMPORT_TAG_SET = "import_tag_set"
#: A built-in taking the entries this build ships. NOT revertible — see
#: `NOT_REVERTIBLE`.
UPDATE_TAG_SET = "update_tag_set"
CREATE_TAG_SET_CATEGORY = "create_tag_set_category"
EDIT_TAG_SET_CATEGORY = "edit_tag_set_category"
MOVE_TAG_SET_CATEGORY = "move_tag_set_category"
DELETE_TAG_SET_CATEGORY = "delete_tag_set_category"
CREATE_TAG_SET_META = "create_tag_set_meta"
EDIT_TAG_SET_META = "edit_tag_set_meta"
DELETE_TAG_SET_META = "delete_tag_set_meta"
CREATE_TAG_SET_ENTRY = "create_tag_set_entry"
EDIT_TAG_SET_ENTRY = "edit_tag_set_entry"
DELETE_TAG_SET_ENTRY = "delete_tag_set_entry"

# ---- the log itself ---------------------------------------------------------
#: Emptying the modification log. NOT revertible — see `NOT_REVERTIBLE`.
CLEAR_HISTORY = "clear_history"


#: Actions that are deliberately NOT revertible, each for a reason.
#:
#: A detection run's faces are EVIDENCE, not an edit — dismissing a wrong one
#: is the action that exists for that; a `detect_text` run's regions are the
#: same kind of thing (dismissing a wrong region, or correcting its text, are
#: the actions that exist for that). `revert` is handled by its own branch in
#: `revert_event` (reverting a revert replays the original, which is redo).
#: `delete_item` is permanent by definition; `add_artifact`,
#: `detect_panels` and `edit_video` produce files and items a revert cannot
#: un-generate — a rendered video is minutes of encoding, and the way back from
#: one is to make another file active (or delete the one it wrote), both of
#: which the item's own Source list already offers. `clear_history` deleted the
#: entries a revert would have to read, including its own — there is nothing
#: left to put back.
NOT_REVERTIBLE = frozenset({
    ADD_ARTIFACT,
    CLEAR_HISTORY,
    DELETE_FILE,
    DELETE_ITEM,
    # A ranking's judgments cascade with it — thousands of rows, which is not
    # a snapshot one event should carry — so the delete confirms up front and
    # says the score tags go with it, like `delete_group`.
    DELETE_RANKING,
    DELETE_RANKING_POOL,
    # A set's entries cascade with it — a 10,000-row snapshot is not
    # something one event should carry; the UI confirms up front instead.
    DELETE_TAG_SET,
    DETECT_FACES,
    DETECT_PANELS,
    DETECT_TEXT,
    EDIT_VIDEO,
    REVERT,
    # A built-in's entries are replaced with the ones this build ships, and
    # what they replace is the PREVIOUS release's file — which is not on this
    # machine any more, so there is nothing to put back.
    UPDATE_TAG_SET,
})

#: Every action string this build can write. Pinned by
#: `tests/test_ops_actions.py`, which is what makes a rename loud instead of
#: silent.
ALL = frozenset({
    SET_TAG_HIDDEN, SET_HIDDEN_NAMESPACES, DESCRIBE_TAG, SET_TAG_CATEGORY,
    CREATE_TAG_SET, EDIT_TAG_SET, SET_TAG_SET_ENABLED, DELETE_TAG_SET,
    DUPLICATE_TAG_SET, IMPORT_TAG_SET, UPDATE_TAG_SET, CREATE_TAG_SET_CATEGORY,
    EDIT_TAG_SET_CATEGORY, MOVE_TAG_SET_CATEGORY, DELETE_TAG_SET_CATEGORY,
    CREATE_TAG_SET_META, EDIT_TAG_SET_META, DELETE_TAG_SET_META,
    CREATE_TAG_SET_ENTRY,
    EDIT_TAG_SET_ENTRY, DELETE_TAG_SET_ENTRY,
    ADD_APPEARANCE, ADD_ARTIFACT, ADD_CAPTION, ADD_CAPTION_TAG, ADD_FACE,
    ADD_GROUP_TAG, ADD_LINK, ADD_LINK_TAG, ADD_SOURCE,
    ADD_SOURCES_BULK, ADD_TAG, ADD_TAGS_BULK,
    ADD_TAG_GROUP_SUBJECT,
    ADD_TAG_GROUP_TAG, ADD_TAG_IMPLICATION, ADD_TO_GROUP, APPROVE_CAPTION,
    CLEAR_HISTORY,
    APPROVE_TAG, COMMENT_META_TAG, COMMENT_TAG,
    DESCRIBE_META_TAG,
    SET_META_COUNT,
    CONFIRM_APPEARANCE, CREATE_EVENT, CREATE_GROUP, CREATE_META_TAG,
    CREATE_PLACE, CREATE_SUBJECT, CREATE_TAG, CREATE_TAG_GROUP, DATE_SUBJECT,
    CREATE_RANKING, EDIT_RANKING, DELETE_RANKING, JUDGE_RANKING,
    DISMISS_RANKING_ITEM, UNDISMISS_RANKING_ITEM, REMOVE_RANKING_ITEM,
    CREATE_RANKING_POOL, EDIT_RANKING_POOL, DELETE_RANKING_POOL,
    REORDER_RANKING_POOLS,
    ADD_TEXT, DELETE_TEXT, DETECT_TEXT, DISMISS_TEXT, EDIT_TEXT, MOVE_TEXT,
    REORDER_TEXT,
    EDIT_GROUP, MOVE_GROUP, DUPLICATE_GROUP,
    CREATE_SEQUENCE, DELETE_SEQUENCE, RENAME_SEQUENCE, REORDER_SEQUENCE,
    REMOVE_SEQUENCE_MEMBERS, SET_MAIN_SEQUENCE,
    ADD_TAG_BOX, EDIT_TAG_BOX, DELETE_TAG_BOX, FLIP_LINK, EDIT_IMAGE,
    DELETE_EVENT, DELETE_FACE, DELETE_FILE, DELETE_GROUP, DELETE_ITEM,
    DELETE_META_TAG, EDIT_VIDEO,
    DELETE_PLACE, DELETE_TAG_GROUP,
    DELETE_SUBJECT, DELETE_TAG, DETECT_FACES, DETECT_PANELS, DISMISS_EVENT,
    DISMISS_FACE, DISMISS_FILE_PLACE, DISMISS_PLACE, EDIT_APPEARANCE,
    SET_APPEARANCE_BOX, SET_FACE_OUTLINE, SET_PLACEMENT_SIGN,
    EDIT_CAPTION, EDIT_EVENT,
    EDIT_PLACE, IMPORT, MERGE_FACES, MERGE_ITEM, MOVE_FACE,
    MOVE_TAG_GROUP, NAME_FACE, NAME_FACES, NAME_PLACE, NAME_SUBJECT,
    REMOVE_APPEARANCE, REMOVE_CAPTION, REMOVE_CAPTION_TAG, REMOVE_FROM_GROUP,
    REMOVE_GROUP_TAG, REMOVE_LINK, REMOVE_LINK_TAG, REMOVE_SOURCE, REMOVE_TAG,
    REMOVE_TAG_GROUP_SUBJECT, REMOVE_TAG_GROUP_TAG, REMOVE_TAG_IMPLICATION,
    RENAME_META_TAG, RENAME_SOURCE, RENAME_SUBJECT, RENAME_TAG,
    RENAME_TAG_GROUP, RESTORE_ITEM,
    PIN_METADATA, UNPIN_METADATA, MUTE_METADATA, UNMUTE_METADATA,
    REORDER_APPEARANCES, RESET_FACE_BOX,
    REVERT, ROTATE_ITEM, SET_ACTIVE_FILE, SET_ALIAS, SET_CAPTION_REFS,
    SET_COORDS, SET_HIDDEN, SET_TAKEN,
    CLUSTERS_DIFFER, SET_CLUSTER_UNNAMED,
    SPLIT_FACES, SPLIT_ITEM, TRASH_ITEM, UNNAME_FACE,
})

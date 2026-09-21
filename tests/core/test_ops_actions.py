"""The History action strings are pinned, and every one is accounted for.

`history._REVERT` / `_REDO` are dictionaries keyed by these literals, so a
rename breaks every event already written into every existing library —
silently, because `is_revertible` just starts returning False and the History
tab quietly stops offering Undo. Nothing raises.

So this module is the tripwire. It fails loudly on a rename, on an action
emitted with no revert handler and no entry in `NOT_REVERTIBLE`, and on a
revert handler keyed to a string nothing writes.
"""

from __future__ import annotations

import pathlib
import re

from media_compost import history
from media_compost.ops import actions

# The set as it stands today, spelled out rather than derived. Deriving it from
# `actions.ALL` would make this test tautological — the point is that a HUMAN
# has to edit this list, in the same commit, to change what the log can say.
PINNED = frozenset({
    "add_appearance", "add_artifact", "add_caption", "add_caption_tag",
    "add_face", "add_group_tag", "add_link", "add_link_tag", "add_source",
    "add_sources_bulk", "add_tags_bulk",
    "add_tag",
    "add_tag_group_subject", "add_tag_group_tag", "add_tag_implication",
    "add_to_group", "approve_caption", "approve_tag", "comment_meta_tag", "describe_meta_tag",
    "clear_history",
    "clusters_differ",
    "comment_tag", "confirm_appearance", "create_event",
    "create_group", "create_meta_tag", "create_place", "create_subject",
    "create_tag", "create_tag_group", "date_subject", "delete_event",
    "delete_face", "delete_file", "delete_group", "delete_item",
    "delete_meta_tag", "edit_video",
    "delete_place", "delete_subject", "delete_tag", "delete_tag_group",
    "edit_group", "move_group", "duplicate_group",
    "create_sequence", "delete_sequence", "rename_sequence",
    "reorder_sequence", "remove_sequence_members", "set_main_sequence",
    "add_tag_box", "edit_tag_box", "delete_tag_box", "flip_link",
    "edit_image",
    "detect_faces", "detect_panels", "dismiss_event", "dismiss_face",
    "add_text", "delete_text", "detect_text", "dismiss_text", "edit_text",
    "move_text", "reorder_text",
    "dismiss_file_place",
    "create_ranking", "edit_ranking", "delete_ranking", "judge_ranking",
    "set_appearance_box",
    "set_face_outline",
    "set_placement_sign",
    "dismiss_ranking_item", "undismiss_ranking_item", "remove_ranking_item",
    "create_ranking_pool", "edit_ranking_pool", "delete_ranking_pool",
    "reorder_ranking_pools",
    "dismiss_place", "edit_appearance", "edit_caption", "edit_event",
    "edit_place", "import", "merge_faces", "merge_item",
    "move_face", "move_tag_group", "name_face", "name_faces", "name_place",
    # "offset_tag" left with the tag-level count offset: the count lives on
    # a META-TAG assignment now ("set_meta_count"), and an old library's
    # offset_tag events simply stop offering Undo — the column their revert
    # wrote is gone.
    "set_meta_count",
    # Kept out of the AUTOCOMPLETE, one tag at a time or a whole namespace.
    # Neither is a deletion: the tags assign, search, count and are listed
    # exactly as before.
    "set_tag_hidden", "set_hidden_namespaces",
    "describe_tag", "set_tag_category",
    "create_tag_set", "edit_tag_set", "set_tag_set_enabled",
    "delete_tag_set", "duplicate_tag_set", "import_tag_set", "update_tag_set",
    "create_tag_set_category", "edit_tag_set_category", "move_tag_set_category",
    "delete_tag_set_category",
    "create_tag_set_meta", "edit_tag_set_meta", "delete_tag_set_meta",
    "create_tag_set_entry",
    "edit_tag_set_entry", "delete_tag_set_entry",
    "name_subject", "remove_appearance", "remove_caption",
    "remove_caption_tag", "remove_from_group", "remove_group_tag",
    "remove_link", "remove_link_tag", "remove_source", "remove_tag",
    "remove_tag_group_subject", "remove_tag_group_tag",
    "remove_tag_implication", "rename_meta_tag", "rename_source",
    "reorder_appearances", "reset_face_box",
    "rename_subject", "rename_tag", "rename_tag_group", "restore_item",
    "mute_metadata", "unmute_metadata", "pin_metadata", "unpin_metadata",
    "revert", "rotate_item", "set_active_file", "set_alias",
    "set_caption_refs", "set_hidden",
    "set_coords",
    "set_cluster_unnamed",
    "set_taken", "split_faces", "split_item", "trash_item",
    "unname_face",
})

_PKG = pathlib.Path(history.__file__).parent


def _source_roots() -> list[pathlib.Path]:
    """Core always; the app package too, when this install has it.

    `jobs.py` and the import router write history with literals of their own,
    which a core-only sweep cannot see — an action emitted there with no
    revert handler and no `NOT_REVERTIBLE` entry would look exactly like a
    covered one. Guarded import, because core's suite must still run on a
    base-only install.
    """
    roots = [_PKG]
    try:
        import media_compost.ui

        roots.append(pathlib.Path(media_compost.ui.__file__).parent)
    except ImportError:
        pass
    return roots


#: argparse spells its option behaviors through the SAME kwarg name the
#: history log uses for its verbs (`action="store_true"` in the CLI parser vs
#: `action="add_tag"` in a log_event call), so the sweep below has to know
#: which tag set a literal belongs to or the CLI's parser reads as
#: un-revertible history.
_ARGPARSE_ACTIONS = frozenset({
    "store", "store_true", "store_false", "store_const", "append",
    "append_const", "count", "extend", "help", "version", "parsers",
})


def _emitted_literals() -> set[str]:
    """Every `action="…"` literal in the packages (the built SPA and vendored
    code excluded)."""
    found: set[str] = set()
    for root in _source_roots():
        for path in root.rglob("*.py"):
            if "_web_dist" in path.parts or "vendor" in path.parts:
                continue
            found |= set(re.findall(r'action="([a-z_]+)"', path.read_text(encoding="utf-8")))
    return found - _ARGPARSE_ACTIONS


def test_the_action_set_is_pinned():
    assert actions.ALL == PINNED, (
        "the History action strings changed. `history._REVERT`/`_REDO` are "
        "keyed by these literals, so renaming one silently breaks Undo for "
        "every event already in every existing library. If this is a genuinely "
        "NEW action, add it here and to actions.py in the same commit."
    )


def test_every_constant_is_in_ALL():
    for name in dir(actions):
        if name.isupper() and isinstance(getattr(actions, name), str):
            assert getattr(actions, name) in actions.ALL, name


def test_every_revert_handler_names_a_real_action():
    """A handler keyed to a string nothing writes is dead code that reads as
    coverage."""
    assert set(history._REVERT) <= actions.ALL
    assert set(history._REDO) <= actions.ALL


def test_every_emitted_action_is_revertible_or_declared_not_to_be():
    """The gap this closes: an action that reverts nowhere and says so nowhere
    looks identical to one whose handler was forgotten."""
    for action in _emitted_literals():
        assert action in actions.ALL, f"{action} is emitted but not in ALL"
        assert (action in history._REVERT
                or action in actions.NOT_REVERTIBLE), (
            f"{action} is written to the log but has no revert handler and is "
            f"not listed in actions.NOT_REVERTIBLE"
        )


def test_not_revertible_actions_really_have_no_handler():
    assert not (actions.NOT_REVERTIBLE & set(history._REVERT))


def test_redo_is_a_subset_of_revert():
    """A redo replays what a revert undid, so it cannot cover an action the
    revert table does not."""
    assert set(history._REDO) <= set(history._REVERT)

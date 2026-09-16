// The History tab's action table: icon, colour and the VERB each action
// group wears — "Tagged 3 items", "Deleted 1 face". Pure data in a module of
// its own so `node --test` can import it (the i18n coverage harvest
// enumerates every verb) and so the verbs are `PluralSource` objects the
// render site hands to `tn()` — as closures inside the component they were
// raw English string-building that no language could translate.

import type { PluralSource } from "../shared/i18nCore";
import { RECORD_ICON } from "../shared/metaEnums.ts";

export type ActionMeta = {
  icon: string; color: string; verb: PluralSource;
};

export const ACTIONS: Record<string, ActionMeta> = {
  add_tag: { icon: "new_label", color: "var(--accent)", verb: { one: "Tagged 1 item", other: "Tagged {n} items" } },
  remove_tag: { icon: "label_off", color: "var(--muted)", verb: { one: "Removed 1 tag", other: "Removed {n} tags" } },
  add_to_group: { icon: "create_new_folder", color: "var(--accent)", verb: { one: "Added 1 item to groups", other: "Added {n} items to groups" } },
  remove_from_group: { icon: "folder_off", color: "var(--muted)", verb: { one: "Removed 1 item from groups", other: "Removed {n} items from groups" } },
  trash_item: { icon: "delete", color: "var(--red-text)", verb: { one: "Moved 1 item to Trash", other: "Moved {n} items to Trash" } },
  restore_item: { icon: "restore_from_trash", color: "var(--accent)", verb: { one: "Restored 1 item", other: "Restored {n} items" } },
  delete_item: { icon: "delete_forever", color: "var(--red-text)", verb: { one: "Deleted 1 item", other: "Deleted {n} items" } },
  rotate_item: { icon: "rotate_right", color: "var(--muted)", verb: { one: "Rotated 1 item", other: "Rotated {n} items" } },
  merge_item: { icon: "merge", color: "var(--muted)", verb: { one: "Merged 1 item", other: "Merged {n} items" } },
  split_item: { icon: "call_split", color: "var(--accent)", verb: { one: "Split 1 item", other: "Split {n} items" } },
  set_active_file: { icon: "swap_horiz", color: "var(--muted)", verb: { one: "Changed 1 active source file", other: "Changed {n} active source files" } },
  add_link: { icon: "link", color: "var(--accent)", verb: { one: "Added 1 link", other: "Added {n} links" } },
  remove_link: { icon: "link_off", color: "var(--muted)", verb: { one: "Removed 1 link", other: "Removed {n} links" } },
  add_caption: { icon: "add_comment", color: "var(--accent)", verb: { one: "Added 1 caption", other: "Added {n} captions" } },
  edit_caption: { icon: "edit_note", color: "var(--muted)", verb: { one: "Edited 1 caption", other: "Edited {n} captions" } },
  remove_caption: { icon: "comments_disabled", color: "var(--muted)", verb: { one: "Removed 1 caption", other: "Removed {n} captions" } },
  create_group: { icon: "folder_special", color: "var(--accent)", verb: { one: "Created 1 group", other: "Created {n} groups" } },
  delete_group: { icon: "folder_delete", color: "var(--red-text)", verb: { one: "Deleted 1 group", other: "Deleted {n} groups" } },
  move_tag_group: { icon: "drive_file_move", color: "var(--muted)", verb: { one: "Moved 1 tag between groups", other: "Moved {n} tags between groups" } },
  comment_tag: { icon: "sms", color: "var(--muted)", verb: { one: "1 tag comment", other: "{n} tag comments" } },
  set_tag_parent: { icon: "account_tree", color: "var(--muted)", verb: { one: "1 tag parent change", other: "{n} tag parent changes" } },
  import: { icon: "download", color: "var(--accent)", verb: { one: "1 import", other: "{n} imports" } },
  // Combined hide/show toggle — the icon/label is resolved from the (last)
  // event's hidden state below, so this generic fallback is rarely shown.
  set_hidden: { icon: "visibility_off", color: "var(--muted)", verb: { one: "Changed visibility of 1 item", other: "Changed visibility of {n} items" } },
  rename_tag: { icon: "edit", color: "var(--muted)", verb: { one: "Renamed 1 tag", other: "Renamed {n} tags" } },
  // A library group's tags flow down to every item under it.
  add_group_tag: { icon: "sell", color: "var(--accent)", verb: { one: "Tagged 1 group", other: "Tagged {n} groups" } },
  remove_group_tag: { icon: "label_off", color: "var(--muted)", verb: { one: "Removed 1 group tag", other: "Removed {n} group tags" } },
  // Groups: what a group SAYS, where it SITS, and a copy of it are three
  // different edits, so they are three rows — a shared one would make an
  // undo of a rename look like an undo of a drag.
  edit_group: { icon: "folder_managed", color: "var(--muted)", verb: { one: "Edited 1 group", other: "Edited {n} groups" } },
  move_group: { icon: "drive_file_move", color: "var(--muted)", verb: { one: "Moved 1 group", other: "Moved {n} groups" } },
  duplicate_group: { icon: "file_copy", color: "var(--accent)", verb: { one: "Duplicated 1 group", other: "Duplicated {n} groups" } },
  // Sequences. Every one of these is revertible, so each says what it would
  // take back — the faces block's rule, one subsystem along.
  create_sequence: { icon: "auto_stories", color: "var(--accent)", verb: { one: "Created 1 sequence", other: "Created {n} sequences" } },
  delete_sequence: { icon: "auto_stories", color: "var(--red-text)", verb: { one: "Removed 1 sequence", other: "Removed {n} sequences" } },
  rename_sequence: { icon: "edit", color: "var(--muted)", verb: { one: "Renamed 1 sequence", other: "Renamed {n} sequences" } },
  reorder_sequence: { icon: "swap_vert", color: "var(--muted)", verb: { one: "Reordered 1 sequence", other: "Reordered {n} sequences" } },
  remove_sequence_members: { icon: "playlist_remove", color: "var(--muted)", verb: { one: "Removed items from 1 sequence", other: "Removed items from {n} sequences" } },
  set_main_sequence: { icon: "star", color: "var(--muted)", verb: { one: "Changed 1 main sequence", other: "Changed {n} main sequences" } },
  // Tag boxes drawn in the annotator (an assignment's own boxes ride in its
  // add_tag/remove_tag events — these are the shapes edited on their own).
  add_tag_box: { icon: "add_box", color: "var(--accent)", verb: { one: "Drew 1 box", other: "Drew {n} boxes" } },
  edit_tag_box: { icon: "edit", color: "var(--muted)", verb: { one: "Edited 1 box", other: "Edited {n} boxes" } },
  delete_tag_box: { icon: "disabled_by_default", color: "var(--red-text)", verb: { one: "Removed 1 box", other: "Removed {n} boxes" } },
  flip_link: { icon: "swap_horiz", color: "var(--muted)", verb: { one: "Reversed 1 link", other: "Reversed {n} links" } },
  edit_image: { icon: "brush", color: "var(--accent)", verb: { one: "Saved 1 edited picture", other: "Saved {n} edited pictures" } },
  // Meta tags — the namespace links, captions and tag groups share.
  create_meta_tag: { icon: "new_label", color: "var(--accent)", verb: { one: "Created 1 meta tag", other: "Created {n} meta tags" } },
  rename_meta_tag: { icon: "edit", color: "var(--muted)", verb: { one: "Renamed 1 meta tag", other: "Renamed {n} meta tags" } },
  comment_meta_tag: { icon: "sms", color: "var(--muted)", verb: { one: "1 meta-tag comment", other: "{n} meta-tag comments" } },
  delete_meta_tag: { icon: "label_off", color: "var(--red-text)", verb: { one: "Deleted 1 meta tag", other: "Deleted {n} meta tags" } },
  // Faces. Every one of these is revertible, so each needs a row that says
  // what it would take back — the generic "N changes" fallback made a
  // deletion and a rename look like the same event.
  detect_faces: { icon: "person_search", color: "var(--accent)", verb: { one: "Detected faces on 1 item", other: "Detected faces on {n} items" } },
  add_face: { icon: "add_box", color: "var(--accent)", verb: { one: "Drew 1 face", other: "Drew {n} faces" } },
  name_face: { icon: RECORD_ICON.subject, color: "var(--accent)", verb: { one: "Named 1 face", other: "Named {n} faces" } },
  unname_face: { icon: "person_off", color: "var(--muted)", verb: { one: "Took the name off 1 face", other: "Took the name off {n} faces" } },
  name_faces: { icon: "groups", color: "var(--accent)", verb: { one: "Named 1 cluster of faces", other: "Named {n} clusters of faces" } },
  merge_faces: { icon: "merge", color: "var(--muted)", verb: { one: "Merged faces 1 time", other: "Merged faces {n} times" } },
  split_faces: { icon: "call_split", color: "var(--muted)", verb: { one: "Split faces off 1 time", other: "Split faces off {n} times" } },
  dismiss_face: { icon: "hide_source", color: "var(--muted)", verb: { one: "Dismissed 1 face", other: "Dismissed {n} faces" } },
  move_face: { icon: "open_with", color: "var(--muted)", verb: { one: "Moved 1 face box", other: "Moved {n} face boxes" } },
  delete_face: { icon: "delete", color: "var(--red-text)", verb: { one: "Deleted 1 face", other: "Deleted {n} faces" } },
  credit_face: { icon: "theater_comedy", color: "var(--accent)", verb: { one: "Credited 1 face to an actor", other: "Credited {n} faces to an actor" } },
  date_face: { icon: "schedule", color: "var(--muted)", verb: { one: "Dated 1 face", other: "Dated {n} faces" } },
  // Subjects, places and events — the three kinds of extra data on a tag.
  // Every one of these reverts, so each needs a row saying what it would take
  // back; the generic "N changes" made a deletion and a rename look alike.
  create_subject: { icon: "person_add", color: "var(--accent)", verb: { one: "Added 1 subject", other: "Added {n} subjects" } },
  rename_subject: { icon: "edit", color: "var(--muted)", verb: { one: "Renamed 1 subject", other: "Renamed {n} subjects" } },
  comment_subject: { icon: "sms", color: "var(--muted)", verb: { one: "1 subject comment", other: "{n} subject comments" } },
  date_subject: { icon: "cake", color: "var(--muted)", verb: { one: "1 subject date", other: "{n} subject dates" } },
  name_subject: { icon: RECORD_ICON.subject, color: "var(--accent)", verb: { one: "Named 1 subject", other: "Named {n} subjects" } },
  delete_subject: { icon: "person_remove", color: "var(--red-text)", verb: { one: "Deleted 1 subject", other: "Deleted {n} subjects" } },
  set_tag_when: { icon: "schedule", color: "var(--muted)", verb: { one: "Dated 1 assignment", other: "Dated {n} assignments" } },
  create_place: { icon: "add_location_alt", color: "var(--accent)", verb: { one: "Added 1 place", other: "Added {n} places" } },
  edit_place: { icon: "edit_location_alt", color: "var(--muted)", verb: { one: "Edited 1 place", other: "Edited {n} places" } },
  name_place: { icon: RECORD_ICON.place, color: "var(--accent)", verb: { one: "Named 1 place", other: "Named {n} places" } },
  delete_place: { icon: "wrong_location", color: "var(--red-text)", verb: { one: "Deleted 1 place", other: "Deleted {n} places" } },
  create_event: { icon: RECORD_ICON.event, color: "var(--accent)", verb: { one: "Added 1 event", other: "Added {n} events" } },
  edit_event: { icon: "edit_calendar", color: "var(--muted)", verb: { one: "Edited 1 event", other: "Edited {n} events" } },
  delete_event: { icon: "event_busy", color: "var(--red-text)", verb: { one: "Deleted 1 event", other: "Deleted {n} events" } },
  dismiss_place: { icon: "location_off", color: "var(--muted)", verb: { one: "Turned down 1 suggested place", other: "Turned down {n} suggested places" } },
  dismiss_event: { icon: "event_busy", color: "var(--muted)", verb: { one: "Turned down 1 suggested event", other: "Turned down {n} suggested events" } },
  revert: { icon: "undo", color: "var(--muted)", verb: { one: "Reverted 1 change", other: "Reverted {n} changes" } },
};

/** The generic row for an action the table does not know. */
export const UNKNOWN_ACTION: ActionMeta = {
  icon: "bolt", color: "var(--muted)",
  verb: { one: "1 change", other: "{n} changes" },
};

export function metaFor(action: string): ActionMeta {
  return ACTIONS[action] ?? UNKNOWN_ACTION;
}

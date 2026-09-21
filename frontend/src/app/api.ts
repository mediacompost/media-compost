// Typed API client for the Media Compost backend.

import type { Group as QueryGroup } from "../query/tree";
import { apiFetch } from "../shared/build";
import { ApiError, api as sharedApi, req } from "../shared/api";
import type { GroupNode, LibraryStats, StorageOut, StorageRow, StorageArtifactRow, StoragePruneRule, StoragePruneOut, StoragePruneJob, TagIndex, TagRow, SubjectRow, PlaceRow, EventRow, Paged, TagNameRow, MetadataCatalogEntry, SavedSearch, ItemSearchBody, AppSettings, SetupStatus, TagSetRef, TagSetText, TagSetSubject, TagSetPlace, TagSetEvent } from "../shared/api";

// Moved to shared/api.ts (the slice `shared/` and `query/` may use);
// re-exported so this module stays the app's one client surface.
export { ApiError } from "../shared/api";
export type { GroupNode, LibraryStats, StorageOut, StorageRow, StorageArtifactRow, StoragePruneRule, StoragePruneOut, StoragePruneJob, TagIndex, TagRow, SubjectRow, PlaceRow, EventRow, Paged, TagNameRow, MetadataCatalogEntry, SavedSearch, ItemSearchBody, AppSettings, SetupStatus , TagSetRef, TagSetText, TagSetSubject, TagSetPlace, TagSetEvent } from "../shared/api";
export type { QueryGroup };


export interface GroupDetail {
  id: number;
  name: string;
  icon: string;
  color: string | null;
  /** The smart group's membership rule; null for an ordinary group. */
  smart_query: string | null;
  parent_id: number | null;
  tags: { name: string; negative: boolean }[];
}

export interface ItemOut {
  id: number;
  // The item's UID, not its rowid: what a query string names it by
  // (`INFO:id=`, `SIMILAR:`). A rowid is reused after a delete; a uid is not.
  uid: string;
  name: string;
  // "image", "video", or "sequence" (a container that opens like a folder).
  kind: string;
  // For a "sequence" item: the sequence it represents (double-click opens it).
  sequence_id: number | null;
  // Video length in seconds (null for images).
  duration: number | null;
  width: number;
  height: number;
  megapixels: number;
  // Non-destructive display rotation of the active file (0/90/180/270). width/
  // height are already in the rotated orientation; used to cache-bust the
  // thumbnail and rotate full previews.
  rotation: number;
  active_file_id: number | null;
  // Short content hash of the active file — cache-busts the thumbnail so a
  // reused file id / changed content never shows a stale cached thumbnail.
  thumb_token: string;
  file_count: number;
  alt_count: number;
  // Hidden from the grid and counts (shown only in the Hidden view).
  hidden: boolean;
  link_item_id: number | null;
  group_ids: number[];
  // 1-based position and length of the item's main sequence (badge on the grid).
  seq_index: number | null;
  seq_total: number;
  // How many sequences this item belongs to (>1 → show a multi-sequence badge).
  seq_count: number;
  // Inside an open SEQUENCE view: which occurrence this card is (the
  // membership row's id). A repeated page is one card per position, all of
  // them the same item — so this, not `id`, is what tells the cards apart.
  member_id?: number | null;
  // Tags assigned directly to the item (with sign); excludes group-inherited
  // tags. Drives the grid's Quick-Assign indicator.
  direct_tags: TagAssignment[];
  // Effective positive tags (direct + group-inherited). Drives the grid's
  // "matches the selected tags" highlight.
  eff_tags: string[];
  // Effective negative tags — lets the highlight match a negatively-selected tag.
  eff_neg: string[];
  // For a sequence item: active file ids of its first four members (2×2 thumb).
  member_thumbs: number[];
}

export interface ItemPage {
  items: ItemOut[];
  total: number;
  page: number;
  page_size: number;
  /** Library revision this page describes — compared across assembled pages;
   *  a mixed window means an external writer moved the view (see
   *  invalidation.reportLibraryRev). */
  rev?: string;
}

export interface ItemFacets {
  /** How many items the scope holds — the sidebar's badge figures, and the
   *  whole of what this endpoint answers. (It used to carry min/max width,
   *  height, megapixels and aspect ratio as "input hints"; nothing read
   *  them, and computing them joined the active file of every item in
   *  scope.) */
  count: number;
}

export interface FileNameEntry {
  id: number;
  name: string;
  // True for a web-URL source (`name` holds the URL); `accessed_at` is its
  // optional ISO access date/time.
  is_url: boolean;
  accessed_at: string | null;
}

export interface FileVersion {
  id: number;
  width: number;
  height: number;
  bytes: number;
  format: string;
  is_derived: boolean;
  active: boolean;
  // "stored" | "video_frame" | "video_clip".
  source_kind: string;
  duration: number | null;
  frame_rate: number | null;
  bitrate: number | null;
  source_start: number | null;
  source_end: number | null;
  // True for edited/derived versions (labelled "edited" in the Source list).
  edited: boolean;
  // Stable per-item source-file number (#1, #2, #3 …).
  number: number | null;
  // For an edited file: the number of the file it is currently based on (the
  // grandparent after a middle file was deleted) and the action that produced
  // it. Null/empty for imports and rotations.
  based_on: number | null;
  edit_action: string;
  // The full historical lineage of edit steps (by file number), preserved even
  // when an intermediate file is deleted.
  edit_chain: { from: number; to: number; action: string }[];
  // Orientation of the stored bytes relative to the item's first source file:
  // clockwise degrees (0/90/180/270) plus a pre-rotation horizontal mirror.
  rotation: number;
  mirrored: boolean;
  // This file's region of the item's reference frame (for tag-box alignment).
  crop_x: number;
  crop_y: number;
  crop_w: number;
  crop_h: number;
  // When this file's bytes were created: import time for a source file, or the
  // save time for an edited/derived file (ISO 8601), or null.
  created_at: string | null;
  // Each source filename this file was imported under.
  names: FileNameEntry[];
  // Auxiliary images generated from this file (depth maps, pose overlays),
  // shown nested under it in the Source list.
  artifacts: FileArtifact[];
}

// An auxiliary image generated from a source file (depth map, pose overlay).
export interface FileArtifact {
  id: number;
  kind: string;        // "depth" | "pose" | "latent" | …
  model: string;       // human label of the model that produced it
  // For a cached training latent: which entry this is ("flipped", "masked").
  variant?: string;
  width: number;
  height: number;
  bytes: number;
  format: string;
  // True when the source file was edited after this was generated (out of date).
  stale: boolean;
  // Artifacts generated from THIS one rather than from the source file: the
  // training latents encoded from a degraded copy of the picture. One level
  // only — nothing is derived from a latent.
  children?: FileArtifact[];
}

/** Which of the item's files says a value. `number` is the per-item file
 *  number the Files tab and the header's file chip already name files by. */
export interface MetadataSource {
  file_id: number;
  number?: number | null;
  active?: boolean;
}

export interface MetadataField {
  key: string;
  value: string;
  // ISO datetime for date fields — formatted per the user's preferences.
  iso?: string | null;
  // The canonical search-catalog name (`INFO:<name>`), or null where the row
  // has none. Replaced the CATALOG_KEY table this file used to carry: the
  // backend has always known the answer, and a mirror of it could drift.
  name?: string | null;
  // What the `INFO:<name>=` atom must carry — the value the INDEX holds, not
  // the string written for a person ("4000" against "4000 px"), so the filter
  // button never parses a label back into a value. Null means the shown value
  // is not what search would find this item by: an offered value from a
  // non-active file. Draw the button iff `name && filter_value`.
  filter_value?: string | null;
  // A value promoted to the ITEM — true whichever file is active.
  pinned?: boolean;
  // The active file says this and the item ignores it: shown struck, with a
  // way back, and not searched.
  muted?: boolean;
  sources?: MetadataSource[];
}

export interface ItemMetadata {
  /** The main section: what the item answers with. */
  fields: MetadataField[];
  /** Every value only a NON-ACTIVE file carries — offered, never applied. */
  others: MetadataField[];
}

export interface MediaTrack {
  index: number;
  // "video" | "audio" | "subtitle" | "data".
  kind: string;
  codec: string;
  detail: string;
  language: string | null;
  // The track's name/title (e.g. a subtitle "Signs" track), when present.
  title?: string | null;
  // Plays/shows by default (container default disposition).
  default?: boolean;
  // Per-track metadata rows (dimensions, frame rate, bitrate, channels, …).
  meta: { label: string; value: string }[];
}

export interface MediaTracks {
  tracks: MediaTrack[];
}

export interface TagBox {
  id?: number;
  // Bounding box as fractions of the image (0..1); all null for a pure time
  // annotation. time_start/time_end (seconds) apply to videos/frames.
  x: number | null;
  y: number | null;
  w: number | null;
  h: number | null;
  time_start: number | null;
  time_end: number | null;
  // Groups the timed boxes of one moving video subject into a single track
  // (null for a standalone box). See the backend's ItemTagBox.track_id.
  track_id?: number | null;
  // A pure TIME RANGE carries its own sign: over a film a tag is present in
  // some stretches and pointedly absent in others. Meaningless on a box with
  // geometry, whose sign is the item's.
  negative?: boolean;
  // An optional POLYGON refining the rectangle: [[x, y], ...] vertices in the
  // same frame. While set, x/y/w/h are its bounding box — the server derives
  // them, so every rectangle reader stays correct.
  points?: [number, number][] | null;
}

export interface TagAssignment {
  name: string;
  negative: boolean;
  count: number;
  // Bounding-box / time-range annotations for this tag on this item.
  boxes?: TagBox[];
}

export interface SequenceMember {
  /** The MEMBERSHIP row's id. The same item may sit at several positions
   *  (a book's blank pages all dedup onto one item), so `item_id` cannot
   *  name one occurrence — reorder and a row's ✕ address THIS. */
  id: number;
  item_id: number;
  position: number;
  name: string;
  active_file_id: number | null;
  kind: string;
}

export interface SequenceInfo {
  id: number;
  // Stable, library-independent identity (what exports/sidecars reference).
  uid: string;
  name: string;
  kind: string;
  is_main: boolean;
  total: number;
  members: SequenceMember[];
  // The sequence's container library item (kind="sequence"), if any.
  item_id: number | null;
  item_uid: string | null;
}

export interface SequenceSummary {
  id: number;
  name: string;
  kind: string;
  total: number;
  thumb_file_id: number | null;
}

export interface RelationshipOut {
  id: number;
  from_item_id: number;
  to_item_id: number;
  other_item_id: number;
  // The linked item's stable uid (the numeric id is library-local).
  other_item_uid: string;
  other_name: string;
  // Active file id of the other item (for a hover thumbnail even when it isn't
  // in the loaded grid page).
  other_file_id: number | null;
  outgoing: boolean;
  kind: string;
  meta: Record<string, number | string>;
  // Bounding boxes on the link (fractions of the ``to_item`` frame). Drawn on
  // the link's hover thumbnail; a link with ≥1 box shows an icon after its name.
  boxes: { x: number; y: number; w: number; h: number }[];
  // Free-form user "link tags" on this relationship (separate from item tags).
  tags: string[];
}

export interface EventOut {
  id: number;
  created_at: string;
  source: string; // "web" | "cli"
  username: string; // who made the change ("" = anonymous / CLI)
  action: string;
  entity_type: string;
  entity_id: number | null;
  summary: string;
  /** The summary's unfilled template and slot values — empty for rows written
   *  before the columns existed (`summary` is the English fallback). A var
   *  may be a nested {key, vars, text} (the "Reverted: …" case). */
  summary_key: string;
  summary_vars: Record<string, SummaryVar>;
  data: Record<string, unknown>;
  reverted: boolean;
  revertible: boolean;
}

export type SummaryVar =
  | string
  | { key: string; vars: Record<string, SummaryVar>; text: string };

export interface HistoryPage {
  events: EventOut[];
  total: number;
}

export interface RevertResult {
  reverted: number[];
  failed: number[];
  // The log entries the reversal itself wrote. Reverting THOSE replays the
  // original, which is all a redo is.
  events: number[];
}

export interface FrameMarker {
  item_id: number;
  timestamp: number;
  name: string;
}

/** A STILL of a video: an image item holding a whole frame, or a crop of one.
 *  It is an ordinary image item — `crop` is provenance on the link back to the
 *  film, not a window on the item itself. */
export interface Still {
  item_id: number;
  timestamp: number;
  name: string;
  /** x, y, w, h as fractions of the frame; null for a whole frame. */
  crop: [number, number, number, number] | null;
  width: number;
  height: number;
  /** The still's active file, for `thumbUrl`. */
  file_id: number | null;
}

export interface IndirectGroupTags {
  group_id: number;
  group_name: string;
  tags: string[];
  // True when the group assigns these tags negatively (marks them removed).
  negative: boolean;
  // Where the tags come from: "group" (a library group), "parent" (implied by
  // the tag hierarchy), or "sequence" (a sequence's member tags).
  source?: "group" | "parent" | "sequence";
  // Tags the item also assigns directly — shown greyed out / struck through.
  overridden?: string[];
  // For source "parent": tag name → the assigned descendant tag(s) that entail
  // it (shown as the reason next to a hierarchy-implied tag).
  sources?: Record<string, string[]>;
}

/** One reference image of an instruction, at its place in the order. */
export interface CaptionRef {
  item_id: number;
  item_uid?: string;
  name?: string;
  file_id?: number | null;
}

export type CaptionKind = "caption" | "instruction";

export interface Caption {
  id: number;
  text: string;
  /** "caption" describes the picture; "instruction" says how it was made from
   *  `refs`. Two lists in the sidebar, two training sources — never mixed. */
  kind?: CaptionKind;
  // True for a machine-generated caption awaiting approval.
  pending?: boolean;
  // Human-readable name of the AI model that generated it ("" for hand-written).
  model?: string;
  // True once a generated caption has been edited by the user.
  edited?: boolean;
  /** Meta tags on this caption — the same namespace a link's tags use. */
  tags?: string[];
  /** An instruction's source images, IN ORDER. Always empty for a caption. */
  refs?: CaptionRef[];
}

export interface TagGroupOut {
  id: number;
  name: string;
  // True for the auto-managed "Pending" group (machine tags awaiting approval).
  system?: boolean;
  /** Meta tags on the grouping itself — the same namespace links and captions
   *  use, never the item's own tags. */
  tags?: string[];
  /** Subjects this grouping is ABOUT (her tags / his tags). Organizational
   *  only: the grouped tags stay the item's, never the subject's attributes. */
  subjects?: number[];
}

export interface TagInstance {
  // Placement id (null for a purely implicit ungrouped instance with no boxes).
  placement_id: number | null;
  name: string;
  negative: boolean;
  // Which tag group this instance is in (null = the ungrouped default).
  group_id: number | null;
  // True for a machine-generated tag awaiting approval.
  pending?: boolean;
  // True for a ranking's own score row — the item's standing, materialized.
  // A score tag assigned by hand is an ordinary instance (false).
  boxes: TagBox[];
}

/** One relationship of an item as the copy action needs it — which item is at
 *  the other end, which way round, of what kind, and its meta tags. Nothing
 *  hydrated: no row is rendered from this. */
export interface LinkSlim {
  other_item_id: number;
  outgoing: boolean;
  kind: string;
  tags: string[];
}

/** The slice of `ItemDetail` the grid's context menu needs, served in bulk by
 *  `POST /api/items/details`: the caption probe and the copy actions.
 *  `tags` are the DIRECT tag names (both signs, sorted); `tag_groups` carry
 *  id/name/system only; `tag_instances` come without boxes; a caption's
 *  `refs` carry bare item ids (an instruction's sources, in order). */
export interface ItemSlim {
  id: number;
  captions: Caption[];
  tags: string[];
  tag_groups: TagGroupOut[];
  tag_instances: TagInstance[];
  links: LinkSlim[];
  /** Live top-level text regions on the ACTIVE file — `ItemDetail.text_count`
   *  per item, so a selection's Text tab can say how much of it has been read
   *  without pulling a tree of blocks and words per picture. */
  text_count?: number;
}

export interface ItemDetail extends ItemOut {
  // The item's stable library-independent identity (32-char hex uid), shown in
  // the Info section in place of the internal numeric id.
  uid: string;
  // The item's two dates (ISO). `created_at` = first seen; `last_imported_at` =
  // refreshed on every re-import. Source files have no dates of their own.
  created_at: string | null;
  last_imported_at: string | null;
  files: FileVersion[];
  captions: Caption[];
  tags: TagAssignment[];
  indirect: IndirectGroupTags[];
  // Per-item tag groups + the placement of each direct tag into them.
  tag_groups: TagGroupOut[];
  tag_instances: TagInstance[];
  /** The item's subjects — a view over its tags, with each appearance. */
  subjects?: SubjectOnItem[];
  /** Face detectors already run over this item, whatever they found — the
      Detect faces menus tick these. */
  face_models?: string[];
  /** Text engines already run over this item — `face_models`' twin, for the
      Detect text menus' ticks. */
  text_models?: string[];
  /** Live top-level text regions. On the wire so the Text tab's BADGE never
      has to pull the whole tree (every word of a manga page) for a number. */
  text_count?: number;
  /** When the picture was taken — sortable YYYYMMDDHHMMSS, zeros for whatever
   *  is unknown. `taken_source` says which of the three answers it is: "set"
   *  (typed by hand), "exif" (what the camera said), "event" (the span of an
   *  event it carries) or "" (nothing says). */
  taken_at?: number | null;
  taken_source?: string;
  /** WHERE it was taken. `coords_source` says which of the three answers it
   *  is, exactly as `taken_source` does: "set" (typed), "exif" (the file's
   *  own), "never" (somebody said there are none) or "" (nothing says). */
  lat?: number | null;
  lon?: number | null;
  coords_source?: string;
  // Set when the item is in the Trash; restore_groups are the groups it returns
  // to on restore.
  trashed: boolean;
  restore_groups: number[];
}


export interface EditRequest {
  source_file_id: number;
  rotate: number;
  crop: number[] | null;
  save_mode: "overwrite" | "derived";
}


// A subject: who or what a picture is OF. A subject is extra data on a TAG —
// `tag` is the identity slug it owns (empty while the subject is unnamed, e.g.
// a face cluster) and `items` is that tag's count.
/** One APPEARANCE: somebody a face has been said to be.
 *
 * A face carries a list of these, because one rectangle can be a character and
 * the actor playing them at once, each with an age of its own. `id` is the
 * appearance row — what dating or removing this one claim addresses. */
export interface FaceSubject {
  id: number;
  subject_id: number;
  name: string;
  comment: string;
  tag: string;
  since_date: number | null;
  /** "user" | "suggested" — a suggestion is offered, never applied. */
  assigned_by: string;
  match_score: number | null;
  /** How old they are in this picture. `when_derived` marks a half worked out
   *  from the subject's since-date rather than typed. */
  when_date: number | null;
  when_age: number | null;
  when_derived: boolean;
}

export interface FaceRow {
  id: number;
  item_id: number;
  /** The item's uid — what an `id:` search takes, so a crop can send the
   *  Library to the picture it came from. */
  item_uid: string;
  /** The file it was found in — for showing the whole picture behind the crop. */
  file_id: number | null;
  /** The box in the item's reference frame, fractions 0..1. */
  x: number;
  y: number;
  w: number;
  h: number;
  /** The detector's confidence; null for a face drawn by hand. */
  det_score: number | null;
  /** Every model that found this face — several when detectors overlap and
   *  their boxes merged, empty for one drawn by hand. */
  models: string[];
  /** Who this face is. Empty when nobody has said; more than one when it is
   *  both a character and the actor. */
  subjects: FaceSubject[];
  dismissed: boolean;
  has_embedding: boolean;
  /** Which embedders have described it; only faces sharing one compare. */
  embedded_by: string[];
  /** The face's optional OUTLINE — the whole figure, drawn by hand.
   *  [x, y, w, h] in the item's reference frame; while `outline_points` is
   *  set the rectangle is its bounding box. A subject attached to the face
   *  uses it wherever it has no subject box of its own. */
  outline?: [number, number, number, number] | null;
  outline_points?: [number, number][] | null;
  /** True while the box is a PERSON's answer — a hand edit of a detected
   *  face. "Reset the box" is offered exactly then. */
  edited?: boolean;
}

/** What the open cluster's pictures say about how to lay its crops out.
 *
 *  PARALLEL ARRAYS on `face_ids` — the tags list's own shape. `tag_names` is
 *  the capsule bar, most CROPS first (crops, not pictures: the grid draws a
 *  card per crop), capped and floored server-side so a tag on one crop — a
 *  group of one — is never offered. */
export interface FaceGroupingOut {
  face_ids: number[];
  /** The sequence each crop's picture is a page of, "" for a picture in none. */
  sequences: string[];
  tag_names: string[];
  /** How many CROPS each tag is on — what the capsule shows. */
  tag_faces: number[];
  /** Which of `tag_names` each crop carries, by index. */
  tags: number[][];
}

export type TextLevel = "block" | "line" | "word" | "char";

/** A region of text found in (or drawn on) a picture, subtree and all.
 *
 * The box is the AABB in the ITEM's reference frame (fractions 0..1), like a
 * face and a tag box — the annotator maps it through `refToFile` /
 * `fileToRef` for whichever file is on screen. `quad` is the engine's own
 * four-point outline where it read a rotated shape; empty means the box IS
 * the shape. */
export interface TextRegion {
  id: number;
  item_id: number;
  /** The item's uid — what an `id:` search takes. */
  item_uid: string;
  file_id: number | null;
  parent_id: number | null;
  level: TextLevel;
  /** Reading order among siblings — the engine's own. */
  ord: number;
  x: number;
  y: number;
  w: number;
  h: number;
  quad: [number, number][];
  text: string;
  /** The engine's confidence; null when it has none to give (Magi is
   *  generative) — whether a region is hand-drawn is `models`, not this. */
  score: number | null;
  lang: string;
  /** Every engine that read it; EMPTY is what "drawn by hand" means, the
   *  same way it does on a face. */
  models: string[];
  dismissed: boolean;
  /** A person corrected the text; no run rewrites it after this. */
  edited: boolean;
  children: TextRegion[];
}

export interface FaceCluster {
  faces: FaceRow[];
  /** How many faces the cluster REALLY has. `faces` may be a first-row-sized
      slice of it, so a "+N more" built from `faces.length` would say there is
      nothing left to see. */
  total: number;
  /** The nameless subject holding a hand-merged cluster together, if any. */
  subject_id?: number | null;
  /** True when descriptors agreed; false for a detection-only model's
      one-face-per-group fallback. */
  grouped: boolean;
  /** How many of those faces carry a name a model guessed and nobody has
      agreed with yet — counted over the WHOLE cluster, since `faces` may be
      a slice and the guesses are exactly what somebody opens it for. */
  guesses: number;
}

export interface NamedFaces {
  clusters: FaceCluster[];
  /** Distinct named faces. Not summable from the clusters: they carry one row
      each, and a face credited to a character AND its actor is under both. */
  faces: number;
}


/** When a tag was true of an item — the state of one assignment. */
export interface TagWhen {
  date: number | null;
  age: number | null;
}

/** One subject on an item, with the state of that assignment. */
/** One appearance of a subject in an item — a row in the sidebar. */
export interface SubjectAppearance {
  id: number;
  face_id: number | null;
  when: TagWhen | null;
  when_derived: boolean;
  assigned_by: string;
  match_score: number | null;
  /** Where the row sits in the sidebar's list — the drag-reorder's answer;
   *  ties break by id, so 0 everywhere is the creation order. */
  position?: number;
  /** The appearance's SUBJECT BOX — [x, y, w, h] in the item's reference
   *  frame, the whole figure where the face is only the head. */
  box?: [number, number, number, number] | null;
  /** The box's optional POLYGON outline — while set, `box` is its bounding
   *  box (the server keeps the two in step). */
  points?: [number, number][] | null;
}

export interface SubjectOnItem {
  id: number;
  display_name: string;
  comment: string;
  tag: string;
  /** The identity tag's id. */
  tag_id: number;
  since_date: number | null;
  /** Every time they are in this picture. A subject with none is on the item
   *  through its tag alone. */
  appearances: SubjectAppearance[];
}



/** A place an event on this item was at — offered, never assigned. */
export interface SuggestedPlace {
  place: PlaceRow;
  occasion_id: number;
  via_event_tag: string;
  via_event_name: string;
}

export interface SuggestedEvent {
  event: EventRow;
  /** The picture's own capture date that put it inside the span, so the row
   *  can say WHY it is being offered rather than merely appearing. */
  date_taken: number | null;
}

export interface FilePlaceSuggestion {
  /** The place the item's own file names (XMP/IPTC city/state/country) —
   *  offered, never created. `place` is the existing named place accepting
   *  would reuse; null means accepting creates it, coordinates and all. */
  name: string;
  lat: number | null;
  lon: number | null;
  place: PlaceRow | null;
}

export interface ItemSuggestions {
  places: SuggestedPlace[];
  events: SuggestedEvent[];
  /** What the item's own file says about where it was taken, unanswered. */
  file_place: FilePlaceSuggestion | null;
  /** False when the item has no indexed capture date at all — the section says
   *  so, rather than showing an empty list that reads as "nothing matched". */
  dated: boolean;
}

// A meta tag in the Tags tab's "Meta" mode: a comment, and one usage count per
// carrier of the namespace (`count` is their total).
export interface LinkTagRow {
  name: string;
  comment: string;
  /** The long form, with line breaks — what the ? beside the name opens. */
  description?: string;
  count: number;
  links: number;
  captions: number;
  tag_groups: number;
  /** The fourth carrier: the library's own tags. */
  tags: number;
}

// AI actions ---------------------------------------------------------------
// A task kind (backend plugins.tasks) — no longer a fixed frontend union, since
// the action list is served by the backend.
export type JobKind = string;

export interface ModelInfo {
  id: string;
  name: string;
  available: boolean;
  note: string;
  url: string;
  family: string;
  variant: string;
  // Downloadable-family key (joins with ModelCacheInfo.key); "" when none.
  family_key: string;
  // All sources the model needs (a model may require several, e.g. a detector +
  // an inpainter); the action menu stays "needs download" until all are cached.
  family_keys: string[];
  // Plugin key whose setup commands the "Run setup" button can execute
  // (POST /api/ml/setup/{key}); "" when nothing is runnable.
  setup_key: string;
  // True when a run needs a user-picked color-reference image: the action
  // opens the reference picker before enqueueing.
  needs_reference?: boolean;
  /** The id of a model that does everything this one does and more. The action
   *  menus leave this one out while THAT one is ready — offering a strictly
   *  worse variant of an installed model is offering a mistake. */
}

// An AI action + its models, so the UI renders actions data-driven.
export interface TaskInfo {
  kind: JobKind;
  label: string;
  icon: string;            // Material Symbols Rounded name
  result: string;          // "image" | "caption" | "tags"
  /** The `panels` task's one switch (gather the panels into a sequence) —
   *  the only extra output an action offers. */
  sequence_option: boolean;
  models: ModelInfo[];
}

/** One save from the video editor. Only `cuts` is required — the rest is
 *  whatever the Video menu was actually asked for. */
export interface VideoEditPlan {
  cuts: { start: number; end: number }[];
  rotate?: number;
  crop?: { x: number; y: number; w: number; h: number } | null;
  scale?: { w: number; h: number } | null;
  fps?: number | null;
  new_item?: boolean;
}

export interface VideoJob {
  job_id: number | null;
  status: string;
  progress: number;
  message: string;
}

export interface ModelsOut {
  tasks: TaskInfo[];
  /** Background-job kinds that are NOT AI actions (a video render) — label and
   *  icon only, so the task list can name their rows. Never rendered as an
   *  action button: the menus are built from `tasks`. */
  job_kinds?: TaskInfo[];
}

export interface JobOut {
  id: number;
  kind: JobKind;
  model: string;
  /** The one picture this job is about — null where the answer is "the
   *  library" (an estimate walks a whole scope and names no item). */
  item_id: number | null;
  item_name: string;
  // Number of items the job covers (>1 for a multi-item tag job).
  item_count: number;
  // "queued" | "running" | "paused" | "done" | "warning" | "failed" | "canceled".
  // A PAUSED job is held, not finished: it keeps its place and its cursor.
  status: string;
  message: string;
  // Progress percentage (0-100) for multi-step jobs; 0 when not reported.
  progress: number;
  /** How many of `item_count` are finished — the batch cursor. */
  done_count: number;
  /** Whether this job has a boundary between items to stop at. Answered by
   *  the server: which kinds run as a batch is the queue's own rule, and a
   *  Pause button that sometimes did nothing would be worse than none. */
  pausable: boolean;
  created_at: string | null;
}

export interface JobItem {
  id: number;
  name: string;
  // "done" | "running" | "pending"
  status: string;
}

export interface JobProgress {
  total: number;
  done: number;
  status: string;
  offset: number;
  items: JobItem[];
}


/** Query string for the shared `{q, limit, offset}` paged-list options. */
function pageParams(opts: { q?: string; limit: number; offset?: number }): string {
  const p = new URLSearchParams();
  if (opts.q) p.set("q", opts.q);
  p.set("limit", String(opts.limit));
  if (opts.offset) p.set("offset", String(opts.offset));
  return p.toString();
}








// One section of the grid. `key` is machine-readable and never a label —
// month and colour names are localized here, at the render site.
export interface GroupRun {
  key: string;
  count: number;
}

export interface ItemGroupRuns {
  group_by: string;
  total: number;
  // In the page order, so the counts prefix-sum into each section's span.
  runs: GroupRun[];
  rev?: string;
}

export interface ImportJob {
  id: string;
  status: string;
  // `hidden_matches` is pairs of `[name, "hidden" | "trashed"]` — see
  // `importer.ImportStats`; everything else here is a count or a list of ids.
  stats: Record<string, number | string[] | string[][]>;
  message: string;
  total: number;
}


export interface ModelCacheInfo {
  key: string;
  label: string;
  repo: string;
  url: string;
  gated: boolean;
  deps_ok: boolean;
  cached: boolean;
  downloading: boolean;
  // Accepted but WAITING for a download slot — nothing is moving yet.
  queued?: boolean;
  // Download progress percent (0-100) while downloading, or -1 when unknown.
  progress: number;
  // Bytes fetched / bytes to fetch while downloading (0 when not known).
  done_bytes?: number;
  total_bytes?: number;
  download_error: string;
  local_path: string;
  // Coarse model type used to group the Settings model list ("" when unknown).
  category: string;
  /** Weights that come from somewhere other than Hugging Face: no repo, but a
   *  Download still means something because the plugin fetches its own. */
  fetchable?: boolean;
  // Rough VRAM estimate to run the model ("4 GB"), or "" when there is nothing
  // to size (a plugin that is pure OpenCV arithmetic has no model).
  vram: string;
  // On-disk size of the downloaded weights in bytes (0 when not cached).
  size: number;
  // Plugin key whose setup commands the "Run setup" button can execute
  // (POST /api/ml/setup/{key}); "" when nothing is runnable.
  setup_key: string;
}


export interface ModelCacheOut {
  models: ModelCacheInfo[];
  token_available: boolean;
  // Non-empty (e.g. "HF_HUB_OFFLINE=1") when the environment forces offline.
  env_offline: string;
}

// ---- rankings ----------------------------------------------------------------

/** One LEAGUE of a ranking — a population with standings of its own under
 *  the ranking's range. `name` is "" for the unnamed first one (rendered
 *  "Default"); the counts are the pool's own. */
export interface RankingPoolRow {
  id: number;
  name: string;
  /** Whether its comparisons can order its pictures at all. False and the
   *  pool is still rated and still fitted; it just has nothing the scale
   *  can honestly say yet. */
  settled: boolean;
  judgments: number;
  items: number;
}

export interface RankingEstimateOut {
  /** How many rated pictures the fit rests on. */
  rated: number;
  /** How many the estimate could answer for. */
  estimated: number;
  /** How many carried no vector in any chosen space — a thing to index,
   *  not a failure of the estimate. */
  unindexed: number;
  /** How many pictures were looked at. A write walks the whole scope; a
   *  preview draws a bounded scrambled sample, since it runs on every edit
   *  of a rule. */
  scanned: number;
  /** …and whether that was less than the scope holds: the counts are then
   *  exact over what was scanned and nothing more. */
  partial: boolean;
  /** What the scope holds, where the preview asked. */
  total: number | null;
  /** Per rule: how many pictures it takes, and a handful of them to look
   *  at — the sample is the RULE's, since a rule is a claim about pictures
   *  and the only way to see whether it travelled is to look at what it
   *  claims. */
  rules: Array<{ matched: number; tags: string[]; groups: number[];
                 sample: RankingItemRef[]; sample_scores: number[] }>;
}

/** THE ESTIMATE REQUEST, one shape for both paths — the preview and the
 *  write are the same question, and the path says which is being asked. */
/** What a ranking verb is about: the named pictures, or the whole view. */
export type RankingItemsBody = Partial<ItemSearchBody> & {
  items?: number[];
  view?: boolean;
};

export type EstimateBody = ItemSearchBody & {
  items?: number[];
  pool_ids?: number[];
  embedders?: string[];
  /** Each a BAND: `min` is where it starts, and the bands are the rules
   *  sorted by it — each running up to the next one's start, the last with
   *  no top — so they partition the scale and a picture is in exactly one. */
  rules: Array<{ min?: number | null; tags: string[]; groups?: number[] }>;
  /** Guess at the pictures the ranking has NOT placed and read the rules
   *  against them too. Off, only the ones it HAS are covered, each at its
   *  own standing — which a picture the ranking placed is always read at,
   *  never at the fit's guess about it. */
  estimate_unranked?: boolean;
};

export interface RankingRow {
  id: number;
  name: string;
  scope: string;
  /** The scale the standings are spread over, inclusive both ends — what
   *  the Assign-ratings rules are written against. A ranking owns no tag
   *  namespace (rung v31), so this is the whole of what it counts in. */
  bucket_lo: number;
  bucket_hi: number;
  judgments: number;
  // Distinct items the judgments name — how many pictures the axis placed.
  items: number;
  // Pictures set aside as not applicable — ranking-wide, never per pool.
  // Its own sidebar row wherever there are any.
  dismissed: number;
  /** FILE ids of its best few pictures — the card's 2×2 mosaic in the
   *  Rankings view. Empty unless the call asked for covers. */
  thumbs: number[];
  // Always at least one; the rate chooser offers a pick only past one.
  pools: RankingPoolRow[];
}

export interface RankingItemRef {
  item_id: number;
  uid: string;
  name: string;
  kind: string;
  file_id: number | null;
  thumb_token: string;
  width: number;
  height: number;
  /** The item's non-destructive display rotation, so a session card shows
   *  the picture the way the library does — and so the card's own rotate
   *  buttons have something to move. */
  rotation: number;
  // A sequence container's pages, for the card to flip through.
  members: RankingItemRef[];
}

/** The tag-batch session feed's reply. `queue` reuses the rating card's ref
 *  shape (the card is shared); `ordered` says whether the classifier had
 *  anything to order by; `embedded`/`total` are the coverage line. */
export interface TagSortNextOut {
  queue: RankingItemRef[];
  /** Candidates left — NULL where the request said it already knows
   *  (`want_pool`), which is every feed after the chooser's own probe: a
   *  count over the whole scope, for a number the session can work out. */
  pool: number | null;
  embedded: number;
  total: number | null;
  ordered: boolean;
  labeled: Record<string, [number, number]>;
  /** Per requested embedder, how many of the pool carry its vector. */
  coverage: Record<string, number>;
}

/** One card of a tag-grid batch: the ref plus where the classifier put it.
 *  `bucket` is where the card STARTS — a suggestion, never an assignment. */
export interface TagGridItem extends RankingItemRef {
  score: number | null;
  bucket: "positive" | "none" | "negative";
  // What the picture already carries, for a session including tagged
  // pictures: the tag, its negative (or the counter tag), or both.
  existing?: "positive" | "negative" | "both" | null;
}

export interface TagGridNextOut {
  queue: TagGridItem[];
  pool: number | null;
  total: number | null;
  /** Scorable at all — a current vector in ANY named space… */
  embedded: number;
  /** …and per embedder, which is what the chooser's index buttons need. */
  coverage: Record<string, number>;
  ordered: boolean;
  labeled: [number, number];
  cut_hi: number | null;
  cut_lo: number | null;
}

export interface RankingPairOut {
  a: RankingItemRef | null;
  b: RankingItemRef | null;
  // Why there is no pair, as a key the UI words ("small_pool").
  reason: string;
  /** How many items the session rates over — NULL where the request said it
   *  already knows (`want_pool`), which is every press after the first: it
   *  is a count over the whole scope and it cannot move while a session
   *  runs. The overlay keeps the figure it was given. */
  pool: number | null;
  judgments: number;
  /** With no pair left and something judged: how the session's pool stands
   *  right now, best first — the overlay's end-of-session summary. */
  summary?: { ref: RankingItemRef; bucket: number;
              /** The pool this standing is in — entries arrive pool by
               *  pool, so one item may appear once per pool. */
              pool_id: number; pool: string }[];
}

export interface RankingBucketOut {
  bucket: number;
  count: number;
  samples: RankingItemRef[];
}

export interface RankingPoolDetailOut {
  id: number;
  name: string;
  /** Whether the comparisons can order the pictures yet. */
  settled: boolean;
  judgments: number;
  scored: number;
  buckets: RankingBucketOut[];
}

export interface RankingItemStanding {
  /** `(pool id, pool name, bucket)` per pool that placed it. Empty where the
   *  ranking has not: unjudged, only ever skipped, or set aside. */
  placed: [number, string, number][];
  /** Decisive or tie judgments this picture has been part of — what the
   *  standing is MADE of, and the honest answer to "why is this a 3". */
  judgments: number;
  dismissed: boolean;
  bucket_lo: number;
  bucket_hi: number;
}

export interface RankingDetailOut {
  id: number;
  /** The FIRST pool's histogram; the per-pool answer is `pools`. */
  buckets: RankingBucketOut[];
  not_applicable: RankingItemRef[];
  judgments: number;
  scored: number;
  pools: RankingPoolDetailOut[];
}

/** One tag list (`/api/tag-sets`) — imported, or one of the app's own. */
export interface TagSetOut {
  id: number;
  key: string;
  name: string;
  description: string;
  version: number;
  /** ONE OF THE LISTS THE APP SHIPS. Read-only — no rename, no entry, no
   *  category — but exported, duplicated into a copy you can edit, ordered,
   *  switched on and off, and its two advice flags are yours. It holds no
   *  entry at all until it is switched on. */
  builtin: boolean;
  /** A built-in whose shipped file has moved on since its entries were
   *  written. The row says so and its ⋯ offers Update; nothing rewrites it
   *  on its own. Only a built-in that HOLDS entries can be behind. */
  outdated: boolean;
  enabled: boolean;
  /** Whether the set's alias spellings are offered and its entries' implied
   *  names are minted — the ROOT of the three-state walk its categories do. */
  aliases_enabled: boolean;
  implications_enabled: boolean;
  position: number;
  entries: number;
  categories: number;
  /** THE LIBRARY'S OWN — the first pill, and not a tag set somebody
   *  imported. It holds no entries (its names are the library's tags, which
   *  is what the Items list draws); what it owns is the CATEGORIES those
   *  tags are filed in. Not hideable, not deletable, not draggable, and its
   *  `entries` is the tag count rather than a row count. */
  library?: boolean;
}

/** The key the LIBRARY'S OWN set is filed under — reserved, so an imported
 *  set can never take it, and stable whether or not the row exists yet (it
 *  is lazy: a library that files nothing never grows one). What the `?`
 *  popover names its first frame by, and what tells the first pill apart. */
export const LIBRARY_SET_KEY = "library";

/** One row of the sidebar's NAMESPACES block. Derived from the names, never
 *  authored and never a row in any table — which is why it is keyed by its
 *  text and why filing a tag in a category cannot move it. */
export interface NamespaceRow {
  name: string;
  count: number;
  /** Kept out of the autocomplete by the prefix setting. Library only; a
   *  set's rows never claim to know. */
  hidden: boolean;
}

export interface TagSetCategoryOut {
  id: number;
  parent_id: number | null;
  name: string;
  /** The tree row's glyph, a Material Symbols name; "" is the folder. */
  icon: string;
  /** Kept out of the autocomplete, with everything under it and every name
   *  in that subtree — a name the library already HAS is unaffected. The
   *  Sets tab shows and edits it as ever; the browse tree never carries it. */
  hidden: boolean;
  /** THREE-STATE for this branch: true offers / mints, false does not, and
   *  null takes the parent's answer (the set's own flag at the root). */
  aliases: boolean | null;
  implications: boolean | null;
  position: number;
  /** The names down to this category, outermost first — never a joined
   *  path, since a name may itself hold a `/`. Drawn with chevrons. */
  trail: string[];
  /** DIRECT entries in it — what clicking it in the tree lists. */
  count: number;
}

export interface TagSetDetail extends TagSetOut {
  /** How many entries are a subject / a place / an event — the sidebar's
   *  three rows, drawn only for the kinds this set has any of. */
  record_counts: Record<string, number>;
  category_rows: TagSetCategoryOut[];
  /** Entries in no category. */
  uncategorized: number;
}

/** One META TAG of a tag set — a label it puts on its own names.
 *
 *  The set's answer to `/api/link-tags/rows`: the same namespace shape, one
 *  tag set along. `uses` counts the SET's entries that carry it, which is
 *  the only count a set can honestly give — what the LIBRARY does with a
 *  label of that name is the library's own row. */
export interface TagSetMetaTagOut {
  id: number;
  name: string;
  comment: string;
  description: string;
  uses: number;
}

/** One crop the "might be the same person" strip offers. */
export interface SimilarFaceRow {
  /** The COVER — the biggest crop of the offer. */
  face: FaceRow;
  /** Every crop of the offer, cover first: one for a face, the whole
   *  cluster where an unanswered cluster is offered as one (owner 2026-09). */
  faces: FaceRow[];
  count: number;
  /** How alike, on the *Minimum face similarity* setting's own scale. */
  score: number;
  /** Whoever it is on now — empty where nobody has said. */
  subject_id?: number | null;
  name: string;
  unnamed: boolean;
}

/** One entry of a set, as `GET /api/tag-sets/{id}/entries` lists them. */
export interface TagSetEntryOut {
  id: number;
  name: string;
  description: string;
  count: number | null;
  category_id: number | null;
  /** Where the set files this entry: the names down to its category,
   *  outermost first, empty for an uncategorized one. */
  category_trail: string[];
  position: number;
  /** THE NAME THIS ROW SPELLS, where the row is an ALIAS — an alias is a
   *  row of the list, exactly as it is in the library's own, with its own
   *  checkbox and its own selection. Null on an ordinary entry. */
  alias_of: string | null;
  /** The OTHER SPELLINGS of this entry. The row does not draw them (they
   *  are rows of their own); the editor and the file hold them as a list. */
  aliases: string[];
  /** The tags this entry ENTAILS, by name — minted and linked as ordinary
   *  library implications the first time the name is assigned. */
  implies: string[];
  /** The META TAGS the set says this name carries — labels about the NAME
   *  ("character", "noflip"), never about a picture. Put on the library's
   *  tag when the door creates it, like `implies`. */
  meta: string[];
  /** Those of `implies` the LIBRARY does not entail. A set's implications
   *  reach the library only when the door CREATES the tag, so a tag that was
   *  already there, or an entry edited after its tag went into use, says
   *  something nothing has acted on — the row strikes these through, and the
   *  ⋯ menu offers to sync them. Empty for a name the library does not have,
   *  which is not behind but unassigned. */
  missing_implies: string[];
  /** The implications are switched off for this entry — its category, one
   *  above it, or the whole set. They mint nothing, so the row leaves them
   *  out; the editor still shows them. */
  implications_off: boolean;
  /** The LIBRARY has this tag (or an alias resolving to it). A row that
   *  does not offers to ADD it rather than to do anything about its
   *  implications: until the tag exists there is nothing for a set's
   *  advice to be about. */
  in_library: boolean;
  /** HOW MANY PICTURES THE LIBRARY HAS under this name — the `Library`
   *  column. Null where the library does not have the name at all, which is
   *  not the same as 0: zero is a tag that exists and is on nothing. An
   *  alias answers with its target's count, as a row does everywhere else. */
  library_count?: number | null;
  /** WHAT THE SET SAYS THE TAG IS. `description` above is the set's own
   *  words about the name and stays in the set; these are advice about the
   *  library's own tag, written at the door and by the sync verb. A record
   *  present but EMPTY says the kind and nothing more. */
  comment: string;
  subject: TagSetSubject | null;
  place: TagSetPlace | null;
  event: TagSetEvent | null;
  /** Which of `comment` / `subject` / `place` / `event` the library's tag
   *  does NOT have — `missing_implies` for the other kind of advice, and
   *  empty for a name the library has never heard of. */
  missing_records: string[];
}

/** This name is somebody. Every field optional: an empty record still says
 *  "a person", which is the whole of what a tag set often knows. */
/** What a sync did. `tags` counts the ones it spoke for; a name the library
 *  does not have, or that no enabled set says anything about, is `skipped`. */
export interface TagSetSyncOut {
  tags: number;
  added: number;
  removed: number;
  skipped: number;
}

/** How a page of a set's entries is narrowed and sorted. Named rather than
 *  inline, because `tagSetEntryIndex` answers about the SAME list and has to
 *  be asked in the same terms. */
export interface TagSetEntriesOpts {
  q?: string;
  category_id?: number | null;
  /** SEVERAL categories — their union, each expanded by `subtree` like the
   *  single one. What the Sets tab asks for when several rows of its tree
   *  are picked. */
  category_ids?: number[];
  uncategorized?: boolean;
  limit?: number;
  offset?: number;
  /** With a category: its own entries AND its sub-categories'. */
  subtree?: boolean;
  /** Only entries carrying one. Both at once means BOTH. */
  has_aliases?: boolean;
  has_implies?: boolean;
  /** With a description, without one, or (undefined) either. */
  described?: boolean;
  /** Inclusive bounds on the set's own popularity count; omit for none. An
   *  entry with NO count is out of any bounded range — "how popular is
   *  this" has no answer there. */
  count_min?: number | null;
  count_max?: number | null;
  /** The derived half beside the categories: the text before the first
   *  colon. A namespace reads as a category holding the names made with
   *  it — several are a union, and one picked beside a real category lists
   *  the entries in either. Empty is no narrowing. */
  namespaces?: string[];
  /** Only the entries the LIBRARY has not caught up with: it has the tag,
   *  and the tag does not entail what the entry says it does. Costs the
   *  candidates rather than the set, and the server caches the answer for
   *  as long as the library has not moved. */
  behind?: boolean;
  /** Only the entries whose COMMENT or RECORD the library lacks — the other
   *  kind of advice, and with `behind` the union of the two: "anything the
   *  library has not caught up with". */
  behind_records?: boolean;
  /** Only the entries that ARE one of these — `subject` / `place` /
   *  `event`. Several is the UNION: "subjects and places" is one list of
   *  the entries that are either, not the empty list of both. */
  records?: string[];
  /** The file's order (`position`, the default), the name, the count or the
   *  category; the name breaks every tie. */
  sort?: "position" | "name" | "count" | "category";
  desc?: boolean;
}

export interface TagSetBulkRowIn {
  name: string;
  description?: string | null;
  count?: number | null;
  /** The trail of names down to the category, MADE where it does not
   *  exist. A list, not a path: one of those names may hold a `/`. */
  category?: string[] | null;
  aliases?: string[];
  implies?: string[];
}

export interface TagSetBulkOut {
  created: number;
  updated: number;
  errors: { name?: string; error?: string }[];
}

export interface TagSetEntriesOut {
  rows: TagSetEntryOut[];
  total: number;
}

/** A category as the BROWSE tree carries it: with its direct entry count. */
export interface TagSetTreeCategory extends TagSetCategoryOut {
  entries: number;
}

/** One ENABLED set in `GET /api/tag-sets/tree` — what an empty, focused
 *  tag field browses. Flat category rows (`parent_id`), a count per node. */
export interface TagSetTreeSet {
  id: number;
  key: string;
  name: string;
  categories: TagSetTreeCategory[];
  uncategorized: number;
  entries: number;
}

export interface TagSetImportOut {
  set: TagSetOut;
  created: number;
  updated: number;
  errors: { name: string; error: string }[];
}

export const api = {
  ...sharedApi,
  group: (id: number) => req<GroupDetail>(`/api/groups/${id}`),
  updateGroup: (id: number, body: { name?: string; icon?: string;
                                    color?: string;
                                    smart_query?: string }) =>
    req<{ ok: boolean }>(`/api/groups/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  moveGroup: (id: number, new_parent_id: number | null) =>
    req<{ ok: boolean }>(`/api/groups/${id}/move`, {
      method: "POST",
      body: JSON.stringify({ new_parent_id }),
    }),
  /** Empty `sources` into `dest` and delete them. The destination is the
   *  path id — the row the context menu was opened on. */
  mergeGroups: (dest: number, sources: number[]) =>
    req<{ ok: boolean; moved: number; emptied: number }>(
      `/api/groups/${dest}/merge`,
      { method: "POST", body: JSON.stringify({ source_ids: sources }) }),
  duplicateGroup: (id: number, new_parent_id: number | null) =>
    req<{ ok: boolean; id: number }>(`/api/groups/${id}/duplicate`, {
      method: "POST",
      body: JSON.stringify({ new_parent_id }),
    }),
  /** `keepChildren` promotes the direct subgroups to this group's own parent
   *  instead of taking the subtree with it — two verbs, and the menu names
   *  both (see `ops/groups.delete_group`). */
  deleteGroup: (id: number, assignTags = false, keepChildren = false) => {
    const q = [assignTags ? "assign_tags=true" : "",
               keepChildren ? "keep_children=true" : ""].filter(Boolean).join("&");
    return req<{ ok: boolean }>(
      `/api/groups/${id}${q ? `?${q}` : ""}`, { method: "DELETE" });
  },
  /** Many (item, group) membership changes in ONE request. The server logs
   *  the same per-item events the single endpoints do (History and revert
   *  behave identically); `added`/`removed` count CHANGES, not requests. */
  bulkGroupMembership: (item_ids: number[], add: number[], remove: number[]) =>
    req<{ ok: boolean; added: number; removed: number;
          /** The events written — what a caller with its OWN undo needs. */
          event_ids?: number[] }>(
      "/api/groups/bulk-membership", {
        method: "POST",
        body: JSON.stringify({ item_ids, add, remove }),
      }),
  /** Add a whole VIEW to a group: "a group from the current items" can mean
   *  the entire library, so the scope travels and the server resolves it —
   *  the same body `itemsQuery` sends, with the same `groups` flattening
   *  (see `quickAssignView`). */
  assignGroupView: (groupId: number, body: ItemSearchBody) =>
    req<{ ok: boolean; added: number; count: number }>(
      `/api/groups/${groupId}/assign-view`, {
        method: "POST",
        body: JSON.stringify({ ...body, groups: (body.groups ?? []).join(",") }),
      }),
  /** Add every item in the view to (and/or remove it from) groups — the
   *  sidebar's whole-view membership action. `count` is memberships changed,
   *  `total` the items the view holds. */
  viewGroupMembership: (scope: ItemSearchBody, add: number[], remove: number[]) =>
    req<{ count: number; total: number }>("/api/items/view/groups", {
      method: "POST",
      body: JSON.stringify({
        ...scope, groups: (scope.groups ?? []).join(","), add, remove }),
    }),

  /** Hide — or show again — every item in the view. `count` is what actually
   *  changed, which is routinely fewer than `total`. */
  viewHide: (scope: ItemSearchBody, hidden: boolean) =>
    req<{ count: number; total: number }>("/api/items/view/hide", {
      method: "POST",
      body: JSON.stringify({
        // `hide`, not `hidden` — the search body's `hidden` is the SCOPE
        // (the Hidden view). Same collision as `task_kind` above.
        ...scope, groups: (scope.groups ?? []).join(","), hide: hidden }),
    }),

  /** Move every item in the view to the Trash. Reversible, which is what
   *  makes it offerable over a scope nobody has enumerated. */
  viewTrash: (scope: ItemSearchBody) =>
    req<{ count: number; total: number }>("/api/items/view/trash", {
      method: "POST",
      body: JSON.stringify({ ...scope, groups: (scope.groups ?? []).join(",") }),
    }),

  assignGroupTag: (groupId: number, tag: string, negative: boolean) =>
    req(`/api/tags/assign/group/${groupId}`, {
      method: "POST",
      body: JSON.stringify({ tag, negative }),
    }),
  unassignGroupTag: (groupId: number, name: string) =>
    req(`/api/tags/assign/group/${groupId}/${encodeURIComponent(name)}`, {
      method: "DELETE",
    }),
  // Item count + numeric bounds for a scope (used for sidebar Trash/Ungrouped
  // counts). Filtering conditions go through itemsQuery, not here.
  itemFacets: (q: { groups?: number[]; ungrouped?: boolean; untagged?: boolean; trash?: boolean; hidden?: boolean; kind?: string; sequence?: number | null }) => {
    const p = new URLSearchParams();
    if (q.groups?.length) p.set("groups", q.groups.join(","));
    if (q.ungrouped) p.set("ungrouped", "true");
    if (q.untagged) p.set("untagged", "true");
    if (q.trash) p.set("trash", "true");
    if (q.hidden) p.set("hidden", "true");
    if (q.kind) p.set("kind", q.kind);
    if (q.sequence != null) p.set("sequence", String(q.sequence));
    return req<ItemFacets>(`/api/items/facets?${p.toString()}`);
  },
  // Structured search: the frontend's parsed condition tree is POSTed and
  // evaluated as-is (no query-string parsing on the backend).
  itemsQuery: (body: ItemSearchBody, signal?: AbortSignal) =>
    req<ItemPage>("/api/items/query", {
      signal,
      method: "POST",
      // The backend takes `groups` as a comma-separated string (shared with the
      // GET listing), so flatten the id list here.
      body: JSON.stringify({ ...body, groups: (body.groups ?? []).join(",") }),
    }),
  /** The IDS of one stretch of the view's order — what a SHIFT+CLICK needs
   *  when the other end has scrolled out of the loaded pages: the grid holds
   *  only what it has drawn, so the items between two positions are a
   *  question only the server can answer. `total` is how long the range
   *  really is; `ids` is capped server-side. */
  /** WHERE THESE ITEMS SIT in a view's order — one answer per id, in the
   *  order they were asked for, `null` for an item the view does not hold.
   *  What the bookmarks need: which of them this view contains, and which
   *  row to scroll the picked one to. */
  itemIndexes: (body: ItemSearchBody, itemIds: number[]) =>
    req<{ indices: (number | null)[] }>("/api/items/index", {
      method: "POST",
      body: JSON.stringify({ ...body, item_ids: itemIds,
                             groups: (body.groups ?? []).join(",") }),
    }),
  itemIdRange: (body: ItemSearchBody, start: number, count: number) =>
    req<{ ids: number[]; total: number }>("/api/items/ids", {
      method: "POST",
      body: JSON.stringify({ ...body, start, count,
                             groups: (body.groups ?? []).join(",") }),
    }),
  /** The grid's sections for one view: `(key, count)` in the page order.
   *  Same body as `itemsQuery` plus `group_by`, and the same `groups`
   *  flattening — diverging there would describe a DIFFERENT scope than the
   *  pages, silently. */
  itemGroupRuns: (body: ItemSearchBody & { group_by: string },
                  signal?: AbortSignal) =>
    req<ItemGroupRuns>("/api/items/groups", {
      signal,
      method: "POST",
      body: JSON.stringify({ ...body, groups: (body.groups ?? []).join(",") }),
    }),
  item: (id: number) => req<ItemDetail>(`/api/items/${id}`),
  /** Slim per-item details for a batch (≤500 ids, else 413) — what the grid's
   *  context menu needs without a full `ItemDetail` fetch per item. Items
   *  that do not exist are simply absent from the reply; each row's
   *  `tag_instances` carry no boxes. */
  itemDetails: (item_ids: number[]) =>
    req<{ items: ItemSlim[] }>("/api/items/details", {
      method: "POST",
      body: JSON.stringify({ item_ids }),
    }),
  itemMetadata: (id: number) => req<ItemMetadata>(`/api/items/${id}/metadata`),
  /** Promote what one of the item's FILES says onto the item, where it
   *  survives the active file changing. A file id rather than a value: the pin
   *  stores the typed row, and re-deriving a type from a string is how a
   *  numeric name quietly becomes a text one. */
  pinItemMetadata: (id: number, name: string, fileId: number) =>
    req<{ ok: boolean }>(`/api/items/${id}/metadata/pin`, {
      method: "POST",
      body: JSON.stringify({ name, file_id: fileId }),
    }),
  unpinItemMetadata: (id: number, name: string, raw: string) =>
    req<{ ok: boolean }>(`/api/items/${id}/metadata/unpin`, {
      method: "POST",
      body: JSON.stringify({ name, raw }),
    }),
  /** Stop taking one name from the item's active file — how a pin becomes an
   *  override rather than a second answer beside it. */
  muteItemMetadata: (id: number, name: string) =>
    req<{ ok: boolean }>(`/api/items/${id}/metadata/mute`, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  unmuteItemMetadata: (id: number, name: string) =>
    req<{ ok: boolean }>(`/api/items/${id}/metadata/unmute`, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  itemTracks: (id: number) => req<MediaTracks>(`/api/items/${id}/tracks`),
  updateItem: (id: number, body: { name?: string; active_file_id?: number;
                                   /** Sortable YYYYMMDDHHMMSS with zeros for
                                    *  whatever is unknown; 0 clears it. */
                                   taken_at?: number;
                                   /** The pair moves together. The two flags
                                    *  are what a pair cannot say: back to the
                                    *  file, and "there are none". */
                                   lat?: number; lon?: number;
                                   clear_coords?: boolean;
                                   no_coords?: boolean }) =>
    req<{ ok: boolean }>(`/api/items/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteItems: (item_ids: number[]) =>
    req<{ ok: boolean; count: number }>("/api/items/delete", {
      method: "POST",
      body: JSON.stringify({ item_ids }),
    }),
  trashItems: (item_ids: number[]) =>
    req<{ ok: boolean; count: number }>("/api/items/trash", {
      method: "POST",
      body: JSON.stringify({ item_ids }),
    }),
  restoreItems: (item_ids: number[]) =>
    req<{ ok: boolean; count: number }>("/api/items/restore", {
      method: "POST",
      body: JSON.stringify({ item_ids }),
    }),
  hideItems: (item_ids: number[], hidden: boolean) =>
    req<{ ok: boolean; count: number }>("/api/items/hide", {
      method: "POST",
      body: JSON.stringify({ item_ids, hidden }),
    }),
  emptyTrash: () =>
    req<{ ok: boolean; count: number }>("/api/items/empty-trash", {
      method: "POST",
    }),
  mergeItems: (source_id: number, target_id: number) =>
    req<{ ok: boolean; target_id: number }>("/api/items/merge", {
      method: "POST",
      body: JSON.stringify({ source_id, target_id }),
    }),
  deleteFile: (fileId: number) =>
    req<{ ok: boolean }>(`/api/files/${fileId}`, { method: "DELETE" }),
  // Rename / remove one of a source file's imported filenames (its info card).
  renameFileName: (fileId: number, nameId: number, name: string) =>
    req<{ ok: boolean }>(`/api/files/${fileId}/names/${nameId}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    }),
  deleteFileName: (fileId: number, nameId: number) =>
    req<{ ok: boolean }>(`/api/files/${fileId}/names/${nameId}`, {
      method: "DELETE",
    }),
  // Add a source to a file: a filename (+ path), or a web URL + access date/time.
  addFileNameSource: (
    fileId: number,
    body: { name?: string; url?: string; accessed_at?: string }
  ) =>
    req<{ ok: boolean; id: number }>(`/api/files/${fileId}/names`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteArtifact: (artifactId: number) =>
    req<{ ok: boolean }>(`/api/artifacts/${artifactId}`, { method: "DELETE" }),
  splitFile: (fileId: number) =>
    req<{ ok: boolean; item_id: number }>(`/api/files/${fileId}/split`, {
      method: "POST",
    }),
  // Several files of one item, out into ONE new item.
  splitFiles: (fileIds: number[]) =>
    req<{ ok: boolean; item_id: number }>(`/api/files/split`, {
      method: "POST",
      body: JSON.stringify({ file_ids: fileIds }),
    }),
  addItemGroup: (itemId: number, groupId: number) =>
    req<{ ok: boolean }>(`/api/items/${itemId}/groups/${groupId}`, {
      method: "POST",
    }),
  removeItemGroup: (itemId: number, groupId: number) =>
    req<{ ok: boolean }>(`/api/items/${itemId}/groups/${groupId}`, {
      method: "DELETE",
    }),
  addCaption: (itemId: number, text: string, kind: CaptionKind = "caption") =>
    req<{ id: number }>(`/api/items/${itemId}/captions`, {
      method: "POST",
      body: JSON.stringify({ text, kind }),
    }),
  /** The same text onto EVERY item named — one request, one transaction, and
   *  one ordinary add-caption entry per item, so each reverts on its own.
   *  The sidebar's multi-selection Add; at most 500 items. */
  addCaptionBulk: (itemIds: number[], text: string,
                   kind: CaptionKind = "caption") =>
    req<{ ids: number[] }>("/api/items/captions/bulk", {
      method: "POST",
      body: JSON.stringify({ item_ids: itemIds, text, kind }),
    }),
  /** An instruction's reference images, as the FULL desired order — one call
   *  covers adding, removing and reordering, and one undo puts it back. */
  setCaptionRefs: (itemId: number, captionId: number, itemIds: number[]) =>
    req<number[]>(`/api/items/${itemId}/captions/${captionId}/refs`, {
      method: "PUT",
      body: JSON.stringify({ item_ids: itemIds }),
    }),
  editCaption: (itemId: number, captionId: number, text: string) =>
    req<{ ok: boolean }>(`/api/items/${itemId}/captions/${captionId}`, {
      method: "PATCH",
      body: JSON.stringify({ text }),
    }),
  deleteCaption: (itemId: number, captionId: number) =>
    req<{ ok: boolean }>(`/api/items/${itemId}/captions/${captionId}`, {
      method: "DELETE",
    }),
  createGroup: (body: { name: string; icon?: string;
                        parent_id?: number | null; smart_query?: string }) =>
    req<GroupNode>("/api/groups", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  /** One page of the tag table. Passing `limit` opts into the
   *  `{rows, total}` envelope (`total` = the FILTERED count). */
  /** WHICH tags the Tags tab lists and in what order — ids and names only.
   *
   *  The whole catalog as ROWS is 60 MB and 4.2 s at 250,000 tags; the same
   *  answers as two parallel arrays are 6 MB and one indexed read. Everything
   *  the list's own machinery does — namespace grouping, folding, windowing,
   *  select-all — is a question about names, so this is what it works over,
   *  and `tagRows` fetches the rest for the window on screen. */
  tagIndex: (opts: { q?: string; sort?: string; dir?: string; kind?: string;
                     aliases?: boolean; implies?: boolean;
                     unassigned?: boolean; media?: string;
                     /** A ranking's MINTED rows. Listed unless told
                      *  otherwise, so `false` is the only value worth
                      *  sending — and the only `false` this builder sends,
                      *  since every other flag here means "narrow to". */
                     scores?: boolean;
                     /** Only the tags carrying this meta tag. */
                     meta?: string;
                     /** "all", or narrowed to the tags the autocomplete
                      *  does ("shown") or does not ("hidden") offer — the
                      *  tag's OWN flag, never the namespace rule. */
                     suggest?: string;
                     /** WHERE THE LIBRARY FILES IT — the sidebar's category
                      *  tree. A comma list, several being the UNION, each
                      *  taken with its subtree the way the tree's own counts
                      *  take it; `uncategorized` is the tree's last fixed row
                      *  and joins the same union. */
                     category?: string;
                     uncategorized?: boolean;
                     /** …and the DERIVED half beside it: the text before
                      *  the first colon, which reads as a category holding
                      *  the names made with it — several are a union, and
                      *  one beside a real category lists the tags in
                      *  either. Picking any FLATTENS the list where they
                      *  all share one, since a parent row over the whole
                      *  list would say nothing. */
                     namespaces?: string[];
                     /** Inclusive bounds on a count column; omit for none. */
                     pos_min?: number; pos_max?: number;
                     ind_min?: number; ind_max?: number;
                     neg_min?: number; neg_max?: number;
                     /** HOW MANY LEADING ROWS TO CARRY WHOLE, so the first
                      *  screenful needs no second request — see
                      *  `TagIndex.rows`. */
                     rows?: number } = {}) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(opts)) {
      if (v === undefined || v === "") continue;
      if (v === false && k !== "scores") continue;
      // REPEATED, not joined: the picked namespaces are a list on the wire
      // the way `record` is, and `String(["a","b"])` would have sent one
      // parameter reading "a,b".
      if (Array.isArray(v)) {
        for (const one of v) p.append(k === "namespaces" ? "namespace" : k,
                                      String(one));
        continue;
      }
      p.set(k, String(v));
    }
    const qs = p.toString();
    return req<TagIndex>(`/api/tags/index${qs ? "?" + qs : ""}`);
  },
  /** Keep these tags out of the AUTOCOMPLETE, or put them back. Returns the
   *  names that MOVED. Not a deletion and not a scope: the tags assign,
   *  search, count and are listed exactly as before. */
  setTagsHidden: (names: string[], hidden = true) =>
    req<string[]>("/api/tags/hidden",
                  { method: "POST", body: JSON.stringify({ names, hidden }) }),
  /** The namespaces the autocomplete does not offer. */
  hiddenNamespaces: () => req<string[]>("/api/tags/hidden-namespaces"),
  /** The WHOLE list — a namespace has no row, so the list is the state. */
  setHiddenNamespaces: (namespaces: string[]) =>
    req<string[]>("/api/tags/hidden-namespaces",
                  { method: "PUT", body: JSON.stringify({ namespaces }) }),
  /** THE LIBRARY'S OWN TAG SET as a tag-set file. Its own route, not
   *  `/api/tag-sets/{id}/export`: the library's set row is lazy, so there
   *  need not be an id to export by, and what is exported is the tags
   *  either way. */
  exportLibrary: () => req<Record<string, unknown>>("/api/tags/export"),
  /** The library's NAMESPACES — the sidebar's derived half. Only those two
   *  or more names share, the rule the inline parent rows follow: a heading
   *  over one thing says nothing. `hidden` is the prefix SETTING, which is
   *  why the row can undo it and a tag row cannot. */
  tagNamespaces: () => req<NamespaceRow[]>("/api/tags/namespaces"),
  /** The same for an imported set, over its own entry names. */
  tagSetNamespaces: (id: number) =>
    req<NamespaceRow[]>(`/api/tag-sets/${id}/namespaces`),
  /** File these names in a category of their own tag set, or take them
   *  out of one (`categoryId` null is "Uncategorized"). `setId` null is the
   *  library's own tags, an id is that imported set's entries. A LIST
   *  because the gesture is a drag of a selection — ONE request either way;
   *  returns the ids that MOVED. */
  setTagCategory: (tagIds: number[], categoryId: number | null,
                   setId: number | null = null) =>
    req<number[]>("/api/tags/category",
                  { method: "POST",
                    body: JSON.stringify({ tag_ids: tagIds,
                                           category_id: categoryId,
                                           ...(setId == null ? {}
                                               : { set_id: setId }) }) }),
  /** The library's FIRST category — and the set row behind it, which is lazy
   *  and so has no id to post to yet. Every later verb on a category (edit,
   *  move, delete) goes through the ordinary `/api/tag-sets/{set_id}/…`
   *  routes with the `set_id` this hands back. */
  createLibraryCategory: (body: { name: string; parent_id?: number | null;
                                  icon?: string; hidden?: boolean }) =>
    req<{ set_id: number; id: number; name: string;
          parent_id: number | null; icon: string; hidden: boolean;
          position: number }>(
      "/api/tags/categories", { method: "POST", body: JSON.stringify(body) }),
  /** The full rows for one window, in the order asked for. */
  tagRows: (ids: number[], setId: number | null = null) =>
    req<TagRow[]>("/api/tags/rows",
                  { method: "POST",
                    body: JSON.stringify({ ids,
                                           ...(setId == null ? {}
                                               : { set_id: setId }) }) }),
  /** The representative items of the tags named — the Tags list's strips.
   *  A read that tops the short tags up on the way. */
  tagRepresentatives: (ids: number[]) =>
    req<{ reps: Record<string, RankingItemRef[]> }>(
      `/api/tags/representatives?ids=${ids.join(",")}`),
  /** "Not representative": the item is refused for the tag and another is
   *  picked; answers the tag's strip as it now is. */
  refuseRepresentative: (tagId: number, itemId: number) =>
    req<{ reps: RankingItemRef[] }>(
      `/api/tags/${tagId}/representatives/${itemId}`, { method: "DELETE" }),
  tagsPage: (opts: { q?: string; sort?: "name" | "positive";
                     dir?: "asc" | "desc"; limit: number; offset?: number }) => {
    const p = new URLSearchParams();
    if (opts.q) p.set("q", opts.q);
    if (opts.sort) p.set("sort", opts.sort);
    if (opts.dir) p.set("dir", opts.dir);
    p.set("limit", String(opts.limit));
    if (opts.offset) p.set("offset", String(opts.offset));
    return req<Paged<TagRow>>(`/api/tags?${p.toString()}`);
  },
  createTag: (body: { name: string; comment?: string; alias_of?: string }) =>
    req<TagRow>("/api/tags", { method: "POST", body: JSON.stringify(body) }),
  /** The CSV import's batch: create-or-update per row, one transaction per
   *  request, the dialog's keep rule applied server-side. */
  bulkUpsertTags: (body: {
    rows: { name: string; comment?: string;
            /** The file's count — stored on the `count_meta` assignment when
             *  the batch names one, else only the minimum's input. */
            count?: number;
            /** Meta tags THIS row's tag carries (the assignments file). */
            meta_tags?: string[];
            /** Per-meta counts this row says outright (the assignments
             *  file's own count column). Assigning rides along. */
            meta_counts?: Record<string, number> }[];
    /** What a tag the library ALREADY has keeps: `keep` fills the gaps only,
     *  `update` takes the file's value for every column it maps, `replace`
     *  makes the tag match the file — a field the row does not carry is
     *  cleared. */
    existing?: "keep" | "update" | "replace";
    /** "Mark every tag with" — applied to every row's tag, once per tag. */
    meta_tags?: string[];
    /** The ONE meta tag the count column lands on (a site name, usually). */
    count_meta?: string;
    /** What a row's count does to an assignment that already carries one —
     *  the whole rule, reading nothing else (`overwrite` is about the text
     *  columns). Absent means `keep`: a number already stored is left alone,
     *  a gap is filled. */
    count_mode?: "keep" | "replace" | "min" | "max";
  }) =>
    req<{ rows: { name: string; id: number | null; created: boolean;
                  error: string | null }[] }>(
      "/api/tags/bulk-upsert", { method: "POST", body: JSON.stringify(body) }),
  // "Assigning this tag also assigns that one." Both return the tag's
  // implications after the change.
  addTagImplication: (tagId: number, name: string) =>
    req<string[]>(`/api/tags/${tagId}/implies`, {
      method: "POST", body: JSON.stringify({ name }),
    }),
  removeTagImplication: (tagId: number, name: string) =>
    req<string[]>(`/api/tags/${tagId}/implies/${encodeURIComponent(name)}`,
                  { method: "DELETE" }),
  // What the TAG SET says about a tag. The meta-tag NAMESPACE lives under
  // /api/link-tags (its catalog, comments and renames); these two put one of
  // its names on one tag. Both return the tag's meta tags after the change.
  addTagMetaTag: (tagId: number, name: string, count?: number) =>
    req<string[]>(`/api/tags/${tagId}/meta-tags`, {
      method: "POST",
      body: JSON.stringify(count != null ? { name, count } : { name }),
    }),
  removeTagMetaTag: (tagId: number, name: string) =>
    req<string[]>(`/api/tags/${tagId}/meta-tags/${encodeURIComponent(name)}`,
                  { method: "DELETE" }),
  updateTag: (id: number, body: { name?: string; comment?: string;
                                  description?: string;
                                  alias_of?: string }) =>
    req<{ ok: boolean }>(`/api/tags/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  /** Fold a tag into another one by name: every assignment, implication and
   *  group tag moves across and the tag is deleted (its name kept as an alias
   *  unless told otherwise). Returns the events it logged, so the caller can
   *  offer an Undo. */
  mergeTag: (id: number, into: string, keepAlias = true) =>
    req<{ ok: boolean; event_ids: number[] }>(`/api/tags/${id}/merge`, {
      method: "POST",
      body: JSON.stringify({ into, keep_alias: keepAlias }),
    }),
  // Returns the history events the deletion logged — one removal per item the
  // tag was on, plus the tag itself — so the caller can offer an Undo that
  // reverts exactly this deletion.
  deleteTag: (id: number) =>
    req<{ ok: boolean; event_ids: number[] }>(`/api/tags/${id}`, { method: "DELETE" }),
  /** Delete a whole selection in one transaction. One request per tag made a
   *  32k-row Delete run invisibly for the better part of an hour; the events
   *  returned are the single delete's exactly, so the Undo covers the lot. */
  bulkDeleteTags: (tag_ids: number[]) =>
    req<{ ok: boolean; event_ids: number[] }>("/api/tags/bulk-delete", {
      method: "POST", body: JSON.stringify({ tag_ids }),
    }),
  /** The same stamp aimed at a WHOLE VIEW rather than a list of ids: quick
   *  tagging with nothing selected means "everything the grid is showing",
   *  and that can be the entire library. The scope travels and the server
   *  resolves it — the same body `itemsQuery` sends, with the same `groups`
   *  flattening, because diverging there would stamp a different set from
   *  the one on screen. */
  quickAssignView: (body: ItemSearchBody & {
    positive: string[];
    negative: string[];
    assign_groups?: number[];
    remove: boolean;
  }) =>
    req<{ ok: boolean; count: number }>("/api/tags/quick-assign/view", {
      method: "POST",
      body: JSON.stringify({ ...body, groups: (body.groups ?? []).join(",") }),
    }),
  quickAssign: (body: {
    item_ids: number[];
    positive: string[];
    negative: string[];
    /** Group memberships stamped (or removed) beside the tags. */
    assign_groups?: number[];
    remove: boolean;
  }) =>
    req<{ ok: boolean; count: number }>("/api/tags/quick-assign", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  assignItemTag: (itemId: number, tag: string, negative: boolean) =>
    // The reply's `event_ids` are the ANSWER'S whole fan (the add_tag plus
    // whatever resolving a pending suggestion wrote) — what the tag-batch
    // overlay's undo reverts together. Existing callers read `ok` alone.
    req<{ ok: boolean; event_id: number | null; event_ids: number[] }>(
      `/api/tags/assign/item/${itemId}`, {
      method: "POST",
      body: JSON.stringify({ tag, negative }),
    }),
  unassignItemTag: (itemId: number, name: string) =>
    // `event_ids` is the removal's fan, the assign reply's rule — a session
    // correcting an existing tag reverts the correction as one step.
    req<{ ok: boolean; event_ids?: number[] }>(
      `/api/tags/assign/item/${itemId}/${encodeURIComponent(name)}`, {
      method: "DELETE",
    }),
  importFiles: (
    files: File[],
    opts: {
      parent_group_id: number | null;
      /** A group of this run's own, INSIDE `parent_group_id`; an empty name
       *  means the backend's own default (a timestamp). */
      new_group?: boolean;
      new_group_name?: string;
      folders_as_groups: boolean;
      archives_as_groups?: boolean;
      archive_sequences?: boolean;
      /** Which half of a SEQUENCE joins the run's groups: both | container |
       *  members. */
      sequence_grouping?: string;
      /** The run's minimums — 0/absent is "not set", and a file must clear
       *  every one that IS set. A sequence is kept whole: it comes in when
       *  any of its pages clears them. */
      min_megapixels?: number;
      min_short_edge?: number;
      min_long_edge?: number;
      /** The run's aspect RANGE, width/height: ignore anything narrower than
       *  `min_aspect` or wider than `max_aspect`. 0/absent is "not set" on
       *  each side, so one end may be given without the other. */
      min_aspect?: number;
      max_aspect?: number;
      /** File types to leave alone: "image" | "video" | "sequence" (a PDF,
       *  an animated GIF or a comic) | "archive" (a zip that scatters). */
      ignore_kinds?: string[];
      /** Model key to detect faces with on what was imported; "" = don't. */
      detect_faces?: string;
      /** Embedder ids to index what was imported with, comma-separated
       *  (`ignore_kinds`' spelling for a form field); "" = don't. Each one
       *  is a run of its own — the spaces never mix. */
      index_embeddings?: string;
      /** Tags put on everything the run creates, plus per-kind lists. */
      tags?: string[];
      tagsExisting?: boolean;
      tags_image?: string[];
      tags_video?: string[];
      tags_sequence?: string[];
      onUploadProgress?: (pct: number) => void;
      signal?: AbortSignal;
    }
  ) => {
    const fd = new FormData();
    for (const f of files) {
      // Preserve folder structure when a directory was picked.
      const rel = (f as File & { webkitRelativePath?: string })
        .webkitRelativePath;
      fd.append("files", f, rel || f.name);
    }
    if (opts.parent_group_id != null)
      fd.append("parent_group_id", String(opts.parent_group_id));
    fd.append("new_group", String(opts.new_group ?? false));
    fd.append("new_group_name", opts.new_group_name ?? "");
    fd.append("folders_as_groups", String(opts.folders_as_groups));
    fd.append("archives_as_groups", String(opts.archives_as_groups ?? false));
    fd.append("archive_sequences", String(opts.archive_sequences ?? false));
    fd.append("sequence_grouping", opts.sequence_grouping ?? "both");
    fd.append("min_megapixels", String(opts.min_megapixels ?? 0));
    fd.append("min_short_edge", String(opts.min_short_edge ?? 0));
    fd.append("min_long_edge", String(opts.min_long_edge ?? 0));
    fd.append("min_aspect", String(opts.min_aspect ?? 0));
    fd.append("max_aspect", String(opts.max_aspect ?? 0));
    fd.append("ignore_kinds", (opts.ignore_kinds ?? []).join(","));
    fd.append("detect_faces", opts.detect_faces ?? "");
    fd.append("index_embeddings", opts.index_embeddings ?? "");
    fd.append("tags_existing", String(opts.tagsExisting ?? true));
    fd.append("tags", (opts.tags ?? []).join(","));
    fd.append("tags_image", (opts.tags_image ?? []).join(","));
    fd.append("tags_video", (opts.tags_video ?? []).join(","));
    fd.append("tags_sequence", (opts.tags_sequence ?? []).join(","));
    // XHR (not fetch) so we can surface real upload progress for big folders.
    return new Promise<ImportJob>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/import");
      if (opts.signal) {
        if (opts.signal.aborted) {
          reject(new DOMException("aborted", "AbortError"));
          return;
        }
        opts.signal.addEventListener("abort", () => xhr.abort(), { once: true });
      }
      xhr.onabort = () => reject(new DOMException("aborted", "AbortError"));
      xhr.upload.onprogress = (e) => {
        if (opts.onUploadProgress && e.lengthComputable)
          opts.onUploadProgress(e.loaded / e.total);
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText) as ImportJob);
          } catch {
            reject(new Error("bad server response"));
          }
        } else {
          reject(new Error(`${xhr.status}: ${xhr.responseText}`));
        }
      };
      xhr.onerror = () => reject(new Error("network error during upload"));
      xhr.send(fd);
    });
  },
  importJob: (id: string) => req<ImportJob>(`/api/import/${id}`),
  /** Every import THIS SERVER knows about — which is not the set this page
   *  knows about. A reload throws the browser's own task away (it holds the
   *  files), so this is what is left of a run nobody is watching any more. */
  importJobs: () =>
    req<{ jobs: (ImportJob & { label: string; started: number })[] }>(
      "/api/import/jobs"),
  clearImportJob: (id: string) =>
    req<{ ok: boolean }>(`/api/import/jobs/${id}/clear`, { method: "POST" }),
  edit: (itemId: number, body: EditRequest) =>
    req<{ item_id: number; file_id: number; mode: string }>(
      `/api/items/${itemId}/edit`,
      { method: "POST", body: JSON.stringify(body) }
    ),
  editRaster: async (
    itemId: number,
    blob: Blob,
    opts: {
      source_file_id: number;
      save_mode: "overwrite" | "derived";
      // The saved buffer's region within the source file (for tag-box alignment).
      crop?: { x: number; y: number; w: number; h: number } | null;
    }
  ) => {
    const fd = new FormData();
    fd.append("image", blob, "edit.png");
    fd.append("source_file_id", String(opts.source_file_id));
    fd.append("save_mode", opts.save_mode);
    if (opts.crop) {
      fd.append("crop_x", String(opts.crop.x));
      fd.append("crop_y", String(opts.crop.y));
      fd.append("crop_w", String(opts.crop.w));
      fd.append("crop_h", String(opts.crop.h));
    }
    const r = await apiFetch(`/api/items/${itemId}/edit-raster`, {
      method: "POST",
      body: fd,
    });
    if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
    return r.json() as Promise<{ item_id: number; file_id: number; mode: string }>;
  },
  // Create a new item from a client-rendered crop, linked back to the original
  // with the crop region (in the source file's frame) as a bounding box. Pass a
  // null box for a rotated crop (which can't be expressed as an axis box).
  cropToItem: async (
    itemId: number,
    blob: Blob,
    opts: {
      source_file_id: number;
      box?: { x: number; y: number; w: number; h: number } | null;
    }
  ) => {
    const fd = new FormData();
    fd.append("image", blob, "crop.png");
    fd.append("source_file_id", String(opts.source_file_id));
    if (opts.box) {
      fd.append("box_x", String(opts.box.x));
      fd.append("box_y", String(opts.box.y));
      fd.append("box_w", String(opts.box.w));
      fd.append("box_h", String(opts.box.h));
    }
    const r = await apiFetch(`/api/items/${itemId}/crop-to-item`, {
      method: "POST",
      body: fd,
    });
    if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
    return r.json() as Promise<{ item_id: number; file_id: number }>;
  },
  // LaMa-inpaint the masked region of an image (the editor's inpaint tool). The
  // mask marks the region to fill (opaque = fill); returns the inpainted PNG.
  inpaint: async (image: Blob, mask: Blob, model = "big_lama"): Promise<Blob> => {
    const fd = new FormData();
    fd.append("image", image, "image.png");
    fd.append("mask", mask, "mask.png");
    fd.append("model", model);
    const r = await apiFetch("/api/ml/inpaint", { method: "POST", body: fd });
    if (!r.ok) {
      let msg = `${r.status}`;
      try { msg = (await r.json()).detail ?? msg; } catch { /* non-JSON */ }
      throw new Error(msg);
    }
    return r.blob();
  },
  // ---- sequences ----
  sequences: () => req<SequenceSummary[]>("/api/sequences"),
  /** One page of the sequences list (`q` matches the name). */
  sequencesPage: (opts: { q?: string; limit: number; offset?: number }) =>
    req<Paged<SequenceSummary>>(`/api/sequences?${pageParams(opts)}`),
  sequence: (seqId: number) => req<SequenceInfo>(`/api/sequences/${seqId}`),
  removeSequence: (seqId: number) =>
    req<{ ok: boolean }>(`/api/sequences/${seqId}`, { method: "DELETE" }),
  itemSequences: (itemId: number) =>
    req<SequenceInfo[]>(`/api/items/${itemId}/sequences`),
  createSequence: (name: string, item_ids: number[]) =>
    req<{ ok: boolean; id: number }>("/api/sequences", {
      method: "POST",
      body: JSON.stringify({ name, item_ids }),
    }),
  renameSequence: (seqId: number, name: string) =>
    req<{ ok: boolean }>(`/api/sequences/${seqId}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    }),
  /** The full desired order as MEMBERSHIP-row ids — the only tag set
   *  that can say which copy of a repeated item goes where. */
  reorderSequence: (seqId: number, member_ids: number[]) =>
    req<{ ok: boolean }>(`/api/sequences/${seqId}/reorder`, {
      method: "POST",
      body: JSON.stringify({ member_ids }),
    }),
  /** Remove ONE occurrence each (membership rows) — a row's own ✕. */
  removeSequenceMembers: (seqId: number, member_ids: number[]) =>
    req<{ ok: boolean; count: number }>(`/api/sequences/${seqId}/remove`, {
      method: "POST",
      body: JSON.stringify({ member_ids }),
    }),
  /** Remove EVERY occurrence of each item — "take this picture out". */
  removeFromSequence: (seqId: number, item_ids: number[]) =>
    req<{ ok: boolean; count: number }>(`/api/sequences/${seqId}/remove`, {
      method: "POST",
      body: JSON.stringify({ item_ids }),
    }),
  setMainSequence: (itemId: number, sequence_id: number | null) =>
    req<{ ok: boolean }>(`/api/items/${itemId}/main-sequence`, {
      method: "PATCH",
      body: JSON.stringify({ sequence_id }),
    }),
  // ---- relationships ----
  itemRelationships: (itemId: number) =>
    req<RelationshipOut[]>(`/api/items/${itemId}/relationships`),
  addRelationship: (
    from_item_id: number,
    to_item_id: number,
    kind = "manual",
    meta: Record<string, number | string> = {}
  ) =>
    req<RelationshipOut>("/api/relationships", {
      method: "POST",
      body: JSON.stringify({ from_item_id, to_item_id, kind, meta }),
    }),
  deleteRelationship: (id: number) =>
    req<{ ok: boolean }>(`/api/relationships/${id}`, { method: "DELETE" }),
  flipRelationship: (id: number) =>
    req<RelationshipOut>(`/api/relationships/${id}/flip`, { method: "POST" }),
  // ---- meta tags (free-form labels on a relationship or a caption) ----
  // The route keeps its historical /api/link-tags path.
  /** Say a per-item tag group is about a subject (her tags / his tags). */
  addTagGroupSubject: (groupId: number, subjectId: number) =>
    req<number[]>(`/api/tags/groups/${groupId}/subjects`, {
      method: "POST", body: JSON.stringify({ subject_id: subjectId }),
    }),
  removeTagGroupSubject: (groupId: number, subjectId: number) =>
    req<number[]>(`/api/tags/groups/${groupId}/subjects/${subjectId}`,
      { method: "DELETE" }),

  /** One page of the places list (`q` matches the name or the tag). */
  placesPage: (opts: { q?: string; limit: number; offset?: number }) =>
    req<Paged<PlaceRow>>(`/api/places?${pageParams(opts)}`),
  createPlace: (body: { tag?: string; name?: string;
                        comment?: string;
                        parent_id?: number | null;
                        lat?: number | null; lon?: number | null }) =>
    req<PlaceRow[]>("/api/places", { method: "POST", body: JSON.stringify(body) }),
  updatePlace: (id: number, body: { tag?: string; name?: string;
                                    comment?: string;
                                    parent_id?: number | null;
                                    clear_parent?: boolean;
                                    lat?: number | null; lon?: number | null }) =>
    req<PlaceRow[]>(`/api/places/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deletePlace: (id: number, withTag = false) =>
    req<PlaceRow[]>(`/api/places/${id}?with_tag=${withTag}`, { method: "DELETE" }),

  createEvent: (body: { tag?: string; display_name?: string; comment?: string;
                        parent_id?: number | null;
                        start_date?: number | null; end_date?: number | null;
                        place_ids?: number[] }) =>
    req<EventRow[]>("/api/events", { method: "POST", body: JSON.stringify(body) }),
  updateEvent: (id: number, body: { tag?: string; display_name?: string;
                                    comment?: string;
                                    parent_id?: number | null;
                                    clear_parent?: boolean;
                                    start_date?: number | null;
                                    end_date?: number | null;
                                    place_ids?: number[] }) =>
    req<EventRow[]>(`/api/events/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteEvent: (id: number, withTag = false) =>
    req<EventRow[]>(`/api/events/${id}?with_tag=${withTag}`, { method: "DELETE" }),
  /** What this picture's events imply, and what its own date suggests —
   *  computed on read, never stored. Only the refusals below persist. */
  itemSuggestions: (itemId: number) =>
    req<ItemSuggestions>(`/api/events/suggestions/${itemId}`),
  dismissSuggestedPlace: (itemId: number, locationId: number,
                          viaOccasionId?: number | null) =>
    req<ItemSuggestions>("/api/events/dismiss-place", {
      method: "POST",
      body: JSON.stringify({ item_id: itemId, location_id: locationId,
                             via_occasion_id: viaOccasionId ?? null }),
    }),
  dismissSuggestedEvent: (itemId: number, occasionId: number) =>
    req<ItemSuggestions>("/api/events/dismiss-event", {
      method: "POST",
      body: JSON.stringify({ item_id: itemId, occasion_id: occasionId }),
    }),
  adoptFilePlace: (itemId: number) =>
    req<ItemSuggestions>("/api/events/adopt-file-place", {
      method: "POST", body: JSON.stringify({ item_id: itemId }),
    }),
  dismissFilePlace: (itemId: number) =>
    req<ItemSuggestions>("/api/events/dismiss-file-place", {
      method: "POST", body: JSON.stringify({ item_id: itemId }),
    }),

  // ---- faces ----
  faces: (itemId: number) => req<FaceRow[]>(`/api/faces/item/${itemId}`),
  subjectFaces: (subjectId: number) =>
    req<FaceRow[]>(`/api/faces/subject/${subjectId}`),
  unnamedFaces: (limit = 40) =>
    req<FaceCluster[]>(`/api/faces/unnamed?limit=${limit}`),
  /** Every named face, one cluster per subject — the other end of the same
   *  view. `per` caps each cluster to what a strip actually draws; the drawer
   *  asks `subjectFaces` for the whole set of the one it opens. */
  /** Paging is opt-in: pass `offset` (0 counts) and the same shape gains
   *  `total` — how many listed subjects (clusters) exist. */
  namedFaces: (limit = 200, per = 0, offset?: number) =>
    req<NamedFaces & { total?: number }>(
      `/api/faces/named?limit=${limit}&per=${per}`
      + (offset != null ? `&offset=${offset}` : "")),
  /** Say who a face is — ADDING a claim, since one face may be two people. */
  nameFace: (id: number, body: { subject_id?: number | null;
                                 display_name?: string; comment?: string }) =>
    req<FaceRow[]>(`/api/faces/${id}/subject`, {
      method: "POST", body: JSON.stringify(body),
    }),
  /** Take ONE name off a face. The face stays — it is evidence. */
  unnameFace: (id: number, subjectId: number) =>
    req<FaceRow[]>(`/api/faces/${id}/subject/${subjectId}`, { method: "DELETE" }),
  updateFace: (id: number, body: {
    dismissed?: boolean; x?: number; y?: number; w?: number; h?: number;
  }) => req<FaceRow[]>(`/api/faces/${id}`, {
    method: "PATCH", body: JSON.stringify(body),
  }),
  /** Draw (or replace) the face's OUTLINE — the whole figure. */
  setFaceOutline: (id: number,
                   box: { x: number; y: number; w: number; h: number;
                          points?: [number, number][] }) =>
    req<FaceRow[]>(`/api/faces/${id}/outline`, {
      method: "PUT", body: JSON.stringify(box),
    }),
  clearFaceOutline: (id: number) =>
    req<FaceRow[]>(`/api/faces/${id}/outline`, { method: "DELETE" }),
  /** Put the detector's rectangle back after a hand edit. */
  resetFaceBox: (id: number) =>
    req<FaceRow[]>(`/api/faces/${id}/reset-box`, { method: "POST" }),
  /** Somebody is in this picture — optionally at a face. */
  addAppearance: (body: { item_id: number; subject_id?: number | null;
                          display_name?: string; face_id?: number | null }) =>
    req<SubjectOnItem[]>("/api/subjects/appearances", {
      method: "POST", body: JSON.stringify(body),
    }),
  /** Date one appearance, or move it onto (or off) a face. */
  editAppearance: (id: number, body: {
    when?: { date: number | null; age: number | null };
    face_id?: number | null;
    /** Agree with a guess: the flag becomes "user" and the tag it put on the
     *  picture stops being pending. */
    confirm?: boolean;
  }) => req<SubjectOnItem[]>(`/api/subjects/appearances/${id}`, {
    method: "PATCH", body: JSON.stringify(body),
  }),
  /** The sidebar's drag-reorder: the item's appearances in the order the
   *  list now shows. */
  reorderAppearances: (itemId: number, ids: number[]) =>
    req<SubjectOnItem[]>("/api/subjects/appearances/order", {
      method: "POST", body: JSON.stringify({ item_id: itemId, ids }),
    }),
  removeAppearance: (id: number) =>
    req<SubjectOnItem[]>(`/api/subjects/appearances/${id}`, { method: "DELETE" }),
  /** Draw (or replace) the appearance's SUBJECT BOX. */
  setAppearanceBox: (id: number,
                     box: { x: number; y: number; w: number; h: number;
                            points?: [number, number][] }) =>
    req<SubjectOnItem[]>(`/api/subjects/appearances/${id}/box`, {
      method: "PUT", body: JSON.stringify(box),
    }),
  clearAppearanceBox: (id: number) =>
    req<SubjectOnItem[]>(`/api/subjects/appearances/${id}/box`,
                         { method: "DELETE" }),
  addFace: (body: { item_id: number; x: number; y: number; w: number;
                    h: number; subject_id?: number | null }) =>
    req<FaceRow[]>("/api/faces", { method: "POST", body: JSON.stringify(body) }),
  deleteFace: (id: number) =>
    req<FaceRow[]>(`/api/faces/${id}`, { method: "DELETE" }),
  /** Pull faces off whoever they are on, onto a NEW person with no name. */
  splitFaces: (faceIds: number[]) =>
    req<FaceCluster[]>("/api/faces/split", {
      method: "POST", body: JSON.stringify({ face_ids: faceIds }),
    }),
  /** Fold several unnamed clusters into one, still unnamed — a nameless
   *  subject holds it together, so the next detector run cannot scatter them. */
  mergeFaceClusters: (faceIds: number[]) =>
    req<FaceCluster[]>("/api/faces/merge-clusters", {
      method: "POST", body: JSON.stringify({ face_ids: faceIds }),
    }),
  /** THE CROPS MOST LIKE ONE CLUSTER, one by one — the strip beside an open
   *  cluster. A FACE rather than a cluster: "is this crop one of these?" is
   *  the question, and a cover crop standing for forty others answered a
   *  different one. `score` is on the library setting's own scale. */
  similarFaces: (of: { subject?: number | null; faces?: number[] },
                 limit = 12) => {
    const p = new URLSearchParams();
    if (of.subject != null) p.set("subject", String(of.subject));
    else p.set("faces", (of.faces ?? []).join(","));
    p.set("limit", String(limit));
    return req<SimilarFaceRow[]>(`/api/faces/similar-faces?${p.toString()}`);
  },
  /** "Not this person", said of the open cluster and each of `others` —
   *  the strip's ✕, and the bar's over a selection of offers. Each other
   *  is held on its own. Answers the strip as it now is, back-filled. */
  clustersNotMatching: (faceIds: number[], others: number[][]) =>
    req<SimilarFaceRow[]>("/api/faces/not-matching", {
      method: "POST",
      body: JSON.stringify({ face_ids: faceIds, other_clusters: others }),
    }),
  /** WHICH OF A CLUSTER'S CROPS LOOK MORE LIKE THE ONES JUST MOVED OUT.
   *
   *  A correction is evidence about the rest: whatever was only in that
   *  cluster because of the crops that left is still in it. A READ (it
   *  writes nothing and decides nothing) that is a POST because it carries
   *  two id lists. */
  /** WHAT THE OPEN CLUSTER'S PICTURES SAY, so the grid can group its crops:
   *  the sequence each is a page of, and the tags on it. Parallel arrays on
   *  `face_ids`, with the tag NAMES sent once and each crop naming its
   *  own by INDEX — see `FaceGroupingOut`. */
  faceGrouping: (faceIds: number[]) =>
    req<FaceGroupingOut>("/api/faces/grouping", {
      method: "POST",
      body: JSON.stringify({ face_ids: faceIds }),
    }),
  oddOnesOut: (faceIds: number[], unlike: number[]) =>
    req<number[]>("/api/faces/odd-ones-out", {
      method: "POST",
      body: JSON.stringify({ face_ids: faceIds, unlike }),
    }),
  /** SOMEBODY WITH NO NAME — a background character, an extra — or the way
   *  back out of it. The other answer to "who is this": it takes the cluster
   *  out of the UNKNOWN queue without a name being invented for it, and each
   *  cluster answered this way stays its own person. */
  setClusterUnnamed: (faceIds: number[], unnamed = true) =>
    req<FaceCluster[]>("/api/faces/unnamed-cluster", {
      method: "POST",
      body: JSON.stringify({ face_ids: faceIds, unnamed }),
    }),
  /** Name every face in a cluster at once — the point of the unnamed view. */
  /** `replace: false` COPIES — the target is added to what the faces already
   *  are, rather than taking their place. The age travels either way. */
  nameFaceCluster: (body: { face_ids: number[]; subject_id?: number | null;
                            display_name?: string; comment?: string;
                            replace?: boolean }) =>
    req<FaceCluster[]>("/api/faces/name-cluster", {
      method: "POST", body: JSON.stringify(body),
    }),
  /** The crop URL, keyed on the BOX as well as the id.
   *
   *  A face id is a SQLite rowid, so it is reused as soon as the row it named
   *  is deleted — and the crop is cached for a day. Without the box in the
   *  URL, a browser that saw face 9 while it belonged to one picture serves
   *  that crop for the unrelated face that inherited the id. The box is also
   *  what changes when a face is moved by hand, so one key answers both. */
  faceCropUrl: (face: { id: number; x: number; y: number; w: number; h: number },
                w = 96) => {
    const at = [face.x, face.y, face.w, face.h].map((n) => n.toFixed(4)).join("_");
    return `/api/faces/${face.id}/crop?w=${w}&at=${at}`;
  },

  /** The item's detected text, the whole tree, top level in reading order.
   *  Every text mutation below returns the same refreshed tree, so one
   *  mutation is one cache write. */
  itemText: (itemId: number) => req<TextRegion[]>(`/api/ocr/item/${itemId}`),
  addTextRegion: (body: { item_id: number; x: number; y: number; w: number;
                          h: number; text?: string; level?: TextLevel;
                          parent_id?: number | null }) =>
    req<TextRegion[]>("/api/ocr", { method: "POST", body: JSON.stringify(body) }),
  /** Correct the text (marks it `edited` server-side), mark as not text, or
   *  move the box. `quad` rides with a move so a rotated region's shape is
   *  not silently replaced by an upright rectangle. */
  updateTextRegion: (id: number, body: {
    text?: string; dismissed?: boolean;
    x?: number; y?: number; w?: number; h?: number;
    quad?: [number, number][];
  }) => req<TextRegion[]>(`/api/ocr/${id}`, {
    method: "PATCH", body: JSON.stringify(body),
  }),
  deleteTextRegion: (id: number) =>
    req<TextRegion[]>(`/api/ocr/${id}`, { method: "DELETE" }),
  /** One sibling run's FULL reading order — every sibling named exactly
   *  once (the server refuses less), so a per-engine drag still sends the
   *  whole top level. */
  reorderTextRegions: (itemId: number, region_ids: number[],
                       parent_id: number | null = null) =>
    req<TextRegion[]>(`/api/ocr/item/${itemId}/order`, {
      method: "POST", body: JSON.stringify({ region_ids, parent_id }),
    }),
  /** The region as a small JPEG strip. `at=` is `faceCropUrl`'s rowid-reuse
   *  guard — an id is handed on after deletion, and moving a box by hand
   *  must not serve the old crop back. */
  textCropUrl: (r: { id: number; x: number; y: number; w: number; h: number },
                w = 160) => {
    const at = [r.x, r.y, r.w, r.h].map((n) => n.toFixed(4)).join("_");
    return `/api/ocr/${r.id}/crop?w=${w}&at=${at}`;
  },

  /** One page of the subjects list (`q` matches display name or tag). */
  subjectsPage: (opts: { q?: string; limit: number; offset?: number }) =>
    req<Paged<SubjectRow>>(`/api/subjects?${pageParams(opts)}`),
  createSubject: (body: { display_name?: string; comment?: string;
                          since_date?: number | null; tag?: string }) =>
    req<SubjectRow[]>("/api/subjects", { method: "POST", body: JSON.stringify(body) }),
  updateSubject: (id: number, body: { display_name?: string; comment?: string;
                                      since_date?: number | null;
                                      tag?: string }) =>
    req<SubjectRow[]>(`/api/subjects/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteSubject: (id: number, withTag = false) =>
    req<SubjectRow[]>(`/api/subjects/${id}?with_tag=${withTag}`, { method: "DELETE" }),
  /** Returns the rows AND the event ids, so a list view can offer an Undo. */
  mergeSubject: (id: number, intoId: number, keepAlias = true) =>
    req<{ subjects: SubjectRow[]; event_ids: number[] }>(`/api/subjects/${id}/merge`, {
      method: "POST",
      body: JSON.stringify({ into_id: intoId, keep_alias: keepAlias }),
    }),
  /** Date/age one tag assignment; both empty clears it. */
  setTagWhen: (itemId: number, tagId: number, body: TagWhen) =>
    req<TagWhen>(`/api/subjects/when/${itemId}/${tagId}`, {
      method: "PUT", body: JSON.stringify(body),
    }),

  addCaptionTag: (itemId: number, captionId: number, name: string) =>
    req<string[]>(`/api/items/${itemId}/captions/${captionId}/tags`, {
      method: "POST", body: JSON.stringify({ name }),
    }),
  removeCaptionTag: (itemId: number, captionId: number, name: string) =>
    req<string[]>(
      `/api/items/${itemId}/captions/${captionId}/tags/${encodeURIComponent(name)}`,
      { method: "DELETE" }),
  addLinkTag: (relId: number, name: string) =>
    req<string[]>(`/api/relationships/${relId}/tags`, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  removeLinkTag: (relId: number, name: string) =>
    req<string[]>(`/api/relationships/${relId}/tags/${encodeURIComponent(name)}`, {
      method: "DELETE",
    }),
  // Link-tag management (Tags tab "Links" mode): rows with usage counts +
  // comments, rename/comment, and delete-everywhere.
  linkTagRows: () => req<LinkTagRow[]>("/api/link-tags/rows"),
  createLinkTag: (name: string, rest?: { comment?: string; description?: string }) =>
    req<LinkTagRow[]>("/api/link-tags/create", {
      method: "POST",
      body: JSON.stringify({ name, ...rest }),
    }),
  updateLinkTag: (body: { name: string; new_name?: string; comment?: string;
                          description?: string }) =>
    req<LinkTagRow[]>("/api/link-tags/update", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteLinkTag: (name: string) =>
    req<LinkTagRow[]>("/api/link-tags/delete", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  // ---- history ----
  history: (limit = 500, offset = 0) =>
    req<HistoryPage>(`/api/history?limit=${limit}&offset=${offset}`),
  /** What has been logged SINCE `afterId` — how a caller asks what the thing
   *  it just did wrote, so it can offer the way back. */
  historySince: (afterId: number, limit = 200) =>
    req<HistoryPage>(`/api/history?limit=${limit}&after_id=${afterId}`),
  revertEvents: (eventIds: number[]) =>
    req<RevertResult>("/api/history/revert", {
      method: "POST",
      body: JSON.stringify({ event_ids: eventIds }),
    }),
  /** Empty the modification log. The library itself is untouched; what goes is
   *  its memory of how it got that way — and with it every Undo. One entry is
   *  written saying it happened. */
  clearHistory: () =>
    req<{ deleted: number }>("/api/history", { method: "DELETE" }),
  // ---- AI jobs (background removal / captioning / tagging) ----
  mlModels: () => req<ModelsOut>("/api/ml/models"),
  /** `skipDone` leaves out the items this model has already been run over —
   *  only face detection records that, and the server does the filtering,
   *  since knowing would otherwise mean fetching every item's detail. */
  /** `detectWith` is TEXT REMOVAL's "detect and remove": the OCR model to
   *  read the page with first. Removal itself never detects — it paints out
   *  the item's stored text regions — so this is how one job does both, and
   *  the reading it makes is kept in the Text tab. */
  enqueueJobs: (kind: JobKind, model: string, item_ids: number[],
                intoSequence = false, reference = "", skipDone = false,
                detectWith = "") =>
    req<{ job_ids: number[]; skipped?: number }>("/api/ml/jobs", {
      method: "POST",
      body: JSON.stringify({ kind, model, item_ids,
                             into_sequence: intoSequence, reference,
                             skip_done: skipDone, detect_with: detectWith }),
    }),
  /** Enqueue `kind`/`model` over every item in the given groups' SUBTREES,
   *  resolved server-side — the browser cannot cheaply know a big group's
   *  members. Trashed/hidden items are excluded, mirroring the grid;
   *  `skipDone` has `enqueueJobs`'s semantics (faces only). */
  enqueueScope: (kind: JobKind, model: string, groups: number[],
                 skipDone = false, view = "", detectWith = "",
                 intoSequence = false) =>
    req<{ queued: number; skipped: number }>("/api/ml/enqueue-scope", {
      method: "POST",
      body: JSON.stringify({ kind, model, groups, skip_done: skipDone,
                             view, detect_with: detectWith,
                             into_sequence: intoSequence }),
    }),
  /** Enqueue `kind`/`model` over everything the VIEW is showing.
   *
   *  `enqueueScope` answers the narrower question (a group subtree, one of
   *  the sidebar's fixed rows); this takes the grid's own search body, with
   *  the same `groups` flattening every view-scoped write uses — diverging
   *  there would run over a different set from the one on screen. The ids
   *  never come back here: a view can be the whole library. */
  enqueueJobsView: (kind: JobKind, model: string, scope: ItemSearchBody,
                    intoSequence = false, reference = "", skipDone = false,
                    detectWith = "") =>
    req<{ queued: number; skipped: number }>("/api/ml/enqueue-view", {
      method: "POST",
      body: JSON.stringify({
        ...scope, groups: (scope.groups ?? []).join(","),
        // `task_kind`, NOT `kind`: the search body already owns `kind` (the
        // ITEM kind the view is filtered to), and one name cannot be both
        // the question and the answer — see `EnqueueView` server-side.
        task_kind: kind, model, into_sequence: intoSequence, reference,
        skip_done: skipDone, detect_with: detectWith,
      }),
    }),
  // Temporary color-reference images (rolling store) for reference-guided models.
  mlRefs: () => req<{ refs: { id: string }[] }>("/api/ml/refs"),
  mlRefUpload: async (file: File) => {
    const fd = new FormData();
    fd.append("image", file, file.name || "ref.png");
    const r = await apiFetch("/api/ml/refs", { method: "POST", body: fd });
    if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
    return r.json() as Promise<{ id: string }>;
  },
  mlRefFromItem: (itemId: number) =>
    req<{ id: string }>(`/api/ml/refs/from-item/${itemId}`, { method: "POST" }),
  mlRefDelete: (id: string) =>
    req<{ ok: boolean }>(`/api/ml/refs/${encodeURIComponent(id)}`, { method: "DELETE" }),
  // Run an image-to-image model on an uploaded buffer (the editor's Image
  // menu) and get the resulting PNG back — synchronous, no job queue.
  mlApply: async (kind: JobKind, model: string, image: Blob, reference = ""): Promise<Blob> => {
    const fd = new FormData();
    fd.append("image", image, "buffer.png");
    fd.append("kind", kind);
    fd.append("model", model);
    if (reference) fd.append("reference", reference);
    const r = await apiFetch("/api/ml/apply", { method: "POST", body: fd });
    if (!r.ok) {
      let msg = `${r.status}`;
      try { msg = (await r.json()).detail || msg; } catch { /* keep status */ }
      throw new Error(msg);
    }
    return r.blob();
  },
  // Detect text / watermark regions on an uploaded buffer — normalized
  // polygons (the editor turns them into a selection).
  mlDetectRegions: async (kind: "text" | "watermark", image: Blob) => {
    const fd = new FormData();
    fd.append("image", image, "buffer.png");
    fd.append("kind", kind);
    const r = await apiFetch("/api/ml/detect-regions", { method: "POST", body: fd });
    if (!r.ok) {
      let msg = `${r.status}`;
      try { msg = (await r.json()).detail || msg; } catch { /* keep status */ }
      throw new Error(msg);
    }
    return r.json() as Promise<{ regions: [number, number][][] }>;
  },
  mlJobs: () => req<{ jobs: JobOut[] }>("/api/ml/jobs"),
  cancelJob: (id: number) =>
    req<{ ok: boolean }>(`/api/ml/jobs/${id}/cancel`, { method: "POST" }),
  cancelAllJobs: () =>
    req<{ ok: boolean; count: number }>("/api/ml/jobs/cancel-all", { method: "POST" }),
  clearFinishedJobs: () =>
    req<{ ok: boolean }>("/api/ml/jobs/clear-finished", { method: "POST" }),
  clearJob: (id: number) =>
    req<{ ok: boolean }>(`/api/ml/jobs/${id}/clear`, { method: "POST" }),
  jobLog: (id: number) =>
    req<{ log: string; message: string; status: string }>(`/api/ml/jobs/${id}/log`),
  /** The item ids a job covers — the batch list when one is recorded, else
   *  the single item. On demand rather than on `JobOut`: a batch job can
   *  hold thousands of ids and the list never needs them. */
  jobItems: (id: number) =>
    req<{ item_ids: number[] }>(`/api/ml/jobs/${id}/items`),
  pauseJob: (id: number) =>
    req<{ ok: boolean }>(`/api/ml/jobs/${id}/pause`, { method: "POST" }),
  resumeJob: (id: number) =>
    req<{ ok: boolean }>(`/api/ml/jobs/${id}/resume`, { method: "POST" }),
  /** A window of a batch job's items, each with what has happened to it.
   *  Paged, because a batch can cover a whole library and the overlay only
   *  ever draws a screenful. */
  jobProgress: (id: number, offset: number, limit: number) =>
    req<JobProgress>(
      `/api/ml/jobs/${id}/progress?offset=${offset}&limit=${limit}`),
  // ---- identity (multi-user) ----
  whoami: () => req<{ username: string; require_auth: boolean }>("/api/whoami"),
  updateSettings: (body: AppSettings) =>
    req<AppSettings>("/api/settings", { method: "PUT", body: JSON.stringify(body) }),
  // ---- tag sets ----
  tagSets: () => req<TagSetOut[]>("/api/tag-sets"),
  tagSet: (id: number) => req<TagSetDetail>(`/api/tag-sets/${id}`),
  createTagSet: (body: { name: string; key?: string; description?: string }) =>
    req<TagSetOut>("/api/tag-sets", { method: "POST", body: JSON.stringify(body) }),
  updateTagSet: (id: number, body: { name?: string; description?: string;
                                      version?: number; position?: number;
                                      aliases_enabled?: boolean;
                                      implications_enabled?: boolean }) =>
    req<TagSetOut>(`/api/tag-sets/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  setTagSetEnabled: (id: number, enabled: boolean) =>
    req<TagSetOut>(`/api/tag-sets/${id}/enabled`,
                   { method: "PUT", body: JSON.stringify({ enabled }) }),
  deleteTagSet: (id: number) =>
    req<{ ok: boolean }>(`/api/tag-sets/${id}`, { method: "DELETE" }),
  duplicateTagSet: (id: number, name = "") =>
    req<TagSetOut>(`/api/tag-sets/${id}/duplicate`,
                   { method: "POST", body: JSON.stringify({ name }) }),
  importTagSet: (document: unknown, mode: "create" | "merge" | "replace" = "create",
                 target_id?: number) =>
    req<TagSetImportOut>("/api/tag-sets/import", {
      method: "POST", body: JSON.stringify({ document, mode, target_id: target_id ?? null }),
    }),
  /** The set as its file — TEXT, not JSON-parsed, so what is saved is byte
   *  for byte what the server wrote. Through `apiFetch` like every `/api/`
   *  read (`noRawApiFetch.test.ts`). */
  exportTagSet: async (id: number) => {
    const r = await apiFetch(`/api/tag-sets/${id}/export`);
    if (!r.ok) throw new Error(`${r.status}`);
    return r.text();
  },
  /** What the enabled sets say about a few names — the hover outside the
   *  lists, and what a tag LINK in a description follows. */
  describeNames: (names: string[]) =>
    req<Record<string, { tag_sets: TagSetRef[]; descriptions: TagSetText[] }>>(
      `/api/tag-sets/describe?names=${encodeURIComponent(names.join(","))}`),
  tagSetTree: () => req<{ sets: TagSetTreeSet[] }>("/api/tag-sets/tree"),
  /** Give a built-in the entries THIS build ships. Slow by nature — it
   *  rewrites every row of the set — which is why it is a press and not
   *  something the server does at open. */
  updateBuiltinTagSet: (id: number) =>
    req<TagSetOut>(`/api/tag-sets/${id}/update`, { method: "POST" }),
  tagSetEntries: (id: number, opts: TagSetEntriesOpts = {}) => {
    const p = new URLSearchParams();
    if (opts.q) p.set("q", opts.q);
    if (opts.sort) p.set("sort", opts.sort);
    if (opts.desc) p.set("desc", "true");
    if (opts.category_id != null) p.set("category_id", String(opts.category_id));
    // Repeated, which is how the endpoint takes a list.
    for (const cid of opts.category_ids ?? []) p.append("category_id", String(cid));
    if (opts.uncategorized) p.set("uncategorized", "true");
    if (opts.subtree) p.set("subtree", "true");
    if (opts.has_aliases) p.set("has_aliases", "true");
    if (opts.has_implies) p.set("has_implies", "true");
    if (opts.described != null) p.set("described", String(opts.described));
    if (opts.behind) p.set("behind", "true");
    if (opts.behind_records) p.set("behind_records", "true");
    for (const k of opts.records ?? []) p.append("record", k);
    // A RANGE ON THE COUNT COLUMN — either end optional, an absent bound
    // being no bound, exactly as the Items list's columns take it.
    if (opts.count_min != null) p.set("count_min", String(opts.count_min));
    if (opts.count_max != null) p.set("count_max", String(opts.count_max));
    for (const ns of opts.namespaces ?? []) p.append("namespace", ns);
    if (opts.limit != null) p.set("limit", String(opts.limit));
    if (opts.offset) p.set("offset", String(opts.offset));
    const qs = p.toString();
    return req<TagSetEntriesOut>(`/api/tag-sets/${id}/entries${qs ? "?" + qs : ""}`);
  },
  /** WHERE a named entry sits in the list as it is narrowed and sorted right
   *  now — the index the windowed list scrolls to. Takes the same options
   *  `tagSetEntries` does, because the answer is only true of that list. */
  tagSetEntryIndex: (id: number, name: string, opts: TagSetEntriesOpts = {}) => {
    const p = new URLSearchParams({ name });
    if (opts.q) p.set("q", opts.q);
    if (opts.sort) p.set("sort", opts.sort);
    if (opts.desc) p.set("desc", "true");
    for (const cid of opts.category_ids ?? []) p.append("category_id", String(cid));
    if (opts.category_id != null) p.append("category_id", String(opts.category_id));
    if (opts.uncategorized) p.set("uncategorized", "true");
    if (opts.subtree) p.set("subtree", "true");
    if (opts.has_aliases) p.set("has_aliases", "true");
    if (opts.has_implies) p.set("has_implies", "true");
    if (opts.described != null) p.set("described", String(opts.described));
    if (opts.behind) p.set("behind", "true");
    if (opts.behind_records) p.set("behind_records", "true");
    for (const k of opts.records ?? []) p.append("record", k);
    return req<{ index: number | null; id: number | null;
                 category_id: number | null }>(
      `/api/tag-sets/${id}/entries/locate?${p.toString()}`);
  },
  /** The labels this tag set puts on its names — the sidebar's Meta
   *  tags row. Its own list, not the library's: what a set calls a
   *  `character` is the set's advice until the door carries it over. */
  tagSetMetaTags: (id: number) =>
    req<TagSetMetaTagOut[]>(`/api/tag-sets/${id}/meta-tags`),
  createTagSetMetaTag: (id: number, body: { name: string; comment?: string;
                                            description?: string }) =>
    req<TagSetMetaTagOut[]>(`/api/tag-sets/${id}/meta-tags`,
                            { method: "POST", body: JSON.stringify(body) }),
  updateTagSetMetaTag: (id: number, mid: number,
                        body: { name?: string; comment?: string;
                                description?: string }) =>
    req<TagSetMetaTagOut[]>(`/api/tag-sets/${id}/meta-tags/${mid}`,
                            { method: "PATCH", body: JSON.stringify(body) }),
  deleteTagSetMetaTag: (id: number, mid: number) =>
    req<TagSetMetaTagOut[]>(`/api/tag-sets/${id}/meta-tags/${mid}`,
                            { method: "DELETE" }),
  createTagSetEntry: (id: number, body: { name: string; description?: string;
                                           count?: number | null; category_id?: number | null;
                                           aliases?: string[];
                                           implies?: string[];
                                           meta?: string[];
                                           comment?: string;
                                           subject?: TagSetSubject | null;
                                           place?: TagSetPlace | null;
                                           event?: TagSetEvent | null }) =>
    req<TagSetEntryOut>(`/api/tag-sets/${id}/entries`,
                        { method: "POST", body: JSON.stringify(body) }),
  updateTagSetEntry: (id: number, eid: number, body: {
      name?: string; description?: string; count?: number | null; clear_count?: boolean;
      category_id?: number | null; clear_category?: boolean;
      aliases?: string[]; implies?: string[]; meta?: string[]; comment?: string;
      /** The records this edit is ABOUT: `kinds` names them, and a kind
       *  named with a null value is taken away. One left out is left
       *  alone — an absent key and a null reach the server the same way. */
      records?: { kinds: Array<"subject" | "place" | "event">;
                  subject?: TagSetSubject | null;
                  place?: TagSetPlace | null;
                  event?: TagSetEvent | null } }) =>
    req<TagSetEntryOut>(`/api/tag-sets/${id}/entries/${eid}`,
                        { method: "PATCH", body: JSON.stringify(body) }),
  /** Make the library's tags say what the set says about them — what the
   *  name entails, the line it carries, and whether it is a subject, a
   *  place or an event. ONE verb, because the door applies all of it at one
   *  moment and a tag that was already there has heard none of it.
   *  `append` keeps what the library says; `replace` overrides it. */
  syncTagSetEntries: (id: number, entry_ids: number[],
                      mode: "append" | "replace") =>
    req<TagSetSyncOut>(`/api/tag-sets/${id}/entries/sync`,
                       { method: "POST",
                         body: JSON.stringify({ entry_ids, mode }) }),
  /** Build the parent hierarchy above these entries' places and events —
   *  its own verb, since following a parent MINTS that tag and its own
   *  parent above it. */
  syncTagSetParents: (id: number, entry_ids: number[],
                      mode: "append" | "replace") =>
    req<TagSetSyncOut>(`/api/tag-sets/${id}/entries/sync-parents`,
                       { method: "POST",
                         body: JSON.stringify({ entry_ids, mode }) }),
  /** Put these entries' tags in the library, through the DOOR — so each
   *  arrives with what its set says: an alias name creates the canonical
   *  tag, and the entry's implied names are minted with it. */
  /** EVERY entry id the narrowing holds, in the list's order — what SELECT
   *  ALL and a shift-range are about. The list is server-paged and
   *  windowed, so "all" cannot be read off the rows in hand. */
  tagSetEntryIds: (id: number, opts: TagSetEntriesOpts = {}) => {
    const p = new URLSearchParams();
    if (opts.q) p.set("q", opts.q);
    for (const c of opts.category_ids ?? []) p.append("category_id", String(c));
    if (opts.uncategorized) p.set("uncategorized", "true");
    if (opts.subtree) p.set("subtree", "true");
    if (opts.has_aliases) p.set("has_aliases", "true");
    if (opts.has_implies) p.set("has_implies", "true");
    if (opts.described != null) p.set("described", String(opts.described));
    if (opts.behind) p.set("behind", "true");
    if (opts.behind_records) p.set("behind_records", "true");
    for (const k of opts.records ?? []) p.append("record", k);
    for (const ns of opts.namespaces ?? []) p.append("namespace", ns);
    if (opts.sort) p.set("sort", opts.sort);
    if (opts.desc) p.set("desc", "true");
    return req<{ ids: number[] }>(
      `/api/tag-sets/${id}/entries/ids?${p.toString()}`);
  },
  addTagSetEntriesToLibrary: (id: number, entry_ids: number[]) =>
    req<{ added: number; skipped: number }>(
      `/api/tag-sets/${id}/entries/add-to-library`,
      { method: "POST", body: JSON.stringify({ entry_ids }) }),
  deleteTagSetEntry: (id: number, eid: number) =>
    req<{ ok: boolean }>(`/api/tag-sets/${id}/entries/${eid}`, { method: "DELETE" }),
  bulkTagSetEntries: (id: number, rows: TagSetBulkRowIn[],
                      existing: "keep" | "update" | "replace" = "keep") =>
    req<TagSetBulkOut>(`/api/tag-sets/${id}/entries/bulk`,
                       { method: "POST", body: JSON.stringify({ rows, existing }) }),
  createTagSetCategory: (id: number, body: { name: string; parent_id?: number | null;
                                              icon?: string; hidden?: boolean;
                                              aliases?: boolean | null;
                                              implications?: boolean | null }) =>
    req<TagSetCategoryOut>(`/api/tag-sets/${id}/categories`,
                           { method: "POST", body: JSON.stringify(body) }),
  updateTagSetCategory: (id: number, cid: number, body: {
      name?: string; parent_id?: number | null; clear_parent?: boolean;
      icon?: string; hidden?: boolean; position?: number;
      /** THREE-STATE: `clear_*` asks for the null (inherit from the parent),
       *  the field itself for an answer. Neither means "leave alone", which
       *  is why `null` cannot say it. */
      aliases?: boolean; clear_aliases?: boolean;
      implications?: boolean; clear_implications?: boolean }) =>
    req<TagSetCategoryOut>(`/api/tag-sets/${id}/categories/${cid}`,
                           { method: "PATCH", body: JSON.stringify(body) }),
  /** The tree's drag: under `parent_id` (null = the top) at `index`. */
  moveTagSetCategory: (id: number, cid: number, body: { parent_id: number | null; index: number }) =>
    req<TagSetCategoryOut>(`/api/tag-sets/${id}/categories/${cid}/move`,
                           { method: "POST", body: JSON.stringify(body) }),
  deleteTagSetCategory: (id: number, cid: number) =>
    req<{ ok: boolean }>(`/api/tag-sets/${id}/categories/${cid}`, { method: "DELETE" }),
  tagSetOrder: () => req<{ keys: string[] }>("/api/settings/tag-set-order"),
  putTagSetOrder: (keys: string[]) =>
    req<{ keys: string[] }>("/api/settings/tag-set-order",
                            { method: "PUT", body: JSON.stringify({ keys }) }),
  modelCache: () => req<ModelCacheOut>("/api/ml/model-cache"),
  downloadModel: (key: string) =>
    req<{ ok: boolean; status: string }>(`/api/ml/model-cache/${key}/download`, { method: "POST" }),
  runSetup: (pluginKey: string) =>
    req<{ ok: boolean }>(`/api/ml/setup/${pluginKey}`, { method: "POST" }),
  cancelDownload: (key: string) =>
    req<{ ok: boolean }>(`/api/ml/model-cache/${key}/cancel-download`, { method: "POST" }),
  deleteModelCache: (key: string) =>
    req<{ ok: boolean; deleted: boolean }>(`/api/ml/model-cache/${key}/delete-cache`, { method: "POST" }),
  approveCaption: (captionId: number) =>
    req<{ ok: boolean }>(`/api/ml/captions/${captionId}/approve`, { method: "POST" }),
  approvePlacement: (placementId: number) =>
    req<{ ok: boolean }>(`/api/ml/placements/${placementId}/approve`, { method: "POST" }),
  // ---- video editor ----
  /** Queue the editor's cutlist as a background render. Returns the job to
   *  watch; the work outlives this window. */
  videoEdit: (itemId: number, plan: VideoEditPlan) =>
    req<VideoJob>(`/api/items/${itemId}/video-edit`, {
      method: "POST",
      body: JSON.stringify(plan),
    }),
  /** The render in flight for this item, if any — what puts the progress
   *  modal back up when the editor is reopened mid-render. */
  videoEditStatus: (itemId: number) =>
    req<VideoJob>(`/api/items/${itemId}/video-edit`),
  createClip: (itemId: number, start: number, end: number, name?: string) =>
    req<{ ok: boolean; item_id: number }>(`/api/items/${itemId}/clip`, {
      method: "POST",
      body: JSON.stringify({ start, end, name }),
    }),
  /** Capture the whole frame as a new image item linked back to the video.
   *  (Cropping is the image editor's job, on the still.) */
  captureFrame: (
    itemId: number, timestamp: number, opts?: { name?: string },
  ) =>
    req<{ ok: boolean; item_id: number; created: boolean }>(
      `/api/items/${itemId}/frame`,
      { method: "POST", body: JSON.stringify({ timestamp, ...opts }) }
    ),
  /** Queue a still every `every` seconds — over `[start, end]` when a range
   *  is marked, else the whole film. A JOB, because each still is an ffmpeg
   *  seek plus a dedup probe and a few hundred of them is minutes. The reply
   *  carries how many it will take, counted SERVER-SIDE: what "every N
   *  seconds of this film" comes to is one rule, in `every_n_timestamps`, and
   *  an estimate here would be a second one. */
  captureFramesEvery: (
    itemId: number, every: number, range?: { start: number; end: number },
  ) =>
    req<{ job_id: number | null; status: string; message: string }>(
      `/api/items/${itemId}/frames`,
      { method: "POST", body: JSON.stringify({
          every, start: range?.start ?? 0, end: range?.end ?? null }) }
    ),
  /** Make the frame at `timestamp` this video's thumbnail. */
  setThumbnailFrame: (itemId: number, timestamp: number) =>
    req<{ ok: boolean }>(`/api/items/${itemId}/thumbnail-frame`,
      { method: "POST", body: JSON.stringify({ timestamp }) }),
  frameMarkers: (itemId: number) =>
    req<FrameMarker[]>(`/api/items/${itemId}/frame-markers`),
  /** Every still of this video (whole frames; older ones may be crops). */
  stills: (itemId: number) =>
    req<Still[]>(`/api/items/${itemId}/stills`),
  // ---- tag boxes ----
  addTagBox: (
    itemId: number, tag: string, box: TagBox, fileId?: number,
    groupId?: number | null,
  ) =>
    req<{ ok: boolean; id: number }>(
      `/api/tags/assign/item/${itemId}/box`,
      {
        method: "POST",
        body: JSON.stringify({
          tag, box, file_id: fileId ?? null, group_id: groupId ?? null,
        }),
      }
    ),
  // Update a box in place (annotation editor): geometry (in fileId's frame),
  // its time range / track (video), and/or its tag label. Keeps the box id
  // stable for clean undo/redo. Time/track fields left undefined are unchanged;
  // clearTime/clearTrack reset them to null.
  updateTagBox: (
    boxId: number,
    body: {
      x?: number; y?: number; w?: number; h?: number; tag?: string; fileId?: number;
      timeStart?: number | null; timeEnd?: number | null; trackId?: number | null;
      negative?: boolean;
      clearTime?: boolean; clearTrack?: boolean;
      // Replace the box's polygon (the rectangle re-derives from it), or
      // clear it back to a plain rectangle.
      points?: [number, number][] | null;
      clearPoints?: boolean;
    },
  ) =>
    req<{ ok: boolean }>(`/api/tags/box/${boxId}`, {
      method: "PATCH",
      body: JSON.stringify({
        x: body.x, y: body.y, w: body.w, h: body.h,
        tag: body.tag, file_id: body.fileId ?? null,
        time_start: body.timeStart ?? undefined,
        time_end: body.timeEnd ?? undefined,
        track_id: body.trackId ?? undefined,
        negative: body.negative ?? undefined,
        clear_time: body.clearTime ?? false,
        clear_track: body.clearTrack ?? false,
        points: body.points ?? undefined,
        clear_points: body.clearPoints ?? false,
      }),
    }),
  /** Flip ONE tag instance's sign — the row's dot, not the whole tag. The
   *  assignment (what search reads) re-derives server-side: negative only
   *  when every instance is. */
  setPlacementSign: (placementId: number, negative: boolean) =>
    req(`/api/tags/placement/${placementId}/sign`, {
      method: "POST", body: JSON.stringify({ negative }),
    }),
  deleteTagBox: (boxId: number) =>
    req<{ ok: boolean }>(`/api/tags/box/${boxId}`, { method: "DELETE" }),
  // ---- per-item tag groups ----
  createTagGroup: (itemId: number, name: string) =>
    req<TagGroupOut>(`/api/tags/item/${itemId}/groups`, {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  // Add a tag as an instance in a specific group (null = ungrouped). Allows the
  // same tag name to live in multiple groups at once.
  addTagToGroup: (itemId: number, tag: string, groupId: number | null, negative = false) =>
    req(`/api/tags/item/${itemId}/group-tag`, {
      method: "POST",
      body: JSON.stringify({ tag, group_id: groupId, negative }),
    }),
  renameTagGroup: (groupId: number, name: string) =>
    req(`/api/tags/groups/${groupId}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    }),
  deleteTagGroup: (groupId: number) =>
    req(`/api/tags/groups/${groupId}`, { method: "DELETE" }),
  // Meta tags on a tag group — same namespace (and same catalog) as a link's
  // and a caption's; both return the group's tags after the change.
  addTagGroupTag: (groupId: number, name: string) =>
    req<string[]>(`/api/tags/groups/${groupId}/tags`, {
      method: "POST", body: JSON.stringify({ name }),
    }),
  removeTagGroupTag: (groupId: number, name: string) =>
    req<string[]>(
      `/api/tags/groups/${groupId}/tags/${encodeURIComponent(name)}`,
      { method: "DELETE" }),
  deleteTagPlacement: (placementId: number) =>
    req(`/api/tags/placements/${placementId}`, { method: "DELETE" }),
  moveTagInstance: (
    itemId: number, name: string,
    fromGroupId: number | null, toGroupId: number | null,
  ) =>
    req(`/api/tags/item/${itemId}/move-instance`, {
      method: "POST",
      body: JSON.stringify({
        name, from_group_id: fromGroupId, to_group_id: toGroupId,
      }),
    }),
  // ---- rankings ------------------------------------------------------------
  /** Every ranking. `thumbs` asks for that many COVER file ids per row —
   *  the grid's cards want four; the sidebar asks for none, since filling
   *  them costs a fit per ranking. */
  rankings: (thumbs = 0) =>
    req<RankingRow[]>(`/api/rankings${thumbs ? `?thumbs=${thumbs}` : ""}`),
  createRanking: (body: { name: string; scope?: string;
                          bucket_lo?: number; bucket_hi?: number }) =>
    req<RankingRow[]>("/api/rankings", {
      method: "POST", body: JSON.stringify(body),
    }),
  updateRanking: (id: number, body: { name?: string;
                                      scope?: string;
                                      bucket_lo?: number;
                                      bucket_hi?: number }) =>
    req<RankingRow[]>(`/api/rankings/${id}`, {
      method: "PATCH", body: JSON.stringify(body),
    }),
  deleteRanking: (id: number) =>
    req<RankingRow[]>(`/api/rankings/${id}`, { method: "DELETE" }),
  /** What a ranking's estimate WOULD claim over a scope — the dialog's
   *  footer, run on every edit of a rule.
   *
   *  The scope travels as the search body, like every whole-view write;
   *  `items` NARROWS here (unlike the sessions' priority rule) because this
   *  is one bulk write rather than a queue. Writes nothing, and reads a
   *  bounded scrambled sample rather than the lot — `partial` says so. */
  estimateRanking: (id: number, body: EstimateBody) =>
    req<RankingEstimateOut>(`/api/rankings/${id}/estimate`, {
      method: "POST",
      body: JSON.stringify({ ...body, groups: (body.groups ?? []).join(",") }),
    }),
  /** QUEUE the write. Answers with the job that will do it, not with what
   *  it wrote: the scope is the library, so this can be minutes of walking
   *  and hundreds of thousands of tag rows. The task list carries it. */
  applyEstimate: (id: number, body: EstimateBody) =>
    req<{ job_id: number }>(`/api/rankings/${id}/estimate/apply`, {
      method: "POST",
      body: JSON.stringify({ ...body, groups: (body.groups ?? []).join(",") }),
    }),
  createRankingPool: (id: number, name: string) =>
    req<RankingRow[]>(`/api/rankings/${id}/pools`, {
      method: "POST", body: JSON.stringify({ name }),
    }),
  renameRankingPool: (id: number, poolId: number, name: string) =>
    req<RankingRow[]>(`/api/rankings/${id}/pools/${poolId}`, {
      method: "PATCH", body: JSON.stringify({ name }),
    }),
  /** Every pool of the ranking, once, in the order wanted. */
  reorderRankingPools: (id: number, poolIds: number[]) =>
    req<RankingRow[]>(`/api/rankings/${id}/pools/order`, {
      method: "POST", body: JSON.stringify({ pool_ids: poolIds }),
    }),
  /** Not revertible — the pool's judgments go with it. */
  deleteRankingPool: (id: number, poolId: number) =>
    req<RankingRow[]>(`/api/rankings/${id}/pools/${poolId}`,
                      { method: "DELETE" }),
  rankingDetail: (id: number) =>
    req<RankingDetailOut>(`/api/rankings/${id}/detail`),
  /** The next pair to rate. The session's scope travels as the same search
   *  body the grid pages with (or an explicit `items` selection); `recent`
   *  keeps the pair just shown from bouncing straight back. */
  /** The tag-batch session feed — the scope rides in it exactly as the
   *  search body does (a read-only POST). `count: 0` is the chooser's
   *  coverage probe. */
  tagSortNext: (body: Partial<ItemSearchBody> & {
    items?: number[]; tags: string[]; smart?: boolean;
    /** The set's shape — the groups with their exclusivity (`tag_groups`,
     *  not `groups`, which is the SCOPE's field) and every counter tag. */
    tag_groups?: { tags: string[]; exclusive: boolean }[];
    counter_tags?: Record<string, string>;
    embedder?: string;
    /** One space or several, fused — the grid's `embedders`; empty means
     *  `embedder` alone. */
    embedders?: string[];
    recent?: number[]; session_negatives?: Record<string, number[]>;
    /** The queue still held unshown from the last fetch — re-scored ahead
     *  of the fresh sample, so the ordering accumulates across answers. */
    carry?: number[];
    count?: number;
    /** Whether the reply needs the pool's SIZE — see `TagSortNextOut.pool`.
     *  Defaults to true server-side, so omitting it is the old behaviour. */
    want_pool?: boolean;
  }) =>
    req<TagSortNextOut>("/api/tagsort/next", {
      method: "POST",
      body: JSON.stringify({ ...body, groups: (body.groups ?? []).join(",") }),
    }),
  /** Queue the embed job over the scope's unindexed items (a write). */
  /** The tag-grid overlay's batch feed — a read-only POST like
   *  `tagSortNext`, its own endpoint because it answers a different
   *  question (a pre-sorted batch with per-card scores and cuts). */
  tagGridNext: (body: Partial<ItemSearchBody> & {
    items?: number[];
    /** THE SET the session asks about — a picture fits when it carries
     *  every one of them. `negative` is the tag's own "doesn't fit"
     *  spelling, a counter tag written positively in place of its
     *  negative. */
    tags: { name: string; negative: string }[];
    recent?: number[]; count?: number;
    /** The session's own "doesn't fit" answers — labels for the fit that
     *  the library was never told, because past one tag the answer writes
     *  nothing (a conjunction's "no" names no tag to write it on). One
     *  flat list: the grid's question is one SET, where the tag batch has
     *  a row per tag. */
    session_negatives?: number[];
    smart?: boolean; embedders?: string[]; boundary?: boolean;
    want_pool?: boolean;
  }) =>
    req<TagGridNextOut>("/api/taggrid/next", {
      method: "POST",
      body: JSON.stringify({ ...body, groups: (body.groups ?? []).join(",") }),
    }),
  tagSortIndex: (body: Partial<ItemSearchBody> & { items?: number[];
                                                   embedder?: string }) =>
    req<{ queued: number; skipped: number }>("/api/tagsort/index", {
      method: "POST",
      body: JSON.stringify({ ...body, groups: (body.groups ?? []).join(",") }),
    }),
  rankingPair: (id: number, body: Partial<ItemSearchBody> & {
    items?: number[]; recent?: number[][]; summary_only?: boolean;
    /** Whether the reply needs the pool's SIZE — see `RankingPairOut.pool`.
     *  Defaults to true server-side, so omitting it is the old behaviour. */
    want_pool?: boolean;
    /** Whose evidence the pick and the standings read — the session's
     *  picked pools. Empty is the ranking's default pool. */
    pool_ids?: number[];
  }) =>
    req<RankingPairOut>(`/api/rankings/${id}/pair`, {
      method: "POST",
      body: JSON.stringify({ ...body, groups: (body.groups ?? []).join(",") }),
    }),
  /** ONE judgement, written into every pool named (one row and one
   *  event per pool — `event_ids` is what the overlay's undo reverts).
   *  Empty = the ranking's default pool. */
  rankingJudge: (id: number, a: number, b: number,
                 outcome: "a" | "b" | "tie" | "skip",
                 poolIds: number[] = []) =>
    req<{ ok: boolean; judgment_id: number; event_id: number | null;
          judgment_ids: number[]; event_ids: (number | null)[] }>(
      `/api/rankings/${id}/judge`, {
        method: "POST",
        body: JSON.stringify({ a_item_id: a, b_item_id: b, outcome,
                               pool_ids: poolIds }),
      }),
  rankingDismiss: (id: number, itemId: number) =>
    req<{ ok: boolean }>(`/api/rankings/${id}/dismiss`, {
      method: "POST", body: JSON.stringify({ item_id: itemId }),
    }),
  rankingUndismiss: (id: number, itemId: number) =>
    req<{ ok: boolean }>(`/api/rankings/${id}/undismiss`, {
      method: "POST", body: JSON.stringify({ item_id: itemId }),
    }),
  /** The score-tag chip's ✕: take the item out of the ranking — every
   *  comparison it was part of is deleted and the standings refit. */
  /** Where one picture stands on this axis — the item sidebar's Ranking tab,
   *  offered while a ranking's own view is the one you are in. */
  rankingItemStanding: (id: number, itemId: number) =>
    req<RankingItemStanding>(`/api/rankings/${id}/items/${itemId}`),
  rankingRemoveItem: (id: number, itemId: number) =>
    req<{ ok: boolean; removed: number }>(
      `/api/rankings/${id}/items/${itemId}`, { method: "DELETE" }),
  /** THE SAME THREE VERBS OVER ANY NUMBER OF PICTURES — a selection, or
   *  everything in the view. `items` names them; `view: true` means the
   *  scope this body carries, whose ids never reach the browser. Naming
   *  neither is refused by the server rather than guessed at. */
  rankingItemsVerb: (id: number, verb: "dismiss" | "undismiss" | "remove",
                     body: RankingItemsBody) =>
    req<{ count: number; total: number; judgments: number }>(
      `/api/rankings/${id}/items/${verb}`, {
        method: "POST",
        body: JSON.stringify({ ...body, groups: (body.groups ?? []).join(",") }),
      }),
  fileUrl: (fileId: number, rotation = 0) =>
    rotation ? `/api/files/${fileId}?r=${rotation}` : `/api/files/${fileId}`,
  /** A video's embedded subtitle stream as WebVTT (for a <track> element). */
  subtitleUrl: (fileId: number, stream: number) =>
    `/api/files/${fileId}/subtitle/${stream}`,
  artifactUrl: (artifactId: number) => `/api/artifacts/${artifactId}`,
  rotateItem: (itemId: number, dir: "left" | "right") =>
    req<{ ok: boolean; rotation: number }>(
      `/api/items/${itemId}/rotate?dir=${dir}`, { method: "POST" }
    ),
};

// `fmtDuration` moved to shared/time.ts (train's Evaluate tab needs it
// too, and shared may not reach back here); re-exported for the grid,
// the properties panel and the video editor.
export { fmtDuration } from "../shared/time";

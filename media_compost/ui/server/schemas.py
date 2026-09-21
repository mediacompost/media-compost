"""Pydantic request/response models for the API."""

from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import ConfigDict, BaseModel, Field

from media_compost.query import Group as QueryGroup


# ---- groups ----


class RequestModel(BaseModel):
    """A model that is a REQUEST BODY, and therefore refuses unknown fields.

    Pydantic ignores an unrecognized key by default, which for a body is the
    worst possible direction: the field lands nowhere, its default applies, and
    the request succeeds while doing something else. On a SEARCH body that is
    catastrophically quiet — a caller that misspells `query` gets no filter at
    all, so a request meaning "the portraits" answers with the whole library,
    and anything that then acts in bulk acts on all of it.

    Forbidding extras turns each of those into a 422 naming the field. The one
    thing it costs is tolerance for a client sending a key the server has
    dropped — a browser tab left open across a deploy — and there a visible
    error beats a silently different answer.

    RESPONSE models stay permissive: several are built from dicts that
    legitimately carry more than the model publishes (`EvalRunOut` from a
    training job's own JSON), and validating our own output is not the point.

    `tests/test_request_models_are_strict.py` walks the routes and holds every
    body model to this, so a new endpoint cannot quietly opt out.
    """

    model_config = ConfigDict(extra="forbid")


class GroupTagOut(BaseModel):
    name: str
    negative: bool


class GroupNode(BaseModel):
    id: int
    name: str
    icon: str
    color: Optional[str] = None
    # A SMART group: membership derived from its stored search, no manual
    # assignment, no child groups.
    smart: bool = False
    count: int
    # Tags this group assigns to its items (positive) or removes (negative).
    tags: list[GroupTagOut] = []
    children: list["GroupNode"] = []


class GroupCreate(RequestModel):
    name: str
    icon: str = "folder"
    parent_id: Optional[int] = None
    # A STRING makes the group SMART — the empty rule included — and None
    # makes it ordinary. That choice is fixed at creation.
    smart_query: Optional[str] = None


class GroupUpdate(RequestModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    # Empty string clears the color; None leaves it unchanged.
    color: Optional[str] = None
    # EDITS a smart group's rule (refused on an ordinary group — smart is
    # an identity); None leaves it unchanged.
    smart_query: Optional[str] = None


class GroupDetail(BaseModel):
    id: int
    name: str
    icon: str
    color: Optional[str] = None
    # The smart group's membership rule; None for an ordinary group.
    smart_query: Optional[str] = None
    # Current parent group (None = top level).
    parent_id: Optional[int] = None
    tags: list[GroupTagOut] = []


class GroupMove(RequestModel):
    # A group has at most one parent, so a move just re-parents it (None = root).
    new_parent_id: Optional[int] = None


class TagRowsIn(RequestModel):
    """The window the Tags tab is showing — see `routers/tags.tag_rows`."""

    ids: list[int] = []
    #: WHICH TAG SET the ids belong to: absent is the library's own
    #: names, an id is that imported set's. The rows carry what that
    #: tag set has to say — a library tag its counts and its records, a
    #: set's name what the set claims and whether the library agrees.
    set_id: Optional[int] = None


class GroupMerge(RequestModel):
    # The DESTINATION is the path id — the row the context menu was opened
    # on — so this names only what is being emptied into it.
    source_ids: list[int] = []


class GroupDuplicate(RequestModel):
    new_parent_id: Optional[int] = None


class GroupBulkMembership(RequestModel):
    """One request covering many (item, group) membership changes.

    Semantics mirror the single add/remove endpoints EXACTLY: one Event per
    (item, group) change with the same action/payload shape, no-ops skipped
    the same way — so History and revert behave identically."""
    item_ids: list[int] = []
    # Group ids to add every item to / remove every item from.
    add: list[int] = []
    remove: list[int] = []


# ---- items ----

class TagBox(BaseModel):
    id: Optional[int] = None
    # Bounding box as fractions of the image (0..1); all None for a pure time
    # annotation. ``time_start``/``time_end`` (seconds) apply to videos/frames.
    x: Optional[float] = None
    y: Optional[float] = None
    w: Optional[float] = None
    h: Optional[float] = None
    time_start: Optional[float] = None
    time_end: Optional[float] = None
    # Groups the timed boxes of one moving subject into a single video track
    # (null for a standalone box). See ItemTagBox.track_id.
    track_id: Optional[int] = None
    # A TIMED box carries its own sign: over a film a tag is present in some
    # stretches and pointedly absent in others. Meaningless on an untimed box,
    # whose sign is the item's.
    negative: bool = False
    # An optional POLYGON refining the rectangle: [[x, y], ...] vertices, at
    # least three, in the same frame as x/y/w/h. When set, the rectangle IS
    # its bounding box (the server derives it) — every rectangle reader stays
    # correct without knowing polygons exist.
    points: Optional[list[list[float]]] = None


class TagAssignment(BaseModel):
    name: str
    negative: bool
    count: int = 0
    # Bounding-box / time-range annotations for this tag on this item.
    boxes: list[TagBox] = []


class TagGroupOut(BaseModel):
    """A per-item, named group of tag instances (see ItemTagGroup)."""
    id: int
    name: str
    # True for the auto-managed "Pending" group (machine tags awaiting approval):
    # no adder, tags shown with approve/dismiss actions.
    system: bool = False
    # Meta tags on the grouping itself — the same namespace links and captions
    # use, not the item's own tags.
    tags: list[str] = []
    # Subjects this grouping is ABOUT (her tags / his tags). Organizational
    # only: the grouped tags stay the item's, never the subject's attributes.
    subjects: list[int] = []


class TagGroupSubjectBody(RequestModel):
    subject_id: int


class TagInstance(BaseModel):
    """One placement of a (direct) tag into a tag group — or the ungrouped
    default (``group_id`` None) — with that instance's own boxes."""
    # Placement id (None for a purely implicit ungrouped instance with no boxes).
    placement_id: Optional[int] = None
    name: str
    negative: bool
    group_id: Optional[int] = None
    # True for a machine-generated tag awaiting approval.
    pending: bool = False
    boxes: list[TagBox] = []


class ItemOut(BaseModel):
    id: int
    # The item's UID, not its rowid. Anything that has to NAME this item in a
    # query string uses it — `INFO:id=`, `SIMILAR:` — because a rowid is
    # reused after a delete and a uid never is, which is also what lets such a
    # query survive in a saved search.
    uid: str = ""
    name: str
    # "image", "video", or "sequence" (a container that opens like a folder);
    # drives the grid badge, the editor/folder action, and card rendering.
    kind: str = "image"
    # For a "sequence" item: the sequence it represents (double-click opens it).
    sequence_id: Optional[int] = None
    # Video length in seconds (None for images) for the grid overlay.
    duration: Optional[float] = None
    width: int
    height: int
    megapixels: float
    # Non-destructive display rotation of the active file (0/90/180/270,
    # clockwise). width/height above are already in the rotated orientation; the
    # frontend also uses this to cache-bust the thumbnail and rotate full previews.
    rotation: int = 0
    active_file_id: Optional[int]
    # Short content hash of the active file, used by the grid to cache-bust the
    # thumbnail URL: it changes whenever the file's *content* does — including a
    # reused file rowid pointing at different bytes — so the browser never keeps
    # showing a stale cached thumbnail for the same id.
    thumb_token: str = ""
    file_count: int
    alt_count: int
    # Hidden from the grid and category counts (shown only in the Hidden view).
    hidden: bool = False
    link_item_id: Optional[int]
    group_ids: list[int]
    # Position (1-based) and length of the item's main sequence, for the grid
    # number badge. ``seq_index`` is None when the item is in no sequence.
    seq_index: Optional[int] = None
    seq_total: int = 0
    # How many sequences this item is a member of. When >1 the grid shows a
    # sequence-count badge instead of the position badge.
    seq_count: int = 0
    # WHICH OCCURRENCE this card is, inside an open sequence view: the
    # membership row's id. A book's repeated blank page is several cards,
    # one per position, and they are the same ITEM — so the id cannot be
    # what keys them apart (React keys, and the drag's payload). None
    # outside a sequence view, where a card is simply an item.
    member_id: Optional[int] = None
    # Tags assigned directly to this item (with sign). Drives the grid's
    # Quick-Assign indicator; group-inherited tags are intentionally excluded.
    direct_tags: list[TagAssignment] = []
    # Effective positive tags (direct + group-inherited, minus negatives). Drives
    # the grid's "matches the selected tags" highlight, which must also count
    # tags an item inherits from its groups.
    eff_tags: list[str] = []
    # Effective *negative* tags (direct + group-inherited negatives). Lets the
    # grid highlight items whose tag matches the selected sign, negatives too.
    eff_neg: list[str] = []
    # For a "sequence" item: active file ids of its first four members, so the
    # grid can render a 2×2 mosaic thumbnail. Empty for non-sequence items.
    member_thumbs: list[int] = []


class ItemPage(BaseModel):
    items: list[ItemOut]
    total: int
    page: int
    page_size: int
    # The library revision this page describes (see `routers/items.library_rev`).
    # The grid compares it across the pages it has assembled: a window mixing
    # two revisions is describing an ordering that no longer exists — an
    # EXTERNAL writer (a script importing in the background) shifts a
    # newest-first view under offset pagination, and no invalidation ever
    # arrives from a writer the app cannot see.
    rev: str = ""


class ItemSearchRequest(RequestModel):
    """The POST body for a structured item search: scope + the parsed condition
    tree + pagination/sort. The tree is evaluated as-is; the backend never parses
    a query string."""
    query: Optional[QueryGroup] = None
    groups: str = ""
    ungrouped: bool = False
    untagged: bool = False
    trash: bool = False
    hidden: bool = False
    show_hidden: bool = False
    kind: str = ""
    sequence: Optional[int] = None
    #: Drop every item that belongs to a sequence, whatever else is on
    #: screen — the three sessions' "Skip pictures in sequences", where the
    #: question is about the picture alone.
    hide_sequenced: bool = False
    #: THE GRID'S "FOLD SEQUENCES": drop a member exactly where a sequence
    #: holding it has its CONTAINER in this same view, so a chapter and its
    #: pages are not both on screen — and the pages stay wherever the
    #: chapter is not shown (a group holding them but not it, a media-kind
    #: filter with sequences unticked). Unlike every other field here it is
    #: not a fact about the item: it asks this view's own where list again,
    #: of the containers (`prefilter.fold_sequenced_clause`).
    fold_sequenced: bool = False
    #: A RANKING'S OWN VIEW: the items it has placed, in its standings order,
    #: best first — and `ranking_pool` narrows that to one pool's fit.
    #: The scope is the JOIN rather than a clause, since a standing is fitted
    #: on read and stored nowhere, so there is no column to sort by
    #: (`ops/search._ranking_scope`, `prefilter.materialize_ranking`).
    #:
    #: IT RIDES THIS MODEL, so it reaches every request that inherits it —
    #: the search, the id range, the group runs, the facets AND the
    #: whole-view writes (`QuickAssignView`, `EnqueueScope`, the hide/trash
    #: buttons). That is the point: a scope one of those ignored would hide
    #: or trash the whole library from a button that said 47.
    ranking: Optional[int] = None
    ranking_pool: Optional[int] = None
    #: The ranking's SET-ASIDE pictures instead of its placed ones — the
    #: "Not applicable" row under a ranking in the sidebar. Ranking-wide,
    #: never per pool, and with no standing to order by, so it is a plain
    #: membership scope and the sort control stays live.
    ranking_dismissed: bool = False
    pending: bool = False
    pending_kind: str = ""
    page: int = 1
    page_size: int = 60
    sort: str = "import_desc"


class ItemIdRangeRequest(ItemSearchRequest):
    """A stretch of the view's ORDER, by id and nothing else.

    What a shift+click needs when the other end has scrolled out of the
    loaded pages: the ids between two positions, which the browser cannot
    know because it holds only what it has drawn. `page`/`page_size` ride
    along from the parent and are ignored — the window is `start`/`count`,
    which is a flat index into the same order `sort` gives the grid.

    A read-only POST, named in `build.READ_ONLY_POSTS`."""
    start: int = 0
    count: int = 0


class ItemIndexRequest(ItemSearchRequest):
    """WHERE THESE ITEMS SIT in the view's order — the flat indices the grid
    pages by, and `null` for one the view does not hold at all.

    What the bookmarks need, and they need both halves of it: which of them
    this view even contains (that is the list the dropdown shows) and, for
    the one that is picked, which row to scroll to. The browser can answer
    neither — it holds the pages it has drawn, and the order is the sort's
    rather than the id's.

    Several ids at once because the first question is about all of them: one
    request per bookmark would be one walk of the view per bookmark.

    A read-only POST, named in `build.READ_ONLY_POSTS`."""

    item_ids: list[int] = []


class ItemIndexes(BaseModel):
    #: One answer per id in the request, IN THAT ORDER: the item's position
    #: in this view counted from 0, or null where the view does not hold it
    #: (hidden, trashed, or simply not in this scope). Null is an ANSWER —
    #: the caller leaves that bookmark out rather than scrolling somewhere
    #: arbitrary.
    indices: list[int | None] = []


class ItemIdRange(BaseModel):
    ids: list[int] = []
    #: How long the range REALLY is. `ids` is capped (see the endpoint), and
    #: a caller that asked for more than it got can say so rather than
    #: quietly believing the short answer.
    total: int = 0


class GroupAssignView(ItemSearchRequest):
    """Group membership aimed at a WHOLE VIEW rather than a list of ids.

    "A group from the current items" can mean the entire library, so the
    browser sends the scope it is showing and the server resolves it — the
    same shape (and the same reasoning) as :class:`QuickAssignView`.
    ``page``/``page_size``/``sort`` ride along and are ignored."""


class ItemGroupRunsRequest(ItemSearchRequest):
    """The POST body for the grid's group runs: the same view as a page
    request, plus which coarsening to cut it into. Inheriting the search
    request is what guarantees the runs describe the SAME scope, query and
    sort the pages do — a second flat body would be a second place to keep
    every scope flag in step."""
    group_by: str = ""


class GroupRun(BaseModel):
    # One section of the grid. `key` is machine-readable and never a label:
    # month and colour names have to be localized, and the frontend is where
    # the date formatters and the colour tag set live.
    key: str
    count: int


class ItemGroupRuns(BaseModel):
    group_by: str
    total: int
    # Same revision the pages carry; the grouped layout and the pages must
    # describe the same library state or the sections misplace every card.
    rev: str = ""
    # In the page order, so the counts prefix-sum into each section's span.
    runs: list[GroupRun]


class FileNameEntry(BaseModel):
    # A recorded source of this file: an imported/added filename (with path), or
    # a web URL. For a URL source ``is_url`` is set (``name`` holds the URL) and
    # ``accessed_at`` is an optional ISO access date/time.
    id: int
    name: str
    is_url: bool = False
    accessed_at: Optional[str] = None


class FileArtifactOut(BaseModel):
    """Something generated from a source file and stored beside it: a depth map
    or pose overlay, or a cached training latent. Shown nested under its source
    file in the Source list."""
    id: int
    kind: str            # "depth" | "pose" | "latent" | …
    model: str = ""      # human label of the model that produced it
    # For a cached training latent, which of a file's entries this is
    # ("flipped", "masked", "flipped, masked"). Empty for everything else.
    variant: str = ""
    width: int
    height: int
    bytes: int
    format: str = "png"
    # True when the source file was edited after this was generated, so it no
    # longer matches the current pixels.
    stale: bool = False
    # Artifacts generated from THIS one rather than from the source file: the
    # latents encoded from a degraded copy of the picture. One level only —
    # nothing here is derived from a latent.
    children: list["FileArtifactOut"] = Field(default_factory=list)


class FileVersion(BaseModel):
    id: int
    width: int
    height: int
    bytes: int
    format: str
    is_derived: bool
    active: bool
    # How the file's bytes are obtained: "stored" | "video_frame" | "video_clip".
    source_kind: str = "stored"
    # Video properties (populated for stored videos and clips).
    duration: Optional[float] = None
    frame_rate: Optional[float] = None
    bitrate: Optional[int] = None
    # Timestamp (frame) or range (clip) in seconds, for the Source list label.
    source_start: Optional[float] = None
    source_end: Optional[float] = None
    # True when this file is an edited/derived version (shown as "edited").
    edited: bool = False
    # Stable per-item source-file number (#1, #2, #3 …).
    number: Optional[int] = None
    # For an edited file: the number of the file it is currently based on (its
    # live parent — the grandparent after a middle file was deleted) and the
    # action that produced it. Null/empty for imports and rotations.
    based_on: Optional[int] = None
    edit_action: str = ""
    # The full historical lineage of edit steps ({"from","to","action"} by file
    # number), preserved even when an intermediate file is deleted.
    edit_chain: list[dict] = []
    # Orientation of the stored bytes relative to the item's first source file:
    # clockwise degrees (0/90/180/270) plus a pre-rotation horizontal mirror.
    rotation: int = 0
    mirrored: bool = False
    # The file's region of the item's reference frame (for tag-box alignment).
    crop_x: float = 0.0
    crop_y: float = 0.0
    crop_w: float = 1.0
    crop_h: float = 1.0
    # When this file's bytes were created: the import time for a source file, or
    # the save time for an edited/derived file (ISO 8601). Shown in the Source list.
    created_at: Optional[str] = None
    # The source filename(s) this file was seen under.
    names: list[FileNameEntry] = []
    # Auxiliary images generated from this file (depth maps, pose overlays),
    # shown nested under it in the Source list.
    artifacts: list[FileArtifactOut] = []


class MetadataSource(BaseModel):
    """WHICH of the item's files says this. ``number`` is the per-item file
    number the Files tab and the header's file chip already name files by."""
    file_id: int
    number: Optional[int] = None
    active: bool = False


class MetadataField(BaseModel):
    key: str
    value: str
    # For a datetime field: the parsed ISO-8601 value, which the frontend
    # reformats per the user's date/time preferences and can filter on (`taken`).
    iso: Optional[str] = None
    # The canonical search-catalog name (`INFO:<name>`), or None where the row
    # has none — a sequence's member count, the item's own last-modified stamp.
    #
    # This REPLACED the frontend's `CATALOG_KEY` table, which existed only
    # because the endpoint used to return EXIF tag names and the search wanted
    # catalog names; the backend has always known the answer.
    name: Optional[str] = None
    # What the `INFO:<name>=` atom must carry. The display string is written
    # for a person ("4000 px", "1:35", "1/125"); this is what the index holds
    # ("4000", "95", "0.008"), so the filter button never parses a label back
    # into a value — which is what `NUM_FIELD` used to do.
    #
    # A STRING deliberately: `query/tree.ts:numTolerance` derives a numeric
    # condition's tolerance from the decimal places in the written atom, so
    # serving a float and letting JSON print it would silently change which
    # pictures the filter matches. The server chooses the precision.
    #
    # None means "the shown value is NOT what search would find this item by" —
    # a value only an unpinned, non-active file carries. The frontend draws the
    # filter button iff `name && filter_value`.
    filter_value: Optional[str] = None
    # True when this row is a value promoted to the ITEM (an `ItemMetaPin`).
    pinned: bool = False
    # True when the active file says this and the item has muted it: still
    # SHOWN — struck through, with a way back — and not searchable.
    muted: bool = False
    # The files that give this value. Empty for an intrinsic row, which is a
    # property of whichever file is active rather than a claim about the
    # picture, and so can be neither pinned nor muted.
    sources: list[MetadataSource] = []


class ItemMetadataOut(BaseModel):
    """The Info tab. ``fields`` is the main section — what the item answers
    with — and ``others`` is every value only a NON-ACTIVE file carries, which
    is offered rather than applied: metadata from another file is never added
    to the main section until somebody pins it."""
    fields: list[MetadataField] = []
    others: list[MetadataField] = []


class PinMetadataIn(RequestModel):
    """Promote what one FILE says about ``name`` onto the item.

    A file id rather than a value string: the pin stores the typed row, and
    re-deriving a type from a wire string is how a numeric name quietly becomes
    a text one."""
    name: str
    file_id: int


class UnpinMetadataIn(RequestModel):
    """Take one promoted value off the item. ``raw`` names WHICH — a name may
    carry several pins — and empty means all of that name's."""
    name: str
    raw: str = ""


class MuteMetadataIn(RequestModel):
    """Stop taking ``name`` from the item's active file, or start again."""
    name: str


# ---- tag sets ----

class TagSetOut(BaseModel):
    id: int
    key: str
    name: str
    description: str = ""
    version: int = 0
    #: ONE OF THE LISTS THE APP SHIPS. Read-only — no rename, no entry, no
    #: category — but exported, duplicated into a copy you can edit, ordered,
    #: switched on and off, and its two advice flags are yours. It holds no
    #: entry until it is switched on.
    builtin: bool = False
    #: A BUILT-IN WHOSE SHIPPED FILE HAS MOVED SINCE ITS ENTRIES WERE WRITTEN.
    #: The row says so and the ⋯ offers Update; nothing rewrites it on its
    #: own, because that would be a hundred thousand rows at the first open
    #: after an upgrade. Only a row that HOLDS entries can be behind — an
    #: empty one takes the current file whenever it is switched on.
    outdated: bool = False
    enabled: bool = True
    #: Whether the set's alias spellings are offered and its entries' implied
    #: names are minted. The ROOT of the three-state walk the categories do.
    aliases_enabled: bool = True
    implications_enabled: bool = True
    position: int = 0
    entries: int = 0
    categories: int = 0
    #: THE LIBRARY'S OWN — the first pill, which is not a tag set somebody
    #: imported. It holds no entries (its names are the `tags` table, which is
    #: what the Items list draws); what it owns is the CATEGORIES the
    #: library's tags are filed in. Hidden, deleting and duplicating are not
    #: offered on it, and `entries` is the tag count rather than a row count.
    library: bool = False


class TagSetCategoryOut(BaseModel):
    id: int
    parent_id: Optional[int] = None
    name: str
    #: The tree row's glyph; "" is the folder.
    icon: str = ""
    #: Kept out of the autocomplete, with everything under it. The Sets tab
    #: shows it as ever — this says what is OFFERED, never what exists — and
    #: the browse tree simply never carries a hidden row.
    hidden: bool = False
    #: THREE-STATE for this branch: true offers / mints, false does not, and
    #: null takes the parent's answer (the set's flag at the root).
    aliases: Optional[bool] = None
    implications: Optional[bool] = None
    position: int = 0
    #: The names down to this category, outermost first — never a joined
    #: path, since a category name may itself hold a "/". The UI draws it
    #: with chevrons between the names.
    trail: list[str] = []
    #: Entries in this category AND under it — what clicking it in the Sets
    #: tab's tree lists (`GET /entries?subtree=true`), so the number beside
    #: the row promises what the click shows. A category implicitly holds
    #: its sub-categories' entries; the browse tree's per-node figure is the
    #: DIRECT one, since its sub-category rows lead to the rest.
    count: int = 0


class TagSetTreeCategory(TagSetCategoryOut):
    #: DIRECT entries in this category (children's are their own).
    entries: int = 0


class TagSetTreeSet(BaseModel):
    """One ENABLED set for the fields' browse mode: its categories (flat rows
    with `parent_id`; the frontend flattens) and how many entries sit in no
    category at all."""
    id: int
    key: str
    name: str
    categories: list[TagSetTreeCategory] = []
    uncategorized: int = 0
    entries: int = 0


class TagSetTreeOut(BaseModel):
    sets: list[TagSetTreeSet] = []


class TagSetDetail(TagSetOut):
    """The set with its category tree (flat rows carrying `parent_id`; the
    frontend flattens with `treeRows.ts`)."""
    category_rows: list[TagSetCategoryOut] = []
    #: Entries in no category — the tree's last row.
    uncategorized: int = 0
    #: How many entries are a subject / a place / an event. The sidebar
    #: draws a row per kind that has any: a tag set of people is read
    #: as people, and hunting for them through a category tree somebody
    #: else authored is not reading it.
    record_counts: dict[str, int] = {}


class TagSetCreate(RequestModel):
    name: str
    key: str = ""
    description: str = ""


class TagSetUpdate(RequestModel):
    name: Optional[str] = None
    description: Optional[str] = None
    version: Optional[int] = None
    position: Optional[int] = None
    aliases_enabled: Optional[bool] = None
    implications_enabled: Optional[bool] = None


class TagSetEnabled(RequestModel):
    enabled: bool


class TagSetDuplicate(RequestModel):
    name: str = ""
    key: str = ""


class TagSetImportIn(RequestModel):
    """A tag-set FILE (`tagsetformat`), validated by the op. `create` makes a
    new set from it; `merge` adds what `target_id` lacks; `replace` empties
    the target first (and is not revertible)."""
    document: dict
    mode: Literal["create", "merge", "replace"] = "create"
    target_id: Optional[int] = None


class TagSetImportOut(BaseModel):
    set: TagSetOut
    created: int = 0
    updated: int = 0
    errors: list[dict] = []


class TagSetSubjectIn(RequestModel):
    """What a set says about a name that is SOMEBODY. Every field optional:
    an empty object still says "this is a person", which is the whole of
    what a tag set often knows."""
    #: The display name where it differs from the tag; "" is the tag's own.
    name: str = ""
    #: A partial date, the library's own `YYYYMMDD` with zeros.
    since: Optional[int] = None


class TagSetPlaceIn(RequestModel):
    #: What the place is CALLED — one line, an address or "Bob's house".
    #: `Location.name` in the library, and the same word everywhere else.
    name: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None
    #: The place this one is IN, by its TAG name — applied only where the
    #: library already has that place.
    parent: str = ""


class TagSetEventIn(RequestModel):
    name: str = ""
    start: Optional[int] = None
    end: Optional[int] = None
    parent: str = ""


class TagSetEntryOut(BaseModel):
    id: int
    name: str
    description: str = ""
    count: Optional[int] = None
    category_id: Optional[int] = None
    #: Where the set files this entry — the names down to its category,
    #: outermost first, empty for an uncategorized one.
    category_trail: list[str] = []
    position: int = 0
    #: THE NAME THIS ROW SPELLS, where the row is an ALIAS — the library
    #: tag row's own `alias_of`, and drawn the same way: the arrow after
    #: the name, the target in accent, a press jumping to it. An alias is
    #: a ROW of the list here, so the list is the tag set's names and
    #: nothing is folded into anything else.
    alias_of: Optional[str] = None
    #: The OTHER SPELLINGS of this entry, where the row is an entry. The
    #: row does not draw them any more (they are rows of their own); the
    #: editor and the file still hold them as a list on the entry.
    aliases: list[str] = []
    #: The tags this entry ENTAILS, by name — minted and linked when the
    #: entry's name is first assigned.
    implies: list[str] = []
    #: Those of `implies` the LIBRARY does not entail: the library has this
    #: tag, and it does not (even through a chain) imply these. The row
    #: strikes them through — they are advice nothing has acted on, since a
    #: set's implications reach the library only when the door CREATES the
    #: tag. Empty for a name the library has never heard of, which is not
    #: behind but simply unassigned.
    missing_implies: list[str] = []
    #: The META TAGS the set says this name carries — labels about the
    #: NAME ("character", "noflip"), never about a picture. Put on the
    #: library's tag as ordinary logged assignments when the door creates
    #: it, like `implies`.
    meta: list[str] = []
    #: This entry's implications are switched OFF — by its category, one
    #: above it, or the whole set. They mint nothing, so the row does not
    #: draw them at all: a list of names that will never be acted on reads
    #: as a promise. The editor still shows and edits them, which is where
    #: the switch can be turned back on.
    implications_off: bool = False
    #: The LIBRARY has this tag (or an alias resolving to it). A row that
    #: does not offers to ADD it instead of offering to do anything about
    #: its implications: a set is advice, and until the tag exists there
    #: is nothing for the advice to be about.
    in_library: bool = False
    #: HOW MANY PICTURES THE LIBRARY HAS under this name — the `Library`
    #: column. Null where the library does not have the name at all, which
    #: is not the same as 0: zero is a tag that exists and is on nothing.
    #: An alias answers with its target's count, as the row does everywhere.
    library_count: Optional[int] = None
    #: WHAT THE SET SAYS THE TAG IS — the one-liner it should carry, and
    #: whether it is a subject, a place or an event. `description` above is
    #: the set's own words about the name and stays in the set; these are
    #: advice about the library's tag, applied at the door and by the sync.
    #: A record present but EMPTY says the kind and nothing more.
    comment: str = ""
    subject: Optional[TagSetSubjectIn] = None
    place: Optional[TagSetPlaceIn] = None
    event: Optional[TagSetEventIn] = None
    #: Which of `comment`/`subject`/`place`/`event` the library's tag does
    #: NOT have — `missing_implies` for the other kind of advice. Empty for
    #: a name the library has never heard of, which is unassigned rather
    #: than behind.
    missing_records: list[str] = []


class TagSetMetaTagOut(BaseModel):
    """One META TAG of a tag set — a label it puts on its own names.

    The set's answer to the library's `/api/link-tags/rows`: same namespace
    shape, one tag set along. `uses` is how many of the SET's entries
    carry it, which is the only count a set can honestly give — what the
    library does with the label is the library's own row.
    """
    id: int
    name: str
    comment: str = ""
    description: str = ""
    uses: int = 0


class TagSetMetaTagCreate(RequestModel):
    name: str
    comment: str = ""
    description: str = ""


class TagSetMetaTagUpdate(RequestModel):
    name: Optional[str] = None
    comment: Optional[str] = None
    description: Optional[str] = None


class TagSetEntriesOut(BaseModel):
    rows: list[TagSetEntryOut] = []
    total: int = 0


class TagSetSyncIn(RequestModel):
    #: The entries to sync, by id. Empty is nothing, never everything.
    entry_ids: list[int] = []
    #: `append` adds what the sets say and leaves everything else; `replace`
    #: makes each tag's implications exactly what the sets say.
    mode: Literal["append", "replace"] = "append"


class TagSetSyncOut(BaseModel):
    #: Tags the sync actually spoke for — a name the library does not have,
    #: or that no enabled set says anything about, is `skipped` instead.
    tags: int = 0
    added: int = 0
    removed: int = 0
    skipped: int = 0


class TagSetAddIn(RequestModel):
    #: The entries whose tags to put in the library, by id.
    entry_ids: list[int] = []


class TagSetAddOut(BaseModel):
    #: Tags created. A name the library already has is `skipped`.
    added: int = 0
    skipped: int = 0


class TagSetEntryCreate(RequestModel):
    name: str
    description: str = ""
    count: Optional[int] = None
    category_id: Optional[int] = None
    aliases: list[str] = []
    implies: list[str] = []
    meta: list[str] = []
    comment: str = ""
    subject: Optional[TagSetSubjectIn] = None
    place: Optional[TagSetPlaceIn] = None
    event: Optional[TagSetEventIn] = None


class TagSetRecordsIn(RequestModel):
    """The three records of one entry, each three-state: absent (this edit
    is not about it), null (take it away) or an object (this is it)."""
    subject: Optional[TagSetSubjectIn] = None
    place: Optional[TagSetPlaceIn] = None
    event: Optional[TagSetEventIn] = None
    #: Which of the three this request is ABOUT — the only way to tell
    #: "take the place away" (named, null) from "leave the place alone"
    #: (not named), since JSON's null and an absent key reach Pydantic the
    #: same way.
    kinds: list[Literal["subject", "place", "event"]] = []


class TagSetEntryUpdate(RequestModel):
    """A field left out is left alone; `clear_count` / `clear_category` say
    "take it away", which an absent Optional cannot.

    The three records are the same shape one level down: `records` names the
    kinds this edit is about, and a kind named as `null` is taken away. A
    request that names none touches none — so a script setting a count
    cannot silently drop somebody's place.
    """
    name: Optional[str] = None
    description: Optional[str] = None
    count: Optional[int] = None
    clear_count: bool = False
    category_id: Optional[int] = None
    clear_category: bool = False
    aliases: Optional[list[str]] = None
    implies: Optional[list[str]] = None
    meta: Optional[list[str]] = None
    comment: Optional[str] = None
    records: Optional[TagSetRecordsIn] = None


class TagSetBulkRowIn(RequestModel):
    name: str
    description: Optional[str] = None
    count: Optional[int] = None
    #: The trail of names down to the category, MADE where it does not
    #: exist. A list, not a path: one of those names may hold a "/".
    category: Optional[list[str]] = None
    aliases: list[str] = []
    implies: list[str] = []
    #: What the set says the LIBRARY's tag should be. `existing` decides
    #: what happens to a row the set already has, records included — and a
    #: record is taken WHOLE or not at all, since half of one file's place
    #: beside half of another's is an address nobody wrote down.
    comment: Optional[str] = None
    subject: Optional[TagSetSubjectIn] = None
    place: Optional[TagSetPlaceIn] = None
    event: Optional[TagSetEventIn] = None


class TagSetBulkIn(RequestModel):
    rows: list[TagSetBulkRowIn]
    existing: Literal["keep", "update", "replace"] = "keep"


class TagSetBulkOut(BaseModel):
    created: int = 0
    updated: int = 0
    errors: list[dict] = []


class TagSetCategoryCreate(RequestModel):
    name: str
    parent_id: Optional[int] = None
    icon: str = ""
    hidden: bool = False
    aliases: Optional[bool] = None
    implications: Optional[bool] = None


class TagSetCategoryMove(RequestModel):
    """The tree's drag: under `parent_id` (null = the top) at `index`."""
    parent_id: Optional[int] = None
    index: int = 0


class TagSetCategoryUpdate(RequestModel):
    name: Optional[str] = None
    parent_id: Optional[int] = None
    clear_parent: bool = False
    icon: Optional[str] = None
    hidden: Optional[bool] = None
    #: THREE-STATE, so `null` is a VALUE — "inherit from the parent" — and
    #: cannot double as "leave alone". `clear_aliases` / `clear_implications`
    #: are how a caller asks for the null, the way `clear_parent` does.
    aliases: Optional[bool] = None
    clear_aliases: bool = False
    implications: Optional[bool] = None
    clear_implications: bool = False
    position: Optional[int] = None


class TagSetOrderIn(RequestModel):
    """The caller's preferred order of tag sets for the `?` popover — which
    set's description shows first. Per user."""
    keys: list[str]


class TagSetOrderOut(BaseModel):
    keys: list[str]


class SavedSearch(BaseModel):
    """A named, persisted query. The ``query`` is the frontend's serialized string
    form, stored opaquely — the backend never parses it."""
    name: str
    query: str


class MetadataCatalogEntry(BaseModel):
    """One filterable metadata name in the library catalog: its canonical name,
    value type, and how many items carry it. Intrinsic (live) and indexed
    (import-time) names appear together — the UI can't tell them apart."""
    name: str
    mtype: str  # numeric | text | date
    count: int
    # Numeric/date range hints for the value input (None for text or when empty).
    num_min: Optional[float] = None
    num_max: Optional[float] = None
    # For an *enumerated* text name (few distinct values in the library, e.g.
    # format / mode), the sorted list of values — the UI offers a dropdown
    # instead of a free-text field. None for free-form or high-cardinality text.
    values: Optional[list[str]] = None


class TrackMeta(BaseModel):
    label: str
    value: str


class MediaTrack(BaseModel):
    index: int
    kind: str  # video | audio | subtitle | data
    codec: str
    detail: str = ""
    language: Optional[str] = None
    # The track's name/title (e.g. a subtitle "Signs" track), when present.
    title: Optional[str] = None
    # Whether this track plays/shows by default (container default disposition).
    default: bool = False
    # Per-track metadata rows (dimensions, frame rate, bitrate, channels, …).
    meta: list[TrackMeta] = []


class MediaTracks(BaseModel):
    tracks: list[MediaTrack] = []


class IndirectGroupTags(BaseModel):
    group_id: int
    group_name: str
    tags: list[str]
    # True when this group assigns the tags negatively (marks them removed).
    negative: bool = False
    # Where these tags come from: "group" (a library group), "parent" (implied
    # by the tag hierarchy via Tag.parent_id), or "sequence" (a sequence's
    # member tags). Drives the sidebar's read-only group icon/label.
    source: str = "group"
    # Subset of ``tags`` the item also assigns *directly* — the sidebar greys
    # these out (they're overridden by the explicit direct assignment).
    overridden: list[str] = []
    # For the "parent" source: tag name -> the assigned descendant tag(s) that
    # entail it (shown as the reason next to a hierarchy-implied tag).
    sources: dict[str, list[str]] = {}


class CaptionRefOut(BaseModel):
    """One reference image of an instruction, at its place in the order. Same
    three identity fields a link row hydrates, for the same reason: the row
    shows a thumbnail and a name."""
    item_id: int
    item_uid: str = ""
    name: str = ""
    file_id: Optional[int] = None


class CaptionOut(BaseModel):
    id: int
    text: str
    # "caption" describes the picture; "instruction" says how it was made from
    # `refs`. The two are separate lists in the sidebar and separate training
    # sources — never mixed.
    kind: str = "caption"
    # True for a machine-generated caption awaiting approval.
    pending: bool = False
    # Human-readable name of the AI model that generated it ("" for hand-written).
    model: str = ""
    # True once a generated caption has been edited by the user.
    edited: bool = False
    # Meta tags on this caption — same namespace as a link's tags.
    tags: list[str] = []
    # An instruction's source images, IN ORDER. Always empty for a caption.
    refs: list[CaptionRefOut] = []


class ModelInfo(BaseModel):
    id: str
    name: str
    available: bool
    note: str = ""
    # Reference URL, surfaced for unavailable models.
    url: str = ""
    # Model family + variant, so the action menu can group variants under one
    # family header instead of repeating the family name on every row.
    family: str = ""
    variant: str = ""
    # The downloadable-family key this model belongs to, so the action menu can
    # join with the per-model cache status. "" when none. `family_keys` lists ALL
    # sources the model needs (e.g. watermark removal needs a detector + an
    # inpainter); the action menu stays "needs download" until every one is cached.
    family_key: str = ""
    family_keys: list[str] = []
    # Plugin key whose setup commands the "Run setup" button executes (empty
    # when the plugin has nothing runnable).
    setup_key: str = ""
    # True when a run needs a user-picked color-reference image: the UI opens
    # the reference picker before enqueueing.
    needs_reference: bool = False


class TaskInfo(BaseModel):
    """An AI action (task) plus its available models, so the UI renders actions
    data-driven rather than hardcoding them."""
    kind: str
    label: str
    icon: str            # Material Symbols Rounded name
    result: str          # "image" | "caption" | "tags"
    #: The `panels` task's one switch (gather the panels into a sequence).
    #: The only extra output an action offers — see `plugins/tasks.py`.
    sequence_option: bool = False
    models: list[ModelInfo]


class ModelsOut(BaseModel):
    """The AI actions offered, each with its models."""
    tasks: list[TaskInfo]
    #: Background-job kinds that are NOT AI actions (a video render). Their own
    #: field, not extra entries in `tasks`: that list is what the action menus
    #: are built from and what the fixed-set test pins, and a video render is
    #: neither. The background-task list reads both, because both can be a row
    #: in it and a row needs a label.
    job_kinds: list[TaskInfo] = []


class EnqueueJobs(RequestModel):
    kind: str  # a plugins.tasks task kind (bg_removal | watermark_removal | tag | caption)
    model: str = ""
    item_ids: list[int]
    # `panels` only: gather the detected panels into a SEQUENCE of their own,
    # beside the items it makes either way. Every other action's result lands
    # on the item it ran on, with nothing to choose.
    into_sequence: bool = False
    # Reference image id (a file in the refs store) for reference-guided models.
    reference: str = ""
    # Leave out the items this model has already been run over — for the
    # kinds that record a per-item run (`ItemFaceRun` / `ItemTextRun`), which
    # are the kinds asked over whole groups, where re-running everything is
    # the difference between minutes and hours.
    skip_done: bool = False
    # TEXT REMOVAL ONLY: an OCR model to READ the page with before painting
    # out what it finds. The removal itself never detects — it consumes the
    # item's stored text regions — so this is how "detect and remove" is one
    # job, and the reading it makes is kept (it lands in the Text tab, where
    # it can be corrected before a second pass).
    detect_with: str = ""


class EnqueueScope(RequestModel):
    """Enqueue a job kind over everything in the given groups' SUBTREES,
    resolved server-side — the browser would have to fetch every member to
    build an ``item_ids`` list, and a group can hold thousands. Trashed and
    hidden items are excluded, mirroring what the grid shows."""
    kind: str
    model: str = ""
    groups: list[int] = []
    # One of the sidebar's FIXED entries instead: "all" | "image" | "video" |
    # "sequence" | "untagged" | "ungrouped" | "pending" | "hidden". Resolved
    # through `search_filtered` — the grid's own semantics, so the run covers
    # exactly what that row shows. (`all_images` predates this and is kept:
    # it is the same scope `view="image"` names.)
    view: str = ""
    # Same semantics as EnqueueJobs.skip_done (the per-item-run kinds).
    skip_done: bool = False
    # Same semantics as EnqueueJobs.detect_with (text removal's "read it,
    # then remove") — the context menus offer the pairing over a scope too.
    detect_with: str = ""
    # Same semantics as EnqueueJobs.into_sequence (`panels` only). Defaulted
    # OFF, so a caller that does not mention it enqueues what it always did.
    into_sequence: bool = False


class EnqueueView(ItemSearchRequest):
    """The same enqueue, aimed at a WHOLE VIEW rather than a list of ids.

    `QuickAssignView`'s bargain, one subsystem along: with nothing selected
    the sidebar's actions are about everything the grid is showing, and that
    view can be the whole library — a million ids is not something a request
    body can carry, and enumerating them in the browser would mean paging the
    library first. So the SCOPE travels and the server resolves it, through
    the very same `search_filtered` the grid pages through.

    `EnqueueScope` answers a narrower question (a group subtree, or one of the
    sidebar's fixed rows) and stays: those scopes have no search body to send.

    **THE TASK KIND IS `task_kind`, NOT `kind`.** The search body already
    owns `kind` — the ITEM kind the view is filtered to — so declaring the
    job kind under that name shadows it, and `kind="faces"` silently reads as
    "the view of items whose kind is faces", i.e. nothing at all. It answers
    200 with `queued: 0`, which is indistinguishable from an empty view. Same
    trap `QuickAssignView.assign_groups` is named apart from `groups` for, and
    `tests/ui/test_view_actions.py` holds every model here to it.
    """

    task_kind: str
    model: str = ""
    into_sequence: bool = False
    reference: str = ""
    skip_done: bool = False
    detect_with: str = ""


class ViewGroupMembership(ItemSearchRequest):
    """Group memberships over a whole view. Group ids; a smart group in
    either list is refused exactly as a manual membership is."""

    add: list[int] = []
    remove: list[int] = []


class ViewVisibility(ItemSearchRequest):
    """Hide or show everything in a view.

    Spelled `hide` rather than `hidden` for the reason `EnqueueView.task_kind`
    is not `kind`: the search body's `hidden` is the SCOPE (the Hidden view),
    and one name cannot be both the question and the answer.
    """

    hide: bool = True


class ViewTrash(ItemSearchRequest):
    """Move everything in a view to the Trash. Reversible — which is what
    makes it offerable over a scope nobody has enumerated."""


class ViewActionOut(BaseModel):
    """How many items an action over a view touched, and how many it was
    aimed at. The two differ wherever the action skips (an item already
    hidden, a model that has already run), and a caller that only ever saw
    the first number could not say so."""

    count: int = 0
    total: int = 0


class MlRefOut(BaseModel):
    """One stored color-reference image (a rolling temp set, newest first)."""
    id: str


class MlRefsOut(BaseModel):
    refs: list[MlRefOut]


class JobOut(BaseModel):
    id: int
    kind: str
    model: str
    #: The one picture this job is about — NULL where the answer is "the
    #: library" (an estimate walks a search's whole scope and never holds
    #: its ids, so there is no item to name).
    item_id: Optional[int] = None
    item_name: str = ""
    # Number of items the job covers (>1 for a multi-item tag job); the UI shows
    # "N items" instead of a single filename when this exceeds 1.
    item_count: int = 1
    # "queued" | "running" | "paused" | "done" | "warning" | "failed" |
    # "canceled". A PAUSED job is held, not finished: it keeps its cursor and
    # its place in the queue, and only `resume` puts it back.
    status: str
    message: str = ""
    # Progress percentage (0-100) for multi-step jobs; 0 when not reported.
    progress: int = 0
    # How many of `item_count` are finished — the batch cursor, which is also
    # what the per-item list reads each item's state off.
    done_count: int = 0
    # Whether this job has a boundary between items to stop at. Answered HERE
    # rather than derived in the browser from the kind: which kinds run as a
    # batch is the queue's own rule, and a Pause button that sometimes did
    # nothing would be worse than none.
    pausable: bool = False
    created_at: Optional[str] = None


class JobsOut(BaseModel):
    jobs: list[JobOut]


class JobItemOut(BaseModel):
    """One item of a batch job, for the task's own progress list."""

    id: int
    name: str = ""
    # "done" | "running" | "pending" — derived from the job's cursor, so it
    # costs no per-item bookkeeping.
    status: str


class JobProgressOut(BaseModel):
    total: int
    done: int
    status: str
    # A window of the item list, `offset` onward: a batch can cover a whole
    # library, and the overlay only ever draws a screenful.
    offset: int
    items: list[JobItemOut]


class ItemDetail(ItemOut):
    # `uid` is inherited from ItemOut — the Info section shows it instead of
    # the internal numeric id, and the grid needs it to NAME an item in a
    # query. It used to be redeclared here, which is why the base gaining it
    # made this class receive it twice.
    # The item's two dates (ISO). ``created_at`` is when the image was first seen
    # in the library; ``last_imported_at`` is refreshed on every re-import. Source
    # files carry no dates of their own — only the item does.
    created_at: Optional[str] = None
    last_imported_at: Optional[str] = None
    files: list[FileVersion]
    captions: list[CaptionOut]
    tags: list[TagAssignment]
    indirect: list[IndirectGroupTags]
    # Per-item tag groups and the placement of each direct tag into them (the
    # same tag may appear in several groups, each with its own boxes).
    tag_groups: list[TagGroupOut] = []
    tag_instances: list[TagInstance] = []
    # The item's subjects — a VIEW over the tags above (a subject is extra data
    # on a tag), each with the state of that assignment. Listed separately
    # because the sidebar shows them as people and places, not as labels.
    subjects: list["SubjectOnItem"] = []
    # Face DETECTORS already run over this item, whatever they found. Not
    # derivable from the faces: a model that found nothing leaves none, and
    # that is exactly the item a "skip what is already done" sweep must not run
    # again. The Detect faces menus tick these.
    face_models: list[str] = []
    # Text ENGINES already run over this item — `face_models`' twin, for the
    # Detect text menus' ticks.
    text_models: list[str] = []
    # Live top-level text regions. On the wire rather than derived by the
    # client because the Text tab's BADGE needs it on every single-item
    # selection, and fetching the whole tree (every word of a manga page) to
    # render a number is the wrong trade.
    text_count: int = 0
    # WHEN THE PICTURE WAS TAKEN — sortable YYYYMMDDHHMMSS, zeros for whatever
    # is unknown. `taken_source` says where it came from: "set" (typed by
    # hand), "exif" (the indexed capture date), "event" (the span of an event
    # it carries), "never" (somebody said the picture has no date, so the walk
    # stopped there) or "" (nothing says). A search reads the same order.
    taken_at: Optional[int] = None
    taken_source: str = ""
    # WHERE it was taken, and which of the three answers it is — the same
    # model as the date above: "set", "exif", "never", or "" for nothing.
    lat: Optional[float] = None
    lon: Optional[float] = None
    coords_source: str = ""
    # True when the item is in the Trash. ``restore_groups`` lists the (still
    # existing) groups it will return to on restore.
    trashed: bool = False
    restore_groups: list[int] = []


class ItemUpdate(RequestModel):
    name: Optional[str] = None
    active_file_id: Optional[int] = None
    link_item_id: Optional[int] = None
    # WHEN THE PICTURE WAS TAKEN, said by hand: sortable YYYYMMDDHHMMSS with
    # zeros for whatever is unknown. **0 clears it** and falls back to EXIF;
    # null leaves it alone, like every other field here.
    taken_at: Optional[int] = None
    # WHERE it was taken, said by hand. The pair moves together; the two flags
    # are the states a pair cannot express — back to the file, and "there is
    # none", which is what `taken_at`'s 0 and -1 say for the date.
    lat: Optional[float] = None
    lon: Optional[float] = None
    clear_coords: bool = False
    no_coords: bool = False


class ItemDelete(RequestModel):
    item_ids: list[int]


class ItemHide(RequestModel):
    item_ids: list[int]
    hidden: bool = True


class ItemMerge(RequestModel):
    # All files/groups/tags/captions of ``source_id`` are folded into
    # ``target_id``; the source item is then removed.
    source_id: int
    target_id: int


class ItemDetailsIn(RequestModel):
    """Bulk request for the slim per-item details below (capped at 500)."""
    item_ids: list[int] = []


class LinkSlim(BaseModel):
    """One relationship of an item, as the grid's copy action needs it: which
    item sits at the other end, which way round, of what kind, and its meta
    tags. No hydration (name, uid, thumbnail file) — nothing that reads this
    renders a row; :class:`RelationshipOut` is where that lives."""
    other_item_id: int
    outgoing: bool
    kind: str
    tags: list[str] = []


class ItemSlim(BaseModel):
    """The slice of :class:`ItemDetail` the grid's context menu needs — the
    caption probe (any non-pending caption?) and the copy actions (captions
    and instructions, links, and direct tags with their per-item tag-group
    placements). A full ``ItemDetail`` per item is heavy (files, resolver,
    faces, taken); this is a handful of chunked selects for the whole batch."""
    id: int
    captions: list[CaptionOut] = []
    # The item's DIRECT tag names (both signs), sorted.
    tags: list[str] = []
    # id/name/system only — the copy action matches groups by name and skips
    # system (Pending) ones; meta tags/subjects stay empty here.
    tag_groups: list[TagGroupOut] = []
    # Placements of the direct tags (implicit ungrouped instances included);
    # ``boxes`` stays empty — the menu never reads it.
    tag_instances: list[TagInstance] = []
    # The item's relationships, both directions.
    links: list[LinkSlim] = []
    # LIVE top-level text regions on the ACTIVE file — `ItemDetail`'s own
    # `text_count`, per item, so the sidebar's Text tab can say how much of
    # a selection has been read without pulling a tree of blocks, lines and
    # words per picture for a number.
    text_count: int = 0


class ItemDetailsOut(BaseModel):
    items: list[ItemSlim] = []


# ---- tags ----

class TagSetRef(BaseModel):
    """One tag set's claim on a tag — the capsule behind the name: the set's
    key and its popularity figure for the name (a booru's post count), or
    None where the set counts nothing. DERIVED on read from the enabled sets;
    nothing is written, so disabling a set takes every capsule with it."""
    key: str
    #: The set's display name, so a chip can say "BASICS" rather than its key.
    name: str = ""
    count: Optional[int] = None


class TagSetText(BaseModel):
    """WHAT ONE SET SAYS about a tag — one per enabled set that KNOWS it,
    described or not, for the `?` popover's switcher.

    More than the description it is named for. A set that knows a name and
    has written no sentence about it still knows how common it is, what else
    it is called, what it entails and what entails it; a popover that opened
    only where somebody had written prose hid all of that. `trail` is the
    category it files the tag under, as the names down to it (["people",
    "girls"]; empty when uncategorized), drawn with chevrons between them.
    """
    key: str
    text: str
    trail: list[str] = []
    #: The set's own popularity figure, where it has one.
    count: Optional[int] = None
    #: The entry's other spellings, what it entails, and — the same table
    #: read the other way — the entries of that set which entail it.
    aliases: list[str] = []
    implies: list[str] = []
    implied_by: list[str] = []
    #: WHAT THE SET LABELS THE NAME WITH — its meta tags. Often the whole of
    #: what a bulk import knows: which kind of name it is, what a dataset
    #: should do with it.
    meta: list[str] = []
    #: THE ENTRY'S OWN NAME, where the name asked about is a SPELLING of it.
    #: Empty when they are the same. A set answers for an alias with its
    #: entry's row, so without this the popover showed a description for
    #: something it never named.
    alias_of: str = ""
    #: What the set says the TAG is — its one-liner, and whether it is a
    #: subject, a place or an event. The popover is often the only place a
    #: name is met (a field, an autocomplete row), so "who is this" belongs
    #: in it and not only in the Sets tab's list.
    comment: str = ""
    subject: Optional[TagSetSubjectIn] = None
    place: Optional[TagSetPlaceIn] = None
    event: Optional[TagSetEventIn] = None


class TagRow(BaseModel):
    id: int
    name: str
    # The one-liner shown beside the name and as the autocomplete's secondary
    # text. See `db.Tag.comment`.
    comment: str
    #: THE LONG FORM, the library's own (rung v27). `descriptions` below is
    #: what the enabled SETS say about the same name — a name can be
    #: described twice now, and the `?` popover shows both with this one
    #: first, because the library is the tag set somebody is actually
    #: working in.
    description: str = ""
    #: Where the library files it — a category of its own set, null for
    #: uncategorized. `category_trail` is the names down to it, the shape
    #: `CategoryTrail` draws (never a joined string: a category name may
    #: contain a slash).
    category_id: Optional[int] = None
    category_trail: list[str] = []
    positive: int
    # How much of `positive` no item assigns directly — implied by another tag,
    # inherited from a group, or carried by a sequence member. Shown in brackets
    # beside the count so the effective number can be read for what it is.
    positive_indirect: int = 0
    negative: int
    # When this tag is an alias, the name of the tag it links to (else None).
    # For an alias, positive/negative carry the *linked* tag's counts (so tag
    # autocomplete can show them); the flat tag list renders them as empty.
    alias_of: Optional[str] = None
    #: Kept out of the AUTOCOMPLETE. Not a deletion and not a scope: the tag
    #: assigns, searches, counts and is listed exactly as before — it just
    #: stops being suggested while somebody types.
    hidden: bool = False
    # Tags this one entails: assigning it also assigns these. Replaces the old
    # single parent — a tag may imply any number of others. Empty for an alias
    # (assigning an alias redirects, so the target's implications apply).
    implies: list[str] = []
    # What the TAG SET says about this tag ("noflip", "character") — the
    # same namespace links, captions and tag groups carry. Shown as capsules
    # behind the name in the tag / subject / place / event lists and nowhere
    # else: it annotates the tag, not the pictures.
    meta_tags: list[str] = []
    # The NONZERO per-meta counts — how many pictures the tag has where each
    # meta tag says ("tumblr": 50). Sparse and beside `meta_tags` rather than
    # replacing it: almost every assignment is a plain mark, and a dict that
    # is empty on 99% of rows costs nothing on the wire. Never folded into
    # `positive` — it orders ties and rides the capsules, the offset's rule.
    meta_counts: dict[str, int] = {}
    # What the enabled TAG SETS say about this name (`TagSetRef`), derived
    # per read. The whole-catalog listing carries `descriptions` as None —
    # "not fetched" — while the window's rows (`POST /api/tags/rows`) carry
    # every set's text for the popover.
    tag_sets: list[TagSetRef] = []
    descriptions: Optional[list[TagSetText]] = None


class TagNameRow(BaseModel):
    """One autocomplete row from ``GET /api/tags/names``: the tag name and its
    DIRECT positive count (one grouped query — autocomplete ranks by it, so
    exactness beyond that is not worth the effective-count pass)."""
    name: str
    # What the row SAYS about the tag, in a line. The typing-driven path used
    # to carry no comment while the static one showed it, so the same list
    # said different things depending on where it was opened.
    comment: str = ""
    positive: int = 0
    # The NONZERO per-meta counts, for the hover ("tumblr 50 · twitter 100")
    # — the ordering already used them server-side (equal counts sort by the
    # highest), so the row only ever SHOWS them.
    meta_counts: dict[str, int] = {}
    # What the tag set says about the tag, shown as capsules on the row
    # where there is width for them. Every name, counted or not: `meta_counts`
    # is sparse by design, so it can say which of them is the biggest and
    # never which of them exist.
    meta_tags: list[str] = []
    # The tag this row is an ALIAS of — a library alias's target, or the
    # canonical entry a TAG SET names for the alias — so the row can wear its
    # arrow and the field can commit the canonical. None for a plain tag.
    alias_of: Optional[str] = None
    #: THE LIBRARY'S OWN LONG FORM, where this row is a library tag. The `?`
    #: draws it FIRST, above `descriptions` — which is what the enabled
    #: foreign sets say. It rides on the row rather than in `descriptions`
    #: because this endpoint answers per KEYSTROKE and the column is already
    #: on the select that fetched the name; building it into `descriptions`
    #: cost a second statement per keystroke.
    description: str = ""
    # The enabled tag sets' claims on the name and their descriptions of it.
    # A row the LIBRARY does not have yet (a set-only suggestion) has
    # `positive` 0 and at least one `tag_sets` entry; picking it creates the
    # tag through the assignment door (`tagcatalog.get_or_create`).
    tag_sets: list[TagSetRef] = []
    descriptions: list[TagSetText] = []


class TagsHiddenIn(RequestModel):
    #: The tags to keep out of the autocomplete, or to put back.
    names: list[str] = []
    hidden: bool = True


class HiddenNamespacesIn(RequestModel):
    #: The WHOLE list, not a delta: a namespace has no row, so the
    #: list is the state.
    namespaces: list[str] = []


class TagCreate(RequestModel):
    name: str
    comment: str = ""
    # If set, create ``name`` as an alias linking to this (target) tag name.
    alias_of: str = ""
    # If set, create ``name`` already implying this tag (created if it doesn't
    # exist yet).
    implies: str = ""


class BulkTagRowIn(RequestModel):
    """One row of the CSV import's tag table. ``None`` = the file says
    nothing about that field, which is a different statement from ``""``."""
    name: str
    comment: Optional[str] = None
    # The file's count for this tag — stored on the ``count_meta``
    # assignment when the batch names one, else only the minimum's input.
    count: Optional[int] = None
    # Meta tags THIS row says the tag carries — the meta-assignments file's
    # pairs, grouped by tag. Applied beside the batch-wide ``meta_tags``.
    meta_tags: Optional[list[str]] = None
    # Per-meta counts this row says outright — the meta-assignments file's
    # own count column, keyed by meta name. Assigning rides along.
    meta_counts: Optional[dict[str, int]] = None


class BulkTagsIn(RequestModel):
    """The tag CSV import's batch: rows plus the dialog's file-wide
    settings — what a tag the library already has keeps, the meta tags to
    mark every named tag with, and what the count column does to a count
    that is already there."""
    rows: list[BulkTagRowIn]
    # WHAT AN EXISTING TAG KEEPS. ``keep`` fills in only what the library has
    # not said, ``update`` takes the file's value for every field the row
    # carries, and ``replace`` makes the tag match the row — a field the row
    # leaves empty is CLEARED, which is how a re-imported dump drops what it
    # no longer says. It was a bool (``overwrite``, i.e. these first two),
    # and the third had no spelling at all.
    existing: Literal["keep", "update", "replace"] = "keep"
    meta_tags: list[str] = []
    # The ONE meta tag the count column lands on (a site name, usually) —
    # per assignment, so "abc" can carry tumblr 50 and twitter 100 at once.
    # Empty = the count is only the minimum's input.
    count_meta: str = ""
    # The count dropdown: what a row's ``count`` does to an assignment that
    # already carries one — the whole rule, reading nothing else (``overwrite``
    # is about the text columns). ``None`` is ``keep``, which is also what the
    # dialog starts on: a number already stored is left alone, a gap is filled.
    count_mode: Optional[Literal["keep", "replace", "min", "max"]] = None


class BulkDeleteTagsIn(RequestModel):
    """The Tags list's bulk delete: the selected tag ids, in display order —
    which is the order the events are written in, exactly as a sequence of
    single deletions would write them."""
    tag_ids: list[int]


class TagImplies(RequestModel):
    """One tag this tag entails, by name (created if it doesn't exist)."""
    name: str


class TagMetaTagBody(RequestModel):
    """One meta tag to put on a tag, by name. Free-form (the namespace keeps
    spaces and capitals — "main character" is a real stored name), so it
    travels in the body rather than the URL path. ``count`` sets the
    assignment's own figure; ``None`` leaves it alone."""
    name: str
    count: Optional[int] = None


class TagUpdate(RequestModel):
    name: Optional[str] = None
    comment: Optional[str] = None
    #: The LONG form — what the tag covers, when to reach for it, what it is
    #: not. A tag carries its own again (rung v27) because the library is a
    #: tag set now and exports as one.
    description: Optional[str] = None
    # Change an alias's linked (target) tag by name; "" clears the alias link.
    alias_of: Optional[str] = None
    # Implications are edited with their own endpoints (add/remove by name),
    # not by replacing a single field — a tag has a set of them.


class LibraryCategoryIn(RequestModel):
    """The library's FIRST category — the one call that has no set id to post
    to, because the library's set row is made by whatever first needs it."""
    name: str
    parent_id: Optional[int] = None
    icon: str = ""
    hidden: bool = False


class TagCategoryIn(RequestModel):
    """File names in a category of their own tag set, or take them out.

    A LIST because the gesture is a drag of a selection onto a category;
    `category_id` null is "Uncategorized".
    """
    tag_ids: list[int]
    category_id: Optional[int] = None
    #: WHICH TAG SET: absent is the library's own tags, an id is that
    #: imported set's entries. One gesture, one request, either list.
    set_id: Optional[int] = None


class SubjectRow(BaseModel):
    """A subject for the Tags tab's "Subjects" mode.

    A subject is extra data on a TAG, so most of a row is the tag's: `tag` is
    the identity slug (empty while the subject is unnamed — a face cluster) and
    `items` is that tag's effective count, the very number the item-tag list
    shows. Only the display name, the disambiguating comment and the since-date
    are the subject's own."""
    id: int
    display_name: str
    comment: str = ""
    # The identity tag's name; "" while the subject has none (unnamed).
    tag: str = ""
    tag_id: Optional[int] = None
    # Partial date, YYYYMMDD with zeros for what is unknown (see partialdate).
    since_date: Optional[int] = None
    # The identity tag's effective positive count, and what it implies — the
    # same numbers the item-tag list shows, so the two lists never disagree.
    items: int = 0
    implies: list[str] = []
    #: SOMEBODY DECIDED THIS IDENTITY HAS NO NAME — a background character.
    #: Told apart from a subject nobody has looked at yet, which is what the
    #: Faces tab calls UNKNOWN: this one is an answer.
    unnamed: bool = False


class SubjectCreate(RequestModel):
    display_name: str = ""
    comment: str = ""
    since_date: Optional[int] = None
    # The identity tag's name. Empty derives a slug from the display name;
    # a subject created with neither is UNNAMED (a face cluster).
    tag: str = ""


class SubjectUpdate(RequestModel):
    display_name: Optional[str] = None
    comment: Optional[str] = None
    # Null is "leave alone"; 0 clears the date (a partial date is never 0).
    since_date: Optional[int] = None
    # Rename (or mint) the identity tag. Renaming onto an existing tag is
    # refused here — that is a merge, and it has its own endpoint.
    tag: Optional[str] = None


class SubjectMerge(RequestModel):
    """Fold this subject into ``into_id``: its faces and its tag's assignments
    move over, and the identity tags merge through the ordinary tag merge."""
    into_id: int
    # Keep the old identity tag's name as an alias of the target's.
    keep_alias: bool = True


class TagWhen(BaseModel):
    """When a tag was true of an item — the state of one assignment.

    Both optional and each derives the other from the subject's since-date, so
    the UI can accept whichever the user has: the year of the picture, or how
    old its subject was in it."""
    date: Optional[int] = None   # partial date, YYYYMMDD with zeros
    age: Optional[int] = None


class SubjectAppearance(BaseModel):
    """One appearance of a subject in an item — a row in the sidebar.

    The subject's TAG is the assignment; this says which of the possibly
    several times they are in the picture, at which face, and how old."""
    id: int
    face_id: Optional[int] = None
    when: Optional[TagWhen] = None
    when_derived: bool = False
    assigned_by: str = "user"
    match_score: Optional[float] = None
    # Where the row sits in the sidebar's list — the drag-reorder's answer;
    # ties break by id, so 0 everywhere is the creation order.
    position: int = 0
    # The appearance's SUBJECT BOX — the whole figure, where the face is only
    # the head. [x, y, w, h] in the item's reference frame; None until drawn.
    box: Optional[list[float]] = None
    # The box's optional polygon outline (`TagBox.points`' rule: the box above
    # is its bounding box while this is set).
    points: Optional[list[list[float]]] = None


class SubjectOnItem(BaseModel):
    """One subject assigned to an item, and every appearance of them in it."""
    id: int
    display_name: str
    comment: str = ""
    tag: str = ""
    # The identity tag's id — what the assignment keys on.
    tag_id: int
    since_date: Optional[int] = None
    appearances: list[SubjectAppearance] = []


# ---- faces ----

class FaceSubjectOut(BaseModel):
    """One APPEARANCE: a subject this face has been said to be.

    A face carries a list of these, because one rectangle can be a character
    and the actor playing them at once, each with an age of its own. `id` is
    the appearance row — what dating or removing this one claim addresses."""
    id: int
    subject_id: int
    name: str = ""
    comment: str = ""
    tag: str = ""
    since_date: Optional[int] = None
    # "user" | "suggested" — a suggestion is shown with its score and a
    # tick/cross, never applied silently.
    assigned_by: str = "user"
    match_score: Optional[float] = None
    # How old they are in this picture. `when_derived` says the missing half
    # was worked out from the subject's since-date rather than typed.
    when_date: Optional[int] = None
    when_age: Optional[int] = None
    when_derived: bool = False


class FaceOut(BaseModel):
    """One detected face on an item.

    The box is in the item's reference frame (fractions 0..1), the same frame
    tag boxes use. `subjects` may be empty (nobody has said who this is), one
    (the common case), or several — and a subject in it may be NAMELESS, which
    is what a hand-merged "these are the same person, whoever they are"
    cluster is."""
    id: int
    item_id: int
    # The item's uid — what `id:` searches for, so a list of faces can send the
    # Library to the one picture a crop came from.
    item_uid: str = ""
    # The file the face was found in — what a caller needs to show the whole
    # picture behind the crop (a list of crops says what each face looks like;
    # only the picture says where it is).
    file_id: Optional[int] = None
    x: float
    y: float
    w: float
    h: float
    det_score: Optional[float] = None
    # Every model that found this face. Several when detectors overlap — the
    # boxes merge, and both are credited.
    models: list[str] = []
    subjects: list[FaceSubjectOut] = []
    dismissed: bool = False
    has_embedding: bool = False
    # Which embedders have described this face. A face may be in several spaces
    # at once, and only faces sharing a space can ever be compared.
    embedded_by: list[str] = []
    # The face's optional OUTLINE — the whole figure, drawn by hand.
    # [x, y, w, h] in the item's reference frame, plus the polygon when one
    # was drawn (`TagBox.points`' rule: the rectangle is then its bounding
    # box). A subject attached to the face uses it wherever it has no subject
    # box of its own.
    outline: Optional[list[float]] = None
    outline_points: Optional[list[list[float]]] = None
    # True while the box is a PERSON's answer rather than the detector's — a
    # hand edit of a detected face. Presence of the reset record; "Reset the
    # box" is offered exactly then.
    edited: bool = False


class FaceWhen(BaseModel):
    """A face's own date/age. Both None clears it."""
    date: Optional[int] = None
    age: Optional[int] = None


class FaceOutlineSet(RequestModel):
    """Draw (or replace) one face's OUTLINE — `AppearanceBoxSet`'s shape one
    level down. Clearing is the DELETE on the same path."""
    x: float
    y: float
    w: float
    h: float
    points: Optional[list[list[float]]] = None


class FaceUpdate(RequestModel):
    """Dismissing a face, or moving its box.

    Who a face IS is not here: an appearance is its own row now (a face may be
    two people at once), so naming goes through `/faces/{id}/subject`."""
    dismissed: Optional[bool] = None
    x: Optional[float] = None
    y: Optional[float] = None
    w: Optional[float] = None
    h: Optional[float] = None


class FaceSubjectIn(RequestModel):
    """Say who a face is — an existing subject, or a new one by name.

    Naming a face also assigns that subject's tag to the item; that connection
    is the whole point of the feature."""
    subject_id: Optional[int] = None
    display_name: str = ""
    comment: str = ""


class AppearanceUpdate(RequestModel):
    """Edit one appearance: when it is, and which face it points at.

    `face_id` 0 detaches it from its face (the person is still in the picture,
    just not that rectangle); null leaves it alone.

    `confirm` agrees with a guess: the machine said this, and somebody has now
    said it too. Saying no is a DELETE — and the face-aware one where there is
    a face, so the refusal is remembered."""
    when: Optional["FaceWhen"] = None
    face_id: Optional[int] = None
    confirm: bool = False


class AppearanceOrder(RequestModel):
    """The sidebar's drag-reorder: the item's appearances in the order the
    list now shows. Ids the item does not hold are skipped."""
    item_id: int
    ids: list[int]


class AppearanceCreate(RequestModel):
    """Somebody is in this picture — optionally at a particular face."""
    item_id: int
    subject_id: Optional[int] = None
    display_name: str = ""
    face_id: Optional[int] = None


class AppearanceBoxSet(RequestModel):
    """Draw (or replace) one appearance's SUBJECT BOX — fractions of the
    item's reference frame, the rectangle around the whole figure where the
    face box is only the head. Clearing is the DELETE on the same path."""
    x: float
    y: float
    w: float
    h: float
    # An optional polygon outline (`TagBox.points`' rule); with one, the
    # rectangle is derived from it server-side and the four values above are
    # ignored.
    points: Optional[list[list[float]]] = None


class FaceCreate(RequestModel):
    """A face drawn by hand: no detector, no score."""
    item_id: int
    x: float
    y: float
    w: float
    h: float
    subject_id: Optional[int] = None


class FaceCluster(BaseModel):
    """A group of unnamed faces the descriptors say are one person.

    `name all N` on this is the point of the whole view: naming people one
    picture at a time is what kills face tagging in other tools."""
    faces: list[FaceOut] = []
    # How many faces the cluster REALLY has. `faces` may be a first-row-sized
    # slice of it (see `/named`'s `per`), and a "+N more" built from the slice
    # would say there are none left to see. Equal to len(faces) when uncapped.
    total: int = 0
    # True when the grouping is real (descriptors agreed, or somebody merged
    # these by hand) rather than a detection-only model's one-face-per-group
    # fallback.
    grouped: bool = False
    # The NAMELESS subject holding a hand-merged cluster together, if any. It
    # is what naming later attaches to, and what a further merge folds into.
    subject_id: Optional[int] = None
    # How many of those faces carry a name a MODEL guessed and nobody has
    # agreed with yet. Counted here rather than read off `faces`, for the same
    # reason `total` is: `faces` may be a slice, and a cluster of three hundred
    # crops whose guesses all sit past the first thirty-two would have said it
    # had none — which is exactly the cluster somebody needs to open.
    guesses: int = 0


class ClustersDiffer(RequestModel):
    """"Not this person" said of two whole clusters.

    Both sides travel as FACE IDS: a cluster the algorithm made has no row of
    its own until something says otherwise, and this is one of the things
    that does.
    """
    face_ids: list[int] = []
    other_face_ids: list[int] = []
    # …AND SEVERAL AT ONCE (owner 2026-09): the row selects, so "not this
    # person" can be said of five offers in one press. Each inner list is
    # ONE cluster — held on its own, as `other_face_ids` is — never all of
    # them on one identity, which would merge the five.
    other_clusters: list[list[int]] = []


class SimilarFace(BaseModel):
    """One offer of the strip, and how alike it is to the open cluster.

    A FACE where the candidate is one crop, and a CLUSTER where the
    unanswered queue holds several crops together (owner 2026-09, refining
    "faces, never clusters" of the same month): a named person's crops are
    still offered one by one — "is this crop one of these?" — but a cluster
    nobody has answered is one question, and forty cards of it were forty
    copies of that question. `face` is the COVER (the biggest crop), `faces`
    every crop cover first, `count` how many; a single crop is `count` 1
    with `faces` of one. `name` is whoever it is currently on, so the row
    can say where it would be coming from; `score` is on the library
    setting's own scale, never a raw cosine.
    """
    face: FaceOut
    faces: list[FaceOut] = []
    count: int = 1
    score: float = 0.0
    subject_id: Optional[int] = None
    name: str = ""
    unnamed: bool = False


class OddOnesOut(RequestModel):
    """Which of a cluster's crops look more like the ones just taken out of it.

    A READ, with two id lists — which is why it is a POST and why it is in
    `build.READ_ONLY_POSTS`: the method is not the signal.
    """
    face_ids: list[int] = []
    unlike: list[int] = []


class FaceGrouping(RequestModel):
    """The face ids of the cluster on screen, for the grid's grouping.

    A READ, and a POST because a cluster is hundreds of ids and a URL is not
    where those belong — so it is in `build.READ_ONLY_POSTS`, like
    `OddOnesOut` beside it.
    """
    face_ids: list[int] = []


class FaceGroupingOut(BaseModel):
    """WHAT THE OPEN CLUSTER'S PICTURES SAY, for grouping its crops by.

    PARALLEL ARRAYS on `face_ids`, the tags list's own shape: the NAMES are
    sent once and each face names its own by INDEX into them, so a
    cluster of nine hundred crops carrying forty tags each is a few thousand
    small integers rather than tens of thousands of repeated strings.

    `tag_names` is what the capsule bar offers, most FACES first — faces, not
    pictures, because the grid groups crops and two crops in one picture are
    two cards. It is capped and thresholded (`_GROUP_TAGS_MAX`,
    `_GROUP_TAG_MIN_FACES`): a tag on one crop makes a group of one, which is
    not a grouping, and a booru-tagged library would otherwise offer a
    thousand capsules for a cluster.
    """
    face_ids: list[int] = []
    #: The sequence each crop's picture belongs to — its name, or "" for a
    #  picture in none. `Item.main_sequence_id` is the one asked, which is the
    #  same sequence the library grid's page badge counts in.
    sequences: list[str] = []
    tag_names: list[str] = []
    #: How many CROPS each of those tags is on — what the capsule shows.
    tag_faces: list[int] = []
    #: Which of `tag_names` each face carries, by index.
    tags: list[list[int]] = []


class NamedFaces(BaseModel):
    """The named clusters, plus what a capped list can no longer be counted for.

    `faces` is the number of DISTINCT faces somebody has named. It cannot be
    summed from the clusters for two reasons: they carry only a first row each,
    and a face credited to a character and to its actor appears under both — it
    is one face either way.
    """
    clusters: list[FaceCluster] = []
    faces: int = 0


class ClusterUnnamed(RequestModel):
    """Say a cluster is somebody with no name — or take that back.

    The other answer to "who is this", beside naming: a background
    character, an extra. `unnamed` false puts the cluster back in the
    UNKNOWN queue.
    """
    face_ids: list[int] = []
    unnamed: bool = True


class NameCluster(RequestModel):
    """Name every face in a cluster at once."""
    face_ids: list[int] = []
    # An existing subject, or a new one from `display_name`.
    subject_id: Optional[int] = None
    display_name: str = ""
    comment: str = ""
    # MOVE (the default) or COPY. Dropping crops onto somebody says "these are
    # hers and not his", which is a move; holding shift says "these are hers AS
    # WELL", which is the character-and-the-actor case and must leave what is
    # already on the face alone.
    replace: bool = True


# ---- detected text ----------------------------------------------------------


class TextRegionOut(BaseModel):
    """One region of detected (or hand-drawn) text on an item, subtree and
    all.

    ONE recursive model rather than a block/span pair — the table is one
    table (the two engines disagree about how deep the tree goes) and the
    wire says the same thing. The box is the AABB in the item's reference
    frame (fractions 0..1), the frame tag boxes and faces use.
    """
    id: int
    item_id: int
    # The item's uid — what `id:` searches for, like FaceOut's.
    item_uid: str = ""
    file_id: Optional[int] = None
    parent_id: Optional[int] = None
    level: str = "block"       # block | line | word | char
    ord: int = 0
    x: float
    y: float
    w: float
    h: float
    # The engine's own four points, when it read a rotated or perspective
    # shape. EMPTY when the box IS the shape, so a reader draws the box and
    # there is never a second copy of an upright rectangle to drift.
    quad: list[list[float]] = []
    text: str = ""
    # NULL = "the engine does not say" (Magi is generative) — provenance is
    # `models == []`, never this.
    score: Optional[float] = None
    lang: str = ""
    # Every engine that read this region; EMPTY is what "drawn by hand"
    # means, the same way it does on a face.
    models: list[str] = []
    dismissed: bool = False
    # A person corrected the text; no run may rewrite it after this.
    edited: bool = False
    children: list["TextRegionOut"] = []


class TextRegionCreate(RequestModel):
    """A text box drawn by hand: no engine, no score."""
    item_id: int
    x: float
    y: float
    w: float
    h: float
    text: str = ""
    level: str = "block"
    parent_id: Optional[int] = None


class TextRegionUpdate(RequestModel):
    """Correcting a region's text, marking it as not text, or moving its box.

    An edit sets `edited` server-side — after it, no run rewrites the string.
    `quad` rides with a box move so a rotated region's shape is not silently
    replaced by an upright rectangle; an empty list clears it (the box
    becomes the shape)."""
    text: Optional[str] = None
    dismissed: Optional[bool] = None
    x: Optional[float] = None
    y: Optional[float] = None
    w: Optional[float] = None
    h: Optional[float] = None
    quad: Optional[list[list[float]]] = None


class TextOrder(RequestModel):
    """One sibling run's FULL reading order — every sibling named exactly
    once, `reorder_members`' rule, so add/remove/reorder is one op and one
    revert."""
    parent_id: Optional[int] = None
    region_ids: list[int] = []


class PlaceRow(BaseModel):
    """A place for the Tags tab's "Places" mode.

    Location data hangs off a TAG, so `tag` is the identity slug (empty for an
    unnamed place — an older library's bare GPS pin) and `items` is that
    tag's count. The name is one free text line."""
    id: int
    tag: str = ""
    tag_id: Optional[int] = None
    # WHAT IT IS CALLED — one free text line, and the only text a place
    # carries. An address is welcome in it; so is "Bob's house", which is
    # why the field, the column and the label all say `name` (rung v26).
    name: str = ""
    # The place this one is IN. Assigning a place implies its parents, which
    # is an ordinary tag implication under the hood.
    parent_id: Optional[int] = None
    # What it IS, beside where it is: the one-liner ("the hotel bar"). The
    # name answers "where" and never "which of the two". The identity TAG's,
    # so an unnamed place shows none.
    comment: str = ""
    lat: Optional[float] = None
    lon: Optional[float] = None
    items: int = 0


class PlaceCreate(RequestModel):
    # The identity tag's name; empty derives a slug from `name`, and a place
    # created with neither is UNNAMED (what a photo's bare GPS produces).
    tag: str = ""
    name: str = ""
    parent_id: Optional[int] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    comment: str = ""


class PlaceUpdate(RequestModel):
    tag: Optional[str] = None
    name: Optional[str] = None
    parent_id: Optional[int] = None
    # Taking a place OUT of its parent — `parent_id: null` cannot say it,
    # since None is also "the caller did not mention the parent".
    clear_parent: bool = False
    lat: Optional[float] = None
    lon: Optional[float] = None
    # The same trap for the coordinates: `lat: null` is also what an untouched
    # field sends, so emptying the pair has to be said by name.
    clear_coords: bool = False
    comment: Optional[str] = None


class EventRow(BaseModel):
    """An event for the Tags tab's "Events" mode.

    Stored as an `Occasion` — the UI's word and the model's differ because
    `Event` is the modification log. Like a subject and a place it is extra
    data on a TAG, so `tag` is the identity slug and `items` is that tag's
    count. The dates are PARTIAL (YYYYMMDD with zeros for what is unknown).

    Its places ride along as whole rows rather than ids: the list is short, and
    a row that wants to show a place's name would otherwise need a second
    fetch to draw one line."""
    id: int
    tag: str = ""
    tag_id: Optional[int] = None
    display_name: str = ""
    comment: str = ""
    # The event this one is PART OF — Day 1 of a convention, in a season.
    parent_id: Optional[int] = None
    start_date: Optional[int] = None
    end_date: Optional[int] = None
    places: list[PlaceRow] = []
    items: int = 0


class EventCreate(RequestModel):
    # The identity tag's name; empty derives a slug from `display_name`.
    tag: str = ""
    display_name: str = ""
    comment: str = ""
    # The event this one is PART OF — assigning it implies its parents.
    parent_id: Optional[int] = None
    start_date: Optional[int] = None
    end_date: Optional[int] = None
    place_ids: list[int] = []


class EventUpdate(RequestModel):
    tag: Optional[str] = None
    display_name: Optional[str] = None
    comment: Optional[str] = None
    parent_id: Optional[int] = None
    # Taking an event OUT of its parent — see `PlaceUpdate.clear_parent`.
    clear_parent: bool = False
    # 0 clears a date, as it does for a subject's since-date.
    start_date: Optional[int] = None
    end_date: Optional[int] = None
    # None leaves the places alone; a list REPLACES them ([] clears): this is
    # a set rather than a form of independent fields, so there is nothing to
    # leave untouched within it.
    place_ids: Optional[list[int]] = None


class DismissPlace(RequestModel):
    """"Not there" — stop offering this place for this picture."""
    item_id: int
    location_id: int
    # Which event prompted the offer, for the log's sentence only.
    via_occasion_id: Optional[int] = None


class FilePlaceRef(RequestModel):
    """Accept or refuse the place the item's own file names — keyed on the
    item alone, since the place need not exist until it is accepted."""
    item_id: int


class DismissEvent(RequestModel):
    item_id: int
    occasion_id: int


class SuggestedPlace(BaseModel):
    """A place an event on this item was at, offered rather than assigned."""
    place: PlaceRow
    occasion_id: int
    via_event_tag: str = ""
    via_event_name: str = ""


class FilePlaceSuggestion(BaseModel):
    """The place the item's own file names (XMP/IPTC city/state/country),
    offered rather than created — the importer used to mint it outright.
    ``place`` is the existing named place accepting would reuse, else None
    (accepting creates it, coordinates and all)."""
    name: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    place: Optional[PlaceRow] = None


class SuggestedEvent(BaseModel):
    event: EventRow
    # The picture's own capture date that put it inside the span, so the row
    # can say WHY it is being offered rather than merely appearing.
    date_taken: Optional[int] = None   # YYYYMMDD


class ItemSuggestions(BaseModel):
    places: list[SuggestedPlace] = []
    events: list[SuggestedEvent] = []
    # What the item's own file says about where it was taken, unanswered.
    file_place: Optional[FilePlaceSuggestion] = None
    # False when the item has no indexed capture date at all. The section says
    # so, rather than showing an empty list that reads as "no events matched"
    # when the truth is "nothing was checked".
    dated: bool = True


class LinkTagRow(BaseModel):
    """A meta-tag row for the Tags tab's "Meta" mode: a comment and one count
    per CARRIER, plus their total. Meta tags have no aliases or parents.

    One namespace serves four carriers (links, captions, per-item tag groups
    and the library's own tags), and "used 7 times" said nothing about which —
    so each is counted on its own and `count` stays the total the filters and
    the delete warning read. A fifth carrier means a fifth field here and a
    column beside it."""
    name: str
    comment: str = ""
    description: str = ""
    count: int = 0
    links: int = 0
    captions: int = 0
    tag_groups: int = 0
    tags: int = 0


class LinkTagUpdate(RequestModel):
    # The link tag being edited (identified by name — link-tag names are
    # free-form, so they travel in the body rather than the URL path).
    name: str
    # Rename to this name (merges into an existing link tag if it already exists).
    new_name: Optional[str] = None
    comment: Optional[str] = None
    description: Optional[str] = None


class LinkTagCreate(RequestModel):
    name: str
    # The New dialog writes all three at once; each is still its own event.
    comment: str = ""
    description: str = ""


class LinkTagDelete(RequestModel):
    name: str


class TagMerge(RequestModel):
    """Fold one tag into another (POST /api/tags/{id}/merge)."""
    # The name of the tag to merge INTO. By name, because that is what the user
    # typed when the rename collided with it.
    into: str
    # Leave the old name behind as an alias of the target, so anything still
    # calling it that lands on the right tag.
    keep_alias: bool = True


class AssignTag(RequestModel):
    tag: str  # tag name; created if missing
    negative: bool = False


class QuickAssign(RequestModel):
    item_ids: list[int]
    positive: list[str] = []
    negative: list[str] = []
    # GROUP memberships stamped alongside the tags (a Quick Assign set may
    # carry both). Removed with the tags when `remove` is set. Group ids; a
    # smart group in the list is refused like any manual membership. Named
    # apart from the view request's `groups`, which is the SCOPE.
    assign_groups: list[int] = []
    remove: bool = False  # if true, unassign instead of assign


class QuickAssignView(ItemSearchRequest):
    """The same stamp, aimed at a WHOLE VIEW rather than a list of ids.

    Quick-tagging with nothing selected means "everything the grid is
    showing", and that view can be the whole library — a million ids is not
    something a request body can carry, and enumerating them in the browser
    would mean paging the entire library first. So the SCOPE travels instead
    and the server resolves it, which is the same shape (and the same words)
    ``POST /api/items/query`` already takes.

    Inheriting the search request is what guarantees the two mean the same
    view: a flat copy of the scope flags would be a second place to keep
    every one of them in step. ``page``/``page_size``/``sort`` come with it
    and are ignored — an order does not change which items a stamp lands on.
    """
    positive: list[str] = []
    negative: list[str] = []
    #: See `QuickAssign.assign_groups` — `groups` here is the scope string.
    assign_groups: list[int] = []
    remove: bool = False


class CaptionIn(RequestModel):
    text: str
    # "caption" describes the picture, "instruction" says how it was made from
    # the items in its reference list. Only read when creating one — editing a
    # caption never changes what kind of thing it is.
    kind: Literal["caption", "instruction"] = "caption"


class CaptionBulkIn(RequestModel):
    """One caption text, onto every item named.

    A caption per item, each its own logged and revertible `add_caption` —
    the sidebar's multi-selection Add, which is a statement about all of
    them rather than a list to be edited item by item. The cap is
    `_DETAILS_CAP`'s, and for its reason: this is a selection somebody is
    holding, not a way to caption a library.
    """
    item_ids: list[int]
    text: str
    kind: Literal["caption", "instruction"] = "caption"


class CaptionRefsIn(RequestModel):
    """The FULL desired order of an instruction's reference images. One body
    covers adding, removing and reordering, so there is one history event and
    one undo for what is one edit to one ordered list."""
    item_ids: list[int] = []


class CaptionTagBody(RequestModel):
    name: str


# ---- import ----

class ImportOptionsIn(RequestModel):
    parent_group_id: Optional[int] = None
    # A box of this run's own INSIDE the parent group; an empty name means
    # `importer.default_run_group_name()`, which is where that answer lives
    # so this door and the CLI's cannot drift.
    new_group: bool = False
    new_group_name: str = ""
    folders_as_groups: bool = True
    recursive: bool = True
    archives_as_groups: bool = False
    # Which half of a SEQUENCE joins the run's groups: both | container |
    # members. Anything else reads as "both" (see `ImportOptions`).
    sequence_grouping: str = "both"
    archive_sequences: bool = False
    # The run's minimums, the Storage page's prune rule read the other way
    # round: 0 is "not set" and a file must clear every one that is set. A
    # sequence is kept whole — it is imported when ANY page clears them.
    min_megapixels: float = Field(0, ge=0, le=10_000)
    min_short_edge: int = Field(0, ge=0, le=1_000_000)
    min_long_edge: int = Field(0, ge=0, le=1_000_000)
    # The run's aspect RANGE, width/height: ignore anything narrower than
    # `min_aspect` or wider than `max_aspect`. 0 is "not set" on each side
    # like the minimums, so one end may be given without the other.
    min_aspect: float = Field(0, ge=0, le=1_000)
    max_aspect: float = Field(0, ge=0, le=1_000)
    # File types the run leaves alone — the four buckets an import can be
    # handed (`ImportOptions.ignore_kinds`). A Literal, so a typo is a 422
    # naming the field rather than a filter that silently matches nothing.
    ignore_kinds: list[Literal["image", "video", "sequence", "archive"]] = []
    # Tags put on everything the run creates, plus per-kind lists.
    tags: list[str] = []
    tags_image: list[str] = []
    tags_video: list[str] = []
    tags_sequence: list[str] = []
    # Model key to run face detection with on everything imported; "" = don't.
    detect_faces: str = ""
    # Embedder ids to index everything imported with, for the tag batch's
    # smart ordering; empty = don't. Queued after the import like the faces
    # run, one job per embedder — the spaces are indexed independently and
    # never mixed (`itemvec.EMBEDDERS`), so asking for two is two runs.
    # Either a list or the comma-separated STRING the multipart form sends
    # (`ignore_kinds`' spelling); a bare id is the one-element list every
    # caller written before this sent, and still means what it meant.
    index_embeddings: Union[str, list[str]] = ""
    paths: Optional[list[str]] = None  # server-side paths (CLI-style)


class ImportJobOut(BaseModel):
    id: str
    status: str
    stats: dict
    message: str = ""
    total: int = 0  # number of files staged for this job (progress denominator)


# ---- sequences ----

class SequenceMember(BaseModel):
    # The MEMBERSHIP row's id. The same item may sit at several positions (a
    # book's blank pages all dedup onto one item), so `item_id` cannot name
    # one occurrence — this is what reorder and a row's own ✕ address.
    id: int
    item_id: int
    position: int  # 1-based ordinal within the sequence
    name: str
    active_file_id: Optional[int] = None
    kind: str = "image"


class SequenceInfo(BaseModel):
    id: int
    # The sequence's stable, library-independent identity — the same uid an
    # export or a merge uses (sequence refs never travel as DB ids).
    uid: str = ""
    name: str
    kind: str
    is_main: bool  # whether this is the queried item's main sequence
    total: int
    members: list[SequenceMember] = []
    # The sequence's container library item (kind="sequence"), if materialized.
    item_id: Optional[int] = None
    item_uid: Optional[str] = None


class SequenceSummary(BaseModel):
    """One row in the left-sidebar Sequences list."""
    id: int
    name: str
    kind: str
    total: int
    # Active file of the first member — drives a hover thumbnail in the sidebar.
    thumb_file_id: Optional[int] = None


class SequenceCreate(RequestModel):
    name: str = ""
    item_ids: list[int] = []


class SequenceRename(RequestModel):
    name: str


class SequenceReorder(RequestModel):
    """The desired order. `member_ids` (membership-row ids) is the real
    tag set — it says which COPY of a repeated item goes where; `item_ids`
    survives for callers that think in items and is refused server-side the
    moment an item is in the sequence twice."""
    item_ids: list[int] = []
    member_ids: list[int] = []


class SequenceItemsIn(RequestModel):
    """`member_ids` removes those occurrences; `item_ids` removes every
    occurrence of each item."""
    item_ids: list[int] = []
    member_ids: list[int] = []


class MainSequenceIn(RequestModel):
    sequence_id: Optional[int] = None  # None clears the main-sequence choice


# ---- relationships ----

class LinkBoxOut(BaseModel):
    # A bounding box on a link, as fractions (0..1) of the link *target*
    # (``to_item``) reference frame — e.g. a detected panel's region on its page.
    x: float
    y: float
    w: float
    h: float


class RelationshipOut(BaseModel):
    id: int
    from_item_id: int
    to_item_id: int
    # The *other* item relative to the queried one, and the direction.
    other_item_id: int
    # The linked item's stable uid — what an export references,
    # since the numeric id is meaningless outside this library.
    other_item_uid: str = ""
    other_name: str
    # Active file id of the other item, so a related row can show a hover
    # thumbnail even when that item isn't in the currently-loaded grid page.
    other_file_id: Optional[int] = None
    outgoing: bool  # True when the queried item is the "from" (original)
    kind: str
    meta: dict = {}
    # Bounding boxes on the link (relative to the ``to_item`` frame). Drawn on the
    # link's hover thumbnail; a link with ≥1 box shows an icon after its name.
    boxes: list[LinkBoxOut] = []
    # Free-form user "link tags" on this relationship (separate from item tags).
    tags: list[str] = []


class RelationshipCreate(RequestModel):
    from_item_id: int
    to_item_id: int
    kind: str = "manual"
    meta: dict = {}


class RelationshipTagBody(RequestModel):
    # A free-form link-tag name to add to a relationship.
    name: str


# ---- tag boxes (bounding box / time range annotations) ----

class AssignTagBox(RequestModel):
    tag: str  # tag name (created + assigned to the item if missing)
    box: TagBox
    # The file the box was drawn on; its crop maps the box into the item's
    # reference frame so the annotation stays aligned across file versions.
    file_id: Optional[int] = None
    # Which tag group this box's instance belongs to (None = ungrouped default).
    group_id: Optional[int] = None


# ---- per-item tag groups ----

class TagGroupCreate(RequestModel):
    name: str = "New group"


class TagGroupUpdate(RequestModel):
    name: str


class TagGroupTagBody(RequestModel):
    """One meta tag added to a per-item tag group (same namespace as a link's
    or a caption's)."""
    name: str


class MoveTagInstance(RequestModel):
    """Move a tag instance from one group to another (None = ungrouped)."""
    name: str  # tag name
    from_group_id: Optional[int] = None
    to_group_id: Optional[int] = None


class AddTagToGroup(RequestModel):
    """Add a tag as an instance in a specific group (None = ungrouped). The same
    tag may live in several groups at once (each is its own placement)."""
    tag: str
    group_id: Optional[int] = None
    negative: bool = False


class PlacementSign(RequestModel):
    """Flip ONE tag instance's sign — the row's dot, not the whole tag.

    The same tag may be positive in one group and negative in another on one
    item; the assignment (what search reads) re-derives as negative only when
    every instance is."""
    negative: bool


class UpdateTagBox(RequestModel):
    """Update a bounding box in place (annotation editor). Geometry is optional
    (all four provided together, in the given file's frame); ``tag`` optionally
    re-labels the box, moving it to that tag's placement in the same group."""
    x: Optional[float] = None
    y: Optional[float] = None
    w: Optional[float] = None
    h: Optional[float] = None
    file_id: Optional[int] = None
    tag: Optional[str] = None
    # A video subject moves, so a timed box's range can be edited in place. Any
    # field given as None below is left unchanged; use the sentinels to clear.
    time_start: Optional[float] = None
    time_end: Optional[float] = None
    track_id: Optional[int] = None
    # The timed box's own sign (None = leave unchanged).
    negative: Optional[bool] = None
    # Because None means "leave unchanged" above, these opt-in flags allow
    # explicitly clearing a field to null (e.g. converting a timed box back to a
    # whole-duration one).
    clear_time: bool = False
    clear_track: bool = False
    # Replace the box's polygon (`TagBox.points`; the rectangle re-derives
    # from it), or clear it back to the plain rectangle. A rect-only update
    # of a polygon box transforms the stored vertices with the rectangle.
    points: Optional[list[list[float]]] = None
    clear_points: bool = False


# ---- history / event log ----

class EventOut(BaseModel):
    id: int
    created_at: str  # ISO timestamp
    source: str  # "web" | "cli"
    username: str = ""  # who made the change ("" = anonymous / CLI)
    action: str
    entity_type: str = ""
    entity_id: Optional[int] = None
    summary: str = ""
    # The summary's unfilled template and slot values — additive, so the UI
    # can say the sentence in its own language; empty for rows written before
    # the columns existed (`summary` is the English fallback). A var may be a
    # nested {key, vars, text} object (the "Reverted: …" case).
    summary_key: str = ""
    summary_vars: dict = {}
    data: dict = {}
    reverted: bool = False
    revertible: bool = False


class HistoryPage(BaseModel):
    events: list[EventOut]
    total: int


class RevertRequest(RequestModel):
    event_ids: list[int]


class RevertResult(BaseModel):
    reverted: list[int]
    failed: list[int]
    # The log entries the reversal wrote, newest-first like `reverted`.
    # Reverting them replays the original — that is what a Redo does.
    events: list[int] = []


class ClearHistoryResult(BaseModel):
    #: How many entries were removed. The log is not empty afterwards — one
    #: entry is written saying this happened, since a log that is simply empty
    #: cannot be told from a library nobody has ever edited.
    deleted: int


# ---- library stats ----

class LibraryStats(BaseModel):
    items: int
    files: int
    # Total bytes of stored file versions (sum of File.bytes).
    bytes: int
    # Per-kind item counts (image / video / sequence container).
    images: int = 0
    videos: int = 0
    sequences: int = 0
    # Number of hidden items (drives the sidebar's Hidden category visibility).
    hidden: int = 0
    # Items with pending AI tags/captions (drives the "Pending" category).
    pending: int = 0
    # Split of the above into items with pending tags vs. pending captions (an
    # item can be in both). Drive the Pending category's Tags/Captions subgroups.
    pending_tags: int = 0
    pending_captions: int = 0
    # Items carrying a face a detector named by itself, still unconfirmed.
    pending_faces: int = 0
    groups: int = 0
    tags: int = 0
    # Absolute path to the library's data directory (shown in the footer).
    data_dir: str = ""
    # What this library calls a near-duplicate: the Hamming distance over the
    # 256-bit perceptual hash that dedup matches within, and the default a
    # `SIMILAR:` condition takes when it names no tolerance of its own. Here
    # because the query builder's slider has to show where "the library's own
    # answer" sits — a slider cannot express "unset" by having no position.
    phash_threshold: int = 10
    # Free / total bytes of the VOLUME holding the data directory — the space
    # imports and edits actually consume. 0 when it can't be read (a permission
    # error or an unmounted path); the UI then shows nothing rather than "0 B
    # free", which would look like a full disk.
    disk_free: int = 0
    disk_total: int = 0


# ---- storage ---------------------------------------------------------------
# What is on disk, by TYPE, so the answer to "why is this library 200 GB" is
# on one page. Every row is a KEY and two numbers, never a sentence: the words
# are the frontend's, like every other label this API produces.


class StorageRow(BaseModel):
    """One line of the breakdown: a key the frontend words, and what it costs."""

    key: str
    count: int = 0
    bytes: int = 0


class StorageArtifactRow(BaseModel):
    """One artifact TYPE — the unit the page's delete button acts on.

    ``kind`` and ``model`` together are that unit ("the sd15 latents"), and
    both travel back to the delete endpoint verbatim. ``cache`` says the bytes
    are regenerable at no cost but the next run's re-encode, which is what the
    UI asks about differently: a depth map deleted is a model run to redo.
    """

    kind: str
    model: str = ""
    count: int = 0
    bytes: int = 0
    cache: bool = False


class StorageOut(BaseModel):
    data_dir: str = ""
    # Source files, grouped by the kind of ITEM they belong to.
    items: list[StorageRow] = []
    # Generated artifacts, grouped by (kind, model).
    artifacts: list[StorageArtifactRow] = []
    # Everything in the library folder that is not an item's own bytes —
    # thumbnails, the database, training runs. Measured by walking, so each
    # row is what that directory actually holds.
    other: list[StorageRow] = []
    # What emptying the trash would give back (already counted in `items`:
    # a trashed item is still a stored item until it is deleted for good).
    trashed: StorageRow = StorageRow(key="trashed")
    disk_free: int = 0
    disk_total: int = 0


class StoragePruneRequest(RequestModel):
    """The Storage page's file-prune rule — see `ops.files.PruneRule`.

    The three thresholds are MINIMUMS a file must clear, so a file below any
    of them is removed; the two keep flags spare what the thresholds matched.
    0 means "not set" for each number, which is why none is Optional: a rule
    with no threshold at all is a real rule ("drop everything that is not the
    active file"), not a missing one.
    """

    keep_active: bool = True
    keep_edited: bool = True
    min_megapixels: float = Field(0, ge=0, le=10_000)
    min_short_edge: int = Field(0, ge=0, le=1_000_000)
    min_long_edge: int = Field(0, ge=0, le=1_000_000)
    #: "" is every kind; "image" and "video" confine the rule to one. A
    #: Literal rather than a free string, so a typo is a 422 naming the field
    #: rather than a rule that silently matches nothing.
    kind: Literal["", "image", "video"] = ""


class StoragePruneOut(BaseModel):
    """What a prune did, or — from the preview — what it would do.

    ``items`` is the count left with no file at all and therefore deleted;
    it is the figure that says a rule aimed at duplicates is about to remove
    pictures, so it is reported separately rather than folded into ``files``.
    """

    files: int = 0
    bytes: int = 0
    items: int = 0


class StoragePruneJobOut(StoragePruneOut):
    """A prune RUN: what it has removed so far, out of what it set out to.

    A prune is minutes of work over a large library, so it is a background
    task rather than a request held open — `files`/`bytes`/`items` are the
    running totals and `total` is the file count the preview promised, which
    is what makes a percentage possible. `total` is fixed at the start and
    never re-read: the rule matches fewer files with every committed chunk,
    so a total recomputed as it goes would count down towards a moving
    number and the bar would never fill.
    """

    id: str
    #: "running" | "done" | "cancelled" | "error"
    status: str = "running"
    total: int = 0
    #: The failure, when `status` is "error". Empty otherwise.
    message: str = ""


class AppSettings(RequestModel):
    # Optional per-model-family local paths (a downloaded model directory used
    # instead of fetching from Hugging Face). Keyed by family id
    # (a plugin source key). The HF access token is NOT stored here — it comes
    # from the environment only (see the /hf-token endpoint). AI jobs always run
    # with local_files_only, so there is no per-model offline flag.
    model_paths: dict[str, str] = {}
    # What double-clicking a grid item does. Image: "quicklook" (default) |
    # "annotate" (tag annotator) | "editor" (image editor) | "none". Video:
    # "quicklook" (default) | "editor" | "none".
    dblclick_image: str = "quicklook"
    dblclick_video: str = "quicklook"
    # Which Florence-2 checkpoint the action menus offer ("florence2_base" or
    # "florence2_large"). Only one is active at a time.
    florence_model: str = "florence2_base"
    # Language & Region. ``language`` is the UI language — one of
    # ``settings._LANGUAGES`` (named there rather than listed here, where a
    # list goes stale with every language added); ``date_format`` is one of a
    # fixed set of patterns (see settings._DATE_FORMATS); ``time_24h``
    # toggles 24-hour vs 12-hour clock. Validated in the router.
    language: str = "en"
    date_format: str = "D MMM YYYY"
    time_24h: bool = False
    # THE TWO "HIDE A PIECE OF UI" SETTINGS, both SERVER-WIDE and both
    # default OFF. Whether a deployment offers a thing at all is a fact about
    # the deployment rather than a taste, and with one of these per user and
    # the other global the same switch meant two things depending which one
    # you had found (owner 2026-09; `hide_unready_actions` was per user).
    #
    # Hide AI actions whose dependencies or weights are not ready, instead of
    # offering them with a "needs download" / "Run setup" chip — the chips are
    # how a fresh install discovers what it could set up, hence OFF. Settings →
    # Actions is unaffected either way: it is where you go to set one up, so
    # hiding things there would be a trap.
    hide_unready_actions: bool = False
    # Take the Faces tab out of the header. It hides the TAB and nothing else:
    # detection still runs, Pending → Faces still fills, and the annotator
    # still asks who somebody is — a library nobody works faces in should not
    # carry the queue in its header, which is not the same as turning the
    # feature off.
    hide_faces_tab: bool = False
    # Prepended to the tag name INVENTED for a new subject / place / event
    # ("subject:" gives `subject:albert_einstein`), so each kind gets a
    # namespace of its own and `place:berlin` can sit beside a plain `berlin`.
    # A tag typed by hand is never touched. Global, not per user: it shapes the
    # tag catalog everyone in the library shares.
    subject_tag_prefix: str = "subject:"
    place_tag_prefix: str = "place:"
    event_tag_prefix: str = "event:"
    # How alike two faces must be before a detection is given a name by itself
    # (cosine similarity, 0..1). The same number decides which unnamed cluster
    # a face joins, so one dial covers both halves of "who is this".
    # `faces.MATCH_DEFAULT` is the one definition of this number; kept here as
    # a literal because a schema default is part of the wire contract.
    face_match_threshold: float = 0.90
    # What the watermark detector tags what it finds with (boxes on this tag,
    # which the box-driven watermark removal then consumes). Empty falls back
    # to the default. Global like the prefixes: it shapes the shared catalog.
    watermark_tag: str = "watermark"
    # OPTIONAL: a tag every OCR run additionally records its regions' boxes
    # under. Empty (the default) means OCR writes text regions only.
    text_tag: str = ""


class ModelCacheInfo(BaseModel):
    key: str
    label: str
    repo: str
    url: str
    gated: bool
    # torch+transformers importable (needed to run the model).
    deps_ok: bool
    # Weights present (in the HF cache or at the local path override).
    cached: bool
    # A download is currently in progress for this model.
    downloading: bool = False
    # …and is WAITING for a slot rather than moving bytes (see
    # `hub.download.MAX_PARALLEL`). Still `downloading` — it has been accepted
    # and will run — but a spinner at 0% for ten minutes reads as a hang.
    queued: bool = False
    # Download progress as a percentage while downloading (0-100), or -1 unknown.
    progress: int = -1
    # Bytes fetched / bytes this download has to fetch (0 when not known), so
    # the UI can say "3.2 GB of 7.1 GB" rather than only a percentage.
    done_bytes: int = 0
    total_bytes: int = 0
    # Last download error for this model (cleared on a new/successful download).
    download_error: str = ""
    # The user's local path override for this family, or "".
    local_path: str = ""
    # Plugin key for the runnable "Run setup" button ("" when none).
    setup_key: str = ""
    # Coarse model type ("Upscaling", "Captioning", …) used to group the Settings
    # model list. "" when it doesn't map to a known task.
    category: str = ""
    # Weights that do not come from Hugging Face: the row has no repo, but a
    # Download still means something because the plugin fetches its own.
    fetchable: bool = False
    # Rough VRAM estimate to run the model (e.g. "~4 GB"), shown as a badge; ""
    # when unknown.
    vram: str = ""
    # On-disk size of the downloaded weights in bytes (0 when not cached from the
    # hub); shown next to "Delete download".
    size: int = 0


class ModelCacheOut(BaseModel):
    models: list[ModelCacheInfo]
    # A Hugging Face token is available in the environment, which gates
    # downloading gated models.
    token_available: bool
    # Non-empty (e.g. "HF_HUB_OFFLINE=1") when the launch environment forces
    # Hugging Face offline mode, so the UI can warn about it.
    env_offline: str = ""


# ---- rankings ----------------------------------------------------------------


class RankingPoolRow(BaseModel):
    """One pool of a ranking — a population with standings of its own.
    ``name`` is ``""`` for the unnamed first one (the UI says "Default");
    the counts are that pool's own, off its judgments."""
    id: int
    name: str = ""
    # Whether its comparisons can order its pictures at all. False and the
    # pool is still rated and still fitted; it just has nothing the scale
    # can honestly say yet (`rankingmath.enough_comparisons`), so the
    # Assign-ratings action passes it by.
    settled: bool = True
    judgments: int = 0
    items: int = 0


class RankingRow(BaseModel):
    id: int
    name: str
    scope: str
    # The bucket range, inclusive both ends — the scale the standings are
    # spread over, and what the Assign-ratings rules are written against.
    bucket_lo: int = 0
    bucket_hi: int = 9
    # How many judgments the axis holds. Coverage figures are deliberately
    # NOT here: the pool is a fact about a rating SESSION (the selection or
    # view it was opened over), so a list-level "x of y placed" was a number
    # about a scope nobody had picked yet — and computing it resolved the
    # whole library once per row.
    judgments: int = 0
    # DISTINCT items the judgments name — how many pictures the axis has
    # placed. Off the evidence, which is all a ranking has.
    items: int = 0
    #: The FILE ids of this ranking's best few pictures — the 2x2 mosaic on
    #: its card in the grid, the way a sequence's cover is its first pages.
    #: Empty unless the caller asked for covers (`GET /api/rankings?thumbs=`),
    #: since filling them costs a fit per ranking.
    thumbs: list[int] = []
    # Pictures set aside as NOT APPLICABLE to this axis — ranking-wide, never
    # per pool. Its own number because it is its own row in the sidebar: the
    # ones somebody looked at and said this axis is not about, which is a
    # place to go and look rather than a fact hidden in a panel.
    dismissed: int = 0
    # The ranking's pools, oldest first — always at least one. The rate
    # chooser offers a pick only past one.
    pools: list[RankingPoolRow] = []


class RankingPoolCreate(RequestModel):
    name: str


class RankingPoolUpdate(RequestModel):
    #: A field left out is left alone — the ranking's own PATCH shape.
    name: str | None = None


class RankingPoolOrder(RequestModel):
    #: Every pool of the ranking, once, in the order wanted.
    pool_ids: list[int]


class RankingCreate(RequestModel):
    name: str
    scope: str = ""
    bucket_lo: int = 0
    bucket_hi: int = 9


class RankingUpdate(RequestModel):
    name: Optional[str] = None
    scope: Optional[str] = None
    bucket_lo: Optional[int] = None
    bucket_hi: Optional[int] = None


class RankingItemRef(BaseModel):
    """One item in a rating card or a detail strip — enough to draw it.

    `kind` is what the card renders (a film plays, a sequence flips), and a
    container's `members` are the pages the card flips through — one level
    only, so a ref inside `members` carries none of its own."""
    item_id: int
    uid: str = ""
    name: str = ""
    kind: str = "image"
    file_id: Optional[int] = None
    thumb_token: str = ""
    width: int = 0
    height: int = 0
    #: The item's non-destructive display rotation, so a session card shows
    #: the picture the way the library does — and so the card's own rotate
    #: buttons have something to move.
    rotation: int = 0
    members: list["RankingItemRef"] = []


class EstimateRuleIn(RequestModel):
    """One BAND of the ranking's scale, and what to write in it.

    A rule says where its band STARTS. The bands are the rules sorted by
    that number, each running up to the next one's start, the last with no
    top (`estimatemath.bands`) — so they partition the scale and a picture
    belongs to exactly one. They were two optional inclusive ends until
    2026-09 ("8 and up", "between 4 and 6"), which is two fields somebody
    had to keep from overlapping and a shape in which "a picture at 9 is
    claimed by both these rules" was the documented behaviour.

    ``tags`` carries the SIGN in the name, the importer's convention (a
    leading ``-`` is a negative assignment) — one field, so the dialog is
    one tag box per rule rather than two people have to guess between.
    """
    min: Optional[float] = None
    tags: list[str] = []
    #: Groups the matching pictures JOIN. Nothing is ever taken out — an
    #: estimate adds what it claims and never unsays what somebody filed.
    groups: list[int] = []


class RankingEstimateRequest(ItemSearchRequest):
    """Estimate a ranking's scale over the scope's pictures, and write the
    rules' tags onto what the estimate claims.

    The scope travels as the search body itself, the way every whole-view
    write sends one. ``items`` NARROWS here, unlike the rating and tag
    sessions' priority rule: this is one bulk write rather than a queue, so
    a selection means the pictures somebody picked out for it.

    ONE body, TWO paths: `/estimate` previews (a bounded scrambled sample,
    writing nothing — a read-only POST by pattern) and `/estimate/apply`
    queues the write as a background job. The path says which, rather than a
    flag in the body: a stale tab may preview, and what it may not do is
    stamp tags, which is a distinction the build check makes by PATH.
    """
    items: list[int] = []
    #: Whose standings the estimate learns from. Empty = the ranking's
    #: enabled pools, fitted together (one scale is being estimated).
    pool_ids: list[int] = []
    #: The embedding spaces, fused. Empty = every space set up, as the tag
    #: batch's own default.
    embedders: list[str] = []
    rules: list[EstimateRuleIn] = []
    #: GUESS AT THE PICTURES THE RANKING HAS NOT PLACED, and read the rules
    #: against them too. Off, only the ones it HAS are covered, each at its
    #: own standing — which is the honest floor of the action: what somebody
    #: actually judged, written down.
    #:
    #: A picture the ranking placed is ALWAYS read at its own standing,
    #: never at the fit's answer about it: the guess would be NEAR the
    #: standing rather than it, and could drop it into a different band
    #: depending on the noise.
    #:
    #: It was `apply_to`, three answers where the question is one thing
    #: being turned on.
    estimate_unranked: bool = True


class EstimateRuleOut(BaseModel):
    """Per rule, how many pictures it claimed (and, in a preview, would) —
    with a handful of them to look at.

    The sample is PER RULE rather than one for the whole request: a rule is
    a claim about pictures, and the only way to see whether the claim
    travelled is to look at what THAT rule takes.
    """
    matched: int
    tags: list[str] = []
    groups: list[int] = []
    sample: list["RankingItemRef"] = []
    sample_scores: list[float] = []


class RankingEstimateOut(BaseModel):
    """What the estimate found and what it wrote.

    ``rated`` is the evidence the fit rests on, ``estimated`` the pictures
    it could answer for, and ``unindexed`` the ones it could not — no vector
    in any chosen space, which is a thing to go and fix rather than a
    failure of the estimate.
    """
    rated: int
    estimated: int
    unindexed: int
    #: How many pictures were LOOKED AT. A write walks the whole scope; a
    #: preview draws a bounded scrambled sample of it, since it runs on
    #: every edit of a rule and reading every vector in a million-item
    #: library for a number nobody has committed to yet is minutes of work
    #: per keystroke.
    scanned: int = 0
    #: Whether that was less than the scope holds — the counts above are
    #: exact over what was scanned and nothing more.
    partial: bool = False
    #: What the scope holds, where the preview asked. None on a write.
    total: Optional[int] = None
    rules: list[EstimateRuleOut] = []


class RankingEstimateJobOut(BaseModel):
    """What queueing the write answers: the job that will do it.

    Nothing else, and nothing about what it will write — the counts are the
    preview's, already on screen. A million-item scope is minutes of walking
    and hundreds of thousands of tag rows, so the write is a background job
    like a video render: the dialog closes, the task list carries the
    progress and the cancel, and what has been written when a cancel lands
    STAYS (it is committed in chunks, and a tag somebody asked for is not a
    partial artifact).
    """
    job_id: int


class RankingPairRequest(ItemSearchRequest):
    """The rating overlay's "next pair" request: the session's scope, sent the
    way every whole-view write sends one (the search request itself, so the
    pool cannot drift from what the grid shows). ``items`` is the grid
    selection the session was opened over — a PRIORITY, never a narrowing:
    those pictures are compared first, each against partners from the whole
    pool. ``recent`` is what the session just showed, so the same two
    pictures do not bounce straight back. A read-only POST — it is named in
    ``build.READ_ONLY_POSTS``."""
    items: list[int] = []
    recent: list[list[int]] = []
    #: WHOSE evidence the pick and the standings read — the session's
    #: picked pools of this ranking. Empty means the ranking's default
    #: pool, which is what every caller before pools existed meant.
    pool_ids: list[int] = []
    #: Ask for the standings WITHOUT a pair — the overlay's mid-session
    #: summary button (and its Esc). The reply carries `summary` only.
    summary_only: bool = False
    #: Whether the reply needs the pool's SIZE.
    #:
    #: It is one `count(*)` over everything the scope admits — 200 ms at a
    #: million items — and it is asked once per KEYPRESS for a number that
    #: cannot move: the scope is captured when the session opens, and
    #: judging changes what is KNOWN about the pool, never what is in it. So
    #: the overlay asks once and then says no; `pool` comes back null and it
    #: keeps the figure it already has.
    #:
    #: Default TRUE, so a caller that says nothing (a script, an older page)
    #: gets exactly the reply it always got.
    want_pool: bool = True


class TagSortGroupIn(RequestModel):
    """One group of a tag-batch session: which of the session's tags, and
    whether they are mutually exclusive (the group's tags then teach each
    other's negative side, and a candidate claimed by several joins the
    likeliest one's stretch)."""
    tags: list[str] = []
    exclusive: bool = False


class TagSortNextRequest(ItemSearchRequest):
    """The tag-batch overlay's session feed: the scope the way every
    whole-view request sends one (the search body), the session's tags, and
    what the session already showed. ``items`` is the grid selection the
    session was opened over — the queue's PRIORITY, never a narrowing: those
    pictures are asked about first, and the classifier orders the rest.
    Stateless — the answers are ordinary writes, so the fit's labels are just
    the tags' current assignments; only the SESSION-LOCAL signal travels:
    ``recent`` (shown items, the skip memory) and ``session_negatives``
    (toggling mode with the negatives option off — committed-but-untoggled
    tags, fed to the fit and never written). A read-only POST, named in
    ``build.READ_ONLY_POSTS``."""
    items: list[int] = []
    tags: list[str] = []
    #: The session's GROUPS — each a subset of ``tags`` with its own
    #: exclusivity. A tag in none stands alone. ``tag_groups`` and not
    #: ``groups``, which is the SCOPE's field (group ids) on every search
    #: body this one inherits.
    tag_groups: list["TagSortGroupIn"] = []
    #: Per tag, the COUNTER tag its "doesn't fit" assigns POSITIVELY in
    #: place of the negative (the tag grid's `negative_tag`, per tag): its
    #: positives are negative labels for the fit, and an item carrying one
    #: is decided.
    counter_tags: dict[str, str] = {}
    recent: list[int] = []
    #: The queue the overlay still holds unshown from its last fetch. Those
    #: are the candidates the last fit ranked highest, and the scored sample
    #: is drawn afresh per fetch — so without this they would be scored again
    #: only by luck (a fifth of the time at a million items) and the ordering
    #: could never accumulate. They are re-admitted against the scope and the
    #: session's exclusions like any candidate, so a stale id is harmless.
    carry: list[int] = []
    session_negatives: dict[str, list[int]] = {}
    #: How many queue refs to return; 0 = the chooser's coverage probe
    #: (counts only, no refs, no scoring).
    count: int = 20
    #: The chooser's "Smart ordering" switch. Off, the feed skips the fit
    #: entirely and returns plain pool order — the coverage counts still
    #: travel, since the chooser reads them either way.
    smart: bool = True
    #: Which embedding space orders the queue (a plugin model id from
    #: `itemvec.EMBEDDERS`) — the chooser's DINOv2 / CLIP choice. Spaces are
    #: never mixed: coverage, the fit and the scores all read this one.
    embedder: str = "dinov2_small"
    #: One space or SEVERAL — the tag grid's `embedders`: with two, each is
    #: fit and scored on its own and an item's score is the mean of the
    #: spaces it is indexed in, so a picture indexed in either is scored and
    #: the two kinds of likeness (DINOv2's look, CLIP's meaning) both count.
    #: Empty means `embedder` alone, which is what every older client sends.
    embedders: list[str] = []
    #: Whether the reply needs the pool's SIZE.
    #:
    #: It is a `count(*)` over everything the scope admits minus what is
    #: already decided — 750 ms at a million items — and it is asked once per
    #: ANSWER for a number the overlay can already work out: every item the
    #: session is handed leaves the candidate set exactly once (answered it
    #: is decided, skipped it is in `recent`), so what is left is the figure
    #: from the chooser's probe minus how many have been shown.
    #:
    #: Default TRUE, so a caller that says nothing gets the reply it always
    #: got; the CHOOSER's probe (`count <= 0`) always counts, since that is
    #: the number it exists to fetch.
    want_pool: bool = True


class TagSortNextOut(BaseModel):
    queue: list[RankingItemRef] = []
    #: Candidates left (after exclusions and `recent`) — NULL where the
    #: request said it already knows (`TagSortNextRequest.want_pool`), which
    #: is every feed after the chooser's own probe.
    pool: Optional[int] = None
    #: Coverage over the POOL: how many carry a current vector.
    embedded: int = 0
    #: The same figure as `pool`, and nullable for the same reason — the
    #: chooser reads this one, the session header the other.
    total: Optional[int] = None
    #: Whether the queue is classifier-ordered (false = plain pool order —
    #: no vectors, or nothing labeled positive yet).
    ordered: bool = False
    #: Per set tag, (positive, negative) label counts — the header's figures.
    labeled: dict[str, tuple[int, int]] = {}
    #: Per requested embedder, how many of the pool carry ITS vector — the
    #: chooser's per-space coverage lines; `embedded` is "any space".
    coverage: dict[str, int] = {}


class TagSortIndexRequest(ItemSearchRequest):
    """Fill missing feature vectors for a scope — a WRITE (it enqueues the
    embed batch job), so deliberately NOT a read-only POST."""
    items: list[int] = []
    #: Which embedder to run (`itemvec.EMBEDDERS`) — must match the space
    #: the session will read.
    embedder: str = "dinov2_small"


class TagGridTagIn(RequestModel):
    """One tag of the grid session's set, with its "doesn't fit" spelling."""
    name: str
    #: "" is the tag itself, negatively; a name is a COUNTER tag assigned
    #: POSITIVELY in its place.
    negative: str = ""


class TagGridNextRequest(ItemSearchRequest):
    """The tag-grid overlay's batch feed — the tag-batch session's sibling
    for the mouse. The scope the way every whole-view request sends one, the
    SET of tags the session asks about, what it already showed (``recent``),
    and how big a batch to pre-sort. ``items`` is the grid selection the
    session was opened over — the batch's PRIORITY, never a narrowing.

    THE QUESTION IS A CONJUNCTION: a picture is a positive example when it
    carries EVERY tag of the set, and a negative one when anything speaks
    against ANY of them (that tag negatively, or its paired counter tag
    positively). Anything else is undecided, which is the pool. The two
    answers are ASYMMETRIC: "fits" decomposes into each conjunct and is
    written as ordinary assignments, "doesn't fit" is only ``NOT a OR NOT
    b`` and past one tag writes nothing — it reaches the fit as
    ``session_negatives`` instead.

    ``embedders`` names one space or two: with two, each is fit and scored
    on its own and an item's score is the mean of the spaces it is indexed
    in (see ``taggridmath.fuse``). ``boundary`` is the chooser's "show
    uncertain pictures" switch — on, half of every batch is drawn from where
    the model is least sure; off, the batch is the top of the ranking. A
    read-only POST, named in ``build.READ_ONLY_POSTS``."""
    items: list[int] = []
    #: The set. Each entry is a tag and, optionally, the COUNTER tag its
    #: "doesn't fit" assigns POSITIVELY in place of the negative
    #: (`small` beside `big`) — whose positives are negative labels and
    #: leave the pool as decided, exactly as that tag's negatives do.
    tags: list["TagGridTagIn"] = []
    #: Keep pictures the tag (or the counter tag) is already on in the pool.
    #: They come with ``existing`` set and start on what they carry rather
    #: than on the classifier's guess — a way to check tags already given.
    include_tagged: bool = False
    recent: list[int] = []
    #: THE SESSION'S OWN "doesn't fit" ANSWERS, fed to the fit and never
    #: written — the tag batch's ``session_negatives``, as one flat list
    #: because the grid's question is one SET rather than a row per tag.
    #: A conjunction's "no" is ``NOT a OR NOT b``, which no assignment can
    #: spell, so past one tag the answer writes nothing at all and would be
    #: forgotten between batches without this. They are the freshest thing
    #: anybody has said about the set, so they outrank the sampled negatives
    #: at the label cap and beat a positive the library holds.
    session_negatives: list[int] = []
    #: How many pictures a batch shows; 0 = the chooser's coverage probe
    #: (counts only, no refs, no scoring).
    count: int = 16
    smart: bool = True
    embedders: list[str] = ["dinov2_small"]
    boundary: bool = True
    #: Whether the reply needs the pool's SIZE — asked once per session (the
    #: session feed's `want_pool`, for the same reason).
    want_pool: bool = True


class TagGridItem(RankingItemRef):
    """One picture of a batch: the card's ref plus where the classifier put
    it. ``score`` is the fused score (None where the item carries no vector
    in any named space), ``bucket`` the band it PRE-FILLS — a suggestion the
    person moves, never an assignment."""
    score: Optional[float] = None
    bucket: str = "none"
    #: What the picture ALREADY carries, for a session that includes tagged
    #: pictures: "positive" (the tag), "negative" (its negative, or the
    #: counter tag), "both" (the tag and the counter tag), else None.
    existing: Optional[str] = None


class TagGridNextOut(BaseModel):
    queue: list[TagGridItem] = []
    #: Candidates left — NULL where the request said it already knows.
    pool: Optional[int] = None
    total: Optional[int] = None
    #: Coverage over the pool: how many carry a current vector in ANY named
    #: space (what can be scored at all)…
    embedded: int = 0
    #: …and per embedder, which is what the chooser's index buttons need.
    coverage: dict[str, int] = {}
    #: Whether the batch is classifier-sorted (false = nothing to go on).
    ordered: bool = False
    #: (positive, negative) label counts — the header's figures.
    labeled: tuple[int, int] = (0, 0)
    #: The calibrated cuts the bands were drawn at, for the curious.
    cut_hi: Optional[float] = None
    cut_lo: Optional[float] = None


class RankingSummaryOut(BaseModel):
    """One placed picture of an exhausted session, with the BUCKET its
    current standing lands in — computed on READ and written nowhere. A
    ranking tags nothing (rung v31); this is what the session has to show
    for itself, and the number is the scale's own."""
    ref: RankingItemRef
    bucket: int = 0
    #: The pool this standing is in — the entries arrive pool by pool
    #: in the request's order, so one item may appear once per pool.
    pool_id: int = 0
    pool: str = ""


class RankingPairOut(BaseModel):
    a: Optional[RankingItemRef] = None
    b: Optional[RankingItemRef] = None
    # Why there is no pair, as a KEY the frontend words ("small_pool",
    # "no_subjects" later) — never a sentence.
    reason: str = ""
    #: How many items the session is rating over — NULL when the request
    #: said it already knows (`RankingPairRequest.want_pool`), which is
    #: every press after the first.
    pool: Optional[int] = None
    judgments: int = 0
    # With no pair left and something judged, how the session's pool stands
    # right now, best first — the overlay's end-of-session summary.
    summary: list[RankingSummaryOut] = []


class RankingJudgeIn(RequestModel):
    a_item_id: int
    b_item_id: int
    outcome: str
    #: ONE judgement, written into every pool named — one row and one
    #: event per pool. Empty = the ranking's default pool.
    pool_ids: list[int] = []


class RankingDismissIn(RequestModel):
    item_id: int


class RankingItemsIn(ItemSearchRequest):
    """WHICH PICTURES A RANKING VERB IS ABOUT, at any of the three sizes the
    sidebar offers it: one, a selection, or everything in the view.

    ``items`` names them; ``view`` says to act on the scope this body
    carries instead (every search body carries one, and for a view the ids
    never reach the browser). Naming NEITHER is refused rather than
    interpreted: "no ids" and "the whole view" are the two answers a slip
    between them would confuse, and one of them is a write over a scope
    nobody enumerated — the lesson `/estimate` learnt when one path meant
    two things.
    """

    items: list[int] = []
    view: bool = False


class RankingItemsOut(BaseModel):
    """How many pictures the verb changed, and how many it was aimed at —
    `ViewActionOut`'s pair, for the same reason: a picture already set aside
    is skipped, and a caller that saw only the first number could not say
    so. ``judgments`` is what a removal deleted (nothing else fills it)."""

    count: int = 0
    total: int = 0
    judgments: int = 0


class RankingBucketOut(BaseModel):
    bucket: int
    count: int
    samples: list[RankingItemRef] = []


class RankingPoolDetailOut(BaseModel):
    """One pool's histogram — the detail draws one per pool."""
    id: int
    name: str = ""
    #: Hidden pools still fit and still draw their histogram; what they
    #: do not do is put their score tags on the pictures.
    enabled: bool = True
    #: Whether the comparisons can order the pictures yet — see
    #: `RankingPoolRow.settled`. The histogram is drawn either way.
    settled: bool = True
    judgments: int = 0
    scored: int = 0
    buckets: list[RankingBucketOut] = []


class RankingItemStanding(BaseModel):
    """WHERE ONE PICTURE STANDS in one ranking — the item half of a ranking,
    which is what survives a selection once the standings themselves are the
    grid's sections rather than a histogram in a panel."""
    #: Its bucket per pool, as `(pool id, pool name, bucket)`. Empty where the
    #: ranking has not placed it: unjudged, only ever skipped past, or set
    #: aside.
    placed: list[tuple[int, str, int]] = []
    #: How many decisive or tie judgments it has been part of, ranking-wide.
    #: What the standing is made OF, and the honest answer to "why is this a
    #: 3" — which the number alone cannot give.
    judgments: int = 0
    #: Set aside as not applicable to this axis. Reversible, and NOT the same
    #: as being removed: the judgments stay.
    dismissed: bool = False
    bucket_lo: int = 0
    bucket_hi: int = 0


class RankingDetailOut(BaseModel):
    id: int
    #: The FIRST pool's histogram and how many it placed — what the two
    #: fields meant before pools, kept for the readers of that shape; the
    #: per-pool answer is `pools`.
    buckets: list[RankingBucketOut]
    not_applicable: list[RankingItemRef] = []
    #: Ranking-wide: every pool's judgments.
    judgments: int = 0
    scored: int = 0
    pools: list[RankingPoolDetailOut] = []


GroupNode.model_rebuild()

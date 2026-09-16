"""SQLAlchemy 2.x models and session management (SQLite).

Schema notes:
- Groups form a TREE via ``group_parents`` (each group has at most one parent,
  enforced by ``UniqueConstraint(group_id)``). Items remain many-to-many with
  groups.
- A ``File`` is one source of an ``Item``; an item's ``active_file_id`` points at
  the version shown by default (largest on import). Every file's bytes live in
  its item's own folder (``items/<uid[:2]>/<uid>/files/<number>.<ext>``);
  ``source_kind`` records provenance only (a captured video frame / extracted
  clip is materialized to real bytes at creation).
- Tag assignments live on both items (``ItemTag``) and groups (``GroupTag``);
  group assignments are inherited by all descendants and may be negative. An
  ``ItemTag`` may carry ``ItemTagBox`` annotations (bounding boxes / time ranges).
- ``Sequence``/``SequenceItem`` model ordered collections (comic pages, video
  frames); an item may belong to several. ``Relationship`` records directional
  original->derived links (clips, frames, edits) between items.
"""

from __future__ import annotations

import itertools
import time
import weakref
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    Computed,
    Index,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

from . import dedup_index as _dedup_index
from .config import Config, config as default_config


# The library's on-disk FORMAT NUMBER. See `docs/compatibility.md` for what is
# a contract here and what is not.
#
# It is DERIVED: appending a step to
# `migrations.MIGRATIONS` IS the version bump, so the constant and the ladder
# cannot drift apart. Any schema change — a column added or dropped, a table
# reshaped, a stored encoding redefined — ships a step in the same commit, and
# `tests/core/test_migrations.py` fails the build when one does not.
#
# `create_all` adds missing TABLES and never ALTERs an existing one, so a
# library written by a different build opens *almost* correctly on its own:
# the queries run, a column that changed meaning is read as whatever it used
# to hold, and the first write bakes the mixture in. The number is what turns
# that into either an upgrade or a refusal, and never a silent mixture.
from .migrations import (
    CURRENT as SCHEMA_VERSION,
    LibraryMigrationError,  # re-exported: callers catch it from here
    LibraryVersionError,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


def new_uid() -> str:
    """A fresh item uid, for a caller that needs it BEFORE the row is
    flushed (the importer names the item's folder by it)."""
    return _new_uid()


def _new_uid() -> str:
    return uuid4().hex


#: ``Item.taken_at`` for "somebody looked and this picture has no date" — as
#: opposed to NULL, which is "nobody has said". See the column's own comment.
TAKEN_NONE = -1

#: "There is no coordinate for this item" said out loud, in ``Item.lat``.
#: Out of range for a real latitude (±90), so the one rule is the same shape
#: as ``taken_at``'s: a stored pair is a place, anything else is not.
COORD_NONE = -999.0


def normalize_taken(value: Optional[int]) -> Optional[int]:
    """A capture date at whatever width it arrived, as the stored 14-digit
    ``YYYYMMDDHHMMSS``.

    The library has TWO widths of the same encoding — ``YYYYMMDD`` for a
    subject's or an event's date, ``YYYYMMDDHHMMSS`` for a capture time — and
    ``Item.taken_at`` stores the second. A date-width value slipped in through
    the Python API for a while (``item.taken = "1503"`` stored ``15030000``),
    which every 14-digit reader misread: the grid's year grouping divides by
    10¹⁰ and filed the Mona Lisa under year 0. Scaling is a semantic no-op —
    the same date, in the column's own width — which is why this normalizes
    rather than refuses, the same tolerance ``query.taken_window`` extends
    when reading.

    Every real ``YYYYMMDD`` sits in [10⁴, 10⁸) — a year is ≥ 1, so the year
    digits alone reach 10000 — and every real ``YYYYMMDDHHMMSS`` is at least
    10¹⁰, so the widths cannot collide and widening once leaves the window
    (the rule is its own idempotence proof: 10⁴·10⁶ = 10¹⁰). ``None``, ``0``
    (clear), ``TAKEN_NONE`` and anything too small to be a date in either
    encoding pass through untouched — what cannot be read must not be
    rewritten. Migration step 5 applies the same rule to rows already stored.
    """
    if value is not None and 10_000 <= value < 100_000_000:
        return value * 1_000_000
    return value


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Stable, library-independent identity — names the item's on-disk folder
    # (``items/<uid[:2]>/<uid>/``) and every cross-item reference in the JSON
    # sidecars. Never reused; survives export/import between libraries.
    uid: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, default=_new_uid
    )
    name: Mapped[str] = mapped_column(String, default="", index=True)
    # Media kind: "image" or "video" (clips are videos too). Drives the grid
    # length badge and which editor opens.
    kind: Mapped[str] = mapped_column(String(16), default="image")
    # Which File version is the primary/displayed one.
    active_file_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("files.id", ondelete="SET NULL"), nullable=True,
        index=True,
    )
    # When the item is in several sequences, this one drives the grid number
    # badge. Null => use its first (or only) sequence, if any.
    main_sequence_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sequences.id", ondelete="SET NULL"), nullable=True,
        index=True,
    )
    # Derived-from link (editor "save as derived" points here).
    link_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("items.id", ondelete="SET NULL"), nullable=True,
        index=True,
    )
    # First time the image was seen in the library. Set once at creation and
    # never modified — drives the "First Import Date" sort.
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    # Most recent time the image was seen during an import (refreshed on every
    # re-import of the same image) — drives the "Recently Imported" sort. Seeded
    # to the creation time. Indexed for `library_rev`'s MAX() (the min/max
    # index optimization): a re-import TOUCH is the one order-shifting write
    # that logs no event and creates no row, so the fingerprint has to read
    # this column or an external crawler re-run reorders the default sort
    # with nothing the grid can notice (`_ensure_indexes` adds the index to
    # existing libraries; index-only, so no version bump).
    last_imported_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, index=True)
    # Bumped whenever the item's tags, captions, groups, name or files change, so
    # the grid can offer a "modification date" sort. Seeded to import time.
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    # Hidden items are kept in the library (and reachable via relationships) but
    # excluded from the grid and from every category count. They surface only in
    # the dedicated "Hidden" sidebar view.
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # WHEN THE PICTURE WAS TAKEN, as said by hand — the sortable
    # ``YYYYMMDDHHMMSS`` the metadata index uses, with **zeros for whatever is
    # unknown**, so `20200000000000` is "2020" and the encoding carries its own
    # precision.
    #
    # An OVERRIDE, not a copy: it wins wherever a capture date is read, and
    # EXIF is left exactly as it was — clearing this falls back to it, and a
    # re-index from the files cannot throw a hand-typed date away.
    #
    # ``TAKEN_NONE`` (-1) is the THIRD state, and it is why this is not simply
    # nullable: NULL means "nobody has said, so read the file and then the
    # events", while -1 means "somebody looked and there is no answer" — a
    # scanned print, a drawing, a screenshot of a screenshot. Without it a
    # wrong EXIF date could be replaced but never removed. A sentinel rather
    # than a second column because every real value is positive, so the two
    # states cannot collide, and there is exactly one rule to remember:
    # ``taken_at > 0`` is a date, anything else is not.
    #
    # Additive column: an existing library needs
    # ``ALTER TABLE items ADD COLUMN taken_at INTEGER`` or a fresh DB.
    taken_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True,
                                                    default=None)
    # WHERE IT WAS TAKEN, said by hand — the same three-state model as
    # ``taken_at`` and for the same reasons. NULL is "nobody has said, so read
    # the file"; a pair is an override that a re-index cannot throw away; and
    # ``COORD_NONE`` on the LATITUDE is "somebody looked and there is no
    # answer", which is how a wrong GPS fix off a borrowed camera is removed
    # rather than merely replaced. Both columns move together — a longitude
    # without a latitude is not a place.
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True,
                                                 default=None)
    lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True,
                                                 default=None)

    files: Mapped[list["File"]] = relationship(
        back_populates="item",
        foreign_keys="File.item_id",
        cascade="all, delete-orphan",
    )
    active_file: Mapped[Optional["File"]] = relationship(
        foreign_keys=[active_file_id], viewonly=True
    )
    captions: Mapped[list["Caption"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        order_by="Caption.position",
    )
    tags: Mapped[list["ItemTag"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )
    groups: Mapped[list["ItemGroup"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )


class File(Base):
    __tablename__ = "files"
    __table_args__ = (
        Index("ix_files_sha256", "sha256"),
        Index("ix_files_phash", "phash"),
        # One index per band-key column — what makes the near-dup probe 12
        # indexed lookups instead of a scan (`dedup_index._candidate_rows`).
        # Declared HERE and not in `_INDEX_DDL`, because `_ensure_indexes`
        # creates every model-declared index idempotently on existing tables,
        # so a fresh and an upgraded library get byte-identical DDL.
        *(Index(f"ix_files_b{i}", f"b{i}")
          for i in range(_dedup_index.BANDS)),
        # The colour search's ENUMERATED path looks a neighbourhood of
        # signatures up by value (`searchctx.neighbourhood`) — 1,597 of them
        # at the default tolerance — where it used to read every signature in
        # the library into Python. Same rule as the band keys: declared here,
        # so `_ensure_indexes` gives an existing library the identical index.
        Index("ix_files_color_sig", "color_sig"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    sha256: Mapped[str] = mapped_column(String(64))
    # Perceptual hash as a hex string (256-bit / 64 hex chars for the current
    # hash size). Nullable for non-image sources (e.g. the stored video itself).
    phash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # THE HASH'S 12 BAND KEYS, DERIVED and kept in lockstep by the
    # `before_flush` listener (`_sweep_flush_for_band_keys`) — never written
    # by hand. `dedup_index.BAND_SPEC` is the layout. NULL exactly where
    # `phash` is.
    b0: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    b1: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    b2: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    b3: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    b4: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    b5: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    b6: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    b7: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    b8: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    b9: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    b10: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    b11: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # COLOUR, FOR ORDERING AND BROWSING ONLY — never for matching. Dedup is
    # still the perceptual hash above plus `dedup.verify_match`; nothing in
    # `dedup.py` / `dedup_index.py` may read either of these columns, or what
    # counts as a duplicate changes silently.
    #
    # `color_key` is a SORTABLE key, not a hash: the mean OKLCh of the image
    # packed hue-major, so ordering by it numerically reads as a gradient —
    # greys first dark-to-light, then a hue wheel, each hue by chroma then
    # lightness. See `media.color_signature`.
    #
    # `color_sig` is a 64-bit colour PRESENCE hash (one bit per fixed bucket
    # the image spends more than a threshold share of itself in), compared by
    # Hamming distance and banded like `phash` — what `COLORLIKE:` reads.
    #
    # Both NULL for anything not hashed as a raster image, i.e. exactly where
    # `phash` is NULL. Additive columns, filled at IMPORT and nowhere else:
    # A library from before they existed keeps a NULL in them for every file
    # already in it — which reads as "no colour" and parks
    # those pictures in the last group of the colour sort. There is no repair
    # command any more (the four backfills were removed; `cli.py` says what
    # that costs), and a re-import does not help: an exact duplicate is
    # recognised and stores nothing.
    color_key: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    color_sig: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # HOW OFTEN THIS FILE'S THUMBNAIL HAS BEEN REPLACED.
    #
    # A thumbnail is derived, so the file's content hash was an honest cache
    # key for it — which is what `ItemOut.thumb_token` and the thumb ETag are.
    # Choosing which frame represents a film breaks that: the thumbnail's bytes
    # change while the file they came from does not, so every reader went on
    # showing the frame that had just been rejected. This counter is the
    # missing half of that key, and nothing else reads it.
    #
    # `text("0")` rather than the string "0": both spellings work, but only
    # this one emits `DEFAULT 0` — the same DDL the migration writes, which is
    # what `tests/core/test_migrations.py` holds an upgraded library to.
    thumb_rev: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"))
    # Path of the file's bytes relative to its item's folder (e.g.
    # ``files/1.jpg``). Every file has stored bytes.
    path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Provenance of the file's bytes (all kinds are stored on disk):
    #   "stored"      -> a plain imported/edited file
    #   "video_frame" -> a frame captured at ``source_start`` from
    #                    ``source_file_id`` (materialized at capture time)
    #   "video_clip"  -> the [source_start, source_end] excerpt of
    #                    ``source_file_id`` (materialized at creation)
    source_kind: Mapped[str] = mapped_column(String(16), default="stored")
    source_file_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("files.id", ondelete="SET NULL"), nullable=True,
        index=True,
    )
    source_start: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source_end: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Video properties (populated for stored videos and clips).
    duration: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    frame_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bitrate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    bytes: Mapped[int] = mapped_column(Integer)
    format: Mapped[str] = mapped_column(String(16))
    # The region of the item's reference frame (its original/base image) that
    # this file shows, normalized to [0,1]. A full frame is (0,0,1,1); a cropped
    # variant is a sub-rectangle. Tag bounding boxes are stored in reference-frame
    # coordinates and transformed through this crop for each file.
    crop_x: Mapped[float] = mapped_column(Float, default=0.0)
    crop_y: Mapped[float] = mapped_column(Float, default=0.0)
    crop_w: Mapped[float] = mapped_column(Float, default=1.0)
    crop_h: Mapped[float] = mapped_column(Float, default=1.0)
    is_derived: Mapped[bool] = mapped_column(Boolean, default=False)
    # Orientation of this file's *stored bytes* relative to the item's first
    # source file: ``rotation`` clockwise degrees (0/90/180/270) and ``mirrored``
    # a horizontal flip applied before the rotation. Together they span all eight
    # dihedral orientations. This is descriptive metadata for the Source list —
    # the pixels are already in this orientation (nothing is rotated at render
    # time), so a rotate produces a new file with rotated bytes.
    rotation: Mapped[int] = mapped_column(Integer, default=0)
    mirrored: Mapped[bool] = mapped_column(Boolean, default=False)
    derived_from_file_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("files.id", ondelete="SET NULL"), nullable=True,
        index=True,
    )
    # Stable per-item source-file number (#1, #2, #3 …), assigned eagerly at row
    # creation (see :func:`next_file_number`) and never reused — a deleted middle
    # file leaves a gap so surviving numbers (and the ``edit_chain`` that
    # references them) stay meaningful. Also names the on-disk file
    # (``files/<number>.<ext>``).
    number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # The full lineage of edit actions that produced this file, as JSON:
    # ``[{"from": <num>, "to": <num>, "action": "edit|bg|watermark|upscale|…"}]``.
    # Built at creation from the parent's chain, so it survives an intermediate
    # file being deleted (the numbers are historical). Empty for imports/rotations.
    edit_chain: Mapped[str] = mapped_column(Text, default="")
    # True when this file was superseded by an in-place overwrite but kept for
    # reference (per DESCRIPTION §Image editor).
    is_kept_original: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    item: Mapped["Item"] = relationship(
        back_populates="files", foreign_keys=[item_id]
    )


class FileArtifact(Base):
    """An auxiliary image *generated from* a source file — a depth map, a pose
    overlay, and so on. Unlike a :class:`File` it is **not** a selectable source
    of the item; it hangs off exactly one source file and is shown nested under
    it in the Source list. Deleted with its parent file (and thus with the item).
    The bytes live in the item's ``artifacts/`` folder
    (``artifacts/<file-number>-<kind>[-<model>].<ext>``); ``path`` is stored
    relative to the item folder, like ``File.path``."""

    __tablename__ = "file_artifacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), index=True
    )
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))     # "depth" | "pose" | …
    # The model id that produced it (shown as a human label in the UI).
    model: Mapped[str] = mapped_column(String, default="")
    sha256: Mapped[str] = mapped_column(String(64))
    path: Mapped[str] = mapped_column(String)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    bytes: Mapped[int] = mapped_column(Integer)
    format: Mapped[str] = mapped_column(String(16), default="png")
    # Set when the source file it was generated from is later edited (the pixels
    # changed, so this control image no longer matches) — surfaced as a badge so
    # the user knows to regenerate it.
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    # Another artifact this one was generated FROM, rather than from the source
    # file directly — a training latent encoded from a degraded copy of the
    # picture, which is the only case so far. It buys the Source list its second
    # level, and it makes invalidation one row to delete: the CASCADE takes the
    # latents down with the degraded image, which is right, because they
    # describe pixels that no longer exist.
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("file_artifacts.id", ondelete="CASCADE"),
        nullable=True, index=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Stable identity used by the JSON sidecars (group refs never use DB ids).
    uid: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, default=_new_uid
    )
    name: Mapped[str] = mapped_column(String, index=True)
    icon: Mapped[str] = mapped_column(String, default="folder")
    # Optional accent color (hex, e.g. "#4f8cff") for the group's icon.
    color: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # A SMART group's membership rule — a query STRING (the saved-search
    # tag set); NULL for an ordinary group. NULL against "" is an
    # IDENTITY, fixed at creation: an ordinary group never becomes smart nor
    # the reverse (ops/groups refuses the transitions), and a smart group
    # whose rule is still "" legitimately exists, holding nothing until the
    # query is written. Membership rows are DERIVED: `ops/smartgroups.
    # rebuild` is the one writer, manual assignment is refused, and a smart
    # group may not have child groups.
    smart_query: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    tags: Mapped[list["GroupTag"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class GroupParent(Base):
    """Tree edge: ``group_id`` has parent ``parent_group_id``.

    Groups form a tree — each group has **at most one** parent. The unique
    constraint on ``group_id`` alone enforces that a group can't be a child of
    more than one group. (Items, by contrast, may still belong to many groups.)
    """

    __tablename__ = "group_parents"
    __table_args__ = (UniqueConstraint("group_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    parent_group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )


class ItemGroup(Base):
    __tablename__ = "item_groups"
    __table_args__ = (UniqueConstraint("item_id", "group_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )

    item: Mapped["Item"] = relationship(back_populates="groups")


class TagRow(Base):
    """ONE NAME IN A TAG SET — the library's own, or an imported set's.

    ONE TABLE, and which tag set a row belongs to is a column (owner
    2026-09). A tag set used to be a table of its own (`tag_set_entries`,
    plus `tag_set_aliases` beside it) on the rule that a 10,000-entry booru
    dump should add nothing to the library's own list. It is one table now:
    the two hold the same thing — a name, what it is called besides, what it
    means, what it entails, what KIND of thing it is and where it is filed —
    and two tables meant every question asked twice, every index built twice,
    and every speed-up landing on whichever half somebody was looking at.

    `tag_set_id` says WHICH tag set (NULL is the library's own, an id is
    that set's) and `kind` says WHAT KIND OF NAME the row is. `kind` is the
    DISCRIMINATOR: `Tag`, `TagSetEntry` and `MetaTag` are mapped classes over
    this one table, so SQLAlchemy adds `kind = 'lib'` to every `select(Tag)`
    — every read, every join, every update, everywhere in the app, without a
    line of it saying so. That is what makes the merge safe: a query nobody
    remembered to scope still means the library's own tags, and it is an
    indexable equality rather than a `tag_set_id IS NULL` the planner cannot
    see through.

    THE THREE KINDS:

      `lib`   a tag of the library — the thing that goes on a picture.
      `set`   one name an imported set knows, and what it says about it.
      `meta`  a META TAG: a name that labels a link, a caption, a tag group
              or another TAG (`TagMetaTag`), never a picture. Its own
              namespace, which is why it is a kind rather than a flag —
              `red` the tag and `red` the meta tag are two different names
              and always were. `tag_set_id` applies here too: a set can
              carry the meta tags it wants its entries labelled with, and
              they travel in its file. Unlike the two above, `select(MetaTag)`
              does NOT scope itself to one tag set, so a read that means
              the library's own says `tag_set_id.is_(None)`.

    The library's name uniqueness is a PARTIAL unique index
    (`uq_tags_library_name_kind`, in `_ensure_indexes`) rather than a
    constraint here: with `tag_set_id` NULL for the library, SQLite counts
    every NULL as distinct, so a plain `UNIQUE (tag_set_id, name, kind)`
    would enforce nothing where it matters most. THE NAME LEADS IT, not the
    kind: a unique index reads the same either way round, and an index a
    seek can answer the DISCRIMINATOR from is one the planner drives whole
    joins from (see `_ensure_indexes`).
    """

    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("tag_set_id", "name", "kind", name="uq_tags_set_name"),
        Index("ix_tags_set", "tag_set_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, index=True)
    #: The lowercase name — what every lookup, every prefix range and the
    #: library/set join actually read. A column rather than `lower(name)` in
    #: fourteen places and an expression index under them: the set's half of
    #: the table always had one, and a plain column is an index the planner
    #: can use for a range, an `IN` and a join alike.
    #:
    #: GENERATED, so it cannot drift and nothing has to remember it: a hook
    #: on the ORM's `name` would have been right for every write the app
    #: makes and empty for every Core insert beside it (the perf fixture's
    #: 200,000 rows found that out). SQLite computes it; nothing may write
    #: it, which is why the rung's INSERTs list every other column.
    lname: Mapped[str] = mapped_column(
        String, Computed("lower(name)"), index=True)
    #: WHICH TAG SET. NULL is the library's own; an id is that set's, and
    #: the rows go with the set (CASCADE).
    tag_set_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("tag_sets.id", ondelete="CASCADE"), nullable=True,
        default=None)
    #: THE DISCRIMINATOR — the same fact as `tag_set_id IS NOT NULL`, as a
    #: value a mapper can be keyed on and an index can seek. Set by the CLASS
    #: (`Tag` or `TagSetEntry`), never by hand.
    #: NOT INDEXED, on its own or in front of anything: it is one of three
    #: values, so an index over it is a list of a third of the table — and
    #: SQLite, with no stats, takes an equality as the most selective thing
    #: in a query and drives whole joins from it. (Measured: the implication
    #: join behind `GET /api/tags` 3 ms → 4.8 s a chunk.) The scope that IS
    #: indexed is `tag_set_id`.
    kind: Mapped[str] = mapped_column(String(8), default="lib",
                                      server_default=text("'lib'"),
                                      nullable=False)
    # WHAT IT IS, at two lengths — one line and as many as it takes.
    #
    # `comment` is the one-liner: "physicist", "basketball" against "actor",
    # the thing that tells two namesakes apart. It rides everywhere the name
    # rides — the autocomplete's secondary text, the row beside the name — so
    # it has to fit on that line, and nothing enforces that but the field
    # being called a comment.
    #
    # The DESCRIPTION is the long form, with line breaks: what the tag
    # covers, when to reach for it, what it is not.
    #
    # It was a column, then it was NOT (this table was rebuilt without it
    # before the first release, on the rule that a description lives in a TAG
    # SET and the library's own tags are described only by whatever set knows
    # the name), and it is a column again — because the LIBRARY IS A SET
    # NOW. It is the first pill in the Tags tab, its tags are filed in
    # categories of its own
    # (`category_id` below), and it EXPORTS as an ordinary format-2 tag-set
    # file. A tag set that cannot say what its own names mean exports to a
    # template with no teaching in it, which is most of what a template is
    # for.
    #
    # So a name can now be described twice — by this library and by an
    # enabled set that also knows it — and the ? popover shows both, the
    # LIBRARY FIRST (`SetSays`; the set order follows it). It still appears
    # NOWHERE by itself: a paragraph in a list is a paragraph nobody reads.
    comment: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="",
                                             server_default=text("''"),
                                             nullable=False)
    #: WHERE THE LIBRARY FILES THIS TAG — a category of the library's own set
    #: (`ops.tagsets.library_set`), the same `TagSetCategory` rows an imported
    #: set uses, so one tree implementation serves both and a category can be
    #: nested, given an icon, hidden and reordered without a second model.
    #:
    #: NULL is "uncategorized", which is where every tag starts: filing is
    #: authored (drag a row onto a category), never derived. The DERIVED
    #: grouping is the NAMESPACE — the text before the first colon, no row,
    #: no column, read on demand (`tagname.py`) — and the two are deliberately
    #: separate axes: `artist:kantoku` is under the `artist:` namespace
    #: whatever category somebody files it in, and `red_skirt` can be filed
    #: under Clothing though it has no namespace at all.
    #:
    #: SET NULL rather than CASCADE: deleting a category must not delete the
    #: tags in it.
    category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("tag_set_categories.id", ondelete="SET NULL"),
        nullable=True, default=None, index=True,
    )
    # NOTE: there USED to be a `count_offset` column here — pictures the tag
    # has somewhere this library is not, one number per tag. It became a
    # count PER META-TAG ASSIGNMENT (`TagMetaTag.count`): one figure could
    # not say "50 on tumblr and 100 on twitter", which is what the number
    # actually is once a library is fed from several crawls. Rung v9 rebuilds
    # this table without the column; the per-site counts are the replacement,
    # not a conversion — an old offset named no site, so there was nothing to
    # convert it INTO, and the rung's summary says the number is dropped.
    # When set, this tag is an *alias* for another tag: it is never assigned to
    # items directly — assigning it redirects to the linked (target) tag. Aliases
    # can't be chained (a target must not itself be an alias).
    # Indexed for the CASCADE's sake: deleting a tag makes SQLite look for
    # its aliases, and without this that lookup is a scan of the whole tags
    # table PER DELETED ROW — measured as most of a 32k-tag bulk delete.
    #: KEPT OUT OF THE AUTOCOMPLETE. The tag is an ordinary member of the
    #: catalog — it assigns, it searches, it counts, the Tags tab lists it —
    #: and it simply stops being SUGGESTED. A booru dump puts a hundred
    #: thousand names in front of every field somebody types in, and most of
    #: a library's own work happens in a few hundred of them; this is how the
    #: rest get out of the way without being deleted.
    hidden: Mapped[bool] = mapped_column(Boolean, default=False,
                                         server_default=text("0"),
                                         nullable=False, index=True)
    alias_of_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), nullable=True, default=None,
        index=True,
    )
    # NOTE: pre-implication libraries also have a `parent_id` column here. It
    # is deliberately not mapped any more — see :class:`TagImplication`, which
    # replaced it — and `Database.__init__` converts any parent links it finds
    # into implications once, so an existing hierarchy is not silently lost.

    # ---- what only a SET's row carries ------------------------------------
    #
    # These sat on `tag_set_entries` until the two tables became one. They
    # are NULL/empty on the library's own rows, and the library's own
    # equivalents are rows of their own: a `Subject`, a `Location`, an
    # `Occasion` pointing back at the tag. A SET cannot have those (its names
    # are advice, and a record is a thing the library HAS), which is why a
    # set says what it knows in columns and the door
    # (`tagcatalog.apply_set_records`) turns them into the real thing.
    #: The set's POPULARITY figure (a booru's post count). Nullable, because
    #: a set need not carry one; it orders the autocomplete's set-only rows
    #: and rides the capsule, and is never added to a library count.
    count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    #: The file's own order.
    position: Mapped[int] = mapped_column(Integer, default=0,
                                          server_default=text("0"))
    #: WHETHER this name is a subject / place / event at all. A flag rather
    #: than "any of its fields is filled in": a person with nothing recorded
    #: but their name is still a person, and a section somebody opened and
    #: left empty must not read as never opened.
    is_subject: Mapped[bool] = mapped_column(Boolean, default=False,
                                             server_default=text("0"))
    #: The display name; "" means the tag's own. Partial dates are the
    #: library's own YYYYMMDD-with-zeros (`partialdate.py`).
    subject_name: Mapped[str] = mapped_column(String, default="",
                                              server_default=text("''"))
    subject_since: Mapped[Optional[int]] = mapped_column(Integer,
                                                         nullable=True)
    is_place: Mapped[bool] = mapped_column(Boolean, default=False,
                                           server_default=text("0"))
    #: THE PLACE'S NAME — the one line it says, `Location.name`.
    place_name: Mapped[str] = mapped_column(Text, default="",
                                            server_default=text("''"))
    place_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    place_lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    #: The place this one is IN, by TAG NAME — like every other reference a
    #: set makes.
    place_parent: Mapped[str] = mapped_column(String, default="",
                                              server_default=text("''"))
    is_event: Mapped[bool] = mapped_column(Boolean, default=False,
                                           server_default=text("0"))
    event_name: Mapped[str] = mapped_column(String, default="",
                                            server_default=text("''"))
    event_start: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    event_end: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    event_parent: Mapped[str] = mapped_column(String, default="",
                                              server_default=text("''"))

    __mapper_args__ = {"polymorphic_on": kind}


class Tag(TagRow):
    """A name the LIBRARY has: the thing that goes on a picture.

    Every `select(Tag)` in the app means exactly this — SQLAlchemy adds the
    discriminator itself (see :class:`TagRow`), so a set's seventeen thousand
    entries are invisible to the catalog, to search, to the counts and to the
    autocomplete's library half without any of them saying so.
    """

    __mapper_args__ = {"polymorphic_identity": "lib"}


class TagSetEntry(TagRow):
    """A name an imported SET knows, with what it says about it.

    The same row as a library tag, with `tag_set_id` filled in — and an ALIAS
    is a row of this kind pointing at another through `alias_of_id`, exactly
    as the library's aliases always were. It was a table of its own
    (`tag_set_aliases`) until the two tag sets became one shape.
    """

    __mapper_args__ = {"polymorphic_identity": "set"}


class MetaTag(TagRow):
    """A META TAG: a name that labels a LINK, a CAPTION, a TAG GROUP or
    another TAG, and never a picture.

    Its own namespace — `red` the tag and `red` the meta tag are two
    different names — which is why it is a KIND of row rather than a flag on
    one. It was a table of its own (`link_tags`, whose name this class kept
    for a while as an alias) holding a name, a comment and a description;
    those are three of this table's columns, the four use-tables refer to a
    meta tag BY NAME as they always did, and folding it in is what lets a
    TAG SET carry the meta tags it wants its entries labelled with.

    `tag_set_id` says whose it is, the way it does for a tag; unlike `Tag`
    and `TagSetEntry` this class does NOT scope itself to one tag set, so
    a read that means the library's own meta tags says so.
    """

    __mapper_args__ = {"polymorphic_identity": "meta"}


#: The name this class had while it was a table of its own. Kept because a
#: dozen modules say `LinkTag`, and renaming them all says nothing new.
LinkTag = MetaTag

#: THE LIBRARY'S OWN META TAGS, and every read that means them says so.
#:
#: `select(Tag)` and `select(TagSetEntry)` scope themselves to one tag set
#: because their discriminator IS the tag set; a meta tag's is not — a set
#: carries the meta tags it wants its entries labelled with, and those are
#: `kind = 'meta'` rows with a `tag_set_id`. So the four carriers of the meta
#: namespace (a link, a caption, a tag group, a TAG) and everything that
#: mints or renames a name in it add this clause, exactly as they would have
#: had to when `link_tags` held only the library's.
#: `tests/core/test_meta_tags.py` holds every `select(LinkTag)` to it.
LIB_META = MetaTag.tag_set_id.is_(None)


class TagImplication(Base):
    """Assigning ``tag`` also entails ``implies`` — "poodle" implies "dog".

    Replaces the old single ``Tag.parent_id``: a tag implies ANY NUMBER of
    others, which is what tagging actually needs ("poodle" implies "dog" and
    "pet", neither of which is the other's parent). Implication is transitive
    and cycle-safe (``resolve.tag_implications``), so a chain still works the
    way a hierarchy did.

    An alias never implies anything — assigning it redirects to its target,
    so the target's implications are the ones that apply.
    """

    __tablename__ = "tag_implications"
    __table_args__ = (
        UniqueConstraint("tag_id", "implies_id"),
        Index("ix_tag_implications_tag", "tag_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), index=True
    )
    implies_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), index=True
    )


class TagMetaTag(Base):
    """A meta tag on a library TAG — the FOURTH carrier of the one meta-tag
    namespace, after :class:`RelationshipTag`, :class:`CaptionTag` and
    :class:`ItemTagGroupTag`.

    It says something ABOUT the tag rather than about a picture: "noflip"
    (mirroring this would be wrong), "character", "from a booru". That is why
    it is not itself a tag — it never reaches an item, so search, counts and
    training see nothing new — while everything that reads the tag set can
    ask for it: `TAG:noflip` finds the pictures carrying such a tag, and a
    training run can refuse to mirror them.

    A catalog row, not an item's: it rides on `tags.json` and marks the
    CATALOG dirty (`_CATALOG_ROWS`), never an item's sidecar. An item.json
    embeds a tag's definition to say what the tag IS on that picture, and how
    the library annotates its own tag set is not that.
    """

    __tablename__ = "tag_meta_tags"
    __table_args__ = (
        UniqueConstraint("tag_id", "name"),
        Index("ix_tag_meta_tags_name", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    # HOW MANY PICTURES the tag has WHERE THE META TAG SAYS — a count per
    # (tag, meta) assignment, so "abc" can carry tumblr 50 AND twitter 100
    # at once. It replaced the tag-level `count_offset`, which was one number
    # that could not say where it came from. Like the offset it is NEVER
    # added to a count the app displays: it orders ties (the autocomplete's
    # equal-count rows sort by the highest of these), and the capsules in
    # the tags list show it beside the meta tag's name. Training's
    # `freq_base` read it for a while under the name the tag-level offset
    # left behind; that value is gone and nothing else adds it to anything. `text("0")`, not `"0"`: the string form
    # is quoted into the DDL as `'0'` and the migration's ALTER writes a
    # bare 0, a shape difference `test_migrations` compares.
    count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0"))


class TagSet(Base):
    """An imported TAG LIST — names with usage descriptions, optional
    popularity counts, aliases, implied names and nestable categories — kept
    APART from the library's own `tags` table.

    That separation is the whole design: a 10,000-entry booru dump adds
    nothing to the tags list, its entries are keyed by NAME (never a tag id),
    and the overlap with the library is a join on the two lowercase indexes.
    A tag set is read-only ADVICE; the library is written only by an
    ASSIGNMENT — assigning one of its names creates the tag row exactly as a
    typed name does (plus its implied names), and nothing else is copied.

    No row is special any more. The shipped Booru list is a TEMPLATE a set
    is made from (`ops/tagsets.templates`), after which it is an ordinary
    set of the library's; and the library's OWN set — where a description
    typed into the tag editor landed — went before the first release, since
    the only way to describe a tag is a set somebody made or imported.
    `builtin` survives as a column an older build's installed copy carries
    until `unlock_builtin_sets` clears it on open.

    `enabled` is library-GLOBAL (which sets feed the autocomplete is a fact
    about the shared library); which set's description somebody PREFERS to
    read is per user, in the prefs (`prefs.TAG_SET_ORDER`).
    """

    __tablename__ = "tag_sets"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=0,
                                         server_default=text("0"))
    builtin: Mapped[bool] = mapped_column(Boolean, default=False,
                                          server_default=text("0"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True,
                                          server_default=text("1"))
    #: WHETHER THE SET'S ADVICE IS TAKEN, one answer per kind. With
    #: `aliases_enabled` off its alias spellings are not offered and do not
    #: redirect; with `implications_enabled` off, assigning one of its names
    #: mints nothing. Both are the ROOT of the three-state walk
    #: `TagSetCategory.aliases` / `.implications` do per branch. Rung v21
    #: (additive; `server_default=text("1")` so `create_all` and the ALTER
    #: agree). Unlike `enabled` these travel in the FILE: whether a
    #: tag set's alias spellings and entailments are worth taking is a
    #: fact about the tag set.
    aliases_enabled: Mapped[bool] = mapped_column(Boolean, default=True,
                                                  server_default=text("1"))
    implications_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("1"))
    position: Mapped[int] = mapped_column(Integer, default=0,
                                          server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class TagSetCategory(Base):
    """A category of a tag set — a browsing aid and NOTHING MORE. Nestable
    (single parent, cycles refused in the ops), ordered by `position`.
    (An `exclusive` "one of these per picture" hint lived here until rung
    v19 dropped it — owner decision, 2026-09: it was enforced nowhere and
    only seeded the tag batch chooser's checkbox.) Sibling-name uniqueness
    lives in the ops (a NULL parent defeats a UNIQUE constraint)."""

    __tablename__ = "tag_set_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    tag_set_id: Mapped[int] = mapped_column(
        ForeignKey("tag_sets.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("tag_set_categories.id", ondelete="SET NULL"), index=True)
    name: Mapped[str] = mapped_column(String)
    #: A Material Symbols name the tree draws instead of the folder; "" is
    #: the folder. Rung v18 (additive; `server_default=text("''")` so
    #: `create_all` and the ALTER agree on `DEFAULT ''`). Travels in the file
    #: as an optional `icon` key, so an export of a set with none is
    #: byte-identical to what it always was.
    icon: Mapped[str] = mapped_column(String, default="",
                                      server_default=text("''"))
    #: HIDDEN FROM THE AUTOCOMPLETE — the category, everything under it and
    #: every name in that subtree are left out of the tag fields' browse tree
    #: and out of the set-only names offered beside the library's own. A name
    #: the LIBRARY already has is unaffected: those rows come from `tags` and
    #: a set has never had a say in them. The Sets tab still shows and edits
    #: the category; hiding is about what is OFFERED, never what exists.
    #: Rung v20 (additive; `server_default=text("0")` so `create_all` and the
    #: ALTER agree). Travels in the file as an optional `hidden` key.
    hidden: Mapped[bool] = mapped_column(Boolean, default=False,
                                         server_default=text("0"))
    #: THREE-STATE, and NULL is the whole point: this branch's alias
    #: spellings / entailments are offered, are not, or are whatever the
    #: parent says — with the SET's own flag at the root of the walk
    #: (`ops/tagsets.alias_scopes_off`). Nullable, so there is no
    #: `server_default` and nothing to keep in step with `create_all`; rung
    #: v21. Travels in the file on the category's settings row, written only
    #: where it is not None.
    aliases: Mapped[Optional[bool]] = mapped_column(Boolean)
    implications: Mapped[Optional[bool]] = mapped_column(Boolean)
    position: Mapped[int] = mapped_column(Integer, default=0,
                                          server_default=text("0"))


class TagSetImplication(Base):
    """An entry entails another NAME — minted and linked as an ordinary
    `TagImplication` the first time the entry's name is assigned
    (`tagcatalog.get_or_create`, the one door a set writes through).

    By NAME, like everything else a set holds: the tag it names need not
    exist in the library, and a set that is never assigned from never puts a
    row in `tag_implications` at all. (The table lay DORMANT for a round —
    owner decision 2026-09, reversed the same month — which is why nothing
    about its shape moved.)"""

    __tablename__ = "tag_set_implications"
    __table_args__ = (
        UniqueConstraint("entry_id", "implies_lname",
                         name="uq_tag_set_implications_entry_lname"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), index=True)
    implies_name: Mapped[str] = mapped_column(String)
    #: INDEXED, because the table is read BACKWARDS too (`implied_by_for`:
    #: "which entries entail this name"). The unique constraint above leads
    #: with `entry_id`, so it cannot seek on this column, and the read that
    #: needs it was answered by walking the tag set — 1.36 s a detail band
    #: on a 132,255-entry set. `Database._ensure_indexes` builds it for a
    #: library that already exists, so this needs no version bump.
    implies_lname: Mapped[str] = mapped_column(String, index=True)


class ItemTag(Base):
    __tablename__ = "item_tags"
    __table_args__ = (
        UniqueConstraint("item_id", "tag_id"),
        Index("ix_item_tags_item", "item_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE")
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), index=True
    )
    negative: Mapped[bool] = mapped_column(Boolean, default=False)
    # True for a machine-generated tag awaiting the user's approval. Pending
    # tags behave like normal tags (search/facets/inheritance) but are shown
    # distinctly and can be approved/edited/deleted (see the ML jobs feature).
    pending: Mapped[bool] = mapped_column(Boolean, default=False)
    item: Mapped["Item"] = relationship(back_populates="tags")
    tag: Mapped["Tag"] = relationship()
    # Placements of this tag into the item's tag groups. The same tag may be
    # placed in several groups (distinct instances), each with its own boxes.
    placements: Mapped[list["ItemTagPlacement"]] = relationship(
        back_populates="item_tag", cascade="all, delete-orphan"
    )


class TagRepresentative(Base):
    """One item standing for a tag in the Tags tab's strips — or, REFUSED,
    one that must not: `representatives.py` is the whole rule. Hangs off
    the ASSIGNMENT (``item_tag_id``, CASCADE), so the row goes the moment
    the tag leaves the item whatever deleted it; ``tag_id``/``item_id`` are
    that row's own, repeated here for the two reads (a tag's strip, an
    item's rows). An additive table — `create_all` adds it on open."""
    __tablename__ = "tag_representatives"
    __table_args__ = (
        Index("ix_tag_representatives_tag", "tag_id", "refused"),
        Index("ix_tag_representatives_item", "item_id"),
    )

    item_tag_id: Mapped[int] = mapped_column(
        ForeignKey("item_tags.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column()
    item_id: Mapped[int] = mapped_column()
    refused: Mapped[bool] = mapped_column(Boolean, default=False,
                                          server_default=text("0"))


class ItemTagGroup(Base):
    """A per-item, named grouping of tag instances (e.g. "Person A").

    Purely organizational: a tag placed in a group still counts as the item
    having that tag (search/facets/inheritance dedup by name via ``ItemTag``).
    The implicit "Ungrouped" group is represented by ``group_id = NULL`` on a
    placement and has no row here.
    """

    __tablename__ = "item_tag_groups"
    __table_args__ = (Index("ix_item_tag_groups_item", "item_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String, default="New group")
    position: Mapped[int] = mapped_column(Integer, default=0)
    # True for the auto-managed "Pending" group that holds machine-generated
    # tags awaiting approval. The UI shows no adder for it and it is deleted
    # automatically once empty (tags are moved out on approval).
    system: Mapped[bool] = mapped_column(Boolean, default=False)


class ItemTagGroupTag(Base):
    """A meta tag on a per-item tag group — the SAME namespace as
    :class:`RelationshipTag` and :class:`CaptionTag`. A tag group says which
    tags belong together ("Person A"); its meta tags say something about that
    grouping itself ("main character", "background") without polluting the
    item's own tags, which are what search and training see.
    """

    __tablename__ = "item_tag_group_tags"
    __table_args__ = (
        UniqueConstraint("group_id", "name"),
        Index("ix_item_tag_group_tags_name", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("item_tag_groups.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))


class ItemTagGroupSubject(Base):
    """A per-item tag group is ABOUT one or more subjects.

    A picture with two people wants two groups of tags — hers and his — and
    naming the groups by hand leaves the connection in a string. This binds the
    grouping to the identity instead, so the group titles itself with the
    subject's name and survives a rename.

    Purely organizational, exactly like :class:`ItemTagGroupTag`: the grouped
    tags stay the ITEM's tags. Binding a group to a subject does NOT make its
    tags attributes of that subject (search never learns "her hair is blonde").
    """

    __tablename__ = "item_tag_group_subjects"
    __table_args__ = (
        UniqueConstraint("group_id", "subject_id"),
        Index("ix_item_tag_group_subjects_subject", "subject_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("item_tag_groups.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )


class ItemTagPlacement(Base):
    """One instance of a tag inside a tag group (or the ungrouped default).

    ``group_id = NULL`` means the item's implicit "Ungrouped" group. At most one
    placement exists per (tag, group); its ``boxes`` are that instance's own
    bounding boxes / time ranges.
    """

    __tablename__ = "item_tag_placements"
    __table_args__ = (
        UniqueConstraint("item_tag_id", "group_id"),
        Index("ix_item_tag_placements_item_tag", "item_tag_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    item_tag_id: Mapped[int] = mapped_column(
        ForeignKey("item_tags.id", ondelete="CASCADE"), index=True
    )
    group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("item_tag_groups.id", ondelete="CASCADE"), nullable=True,
        index=True,
    )
    #: THE INSTANCE'S OWN SIGN: the same tag may be positive in one group and
    #: negative in another on one item. `ItemTag.negative` stays what search,
    #: facets, counts and training read, DERIVED by `tagassign.
    #: sync_placement_sign` — negative only when EVERY placement is (any
    #: positive placement wins), the timed-range rule one level up.
    #: `server_default=text("0")` and not `"0"` — the `count_offset` quotes
    #: lesson, or the migration census fails on `DEFAULT '0'` vs `DEFAULT 0`.
    negative: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("0"))

    item_tag: Mapped["ItemTag"] = relationship(back_populates="placements")
    boxes: Mapped[list["ItemTagBox"]] = relationship(
        back_populates="placement", cascade="all, delete-orphan"
    )


class ItemTagBox(Base):
    """A bounding box and/or time range annotating one tag *instance*.

    ``x/y/w/h`` are fractions of the image's reference frame (0..1); all null for
    a pure time-range annotation. ``time_start/time_end`` (seconds) apply to
    video items / frame ranges. A placement may have several boxes (e.g. the same
    tag at different times in a video).

    ``track_id`` groups the boxes of ONE moving subject across a video into a
    single logical track (several timed placements of the same tag as the subject
    moves). It is null for a standalone box. Two subjects sharing a tag (both
    ``person``) get different ``track_id``s so they stay distinct tracks — which
    inferring a track from the tag name alone could not express. The id is client
    -assigned and only unique within an item; it is not a foreign key.

    ``negative`` is the sign of a TIMED box: over a film's length a tag is
    present in some stretches and pointedly absent in others, which one flag on
    the (item, tag) pair cannot say. ``ItemTag.negative`` stays the item-level
    answer and is kept in step — a tag is negative for the item only when every
    one of its timed ranges is (see ``tags._sync_timed_sign``) — so search,
    facets and counts go on reading one field. Ranges of the same tag may not
    overlap, whatever their signs.
    """

    __tablename__ = "item_tag_boxes"

    id: Mapped[int] = mapped_column(primary_key=True)
    placement_id: Mapped[int] = mapped_column(
        ForeignKey("item_tag_placements.id", ondelete="CASCADE"), index=True
    )
    x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    w: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    time_start: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    time_end: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    track_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    negative: Mapped[bool] = mapped_column(Boolean, default=False)
    #: An optional POLYGON refining the rectangle — JSON [[x,y], ...] in the
    #: same reference-frame fractions. When set, x/y/w/h HOLD ITS BOUNDING
    #: BOX (the writers keep them in step), so every rectangle reader —
    #: training crops, the grid's indicators, QuickLook — keeps working
    #: unchanged; the polygon is the finer drawing on top. NULL = a plain
    #: rectangle, which every box before the column was.
    points: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    placement: Mapped["ItemTagPlacement"] = relationship(back_populates="boxes")


class Subject(Base):
    """Who or what a picture is OF — a person, an animal, a building.

    A subject is **extra data on a tag**, not a catalog beside it: `tag_id` is
    the tag the subject IS, so assigning a subject to an item is assigning that
    tag, and search, counts, facets, aliases, implications, training prompts,
    sidecars and revert keep working with no new machinery.

    What tags cannot do, and this table adds:

    * **An identity with no name.** `tag_id` is NULL for a face cluster nobody
      has named yet. Naming it mints the tag and back-fills it onto every item
      one of its faces sits on. A tag cannot be nameless, and inventing
      `unknown_person_3` tags would leak that junk into prompts and exports.
    * **Two identities with one name.** Tag names are unique; two people called
      Michael Jordan are two subjects with one display name, told apart by
      `comment` ("basketball" / "actor"). Their slugs differ quietly.
    * **A display name** with spaces and capitals, which tag names normalize
      away.
    """

    __tablename__ = "subjects"
    __table_args__ = (
        UniqueConstraint("tag_id"),
        Index("ix_subjects_name", "display_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # The tag this subject is. NULL = unnamed (a face cluster).
    #
    # SET NULL rather than CASCADE: deleting the tag takes the subject's NAME
    # away, not its identity. It becomes an unnamed subject — which is what an
    # identity that lost its name is — and keeps its faces, instead of silently
    # taking them down with it.
    tag_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("tags.id", ondelete="SET NULL"), nullable=True, default=None
    )
    display_name: Mapped[str] = mapped_column(String, default="")
    # NO `comment`/`description` HERE — they are the TAG's (see `Tag.comment`).
    # A subject is extra data on a tag, so "what is this, in a line" has one
    # answer and one place to edit it; two columns meant the Subjects list and
    # the Items list could disagree about the same thing. A subject with no tag
    # (a face cluster nobody has named) therefore has nowhere to put one, which
    # is honest: it is not a named thing yet.
    # When the subject came to be — born, built, founded, opened, released. One
    # neutral field rather than a word to choose.
    #
    # A PARTIAL date, encoded as the sortable number YYYYMMDD with ZEROS for the
    # parts that are not known: 19750000 is "1975", 19990700 is "July 1999",
    # 18790314 is "14 March 1879". The zeros ARE the precision, so there is no
    # second column to keep in step, and a range query is a plain integer
    # comparison (see `partialdate.bounds`).
    since_date: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    #: SOMEBODY DECIDED THIS IDENTITY HAS NO NAME — a background character, an
    #: extra, the third person at the table. It is an ANSWER, not a state of
    #: not having looked yet, and the difference is the whole point: a subject
    #: with no tag and no display name is a face cluster the Faces tab is
    #: still ASKING about (it calls those UNKNOWN), and this is how one leaves
    #: that queue without a name being invented for it.
    #:
    #: A FLAG PER SUBJECT, never one shared "Unnamed" identity: two background
    #: characters are two people, and putting them on one subject would fold
    #: their faces together and put the tag — if one were ever minted — on
    #: both. So marking a cluster unnamed gives it a nameless subject of its
    #: OWN, which is exactly what a hand-merged cluster already is.
    unnamed: Mapped[bool] = mapped_column(Boolean, default=False,
                                          server_default=text("0"),
                                          nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ItemFaceRun(Base):
    """That a face DETECTOR has been run over an item — whatever it found.

    ``Face.model`` says which detectors found a given face, which answers a
    different question: an item a model looked at and found nothing in has no
    face to record it on, and is exactly the item a "skip what is already done"
    sweep must not run again. So the run itself is recorded, once per
    (item, model).

    Written by ``jobs._apply_faces`` after a run finishes for an item, so a
    cancelled or failed job leaves no claim behind.
    """

    __tablename__ = "item_face_runs"
    __table_args__ = (UniqueConstraint("item_id", "model"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True)
    #: A detector's plugin key, e.g. ``anime_face_magi``.
    model: Mapped[str] = mapped_column(String, index=True)


class Face(Base):
    """A face found in a picture, and who it belongs to.

    Detection data is **kept forever**, assigned or not. A face nobody has named
    is still the evidence that someone is there, it is what the unnamed-faces
    view clusters, and re-running a detector must never be able to lose work
    done by hand.

    The box is in the item's REFERENCE FRAME (fractions 0..1), the same frame
    ``ItemTagBox`` uses, so a later crop or rotation of the file does not strand
    it. ``file_id`` records which file it was actually found in.

    Who a face IS lives in ``ItemSubject``: zero, one or several appearances
    may point at the same rectangle, which is what lets one drawn head be both
    Peter Parker and Andrew Garfield with an age of its own for each. A face
    with no appearance at all is what the unnamed view clusters.

    ``dismissed`` means "not a face" — a false positive that stays on record so
    the same detector's next run does not offer it again.
    """

    __tablename__ = "faces"
    __table_args__ = (
        Index("ix_faces_item", "item_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("files.id", ondelete="SET NULL"), nullable=True,
        default=None, index=True,
    )
    # The box, in the item's reference frame (0..1).
    x: Mapped[float] = mapped_column(Float, default=0.0)
    y: Mapped[float] = mapped_column(Float, default=0.0)
    w: Mapped[float] = mapped_column(Float, default=0.0)
    h: Mapped[float] = mapped_column(Float, default=0.0)
    # The detector's confidence, kept and shown. NULL for a hand-drawn face.
    det_score: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, default=None
    )
    # Every model that has found this face, comma-separated in the order they
    # first did — "" when a person drew it. A plural, because two detectors
    # covering different material (anime and photographic) legitimately find
    # the same head, and reconciliation MERGES them: recording only the latest
    # would erase the fact that the other one agreed.
    model: Mapped[str] = mapped_column(String, default="")
    # Descriptors live in `face_embeddings`, one row per (face, embedder) —
    # see that table for why they cannot be one column here.
    # "Not a face" — kept rather than deleted so the next run doesn't re-offer it.
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class FaceEmbedding(Base):
    """One face's descriptor, in ONE model's space.

    A row per (face, embedder) rather than a column on the face, because the
    two are not interchangeable: a cosine between an ArcFace vector and a manga
    embedder's vector is not a number about people at all. The old single
    column made that mistake silently — every run overwrote it with whichever
    model had just finished, while `Face.model` accumulated both names, so a
    descriptor's space was unknowable from the row that held it.

    It survived only by arithmetic accident (`faces.similarity` returns 0 when
    the lengths differ, and buffalo_l is 512-d against Magi's 768-d). Two
    models sharing 512 dimensions — the common width in this field — would
    have scored garbage against the threshold.

    `model` is the EMBEDDER, which is not always the detector: `anime_face`
    finds boxes and describes nothing, and an embedder that runs over another
    detector's boxes is the obvious next plugin.

    Regenerable from the picture, so it is never written to a sidecar.
    """

    __tablename__ = "face_embeddings"
    __table_args__ = (
        UniqueConstraint("face_id", "model"),
        Index("ix_face_embeddings_model", "model"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    face_id: Mapped[int] = mapped_column(
        ForeignKey("faces.id", ondelete="CASCADE"), index=True
    )
    model: Mapped[str] = mapped_column(String, default="")
    # A raw float32 array as bytes: opaque to SQL, only ever compared whole.
    vector: Mapped[bytes] = mapped_column(LargeBinary)


class ItemEmbedding(Base):
    """One ITEM's feature vector, in ONE embedder's space — the whole-picture
    sibling of `FaceEmbedding`, and the tag-batch overlay's queue ordering is
    its only reader.

    A row per (item, space): `model` is the SPACE STRING (e.g. "dinov2s-v1"),
    which carries every constant — embedder, dim, dtype, preprocessing — so
    vectors are only ever compared within one space and any change of recipe
    is a NEW string and a re-index, never a silent mix (FaceEmbedding's
    lesson, learned the hard way there).

    `file_id` records which file the vector was computed from: the vector
    describes pixels, so "indexed" means the row exists AND `file_id ==
    item.active_file_id` — the OCR per-active-file rule, which is what makes
    an edited picture re-index instead of answering for pixels it no longer
    shows.

    The bytes are a raw float16 array, opaque to SQL, only ever read whole.
    Regenerable from the picture, so it is never written to a sidecar, and
    writing one logs no history event (derived data, like a face descriptor).
    """

    __tablename__ = "item_embeddings"
    __table_args__ = (
        UniqueConstraint("item_id", "model"),
        Index("ix_item_embeddings_model", "model"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    model: Mapped[str] = mapped_column(String, default="")
    file_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("files.id", ondelete="SET NULL"), nullable=True,
        index=True,
    )
    dim: Mapped[int] = mapped_column(Integer, default=0)
    vector: Mapped[bytes] = mapped_column(LargeBinary)


class FaceRejection(Base):
    """"This face is not that person" — a refusal, kept.

    The negative half of the loop, and the half every photo manager that works
    turns out to have: digiKam passes a per-region rejected list to its
    classifier as an exclusion, Ente feeds one into its clusterer as a
    cannot-link, and Apple's patent claim is literally storing that a face does
    not belong to a candidate "and not identifying another person". Without it
    a re-run offers the same wrong name again, which is the complaint
    Lightroom users have had for years.

    A rejection is recorded ONLY for a machine's guess. Taking a name somebody
    gave by hand back off is a different statement — they changed their mind,
    not "the model was wrong about this pair".

    `subject_id` is the person refused. A refusal is written only when a GUESS
    is taken back, so it says "the model was wrong about this pair" — which
    stays true whatever else the face turns out to be.

    `model`, `item_uid` and `box` are the rowid-reuse guard. SQLite hands a
    deleted face's id to the next one (this codebase already met that when a
    cached crop URL keyed on an id served the wrong picture), and a rejection
    is meant to be permanent — so it records enough to tell whether the face it
    names is still the face it meant. The space matters too: re-embed the crop
    with a different model and the geometric fact no longer holds.
    """

    __tablename__ = "face_rejections"
    __table_args__ = (
        UniqueConstraint("face_id", "subject_id"),
        Index("ix_face_rejections_subject", "subject_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    face_id: Mapped[int] = mapped_column(
        ForeignKey("faces.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE")
    )
    # Which of that person's faces actually won, so a hub exemplar — one close
    # to everything — can be told from a person who is simply hard to match.
    exemplar_face_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("faces.id", ondelete="SET NULL"), nullable=True,
        default=None, index=True,
    )
    model: Mapped[str] = mapped_column(String, default="")
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True,
                                                   default=None)
    item_uid: Mapped[str] = mapped_column(String, default="")
    box: Mapped[str] = mapped_column(String, default="")
    username: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class SubjectCannotLink(Base):
    """"These two are not the same person" — from splitting a cluster.

    Stored unordered (the smaller id first) because the statement is
    symmetric, and **cleared by a later merge**: the user is allowed to change
    their mind, and the merge is the newer statement.
    """

    __tablename__ = "subject_cannot_link"
    __table_args__ = (UniqueConstraint("a_subject_id", "b_subject_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    a_subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    b_subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ItemSubject(Base):
    """One APPEARANCE of a subject in an item — who is in the picture, and how.

    A row per appearance rather than a fact about (item, subject), because a
    manga page can hold the same character twice at two ages and a photograph
    can hold three actors playing one part. The old `ItemTagWhen` was keyed on
    the assignment, which could say neither.

    ``face_id`` attaches the appearance to a detected face: **at most one face
    per appearance, and any number of appearances per face.** That asymmetry is
    the whole model — one rectangle is both Peter Parker and Andrew Garfield,
    each with its own age — and it is why this is a table rather than a column
    on either side. An appearance with no face is somebody who is in the
    picture without a detector having found them.

    The subject's TAG is still assigned to the item, and that is what search,
    facets, counts, training and export read. This row says how many times,
    which face, and when — never anything a query has to learn about.

    ``assigned_by`` separates a person's answer from a model's guess, and
    ``match_score`` is how sure the guess was ("Alice? · 87%"). They live here
    rather than on the face because they are about the CLAIM, and one face may
    carry a guess and an answer at once.
    """

    __tablename__ = "item_subjects"
    __table_args__ = (
        Index("ix_item_subjects_item", "item_id"),
        Index("ix_item_subjects_subject", "subject_id"),
        Index("ix_item_subjects_face", "face_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id", ondelete="CASCADE"), index=True
    )
    # SET NULL, not CASCADE: deleting a detection does not delete the statement
    # that the person is in the picture. It only stops pointing at a rectangle.
    face_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("faces.id", ondelete="SET NULL"), nullable=True, default=None
    )
    # WHEN this appearance is, in the same partial-date encoding as
    # `Subject.since_date` (YYYYMMDD, zeros for what is unknown); either value
    # derives the other given that since-date.
    when_date: Mapped[Optional[int]] = mapped_column(Integer, nullable=True,
                                                     default=None)
    when_age: Mapped[Optional[int]] = mapped_column(Integer, nullable=True,
                                                    default=None)
    # "user" | "suggested". A person's answer is never overwritten by a model.
    assigned_by: Mapped[str] = mapped_column(String, default="user")
    match_score: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True, default=None
    )
    # Where this appearance sits in the sidebar's list — the drag-reorder's
    # answer. 0 for everything until somebody reorders; ties break by id
    # (creation order), so an untouched library keeps the order it had.
    # `text("0")` and not "0" — the count_offset quotes lesson: the rung's
    # ALTER writes DEFAULT 0, and the shape comparison fails on the quotes.
    position: Mapped[int] = mapped_column(Integer, default=0,
                                          server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ItemSubjectBox(Base):
    """The optional SUBJECT BOX of one appearance — where in the picture the
    subject is, as a rectangle.

    The face is only the FALLBACK for that question: a figure facing away, a
    building, a vehicle — anything whose face is absent or beside the point —
    is the case this exists for. At most one box per appearance (drawing
    again replaces it), fractions of the item's reference frame like
    ``ItemTagBox``, and its OWN TABLE rather than columns on `item_subjects`:
    an additive table is what `create_all` gives an existing library on open,
    where an ALTER would need the migration ladder for a format that has not
    otherwise moved.

    Readers, in fallback order: the annotator's Subjects layer draws it, an
    appearance-targeted ranking's cards outline it, and crop-aware training
    prefers it over the appearance's face (a hand-drawn box says the whole
    person where a face box says the head).
    """

    __tablename__ = "item_subject_boxes"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_subject_id: Mapped[int] = mapped_column(
        ForeignKey("item_subjects.id", ondelete="CASCADE"),
        unique=True, index=True,
    )
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    w: Mapped[float] = mapped_column(Float)
    h: Mapped[float] = mapped_column(Float)
    #: `ItemTagBox.points`' rule: an optional polygon whose bounding box the
    #: four columns hold, so every rectangle reader stays unchanged.
    points: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class FaceOutline(Base):
    """The optional OUTLINE of one face — the whole figure, drawn by hand.

    `ItemSubjectBox`'s shape one level down: at most one per FACE (drawing
    again replaces it), fractions of the item's reference frame, the four
    columns holding the polygon's bounding box while ``points`` is set
    (`ItemTagBox.points`' rule). Its own additive TABLE for the same reason
    the subject box is one — `create_all` adds it on open, and the faces
    table itself is rebuilt from the model on shape changes, which an extra
    column would trip for every existing library.

    What it is FOR: a subject attached to the face uses this outline wherever
    it has no subject box of its own — the sidebar's outline preview and
    crop-aware training's fallback chain (tag box → subject box → face
    outline → face box). CASCADE with the face; `faces.reconcile` never sees
    it, so a re-run cannot move or lose what a person drew.
    """

    __tablename__ = "face_outlines"

    id: Mapped[int] = mapped_column(primary_key=True)
    face_id: Mapped[int] = mapped_column(
        ForeignKey("faces.id", ondelete="CASCADE"), unique=True, index=True,
    )
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    w: Mapped[float] = mapped_column(Float)
    h: Mapped[float] = mapped_column(Float)
    points: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class FaceBoxEdit(Base):
    """The DETECTOR's rectangle for a face whose box somebody edited by hand.

    Present exactly while the face's geometry is a person's answer rather
    than the detector's: ``ops/faces.update_face`` writes it on the FIRST
    hand edit of a detected face (the pre-edit box), ``reset_face_box``
    restores it and takes it down, and a re-run refreshes THIS record instead
    of the face's own columns (``jobs._apply_faces``) — so the edit survives
    every run, and reset always answers with the newest detection. A face a
    person drew never gets one: there is no detector's rectangle to go back
    to. Its own additive TABLE for the reason ``FaceOutline`` is one, and
    CASCADE with the face.
    """

    __tablename__ = "face_box_edits"

    id: Mapped[int] = mapped_column(primary_key=True)
    face_id: Mapped[int] = mapped_column(
        ForeignKey("faces.id", ondelete="CASCADE"), unique=True, index=True,
    )
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    w: Mapped[float] = mapped_column(Float)
    h: Mapped[float] = mapped_column(Float)


class ItemTextRun(Base):
    """That a text ENGINE has been run over a FILE of an item — whatever it
    read.

    ``TextRegion.model`` says which engines read a given region, which answers
    a different question: an item an engine looked at and read nothing in has
    no region to record it on, and is exactly the item a "skip what is already
    done" sweep must not run again. Same shape and same reason as
    ``ItemFaceRun``; written by ``jobs._apply_ocr`` after a run finishes for an
    item, so a cancelled or failed job leaves no claim behind.

    Keyed per ``(item, file, model)``, not per item: a reading is a fact
    about PIXELS, so an edited file — a new source file made active — has no
    runs and reads as never-read, which is what makes the Detect menu's
    ticks clear and ``skip_done`` re-run it. The file FK CASCADEs for the
    same reason an artifact's does: the claim dies with the pixels it is
    about.
    """

    __tablename__ = "item_text_runs"
    __table_args__ = (UniqueConstraint("item_id", "file_id", "model"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True)
    file_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), nullable=True,
        default=None, index=True)
    #: An engine's model id, e.g. ``magiv3_ocr`` or ``rapidocr_multi``.
    model: Mapped[str] = mapped_column(String, index=True)


class TextRegion(Base):
    """A region of TEXT found in (or drawn on) a picture, and what it says.

    Modelled on ``Face`` — found by a detector, corrected by a person, and a
    re-run must never lose the correction — with two structural differences.

    **It is a TREE** (``parent_id``, self-FK CASCADE): an engine that reads a
    page as blocks holding lines holding words keeps that structure rather
    than having it flattened away, and the two shipping engines disagree
    about how deep it goes (Magi emits blocks with no children, RapidOCR
    emits lines with word children and no blocks at all), which is why the
    depth is data rather than schema. Deleting a region CASCADEs its
    children — they describe a breakdown of something that no longer exists,
    the ``FileArtifact.parent_id`` argument.

    **Its identity is a COLUMN of the same row** (``text``), where a face's
    lives in ``ItemSubject``. So the protection "a re-run refreshes geometry
    but never what a person said" has to be explicit here: ``edited`` marks a
    region whose text somebody corrected, and ``ocr.reconcile`` never
    rewrites such a region's text.

    The box is the AABB in the item's REFERENCE FRAME (fractions 0..1), the
    frame ``ItemTagBox`` and ``Face`` use. ``quad`` carries the engine's own
    four points where it read a rotated or perspective shape (eight
    comma-joined fractions, packed by ``ocr.pack_quad``); ``""`` means "the
    box IS the shape", so an upright region never has a second source of
    truth to drift from.

    ``file_id`` is WHICH PIXELS were read, and it is load-bearing: a reading
    is a fact about a file, not about the item, so every reader shows the
    ACTIVE file's regions and an edited file (a new source made active)
    starts blank until an engine reads it — the artifact rule, and the FK
    CASCADEs for the artifact's reason (a reading of pixels that no longer
    exist describes nothing). Reconciliation partitions by it too: an old
    file's reading never merges with the new file's.

    Provenance is read off ``model == ""`` (hand-drawn), NEVER off the score:
    ``score`` is NULL both for a hand-drawn region and for an engine that has
    no confidence to give (Magi is generative). ``dismissed`` means "not
    text" — kept rather than deleted so the same engine's next run does not
    offer it again (a dismissal ABSORBS its detection, ``Face``'s rule).

    ``ord`` is the reading order among SIBLINGS — the engine's own order, the
    only one anybody has — per-sibling rather than global so dismissing a
    block renumbers nothing.
    """

    __tablename__ = "text_regions"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    file_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), nullable=True,
        default=None, index=True
    )
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("text_regions.id", ondelete="CASCADE"), nullable=True,
        default=None, index=True
    )
    #: "block" | "line" | "word" | "char" — as deep as the engine actually
    #: went, never a level invented to fill the ladder.
    level: Mapped[str] = mapped_column(String(8), default="block")
    ord: Mapped[int] = mapped_column(Integer, default=0)
    # The AABB, in the item's reference frame (0..1). Always filled — it is
    # what everything generic reads (crops, IoU, counts, hit-testing).
    x: Mapped[float] = mapped_column(Float, default=0.0)
    y: Mapped[float] = mapped_column(Float, default=0.0)
    w: Mapped[float] = mapped_column(Float, default=0.0)
    h: Mapped[float] = mapped_column(Float, default=0.0)
    #: Eight comma-joined fractions (x1,y1,…,x4,y4) for a rotated shape;
    #: ``""`` when the AABB is the shape. Opaque to SQL, like
    #: ``FaceRejection.box``; pack/unpack live in ``ocr.py``.
    quad: Mapped[str] = mapped_column(String, default="")
    text: Mapped[str] = mapped_column(Text, default="")
    # The engine's confidence. NULL = "the engine does not say" (or nobody
    # ran one) — provenance is model == "", never this.
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True,
                                                   default=None)
    lang: Mapped[str] = mapped_column(String(16), default="")
    # Every model that has read this region, comma-separated in the order
    # they first did — "" when a person drew it. Face.model's rule.
    model: Mapped[str] = mapped_column(String, default="")
    # "Not text" — kept rather than deleted so the next run doesn't re-offer it.
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    # A person corrected the text; no run may rewrite it after this.
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Location(Base):
    """WHERE a picture is — attached to a TAG, like a subject and an event.

    Location data hangs off a tag exactly as subject data does, so assigning a
    location is assigning that tag and the whole search/count/facet machinery
    keeps working.

    **The name is ONE free text field, and it is the whole of what a place
    SAYS.** It was eight typed components with a per-country form deciding
    which existed, what they were called and in what order they read — a small
    address database, for a field whose only consumer is a person reading a
    line. Nobody could type "the corner of the old market" into it, every
    country needed its form written down, and the parts were searchable
    individually in a way nothing else in the app is. One field says all of
    that and refuses none of it.

    **The hierarchy is `parent_id`**, one optional parent per place: Tokyo
    Tower in Tokyo in Japan. Assigning a place implies its parents, and that
    is not a second mechanism — a place IS a tag, so `ops/places.set_parent`
    writes the ordinary `TagImplication` between the two identity tags and
    search, counts, facets, training and sidecars learn nothing new. The
    column is the TREE (single parent, no cycles, what the list draws); the
    implication is its consequence.

    `tag_id` is NULL for an UNNAMED place: a bare GPS pin an older library's
    import minted (nothing mints one now). The Places list's "Unnamed" filter
    finds them until somebody names one — the same flow as naming a face.
    """

    __tablename__ = "locations"
    __table_args__ = (UniqueConstraint("tag_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tag_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("tags.id", ondelete="SET NULL"), nullable=True, default=None
    )
    # WHAT THE PLACE IS CALLED, and it is the ONLY text one carries: one
    # line, in whatever form suits — "Invalidenstraße 43, 10115 Berlin",
    # "the corner of the old market", "Bob's house".
    #
    # There was a `name` beside an `address` and a `country` beside that;
    # three fields for one line meant three places to look and three things
    # to keep in step, and the country was the last piece of the address
    # database this replaced. The survivor was called `address` for a while
    # after — the word the widest of the three had used — and every surface
    # a person meets ended up saying "name", because an address is welcome
    # in it but "Bob's house" is as much a place and a field labelled
    # Address said otherwise. Rung v26 made the column agree.
    name: Mapped[str] = mapped_column(Text, default="")
    # The place this one is IN. SET NULL, so deleting Japan leaves Tokyo
    # standing at the top rather than taking it down.
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("locations.id", ondelete="SET NULL"), nullable=True,
        default=None, index=True
    )
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ItemLocation(Base):
    """An item is at an UNNAMED place.

    Named places are assigned by their tag, like everything else here. This
    table exists only for the tagless case — a photo's bare GPS on import —
    where there is no tag to assign yet. Naming the place mints the tag,
    back-fills it onto these items and empties this table of those rows.
    """

    __tablename__ = "item_locations"
    __table_args__ = (
        UniqueConstraint("item_id", "location_id"),
        Index("ix_item_locations_location", "location_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[int] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE")
    )


class Occasion(Base):
    """WHAT WAS HAPPENING — an event, attached to a TAG.

    **The UI calls this an Event.** `Event` is taken by the modification log
    (below), and renaming that is a sweep through the one module where a silent
    mistake costs an un-undoable action — so the stored name and the word on the
    screen diverge, exactly as `link_tags` and "meta tags" already do.

    The third of the same kind as `Subject` and `Location`: assigning an event
    is assigning its tag, so search, counts, facets, training and sidecars need
    nothing new. What the row adds is a NAME with spaces and capitals ("San
    Diego Comic-Con 2014"), a span of days, and the places it was at.

    `tag_id` is SET NULL like its siblings': deleting the tag takes the event's
    name away, not its record. Nothing mints a nameless occasion, so one is a
    repair job rather than a workflow — unlike a place, which import genuinely
    creates unnamed from a bare coordinate.

    The dates are PARTIAL (`partialdate.py`: YYYYMMDD with zeros for what is
    unknown), so "summer 1999" and "24 July 2014" are both sayable and a range
    query stays an integer comparison.
    """

    __tablename__ = "occasions"
    __table_args__ = (
        UniqueConstraint("tag_id"),
        Index("ix_occasions_name", "display_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tag_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("tags.id", ondelete="SET NULL"), nullable=True, default=None
    )
    display_name: Mapped[str] = mapped_column(String, default="")
    # The event this one is PART OF: Day 1 of NY Comic Con 2026, which is part
    # of Summer 2026. One optional parent, exactly as a place has — and the
    # same consequence: `ops/events.set_parent` writes the ordinary
    # `TagImplication` between the identity tags, so assigning the day
    # assigns the convention and the season with it.
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("occasions.id", ondelete="SET NULL"), nullable=True,
        default=None, index=True
    )
    # The pair is the TAG's — see `Subject` and `Tag.comment`.
    start_date: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    end_date: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class OccasionPlace(Base):
    """Where an event was. Several, because a convention is a hall and a hotel.

    The place must be NAMED (`Location.tag_id` is not null) and
    `ops/events.set_places` refuses one that is not. That is not a restriction so much as the thing that
    makes the sidecar possible: a sidecar refers to other objects by uid, file
    number or tag NAME and never by row id, and an unnamed place has no name to
    write down.
    """

    __tablename__ = "occasion_places"
    __table_args__ = (UniqueConstraint("occasion_id", "location_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    occasion_id: Mapped[int] = mapped_column(
        ForeignKey("occasions.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[int] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE"), index=True
    )


class ItemPlaceDismissal(Base):
    """"Not there" — a suggested place refused for this picture, for good.

    An event knows where it was, so a picture carrying its tag can be OFFERED
    the venue. It is never given it: half of a week's photographs were taken
    somewhere else. Saying no has to stick, or the same question is asked on
    every visit.

    Keyed on (item, place) and NOTHING else, and both consequences are the
    point: editing the event that offered it cannot resurrect it, and a second
    event at the same venue does not re-ask a question already answered.
    `via_occasion_id` is for the log's sentence only — it is never read by the
    suggestion rule, so it may look like dead data. It is not; it is what lets
    the History entry say which event prompted the offer.

    It is NOT a negative tag. `ItemTag.negative` says "pointedly untrue here"
    and reaches search, facets, counts and training; a dismissal reaches nothing
    but the suggestion list, and the place stays a perfectly good thing for
    somebody to assign by hand later.
    """

    __tablename__ = "item_place_dismissals"
    __table_args__ = (
        UniqueConstraint("item_id", "location_id"),
        Index("ix_item_place_dismissals_location", "location_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[int] = mapped_column(
        ForeignKey("locations.id", ondelete="CASCADE")
    )
    via_occasion_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("occasions.id", ondelete="SET NULL"), nullable=True,
        default=None, index=True,
    )
    username: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ItemFilePlaceDismissal(Base):
    """"Not that either" — the place the item's OWN FILE names, refused.

    The third dismissal, for the suggestion derived from the file's indexed
    ``location``/``gps_lat``/``gps_lon`` metadata (the importer used to CREATE
    that place outright — a crawl of random web images filled the Places list
    with strangers' coordinates, which is why creation became an offer). The
    suggestion has no place row to key on — nothing exists until it is
    accepted — so this is keyed on the ITEM alone: one file, one claim about
    where it was taken, one answer. Additive table; ``create_all`` adds it on
    an existing library.
    """

    __tablename__ = "item_file_place_dismissals"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), unique=True
    )
    username: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ItemOccasionDismissal(Base):
    """"Not from that" — an event offered by the picture's own date, refused.

    The other half of the same idea, and a separate table rather than one
    polymorphic (item, kind, target) row: a shared table could carry no real
    foreign key, so a deleted place would leave a row that silently suppresses a
    suggestion for whatever inherits its rowid — the rowid-reuse trap
    `FaceRejection` carries `item_uid` and `box` to survive. Two tables get the
    key for free.

    They also have different lifetimes. "This picture was not taken at the
    convention centre" stays true once the event is gone; "this picture is not
    from Comic-Con 2014" means nothing without it — hence CASCADE here and none
    on the place one.
    """

    __tablename__ = "item_occasion_dismissals"
    __table_args__ = (UniqueConstraint("item_id", "occasion_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    occasion_id: Mapped[int] = mapped_column(
        ForeignKey("occasions.id", ondelete="CASCADE"), index=True
    )
    username: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Ranking(Base):
    """One pairwise-comparison axis — "Quality", "Composition".

    **A RANKING ORDERS PICTURES AND TAGS NONE OF THEM** (owner 2026-09).
    It used to own a tag namespace: ``<prefix>:0`` …
    ``<prefix>:9`` were minted with it, locked against every catalog verb,
    and a derived ``item_tags`` row per scored picture was diffed into place
    by ``rebuild``. All of that is gone, and with it ``prefix``, ``enabled``
    (which was the switch for exactly that writing) and a pool's own. What
    is left is what a ranking always WAS: the judgments, and the standings
    fitted from them (``standings``, computed on the way out and stored
    nowhere). Writing something onto the pictures is the **Assign ratings**
    action's business, and what IT writes are ordinary assignments through
    the ordinary door.

    ``scope`` is a query STRING (the saved-search tag set) naming which
    pictures the axis applies to at all — "" is the whole library. Additive
    table; ``create_all`` adds it on an existing library.

    A ``target`` column and per-side appearance ids existed for a
    subject-targeted variant, removed before the first release. The lesson
    that removal left, which binds any column taken out of a table from here
    on: **a leftover column is only ignorable while it is NULLABLE and named
    in no constraint.** ``target`` was neither — NOT NULL with no default —
    so every ranking INSERT failed with a bare ``IntegrityError``, and
    ``ranking_dismissals`` carried the milder half, its UNIQUE still naming
    ``appearance_id`` where a NULL is DISTINCT in a SQLite unique index, so
    the constraint on ``(ranking, item)`` quietly held nothing. ``create_all``
    never ALTERs, so only a MIGRATED library can carry that class of fault
    and a rung is the only thing that can repair it.
    """

    __tablename__ = "rankings"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, default="")
    scope: Mapped[str] = mapped_column(Text, default="")
    # The bucket RANGE, inclusive both ends: 0…9 by default, 1…5 or 0…100 by
    # choice. It is what the standings are SPREAD over — the scale the axis
    # speaks in, which the Assign-ratings rules are written against. It
    # outlived the tags it used to name. `text("0")`, not `"0"`: the
    # `count_offset` lesson — an ALTER and create_all must produce one shape.
    bucket_lo: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"))
    bucket_hi: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("9"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class RankingPool(Base):
    """One POPULATION a ranking is computed over — "Illustrations",
    "Photographs" — with standings and buckets of its own under the
    ranking's one prefix and one range.

    Membership is DERIVED: an item is in a pool when a judgment of that
    pool names it, either side — there is no membership table, and a
    picture joins a pool by being rated in it. A ranking always has at
    least one pool; the first is born with it and UNNAMED (``""``, which
    the UI renders as "Default"), and the last cannot be deleted. The NAME
    is the pool's portable identity (unique per ranking): the item dict
    and the library merge name a judgment's pool by it, and omit it
    entirely for the unnamed one so a single-pool library's dict stays
    byte-identical to what it was before pools existed.

    Each pool is FITTED on its own, so an item rated in two of them has
    two standings — which is the point of a population. Not-applicable
    stays a fact about the whole ranking (`RankingDismissal`).
    """

    __tablename__ = "ranking_pools"
    __table_args__ = (UniqueConstraint("ranking_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ranking_id: Mapped[int] = mapped_column(
        ForeignKey("rankings.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String, default="")
    # The order the pools are listed and asked in (the dialog's
    # drag-reorder; ties break by id). `text("0")`: the count_offset lesson.
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0)
    # A pool had an `enabled` switch once. It meant "materialize
    # no score assignments for this population" and nothing else — the
    # rating never read it — so it left with the assignments.
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class RankingJudgment(Base):
    """One comparison somebody made on a ranking: A against B, and which won.

    ``outcome`` is ``"a"`` / ``"b"`` (the winner) or ``"skip"`` — "can't
    decide, put this pair aside", which the pair selector honours and the fit
    ignores. Repeated pairs are allowed and are evidence like any other. The
    judgment is the durable record (logged, revertible, riding item A's
    sidecar); the standings are fitted from these on the way out.
    A judgment belongs to ONE pool of its ranking (`pool_id`); a rating
    session that writes into several pools writes one row per pool.
    """

    __tablename__ = "ranking_judgments"

    id: Mapped[int] = mapped_column(primary_key=True)
    ranking_id: Mapped[int] = mapped_column(
        ForeignKey("rankings.id", ondelete="CASCADE"), index=True
    )
    # WHICH POOL the comparison was made in — NOT NULL, and the whole of
    # pool membership (see `RankingPool`). Every constructor sets it:
    # `ops/rankings.judge`, `history._revert_remove_ranking_item`,
    # `libimport._apply_ranking_records`.
    pool_id: Mapped[int] = mapped_column(
        ForeignKey("ranking_pools.id", ondelete="CASCADE"), index=True
    )
    a_item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    b_item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    outcome: Mapped[str] = mapped_column(String(8))
    username: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class RankingDismissal(Base):
    """"This axis does not apply to this picture" — remembered, so the rating
    overlay never offers the pair again. The same shape as the two suggestion
    dismissals above, and like them deliberately NOT a negative tag: it
    reaches nothing but pair selection."""

    __tablename__ = "ranking_dismissals"
    __table_args__ = (
        UniqueConstraint("ranking_id", "item_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ranking_id: Mapped[int] = mapped_column(
        ForeignKey("rankings.id", ondelete="CASCADE"), index=True
    )
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    username: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class GroupTag(Base):
    __tablename__ = "group_tags"
    __table_args__ = (
        UniqueConstraint("group_id", "tag_id"),
        Index("ix_group_tags_group", "group_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE")
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"), index=True
    )
    negative: Mapped[bool] = mapped_column(Boolean, default=False)

    group: Mapped["Group"] = relationship(back_populates="tags")
    tag: Mapped["Tag"] = relationship()


class Caption(Base):
    __tablename__ = "captions"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, default=0)
    # "caption" describes the picture; "instruction" says how it was MADE from
    # the items in :class:`CaptionRef` — the training data an edit/instruction
    # model needs. An explicit column rather than "does it have refs", because
    # an instruction being drafted has none yet and one whose refs were all
    # deleted must not silently become a description in the next training run.
    kind: Mapped[str] = mapped_column(
        String(16), default="caption", server_default="caption"
    )
    # True for a machine-generated caption awaiting the user's approval.
    pending: Mapped[bool] = mapped_column(Boolean, default=False)
    # The AI model id that generated this caption (e.g. "joycaption:descriptive"),
    # or "" for a hand-written one. Surfaced so the user can see the provenance.
    model: Mapped[str] = mapped_column(String, default="")
    # True once a generated caption has been edited by the user (its `model` is
    # kept so the UI can still show what it was based on).
    edited: Mapped[bool] = mapped_column(Boolean, default=False)

    item: Mapped["Item"] = relationship(back_populates="captions")


class ItemMetadata(Base):
    """What an item's ACTIVE FILE says about itself, minus what the item mutes.

    DERIVED — the only writer is ``importer.rebuild_item_metadata``, which builds
    it from the active file's :class:`FileMetadata` rows less any name carrying an
    :class:`ItemMetaMute`. It used to be the whole of an item's indexed metadata;
    it is now HALF of it, and :class:`ItemMetaPin` is the other half. Search reads
    the UNION of the two, which is the whole of "only item-level metadata and the
    active file's metadata are searched" — a rule that holds by construction,
    because nothing copies a non-active file's values here.

    Every reader must consider pins as well, or a pinned value is silently
    invisible to it. That union is spelled ONCE, in ``searchctx.load_indexed_meta``
    (and ``ops/metadata.effective_one`` for the readers that want a single
    answer); do not write it a second time.

    Each row is one ``name``/value pair with a ``mtype``
    (``numeric``/``text``/``date``); the value lives in ``num_value`` (a raw
    number, or a date as a sortable ``YYYYMMDDHHMMSS`` number — see
    ``media.date_sortkey``) or ``text_value`` accordingly, and ``raw`` keeps the
    human display string.

    Intrinsic/derived properties of the *active file* (width, height, resolution,
    aspect, length, fps, bitrate, import/capture date) are **not** stored here —
    they are columns already, so indexing them would be a second copy of a fact
    the database holds and ``prefilter`` compiles them straight to SQL over those
    columns. Only genuinely static metadata is indexed.

    The metadata *catalog* (name + type + item-count) is a cheap aggregate over
    this table and ``item_meta_pins``, unioned with the intrinsic names.
    """

    __tablename__ = "item_metadata"
    __table_args__ = (
        UniqueConstraint("item_id", "name"),
        Index("ix_item_metadata_item", "item_id"),
        Index("ix_item_metadata_name", "name"),
        # COVERING, for the metadata catalog's aggregate — the search
        # builder's autocomplete groups this whole table by (name, mtype).
        # Without it SQLite sorts every row into a temp b-tree twice, once
        # for the GROUP BY and once for the count(DISTINCT); with it the scan
        # arrives already grouped. It only pays off once the query is not a
        # UNION — a compound subquery is materialized as a co-routine and no
        # index can reach through it (see `routers/metadata.py`).
        #
        # AN INDEX ON THIS TABLE IS NOT CHEAP and the size is the reason
        # there is one here rather than two. Measured over 3.6M rows on a
        # 545 MB library:
        #
        #   this one          +103 MB (19%)  aggregate 2.44 s -> 0.57 s
        #                                    enum      0.83 s -> 0.66 s
        #   (name, mtype,     +114 MB (21%)  aggregate unchanged
        #    text_value,                     enum      0.83 s -> 0.18 s
        #    item_id)
        #
        # The second was measured and REJECTED on that library, and REVISITED
        # with numbers on a bigger one — which is what that note asked for.
        # `/metadata/values` is not a pass nobody runs: it is what fills the
        # query builder's value dropdown, once per name whose dropdown is
        # opened, so it is interactive. Measured over 4.5M rows on a 3.26 GB
        # library, `?name=camera_make`:
        #
        #   as it was (a UNION with the pins, `IN (visible items)`)  1.92 s
        #   per table, `NOT IN (trashed)` — the same answer, free    0.79 s
        #   ...and with this index                                  0.08 s
        #
        # Its cost was the reason for the earlier no: +114 MB on a 545 MB
        # library, i.e. 21%. On this one it is +129 MB on 3.26 GB — 4.0%.
        # Both figures are the same index; the PERCENTAGE was a fact about
        # how much else that library held, and the case where it looks
        # expensive is exactly the case where the dropdown is slowest.
        Index("ix_item_metadata_group", "name", "mtype", "item_id",
              "num_value"),
        Index("ix_item_metadata_values", "name", "mtype", "text_value",
              "item_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    # "numeric" | "text" | "date"
    mtype: Mapped[str] = mapped_column(String(8), default="text")
    num_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    text_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # The original display string (e.g. "Canon EOS 5D", "2026:07:11 09:44:03").
    raw: Mapped[str] = mapped_column(Text, default="")


class FileMetadata(Base):
    """What ONE FILE says about itself — read once, when the file is created.

    An item holds several source files (a near-dup import lands as an
    "alternative", a rotation folds in, an editor save adds one), and for as long
    as metadata lived only on the item, only the active one was ever read: the
    same picture re-saved with richer EXIF was stored, and everything it said
    about itself was invisible and unsearchable forever. This is where it goes.

    Same value columns as :class:`ItemMetadata`, which is what lets
    ``rebuild_item_metadata`` copy a row across without translating anything.
    One answer per name per file — a file is one set of bytes and has one
    opinion — so ``(file_id, name)`` is a real constraint here where it is
    deliberately absent on the item side.

    Every path that creates a ``File`` from real bytes must call
    ``importer.index_file_metadata``: a file with no rows here contributes
    NOTHING the moment it becomes active. That is the same call-site discipline
    ``compute_phash_image`` and ``colorkey.color_signature`` already carry, and
    ``tests/ui/test_file_metadata.py`` is what holds it.
    """

    __tablename__ = "file_metadata"
    __table_args__ = (
        UniqueConstraint("file_id", "name"),
        Index("ix_file_metadata_file", "file_id"),
        Index("ix_file_metadata_name", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    # "numeric" | "text" | "date" — see ItemMetadata for the encoding.
    mtype: Mapped[str] = mapped_column(String(8), default="text")
    num_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    text_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw: Mapped[str] = mapped_column(Text, default="")


class ItemMetaPin(Base):
    """A metadata value promoted to ITEM level: true of the picture, whichever
    file happens to be active.

    The ``Item.taken_at`` pattern in a second subject — somebody looked at what
    two files said and answered. Search reads pins BESIDE the active file's own
    values rather than instead of them, so pinning a second ISO makes the item
    answer both; :class:`ItemMetaMute` is how a pin becomes an override.

    The VALUE is stored, not a reference to the file it came from, so a pin
    survives that file being deleted or re-encoded — it was an answer about the
    picture, not about the bytes. ``source_file_id`` is SET NULL and is read only
    to say "promoted from file 2".

    Identity is ``(item_id, name, raw)``: ``raw`` is never NULL, so it is a
    constraint SQLite will actually enforce, where ``(num_value, text_value)``
    would not be (NULLs compare distinct in a unique index). Keying on the value
    rather than on the name is what lets two answers for one name both be pinned
    — which is what the Info tab's one-row-per-unique-value offer produces.
    """

    __tablename__ = "item_meta_pins"
    __table_args__ = (
        UniqueConstraint("item_id", "name", "raw"),
        Index("ix_item_meta_pins_item", "item_id"),
        Index("ix_item_meta_pins_name", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))
    mtype: Mapped[str] = mapped_column(String(8), default="text")
    num_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    text_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw: Mapped[str] = mapped_column(Text, default="")
    # Provenance for the Info tab's "promoted from file 2" line, and nothing
    # else — no rule reads it, so say so wherever it is touched.
    source_file_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("files.id", ondelete="SET NULL"), nullable=True,
        index=True,
    )


class ItemMetaMute(Base):
    """"Do not take this name from the active file" — the dual of a pin.

    Without it a pin could only ever ADD an answer, so a wrong capture date on
    the active file could be joined but never overruled. Muting is what makes a
    pin an override.

    Per NAME, not per value: the active file contributes at most one answer per
    name, and a mute keyed on the name is the one that survives the file being
    re-encoded or another file becoming active — which is the point of an answer
    that lives on the item.
    """

    __tablename__ = "item_meta_mutes"
    __table_args__ = (UniqueConstraint("item_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))


class FileName(Base):
    """A recorded *source* of a stored file — either an imported filename (with
    its relative path) or a web URL the file came from.

    A byte-identical file imported again under a *different* name adds another
    row here rather than a second copy on disk. A re-import under an
    already-known name is skipped entirely. The user can also add sources by
    hand (a filename+path or a URL). For a web-URL source ``name`` holds the URL
    and ``accessed_at`` the access date/time; a filename source has
    ``accessed_at`` null.

    Uniqueness is enforced at the app level (routers/files.py), not by a DB
    constraint: a filename source is unique per (file, name), while a URL
    source is unique per (file, name, accessed_at) — the same URL may be
    recorded several times with *different* access times.
    """

    __tablename__ = "file_names"
    __table_args__ = (Index("ix_file_names_file_name", "file_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String)
    # True when this source is a web URL (``name`` holds the URL) rather than an
    # imported/local filename.
    is_url: Mapped[bool] = mapped_column(Boolean, default=False)
    # Optional access date/time for a web-URL source.
    accessed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Sequence(Base):
    """An ordered collection of items (comic pages, video frames, manual).

    An item may belong to several sequences via ``SequenceItem``; its
    ``Item.main_sequence_id`` selects which one drives the grid number badge.
    """

    __tablename__ = "sequences"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Stable identity used by the JSON sidecars (sequence refs never use DB ids).
    uid: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, default=_new_uid
    )
    name: Mapped[str] = mapped_column(String, index=True)
    # "archive" (comic), "pdf" (a document's pages), "gif" (the frames of an
    # animated GIF), "video" (frames of a video), or "manual".
    kind: Mapped[str] = mapped_column(String(16), default="manual")
    # The file/archive/video name the sequence was created from (default name).
    source_name: Mapped[str] = mapped_column(String, default="")
    # The container Item (kind="sequence") that represents this sequence in the
    # library — it carries the sequence's tags/groups/captions and is what the
    # user sees in the grid. Shares the sequence's lifecycle. Null only during
    # construction.
    item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    items: Mapped[list["SequenceItem"]] = relationship(
        back_populates="sequence", cascade="all, delete-orphan",
        order_by="SequenceItem.position",
    )


class SequenceItem(Base):
    """One POSITION of a sequence — deliberately NOT unique per (sequence,
    item). A book's three blank pages all dedup onto one item, and the
    sequence is what keeps the book's structure: that item sits at each of
    the three positions, one row each. Anything addressing ONE occurrence
    addresses the ROW (`member_ids` in the reorder/remove bodies); an item
    id means every occurrence at once. (There was a unique constraint here
    once; a migration step dropped it, and the step went with the ladder at
    version 1.)
    """

    __tablename__ = "sequence_items"
    __table_args__ = (
        Index("ix_sequence_items_sequence", "sequence_id"),
        Index("ix_sequence_items_item", "item_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sequence_id: Mapped[int] = mapped_column(
        ForeignKey("sequences.id", ondelete="CASCADE"), index=True
    )
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    # 0-based ordinal within the sequence; displayed 1-based.
    position: Mapped[int] = mapped_column(Integer, default=0)

    sequence: Mapped["Sequence"] = relationship(back_populates="items")


class VideoFrame(Base):
    """A perceptual hash of one sampled frame of an imported video.

    Stored so that an image imported *later* (a screenshot grabbed from the
    video) can be matched back to the video it came from — the video-import scan
    only sees images already in the library, so without these rows a screenshot
    imported afterwards would never be linked. ``phash`` is the 256-bit hash as
    hex (like ``File.phash``); matching scans these rows by Hamming distance.
    """

    __tablename__ = "video_frames"
    __table_args__ = (
        Index("ix_video_frames_video", "video_item_id"),
        # Band-key indexes, exactly as on `files` — this is the biggest table
        # in the app, which is why the probe must be indexed lookups.
        *(Index(f"ix_video_frames_b{i}", f"b{i}")
          for i in range(_dedup_index.BANDS)),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    video_item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    video_file_id: Mapped[int] = mapped_column(
        ForeignKey("files.id", ondelete="CASCADE"), index=True
    )
    timestamp: Mapped[float] = mapped_column(Float)
    phash: Mapped[str] = mapped_column(String(64))
    # The hash's band keys, like `File`'s: derived and listener-filled.
    # (`phash` is NOT NULL here, so these are too in practice — nullable
    # anyway, since the listener fills them after the row is constructed.)
    b0: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    b1: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    b2: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    b3: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    b4: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    b5: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    b6: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    b7: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    b8: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    b9: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    b10: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    b11: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Frame pixel size — used to reject a match whose aspect ratio is clearly
    # different (a 16:9 frame must not match an A4-portrait page).
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)


class Relationship(Base):
    """A directional link from an original item to a derived one.

    ``kind`` is e.g. "clip", "frame", "edit", "crop", "panel", "manual";
    ``edit`` rows point original -> derived (the importer's chain walk reads
    them that way); ``crop``/``panel``/``frame``/``clip`` rows point
    derived -> source, with any region boxes on the SOURCE's frame. ``meta`` holds
    kind-specific JSON (e.g. a clip's ``{"start": .., "end": ..}``, or a frame
    match's ``{"timestamps": [..]}``). Cycles are rejected by the router that
    creates relationships.
    """

    __tablename__ = "relationships"
    __table_args__ = (
        UniqueConstraint("from_item_id", "to_item_id", "kind"),
        Index("ix_relationships_from", "from_item_id"),
        Index("ix_relationships_to", "to_item_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    from_item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    to_item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16), default="manual")
    meta: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class RelationshipTag(Base):
    """A free-form label on a relationship — a "link tag", separate from item
    tags (not part of the Tags tab). A link tag exists only while at least one
    relationship uses it, so the autocomplete list is simply the distinct set of
    names currently in use."""

    __tablename__ = "relationship_tags"
    __table_args__ = (
        UniqueConstraint("relationship_id", "name"),
        Index("ix_relationship_tags_name", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    relationship_id: Mapped[int] = mapped_column(
        ForeignKey("relationships.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))


class CaptionTag(Base):
    """A meta tag on a caption — the SAME namespace as :class:`RelationshipTag`
    (the app calls them "meta tags"): free-form labels that annotate a caption
    or a link rather than the image itself ("alt text", "for training",
    "German"). Separate from item ``Tag``s: no aliases, no parents."""

    __tablename__ = "caption_tags"
    __table_args__ = (
        UniqueConstraint("caption_id", "name"),
        Index("ix_caption_tags_name", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    caption_id: Mapped[int] = mapped_column(
        ForeignKey("captions.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64))


class CaptionRef(Base):
    """One reference image of an INSTRUCTION, at its place in the order.

    An instruction sits on the item it produced — the picture the model must
    make — and these are the pictures it was made FROM, in the order the model
    is shown them. The order is the point, which is why this is its own table
    rather than a :class:`Relationship`: those are unordered, unique per
    ``(from, to, kind)`` and shared by every caption on the item, so two
    instructions naming the same two sources in different orders could not
    both be said. Shaped exactly like :class:`SequenceItem`, this library's one
    ordered-membership pattern.
    """

    __tablename__ = "caption_refs"
    __table_args__ = (
        UniqueConstraint("caption_id", "item_id"),
        Index("ix_caption_refs_caption", "caption_id"),
        Index("ix_caption_refs_item", "item_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    caption_id: Mapped[int] = mapped_column(
        ForeignKey("captions.id", ondelete="CASCADE"), index=True
    )
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True
    )
    # 0-based ordinal within the instruction; displayed 1-based.
    position: Mapped[int] = mapped_column(Integer, default=0)


class TrashedItem(Base):
    """An item moved to the Trash. Hidden from normal listings until restored.

    ``original_groups`` is a comma-separated snapshot of the group ids the item
    belonged to when trashed, so restore can put it back where it was.
    ``original_sequences`` is the same idea for sequence membership —
    ``"seq:pos"`` per OCCURRENCE (a repeated page is several rows and comes
    back as several) — because trashing takes the item out of its sequences: a
    trashed page must not go on holding a place in a chapter. Nullable, and
    NULL reads as "nothing recorded": rows written before the column existed
    (schema version 2) never had their memberships removed either.
    """

    __tablename__ = "trashed_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), unique=True, index=True
    )
    original_groups: Mapped[str] = mapped_column(Text, default="")
    original_sequences: Mapped[Optional[str]] = mapped_column(Text)
    #: Whether the item was HIDDEN when it was trashed.
    #:
    #: **An item in the Trash is never hidden.** They are two different
    #: answers to "why is this not in the grid", and holding both meant the
    #: Hidden badge went on counting a picture the Hidden view no longer
    #: showed — a count nothing could make agree with the list under it. So
    #: `trash_one` clears the flag, and this is where it goes so that
    #: restoring puts the item back the way it was rather than back in
    #: everybody's face.
    original_hidden: Mapped[bool] = mapped_column(Boolean, default=False,
                                                  server_default=text("0"))
    trashed_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Event(Base):
    """An append-only log of library modifications, powering the History view.

    Each row is one fine-grained action (the UI groups similar consecutive ones
    into a summary row). ``data`` is structured JSON carrying everything needed
    to describe the action, link to the entities it touched, and — where the
    action is invertible — revert it. Because every field is machine-readable, a
    delta between two points in time is just the events in that window.
    """

    __tablename__ = "events"
    __table_args__ = (Index("ix_events_created", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    # Where the change came from: "web" (the app) or "cli" (bulk import tool).
    source: Mapped[str] = mapped_column(String(8), default="web")
    # The user who made the change (from upstream auth). Empty = anonymous / CLI.
    username: Mapped[str] = mapped_column(String(64), default="")
    # Machine action name, e.g. "add_tag", "remove_from_group", "trash_item".
    action: Mapped[str] = mapped_column(String(32), index=True)
    # The primary entity kind/id this action is about (for grouping + linking).
    entity_type: Mapped[str] = mapped_column(String(16), default="")
    entity_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Human one-liner (fallback display) and the structured payload.
    summary: Mapped[str] = mapped_column(Text, default="")
    # The summary's unfilled TEMPLATE and its slot values (JSON object) — what
    # lets the History view say the sentence in another language: look the
    # template up in the UI's catalog, fill the same slots. `summary` stays
    # the filled English and is the fallback for rows written before these
    # columns existed (there is no backfill: the values cannot be recovered
    # from an interpolated string, and a truthful English row beats a guess).
    # Empty means "the summary is its own template, nothing to fill".
    # `server_default` so the migrated ALTER's DEFAULT matches `create_all`'s
    # DDL — the Caption.kind precedent, held by tests/core/test_migrations.py.
    summary_key: Mapped[str] = mapped_column(Text, default="", server_default="")
    summary_vars: Mapped[str] = mapped_column(Text, default="", server_default="")
    data: Mapped[str] = mapped_column(Text, default="{}")
    # Set when the action has been reverted from the History view (an invertible
    # action can be undone once; the row is then shown struck-through).
    reverted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Job(Base):
    """A queued machine-learning task over one item (background removal,
    captioning, or tagging). Jobs run one at a time on a background worker; the
    UI lists queued/running/recent jobs and can cancel the ones not yet done.

    The one table only `media_compost.ui` writes, kept HERE anyway: the model
    metadata and the migration ladder are one thing, and splitting them so
    that one package's table lives in that package would mean two ladders
    over one file — a far worse wart than a table the base install never
    fills. (It is also why the `after_flush` sidecar sweep can keep its
    "anything with an `item_id` except Job" rule in one place.)
    """

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    # "bg_removal" | "caption" | "tag"
    kind: Mapped[str] = mapped_column(String(16), index=True)
    model: Mapped[str] = mapped_column(String(64), default="")
    # WHICH PICTURE this is about — NULL where the answer is "the library".
    # Almost every job here is one model over one item, and the list, the
    # per-item state and the jobs↔item join are all built on that. An
    # estimate is not: it walks a search's whole scope a page at a time and
    # never holds the ids, which is what lets it run over a million items,
    # so there is no item to name and naming an arbitrary one would put the
    # job on that picture's row. Nullable rather than a second table: what
    # such a job wants from the queue is the worker, the row, the progress
    # bar and the cancel button, which is what this table is.
    item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), index=True, nullable=True
    )
    # For a multi-item job (e.g. tagging a whole selection in one task), the JSON
    # list of every item id it covers; NULL for a single-item job, whose only
    # item is ``item_id``. ``item_id`` stays set to the first item either way, so
    # the single-item code path and the jobs↔item join keep working unchanged.
    item_ids: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # The user who enqueued the job (from upstream auth). Empty = anonymous.
    # Captured here because the worker applies results off-request, out of any
    # HTTP context, and stamps the resulting history event with it.
    username: Mapped[str] = mapped_column(String(64), default="")
    # Optional per-job options as JSON — the action extras a KIND asks for:
    # {"reference": "<ref id>"} for a reference-guided colorization,
    # {"into_sequence": true} for the panels task's own switch. Empty for
    # jobs without extras.
    options: Mapped[str] = mapped_column(Text, default="")
    # "queued" | "running" | "done" | "failed" | "canceled"
    status: Mapped[str] = mapped_column(String(12), default="queued", index=True)
    # Short human result/error message (e.g. "3 tags", or the failure reason).
    message: Mapped[str] = mapped_column(Text, default="")
    # Full captured output (stdout/stderr + logging) from the run, for the
    # "view log" overlay. Can be large, so it's fetched on demand, not listed.
    log: Mapped[str] = mapped_column(Text, default="")
    # Progress percentage (0-100) for multi-step jobs (e.g. per-page panel
    # detection on a sequence); 0 for single-step jobs that don't report it.
    progress: Mapped[int] = mapped_column(Integer, default=0)
    # How many of ``item_ids`` are finished — the CURSOR, not a display
    # figure: a paused batch job resumes from it, and the per-item list reads
    # each item's state off it (everything before it is done). Written after
    # every committed chunk, so it survives the process that wrote it.
    done_count: Mapped[int] = mapped_column(Integer, default=0,
                                            server_default=text("0"))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Setting(Base):
    """A tiny key/value store for user-adjustable app settings (e.g. whether AI
    models may download from the network or must use locally cached files only).
    New tables are created by ``create_all`` on existing libraries too, so this
    needs no additive migration."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


def get_setting(session: Session, key: str, default: str = "") -> str:
    row = session.get(Setting, key)
    return row.value if row is not None else default


def set_setting(session: Session, key: str, value: str) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - infra
    """Enable foreign keys and WAL for concurrent read during import."""
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    # Wait (rather than immediately erroring) when another connection holds the
    # write lock — the background ML worker and request threads both write.
    # 30 s, not 5: a bulk import's periodic commit can hold the write lock for
    # several seconds, and a request thread timing out surfaces as a 500.
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()


def is_locked_error(exc: BaseException) -> bool:
    """Whether ``exc`` is SQLite's transient write collision.

    Two spellings of one situation: "database is locked" is a deferred
    transaction that READ, then met another process's commit when its first
    write tried to upgrade — SQLite refuses IMMEDIATELY there, deliberately
    ignoring ``busy_timeout``, because the transaction's snapshot can never
    become current. Waiting inside the transaction is therefore pointless;
    the cure is to END it and run the work again on a fresh snapshot, which
    is what every caller of this predicate does. "database is busy" is the
    plain writer-vs-writer case past its timeout, retryable the same way.
    """
    from sqlalchemy.exc import OperationalError

    if not isinstance(exc, OperationalError):
        return False
    text = str(exc)
    return "database is locked" in text or "database is busy" in text



def chunked(ids, size: int = 10_000):
    """Yield ``ids`` in lists of at most ``size`` elements.

    SQLite caps bind parameters per statement (``SQLITE_LIMIT_VARIABLE_NUMBER``),
    so any Python-side id collection that parameterizes an ``IN (...)`` must be
    split — a single oversized list raises ``OperationalError: too many SQL
    variables``.

    **AND THE CAP IS NOT THE ONLY REASON, NOR THE ONE THAT BITES NOW.** It was
    32,766 when this was written and is 250,000 on the SQLite shipping here
    (3.53), so an unsplit catalog-sized list no longer errors — it goes
    QUADRATIC. Measured on a 100,000-tag library through `implied_names`, which
    had been spelled without this: 0.05 s at 90,000 ids and 241 s at 100,000,
    returning the same two rows. A loud error became a listing that hangs, so
    the rule matters more than it did rather than less, and a version bump can
    turn a working query into that with nothing in this repository changing.
    """
    from itertools import islice

    it = iter(ids)
    while chunk := list(islice(it, size)):
        yield chunk


def touch_items(session: Session, item_ids) -> None:
    """Mark items as modified now (drives the "modification date" sort).

    Call after any edit to an item's tags, captions, groups, name or files.
    Silently ignores ids that don't exist.
    """
    from sqlalchemy import update

    ids = [i for i in set(item_ids) if i is not None]
    if not ids:
        return
    for chunk in chunked(ids):
        session.execute(
            update(Item).where(Item.id.in_(chunk)).values(updated_at=_now())
        )


def next_file_number(session: Session, item_id: int) -> int:
    """The next free stable file number (#1, #2, …) for an item.

    Called at File creation everywhere (numbers are assigned eagerly — they name
    the on-disk file ``files/<number>.<ext>``). Continues past the current
    maximum so numbers are effectively never reused within an item's lifetime.
    """
    from sqlalchemy import func, select

    mx = session.execute(
        select(func.coalesce(func.max(File.number), 0))
        .where(File.item_id == item_id)
    ).scalar_one()
    return int(mx) + 1


def copy_item_associations(session: Session, src_item_id: int,
                           dst_item_id: int, *, links: bool = False) -> None:
    """Copy everything the library knows ABOUT ``src`` onto ``dst``: group
    memberships, tags (with their per-item tag groups, placements and boxes and
    dates), captions, the faces and who they are, where it was taken, when it
    was taken, and the suggestions somebody has already refused.

    Used when a brand-new item is spun off from a source — the "new item"
    result of background/watermark removal, splitting a file into its own item,
    and the editors' "Save to a new item" — so the derived item inherits the
    same organization instead of starting bare. Assumes ``dst`` has none of
    these associations yet (it is freshly created).

    **The boxes and faces travel VERBATIM, and that is correct because the two
    items share a reference frame**: a derived file records its region within
    the original's frame (`File.crop_*`), so a crop does not move them. A
    ROTATED crop is the exception the editor already knows about — it cannot be
    expressed as a region, so its boxes are the one thing here that can land
    wrong.

    ``links`` additionally copies the relationships the source is either end
    of. Off by default: for a background-removal result "linked to everything
    the original is linked to" is a claim nobody made, while for a full copy of
    the item it is exactly what was asked for.
    """
    from sqlalchemy import select

    # Group memberships.
    for gid in session.execute(
        select(ItemGroup.group_id).where(ItemGroup.item_id == src_item_id)
    ).scalars().all():
        session.add(ItemGroup(item_id=dst_item_id, group_id=gid))

    # Per-item tag groups — recreated so placements can be remapped onto them.
    group_map: dict[int, int] = {}
    for g in session.execute(
        select(ItemTagGroup).where(ItemTagGroup.item_id == src_item_id)
    ).scalars().all():
        ng = ItemTagGroup(item_id=dst_item_id, name=g.name,
                          position=g.position, system=g.system)
        session.add(ng)
        session.flush()
        group_map[g.id] = ng.id
        for name in session.execute(
            select(ItemTagGroupTag.name).where(ItemTagGroupTag.group_id == g.id)
        ).scalars().all():
            session.add(ItemTagGroupTag(group_id=ng.id, name=name))

    # Tags with their placements (remapped group) and boxes.
    for it in session.execute(
        select(ItemTag).where(ItemTag.item_id == src_item_id)
    ).scalars().all():
        nit = ItemTag(item_id=dst_item_id, tag_id=it.tag_id,
                      negative=it.negative, pending=it.pending)
        session.add(nit)
        session.flush()
        for p in session.execute(
            select(ItemTagPlacement).where(ItemTagPlacement.item_tag_id == it.id)
        ).scalars().all():
            gid = group_map.get(p.group_id) if p.group_id is not None else None
            np = ItemTagPlacement(item_tag_id=nit.id, group_id=gid)
            session.add(np)
            session.flush()
            for b in session.execute(
                select(ItemTagBox).where(ItemTagBox.placement_id == p.id)
            ).scalars().all():
                session.add(ItemTagBox(
                    placement_id=np.id, x=b.x, y=b.y, w=b.w, h=b.h,
                    time_start=b.time_start, time_end=b.time_end,
                    # The box's whole shape travels: without these a negative
                    # time range copied onto the new item read as positive
                    # (violating the _sync_timed_sign invariant) and a moving
                    # subject's track fell apart.
                    track_id=b.track_id, negative=b.negative,
                    points=b.points,
                ))

    # Captions (order + kind + provenance/pending/edited flags preserved), with
    # the meta tags that label them and — for an instruction — the ordered
    # reference images: a copy of the result was made from the same sources, so
    # dropping them would leave a sentence pointing at nothing.
    for c in session.execute(
        select(Caption).where(Caption.item_id == src_item_id)
        .order_by(Caption.position, Caption.id)
    ).scalars().all():
        nc = Caption(item_id=dst_item_id, text=c.text, position=c.position,
                     kind=c.kind or "caption",
                     pending=c.pending, model=c.model, edited=c.edited)
        session.add(nc)
        session.flush()
        for name in session.execute(
            select(CaptionTag.name).where(CaptionTag.caption_id == c.id)
        ).scalars().all():
            session.add(CaptionTag(caption_id=nc.id, name=name))
        for ref_item, pos in session.execute(
            select(CaptionRef.item_id, CaptionRef.position)
            .where(CaptionRef.caption_id == c.id)
            .order_by(CaptionRef.position, CaptionRef.id)
        ).all():
            session.add(CaptionRef(caption_id=nc.id, item_id=ref_item,
                                   position=pos))

    # WHEN the picture was taken, as an override somebody typed. A copy of the
    # picture was taken at the same moment; the EXIF and event fallbacks need
    # nothing copied, since they are read from the file and the tags.
    src_item = session.get(Item, src_item_id)
    dst_item = session.get(Item, dst_item_id)
    if src_item is not None and dst_item is not None:
        dst_item.taken_at = src_item.taken_at

    # The FACES, who they are, and what each descriptor was. A face is evidence
    # about the picture, so a copy of the picture carries it — and the
    # descriptors come too, or the copy's faces could never cluster or be
    # suggested until every detector was run again.
    face_map: dict[int, int] = {}
    for f in session.execute(
        select(Face).where(Face.item_id == src_item_id)
    ).scalars().all():
        nf = Face(item_id=dst_item_id, file_id=None, x=f.x, y=f.y, w=f.w,
                  h=f.h, det_score=f.det_score, model=f.model,
                  dismissed=f.dismissed)
        session.add(nf)
        session.flush()
        face_map[f.id] = nf.id
        for e in session.execute(
            select(FaceEmbedding).where(FaceEmbedding.face_id == f.id)
        ).scalars().all():
            session.add(FaceEmbedding(face_id=nf.id, model=e.model,
                                      vector=e.vector))
    # …and the appearances: who is in the picture, at which face, how old, and
    # whether that was somebody's answer or a model's guess.
    for a in session.execute(
        select(ItemSubject).where(ItemSubject.item_id == src_item_id)
    ).scalars().all():
        session.add(ItemSubject(
            item_id=dst_item_id, subject_id=a.subject_id,
            face_id=face_map.get(a.face_id) if a.face_id is not None else None,
            when_date=a.when_date, when_age=a.when_age,
            assigned_by=a.assigned_by, match_score=a.match_score,
        ))

    # The TEXT read off the picture, tree and all. Like a face it is evidence
    # about the picture, so a copy carries it — and a corrected string is not
    # regenerable from anything, so losing it here would lose work done by
    # hand. A reading belongs to a FILE, so only the SOURCE's active file's
    # regions travel (the copy's pixels derive from that file and no other),
    # stamped onto the COPY's active file — every caller sets that pointer
    # before copying, and a None simply keeps the rows invisible until an
    # engine reads the copy. Parents are walked before children EXPLICITLY
    # (a region's parent must exist before its id can be remapped); ordering
    # by id happens to get that right for engine-written trees and is wrong
    # the moment a child is drawn by hand later.
    src_item = session.get(Item, src_item_id)
    dst_item = session.get(Item, dst_item_id)
    region_map: dict[int, int] = {}
    text_rows = session.execute(
        select(TextRegion).where(
            TextRegion.item_id == src_item_id,
            TextRegion.file_id == (src_item.active_file_id
                                   if src_item is not None else None))
    ).scalars().all()
    pending_rows = list(text_rows)
    while pending_rows:
        rest: list[TextRegion] = []
        for r in pending_rows:
            if r.parent_id is not None and r.parent_id not in region_map:
                rest.append(r)
                continue
            nr = TextRegion(
                item_id=dst_item_id,
                file_id=(dst_item.active_file_id
                         if dst_item is not None else None),
                parent_id=(region_map[r.parent_id]
                           if r.parent_id is not None else None),
                level=r.level, ord=r.ord, x=r.x, y=r.y, w=r.w, h=r.h,
                quad=r.quad, text=r.text, score=r.score, lang=r.lang,
                model=r.model, dismissed=r.dismissed, edited=r.edited,
            )
            session.add(nr)
            session.flush()
            region_map[r.id] = nr.id
        if len(rest) == len(pending_rows):  # orphans (shouldn't happen)
            break
        pending_rows = rest

    # An UNNAMED place the picture is pinned to (a bare GPS fix from import).
    # Named places are tags and travelled with them.
    for lid in session.execute(
        select(ItemLocation.location_id)
        .where(ItemLocation.item_id == src_item_id)
    ).scalars().all():
        session.add(ItemLocation(item_id=dst_item_id, location_id=lid))

    # The suggestions somebody has already refused. Not copying them would
    # re-offer, on the copy, exactly what was turned down on the original.
    for d in session.execute(
        select(ItemPlaceDismissal)
        .where(ItemPlaceDismissal.item_id == src_item_id)
    ).scalars().all():
        session.add(ItemPlaceDismissal(
            item_id=dst_item_id, location_id=d.location_id,
            via_occasion_id=d.via_occasion_id))
    for d in session.execute(
        select(ItemOccasionDismissal)
        .where(ItemOccasionDismissal.item_id == src_item_id)
    ).scalars().all():
        session.add(ItemOccasionDismissal(
            item_id=dst_item_id, occasion_id=d.occasion_id))

    if links:
        _copy_links(session, src_item_id, dst_item_id)


def _copy_links(session: Session, src_item_id: int, dst_item_id: int) -> None:
    """Give ``dst`` the same relationships ``src`` has, in both directions,
    with their meta tags.

    A link between the two of them is skipped: the copy is already related to
    its source by the edit link the caller writes, and pointing it at itself is
    not a relationship at all.
    """
    from sqlalchemy import or_, select

    rows = session.execute(
        select(Relationship).where(or_(
            Relationship.from_item_id == src_item_id,
            Relationship.to_item_id == src_item_id,
        ))
    ).scalars().all()
    for r in rows:
        other = r.to_item_id if r.from_item_id == src_item_id else r.from_item_id
        if other in (src_item_id, dst_item_id):
            continue
        outgoing = r.from_item_id == src_item_id
        nr = Relationship(
            from_item_id=dst_item_id if outgoing else other,
            to_item_id=other if outgoing else dst_item_id,
            kind=r.kind, meta=r.meta or "",
        )
        session.add(nr)
        session.flush()
        for name in session.execute(
            select(RelationshipTag.name)
            .where(RelationshipTag.relationship_id == r.id)
        ).scalars().all():
            session.add(RelationshipTag(relationship_id=nr.id, name=name))


# (Two listeners lived here until 2026-08 — the ``after_flush`` sidecar sweep
# and the rollback mark-drop — feeding an ``after_commit`` writer that kept a
# per-item ``item.json`` beside every item's files, plus library-wide catalog
# files. SIDECARS ARE GONE WHOLE, by owner decision: they were unused in
# practice and their upkeep was measured at 72 s of catalog builds per 12 s of
# import on a large library. What replaces the restore they enabled is the
# ``merge-library`` CLI command, which reads another LIBRARY's database — a
# strictly higher-fidelity source than the files ever were.)


def _assign_band_keys(obj) -> None:
    ph = obj.phash
    keys = (_dedup_index.band_keys(int(ph, 16)) if ph
            else [None] * _dedup_index.BANDS)
    for name, key in zip(_dedup_index.BAND_COLUMNS, keys):
        setattr(obj, name, key)


def _sweep_flush_for_band_keys(session: Session, _ctx, _instances) -> None:
    """``before_flush``: fill the derived band-key columns (``b0``..``b11``)
    of every File/VideoFrame this flush writes, from its ``phash``.

    A LISTENER, not call-site discipline: `phash` is written at 13 `File(...)`
    construction sites plus two in-place rewrites in `fileops` (a rotation
    applied `in_place` writes new bytes over an existing file and reassigns
    the hash), plus `libimport`'s sidecar restore, and one forgotten site
    would be a file the near-dup probe silently never nominates again.
    ``before_flush`` and not ``after_flush``, because an attribute set in
    ``after_flush`` is not written by the flush that just ran — and because
    only ``before_flush`` sees ``session.new``, which is where almost every
    hash-carrying row is born.

    (This listener's ancestor detected the in-place rewrite to INVALIDATE the
    in-memory near-dup index — an index that went on nominating a rotated
    file by its pre-rotation hash, hidden for months because the thumb LRU
    was stale in exactly the same way and the two cancelled out. The band
    columns cannot go stale that way: they travel in the same flush as the
    hash they derive from, and the thumb LRU is keyed by ``(id, phash)`` now.)
    """
    from sqlalchemy import inspect as sa_inspect

    for obj in session.new:
        if isinstance(obj, (File, VideoFrame)):
            _assign_band_keys(obj)
    for obj in session.dirty:
        # `committed_state` holds the pre-change value of every attribute
        # modified since the last load or commit, so membership is the
        # question — 0.39 us against the 1.48 us of asking for the attribute's
        # history, on a listener that runs for every dirty File of every
        # flush. It answers yes for a set-to-the-same-value too, which costs
        # twelve redundant assignments; over-filling is the safe direction,
        # and under-filling is a silently unfindable file.
        if (isinstance(obj, (File, VideoFrame))
                and "phash" in sa_inspect(obj).committed_state):
            _assign_band_keys(obj)


#: How long a schema upgrade waits for the write lease before refusing —
#: a concurrent writer's unit of work is seconds (that is the lease's whole
#: design), so 30 s means "mid-chunk", not "busy library". Module-level so a
#: test can shrink it instead of waiting half a minute for the refusal.
MIGRATE_WRITE_WAIT = 30.0


def ensure_schema_current(session: Session, doing: str) -> None:
    """Raise :class:`LibraryVersionError` if the library's ``user_version``
    is no longer what THIS build writes.

    For the long-running writers — an import script's chunk loop, a script's
    ``Library`` writes — which check the version once, at open, and then may
    run for an hour: a NEWER build launched meanwhile upgrades the schema
    under them (the migration takes the write lease, so it slots between two
    of their units of work), and an old build that kept writing would insert
    old-shape rows into the new format with no error anywhere — after a rung
    like v10, files whose band columns are NULL and that near-dup matching
    silently never finds again. Called under the caller's own freshly
    acquired write lease, which is what makes it race-free: the ladder
    cannot run between this check and the writes it vouches for.

    One ``PRAGMA user_version`` — microseconds, and reading it is also what
    opens the unit's snapshot, so the check sees exactly the schema the
    writes will.
    """
    got = int(session.connection().exec_driver_sql(
        "PRAGMA user_version").scalar() or 0)
    if got != SCHEMA_VERSION:
        raise LibraryVersionError(
            f"the library was upgraded to format {got} by another process "
            f"while this {doing} was running (this build writes format "
            f"{SCHEMA_VERSION}). Nothing more was written — rerun the "
            f"{doing} with the build that matches the library.")


#: How many `cached()` answers one library keeps. A scope's total is a few
#: bytes; what this bounds is a session that walks a hundred searches.
_MEMO_MAX = 64


def _weak_method(obj: object, name: str):
    """A listener that does NOT keep its ``Database`` alive.

    The per-database Session subclass above is only half the story, and the
    other half is a classic ``WeakKeyDictionary`` trap.
    ``_ClsLevelDispatch._clslevel`` is weak-keyed BY THAT CLASS — but its
    VALUE is the deque of listeners, and a bound method in it reaches the
    ``Database``, which owns the ``sessionmaker``, which owns the class. A
    value that reaches its own key holds that key alive, so the entry is
    immortal and so is everything behind it.

    Registering a closure over a ``weakref`` breaks the chain: nothing
    strongly refers to the ``Database``, so once the library is dropped it
    collects, the class goes with it, and the dispatch entry disappears by
    itself. The listener is a no-op after that — which is exactly right, a
    dead library having nothing to keep in step.
    """
    ref = weakref.ref(obj)

    def listener(*args, **kwargs):
        live = ref()
        if live is not None:
            return getattr(live, name)(*args, **kwargs)

    listener.__name__ = f"weak_{name.lstrip('_')}"
    return listener


def _session_class() -> type[Session]:
    """A Session SUBCLASS PER DATABASE, and it is what keeps a library's
    listeners its own.

    ``event.listen(sessionmaker, ...)`` does NOT attach to the sessionmaker:
    ``SessionEvents._accept_with`` resolves it to ``sessionmaker.class_``,
    so with the plain ``Session`` every ``Database`` registered its five
    bound methods on the GLOBAL class, permanently. Three things followed,
    and only the first is visible in production one library at a time.

    Two libraries open at once — which is exactly what ``merge-library`` and
    the app's own merge do — fired EACH OTHER's listeners: the destination's
    commit poked the source's smart-group sweeper (against a database opened
    ``mode=ro``), ran the source's active-file reindex on the destination's
    session, and bumped the wrong ``commits``, which is what the stats cache
    reads to decide whether anything changed.

    And nothing was ever unregistered, so every ``Database`` ever built was
    pinned by that global deque for the life of the process, with its engine
    and its pool. Measured over ``tests/ui``: 826 live ``Database`` objects
    at the end of a 1353-test run and 3.4 GB of resident memory — times
    eight workers. The work grew with them, too: by the end of the suite one
    commit ran 826 copies of each listener, so the cost of a flush was linear
    in how many libraries the process had ever opened.

    A subclass per instance is the whole fix: the listeners live on a class
    the ``sessionmaker`` alone refers to, so they are this library's and they
    die with it.
    """
    return type("LibrarySession", (Session,), {})


class Database:
    """Owns the engine + session factory for one data directory.

    (JSON sidecars — a per-item ``item.json`` kept in step by flush/commit
    listeners here, with `sidecars`/`sidecar_async` knobs on this
    constructor — are GONE, owner decision 2026-08. The database is the one
    record; `merge-library` is how another library's items come in.)
    """

    def __init__(self, cfg: Config | None = None, *,
                 busy_timeout: float | None = None):
        import os

        self.config = cfg or default_config
        self.config.ensure_dirs()
        self.engine = create_engine(
            f"sqlite:///{self.config.db_path}", future=True
        )
        if busy_timeout is not None:
            # The module-level connect listener sets the 30 s default on every
            # engine; this one is registered on THIS engine and fires after it,
            # so the later pragma wins. Registered before the first connection
            # (the migration below is what opens one), so every connection the
            # pool ever hands out carries the caller's timeout.
            ms = max(0, int(busy_timeout * 1000))

            @event.listens_for(self.engine, "connect")
            def _custom_busy_timeout(dbapi_conn, _record):  # pragma: no cover
                cur = dbapi_conn.cursor()
                cur.execute(f"PRAGMA busy_timeout={ms}")
                cur.close()
        self.Session = sessionmaker(
            bind=self.engine, expire_on_commit=False, class_=_session_class()
        )
        # BEFORE `create_all`, and this is load-bearing three times over. A
        # library this build cannot read must be left exactly as it was found,
        # and `create_all` writes. A step must see the library exactly as the
        # previous build left it — `create_all` invents tables, so a step that
        # renames one aside and recreates it would fail outright and a step
        # that creates one and copies into it would find it already there and
        # empty, i.e. SILENTLY half-applied. And if step 5 of 7 fails, the
        # file must be "version 4, otherwise untouched" rather than version 4
        # plus whatever tables the newer build has invented.
        self._migrate()
        Base.metadata.create_all(self.engine)
        # (Six shape-detecting converters used to run here for libraries from
        # before the format number existed — tag parents into implications,
        # face descriptors into their own table, face names into appearances,
        # a `faces` rebuild, the metadata index onto files, training models
        # out of the settings table. Every library they served predates the
        # first release, and such a library is refused by `_migrate` now, so
        # they went with the pre-release ladder.)
        self._ensure_indexes()
        self._install_tag_sets()
        self._store = None
        # The metadata index is queried state and must track the active file
        # in every library.
        event.listen(self.Session, "before_flush",
                     _weak_method(self, "_reindex_swapped_active_files"))
        # The band-key columns are queried state too (the near-dup probe
        # reads them), and every writer of a hash must fill them or that row
        # is silently unfindable.
        event.listen(self.Session, "before_flush",
                     _sweep_flush_for_band_keys)
        # A tag's REPRESENTATIVE items follow its assignments: the new ones
        # are adopted while the tag is short, the ones that go leave a gap a
        # random pick fills (`representatives.py`). Collected before the
        # flush (where `session.new` and the attribute histories are) and
        # applied after it (where a new row has its id).
        event.listen(self.Session, "before_flush",
                     _weak_method(self, "_collect_representatives"))
        event.listen(self.Session, "after_flush",
                     _weak_method(self, "_apply_representatives"))
        # Smart-group membership depends on nearly everything a commit can
        # touch, so EVERY commit pokes the sweeper — whose no-smart-groups
        # early-out is one indexed SELECT, and whose own session carries a
        # marker that stops the loop. A Database-level hook, so every writer
        # is covered (API, importer, jobs worker, CLI, scripting).
        # Constructed lazily on first poke — `ops` imports `db`, so a
        # module-level import the other way round would be a cycle. The env
        # var makes it SYNCHRONOUS (the suite's determinism knob).
        self._sweep_sync = bool(os.environ.get("MEDIA_COMPOST_SYNC_SWEEPS"))
        self._smart_sweeper = None
        #: How many commits this process has made THAT WROTE ANYTHING — the
        #: cheap half of "has anything changed since I last looked"
        #: (`routers/stats`' cache reads it beside SQLite's own
        #: `data_version`, which answers for every OTHER process). A counter
        #: rather than a timestamp: it is compared for equality, never read
        #: as a clock.
        #:
        #: WROTE ANYTHING is the whole point. Every request commits — the
        #: app commits before responding, whether or not the handler wrote —
        #: so counting commits would move the number on every read and the
        #: cache would never hit. `after_flush` fires only when a session
        #: actually has changes to write, so it is what marks the session.
        self.commits = 0
        #: THE HIGHEST `PRAGMA data_version` ANY CONNECTION HAS REPORTED.
        #: SQLite's counter is per CONNECTION, so a pool answers with two
        #: different numbers after a write and the token would flap — see
        #: `revision`.
        self._data_version = 0
        #: `cached()`'s store and the revision it was filled at.
        self._memo: "OrderedDict[object, object]" = OrderedDict()
        self._memo_rev: tuple = ()
        event.listen(self.Session, "after_flush",
                     _weak_method(self, "_mark_written"))
        event.listen(self.Session, "after_commit",
                     _weak_method(self, "_count_commit"))
        event.listen(self.Session, "after_commit",
                     _weak_method(self, "_poke_smart_sweeper"))

    def _install_tag_sets(self) -> None:
        """Nothing is INSTALLED any more; the name survives for what the hook
        still does at open. The shipped Booru set used to be a locked row in
        every library; it is a TEMPLATE now (`ops/tagsets.templates`), and a
        copy an older build installed is unlocked into an ordinary set of
        the library's (`unlock_builtin_sets`) — same rows, same switch, now
        editable and deletable. A system write at open like the adopters
        above (no Ctx, no event). Lazy import: `ops` imports this module,
        the `smart_sweeper` shape.
        """
        from .ops import tagsets

        with self.Session() as s:
            tagsets.unlock_builtin_sets(s)
            s.commit()

    def _open_fresh(self) -> None:
        """Everything a brand-new library needs: the tables, the number that
        says which shape they are, and the indexes."""
        from . import migrations

        Base.metadata.create_all(self.engine)
        with self.engine.begin() as conn:
            migrations.stamp_user_version(conn, SCHEMA_VERSION)
        self._ensure_indexes()

    def _migrate(self) -> None:
        """Bring the library up to :data:`SCHEMA_VERSION`, or refuse it.

        Refusing is the same as it always was: a library this build cannot
        read is left exactly as it was found, and the message says so. What is
        new is the middle case, where the number is one this build knows how
        to grow out of.
        """
        from . import instance, migrations

        with self.engine.connect() as conn:
            found = migrations.user_version(conn)
            tables = migrations.has_user_tables(conn)

        try:
            plan = migrations.classify(found, has_tables=tables)
        except LibraryVersionError as exc:
            raise LibraryVersionError(f"{self.config.db_path}: {exc}") from None
        if found == 0:
            # A blank the engine just made (anything else at zero was refused
            # above): say what the file is before anything is written to it.
            found = migrations.CURRENT
            with self.engine.begin() as conn:
                migrations.stamp_user_version(conn, found)
        if not plan:
            return

        # A server that is SERVING must not have the schema changed under it:
        # a table rebuild drops and recreates a table mid-request, and
        # `foreign_keys=OFF` is per-connection, so its own connections would
        # go on enforcing keys against a half-rebuilt table. The server's own
        # startup takes its lock BEFORE opening the library, so it never
        # trips this on itself.
        holder = instance.server_is_running(self.config.data_dir)
        if holder:
            raise LibraryMigrationError(
                f"{self.config.db_path} needs upgrading from version {found} "
                f"to {SCHEMA_VERSION}, and a server is running against it "
                f"({holder}). Stop that server and try again. Nothing was "
                f"changed."
            )

        try:
            with instance.library_lock(self.config.data_dir,
                                       instance.MIGRATE_LOCK_NAME):
                # Re-read under the lock. Without this, waiting for another
                # process only serializes the bug: we would then redo the very
                # steps it just finished.
                with self.engine.connect() as conn:
                    found = migrations.user_version(conn)
                plan = migrations.classify(found, has_tables=True)
                if not plan:
                    return
                # THE WRITE LEASE, held for the whole ladder. The server
                # refusal above covers a serving app and `migrate.lock` a
                # second migrator, but a SCRIPT importing in the background
                # holds neither — it leases `write.lock` per chunk. Without
                # this the ladder interleaved with a live writer's chunks,
                # racing them on `busy_timeout` alone; with it the upgrade
                # waits for the chunk in flight (seconds) and then owns the
                # library until the last rung stamps. The writer's own next
                # chunk then re-reads `user_version` under ITS lease
                # (`ensure_schema_current`) and refuses to write old-shape
                # rows into the new format — which is the half that matters,
                # because an old build inserting after a rung like v10 would
                # otherwise produce rows that are silently wrong forever.
                try:
                    instance.acquire_write_lease(
                        self.config.data_dir, timeout=MIGRATE_WRITE_WAIT)
                except instance.LockBusy as exc:
                    raise LibraryMigrationError(
                        f"{self.config.db_path} needs upgrading, and another "
                        f"process is mid-write ({exc.holder or 'unknown'}). "
                        f"Let it finish (or stop it) and try again. Nothing "
                        f"was changed."
                    ) from None
                try:
                    self._run_ladder(found, plan)
                finally:
                    instance.release_write_lease(self.config.data_dir)
        except instance.LockBusy as exc:
            raise LibraryMigrationError(
                f"{self.config.db_path} needs upgrading and another process "
                f"is already doing it ({exc.holder or 'unknown'}). Wait for "
                f"it to finish and try again."
            ) from None
        return

    def _run_ladder(self, found: int, plan) -> None:
        """Back up, then walk the plan, saying what is happening.

        A four-minute upgrade of a large library with no output looks like a
        hang, and the one thing somebody will do to a hang is kill it — which
        is exactly the moment the per-step transactions save them, but they
        should not have to discover that.

        So everything long says so BEFORE it starts and reports how long it
        took after: the copy (the single longest thing here, and the one that
        used to print only once it was already over) and each rung. The
        heading carries the SIZE for the same reason — how long this will take
        is mostly how big the library is, and that number is the only warning
        anybody gets.
        """
        from . import migrations

        mb = self._library_mb()
        total = len(plan)
        print(f"Upgrading the library at {self.config.data_dir} from format "
              f"{found} to {SCHEMA_VERSION} — "
              f"{total} step{'' if total == 1 else 's'}"
              + (f", {mb} MB." if mb else "."), flush=True)
        started = time.time()
        if migrations.skip_backup():
            print(f"  NO BACKUP — {migrations.SKIP_BACKUP_VAR} is set. If this "
                  f"goes wrong the library cannot be put back.", flush=True)
        else:
            # Announced first. `VACUUM INTO` reads and rewrites the whole
            # library, so on anything large this is minutes during which the
            # old code said nothing at all.
            # "this may take a while" is only true when it is: on a 40 MB
            # library the copy is over before the line is read, and a warning
            # that cries wolf on every open is one nobody believes on the
            # open where it matters.
            print(f"  backing up the library first"
                  + (f" — {mb} MB to copy, this may take a while."
                     if mb >= self._SLOW_BACKUP_MB
                     else f" ({mb} MB)." if mb else "."), flush=True)
            began = time.time()
            dest = migrations.backup(self.engine, self.config.db_path,
                                     self.config.backup_dir, found)
            size = dest.stat().st_size // 1_000_000
            print(f"  backup: {dest} ({size} MB) — done in "
                  f"{time.time() - began:.1f} s", flush=True)

        # A rung announces itself with no newline and closes its own line with
        # the time, so a slow one is visibly IN PROGRESS rather than merely
        # the last thing printed. A failure has to close that line itself, or
        # the error runs on from the end of it.
        done = itertools.count(1)
        try:
            migrations.apply(
                self.engine, plan,
                on_step=lambda m: print(
                    f"  {next(done)}/{total}  {m.summary}… ",
                    end="", flush=True),
                on_done=lambda m, secs: print(f"done in {secs:.1f} s",
                                              flush=True))
        except Exception:
            print(flush=True)
            raise
        if not migrations.skip_backup():
            kept = migrations.KEEP_BACKUPS
            extra = len(migrations.list_backups(self.config.backup_dir)) - kept
            migrations.prune_backups(self.config.backup_dir)
            if extra > 0:
                print(f"  removed {extra} older "
                      f"backup{'' if extra == 1 else 's'}, keeping the newest "
                      f"{kept}.", flush=True)
        print(f"Library upgraded to format {SCHEMA_VERSION} in "
              f"{time.time() - started:.1f} s.", flush=True)
        for line in migrations.advice_for(plan):
            print(f"  {line}", flush=True)

    #: Past this, the copy is worth warning about rather than merely stating.
    #: `VACUUM INTO` reads and rewrites every page, so the threshold is about
    #: seconds of disk rather than anything the schema does.
    _SLOW_BACKUP_MB = 200

    def _library_mb(self) -> int:
        """How big the thing being upgraded is, in MB — 0 when it cannot be
        read, which is not worth reporting as an error on a line whose only
        job is to set expectations."""
        try:
            return self.config.db_path.stat().st_size // 1_000_000
        except OSError:
            return 0

    def _reindex_swapped_active_files(self, session: Session, _ctx,
                                      _instances) -> None:
        """``before_flush``: an item's indexed metadata describes its ACTIVE
        file, so refresh it whenever that file is swapped.

        An editor save, an applied AI result, a rotation, a revert or simply
        picking a different source all replace the active file — a dozen places
        across five modules. Hooking the flush rather than each of them is what
        keeps the index honest: otherwise an item edited from WEBP to PNG goes
        on answering ``INFO:mode=RGB`` while its Info panel says RGBA.

        It reads ``file_metadata`` rather than the file on disk now, so it is
        pure SQL — and that is what finally makes it work for VIDEOS, which the
        old disk-reading path skipped outright (`kind == "image"`), leaving
        every film in the library unsearchable by anything it said about itself.

        Only *updates* count. A brand-new item is indexed by whoever created it
        (the importer), so a bulk import never reads its files twice.
        """
        from sqlalchemy import inspect as sa_inspect

        # Items an explicit indexer already queued rows for in this
        # transaction: its values are the fresher ones, so leave them be. This
        # still works unchanged now that the rebuild is what queues them —
        # `rebuild_item_metadata` adds `ItemMetadata` rows to the session, so an
        # item it has already rebuilt is in this set.
        being_indexed = {
            obj.item_id for obj in session.new
            if isinstance(obj, ItemMetadata)
        }
        changed = [
            obj.id for obj in session.dirty
            if isinstance(obj, Item) and obj.id is not None
            and obj.id not in being_indexed
            and sa_inspect(obj).attrs.active_file_id.history.has_changes()
        ]
        if not changed:
            return
        from .itemmeta import rebuild_item_metadata

        # No autoflush: this runs *inside* a flush, and the DELETE clearing an
        # item's old rows would otherwise re-enter it. It is also why the
        # rebuild cannot flush pending `FileMetadata` itself — the writer does.
        with session.no_autoflush:
            for iid in changed:
                rebuild_item_metadata(session, iid)

    # Indexes the hot paths need that older libraries lack. `create_all`
    # never touches an existing table, so these are created idempotently on
    # every open instead. Index-only additions need NO SCHEMA_VERSION bump:
    # the guard exists for changes that make a library READ wrong, and an
    # index changes plans, never meaning — a build without them still reads
    # the same library correctly.
    #: A boolean PARTIAL index is matched SYNTACTICALLY, and that is why
    #: every one of these spells its predicate `IS 1` / `IS 0` rather than
    #: the `WHERE pending` / `WHERE NOT dismissed` they read better as.
    #: SQLite will use a partial index only where a WHERE term matches the
    #: index's own predicate, and the matching is by SPELLING: probed on
    #: 3.53, `flag` reaches `WHERE flag` and `flag IS 1`, `flag = 1` and
    #: `flag IS NOT 0` all reach none of it, each spelling finding only the
    #: index written the same way. SQLAlchemy renders `col.is_(True)` as
    #: `col IS 1` and has no way to emit a bare `col` on SQLite at all
    #: (`~col` comes out `col = 0`), so these four indexes were written in a
    #: spelling nothing here can produce and had never been used once.
    #: Measured on a 200,000-item library with 50,000 pending assignments,
    #: the sidebar's own pending count: 150 ms -> 31 ms.
    #: A PARTIAL INDEX IS MATCHED BY SPELLING, so re-spelling a predicate
    #: means re-NAMING the index too: under the same name `IF NOT EXISTS`
    #: keeps the old one, silently, forever. The `_is1`/`_is0` suffixes are
    #: that rule's marks — SQLAlchemy renders `col.is_(True)` as `col IS 1` —
    #: and a future change to one of these predicates needs a new name and a
    #: `DROP INDEX IF EXISTS` for the old one beside it.
    #: A BOUND PARAMETER matches no partial index either — `name = ?` is a
    #: full scan where `name = 'date_taken'` uses one — so a predicate over
    #: a constant needs that constant rendered inline, which SQLAlchemy does
    #: not do by default.
    #: See `_MEMO_MAX`.
    MEMO_MAX = _MEMO_MAX

    _INDEX_DDL = (
        # Pending review scans (partial: the pending fraction is tiny).
        "CREATE INDEX IF NOT EXISTS ix_item_tags_pending_is1 "
        "ON item_tags (item_id) WHERE pending IS 1",
        "CREATE INDEX IF NOT EXISTS ix_captions_pending_is1 "
        "ON captions (item_id) WHERE pending IS 1",
        # Every caption read is now "this item's captions OF THIS KIND" — the
        # two sidebar lists, the two counts, the search EXISTS and the training
        # split all narrow by it.
        "CREATE INDEX IF NOT EXISTS ix_captions_item_kind "
        "ON captions (item_id, kind)",
        "CREATE INDEX IF NOT EXISTS ix_item_subjects_suggested "
        "ON item_subjects (item_id, face_id) WHERE assigned_by = 'suggested'",
        # Tag probes by tag id (search EXISTS, counts, fan-outs). Covering:
        # (tag_id, negative, item_id) answers them from the index alone.
        "CREATE INDEX IF NOT EXISTS ix_item_tags_tag_neg_item "
        "ON item_tags (tag_id, negative, item_id)",
        "CREATE INDEX IF NOT EXISTS ix_group_tags_tag "
        "ON group_tags (tag_id)",
        # Face partitions.
        "CREATE INDEX IF NOT EXISTS ix_faces_item_live_is0 "
        "ON faces (item_id) WHERE dismissed IS 0",
        # Text-region partitions: the block list (top-level, in reading
        # order) and the live count the search intrinsic reads.
        "CREATE INDEX IF NOT EXISTS ix_text_regions_blocks "
        "ON text_regions (item_id, ord) WHERE parent_id IS NULL",
        "CREATE INDEX IF NOT EXISTS ix_text_regions_live_is0 "
        "ON text_regions (item_id) WHERE dismissed IS 0",
        "CREATE INDEX IF NOT EXISTS ix_faces_dismissed "
        "ON faces (dismissed)",
        "CREATE INDEX IF NOT EXISTS ix_item_subjects_assigned "
        "ON item_subjects (assigned_by)",
        # GPS bounding-box lookups for unnamed-place clustering.
        "CREATE INDEX IF NOT EXISTS ix_locations_gps "
        "ON locations (lat, lon)",
        # Per-entity history lookups (revert origins, item timelines).
        "CREATE INDEX IF NOT EXISTS ix_events_entity "
        "ON events (entity_type, entity_id)",
        # The capture-date sort's correlated subquery, which runs per row of
        # the whole scope. Partial and covering: the one name it ever reads.
        "CREATE INDEX IF NOT EXISTS ix_item_metadata_taken "
        "ON item_metadata (item_id, num_value) WHERE name = 'date_taken'",
        # THE GRID'S SORTS. A page is 60 rows and SQLite was sorting the
        # whole library to find them: the plan read `SEARCH items USING
        # INDEX ix_items_hidden` and then `USE TEMP B-TREE FOR ORDER BY`,
        # 246 ms per page at a million items — every view, every page. Each
        # of these puts the scope's equality (`hidden`) in front of the
        # sort's own key, which is what lets the index BE the order: the
        # temp b-tree disappears and the page costs 0.1 ms.
        #
        # The keys are the SORT EXPRESSIONS, not the columns
        # (`prefilter._sort_exprs`) — `coalesce(last_imported_at,
        # created_at)` and `lower(name)` are what the ORDER BY says, and an
        # index on the bare column cannot answer them (measured: it does
        # not, and the temp b-tree stays). Expression indexes need SQLite
        # 3.9 (2015) and are written as raw DDL here because SQLAlchemy's
        # reflection cannot see one, so `checkfirst` would recreate it on
        # every open.
        #
        # Four of the ten sorts, and the ones that can be indexed at all:
        # colour and resolution sort by a joined FILE column and taken by a
        # correlated subquery, which no index on `items` can order.
        "CREATE INDEX IF NOT EXISTS ix_items_sort_recent "
        "ON items (hidden, coalesce(last_imported_at, created_at))",
        "CREATE INDEX IF NOT EXISTS ix_items_sort_modified "
        "ON items (hidden, updated_at)",
        "CREATE INDEX IF NOT EXISTS ix_items_sort_created "
        "ON items (hidden, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_items_sort_name "
        "ON items (hidden, lower(name))",
        # THE AUTOCOMPLETE'S PREFIX BUCKET. `/api/tags/names` ranks a name
        # that STARTS with what was typed above one that merely contains it,
        # so the first bucket it fills is a RANGE (`lower(name) >= 'hai' AND
        # < 'haj'`) and this is what turns that from a scan of the catalog
        # into a seek: measured on a 200,000-tag catalog, 0.1 ms for a
        # six-letter fragment against 21 ms of scan. It must be a RANGE and
        # not a `LIKE 'hai%'` — SQLite's LIKE optimization wants a plain
        # indexed COLUMN and does not reach an indexed expression, which the
        # query plan says out loud.
        # ONE TAG SET PER SEEK — and NOT BY `kind`. The table holds the
        # library's names and every imported set's, so a seek wants the
        # scope in front of the range key; the scope that is a real value is
        # `tag_set_id` (NULL for the library, which SQLite can seek), and
        # the discriminator is deliberately left OUT of every index.
        #
        # NO INDEX MAY LEAD WITH `kind`. It is the criterion SQLAlchemy
        # adds to every read of `Tag` — including the ON clause of a join
        # from `item_tags`, `subjects`, `tag_implications` — and an index
        # that can answer it makes it look like the cheapest thing in the
        # query to a planner with no `ANALYZE` stats. It then DRIVES from
        # `tags`: measured on a 100,000-tag catalog, the implication join
        # behind `GET /api/tags` went from 3 ms to 4.8 s a chunk and the
        # whole listing from 7 s to 238. With no such index the criterion is
        # what it should be — a per-row check on rows some other table's
        # index already found.
        "CREATE INDEX IF NOT EXISTS ix_tags_set_lname "
        "ON tags (tag_set_id, lname)",
        # …AND THE SAME RANGE INSIDE THE VISIBLE SCOPE, which is the one the
        # autocomplete actually asks. `Tag.hidden` arrived with its own
        # `ix_tags_hidden`, and that index then WON the plan: `hidden IS 0`
        # is an equality and the name range an inequality, and with no
        # `ANALYZE` stats SQLite guesses an equality is the more selective
        # of the two — so the prefix bucket went back to reading every
        # visible tag and evaluating the range per row, which is exactly
        # what `ix_tags_lname` exists to prevent (`test_perf_catalog.py`
        # asserts the PLAN, and that is how it was caught).
        #
        # The scope's equality in FRONT of the range key, the four `items`
        # sort indexes' shape and for the same reason: one index that
        # answers both constraints beats either of the two that answer one.
        # `ix_tags_lname` stays — the chunked `lower(name) IN (…)` probes
        # (`tagsets.in_library`, `_library_names`) say nothing about
        # `hidden` and could not use this one.
        "CREATE INDEX IF NOT EXISTS ix_tags_visible_lname2 "
        "ON tags (hidden, lname)",
        # THE LIBRARY'S NAMES ARE UNIQUE, and this is where that is said: a
        # plain `UNIQUE (tag_set_id, kind, name)` cannot say it, because
        # SQLite counts every NULL as distinct and the library's rows are the
        # ones with a NULL set. Spelled `IS NULL` and named for what it is.
        # PER KIND: a meta tag is its own namespace, so the library can hold
        # the tag `red` and the meta tag `red` and they are two names. The
        # NAME leads — a unique index reads the same either way round, and
        # nothing here may let a seek answer the discriminator alone.
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tags_library_name_kind "
        "ON tags (name, kind) WHERE tag_set_id IS NULL",
        # THE MEDIA-KIND CATEGORIES. Images / Videos / Sequences are an
        # equality on `kind` inside the ordinary `hidden` scope, and without
        # this the view's TOTAL walks every visible item to find them:
        # measured on a 1M-item library, 107 ms for the 20,000 sequences in
        # it. Covering (`id` last), so the count never leaves the index.
        # The PAGE does not need it — the sort indexes above already make a
        # page of 60 an index range whatever the filter — which is why this
        # carries no sort key: it is the count's index, and a count has no
        # order.
        "CREATE INDEX IF NOT EXISTS ix_items_kind ON items (hidden, kind, id)",
    )

    def _ensure_indexes(self) -> None:
        """The hand-written indexes above, plus every index the MODELS declare.

        The second half is what stops a whole class of silent drift.
        `create_all` creates a table's indexes only when it creates the TABLE,
        so an index added to a model whose table already exists is never made
        in any existing library — the column arrives (by a migration step),
        the index does not, and the two libraries then answer the same query
        with different plans and nothing says so. That is exactly what
        happened to `ix_file_artifacts_parent_id`, and it was invisible until
        an upgraded library was compared with a fresh one.

        Doing it here rather than in the step that adds the column is
        deliberate: `checkfirst` makes it idempotent, so declaring an index on
        a model is now all there is to it, and index-only changes go on
        needing no version bump at all.
        """
        import warnings

        from sqlalchemy import exc as sa_exc
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy import text as sa_text

        for ddl in self._INDEX_DDL:
            # ONE TRANSACTION EACH, and a missing table or column is a SKIP —
            # the rule the model-declared half below already keeps, for the
            # same reason: a library an older build (or a test's synthetic
            # one) left without the column would otherwise fail the whole
            # OPEN over an index, which is the failure this method exists to
            # avoid. The message is SQLite's own and this module is SQLite's;
            # anything else is a real error and is raised.
            try:
                with self.engine.begin() as conn:
                    conn.execute(sa_text(ddl))
            except sa_exc.OperationalError as exc:
                if "no such" not in str(getattr(exc, "orig", exc)).lower():
                    raise
        insp = sa_inspect(self.engine)
        for table in Base.metadata.tables.values():
            # Only over columns the table ACTUALLY has: `checkfirst` asks
            # whether the INDEX exists, not whether its column does, and a
            # table an old build (or a test's synthetic library) made without
            # the column would fail the whole open over an index — the exact
            # failure this method exists to avoid.
            have = {c["name"] for c in insp.get_columns(table.name)} \
                if insp.has_table(table.name) else set()
            for index in table.indexes:
                if any(getattr(c, "name", None) not in have
                       for c in index.columns):
                    continue
                # `checkfirst` REFLECTS, and reflection warns once per
                # EXPRESSION index it meets ("Skipped unsupported reflection
                # of expression-based index") — which is every sort index in
                # `_INDEX_DDL`, on every open. Expected, and the reason
                # those are raw DDL in the first place: SQLAlchemy cannot
                # model them, so it cannot check for them either.
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore", message="Skipped unsupported reflection",
                        category=sa_exc.SAWarning)
                    index.create(bind=self.engine, checkfirst=True)

    @property
    def smart_sweeper(self):
        """The smart-group refresher (created on first poke; see
        `ops/smartgroups.SmartGroupSweeper`). Lazy import — `ops` imports
        `db`, so the other direction must wait until runtime."""
        if self._smart_sweeper is None:
            from .smartsweep import SmartGroupSweeper

            self._smart_sweeper = SmartGroupSweeper(
                self, sync=self._sweep_sync)
        return self._smart_sweeper

    @staticmethod
    def _mark_written(session: Session, _ctx) -> None:
        session.info["wrote"] = True

    def _collect_representatives(self, session: Session, _ctx,
                                 _instances) -> None:
        """``before_flush``: which assignments this flush adds, takes away
        or flips — stashed on the session for `_apply_representatives`,
        which runs once the rows are written and have ids."""
        from sqlalchemy import inspect as sa_inspect

        from . import representatives as reps
        added: list = []
        gone: set = set()
        for obj in session.new:
            if isinstance(obj, ItemTag) and reps.is_eligible_row(obj):
                added.append(obj)
        for obj in session.deleted:
            if isinstance(obj, ItemTag) and obj.tag_id is not None:
                gone.add(int(obj.tag_id))
        dropped: list = []
        for obj in session.dirty:
            if not isinstance(obj, ItemTag):
                continue
            attrs = sa_inspect(obj).attrs
            changed = any(attrs[n].history.has_changes()
                          for n in ("negative", "pending"))
            if not changed:
                continue
            if reps.is_eligible_row(obj):
                added.append(obj)
            else:
                dropped.append(obj)
        if added or gone or dropped:
            session.info["_reps_pending"] = (added, gone, dropped)

    def _apply_representatives(self, session: Session, _ctx) -> None:
        """``after_flush``: adopt the new eligible assignments, drop the
        live rows of the ones that stopped being eligible, and settle every
        tag that lost one (a deleted row's representative went with it by
        cascade; the tag is short either way)."""
        pending = session.info.pop("_reps_pending", None)
        if not pending:
            return
        from . import representatives as reps
        added, gone, dropped = pending
        if dropped:
            gone |= reps.drop_live(session, [
                (obj.tag_id, obj.item_id) for obj in dropped
                if obj.tag_id is not None and obj.item_id is not None])
        if added:
            reps.adopt(session, [
                (obj.id, obj.tag_id, obj.item_id) for obj in added
                if obj.id is not None and obj.tag_id is not None
                and obj.item_id is not None])
        if gone:
            reps.settle(session, gone)

    def _count_commit(self, session: Session) -> None:
        if session.info.pop("wrote", False):
            self.commits += 1

    # ---- answers that hold until the library changes ---------------------

    def revision(self, session: Session) -> tuple[int, int]:
        """A token that changes whenever ANYTHING in the library may have.

        Two halves, because there are two ways it can move. `commits` counts
        this process's own WRITING commits — exact, since every write goes
        through a session. `PRAGMA data_version` is SQLite's own answer for
        everybody else: it changes when another CONNECTION commits, which is
        what a CLI import running beside the app is. Both are µs to read.

        Deliberately not a clock: it is compared for equality, never ordered,
        so there is no window in which a stale answer is "recent enough".

        **AND `data_version` IS PER CONNECTION, WHICH IS WHY IT IS KEPT AS A
        HIGH-WATER MARK** (2026-09). SQLite's counter answers "how many times
        has the file been changed by SOMEBODY ELSE", and "somebody else" is
        relative to the connection asking: the connection that did the write
        goes on reporting its old number for ever, while every other
        connection reports the new one. A server hands each request whatever
        connection the pool has free, so after ANY write the token FLAPPED
        between two values from one request to the next — and `cached` drops
        the whole memo whenever the token moves. Every read that is held
        here was therefore recomputed on about half of all requests for the
        rest of the session: a category click in the Tags tab went from
        30 ms to 450, because `set-numbers` alone is 260 ms and it is the
        thing the memo exists for.
        The MAX converges — a stale connection can only read low, never
        high, and another process's commit raises whichever connection sees
        it next — so the token still moves the moment anything changes and
        never moves when nothing has.
        """
        from sqlalchemy import text as sa_text

        ver = int(session.execute(sa_text("PRAGMA data_version")).scalar() or 0)
        if ver > self._data_version:
            self._data_version = ver
        return (self.commits, self._data_version)

    def cached(self, session: Session, key, compute):
        """``compute()``, remembered for as long as the library has not moved.

        For an answer that is EXPENSIVE, ASKED OFTEN and A PURE FUNCTION OF
        THE LIBRARY — the grid's total for a scope (one scan of the items
        table, asked again for every page and every category switch) and the
        rating pool's size (asked once per keypress and constant for the
        session). Not a TTL: the token moves the moment anything changes, so
        the answer is either this library's or it is recomputed.

        The whole memo is dropped on a bump rather than being invalidated
        entry by entry, which is the only honest rule available — what a
        write changes about a COUNT over an arbitrary search is not something
        this layer can know. It is an LRU past `MEMO_MAX` so a session that
        walks many scopes cannot grow it without bound.

        No lock: the worst a race between two request threads can do is
        compute the same answer twice, and both answers are the same.
        """
        rev = self.revision(session)
        if self._memo_rev != rev:
            self._memo.clear()
            self._memo_rev = rev
        if key in self._memo:
            self._memo.move_to_end(key)
            return self._memo[key]
        value = compute()
        self._memo[key] = value
        while len(self._memo) > self.MEMO_MAX:
            self._memo.popitem(last=False)
        return value

    def _poke_smart_sweeper(self, session: Session) -> None:
        """``after_commit``: smart-group membership depends on nearly
        everything a commit can touch, so every commit pokes the sweeper.
        Its no-smart-groups early-out is one indexed SELECT, and its own
        session carries the ``smart_sweep`` marker that stops the loop.
        Never raises — derived state; the next commit retries."""
        if session.info.get("smart_sweep"):
            return
        try:
            self.smart_sweeper.notify()
        except Exception:  # noqa: BLE001 — derived data; next commit retries
            pass

    def session(self) -> Session:
        s = self.Session()
        # THE SESSION KNOWS ITS DATABASE, so an op can reach the
        # revision-keyed memo (`cached`) without every caller threading one
        # through for it. Only the memo wants this — nothing else below the
        # server should be reaching up through a session for the engine.
        s.info["mc_db"] = self
        return s

    @classmethod
    def in_memory(cls) -> "Database":
        """Ephemeral DB for tests."""
        import os

        db = cls.__new__(cls)
        db.config = default_config
        db.engine = create_engine("sqlite:///:memory:", future=True)
        db.Session = sessionmaker(
            bind=db.engine, expire_on_commit=False, class_=_session_class()
        )
        # The same tail a real fresh library gets. It used to be `create_all`
        # alone, which made every in-memory test run against a database
        # missing all of `_INDEX_DDL` — a different database from production,
        # with different query plans, in the tests that most care about them.
        # The ladder is deliberately NOT run: on an empty file the plan is
        # empty by construction, so it could only add a path where a bug in
        # the empty-file detection would fire across every in-memory test.
        db._open_fresh()
        db._install_tag_sets()
        db._store = None
        db._sweep_sync = bool(os.environ.get("MEDIA_COMPOST_SYNC_SWEEPS"))
        db._smart_sweeper = None
        # The same `before_flush` listener the real `__init__` registers
        # unconditionally, so an in-memory test runs the production flush path
        # (an active-file swap re-reads the metadata index). Costless while
        # nothing swaps: the listener builds its `ItemStore` — the one thing
        # that would touch `./_data` — only once a swap actually happens, and a
        # missing file leaves the index untouched.
        event.listen(db.Session, "before_flush",
                     _weak_method(db, "_reindex_swapped_active_files"))
        event.listen(db.Session, "before_flush", _sweep_flush_for_band_keys)
        # …and the WRITE COUNTER with its memo, for the same reason: a
        # revision-scoped answer (`cached`) that never invalidated in tests
        # would be a different database from production in exactly the tests
        # that care whether it invalidates.
        db.commits = 0
        db._data_version = 0
        db._memo = OrderedDict()
        db._memo_rev = ()
        event.listen(db.Session, "after_flush",
                     _weak_method(db, "_mark_written"))
        event.listen(db.Session, "after_commit",
                     _weak_method(db, "_count_commit"))
        event.listen(db.Session, "after_commit",
                     _weak_method(db, "_poke_smart_sweeper"))
        return db

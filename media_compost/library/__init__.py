"""Scripting a Media Compost library from Python.

    from media_compost import open_library

    with open_library("/path/to/library") as lib:
        for item in lib.query("portrait INFO:width>=800").prefetch("tags"):
            print(item.uid, item.path, sorted(item.effective_tags))

Five rules the whole surface follows, so nothing has to be learned twice:

1. **Handles, not snapshots.** Every object wraps one row, reads lazily and
   writes through. A handle held across a commit stays current; one whose row
   was deleted raises rather than answering with what it last saw.
2. **Collections are the standard ABCs.** Set-shaped things are `MutableSet`,
   ordered ones `MutableSequence`, uniquely-named catalogs `Mapping`. Mutating
   the collection IS the write.
3. **What the item SAYS gets the short name; what the library CONCLUDES gets
   the long one.** `item.tags` is direct and editable; `item.effective_tags`
   is read-only.
4. **One call, one commit** — unless you open `with lib.transaction():`.
5. **Derived data is read-only**, and its docstring names the writer.

There is no export format. `item.path` and `file.path` are the answer: the
bytes are on disk, and what a script does with them is its own business.
"""

from __future__ import annotations

import time as _time

from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Union

from sqlalchemy import func, select

from .. import db as _db
from ..config import Config
from ..db import Database
from ..ops import Ctx
from ..ops.errors import OpError
from ..storage import ItemStore
from . import errors as _errors
from ._collections import Catalog, NameMap
from .errors import (
    AmbiguousName, ConflictError, DuplicateName, GroupCycleError, ImportFailed,
    InvalidDate, InvalidLink, InvalidTagName, LibraryError,
    LibraryVersionError, MediaCompostError, MediaUnreadable, NotFound,
    ObjectDeleted, ReadOnlyError, UnsupportedOperation, ValidationError,
)
from .handles import (
    Appearance, Artifact, Box, Caption, Event, Face, File, FileSource, Group,
    Item, ItemTagGroup, Link, MetaTag, Place, Sequence, Subject, Tag,
    TextRegion,
)
from .importing import ImportEntry, ImportResult, ImportRun, ImportStatus
from .coerce import as_group
from .query import ItemSet
from .values import NEVER, GroupedTags, PartialDate, Phash, Rect, TimeRange

__all__ = [
    "open_library", "Library", "NEVER", "PartialDate", "Phash", "Rect",
    "TimeRange", "GroupedTags", "codec_roundtrip", "encoder_available",
    "default_data_dir",
    "ItemSet", "ImportEntry", "ImportResult", "ImportRun", "ImportStatus",
    "Item", "File", "FileSource", "Artifact", "Tag", "MetaTag", "Group",
    "Subject", "Place", "Event", "Face", "Appearance", "Caption", "Link",
    "Sequence", "ItemTagGroup", "Box", "TextRegion",
    "MediaCompostError", "LibraryError", "LibraryVersionError",
    "ReadOnlyError", "NotFound", "ObjectDeleted",
    "AmbiguousName", "ValidationError", "InvalidTagName", "InvalidDate",
    "ConflictError", "DuplicateName", "GroupCycleError", "InvalidLink",
    "ImportFailed", "UnsupportedOperation", "MediaUnreadable",
]


# -- pixels, without the library ---------------------------------------------
#
# The two things a consumer needs from ffmpeg that are not about the library's
# own files. They live here because this package owns ffmpeg discovery — the
# bundled `imageio-ffmpeg` binary, whatever is on PATH, and neither on Windows
# — and a second implementation of that in every consumer is exactly the
# duplication the public API exists to prevent.

def default_data_dir() -> Path:
    """The library a bare `open_library()` would open.

    `MEDIA_COMPOST_DATA` if it is set, else `./_data` — the same rule the app
    and the CLI follow. Exported because a consumer often needs the PATH
    before it opens anything (to name a sibling directory of its own, say),
    and the alternative is re-implementing a two-line rule that then drifts.
    """
    return Config().data_dir


def codec_roundtrip(image, codec: str = "h264", crf: int = 28):
    """A picture through a video encoder and back, as a PIL image.

    What a consumer building deliberately-degraded copies needs: video
    compression artifacts are not something PIL can produce.
    """
    from .. import media
    from .errors import MediaUnreadable

    try:
        return media.codec_roundtrip(image, codec, crf)
    except media.MediaError as exc:
        raise MediaUnreadable(str(exc)) from None


def encoder_available(codec: str) -> bool:
    """Whether this machine's ffmpeg can encode with that codec.

    Takes the same word `codec_roundtrip` does — "h264", "h265" — and not the
    ENCODER behind it. The two are different names for one thing (libx264
    implements h264) and a two-function surface that spoke both tag sets
    would make a caller look the mapping up to ask whether the other function
    would work.
    """
    from .. import media

    return bool(media.has_encoder(media.CODEC_ENCODERS.get(codec, codec)))


def open_library(data_dir: Union[str, Path, None] = None, *, mode: str = "r+",
                 user: str = "", source: str = "cli",
                 busy_timeout: float = 30.0) -> "Library":
    """Open the library at ``data_dir`` (default ``./_data``).

    Reads like `gzip.open` / `shelve.open` / `sqlite3.connect`, and works as a
    context manager::

        with open_library("/path/to/library") as lib:
            ...

    ``mode="r"`` makes every mutator raise `ReadOnlyError` before touching the
    database — the guarantee the old read-only API gave, kept as an option.

    ``user`` is recorded against everything this session changes, so the
    History view can say who did it; without one, scripted changes are
    anonymous. ``source`` is the badge beside them — ``"cli"`` means a local
    process against the library, which is what a script is.
    """
    if mode not in ("r", "r+"):
        raise ValueError(
            f"mode must be 'r' or 'r+', not {mode!r} — a library cannot be "
            "truncated or appended to")
    cfg = Config(data_dir=Path(data_dir).resolve()) if data_dir else Config()
    return Library(cfg, mode=mode, user=user, source=source,
                   busy_timeout=busy_timeout)


class Library:
    """An open library. Build one with :func:`open_library`."""

    def __init__(self, config: Config, *, mode: str = "r+", user: str = "",
                 source: str = "cli", busy_timeout: float = 30.0):
        self.config = config
        self.mode = mode
        self.user = user
        self.source = source
        try:
            self._db = Database(config, busy_timeout=busy_timeout)
        except _db.LibraryVersionError as exc:
            raise LibraryVersionError(str(exc)) from exc
        self._store = ItemStore(config)
        # ONE long-lived session. `expire_on_commit=False` is already the
        # sessionmaker's setting here, which is what lets a handle survive a
        # commit at all; the generation counter below is what keeps it CURRENT.
        self._session = self._db.session()
        self._session.info["username"] = user
        self._generation = 0
        self._depth = 0
        self._eff_cache: dict = {}
        self._resolver_cache = None
        self._busy_timeout = busy_timeout
        self._closed = False

    # -- lifecycle -----------------------------------------------------------

    def __enter__(self) -> "Library":
        return self

    def __exit__(self, *exc) -> None:
        if exc[0] is None:
            self.close()
        else:
            self.rollback()
            self.close()

    def close(self) -> None:
        """Let the database go."""
        if self._closed:
            return
        self._closed = True
        self._session.close()
        self._db.engine.dispose()

    @property
    def path(self) -> Path:
        return self.config.data_dir

    @property
    def readonly(self) -> bool:
        return self.mode == "r"

    @property
    def phash_threshold(self) -> int:
        """How far apart two perceptual hashes may be and still be the same
        picture.

        The importer's own number, exposed so a consumer deduping pictures of
        its own — frames it sampled out of a film, copies it derived — means
        by "the same" exactly what the library means. Read-only: it comes
        from the config rather than the settings table, and a writable
        property would be a lie about where it lives.
        """
        return self.config.phash_threshold

    # -- transactions --------------------------------------------------------

    @contextmanager
    def transaction(self):
        """Group many changes into ONE commit.

        Outside a block every call commits by itself, which is what a one-off
        script wants. Inside one, nothing lands until the block ends — and
        nothing lands at all if it raises. Reentrant: a helper may open one
        without knowing whether its caller did.
        """
        # The write lease travels with the outermost block: this is a unit of
        # committed work by definition, and holding it keeps a concurrent
        # process's importer or jobs worker from interleaving with the batch.
        # Reentrant on both sides, so the depths cannot disagree. Under the
        # fresh lease the schema version is re-checked — a long-running
        # script checks it once at open, and a newer build's migration takes
        # this same lease for its ladder, so between two of the script's
        # units the format can have moved (`db.ensure_schema_current`).
        from ..instance import acquire_write_lease, release_write_lease

        if self._depth == 0:
            acquire_write_lease(self.config.data_dir)
            try:
                _db.ensure_schema_current(self._session, "script")
            except _db.LibraryVersionError as exc:
                release_write_lease(self.config.data_dir)
                raise LibraryVersionError(str(exc)) from None
        self._depth += 1
        try:
            yield self
        except BaseException:
            self._depth -= 1
            if self._depth == 0:
                self.rollback()
                release_write_lease(self.config.data_dir)
            raise
        self._depth -= 1
        if self._depth == 0:
            try:
                self.commit()
            finally:
                release_write_lease(self.config.data_dir)

    def commit(self) -> None:
        self._session.commit()
        self._generation += 1
        self._forget_resolved()

    def rollback(self) -> None:
        self._session.rollback()
        self._generation += 1
        self._forget_resolved()

    # -- resolved tags --------------------------------------------------------

    def _resolver(self):
        """The one effective-tag resolver for the current generation.

        A `Resolver` loads three catalogs — the group ancestor edges, every
        group's tag grants, the whole implication closure — and memoizes them.
        Building one per item therefore loads all three per item, which is
        what `effective_for_item` does and why walking a library asking for
        `item.effective_tags` was one full catalog load per picture. One
        shared instance turns that into one load per generation.
        """
        got = self._resolver_cache
        if got is None:
            from ..resolve import Resolver

            got = self._resolver_cache = Resolver(self._session)
        return got

    def _forget_resolved(self) -> None:
        """Drop everything derived from tags. Called wherever the data under
        it may have moved — a commit, a rollback, and every write, because a
        write inside `transaction()` does NOT commit and would otherwise
        leave both the cache and the resolver's catalogs describing the
        library as it was before it."""
        self._eff_cache.clear()
        self._resolver_cache = None

    def _ctx(self) -> Ctx:
        return Ctx(session=self._session, source=self.source, username=self.user,
                   _store=self._store, _config=self.config)

    def _do(self, fn, *args, **kw):
        """Run one operation under the autocommit-or-batch rule.

        Outside a `transaction()` block the write additionally holds the
        write LEASE for its own commit — the same courtesy the block and the
        importer's chunks extend, so a script's one-line edits queue behind a
        concurrent process's unit of work instead of interleaving with it —
        and a TRANSIENT "database is locked" is retried on a fresh snapshot:
        pysqlite begins transactions deferred, so an op that READ and then
        met another process's commit at its first write is refused
        immediately, `busy_timeout` notwithstanding (the snapshot can never
        become current). The rollback below is exactly the fresh snapshot the
        retry needs, and an op re-run from scratch is an op run once — the
        failed attempt left nothing behind. Inside a block there is no retry:
        the rollback threw the caller's whole batch away, which is not
        something to hide behind a silent replay.
        """
        if self.readonly:
            raise ReadOnlyError(
                'this library was opened with mode="r"; reopen it with '
                '"r+" to change anything')
        from ..instance import acquire_write_lease, release_write_lease

        leased = False
        if self._depth == 0:
            acquire_write_lease(self.config.data_dir)
            leased = True
            # The transaction() rule at the single-call grain: a migration
            # slots in between two autocommitted writes, and an old build
            # must stop rather than write old-shape rows into the new format.
            try:
                _db.ensure_schema_current(self._session, "script")
            except _db.LibraryVersionError as exc:
                release_write_lease(self.config.data_dir)
                raise LibraryVersionError(str(exc)) from None
        try:
            attempts = 4
            for attempt in range(attempts):
                try:
                    out = fn(self._ctx(), *args, **kw)
                except OpError as exc:
                    self._session.rollback()
                    self._generation += 1
                    self._forget_resolved()
                    raise _errors.translate(exc) from None
                except Exception as exc:
                    self._session.rollback()
                    self._generation += 1
                    self._forget_resolved()
                    if (self._depth == 0 and attempt < attempts - 1
                            and _db.is_locked_error(exc)):
                        _time.sleep(0.05 * (2 ** attempt))
                        continue
                    raise
                # BEFORE the commit check, not inside it: inside
                # `transaction()` the commit does not happen, and the write
                # still moved what the cache and the resolver's catalogs
                # describe.
                self._forget_resolved()
                if self._depth == 0:
                    self.commit()
                return out
        finally:
            if leased:
                release_write_lease(self.config.data_dir)

    # -- items ---------------------------------------------------------------

    def query(self, conditions=None, **scope) -> ItemSet:
        """Every non-trashed item matching ``conditions``.

        Takes a query STRING (``"portrait INFO:width>=800"``) — the same one
        the search bar takes — or a raw condition tree, or None for
        everything. The scope
        keywords are the grid's own views: ``groups``, ``ungrouped``,
        ``untagged``, ``trash``, ``hidden``, ``kind``, ``sequence``,
        ``pending``…
        """
        groups = scope.pop("groups", "")
        if not isinstance(groups, str):
            if isinstance(groups, (int, Group)):
                groups = [groups]
            groups = ",".join(str(g._id if isinstance(g, Group) else int(g))
                              for g in groups)
        sequence = scope.pop("sequence", None)
        if isinstance(sequence, Sequence):
            sequence = sequence.id
        sort = scope.pop("sort", "recent")
        prefetch = scope.pop("prefetch", ("files",))
        return ItemSet(self, as_group(conditions),
                       {**scope, "groups": groups, "sequence": sequence},
                       sort, prefetch)

    @property
    def items(self) -> "_Items":
        """Every non-trashed item, plus lookup by uid or id."""
        return _Items(self)

    def file(self, file_id: int) -> File:
        """One stored file by id.

        `item.files` is the way to a file you reached through its item; this
        is for the other direction, where an id is what you were handed —
        a manifest naming the files a run cached latents for, a log line, a
        report. There is no `lib.files` collection because "every file in the
        library" is not a list anybody wants.
        """
        row = self._session.get(_db.File, int(file_id))
        if row is None:
            raise NotFound(f"no file with id {file_id}")
        return File(self, row.id, row)

    @property
    def trash(self) -> ItemSet:
        return self.query(None, trash=True)

    @property
    def hidden(self) -> ItemSet:
        return self.query(None, hidden=True)

    @property
    def pending(self) -> ItemSet:
        """Items with a machine's result waiting to be reviewed."""
        return self.query(None, pending=True)

    def empty_trash(self) -> int:
        from ..ops import items as ops_items

        return self._do(ops_items.empty_trash)

    def prune(self) -> int:
        """Sweep stray files the database no longer references."""
        if self.readonly:
            raise ReadOnlyError('opened with mode="r"')
        return self._store.prune_all(self._session)

    # -- catalogs ------------------------------------------------------------

    @property
    def tags(self) -> "_Tags":
        return _Tags(self)

    @property
    def meta_tags(self) -> NameMap:
        """The namespace shared by links, captions and per-item tag groups."""
        def names() -> list[str]:
            return sorted(self._session.execute(
                select(_db.LinkTag.name)).scalars().all())

        def lookup(name: str):
            row = self._session.execute(select(_db.LinkTag)
                                        .where(_db.LinkTag.name == name)
                                        ).scalars().first()
            return MetaTag(self, row.id, row) if row else None

        cat = NameMap(names, lookup, "meta tag")
        cat.create = lambda name: self._create_meta_tag(name)  # type: ignore
        return cat

    def _create_meta_tag(self, name: str) -> MetaTag:
        from ..ops import links as ops_links

        self._do(ops_links.create_meta_tag, name)
        return self.meta_tags[ops_links.norm_name(name)]

    @property
    def groups(self) -> "_Groups":
        return _Groups(self)

    @property
    def subjects(self) -> Catalog:
        return _catalog(self, _db.Subject, Subject, "subject",
                        lambda r, q: q in (r.display_name or "").lower())

    @property
    def places(self) -> Catalog:
        return _catalog(self, _db.Location, Place, "place", None)

    @property
    def events(self) -> Catalog:
        return _catalog(self, _db.Occasion, Event, "event",
                        lambda r, q: q in (r.display_name or "").lower())

    @property
    def sequences(self) -> Catalog:
        return _catalog(self, _db.Sequence, Sequence, "sequence",
                        lambda r, q: q in (r.name or "").lower())

    # -- creating ------------------------------------------------------------

    def create_subject(self, display_name: str, *, comment: str = "",
                       since=None, tag: str = "") -> Subject:
        from ..ops import subjects as ops_subjects

        got = PartialDate.coerce(since)
        row = self._do(ops_subjects.create, display_name, comment=comment,
                       since_date=None if got is None else int(got), tag=tag)
        return Subject(self, row.id, row)

    def create_place(self, *, tag: str = "", name: str = "",
                     parent=None, lat=None, lon=None) -> Place:
        """A place — `name` is its one line."""
        from ..ops import places as ops_places

        row = self._do(ops_places.create, tag=tag, name=name,
                       lat=lat, lon=lon,
                       parent_id=(getattr(parent, "_id", parent)
                                  if parent is not None else None))
        return Place(self, row.id, row)

    def create_event(self, display_name: str = "", *, tag: str = "",
                     comment: str = "",
                     start=None, end=None,
                     places=None) -> Event:
        from ..ops import events as ops_events

        lo, hi = PartialDate.coerce(start), PartialDate.coerce(end)
        ids = [p._id if isinstance(p, Place) else int(p) for p in (places or [])]
        row = self._do(ops_events.create, tag=tag, display_name=display_name,
                       comment=comment,
                       start_date=None if lo is None else int(lo),
                       end_date=None if hi is None else int(hi), places=ids)
        return Event(self, row.id, row)

    def create_sequence(self, items, *, name: str = "") -> Sequence:
        from ..ops import sequences as ops_sequences
        from .handles import _item_ids

        seq_id, _item_id = self._do(ops_sequences.create, _item_ids(items),
                                    name=name)
        return Sequence(self, seq_id)

    def merge(self, source: Item, target: Item) -> Item:
        """Fold one item into another; the source disappears."""
        from ..ops import items as ops_items

        self._do(ops_items.merge, source.id, target.id)
        return target

    # -- importing -----------------------------------------------------------

    def import_file(self, path, *, move: bool = False, **options):
        """Import ONE local file, and say where it landed.

        ``move=True`` takes the source instead of copying it — including when
        the bytes turn out to be a duplicate, because "move it in" is not
        achieved by leaving the original where it was.

        There is no destination-group argument: the result carries the item,
        so put it where you want it after::

            got = lib.import_file("/inbox/a.jpg", move=True)
            got.item.groups.add(lib.groups["Trips/Japan"])
            got.file.add_url("https://example.com/a.jpg")
        """
        from .importing import import_one

        return import_one(self, path, move=move, **options)

    def import_bytes(self, data: bytes, name: str = "", **options):
        """Import bytes a caller already has — a download, an archive reader.

        They get the identical import a dropped file gets. Record where they
        came from on the RESULT: ``got.file.add_url(url, accessed_at=...)``
        — ``got.file`` is the stored file they landed on, the existing one
        when they turn out to be a duplicate.
        """
        from ..importer import ImportBytes
        from .importing import import_one

        return import_one(self, ImportBytes(data=data, name=name), **options)

    def add_file_urls(self, rows) -> int:
        """Record many web-URL sources in one transaction — the crawl batch.

        ``rows`` is ``(file, url, accessed_at)`` triples (`File` handles or
        ids; ``accessed_at`` a `datetime`, an ISO string, or None), with
        `File.add_url`'s own rules per row: idempotent per (file, url,
        access time), an offset-aware time stored as the UTC moment it
        names. One revertible History entry for the batch; returns how many
        rows were new. The singular `File.add_url` stays the shape for a
        one-off — this is for the loop that would otherwise pay an ops
        round-trip per file.
        """
        from ..ops import files as files_ops

        norm = [(getattr(f, "id", f), url, when) for f, url, when in rows]
        return self._do(files_ops.add_urls_bulk, norm)

    def assign_tags(self, pairs) -> int:
        """Assign many ``(item, tag name)`` pairs in one transaction.

        Items are `Item` handles or ids; names follow the tag-field rules
        (a leading ``-`` is the negative sign) and go through the ordinary
        assignment door — an alias assigns its target, a refused name (a
        minted score tag) is skipped rather than failing the batch. Pairs
        the item already carries are left alone. One revertible History
        entry; returns how many assignments were new. `Item.tags.add` stays
        the shape for a one-off.
        """
        from ..ops import tagassign

        norm = [(getattr(i, "id", i), name) for i, name in pairs]
        return self._do(tagassign.assign_bulk, norm)

    def import_folder(self, path, **options):
        """Import a folder. Returns everything it produced."""
        from .importing import import_one

        return import_one(self, path, **options)

    def import_all(self, sources, **options):
        """Import many sources as ONE run — one commit rhythm, one
        History entry, and upcoming images hashed ahead on worker threads
        (`ImportRun.add_many` is the loop underneath, for callers that
        want the per-source results)."""
        from .importing import import_many

        return import_many(self, sources, **options)

    def importing(self, **options):
        """An import run for sources discovered one at a time:

            with lib.importing() as run:
                for data, url, when, name in downloads():
                    got = run.add(ImportBytes(data=data, name=name))
                    if got.file:
                        got.file.add_url(url, accessed_at=when)

        `ImportRun.add` takes paths too, and `ImportRun.add_many` is the
        fast shape when the sources can be listed up front: it decodes and
        hashes ahead on worker threads and yields the same per-source
        results."""
        from .importing import import_run

        return import_run(self, **options)

    def merge_library(self, folder, *, dry_run: bool = False):
        """Merge every item of another LIBRARY folder into this one — the
        Python spelling of ``media-compost merge-library``. Reads the source's
        own database (which must already be at this build's format) and copies
        file bytes out of its item folders; idempotent per uid."""
        from ..libimport import merge_library as _merge

        if self.readonly:
            raise ReadOnlyError('opened with mode="r"')
        out = _merge(self._session, self._store, self.config, Path(folder),
                     dry_run=dry_run)
        self.commit()
        return out

    # -- the rest ------------------------------------------------------------

    @property
    def history(self):
        from .history import History

        return History(self)

    @property
    def settings(self):
        from .settings import Settings

        return Settings(self)

    @property
    def stats(self) -> dict:
        """How much of everything the library holds."""
        s = self._session
        counts = {}
        for name, model in (("items", _db.Item), ("files", _db.File),
                            ("tags", _db.Tag), ("groups", _db.Group),
                            ("subjects", _db.Subject),
                            ("places", _db.Location),
                            ("events", _db.Occasion), ("faces", _db.Face),
                            ("text_regions", _db.TextRegion),
                            ("captions", _db.Caption),
                            ("sequences", _db.Sequence)):
            counts[name] = int(s.execute(
                select(func.count(model.id))).scalar_one())
        return counts

    @property
    def metadata_names(self) -> list[str]:
        """Every metadata name an `INFO:` condition can use."""
        from ..metadata_catalog import INTRINSIC_NAMES

        # Both halves of what an item answers with: the active file's values
        # and anything pinned to the item. A name that exists in the library
        # only as a pin is still a name `INFO:` can use.
        indexed = self._session.execute(
            select(_db.ItemMetadata.name).distinct()).scalars().all()
        pinned = self._session.execute(
            select(_db.ItemMetaPin.name).distinct()).scalars().all()
        return sorted(set(indexed) | set(pinned) | set(INTRINSIC_NAMES))

    # -- maintenance ---------------------------------------------------------

    def reindex_metadata(self) -> int:
        """Re-read what EVERY FILE of every item says about itself, then
        rebuild each item's index from its active one. Returns how many FILES
        were read (it used to return items).

        THE ONE SURVIVING REPAIR: a library whose files were stored before
        every path that creates a file indexed its metadata has an index for
        the ACTIVE files alone. The four backfill CLI commands are gone by
        policy and none comes back, so this is reachable from a script and
        nowhere else.

        It does NOT clear pins or mutes — those are answers somebody gave about
        which of several files to believe, and no amount of re-reading bytes
        can produce them again.
        """
        from ..db import File
        from ..itemmeta import index_file_metadata, rebuild_item_metadata

        if self.readonly:
            raise ReadOnlyError('opened with mode="r"')
        done = 0
        for item in self.query(None):
            rows = self._session.execute(
                select(File).where(File.item_id == item.id)
            ).scalars().all()
            for f in rows:
                index_file_metadata(self._session, self._store, f)
                done += 1
            rebuild_item_metadata(self._session, item.id)
        self.commit()
        return done

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<Library {str(self.path)!r} mode={self.mode!r}>"


# ---- the catalog wrappers ---------------------------------------------------


def _catalog(lib, model, handle, what, matcher):
    def rows() -> list:
        found = lib._session.execute(select(model).order_by(model.id)
                                     ).scalars().all()
        return [handle(lib, r.id, r) for r in found]

    def get(row_id: int):
        row = lib._session.get(model, row_id)
        return handle(lib, row.id, row) if row else None

    def match(name: str) -> list:
        q = (name or "").lower()
        if not q:
            return rows()
        found = lib._session.execute(select(model)).scalars().all()
        out = []
        for r in found:
            if matcher is not None and matcher(r, q):
                out.append(handle(lib, r.id, r))
            elif r.tag_id if hasattr(r, "tag_id") else None:
                tag = lib._session.get(_db.Tag, r.tag_id)
                if tag and q in tag.name.lower():
                    out.append(handle(lib, r.id, r))
        return out

    def exact(name: str) -> list:
        # `one()`'s tie-breaker: the rows whose display name (or identity
        # tag) IS the query, case aside — not merely contains it.
        q = (name or "").lower()
        out = []
        for r in lib._session.execute(select(model)).scalars().all():
            own = (getattr(r, "display_name", "") or "").lower()
            if own == q:
                out.append(handle(lib, r.id, r))
                continue
            tid = getattr(r, "tag_id", None)
            if tid:
                tag = lib._session.get(_db.Tag, tid)
                if tag and tag.name.lower() == q:
                    out.append(handle(lib, r.id, r))
        return out

    return Catalog(rows, get, match, what, exact=exact)


class _Items:
    """`lib.items` — every item, and lookup by uid or id."""

    __slots__ = ("_lib",)

    def __init__(self, lib):
        self._lib = lib

    def _all(self) -> ItemSet:
        return self._lib.query()

    def __iter__(self):
        return iter(self._all())

    def __len__(self) -> int:
        return len(self._all())

    def __contains__(self, value) -> bool:
        return value in self._all()

    def __getitem__(self, key) -> Item:
        """`lib.items["9f3c…"]` is a uid, `lib.items[42]` an id.

        Type-dispatched because the two key spaces cannot collide — a uid is
        32 hex characters and an id is an integer — so making a caller choose
        `by_uid` for the common case buys nothing.
        """
        row = None
        if isinstance(key, str):
            row = self._lib._session.execute(
                select(_db.Item).where(_db.Item.uid == key)).scalars().first()
        elif isinstance(key, int):
            row = self._lib._session.get(_db.Item, key)
        else:
            raise TypeError("look an item up by uid (str) or id (int)")
        if row is None:
            raise NotFound(f"no item {key!r}")
        return Item(self._lib, row.id, row)

    def get(self, key, default=None):
        try:
            return self[key]
        except NotFound:
            return default

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<{len(self)} items>"


class _Tags(NameMap):
    """`lib.tags` — a Mapping keyed by name, because a tag name IS unique."""

    def __init__(self, lib):
        self._lib = lib
        super().__init__(
            lambda: sorted(lib._session.execute(
                select(_db.Tag.name)).scalars().all()),
            self._lookup, "tag")

    def _lookup(self, name: str):
        row = self._lib._session.execute(
            select(_db.Tag).where(_db.Tag.name == name)).scalars().first()
        return Tag(self._lib, row.id, row) if row else None

    def create(self, name: str, *, comment: str = "",
               alias_of: str = "",
               implies: str = "") -> Tag:
        """A brand-new tag. Raises `DuplicateName` if it exists — a read must
        not write, so `lib.tags[name]` never creates one."""
        from ..ops import tagcatalog

        row, _alias, _implied = self._lib._do(
            tagcatalog.create, name, comment=comment, alias_of=alias_of,
            implies=implies)
        return Tag(self._lib, row.id, row)

    def get_or_create(self, name: str) -> Tag:
        got = self._lookup(name)
        return got if got is not None else self.create(name)

    def with_meta(self, meta: str) -> tuple[Tag, ...]:
        """Every tag the tag set marks with `meta`, by name.

        The question `TAG:character` asks, answered over the catalog: one
        indexed statement, so it stays cheap on a booru-sized tag set.

        `meta_map()` is the same relation read whole and keyed by a
        LOWERCASED name, which is right for matching a name and wrong for
        reaching the tag — `lib.tags[...]` matches exactly, so a mixed-case
        tag cannot be looked up by the key it appears under there. This
        hands back handles, so a caller that means to edit what it finds
        never has to.
        """
        from ..ops import links as ops_links

        rows = self._lib._session.execute(
            select(_db.Tag)
            .join(_db.TagMetaTag, _db.TagMetaTag.tag_id == _db.Tag.id)
            .where(_db.TagMetaTag.name == ops_links.norm_name(meta))
            .order_by(_db.Tag.name)
        ).scalars().all()
        return tuple(Tag(self._lib, r.id, r) for r in rows)

    def meta_map(self) -> dict[str, set[str]]:
        """Every tag that carries meta tags, lowercased: name -> its meta tags.

        ONE statement for the whole catalog, where reading `tag.meta_tags` per
        tag is a query each — which matters because the caller that wants this
        is a training run resolving "every tag marked noflip" over a catalog
        that can hold tens of thousands.
        """
        out: dict[str, set[str]] = {}
        for name, meta in self._lib._session.execute(
            select(_db.Tag.name, _db.TagMetaTag.name)
            .join(_db.TagMetaTag, _db.TagMetaTag.tag_id == _db.Tag.id)
        ).all():
            out.setdefault(name.lower(), set()).add(meta.lower())
        return out

    def __delitem__(self, name: str) -> None:
        self[name].delete()


class _Groups:
    """`lib.groups` — a TREE, so the natural key is a path."""

    __slots__ = ("_lib",)

    def __init__(self, lib):
        self._lib = lib

    def _rows(self) -> list:
        found = self._lib._session.execute(
            select(_db.Group).order_by(_db.Group.name)).scalars().all()
        return [Group(self._lib, g.id, g) for g in found]

    def __iter__(self):
        return iter(self._rows())

    def __len__(self) -> int:
        return len(self._rows())

    def __contains__(self, value) -> bool:
        return value in self._rows()

    @property
    def roots(self) -> tuple[Group, ...]:
        parented = set(self._lib._session.execute(
            select(_db.GroupParent.group_id)).scalars().all())
        return tuple(g for g in self._rows() if g.id not in parented)

    def __getitem__(self, key) -> Group:
        """By id, by bare name, or by path — `lib.groups["Trips/2019/Japan"]`."""
        if isinstance(key, int):
            row = self._lib._session.get(_db.Group, key)
            if row is None:
                raise NotFound(f"no group {key}")
            return Group(self._lib, row.id, row)
        wanted = str(key).strip("/")
        rows = self._rows()
        if "/" in wanted:
            hits = [g for g in rows if g.path == wanted]
        else:
            hits = [g for g in rows if g.name == wanted]
        if not hits:
            raise NotFound(f"no group {key!r}")
        if len(hits) > 1:
            raise AmbiguousName(
                f"{len(hits)} groups are called {key!r} — use a full path, "
                "or an id")
        return hits[0]

    def get(self, key, default=None):
        try:
            return self[key]
        except NotFound:
            return default

    def find(self, name: str = "") -> list[Group]:
        q = name.lower()
        return [g for g in self._rows() if q in g.name.lower()]

    def create(self, name: str, *, parent=None, icon: str = "folder",
               smart_query: "str | None" = None) -> Group:
        """A new group — SMART when ``smart_query`` is a string (the empty
        rule included; such a group holds nothing until the rule is
        written), ordinary when None. Smart is an IDENTITY fixed here: the
        query decides its members (rebuilt immediately and after library
        changes), manual assignment is refused, and it may not hold child
        groups."""
        from ..ops import groups as ops_groups

        pid = None if parent is None else (
            parent._id if isinstance(parent, Group) else self[parent]._id)
        row = self._lib._do(ops_groups.create, name, icon=icon, parent_id=pid,
                            smart_query=smart_query)
        return Group(self._lib, row.id, row)

    def get_or_create(self, path: str, *, icon: str = "folder") -> Group:
        """The group at this PATH, creating whatever part of it is missing.

        A whole chain, because the alternative is making every caller walk it
        by hand — `get_or_create("Trips/2019/Japan")` on an empty library is
        three groups, and on a library that already has "Trips" it is two.

        A name is matched among the CHILDREN of the level above rather than
        library-wide: group names are not unique, so a bare `_rows()` scan
        would adopt an unrelated "Japan" from somewhere else in the tree.
        """
        wanted = [p for p in str(path).strip("/").split("/") if p]
        if not wanted:
            raise ValidationError("a group path cannot be empty")
        parent: Optional[Group] = None
        with self._lib.transaction():
            for name in wanted:
                siblings = (parent.children if parent is not None
                            else self.roots)
                got = next((g for g in siblings if g.name == name), None)
                parent = got if got is not None else self.create(
                    name, parent=parent, icon=icon)
        assert parent is not None
        return parent

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<{len(self)} groups>"

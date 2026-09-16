"""The live objects a script works with.

Each wraps one row and writes through. Nothing here holds a session in a
signature: the library owns that, and every mutator goes through
`Library._do`, which is where the autocommit-or-batch rule lives.

The one distinction worth reading twice is on an item's tags::

    item.tags             what the ITEM says   — editable, direct
    item.effective_tags   what the LIBRARY concludes — read-only

The second is direct plus group-inherited plus implied, which is what search
matches on. Writing to it would mean writing to a group or to an implication,
which are different things in different places, so it is a `frozenset` and
fails with the stdlib's own `AttributeError`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from sqlalchemy import select

from .. import db as _db
from ..ops import (
    artifacts as ops_artifacts, captions as ops_captions, faces as ops_faces,
    files as ops_files, items as ops_items, links as ops_links,
    ocr as ops_ocr, sequences as ops_sequences, subjects as ops_subjects,
    tagassign, tagcatalog,
)
from ..storage import sha256_bytes as _sha256_bytes
from ._base import Handle
from ._collections import HandleList, HandleSet, NameSet
from .errors import AmbiguousName, NotFound, UnsupportedOperation
from .values import (
    NEVER, PartialDate, Rect, TimeRange, stored_to_taken, taken_to_stored,
)


class Tag(Handle):
    """A row in the tag catalog."""

    _model = _db.Tag
    _what = "tag"

    @property
    def name(self) -> str:
        return self._r.name

    @name.setter
    def name(self, value: str) -> None:
        self._write(tagcatalog.update, self._id, name=value)

    @property
    def comment(self) -> str:
        return self._r.comment or ""

    @comment.setter
    def comment(self, value: str) -> None:
        self._write(tagcatalog.update, self._id, comment=value)

    @property
    def meta_tag_counts(self) -> dict[str, int]:
        """Pictures this tag has WHERE EACH META TAG SAYS — `{"tumblr": 50,
        "twitter": 100}`, nonzero entries only. The per-site successor of the
        old tag-level `count_offset` (one number could not say where it came
        from).

        Never added to a count the app displays — a total that silently
        included it would be the app making a claim about somewhere else.
        What it is FOR is ordering: the autocomplete's equal-count ties sort
        by the highest of these. (A training run could once balance against
        it, under the name the tag-level offset left behind; that `freq_base`
        value is gone.)
        """
        return dict(tagcatalog.meta_counts(
            self._lib._session, [self._id]).get(self._id, {}))

    def set_meta_tag_count(self, name: str, count: int) -> None:
        """Set the count on one meta-tag assignment — assigning the meta tag
        first when the tag does not carry it yet. Logged and revertible like
        every other Tags-tab edit."""
        self._write(tagcatalog.add_meta_tag, self._id, name, int(count))

    @property
    def alias_of(self) -> Optional["Tag"]:
        """The tag this one is a second name FOR, if any.

        Assigning an alias redirects to its target, which is why an alias
        implies nothing of its own.
        """
        tid = self._r.alias_of_id
        return Tag(self._lib, tid) if tid else None

    @alias_of.setter
    def alias_of(self, value) -> None:
        name = "" if value is None else (value.name if isinstance(value, Tag)
                                         else str(value))
        self._write(tagcatalog.update, self._id, alias_of=name)

    @property
    def namespace(self) -> str:
        """The text before the first colon — `costume` in `costume:tiger`."""
        from .. import tagname

        return tagname.namespace(self.name)

    @property
    def basename(self) -> str:
        from .. import tagname

        return tagname.basename(self.name)

    @property
    def implies(self) -> NameSet:
        """What assigning this tag also assigns, transitively."""
        return NameSet(
            lambda: set(tagcatalog.implied_names(
                self._lib._session, [self._id]).get(self._id, [])),
            lambda name, **kw: self._write(tagcatalog.add_implication,
                                           self._id, name),
            lambda name: self._write(tagcatalog.remove_implication,
                                     self._id, name),
            "implication",
        )

    @property
    def meta_tags(self) -> NameSet:
        """What the TAG SET says about this tag — "noflip", "character" —
        in the same namespace links, captions and tag groups use.

        It never reaches a picture, so search, counts and training see no new
        tag; what reads it is what asks about the tag itself (`TAG:noflip`,
        and a training run refusing to mirror what carries it).
        """
        return NameSet(
            lambda: set(tagcatalog.meta_names(
                self._lib._session, [self._id]).get(self._id, [])),
            lambda name, **kw: self._write(tagcatalog.add_meta_tag,
                                           self._id, name),
            lambda name: self._write(tagcatalog.remove_meta_tag,
                                     self._id, name),
            "meta tag",
        )

    @property
    def items(self):
        """Every item this tag is effectively on."""
        return self._lib.query(f"{self.name}")

    @property
    def item_count(self) -> int:
        """How many items carry it, folded exactly as a search folds it.

        `len(tag.items)` is the same number for a tag whose name a search
        can be typed for, and this is the one to reach for when it may not
        be: `items` goes through the query grammar, which LOWERCASES what
        it is given, so a tag whose stored name carries a capital is not
        found by it at all — it answers 0 for a tag on a thousand pictures.
        The catalog's own names are case-preserving (an import can carry
        one), so this matches the name as stored.
        """
        from ..prefilter import count_items_with_tag

        return count_items_with_tag(self._lib._session, self.name)

    @property
    def subject(self) -> Optional["Subject"]:
        row = self._lib._session.execute(select(_db.Subject).where(
            _db.Subject.tag_id == self._id)).scalars().first()
        return Subject(self._lib, row.id, row) if row else None

    @property
    def place(self) -> Optional["Place"]:
        row = self._lib._session.execute(select(_db.Location).where(
            _db.Location.tag_id == self._id)).scalars().first()
        return Place(self._lib, row.id, row) if row else None

    @property
    def event(self) -> Optional["Event"]:
        row = self._lib._session.execute(select(_db.Occasion).where(
            _db.Occasion.tag_id == self._id)).scalars().first()
        return Event(self._lib, row.id, row) if row else None

    def merge_into(self, other, *, keep_alias: bool = True) -> "Tag":
        """Fold this tag into another and delete it. The old name lives on as
        an alias, so nothing still saying it goes looking for a tag that no
        longer exists."""
        name = other.name if isinstance(other, Tag) else str(other)
        self._write(tagcatalog.merge, self._id, name, keep_alias=keep_alias)
        return self._lib.tags[name]

    def delete(self) -> None:
        self._write(tagcatalog.delete_tag, self._id)

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<Tag {self.name!r}>"


class MetaTag(Handle):
    """A name in the meta-tag namespace — the labels on links, captions and
    per-item tag groups. A separate namespace from item tags on purpose: these
    describe the annotation, not the picture, and never reach search."""

    _model = _db.LinkTag
    _what = "meta tag"

    @property
    def name(self) -> str:
        return self._r.name

    @name.setter
    def name(self, value: str) -> None:
        self._write(ops_links.update_meta_tag, self.name, new_name=value)

    @property
    def comment(self) -> str:
        return self._r.comment or ""

    @comment.setter
    def comment(self, value: str) -> None:
        self._write(ops_links.update_meta_tag, self.name, comment=value)

    @property
    def description(self) -> str:
        """The long form, with line breaks — what a ? beside the name
        opens. `comment` is the one-liner that rides beside the name."""
        return self._r.description or ""

    @description.setter
    def description(self, value: str) -> None:
        self._write(ops_links.update_meta_tag, self.name, description=value)

    def delete(self) -> None:
        """Remove it from every link, caption and tag group carrying it."""
        self._write(ops_links.delete_meta_tag, self.name)

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<MetaTag {self.name!r}>"


class Group(Handle):
    """A library group. Groups form a TREE — one parent at most."""

    _model = _db.Group
    _what = "group"

    @property
    def name(self) -> str:
        return self._r.name

    @name.setter
    def name(self, value: str) -> None:
        _group_update(self._lib, self._id, name=value)

    @property
    def icon(self) -> str:
        return self._r.icon or ""

    @icon.setter
    def icon(self, value: str) -> None:
        _group_update(self._lib, self._id, icon=value)

    @property
    def color(self) -> str:
        return self._r.color or ""

    @color.setter
    def color(self, value: str) -> None:
        _group_update(self._lib, self._id, color=value)

    @property
    def smart_query(self) -> str:
        """The SMART group's membership rule (the saved-search tag set);
        "" for an ordinary group too, since it has none. Smart is an
        IDENTITY fixed at creation (`groups.create(smart_query=…)`):
        assigning here edits a smart group's rule — refused on an ordinary
        group, and a smart group stays smart whatever the rule says (an
        empty rule holds nothing)."""
        return self._r.smart_query or ""

    @smart_query.setter
    def smart_query(self, value: str) -> None:
        _group_update(self._lib, self._id, smart_query=str(value))

    @property
    def smart(self) -> bool:
        return self._r.smart_query is not None

    @property
    def parent(self) -> Optional["Group"]:
        pid = self._lib._session.execute(select(_db.GroupParent.parent_group_id)
                                         .where(_db.GroupParent.group_id ==
                                                self._id)).scalars().first()
        return Group(self._lib, pid) if pid else None

    @parent.setter
    def parent(self, value) -> None:
        """Assigning MOVES the group. A descendant raises `GroupCycleError`."""
        from ..ops import groups as ops_groups

        target = None if value is None else (
            value._id if isinstance(value, Group) else int(value))
        self._write(ops_groups.move, self._id, target)

    @property
    def path(self) -> str:
        """`Trips/2019/Japan` — the names from the root down."""
        names, node = [], self
        seen = set()
        while node is not None and node._id not in seen:
            seen.add(node._id)
            names.append(node.name)
            node = node.parent
        return "/".join(reversed(names))

    @property
    def children(self) -> tuple["Group", ...]:
        rows = self._lib._session.execute(
            select(_db.GroupParent.group_id)
            .where(_db.GroupParent.parent_group_id == self._id)
        ).scalars().all()
        return tuple(Group(self._lib, g) for g in rows)

    @property
    def descendants(self) -> tuple["Group", ...]:
        from ..resolve import descendant_groups

        ids = descendant_groups(self._lib._session, [self._id]) - {self._id}
        return tuple(Group(self._lib, g) for g in sorted(ids))

    @property
    def items(self):
        """Items directly in this group."""
        return self._lib.query(None, groups=[self._id])

    @property
    def tags(self) -> NameSet:
        """Tags this group GRANTS its items — inherited by the whole subtree.

        The highest-leverage write in the API: one assignment tags everything
        under it, and it is where most of a library's inherited tags come from.
        """
        def read() -> set:
            names = self._lib._session.execute(
                select(_db.Tag.name)
                .join(_db.GroupTag, _db.GroupTag.tag_id == _db.Tag.id)
                .where(_db.GroupTag.group_id == self._id,
                       _db.GroupTag.negative.is_(False))
            ).scalars().all()
            return set(names)

        return NameSet(
            read,
            lambda name, negative=False: self._write(
                tagassign.assign_group_tag, self._id, name, negative=negative),
            lambda name: self._write(tagassign.unassign_group_tag, self._id,
                                     name),
        )

    def add(self, items) -> int:
        """Put items in this group (bulk — one call, one event each)."""
        from ..ops import groups as ops_groups

        ids = _item_ids(items)
        added, _ = self._write(ops_groups.bulk_membership, ids, [self._id], [])
        return added

    def remove(self, items) -> int:
        from ..ops import groups as ops_groups

        ids = _item_ids(items)
        _, removed = self._write(ops_groups.bulk_membership, ids, [],
                                 [self._id])
        return removed

    def duplicate(self, parent=None) -> "Group":
        """A deep copy of this group and its subtree, sharing the items."""
        from ..ops import groups as ops_groups

        pid = None if parent is None else (parent._id
                                           if isinstance(parent, Group)
                                           else int(parent))
        new_id = self._write(ops_groups.duplicate, self._id, pid)
        return Group(self._lib, new_id)

    def delete(self, *, assign_tags: bool = False) -> None:
        """Delete the group. ``assign_tags`` bakes what it granted onto its
        items first, so they keep the tags they were inheriting."""
        from ..ops import groups as ops_groups

        self._write(ops_groups.delete_group, self._id,
                    assign_tags=assign_tags)

    def __str__(self) -> str:
        return self.path

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<Group {self.path!r}>"


def _group_update(lib, group_id: int, **kw) -> None:
    from ..ops import groups as ops_groups

    lib._do(ops_groups.update, group_id, **kw)


def _item_ids(items) -> list[int]:
    """Whatever a caller passed — a handle, an id, or a run of either."""
    if isinstance(items, (int, Handle)):
        items = [items]
    return [i._id if isinstance(i, Handle) else int(i) for i in items]


class FileSource(Handle):
    """Where a stored file's bytes came from: a filename with its import path,
    or a web URL with the time it was fetched."""

    _model = _db.FileName
    _what = "source"

    @property
    def name(self) -> str:
        return self._r.name

    @name.setter
    def name(self, value: str) -> None:
        self._write(ops_files.rename_source, self._r.file_id, self._id, value)

    @property
    def is_url(self) -> bool:
        return bool(self._r.is_url)

    @property
    def accessed_at(self):
        return self._r.accessed_at

    def delete(self) -> None:
        self._write(ops_files.remove_source, self._r.file_id, self._id)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<FileSource {self.name!r}{' (url)' if self.is_url else ''}>"


class Artifact(Handle):
    """Something generated from a file and stored beside it — a depth map, a
    pose overlay, a cached training latent."""

    _model = _db.FileArtifact
    _what = "artifact"

    @property
    def kind(self) -> str:
        return self._r.kind

    @property
    def model(self) -> str:
        return self._r.model or ""

    @property
    def stale(self) -> bool:
        """True when the source file was edited after this was generated."""
        return bool(self._r.stale)

    @property
    def sha256(self) -> str:
        return self._r.sha256 or ""

    @property
    def width(self) -> int:
        return self._r.width or 0

    @property
    def height(self) -> int:
        return self._r.height or 0

    @property
    def bytes(self) -> int:
        return self._r.bytes or 0

    @property
    def format(self) -> str:
        return self._r.format or ""

    @property
    def rel_path(self) -> str:
        """Where this sits inside the item's folder — the name
        `File.artifact_name` produces."""
        return self._r.path or ""

    @property
    def path(self) -> Optional[Path]:
        try:
            return self._lib._store.path_of(self._lib._session, self._r)
        except FileNotFoundError:
            return None

    @property
    def parent(self) -> Optional["Artifact"]:
        """The artifact this one was made FROM, when it was not made from the
        file itself — a latent cached off a degraded copy points at that copy,
        so deleting the copy takes its latents with it."""
        pid = self._r.parent_id
        return None if pid is None else Artifact(self._lib, pid)

    @property
    def file(self) -> "File":
        return File(self._lib, self._r.file_id)

    @property
    def item(self) -> "Item":
        return Item(self._lib, self._r.item_id)

    def delete(self) -> None:
        self._write(ops_artifacts.delete_artifact, self._id)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<Artifact {self.kind}>"


class File(Handle):
    """One version of an item's bytes."""

    _model = _db.File
    _what = "file"

    # -- facts ---------------------------------------------------------------

    @property
    def number(self) -> Optional[int]:
        """The stable per-item source number (#1, #2, …) — what names the file
        on disk."""
        return self._r.number

    @property
    def format(self) -> str:
        return self._r.format or ""

    @property
    def width(self) -> int:
        return self._r.width or 0

    @property
    def height(self) -> int:
        return self._r.height or 0

    @property
    def bytes(self) -> int:
        return self._r.bytes or 0

    @property
    def sha256(self) -> str:
        return self._r.sha256 or ""

    @property
    def phash(self) -> Optional[str]:
        """The perceptual hash dedup compares. None for a video."""
        return self._r.phash

    @property
    def rotation(self) -> int:
        """Which way these bytes sit relative to the item's FIRST source file.

        Provenance, not a transform to apply: the pixels are already turned.
        `width`/`height` are likewise already in this orientation.
        """
        return self._r.rotation or 0

    @property
    def mirrored(self) -> bool:
        return bool(self._r.mirrored)

    @property
    def crop(self) -> Rect:
        """This file's region of the item's reference frame."""
        r = self._r
        return Rect(r.crop_x, r.crop_y, r.crop_w, r.crop_h)

    @property
    def is_derived(self) -> bool:
        return bool(self._r.is_derived)

    @property
    def source_kind(self) -> str:
        """stored | video_frame | video_clip."""
        return self._r.source_kind or "stored"

    @property
    def duration(self) -> Optional[float]:
        return self._r.duration

    @property
    def frame_rate(self) -> Optional[float]:
        """Frames per second, for a video. None when nothing probed it —
        which is a real state, not a zero: no ffprobe on the machine means a
        film imports with no duration and no rate at all."""
        return self._r.frame_rate

    @property
    def created_at(self):
        return self._r.created_at

    @property
    def item(self) -> "Item":
        return Item(self._lib, self._r.item_id)

    @property
    def is_active(self) -> bool:
        return self.item._r.active_file_id == self._id

    # -- the bytes -----------------------------------------------------------

    @property
    def path(self) -> Optional[Path]:
        """Where the bytes are on disk. None when the row has no stored file.

        This is the answer to "there is no export, but let me at the files".
        """
        try:
            got = self._lib._store.path_of(self._lib._session, self._r)
        except FileNotFoundError:
            return None
        return got if got.exists() else None

    def open(self, mode: str = "rb"):
        got = self.path
        if got is None:
            raise NotFound("this file has no stored bytes")
        return got.open(mode)

    def image(self):
        """The pixels as a PIL image.

        The stored bytes are ALREADY in their final orientation — rotating an
        item writes a new file with the turned pixels — so `rotation` is
        provenance (which way these bytes sit relative to the item's first
        source file), not something to apply. Opening the path and rotating by
        it would turn every rotated picture twice.
        """
        from PIL import Image

        got = self.path
        if got is None:
            raise NotFound("this file has no stored bytes")
        return Image.open(got)

    def thumbnail(self, *, ensure: bool = True) -> Optional[Path]:
        store = self._lib._store
        if not ensure:
            got = store.thumb_path(self._id, self.sha256)
            return got if got.exists() else None
        src = self.path
        if src is None:
            return None
        return store.ensure_thumb(self._id, self.sha256, src)

    # -- sources and artifacts ------------------------------------------------

    @property
    def sources(self) -> HandleList:
        """Every recorded source of these bytes."""
        def read() -> list:
            rows = self._lib._session.execute(
                select(_db.FileName).where(_db.FileName.file_id == self._id)
                .order_by(_db.FileName.created_at, _db.FileName.id)
            ).scalars().all()
            return [FileSource(self._lib, r.id, r) for r in rows]

        return HandleList(read, delete=lambda src: src.delete())

    def add_source(self, name: str) -> FileSource:
        """Record a filename this file was seen under."""
        row = self._write(ops_files.add_source, self._id, name=name)
        return FileSource(self._lib, row.id, row)

    def add_url(self, url: str, *, accessed_at=None) -> FileSource:
        """Record a web address these bytes came from, and when.

        THE PROVENANCE CALL for an import:
        [`ImportResult.file`][media_compost.library.importing.ImportResult.file]
        names the stored file a source landed on — the EXISTING one for a
        duplicate, which is the case worth recording (one picture at a second
        address) — so ``got.file.add_url(url, accessed_at=fetched)`` is the
        line after every imported download. Idempotent per (url, access
        time): re-recording
        the same fetch answers the existing row, so a re-crawl needs no
        try/except; the same URL at a DIFFERENT time is a second, genuinely
        different record. An offset-aware time is stored as the UTC moment
        it names.
        """
        stamp = accessed_at.isoformat() if hasattr(accessed_at, "isoformat") \
            else accessed_at
        row = self._write(ops_files.add_source, self._id, url=url,
                          accessed_at=stamp, exist_ok=True)
        return FileSource(self._lib, row.id, row)

    @property
    def artifacts(self) -> HandleList:
        def read() -> list:
            rows = self._lib._session.execute(
                select(_db.FileArtifact)
                .where(_db.FileArtifact.file_id == self._id)
                .order_by(_db.FileArtifact.id)
            ).scalars().all()
            return [Artifact(self._lib, r.id, r) for r in rows]

        return HandleList(read, delete=lambda a: a.delete())

    # -- artifacts as a CACHE -------------------------------------------------
    #
    # `artifacts` above is the view: everything generated from this file, in
    # the order it was made. What follows is the other way of using that table
    # — addressing a rendering by what produced it, so a second run finds the
    # bytes instead of making them again. The name is deterministic, which is
    # the whole mechanism: `artifact_name` is both where the bytes go and how
    # they are found later.

    def artifact_name(self, kind: str, key: str = "", ext: str = "bin") -> str:
        """The item-folder-relative name an artifact of this file WOULD have.

        Creates nothing and touches no disk. `key` is whatever makes one
        rendering different from another — a model, a size, a set of drawn
        parameters — and may be composed out of pieces; it is slugged, so
        which characters survive is not the caller's problem.
        """
        return ops_artifacts.cache_name(self._r.number, kind, key, ext)

    def artifact_path(self, kind: str, key: str = "", ext: str = "bin") -> Path:
        """`artifact_name` as an absolute path — what you hand to a process
        that will write the bytes itself. The folder is created."""
        rel = self.artifact_name(kind, key, ext)
        uid = self.item.uid
        dst = self._lib._store.file_path(uid, rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        return dst

    def find_artifact(self, kind: str, *, model: str = "",
                      name: str = "") -> Optional["Artifact"]:
        """The recorded artifact of this kind (and model, and stored name), or
        None. This is the cache lookup.

        Note it answers about the ROW. A row whose bytes have since been
        pruned still answers, which is why a cache that cares checks
        `artifact.path` too — the two can disagree, and re-encoding is
        cheaper than reading a file that is not there.
        """
        row = ops_artifacts.find(self._lib._ctx(), self._id, kind=kind,
                                 model=model, path=name)
        return None if row is None else Artifact(self._lib, row.id, row)

    def add_artifact(self, kind: str, data: bytes, *, key: str = "",
                     ext: str = "", model: str = "", width: int = 0,
                     height: int = 0,
                     parent: Optional["Artifact"] = None) -> "Artifact":
        """Store `data` at `artifact_name(kind, key, ext)` and record it."""
        rel = self.artifact_name(kind, key, ext or "bin")
        self._lib._store.write_bytes_at(self.item.uid, rel, data)
        row = self._write(
            ops_artifacts.create_one, file_id=self._id, kind=kind, path=rel,
            sha256=_sha256_bytes(data), width=width, height=height,
            bytes=len(data), format=(ext or "bin").lstrip(".").lower(),
            model=model, parent_id=(parent._id if parent is not None else None),
        )
        return Artifact(self._lib, row.id, row)

    def record_artifact(self, kind: str, *, key: str = "", ext: str = "",
                        model: str = "", width: int = 0, height: int = 0,
                        parent: Optional["Artifact"] = None
                        ) -> Optional["Artifact"]:
        """Record bytes ALREADY on disk at `artifact_path(kind, key, ext)`.

        For a file another process wrote — a trainer caching a tensor the
        library could not have produced. Returns None when nothing is there,
        and the existing handle when the row already exists, so running it
        again over a folder adds nothing.
        """
        rel = self.artifact_name(kind, key, ext or "bin")
        got = self.find_artifact(kind, name=rel)
        if got is not None:
            return got
        dst = self._lib._store.file_path(self.item.uid, rel)
        if not dst.is_file():
            return None
        row = self._write(
            ops_artifacts.create_one, file_id=self._id, kind=kind, path=rel,
            width=width, height=height, bytes=dst.stat().st_size,
            format=(ext or "bin").lstrip(".").lower(), model=model,
            parent_id=(parent._id if parent is not None else None),
        )
        return Artifact(self._lib, row.id, row)

    # -- operations ----------------------------------------------------------

    def split_out(self) -> "Item":
        """Move this file into an item of its own, linked back to this one.

        For when the deduper grouped genuinely different pictures as versions
        of each other.
        """
        new_id = self._write(ops_files.split, self._id)
        return Item(self._lib, new_id)

    def delete(self) -> None:
        """Remove this version, its bytes, its artifacts and its thumbnail."""
        self._write(ops_files.delete_file, self._id)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<File #{self.number} {self.format} {self.width}×{self.height}>"


class Caption(Handle):
    """One caption on an item."""

    _model = _db.Caption
    _what = "caption"

    @property
    def text(self) -> str:
        return self._r.text

    @text.setter
    def text(self, value: str) -> None:
        self._write(ops_captions.edit, self._r.item_id, self._id, value)

    @property
    def tags(self) -> NameSet:
        """The caption's META tags — the app's own namespace, which never
        reaches a picture's tags, search or training."""
        item_id = self._r.item_id
        return NameSet(
            lambda: ops_captions.caption_tags(self._lib._session, self._id),
            lambda name: self._write(ops_captions.add_meta_tag, item_id,
                                     self._id, name),
            lambda name: self._write(ops_captions.remove_meta_tag, item_id,
                                     self._id, name))

    @property
    def kind(self) -> str:
        """"caption" (what the picture is) or "instruction" (how it was made
        from the items in `refs`). Fixed when the row is created."""
        return self._r.kind or "caption"

    @property
    def refs(self) -> list:
        """An instruction's source images, IN ORDER. Empty for a caption."""
        ids = ops_captions.caption_refs(self._lib._session, self._id)
        return [Item(self._lib, i) for i in ids]

    @refs.setter
    def refs(self, value) -> None:
        ids = [v._id if isinstance(v, Handle) else int(v) for v in value]
        self._write(ops_captions.set_refs, self._r.item_id, self._id, ids)

    @property
    def pending(self) -> bool:
        """True for a machine-written caption nobody has agreed to yet."""
        return bool(self._r.pending)

    @property
    def model(self) -> str:
        return self._r.model or ""

    @property
    def edited(self) -> bool:
        return bool(self._r.edited)

    @property
    def meta_tags(self) -> NameSet:
        return NameSet(
            lambda: set(ops_captions.caption_tags(self._lib._session,
                                                  self._id)),
            lambda name, **kw: self._write(ops_captions.add_meta_tag,
                                           self._r.item_id, self._id, name),
            lambda name: self._write(ops_captions.remove_meta_tag,
                                     self._r.item_id, self._id, name),
            "meta tag",
        )

    def approve(self) -> None:
        """Agree with a machine's caption as it stands. Editing one approves
        it too; this is the button for when it needed no changing."""
        self._write(ops_captions.approve, self._id)

    def delete(self) -> None:
        self._write(ops_captions.remove, self._r.item_id, self._id)

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<Caption {self.text[:40]!r}>"


def _tag_pair(lib, tag_id, field: str) -> str:
    """A record's `comment`, read off its identity TAG.

    A subject, a place and an event are extra data ON a tag, so what the
    thing is, in a line, has one home. A record with no tag (a face cluster,
    a bare GPS fix) answers "": it is not a named thing yet. (The name is
    from when the pair was two fields; the long form is a tag set's now.)
    """
    if not tag_id:
        return ""
    row = lib._session.get(_db.Tag, tag_id)
    if row is None:
        return ""
    return getattr(row, field, "") or ""


class Subject(Handle):
    """Who or what a picture is OF — extra data on a tag."""

    _model = _db.Subject
    _what = "subject"

    @property
    def display_name(self) -> str:
        return self._r.display_name or ""

    @display_name.setter
    def display_name(self, value: str) -> None:
        self._write(ops_subjects.update, self._id, display_name=value)

    @property
    def comment(self) -> str:
        """What tells two people of one name apart — the identity TAG's."""
        return _tag_pair(self._lib, self._r.tag_id, "comment")

    @comment.setter
    def comment(self, value: str) -> None:
        self._write(ops_subjects.update, self._id, comment=value)

    @property
    def since(self) -> Optional[PartialDate]:
        """When they came into being — a birth date, a release date."""
        v = self._r.since_date
        return PartialDate(v) if v else None

    @since.setter
    def since(self, value) -> None:
        got = PartialDate.coerce(value)
        self._write(ops_subjects.update, self._id,
                    since_date=0 if got is None else int(got))

    @property
    def tag(self) -> Optional[Tag]:
        """The tag this subject IS. None for a face cluster nobody has named."""
        tid = self._r.tag_id
        return Tag(self._lib, tid) if tid else None

    @tag.setter
    def tag(self, value) -> None:
        """Naming an unnamed subject MINTS the tag and back-fills it onto
        every item their faces are already in."""
        name = value.name if isinstance(value, Tag) else str(value)
        self._write(ops_subjects.update, self._id, tag=name)

    @property
    def items(self):
        got = self.tag
        return self._lib.query(got.name) if got else self._lib.query("!(a|!a)")

    @property
    def faces(self) -> tuple["Face", ...]:
        rows = self._lib._session.execute(
            select(_db.ItemSubject.face_id)
            .where(_db.ItemSubject.subject_id == self._id,
                   _db.ItemSubject.face_id.is_not(None))
        ).scalars().all()
        return tuple(Face(self._lib, f) for f in dict.fromkeys(rows))

    def merge_into(self, other, *, keep_alias: bool = True) -> "Subject":
        """Fold this identity into another: the faces move and the tags
        merge."""
        target = other._id if isinstance(other, Subject) else int(other)
        self._write(ops_subjects.merge, self._id, target,
                    keep_alias=keep_alias)
        return Subject(self._lib, target)

    def delete(self, *, with_tag: bool = False) -> None:
        """Delete the identity, keeping its tag — the pictures are still of
        something. ``with_tag`` deletes that too."""
        self._write(ops_subjects.delete_subject, self._id, with_tag=with_tag)

    def __str__(self) -> str:
        return self.display_name or f"subject #{self._id}"

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<Subject {str(self)!r}>"


class Place(Handle):
    """Where a picture was taken — location data on a tag."""

    _model = _db.Location
    _what = "place"

    @property
    def tag(self) -> Optional[Tag]:
        tid = self._r.tag_id
        return Tag(self._lib, tid) if tid else None

    @tag.setter
    def tag(self, value) -> None:
        """Naming an unnamed place (a bare GPS pair off a photo's EXIF) mints
        the tag and moves every item pinned to it onto that tag."""
        from ..ops import places as ops_places

        name = value.name if isinstance(value, Tag) else str(value)
        self._write(ops_places.update, self._id, tag=name)

    @property
    def name(self) -> str:
        """What the place is called, as ONE line — an address, "the corner of
        the old market", "Bob's house". It was eight typed components with a
        per-country form; a place is a line somebody reads."""
        return self._r.name or ""

    @name.setter
    def name(self, value: str) -> None:
        from ..ops import places as ops_places

        self._write(ops_places.update, self._id, name=value)

    @property
    def parent(self) -> Optional["Place"]:
        """The place this one is IN. Assigning it implies the parents — the
        containment is an ordinary tag implication under the hood."""
        pid = self._r.parent_id
        return Place(self._lib, pid) if pid else None

    @parent.setter
    def parent(self, value) -> None:
        from ..ops import places as ops_places

        if value is None:
            self._write(ops_places.update, self._id, clear_parent=True)
        else:
            pid = value._id if isinstance(value, Place) else int(value)
            self._write(ops_places.update, self._id, parent_id=pid)

    @property
    def items(self):
        got = self.tag
        return self._lib.query(got.name) if got else self._lib.query("!(a|!a)")

    def delete(self, *, with_tag: bool = False) -> None:
        from ..ops import places as ops_places

        self._write(ops_places.delete_place, self._id, with_tag=with_tag)

    def __str__(self) -> str:
        got = self.tag
        return got.name if got else (self.name or f"place #{self._id}")

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<Place {str(self)!r}>"


class Event(Handle):
    """What was happening — a span of days on a tag.

    The MODEL is called `Occasion`, because `Event` is the modification log's
    row. The UI, the routes and this API all say "event"; only the ORM
    diverges, and this is where that stops mattering.
    """

    _model = _db.Occasion
    _what = "event"

    @property
    def display_name(self) -> str:
        return self._r.display_name or ""

    @display_name.setter
    def display_name(self, value: str) -> None:
        from ..ops import events as ops_events

        self._write(ops_events.update, self._id, display_name=value)

    @property
    def comment(self) -> str:
        """The identity TAG's, like a subject's and a place's."""
        return _tag_pair(self._lib, self._r.tag_id, "comment")

    @comment.setter
    def comment(self, value: str) -> None:
        from ..ops import events as ops_events

        self._write(ops_events.update, self._id, comment=value)

    @property
    def tag(self) -> Optional[Tag]:
        tid = self._r.tag_id
        return Tag(self._lib, tid) if tid else None

    @property
    def start(self) -> Optional[PartialDate]:
        v = self._r.start_date
        return PartialDate(v) if v else None

    @property
    def end(self) -> Optional[PartialDate]:
        v = self._r.end_date
        return PartialDate(v) if v else None

    def span(self, start=None, end=None) -> None:
        """Set when it was. Either side may be None to leave it alone."""
        from ..ops import events as ops_events

        lo = PartialDate.coerce(start)
        hi = PartialDate.coerce(end)
        self._write(ops_events.update, self._id,
                    start_date=None if lo is None else int(lo),
                    end_date=None if hi is None else int(hi))

    @property
    def places(self) -> HandleSet:
        """Where it was. Every one must be NAMED — a venue is a tag on no item
        at all more often than not, and an unnamed place has no name for
        anything to refer to it by."""
        from ..ops import events as ops_events
        from ..ops.context import Ctx

        def read() -> list:
            ctx = Ctx(session=self._lib._session)
            return [Place(self._lib, pid)
                    for pid in ops_events.place_ids(ctx, self._r)]

        def write(ids: list[int]) -> None:
            from ..ops import events as ev

            self._write(ev.update, self._id, places=ids)

        return HandleSet(
            read,
            lambda p, **kw: write([x._id for x in read()]
                                  + [p._id if isinstance(p, Place) else int(p)]),
            lambda p: write([x._id for x in read()
                             if x._id != (p._id if isinstance(p, Place)
                                          else int(p))]),
            "place",
        )

    @property
    def items(self):
        got = self.tag
        return self._lib.query(got.name) if got else self._lib.query("!(a|!a)")

    def delete(self, *, with_tag: bool = False) -> None:
        from ..ops import events as ops_events

        self._write(ops_events.delete_event, self._id, with_tag=with_tag)

    def __str__(self) -> str:
        got = self.tag
        return self.display_name or (got.name if got else f"event #{self._id}")

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<Event {str(self)!r}>"


class Appearance(Handle):
    """One "this person is in this picture", optionally at one face.

    Several per item is the point: the same character twice on a page, at two
    ages. The AGE is a fact about the picture, not about the name on it.
    """

    _model = _db.ItemSubject
    _what = "appearance"

    @property
    def item(self) -> "Item":
        return Item(self._lib, self._r.item_id)

    @property
    def subject(self) -> Subject:
        return Subject(self._lib, self._r.subject_id)

    @property
    def face(self) -> Optional["Face"]:
        fid = self._r.face_id
        return Face(self._lib, fid) if fid else None

    @property
    def when(self) -> Optional[PartialDate]:
        v = self._r.when_date
        return PartialDate(v) if v else None

    @when.setter
    def when(self, value) -> None:
        got = PartialDate.coerce(value)
        self._write(ops_subjects.edit_appearance, self._id, set_when=True,
                    when_date=None if got is None else int(got),
                    when_age=self._r.when_age)

    @property
    def age(self) -> Optional[int]:
        return self._r.when_age

    @age.setter
    def age(self, value: Optional[int]) -> None:
        self._write(ops_subjects.edit_appearance, self._id, set_when=True,
                    when_date=self._r.when_date, when_age=value)

    @property
    def rect(self) -> Optional[Rect]:
        """The appearance's SUBJECT BOX — the whole figure, where the face is
        only the head. None until somebody draws one."""
        b = self._lib._session.execute(select(_db.ItemSubjectBox).where(
            _db.ItemSubjectBox.item_subject_id == self._id)).scalars().first()
        return Rect(b.x, b.y, b.w, b.h) if b is not None else None

    @rect.setter
    def rect(self, value) -> None:
        if value is None:
            self._write(ops_subjects.set_appearance_box, self._id, clear=True)
            return
        x, y, w, h = value
        self._write(ops_subjects.set_appearance_box, self._id,
                    x=float(x), y=float(y), w=float(w), h=float(h))

    @property
    def points(self) -> Optional[list]:
        """The subject box's optional polygon (`Box.points`' rule: while one
        is set, `rect` is its bounding box)."""
        b = self._lib._session.execute(select(_db.ItemSubjectBox).where(
            _db.ItemSubjectBox.item_subject_id == self._id)).scalars().first()
        return tagassign.points_list(b.points) if b is not None else None

    @points.setter
    def points(self, value) -> None:
        if value is None:
            self._write(ops_subjects.set_appearance_box, self._id, clear=True)
            return
        self._write(ops_subjects.set_appearance_box, self._id,
                    points=value)

    @property
    def guessed(self) -> bool:
        """A machine said this and nobody has agreed yet."""
        return (self._r.assigned_by or "user") == "suggested"

    @property
    def match_score(self) -> Optional[float]:
        return self._r.match_score

    def confirm(self) -> None:
        """Agree with a guess. Its pending tag stops being pending, which is
        what lets search, training and export see it at last."""
        self._write(ops_subjects.edit_appearance, self._id, confirm=True)

    def delete(self) -> None:
        self._write(ops_subjects.remove_appearance, self._id)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<Appearance {self.subject} in #{self._r.item_id}>"


class Face(Handle):
    """A crop a detector found, or a hand drew.

    Evidence, not an edit: it keeps its box, its score and its descriptor
    forever, named or not, and a re-run never loses work.
    """

    _model = _db.Face
    _what = "face"

    @property
    def item(self) -> "Item":
        return Item(self._lib, self._r.item_id)

    @property
    def rect(self) -> Rect:
        r = self._r
        return Rect(r.x, r.y, r.w, r.h)

    @property
    def outline(self) -> Optional[Rect]:
        """The face's optional OUTLINE — the whole figure, drawn by hand,
        where the face box is only the head. A subject attached to the face
        uses it wherever it has no subject box of its own."""
        row = self._lib._session.execute(select(_db.FaceOutline).where(
            _db.FaceOutline.face_id == self._id)).scalars().first()
        return Rect(row.x, row.y, row.w, row.h) if row is not None else None

    @property
    def outline_points(self) -> Optional[list]:
        """The outline's polygon (`Box.points`' rule: `outline` is then its
        bounding box)."""
        row = self._lib._session.execute(select(_db.FaceOutline).where(
            _db.FaceOutline.face_id == self._id)).scalars().first()
        return tagassign.points_list(row.points) if row is not None else None

    @property
    def det_score(self) -> Optional[float]:
        """How sure the detector was. None for a face somebody drew."""
        return self._r.det_score

    @property
    def models(self) -> tuple[str, ...]:
        """Every detector that found this face — one head, one rectangle, so
        several models may agree on it."""
        return tuple(m for m in (self._r.model or "").split(",") if m)

    @property
    def drawn_by_hand(self) -> bool:
        return not self.models

    @property
    def dismissed(self) -> bool:
        return bool(self._r.dismissed)

    @dismissed.setter
    def dismissed(self, value: bool) -> None:
        """Dismissing ABSORBS the next detection over the same box, so the same
        false positive is not offered again — which is why it is the answer for
        a detected face and delete is the answer for a drawn one."""
        self._write(ops_faces.update_face, self._id, dismissed=bool(value))

    @property
    def appearances(self) -> tuple[Appearance, ...]:
        """Every claim on this face — who, how sure, and how old they are in
        it. A face may be several people at once, so this is a tuple."""
        rows = ops_faces.appearances_of(self._lib._session,
                                        [self._id]).get(self._id, [])
        return tuple(Appearance(self._lib, r.id, r) for r in rows)

    @property
    def subjects(self) -> tuple[Subject, ...]:
        """Just the people, which is what the name promises.

        This used to return the `Appearance` rows, so `face.subjects[0]
        .display_name` — the obvious line — raised. `Item` already had the
        pair, and `Face` disagreeing with it was one word doing two jobs.
        """
        return tuple(a.subject for a in self.appearances
                     if a.subject is not None)

    def move(self, x: float, y: float, w: float, h: float) -> None:
        self._write(ops_faces.update_face, self._id, x=x, y=y, w=w, h=h)

    def name(self, who, *, comment: str = "") -> "Face":
        """Say who this is — ADDING a claim, not replacing one.

        A face may be several people at once (a drawn character and the actor
        who plays them), so this appends. `unname` takes one off, and is
        remembered differently: taking off a machine's GUESS records a refusal
        so the next run does not offer it again.
        """
        if isinstance(who, Subject):
            self._write(ops_faces.name_face, self._id, subject_id=who._id)
        else:
            self._write(ops_faces.name_face, self._id, display_name=str(who),
                        comment=comment)
        return self

    def unname(self, who) -> "Face":
        sid = who._id if isinstance(who, Subject) else int(who)
        self._write(ops_faces.unname_face, self._id, sid)
        return self

    def crop(self, *, margin: float = 0.25):
        """The face as a PIL image, cut out of its item's picture."""
        from .. import faces as facelib

        picture = self.item.image()
        if picture is None:
            raise NotFound("this face's item has no stored image")
        box = facelib.crop_box((self._r.x, self._r.y, self._r.w, self._r.h),
                               picture.width, picture.height, margin)
        return picture.crop(box)

    def delete(self) -> None:
        self._write(ops_faces.delete_face, self._id)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        who = ", ".join(str(s) for s in self.subjects) or "unnamed"
        return f"<Face {who}>"


class TextRegion(Handle):
    """A region of text an OCR engine read, or a hand drew.

    Evidence, not an edit, like a :class:`Face` — a re-run refreshes where it
    is and never what a person said it says. Regions form a tree (a block
    holds lines, a line holds words), as deep as the engine actually went.
    """

    _model = _db.TextRegion
    _what = "text region"

    @property
    def item(self) -> "Item":
        return Item(self._lib, self._r.item_id)

    @property
    def parent(self) -> Optional["TextRegion"]:
        pid = self._r.parent_id
        return TextRegion(self._lib, pid) if pid is not None else None

    @property
    def level(self) -> str:
        """"block" | "line" | "word" | "char"."""
        return self._r.level

    @property
    def order(self) -> int:
        """Reading order among siblings — the engine's own."""
        return self._r.ord

    @property
    def rect(self) -> Rect:
        r = self._r
        return Rect(r.x, r.y, r.w, r.h)

    @property
    def quad(self) -> tuple[tuple[float, float], ...]:
        """The engine's own four points for a rotated shape; empty when the
        rectangle IS the shape."""
        from .. import ocr as ocrlib

        return tuple(ocrlib.unpack_quad(self._r.quad))

    @property
    def score(self) -> Optional[float]:
        """The engine's confidence. None when it has none to give (Magi is
        generative) — whether a region is hand-drawn is `models`, not this."""
        return self._r.score

    @property
    def lang(self) -> str:
        return self._r.lang or ""

    @property
    def models(self) -> tuple[str, ...]:
        """Every engine that read this region — empty for one drawn by hand."""
        return tuple(m for m in (self._r.model or "").split(",") if m)

    @property
    def drawn_by_hand(self) -> bool:
        return not self.models

    @property
    def edited(self) -> bool:
        """Whether a person corrected the text. After that, no run rewrites
        it — set by assigning `text`, never directly."""
        return bool(self._r.edited)

    @property
    def text(self) -> str:
        return self._r.text or ""

    @text.setter
    def text(self, value: str) -> None:
        """Correct the transcription. The point of this API here: fixing a
        misreading across a chapter should be one line in a script."""
        self._write(ops_ocr.update_region, self._id, text=str(value))

    @property
    def dismissed(self) -> bool:
        return bool(self._r.dismissed)

    @dismissed.setter
    def dismissed(self, value: bool) -> None:
        """"Not text". Dismissing ABSORBS the next detection over the same
        box, so the same false positive is not offered again — the answer for
        a detected region, where delete is the answer for a drawn one."""
        self._write(ops_ocr.update_region, self._id, dismissed=bool(value))

    @property
    def children(self) -> HandleList:
        """The finer regions inside this one (a block's lines, a line's
        words), in reading order."""
        def read() -> list:
            rows = ops_ocr.children_of(self._lib._session,
                                       [self._id]).get(self._id, [])
            return [TextRegion(self._lib, r.id, r) for r in rows]

        return HandleList(read, delete=lambda r: r.delete())

    def move(self, x: float, y: float, w: float, h: float) -> None:
        self._write(ops_ocr.update_region, self._id, x=x, y=y, w=w, h=h)

    def crop(self, *, margin: float = 0.05):
        """The region as a PIL image, cut out of its item's picture. The
        default margin is text's own — glyphs unshaved, not head and
        shoulders."""
        from .. import ocr as ocrlib

        picture = self.item.image()
        if picture is None:
            raise NotFound("this text region's item has no stored image")
        box = ocrlib.crop_box((self._r.x, self._r.y, self._r.w, self._r.h),
                              picture.width, picture.height, margin)
        return picture.crop(box)

    def delete(self) -> None:
        """Remove the region and everything under it. Prefer dismissing a
        detected false positive — a deleted one comes back on the next run."""
        self._write(ops_ocr.delete_region, self._id)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        text = self.text
        if len(text) > 40:
            text = text[:37] + "…"
        return f"<TextRegion {self.level} {text!r}>"


class Link(Handle):
    """A directed edge between two items — an edit to what it came from, a
    panel to its page, a still to its film."""

    _model = _db.Relationship
    _what = "link"

    __slots__ = ("_outgoing",)

    def __init__(self, lib, row_id: int, row=None, *, outgoing: bool = True):
        super().__init__(lib, row_id, row)
        self._outgoing = outgoing

    @property
    def kind(self) -> str:
        return self._r.kind

    @property
    def outgoing(self) -> bool:
        return self._outgoing

    @property
    def other(self) -> "Item":
        r = self._r
        return Item(self._lib, r.to_item_id if self._outgoing
                    else r.from_item_id)

    @property
    def meta(self) -> dict:
        import json

        try:
            return json.loads(self._r.meta) if self._r.meta else {}
        except ValueError:
            return {}

    @property
    def meta_tags(self) -> NameSet:
        return NameSet(
            lambda: set(ops_links.tags_by_rel(self._lib._session,
                                              [self._id]).get(self._id, [])),
            lambda name, **kw: self._write(ops_links.add_meta_tag, self._id,
                                           name),
            lambda name: self._write(ops_links.remove_meta_tag, self._id,
                                     name),
            "meta tag",
        )

    def flip(self) -> "Link":
        """Reverse which end is the original. For an `edit` link this re-roots
        the whole cluster, so "one original per item" stays true."""
        self._write(ops_links.flip, self._id)
        return self

    def delete(self) -> None:
        self._write(ops_links.remove, self._id)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        arrow = "→" if self._outgoing else "←"
        return f"<Link {arrow} #{self.other.id} ({self.kind})>"


class Sequence(Handle):
    """An ordered run of items — a chapter, a film's frames, a set."""

    _model = _db.Sequence
    _what = "sequence"

    @property
    def name(self) -> str:
        return self._r.name or ""

    @name.setter
    def name(self, value: str) -> None:
        self._write(ops_sequences.rename, self._id, value)

    @property
    def kind(self) -> str:
        """How it came to be: archive | pdf | gif | manual (an older library
        may hold `video`, from a removed import option). Provenance only —
        all sequences behave alike, but a re-import recognises its own by
        it."""
        return self._r.kind or "manual"

    @property
    def item(self) -> Optional["Item"]:
        """The CONTAINER item, so a sequence can be selected and tagged like
        anything else in the grid."""
        iid = self._r.item_id
        return Item(self._lib, iid) if iid else None

    @property
    def members(self) -> HandleList:
        """The items, one entry per POSITION — a book's repeated blank page
        is one item listed at each of its positions. This list speaks in
        ITEMS: deleting one removes every occurrence, and `reorder` refuses
        a sequence that repeats an item (a list of items cannot say which
        copy goes where — the app's own reorder addresses membership rows).
        """
        def read() -> list:
            rows = self._lib._session.execute(
                select(_db.SequenceItem.item_id)
                .where(_db.SequenceItem.sequence_id == self._id)
                .order_by(_db.SequenceItem.position, _db.SequenceItem.id)
            ).scalars().all()
            return [Item(self._lib, i) for i in rows]

        return HandleList(
            read,
            delete=lambda it: self._write(ops_sequences.remove_members,
                                          self._id, [it._id]),
            reorder=lambda order: self._write(
                ops_sequences.reorder, self._id, _item_ids(order)),
        )

    def remove(self, items) -> int:
        """Take items out — EVERY occurrence of each; that is what "remove
        this picture from the chapter" means."""
        return self._write(ops_sequences.remove_members, self._id,
                           _item_ids(items))

    def delete(self) -> None:
        """Remove the sequence and its container, keeping the members."""
        self._write(ops_sequences.remove, self._id)

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<Sequence {self.name!r} ({len(self.members)})>"


class TagSet(NameSet):
    """An item's DIRECT positive tags, with `.negative` beside it.

    `item.effective_tags` is the other half — direct plus group-inherited plus
    implied, which is what search matches on — and it is read-only, because
    writing to it would mean writing to a group or to an implication.
    """

    __slots__ = ("_item",)

    def __init__(self, item: "Item", negative: bool = False):
        self._item = item
        super().__init__(
            lambda: item._direct(negative),
            # The set's own sign is the DEFAULT, not an override: this same
            # closure serves `item.tags` and `item.tags.negative`, so passing
            # it positionally made the documented `add(name, negative=True)`
            # raise "got multiple values for keyword argument 'negative'".
            lambda name, **kw: item._assign(
                name, **{"negative": negative, **kw}),
            lambda name: item._unassign(name),
        )

    @property
    def negative(self) -> "TagSet":
        """The tags this item is marked as NOT having."""
        return TagSet(self._item, negative=True)

    def __getitem__(self, name: str) -> "TagOnItem":
        if name not in self._item._direct(False) \
                and name not in self._item._direct(True):
            raise NotFound(f"{name!r} is not on this item")
        return TagOnItem(self._item, name)

    def explain(self, name: str) -> "TagOrigin":
        """Why does this picture have that tag?

        The question a script actually asks, answered in one lookup instead of
        a walk: assigned directly, granted by which groups, implied by which
        tags, and whether a direct assignment overrides the rest.
        """
        return self._origin(self._item._effective(), name)

    def explain_all(self) -> dict:
        """`explain()` for every tag on this picture, in one resolve.

        The same answers `explain` gives, keyed by name — for a caller
        deciding something about ALL of an item's tags (which of them a rule
        drops, which were only implied by tags it dropped). Asking name by
        name is a resolve apiece, which over a library is the difference
        between a pass and an afternoon.

        Covers the effective set plus anything directly assigned, so a tag a
        negative override has taken out of `effective` still has an entry
        saying so.
        """
        eff = self._item._effective()
        names = set(eff.positive) | set(eff.direct_positive) \
            | set(eff.direct_negative)
        return {name: self._origin(eff, name) for name in sorted(names)}

    def _origin(self, eff, name: str) -> "TagOrigin":
        by_group = {gid: names for gid, names in eff.indirect_by_group.items()
                    if name in names}
        return TagOrigin(
            name=name,
            direct=name in eff.direct_positive,
            negative=name in eff.direct_negative,
            from_groups=tuple(Group(self._item._lib, g) for g in by_group),
            implied_by=tuple(sorted(eff.parent_sources.get(name, ()))),
            effective=name in eff.positive,
        )


class TagOrigin:
    """Where one tag on one item came from."""

    __slots__ = ("name", "direct", "negative", "from_groups", "implied_by",
                 "effective")

    def __init__(self, *, name, direct, negative, from_groups, implied_by,
                 effective):
        self.name = name
        self.direct = direct
        self.negative = negative
        self.from_groups = from_groups
        self.implied_by = implied_by
        self.effective = effective

    def __repr__(self) -> str:  # pragma: no cover - trivial
        bits = []
        if self.direct:
            bits.append("direct")
        if self.negative:
            bits.append("negative")
        if self.from_groups:
            bits.append(f"from {len(self.from_groups)} group(s)")
        if self.implied_by:
            bits.append(f"implied by {', '.join(self.implied_by)}")
        return f"<TagOrigin {self.name!r}: {', '.join(bits) or 'absent'}>"


class TagOnItem:
    """One tag as it sits on one item — its sign, and its boxes."""

    __slots__ = ("_item", "_name")

    def __init__(self, item: "Item", name: str):
        self._item = item
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def negative(self) -> bool:
        return self._name in self._item._direct(True)

    @negative.setter
    def negative(self, value: bool) -> None:
        self._item._assign(self._name, negative=bool(value))

    @property
    def boxes(self) -> "BoxList":
        return BoxList(self._item, self._name)

    @property
    def pending(self) -> bool:
        """True while a machine suggested this and nobody has agreed yet.

        Search, training and export leave a pending tag alone, so this is what
        a review script reads — `lib.pending` is the same question asked of the
        whole library.
        """
        row = self._itemtag()
        return bool(row is not None and row.pending)

    @pending.setter
    def pending(self, value: bool) -> None:
        self._item._write(tagassign.set_pending, self._item._id, self._name,
                          bool(value))

    def _itemtag(self):
        s = self._item._lib._session
        tag = s.execute(select(_db.Tag)
                        .where(_db.Tag.name == self._name)).scalars().first()
        if tag is None:
            return None
        return s.execute(select(_db.ItemTag).where(
            _db.ItemTag.item_id == self._item._id,
            _db.ItemTag.tag_id == tag.id)).scalars().first()

    def delete(self) -> None:
        self._item._unassign(self._name)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<TagOnItem {self._name!r}{' −' if self.negative else ''}>"


class Box(Handle):
    """A rectangle, a time range, or both, hanging off a tag on an item."""

    _model = _db.ItemTagBox
    _what = "box"

    @property
    def rect(self) -> Optional[Rect]:
        r = self._r
        if r.x is None:
            return None
        return Rect(r.x, r.y, r.w, r.h)

    @property
    def points(self) -> Optional[list]:
        """The box's optional POLYGON — [[x, y], ...] vertices in the item's
        reference frame. While one is set, `rect` is its bounding box (the
        server keeps the two in step). None for a plain rectangle."""
        return tagassign.points_list(self._r.points)

    @points.setter
    def points(self, value) -> None:
        if value is None:
            self._write(tagassign.update_box, self._id, clear_points=True)
        else:
            self._write(tagassign.update_box, self._id, points=value)

    @property
    def time(self) -> Optional[TimeRange]:
        r = self._r
        if r.time_start is None:
            return None
        return TimeRange(r.time_start, r.time_end)

    @property
    def track_id(self) -> Optional[int]:
        return self._r.track_id

    @property
    def negative(self) -> bool:
        """A TIME RANGE carries its own sign: over a film a tag is present in
        some stretches and pointedly absent in others."""
        return bool(self._r.negative)

    def move(self, x: float, y: float, w: float, h: float) -> None:
        self._write(tagassign.update_box, self._id, x=x, y=y, w=w, h=h)

    def retag(self, name: str) -> None:
        self._write(tagassign.update_box, self._id, tag=name)

    def delete(self) -> None:
        self._write(tagassign.delete_box, self._id)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<Box {self.rect or self.time}>"


class BoxList(HandleList):
    """The boxes of one tag on one item."""

    __slots__ = ("_item", "_name")

    def __init__(self, item: "Item", name: str):
        self._item = item
        self._name = name
        # NOT `_read` — that is `HandleList`'s slot, and a method of the same
        # name on the subclass shadows the slot descriptor, so assigning to it
        # raises "attribute '_read' is read-only" from inside super().__init__.
        super().__init__(self._rows, delete=lambda b: b.delete())

    def _rows(self) -> list:
        lib = self._item._lib
        rows = lib._session.execute(
            select(_db.ItemTagBox)
            .join(_db.ItemTagPlacement,
                  _db.ItemTagPlacement.id == _db.ItemTagBox.placement_id)
            .join(_db.ItemTag, _db.ItemTag.id == _db.ItemTagPlacement.item_tag_id)
            .join(_db.Tag, _db.Tag.id == _db.ItemTag.tag_id)
            .where(_db.ItemTag.item_id == self._item._id,
                   _db.Tag.name == self._name)
            .order_by(_db.ItemTagBox.id)
        ).scalars().all()
        return [Box(lib, r.id, r) for r in rows]

    def add(self, x=None, y=None, w=None, h=None, *, file=None, time=None,
            track=None, negative: bool = False, group=None,
            points=None) -> Box:
        """Add a box, a time range, or both.

        Geometry is in the item's REFERENCE frame unless you pass the `file`
        it was drawn on, in which case it is mapped through that file's crop.
        ``points`` draws a POLYGON instead — [[x, y], ...] vertices in the
        same frame; the rectangle becomes its bounding box.
        """
        start = end = None
        if time is not None:
            start, end = (time if isinstance(time, (tuple, list))
                          else (time, None))
        row = self._item._lib._do(
            tagassign.add_box, self._item._id, self._name,
            x=x, y=y, w=w, h=h, time_start=start, time_end=end,
            track_id=track, negative=negative,
            file_id=(file._id if isinstance(file, File) else file),
            group_id=(group._id if isinstance(group, ItemTagGroup) else group),
            points=points,
        )
        return Box(self._item._lib, row.id, row)


class ItemTagGroup(Handle):
    """A per-item grouping of tags — "hers", "his", or the auto-managed
    Pending group a generation run files its guesses into."""

    _model = _db.ItemTagGroup
    _what = "tag group"

    @property
    def name(self) -> str:
        return self._r.name

    @name.setter
    def name(self, value: str) -> None:
        self._write(tagassign.rename_group, self._id, value)

    @property
    def system(self) -> bool:
        """True for the auto-managed Pending group. It takes no drops."""
        return bool(self._r.system)

    @property
    def tags(self) -> NameSet:
        def read() -> set:
            names = self._lib._session.execute(
                select(_db.Tag.name)
                .join(_db.ItemTag, _db.ItemTag.tag_id == _db.Tag.id)
                .join(_db.ItemTagPlacement,
                      _db.ItemTagPlacement.item_tag_id == _db.ItemTag.id)
                .where(_db.ItemTagPlacement.group_id == self._id)
            ).scalars().all()
            return set(names)

        return NameSet(
            read,
            lambda name, **kw: self._write(tagassign.place_tag,
                                           self._r.item_id, name,
                                           group_id=self._id, **kw),
            lambda name: self._write(tagassign.move_instance, self._r.item_id,
                                     name, from_group_id=self._id,
                                     to_group_id=None),
        )

    @property
    def meta_tags(self) -> NameSet:
        """Labels on the GROUPING itself. They never become tags of the item —
        that separation is the whole point of them."""
        from ..ops.context import Ctx

        return NameSet(
            lambda: set(tagassign.group_meta_tags(
                Ctx(session=self._lib._session), self._id)),
            lambda name, **kw: self._write(tagassign.add_group_meta_tag,
                                           self._id, name),
            lambda name: self._write(tagassign.remove_group_meta_tag,
                                     self._id, name),
            "meta tag",
        )

    @property
    def subjects(self) -> HandleSet:
        """Who this grouping is ABOUT — purely organizational, like the meta
        tags: search never learns "her hair is blonde"."""
        from ..ops.context import Ctx

        return HandleSet(
            lambda: [Subject(self._lib, sid) for sid in
                     tagassign.group_subjects(Ctx(session=self._lib._session),
                                              self._id)],
            lambda who, **kw: self._write(
                tagassign.add_group_subject, self._id,
                who._id if isinstance(who, Subject) else int(who)),
            lambda who: self._write(
                tagassign.remove_group_subject, self._id,
                who._id if isinstance(who, Subject) else int(who)),
            "subject",
        )

    def delete(self) -> None:
        """Delete the grouping; its tags fall back to Ungrouped."""
        self._write(tagassign.delete_group, self._id)

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<ItemTagGroup {self.name!r}>"


class Item(Handle):
    """One picture, video or sequence container — everything else hangs off it."""

    _model = _db.Item
    _what = "item"

    # -- what it is ----------------------------------------------------------

    @property
    def uid(self) -> str:
        """The stable identity that names the item's folder on disk and every
        cross-item reference in an export or a merge. Survives export and
        re-import."""
        return self._r.uid

    @property
    def name(self) -> str:
        return self._r.name

    @name.setter
    def name(self, value: str) -> None:
        self._write(ops_items.update, self._id, name=value)

    @property
    def kind(self) -> str:
        """image | video | sequence."""
        return self._r.kind

    @property
    def created_at(self):
        """First time it was seen in the library."""
        return self._r.created_at

    @property
    def last_imported_at(self):
        return self._r.last_imported_at

    @property
    def updated_at(self):
        return self._r.updated_at

    @property
    def hidden(self) -> bool:
        return bool(self._r.hidden)

    @hidden.setter
    def hidden(self, value: bool) -> None:
        self._write(ops_items.hide, [self._id], bool(value))

    @property
    def trashed(self) -> bool:
        return self._lib._session.execute(
            select(_db.TrashedItem.id)
            .where(_db.TrashedItem.item_id == self._id)).first() is not None

    # -- when it was taken ---------------------------------------------------

    @property
    def taken(self):
        """When the picture was taken, as SOMEBODY SAID it — the override.

        Three states, which is why `NEVER` exists: `None` means nobody has
        said (read the file, then the events it carries), a date means
        somebody typed one, and `NEVER` means somebody looked and there is
        none. Without the third a wrong EXIF date could be replaced but never
        removed.
        """
        v = self._r.taken_at
        if v is None:
            return None
        if v == _db.TAKEN_NONE:
            return NEVER
        return stored_to_taken(v)

    @taken.setter
    def taken(self, value) -> None:
        stored = taken_to_stored(value)
        self._write(ops_items.update, self._id,
                    taken_at=0 if stored is None else stored)

    @property
    def taken_effective(self) -> Optional[PartialDate]:
        """What the library concludes, walking the three answers in order:
        what somebody typed, the indexed EXIF date, then the span of the
        events this picture carries."""
        value, _source = ops_items.taken_of(self._lib._session, self._r)
        return stored_to_taken(value) if value and value > 0 else None

    @property
    def taken_source(self) -> str:
        """set | exif | event | never | "" — which of the three answered."""
        return ops_items.taken_of(self._lib._session, self._r)[1]

    # -- files ---------------------------------------------------------------

    @property
    def files(self) -> HandleList:
        def read() -> list:
            rows = self._lib._session.execute(
                select(_db.File).where(_db.File.item_id == self._id)
                .order_by(_db.File.number, _db.File.id)
            ).scalars().all()
            return [File(self._lib, r.id, r) for r in rows]

        return HandleList(read, delete=lambda f: f.delete())

    @property
    def active_file(self) -> Optional[File]:
        """The version everything reads — thumbnail, preview, metadata,
        export."""
        fid = self._r.active_file_id
        return File(self._lib, fid) if fid else None

    @active_file.setter
    def active_file(self, value) -> None:
        fid = value._id if isinstance(value, File) else int(value)
        self._write(ops_items.update, self._id, active_file_id=fid)

    @property
    def path(self) -> Optional[Path]:
        """The active file's bytes on disk."""
        got = self.active_file
        return got.path if got else None

    @property
    def paths(self) -> list[Path]:
        return [p for p in (f.path for f in self.files) if p is not None]

    def open(self, mode: str = "rb"):
        got = self.active_file
        if got is None:
            raise NotFound("this item has no active file")
        return got.open(mode)

    def image(self):
        """The active file as a PIL image, in its final orientation."""
        got = self.active_file
        return got.image() if got else None

    def thumbnail(self, *, ensure: bool = True) -> Optional[Path]:
        got = self.active_file
        return got.thumbnail(ensure=ensure) if got else None

    @property
    def width(self) -> int:
        got = self.active_file
        return got.width if got else 0

    @property
    def height(self) -> int:
        got = self.active_file
        return got.height if got else 0

    @property
    def duration(self) -> Optional[float]:
        got = self.active_file
        return got.duration if got else None

    def frames(self, fps: Optional[float] = None, *,
               max_dim: Optional[int] = None) -> Iterator:
        """`(index, timestamp, PIL.Image)` decoded straight from a video.

        Nothing is written to the library, which is what makes this the way to
        turn a film into training images inside an exporter.

        `max_dim` caps the long side — ffmpeg downscales, never upscales, and
        the aspect is kept. A consumer that only needs a bucket-sized picture
        pays neither the decode nor the scratch space of a 4K frame, and a
        perceptual hash is unaffected by the reduction.
        """
        from .. import media
        from .errors import MediaUnreadable

        if self.kind != "video" or self.path is None:
            raise UnsupportedOperation(
                "frames() is only for video items with a stored file")
        try:
            yield from media.iter_video_frames(self.path, None, sample_fps=fps,
                                               max_dim=max_dim)
        except media.MediaError as exc:
            raise MediaUnreadable(str(exc)) from None

    # -- tags ----------------------------------------------------------------

    def _effective(self):
        """This item's effective tags, resolved at most once per generation.

        Goes through the library's shared `Resolver` and its cache, which is
        what `prefetch("tags")` fills. Reading it here is the point: without
        it the prefetch was write-only and a loop over a library resolved —
        and reloaded all three catalogs — once per picture.
        """
        from ..resolve import EffectiveTags

        cache = self._lib._eff_cache
        got = cache.get(self._id)
        if got is None:
            got = self._lib._resolver().effective_for([self._id]).get(
                self._id, EffectiveTags())
            cache[self._id] = got
        return got

    def _direct(self, negative: bool) -> set:
        eff = self._effective()
        return set(eff.direct_negative if negative else eff.direct_positive)

    def _assign(self, name: str, *, negative: bool = False, group=None,
                box=None, pending: Optional[bool] = None, **kw) -> None:
        """`MutableSet.add` takes one argument; these are the extras that make
        the annotated case a single line.

        They are NAMED rather than swallowed by `**kw`: an unknown keyword used
        to be accepted and silently do nothing, so `add(name, bbox=…)` — or the
        `box=` this signature had documented but never implemented — looked
        like it had worked.
        """
        if kw:
            raise TypeError(
                f"unknown option {sorted(kw)[0]!r} for adding a tag; "
                "try negative=, group=, box= or pending=")
        with self._lib.transaction():
            if group is not None:
                self._write(tagassign.place_tag, self._id, name,
                            group_id=(group._id
                                      if isinstance(group, ItemTagGroup)
                                      else int(group)), negative=negative)
            else:
                self._write(tagassign.assign_item_tag, self._id, name,
                            negative=negative)
            if box is not None:
                rect = box if isinstance(box, (tuple, list)) else (box,)
                TagOnItem(self, name).boxes.add(*rect, negative=negative,
                                                group=group)
            if pending is not None:
                self._write(tagassign.set_pending, self._id, name, pending)

    def _unassign(self, name: str) -> None:
        self._write(tagassign.unassign_item_tag, self._id, name)

    @property
    def tags(self) -> TagSet:
        """What the ITEM says — direct, positive. `.negative` is the sibling."""
        return TagSet(self)

    @tags.setter
    def tags(self, names) -> None:
        """Replace the direct positive tags with exactly these.

        A setter as well as a mutable set, because `item.tags |= {...}` is
        `item.tags = item.tags.__ior__(...)` — the augmented form assigns the
        result back, and without this it raises for a reason nobody would
        guess from the expression.
        """
        wanted = {str(n) for n in names}
        current = self._direct(False)
        with self._lib.transaction():
            for gone in current - wanted:
                self._unassign(gone)
            for fresh in wanted - current:
                self._assign(fresh)

    @property
    def effective_tags(self) -> frozenset:
        """What the LIBRARY concludes: direct + group-inherited + implied.

        Read-only, and a plain `frozenset` so `.add()` fails with the stdlib's
        own message. Assigning goes through `tags`, a group's grants, or an
        implication — three different things in three different places.
        """
        return frozenset(self._effective().positive)

    @property
    def effective_neg_tags(self) -> frozenset:
        return frozenset(self._effective().negative)

    @property
    def tag_groups(self):
        """This item's tag groupings. `[...]` takes a NAME and gets-or-creates
        (exact spelling first, else a unique case-insensitive match, else a
        new group — minting "hers" beside "Hers" over a shift key is the
        silent duplicate this avoids), so the doc's
        `item.tag_groups["Hers"].tags.add("blue_eyes")` is one line. A name
        two groups share raises `AmbiguousName`; an int is still an id, and
        `.get(name)` is the read that never creates."""
        from ._collections import Catalog

        def rows() -> list:
            found = self._lib._session.execute(
                select(_db.ItemTagGroup)
                .where(_db.ItemTagGroup.item_id == self._id)
                .order_by(_db.ItemTagGroup.position, _db.ItemTagGroup.id)
            ).scalars().all()
            return [ItemTagGroup(self._lib, g.id, g) for g in found]

        def by_name(name: str):
            wanted = name.strip()
            found = rows()
            got = [g for g in found if g.name == wanted]
            if not got:
                got = [g for g in found
                       if g.name.lower() == wanted.lower()]
            if len(got) > 1:
                raise AmbiguousName(
                    f"{len(got)} tag groups here are named {wanted!r} — "
                    f"use [] with an id")
            return got[0] if got else None

        return Catalog(
            rows,
            lambda gid: next((g for g in rows() if g._id == gid), None),
            lambda name: [g for g in rows()
                          if name.lower() in g.name.lower()],
            "tag group",
            create=lambda name: ItemTagGroup(
                self._lib,
                self._write(tagassign.create_group, self._id, name).id),
            extra={"pending": lambda: next((g for g in rows() if g.system),
                                           None)},
            by_name=by_name,
        )

    # -- everything else on the item -----------------------------------------

    @property
    def groups(self) -> HandleSet:
        def read() -> list:
            gids = self._lib._session.execute(
                select(_db.ItemGroup.group_id)
                .where(_db.ItemGroup.item_id == self._id)).scalars().all()
            return [Group(self._lib, g) for g in gids]

        return HandleSet(
            read,
            lambda g, **kw: self._write(
                ops_items.add_to_group, self._id,
                g._id if isinstance(g, Group) else int(g)),
            lambda g: self._write(
                ops_items.remove_from_group, self._id,
                g._id if isinstance(g, Group) else int(g)),
            "group",
        )

    def _captions_of(self, kind: str) -> HandleList:
        def read() -> list:
            rows = self._lib._session.execute(
                select(_db.Caption).where(_db.Caption.item_id == self._id)
                .order_by(_db.Caption.position, _db.Caption.id)
            ).scalars().all()
            return [Caption(self._lib, r.id, r) for r in rows
                    if (r.kind or "caption") == kind]

        return HandleList(read, delete=lambda c: c.delete())

    @property
    def captions(self) -> HandleList:
        """What the picture IS. Instructions are a separate list — mixing them
        is how a description ends up training an edit model."""
        return self._captions_of("caption")

    @property
    def instructions(self) -> HandleList:
        """How the picture was MADE from others: text plus the ordered source
        items. Same row type as a caption, deliberately kept apart."""
        return self._captions_of("instruction")

    def add_caption(self, text: str) -> Caption:
        row = self._write(ops_captions.add, self._id, text)
        return Caption(self._lib, row.id, row)

    def add_instruction(self, text: str, refs: Iterable = ()) -> Caption:
        """An instruction on this item, with the items it was made FROM.

        `refs` is an ordered sequence of `Item` handles or ids; the order is
        the order the model is shown them.
        """
        row = self._write(ops_captions.add, self._id, text, kind="instruction")
        cap = Caption(self._lib, row.id, row)
        if refs:
            cap.refs = refs
        return cap

    @property
    def appearances(self) -> HandleList:
        def read() -> list:
            rows = self._lib._session.execute(
                select(_db.ItemSubject)
                .where(_db.ItemSubject.item_id == self._id)
                .order_by(_db.ItemSubject.id)).scalars().all()
            return [Appearance(self._lib, r.id, r) for r in rows]

        return HandleList(read, delete=lambda a: a.delete())

    @property
    def subjects(self) -> HandleSet:
        """Who is in this picture. Adding one assigns their identity tag —
        that connection is the point, since the tag is what search reads."""
        def read() -> list:
            sids = self._lib._session.execute(
                select(_db.ItemSubject.subject_id)
                .where(_db.ItemSubject.item_id == self._id)).scalars().all()
            return [Subject(self._lib, s) for s in dict.fromkeys(sids)]

        def add(who, *, face=None, when=None, age=None):
            if isinstance(who, Subject):
                row = self._write(ops_subjects.add_appearance, self._id,
                                  subject_id=who._id,
                                  face_id=(face._id if isinstance(face, Face)
                                           else face))
            else:
                row = self._write(ops_subjects.add_appearance, self._id,
                                  display_name=str(who),
                                  face_id=(face._id if isinstance(face, Face)
                                           else face))
            if when is not None or age is not None:
                got = PartialDate.coerce(when)
                self._write(ops_subjects.edit_appearance, row.id,
                            set_when=True,
                            when_date=None if got is None else int(got),
                            when_age=age)
            return Appearance(self._lib, row.id)

        def remove(who) -> None:
            sid = who._id if isinstance(who, Subject) else int(who)
            for ap in self.appearances:
                if ap._r.subject_id == sid:
                    ap.delete()

        return HandleSet(read, add, remove, "subject")

    @property
    def faces(self) -> HandleList:
        def read() -> list:
            rows = ops_faces.faces_of(_ctx_of(self._lib), self._id)
            return [Face(self._lib, r.id, r) for r in rows]

        return HandleList(read, delete=lambda f: f.delete())

    def add_face(self, x: float, y: float, w: float, h: float, *,
                 subject=None) -> Face:
        """Draw a face by hand — no detector, so no score and no descriptor,
        and no later run can take it away."""
        row = self._write(
            ops_faces.create_face, self._id, x, y, w, h,
            subject_id=(subject._id if isinstance(subject, Subject)
                        else subject))
        return Face(self._lib, row.id, row)

    @property
    def face_models(self) -> tuple[str, ...]:
        """Detectors that have LOOKED at this item, whatever they found.

        Not derivable from the faces: an item a model found nothing in has no
        face to carry the fact, and that is exactly the item a "skip what is
        done" sweep must not run again.
        """
        rows = self._lib._session.execute(
            select(_db.ItemFaceRun.model)
            .where(_db.ItemFaceRun.item_id == self._id)).scalars().all()
        return tuple(sorted(rows))

    @property
    def text_blocks(self) -> HandleList:
        """The ACTIVE file's TOP-LEVEL text regions, in reading order; each
        carries its finer levels as `children`. Per file, the artifact rule:
        a reading is a fact about pixels, so an edited file made active
        answers with nothing until an engine reads it. Deliberately no
        `item.text` shortcut — a page's text is a rendering decision
        (separator, dismissed regions in or out, children flattened or not),
        so the one-liner is yours:
        ``"\\n".join(b.text for b in item.text_blocks)``.
        """
        def read() -> list:
            rows = ops_ocr.blocks_of(_ctx_of(self._lib), self._id)
            return [TextRegion(self._lib, r.id, r) for r in rows]

        return HandleList(read, delete=lambda r: r.delete())

    def add_text(self, x: float, y: float, w: float, h: float, *,
                 text: str = "", level: str = "block",
                 parent=None) -> TextRegion:
        """Draw a text box by hand — no engine, so no score and no model
        credit, and no later run can rewrite what is typed into it."""
        row = self._write(
            ops_ocr.create_region, self._id, x, y, w, h, text=text,
            level=level,
            parent_id=(parent._id if isinstance(parent, TextRegion)
                       else parent))
        return TextRegion(self._lib, row.id, row)

    @property
    def text_models(self) -> tuple[str, ...]:
        """Text engines that have READ this item's ACTIVE file, whatever
        they found — `face_models`' twin (`ItemTextRun`), per file so an
        edited file reads as never-read."""
        active = self._lib._session.execute(
            select(_db.Item.active_file_id)
            .where(_db.Item.id == self._id)).scalar_one_or_none()
        rows = self._lib._session.execute(
            select(_db.ItemTextRun.model)
            .where(_db.ItemTextRun.item_id == self._id,
                   _db.ItemTextRun.file_id == active)).scalars().all()
        return tuple(sorted(rows))

    @property
    def places(self) -> tuple[Place, ...]:
        """Where this was taken — derived from the tags it carries."""
        names = self.effective_tags
        if not names:
            return ()
        rows = self._lib._session.execute(
            select(_db.Location).join(_db.Tag, _db.Tag.id == _db.Location.tag_id)
            .where(_db.Tag.name.in_(sorted(names)))).scalars().all()
        return tuple(Place(self._lib, r.id, r) for r in rows)

    @property
    def events(self) -> tuple[Event, ...]:
        names = self.effective_tags
        if not names:
            return ()
        rows = self._lib._session.execute(
            select(_db.Occasion).join(_db.Tag, _db.Tag.id == _db.Occasion.tag_id)
            .where(_db.Tag.name.in_(sorted(names)))).scalars().all()
        return tuple(Event(self._lib, r.id, r) for r in rows)

    @property
    def links(self) -> HandleSet:
        """Items derived FROM this one."""
        def read() -> list:
            rows = self._lib._session.execute(
                select(_db.Relationship)
                .where(_db.Relationship.from_item_id == self._id)
            ).scalars().all()
            return [Link(self._lib, r.id, r, outgoing=True) for r in rows]

        def add(other, *, kind: str = "manual", meta=None):
            oid = other._id if isinstance(other, Item) else int(other)
            row = self._write(ops_links.create, self._id, oid, kind=kind,
                              meta=meta)
            return Link(self._lib, row.id, row, outgoing=True)

        return HandleSet(read, add, lambda link: link.delete(), "link")

    @property
    def linked_by(self) -> HandleSet:
        """Items this one derives from."""
        def read() -> list:
            rows = self._lib._session.execute(
                select(_db.Relationship)
                .where(_db.Relationship.to_item_id == self._id)
            ).scalars().all()
            return [Link(self._lib, r.id, r, outgoing=False) for r in rows]

        def add(other, *, kind: str = "manual", meta=None):
            oid = other._id if isinstance(other, Item) else int(other)
            row = self._write(ops_links.create, oid, self._id, kind=kind,
                              meta=meta)
            return Link(self._lib, row.id, row, outgoing=False)

        return HandleSet(read, add, lambda link: link.delete(), "link")

    @property
    def sequences(self) -> tuple[Sequence, ...]:
        # DISTINCT: an item at three positions of one sequence is in ONE
        # sequence, not three copies of it.
        rows = self._lib._session.execute(
            select(_db.SequenceItem.sequence_id)
            .where(_db.SequenceItem.item_id == self._id)
            .distinct()).scalars().all()
        return tuple(Sequence(self._lib, s) for s in rows)

    @property
    def metadata(self) -> dict:
        """Everything known about the picture: the intrinsic values computed
        from the active file, plus what the item answers with — its active
        file's own metadata and anything pinned to the item. Read-only.

        ONE value per name here, the PIN winning, because this is a plain dict
        and a script asking ``item.metadata["iso"]`` wants an answer rather
        than a set. Search is the place that matches ANY of an item's values;
        ``files`` is where each file's own answers can be read one by one.
        """
        from ..metadata_catalog import intrinsic_nums, intrinsic_texts

        out: dict[str, Any] = {}
        af = self._r.active_file if self._r.active_file_id else None
        out.update(intrinsic_texts(self.kind, af, self.uid))
        if af is not None:
            out.update(intrinsic_nums(af, self._r.last_imported_at,
                                      self._r.created_at))
        for table in (_db.ItemMetadata, _db.ItemMetaPin):  # pins written last
            for m in self._lib._session.execute(
                select(table).where(table.item_id == self._id)
            ).scalars().all():
                out[m.name] = (m.text_value if m.mtype == "text"
                               else (m.num_value or 0.0))
        return out

    # -- operations ----------------------------------------------------------

    def rotate(self, direction="right") -> None:
        """Turn the active image a quarter. Lossless, so repeated rotations
        never degrade it."""
        if isinstance(direction, int):
            direction = "right" if direction > 0 else "left"
        self._write(ops_items.rotate, self._id, direction)

    def hide(self) -> None:
        self._write(ops_items.hide, [self._id], True)

    def show(self) -> None:
        self._write(ops_items.hide, [self._id], False)

    def trash(self) -> None:
        self._write(ops_items.trash, [self._id])

    def restore(self) -> None:
        self._write(ops_items.restore, [self._id])

    def delete(self) -> None:
        """Permanently — the files, the folder, the thumbnails. `trash()` is
        the reversible one."""
        self._write(ops_items.delete_items, [self._id])

    def merge_from(self, other) -> "Item":
        """Fold another item into this one: its files, groups, tags and
        captions come across and it disappears."""
        oid = other._id if isinstance(other, Item) else int(other)
        self._write(ops_items.merge, oid, self._id)
        return self

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<Item {self.name!r} ({self.kind})>"


def _ctx_of(lib):
    from ..ops.context import Ctx

    return Ctx(session=lib._session)

"""Import pipeline: files, folders, archives and videos into the library.

Shared by the web upload endpoint and the CLI so behavior is identical. The
dedup rules (DESCRIPTION §Import):

1. Exact sha256 match  -> skip the file, but still assign the target groups.
2. Near-dup (pHash <= threshold) -> add as an alternative version of that item.
3. Otherwise -> create a new item.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Iterator, Optional, Union

import io
import json
import os
import sys
import tempfile
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from PIL import Image

from . import instance
from . import media, orient
from .config import Config, ext_of
from .fileops import make_oriented_file
from .colorkey import color_signature
from .dedup import (
    canon_thumb,
    compute_phash_image,
    norm_rgb,
    phash_to_int,
    verify_vec,
    whole_image_edit,
)
from .dedup_index import (ThumbLRU, find_files, find_frames,
                          find_nearest_file)
from .db import (
    new_uid,
    ensure_schema_current,
    is_locked_error,
    File,
    FileMetadata,
    FileName,
    Group,
    GroupParent,
    Item,
    ItemGroup,
    ItemMetaMute,
    ItemMetadata,
    ItemTag,
    Relationship,
    Sequence,
    SequenceItem,
    TrashedItem,
    VideoFrame,
    chunked,
    next_file_number,
    touch_items,
)
from . import tagname
from .itemmeta import index_file_metadata, rebuild_item_metadata  # noqa: F401
from .sequences import ensure_container
from .storage import ItemStore, sha256_bytes, sha256_file

ProgressFn = Callable[["ImportStats", str], None]


# Formats treated as "uncompressed"/lossless when comparing source quality; a
# lossless file is preferred over a lossy one at (about) the same resolution.
_LOSSLESS_FORMATS = frozenset({"png", "bmp", "tiff", "tif"})


# Video frames are decoded this small for scanning: the perceptual hash feeds a
# 64 px DCT and the pixel verifier a 32×32 grayscale, so anything past a few
# hundred pixels is wasted decoding on every frame. Matched frames are
# re-extracted at full resolution before being stored.
FRAME_MATCH_MAX_DIM = 256

#: (There used to be a COLOUR gate on hash-nominated candidates here,
#: `_COLOR_GATE_BITS` — reject a candidate whose stored `color_sig` sat too
#: far from the incoming picture's before it cost a decode. Removed by owner
#: decision after being measured at ZERO pruning on both real populations
#: tried: over 14,591 colour-diverse crawl images, 500 probes nominated nine
#: candidates and the colour gate dropped none — genuine near-duplicates
#: match in colour by construction, and greyscale content defeats the gate
#: for `colorkey.py`'s reason, every page of ink on white sharing one
#: palette. What it bounded was only the seeded collision storm, which the
#: ~21-bit bands now shrink ~51x by themselves. The colour COLUMNS stay:
#: `COLORLIKE:` and the colour sort read them; only matching never did.)

#: How deep archives may nest before a member is skipped rather than opened.
#: A zip inside a zip inside a zip is depth 2 and imports; past this it is a
#: hostile or absurd input, recorded as a skipped entry naming the member.
_ARCHIVE_DEPTH_MAX = 3


def _archive_junk(inner_name: str) -> bool:
    """Whether an archive member is litter rather than content: a hidden
    file (`.DS_Store`, an AppleDouble `._page.jpg`) or anything under a
    `__MACOSX` folder — the sidecar tree macOS Finder writes into every zip
    it makes. Asked of the NAME alone and before the member's kind, because
    the AppleDouble fork wears the real file's extension and would otherwise
    be handed to a decoder that cannot read it."""
    return (PurePosixPath(inner_name).name.startswith(".")
            or "__MACOSX" in inner_name.split("/"))

#: A picture is on screen for a while, so one screenshot matches a whole RUN of
#: stored hashes. A gap longer than this separates two APPEARANCES — the same
#: shot coming back later in the film, which really is a second moment worth
#: recording. Within one appearance only the best-matching moment is reported.
FRAME_APPEARANCE_GAP = 1.0


def _new_run(last: Optional[int], phash_int: int) -> bool:
    """Is this frame the start of a new run, i.e. worth a row of its own?

    EVERY FRAME IS HASHED, AND THAT IS THE POINT. The index used to be SAMPLED
    at `video_match_fps` (2/s), which assumes a film's content arrives at a
    steady rate — and no film's does: one may hold a single drawing for four
    seconds and the next may flash twenty-four different frames in one. What
    that cost is a screenshot taken between two samples matching nothing at
    all. Measured on a real library: two stills of one shot imported together,
    one of them exactly on a sample (distance 0) and the other 22 bits from
    the nearest one, well past the near-dup threshold — so the first got its
    link to the film and the second got nothing, which is indistinguishable
    from the feature being broken.

    What is stored is one row per RUN OF IDENTICAL HASHES, not one per frame.
    That is lossless in the only sense that matters here: the frames dropped
    hash to the same 256 bits as the row that stands for them, so every
    picture that would have matched one of them matches it. It is also what
    makes the held drawing cheap and the busy second complete, which is the
    whole complaint about a fixed rate stated the other way round.

    Measured end to end on a 24-minute episode: 23 s to hash all 34 300 of its
    frames, against 22 s for the 2 863 the sampled index held — the frames come
    down a pipe now (see `media.iter_video_frames`), and PNG was the whole of
    the old cost. 23 100 rows where there were 2 863, i.e. two thirds of the
    frames start a run. A NEAR-MISS rule (drop a frame within k bits of the
    run's hash) was measured too and is not worth it: at k=2 it saves a fifth
    of the rows in exchange for a claim about pictures nobody has compared.

    The reported pair now resolves at 386.55 s and 386.68 s — two moments an
    eighth of a second apart, which is exactly what they are.
    """
    return last is None or last != phash_int


def _appearances(hits: list[tuple[float, int]]) -> list[float]:
    """The best moment of each run of ``(timestamp, distance)`` matches.

    Pure so the rule can be stated as a test. Ties go to the EARLIEST moment:
    a run of equally good frames is one picture held on screen, and its start
    is when it appeared.
    """
    best: list[float] = []
    cur: Optional[tuple[float, int]] = None
    prev: Optional[float] = None
    for ts, d in sorted(hits):
        if prev is not None and ts - prev > FRAME_APPEARANCE_GAP:
            if cur is not None:
                best.append(cur[0])
            cur = None
        if cur is None or d < cur[1]:
            cur = (ts, d)
        prev = ts
    if cur is not None:
        best.append(cur[0])
    return best


def _aspect_close(a1: float, a2: float, tol: float = 0.15) -> bool:
    """Whether two aspect ratios are within ``tol`` (default 15%). Unknown ratios
    (0) pass, so a missing dimension never blocks an otherwise-good match."""
    if a1 <= 0 or a2 <= 0:
        return True
    hi, lo = (a1, a2) if a1 >= a2 else (a2, a1)
    return hi / lo <= 1.0 + tol

# Relationship kind for auto-detected derived images (a rotation or flip of
# another item). One umbrella label — "edit" — covers both; the specific
# transform ("rotate"/"flip") is recorded in the relationship's ``meta``. The
# same kind is reused for user edits saved from the image editor (transform
# "user"), so the whole "derived from" family lives under one relationship kind.
_EDIT_KIND = "edit"


class _LazyGroup:
    """A folder/archive group that is created only once an item lands in it.

    Resolving creates the group (and any not-yet-resolved ancestors) on demand.
    Folders that turn out to hold no importable files never trigger a resolve,
    so they never spawn an empty group (DESCRIPTION §Import).
    """

    __slots__ = ("_importer", "_name", "_icon", "_parent", "_id")

    def __init__(self, importer: "Importer", name: str, icon: str,
                 parent: "GroupRef"):
        self._importer = importer
        self._name = name
        self._icon = icon
        self._parent = parent
        self._id: Optional[int] = None

    def resolve(self) -> int:
        if self._id is None:
            parent_id = _resolve_group(self._parent)
            self._id = self._importer.get_or_create_group(
                self._name, self._icon, parent_id
            )
        return self._id


# A group reference threaded through the import traversal: a concrete group id,
# None (top level), or a lazily-created folder/archive group.
GroupRef = Union[int, None, _LazyGroup]


def default_run_group_name(now: "Optional[datetime]" = None) -> str:
    """What an unnamed run group is called.

    Here rather than in the CLI or the router so the two doors cannot drift
    into two names. To the MINUTE: it has to be distinct enough that two
    imports do not silently share a box, and readable enough to recognise in
    a tree a week later — seconds buy nothing a person can use, and two
    imports started inside one minute are, in practice, one import.
    """
    from datetime import datetime as _dt

    return f"Imported {(now or _dt.now()).strftime('%Y-%m-%d %H:%M')}"


def _resolve_group(ref: "GroupRef") -> Optional[int]:
    if isinstance(ref, _LazyGroup):
        return ref.resolve()
    return ref


import re as _re


def _natural_key(name: str) -> list:
    """Sort key that orders 'page2' before 'page10' (natural numeric order)."""
    return [
        int(tok) if tok.isdigit() else tok.lower()
        for tok in _re.split(r"(\d+)", name)
    ]
#: Filename for imported bytes that arrive without a usable name of their own.
GENERIC_IMPORT_NAME = "image"

#: Path separators, control characters and the characters Windows refuses.
_UNSAFE_NAME = _re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')


def _stage_name(name: str) -> str:
    """A filename that is safe to create on disk, out of an untrusted one.

    Bytes handed to the import carry whatever name their source suggested — a
    Content-Disposition header, a URL path — so it is reduced to a plain
    basename here rather than trusted. This is the name the file is staged,
    stored and listed under; ``ext_of`` still has to find the extension in it,
    so the shape (stem + '.' + ext) is preserved.
    """
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = _UNSAFE_NAME.sub("_", base).strip(" .")
    stem, dot, ext = base.rpartition(".")
    if not dot:
        return base[:120] or GENERIC_IMPORT_NAME
    return (stem[:120] or GENERIC_IMPORT_NAME) + "." + ext[:16]


#: What `ImportOptions.sequence_grouping` may say, for the interfaces that
#: offer it as a choice (the CLI's `choices`, the import form, the overlay).
#: The importer itself needs no validation: the two helpers that read it ask
#: for "container" and "members" by name, so anything else IS "both".
SEQUENCE_GROUPINGS = ("both", "container", "members")


#: Why the gate turned a source away. Recorded on the source's own entry, so
#: a run that imported less than somebody expected says which rule did it —
#: the size minimums and the aspect range are different questions and a single
#: "ignored" could not tell them apart.
SIZE_REJECTED = "under the import's minimum size"
ASPECT_REJECTED = "outside the import's aspect-ratio range"


@dataclass
class ImportOptions:
    """How one import run behaves — what `Library.importing` and the other
    import calls accept as keyword arguments (``lib.importing(move=True)``),
    gathered into one object."""

    parent_group_id: Optional[int] = None
    """Put everything the run creates into this group."""

    new_group: bool = False
    """Make a group of this run's own, INSIDE `parent_group_id`, and put
    everything there.

    "Where it goes" says which shelf; this says the import gets a box on it.
    It is a `_LazyGroup` like a folder's, so a run that imports nothing
    (every file a duplicate, or every one filtered out) leaves no empty group
    behind — the same rule DESCRIPTION states for folders.

    Get-or-create by name at that parent, which is what makes a re-run of the
    same import land back in the same box rather than beside it."""

    new_group_name: str = ""
    """What to call it. Empty means `default_run_group_name()` — a timestamp,
    since the alternative is asking somebody to name every import."""

    move: bool = False
    """TAKE the source file instead of copying it into the item folder. Only
    ever removes a source the library actually stored: an exact duplicate
    stores nothing, so its file is left where it is (there is a copy of
    those bytes already, and deleting the caller's is not this run's to do)."""

    folders_as_groups: bool = True
    """Recreate an imported folder tree as groups."""

    recursive: bool = True
    """Descend into subfolders of an imported folder."""

    archives_as_groups: bool = False
    """Give each imported archive its own group (named after the archive).
    When off — the default — the archive's contents are placed directly in
    the group the archive itself would have joined (its parent).

    OFF by default: a comic archive is already a SEQUENCE, which is the thing
    that holds its pages in order and the thing the library shows, so a group
    around the same pages is a second container saying less. A folder of
    forty chapters produced forty groups nobody asked for."""

    sequence_grouping: str = "both"
    """Which half of a SEQUENCE joins the run's groups: ``both`` (the
    default), ``container`` (the sequence alone) or ``members`` (the items
    inside it alone).

    A sequence is two things at once — the item the library shows and the
    items inside it — and which of them somebody wants in their groups is a
    real choice: a group per chapter is either a shelf of books or a pile of
    what is in them, and both readings are in use. `both` is what the
    importer has always done.

    ITEMS rather than pages throughout, because the same machinery holds a
    comic's pages, a PDF's pages and an animated GIF's FRAMES — the word has
    to fit all three.

    Each side keeps its own LEVEL, which the option does not touch: the items
    go where the archive's contents go (its own group when
    `archives_as_groups`, else the level the file sits at) and the container
    goes to the level the archive FILE sits at — falling back to the
    archive's own group when that level has none, so a sequence is never
    groupless while its own items are grouped."""

    archive_sequences: bool = False
    """Build a sequence from the contents of a *non-comic* compressed archive
    (zip/7z). Comic archives (cbz/cbr) always become sequences regardless."""

    min_megapixels: float = 0.0
    """Ignore anything under this many megapixels (width x height)."""

    min_short_edge: int = 0
    """Ignore anything under this many pixels on its SHORTER side."""

    min_long_edge: int = 0
    """Ignore anything under this many pixels on its LONGER side.

    The three minimums are the Storage page's file-prune rule read the other
    way round (`ops.files.PruneRule`, whose docstring carries the reasoning):
    0 is "not set", a file must clear EVERY one that is set, and the two edge
    thresholds ask different questions — the short edge is about a thumbnail
    (small however it is shaped), the long edge about a picture that is small
    in the direction it is widest. A file nothing could measure is never
    ignored: the run cannot say whether it is small, and the safe direction
    is to import it.

    A SEQUENCE is judged by its LARGEST page and kept whole — a book's blank
    or half-height pages are part of it, and a filter that dropped them would
    leave a chapter with holes in it. So the pages are not judged one by one:
    either the book has a page that passes and all of it is imported, or none
    of them does and the whole book is ignored. (An archive that is NOT a
    sequence scatters into items of its own, and those ARE judged one by one.)
    """

    ignore_kinds: "tuple[str, ...] | list[str]" = ()
    """File types the run leaves alone: any of ``image``, ``video``,
    ``sequence`` and ``archive``.

    Four buckets that PARTITION what an import can be handed, so every source
    falls in exactly one: a loose picture, a film, a book (a PDF, an animated
    GIF, a comic archive — anything that becomes a sequence) and an archive
    that scatters into items of its own. Whether a zip is the third or the
    fourth is `archive_sequences`' answer, which is the same question
    `_import_archive` asks itself.

    It reaches a member of a plain archive too, since those become items of
    their own — but never a PAGE of a book: a sequence is kept whole, so
    ignoring images does not hollow out a comic whose pages are images.
    """

    min_aspect: float = 0.0
    """Ignore anything NARROWER than this width-to-height ratio."""

    max_aspect: float = 0.0
    """Ignore anything WIDER than this width-to-height ratio.

    The pair is a RANGE where the three above are minimums, and it is
    `width / height` throughout — 1.0 is square, 0.5 is twice as tall as it
    is wide, 2.0 twice as wide as tall — so `min_aspect=0.5, max_aspect=2`
    is "nothing more extreme than 2:1 either way". 0 is "not set" on each
    side, exactly as it is for the minimums, so one end may be given without
    the other ("no panoramas" is `max_aspect` alone).

    ORIENTATION-AWARE, deliberately: a landscape and a portrait crop of one
    picture are different pictures to a dataset, and a rule written over the
    long and short edges could not tell them apart. What cannot be measured
    is never ignored, and a SEQUENCE is judged by its pages the same way the
    minimums judge it — kept whole when any page passes.
    """

    @property
    def has_minimum(self) -> bool:
        """Is any of the three minimums set? `PruneRule.has_threshold`'s
        twin."""
        return (self.min_megapixels > 0 or self.min_short_edge > 0
                or self.min_long_edge > 0)

    @property
    def has_aspect(self) -> bool:
        """Is either end of the aspect range set?"""
        return self.min_aspect > 0 or self.max_aspect > 0

    @property
    def has_gate(self) -> bool:
        """Is there any reason to MEASURE a source at all?

        The one question every gate call site asks — a run that filters on
        nothing must not pay a header read, or an ffprobe, for a question
        nobody asked. It is the union rather than `has_minimum` because the
        aspect range is answered by the same measurement.
        """
        return self.has_minimum or self.has_aspect

    tags_existing: bool = True
    """Also put the run's tags on items the run MATCHED rather than created —
    an exact duplicate that stored nothing, a near-dup that folded in as an
    alternative file. On by default: "tag whatever this import is about" is
    the ordinary meaning, and a re-import of a folder is how a batch gets a
    tag after the fact."""

    tags: "tuple[str, ...] | list[str]" = ()
    """Tag names put on every item the run CREATES (sequence containers
    included). Names go through the ordinary assignment door
    (`tagcatalog.get_or_create` — alias redirection, the tag set's own
    advice), and a name the door refuses is skipped rather than failing a
    finished run.
    No per-item events, like the group memberships an import writes: the
    run's one `import` entry is the log."""

    tags_image: "tuple[str, ...] | list[str]" = ()
    """Tags for created IMAGE items only."""

    tags_video: "tuple[str, ...] | list[str]" = ()
    """Tags for created VIDEO items only."""

    tags_sequence: "tuple[str, ...] | list[str]" = ()
    """Tags for created SEQUENCE container items only."""


@dataclass
class ImportBytes:
    """One in-memory file to import, wherever a path would otherwise be given.

    A pure stand-in for a file and nothing else: ``data`` is what the file
    would hold and ``name`` what it would be called. The name's extension
    decides how the bytes are read (image / video / archive), so a name
    carrying none the importer accepts gets one from the content itself
    (``media.sniff_ext``) — a video has to arrive named, since nothing here
    sniffs one. The bytes are staged as a real file for the length of the
    import (the readers all take a path) and the library's own copy is
    written by `ItemStore` exactly as for a file that came off disk.

    Where the bytes CAME FROM is recorded afterwards, through the result and
    the bulk provenance ops: ``got.files`` names every stored file they
    landed on — the existing one for a duplicate, which is the case worth
    recording — and `Library.add_file_urls` / `Library.assign_tags` write a
    whole crawl batch in one transaction each. (The fields rode HERE once,
    applied by the importer; reverted deliberately — an import source is a
    file, not an instruction sheet, and the batching the importer provided
    now lives in the bulk ops where every caller can reach it.)
    """
    data: bytes
    name: str = ""


def _clean_tag_names(names) -> "list[tuple[str, bool]]":
    """Tag-field normalization for names an import option carries: a leading
    ``-`` is the NEGATIVE sign (the overlay's flip), not part of the name."""
    out = []
    for n in names or ():
        raw = str(n).strip()
        negative = raw.startswith("-")
        if negative:
            raw = raw[1:]
        name = tagname.normalize(_re.sub(r"\s+", "_", raw.strip().lower()))
        if name:
            out.append((name, negative))
    return list(dict.fromkeys(out))


ImportSource = Union[str, Path, ImportBytes]
"""What an import call accepts as one source: a path on disk — a file, a
folder, an archive, a video — or an
[`ImportBytes`][media_compost.importer.ImportBytes] for data already in
memory."""


#: The 8 dihedral transforms of the plane (four rotations x optional mirror) —
#: the orientations `dedup.whole_image_edit` classifies. Hashing the incoming
#: image under each lets the pHash index nominate rotate/flip candidates: one
#: of the transforms undoes the reorientation, and THAT copy's hash lands
#: within the near-dup threshold of the original's.
DIHEDRAL = (
    Image.Transpose.ROTATE_90,
    Image.Transpose.ROTATE_180,
    Image.Transpose.ROTATE_270,
    Image.Transpose.FLIP_LEFT_RIGHT,
    Image.Transpose.FLIP_TOP_BOTTOM,
    Image.Transpose.TRANSPOSE,
    Image.Transpose.TRANSVERSE,
)


def dihedral_phashes(image: Image.Image, phash_int: int) -> list[int]:
    """The pHashes of ``image`` under all 8 dihedral orientations.

    The identity is the exact hash the caller already computed; the other
    seven are hashed from a downscaled copy (the pHash pipeline reduces to a
    64px DCT anyway, so transposing the full image first is pure waste).

    A MODULE FUNCTION rather than a method, because this is the single most
    expensive thing the serial import used to do — 12 ms a picture, measured
    at 23% of a crawl import's wall clock — and it reads no library state at
    all, so :func:`prepare_source` computes it ahead of time instead.
    """
    small = image.copy()
    small.thumbnail((256, 256))
    out = [phash_int]
    for op in DIHEDRAL:
        out.append(phash_to_int(compute_phash_image(small.transpose(op))))
    return out


@dataclass
class PreparedImage:
    """The CPU-heavy half of one still-image import, computed ahead of time.

    `ImportRun.add_many` calls :func:`prepare_source` on worker threads — or
    in worker PROCESSES — while the serial import loop works, and hands the
    result to :meth:`Importer.add_source`, which then reuses all of it instead
    of recomputing it. Everything in here is derived from the source's own
    bytes and nothing else, which is what makes computing it out of order
    safe: no library state is read or written.

    EVERYTHING EXCEPT ``rgb`` IS SMALL, AND THAT IS THE POINT. Pickled for a
    process boundary this bundle is 4.7 MB carrying the decoded image and
    ~10 KB without it — 236 MB/s of IPC against half a megabyte at import
    speed — so a cross-process prefetch drops the decode and sends the
    ANSWERS. ``canon``, ``dihedral``, ``rgb32`` and ``meta_values`` are here
    for exactly that reason: they were the things the serial half still
    needed full pixels for, and each is a few kilobytes once computed. What
    is left needing ``rgb`` is the exact-pixel film-frame check — rare — and
    there :meth:`Importer._ingest_image` decodes the staged file again,
    which is the cheaper half of the trade.
    """

    digest: str
    info: "media.ImageInfo"
    rgb: Optional[Image.Image]
    phash: str
    color_key: int
    color_sig: int
    #: pHashes under all 8 orientations (`dihedral_phashes`), for the
    #: rotate/flip prefilter.
    dihedral: tuple = ()
    #: The 48x48 grayscale array `dedup.canon_thumb` produces, for the thumb
    #: LRU the rotate/flip pixel check reads.
    canon: object = None
    #: What the bytes say about themselves (`media.typed_image_metadata`),
    #: handed to `itemmeta.index_file_metadata` so it need not re-read them.
    meta_values: Optional[list] = None
    #: `dedup.norm_rgb` of the picture — the INCOMING side of the near-dup
    #: pixel verify, so a fifth of a crawl's imports (the near-duplicates)
    #: stops re-decoding a multi-megabyte file on the serial thread to
    #: answer a question about 3072 colour values. It was `norm_gray` until
    #: the verifier went RGB (`dedup.norm_rgb` says what that caught).
    rgb32: tuple = ()

    def without_image(self) -> "PreparedImage":
        """The same bundle minus the decoded pixels — what crosses a pipe."""
        return replace(self, rgb=None)


def prepare_source(source: ImportSource,
                   *, with_image: bool = True) -> Optional[PreparedImage]:
    """sha256, decode, pHash, colour, orientations and metadata, off-line.

    Answers None for anything that is not a lone, readable still image — a
    video, an archive, a PDF, a folder, unrecognizable bytes — and the serial
    path then handles the source whole, exactly as it would without a
    prefetch. Pure: reads the source, touches no library state.

    ``with_image`` False drops the decoded pixels from the answer, which is
    what a prefetch running in another PROCESS passes: see `PreparedImage`
    for why the picture may not travel and what stands in for it.
    """
    try:
        if isinstance(source, ImportBytes):
            name = _stage_name(source.name)
            if media.classify(Path(name)) == "other":
                ext = media.sniff_ext(source.data)
                if not ext:
                    return None
                name = f"{Path(name).stem or GENERIC_IMPORT_NAME}.{ext}"
            if media.classify(Path(name)) != "image":
                return None
            # `classify` reads the frame count off the FILE, and there is no
            # file here — so every gif reaches it as "image". An animated one
            # is a book of pictures (`Importer._import_gif`) and this bundle
            # is the whole file's; handing it over would give the first frame
            # the GIF's own sha256.
            if ext_of(name) == "gif" and media.is_animated_bytes(source.data):
                return None
            digest = sha256_bytes(source.data)
            info, rgb = media.load_rgb_with_info(io.BytesIO(source.data),
                                                 name=name)
            read_from = source.data
        else:
            p = Path(source)
            if not p.is_file() or media.classify(p) != "image":
                return None
            digest = sha256_file(p)
            info, rgb = media.load_rgb_with_info(p)
            read_from = p
        ckey, csig = color_signature(rgb)
        phash = compute_phash_image(rgb)
        # Each of these three is best-effort on its own: the serial half falls
        # back to computing it, so a picture that defeats one of them is
        # slower rather than broken.
        try:
            canon = canon_thumb(rgb)
        except Exception:  # noqa: BLE001
            canon = None
        try:
            probes = tuple(dihedral_phashes(rgb, phash_to_int(phash)))
        except Exception:  # noqa: BLE001
            probes = ()
        try:
            values = media.typed_image_metadata(read_from)
        except Exception:  # noqa: BLE001
            values = None
        try:
            rgbvec = tuple(norm_rgb(rgb))
        except Exception:  # noqa: BLE001
            rgbvec = ()
        got = PreparedImage(digest=digest, info=info, rgb=rgb, phash=phash,
                            color_key=ckey, color_sig=csig, dihedral=probes,
                            canon=canon, meta_values=values, rgb32=rgbvec)
        return got if with_image else got.without_image()
    except Exception:  # noqa: BLE001 - the serial path re-reads and reports
        return None


def prepare_source_slim(source: ImportSource) -> Optional[PreparedImage]:
    """:func:`prepare_source` without the decoded image, for a worker PROCESS.

    A module-level function rather than a lambda or a partial because a
    process pool has to pickle whatever it is asked to call.
    """
    return prepare_source(source, with_image=False)


def _render_and_prepare(pdf_path: str, index: int,
                        out_dir: str) -> tuple[str, Optional[PreparedImage]]:
    """Render one PDF page and hash it, on a look-ahead worker: the page's
    file (in ``out_dir``) and its bundle. Module-level and string-argumented
    so a process pool can call it (`media.render_pdf_page` keeps the
    document open per process)."""
    out = media.render_pdf_page(Path(pdf_path), index, Path(out_dir))
    return str(out), prepare_source_slim(out)


def _prefetchable(source: "ImportSource") -> bool:
    """Whether to hand this source to a look-ahead worker at all.

    :func:`worth_prefetching`'s question with the one case it does not have
    to answer: a DIRECTORY, which `import_paths` may be handed and which
    `_import_dir` walks (and prefetches) itself. `prepare_source` would
    answer None for it anyway; the point is not to spend a worker slot, and
    a slot in this window is one of four.
    """
    if isinstance(source, ImportBytes):
        return worth_prefetching(source)
    try:
        return Path(source).is_file()
    except OSError:
        return False


def worth_prefetching(source: ImportSource) -> bool:
    """Whether handing ``source`` to a prefetch worker could possibly pay.

    The cheap parent-side half of :func:`prepare_source`'s own gate, for
    `add_many` to ask BEFORE submitting: a video or archive body still ends
    up at the serial path either way, but through a process pool the whole
    body is pickled across a pipe first — a feature-length film copied to a
    worker whose entire answer is None. Only what the NAME already rules out
    is skipped (`prepare_source` re-derives the same answer from more
    evidence, so a skip here is never a different import, only a prefetch
    that does not happen); nameless bytes go to the worker, which sniffs
    them. A PATH is always worth submitting — it pickles as a string, and
    classifying it here would read the file on the serial thread.
    """
    if not isinstance(source, ImportBytes):
        return True
    try:
        kind = media.classify(Path(_stage_name(source.name)))
    except Exception:  # noqa: BLE001 - let the worker answer
        return True
    # "image" may prepare; "other" may be a nameless picture the worker's
    # sniff identifies. Everything the name already decides — video, gif,
    # archive, pdf — is the serial path's whatever a worker says.
    return kind in ("image", "other")


@dataclass
class ImportOutcome:
    """Where ONE source landed — what :meth:`Importer.add_source` reports.

    ``status`` is what happened to it:

    ``imported``     a new item now holds these bytes
    ``alternative``  they joined an existing item as another version of it
    ``duplicate``    the library already had them, byte for byte; nothing was
                     stored, and the existing file merely learned another name
    ``multi``        a folder, an archive or a video: several items, so there
                     is no single one to point at — read ``stats``
    ``skipped``      nothing the importer handles
    ``ignored``      the run's own minimums left it out — its own answer,
                     since "cannot read it", "already have it" and "told me
                     not to" are three different things that all store
                     nothing
    ``error``        it blew up; the reason is the run's last error

    ``item_id``/``file_id`` are the row a handle can be built from, and are
    None for anything but the first three.
    """

    status: str = "skipped"
    item_id: Optional[int] = None
    file_id: Optional[int] = None
    error: str = ""


# (There used to be a `HashCache` dataclass here — the process-shared
# near-dup and video-frame indexes, primed from the DB per process behind a
# `(count, max_id)` reuse guard with an additive append path and a
# flush-listener invalidation channel. All of it is gone: the band keys are
# indexed COLUMNS now (`dedup_index` module docstring), so there is nothing
# to prime, nothing to guard and nothing to invalidate. What survives of the
# sharing is the thumb LRU below, passed as `shared_thumbs`.)


def import_event(stats: "ImportStats", parent_group_id) -> Optional[dict]:
    """The one History entry an import run writes, as ``log_event`` keyword
    arguments — shared by the CLI, the web import and the Python API so the
    three cannot drift — or None when the run changed nothing worth an
    entry. A run that created nothing but TAGGED existing items (the
    `tags_existing` default over a re-import) is such an entry: it used to
    write none, so those assignments were invisible and could not be
    reverted."""
    tagged = list(stats.tagged_pairs)
    if not (stats.imported or stats.added_alternative or tagged):
        return None
    data = {
        "imported": stats.imported,
        "alternatives": stats.added_alternative,
        "skipped": stats.skipped_duplicate,
        "groups_created": stats.groups_created,
        "edit_links": stats.edit_links,
        "parent_group_id": parent_group_id,
        "imported_item_ids": list(stats.imported_item_ids),
    }
    if tagged:
        # Conditional, so an untagged run's entry is byte-identical to what
        # every earlier build wrote.
        data["tagged"] = tagged
    if stats.imported or stats.added_alternative:
        return dict(action="import", entity_type="import",
                    summary="Imported {new} new, {alt} alternative",
                    summary_vars={"new": stats.imported,
                                  "alt": stats.added_alternative},
                    data=data)
    items = len({iid for iid, _t in tagged})
    return dict(action="import", entity_type="import",
                summary="Tagged {n} existing items on import",
                summary_vars={"n": items}, data=data)


@dataclass
class ImportStats:
    """One run's counters — what
    [`ImportResult.stats`][media_compost.library.importing.ImportResult.stats]
    and `ImportRun.stats` answer with, live during the run and final once it
    closes."""

    processed: int = 0
    """Top-level files handled so far (the progress numerator)."""

    imported: int = 0
    """Brand-new items created."""

    skipped_duplicate: int = 0
    """Byte-identical files that stored nothing (the existing file learned
    another name)."""

    added_alternative: int = 0
    """Files that joined an existing item as another version of it."""

    ignored: int = 0
    """Files the run's minimums left out — counted per SOURCE the gate turned
    away, so an ignored book is one, not one per page. Its OWN counter beside
    `skipped_duplicate`: a file the library already holds and a file the run
    was told not to take are two different answers, and one number for both
    reads as "these are here somewhere"."""

    frames_extracted: int = 0
    """Stills kept beside a video's frames."""

    frames_matched: int = 0
    """Video frames matched to an existing image item."""
    tagged_pairs: list = field(default_factory=list)
    """The ``(item_id, tag_id)`` assignments the run's own tags CREATED
    (`ImportOptions.tags` and its per-kind lists), on new and matched items
    alike. What the run's History entry records so a revert can take them
    back — and what makes a run that created nothing but tagged something
    worth an entry at all."""

    sequences_created: int = 0
    """Sequences built (comic archives, PDFs, opted-in archives/videos)."""

    archives_expanded: int = 0
    """Archives whose contents were extracted and imported."""

    videos_split: int = 0
    """Videos split at scene cuts."""

    groups_created: int = 0
    """Groups minted for folders and archives."""

    edit_links: int = 0
    """Rotation/flip copies folded into their original's item."""

    imported_item_ids: list[int] = field(default_factory=list)
    """Ids of the brand-new items this run created — so an import can be
    reverted from History by trashing exactly those, never pre-existing
    dedup targets."""

    errors: list[str] = field(default_factory=list)
    """One line per file that failed, in order."""

    hidden_matches: list[tuple[str, str]] = field(default_factory=list)
    """Files that landed on an item nobody can SEE — skipped as a duplicate
    of one, or added as another version of one, where that item is hidden or
    in the Trash. ``(name, "hidden" | "trashed")``, name as it was handed in.

    The import worked and reported nothing wrong, and the picture is not in
    the library afterwards — it is inside something the grid does not show,
    which reads exactly like an import that silently dropped files. There is
    nothing to fix automatically: un-hiding somebody's hidden item or
    restoring what they threw away are both decisions, so the run says what
    happened and names the files."""

    def as_dict(self) -> dict:
        return {
            "processed": self.processed,
            "imported": self.imported,
            "skipped_duplicate": self.skipped_duplicate,
            "added_alternative": self.added_alternative,
            "ignored": self.ignored,
            "frames_extracted": self.frames_extracted,
            "frames_matched": self.frames_matched,
            "sequences_created": self.sequences_created,
            "archives_expanded": self.archives_expanded,
            "videos_split": self.videos_split,
            "groups_created": self.groups_created,
            "edit_links": self.edit_links,
            "imported_item_ids": self.imported_item_ids,
            "errors": self.errors,
            # Pairs, as two-element lists over the wire.
            "hidden_matches": [list(p) for p in self.hidden_matches],
        }


class Importer:
    def __init__(self, session: Session, store: ItemStore, cfg: Config,
                 on_progress: ProgressFn | None = None,
                 shared_thumbs: "ThumbLRU | None" = None):
        self.session = session
        self.store = store
        self.config = cfg
        self.on_progress = on_progress
        self.stats = ImportStats()
        # Near-dup and frame matching go through the band-key columns
        # (`dedup_index.find_files` / `find_frames`) — no in-memory index and
        # no priming. What IS still shared across imports is the decoded
        # 48x48 thumbs the rotate/flip pixel check compares against, keyed by
        # (file id, phash) so an in-place pixel rewrite ages out by itself.
        self._thumbs: ThumbLRU = (
            shared_thumbs if shared_thumbs is not None else ThumbLRU()
        )
        self._move_sources = False
        # Per-run memo of named places, keyed by the address: the second
        # photo from the same city is a dict hit instead of a table scan.
        # Commit cadence for long imports: every N files or T seconds,
        # whichever comes first (see `_import_file`).
        self._last_commit_processed = 0
        self._last_commit_time = time.monotonic()
        # Whether this run holds the library's write lease (chunk-scoped).
        self._leased = False
        # The web-URL source of the file currently being ingested, if it came
        # from :class:`ImportBytes`. It rides on the importer for the same
        # reason the options do: the branch that knows WHICH stored file the
        # source landed on is several frames below the call that carries it.
        # Whether reorientation (rotate/flip) detection runs. Always attempted on
        # import unless disabled via the global config toggle; there is no
        # per-import opt-out.
        self._edit_enabled = cfg.edit_detect
        self._options = ImportOptions()
        # Did the minimum-resolution gate turn the current FILE away? Reset
        # per file in `_import_file`; here so the attribute exists whatever
        # order a caller drives this in.
        self._gated = False
        # The folder walk's look-ahead pool, built on first use and shut down
        # by `finish_run`. Here as well as in `begin_run`, so the attribute
        # exists whatever order a caller drives this in.
        self._pool = None
        self._stages: dict[str, float] = {}
        if self._PROFILE:
            self._profile_hooks()

    # ---- public entry point ----

    def import_paths(self, paths: "list[ImportSource]",
                     options: ImportOptions) -> ImportStats:
        """Import files, folders and in-memory bytes (see :class:`ImportBytes`).

        Named for its original argument; every source kind goes through the same
        pipeline, so a caller may mix them freely in one list.
        """
        self.begin_run(options)
        # The SAME look-ahead the folder walk gets. A list of files is what
        # the WEB import passes — its staging directory is flat, so those
        # sources never reach `_import_dir` — and what a shell glob gives the
        # CLI. Without this, the one caller most in need of it (a browser
        # handing over 200 files a batch) was the one path with no prefetch
        # at all: measured on 400 pictures, 5.3 s of import against the CLI's
        # 2.7 s for the same files, where the upload was 0.8 s of it.
        sources = list(paths)
        ahead = self._prefetch(sources)
        for i, p in enumerate(sources):
            self.add_source(p, options, prepared=ahead(i))
        return self.finish_run()

    def begin_run(self, options: ImportOptions) -> None:
        """Prime the caches and arm the commit cadence for a run.

        Split out of :meth:`import_paths` so a caller that discovers its
        sources one at a time (the scripting API's import run) pays the priming
        once instead of per source."""
        self._edit_enabled = self.config.edit_detect
        self._landed = ImportOutcome()
        self._landed_file_id: Optional[int] = None
        self._prepared: Optional[PreparedImage] = None
        self._move_sources = options.move
        # The ingest helpers run several frames below the call that carries the
        # options, so the run's options live on the importer for its duration.
        self._options = options
        # WHERE THIS RUN'S ITEMS GO — `parent_group_id`, or a box inside it.
        # Resolved once here rather than per source, so every source of one
        # run lands in the same group and an unnamed one is named once.
        self._run_group: GroupRef = options.parent_group_id
        if options.new_group:
            self._run_group = _LazyGroup(
                self, options.new_group_name.strip() or
                default_run_group_name(), "folder", options.parent_group_id)
        # The commit cadence clock starts at the run, not at construction.
        self._last_commit_processed = self.stats.processed
        self._last_commit_time = time.monotonic()
        self._leased = False
        # Sequence CONTAINERS the run mints — they are not in
        # `imported_item_ids` (the revert's trash list), but the run's tags
        # apply to them like any other item it created.
        self._new_containers: list[int] = []
        self._matched_item_ids: list[int] = []
        # Every stored file a source's bytes have landed on, in order. The
        # singular `_landed_file_id` answers "where did THIS source land" for
        # a still picture and cannot answer at all for a book of pictures,
        # which has no one file — so a caller recording where the bytes came
        # from needs the list. Appended in `_add_filename`, the one choke
        # point every landing branch passes through.
        self._landed_file_ids: list[int] = []
        self._tag_id_cache: dict[str, Optional[int]] = {}
        # The CURRENT source's result records — see `add_source`.
        self._entries: list[dict] = []
        self._leaf_sink: list[dict] = self._entries
        self._gated = False
        # The folder walk's look-ahead pool, built on first use.
        self._pool = None

    def add_source(self, source: "ImportSource",
                   options: ImportOptions,
                   prepared: Optional[PreparedImage] = None) -> ImportOutcome:
        """Import one source into a run opened by :meth:`begin_run`.

        Returns where it landed, so a caller holding one picture can go on to
        say something about it (a web source, a tag) without searching the
        library for what it just imported.

        ``prepared`` must be :func:`prepare_source`'s answer FOR THIS SOURCE
        (or None): the digest and hashes in it are trusted as the source's
        own, so a bundle from a different source would silently import the
        wrong identity.
        """
        self._landed_file_id = None
        self._landed = ImportOutcome()
        # Consumed by `_ingest_image`, which runs several frames below — the
        # same reason the run's options ride on the importer.
        self._prepared = prepared
        # THIS source's result records, taken by the caller afterwards
        # (`ImportRun._result`): a FLAT list of entries — one per file-shaped
        # thing the source turned out to contain, however deeply nested it
        # physically was — each with optional page/frame `children`. Leaf
        # landings go through `_leaf_sink`, which a book importer redirects
        # to its own children for the length of its page loop; the book's
        # own entry always lands on `_entries`, which is what keeps a book
        # inside a book a flat sibling rather than a deeper level.
        self._entries = []
        self._leaf_sink = self._entries
        # The write lease travels with the CHUNK — the boundary the commits
        # already have — so tenancy stays seconds even on a 500-file import,
        # and a concurrent process's writer queues at a chunk edge instead of
        # interleaving with half-imported state. Under the fresh lease the
        # schema version is re-checked: a chunk edge is exactly where a NEWER
        # build's migration can slot in (it takes this same lease for its
        # ladder), and an old build writing on into the upgraded format would
        # insert old-shape rows with no error anywhere — `db.
        # ensure_schema_current` says the rest. Released before raising, or
        # a caller that never reaches `finish_run` (the web import job) would
        # hold the lease for the life of its process.
        if not self._leased:
            instance.acquire_write_lease(self.config.data_dir)
            try:
                ensure_schema_current(self.session, "import run")
            except BaseException:
                instance.release_write_lease(self.config.data_dir)
                raise
            self._leased = True
            self._relax_durability()
        errors_before = len(self.stats.errors)
        root = self._run_group
        if isinstance(source, ImportBytes):
            self._import_bytes(source, root, options)
        else:
            p = Path(source)
            if p.is_dir():
                self._import_dir(p, root, options)
                self._landed = ImportOutcome(status="multi")
            elif p.is_file():
                self._import_file(p, root, options)
            else:
                self.stats.errors.append(f"not found: {p}")
        if len(self.stats.errors) > errors_before:
            return ImportOutcome(status="error", error=self.stats.errors[-1])
        out = self._landed
        if out.item_id is not None and out.file_id is None:
            out.file_id = self._landed_file_id
        return out

    def finish_run(self) -> ImportStats:
        self._print_stages()
        """Commit the run and release the write lease."""
        try:
            self._apply_import_tags()
            self.session.commit()
        finally:
            if getattr(self, "_leased", False):
                self._restore_durability()
                instance.release_write_lease(self.config.data_dir)
                self._leased = False
            self._stop_prefetch()
        return self.stats

    def _apply_import_tags(self) -> None:
        """The run's tags onto what it created — `ImportOptions.tags` on every
        created item and container, the per-kind lists on their kinds.

        Through `tagcatalog.get_or_create`, the one assignment door (alias
        redirection, the tag set's own advice); a refused name is SKIPPED, because a
        bad tag option must not fail an import that has already stored its
        files. No per-item events — the run's one `import` entry is the log,
        exactly as for the group memberships an import writes.
        """
        opts = getattr(self, "_options", None)
        matched = (list(getattr(self, "_matched_item_ids", []))
                   if opts is not None and opts.tags_existing else [])
        ids = list(dict.fromkeys(
            self.stats.imported_item_ids
            + list(getattr(self, "_new_containers", []))
            + matched))
        if opts is None or not ids:
            return
        base = _clean_tag_names(opts.tags)
        per_kind = {"image": _clean_tag_names(opts.tags_image),
                    "video": _clean_tag_names(opts.tags_video),
                    "sequence": _clean_tag_names(opts.tags_sequence)}
        if not base and not any(per_kind.values()):
            return
        s = self.session
        kinds = {}
        for chunk in chunked(ids):
            kinds.update(s.execute(
                select(Item.id, Item.kind).where(Item.id.in_(chunk))).all())
        want: list[tuple[int, int, bool]] = []
        for iid in ids:
            entries = base + per_kind.get(kinds.get(iid, ""), [])
            for name, negative in entries:
                tid = self._tag_id(name)
                if tid is not None:
                    want.append((iid, tid, negative))
        self.stats.tagged_pairs.extend(
            [iid, tid] for iid, tid, _n in self._assign_tag_pairs(want))

    def _tag_id(self, name: str) -> Optional[int]:
        """The tag a name assigns as, through the one assignment door
        (`tagcatalog.get_or_create` — alias redirection, the tag set's own
        advice), cached per run so a crawl minting one tag per domain resolves each
        name once. None for a refused name, which is SKIPPED — a bad tag must
        not fail an import that has already stored its files."""
        if name not in self._tag_id_cache:
            from .ops import tagcatalog
            from .ops.context import Ctx

            try:
                self._tag_id_cache[name] = tagcatalog.get_or_create(
                    Ctx(session=self.session), name).id
            except Exception:  # noqa: BLE001 - a refused name is skipped
                self._tag_id_cache[name] = None
        return self._tag_id_cache[name]

    def _assign_tag_pairs(self, want: "list[tuple[int, int, bool]]"
                          ) -> "list[tuple[int, int, bool]]":
        """Bulk-assign (item, tag, sign) rows: pairs the item already carries
        are left alone, items that no longer exist are dropped (a retried
        attempt's rolled-back ids), and the whole batch is one touch.
        No per-item events — the run's one ``import`` entry is the log, which
        is why the rows actually CREATED are returned: they are what it
        records."""
        want = list(dict.fromkeys(want))
        if not want:
            return []
        s = self.session
        ids = sorted({iid for iid, _t, _n in want})
        alive: set[int] = set()
        have: set[tuple[int, int]] = set()
        tag_ids = sorted({t for _, t, _n in want})
        for chunk in chunked(ids):
            alive.update(s.execute(
                select(Item.id).where(Item.id.in_(chunk))).scalars())
            have.update(s.execute(
                select(ItemTag.item_id, ItemTag.tag_id).where(
                    ItemTag.item_id.in_(chunk),
                    ItemTag.tag_id.in_(tag_ids))).all())
        fresh = [t for t in want
                 if t[0] in alive and (t[0], t[1]) not in have]
        s.add_all([ItemTag(item_id=iid, tag_id=tid, negative=negative)
                   for iid, tid, negative in fresh])
        if fresh:
            s.flush()
            touch_items(s, sorted({iid for iid, _t, _n in fresh}))
        return fresh


    # ---- groups ----

    def _match_video_frames(self, phash_int: int, w: int, h: int) -> dict[int, list[float]]:
        """Video items whose frames match ``phash_int`` AND have a roughly equal
        aspect ratio to a ``w``×``h`` image, mapped to the moments it is on
        screen (Hamming distance ≤ the near-dup threshold).

        ONE MOMENT PER APPEARANCE, not one per matching row. A picture stays on
        screen for a second or two and the index holds every run within it, so
        a screenshot matches a dozen rows in a row — and reporting all of them
        would put a dozen timestamps on one link and a dozen rows in the stills
        list for a picture that appears once. `_appearances` cuts the hits at
        `FRAME_APPEARANCE_GAP` and keeps the BEST-matching moment of each, so a
        shot that comes back later in the film is still two answers.
        """
        hits: dict[int, list[tuple[float, int]]] = {}
        aspect = w / h if h else 0.0
        for vid, ts, fa, d in find_frames(
            self.session, phash_int, self.config.phash_threshold
        ):
            if not _aspect_close(aspect, fa):
                continue
            hits.setdefault(vid, []).append((ts, d))
        return {vid: _appearances(v) for vid, v in hits.items()}

    def _link_image_to_video(self, image_item_id: int, video_item_id: int,
                             timestamps: list[float]) -> None:
        """Upsert a ``frame`` link image → video, merging ``timestamps`` (rounded)
        into its ``{"timestamps": [...]}`` metadata. No-op for a self-link."""
        if image_item_id == video_item_id:
            return
        rel = self.session.execute(
            select(Relationship).where(
                Relationship.from_item_id == image_item_id,
                Relationship.to_item_id == video_item_id,
                Relationship.kind == "frame",
            )
        ).scalars().first()
        existing: list[float] = []
        if rel is not None and rel.meta:
            try:
                existing = list(json.loads(rel.meta).get("timestamps", []))
            except (ValueError, TypeError):
                existing = []
        merged = sorted({round(t, 2) for t in existing + list(timestamps)})
        meta = json.dumps({"timestamps": merged})
        if rel is None:
            self.session.add(Relationship(
                from_item_id=image_item_id, to_item_id=video_item_id,
                kind="frame", meta=meta,
            ))
        else:
            rel.meta = meta
        self.session.flush()

    def _apply_video_frame_matches(self, item_id: int, phash_int: int,
                                   w: int, h: int,
                                   hits: dict[int, list[float]] | None = None
                                   ) -> None:
        """Link ``item_id`` (a just-imported image) to any video whose sampled
        frames it matches — the "imported a screenshot from a video" case.

        ``hits`` is the answer where the caller has already asked (the ingest
        path asks before deciding whether this picture may be folded into
        another item at all); recomputing it would be a second scan of the
        frame index per file.
        """
        matched = self._match_video_frames(phash_int, w, h) if hits is None else hits
        for vid, tss in matched.items():
            self._link_image_to_video(item_id, vid, tss)

    def _is_film_frame(self, file_id: int) -> bool:
        """Is the item this file belongs to a moment of some film?

        Any `frame` link out of it says so — one the importer wrote when it
        matched this picture to a video, or one the annotator wrote when
        somebody kept the frame as a still. Both mean the same thing here.
        """
        f = self.session.get(File, file_id)
        if f is None:
            return False
        return self.session.execute(
            select(Relationship.id).where(
                Relationship.from_item_id == f.item_id,
                Relationship.kind == "frame",
            )
        ).first() is not None

    def _same_pixels(self, file_id: int, incoming: Image.Image) -> bool:
        """The stored file and this picture, to the byte. No tolerance: the
        callers that want tolerance use `_verify`."""
        f = self.session.get(File, file_id)
        if f is None:
            return False
        try:
            other = self._file_image(f)
        except (OSError, media.MediaError):
            return False
        return other.size == incoming.size and other.tobytes() == incoming.tobytes()

    def _file_image(self, f: File) -> Image.Image:
        """Load a File's pixels from its item folder."""
        if f.path:
            return Image.open(
                self.store.path_of(self.session, f)
            ).convert("RGB")
        raise media.MediaError(f"cannot load image for file {f.id}")

    def get_or_create_group(self, name: str, icon: str,
                            parent_id: Optional[int]) -> int:
        """Reuse a same-named group under ``parent_id``, else create one."""
        stmt = select(Group.id).where(Group.name == name)
        if parent_id is None:
            # A "root" group: has no parent edges.
            candidates = self.session.execute(stmt).scalars().all()
            for gid in candidates:
                has_parent = self.session.execute(
                    select(GroupParent.id).where(GroupParent.group_id == gid)
                ).first()
                if not has_parent:
                    return gid
        else:
            candidates = self.session.execute(stmt).scalars().all()
            for gid in candidates:
                edge = self.session.execute(
                    select(GroupParent.id).where(
                        GroupParent.group_id == gid,
                        GroupParent.parent_group_id == parent_id,
                    )
                ).first()
                if edge:
                    return gid
        group = Group(name=name, icon=icon)
        self.session.add(group)
        self.session.flush()
        if parent_id is not None:
            self.session.add(
                GroupParent(group_id=group.id, parent_group_id=parent_id)
            )
        self.stats.groups_created += 1
        return group.id

    def _add_filename(self, file_id: int, name: str, fresh: bool = False) -> None:
        """Record ``name`` as a source filename for a stored file.

        Each (file, name) pair is stored once, but a fresh import under the same
        name refreshes its timestamp — so an item's newest/oldest import dates
        (derived from these rows) reflect the most recent time it was seen, and
        re-importing an existing image floats it to the top of a newest-first
        sort (DESCRIPTION §Content Area).

        Also where the run RECORDS which files a source landed on
        (`_landed_file_ids`): every branch that lands a source on a stored
        file calls this — the new item, the near-dup alternative, the
        reoriented copy and the exact duplicate that stores nothing — which
        is exactly the set of files "where did these bytes come from" is
        about, and what `ImportResult.files` reports for the bulk provenance
        ops to write against.
        """
        if name:
            # `.first()` (not scalar_one): a URL source may legitimately exist
            # several times under the same name with different access times.
            # `fresh`: the file row was made a moment ago in this very
            # savepoint, so no name of it exists yet and the lookup is a round
            # trip for a known answer.
            row = None if fresh else self.session.execute(
                select(FileName).where(
                    FileName.file_id == file_id, FileName.name == name
                )
            ).scalars().first()
            if row is None:
                self.session.add(FileName(file_id=file_id, name=name))
            else:
                row.created_at = datetime.now(timezone.utc)
        # Where this source LANDED, for a caller that wants a handle back
        # (`Importer.add_source`). Recorded here because this is the one place
        # every branch passes through — the new item, the near-dup
        # alternative, the reoriented copy and the exact duplicate alike.
        self._landed_file_id = file_id
        # And the same answer in the plural, which is the one a source with
        # no single file can give: an archive's pages, a GIF's frames, a
        # video. Truncated with the savepoint in `_import_file`, so a file
        # that was rolled back is not reported as stored.
        self._landed_file_ids.append(file_id)

    # ---- the size / shape gate ----

    def _gate_reason(self, width: int, height: int) -> Optional[str]:
        """Why the run would turn a picture of this size away — or None.

        A REASON rather than a bool, because there are two kinds of answer
        now and the one recorded against the source is the one somebody reads
        to find out what happened to it.

        Under ANY of the minimums: they are minimums a file must clear,
        exactly as the Storage page's prune rule reads them
        (`ops.files.PruneRule`), so setting a second one is strictly more
        selective than either alone — and the aspect range narrows it again.

        A size nothing could read — a 0 anywhere — never trips the gate: a
        picture the importer cannot measure is one it has no opinion about,
        and dropping it would turn "too small" into "unreadable header". That
        covers the aspect test twice over, since a 0 height is also the
        division it must not do.
        """
        o = self._options
        if not o.has_gate or width <= 0 or height <= 0:
            return None
        if o.min_megapixels > 0 and (
                width * height < int(round(o.min_megapixels * 1_000_000))):
            return SIZE_REJECTED
        if o.min_short_edge > 0 and min(width, height) < o.min_short_edge:
            return SIZE_REJECTED
        if o.min_long_edge > 0 and max(width, height) < o.min_long_edge:
            return SIZE_REJECTED
        aspect = width / height
        if o.min_aspect > 0 and aspect < o.min_aspect:
            return ASPECT_REJECTED
        if o.max_aspect > 0 and aspect > o.max_aspect:
            return ASPECT_REJECTED
        return None

    def _kind_bucket(self, path: Path, options: ImportOptions,
                     kind: Optional[str] = None) -> str:
        """Which of `ImportOptions.ignore_kinds`' four this source is.

        ``kind`` is `media.classify`'s answer when the caller already has it —
        it reads the file, and the dispatch above has usually just asked.
        """
        kind = kind or media.classify(path)
        if kind in ("pdf", "gif"):
            return "sequence"
        if kind == "archive":
            return ("sequence"
                    if media.is_comic(path) or options.archive_sequences
                    else "archive")
        return kind          # "image", "video", or "other" (never ignored)

    def _ignored_kind(self, path: Path, options: ImportOptions,
                      kind: Optional[str] = None) -> bool:
        """Is this source a type the run was told to leave alone?"""
        return (bool(options.ignore_kinds)
                and self._kind_bucket(path, options, kind)
                in options.ignore_kinds)

    def _best_page(self, sizes: "list[tuple[int, int]]") -> "tuple[int, int]":
        """The page a SEQUENCE is judged by: the first one that clears the
        run's filters, else any of them (the book is ignored either way).

        Not "the largest": with three thresholds and an aspect range there is
        no single largest — the page with the most pixels need not be the one
        with the longest short edge, and neither need be the one shaped like
        the rest of the book — so the question is asked of each page instead,
        which is exactly what "kept whole if ANY page passes" means. `(0, 0)`
        for a book whose pages could not be measured at all, which the gate
        then lets through.
        """
        for wh in sizes:
            if self._gate_reason(*wh) is None:
                return wh
        return sizes[0] if sizes else (0, 0)

    def _ignore_source(self, name: str, why: str,
                       into_entries: bool = False) -> None:
        """Record one source the gate turned away — for its size, its shape,
        or for being a type the run leaves alone (`why` says which).

        Its OWN status, `ignored` — not `skipped`, which means "nothing the
        importer handles", and not `duplicate`, which means "the library
        already has these bytes". All three store nothing, and telling them
        apart is the difference between "this app cannot read it", "you
        already have it" and "you told me not to".
        """
        self.stats.ignored += 1
        # What `_landed_multi` reads: a book or a video the gate refused has
        # imported nothing, so it must not be stamped `multi` — and a
        # move-import must not delete a source it never took (`ignored` is
        # not in the list of statuses that take one).
        self._gated = True
        self._landed = ImportOutcome(status="ignored")
        rec = {"status": "ignored", "item_id": None, "file_id": None,
               "name": name, "error": why}
        (self._entries if into_entries else self._leaf_sink).append(rec)
        self._progress(name)

    def _archive_page_sizes(self, path: Path) -> "list[tuple[int, int]]":
        """The sizes of an archive's own image members, for the gate.

        It UNPACKS THE ARCHIVE A SECOND TIME, and only when a minimum is set:
        the members have to exist as files to be read, and the alternative is
        a second implementation of `media.iter_archive`'s format dispatch —
        one more place for zip / cbr / 7z to disagree, to save an unpack that
        nobody pays for unless they asked for the gate. What it reads is
        headers, not pictures.

        DIRECT image members only. Anything else inside — a nested archive, a
        PDF, a video — is a flat sibling entry with a gate of its own, not one
        of this book's pages.
        """
        out: "list[tuple[int, int]]" = []
        try:
            for _inner, member in media.iter_archive(path):
                if media.classify(member) == "image":
                    size = media.image_size(member)
                    if size is not None:
                        out.append(size)
        except media.MediaError:
            # Unreadable is not "too small": the import runs and reports the
            # failure where it always did.
            return []
        return out

    def _landed_multi(self) -> None:
        """A folder, an archive, a video: several items, so there is no single
        one to point at. NOT when the gate turned the source away — it stays
        `skipped`, which is also what keeps a move-import from deleting a file
        it never took."""
        if not self._gated:
            self._landed = ImportOutcome(status="multi")

    def _record_leaf(self, status: str, item_id: Optional[int] = None,
                     file_id: Optional[int] = None, name: str = "",
                     error: str = "", derived: bool = False) -> None:
        """Record one LANDING for the current source's result: a page, a
        frame, a whole picture — wherever bytes met an item. Appends to
        `_leaf_sink`, which is the source's flat entry list except while a
        book importer has redirected it to its own children."""
        rec: dict = {"status": status, "item_id": item_id, "file_id": file_id,
                     "name": name}
        if error:
            rec["error"] = error
        if derived:
            # A file DERIVED from the source (a materialized video frame)
            # rather than a copy of its bytes — excluded from
            # `ImportResult.files`, the provenance walk.
            rec["derived"] = True
        self._leaf_sink.append(rec)

    @contextmanager
    def _collect_into(self, sink: "list[dict]") -> "Iterator[list[dict]]":
        """Redirect leaf recording into ``sink`` for the length of the block —
        how a book importer gathers its pages as children, and how a
        non-sequence archive flattens its members into the source's own
        entries whatever level it was found at."""
        parent = self._leaf_sink
        self._leaf_sink = sink
        try:
            yield sink
        finally:
            self._leaf_sink = parent

    def _touch_imported(self, item_id: int) -> None:
        """Record that ``item_id`` was seen during this import, refreshing its
        ``last_imported_at`` (drives the "Recently Imported" sort). ``created_at``
        is left untouched so it stays the item's first-seen time.
        """
        item = self.session.get(Item, item_id)
        if item is not None:
            item.last_imported_at = datetime.now(timezone.utc)
            # The run's "matched, not created" list — what `tags_existing`
            # extends the import tags over.
            self._matched_item_ids.append(item_id)

    def _note_if_out_of_sight(self, item_id: int, name: str) -> None:
        """Record a file that landed on an item the grid does not show.

        Called wherever an incoming picture joins an EXISTING item rather than
        making one — the exact duplicate and both alternative paths. A hidden
        item or one in the Trash is still a match, and folding onto it is still
        the right thing to do (the alternative is a second copy of a picture
        the library already has). What is wrong is doing it silently: the run
        reports success, and the picture is nowhere the grid can show it.
        """
        item = self.session.get(Item, item_id)
        if item is None:
            return
        # By ITEM id, not by `session.get`: `TrashedItem`'s primary key is its
        # own, so `get(TrashedItem, item_id)` asks whether some OTHER item's
        # trash row happens to have that rowid — which it does, all the time.
        trashed = self.session.execute(
            select(TrashedItem.id).where(TrashedItem.item_id == item_id)
        ).first()
        if trashed is not None:
            self.stats.hidden_matches.append((name, "trashed"))
        elif item.hidden:
            self.stats.hidden_matches.append((name, "hidden"))

    def _assign_group(self, item_id: int, group_ref: "GroupRef") -> None:
        group_id = _resolve_group(group_ref)
        if group_id is None:
            return
        exists = self.session.execute(
            select(ItemGroup.id).where(
                ItemGroup.item_id == item_id, ItemGroup.group_id == group_id
            )
        ).first()
        if not exists:
            self.session.add(ItemGroup(item_id=item_id, group_id=group_id))

    # ---- traversal ----

    def _import_dir(self, d: Path, parent: "GroupRef",
                    options: ImportOptions, rel: Optional[str] = None) -> None:
        # ``rel`` is the folder's path relative to the import root (starting at
        # the dropped/selected folder's own name), recorded as the source path
        # for the files below it, e.g. "ABC/sub/photo.jpg".
        rel = rel or d.name
        group: "GroupRef" = parent
        if options.folders_as_groups:
            # Lazy: the group is only created once a file actually lands in it.
            group = _LazyGroup(self, d.name, "folder", parent)
        entries = sorted(d.iterdir())
        ahead = self._prefetch(entries)
        for i, entry in enumerate(entries):
            if entry.is_dir():
                if options.recursive:
                    self._import_dir(entry, group, options,
                                     rel=f"{rel}/{entry.name}")
            elif entry.is_file():
                # The bundle for THIS file, hashed while the one before it was
                # being stored. `_ingest_image` consumes and clears it; the
                # clear here is for everything that never reaches it (a video,
                # an archive), where `prepare_source` answered None anyway —
                # so the clear makes that a fact rather than a coincidence.
                self._prepared = ahead(i)
                try:
                    self._import_file(entry, group, options,
                                      source_name=f"{rel}/{entry.name}")
                finally:
                    self._prepared = None

    #: How many upcoming files may be hashed ahead, and on how many workers.
    #: THE WINDOW IS THE CORES, and a bundle carries NO PIXELS. It was four,
    #: because a thread bundle held its decoded picture until its turn and
    #: this path is every folder import there is — it may not park a phone
    #: camera's worth of RGB per slot. Four workers hashed about a hundred
    #: pictures a second and the serial half spent 10 of a 19 s run waiting
    #: for them (2 000 crawl pictures, M4 Max). The bundle is the SLIM one
    #: now (`prepare_source_slim`: digest, hashes, canon, colour, metadata,
    #: the verifier's 3072 floats — a few kilobytes), and the one branch that
    #: wants pixels, the exact-pixel film-frame check, decodes the file again
    #: through `rgb()`. `MEDIA_COMPOST_IMPORT_PREFETCH` says otherwise.
    _PREFETCH_WINDOW = max(0, int(os.environ.get("MEDIA_COMPOST_IMPORT_PREFETCH")
                                  or min(32, max(4, os.cpu_count() or 4))))

    def _prefetch(self, entries):
        """Hash the next few STILL IMAGES on workers, in the caller's order.

        The per-source arithmetic — sha256, decode, pHash, colour signature,
        the eight orientation hashes, the metadata read — reads no library
        state, so it can run while the serial half stores the file before it.
        That is what `ImportRun.add_many` already does for a caller feeding
        sources one at a time (the crawler script's shape); a FOLDER reaches
        that path as a single source and was walked serially, so the CLI's
        `import` — and the web import's staging directory — got none of it.

        Order is the sorted walk's, exactly: what is submitted ahead is only
        submitted, and each file is still imported when the loop reaches it.
        A worker that dies costs that file its prefetch and nothing else — the
        serial path reads it as it does for anything with no bundle.
        """
        pool = self._prefetch_pool(len(entries))
        if pool is None:
            return lambda _i: None
        pending: dict = {}
        nxt = [0]

        def fill():
            while len(pending) < self._PREFETCH_WINDOW and nxt[0] < len(entries):
                i = nxt[0]
                nxt[0] += 1
                if _prefetchable(entries[i]):
                    pending[i] = pool.submit(prepare_source_slim, entries[i])

        def take(i):
            fill()
            fut = pending.pop(i, None)
            fill()
            if fut is None:
                return None
            try:
                return self._wait(fut)
            except Exception:  # noqa: BLE001 - a prefetch, never the import
                return None

        return take

    def _wait(self, fut):
        """The bundle, when the pool has it — the serial half's WAIT for the
        prefetch, which the profile times."""
        if not self._PROFILE:
            return fut.result()
        return self._timed("prefetch-wait", fut.result)()

    #: A folder of at least this many entries is hashed in PROCESSES, a
    #: smaller one on threads. Threads share the serial half's GIL: with
    #: sixteen of them decoding, the serial half's own work — SQLAlchemy,
    #: mostly — stretched by a third and the run gained nothing from four
    #: more workers (2 000 crawl pictures, M4 Max: 12.8 s at 16 threads,
    #: 13.5 with the serial path trimmed). A spawned pool costs ~0.4 s to
    #: come up and pickles ~10 KB a picture, which a handful of files does
    #: not earn. `ImportRun.add_many` has had the same switch, opt-in; a
    #: folder gets it by size. `MEDIA_COMPOST_IMPORT_THREADS=1` keeps threads.
    _PROCESSES_FROM = 32
    #: A BOOK's pages or members go to PROCESSES only past this many:
    #: MEASURED (M4 Max), threads beat the spawned pool for a 100-picture
    #: cbz (0.8 s against 1.4) and a 300-page PDF (4.9 s against 6.2) — a
    #: pool of interpreters importing the package costs more than the
    #: hashing of a few hundred pages, where a folder's rule above was
    #: measured over thousands of files on a machine whose threads starved
    #: the serial half.
    _PROCESSES_FROM_BOOK = 1000

    def _prefetch_pool(self, count: int = 0):
        """One pool for the whole RUN, built on first use and shut down by
        `finish_run` — a deep tree of small folders must not pay a pool per
        directory. PROCESSES for a run worth it (`_PROCESSES_FROM`), spawned
        — never forked: a fork copies a live SQLite connection and the
        library's own daemon threads into a child that will never run them,
        the classic way to get a corrupt file out of a working program."""
        from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

        want_procs = (count >= self._PROCESSES_FROM
                      and not os.environ.get("MEDIA_COMPOST_IMPORT_THREADS"))
        if self._pool is not None:
            # The run's first prefetch is over its top-level sources — ONE
            # folder, a thread pool — and the folder's own two thousand
            # entries arrive at the next call: a thread pool is traded up
            # for processes then, once, rather than kept for the run.
            if want_procs and isinstance(self._pool, ThreadPoolExecutor):
                self._pool.shutdown(wait=True)
                self._pool = None
            else:
                return self._pool
        if self._PREFETCH_WINDOW <= 0:
            return None

        workers = min(self._PREFETCH_WINDOW, max(1, os.cpu_count() or 1))
        if workers < 2:
            return None
        if want_procs:
            import multiprocessing
            try:
                self._pool = ProcessPoolExecutor(
                    max_workers=workers,
                    mp_context=multiprocessing.get_context("spawn"))
                return self._pool
            except Exception:  # noqa: BLE001 - threads are always right
                pass
        self._pool = ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="import-prefetch")
        return self._pool

    def _stop_prefetch(self):
        """Not `cancel_futures`: what is in flight is pure arithmetic on files
        this run has already read, and letting it finish costs less than the
        bookkeeping to abandon it."""
        pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=True)

    #: How often one file's import is re-attempted after a transient
    #: "database is locked" before the error is recorded for real.
    _LOCKED_RETRIES = 3

    #: THE RUN'S CONNECTION SYNCS THE WAL AT CHECKPOINTS, NOT AT EVERY FILE.
    #: A file's savepoint is its own commit (the rule above it: do not fix
    #: that), and in WAL mode at `synchronous=FULL` every commit fsyncs the
    #: log: 7 ms a picture on the 5090 box's encrypted btrfs, 14 s of a 25 s
    #: run of 2 000 (a Mac's APFS answers an fsync in a fraction of a
    #: millisecond, so it never showed there). `NORMAL` keeps the database
    #: consistent through a crash or power loss — the WAL is still synced at
    #: every checkpoint — and can lose only the last commits before a power
    #: loss, which for an import is files the next run imports again. Set on
    #: THIS session's connection for the run, restored with the lease.
    _RELAXED_SYNC = "NORMAL"

    def _relax_durability(self) -> None:
        try:
            conn = self.session.connection()
            self._sync_before = conn.exec_driver_sql("PRAGMA synchronous").scalar()
            conn.exec_driver_sql(f"PRAGMA synchronous={self._RELAXED_SYNC}")
        except Exception:  # noqa: BLE001 - a run is not worth failing for this
            self._sync_before = None

    def _restore_durability(self) -> None:
        before = getattr(self, "_sync_before", None)
        if before is None:
            return
        try:
            self.session.connection().exec_driver_sql(f"PRAGMA synchronous={int(before)}")
        except Exception:  # noqa: BLE001
            pass
        self._sync_before = None

    #: Files between commits (or two seconds, whichever first).
    _COMMIT_EVERY = max(1, int(os.environ.get("MEDIA_COMPOST_IMPORT_COMMIT_EVERY") or 20))

    #: `MEDIA_COMPOST_IMPORT_PROFILE=1` prints, at `finish_run`, how the
    #: SERIAL half of the run divided its time — the wait for the prefetch,
    #: the near-dup probes, the copy, the rows and flushes, the metadata
    #: index, the commits — so an import's shape can be read on a machine
    #: this repository cannot see (the job pipeline's variable is
    #: `MEDIA_COMPOST_JOB_PROFILE`; the two are read the same way). The
    #: stages are the run's own methods and collaborators, wrapped on THIS
    #: importer at construction, so the hot path carries no timers of its
    #: own when the variable is unset.
    _PROFILE = bool(os.environ.get("MEDIA_COMPOST_IMPORT_PROFILE"))

    def _timed(self, name: str, fn):
        def wrapped(*a, **kw):
            t = time.perf_counter()
            try:
                return fn(*a, **kw)
            finally:
                self._stages[name] = self._stages.get(name, 0.0) + time.perf_counter() - t
        return wrapped

    def _profile_hooks(self) -> None:
        for name, attr in (("probe-frames", "_match_video_frames"),
                           ("probe-files", "_gate_candidates"),
                           ("verify", "_verify"),
                           ("same-pixels", "_same_pixels"),
                           ("probe-edits", "_find_edit_original"),
                           ("filename", "_add_filename"),
                           ("index-edit", "_index_edit"),
                           ("group", "_assign_group"),
                           ("frames-apply", "_apply_video_frame_matches"),
                           ("record", "_record_leaf"),
                           ("progress", "_progress"),
                           ("classify", "_ignored_kind"),
                           ("TOTAL import-file", "_import_file"),
                           ("TOTAL ingest", "_ingest_image"),
                           ("dir-walk", "_import_dir")):
            setattr(self, attr, self._timed(name, getattr(self, attr)))
        self.session.begin_nested = self._timed("savepoint-open", self.session.begin_nested)
        self.store.write_file = self._timed("copy", self.store.write_file)
        self.session.flush = self._timed("flush", self.session.flush)
        self.session.commit = self._timed("commit", self.session.commit)
        self.session.execute = self._timed("execute", self.session.execute)
        g = globals()
        for name, fn in (("metadata", "index_file_metadata"),
                         ("find-files", "find_files"),
                         ("sha-file", "sha256_file"),
                         ("classify", "classify")):
            target = g if fn != "classify" else media.__dict__
            if fn in target:
                target[fn] = self._timed(name, target[fn])

    def _print_stages(self) -> None:
        if not self._PROFILE or not self._stages:
            return
        print("[import-profile] serial path, per stage: " + ", ".join(
            f"{k} {v:.1f}s" for k, v in sorted(self._stages.items(), key=lambda kv: -kv[1]))
              + f" (over {self.stats.processed} files)", file=sys.stderr, flush=True)
        self._stages.clear()

    def _import_file(self, path: Path, group: "GroupRef",
                     options: ImportOptions,
                     source_name: Optional[str] = None) -> None:
        try:
            # A SAVEPOINT per file: if one file blows up (unreadable, DB hiccup,
            # …) we roll back just that file and carry on with the rest of the
            # batch instead of aborting the whole import.
            #
            # AND THE SAVEPOINT IS ITS OWN COMMIT — pysqlite emits its
            # implicit BEGIN before DML only, never before a SAVEPOINT, so
            # this opens as the outermost transaction and its RELEASE
            # commits. That is load-bearing, not waste: the sync sidecar
            # writer runs at exactly that moment and reads the item back
            # from a FRESH session, so opening a real chunk transaction
            # first (tried, to save the per-file fsync — worth 0.26 s per
            # 199 files at a 1M library) left it reading nothing and every
            # imported item without an item.json.
            #
            # A TRANSIENT "database is locked" gets the file re-run instead of
            # lost: it means this chunk's FIRST write met a snapshot another
            # process's commit had just invalidated (an app open beside the
            # script — pysqlite begins deferred, and that upgrade ignores
            # `busy_timeout` by design, since the snapshot can never become
            # current). The savepoint has already rolled the file back; what
            # must ALSO end is the chunk transaction holding the stale
            # snapshot, or the retry meets the same refusal forever. COMMIT,
            # not rollback: earlier files of the chunk are applied work — and
            # a transaction that has written holds the write lock, nobody
            # else can have committed under it, so the collision can only
            # happen where the commit closes a read-only transaction and
            # loses nothing.
            for attempt in range(self._LOCKED_RETRIES + 1):
                # What the savepoint would undo. A rolled-back attempt has
                # already appended whatever files it wrote, and those rows
                # are about to stop existing — reported as stored they are a
                # handle to a deleted row, inside the slice of a source that
                # SUCCEEDED, so nothing else would flag it. (An attempt that
                # ends in an error is not that case: `add_source` reports the
                # whole source as an error and a failed result names no
                # files.) Usually invisible, because SQLite hands the retry
                # the rowid the rollback freed and the ids coincide — which
                # is a fact about rowid allocation and not one to build on.
                landed_mark = len(self._landed_file_ids)
                entry_mark = len(self._entries)
                try:
                    with self.session.begin_nested():
                        kind = media.classify(path)
                        # Per FILE, not per source: a folder walks through
                        # here once per file, and file 3's gate must not
                        # still be set while file 4 reports what it did.
                        self._gated = False
                        if self._ignored_kind(path, options, kind):
                            # A type the run leaves alone — asked before the
                            # file is opened for anything else, since the
                            # answer is its NAME (and, for an archive, one
                            # extension check).
                            self._ignore_source(
                                source_name or path.name,
                                "a file type this import leaves alone",
                                into_entries=True)
                        elif kind == "image":
                            self._ingest_image(
                                path, group,
                                source_name=source_name or path.name)
                        elif kind == "video":
                            self._import_video(path, group, options)
                            self._landed_multi()
                        elif kind == "archive":
                            self._import_archive(path, group, options)
                            self._landed_multi()
                        elif kind == "pdf":
                            self._import_pdf(path, group, options)
                            self._landed_multi()
                        elif kind == "gif":
                            self._import_gif(path, group, options)
                            self._landed_multi()
                        # 'other' is silently ignored (only compatible files
                        # are kept).
                    break
                except Exception as exc:  # noqa: BLE001 - see the retry note
                    del self._landed_file_ids[landed_mark:]
                    # The recording too: those rows are about to stop
                    # existing. (An exception unwinds every `_collect_into`
                    # on the way up, so the sink is already back on
                    # `_entries` by the time this runs.)
                    del self._entries[entry_mark:]
                    if (attempt >= self._LOCKED_RETRIES
                            or not is_locked_error(exc)):
                        raise
                    self._landed = ImportOutcome()
                    self.session.commit()
                    time.sleep(0.05 * (2 ** attempt))
            # The source is TAKEN only once the file is safely stored — and
            # for a duplicate too, whose bytes the library provably already
            # holds. Leaving those behind would mean a move-import of an inbox
            # tidied everything except the duplicates, which are exactly the
            # files it was most wanted for. Done here rather than inside
            # `write_file` because the readers below it — the hash, the
            # thumbnail, the EXIF — are still holding the path open.
            if self._move_sources and self._landed.status in (
                    "imported", "alternative", "duplicate", "multi"):
                path.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001 - keep going past a bad file
            self.stats.errors.append(f"{path.name}: {exc}")
        finally:
            self.stats.processed += 1
            self._progress(path.name)
            # Periodic commit: durability for long imports and bounds the size
            # of the open transaction / savepoint stack. 20 files or 2 s since
            # the last commit, whichever comes first — 200 files of large
            # photos held a write transaction open for minutes.
            now = time.monotonic()
            if (
                self.stats.processed - self._last_commit_processed >= self._COMMIT_EVERY
                or now - self._last_commit_time >= 2.0
            ):
                self.session.commit()
                self._last_commit_processed = self.stats.processed
                self._last_commit_time = now
                # A chunk ends at its commit; let queued writers through.
                if self._leased:
                    instance.release_write_lease(self.config.data_dir)
                    self._leased = False

    def _import_bytes(self, src: ImportBytes, group: "GroupRef",
                      options: ImportOptions) -> None:
        """Import in-memory bytes by staging them as a real file.

        Everything below `_import_file` reads from a path — Pillow, ffprobe,
        the archive readers — so the one honest way to give bytes the *same*
        import (dedup, EXIF metadata, GPS place, rotation detection, archives,
        sequences) is to give them a file to be read from. The stage lives in
        the data dir, so the store's copy into the item folder is a same-device
        copy, and it is removed again whatever happens; what stays in the
        library is the copy `ItemStore` writes, like any other import.
        """
        name = _stage_name(src.name)
        if media.classify(Path(name)) == "other":
            # Either no extension or one that doesn't match the bytes; the
            # content decides, since the extension is what the readers key off.
            ext = media.sniff_ext(src.data)
            if not ext:
                self.stats.processed += 1
                self.stats.errors.append(f"{name}: unrecognized file type")
                self._progress(name)
                return
            name = f"{Path(name).stem or GENERIC_IMPORT_NAME}.{ext}"
        stage_root = self.config.import_stage_dir
        stage_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(stage_root)) as tmp:
            # A directory of its own so the staged file keeps the name it
            # will be listed under — it is what the errors, the progress
            # line and the item's own name are taken from.
            staged = Path(tmp) / name
            staged.write_bytes(src.data)
            self._import_file(staged, group, options, source_name=name)

    def _import_video(self, path: Path, parent: "GroupRef",
                      options: ImportOptions,
                      source_name: Optional[str] = None) -> None:
        """Store the video once, then match each frame to existing images.

        The video becomes one video Item. Frames that match an existing image are
        materialized as an alternative source file of that image (a real PNG in
        its item folder, with ``video_frame`` provenance); no item is created for
        unmatched frames. Matched images form a sequence (and, with
        ``folders_as_groups``, a group) named after the video.
        """
        name = source_name or path.name
        # FILTERED OUT? Before the hash, like a picture's gate and for the
        # same reason — and the probe that answers it is the one the import
        # needs anyway, so nothing is read twice. A video is measured by its
        # frame, which is what "1080p" already means. Only when the run
        # filters on something: one without a filter must not pay an ffprobe
        # for a film it is about to recognize as a duplicate by its bytes.
        probed: "Optional[tuple[media.VideoInfo, list]]" = None
        if self._options.has_gate:
            probed = media.probe_video_full(path)
            why = self._gate_reason(probed[0].width or 0, probed[0].height or 0)
            if why:
                self._ignore_source(name, why, into_entries=True)
                return
        digest = sha256_file(path)
        # Byte-identical to a stored file? Same handling as an image duplicate:
        # no second copy, remember the (possibly new) name, refresh the import
        # date. Videos used to skip this entirely, so re-importing a film
        # stored the bytes again as a second item.
        existing = self.session.execute(
            select(File).where(File.sha256 == digest)
        ).scalars().first()
        if existing is not None:
            self._add_filename(existing.id, name)
            self._touch_imported(existing.item_id)
            self._note_if_out_of_sight(existing.item_id, name)
            self._assign_group(existing.item_id, parent)
            self.stats.skipped_duplicate += 1
            # Straight onto `_entries`, not the leaf sink: a video found
            # inside a book is a flat sibling entry, never one of its pages.
            self._entries.append({
                "status": "duplicate", "item_id": existing.item_id,
                "file_id": existing.id, "name": name})
            self._progress(name)
            return

        # The FULL probe: same single ffprobe run, and it also hands back what
        # the container says about itself (camera, capture date, codecs, audio).
        # Until this existed a video carried no indexed metadata at all. (The
        # gate above may have run it already; one probe either way.)
        info, vmeta = probed if probed is not None else media.probe_video_full(path)
        ext = ext_of(name) or "mp4"

        item = Item(name=name, kind="video")
        self.session.add(item)
        self.session.flush()
        rel = self.store.write_file(item.uid, 1, ext, src=path)
        vfile = File(
            item_id=item.id, sha256=digest, path=rel, number=1,
            source_kind="stored",
            duration=info.duration, frame_rate=info.frame_rate,
            bitrate=info.bitrate, width=info.width or 0, height=info.height or 0,
            bytes=path.stat().st_size, format=ext,
        )
        self.session.add(vfile)
        self.session.flush()
        item.active_file_id = vfile.id
        self._add_filename(vfile.id, name)
        index_file_metadata(self.session, self.store, vfile, values=vmeta)
        self._assign_group(item.id, parent)  # the video sits in the parent folder
        # Count the new item as IMPORTED: these two are what make the run log
        # an import event at all and what `_revert_import` walks — a video-only
        # import used to log nothing and could never be undone.
        self.stats.imported += 1
        self.stats.imported_item_ids.append(item.id)

        # What this file's frames need doing to them, worked out ONCE: it is an
        # `ffprobe` of its own (~42 ms) and it is the same answer for the
        # thumbnail, the scan and every matched frame. It used to be re-probed
        # per extraction — 11 probes for a video with 9 matches.
        cfilt = media.color_filter_for(path)

        # Thumbnail: a frame from the middle of the video, downscaled BY FFMPEG
        # rather than decoded at full resolution and resized here.
        try:
            thumb_im = media.extract_frame(
                path, (info.duration or 0.0) / 2,
                max_dim=self.config.thumb_size, color_filter=cfilt)
            self.store.ensure_thumb_from_image(vfile.id, vfile.sha256, thumb_im)
        except media.MediaError:
            pass

        # The video's own entry, with the matched-frame landings as its
        # children — collected below, appended once the scan is done. Straight
        # onto `_entries`: a video inside an archive is a flat sibling entry,
        # never a page of the book that contained it.
        frame_children: list[dict] = []

        # Match every frame against existing image items, and store each frame's
        # hash so a screenshot imported LATER can be matched back to this video.
        matched: dict[int, float] = {}  # item_id -> first matching timestamp
        # (item_id, frame_index, timestamp) for each newly matched item: the
        # full-resolution frames are extracted together once the scan is done
        # (see below), not one ffmpeg run at a time in the middle of it.
        wanted: list[tuple[int, int, float]] = []
        try:
            # Real video dims; frames are decoded small (aspect preserved), so the
            # frame's own size is not the video's — use the probe for records.
            vw, vh = info.width or 0, info.height or 0
            fa = vw / vh if vh else 0.0
            # EVERY FRAME IS HASHED — see `_new_run` for why sampling could not
            # be made to work, and what is stored instead.
            last: Optional[int] = None
            for idx, ts, frame in media.iter_video_frames(
                path, info.frame_rate, max_dim=FRAME_MATCH_MAX_DIM,
                color_filter=cfilt,
            ):
                phash = compute_phash_image(frame)
                phash_i = phash_to_int(phash)
                if not _new_run(last, phash_i):
                    continue
                last = phash_i
                # Persist the run's hash + the video's real size (every run,
                # matched or not). Flushed with everything else at the file's
                # savepoint; the probe below reads FILES, so nothing in this
                # loop needs the pending frame rows visible.
                self.session.add(VideoFrame(
                    video_item_id=item.id, video_file_id=vfile.id,
                    timestamp=ts, phash=phash, width=vw, height=vh,
                ))
                got = find_nearest_file(
                    self.session, phash_i, self.config.phash_threshold,
                )
                if got is None:
                    continue
                cand, cand_dist = got
                cand_file = self.session.get(File, cand)
                if cand_file is None or cand_file.item_id == item.id:
                    continue
                # A frame must not match an image of a clearly different shape
                # (a 16:9 blank frame vs an A4-portrait blank page).
                if not _aspect_close(fa, (cand_file.width / cand_file.height) if cand_file.height else 0.0):
                    continue
                # Link this existing image to the video (with the timestamp),
                # even for a second matching frame of an already-matched item.
                # The verifier downscales to 32×32, so the small frame is fine.
                if not self._verify(cand, lambda: norm_rgb(frame), cand_dist):
                    continue
                self._link_image_to_video(cand_file.item_id, item.id, [ts])
                if cand_file.item_id in matched:
                    continue
                matched[cand_file.item_id] = ts
                # The saved screenshot must be the real thing, so the frame is
                # re-extracted at FULL resolution — but AFTERWARDS, all of them
                # in one pass. Doing it here meant an ffmpeg run (and, before
                # `cfilt`, an ffprobe) per match in the middle of the scan:
                # ~192 ms each, 62% of the wall clock of a video with 9
                # matches.
                wanted.append((cand_file.item_id, idx, ts))
        except media.MediaError as exc:
            self.stats.errors.append(str(exc))

        # One decode pass for every matched frame — and one that selects by
        # frame INDEX, so what is stored is the frame that actually matched
        # rather than whatever a rounded three-decimal seek landed on.
        if wanted:
            try:
                frames = media.extract_frames(
                    path, [(idx, ts) for _iid, idx, ts in wanted],
                    color_filter=cfilt)
            except media.MediaError as exc:
                frames = {}
                self.stats.errors.append(str(exc))
            for item_id, idx, ts in wanted:
                full = frames.get(idx)
                if full is None:
                    continue
                frame_file = self._add_video_frame_file(
                    item_id, vfile.id, ts, full)
                # Byte identity wins over the perceptual match (see
                # `_add_video_frame_file`): the frame lives where its exact
                # bytes live, so the link, the touch and the child record
                # all follow the returned file's item.
                final_item = frame_file.item_id
                if final_item != item_id:
                    self._link_image_to_video(final_item, item.id, [ts])
                self._touch_imported(final_item)
                self.stats.frames_matched += 1
                # An "alternative" in the ordinary sense — a file joined an
                # existing item — but DERIVED from the source rather than a
                # copy of its bytes, which is what keeps it out of the
                # provenance walk (`ImportResult.files`).
                frame_children.append({
                    "status": "alternative", "item_id": final_item,
                    "file_id": frame_file.id,
                    "name": name, "derived": True})

        self._entries.append({
            "status": "imported", "item_id": item.id, "file_id": vfile.id,
            "name": name, "children": frame_children})

        # A video NEVER becomes a sequence. A sequence is something read in
        # order — a GIF's frames, a book's pages — and the frames a film
        # happens to match in the library are a scattered subset of it, not a
        # reading order (the same judgment that keeps captured stills out of
        # sequences, in `ui/ops/video.capture_frame`). The frame *references*
        # above are the record; `ImportOptions.video_sequences` and the
        # "Videos become sequences" toggle are gone with the build.
        self.stats.videos_split += 1

    def _add_video_frame_file(self, item_id: int, video_file_id: int,
                              timestamp: float,
                              frame: Image.Image) -> Optional[File]:
        """Materialize a matched video frame as an alternative source file of
        ``item_id`` (a real full-resolution picture in the item folder, with
        ``video_frame`` provenance so the UI can label it "frame @ Xs"). A
        byte-identical frame already in the library (e.g. from re-importing the
        same video) is not stored twice — the EXISTING file is returned, and
        BYTE IDENTITY IS AUTHORITATIVE: its item, not the perceptual match's,
        is where this frame lives. The two can disagree on exactly the
        content frame matching is about (near-identical items the film-frame
        rule keeps separate, with the nearest hash drifting between them as
        the index grows), and exact pixels are strictly stronger evidence
        than nearest-hash-plus-tolerant-verify — the same precedence the
        ordinary import gives its step 1. The caller follows the returned
        file's item for the link and the touch, which is what makes
        ``file.item`` always the matched item by construction. The pHash is
        computed from the stored (full-resolution) frame.

        Lossless, through `media.encode_lossless` — the same encoder a captured
        still and a PDF page go through, because this IS a captured still: the
        frame a film matched to a picture already here, kept beside it."""
        ext, data = media.encode_lossless(frame)
        digest = sha256_bytes(data)
        existing = self.session.execute(
            select(File).where(File.sha256 == digest)
        ).scalars().first()
        if existing is not None:
            return existing
        phash = compute_phash_image(frame)
        ckey, csig = color_signature(frame)
        uid = self.session.get(Item, item_id).uid
        number = next_file_number(self.session, item_id)
        rel = self.store.write_file(uid, number, ext, data=data)
        vf = File(
            item_id=item_id, sha256=digest,
            phash=phash, color_key=ckey, color_sig=csig,
            path=rel, number=number, source_kind="video_frame",
            source_file_id=video_file_id, source_start=timestamp,
            width=frame.width, height=frame.height, bytes=len(data),
            format=ext,
        )
        self.session.add(vf)
        self.session.flush()
        index_file_metadata(self.session, self.store, vf)
        # The materialized frame is what this counter reports (the CLI prints
        # it) — it sat at zero forever after the old frame-splitting path went.
        self.stats.frames_extracted += 1
        return vf

    def _import_archive(self, path: Path, parent: "GroupRef",
                        options: ImportOptions, depth: int = 0,
                        source_name: Optional[str] = None) -> None:
        """Import an archive: EVERY supported format inside it, not just the
        loose pictures. Each member goes to the branch its own kind calls for
        — an image through `_ingest_image`, a GIF/PDF/video/nested archive
        through its own importer — so a zip of PDFs imports the PDFs (it used
        to import NOTHING, near-silently: only image members were kept).

        The RESULT stays flat whatever the physical nesting: direct image
        members become this archive's pages (when it is a sequence) or
        entries of their own (when it is not), while a book or video found
        inside appends its own entry to `_entries` — a book inside a book is
        a flat sibling, never a member of the outer sequence, which is the
        rule that keeps the result's depth fixed at entries + children.

        Groups are unchanged: lazy, only for folders that end up with at
        least one importable file, and archive-internal folders still nest.
        ``depth`` guards hostile nesting (`_ARCHIVE_DEPTH_MAX`); a member too
        deep is recorded as skipped by name rather than opened. An
        unsupported member is a skipped entry too — hidden files and
        `__MACOSX` junk excepted, or every macOS zip would report its litter.
        """
        name = source_name or path.name
        # A NESTED archive's members are named through it — "inner.zip/x.png"
        # — so a flattened entry still says where it was found. Groups keep
        # reading the raw member path: the folders recreated are the inner
        # archive's own.
        prefix = f"{source_name}/" if source_name else ""
        group: "GroupRef" = (
            _LazyGroup(self, name, "folder_zip", parent)
            if options.archives_as_groups else parent
        )
        comic = media.is_comic(path)
        # Comics always become a sequence; other archives only when asked.
        sequence = comic or options.archive_sequences
        member_group = self._member_group(group, options)
        # A BOOK IS JUDGED WHOLE, by its largest page. A plain archive is not
        # a book: its members become items of their own, so each one answers
        # the gate itself, in `_ingest_image` below.
        if sequence and options.has_gate:
            sizes = self._archive_page_sizes(path)
            why = self._gate_reason(*self._best_page(sizes)) if sizes else None
            if why:
                self._ignore_source(name, why, into_entries=True)
                return
        pages: list[tuple[str, int]] = []  # (inner_name, item_id) for sequencing
        children: list[dict] = []
        # Direct image members: the book's pages, or flat entries of the
        # source when this archive is no sequence — explicitly `_entries`,
        # because a plain zip inside a comic must not donate its pictures to
        # the comic's page list.
        page_sink = children if sequence else self._entries
        failed = ""
        try:
            for inner_name, member, ahead in self._archive_members(path):
                # JUNK IS SKIPPED BEFORE ITS KIND IS ASKED. A macOS zip's
                # `__MACOSX/._005.jpg` is an AppleDouble resource fork
                # wearing the picture's own extension, so by extension it
                # classifies as an IMAGE — and tested only in the
                # unsupported-kind branch below (where this rule used to
                # live), every such member reached the decoder and reported
                # "cannot read image ._005.jpg", one error line per page of
                # a Viz volume. Hidden files (`.DS_Store`, `._x`) and
                # anything under `__MACOSX` are not members of the book
                # whatever they are called.
                if _archive_junk(inner_name):
                    continue
                kind = media.classify(member)
                # A MEMBER of this book follows the sequence's member group;
                # something that becomes an item of ITS own (a nested book, a
                # video) is not part of the sequence and keeps the archive's.
                base: "GroupRef" = (member_group if sequence and kind == "image"
                                    else group)
                sub_parent: "GroupRef" = base
                if options.folders_as_groups and "/" in inner_name \
                        and base is not None:
                    # Recreate the archive's internal folders as nested groups.
                    # Not below a member group of NONE: "the items join no
                    # group" cannot mean "a group per folder inside the book".
                    for part in inner_name.split("/")[:-1]:
                        sub_parent = _LazyGroup(self, part, "folder", sub_parent)
                # A MEMBER that becomes an item of its own answers the type
                # filter too — but a PAGE of this book never does, or
                # ignoring images would hollow out a comic. (The nested
                # book/video/archive cases are items of their own whatever
                # this archive is, so they always ask.)
                if self._ignored_kind(member, options, kind) and (
                        kind != "image" or not sequence):
                    with self._collect_into(page_sink):
                        self._ignore_source(
                            prefix + inner_name,
                            "a file type this import leaves alone")
                    continue
                if kind == "image":
                    # Keep the member's relative path inside the archive as its
                    # source name (e.g. "sub/photo.jpg").
                    self._prepared = ahead()
                    with self._collect_into(page_sink):
                        item_id = self._ingest_image(
                            member, sub_parent,
                            source_name=prefix + inner_name,
                            # A page of this book has been judged with it;
                            # a member of a plain archive is its own item.
                            gate=not sequence,
                        )
                    if sequence and item_id is not None:
                        pages.append((inner_name, item_id))
                elif kind == "gif":
                    self._prepared = None
                    self._import_gif(member, sub_parent, options,
                                     source_name=prefix + inner_name)
                elif kind == "pdf":
                    self._import_pdf(member, sub_parent, options,
                                     source_name=prefix + inner_name)
                elif kind == "video":
                    self._import_video(member, sub_parent, options,
                                       source_name=prefix + inner_name)
                elif kind == "archive":
                    if depth + 1 >= _ARCHIVE_DEPTH_MAX:
                        self.stats.errors.append(
                            f"{inner_name}: archive nested too deep")
                        self._entries.append({
                            "status": "skipped", "item_id": None,
                            "file_id": None, "name": prefix + inner_name,
                            "error": "archive nested too deep"})
                        continue
                    self._import_archive(member, sub_parent, options,
                                         depth=depth + 1,
                                         source_name=prefix + inner_name)
                else:
                    self._entries.append({
                        "status": "skipped", "item_id": None,
                        "file_id": None, "name": prefix + inner_name})
            self.stats.archives_expanded += 1
        except media.MediaError as exc:
            failed = str(exc)
            self.stats.errors.append(str(exc))
        container_id = None
        if sequence and pages:
            container_id = self._build_comic_sequence(
                name, pages, self._container_group(parent, group, options))
        if sequence:
            self._entries.append({
                "status": "multi", "item_id": container_id, "file_id": None,
                "name": name, "children": children, "error": failed})
        elif failed:
            # A flattened archive has no entry of its own to carry the
            # failure, so the failure gets one.
            self._entries.append({
                "status": "error", "item_id": None, "file_id": None,
                "name": name, "error": failed})

    def _import_pdf(self, path: Path, parent: "GroupRef",
                    options: ImportOptions,
                    source_name: Optional[str] = None) -> None:
        """Every page becomes an ordinary image item, and the pages a sequence.

        `_import_archive`'s shape exactly, because a PDF IS an archive of
        pictures as far as this library is concerned — the only difference is
        that its pages are rendered rather than unpacked, which is
        `media.iter_pdf_pages`' business. Going through `_ingest_image` per
        page is what gives them dedup, hashing, colour keys, thumbnails and
        everything else a picture gets; a PDF-shaped ingest path of its own
        would have to grow all of that again.

        A PDF is ALWAYS a sequence, like a comic archive and for the same
        reason: its pages are a thing read in order, and that is what a PDF is.
        """
        name = source_name or path.name
        # Judged whole, like any other book — and by arithmetic rather than by
        # rendering it twice: `iter_pdf_pages` scales every page to the same
        # long side, so `pdf_page_sizes` already knows what the pages will be.
        if options.has_gate:
            sizes = media.pdf_page_sizes(path)
            why = self._gate_reason(*self._best_page(sizes)) if sizes else None
            if why:
                self._ignore_source(name, why, into_entries=True)
                return
        group: "GroupRef" = (
            _LazyGroup(self, name, "folder_zip", parent)
            if options.archives_as_groups else parent
        )
        member_group = self._member_group(group, options)
        pages: list[tuple[str, int]] = []
        children: list[dict] = []
        failed = ""
        try:
            with self._collect_into(children):
                for page_name, page_path in self._pdf_pages(path):
                    item_id = self._ingest_image(
                        page_path, member_group, source_name=page_name,
                        gate=False)
                    if item_id is not None:
                        pages.append((page_name, item_id))
            self.stats.archives_expanded += 1
        except media.MediaError as exc:
            failed = str(exc)
            self.stats.errors.append(f"{name}: {exc}")
        container_id = None
        if pages:
            container_id = self._build_comic_sequence(
                name, pages, self._container_group(parent, group, options),
                kind="pdf")
        self._entries.append({
            "status": "multi", "item_id": container_id, "file_id": None,
            "name": name, "children": children, "error": failed})

    def _archive_members(self, path: Path):
        """``(inner_name, member_path, ahead)`` for every member, extracted
        by `media.extract_archive` and HASHED AHEAD on the run's look-ahead
        pool as a folder's files are: ``ahead()`` answers the member's
        bundle (or None). The window runs `_PREFETCH_WINDOW` members past
        the one being imported; the extracted files live for the whole
        loop.

        MEASURED (M4 Max, a 100-picture cbz): 18 ms a picture serial
        against 6-10 for the same pictures in a folder — the hashing was on
        the serial thread, the pool idle.
        """
        with media.extract_archive(path) as members:
            pool = self._prefetch_pool(
                len(members) if len(members) >= self._PROCESSES_FROM_BOOK else 0)
            pending: dict = {}
            nxt = [0]

            def fill():
                while (pool is not None and nxt[0] < len(members)
                       and len(pending) < self._PREFETCH_WINDOW):
                    i = nxt[0]
                    nxt[0] += 1
                    member = members[i][1]
                    if _prefetchable(member) and media.classify(member) == "image":
                        pending[i] = pool.submit(prepare_source_slim, member)

            def take(i):
                fut = pending.pop(i, None)

                def ahead():
                    if fut is None:
                        return None
                    try:
                        return self._wait(fut)
                    except Exception:  # noqa: BLE001 - a prefetch, never the import
                        return None
                return ahead

            fill()
            for i, (inner_name, member) in enumerate(members):
                ahead = take(i)
                fill()
                yield inner_name, member, ahead

    def _pdf_pages(self, path: Path):
        """``(page_name, page_path)`` for every page, RENDERED AND HASHED
        AHEAD on the run's look-ahead pool (`_render_and_prepare`), each
        page's bundle handed to `_ingest_image` as a folder's files are.

        MEASURED (M4 Max, a 100-page PDF of photographs): 100 ms a page
        serial, of which 64 was the render and the lossless encode and the
        rest the hashing — none of it library state, all of it done here
        on the serial thread while the workers sat idle. Pages are consumed
        in order; a page whose worker failed is rendered here instead.
        """
        n = media.pdf_page_count(path)
        pool = self._prefetch_pool(n if n >= self._PROCESSES_FROM_BOOK else 0)
        with tempfile.TemporaryDirectory(prefix="mc_pdf_") as td:
            pending: dict = {}
            nxt = 0

            def fill():
                nonlocal nxt
                while (pool is not None and nxt < n
                       and len(pending) < self._PREFETCH_WINDOW):
                    pending[nxt] = pool.submit(_render_and_prepare,
                                               str(path), nxt, td)
                    nxt += 1

            fill()
            for i in range(n):
                fut = pending.pop(i, None)
                fill()
                bundle = None
                out = None
                if fut is not None:
                    try:
                        out_s, bundle = self._wait(fut)
                        out = Path(out_s)
                    except Exception:  # noqa: BLE001 - render it here instead
                        out, bundle = None, None
                if out is None:
                    out = media.render_pdf_page(path, i, Path(td))
                self._prepared = bundle
                try:
                    yield out.name, out
                finally:
                    self._prepared = None
                    out.unlink(missing_ok=True)

    def _import_gif(self, path: Path, parent: "GroupRef",
                    options: ImportOptions,
                    source_name: Optional[str] = None) -> None:
        """Every frame becomes an ordinary image item, and the frames a sequence.

        `_import_pdf`'s shape, and the same argument one format along: an
        animated GIF is a run of pictures, not a film. It USED to import as a
        video item — and no browser plays a GIF in a `<video>` element, so the
        preview overlay, the annotator and the video editor were each a black
        rectangle over an item nothing could open. Nothing about the video
        pipeline applies to it either: ffprobe reports no usable frame rate,
        the frame index is built for matching screenshots to films, and a
        rendered cut would have to be re-encoded into a real video format.

        As frames it is what the library already knows how to hold: each one
        goes through `_ingest_image`, so they dedup, hash, thumbnail and tag
        like any picture — a GIF that holds one drawing on screen for a second
        collapses onto ONE item held at several positions, which is exactly
        what a sequence's repeated members are for — and the sequence is the
        order they play in.

        ALWAYS a sequence, like a PDF and a comic archive: the frames are a
        thing read in order and there is nothing else they could be.
        """
        name = source_name or path.name
        # Judged whole, and one header read answers for every frame: a GIF's
        # frames are composited onto the file's own canvas, so they are all
        # that size.
        if options.has_gate:
            size = media.image_size(path)
            why = self._gate_reason(*size) if size is not None else None
            if why:
                self._ignore_source(name, why, into_entries=True)
                return
        group: "GroupRef" = (
            _LazyGroup(self, name, "folder_zip", parent)
            if options.archives_as_groups else parent
        )
        # The run's prefetched bundle belongs to the GIF as a whole; the frames
        # are not it. `prepare_source` answers None for an animated gif, so
        # this is normally already clear — the clear is what makes it a fact
        # rather than a coincidence (see `_ingest_image`'s note).
        self._prepared = None
        member_group = self._member_group(group, options)
        frames: list[tuple[str, int]] = []
        children: list[dict] = []
        failed = ""
        try:
            with self._collect_into(children), \
                    media.iter_gif_frames(path) as rendered:
                for frame_name, frame_path in rendered:
                    item_id = self._ingest_image(
                        frame_path, member_group, source_name=frame_name,
                        gate=False)
                    if item_id is not None:
                        frames.append((frame_name, item_id))
            self.stats.archives_expanded += 1
        except Exception as exc:  # noqa: BLE001 - a bad GIF is one bad file
            failed = str(exc)
            self.stats.errors.append(f"{name}: {exc}")
        container_id = None
        if frames:
            container_id = self._build_comic_sequence(
                name, frames, self._container_group(parent, group, options),
                kind="gif")
        self._entries.append({
            "status": "multi", "item_id": container_id, "file_id": None,
            "name": name, "children": children, "error": failed})

    def _member_group(self, group: "GroupRef",
                    options: ImportOptions) -> "GroupRef":
        """Where a sequence's own ITEMS go — nowhere at all when the run
        says only the sequence itself joins groups.

        Items rather than pages: the same sequence machinery holds a comic's
        pages, a PDF's pages and an animated GIF's FRAMES, and only two of
        those are pages."""
        return None if options.sequence_grouping == "container" else group

    def _container_group(self, parent: "GroupRef", group: "GroupRef",
                         options: ImportOptions) -> "GroupRef":
        """Where a sequence's CONTAINER goes.

        The level the archive FILE sits at — so a book does not nest inside
        the group made of its own pages — and, when that level has no group,
        the archive's own group rather than nothing. That fallback is the
        fix for a real report: a PDF dropped on its own put its pages in a
        "book.pdf" group and left the sequence in no group at all, which
        reads as an import that lost the book.
        """
        if options.sequence_grouping == "members":
            return None
        return parent if parent is not None else group

    def _build_comic_sequence(self, name: str,
                              pages: list[tuple[str, int]],
                              group: "GroupRef",
                              kind: str = "archive") -> Optional[int]:
        """Mark comic pages as an ordered, numbered sequence (natural order).

        ``group`` is where the sequence *container* item is placed (see the
        caller — the archive's parent level, not the archive's own group).

        A page that DEDUPS onto an earlier one keeps its position: a book's
        three blank pages are one item at three positions, which is the whole
        reason a sequence may repeat an item. (They used to be collapsed to
        the first occurrence, and the book silently lost pages.)"""
        ordered = sorted(pages, key=lambda p: _natural_key(p[0]))
        member_ids = [item_id for _inner, item_id in ordered]

        # Re-import dedup: if a same-named archive sequence with the identical
        # member LIST already exists, don't create a second one — just refresh
        # its dates (like a byte-identical image re-import floats to the top).
        # An ordered list, not a set: [a, b, a] is not a re-import of [a, b].
        existing = self.session.execute(
            select(Sequence).where(
                Sequence.name == name, Sequence.kind == kind
            )
        ).scalars().all()
        for seq in existing:
            members = list(self.session.execute(
                select(SequenceItem.item_id)
                .where(SequenceItem.sequence_id == seq.id)
                .order_by(SequenceItem.position, SequenceItem.id)
            ).scalars().all())
            if members == member_ids:
                if seq.item_id is not None:
                    self._touch_imported(seq.item_id)
                for iid in dict.fromkeys(member_ids):
                    self._touch_imported(iid)
                return seq.item_id

        seq = Sequence(name=name, kind=kind, source_name=name)
        self.session.add(seq)
        self.session.flush()
        for pos, item_id in enumerate(member_ids):
            self.session.add(
                SequenceItem(sequence_id=seq.id, item_id=item_id, position=pos)
            )
            it = self.session.get(Item, item_id)
            if it is not None and it.main_sequence_id is None:
                it.main_sequence_id = seq.id
        self.session.flush()
        container = ensure_container(self.session, seq)
        self._new_containers.append(container.id)
        self._assign_group(container.id, group)
        self.stats.sequences_created += 1
        return container.id

    # ---- core image ingestion (dedup) ----

    def _ingest_image(self, path: Path, group: "GroupRef",
                      source_name: str | None = "__use_path__",
                      gate: bool = True) -> Optional[int]:
        """Ingest one image; return the id of the item it landed on (or None).

        ``gate`` is the run's size and shape filter, and it is OFF for a page
        of a sequence: a book is judged whole, so its own importer asks the
        question once and every page then comes in regardless
        (`ImportOptions.min_long_edge` and its siblings).
        """
        name = path.name if source_name == "__use_path__" else (
            source_name or path.name
        )
        # A prefetched bundle is consumed ONCE, by the source it was made for:
        # an archive's members reach this method too, and they must not read
        # the archive's own (prepare_source answers None for an archive, but
        # the clear is what makes that a fact rather than a coincidence).
        pre = self._prepared
        self._prepared = None
        # FILTERED OUT? Asked FIRST — before the hash, before any decode —
        # because it is a fact about the file rather than about what the
        # library makes of it: a picture the run filters out is not imported,
        # not folded into a near-duplicate, and not counted as a duplicate
        # that refreshes some existing item's dates. The header read costs
        # nothing (Pillow opens lazily) and a prefetched bundle has already
        # answered it.
        if gate and self._options.has_gate:
            size = ((pre.info.width, pre.info.height) if pre is not None
                    else media.image_size(path))
            why = self._gate_reason(*size) if size is not None else None
            if why:
                self._ignore_source(name, why)
                return None
        # Hash the bytes first so exact duplicates are recognized *without*
        # decoding the image at all — the dominant cost for large photos and for
        # re-imports of an existing library.
        digest = pre.digest if pre is not None else sha256_file(path)

        # 1. Exact duplicate?
        existing = self.session.execute(
            select(File).where(File.sha256 == digest)
        ).scalars().first()
        if existing is not None:
            # Byte-identical: no second copy, but remember the (possibly new)
            # filename it came in under so both names surface in the UI. Assign
            # the group last so lazy-group creation is the final DB op (keeping
            # it out of this file's rollback path — see _import_file's savepoint).
            self._add_filename(existing.id, name)
            self._touch_imported(existing.item_id)
            self._note_if_out_of_sight(existing.item_id, name)
            self._assign_group(existing.item_id, group)
            self.stats.skipped_duplicate += 1
            self._landed = ImportOutcome("duplicate", existing.item_id,
                                         existing.id)
            self._record_leaf("duplicate", existing.item_id, existing.id, name)
            self._progress(name)
            return existing.item_id

        # Not an exact dup: decode once and derive both metadata and pHash (and,
        # if needed, the secondary near-dup verification) from that single
        # decode — or take all of it from the prefetched bundle.
        decoded: Optional[Image.Image] = None
        if pre is not None:
            info, decoded = pre.info, pre.rgb
            phash, ckey, csig = pre.phash, pre.color_key, pre.color_sig
        else:
            try:
                info, decoded = media.load_rgb_with_info(path)
            except media.MediaError as exc:
                self.stats.errors.append(str(exc))
                self._record_leaf("error", name=name, error=str(exc))
                return None
            phash = compute_phash_image(decoded)
            ckey, csig = color_signature(decoded)

        def rgb() -> Image.Image:
            """The decoded picture, DECODED AGAIN if it has to be.

            A bundle prepared in another process carries the answers and not
            the pixels (`PreparedImage` says why), so the one branch that
            genuinely needs them — the exact-pixel film-frame check — reads
            the file back. Cached, because a branch may ask twice.
            """
            nonlocal decoded
            if decoded is None:
                decoded = media.load_rgb_with_info(path)[1]
            return decoded

        def rgbvec() -> "list[float]":
            """The near-dup verifier's 32x32 RGB vector for THIS picture —
            from the bundle where one rode along, else off the pixels."""
            if pre is not None and pre.rgb32:
                return list(pre.rgb32)
            return norm_rgb(rgb())

        _canon: Optional[object] = None

        def canon() -> "object":
            """The 48x48 `canon_thumb`, from the bundle or the pixels. One
            answer for the thumb LRU and the orientation record — cached,
            because a rotate/flip fold asks for both."""
            nonlocal _canon
            if _canon is None:
                _canon = (pre.canon if pre is not None
                          and pre.canon is not None else canon_thumb(rgb()))
            return _canon

        # What the bytes said about themselves, read by the prefetch. None
        # falls back to `index_file_metadata` reading the stored file, which
        # is what every caller without a bundle has always done.
        meta_values = pre.meta_values if pre is not None else None
        phash_int = phash_to_int(phash)
        ext = ext_of(path.name) or info.format

        # A FRAME OF A FILM IS A MOMENT, and two moments are two pictures.
        # Asked BEFORE the near-dup fold below, because that fold is what a run
        # of screenshots from one film used to disappear into: consecutive
        # frames are near-duplicates by construction, so importing twenty of
        # them produced ONE item with nineteen "alternative" source files on it
        # (reported as "images that match frames in a video are skipped"). The
        # near-dup rule is for the same picture at another size or encoding — a
        # claim nobody can make about two moments of a film.
        frame_hits = self._match_video_frames(phash_int, info.width, info.height)

        # 2. Near-duplicate -> alternative version of an existing item. The
        #    pHash only NOMINATES; the pixel check must agree before a merge.
        #    EVERY candidate within the threshold gets its turn, nearest hash
        #    first, until one passes — it used to be the single nearest
        #    alone, so a hash collision sitting closer than the true match
        #    silently cost the fold (watched happen in the collision-storm
        #    benchmark: a re-encoded pair imported as two items because a
        #    seeded collider out-neighboured the sibling). Two things are
        #    what make checking them all SAFE AND AFFORDABLE, and both are
        #    the owner's "reduce collisions instead of missing duplicates"
        #    rule. `_gate_candidates` prunes what the stored aspect and
        #    colour columns already rule out, so a storm mostly never
        #    decodes. And the verifier compares RGB, not grayscale — the
        #    first build of this loop merged three different solid-colour
        #    test photos whose GRAYS coincided (caught by the places suite),
        #    which is the pHash-degeneracy trade: more candidates must never
        #    mean wrong merges, so the verifier had to learn colour before
        #    the loop could exist (`dedup.norm_rgb`).
        #
        # And where EITHER side is a frame of a film, only an EXACT match
        # folds: a PNG and a WebP of one screenshot are one picture and belong
        # on one item, while everything else gets an item of its own. (An exact
        # BYTE match was already handled at step 1; this is the same pixels
        # through another encoder.)
        #
        # BOTH sides, because the frame index is sampled — a screenshot from a
        # moment between two samples matches nothing, and the picture it is a
        # near-duplicate OF is the screenshot imported a moment before it. So
        # the run collapsed anyway, one fold later: the first frame made an
        # item and every frame after it landed on that item as an
        # "alternative".
        similar_file_id: Optional[int] = None
        for cand_fid, cand_dist in self._gate_candidates(
            [(fid, d) for fid, _iid, d in find_files(
                self.session, [phash_int], self.config.phash_threshold)],
            aspect=(info.width / info.height) if info.height else 0.0,
        ):
            if ((frame_hits or self._is_film_frame(cand_fid))
                    and not self._same_pixels(cand_fid, rgb())):
                continue
            if self._verify(cand_fid, rgbvec, cand_dist):
                similar_file_id = cand_fid
                break
        if similar_file_id is not None:
            sim = self.session.get(File, similar_file_id)
            number = next_file_number(self.session, sim.item_id)
            rel = self.store.write_file(
                self.session.get(Item, sim.item_id).uid, number, ext, src=path
            )
            new_file = File(
                item_id=sim.item_id, sha256=digest, phash=phash,
                color_key=ckey, color_sig=csig, path=rel,
                number=number, width=info.width, height=info.height,
                bytes=path.stat().st_size, format=info.format,
            )
            self.session.add(new_file)
            self.session.flush()
            self._add_filename(new_file.id, name)
            # THE REPORTED BUG WAS HERE. This file's EXIF used to be read only
            # if it went on to become the active one — so the usual case, the
            # same picture re-saved with richer metadata folding in as an
            # alternative, stored the bytes and threw away everything they said.
            # It is read unconditionally now and kept on the file itself.
            index_file_metadata(self.session, self.store, new_file,
                                values=meta_values)
            # Cache the alternative's thumb too (a future rotation/flip could
            # match this version); it's the same item, so no relationship forms.
            self._index_edit(new_file, canon)
            # Make this newly-imported version the active source when it's a
            # better original than the current one (higher resolution, or a
            # less-compressed format / more bytes-per-pixel at ~equal resolution).
            self._maybe_promote_active(sim.item_id, new_file)
            self._touch_imported(sim.item_id)
            self._note_if_out_of_sight(sim.item_id, name)
            self._assign_group(sim.item_id, group)
            self._apply_video_frame_matches(sim.item_id, phash_int,
                                            info.width, info.height, frame_hits)
            self.stats.added_alternative += 1
            self._landed = ImportOutcome("alternative", sim.item_id)
            self._record_leaf("alternative", sim.item_id, new_file.id, name)
            self._progress(name)
            return sim.item_id

        # 3. Rotation/flip of an existing item? Fold the reoriented file into
        #    that item's source files rather than creating a separate linked
        #    item (a reorientation is just another representation of the same
        #    picture). The existing orientation stays the active source.
        edit_match = self._find_edit_original(
            rgb, phash_int, list(pre.dihedral) if pre is not None
            and pre.dihedral else None,
            size=(info.width, info.height))
        if edit_match is not None:
            target_iid, _transform = edit_match
            number = next_file_number(self.session, target_iid)
            rel = self.store.write_file(
                self.session.get(Item, target_iid).uid, number, ext, src=path
            )
            new_file = File(
                item_id=target_iid, sha256=digest, phash=phash,
                color_key=ckey, color_sig=csig, path=rel,
                number=number, width=info.width, height=info.height,
                bytes=path.stat().st_size, format=info.format,
            )
            self.session.add(new_file)
            self.session.flush()
            # Record the reoriented file's orientation relative to the item's
            # first source file, so the Source list can show its angle/flip. The
            # incoming bytes are already in that orientation (no re-encode).
            self._record_orientation(new_file, canon, target_iid)
            self._add_filename(new_file.id, name)
            # As above, and worse here: this branch never read the file's EXIF
            # at all, under any condition — a rotated copy carrying a better
            # capture date simply lost it.
            index_file_metadata(self.session, self.store, new_file,
                                values=meta_values)
            # Cache its thumb so a later rotation/flip of *this* variant is also
            # recognized as belonging to the same item.
            self._index_edit(new_file, canon)
            self._touch_imported(target_iid)
            self._note_if_out_of_sight(target_iid, name)
            self._assign_group(target_iid, group)
            self.stats.added_alternative += 1
            # The reorientation fold IS the edit link this counter reports —
            # it sat at zero forever, stored in every import event.
            self.stats.edit_links += 1
            self._landed = ImportOutcome("alternative", target_iid)
            self._record_leaf("alternative", target_iid, new_file.id, name)
            self._progress(name)
            return target_iid

        # 4. Brand new item.
        # ONE FLUSH for the item and its file: the uid is minted HERE
        # (`db.new_uid` — the column default runs at INSERT, not at
        # construction), so the folder can be written before either row
        # exists, and the file hangs off the item by RELATIONSHIP so the
        # flush that makes the item's id fills the file's `item_id` too. It
        # was two flushes, and every flush is a pass of the session's
        # listeners over everything dirty (measured: flushes were the
        # serial path's widest stage, 4.4 s of a 12.8 s run of 2 000).
        item = Item(name=name, uid=new_uid())
        rel = self.store.write_file(item.uid, 1, ext, src=path)
        new_file = File(
            item=item, sha256=digest, phash=phash,
            color_key=ckey, color_sig=csig, path=rel, number=1,
            width=info.width, height=info.height,
            bytes=path.stat().st_size, format=info.format,
        )
        self.session.add(item)
        self.session.add(new_file)
        self.session.flush()
        item.active_file_id = new_file.id
        self._add_filename(new_file.id, name, fresh=True)
        # Cache this file's thumb so rotations/flips of it fold into this item.
        self._index_edit(new_file, canon)
        # Index the file's static (EXIF) metadata. It is the active one, so this
        # also builds the item's own index off it.
        index_file_metadata(self.session, self.store, new_file,
                            values=meta_values, fresh=True)
        self._assign_group(item.id, group)
        # A screenshot grabbed from an already-imported video links back to it.
        self._apply_video_frame_matches(item.id, phash_int, info.width,
                                        info.height, frame_hits)
        self.stats.imported += 1
        self.stats.imported_item_ids.append(item.id)
        self._landed = ImportOutcome("imported", item.id)
        self._record_leaf("imported", item.id, new_file.id, name)
        self._progress(name)
        return item.id

    def _gate_candidates(self, cands: "list[tuple[int, int]]", *,
                         aspect: float,
                         rotations: bool = False) -> "list[tuple[int, int]]":
        """Hash-nominated ``(file id, distance)``, NEAREST FIRST, minus what the
        stored ASPECT RATIO already rules out — every survivor still gets its
        pixel check, so this can prune work and never an answer.

        Every check downstream is a full decode of a stored file, and on
        look-alike content the pHash nominates by the dozen (a storm of 25
        colliders per import measured ~110 ms apiece, all of it decoding), so
        a candidate that cannot possibly pass is dropped on a fact the
        `files` row already holds: a re-encode keeps the aspect and a
        reorientation at most swaps it (``rotations`` says whether the
        swapped one is also acceptable). Anything unknown — a zero dimension
        — passes, so a gate can only ever prune, never unmatch. Ties in
        distance break on the lower file id, which is `find_best_file`'s own
        earliest-inserted rule. (A COLOUR gate sat beside this one and was
        removed — the module constant's note above has the measurements.)

        The DISTANCE rides out with each survivor because the pixel bound
        depends on it (`Config.verify_mse`): the further out a candidate was
        nominated from, the better its pixels have to agree. Dropping it here
        is exactly how the verifier came to hold a candidate the hash was sure
        of and one at the very edge of the neighbourhood to the same bound.
        """
        if not cands:
            return []
        best: dict[int, int] = {}
        for fid, d in cands:
            if d < best.get(fid, 999):
                best[fid] = d
        rows: dict[int, tuple] = {}
        for chunk in chunked(sorted(best)):
            for fid, w, h in self.session.execute(
                select(File.id, File.width, File.height)
                .where(File.id.in_(chunk))
            ):
                rows[fid] = (w, h)
        out: list[tuple[int, int]] = []
        for fid, d in sorted(best.items(), key=lambda kv: (kv[1], kv[0])):
            got = rows.get(fid)
            if got is None:
                continue
            w, h = got
            ca = (w / h) if w and h else 0.0
            if not (_aspect_close(aspect, ca)
                    or (rotations and ca
                        and _aspect_close(aspect, 1.0 / ca))):
                continue
            out.append((fid, d))
        return out

    def _verify(self, candidate_file_id: int,
                vec: "Callable[[], list[float]]", distance: int) -> bool:
        """Confirm the incoming picture is really the same as a pHash candidate.

        ``vec`` answers with the incoming side's `dedup.norm_rgb` vector — a
        CALLABLE, so a bundle that carries one costs nothing and a verify that
        is switched off decodes nothing. ``distance`` is the candidate's own
        Hamming distance, which is what picks the bound — the further out it
        was nominated from, the better the pixels have to agree
        (`Config.verify_mse`). Returns True to allow a merge. Falls back to
        trusting the pHash if either side can't be loaded.
        """
        if not self.config.dedup_verify:
            return True
        cand = self.session.get(File, candidate_file_id)
        if cand is None:
            return False
        try:
            return verify_vec(
                vec(), self._file_image(cand), self.config.verify_mse(distance)
            )
        except (OSError, media.MediaError):
            return True

    # ---- rotate / flip relatives (original -> derived) ----

    def _index_edit(self, f: File,
                    canon: "Callable[[], object]") -> None:
        """Cache a small grayscale thumb of a stored image file so the rotate/flip
        pixel check can compare against it later without re-decoding. (The
        candidate *index* is the pHash index — this only pre-warms the thumb
        LRU from the already-decoded image.)

        ``canon`` answers with that thumb — from the prefetched bundle where
        one rode along, else off the pixels. It is the reason this runs for
        EVERY stored file without the picture having to be in memory: without
        it, one 9 KB array would have kept a 4.7 MB decode alive across the
        process boundary.
        """
        if not self._edit_enabled:
            return
        try:
            # (id, phash), not the bare id: `fileops` rewrites a file's
            # pixels in place (an in-place rotation) and reassigns the hash,
            # so under this key the stale thumb is simply never hit again —
            # which is what let the old invalidation channel be deleted.
            self._thumbs.put((f.id, f.phash), canon())
        except Exception:  # noqa: BLE001 - a decode failure just skips detection
            pass

    def _current_original(self, item_id: int) -> Optional[int]:
        # first(), not one: a library written before crops got their own
        # relationship kind can hold several backwards "edit" rows pointing at
        # one item, and a chain walk must degrade to picking the oldest rather
        # than erroring the import of an unrelated file.
        return self.session.execute(
            select(Relationship.from_item_id).where(
                Relationship.to_item_id == item_id,
                Relationship.kind == _EDIT_KIND,
            ).order_by(Relationship.id)
        ).scalars().first()

    def _root_original(self, item_id: int) -> int:
        """Climb the edit chain to its topmost original ancestor."""
        cur = item_id
        seen: set[int] = set()
        while cur not in seen:
            seen.add(cur)
            o = self._current_original(cur)
            if o is None:
                return cur
            cur = o
        return cur


    def _decode_thumb(self, f: File):
        """A file's 48x48 grayscale thumb, from the bounded LRU or decoded on
        demand (only candidates that actually get compared are ever decoded).
        Takes the ROW rather than the id: the cache key carries the phash
        (see `_index_edit`), which the row already knows."""
        key = (f.id, f.phash)
        thumb = self._thumbs.get(key)
        if thumb is not None:
            return thumb
        try:
            thumb = canon_thumb(self._file_image(f))
        except (OSError, media.MediaError, ValueError):
            return None
        self._thumbs.put(key, thumb)
        return thumb

    def _item_thumb(self, item_id: int):
        """The pixel thumb of an item's active file, from cache or decoded."""
        it = self.session.get(Item, item_id)
        if it is None or not it.active_file_id:
            return None
        f = self.session.get(File, it.active_file_id)
        return self._decode_thumb(f) if f is not None else None

    def _find_edit_original(
        self, image: "Callable[[], Image.Image]", phash_int: int,
        probes: "list[int] | None" = None,
        size: "tuple[int, int]" = (0, 0),
    ) -> Optional[tuple[int, str]]:
        """Detect whether an about-to-be-imported image is a rotation/flip of an
        existing item; return ``(item_id, transform)`` of that item, or None.

        Candidates come from the pHash index probed with the 8 dihedral hashes
        of the incoming image (:func:`dihedral_phashes`) — the old design
        ran the pixel check against EVERY stored file's thumb, an O(library)
        decode-and-compare per import. The orientation-invariant pixel check
        (:func:`whole_image_edit`) still has the final word on each candidate,
        so a hash collision can never fold two different pictures. This runs
        *before* the new file is created, so the caller can fold the reoriented
        file into the matched item's sources rather than spawning a separate
        linked item.

        ``probes`` is those 8 hashes when a prefetch has already computed them
        — which is most of the point of the prefetch, since hashing the eight
        orientations was 23% of a crawl import's wall clock. ``image`` is a
        CALLABLE rather than a picture because with them in hand this method
        usually never needs the pixels at all.
        """
        if not self._edit_enabled:
            return None
        if probes is None:
            try:
                probes = dihedral_phashes(image(), phash_int)
            except Exception:  # noqa: BLE001
                return None
        thr = self.config.phash_threshold
        # ONE query for all 8 dihedral probes (12 IN-clauses of 8 values),
        # already reduced to the minimum distance per candidate file.
        hits: list[tuple[int, int]] = [
            (fid, d)
            for fid, _iid, d in find_files(self.session, probes, thr)
        ]
        # Nearest hash first, minus what the stored aspect rules out — a
        # reorientation keeps the picture's aspect or swaps it, so a
        # candidate matching neither cannot pass the pixel check it would
        # otherwise cost a full decode to fail. Every survivor
        # IS checked: on look-alike content the pHash nominates by the dozen
        # and the checks are what a storm costs, but a candidate skipped on a
        # hash ordering alone could be the one genuine reorientation.
        w, h = size
        cand_fids = [fid for fid, _d in self._gate_candidates(
            hits, aspect=(w / h) if h else 0.0, rotations=True)]
        if not cand_fids:
            return None
        # The pixel thumb only once something nominated a candidate — which is
        # the rare case; computing it up front cost a full-size resize on
        # every brand-new image. (`image()` may decode the file again here,
        # for the same reason and just as rarely.)
        try:
            incoming = canon_thumb(image())
        except Exception:  # noqa: BLE001
            return None
        mse = self.config.edit_mse
        best_iid: Optional[int] = None
        best_transform: Optional[str] = None
        for fid in cand_fids:
            f = self.session.get(File, fid)
            # Same candidate set as the old thumb index: stored still images.
            if f is None or f.source_kind != "stored":
                continue
            ct = self._decode_thumb(f)
            if ct is None:
                continue
            t = whole_image_edit(incoming, ct, mse)
            if t in ("rotate", "flip"):
                # Anchor on the earliest-imported matching item (lowest id).
                if best_iid is None or f.item_id < best_iid:
                    best_iid, best_transform = f.item_id, t
        if best_iid is None:
            return None
        # Fold into the root of the matched cluster (older imports may carry
        # legacy edit chains).
        root = self._root_original(best_iid)
        transform = best_transform
        if root != best_iid:
            rt = self._item_thumb(root)
            if rt is not None:
                t = whole_image_edit(incoming, rt, mse)
                if t in ("rotate", "flip"):
                    transform = t
        return (root, transform or "rotate")

    @staticmethod
    def _is_higher_quality(cand: File, cur: File) -> bool:
        """True when ``cand`` is a better source image than ``cur``.

        Resolution dominates: a clearly larger image (>5% more pixels) always
        wins. At about the same resolution, a lossless/uncompressed format beats
        a lossy one, and failing that the file with more bytes-per-pixel (less
        aggressive compression) wins.
        """
        ca = (cand.width or 0) * (cand.height or 0)
        ua = (cur.width or 0) * (cur.height or 0)
        if ca and ua:
            if ca > ua * 1.05:
                return True
            if ua > ca * 1.05:
                return False
        elif ca != ua:
            return ca > ua
        cl = (cand.format or "").lower() in _LOSSLESS_FORMATS
        ul = (cur.format or "").lower() in _LOSSLESS_FORMATS
        if cl != ul:
            return cl
        cbpp = (cand.bytes or 0) / ca if ca else 0.0
        ubpp = (cur.bytes or 0) / ua if ua else 0.0
        return cbpp > ubpp

    def _first_file(self, item_id: int) -> Optional[File]:
        """The item's first stored still-image source (lowest id) — the
        orientation reference frame for every other file."""
        return self.session.execute(
            select(File).where(
                File.item_id == item_id,
                File.source_kind == "stored",
                File.path.isnot(None),
            ).order_by(File.id).limit(1)
        ).scalars().first()

    def _record_orientation(
        self, new_file: File, canon: "Callable[[], object]", item_id: int
    ) -> None:
        """Store ``new_file``'s orientation (rotation + mirror) relative to the
        item's first source file, detected from small grayscale thumbnails.

        ``canon`` answers with the incoming picture's `canon_thumb` — the
        bundle's where one rode along, so a rotate/flip fold no longer
        re-decodes the file on the serial thread just to orient it."""
        base = self._first_file(item_id)
        if base is None or base.id == new_file.id:
            return
        try:
            incoming = canon()
        except Exception:  # noqa: BLE001
            return
        base_thumb = self._decode_thumb(base)
        if base_thumb is None:
            return
        found = orient.detect_orientation(
            base_thumb, incoming, self.config.edit_mse
        )
        if found is not None:
            new_file.rotation, new_file.mirrored = int(found[0]), bool(found[1])

    def _maybe_promote_active(self, item_id: int, candidate: File) -> None:
        """Promote ``candidate`` to the item's active source if it's higher
        quality than the current active file (see :meth:`_is_higher_quality`).

        Never overrides a user's edit: if the active file is an edited/derived
        version, it stays active regardless of an incoming higher-quality import
        (the edit is the version the user wants to see). When the current active
        file is a reoriented base (shown rotated/flipped), promote a copy of the
        candidate baked to that same orientation so the display angle is kept."""
        item = self.session.get(Item, item_id)
        if item is None:
            return
        cur = (
            self.session.get(File, item.active_file_id)
            if item.active_file_id is not None else None
        )
        if cur is None:
            item.active_file_id = candidate.id
        elif not cur.is_derived and self._is_higher_quality(candidate, cur):
            if int(cur.rotation or 0) % 360 or cur.mirrored:
                # The item is displayed reoriented; bake a matching-orientation
                # copy of the higher-quality candidate and make that active.
                try:
                    oriented = make_oriented_file(
                        self.session, self.store, candidate,
                        int(cur.rotation or 0), bool(cur.mirrored),
                    )
                    item.active_file_id = oriented.id
                except (OSError, media.MediaError):
                    item.active_file_id = candidate.id
            else:
                item.active_file_id = candidate.id

    def _progress(self, name: str) -> None:
        if self.on_progress:
            self.on_progress(self.stats, name)

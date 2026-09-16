"""Intrinsic (live-computed) metadata names shared by the catalog and evaluator.

Metadata search is uniform in the query language — every condition is
``meta:name op value`` — but values come from two internal sources:

* **Intrinsic** names (defined here) are properties of an item's *active file*
  and can change on edit / rotate / active-file switch, so they are computed live
  from the file/item columns at query time (never indexed).
* **Indexed** names (EXIF and similar, in the ``item_metadata`` table) are static,
  written once at import.

The metadata catalog unions both so the UI treats every name identically.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # avoid import cycles at module load
    from datetime import datetime

    from .db import File

# Canonical intrinsic name -> value type. These names are reserved: an indexed
# (EXIF) name must never collide with one of them.
INTRINSIC: dict[str, str] = {
    "width": "numeric",
    "height": "numeric",
    "resolution": "numeric",  # megapixels
    "aspect": "numeric",
    "length": "numeric",      # seconds (video)
    "fps": "numeric",         # frames/sec (video)
    "bitrate": "numeric",     # Mbps (video)
    "type": "text",           # item kind: image / video / sequence
    "format": "text",         # active file's container format (PNG/JPEG/…)
    "id": "text",             # the item's uid (exact, or any part of it via "~")
    "import_date": "date",       # YYYYMMDDHHMMSS, from Item.created_at (first)
    "last_import_date": "date",  # YYYYMMDDHHMMSS, from Item.last_imported_at
    # Live counts over the item's current tag/caption state. NOT produced by
    # intrinsic_nums (they aren't file properties) — the search paths inject
    # them into QueryCtx.nums themselves (see items.py / scripting.py).
    "tag_count": "numeric",      # effective positive tags
    "caption_count": "numeric",  # non-pending captions (descriptions only)
    # Non-pending INSTRUCTIONS — a caption that says how the picture was made
    # from others. Counted apart from `caption_count` for the same reason the
    # two are two lists: an item may carry both, and each answers its own
    # question. An intrinsic name rather than a condition kind, so every
    # operator and the whole query builder work on it unchanged.
    "instruction_count": "numeric",
    "faces": "numeric",          # detected faces, not dismissed
    "unnamed_faces": "numeric",  # of those, the ones nobody has named
    # Live top-level text regions (OCR blocks) — blocks, not words, the same
    # number the Text tab's badge shows. ONE intrinsic where faces have a
    # pair: an unnamed face is work-left-to-do driving a review view, and a
    # text region has no such state (yet).
    "text_blocks": "numeric",
    # How many SEQUENCES the item is a member of — distinct sequences, so a
    # page repeated inside one chapter still counts it once.
    # `INFO:sequence_count=0` finds the loose pages, `>=2` the ones two books
    # share. An intrinsic name rather than a condition kind, like the counts
    # above, so every operator and the whole builder work unchanged.
    "sequence_count": "numeric",
    # HOW MANY SOURCE FILES the item holds — every row the Sources list shows,
    # the derived ones (an editor save, a rotation) and the alternatives a
    # near-dup fold added included. `INFO:file_count=1` is the ordinary
    # picture, `>=2` the ones carrying a second copy or an edit, and a
    # sequence CONTAINER answers 0 because it has no file of its own.
    # Artifacts are not files (they hang off one), so they are not counted.
    "file_count": "numeric",
}

INTRINSIC_NAMES = frozenset(INTRINSIC)


def intrinsic_nums(
    af: "File",
    last_imported_at: "Optional[datetime]",
    created_at: "Optional[datetime]" = None,
) -> dict[str, float]:
    """The intrinsic numeric/date metadata values for an item, keyed by canonical
    name.

    Mirrors the display/units used elsewhere: resolution in MP, bitrate in Mbps,
    dates as a sortable ``YYYYMMDDHHMMSS`` number. ``import_date`` is the first
    import (``created_at``); ``last_import_date`` is ``last_imported_at``.
    Missing values are 0.0."""
    w, h = af.width or 0, af.height or 0
    return {
        "width": float(w),
        "height": float(h),
        "resolution": (w * h) / 1_000_000.0,
        "aspect": (w / h) if h else 0.0,
        "length": float(af.duration or 0.0),
        "fps": float(af.frame_rate or 0.0),
        "bitrate": (af.bitrate / 1_000_000.0) if af.bitrate else 0.0,
        "import_date": float(created_at.strftime("%Y%m%d%H%M%S"))
        if created_at else 0.0,
        "last_import_date": float(last_imported_at.strftime("%Y%m%d%H%M%S"))
        if last_imported_at else 0.0,
    }


def intrinsic_texts(
    kind: "Optional[str]",
    af: "Optional[File]" = None,
    uid: "Optional[str]" = None,
) -> dict[str, str]:
    """The intrinsic *text* metadata values for an item: its media ``type``,
    its active file's ``format``, and its ``id`` (uid).

    ``format`` is intrinsic rather than indexed on purpose. It belongs to the
    *active* file, so it changes when the item is edited, rotated or switched
    to another source — an index written at import goes stale the moment a PNG
    edit becomes the active file, and the item then stops matching
    ``meta:format=PNG`` while the Metadata panel happily shows PNG.
    """
    return {
        "type": kind or "",
        "format": (af.format or "").upper() if af is not None else "",
        "id": uid or "",
    }

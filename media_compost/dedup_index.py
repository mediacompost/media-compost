"""The banded (LSH) layout over 256-bit perceptual hashes, and its SQL probe.

Each hash is cut into **12 disjoint bands** (three per 64-bit word: 22+21+21
bits, so no band straddles a word and every key is one shift and one mask).
Two hashes within Hamming distance ``d`` differ in ``d`` bit positions; spread
over 12 bands, if every band differed the total distance would be at least 12
— so by pigeonhole **any two hashes within distance <= 11 agree exactly on at
least one band**. Probing the 12 per-band lookups therefore yields a candidate
set that is a strict superset of every true match for any threshold up to 11
(``Config.phash_threshold`` is 10, and refuses to go higher than 11).
Exact Hamming distance is then computed over the few colliding candidates.

THE BUCKETS LIVE IN SQLITE, NOT IN MEMORY. This module used to hold two
in-process index classes (``PhashIndex``, ``VideoFrameIndex``) primed from the
DB at the start of every import — 17.7 s per process on a 1M-item library with
5M frame rows, plus ~200 MB of RAM per million frame rows, plus a whole
cache-coherency apparatus (a ``(count, max_id)`` reuse guard, an additive
append path, a flush-listener invalidation channel) to keep them honest.
The band keys are COLUMNS now — ``b0``..``b11`` on ``files`` and on
``video_frames``, filled by a ``before_flush`` listener in ``db.py`` and
indexed by ``Database._ensure_indexes`` — so a probe is 12 indexed lookups
against rows that are correct by construction: no priming, constant RAM, and
nothing to invalidate.

Band WIDTH is why this had to move with the storage. 16-bit bands returned
``N / 2**16`` rows per band — 1,466 candidates at 6M rows, every one a decode
risk — while these ~21-bit bands return ~29. But wide bands are unaffordable
in Python dicts (16.7M buckets averaging 1.4 entries measured 5,416 MB against
3,031 MB at 2M entries) and free in a B-tree, which is what a band index is.

The probes take the caller's ``Session`` and go through
``session.connection()`` — the same transaction, so rows flushed inside an
import run's savepoints are candidates before any commit, WITHOUT autoflush:
a probe never flushes pending state, so the frame-scan loop can probe between
``session.add`` calls without paying a flush per frame. Callers that need a
just-created row visible flush first, which every creation site already does.

``ThumbLRU`` stays here: it serves the rotate/flip pixel check, not the band
probe. It is keyed by ``(file_id, phash)`` now — a file whose pixels are
rewritten in place gets a new phash, so its stale thumb is simply never asked
for again and ages out of the cap. That keying is what let the invalidation
channel be deleted along with the indexes it existed for.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Iterable, Optional

#: 12 bands over 256 bits (dedup.HASH_SIZE**2): three per 64-bit word.
BANDS = 12

#: (bit offset, width) per band. 22+21+21 = 64, so no band straddles a word —
#: every key is one shift and one mask, on both the Python and the SQL side.
BAND_SPEC = tuple((w * 64 + off, width) for w in range(4)
                  for off, width in ((0, 22), (22, 21), (43, 21)))

BAND_MASKS = tuple((1 << width) - 1 for _off, width in BAND_SPEC)

#: The largest threshold the band structure guarantees completeness for
#: (pigeonhole over BANDS bands). There is no fallback past it any more —
#: ``Config.phash_threshold`` is bounded by it at load, and the probes below
#: REFUSE a larger threshold rather than silently missing matches.
MAX_BANDED_THRESHOLD = BANDS - 1

#: The band-key column names, in :data:`BAND_SPEC` order — one place, read by
#: the models, the flush listener, the migration backfill and the probe SQL.
BAND_COLUMNS = tuple(f"b{i}" for i in range(BANDS))


def band_keys(hash_int: int) -> "list[int]":
    """The 12 band keys of one 256-bit hash, in :data:`BAND_COLUMNS` order."""
    return [(hash_int >> off) & mask
            for (off, _w), mask in zip(BAND_SPEC, BAND_MASKS)]


def as_int(phash) -> int:
    """Accept a hash as an int or as the DB's hex-string form."""
    if isinstance(phash, str):
        return int(phash, 16)
    return int(phash)


# ---------------------------------------------------------------------------
# The probe
# ---------------------------------------------------------------------------

def _candidate_rows(session, table: str, cols: str, probes: "list[int]",
                    max_id: Optional[int]) -> list:
    """Rows of ``table`` sharing at least one band key with any probe,
    ``ORDER BY id`` — i.e. insertion order, which the tie-breaks rely on.

    One statement: 12 indexed subselects ``UNION``ed (UNION, not OR — the OR
    optimization can fall back to a scan, a union of index probes cannot; the
    duplicate a row hit through two bands is dedup'd by the UNION itself).
    The SQL text is constant per (probe count, max_id presence), so sqlite3's
    per-connection statement cache absorbs the parse on hot paths like the
    frame scan. ``cols`` must start with ``id`` for the ORDER BY.
    """
    per_band: list[list[int]] = [[] for _ in range(BANDS)]
    for p in probes:
        for b, key in enumerate(band_keys(p)):
            per_band[b].append(key)
    guard = " AND id <= ?" if max_id is not None else ""
    marks = ",".join("?" * len(probes))
    parts = []
    args: list[int] = []
    for b in range(BANDS):
        parts.append(f"SELECT {cols} FROM {table} "
                     f"WHERE b{b} IN ({marks}){guard}")
        args.extend(per_band[b])
        if max_id is not None:
            args.append(max_id)
    sql = " UNION ".join(parts) + " ORDER BY id"
    return session.connection().exec_driver_sql(sql, tuple(args)).fetchall()


def _check_threshold(threshold: int) -> None:
    if threshold > MAX_BANDED_THRESHOLD:
        raise ValueError(
            f"threshold {threshold} exceeds the band guarantee "
            f"({MAX_BANDED_THRESHOLD}); matches past it would be silently "
            "missed")


def find_files(session, probes: "Iterable[int]", threshold: int, *,
               max_id: Optional[int] = None) -> "list[tuple[int, int, int]]":
    """Every stored file within ``threshold`` of ANY probe hash, as
    ``(file_id, item_id, distance)`` in file-id (= insertion) order, with
    ``distance`` the minimum over the probes.

    ``probes`` is one hash for a near-dup lookup and the 8 dihedral hashes for
    rotate/flip detection — one query either way. ``max_id`` bounds the search
    to rows that existed at a caller-chosen moment (the sidecar restore, which
    must not merge one restored item onto another it created a moment ago).
    """
    _check_threshold(threshold)
    probe_ints = [as_int(p) for p in probes]
    if not probe_ints:
        return []
    out: "list[tuple[int, int, int]]" = []
    for fid, iid, ph in _candidate_rows(
        session, "files", "id, item_id, phash", probe_ints, max_id
    ):
        h = int(ph, 16)
        d = min((h ^ p).bit_count() for p in probe_ints)
        if d <= threshold:
            out.append((fid, iid, d))
    return out


def find_nearest_file(session, phash, threshold: int, *,
                      max_id: Optional[int] = None
                      ) -> "Optional[tuple[int, int]]":
    """``(file id, distance)`` of the nearest stored file within ``threshold``.

    Same answer as ``dedup.find_similar`` over a flat ``(id, phash)`` list in
    id order: nearest wins, ties go to the earliest-inserted (lowest id).

    The DISTANCE comes back because the pixel bound the caller then applies
    depends on it (`Config.verify_mse`) — a candidate at the very edge of the
    neighbourhood has to agree far better than one the hash was sure of."""
    best: "Optional[tuple[int, int]]" = None
    best_d = threshold + 1
    for fid, _iid, d in find_files(session, [phash], threshold,
                                   max_id=max_id):
        if d < best_d:
            best, best_d = (fid, d), d
            if d == 0:
                break
    return best


def find_best_file(session, phash, threshold: int, *,
                   max_id: Optional[int] = None) -> Optional[int]:
    """File id of the nearest stored file within ``threshold``, else None —
    `find_nearest_file` for a caller with no use for the distance."""
    got = find_nearest_file(session, phash, threshold, max_id=max_id)
    return None if got is None else got[0]


def find_frames(session, phash, threshold: int
                ) -> "list[tuple[int, float, float, int]]":
    """Every stored video-frame run within ``threshold`` of ``phash``, as
    ``(video_item_id, timestamp, aspect, distance)`` in row order.

    The aspect FILTER stays with the caller (it is import policy, not index
    structure); the frame's aspect rides along so applying it costs nothing.
    """
    _check_threshold(threshold)
    p = as_int(phash)
    out: "list[tuple[int, float, float, int]]" = []
    for _rid, vid, ts, ph, w, h in _candidate_rows(
        session, "video_frames",
        "id, video_item_id, timestamp, phash, width, height", [p], None,
    ):
        d = (int(ph, 16) ^ p).bit_count()
        if d <= threshold:
            out.append((vid, ts, (w / h if h else 0.0), d))
    return out


class ThumbLRU:
    """A bounded cache of decoded 48x48 grayscale thumbs, keyed by
    ``(file_id, phash)``.

    The rotate/flip detector used to backfill every compared thumb into an
    unbounded per-candidate list (~9 KB of float32 each — gigabytes at a
    million files). Bounded at 4096 entries this stays around 40 MB while
    still absorbing the repeated-candidate decodes within an import run.

    THE PHASH IS PART OF THE KEY, and that is what makes the cache safe to
    share for the life of a process: `fileops` really does rewrite a file's
    pixels in place (an in-place rotation), and a thumb cached under the bare
    file id then confirmed reorientations against pixels that no longer
    exist. The rewrite reassigns ``File.phash``, so under this key the stale
    entry is simply never hit again and ages out of the cap — no invalidation
    channel required.
    """

    __slots__ = ("_cap", "_data")

    def __init__(self, cap: int = 4096) -> None:
        self._cap = cap
        self._data: OrderedDict = OrderedDict()

    def __len__(self) -> int:
        return len(self._data)

    def get(self, key):
        thumb = self._data.get(key)
        if thumb is not None:
            self._data.move_to_end(key)
        return thumb

    def put(self, key, thumb) -> None:
        if thumb is None:
            return
        self._data[key] = thumb
        self._data.move_to_end(key)
        while len(self._data) > self._cap:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()

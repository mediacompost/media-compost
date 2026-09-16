"""The band-key probe must agree exactly with a brute-force scan using
dedup's own Hamming helpers as the oracle — same answers, same tie-breaks,
over rows written the way the app writes them (through the ORM, so the
``before_flush`` listener fills the band columns; nothing here sets a band
by hand)."""

from __future__ import annotations

import random

import pytest

from media_compost import dedup_index
from media_compost.config import Config
from media_compost.db import Database, File, Item, VideoFrame
from media_compost.dedup import find_similar, hamming
from media_compost.dedup_index import (
    BAND_COLUMNS,
    BAND_SPEC,
    BANDS,
    MAX_BANDED_THRESHOLD,
    ThumbLRU,
    band_keys,
    find_best_file,
    find_files,
    find_frames,
)


def _flip_bits(h: int, positions: list[int]) -> int:
    for p in positions:
        h ^= 1 << p
    return h


@pytest.fixture()
def s():
    db = Database.in_memory()
    session = db.session()
    yield session
    session.close()


def _add_file(s, h, item_id=None) -> int:
    """One File row through the ORM — the flush is what fills the bands."""
    if item_id is None:
        it = Item(name="i")
        s.add(it)
        s.flush()
        item_id = it.id
    f = File(item_id=item_id,
             sha256=f"{random.getrandbits(160):064x}",
             phash=None if h is None else f"{h:064x}",
             width=100, height=100, bytes=1, format="png")
    s.add(f)
    s.flush()
    return f.id


def _corpus(s, rng: random.Random, n: int = 120):
    """Random 256-bit hashes plus planted near-duplicates at every distance
    0..11 (including the distance-exactly-11 band-guarantee edge)."""
    it = Item(name="corpus")
    s.add(it)
    s.flush()
    entries: list[tuple[int, int]] = []
    for _ in range(n):
        h = rng.getrandbits(256)
        entries.append((_add_file(s, h, it.id), h))
    probes: list[int] = []
    for d in range(MAX_BANDED_THRESHOLD + 1):  # 0..11 inclusive
        _fid, base = entries[rng.randrange(len(entries))]
        probes.append(_flip_bits(base, rng.sample(range(256), d)))
    # A few probes with no planted relative at all.
    probes.extend(rng.getrandbits(256) for _ in range(10))
    return entries, probes


def test_find_best_and_find_files_agree_with_brute_force(s):
    rng = random.Random(42)
    entries, probes = _corpus(s, rng)

    for thr in range(MAX_BANDED_THRESHOLD + 1):
        for p in probes:
            assert find_best_file(s, p, thr) == find_similar(p, entries, thr)
            oracle = sorted(
                (i, hamming(p, h)) for i, h in entries if hamming(p, h) <= thr
            )
            mine = sorted((fid, d) for fid, _iid, d in find_files(s, [p], thr))
            assert mine == oracle


def test_distance_exactly_11_is_still_found(s):
    """The pigeonhole guarantee's edge: 11 differing bits over 12 bands leave
    at least one band untouched, so a distance-11 pair must never be missed."""
    rng = random.Random(7)
    it = Item(name="edge")
    s.add(it)
    s.flush()
    for trial in range(25):
        base = rng.getrandbits(256)
        near = _flip_bits(base, rng.sample(range(256), 11))
        fid = _add_file(s, near, it.id)
        got = find_files(s, [base], MAX_BANDED_THRESHOLD)
        assert (fid, it.id, 11) in got, f"trial {trial}"
        assert hamming(base, near) == 11  # the plant really is at 11


def test_ties_resolve_to_the_first_inserted_like_find_similar(s):
    base = random.Random(3).getrandbits(256)
    a = _flip_bits(base, [5])    # distance 1
    b = _flip_bits(base, [200])  # distance 1, inserted later
    fa = _add_file(s, a)
    fb = _add_file(s, b)
    assert fa < fb  # insertion order IS id order — the contract
    assert find_similar(base, [(fa, a), (fb, b)], 5) == fa
    assert find_best_file(s, base, 5) == fa


def test_exact_hit_beats_a_near_hit(s):
    rng = random.Random(11)
    h = rng.getrandbits(256)
    _add_file(s, _flip_bits(h, [3]))  # distance 1, inserted first
    exact = _add_file(s, h)           # distance 0
    assert find_best_file(s, h, 10) == exact


def test_a_flushed_uncommitted_row_is_probeable_at_once(s):
    """The importer probes between savepoints, before any commit — a flushed
    row must already be a candidate (and the probe itself must not flush:
    it reads the session's connection, never autoflushes)."""
    rng = random.Random(9)
    h = rng.getrandbits(256)
    assert find_best_file(s, h, 10) is None
    near = _flip_bits(h, [1, 100, 255])
    fid = _add_file(s, near)          # flushes, does not commit
    assert find_best_file(s, h, 10) == fid
    assert (fid, 3) in [(f, d) for f, _i, d in find_files(s, [h], 10)]


def test_hex_probes_are_accepted(s):
    """The DB stores phashes as hex strings; a probe may be one too."""
    rng = random.Random(5)
    h = rng.getrandbits(256)
    fid = _add_file(s, h)
    assert find_best_file(s, f"{h:064x}", 0) == fid


def test_a_null_phash_stores_null_bands_and_is_never_nominated(s):
    fid = _add_file(s, None)
    f = s.get(File, fid)
    assert all(getattr(f, c) is None for c in BAND_COLUMNS)
    assert find_files(s, [random.Random(6).getrandbits(256)],
                      MAX_BANDED_THRESHOLD) == []


def test_a_rewritten_phash_moves_the_bands_with_it(s):
    """`fileops` rewrites a file's pixels in place and reassigns the hash —
    the listener's dirty branch must move the band keys in the same flush,
    or the probe nominates the file by its pre-rotation hash forever."""
    rng = random.Random(13)
    old, new = rng.getrandbits(256), rng.getrandbits(256)
    fid = _add_file(s, old)
    f = s.get(File, fid)
    f.phash = f"{new:064x}"
    s.flush()
    assert [getattr(f, c) for c in BAND_COLUMNS] == band_keys(new)
    assert find_best_file(s, new, 0) == fid
    assert find_best_file(s, old, 0) is None


def test_a_threshold_past_the_guarantee_is_refused(s):
    """There is no full-scan fallback any more, so probing past the band
    guarantee would silently miss matches — it must refuse instead."""
    for fn in (lambda: find_files(s, [1], MAX_BANDED_THRESHOLD + 1),
               lambda: find_best_file(s, 1, MAX_BANDED_THRESHOLD + 1),
               lambda: find_frames(s, 1, MAX_BANDED_THRESHOLD + 1)):
        with pytest.raises(ValueError):
            fn()


def test_max_id_bounds_the_probe(s):
    """The sidecar restore probes under the pre-run high-water mark, so it
    can only ever merge onto what already existed."""
    rng = random.Random(17)
    h = rng.getrandbits(256)
    fid = _add_file(s, h)
    assert find_best_file(s, h, 0, max_id=fid) == fid
    assert find_best_file(s, h, 0, max_id=fid - 1) is None
    assert find_files(s, [h], 0, max_id=fid - 1) == []


def test_multi_probe_reduces_to_the_minimum_distance(s):
    """The 8 dihedral probes go out as ONE query; a candidate near several
    probes reports the distance of the nearest."""
    rng = random.Random(19)
    h = rng.getrandbits(256)
    fid = _add_file(s, h)
    p1 = _flip_bits(h, [1, 2, 3])            # distance 3
    p2 = _flip_bits(h, [7])                  # distance 1
    got = find_files(s, [p1, p2], 10)
    assert [(f, d) for f, _i, d in got] == [(fid, 1)]


def test_the_frame_probe_answers_with_moment_and_aspect(s):
    rng = random.Random(21)
    it = Item(name="film")
    s.add(it)
    s.flush()
    vfid = _add_file(s, None, it.id)
    h1, h2 = rng.getrandbits(256), rng.getrandbits(256)
    for ts, h, w, hh in ((1.5, h1, 1920, 1080), (3.0, _flip_bits(h1, [4]),
                                                 1920, 1080),
                         (0.0, h2, 640, 480)):
        s.add(VideoFrame(video_item_id=it.id, video_file_id=vfid,
                         timestamp=ts, phash=f"{h:064x}", width=w, height=hh))
    s.flush()
    hits = find_frames(s, h1, 10)
    assert (it.id, 1.5, 1920 / 1080, 0) in hits
    assert (it.id, 3.0, 1920 / 1080, 1) in hits
    assert all(a != 640 / 480 for _v, _t, a, _d in hits)


# ---------------------------------------------------------------------------
# The layout itself
# ---------------------------------------------------------------------------

def test_the_bands_partition_all_256_bits_without_straddling_a_word():
    covered: set[int] = set()
    for off, width in BAND_SPEC:
        # One band, one word: a key must stay one shift and one mask on both
        # the Python and the SQL side.
        assert off // 64 == (off + width - 1) // 64, (off, width)
        covered |= set(range(off, off + width))
    assert covered == set(range(256))
    assert len(BAND_SPEC) == BANDS == len(BAND_COLUMNS)
    assert MAX_BANDED_THRESHOLD == BANDS - 1


def test_every_configured_threshold_fits_under_the_guarantee():
    """`Config.phash_threshold` is bounded by the band guarantee — and the
    guarantee has no fallback, so this is what makes 'refused rather than
    silently incomplete' true.

    It used to check the search's cap against the same number, because
    `SIMILAR:` probed these very columns. That space is gone (the importer
    folds a re-encode onto the item it matches, so the search found the
    picture itself and nothing else), and the near-dup MATCH is the only
    reader of the guarantee now.
    """
    assert Config().phash_threshold <= MAX_BANDED_THRESHOLD
    with pytest.raises(ValueError):
        Config(phash_threshold=MAX_BANDED_THRESHOLD + 1)


def test_band_keys_matches_the_spec_by_hand():
    h = random.Random(29).getrandbits(256)
    for key, (off, width) in zip(band_keys(h), BAND_SPEC):
        assert key == (h >> off) % (1 << width)


# ---------------------------------------------------------------------------
# ThumbLRU
# ---------------------------------------------------------------------------

def test_thumb_lru_is_bounded_and_recency_ordered():
    lru = ThumbLRU(cap=3)
    for k in (1, 2, 3):
        lru.put((k, "h"), f"t{k}")
    assert lru.get((1, "h")) == "t1"    # touch 1 -> 2 is now the oldest
    lru.put((4, "h"), "t4")             # evicts 2
    assert len(lru) == 3
    assert lru.get((2, "h")) is None
    assert lru.get((1, "h")) == "t1" and lru.get((4, "h")) == "t4"
    lru.put((5, "h"), None)             # a failed decode is not cached
    assert len(lru) == 3
    lru.clear()
    assert len(lru) == 0 and lru.get((1, "h")) is None


def test_thumb_lru_keys_carry_the_phash_so_a_rewrite_misses():
    """The invalidation channel's replacement: an in-place pixel rewrite
    reassigns the file's phash, so the stale thumb is simply never asked
    for again."""
    lru = ThumbLRU(cap=8)
    lru.put((1, "old-hash"), "stale")
    assert lru.get((1, "new-hash")) is None
    assert lru.get((1, "old-hash")) == "stale"

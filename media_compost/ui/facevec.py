"""Vectorized face-descriptor arithmetic: matrices, blocked cosine, optional ANN.

The scalar reference lives in :mod:`media_compost.faces` (``similarity``,
``best_match``, ``cluster_spaces``) and stays the DEFINITION of the rules; this
module reproduces those answers over numpy matrices so a library of tens of
thousands of faces clusters in milliseconds instead of minutes. Descriptors are
raw float32 bytes compared by cosine, so a matrix of L2-normalized rows turns
every comparison into a dot product.

Two vectors of different lengths score 0 in ``faces.similarity`` — they carry
no evidence about each other — so matrices are built per **(space, dimension)**
block and a mismatched vector simply never joins one.

**faiss is an OPTIONAL accelerator** (``faiss-cpu``, which rides along with
the ``[full]`` extra): ``edges()`` switches to an HNSW index for large
pools and falls back to the exact blocked matmul whenever faiss is missing.
The brute path is the reference and the only required one — do not add faiss
to the mandatory dependencies.
"""

from __future__ import annotations

import threading
from typing import Iterable, Iterator, Optional, Sequence

import numpy as np

from media_compost.faces import SAME_PERSON

try:  # pragma: no cover - exercised only where faiss is installed
    import faiss  # type: ignore

    _HAVE_FAISS = True
except Exception:  # pragma: no cover - the normal case (optional extra)
    faiss = None  # type: ignore
    _HAVE_FAISS = False

#: Below this many vectors the exact blocked matmul is faster than building an
#: ANN index (and it is exact, so it is preferred wherever affordable).
_ANN_MIN = 20_000

#: Neighbours asked of the ANN index per vector. Clustering only needs the
#: same-person agreements, and a person with more than this many *mutual*
#: nearest crops still chains together through single-link union-find.
_ANN_K = 16


def matrix(vectors: list[bytes], dim: int) -> np.ndarray:
    """Float32 rows, L2-normalized, one per descriptor.

    A vector whose byte length does not match ``dim`` (or an empty one) becomes
    a ZERO row: its cosine against anything is 0, exactly what
    ``faces.similarity`` answers for a length mismatch or a degenerate vector.
    """
    X = np.zeros((len(vectors), dim), dtype=np.float32)
    want = dim * 4
    for i, raw in enumerate(vectors):
        if raw and len(raw) == want:
            X[i] = np.frombuffer(raw, dtype=np.float32)
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return X / norms


def unit(raw: Optional[bytes], dim: int) -> Optional[np.ndarray]:
    """One descriptor as an L2-normalized float32 vector, or None when it is
    missing, mismatched or degenerate (the cases ``similarity`` scores 0)."""
    if not raw or len(raw) != dim * 4:
        return None
    v = np.frombuffer(raw, dtype=np.float32).astype(np.float32)
    n = float(np.linalg.norm(v))
    if n == 0:
        return None
    return v / n


def scores(X_pool: np.ndarray, v) -> np.ndarray:
    """Cosine of one descriptor against every pool row.

    ``v`` may be raw float32 bytes or an already-normalized vector. A missing /
    mismatched / degenerate ``v`` scores 0 everywhere, like ``similarity``.
    """
    if isinstance(v, (bytes, bytearray)):
        u = unit(bytes(v), X_pool.shape[1] if X_pool.ndim == 2 else 0)
        if u is None:
            return np.zeros(len(X_pool), dtype=np.float32)
        v = u
    v = np.asarray(v, dtype=np.float32)
    return X_pool @ v


def pair_edges(ids: list[int], X: np.ndarray, threshold: float,
               block: int = 1024) -> Iterator[tuple[int, int]]:
    """Every (id_a, id_b) pair with cosine >= ``threshold``, upper-triangle only.

    Blocked ``X[i:i+B] @ X.T`` so memory stays ``B×n`` instead of ``n×n``; rows
    are already normalized, so the matmul IS the cosine.
    """
    n = len(ids)
    if n < 2:
        return
    for i0 in range(0, n, block):
        i1 = min(i0 + block, n)
        S = X[i0:i1] @ X.T                     # (block, n)
        for bi in range(i1 - i0):
            gi = i0 + bi
            hits = np.nonzero(S[bi, gi + 1:] >= threshold)[0]
            for off in hits:
                yield ids[gi], ids[gi + 1 + int(off)]


def _ann_edges(ids: list[int], X: np.ndarray, threshold: float
               ) -> Iterator[tuple[int, int]]:  # pragma: no cover - needs faiss
    """Approximate near-neighbour pairs via a faiss HNSW index (inner product
    over normalized rows = cosine). Emits each pair once, in id-pair order."""
    index = faiss.IndexHNSWFlat(X.shape[1], 32, faiss.METRIC_INNER_PRODUCT)
    index.add(np.ascontiguousarray(X, dtype=np.float32))
    D, I = index.search(np.ascontiguousarray(X, dtype=np.float32), _ANN_K)
    seen: set[tuple[int, int]] = set()
    for i in range(len(ids)):
        for score, j in zip(D[i], I[i]):
            j = int(j)
            if j < 0 or j == i or score < threshold:
                continue
            a, b = (i, j) if i < j else (j, i)
            if (a, b) in seen:
                continue
            seen.add((a, b))
            yield ids[a], ids[b]


def edges(ids: list[int], X: np.ndarray, threshold: float,
          block: int = 1024) -> Iterator[tuple[int, int]]:
    """Same-person agreements: exact blocked matmul for any pool a matmul can
    afford, faiss HNSW above ``_ANN_MIN`` when it is installed."""
    if len(ids) < _ANN_MIN or not _HAVE_FAISS:
        yield from pair_edges(ids, X, threshold, block)
    else:  # pragma: no cover - needs faiss
        yield from _ann_edges(ids, X, threshold)


def space_matrices(vectors: dict[int, dict[str, bytes]]
                   ) -> dict[tuple[str, int], tuple[list[int], np.ndarray]]:
    """Per **(space, dimension)** blocks of ``(face_ids, normalized matrix)``.

    Keyed by dimension as well as space because two vectors of different
    lengths score 0 in ``faces.similarity`` — they can never join, so they
    live in separate blocks rather than zero-padding one matrix.

    Id order within a block follows the iteration order of ``vectors``, which
    callers keep equal to their face-id order — that is what makes the fast
    clustering's output ordering identical to the scalar reference's.
    """
    per: dict[tuple[str, int], tuple[list[int], list[bytes]]] = {}
    for fid, spaces in vectors.items():
        for m, raw in (spaces or {}).items():
            if not raw or len(raw) % 4:
                continue
            fids, raws = per.setdefault((m, len(raw) // 4), ([], []))
            fids.append(fid)
            raws.append(raw)
    return {key: (fids, matrix(raws, key[1]))
            for key, (fids, raws) in per.items()}


#: How big a reachable component the exact refinement will take on. The scan
#: for the best pair keeps a score per PAIR of groups, so the memory is the
#: square of the component — 32 MB a block at this size, and four times that
#: at twice it. A component past this is a library-wide problem rather than a
#: person, and is left as reachability found it.
SPLIT_MAX = 2000


def to_setting_scale(space: str, arr: np.ndarray) -> np.ndarray:
    """``faces.comparable`` over a whole matrix — the same affine map onto the
    setting's own scale, so scores from two spaces can be compared."""
    from media_compost import faces as facelib

    band = facelib.SPACE_BANDS.get(space)
    if band is None:
        return arr
    lo, hi = band
    ref = facelib.SPACE_BANDS.get("anime_face_magi", (lo, hi))
    span = hi - lo
    pos = np.full_like(arr, 0.5) if span <= 0 else (arr - lo) / span
    return np.clip(ref[0] + pos * (ref[1] - ref[0]), 0.0, 1.0)


def group_matrices(vectors: dict[int, dict[str, bytes]],
                   ids: Sequence[int]) -> dict[tuple[str, int], np.ndarray]:
    """One group's descriptors as unit rows, per (space, dimension).

    `faces.group_blocks` with matrices — the same blocking, because two
    vectors of different lengths can never be compared.
    """
    per: dict[tuple[str, int], list[np.ndarray]] = {}
    for fid in ids:
        for space, raw in (vectors.get(fid) or {}).items():
            if not raw or len(raw) % 4:
                continue
            # NORMALIZED IN float64, unlike `matrix`: this answer is COMPARED
            # with the reference's rather than only ranked against itself, and
            # normalizing in float32 first put the two 3e-9 apart.
            v = np.frombuffer(raw, dtype=np.float32).astype(np.float64)
            n = float(np.linalg.norm(v))
            if n == 0:
                continue
            per.setdefault((space, len(raw) // 4), []).append(v / n)
    return {key: np.array(rows, dtype=np.float64)
            for key, rows in per.items() if rows}


def pair_likeness(a: dict[tuple[str, int], np.ndarray],
                  b: dict[tuple[str, int], np.ndarray]) -> Optional[float]:
    """`faces.group_likeness` with matrices — how alike two groups are, on the
    SETTING's own scale, the BEST of the spaces they share.

    THE MEAN OF EVERY CROSS PAIR, never the angle between their averages, for
    the reason the clustering keeps it that way: an embedder handed pictures
    outside its domain answers with vectors that all lean one way, and the
    average of a dozen of those IS that lean — two groups' means then agree
    almost perfectly while no two of their faces do. Measured on the demo
    library, the averages read ~20 points high and put a 297-crop cluster
    above a 3-crop one that was the better match.
    """
    best: Optional[float] = None
    for key, A in a.items():
        B = b.get(key)
        if B is None or not len(A) or not len(B):
            continue
        got = float(to_setting_scale(key[0], np.asarray(float((A @ B.T).mean()))))
        if best is None or got > best:
            best = got
    return best


def odd_ones_out(vectors: dict[int, dict[str, bytes]],
                 ids: Sequence[int],
                 unlike: Sequence[int]) -> list[int]:
    """Which of `ids` look more like `unlike` than like the rest of `ids`.

    The question a correction raises: somebody has just said that these crops
    are somebody else, so the group they left is one answer narrower — and
    whatever was only in it BECAUSE of them is still in it. Each remaining
    crop is scored against the two sides the way any two groups are scored
    (the mean of every cross pair per shared space, the best shared space
    deciding, `pair_likeness`' rule), and the ones the departed side wins are
    handed back.

    STRICTLY MORE LIKE, with no margin: this is an OFFER, not a write — the
    row it fills says "these look like the ones you moved" and a person
    presses or ignores it. A crop that no space can compare with either side
    is not offered, because nothing was said about it either way.
    """
    ids = list(ids)
    if len(ids) < 2 or not unlike:
        return []
    here: dict[int, float] = {}
    there: dict[int, float] = {}
    mine = group_matrices(vectors, ids)
    theirs = group_matrices(vectors, unlike)
    for key, A in mine.items():
        rows = [fid for fid in ids
                if (vectors.get(fid) or {}).get(key[0])
                and len((vectors[fid][key[0]])) // 4 == key[1]]
        if len(rows) != len(A):
            continue
        if len(rows) > 1:
            S = A @ A.T
            rest = (S.sum(axis=1) - np.diagonal(S)) / (len(rows) - 1)
            for fid, got in zip(rows, to_setting_scale(key[0], rest)):
                here[fid] = max(here.get(fid, -1.0), float(got))
        B = theirs.get(key)
        if B is not None and len(B):
            away = (A @ B.T).mean(axis=1)
            for fid, got in zip(rows, to_setting_scale(key[0], away)):
                there[fid] = max(there.get(fid, -1.0), float(got))
    return [fid for fid in ids
            if fid in there and there[fid] > here.get(fid, -1.0)]


def split_component(members: list[int],
                    rows: dict[tuple[str, int], tuple[dict[int, int],
                                                      np.ndarray]],
                    setting: float) -> list[list[int]]:
    """``faces.split_by_likeness`` with matrices: greedy average-link
    agglomeration inside ONE reachable component, merging the two groups that
    look most alike while they still look like one person.

    Kept to the same arithmetic as the reference — the MEAN of every cross
    pair per shared (space, dimension) block, the best block deciding, ties
    going to the earliest pair — because the two are asserted equal
    (`test_cluster_spaces_fast_equals_the_reference`). float64 throughout for
    that reason: a component's whole answer can turn on which side of the
    threshold one pair lands, and float32 rounds differently from the
    reference's Python floats.

    A merged group's mean against everything else is the WEIGHTED MEAN of the
    two it came from (`n_a·m_a + n_b·m_b) / (n_a + n_b)`, the Lance-Williams
    update for average linkage) — exactly the number the reference recomputes
    from the members, without touching a vector again. So the vectors are read
    once, and each merge costs one row.
    """
    k = len(members)
    # Under three there is nothing to cut, and past the cap the component is
    # left as reachability found it — the reference's rule exactly.
    if k < 3 or k > SPLIT_MAX:
        return [list(members)]
    parts = [[fid] for fid in members]
    NEG = -np.inf
    # Per block: the mean cross-pair similarity between every two groups (NaN
    # where the block has nothing to say about one of them), and how many of
    # each group's faces the block speaks for.
    means: dict[tuple[str, int], np.ndarray] = {}
    counts: dict[tuple[str, int], np.ndarray] = {}
    for key, (index, X) in rows.items():
        here = [i for i in range(k) if members[i] in index]
        if len(here) < 2:
            continue
        idx = np.array(here)
        V = X[np.array([index[members[i]] for i in here])].astype(np.float64)
        M = np.full((k, k), np.nan, dtype=np.float64)
        M[np.ix_(idx, idx)] = V @ V.T
        n = np.zeros(k, dtype=np.float64)
        n[idx] = 1.0
        means[key], counts[key] = M, n
    if not means:
        return parts

    def scores_for(row: int) -> np.ndarray:
        got = np.full(k, NEG, dtype=np.float64)
        for key, M in means.items():
            line = M[row]
            live = ~np.isnan(line)
            if not live.any():
                continue
            mapped = to_setting_scale(key[0], np.where(live, line, 0.0))
            np.maximum(got, np.where(live, mapped, NEG), out=got)
        return got

    S = np.full((k, k), NEG, dtype=np.float64)
    for i in range(k):
        S[i] = scores_for(i)
    S[np.tril_indices(k)] = NEG
    alive = np.ones(k, dtype=bool)

    # THE BEST PAIR IS FOUND THROUGH A ROW INDEX, not by scanning the whole
    # matrix again per merge. `np.argmax(S)` is k² elements, and a component
    # of 300 faces merges ~300 times: 0.31 s of a 0.54 s unnamed-faces read
    # was this one line, which every face write pays for (a write moves the
    # cache's signature and the next read re-clusters).
    #
    # IT PICKS THE SAME PAIR. Row-major `argmax` answers the smallest row
    # with the maximum, then the smallest column in it — which is
    # `argmax(bestv)` (first row whose best is the global best) and
    # `bestj[a]` (first column in that row), so the "ties go to the earliest
    # pair" rule the reference is held to is unchanged.
    bestj = S.argmax(axis=1)
    bestv = S[np.arange(k), bestj]

    def rescan(i: int) -> None:
        j = int(np.argmax(S[i]))
        bestj[i], bestv[i] = j, S[i, j]

    while True:
        a = int(np.argmax(bestv))
        b = int(bestj[a])
        if bestv[a] < setting:
            break
        parts[a] = parts[a] + parts[b]
        parts[b] = []
        alive[b] = False
        S[b, :] = NEG
        S[:, b] = NEG
        for key, M in means.items():
            n = counts[key]
            na, nb = float(n[a]), float(n[b])
            if na or nb:
                la, lb = M[a], M[b]
                ga, gb = ~np.isnan(la), ~np.isnan(lb)
                line = np.where(
                    ga & gb, (na * np.nan_to_num(la) + nb * np.nan_to_num(lb))
                    / (na + nb or 1.0),
                    np.where(ga, la, lb))
                line[~(ga | gb)] = np.nan
                M[a, :] = line
                M[:, a] = line
            n[a], n[b] = na + nb, 0.0
            M[b, :] = np.nan
            M[:, b] = np.nan
            M[a, a] = np.nan
        row = scores_for(a)
        row[~alive] = NEG
        row[a] = NEG
        S[a, :] = NEG
        S[:, a] = NEG
        S[a, a + 1:] = row[a + 1:]
        S[:a, a] = row[:a]

        # WHICH ROWS' ANSWERS MOVED. The merge rewrote row `a` whole, emptied
        # row and column `b`, and gave every row above `a` a new `S[i, a]`.
        # So: a row that was aiming at `a` or `b` has to look again, row `a`
        # is recomputed, `b` leaves — and for the rest only the ONE new
        # value can have changed the answer, which is a comparison rather
        # than a scan (strictly better, or equal from an earlier column,
        # since the earliest pair wins).
        stale = np.flatnonzero(((bestj == a) | (bestj == b)) & alive)
        for i in stale:
            if i != a:
                rescan(int(i))
        rescan(a)
        bestj[b], bestv[b] = 0, NEG
        if a:
            col = S[:a, a]
            take = ((col > bestv[:a])
                    | ((col == bestv[:a]) & (a < bestj[:a]))) & alive[:a]
            hit = np.flatnonzero(take)
            bestj[hit], bestv[hit] = a, col[hit]
        bestv[~alive] = NEG

    return [parts[i] for i in range(k) if alive[i]]


def cluster_ids(ids: list[int],
                spaces: dict[tuple[str, int], tuple[list[int], np.ndarray]],
                setting: float) -> list[list[int]]:
    """ONE union-find over ``ids``, fed each space's agreements separately, and
    then each component CUT into groups that each look like one person — the
    same two stages as ``faces.cluster_spaces``, so the same partition,
    ordering included (groups in ``ids`` order, biggest first)."""
    from media_compost import faces as facelib

    parent = {fid: fid for fid in ids}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    ids = list(ids)
    known = set(ids)
    for (space, _dim), (fids, X) in spaces.items():
        thr = facelib.threshold_for(space, setting)
        for a, b in edges(fids, X, thr):
            if a not in known or b not in known:
                continue
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra
    groups: dict[int, list[int]] = {}
    for fid in ids:
        groups.setdefault(find(fid), []).append(fid)
    rows = {key: (dict(zip(fids, range(len(fids)))), X)
            for key, (fids, X) in spaces.items()}
    out: list[list[int]] = []
    for members in groups.values():
        out.extend(split_component(members, rows, setting))
    # Biggest first — the cluster worth naming is the one that saves most work.
    return sorted(out, key=lambda g: (-len(g), g[0]))


# ---- the per-library cache --------------------------------------------------


class FaceCache:
    """Per-library cache of face matrices and the last unnamed clustering
    (``deps.Library.face_cache``).

    Guarded by a cheap signature over the tables the answer is computed from:
    ``faces`` (count, max id, how many dismissed — a dismissal flips a row's
    membership without changing count or max), ``face_embeddings`` (count, max
    id, total vector bytes — a re-run REPLACES a vector in place), and
    ``item_subjects`` (count, max id, id sums — merge/split RETARGET rows in
    place, which count+max cannot see), plus the ``face_match_threshold``
    setting. Any mismatch rebuilds; a hit skips the embedding load and the
    clustering entirely.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._key: Optional[tuple] = None
        #: The last ``space_matrices`` result, kept so a caller that only needs
        #: the matrices (not the clustering) can reuse them on a hit.
        self.spaces: Optional[dict] = None
        self._clusters: Optional[list[list[int]]] = None

    @staticmethod
    def signature(session) -> tuple:
        from sqlalchemy import Integer, cast, func, select

        from media_compost.db import Face, FaceEmbedding, ItemSubject

        # CAST, or the count comes back as a BOOLEAN. `Face.dismissed` is a
        # Boolean column, and SQLAlchemy runs the COLUMN's result processor
        # over whatever the aggregate returns — so `sum()` over it answered
        # True for one dismissal and True for four hundred. Which is exactly
        # the case this term exists for: a dismissal moves neither the count
        # nor the max, so the second one and every one after it left the
        # signature unmoved and the clustering was served from the cache
        # with the dismissed face still in it. On screen: "not a face" did
        # nothing at all, until something else in the library moved.
        f = session.execute(select(
            func.count(Face.id), func.max(Face.id),
            func.sum(cast(Face.dismissed, Integer)))).one()
        e = session.execute(select(
            func.count(FaceEmbedding.id), func.max(FaceEmbedding.id),
            func.sum(func.length(FaceEmbedding.vector)))).one()
        a = session.execute(select(
            func.count(ItemSubject.id), func.max(ItemSubject.id),
            func.sum(ItemSubject.subject_id),
            func.sum(func.coalesce(ItemSubject.face_id, 0)))).one()
        return tuple(f) + tuple(e) + tuple(a)

    def unnamed_clusters(self, session, loose_ids: list[int],
                         threshold: float) -> list[list[int]]:
        """The loose (no-appearance) faces' grouping, rebuilt only when the
        signature moved. Identical to ``faces.cluster_spaces_fast`` output."""
        from media_compost import faces as facelib

        key = (self.signature(session), float(threshold))
        with self._lock:
            if key == self._key and self._clusters is not None:
                return self._clusters
        vectors = facelib.embeddings_of(session, loose_ids)
        spaces = space_matrices(
            {fid: vectors[fid] for fid in loose_ids if vectors.get(fid)})
        clusters = cluster_ids(list(loose_ids), spaces, threshold)
        with self._lock:
            self._key, self.spaces, self._clusters = key, spaces, clusters
        return clusters


# ---- the suggestion pool, loaded once per batch -----------------------------


class SubjectMatcher:
    """The face-suggestion pool, loaded ONCE and asked many times.

    ``jobs._suggest_subjects`` used to rebuild the pool — every user-assigned
    face, its descriptors, and every claimed face id — per ITEM, which made a
    thousand-item detection batch a thousand library scans. ``load()`` does it
    once; ``match()`` reproduces ``faces.best_match`` exactly (per-space
    threshold via ``threshold_for``, the same runner-up margin, the same
    first-wins tie rule) over the pool matrices; ``claim()`` records a
    suggestion just written so the same face is not asked about again within
    the batch.

    Only a PERSON's answers seed the pool (``assigned_by == "user"``), so one
    machine mistake cannot breed the next — the rule is unchanged, just loaded
    up front.
    """

    def __init__(self, spaces: dict, claimed: set[int], setting: float):
        #: {(space, dim): (subject_ids, exemplar_face_ids, matrix)} — arrays
        #: parallel to the matrix rows, in pool-row order (first wins on ties,
        #: exactly as ``best_match`` iterates its candidates).
        self._spaces = spaces
        #: Faces that already carry any appearance — never asked about.
        self.claimed = claimed
        #: The library's single threshold setting (a position in the reference
        #: band; each space reads it through ``threshold_for``).
        self.setting = setting

    @property
    def has_pool(self) -> bool:
        return bool(self._spaces)

    @classmethod
    def load(cls, session) -> "SubjectMatcher":
        from sqlalchemy import select

        from media_compost import faces as facelib
        from media_compost.db import ItemSubject
        from media_compost.prefs import read_face_match_threshold

        pool_rows = list(session.execute(
            select(ItemSubject.face_id, ItemSubject.subject_id)
            .where(ItemSubject.face_id.is_not(None),
                   ItemSubject.assigned_by == "user")
        ).all())
        claimed = {
            fid for fid, in session.execute(
                select(ItemSubject.face_id)
                .where(ItemSubject.face_id.is_not(None))
            ).all()
        }
        vectors = facelib.embeddings_of(session,
                                        [fid for fid, _ in pool_rows])
        per: dict[tuple[str, int],
                  tuple[list[int], list[int], list[bytes]]] = {}
        for fid, sid in pool_rows:      # pool-row order == candidate order
            for m, raw in (vectors.get(fid) or {}).items():
                if not raw or len(raw) % 4:
                    continue
                subs, fids, raws = per.setdefault(
                    (m, len(raw) // 4), ([], [], []))
                subs.append(sid)
                fids.append(fid)
                raws.append(raw)
        spaces = {
            key: (np.asarray(subs, dtype=np.int64),
                  np.asarray(fids, dtype=np.int64),
                  matrix(raws, key[1]))
            for key, (subs, fids, raws) in per.items()
        }
        return cls(spaces, claimed, read_face_match_threshold(session))

    def claim(self, face_id: int) -> None:
        """A suggestion was just written at this face — stop asking about it."""
        self.claimed.add(face_id)

    def match(self, space: str, vector: Optional[bytes],
              exclude_subject_ids: Iterable[int] = ()):
        """Who this descriptor most resembles in ``space`` — or None.

        Same answer as ``faces.best_match`` over the pool this space holds:
        refused subjects are dropped BEFORE the comparison (a rejected person
        cannot even be the runner-up that suppresses somebody else), the best
        single exemplar wins, and the winner must beat the best score of any
        OTHER subject by ``RUNNER_UP_MARGIN``.
        """
        from media_compost import faces as facelib

        if not vector or len(vector) % 4:
            return None
        entry = self._spaces.get((space, len(vector) // 4))
        if entry is None:
            return None
        subs, fids, X = entry
        v = unit(vector, X.shape[1])
        if v is None:
            return None
        sc = X @ v
        ok = sc >= facelib.threshold_for(space, self.setting)
        refused = set(exclude_subject_ids)
        if refused:
            ok &= ~np.isin(subs, np.fromiter(refused, dtype=np.int64,
                                             count=len(refused)))
        idx = np.nonzero(ok)[0]
        if idx.size == 0:
            return None
        best_i = idx[int(np.argmax(sc[idx]))]   # first occurrence wins ties
        best_subject = int(subs[best_i])
        best_score = float(sc[best_i])
        others = idx[subs[idx] != best_subject]
        runner_up = float(sc[others].max()) if others.size else 0.0
        if best_score < runner_up + facelib.RUNNER_UP_MARGIN:
            return None
        return facelib.Match(best_subject, best_score, int(fids[best_i]))



def cluster_spaces_fast(ids: Sequence[int],
                        vectors: dict[int, dict[str, bytes]],
                        setting: float = SAME_PERSON) -> list[list[int]]:
    """``faces.cluster_spaces``, answered with matrices instead of the O(n²)
    scalar loop — same inputs, same partition, same ordering.

    The scalar version stays in CORE as the reference (and the oracle the
    tests compare this against): the rule's definition is library knowledge,
    while this accelerated form needs numpy and so lives with the app. It
    builds one normalized matrix per (space, dimension) block
    (`space_matrices`) and feeds each block's agreements (`edges`) into the
    same one-union-find-across-spaces rule.
    """
    ids = list(ids)
    subset = {fid: vectors[fid] for fid in ids if vectors.get(fid)}
    return cluster_ids(ids, space_matrices(subset), setting)

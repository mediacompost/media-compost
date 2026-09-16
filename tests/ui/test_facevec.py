"""facevec against its scalar oracle.

`faces.similarity` / `faces.best_match` / `faces.cluster_spaces` are the
DEFINITION of the matching rules; `facevec` re-answers them with matrices.
Every test here compares the fast path against the scalar one on randomized
inputs — same edges, same scores (to float32 precision), same partitions,
same suggestions.
"""

from __future__ import annotations

import random

import numpy as np
import pytest

from media_compost import faces as facelib
from media_compost.ui import facevec
from media_compost.db import (
    Database, Face, FaceRejection, Item, ItemSubject, Subject,
)


def _vec(rng: random.Random, dim: int) -> list[float]:
    v = [rng.gauss(0, 1) for _ in range(dim)]
    n = sum(x * x for x in v) ** 0.5
    return [x / n for x in v]


def _pack(values) -> bytes:
    return facelib.pack_embedding(values)


def _safe_threshold(sims: list[float], want: float) -> float:
    """A cutoff near ``want`` that no pair sits on, so float32-vs-float64
    rounding at the boundary cannot flip an edge between fast and oracle."""
    cuts = sorted(set(sims))
    for a, b in zip(cuts, cuts[1:]):
        if a < want <= b:
            return (a + b) / 2
    return want


# ---- pair_edges / scores ----------------------------------------------------


def test_pair_edges_match_the_scalar_double_loop():
    rng = random.Random(7)
    dim, n = 8, 60
    raws = [_pack(_vec(rng, dim)) for _ in range(n)]
    ids = [100 + i for i in range(n)]
    X = facevec.matrix(raws, dim)

    unpacked = [facelib.unpack_embedding(r) for r in raws]
    sims = [facelib.similarity(unpacked[i], unpacked[j])
            for i in range(n) for j in range(i + 1, n)]
    threshold = _safe_threshold(sims, 0.5)

    want = {(ids[i], ids[j])
            for i in range(n) for j in range(i + 1, n)
            if facelib.similarity(unpacked[i], unpacked[j]) >= threshold}
    # A small block size so the blocked path really iterates.
    got = set(facevec.pair_edges(ids, X, threshold, block=7))
    assert got == want and want, "expected some edges to compare"
    # And through the selector (brute here — the pool is small / no faiss).
    assert set(facevec.edges(ids, X, threshold)) == want


def test_a_mismatched_or_empty_vector_scores_zero_like_similarity():
    rng = random.Random(3)
    good = _pack(_vec(rng, 8))
    short = _pack(_vec(rng, 4))
    X = facevec.matrix([good, short, b""], 8)
    assert np.allclose(X[1], 0) and np.allclose(X[2], 0)
    sc = facevec.scores(X, good)
    assert sc[1] == 0.0 and sc[2] == 0.0
    assert facevec.scores(X, short).tolist() == [0.0, 0.0, 0.0]
    assert facevec.scores(X, b"").tolist() == [0.0, 0.0, 0.0]


def test_scores_equal_similarity_per_vector():
    rng = random.Random(11)
    dim = 12
    raws = [_pack(_vec(rng, dim)) for _ in range(30)]
    probe = _pack(_vec(rng, dim))
    X = facevec.matrix(raws, dim)
    got = facevec.scores(X, probe)
    for i, raw in enumerate(raws):
        want = facelib.similarity(facelib.unpack_embedding(probe),
                                  facelib.unpack_embedding(raw))
        assert got[i] == pytest.approx(want, abs=1e-5)


# ---- clustering -------------------------------------------------------------


def _random_vectors(rng: random.Random, ids, spaces: dict[str, int],
                    coverage: float = 0.8) -> dict[int, dict[str, bytes]]:
    """Random per-face descriptors: some faces in no space, some in several.
    Planted near-duplicates make sure real clusters exist."""
    out: dict[int, dict[str, bytes]] = {}
    anchors = {m: [_vec(rng, d) for _ in range(3)] for m, d in spaces.items()}
    for fid in ids:
        mine: dict[str, bytes] = {}
        for m, d in spaces.items():
            if rng.random() > coverage:
                continue
            if rng.random() < 0.5:      # near an anchor -> clusters form
                base = rng.choice(anchors[m])
                v = [x + rng.gauss(0, 0.05) for x in base]
            else:
                v = _vec(rng, d)
            mine[m] = _pack(v)
        if mine:
            out[fid] = mine
    return out


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_cluster_spaces_fast_equals_the_reference(seed):
    rng = random.Random(seed)
    ids = [10 + i for i in range(40)]
    vectors = _random_vectors(
        rng, ids, {"insightface_buffalo_l": 8, "anime_face_magi": 6})
    want = facelib.cluster_spaces(ids, vectors)
    got = facevec.cluster_spaces_fast(ids, vectors)
    assert got == want


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_pair_likeness_equals_the_reference(seed):
    """The strip and the clustering ask ONE question, so the matrix answer and
    the scalar one have to be the same number — including None where the two
    groups share no space to be compared in."""
    rng = random.Random(seed)
    ids = [10 + i for i in range(12)]
    vectors = _random_vectors(
        rng, ids, {"insightface_buffalo_l": 8, "anime_face_magi": 6})
    a, b = ids[:5], ids[5:]
    unpacked = {fid: {m: facelib.unpack_embedding(v) for m, v in sp.items()}
                for fid, sp in vectors.items()}
    want = facelib.group_likeness(facelib.group_blocks(unpacked, a),
                                  facelib.group_blocks(unpacked, b))
    got = facevec.pair_likeness(facevec.group_matrices(vectors, a),
                                facevec.group_matrices(vectors, b))
    assert (want is None) == (got is None)
    if want is not None:
        assert got == pytest.approx(want, abs=1e-9)


def test_pair_likeness_is_none_where_no_space_is_shared():
    """A drawn face and a photographed one are embedded by different detectors
    and cannot be compared at all — which is not the same as 'not alike'."""
    rng = random.Random(4)
    drawn = {1: {"anime_face_magi": _pack(_vec(rng, 6))}}
    shot = {2: {"insightface_buffalo_l": _pack(_vec(rng, 8))}}
    assert facevec.pair_likeness(facevec.group_matrices(drawn, [1]),
                                 facevec.group_matrices(shot, [2])) is None


def test_odd_ones_out_hands_back_what_leans_the_other_way():
    """A CORRECTION IS EVIDENCE ABOUT THE REST.

    Two crops of one person, two of another, and somebody takes the second
    pair out: what is handed back is the crops that look more like the ones
    that left than like the ones that stayed — which is nothing here, since
    the two that stayed are each other's best match. Put one of the OTHER
    person's crops back in the cluster and it is exactly what comes out.
    """
    rng = random.Random(11)
    a1, a2 = _vec(rng, 8), None
    a2 = [x + rng.gauss(0, 0.02) for x in a1]
    b1 = _vec(rng, 8)
    b2 = [x + rng.gauss(0, 0.02) for x in b1]
    space = "anime_face_magi"
    vectors = {1: {space: _pack(a1)}, 2: {space: _pack(a2)},
               3: {space: _pack(b1)}, 4: {space: _pack(b2)}}
    # The cluster held 1, 2 and 3; 4 has just been taken out as somebody else.
    assert facevec.odd_ones_out(vectors, [1, 2, 3], [4]) == [3]
    # …and with only its own people left, nothing is.
    assert facevec.odd_ones_out(vectors, [1, 2], [4]) == []


def test_odd_ones_out_says_nothing_about_a_crop_it_cannot_compare():
    """A crop described in a space neither side shares is not an answer of
    'it belongs' — it is no answer at all, and the offer stays quiet."""
    rng = random.Random(12)
    magi = {"anime_face_magi": _pack(_vec(rng, 6))}
    shot = {"insightface_buffalo_l": _pack(_vec(rng, 8))}
    vectors = {1: magi, 2: magi, 3: shot, 4: magi}
    assert 3 not in facevec.odd_ones_out(vectors, [1, 2, 3], [4])


def test_cluster_spaces_fast_with_no_vectors_is_one_group_per_face():
    ids = [1, 2, 3]
    assert facevec.cluster_spaces_fast(ids, {}) == [[1], [2], [3]]


def test_cluster_spaces_fast_respects_the_setting():
    """The setting travels through `threshold_for` exactly as in the scalar
    path — a stricter setting splits what the default joins."""
    rng = random.Random(9)
    base = _vec(rng, 8)
    close = [x + 0.02 * y for x, y in zip(base, _vec(rng, 8))]
    vectors = {1: {"anime_face_magi": _pack(base)},
               2: {"anime_face_magi": _pack(close)}}
    for setting in (0.5, 0.62, 0.9):
        assert (facevec.cluster_spaces_fast([1, 2], vectors, setting)
                == facelib.cluster_spaces([1, 2], vectors, setting))


# ---- SubjectMatcher ---------------------------------------------------------


def _seeded_db():
    """Two named people with user-answered exemplar faces in TWO spaces, one
    suggested-only appearance (must not seed the pool), and query faces."""
    db = Database.in_memory()
    rng = random.Random(21)
    dims = {"insightface_buffalo_l": 8, "anime_face_magi": 6}
    with db.session() as s:
        items = [Item(name=f"i{i}") for i in range(6)]
        s.add_all(items)
        alice, bob = Subject(display_name="Alice"), Subject(display_name="Bob")
        s.add_all([alice, bob])
        s.flush()

        anchor = {("a", m): _vec(rng, d) for m, d in dims.items()}
        anchor.update({("b", m): _vec(rng, d) for m, d in dims.items()})

        def face(item, box=0.1):
            f = Face(item_id=item.id, x=box, y=box, w=0.2, h=0.2,
                     det_score=0.9, model="m")
            s.add(f)
            s.flush()
            return f

        def near(key, m, jitter=0.04):
            return _pack([x + rng.gauss(0, jitter) for x in anchor[(key, m)]])

        pool_faces = []
        for who, subject in (("a", alice), ("b", bob)):
            for k in range(2):
                f = face(items[k])
                for m in dims:
                    facelib.store_embedding(s, f.id, m, near(who, m))
                s.add(ItemSubject(item_id=f.item_id, subject_id=subject.id,
                                  face_id=f.id, assigned_by="user"))
                pool_faces.append(f.id)
        # A machine's guess — claimed, but NOT pool material.
        guessed = face(items[2])
        facelib.store_embedding(s, guessed.id, "anime_face_magi",
                                near("a", "anime_face_magi"))
        s.add(ItemSubject(item_id=guessed.item_id, subject_id=alice.id,
                          face_id=guessed.id, assigned_by="suggested",
                          match_score=0.9))

        # Query faces: near alice, near bob, random, and one refused-for-alice.
        queries = []
        specs = [("a", None), ("b", None), (None, None), ("a", alice.id)]
        for i, (who, refuse) in enumerate(specs):
            f = face(items[3 + i % 3], box=0.3 + i * 0.1)
            for m in dims:
                raw = (near(who, m) if who else _pack(_vec(rng, dims[m])))
                facelib.store_embedding(s, f.id, m, raw)
            if refuse:
                s.add(FaceRejection(face_id=f.id, subject_id=refuse))
            queries.append(f.id)
        s.commit()
        return db, pool_faces, queries, dims


def test_matcher_reproduces_best_match_over_every_space():
    db, _pool, queries, dims = _seeded_db()
    with db.session() as s:
        from sqlalchemy import select

        from media_compost.ui.facevec import SubjectMatcher
        from media_compost.ui.server.routers.settings import \
            read_face_match_threshold

        matcher = SubjectMatcher.load(s)

        # The old per-item pool, built the way jobs._suggest_subjects did.
        pool_rows = list(s.execute(
            select(ItemSubject.face_id, ItemSubject.subject_id)
            .where(ItemSubject.face_id.is_not(None),
                   ItemSubject.assigned_by == "user")).all())
        vectors = facelib.embeddings_of(
            s, [fid for fid, _ in pool_rows] + queries)
        refused = facelib.rejections_for(s, queries)
        threshold = read_face_match_threshold(s)

        compared = 0
        for fid in queries:
            no = refused.get(fid, frozenset())
            for space, vector in (vectors.get(fid) or {}).items():
                pool = [(sid, v, pfid)
                        for pfid, sid in pool_rows
                        for v in [(vectors.get(pfid) or {}).get(space)]
                        if v is not None]
                want = facelib.best_match(
                    vector, pool,
                    threshold=facelib.threshold_for(space, threshold),
                    exclude=no)
                got = matcher.match(space, vector, no)
                if want is None:
                    assert got is None, (fid, space, got)
                else:
                    assert got is not None, (fid, space)
                    assert got.subject_id == want.subject_id
                    assert got.exemplar_face_id == want.exemplar_face_id
                    assert got.score == pytest.approx(want.score, abs=1e-5)
                    compared += 1
        assert compared > 0, "expected at least one positive match to compare"


def test_matcher_pool_is_user_answers_only_and_claimed_is_everything():
    db, pool_faces, _queries, _dims = _seeded_db()
    with db.session() as s:
        from sqlalchemy import select

        from media_compost.ui.facevec import SubjectMatcher

        matcher = SubjectMatcher.load(s)
        all_claimed = {
            fid for fid, in s.execute(
                select(ItemSubject.face_id)
                .where(ItemSubject.face_id.is_not(None))).all()
        }
        assert matcher.claimed == all_claimed
        assert len(all_claimed) == len(pool_faces) + 1  # + the guess
        # Claiming marks the face at once, and stays local to the matcher.
        matcher.claim(99_999)
        assert 99_999 in matcher.claimed


def test_matcher_match_needs_a_pool_in_that_space():
    db, _pool, queries, dims = _seeded_db()
    with db.session() as s:
        from media_compost.ui.facevec import SubjectMatcher

        matcher = SubjectMatcher.load(s)
        vec = facelib.embeddings_of(s, [queries[0]])[queries[0]]
        space, raw = next(iter(vec.items()))
        assert matcher.match("no_such_space", raw) is None
        assert matcher.match(space, None) is None
        assert matcher.match(space, b"") is None


def _old_suggest(s, item_id: int) -> list[tuple[int, int, float]]:
    """The retired per-item suggestion pass, verbatim minus the writes — the
    oracle the matcher-driven `jobs._suggest_subjects` must agree with."""
    from sqlalchemy import select

    from media_compost.ui.server.routers.settings import read_face_match_threshold

    pool_rows = list(s.execute(
        select(ItemSubject.face_id, ItemSubject.subject_id)
        .where(ItemSubject.face_id.is_not(None),
               ItemSubject.assigned_by == "user")).all())
    claimed = {fid for fid, in s.execute(
        select(ItemSubject.face_id)
        .where(ItemSubject.face_id.is_not(None))).all()}
    asking = [f for f in s.execute(
        select(Face).where(Face.item_id == item_id,
                           Face.dismissed.is_(False))).scalars().all()
              if f.id not in claimed]
    if not pool_rows or not asking:
        return []
    vectors = facelib.embeddings_of(
        s, [fid for fid, _ in pool_rows] + [f.id for f in asking])
    refused = facelib.rejections_for(s, [f.id for f in asking])
    threshold = read_face_match_threshold(s)
    out = []
    for f in asking:
        mine = vectors.get(f.id) or {}
        no = refused.get(f.id, frozenset())
        best = None
        for space, vector in mine.items():
            pool = [(sid, v, pfid)
                    for pfid, sid in pool_rows
                    for v in [(vectors.get(pfid) or {}).get(space)]
                    if v is not None]
            if not pool:
                continue
            hit = facelib.best_match(
                vector, pool,
                threshold=facelib.threshold_for(space, threshold), exclude=no)
            if hit is not None and (best is None or hit.score > best.score):
                best = hit
        if best is not None:
            out.append((f.id, best.subject_id, best.score))
    return out


def test_suggest_subjects_writes_what_the_old_path_would_have():
    """The whole point of B-9: same suggestions, loaded once instead of per
    item. Oracle first (pure), then the real `_suggest_subjects`, item by
    item, so the claims evolve exactly as they used to."""
    from sqlalchemy import select

    from media_compost.ui import jobs as jobs_mod

    db, _pool, queries, _dims = _seeded_db()
    with db.session() as s:
        item_ids = sorted({f.item_id for f in (
            s.get(Face, fid) for fid in queries)})
        expected: list[tuple[int, int, float]] = []
        for iid in item_ids:
            want = _old_suggest(s, iid)
            expected.extend(want)
            named = jobs_mod.suggest_subjects(s, s.get(Item, iid))
            assert named == len(want)
        s.commit()
        assert expected, "the seed is supposed to produce suggestions"

        written = {
            r.face_id: (r.subject_id, r.match_score)
            for r in s.execute(select(ItemSubject).where(
                ItemSubject.assigned_by == "suggested",
                ItemSubject.face_id.in_(queries))).scalars().all()
        }
        assert set(written) == {fid for fid, _sid, _sc in expected}
        for fid, sid, score in expected:
            got_sid, got_score = written[fid]
            assert got_sid == sid
            assert got_score == pytest.approx(score, abs=1e-5)


def test_batch_faces_share_one_matcher_and_claims_carry_over():
    """A face suggested for one item of a batch is claimed for the rest —
    `matcher.claim` is what replaces the per-item claimed query."""
    db, _pool, queries, _dims = _seeded_db()
    with db.session() as s:
        from media_compost.ui.facevec import SubjectMatcher

        matcher = SubjectMatcher.load(s)
        before = set(matcher.claimed)
        assert queries[0] not in before
        matcher.claim(queries[0])
        assert queries[0] in matcher.claimed
        # A fresh matcher still reads only what the DB says.
        assert queries[0] not in SubjectMatcher.load(s).claimed


# ---- FaceCache --------------------------------------------------------------


def test_face_cache_reuses_and_invalidates(monkeypatch):
    db, _pool, queries, _dims = _seeded_db()
    cache = facevec.FaceCache()
    calls = {"n": 0}
    real = facevec.cluster_ids

    def counting(ids, spaces, setting):
        calls["n"] += 1
        return real(ids, spaces, setting)

    monkeypatch.setattr(facevec, "cluster_ids", counting)
    with db.session() as s:
        first = cache.unnamed_clusters(s, queries, facelib.SAME_PERSON)
        assert calls["n"] == 1
        again = cache.unnamed_clusters(s, queries, facelib.SAME_PERSON)
        assert again is first, "unchanged library returns the cached answer"
        assert calls["n"] == 1

        # A different threshold is a different question.
        cache.unnamed_clusters(s, queries, 0.9)
        assert calls["n"] == 2

        # New data invalidates.
        item = s.execute(
            __import__("sqlalchemy").select(Item).limit(1)).scalars().first()
        s.add(Face(item_id=item.id, x=0.7, y=0.7, w=0.1, h=0.1,
                   det_score=0.5, model="m"))
        s.commit()
        cache.unnamed_clusters(s, queries, 0.9)
        assert calls["n"] == 3

        # A DISMISSAL changes no row count and no max id — the signature must
        # still move, or the cache serves the dismissed face forever.
        f = s.get(Face, queries[0])
        f.dismissed = True
        s.commit()
        left = [q for q in queries if q != f.id]
        cache.unnamed_clusters(s, left, 0.9)
        assert calls["n"] == 4

        # AND SO MUST THE SECOND ONE. The term counting them is a SUM over a
        # BOOLEAN column, which SQLAlchemy read back through that column's own
        # result processor: True for one dismissal and True for every one
        # after it, so the signature stopped moving after the first and "not a
        # face" appeared to do nothing at all.
        g = s.get(Face, left[0])
        g.dismissed = True
        s.commit()
        cache.unnamed_clusters(s, [q for q in left if q != g.id], 0.9)
        assert calls["n"] == 5


def test_face_cache_result_matches_cluster_spaces_fast():
    db, _pool, queries, _dims = _seeded_db()
    cache = facevec.FaceCache()
    with db.session() as s:
        want = facevec.cluster_spaces_fast(
            queries, facelib.embeddings_of(s, queries), facelib.SAME_PERSON)
        got = cache.unnamed_clusters(s, queries, facelib.SAME_PERSON)
        assert got == want

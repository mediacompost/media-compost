"""The rule that makes face detection safe to re-run.

Detection is cheap; naming faces is not. Every test here is about the second
run not undoing the first one's human work.
"""

from __future__ import annotations

import math

from media_compost import faces
from media_compost.faces import Detected, Known


def test_a_jittered_box_is_the_same_face():
    """Detectors move a box a little between runs and versions. That must not
    read as a new person appearing next to the old one."""
    known = [Known(id=7, box=(0.10, 0.10, 0.20, 0.20))]
    out = faces.reconcile(known, [Detected(box=(0.11, 0.105, 0.20, 0.21),
                                           score=0.98)])
    assert list(out.updated) == [7], "the id survives, so the name does"
    assert out.added == []


def test_two_faces_side_by_side_stay_two_faces():
    known = [Known(id=1, box=(0.0, 0.0, 0.2, 0.2)),
             Known(id=2, box=(0.22, 0.0, 0.2, 0.2))]
    out = faces.reconcile(known, [
        Detected(box=(0.01, 0.0, 0.2, 0.2), score=0.9),
        Detected(box=(0.23, 0.0, 0.2, 0.2), score=0.9),
    ])
    assert sorted(out.updated) == [1, 2]
    assert out.added == []


def test_a_detection_goes_to_the_face_it_overlaps_most():
    """Greedy in list order would give the first known face the detection that
    really belongs to the second."""
    known = [Known(id=1, box=(0.00, 0.0, 0.30, 0.30)),
             Known(id=2, box=(0.10, 0.0, 0.30, 0.30))]
    out = faces.reconcile(known, [Detected(box=(0.11, 0.0, 0.30, 0.30),
                                           score=0.9)])
    assert list(out.updated) == [2]


def test_a_face_the_run_missed_is_left_alone():
    """A hand-drawn face, or one a worse model version stopped seeing. A
    detector is not evidence of absence."""
    known = [Known(id=5, box=(0.5, 0.5, 0.2, 0.2))]
    out = faces.reconcile(known, [Detected(box=(0.0, 0.0, 0.1, 0.1), score=0.7)])
    assert out.updated == {}
    assert len(out.added) == 1, "the new one is added"
    # …and nothing in the result asks for face 5 to be touched.


def test_a_dismissed_face_absorbs_its_detection():
    """Otherwise every run re-adds the same false positive for the user to
    dismiss again."""
    known = [Known(id=9, box=(0.4, 0.4, 0.1, 0.1), dismissed=True)]
    out = faces.reconcile(known, [Detected(box=(0.4, 0.4, 0.1, 0.1), score=0.6)])
    assert list(out.updated) == [9]
    assert out.added == []


def test_one_run_that_finds_a_face_twice_records_it_once():
    """The anime detector really does return a confident box and a weaker one
    just inside it. Reconciliation only compares a detection with the record,
    so without collapsing the run first both would be stored."""
    out = faces.reconcile([], [
        Detected(box=(0.10, 0.70, 0.13, 0.07), score=0.50),
        Detected(box=(0.10, 0.71, 0.10, 0.06), score=0.31),
    ])
    assert len(out.added) == 1
    assert out.added[0].score == 0.50, "the confident box is the one kept"


def test_a_second_box_over_a_claimed_face_is_not_added_beside_it():
    known = [Known(id=3, box=(0.10, 0.70, 0.13, 0.07))]
    out = faces.reconcile(known, [
        Detected(box=(0.10, 0.70, 0.13, 0.07), score=0.50),
        Detected(box=(0.10, 0.71, 0.10, 0.06), score=0.31),
    ])
    assert list(out.updated) == [3]
    assert out.added == []


def test_a_stored_duplicate_is_reported_and_the_weaker_one_goes():
    known = [Known(id=12, box=(0.10, 0.70, 0.13, 0.07), score=0.50),
             Known(id=13, box=(0.10, 0.71, 0.10, 0.06), score=0.31)]
    assert faces.duplicates(known) == [13]


def test_an_answered_face_is_never_the_duplicate_that_goes():
    """Even when a stronger detection sits on top of it: the answer is the part
    worth keeping, and the box is only how it was found."""
    named = Known(id=1, box=(0.10, 0.70, 0.10, 0.06), score=0.20, answered=True)
    fresh = Known(id=2, box=(0.10, 0.70, 0.13, 0.07), score=0.99)
    assert faces.duplicates([named, fresh]) == [2]
    assert faces.duplicates([fresh, named]) == [2], "order must not decide it"


def test_two_answered_faces_on_one_spot_both_stay():
    """Two people tagged on top of each other is somebody's decision, not a
    detector's mistake."""
    a = Known(id=1, box=(0.1, 0.1, 0.2, 0.2), answered=True)
    b = Known(id=2, box=(0.1, 0.1, 0.2, 0.2), answered=True)
    assert faces.duplicates([a, b]) == []


def test_faces_apart_are_not_duplicates():
    known = [Known(id=1, box=(0.0, 0.0, 0.2, 0.2), score=0.9),
             Known(id=2, box=(0.5, 0.5, 0.2, 0.2), score=0.8)]
    assert faces.duplicates(known) == []


def test_iou_of_disjoint_boxes_is_zero():
    assert faces.iou((0, 0, 0.1, 0.1), (0.5, 0.5, 0.1, 0.1)) == 0.0
    assert faces.iou((0, 0, 0.2, 0.2), (0, 0, 0.2, 0.2)) == 1.0


# ---- crops -----------------------------------------------------------------

def test_a_crop_gets_margin_and_stays_inside_the_image():
    assert faces.crop_box((0.4, 0.4, 0.2, 0.2), 1000, 1000) == (350, 350, 650, 650)
    # A face at the corner keeps its size; it is not shifted inwards.
    assert faces.crop_box((0.0, 0.0, 0.2, 0.2), 100, 100) == (0, 0, 25, 25)


# ---- embeddings ------------------------------------------------------------

def test_descriptors_round_trip_through_bytes():
    values = [0.5, -0.25, 0.125]
    out = faces.unpack_embedding(faces.pack_embedding(values))
    assert [round(v, 4) for v in out] == values
    assert faces.unpack_embedding(None) == []


def test_similarity_is_by_angle_not_length():
    a = faces.unpack_embedding(faces.pack_embedding([1.0, 0.0]))
    long_a = faces.unpack_embedding(faces.pack_embedding([5.0, 0.0]))
    b = faces.unpack_embedding(faces.pack_embedding([0.0, 1.0]))
    assert round(faces.similarity(a, long_a), 6) == 1.0
    assert faces.similarity(a, b) == 0.0
    assert faces.similarity(a, []) == 0.0


def test_clustering_groups_the_same_person_and_leaves_the_rest_alone():
    alice = faces.pack_embedding([1.0, 0.0, 0.0])
    alice2 = faces.pack_embedding([0.95, 0.1, 0.0])
    bob = faces.pack_embedding([0.0, 1.0, 0.0])
    groups = faces.cluster([(1, alice), (2, bob), (3, alice2)])
    assert groups[0] == [1, 3], "biggest cluster first — most work saved"
    assert [2] in groups


def test_a_chain_of_lookalikes_is_not_one_person():
    """REACHABILITY IS NOT THE ANSWER, ONLY THE QUESTION.

    Four faces a step apart, each a match for its neighbour and nothing else:
    single link puts all four in one cluster, and that is how 660 of a demo
    library's 927 unanswered faces ended up as one "person" — a page of manga
    is a chain of characters drawn in one hand. Average linkage asks whether a
    face looks like what the GROUP looks like, and answers with the two pairs.
    """
    step = [faces.pack_embedding(
        [math.cos(math.radians(45 * i)), math.sin(math.radians(45 * i))])
        for i in range(4)]
    ids = [1, 2, 3, 4]
    vectors = {fid: {"": raw} for fid, raw in zip(ids, step)}
    # Every neighbour is a match at this setting (cos 45° = 0.707), and no
    # other pair is (cos 90° = 0, cos 135° = -0.707).
    assert faces.cluster_spaces(ids, vectors, 0.62) == [[1, 2], [3, 4]]


def test_a_face_with_no_descriptor_comes_back_alone():
    """The anime detector produces no embeddings, and the view still has to
    work — just ungrouped."""
    groups = faces.cluster([(1, None), (2, None)])
    assert groups == [[1], [2]]


def test_a_suggestion_is_only_offered_above_the_threshold():
    alice = faces.pack_embedding([1.0, 0.0, 0.0])
    near = faces.pack_embedding([0.9, 0.2, 0.0])
    far = faces.pack_embedding([0.2, 1.0, 0.0])
    assert faces.best_match(alice, [(4, far)]) is None
    hit = faces.best_match(alice, [(4, far), (5, near)])
    assert hit is not None and hit[0] == 5
    assert faces.best_match(None, [(5, near)]) is None

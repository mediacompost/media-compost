"""The rule that makes OCR safe to re-run.

Reading text is cheap; correcting it is not. Every test here is about the
second run not undoing the first one's human work — plus the two rules faces
never needed: regions form a TREE (children reconcile inside their matched
parent, and the missing-is-left-alone rule INVERTS there), and two engines'
readings never merge (each reconciles only against its own).
"""

from __future__ import annotations

from media_compost import ocr
from media_compost.ocr import Detected, Known


def _f(*models: str) -> frozenset[str]:
    return frozenset(models)


# ---- geometry ---------------------------------------------------------------


def test_pack_quad_round_trips():
    quad = [(0.1, 0.2), (0.4, 0.21), (0.41, 0.3), (0.09, 0.29)]
    assert ocr.unpack_quad(ocr.pack_quad(quad)) == [
        (0.1, 0.2), (0.4, 0.21), (0.41, 0.3), (0.09, 0.29)]


def test_pack_quad_refuses_anything_but_four_points():
    """"" means "the box is the shape" — a malformed quad must read as that,
    never as a crash, because a sidecar from any build can hold anything."""
    assert ocr.pack_quad(None) == ""
    assert ocr.pack_quad([]) == ""
    assert ocr.pack_quad([(0.1, 0.2), (0.3, 0.4)]) == ""
    assert ocr.unpack_quad("") == []
    assert ocr.unpack_quad("0.1,0.2,junk") == []
    assert ocr.unpack_quad("0.1,0.2") == []


def test_aabb_of_a_rotated_quad():
    quad = [(0.2, 0.1), (0.5, 0.2), (0.45, 0.4), (0.15, 0.3)]
    x, y, w, h = ocr.aabb_of(quad)
    assert (x, y) == (0.15, 0.1)
    assert abs(w - 0.35) < 1e-9 and abs(h - 0.3) < 1e-9


def test_crop_box_uses_texts_own_margin():
    """A text crop wants its glyphs unshaved, not head and shoulders."""
    left, top, right, bottom = ocr.crop_box((0.5, 0.5, 0.2, 0.1), 1000, 1000)
    assert left == 490 and right == 710  # 5% of the box each side, not 25%


# ---- flat reconciliation (faces' rules, restated) ---------------------------


def test_a_jittered_box_is_the_same_region():
    known = [Known(id=7, box=(0.10, 0.10, 0.30, 0.10), models=_f("magiv3_ocr"),
                   text="Hello")]
    out = ocr.reconcile(known, [Detected(box=(0.11, 0.105, 0.30, 0.11),
                                         text="Hello!")],
                        model="magiv3_ocr")
    assert list(out.updated) == [7]
    assert out.added == [] and out.orphaned == []


def test_a_plain_rerun_rewrites_the_text():
    """Nobody has answered, so the newer reading wins — that is what re-running
    a better model is for."""
    known = [Known(id=7, box=(0.1, 0.1, 0.3, 0.1), models=_f("m"), text="0ld")]
    out = ocr.reconcile(known, [Detected(box=(0.1, 0.1, 0.3, 0.1),
                                         text="Old")], model="m")
    assert 7 in out.retext


def test_an_edited_region_keeps_its_text_and_takes_the_new_geometry():
    """Only a person says WHAT, once a person has said it; the machine goes on
    saying WHERE."""
    known = [Known(id=7, box=(0.1, 0.1, 0.3, 0.1), models=_f("m"),
                   text="corrected by hand", edited=True)]
    out = ocr.reconcile(known, [Detected(box=(0.12, 0.1, 0.3, 0.1),
                                         text="machine says otherwise")],
                        model="m")
    assert list(out.updated) == [7], "the geometry still follows the engine"
    assert 7 not in out.retext, "the text never does"


def test_a_dismissed_region_absorbs_its_detection():
    """Otherwise every run re-adds the same false positive for the user to
    dismiss again. Nothing under it changes either — recursing would
    resurface the text below a region somebody said is not text."""
    known = [Known(id=9, box=(0.4, 0.4, 0.2, 0.1), models=_f("m"),
                   dismissed=True)]
    out = ocr.reconcile(
        known,
        [Detected(box=(0.4, 0.4, 0.2, 0.1), text="noise",
                  children=(Detected(box=(0.4, 0.4, 0.1, 0.1), text="no",
                                     level="word"),))],
        model="m")
    assert list(out.updated) == [9]
    assert 9 not in out.retext
    assert out.added == [], "no child rows appear under a dismissal"


def test_a_region_the_run_missed_is_left_alone():
    """It may be hand-drawn, and it may be in a script THIS pass's recogniser
    does not know — a Japanese pass after a Latin one is the normal workflow."""
    known = [Known(id=5, box=(0.5, 0.5, 0.2, 0.1), models=_f("m"), text="x")]
    out = ocr.reconcile(known, [Detected(box=(0.0, 0.0, 0.2, 0.1), text="y")],
                        model="m")
    assert out.updated == {} and out.orphaned == []
    assert len(out.added) == 1


def test_a_runs_own_overlapping_boxes_collapse_and_the_earlier_wins():
    """RapidOCR returns overlapping quads for stacked vertical text; list
    order is the engine's reading order, which is the priority that means
    something (half the engines have no score at all)."""
    out = ocr.reconcile([], [
        Detected(box=(0.10, 0.70, 0.20, 0.08), text="first"),
        Detected(box=(0.11, 0.70, 0.19, 0.08), text="again"),
    ], model="m")
    assert len(out.added) == 1
    assert out.added[0][1].text == "first"


# ---- what faces never needed ------------------------------------------------


def test_two_engines_never_match_each_other():
    """Grouped-by-engine is a contract: engine B's run must not claim (or
    rewrite) engine A's reading of the same stretch."""
    known = [Known(id=1, box=(0.1, 0.1, 0.3, 0.1), models=_f("a"), text="A's")]
    out = ocr.reconcile(known, [Detected(box=(0.1, 0.1, 0.3, 0.1),
                                         text="B's")], model="b")
    assert out.updated == {}
    assert len(out.added) == 1, "B's reading lands beside A's, not over it"


def test_an_engine_may_claim_a_hand_drawn_region():
    known = [Known(id=1, box=(0.1, 0.1, 0.3, 0.1), models=_f(), text="typed")]
    out = ocr.reconcile(known, [Detected(box=(0.1, 0.1, 0.3, 0.1),
                                         text="read")], model="m")
    assert list(out.updated) == [1]
    # Hand-drawn means answered: the typed text survives the claim.
    assert 1 not in out.retext


def test_cross_level_matching_is_refused():
    """A Magi block and a RapidOCR line over one bubble are two READINGS, not
    one region jittered — and two stacked lines overlap far more than two
    faces ever do, which is why level partitions before IoU is consulted."""
    known = [Known(id=1, box=(0.1, 0.1, 0.3, 0.1), level="block",
                   models=_f("m"))]
    out = ocr.reconcile(known, [Detected(box=(0.1, 0.1, 0.3, 0.1),
                                         level="line", text="x")], model="m")
    assert out.updated == {}
    assert len(out.added) == 1


def test_children_reconcile_inside_their_matched_parent():
    known = [
        Known(id=1, box=(0.1, 0.1, 0.4, 0.3), models=_f("m"), text="block"),
        Known(id=2, box=(0.1, 0.1, 0.4, 0.1), level="line", parent_id=1,
              models=_f("m"), text="line one"),
    ]
    out = ocr.reconcile(known, [
        Detected(box=(0.1, 0.1, 0.4, 0.3), text="block", children=(
            Detected(box=(0.11, 0.1, 0.4, 0.1), level="line", text="line 1"),
            Detected(box=(0.1, 0.22, 0.4, 0.1), level="line", text="line 2"),
        )),
    ], model="m")
    assert sorted(out.updated) == [1, 2]
    assert 2 in out.retext
    assert len(out.added) == 1, "the new second line is added under the block"
    assert out.added[0][0] == 1, "…parented to the KNOWN block's id"


def test_an_unanswered_orphan_child_is_deleted_and_an_answered_one_survives():
    """A block's line breakdown is THIS run's reading of that block, not an
    independent finding — leaving the old lines beside the new shows the
    sentence twice. But an answer survives everything."""
    known = [
        Known(id=1, box=(0.1, 0.1, 0.4, 0.3), models=_f("m"), text="block"),
        Known(id=2, box=(0.1, 0.1, 0.4, 0.1), level="line", parent_id=1,
              models=_f("m"), text="stale line"),
        Known(id=3, box=(0.1, 0.22, 0.4, 0.1), level="line", parent_id=1,
              models=_f("m"), text="fixed line", edited=True),
    ]
    out = ocr.reconcile(known, [
        Detected(box=(0.1, 0.1, 0.4, 0.3), text="block", children=()),
    ], model="m")
    assert out.orphaned == [2], "the unanswered breakdown goes"
    assert 3 not in out.orphaned, "the corrected line stays"


def test_an_unmatched_block_is_added_whole():
    out = ocr.reconcile([], [
        Detected(box=(0.1, 0.1, 0.4, 0.3), text="block", children=(
            Detected(box=(0.1, 0.1, 0.4, 0.1), level="line", text="a line"),
        )),
    ], model="m")
    assert len(out.added) == 1
    parent_id, det = out.added[0]
    assert parent_id is None
    assert len(det.children) == 1, "the subtree rides along for the applier"


# ---- duplicates -------------------------------------------------------------


def test_duplicates_heal_a_doubled_row():
    known = [
        Known(id=1, box=(0.1, 0.1, 0.3, 0.1), models=_f("m"), score=0.9),
        Known(id=2, box=(0.11, 0.1, 0.3, 0.1), models=_f("m"), score=0.5),
    ]
    assert ocr.duplicates(known) == [2]


def test_duplicates_never_drop_an_answered_region():
    known = [
        Known(id=1, box=(0.1, 0.1, 0.3, 0.1), models=_f("m"), score=0.9),
        Known(id=2, box=(0.11, 0.1, 0.3, 0.1), models=_f("m"), edited=True),
    ]
    assert ocr.duplicates(known) == [1], "the answer wins over the confidence"


def test_duplicates_leave_two_engines_readings_alone():
    """Two engines over one stretch are two rows by design — the sidebar
    groups by engine, and collapsing them here would merge what reconcile
    is built to keep apart."""
    known = [
        Known(id=1, box=(0.1, 0.1, 0.3, 0.1), models=_f("a")),
        Known(id=2, box=(0.1, 0.1, 0.3, 0.1), models=_f("b")),
    ]
    assert ocr.duplicates(known) == []


def test_duplicates_are_scoped_per_parent_and_level():
    known = [
        Known(id=1, box=(0.1, 0.1, 0.3, 0.1), level="line", parent_id=10,
              models=_f("m")),
        Known(id=2, box=(0.1, 0.1, 0.3, 0.1), level="line", parent_id=11,
              models=_f("m")),
        Known(id=3, box=(0.1, 0.1, 0.3, 0.1), level="word", parent_id=10,
              models=_f("m")),
    ]
    assert ocr.duplicates(known) == []

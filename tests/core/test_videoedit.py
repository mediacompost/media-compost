"""The video edit plan — the half that is arithmetic, tested without ffmpeg."""

from media_compost import videoedit as ve


def plan(**kw) -> ve.Plan:
    kw.setdefault("cuts", [(0.0, 10.0)])
    return ve.Plan(**kw)


def test_cuts_that_touch_become_one():
    # Two ranges meeting at the same timestamp are one continuous shot, and
    # encoding them as two puts a concat boundary in the middle of it.
    assert ve.normalize_cuts([(0, 5), (5, 9)], 20) == [(0.0, 9.0)]


def test_empty_and_backwards_cuts_are_dropped():
    assert ve.normalize_cuts([(3, 3), (5, 4), (1, 2)], 20) == [(1.0, 2.0)]


def test_cuts_are_clamped_to_the_file():
    assert ve.normalize_cuts([(-3, 5), (8, 99)], 20) == [(0.0, 5.0), (8.0, 20.0)]


def test_the_whole_file_uncut_is_nothing_to_do():
    assert ve.is_noop(plan(cuts=[(0.0, 10.0)]), 10.0)
    # …but only while nothing touches a pixel.
    assert not ve.is_noop(plan(cuts=[(0.0, 10.0)], rotate=90), 10.0)
    assert not ve.is_noop(plan(cuts=[(1.0, 10.0)]), 10.0)


def test_a_quarter_turn_swaps_the_size():
    assert ve.output_size(1920, 1080, plan(rotate=90)) == (1080, 1920)
    assert ve.output_size(1920, 1080, plan(rotate=180)) == (1920, 1080)


def test_every_output_size_is_even():
    # yuv420p halves the chroma planes, so an odd dimension is an encode that
    # fails outright.
    p = plan(crop=ve.Crop(0, 0, 0.333, 0.777))
    w, h = ve.output_size(1921, 1081, p)
    assert w % 2 == 0 and h % 2 == 0
    w, h = ve.output_size(1920, 1080, plan(scale=(641, 361)))
    assert (w, h) == (640, 360)


def test_the_crop_is_taken_on_the_ROTATED_frame():
    # The rectangle was drawn on the picture as it was being watched.
    p = plan(rotate=90, crop=ve.Crop(0, 0, 0.5, 0.5))
    assert ve.output_size(1920, 1080, p) == (540, 960)
    chain = ve.picture_filters(1920, 1080, p)
    assert chain[0] == "transpose=1"
    assert chain[1] == "crop=540:960:0:0"


def test_filters_are_empty_when_the_plan_only_cuts():
    assert ve.picture_filters(1920, 1080, plan(cuts=[(1, 2)])) == []
    assert not plan(cuts=[(1, 2)]).transforms_picture


def test_the_filter_graph_trims_concats_and_transforms():
    p = plan(cuts=[(0, 2), (5, 7)], fps=25)
    g = ve.filter_complex(p.cuts, 640, 480, p, audio_stream=0)
    assert "trim=start=0.000000:end=2.000000" in g
    assert "atrim=start=5.000000:end=7.000000" in g
    assert "[v0][a0][v1][a1]concat=n=2:v=1:a=1[vcat][aout]" in g
    assert g.endswith("[vcat]fps=25[vout]")


def test_the_audio_track_is_named_rather_than_left_to_ffmpeg():
    """`[0:a]` lets ffmpeg's own stream selection choose, and it takes the
    track with the MOST CHANNELS — so a film with a stereo original and a 5.1
    dub rendered with the dub, whatever the container marked default."""
    p = plan(cuts=[(0, 2)])
    g = ve.filter_complex(p.cuts, 640, 480, p, audio_stream=2)
    assert "[0:a:2]atrim" in g
    assert "[0:a]" not in g


def test_a_silent_source_gets_no_audio_chain():
    p = plan(cuts=[(0, 2)])
    g = ve.filter_complex(p.cuts, 640, 480, p, audio_stream=None)
    assert "atrim" not in g and "a=0" in g


def test_a_scale_that_changes_nothing_adds_no_filter():
    assert ve.picture_filters(640, 480, plan(scale=(640, 480))) == []


def test_total_duration_is_the_sum_of_the_pieces():
    assert ve.total_duration([(0, 2.5), (10, 12.5)]) == 5.0


# ---- ffmpeg's progress stream ----------------------------------------------

def test_progress_reads_microseconds_and_timecodes():
    from media_compost.media import _progress_seconds

    assert _progress_seconds("out_time_us=2500000") == 2.5
    assert _progress_seconds("out_time=00:01:30.500000") == 90.5
    assert _progress_seconds("out_time=N/A") is None
    assert _progress_seconds("frame=42") is None


def test_out_time_ms_is_ignored_because_it_is_not_milliseconds():
    """ffmpeg's `out_time_ms` carries MICROseconds despite the name. Reading it
    as milliseconds made every render report 100% a second in — the progress
    bar was full before the first minute of a film had been encoded."""
    from media_compost.media import _progress_seconds

    assert _progress_seconds("out_time_ms=2500000") is None


# ---- gaps ------------------------------------------------------------------
# A gap is a piece with no source: black picture and silence, of a stated
# length. It rides on the same 2-tuple as a range, with a NEGATIVE start —
# every real start is >= 0, so one rule covers both sides and the wire format
# (a list of [a, b] pairs) carries it with no change at all.


def test_a_gap_is_told_apart_by_its_negative_start():
    assert ve.is_gap((ve.GAP, ve.GAP + 2.0))
    assert not ve.is_gap((0.0, 2.0))
    assert ve.piece_len((ve.GAP, ve.GAP + 2.0)) == 2.0
    assert ve.piece_len((1.0, 4.0)) == 3.0
    assert ve.has_gaps([(0.0, 1.0), (ve.GAP, ve.GAP + 2.0)])
    assert not ve.has_gaps([(0.0, 1.0), (2.0, 3.0)])


def test_a_gap_counts_towards_the_length():
    cuts = [(0.0, 2.0), (ve.GAP, ve.GAP + 1.5), (5.0, 6.0)]
    assert ve.total_duration(cuts) == 4.5


def test_ranges_either_side_of_a_gap_are_not_joined():
    """Two ranges that MEET are one continuous shot and are joined. With a gap
    between them they are not adjacent, whatever their timestamps say — and
    joining them would delete the gap."""
    cuts = ve.normalize_cuts(
        [(0.0, 2.0), (ve.GAP, ve.GAP + 1.0), (2.0, 4.0)], 10.0)
    assert cuts == [(0.0, 2.0), (ve.GAP, ve.GAP + 1.0), (2.0, 4.0)]
    # Without the gap they collapse, as they always have.
    assert ve.normalize_cuts([(0.0, 2.0), (2.0, 4.0)], 10.0) == [(0.0, 4.0)]


def test_two_gaps_that_meet_become_one():
    cuts = ve.normalize_cuts(
        [(ve.GAP, ve.GAP + 1.0), (ve.GAP, ve.GAP + 0.5)], 10.0)
    assert cuts == [(ve.GAP, ve.GAP + 1.5)]


def test_a_gap_is_not_clamped_to_the_source():
    """It names no part of the file, so there is no file to clamp it to — a
    gap longer than the video is a perfectly ordinary thing to ask for."""
    assert ve.normalize_cuts([(ve.GAP, ve.GAP + 90.0)], 10.0) == \
        [(ve.GAP, ve.GAP + 90.0)]


def test_a_gap_that_is_too_short_is_dropped_like_any_piece():
    assert ve.normalize_cuts([(ve.GAP, ve.GAP + 0.001)], 10.0) == []


def test_a_lone_gap_is_not_the_whole_file():
    """`is_whole` decides whether there is anything to render at all, and a
    black screen where the film was is very much something."""
    assert not ve.is_whole([(ve.GAP, ve.GAP + 10.0)], 10.0)
    assert ve.is_whole([(0.0, 10.0)], 10.0)


def test_a_gap_is_generated_rather_than_trimmed():
    plan = ve.Plan(cuts=[(0.0, 1.0), (ve.GAP, ve.GAP + 2.0)])
    g = ve.filter_complex(plan.cuts, 640, 480, plan, audio_stream=0, fps=25)
    # The real piece is trimmed out of the input; the gap is made from nothing.
    assert "[0:v]trim=start=0.000000:end=1.000000" in g
    assert "color=c=black:s=640x480:r=25.000000:d=2.000000" in g
    assert "aevalsrc=0:d=2.000000" in g
    # Both sides normalized, or a source with an odd pixel aspect or sample
    # format would fail the concat only when a gap was present.
    assert g.count("setsar=1") == 2
    assert g.count("aformat=") == 2
    assert "concat=n=2:v=1:a=1" in g


def test_a_gap_without_audio_generates_no_silence():
    plan = ve.Plan(cuts=[(ve.GAP, ve.GAP + 2.0)])
    g = ve.filter_complex(plan.cuts, 320, 240, plan, audio_stream=None, fps=30)
    assert "aevalsrc" not in g and "concat=n=1:v=1:a=0" in g

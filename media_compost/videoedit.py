"""What a video edit IS, as arithmetic — the half of the video editor that can
be tested without ffmpeg.

The editor hands back a **cutlist**: an ordered list of ``[start, end]`` pieces
which, concatenated in that order, are the new video. Almost all of them are
ranges of the SOURCE file, and that one shape covers every edit the window
offers — trimming keeps one range, removing splits one into two, cut/copy/paste
reorder and duplicate them — so nothing downstream needs a tag set of
operations, only a list of pieces.

The exception is a **gap**: black picture and silence, belonging to no part of
the source. It is the same ``[start, end]`` pair in a source space of its own
(:data:`GAP`), so its length is ``end - start`` like any other piece's, the
wire format did not have to change, and none of the arithmetic needed a branch.
A gap is GENERATED at render time, which is also why a cutlist holding one can
never take the copy fast path — there are no compressed frames to copy.

Alongside it come the whole-video transforms (rotation, crop, scale, frame
rate). The order they apply in is fixed and is the order the person did them
in: **trim → rotate → crop → scale → frame rate**. Crop after rotate because
the rectangle was drawn on the picture as it was being watched, which is the
rotated one; scale after crop because the size asked for is the size of the
result.

Every dimension this produces is EVEN. `yuv420p` — what every player can
decode, and what the encoder is asked for — stores chroma at half resolution
in both axes, so an odd width has half a chroma sample at the edge and ffmpeg
refuses the encode outright. Rounding here (rather than leaving it to a filter
expression) also means the size in the plan is the size in the file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

#: A piece of the assembly, in seconds. Half-open: the frame at ``end`` is the
#: first one NOT included, which is what makes two adjacent ranges join without
#: a duplicated frame.
#:
#: A GAP is the same tuple, in the separate source space :data:`GAP` names —
#: not a third field, so every ``for a, b in cuts`` unpacking keeps working and
#: the wire format carries one unchanged.
Cut = tuple[float, float]

#: Where a gap's range lives: a source that does not exist, far below zero.
#:
#: A gap is an ordinary ``(start, end)`` pair in THIS space, so its length is
#: ``end - start`` exactly like a real range's and every piece of arithmetic
#: downstream — the total, the offsets, the slicing, the splitting — needs no
#: branch at all. Only the two places that actually touch the FILE (the render
#: graph and the keyframe check) ask which kind it is.
#:
#: Far below zero rather than at -1 because a slightly negative start already
#: meant something: `normalize_cuts` clamps it to the start of the file, which
#: is how a drag that overshoots the left edge is absorbed. Reading every
#: negative as a gap would silently turn those into black screens, so the two
#: spaces are put a billion seconds apart where nothing can reach across.
GAP = -1e9

#: Anything at or below this is in gap space. Halfway to :data:`GAP`, so a gap
#: sliced or split anywhere inside itself is still unmistakably one.
GAP_MAX = -1e8

#: Ranges shorter than this are dropped. A cut that survives has to be at least
#: a frame or two at any sane frame rate; below that it is a rounding artefact
#: of a drag, and ffmpeg's `trim` would emit an empty segment that breaks the
#: concat filter's stream count.
MIN_CUT = 0.02


def is_gap(cut: Cut) -> bool:
    return cut[0] <= GAP_MAX


def piece_len(cut: Cut) -> float:
    """How long this piece plays for — the same rule for both kinds, which is
    the whole point of putting gaps in a source space of their own."""
    return max(0.0, cut[1] - cut[0])


def has_gaps(cuts: list[Cut]) -> bool:
    return any(is_gap(c) for c in cuts)


@dataclass(frozen=True)
class Crop:
    """A rectangle on the DISPLAYED frame, in fractions of it (0..1)."""

    x: float
    y: float
    w: float
    h: float


@dataclass
class Plan:
    """One save's worth of edit: which parts of the source, and what to do to
    the picture as a whole."""

    cuts: list[Cut] = field(default_factory=list)
    #: Clockwise, in degrees: 0, 90, 180 or 270.
    rotate: int = 0
    crop: Optional[Crop] = None
    #: Output size in pixels, or None for "whatever the crop leaves".
    scale: Optional[tuple[int, int]] = None
    #: Output frame rate, or None to keep the source's.
    fps: Optional[float] = None

    @property
    def transforms_picture(self) -> bool:
        """Does anything here change a PIXEL? If not, the output can be
        assembled by copying the source's own compressed frames."""
        return bool(self.rotate % 360) or self.crop is not None \
            or self.scale is not None or self.fps is not None


def normalize_cuts(cuts: list[Cut], duration: float) -> list[Cut]:
    """Clamp to the file, drop the empty ones, and join what touches.

    Joining matters for more than tidiness: two ranges that meet at the same
    timestamp are one continuous piece of video, and encoding them as two
    segments puts a concat boundary in the middle of a continuous shot — one
    more chance for a frame to be dropped or a timestamp to drift.
    """
    out: list[Cut] = []
    for start, end in cuts:
        if float(start) <= GAP_MAX:
            # A gap names no part of the source, so there is no file to clamp
            # it to. Two that meet ARE one longer gap, worth joining for the
            # same reason two ranges are: one generated segment instead of two.
            length = float(end) - float(start)
            if length < MIN_CUT:
                continue
            if out and is_gap(out[-1]):
                out[-1] = (out[-1][0], out[-1][1] + length)
            else:
                out.append((GAP, GAP + length))
            continue
        a = max(0.0, min(float(start), duration if duration > 0 else float(start)))
        b = min(float(end), duration) if duration > 0 else float(end)
        if b - a < MIN_CUT:
            continue
        # Never across a gap: the ranges either side of one are not adjacent,
        # whatever their timestamps say.
        if out and not is_gap(out[-1]) and abs(out[-1][1] - a) < MIN_CUT:
            out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out


def total_duration(cuts: list[Cut]) -> float:
    return sum(piece_len(c) for c in cuts)


def is_whole(cuts: list[Cut], duration: float) -> bool:
    """Is this cutlist just "the whole file", uncut?"""
    if len(cuts) != 1 or is_gap(cuts[0]):
        return False
    a, b = cuts[0]
    return a < MIN_CUT and (duration <= 0 or b >= duration - MIN_CUT)


def is_noop(plan: Plan, duration: float) -> bool:
    """Nothing to render: the whole file, untouched."""
    return not plan.transforms_picture and is_whole(plan.cuts, duration)


def _even(n: float, lo: int = 2) -> int:
    return max(lo, int(n) // 2 * 2)


def rotated_size(w: int, h: int, rotate: int) -> tuple[int, int]:
    return (h, w) if rotate % 180 == 90 else (w, h)


def output_size(w: int, h: int, plan: Plan) -> tuple[int, int]:
    """The pixel size the rendered file will have."""
    rw, rh = rotated_size(w, h, plan.rotate)
    if plan.crop is not None:
        rw = _even(rw * plan.crop.w)
        rh = _even(rh * plan.crop.h)
    if plan.scale is not None:
        rw, rh = _even(plan.scale[0]), _even(plan.scale[1])
    return _even(rw), _even(rh)


def picture_filters(w: int, h: int, plan: Plan) -> list[str]:
    """The ffmpeg video filters for the whole-picture half of the plan, in the
    order they apply. Empty when the plan only cuts."""
    out: list[str] = []
    rot = plan.rotate % 360
    if rot == 90:
        out.append("transpose=1")
    elif rot == 180:
        # Two transposes rather than `hflip,vflip`: one filter's worth of
        # arithmetic either way, and this cannot be read as a mirror.
        out.append("transpose=1,transpose=1")
    elif rot == 270:
        out.append("transpose=2")
    rw, rh = rotated_size(w, h, plan.rotate)
    if plan.crop is not None:
        cw, ch = _even(rw * plan.crop.w), _even(rh * plan.crop.h)
        # The offset is rounded to even as well: an odd one puts the chroma
        # plane half a sample out of step with the luma.
        cx = _even(rw * plan.crop.x, lo=0)
        cy = _even(rh * plan.crop.y, lo=0)
        cx = min(cx, max(0, rw - cw))
        cy = min(cy, max(0, rh - ch))
        out.append(f"crop={cw}:{ch}:{cx}:{cy}")
        rw, rh = cw, ch
    if plan.scale is not None:
        sw, sh = _even(plan.scale[0]), _even(plan.scale[1])
        if (sw, sh) != (rw, rh):
            # `setsar=1` because a source with non-square pixels would
            # otherwise carry its aspect ratio onto a size that no longer has
            # it, and the result plays stretched.
            out.append(f"scale={sw}:{sh},setsar=1")
            rw, rh = sw, sh
    if plan.fps is not None:
        out.append(f"fps={plan.fps:g}")
    # An odd dimension survives only if the source had one and nothing above
    # touched it; the encoder would refuse, so trim the last row/column.
    if rw % 2 or rh % 2:
        out.append(f"crop={_even(rw)}:{_even(rh)}:0:0")
    return out


#: What a gap's audio is generated at. Fixed rather than probed, and every
#: segment — real or generated — is normalized to it, because the concat filter
#: requires its inputs to agree and the output is AAC either way.
GAP_RATE = 48000
GAP_LAYOUT = "stereo"
#: The frame rate a gap is generated at when the source's could not be probed.
GAP_FPS_FALLBACK = 25.0


def filter_complex(cuts: list[Cut], w: int, h: int, plan: Plan,
                   audio_stream: Optional[int], fps: Optional[float] = None) -> str:
    """The whole `-filter_complex` graph: one segment per piece, a concat, then
    the picture filters.

    Trimming inside the filter graph (rather than with `-ss`/`-to`) is what
    makes the cuts FRAME-ACCURATE: input seeking lands on a keyframe, which is
    up to a group-of-pictures away from what was asked for — the fast path in
    `media.render_cutlist` uses that deliberately and only where it is exact.

    ``audio_stream`` is WHICH audio track to take, counted among the audio
    streams, or None for a silent render. It has to be named: `[0:a]` leaves
    the choice to ffmpeg's own stream selection, which takes the track with the
    MOST CHANNELS — so a film with a stereo original and a 5.1 dub rendered
    with the dub, whatever the container marked default and whatever the window
    was playing.

    A GAP is generated rather than trimmed: `color` for the picture and
    `aevalsrc` for the silence. Both are given the SOURCE's dimensions and rate
    because the concat happens before the picture filters, so every segment
    reaching it must already agree — which is also why `format`/`setsar` and
    `aformat` are applied to the real segments too, rather than only to the
    generated ones. Normalizing both sides is what stops a source with an odd
    pixel aspect or sample format failing the concat only when a gap is
    present.
    """
    rate = fps or GAP_FPS_FALLBACK
    audio = audio_stream is not None
    src_a = f"[0:a:{audio_stream}]"
    parts: list[str] = []
    for i, cut in enumerate(cuts):
        a, b = cut
        if is_gap(cut):
            length = piece_len(cut)
            parts.append(
                f"color=c=black:s={w}x{h}:r={rate:.6f}:d={length:.6f},"
                f"format=yuv420p,setsar=1[v{i}]")
            if audio:
                parts.append(
                    f"aevalsrc=0:d={length:.6f}:s={GAP_RATE}:c={GAP_LAYOUT},"
                    f"aformat=sample_fmts=fltp:sample_rates={GAP_RATE}:"
                    f"channel_layouts={GAP_LAYOUT}[a{i}]")
            continue
        parts.append(
            f"[0:v]trim=start={a:.6f}:end={b:.6f},setpts=PTS-STARTPTS,"
            f"format=yuv420p,setsar=1[v{i}]")
        if audio:
            parts.append(
                f"{src_a}atrim=start={a:.6f}:end={b:.6f},asetpts=PTS-STARTPTS,"
                f"aformat=sample_fmts=fltp:sample_rates={GAP_RATE}:"
                f"channel_layouts={GAP_LAYOUT}[a{i}]")
    n = len(cuts)
    if audio:
        chain = "".join(f"[v{i}][a{i}]" for i in range(n))
        parts.append(f"{chain}concat=n={n}:v=1:a=1[vcat][aout]")
    else:
        chain = "".join(f"[v{i}]" for i in range(n))
        parts.append(f"{chain}concat=n={n}:v=1:a=0[vcat]")
    filters = picture_filters(w, h, plan)
    if filters:
        parts.append("[vcat]" + ",".join(filters) + "[vout]")
    else:
        parts.append("[vcat]null[vout]")
    return ";".join(parts)

// Run with: npm test  (Node's built-in test runner + type stripping).
import { test } from "node:test";
import assert from "node:assert/strict";
import type { Cut } from "./cutlist.ts";
import * as cl from "./cutlist.ts";

/** A ten-second file, uncut. */
const ten = (): Cut[] => cl.whole(10);
const at = (cuts: Cut[]) => cuts.map((c) => [c.start, c.end]);

test("an uncut file is one range, and its edited time is its source time", () => {
  assert.deepEqual(at(ten()), [[0, 10]]);
  assert.equal(cl.duration(ten()), 10);
  assert.deepEqual(cl.sourceAt(ten(), 4), { index: 0, time: 4 });
});

test("trimming keeps what was marked", () => {
  assert.deepEqual(at(cl.trimTo(ten(), 2, 6)), [[2, 6]]);
  assert.equal(cl.duration(cl.trimTo(ten(), 2, 6)), 4);
});

test("removing takes the middle out and the ends close up", () => {
  const cuts = cl.removeRange(ten(), 3, 5);
  assert.deepEqual(at(cuts), [[0, 3], [5, 10]]);
  // The assembly is now 8 seconds, and edited 4 s is source 6 s.
  assert.equal(cl.duration(cuts), 8);
  assert.deepEqual(cl.sourceAt(cuts, 4), { index: 1, time: 6 });
});

test("every operation is against the EDITED timeline", () => {
  // Remove 3–5, then remove 3–4 of what is LEFT — which is source 5–6, not
  // 3–4 again. Reading the second range as source time is the bug this rule
  // exists to prevent.
  let cuts = cl.removeRange(ten(), 3, 5);
  cuts = cl.removeRange(cuts, 3, 4);
  assert.deepEqual(at(cuts), [[0, 3], [6, 10]]);
});

test("removing to the end, and from the start", () => {
  assert.deepEqual(at(cl.removeRange(ten(), 7, 10)), [[0, 7]]);
  assert.deepEqual(at(cl.removeRange(ten(), 0, 2)), [[2, 10]]);
});

test("a copy is a cutlist of its own, and pasting splices it in", () => {
  const clip = cl.slice(ten(), 1, 3);
  assert.deepEqual(at(clip), [[1, 3]]);
  const cuts = cl.insertAt(ten(), 8, clip);
  assert.deepEqual(at(cuts), [[0, 8], [1, 3], [8, 10]]);
  assert.equal(cl.duration(cuts), 12);
});

test("a pasted copy is REACHED — the same source second appears twice", () => {
  // This is why `sourceAt` reports an index: at edited 9 the player must be
  // in the pasted copy (cut 1), not back at the start of the file.
  const cuts = cl.insertAt(ten(), 8, cl.slice(ten(), 1, 3));
  assert.deepEqual(cl.sourceAt(cuts, 9), { index: 1, time: 2 });
  assert.deepEqual(cl.sourceAt(cuts, 2), { index: 0, time: 2 });
  // …and back the other way, which is the direction the player runs in.
  assert.equal(cl.editedAt(cuts, 1, 2), 9);
  assert.equal(cl.editedAt(cuts, 0, 2), 2);
});

test("cut is copy then remove, and the result is shorter by the piece", () => {
  const clip = cl.slice(ten(), 4, 6);
  const cuts = cl.removeRange(ten(), 4, 6);
  assert.equal(cl.duration(clip), 2);
  assert.equal(cl.duration(cuts), 8);
  // Pasting it back where it came from restores the original.
  assert.deepEqual(at(cl.insertAt(cuts, 4, clip)), [[0, 10]]);
});

test("pieces that meet are joined", () => {
  // Not tidiness: two ranges touching at one timestamp are one continuous
  // shot, and keeping them apart puts a concat seam inside it.
  assert.deepEqual(at(cl.normalize([{ start: 0, end: 5 }, { start: 5, end: 9 }])),
    [[0, 9]]);
});

test("a slice of nothing is nothing, and an empty cutlist survives it", () => {
  assert.deepEqual(cl.slice(ten(), 4, 4), []);
  assert.deepEqual(cl.slice([], 0, 5), []);
  assert.equal(cl.sourceAt([], 1), null);
});

test("the seams are every place a piece can be spliced in", () => {
  // The start, each piece's end — so every split between two pieces and both
  // ends of every gap, which is what a dropped clip is offered.
  const cuts = [{ start: 0, end: 3 }, cl.gap(2), { start: 5, end: 6 }];
  assert.deepEqual(cl.seams(cuts), [0, 3, 5, 6]);
  assert.deepEqual(cl.seams(ten()), [0, 10]);
});

test("the whole file is recognised as unchanged", () => {
  assert.ok(cl.isWhole(ten(), 10));
  assert.ok(!cl.isWhole(cl.trimTo(ten(), 0, 9), 10));
  assert.ok(!cl.isWhole(cl.removeRange(ten(), 3, 5), 10));
});

test("a seek past the end lands on the last frame, not nowhere", () => {
  const cuts = cl.removeRange(ten(), 3, 5);
  const hit = cl.sourceAt(cuts, 999);
  assert.equal(hit?.index, 1);
  assert.equal(hit?.time, 10);
});

// ---- the pieces, one at a time (the timeline track's own edits) ----------

test("trimming moves ONE edge and leaves the other exactly where it was", () => {
  const cuts = cl.trimCut(ten(), 0, "end", 4, 10);
  assert.deepEqual(cuts, [{ start: 0, end: 4 }]);
  assert.deepEqual(cl.trimCut(cuts, 0, "start", 1, 10),
                   [{ start: 1, end: 4 }]);
});

test("a piece can be dragged back OUT to material that was cut away", () => {
  // Trim is undoable by hand, not only by Undo: the source is the limit, not
  // whatever the piece happens to cover now.
  const cuts = [{ start: 3, end: 5 }];
  assert.deepEqual(cl.trimCut(cuts, 0, "end", 9, 10), [{ start: 3, end: 9 }]);
  assert.deepEqual(cl.trimCut(cuts, 0, "start", 0, 10), [{ start: 0, end: 5 }]);
});

test("an edge stops at the source's ends and never crosses the other one", () => {
  const cuts = [{ start: 3, end: 5 }];
  assert.deepEqual(cl.trimCut(cuts, 0, "end", 99, 10), [{ start: 3, end: 10 }]);
  assert.deepEqual(cl.trimCut(cuts, 0, "start", -5, 10), [{ start: 0, end: 5 }]);
  // Dragged past the far edge it stops MIN_CUT short of it, both ways.
  assert.deepEqual(cl.trimCut(cuts, 0, "end", 1, 10),
                   [{ start: 3, end: 3 + cl.MIN_CUT }]);
  assert.deepEqual(cl.trimCut(cuts, 0, "start", 9, 10),
                   [{ start: 5 - cl.MIN_CUT, end: 5 }]);
});

test("trimming keeps the array's length and order, so a live drag can index it", () => {
  const three = [{ start: 0, end: 1 }, { start: 4, end: 5 }, { start: 8, end: 9 }];
  const out = cl.trimCut(three, 1, "end", 6, 10);
  assert.equal(out.length, 3);
  assert.deepEqual(out[1], { start: 4, end: 6 });
  assert.deepEqual(out[0], three[0]);
  assert.deepEqual(out[2], three[2]);
});

test("`to` is the index in the RESULT — the off-by-one a rightward drag hits", () => {
  const three = [{ start: 0, end: 1 }, { start: 4, end: 5 }, { start: 8, end: 9 }];
  // First piece dropped at the end: it really does end up last.
  assert.deepEqual(cl.moveCut(three, 0, 2),
                   [three[1], three[2], three[0]]);
  // And leftwards.
  assert.deepEqual(cl.moveCut(three, 2, 0),
                   [three[2], three[0], three[1]]);
  // A move onto its own slot changes nothing.
  assert.deepEqual(cl.moveCut(three, 1, 1), three);
});

test("a move out of range is refused rather than dropping a piece", () => {
  const three = [{ start: 0, end: 1 }, { start: 4, end: 5 }, { start: 8, end: 9 }];
  assert.deepEqual(cl.moveCut(three, 7, 0), three);
  // A `to` past the end simply lands last.
  assert.deepEqual(cl.moveCut(three, 0, 99), [three[1], three[2], three[0]]);
});

test("removing a piece leaves the others ALONE, even where they now meet", () => {
  const three = [{ start: 0, end: 2 }, { start: 5, end: 6 }, { start: 2, end: 4 }];
  // Dropping the middle leaves 0–2 and 2–4, which do run continuously — and
  // they stay TWO pieces. Joining them would quietly reduce the block count
  // after a delete, and a deliberate split is exactly two pieces that meet
  // (see `splitAt`). The render joins them; the editor must not.
  assert.deepEqual(cl.removeCuts(three, [1]),
                   [{ start: 0, end: 2 }, { start: 2, end: 4 }]);
  assert.deepEqual(cl.removeCuts(ten(), [0]), []);
});

test("SEVERAL pieces go in one call, against the ORIGINAL indices", () => {
  // One at a time is the way that loop is written wrong: the second index
  // means something else once the first has gone.
  const four = [{ start: 0, end: 1 }, { start: 2, end: 3 },
                { start: 4, end: 5 }, { start: 6, end: 7 }];
  assert.deepEqual(cl.removeCuts(four, [0, 2]), [four[1], four[3]]);
  assert.deepEqual(cl.removeCuts(four, [3, 1]), [four[0], four[2]]);
  assert.deepEqual(cl.removeCuts(four, []), four);
  assert.deepEqual(cl.removeCuts(four, [0, 1, 2, 3]), []);
  // An index that is not there is simply not there.
  assert.deepEqual(cl.removeCuts(four, [99]), four);
});

test("picking pieces is removing them the other way round", () => {
  const four = [{ start: 0, end: 1 }, { start: 2, end: 3 },
                { start: 4, end: 5 }, { start: 6, end: 7 }];
  assert.deepEqual(cl.pickCuts(four, [0, 2]), [four[0], four[2]]);
  // IN TRACK ORDER, whatever order they were picked in — the clipboard is an
  // assembly and the only order it can mean is the one on screen.
  assert.deepEqual(cl.pickCuts(four, [3, 1]), [four[1], four[3]]);
  assert.deepEqual(cl.pickCuts(four, []), []);
  // A picked-twice index is one piece, not two.
  assert.deepEqual(cl.pickCuts(four, [1, 1]), [four[1]]);
  // An index that is not there is simply not there — never a hole.
  assert.deepEqual(cl.pickCuts(four, [1, 99]), [four[1]]);
  // Copies, so editing what comes back cannot reach into the cutlist.
  const out = cl.pickCuts(four, [0]);
  out[0].end = 99;
  assert.equal(four[0].end, 1);
  // Two pieces that MEET stay two: they were split deliberately, and joining
  // them is `insertAt`'s decision at the paste, not this one's.
  const split = cl.splitAt(ten(), 4);
  assert.deepEqual(cl.pickCuts(split, [0, 1]), split);
  // A gap is an ordinary piece here, as everywhere else in this module.
  const withGap = [{ start: 0, end: 1 }, cl.gap(2), { start: 4, end: 5 }];
  assert.deepEqual(cl.pickCuts(withGap, [1]), [cl.gap(2)]);
});

test("a split makes two blocks and changes nothing about the video", () => {
  const cuts = cl.splitAt(ten(), 4);
  assert.deepEqual(cuts, [{ start: 0, end: 4 }, { start: 4, end: 10 }]);
  // The whole point: the output is identical, and now there are two pieces to
  // take hold of.
  assert.equal(cl.duration(cuts), 10);
  assert.deepEqual(cl.slice(cuts, 0), cl.slice(ten(), 0).length === 1
    ? [{ start: 0, end: 10 }] : cl.slice(cuts, 0));
});

test("a split splits the piece the playhead is IN, in edited time", () => {
  // Remove 3–5, so edited 4 s is source 6 s inside the second piece.
  const cuts = cl.removeRange(ten(), 3, 5);
  const out = cl.splitAt(cuts, 4);
  assert.deepEqual(out, [{ start: 0, end: 3 }, { start: 5, end: 6 }, { start: 6, end: 10 }]);
});

test("a split at a piece's own edge is refused, not a piece of no length", () => {
  assert.deepEqual(cl.splitAt(ten(), 0), ten());
  assert.deepEqual(cl.splitAt(ten(), 10), ten());
  assert.deepEqual(cl.splitAt(ten(), 0.001), ten());
  assert.deepEqual(cl.splitAt([], 1), []);
});

test("compact keeps a split; normalize would swallow it — the trap", () => {
  const split = cl.splitAt(ten(), 4);
  assert.equal(cl.compact(split).length, 2);
  // …which is exactly why the per-piece gestures do not use this one.
  assert.equal(cl.normalize(split).length, 1);
});

test("compact still drops what is too short to be video", () => {
  assert.deepEqual(cl.compact([{ start: 0, end: 1 }, { start: 4, end: 4.001 }]),
                   [{ start: 0, end: 1 }]);
});

// ---- when playback has left a piece ---------------------------------------

test("playedPast: only reaching the END means the piece is over", () => {
  const cut = { start: 10, end: 20 };
  assert.equal(cl.playedPast(cut, 15), false, "in the middle");
  assert.equal(cl.playedPast(cut, 19.9), false, "nearly there");
  assert.equal(cl.playedPast(cut, 20), true, "at the end");
  assert.equal(cl.playedPast(cut, 25), true, "past it");
});

test("playedPast: a time BEFORE the piece is not past it", () => {
  // The rule this replaced treated a time more than 0.3 s before the start as
  // "left the piece" and answered by jumping FORWARD — so a scrub backwards,
  // or a stale report from a seek in flight, walked the playhead the wrong
  // way. Scrubbing is what sets the index; there is nothing here to correct.
  const cut = { start: 10, end: 20 };
  assert.equal(cl.playedPast(cut, 0), false);
  assert.equal(cl.playedPast(cut, 9), false);
  assert.equal(cl.playedPast(cut, 9.9), false);
});

test("playedPast: a scrub BACKWARDS is not read as leaving the piece", () => {
  // THE REGRESSION, and the direction matters. `seekEdited` sets the index and
  // then seeks; the element goes on reporting the OLD time until the new one
  // decodes. The rule this replaced treated a time more than 0.3 s before the
  // piece's start as "left it" and answered by advancing — so every one of
  // those stale reports walked the playhead FORWARD through the cutlist, which
  // needs more than one piece to be reachable at all.
  const third = { start: 40, end: 50 };
  const oldRule = (c: { start: number; end: number }, t: number) =>
    !(t < c.end - 0.03 && t >= c.start - 0.3);   // true = "advance"
  assert.equal(oldRule(third, 5), true, "the old rule advanced on a stale time");
  assert.equal(cl.playedPast(third, 5), false, "the new one leaves it alone");
});

test("playedPast: no piece is never past", () => {
  assert.equal(cl.playedPast(undefined, 5), false);
});

// ---- gaps ------------------------------------------------------------------
// A gap is black picture and silence: an ordinary range in a source that does
// not exist. Putting it in a space of its own rather than giving it a shape of
// its own is what lets every primitive below stay exactly as it was.

test("a gap has a length like any other piece", () => {
  assert.equal(cl.duration([cl.gap(2)]), 2);
  assert.equal(cl.duration([{ start: 0, end: 1 }, cl.gap(2)]), 3);
  assert.ok(cl.isGap(cl.gap(2)));
  assert.ok(!cl.isGap({ start: 0, end: 2 }));
});

test("a gap takes its place in edited time", () => {
  const cuts = [{ start: 0, end: 2 }, cl.gap(3), { start: 5, end: 6 }];
  assert.equal(cl.cutStart(cuts, 1), 2);
  assert.equal(cl.cutStart(cuts, 2), 5);
  assert.equal(cl.duration(cuts), 6);
});

test("a gap and a range are never joined, however they meet", () => {
  // Two ranges that touch ARE one shot; a gap between them is not adjacent to
  // either, and joining across it would silently delete the black.
  const out = cl.normalize([{ start: 0, end: 2 }, cl.gap(1), { start: 2, end: 4 }]);
  assert.equal(out.length, 3);
  assert.ok(cl.isGap(out[1]));
});

test("two gaps that meet become one", () => {
  const out = cl.normalize([cl.gap(1), cl.gap(2)]);
  assert.equal(out.length, 1);
  assert.equal(out[0].end - out[0].start, 3);
});

test("a gap survives being sliced, moved, split and removed", () => {
  const cuts = [{ start: 0, end: 2 }, cl.gap(4), { start: 5, end: 6 }];
  // Slicing through it keeps the part that is left a gap.
  const mid = cl.slice(cuts, 3, 5);
  assert.equal(mid.length, 1);
  assert.ok(cl.isGap(mid[0]), "a slice of a gap is a gap");
  assert.equal(cl.duration(mid), 2);
  // Splitting inside it gives two gaps.
  const split = cl.splitAt(cuts, 4);
  assert.equal(split.length, 4);
  assert.ok(cl.isGap(split[1]) && cl.isGap(split[2]));
  assert.equal(cl.duration(split), cl.duration(cuts));
  // Moving it to the front keeps it a gap.
  const moved = cl.moveCut(cuts, 1, 0);
  assert.ok(cl.isGap(moved[0]));
  // And it deletes like any other piece.
  const gone = cl.removeCuts(cuts, [1]);
  assert.equal(gone.length, 2);
  assert.ok(!gone.some(cl.isGap));
  assert.equal(cl.duration(gone), 3);
});

test("a gap is trimmed against itself, not against the file", () => {
  // A range cannot be dragged out past the material that exists. A gap names
  // no material, so capping it at the film's own length would be arbitrary.
  const cuts = [cl.gap(2)];
  const longer = cl.trimCut(cuts, 0, "end", cl.GAP + 90, 10);
  assert.equal(longer[0].end - longer[0].start, 90);
  assert.ok(cl.isGap(longer[0]));
});

test("a lone gap is not the whole file", () => {
  assert.ok(!cl.isWhole([cl.gap(10)], 10), "a black screen is very much an edit");
  assert.ok(cl.isWhole([{ start: 0, end: 10 }], 10));
});

// ---- carrying a piece somewhere -------------------------------------------

test("a drop on MATERIAL inserts at the nearest seam and pushes the rest back", () => {
  // The gesture rearranges; it must not destroy, and two pieces may never
  // overlap. Four seconds dropped two seconds into another clip cannot lie
  // there, so they go to the nearest seam — the start — and that clip follows.
  const cuts = [{ start: 0, end: 4 }, { start: 10, end: 14 }];
  const { cuts: out, index } = cl.moveCutTo(cuts, 1, 2);
  assert.equal(cl.duration(out), cl.duration(cuts), "nothing is created or lost");
  assert.deepEqual(out.map((c) => [c.start, c.end]), [[10, 14], [0, 4]]);
  assert.equal(index, 0);
});

test("a drop on BLACK is free placement, and leaves black where it was", () => {
  // A clip, eight seconds of black, another clip: the first can be put
  // anywhere in that black, nothing else moves, and the film keeps its length.
  const cuts = [{ start: 0, end: 2 }, cl.gap(8), { start: 30, end: 32 }];
  const { cuts: out, index } = cl.moveCutTo(cuts, 0, 5);
  assert.equal(cl.duration(out), cl.duration(cuts));
  assert.equal(cl.cutStart(out, index), 5);
  assert.deepEqual([out[index].start, out[index].end], [0, 2]);
  assert.ok(cl.isGap(out[0]) && out[0].end - out[0].start === 5);
});

test("a piece that would half-cover a clip is not laid over it", () => {
  // Two seconds of black and then a clip: dropping the other clip one second
  // in would overlap, so it takes the nearest seam instead.
  const cuts = [{ start: 0, end: 2 }, cl.gap(2), { start: 20, end: 26 }];
  const { cuts: out } = cl.moveCutTo(cuts, 0, 3);
  assert.equal(cl.duration(out), cl.duration(cuts));
  assert.ok(!out.some((c) => !cl.isGap(c) && out.some((o) =>
    o !== c && !cl.isGap(o) && o.start < c.end && c.start < o.end)),
    "nothing overlaps");
});

test("a drop back onto its own start changes nothing", () => {
  const cuts = [{ start: 0, end: 2 }, { start: 10, end: 20 }];
  const { cuts: out } = cl.moveCutTo(cuts, 1, 2);
  assert.deepEqual(out.map((c) => [c.start, c.end]), [[0, 2], [10, 20]]);
});

test("an INSERT has a flat stretch: a nudge inside its own footprint stays put", () => {
  // Three clips shoulder to shoulder — there is nowhere free to go, so every
  // drop is an insert, and one aimed inside the piece's own slot resolves to
  // the seam it already sits on.
  const cuts = [{ start: 0, end: 2 }, { start: 4, end: 8 }, { start: 20, end: 22 }];
  for (const at of [2, 3, 5]) {
    const { cuts: out } = cl.moveCutTo(cuts, 1, at);
    assert.deepEqual(out.map((c) => [c.start, c.end]),
      [[0, 2], [4, 8], [20, 22]], `dropped at ${at}`);
  }
});

test("dropping past the end pads with black, and never trails it", () => {
  // Past the end is empty, so this is a free placement — and it is the one
  // way to open black on a solid run of clips.
  const cuts = [{ start: 0, end: 2 }, { start: 4, end: 6 }];
  const { cuts: out, index } = cl.moveCutTo(cuts, 1, 10);
  assert.equal(cl.duration(out), 12);
  assert.deepEqual([out[index].start, out[index].end], [4, 6]);
  assert.equal(index, out.length - 1, "it is the last thing in the video");
  assert.ok(out.some(cl.isGap), "and the distance is real black");
  // And the same piece dragged back to the front leaves no tail of black.
  const back = cl.moveCutTo(out, index, 0);
  assert.ok(!cl.isGap(back.cuts[back.cuts.length - 1]),
            "a video does not end later because a clip moved earlier");
});

test("moving does not re-join a deliberate split", () => {
  // `slice` normalizes, which would fold these two halves back into one — the
  // trap `compact` exists for, now on the walk a move does.
  const cuts = [{ start: 0, end: 5 }, { start: 5, end: 10 }, { start: 20, end: 22 }];
  const { cuts: out } = cl.moveCutTo(cuts, 2, 4);
  assert.equal(out.length, 3);
  assert.ok(out.some((c) => c.start === 0 && c.end === 5));
  assert.ok(out.some((c) => c.start === 5 && c.end === 10));
});

test("two gaps left touching become one", () => {
  const cuts = [cl.gap(2), { start: 0, end: 1 }, cl.gap(2), { start: 5, end: 9 }];
  const { cuts: out } = cl.moveCutTo(cuts, 1, 0);
  // The piece leaves a hole between the two stretches of black: black next to
  // black is one stretch of black.
  assert.equal(out.filter(cl.isGap).length, 1);
  assert.equal(cl.duration(out), cl.duration(cuts));
});

test("a piece snaps to the edges around it, the playhead and the start", () => {
  const cuts = [{ start: 0, end: 4 }, { start: 10, end: 12 }];
  const times = cl.snapTimes(cuts, 1, 7);
  assert.ok(times.includes(0) && times.includes(4) && times.includes(7));
  assert.ok(!times.includes(6), "its own edges are not candidates");
  // Its START lands on a neighbour's end…
  assert.equal(cl.snapTo(4.2, 2, times, 0.5), 4);
  // …and so does its END, which is what butts two clips together.
  assert.equal(cl.snapTo(1.9, 2, times, 0.5), 2);
  // Out of reach, it stays where the hand put it.
  assert.equal(cl.snapTo(6, 2, times, 0.5), 6);
});

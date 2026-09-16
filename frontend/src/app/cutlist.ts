/**
 * The video editor's CUTLIST: which parts of the source file, in which order,
 * make up the video you are watching.
 *
 * Every edit the window offers is a rewrite of this one list — trimming keeps
 * a range, removing takes one out, cut/copy/paste move and duplicate them — so
 * nothing downstream needs a tag set of operations. The backend takes the
 * list and assembles it; nothing is applied to the file until Save.
 *
 * **Two timelines, and keeping them apart is the whole of this module.**
 * SOURCE time is a position in the file on disk. EDITED time is a position in
 * the assembly, which is what the scrubber shows and what every operation
 * below takes — because once a range has been removed or a copy pasted in, the
 * two no longer agree, and an edit expressed against the source could not say
 * which copy it meant.
 *
 * One primitive does the work: `slice(cuts, a, b)` is the part of the assembly
 * between two edited times. Removing is the two slices either side, trimming
 * is the slice itself, pasting is a slice, the clip, and a slice. Written as
 * separate walks they would each need their own boundary handling, which is
 * exactly where an off-by-one frame lives.
 */

export interface Cut {
  /** Seconds into the SOURCE file. */
  start: number;
  end: number;
}

/** Shorter than this is nothing: a rounding artefact of a drag rather than a
 *  piece of video. Matches the backend's `videoedit.MIN_CUT`. */
export const MIN_CUT = 0.02;

/**
 * Where a GAP's range lives: a source that does not exist, far below zero.
 * Matches `videoedit.GAP`, and the wire format carries one unchanged.
 *
 * A gap is black picture and silence — an ordinary `{start, end}` pair in THIS
 * space, so its length is `end - start` exactly like a real piece's. That is
 * the whole reason it is a second source rather than a second SHAPE: `slice`,
 * `duration`, `cutStart`, `sourceAt`, `editedAt`, `splitAt`, `trimCut`,
 * `moveCut` and `removeCuts` all go on working with no branch at all, because
 * every one of them is arithmetic on lengths and offsets. Only the places that
 * touch the actual FILE — the player, the render graph — ask which kind a
 * piece is.
 *
 * Far below zero rather than at -1 because a slightly negative start already
 * meant something (a drag overshooting the left edge, clamped to 0), so the
 * two spaces are put a billion seconds apart where nothing can reach across.
 */
export const GAP = -1e9;

/** Anything at or below this is in gap space — halfway to `GAP`, so a gap
 *  sliced or split anywhere inside itself is still unmistakably one. */
export const GAP_MAX = -1e8;

export function isGap(c: Cut): boolean {
  return c.start <= GAP_MAX;
}

/** A gap of `seconds`. */
export function gap(seconds: number): Cut {
  return { start: GAP, end: GAP + Math.max(0, seconds) };
}

export function duration(cuts: Cut[]): number {
  return cuts.reduce((n, c) => n + Math.max(0, c.end - c.start), 0);
}

/** Drop the empty pieces and join the ones that meet — two ranges touching at
 *  the same source timestamp are one continuous shot, and keeping them apart
 *  would put a concat boundary in the middle of it. */
export function normalize(cuts: Cut[]): Cut[] {
  const out: Cut[] = [];
  for (const c of cuts) {
    if (c.end - c.start < MIN_CUT) continue;
    const last = out[out.length - 1];
    if (last && isGap(last) && isGap(c)) {
      // Two gaps in a row are ALWAYS one longer gap. Unlike ranges, they need
      // no timestamps to agree: consecutive in the list is consecutive in the
      // assembly, and one stretch of black is one stretch of black. (They
      // would rarely meet anyway — two gaps made independently both begin at
      // `GAP`, so they overlap in gap space rather than touching.)
      last.end += c.end - c.start;
    } else if (last && !isGap(last) && !isGap(c)
        && Math.abs(last.end - c.start) < 1e-6) {
      last.end = c.end;
    } else {
      out.push({ start: c.start, end: c.end });
    }
  }
  return out;
}

/**
 * The part of the assembly between two EDITED times, as its own cutlist.
 *
 * The one primitive everything else is written in terms of. `b` past the end
 * (or omitted) means "to the end", which is what makes "everything after here"
 * a slice like any other.
 */
export function slice(cuts: Cut[], a: number, b = Infinity): Cut[] {
  const from = Math.max(0, a);
  const to = Math.max(from, b);
  const out: Cut[] = [];
  let at = 0;                                   // edited time at this cut's start
  for (const c of cuts) {
    const len = Math.max(0, c.end - c.start);
    const lo = Math.max(from, at);
    const hi = Math.min(to, at + len);
    if (hi > lo) {
      out.push({ start: c.start + (lo - at), end: c.start + (hi - at) });
    }
    at += len;
    if (at >= to) break;
  }
  return normalize(out);
}

/** Keep only `[a, b)` — the Trim action. */
export function trimTo(cuts: Cut[], a: number, b: number): Cut[] {
  return slice(cuts, a, b);
}

/** Take `[a, b)` out — the Remove action, and the second half of Cut. */
export function removeRange(cuts: Cut[], a: number, b: number): Cut[] {
  return normalize([...slice(cuts, 0, a), ...slice(cuts, b)]);
}

/** Splice `clip` in at an edited time — the Paste action. */
export function insertAt(cuts: Cut[], at: number, clip: Cut[]): Cut[] {
  return normalize([...slice(cuts, 0, at), ...clip, ...slice(cuts, at)]);
}

/**
 * Where an edited time lands in the SOURCE, as a cut index and a time in it.
 *
 * The index matters and is why this does not just return a number: after a
 * paste the same source second appears twice in the assembly, so "which copy"
 * is a question only the index answers — and the player has to know, or
 * playing the second copy would jump back to the first.
 */
export function sourceAt(cuts: Cut[], t: number):
    { index: number; time: number } | null {
  if (cuts.length === 0) return null;
  let at = 0;
  for (let i = 0; i < cuts.length; i++) {
    const len = Math.max(0, cuts[i].end - cuts[i].start);
    if (t < at + len || i === cuts.length - 1) {
      const into = Math.max(0, Math.min(len, t - at));
      return { index: i, time: cuts[i].start + into };
    }
    at += len;
  }
  return null;
}

/** Where a cut starts in EDITED time. */
export function cutStart(cuts: Cut[], index: number): number {
  let at = 0;
  for (let i = 0; i < index && i < cuts.length; i++) {
    at += Math.max(0, cuts[i].end - cuts[i].start);
  }
  return at;
}

/** The edited time of a source position INSIDE a known cut. The pair to
 *  `sourceAt`, and the direction the player runs in: the element reports a
 *  source time and the scrubber needs an edited one. */
export function editedAt(cuts: Cut[], index: number, sourceTime: number): number {
  const c = cuts[index];
  if (!c) return 0;
  const into = Math.max(0, Math.min(c.end - c.start, sourceTime - c.start));
  return cutStart(cuts, index) + into;
}

/** The whole file, uncut — a fresh editor's cutlist. */
export function whole(sourceDuration: number): Cut[] {
  return sourceDuration > 0 ? [{ start: 0, end: sourceDuration }] : [];
}

/** Is this cutlist just the whole file? Nothing to render, nothing to save. */
export function isWhole(cuts: Cut[], sourceDuration: number): boolean {
  return cuts.length === 1
    && !isGap(cuts[0])
    && cuts[0].start < MIN_CUT
    && cuts[0].end >= sourceDuration - MIN_CUT;
}

/**
 * ---- THE PIECES, ONE AT A TIME -----------------------------------------
 *
 * The three above rewrite the assembly through `slice`, which is what a marked
 * RANGE means. These three act on ONE PIECE, which is what a block on the
 * timeline track means, and they are deliberately a different shape: they keep
 * the array's length and order (`removeCut` excepted) so a live drag can index
 * into it frame by frame without the piece under the pointer moving or merging
 * away mid-gesture.
 *
 * `normalize` is therefore the CALLER's, once, at the end of the gesture —
 * which is also the one undo entry it should leave behind.
 */

/**
 * Move ONE EDGE of a piece, in source time. The other edge stays exactly where
 * it is, which is why the edge is named rather than both ends passed: a drag
 * moves one of them, and a function taking both has to guess which one won
 * when they cross.
 *
 * A piece may be dragged back OUT to material that was cut away — the only
 * limits are the source's own ends and `MIN_CUT` — so a trim is undoable by
 * hand as well as by Undo. Two pieces are allowed to cover the same source
 * seconds, because that is what pasting a copy already does.
 */
export function trimCut(
  cuts: Cut[], index: number, edge: "start" | "end", to: number,
  sourceDuration: number,
): Cut[] {
  const c = cuts[index];
  if (!c) return cuts;
  // A GAP is bounded by nothing but itself. The source's ends are what stop a
  // range being dragged out past the material that exists; a gap names no
  // material, so it can be made as long as anybody likes and as short as
  // MIN_CUT. Clamping it to the file would have capped a black stretch at the
  // film's own length for no reason at all.
  const lo = isGap(c) ? GAP : 0;
  const hi = isGap(c) ? Infinity : sourceDuration;
  const next = edge === "start"
    ? { start: clamp(to, lo, c.end - MIN_CUT), end: c.end }
    : { start: c.start, end: clamp(to, c.start + MIN_CUT, hi) };
  const out = cuts.slice();
  out[index] = next;
  return out;
}

/**
 * Put the piece at `from` in position `to`.
 *
 * `to` is its index in the RESULT, not an "insert before" index into the
 * original — those two differ by one whenever a piece moves rightwards, which
 * is the classic way a drag lands one slot short of where it was dropped.
 */
export function moveCut(cuts: Cut[], from: number, to: number): Cut[] {
  if (from < 0 || from >= cuts.length) return cuts;
  const out = cuts.slice();
  const [c] = out.splice(from, 1);
  out.splice(clamp(to, 0, out.length), 0, c);
  return out;
}

/**
 * Carry a piece to an EDITED TIME — the timeline's drag, and what makes this a
 * video track rather than a queue.
 *
 * `moveCut` above is a REORDER: the pieces stay shoulder to shoulder and one of
 * them changes place in the line. That is what the track did, because a cutlist
 * had no way to say "nothing here" — and it meant dragging a clip a second to
 * the right either did nothing at all or jumped it past its neighbour. Gaps are
 * ordinary pieces, so a POSITION can be said, and the gesture is what it looks
 * like.
 *
 * **TWO PIECES MAY NEVER OVERLAP**, and the whole rule falls out of that. The
 * piece is lifted, leaving a hole of its own length so that nothing else moves,
 * and then one of two things happens:
 *
 *   - **The drop fits in BLACK** (or past the end of everything): the piece
 *     goes exactly there. That is free placement, and it is what makes the
 *     timeline a thing you arrange pieces on. Nothing moves and nothing is
 *     lost: black is being swapped for black.
 *   - **The drop would land on MATERIAL**: it is INSERTED instead, at the
 *     nearest seam — a split between two pieces, or a gap's start or end,
 *     whichever is closer — and everything after it moves along to make room.
 *     The hole it came out of closes up to pay for that room, so the film keeps
 *     its length. OVERWRITING is the other reading (the piece laid over
 *     `[at, at + its length)`, whatever was under it trimmed away) and it
 *     throws material away on a gesture whose whole purpose is to rearrange it.
 *
 * Two rules survive from the overwrite:
 *   - Dropping past the end pads with a gap, so a piece really can be parked
 *     after everything and the black in between is real. That is also the one
 *     way to open black on a solid run of clips, and it is why the Gap button
 *     is gone: black is simply where a clip is not.
 *   - A gap at the very END is dropped. It is the one place black says nothing
 *     — a video does not end later because its last clip moved earlier.
 *
 * `at` is measured against the film as it stands, i.e. WITH the piece still in
 * it, because that is the timeline the pointer is over. The insert point is
 * that time in the closed-up film, which is a continuous, non-decreasing map
 * with one flat stretch: anywhere inside the piece's own footprint leaves it
 * exactly where it is, which is what makes a drag that does not mean to move it
 * harmless.
 *
 * Returns the piece's new INDEX as well: the track draws it lifted and marks
 * where it will land, and with free positioning that is no longer derivable
 * from the drop time by counting.
 */
export function moveCutTo(cuts: Cut[], index: number, at: number):
    { cuts: Cut[]; index: number } {
  const c = cuts[index];
  if (!c) return { cuts, index };
  const len = Math.max(0, c.end - c.start);
  const piece = { start: c.start, end: c.end };
  const want = Math.max(0, at);

  // LIFTED IN PLACE: a gap of its own length, so every other piece is still at
  // the edited time it was at.
  const lifted = cuts.map((x, i) => (i === index ? gap(len) : x));
  // It lands on black, so it TAKES that black's place — swallowing `len` of it
  // rather than pushing it along, or a move within a hole would lengthen the
  // film by the piece every time.
  if (isBlank(lifted, want, want + len)) return splice(lifted, piece, want, len);

  // It would land on material, so INSERT at the nearest seam of the film
  // WITHOUT it, swallowing nothing. `compact` rather than `normalize`, so the
  // two neighbours that have just met do not fuse a deliberate split.
  const rest = compact(cuts.filter((_, i) => i !== index));
  const hole = cutStart(cuts, index);
  const target = want <= hole ? want : Math.max(hole, want - len);
  return splice(rest, piece, nearest(seams(rest), target), 0);
}

/** Put `piece` into `cuts` at an edited time, swallowing `eats` seconds of
 *  what was there, padding past the end, and never leaving black trailing the
 *  result. Both halves of a move end here. */
function splice(cuts: Cut[], piece: Cut, at: number, eats: number):
    { cuts: Cut[]; index: number } {
  const total = duration(cuts);
  const head = part(cuts, 0, at);
  // Past the end of everything: the distance is real black, not a shrug.
  if (at > total) head.push(gap(at - total));
  const out = compact([...head, piece, ...part(cuts, at + eats, Infinity)]);
  while (out.length > 1 && isGap(out[out.length - 1])) out.pop();
  // WHERE THE PIECE ENDED UP, counted through the same tidy-up rather than
  // from `head.length`: `compact` joins two gaps that meet, so a head whose
  // last two entries are both black is one entry in the result and the piece
  // is a slot earlier than it was put in. (`compact` only ever merges with the
  // element immediately before, so the count up to and including the piece is
  // the same whether the tail is there or not.)
  const upto = compact([...head, piece]);
  return { cuts: out, index: Math.min(upto.length - 1, out.length - 1) };
}

/** Is every second of `[a, b)` black — or past the end, which is as empty as
 *  black gets? The test that decides whether a drop is free placement or an
 *  insert. */
function isBlank(cuts: Cut[], a: number, b: number): boolean {
  let at = 0;
  for (const c of cuts) {
    const len = Math.max(0, c.end - c.start);
    if (Math.min(b, at + len) > Math.max(a, at) && !isGap(c)) return false;
    at += len;
    if (at >= b) break;
  }
  return true;
}

/** Every place a piece can be spliced in without cutting one in half: the
 *  start and each piece's end — so every split between two pieces, and both
 *  ends of every gap. */
export function seams(cuts: Cut[]): number[] {
  const out = [0];
  let at = 0;
  for (const c of cuts) { at += Math.max(0, c.end - c.start); out.push(at); }
  return out;
}

function nearest(values: number[], to: number): number {
  let best = to;
  let by = Infinity;
  for (const v of values) {
    const d = Math.abs(v - to);
    if (d < by) { by = d; best = v; }
  }
  return best;
}

/**
 * `slice`'s walk without its `normalize` — the part of the assembly between two
 * edited times, JOINING NOTHING.
 *
 * The distinction is the same one `compact` draws against `normalize`, and for
 * the same reason: a move must not silently re-join a deliberate split
 * somewhere else on the timeline just because it walked past it.
 */
function part(cuts: Cut[], a: number, b: number): Cut[] {
  const out: Cut[] = [];
  let at = 0;
  for (const c of cuts) {
    const len = Math.max(0, c.end - c.start);
    const lo = Math.max(a, at);
    const hi = Math.min(b, at + len);
    if (hi > lo) out.push({ start: c.start + (lo - at), end: c.start + (hi - at) });
    at += len;
    if (at >= b) break;
  }
  return out;
}

/**
 * The times a dragged piece's edges want to land on: every other piece's edges,
 * the playhead, and the start.
 *
 * Snapping is why a track feels like a track — butting two clips together by
 * hand at 4 px per second is not something anybody can do, and a frame of black
 * left between them is invisible until it plays. The caller decides how near is
 * near enough, in PIXELS, because that is the tolerance a hand has.
 */
export function snapTimes(cuts: Cut[], skipIndex: number, playhead: number): number[] {
  const out = [0, playhead];
  let at = 0;
  for (let i = 0; i < cuts.length; i++) {
    const len = Math.max(0, cuts[i].end - cuts[i].start);
    if (i !== skipIndex) { out.push(at); out.push(at + len); }
    at += len;
  }
  return out;
}

/** Move `at` (with `len` behind it) onto a snap time when one is within
 *  `tolerance` of either of its edges. The NEAREST wins, and the piece's own
 *  two edges are tried against every candidate — a clip butts up on its left as
 *  readily as on its right. */
export function snapTo(at: number, len: number, times: number[], tolerance: number): number {
  let best = at;
  let bestGap = tolerance;
  for (const t of times) {
    for (const candidate of [t, t - len]) {
      const d = Math.abs(candidate - at);
      if (d < bestGap && candidate >= 0) { bestGap = d; best = candidate; }
    }
  }
  return best;
}

/** Drop pieces by index. Unlike the two above this ends a gesture rather than
 *  running through one, so it compacts.
 *
 *  Several at once, because the track selects several: removing them one at a
 *  time would shift the indices under the caller between calls, which is the
 *  way that loop is written wrong. */
export function removeCuts(cuts: Cut[], indices: Iterable<number>): Cut[] {
  const drop = new Set(indices);
  return compact(cuts.filter((_, i) => !drop.has(i)));
}

/**
 * KEEP pieces by index — `removeCuts`' counterpart, and what copying a
 * selection of blocks produces.
 *
 * **In TRACK order, whatever order they were picked in.** The clipboard is an
 * assembly, and the only order it can mean is the one on screen: ⌘-clicking
 * the fourth block and then the first must not paste them back to front.
 *
 * **Not normalized, and not compacted either.** Two picked pieces that meet in
 * the source were split deliberately, and joining them here would decide for
 * `insertAt` — which normalizes at the paste, where the question actually
 * belongs. Out-of-range indices are ignored rather than yielding holes; a
 * selection outliving the cutlist it named is a caller's bug, not a shape the
 * clipboard should be able to hold.
 */
export function pickCuts(cuts: Cut[], indices: Iterable<number>): Cut[] {
  return [...new Set(indices)]
    .sort((a, b) => a - b)
    .map((i) => cuts[i])
    .filter((c): c is Cut => c != null)
    .map((c) => ({ start: c.start, end: c.end }));
}

/**
 * Cut the piece under an EDITED time in two, there.
 *
 * The output is unchanged by this — the two halves play exactly what the one
 * piece did — and that is the point: it makes them two BLOCKS, which can then
 * be moved, trimmed and deleted apart from each other. A razor does nothing
 * on its own in every editing program for the same reason.
 *
 * **It must not be normalized afterwards, and this is the trap.** `normalize`
 * joins ranges that meet at the same source timestamp, which is exactly what
 * a split produces — so a split followed by a normalize is a no-op, and a
 * split followed by ANY other gesture would silently undo itself. That is why
 * the per-piece gestures compact rather than normalize (see `compact`). The
 * backend still joins them when it renders, which is right there: at that
 * point the two really are one continuous shot, and encoding them as two
 * segments puts a concat boundary in the middle of it for nothing.
 *
 * A split at a piece's own edge is refused rather than making a piece of no
 * length.
 */
export function splitAt(cuts: Cut[], at: number): Cut[] {
  const hit = sourceAt(cuts, at);
  if (!hit) return cuts;
  const c = cuts[hit.index];
  if (hit.time - c.start < MIN_CUT || c.end - hit.time < MIN_CUT) return cuts;
  const out = cuts.slice();
  out.splice(hit.index, 1,
             { start: c.start, end: hit.time },
             { start: hit.time, end: c.end });
  return out;
}

/**
 * Drop the empty pieces, join two GAPS that meet, and join nothing else.
 *
 * `normalize` is right for the range operations — removing a stretch and
 * putting the halves back together really does produce one continuous shot —
 * and wrong for the per-piece ones, where two pieces meeting in the source is
 * something somebody asked for (see `splitAt`). Same tidy-up, one rule fewer.
 *
 * Gaps are the exception, because there is nothing to ask for: black next to
 * black is one stretch of black however it came about, and leaving the two
 * apart would put two blocks on the track that no gesture can tell apart —
 * which is exactly what carrying a piece out from between two gaps produces.
 */
export function compact(cuts: Cut[]): Cut[] {
  const out: Cut[] = [];
  for (const c of cuts) {
    if (c.end - c.start < MIN_CUT) continue;
    const last = out[out.length - 1];
    if (last && isGap(last) && isGap(c)) last.end += c.end - c.start;
    else out.push({ start: c.start, end: c.end });
  }
  return out;
}

/** How far past a piece's end still counts as being in it — a frame's worth of
 *  disagreement between the element's clock and React's mirror of it. */
export const PLAYED_PAST_EPS = 0.03;

/**
 * Has playback run PAST this piece, so the playhead should jump to the next?
 *
 * The element plays the source straight through; the edit is what says where
 * to skip. This is the whole of that decision, pulled out of the effect that
 * makes it so it can be stated as tests rather than as prose.
 *
 * The rule is deliberately ONE-SIDED: only reaching the END means the piece is
 * over. The version this replaced also fired when the time was more than 0.3 s
 * BEFORE the piece's start, and answered that by jumping FORWARD — the wrong
 * direction for the only thing that produces such a time. Scrubbing backwards
 * sets the index and then seeks, and the element goes on reporting the OLD
 * time until the new one decodes; read as "left the piece", every one of those
 * reports advanced the playhead, so a scrub backwards walked forward through
 * the cutlist instead. It is only reachable with more than one piece, which is
 * why the symptom looked like the split's fault.
 *
 * The other half of the fix is not here, because it is a fact about the
 * element rather than about the cutlist: a caller must ignore reports while a
 * seek is in flight (`video.seeking`), or its correction cancels the seek and
 * the next report starts another.
 */
export function playedPast(cut: Cut | undefined, time: number): boolean {
  if (!cut) return false;
  return time >= cut.end - PLAYED_PAST_EPS;
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}


/**
 * Pure helpers for the annotator's video track model (unit-tested under
 * `node --test`, so no DOM/React here). A "track" is the set of an item's timed
 * boxes that share a `track_id` — one moving subject, several timed placements.
 */


/** True when time `t` falls inside the entry's range (single-frame = at start). */
export function entryContains(e: { start: number; end: number | null }, t: number, eps = 1e-3): boolean {
  if (e.end == null) return Math.abs(t - e.start) <= eps;
  return t >= e.start - eps && t <= e.end + eps;
}




/** One stretch of film a tag covers. `end == null` = a single frame at `start`
 *  — the same shape a time-only `ItemTagBox` is stored in. */
export interface Span { start: number; end: number | null }

// Internally every span is a closed interval; a single frame is zero-length.
type Iv = { s: number; e: number };
const toIv = (sp: Span): Iv => ({ s: sp.start, e: sp.end ?? sp.start });
// Back to the stored shape: anything shorter than the tolerance (half a frame,
// in practice) is one frame, not a sliver of a range nobody can see or seek to.
const toSpan = (iv: Iv, eps: number): Span =>
  ({ start: iv.s, end: iv.e - iv.s > eps ? iv.e : null });

/** Sort and fuse: intervals that overlap, touch, or sit less than `eps` apart
 *  become one. `eps` is the caller's idea of "no gap" — half a frame. */
function fuse(ivs: Iv[], eps: number): Iv[] {
  const out: Iv[] = [];
  for (const iv of [...ivs].sort((a, b) => a.s - b.s)) {
    const last = out[out.length - 1];
    if (last && iv.s <= last.e + eps) last.e = Math.max(last.e, iv.e);
    else out.push({ ...iv });
  }
  return out;
}

/**
 * Union `range` into a tag's coverage — "this tag also applies here".
 * Returns the whole coverage, normalized (sorted, non-overlapping).
 */
export function addSpan(spans: Span[], range: Span, eps = 1e-6): Span[] {
  return fuse([...spans.map(toIv), toIv(range)], eps).map((iv) => toSpan(iv, eps));
}

/**
 * The stretches covered by ANY of several tags — which is the coverage a tag
 * IMPLIED by them inherits.
 *
 * A film's tag applies to stretches rather than to the whole of it, and an
 * entailed tag is true exactly where something entailing it is true: `poodle`
 * over 0–10 and `terrier` over 20–30 both imply `dog`, so `dog` covers both.
 * The union, not the intersection — either one being on screen is enough.
 *
 * **`null` is "the whole film", and it is contagious.** A tag with no ranges
 * of its own applies throughout, so anything it entails does too, whatever
 * the other sources say — one untimed `poodle` makes `dog` a whole-film tag
 * even if `terrier` is confined to a minute of it. Same for no sources at
 * all: nothing is known, so nothing is claimed.
 *
 * Signs are not read here, exactly as `tagRanges` does not read them: a
 * negative stretch is still a stretch this tag's row is about, and the rows
 * that already show ranges (subject, place, event) make the same choice.
 */
export function coverageOfAll(perTag: Span[][], eps = 1e-6): Span[] | null {
  if (perTag.length === 0 || perTag.some((spans) => spans.length === 0)) {
    return null;
  }
  let out: Span[] = [];
  for (const spans of perTag) {
    for (const sp of spans) out = addSpan(out, sp, eps);
  }
  return out;
}

/**
 * Cut `range` out of a tag's coverage — "this tag does not apply here".
 * A span straddling the range survives as the pieces on either side; a single
 * frame inside the range disappears.
 */
export function subtractSpan(spans: Span[], range: Span, eps = 1e-6): Span[] {
  const cut = toIv(range);
  const out: Iv[] = [];
  for (const iv of fuse(spans.map(toIv), eps)) {
    // Clear of the cut on one side or the other: kept whole.
    if (iv.e < cut.s - eps || iv.s > cut.e + eps) { out.push(iv); continue; }
    if (iv.s < cut.s - eps) out.push({ s: iv.s, e: Math.min(iv.e, cut.s) });
    if (iv.e > cut.e + eps) out.push({ s: Math.max(iv.s, cut.e), e: iv.e });
  }
  return out.map((iv) => toSpan(iv, eps));
}

/**
 * The next moment in `times` that lies on a different FRAME than `now`, walking
 * `dir` (+1 forward, -1 back); null when there is none that way.
 *
 * Frames, not seconds, on purpose. Seeking to a moment lands the element on the
 * nearest frame boundary — a few milliseconds off the value asked for — and a
 * seconds comparison then still reads that same moment as "ahead", so a jump
 * button stayed lit after taking you exactly where it pointed, and clicking it
 * again did nothing. Comparing frame numbers makes "the frame I am on" one
 * value, however the seek rounded.
 */
export function nextStop(
  times: number[], now: number, dir: 1 | -1, fps: number
): number | null {
  const rate = fps > 0 ? fps : 25;
  // The frame CONTAINING t — floor, not round: frames occupy [n/fps, (n+1)/fps),
  // and a seek reports the start of the frame it landed on, which must come out
  // as the same frame as the time that was asked for.
  const frame = (t: number) => Math.floor(t * rate + 1e-6);
  const here = frame(now);
  const ahead = times.filter((t) => (dir > 0 ? frame(t) > here : frame(t) < here));
  if (ahead.length === 0) return null;
  return dir > 0 ? Math.min(...ahead) : Math.max(...ahead);
}

/** The shape a stored box is read in here — a `TagBox` narrowed to what a
 *  RANGE is: a time, no geometry, and a sign of its own. */
export interface RangeBox {
  x?: number | null;
  time_start?: number | null;
  time_end?: number | null;
  negative?: boolean | null;
}

/** The stretches of film a tag covers, in order.
 *
 *  A range is a box with a TIME and NO GEOMETRY — a box that has geometry is a
 *  still's, or a moving subject's placement, and says nothing about when the
 *  tag applies. This is the one definition of that test, because it decides
 *  what four different readers show: the tag rows, the activity lanes, the
 *  range add/subtract, and now the subject / place / event rows, each of which
 *  is a view of the SAME tag.
 *
 *  A tag with no ranges returns none, which is not "never" but "the whole
 *  film" — the caller shows no subtitle rather than an empty one. */
export function tagRanges(boxes: RangeBox[] | null | undefined): Span[] {
  return (boxes ?? [])
    .filter((b) => b.time_start != null && b.x == null)
    .sort((a, b) => (a.time_start as number) - (b.time_start as number))
    .map((b) => ({ start: b.time_start as number, end: b.time_end ?? null }));
}

/**
 * SMPTE video timecodes (`HH:MM:SS:FF`, always full and zero-padded, where `FF`
 * is the frame within the second, `0 … fps-1`). Pure + unit-tested
 * (`timecode.test.ts`, run under `node --test`) so keep it free of DOM/React.
 */

function pad(n: number, w = 2): string {
  return String(Math.max(0, Math.floor(n))).padStart(w, "0");
}

/** Seconds → a full SMPTE timecode `HH:MM:SS:FF`, or `MM:SS:FF` when
 *  `trimHours` is set and the position is under an hour.
 *
 *  Trimming is for READING — a sidebar row, where almost every film is under an
 *  hour and a leading `00:` on every line is three characters saying nothing.
 *  Never for a FIELD: `TimecodeField` addresses its four fields by character
 *  offset (`TC_SEGMENTS`), so a width that changed with the value would move
 *  them under the caret. */
export function formatTimecode(
  seconds: number, fps: number, trimHours = false
): string {
  const f = fps > 0 ? fps : 25;
  const s = Math.max(0, seconds);
  const whole = Math.floor(s);
  // Frame within the second, clamped so rounding never shows `:fps`.
  let frame = Math.round((s - whole) * f);
  let carry = 0;
  if (frame >= f) { frame = 0; carry = 1; }
  const total = whole + carry;
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const sec = total % 60;
  const rest = `${pad(m)}:${pad(sec)}:${pad(frame)}`;
  return trimHours && h === 0 ? rest : `${pad(h)}:${rest}`;
}

/** A position in the shortest form that still reads as a clock: `1:23`, and
 *  `1:02:03` once there are hours.
 *
 *  Not a timecode — no frame, and no zero-padded hour. This is for places
 *  where the position is an ASIDE (a tab's title) rather than the thing being
 *  edited, and `00:01:23:00` there is eight characters of leading zeros in a
 *  strip that is already short of room. Seconds are always two digits, so the
 *  text does not change width every second. */
export function shortTime(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}

/** One stretch, as a row's subtitle: `start – end`, or a lone timecode for a
 *  single frame. */
export function formatSpan(
  span: { start: number; end: number | null }, fps: number, trimHours = false
): string {
  const from = formatTimecode(span.start, fps, trimHours);
  return span.end == null ? from
    : `${from} – ${formatTimecode(span.end, fps, trimHours)}`;
}

/** Every stretch a tag covers, ONE PER LINE.
 *
 *  A TAG ROW is one range each, so it never needs this — but a subject, a
 *  place or an event is one row for the whole tag (the row is the person, not
 *  the stretch), so its subtitle has to carry all of them. They used to be
 *  joined with commas onto a single line, which is a line nobody can read
 *  past the second pair: a timecode pair is already most of a sidebar's width,
 *  so two of them side by side are two truncated halves. Past `max` the rest
 *  are counted instead, on a line of their own. */
export function spanLines(
  spans: { start: number; end: number | null }[], fps: number,
  max = 3, more = (n: number) => `+${n} more`
): string[] {
  if (spans.length === 0) return [];
  const shown = spans.slice(0, max).map((s) => formatSpan(s, fps, true));
  const rest = spans.length - shown.length;
  return rest > 0 ? [...shown, more(rest)] : shown;
}

/** The four fields of `HH:MM:SS:FF` as `[start, end)` character offsets. */
export const TC_SEGMENTS: ReadonlyArray<readonly [number, number]> = [
  [0, 2], [3, 5], [6, 8], [9, 11],
];

/** Which field a caret offset sits in (a separator belongs to the field left
 *  of it, so clicking just past ":" doesn't jump a field). */
export function segmentAt(pos: number): number {
  for (let i = 0; i < TC_SEGMENTS.length; i++) {
    if (pos <= TC_SEGMENTS[i][1]) return i;
  }
  return TC_SEGMENTS.length - 1;
}

/** The largest value a field can hold: 99 hours, 59 minutes/seconds, and one
 *  frame less than the frame rate. */
export function segmentMax(seg: number, fps: number): number {
  if (seg === 0) return 99;
  if (seg === 3) return Math.max(1, Math.round(fps > 0 ? fps : 25)) - 1;
  return 59;
}

/** Write one field of a `HH:MM:SS:FF` string, clamped to that field's range. */
export function setSegment(text: string, seg: number, value: number, fps: number): string {
  const v = Math.min(segmentMax(seg, fps), Math.max(0, Math.floor(value)));
  const [a, b] = TC_SEGMENTS[seg];
  return text.slice(0, a) + pad(v) + text.slice(b);
}

/** Read one field of a `HH:MM:SS:FF` string. */
export function getSegment(text: string, seg: number): number {
  const [a, b] = TC_SEGMENTS[seg];
  return Number(text.slice(a, b)) || 0;
}

/**
 * Parse a timecode back to seconds. Accepts full SMPTE `HH:MM:SS:FF` as well as
 * the looser forms `M:SS:FF`, `M:SS`, and a bare `SS(.mmm)`. Returns null for
 * anything it can't read, so callers can ignore bad input.
 */
export function parseTimecode(text: string, fps: number): number | null {
  const f = fps > 0 ? fps : 25;
  const t = text.trim();
  if (t === "") return null;
  if (!t.includes(":")) {
    const n = Number(t);
    return Number.isFinite(n) && n >= 0 ? n : null;
  }
  const parts = t.split(":");
  if (parts.some((p) => p.trim() === "" || !/^\d+(?:\.\d+)?$/.test(p.trim()))) return null;
  const nums = parts.map((p) => Number(p));
  let h = 0, m = 0, s = 0, frame = 0;
  if (nums.length === 2) { [m, s] = nums; }
  else if (nums.length === 3) { [m, s, frame] = nums; }
  else if (nums.length === 4) { [h, m, s, frame] = nums; }
  else return null;
  if (frame >= f) return null;
  return h * 3600 + m * 60 + s + frame / f;
}

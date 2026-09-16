/**
 * THE TIME RULER above the video editor's track: which marks to draw, at a
 * given zoom.
 *
 * Pure, because the answer is a small ladder and the way to get it wrong is
 * not — a step computed as "a round fraction of the visible span" gives 3.7 s
 * between labels at one zoom and 0.83 s at the next, and a ruler nobody can
 * read the numbers off is worse than no ruler. The steps are the ones a person
 * counts in: seconds, then the familiar 15 / 30 / 60, then minutes — and,
 * BELOW a second, frames.
 */
// The `.ts` is what `node --test` resolves this by — a value import from a
// pure module has to carry it, as every other one here does.
import { formatTimecode } from "./timecode.ts";

/** The steps a ruler is allowed to use, in seconds, from one second up. */
const STEPS = [
  1, 2, 5, 10, 15, 30,
  60, 120, 300, 600, 900, 1800, 3600, 7200,
];

/** The sub-second steps: tenths, as they always were. */
const SUB_STEPS = [0.1, 0.2, 0.5];

/** FRAME SCALE. Below a tenth of a second the marks are frames and are
 *  labelled as such; at or above it they are tenths and read as decimals.
 *
 *  The line is where the two notations stop competing. A tenth of a second is
 *  three frames at 30 fps, and nobody zoomed that far out is aiming at one —
 *  while "0.5s" written as the timecode `00:00:15` reads as fifteen SECONDS
 *  to anybody not already thinking in frames. So the decimal keeps the range
 *  it is good at, and the timecode takes over exactly where a frame becomes
 *  the thing you are pointing at. */
const FRAME_SCALE = 0.1;

/** Whole numbers of FRAMES, for the bottom of the ladder. A frame is the
 *  finest thing a video HAS, so it is where the ladder stops. */
const SUB_FRAMES = [1, 2, 5, 10, 15, 30];

/** The whole ladder for a given frame rate (0 = unknown). */
function stepsFor(fps: number): number[] {
  const frames = fps > 0
    ? SUB_FRAMES.map((n) => n / fps).filter((s) => s < FRAME_SCALE)
    : [];
  return [...frames, ...SUB_STEPS, ...STEPS];
}

/**
 * Seconds between LABELLED marks, for a scale in pixels per second.
 *
 * The smallest step whose marks are at least `minLabelPx` apart, so a label
 * always has room for its own text. Past the top of the ladder the largest
 * step is used and the labels simply thin out — an hour between marks is a
 * reasonable ruler for a four-hour film, where a computed step would offer
 * something like "every 4211 seconds".
 */
export function rulerStep(pxPerSecond: number, minLabelPx = 64,
                          fps = 0): number {
  const steps = stepsFor(fps);
  if (!(pxPerSecond > 0)) return steps[steps.length - 1];
  for (const s of steps) if (s * pxPerSecond >= minLabelPx) return s;
  return steps[steps.length - 1];
}

/**
 * The marks between two times, at `step`, as seconds.
 *
 * Aligned to whole multiples of the step rather than to `from`, so scrolling
 * slides the ruler past the marks instead of dragging the marks along with it.
 * The count is capped: a caller that asks for an hour at 0.1 s would otherwise
 * get 36 000 DOM nodes for a strip 900 px wide.
 *
 * **Ask for the VISIBLE stretch, not the whole film.** The cap is a backstop
 * against a runaway, not a way of choosing which marks matter: asked for the
 * whole duration at a fine step it keeps the first 400 and drops the rest, so
 * a film zoomed in far enough had a ruler that simply STOPPED partway along
 * and left everything past it unnumbered. That was "the ruler breaks when you
 * zoom in".
 */
export function rulerTicks(
  from: number, to: number, step: number, cap = 400,
): number[] {
  if (!(step > 0) || !(to > from)) return [];
  const out: number[] = [];
  // Counted in WHOLE STEPS and multiplied out, never accumulated: adding
  // `step` thirty times puts 0.1 × 30 at 3.0000000000000004, which is past a
  // `to` of 3 — so the last mark of a span silently went missing.
  const first = Math.ceil(Math.max(0, from) / step - 1e-9);
  const last = Math.floor(to / step + 1e-9);
  // `+ 0` turns the -0 that `Math.ceil(-1e-9) * step` produces at the origin
  // back into 0 — invisible on screen, and a failing equality in a test.
  for (let n = first; n <= last && out.length < cap; n++) out.push(n * step + 0);
  return out;
}

/**
 * A mark's label. Seconds below a minute, `m:ss` above it, a decimal where the
 * step is finer than a second (`0:03.5`) — and, at FRAME SCALE, the position
 * as a TIMECODE with its frame (`00:12:04`), which is what every other
 * position in these two windows is written as. Without a frame rate there are
 * no frames to count and the decimal is the best that can be said.
 */
export function rulerLabel(at: number, step: number, fps = 0): string {
  const s = Math.max(0, at);
  if (step < FRAME_SCALE && fps > 0) return formatTimecode(s, fps, true);
  const decimals = step < 1 ? 1 : 0;
  if (s < 60) return `${s.toFixed(decimals)}s`;
  const m = Math.floor(s / 60);
  const rest = s - m * 60;
  const h = Math.floor(m / 60);
  const mm = m % 60;
  const secs = decimals > 0
    ? rest.toFixed(decimals).padStart(decimals + 3, "0")
    : String(Math.round(rest)).padStart(2, "0");
  return h > 0 ? `${h}:${String(mm).padStart(2, "0")}:${secs}`
               : `${mm}:${secs}`;
}

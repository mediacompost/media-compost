/**
 * A SLIDER THAT SPENDS ITS LENGTH WHERE THE SMALL NUMBERS ARE.
 *
 * A brush runs from 1 px to 200, and on a linear track the first twenty — the
 * ones used for anything fine — share a tenth of it, about nine pixels of
 * travel for the whole useful low end, while the top half picks between sizes
 * nobody can tell apart. Logarithmic, each DOUBLING gets the same length: 1→2
 * is as far as 100→200, so a 3 px tip is as easy to land on as a 150 px one.
 *
 * The position is the slider's own unit and means nothing outside it; the
 * VALUE is what the tool and the typed field speak. `SliderProp` already
 * separates those (`inputValue`/`onInput`), which is what this plugs into.
 *
 * STEPS IS FINE ENOUGH THAT EVERY VALUE SURVIVES THE ROUND TRIP. The tightest
 * gap in log space is at the top — 199 to 200 is 0.09% of the range — so a
 * coarse track cannot represent both and dragging to 199 would land on 198.
 * At 10,000 steps every whole size from 1 to 200 has a position of its own,
 * which `logSlider.test.ts` checks one by one.
 */
export const LOG_STEPS = 10000;

/** Where `value` sits on the track, 0…LOG_STEPS. */
export function logSliderPos(value: number, min: number, max: number): number {
  const v = Math.max(min, Math.min(max, value));
  return Math.round((LOG_STEPS * Math.log(v / min)) / Math.log(max / min));
}

/** What a position on the track means, as a whole value. */
export function logSliderValue(pos: number, min: number, max: number): number {
  const t = Math.max(0, Math.min(LOG_STEPS, pos)) / LOG_STEPS;
  return Math.max(min, Math.min(max, Math.round(min * Math.pow(max / min, t))));
}

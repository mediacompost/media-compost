// Which stat bars change colour as they fill, and which deliberately do not.
//
// A .ts module rather than logic inside GpuStatsBar.tsx so `node --test` can
// load it — the same reason zoomPivot.ts and treeRows.ts are separate: the
// runner strips types from .ts and cannot transform JSX.

/** How close to the ceiling starts to matter, and where it is alarming. */
export const WARN_AT = 0.8;
export const DANGER_AT = 0.92;

/** Metrics where a high reading is BAD.
 *
 *  GPU utilisation and fan speed are deliberately absent: a card at 100%
 *  utilisation is doing exactly what it was asked to, and a fan at 100% is the
 *  cooling working rather than failing. Colouring those would paint a healthy
 *  training run red and teach people to ignore the colour everywhere it does
 *  mean something. */
export const PRESSURE = new Set(["vram", "mem", "disk", "temp", "power"]);

export function barColor(key: string, pct: number): string {
  if (!PRESSURE.has(key)) return "var(--accent)";
  if (pct >= DANGER_AT * 100) return "var(--red)";
  if (pct >= WARN_AT * 100) return "var(--yellow)";
  return "var(--accent)";
}

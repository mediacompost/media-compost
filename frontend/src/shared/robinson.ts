/**
 * WHERE A COORDINATE LANDS ON THE MAP — the Robinson projection, and the fit
 * that ties it to the one outline this app ships.
 *
 * Pure, so `node --test` covers the whole of it: the projection is a table
 * lookup with linear interpolation between 5° rows, exactly as Robinson
 * defined it (there is no closed form — the table IS the projection).
 *
 * THE FIT IS MEASURED, NOT ASSUMED. A world SVG is not obliged to span
 * −180…180 across its viewBox, and this one does not: it is cropped a little
 * on the left and well below the Antarctic circle. So `X0`/`Y0`/`K` come from
 * a least-squares fit of the projection against the bounding boxes of eight
 * small, well-known countries in the file itself (`scripts/build_worldmap.py`
 * ships the outline; the fit was done once, against it, to a mean residual of
 * ~3 units in a 2000-unit space — about a pixel at any size this map is
 * drawn). Replace the outline and these three numbers must be re-fitted.
 */

/** Robinson's table, 0°…90° in 5° steps. X scales longitude, Y is latitude. */
const X = [1.0000, 0.9986, 0.9954, 0.9900, 0.9822, 0.9730, 0.9600, 0.9427,
           0.9216, 0.8962, 0.8679, 0.8350, 0.7986, 0.7597, 0.7186, 0.6732,
           0.6213, 0.5722, 0.5322];
const Y = [0.0000, 0.0620, 0.1240, 0.1860, 0.2480, 0.3100, 0.3720, 0.4340,
           0.4958, 0.5571, 0.6176, 0.6769, 0.7346, 0.7903, 0.8435, 0.8936,
           0.9394, 0.9761, 1.0000];

function interp(table: readonly number[], lat: number): number {
  const a = Math.min(Math.abs(lat), 90) / 5;
  const i = Math.min(Math.floor(a), 17);
  return table[i] + (table[i + 1] - table[i]) * (a - i);
}

/** The fit against the shipped outline (viewBox 2000 × 857). */
const K = 381.7563;
const X0 = 986.138;
const Y0 = 501.189;

/** A point in the map's own coordinate space. Off-map values are possible and
 *  are NOT clamped: Antarctica is below this outline's bottom edge, and a
 *  caller that wants to say so needs to see that it is. */
export function project(lon: number, lat: number): { x: number; y: number } {
  const px = 0.8487 * interp(X, lat) * (lon * Math.PI / 180);
  const py = 1.3523 * interp(Y, lat) * (lat >= 0 ? 1 : -1);
  return { x: X0 + K * px, y: Y0 - K * py };
}

/** Whether a pair of numbers is a coordinate at all. The API hands back
 *  `null` for "none" and a stored pair is always both or neither, but a text
 *  field on the way in can be anything. */
export function isCoord(lat: unknown, lon: unknown): boolean {
  return typeof lat === "number" && typeof lon === "number"
    && Number.isFinite(lat) && Number.isFinite(lon)
    && Math.abs(lat) <= 90 && Math.abs(lon) <= 180;
}

/** `35.6812, 139.7671` — the form the app writes and reads back. Four
 *  decimals is about 11 m, which is finer than anything a picture's own
 *  metadata is worth. */
export function formatCoord(lat: number, lon: number): string {
  return `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
}

/** The pair a person typed, or null. Accepts a comma, a semicolon or plain
 *  space between the two, and a trailing N/S/E/W. */
export function parseCoord(s: string): { lat: number; lon: number } | null {
  const m = s.trim().match(
    /^(-?\d+(?:\.\d+)?)\s*([NnSs])?\s*[,;]?\s+?(-?\d+(?:\.\d+)?)\s*([EeWw])?$/)
    ?? s.trim().match(
      /^(-?\d+(?:\.\d+)?)\s*([NnSs])?\s*[,;]\s*(-?\d+(?:\.\d+)?)\s*([EeWw])?$/);
  if (!m) return null;
  let lat = Number(m[1]);
  let lon = Number(m[3]);
  if (m[2] && m[2].toLowerCase() === "s") lat = -lat;
  if (m[4] && m[4].toLowerCase() === "w") lon = -lon;
  if (!isCoord(lat, lon)) return null;
  return { lat, lon };
}

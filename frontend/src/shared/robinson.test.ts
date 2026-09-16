/**
 * The map projection, and the fit that ties it to the one outline we ship.
 *
 * `robinson.ts` says of itself "Pure, so `node --test` covers the whole of
 * it" — and there was no test. What the module's own comment records instead
 * is a MANUAL check: the fit was verified once "by plotting a dozen cities".
 * That is exactly the thing to freeze, because the failure it guards is
 * silent. `X0`/`Y0`/`K` are three magic numbers fitted against a specific SVG;
 * replace the outline, or edit one digit, and every pin lands somewhere
 * plausible and wrong — a map with no error message anywhere.
 *
 * The expected pixel positions below were produced by the module as it stands
 * and cross-checked against the shipped outline's viewBox (2000 x 857): each
 * city lands where the coastline under it is. They are a REGRESSION anchor,
 * not an independent derivation of Robinson's table.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import {
  formatCoord, isCoord, parseCoord, project,
} from "./robinson.ts";

/** The outline's own viewBox, from `scripts/build_worldmap.py`. */
const VIEW = { w: 2000, h: 857 };

const CITIES: [string, number, number][] = [
  // name, lat, lon
  ["London", 51.5074, -0.1278],
  ["Tokyo", 35.6762, 139.6503],
  ["New York", 40.7128, -74.0060],
  ["Sydney", -33.8688, 151.2093],
  ["Cape Town", -33.9249, 18.4241],
  ["Rio de Janeiro", -22.9068, -43.1729],
  ["Reykjavik", 64.1466, -21.9426],
  ["Singapore", 1.3521, 103.8198],
];

test("the equator and the prime meridian are where the fit put them", () => {
  const o = project(0, 0);
  // Y0 is the equator's row; X0 the meridian's column. Neither is the middle
  // of the viewBox, and that asymmetry IS the fit: the outline is cropped a
  // little on the left and well above the Antarctic circle.
  assert.ok(Math.abs(o.x - 986.138) < 1e-6, `x=${o.x}`);
  assert.ok(Math.abs(o.y - 501.189) < 1e-6, `y=${o.y}`);
  // West of the meridian gets less room than east: the map is cut short on
  // the left, so −180 falls just off the canvas while +180 barely clears it.
  assert.ok(o.x < VIEW.w / 2, "the meridian should sit left of centre");
  assert.ok(project(-180, 0).x < 0, "−180 should fall off the left edge");
  assert.ok(project(180, 0).x > VIEW.w, "…and +180 just off the right");
  // North of the equator gets more room than south, because the south is
  // where the crop is.
  assert.ok(o.y > VIEW.h / 2, "the equator should sit below centre");
});

test("every city lands inside the map, on the right side of both axes", () => {
  for (const [name, lat, lon] of CITIES) {
    const { x, y } = project(lon, lat);
    assert.ok(x > 0 && x < VIEW.w, `${name}: x=${x} off the viewBox`);
    assert.ok(y > 0 && y < VIEW.h, `${name}: y=${y} off the viewBox`);
    const o = project(0, 0);
    assert.equal(x > o.x, lon > 0, `${name}: wrong side of the meridian`);
    assert.equal(y < o.y, lat > 0, `${name}: wrong side of the equator`);
  }
});

test("the fitted constants have not moved", () => {
  // The regression anchor. Rounded to whole units — the fit's own residual is
  // ~3 units in 2000, so a tighter assertion would be pinning noise, and a
  // looser one would not notice a digit changing in K.
  const at = (lat: number, lon: number) => {
    const p = project(lon, lat);
    return [Math.round(p.x), Math.round(p.y)];
  };
  assert.deepEqual(at(51.5074, -0.1278), [986, 173]);    // London
  assert.deepEqual(at(35.6762, 139.6503), [1728, 273]);  // Tokyo
  assert.deepEqual(at(40.7128, -74.0060), [602, 241]);   // New York
  assert.deepEqual(at(-33.8688, 151.2093), [1796, 718]); // Sydney
  assert.deepEqual(at(-33.9249, 18.4241), [1085, 718]);  // Cape Town
  assert.deepEqual(at(-22.9068, -43.1729), [748, 648]);  // Rio de Janeiro
  assert.deepEqual(at(1.3521, 103.8198), [1573, 493]);   // Singapore
});

test("longitude is linear at a fixed latitude, and latitude is monotone", () => {
  // Robinson scales longitude by a per-latitude factor, so along one parallel
  // the spacing must be even — that is what makes it a table lookup rather
  // than a projection with a closed form.
  const y0 = project(0, 40).x;
  const step = project(10, 40).x - y0;
  for (let lon = 20; lon <= 170; lon += 10) {
    const got = project(lon, 40).x - project(lon - 10, 40).x;
    assert.ok(Math.abs(got - step) < 1e-9, `spacing changed at ${lon}`);
  }
  // Going north always goes up the image, never back down.
  let prev = Infinity;
  for (let lat = -90; lat <= 90; lat += 1) {
    const { y } = project(0, lat);
    assert.ok(y < prev, `y stopped decreasing at lat ${lat}`);
    prev = y;
  }
});

test("the table's own rows are hit exactly, and between them it interpolates", () => {
  // The table is defined at 5° steps; 45° is a row and 42.5° is the midpoint
  // between two, so the interpolation has to land halfway.
  const a = project(0, 40).y, b = project(0, 45).y;
  const mid = project(0, 42.5).y;
  assert.ok(Math.abs(mid - (a + b) / 2) < 1e-9, `${mid} is not the midpoint`);
});

test("the poles are symmetric and the projection does not clamp off-map", () => {
  const n = project(0, 90), s = project(0, -90);
  const eq = project(0, 0).y;
  assert.ok(Math.abs((eq - n.y) - (s.y - eq)) < 1e-9, "poles are asymmetric");
  // Antarctica really is below this outline's bottom edge, and the module
  // says so on purpose: a caller that wants to report it needs to see it.
  assert.ok(s.y > VIEW.h, "the south pole should fall off the shipped map");
});

test("beyond the poles the table stops rather than running off its end", () => {
  // `interp` clamps the INDEX, so a latitude a text field could produce does
  // not read past the array and return NaN.
  for (const lat of [90, 95, 180, -95]) {
    const { x, y } = project(10, lat);
    assert.ok(Number.isFinite(x) && Number.isFinite(y), `NaN at lat ${lat}`);
  }
});

test("isCoord takes a real pair and nothing else", () => {
  assert.equal(isCoord(51.5, -0.12), true);
  assert.equal(isCoord(0, 0), true);
  assert.equal(isCoord(90, 180), true);
  assert.equal(isCoord(-90, -180), true);
  // Out of range, out of type, out of the number line.
  assert.equal(isCoord(91, 0), false);
  assert.equal(isCoord(0, 181), false);
  assert.equal(isCoord(NaN, 0), false);
  assert.equal(isCoord(Infinity, 0), false);
  assert.equal(isCoord(null, null), false);
  assert.equal(isCoord("51.5", "-0.12"), false);
  assert.equal(isCoord(51.5, undefined), false);
});

test("a coordinate round-trips through format and parse", () => {
  // The pair the app writes into the field and reads back out of it. Four
  // decimals is the stated precision, so the round trip is exact at that.
  for (const [name, lat, lon] of CITIES) {
    const round = (v: number) => Number(v.toFixed(4));
    const back = parseCoord(formatCoord(lat, lon));
    assert.deepEqual(back, { lat: round(lat), lon: round(lon) }, name);
  }
});

test("parseCoord takes the separators a person actually types", () => {
  const want = { lat: 35.6812, lon: 139.7671 };
  assert.deepEqual(parseCoord("35.6812, 139.7671"), want);
  assert.deepEqual(parseCoord("35.6812,139.7671"), want);
  assert.deepEqual(parseCoord("35.6812 139.7671"), want);
  assert.deepEqual(parseCoord("35.6812; 139.7671"), want);
  assert.deepEqual(parseCoord("  35.6812 , 139.7671  "), want);
});

test("parseCoord reads a hemisphere suffix and signs the number", () => {
  assert.deepEqual(parseCoord("33.8688S, 151.2093E"),
                   { lat: -33.8688, lon: 151.2093 });
  assert.deepEqual(parseCoord("40.7128 N, 74.0060 W"),
                   { lat: 40.7128, lon: -74.0060 });
  // A suffix agreeing with the sign it already has leaves it alone.
  assert.deepEqual(parseCoord("40.7128N, 0E"), { lat: 40.7128, lon: 0 });
});

test("parseCoord answers null rather than a wrong pair", () => {
  // It is fed a text field, so everything below is something somebody can
  // type — and a silently-wrong coordinate is a pin in the sea.
  for (const bad of ["", "   ", "51.5", "abc", "51.5, abc", "91, 0", "0, 181",
                     "51.5,,0.12", "51.5 0.12 3", "N51.5, E0.12"]) {
    assert.equal(parseCoord(bad), null, `accepted ${JSON.stringify(bad)}`);
  }
});

test("formatCoord always writes four decimals, zeros included", () => {
  // A fixed width is what makes the round trip above exact, and what keeps a
  // column of coordinates aligned.
  assert.equal(formatCoord(0, 0), "0.0000, 0.0000");
  assert.equal(formatCoord(51.5, -0.1), "51.5000, -0.1000");
  assert.equal(formatCoord(35.68123456, 139.76712345), "35.6812, 139.7671");
});

test("the hand-kept viewBox agrees with the generated one", async () => {
  // `WorldMap.tsx` carries its own copy of the outline's coordinate space, so
  // the first paint — before the 100 KB chunk lands — is the same size as the
  // one after it. That is a deliberate duplicate of a GENERATED value:
  // `scripts/build_worldmap.py` writes `WORLD_VIEWBOX` from whatever SVG it
  // was given, and regenerating the map from a differently-cropped source
  // would move it while the hand-kept copy sat still — a map drawn at the
  // wrong scale, with the projection constants below still fitted to the old
  // one. Nothing else compares the two, so this does.
  const { WORLD_VIEWBOX } = await import("./worldLand.ts");
  const src = await readFile(
    new URL("./WorldMap.tsx", import.meta.url), "utf8");
  const m = src.match(/const VB = \{ w: (\d+(?:\.\d+)?), h: (\d+(?:\.\d+)?) \}/);
  assert.ok(m, "WorldMap.tsx no longer declares `const VB = { w, h }`");
  assert.deepEqual({ w: Number(m![1]), h: Number(m![2]) }, WORLD_VIEWBOX);
});

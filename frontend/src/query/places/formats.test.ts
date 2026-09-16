import test from "node:test";
import assert from "node:assert/strict";

import {
  formatLatLon, parseLatLon, placeLabel, placeValues, shortPlace,
} from "./formats.ts";

// The per-country address table this file used to be is gone with the eight
// typed components — a place is one line now, so the only rules left are
// which of its own fields to show and how a coordinate pair reads.

test("a place reads as its name, then its tag", () => {
  assert.equal(placeLabel({ name: "12 Mill Lane", tag: "studio" }),
               "12 Mill Lane");
  assert.equal(placeLabel({ tag: "studio" }), "studio");
  assert.equal(placeLabel({}), "");
});

test("the short form keeps the specific end of the name", () => {
  // A place's line reads finest-first in most of the world.
  assert.equal(shortPlace({ name: "Center Gai, Shibuya, Tokyo" }),
               "Center Gai");
  assert.equal(shortPlace({ tag: "somewhere" }), "somewhere");
});

test("the suggestions are the names the library holds, commonest first", () => {
  const places = [
    { tag: "tokyo", name: "Tokyo" },
    { tag: "kyoto", name: "Kyoto" },
    { tag: "berlin", name: "Berlin" },
    { tag: "shibuya", name: "Tokyo" },
  ];
  assert.deepEqual(placeValues(places), ["Tokyo", "Berlin", "Kyoto"]);
  // The identity TAG is not offered: a place condition matches the name,
  // and who the place IS is the tag field's own question.
  assert.ok(!placeValues(places).includes("shibuya"));
  assert.deepEqual(placeValues([{ tag: "nameless" }]), []);
});

test("coordinates read back the way they were written", () => {
  assert.deepEqual(parseLatLon("35.6812, 139.7671"),
                   { lat: 35.6812, lon: 139.7671 });
  assert.deepEqual(parseLatLon("35.6812 139.7671"),
                   { lat: 35.6812, lon: 139.7671 });
  assert.deepEqual(parseLatLon("33.9S 18.4E"), { lat: -33.9, lon: 18.4 });
  assert.equal(parseLatLon("somewhere"), null);
  assert.equal(parseLatLon("91, 0"), null, "off the globe");
  assert.equal(formatLatLon(35.6812, 139.7671), "35.68120, 139.76710");
  assert.equal(formatLatLon(null, 1), "");
});

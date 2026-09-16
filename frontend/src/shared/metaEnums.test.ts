import test from "node:test";
import assert from "node:assert/strict";

import { decodeMeta, hasMetaEnum, metaEnumOptions } from "./metaEnums.ts";

test("a known code becomes words", () => {
  assert.equal(decodeMeta("orientation", "6"), "Rotated 90° CW");
  assert.equal(decodeMeta("metering_mode", "2"), "Centre-weighted");
  assert.equal(decodeMeta("white_balance", "0"), "Auto");
  assert.equal(decodeMeta("flash", "16"), "Off, did not fire");
});

test("an UNKNOWN code stays the number rather than claiming something", () => {
  // "Unknown" here would be the app putting a word in the file's mouth.
  assert.equal(decodeMeta("orientation", "99"), "99");
  assert.equal(decodeMeta("metering_mode", "42"), "42");
});

test("an unnamed flash code still answers the question it is asked", () => {
  // Flash is a bitfield; bit 0 is "it fired", and that is what anybody wants
  // to know of a combination the EXIF table does not define.
  assert.equal(decodeMeta("flash", "3"), "Fired");
  assert.equal(decodeMeta("flash", "34"), "Did not fire");
});

test("a name with no table is left completely alone", () => {
  assert.equal(decodeMeta("camera_make", "Canon"), "Canon");
  assert.equal(decodeMeta("iso", "400"), "400");
  assert.equal(decodeMeta(null, "400"), "400");
  assert.equal(decodeMeta(undefined, "x"), "x");
});

test("a non-numeric value under an enum name is left alone", () => {
  assert.equal(decodeMeta("flash", ""), "");
  assert.equal(decodeMeta("orientation", "n/a"), "n/a");
});

test("the builder's options carry the NUMBER as the value, words as the label", () => {
  // The whole split: the query string keeps numbers, only the choosing is in
  // words. An option whose `value` were the label would serialize the label.
  const opts = metaEnumOptions("orientation");
  assert.deepEqual(opts[0], { value: "1", label: "Normal" });
  assert.ok(opts.every((o) => String(Number(o.value)) === o.value),
            "every option value must be a bare number");
  // Lowest code first, so the list reads in the order the spec defines.
  const codes = opts.map((o) => Number(o.value));
  assert.deepEqual(codes, [...codes].sort((a, b) => a - b));
});

test("a name with no table offers nothing, so the field stays a number", () => {
  assert.deepEqual(metaEnumOptions("iso"), []);
  assert.deepEqual(metaEnumOptions(null), []);
  assert.equal(hasMetaEnum("iso"), false);
  assert.equal(hasMetaEnum("flash"), true);
  assert.equal(hasMetaEnum(undefined), false);
});

test("every option's label round-trips through decodeMeta", () => {
  // The dropdown and the Info tab read the same table, so a value picked in
  // one must show as the same words in the other.
  for (const name of ["orientation", "flash", "metering_mode", "white_balance"]) {
    for (const o of metaEnumOptions(name)) {
      assert.equal(decodeMeta(name, o.value), o.label, `${name}=${o.value}`);
    }
  }
});

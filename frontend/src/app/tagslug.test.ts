import { strict as assert } from "node:assert";
import { test } from "node:test";
import { bracketSlug, freeSlug, slugTaken, splitBracketed } from "./tagslug.ts";

test("a free base is left exactly as it is", () => {
  assert.equal(freeSlug("maria", ["carlos"]), "maria");
});

test("a taken base counts up, starting at two", () => {
  assert.equal(freeSlug("maria", ["maria"]), "maria_2");
  assert.equal(freeSlug("maria", ["maria", "maria_2"]), "maria_3");
});

test("taken is case-insensitive, like the server's own lookup", () => {
  assert.equal(freeSlug("Maria", ["MARIA"]), "Maria_2");
  assert.equal(slugTaken("MARIA", ["maria"]), true);
});

test("an empty base stays empty rather than becoming _2", () => {
  assert.equal(freeSlug("", ["", "x"]), "");
});

test("a gap is filled rather than skipped past", () => {
  assert.equal(freeSlug("m", ["m", "m_3"]), "m_2");
});

test("the name it already has is not a clash with itself", () => {
  assert.equal(slugTaken("maria", ["maria"], "maria"), false);
  assert.equal(slugTaken("maria", ["maria"], "carlos"), true);
});

test("whitespace and an empty slug never read as taken", () => {
  assert.equal(slugTaken("  ", ["", "x"]), false);
});

test("a trailing bracket splits into name and comment", () => {
  assert.deepEqual(splitBracketed("Traveler (Genshin Impact)"),
                   { name: "Traveler", comment: "Genshin Impact" });
  assert.deepEqual(splitBracketed("  Alice  "),
                   { name: "Alice", comment: "" });
  // Only TRAILING brackets split — one in the middle is part of the name.
  assert.deepEqual(splitBracketed("A (b) c"),
                   { name: "A (b) c", comment: "" });
  // Empty halves don't split.
  assert.deepEqual(splitBracketed("(solo)"),
                   { name: "(solo)", comment: "" });
  assert.deepEqual(splitBracketed("name ()"),
                   { name: "name ()", comment: "" });
});

test("the bracket slug keeps the comment in brackets", () => {
  assert.equal(bracketSlug("Traveler", "Genshin Impact"),
               "traveler_(genshin_impact)");
  assert.equal(bracketSlug("Alice", ""), "alice");
  assert.equal(bracketSlug("", "x"), "");
});

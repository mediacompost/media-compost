import assert from "node:assert/strict";
import { test } from "node:test";

import { chosen } from "./engineChoice.ts";

test("chosen: the remembered engine wins while it still has a reading", () => {
  const choices = { "7": "magiv3_ocr" };
  assert.equal(chosen(choices, 7, ["rapidocr_multi", "magiv3_ocr"]),
               "magiv3_ocr");
});

test("chosen: an engine with no reading here falls back to the first", () => {
  // The memory outlives a reading — an engine's regions can be dismissed, or
  // the file replaced (a reading belongs to a file). Falling back rather
  // than answering with an engine that has nothing is what keeps the list
  // and the boxes beside it from showing an empty page.
  const choices = { "7": "magiv3_ocr" };
  assert.equal(chosen(choices, 7, ["rapidocr_multi"]), "rapidocr_multi");
});

test("chosen: nothing remembered, nothing read", () => {
  assert.equal(chosen({}, 7, ["rapidocr_multi"]), "rapidocr_multi");
  assert.equal(chosen({}, 7, []), "");
});

test("chosen: an item with no id of its own takes the first reading", () => {
  assert.equal(chosen({ "7": "magiv3_ocr" }, null,
                      ["rapidocr_multi", "magiv3_ocr"]), "rapidocr_multi");
});

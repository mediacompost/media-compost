// The find/replace arithmetic behind the caption editor's ⌘F bar. Every case
// here is something a person does within a minute of opening it.
import test from "node:test";
import assert from "node:assert/strict";

import {
  findMatches, highlightRuns, matchAt, replaceAll, replaceOne, stepMatch,
} from "./findReplace.ts";

test("finds every occurrence, left to right", () => {
  //                0123456789…  — "cat" holds one at 3, "mat" one at 12.
  assert.deepEqual(findMatches("a cat on a mat", "at"),
                   [{ start: 3, end: 5 }, { start: 12, end: 14 }]);
});

test("is case-insensitive unless asked", () => {
  assert.equal(findMatches("Cat cat CAT", "cat").length, 3);
  assert.equal(findMatches("Cat cat CAT", "cat", true).length, 1);
});

test("matches never overlap", () => {
  // With overlaps this finds two, and replacing both would write over the
  // same characters twice — which is what makes replace-all disagree with
  // what the highlight showed.
  assert.deepEqual(findMatches("aaa", "aa"), [{ start: 0, end: 2 }]);
});

test("an empty needle finds nothing", () => {
  // "a match at every position" would make every function below nonsense,
  // and the bar has nothing to search for yet anyway.
  assert.deepEqual(findMatches("anything", ""), []);
});

test("punctuation is text, not syntax", () => {
  // A caption is prose: `.` and `(` are ordinary characters in it, and the
  // one thing this must not do is read them as a pattern.
  assert.deepEqual(findMatches("a (b) c.", "(b)"), [{ start: 2, end: 5 }]);
  assert.deepEqual(findMatches("a.b axb", "a.b"), [{ start: 0, end: 3 }]);
});

test("the caret picks the match to start from, and wraps past the last", () => {
  const m = findMatches("at at at", "at");
  assert.equal(matchAt(m, 0), 0);
  assert.equal(matchAt(m, 2), 1);      // past the first
  assert.equal(matchAt(m, 8), 0);      // past them all — back to the top
  assert.equal(matchAt([], 0), -1);
});

test("stepping wraps at both ends", () => {
  assert.equal(stepMatch(3, 2, 1), 0);
  assert.equal(stepMatch(3, 0, -1), 2);
  assert.equal(stepMatch(0, -1, 1), -1);
});

test("replacing one leaves the caret after what was written", () => {
  const m = findMatches("a cat", "cat");
  assert.deepEqual(replaceOne("a cat", m, 0, "dog"),
                   { text: "a dog", caret: 5 });
});

test("replacing an index that is no longer there changes nothing", () => {
  assert.deepEqual(replaceOne("a cat", [], 0, "dog"),
                   { text: "a cat", caret: 0 });
});

test("replace-all replaces what was highlighted and nothing more", () => {
  assert.equal(replaceAll("a cat on a mat", "at", "og"), "a cog on a mog");
});

test("replace-all terminates when the replacement contains the needle", () => {
  // The loop-and-research spelling never finishes this one: each `aa` it
  // writes is two more matches.
  assert.equal(replaceAll("a a", "a", "aa"), "aa aa");
});

test("replace-all over no match is the same string", () => {
  assert.equal(replaceAll("nothing here", "zzz", "x"), "nothing here");
});

test("the highlight runs rebuild the text exactly", () => {
  // The layer is drawn BEHIND the textarea and has to line up with it to the
  // character, so what it holds must be the whole string.
  for (const [text, needle] of [["a cat on a mat", "at"], ["at", "at"],
                                ["catcat", "cat"], ["no match", "zz"]]) {
    const runs = highlightRuns(text, findMatches(text, needle));
    assert.equal(runs.map((r) => r.text).join(""), text, `${text} / ${needle}`);
  }
});

test("the runs number the matches so the current one can differ", () => {
  const runs = highlightRuns("a cat", findMatches("a cat", "cat"));
  assert.deepEqual(runs, [{ text: "a ", match: -1 }, { text: "cat", match: 0 }]);
});

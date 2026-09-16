import { test } from "node:test";
import assert from "node:assert/strict";
import {
  parseQuickTags, quickTagPlan, quickTagTokens, splitPrefix, tokenAt,
 parseQuickWord, toneOfPrefix } from "./quickTags.ts";

test("one word reads the same as the line does, and a prefix has a tone", () => {
  assert.deepEqual(parseQuickWord("-Blue_Hair"), { name: "blue_hair", remove: true, negative: false });
  assert.deepEqual(parseQuickWord("!x"), { name: "x", remove: false, negative: true });
  assert.deepEqual(parseQuickWord("-!x"), { name: "x", remove: true, negative: false });
  assert.equal(parseQuickWord("-"), null);
  assert.deepEqual(["", "+", "!", "+!", "-", "-!"].map(toneOfPrefix),
                   ["positive", "positive", "negative", "negative", "remove", "remove"]);
});

test("a bare name adds it; + says the same thing out loud", () => {
  assert.deepEqual(parseQuickTags("cat +dog"), [
    { name: "cat", remove: false, negative: false },
    { name: "dog", remove: false, negative: false },
  ]);
});

test("- removes, ! adds a negative, +! is the same as !", () => {
  assert.deepEqual(parseQuickTags("-cat !dog +!bird"), [
    { name: "cat", remove: true, negative: false },
    { name: "dog", remove: false, negative: true },
    { name: "bird", remove: false, negative: true },
  ]);
});

test("- wins over !: a removal takes the tag off whatever sign it had", () => {
  assert.deepEqual(parseQuickTags("-!cat"),
    [{ name: "cat", remove: true, negative: false }]);
});

test("names are committed the way every tag field commits them", () => {
  // Including the trailing colon: `d:` is a tag, so the line applies exactly
  // the name it holds rather than a shorter one the app guessed at.
  assert.deepEqual(parseQuickTags("Blue Sky costume: d:"),
    [{ name: "blue", remove: false, negative: false },
     { name: "sky", remove: false, negative: false },
     { name: "costume:", remove: false, negative: false },
     { name: "d:", remove: false, negative: false }]);
});

test("a half-typed word is dropped rather than refused", () => {
  assert.deepEqual(parseQuickTags("cat + - !"),
    [{ name: "cat", remove: false, negative: false }]);
  assert.deepEqual(parseQuickTags(""), []);
});

test("the last mention of a name wins", () => {
  // Somebody changing their mind mid-line — applying both would be one of
  // them silently losing.
  assert.deepEqual(parseQuickTags("cat -cat"),
    [{ name: "cat", remove: true, negative: false }]);
  assert.deepEqual(parseQuickTags("-cat !cat"),
    [{ name: "cat", remove: false, negative: true }]);
});

test("commas separate as whitespace does", () => {
  assert.deepEqual(quickTagTokens("a, b,c  d"), ["a", "b", "c", "d"]);
});

test("the plan is the two calls that carry the ops out", () => {
  assert.deepEqual(quickTagPlan(parseQuickTags("cat !dog -bird +fish")), {
    positive: ["cat", "fish"], negative: ["dog"], remove: ["bird"],
  });
});

test("splitPrefix keeps the name and hands back what led it", () => {
  assert.deepEqual(splitPrefix("+!cat"), { prefix: "+!", rest: "cat" });
  assert.deepEqual(splitPrefix("!cat"), { prefix: "!", rest: "cat" });
  assert.deepEqual(splitPrefix("cat"), { prefix: "", rest: "cat" });
  assert.deepEqual(splitPrefix("-cat"), { prefix: "-", rest: "cat" });
});

test("tokenAt names the word the caret is in, with its bounds", () => {
  const text = "cat dog bird";
  assert.deepEqual(tokenAt(text, 0), { start: 0, end: 3, word: "cat" });
  assert.deepEqual(tokenAt(text, 3), { start: 0, end: 3, word: "cat" });
  assert.deepEqual(tokenAt(text, 5), { start: 4, end: 7, word: "dog" });
  assert.deepEqual(tokenAt(text, text.length),
    { start: 8, end: 12, word: "bird" });
});

test("a caret on a separator is at the start of the next word", () => {
  // Which is where typing would put text — so the list is about what you are
  // ABOUT to write, not about the word you just finished.
  assert.deepEqual(tokenAt("cat  dog", 4), { start: 4, end: 4, word: "" });
  assert.deepEqual(tokenAt("cat ", 4), { start: 4, end: 4, word: "" });
});

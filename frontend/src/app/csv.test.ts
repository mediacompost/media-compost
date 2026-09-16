// Run with: npm test  (Node's built-in test runner + type stripping).
import { test } from "node:test";
import assert from "node:assert/strict";
import { detectDelimiter, parseCsv, toCsv } from "./csv.ts";

test("parseCsv: plain rows", () => {
  assert.deepEqual(parseCsv("a,b\n1,2"), [["a", "b"], ["1", "2"]]);
});

test("parseCsv: quoted fields keep separators, newlines and doubled quotes", () => {
  const rows = parseCsv('name,comment\nred_fox,"a, b"\nx,"line1\nline2"\ny,"say ""hi"""');
  assert.deepEqual(rows, [
    ["name", "comment"],
    ["red_fox", "a, b"],
    ["x", "line1\nline2"],
    ["y", 'say "hi"'],
  ]);
});

test("parseCsv: CRLF, BOM and blank lines", () => {
  assert.deepEqual(parseCsv("﻿a,b\r\n1,2\r\n\r\n"), [["a", "b"], ["1", "2"]]);
});

test("detectDelimiter: semicolon and tab exports", () => {
  assert.equal(detectDelimiter("a;b;c\n1;2;3"), ";");
  assert.equal(detectDelimiter("a\tb\tc\n1\t2\t3"), "\t");
  assert.equal(detectDelimiter("a,b,c\n1,2,3"), ",");
  // Separators INSIDE quotes must not win the vote.
  assert.equal(detectDelimiter('name,comment\nfox,"a;b;c;d"'), ",");
});

test("parseCsv: semicolon files parse without an explicit delimiter", () => {
  assert.deepEqual(parseCsv("tag;parent\nposhpudel;dog"), [["tag", "parent"], ["poshpudel", "dog"]]);
});

test("toCsv: quotes only what needs it, round-trips through parseCsv", () => {
  const rows = [["tag", "comment"], ["red_fox", 'a, b "quoted"'], ["plain", "ok"]];
  const text = toCsv(rows);
  assert.equal(text.split("\r\n")[1], 'red_fox,"a, b ""quoted"""');
  assert.deepEqual(parseCsv(text), rows);
});

test("toCsv: numbers and empty cells survive the round trip", () => {
  const rows = [["tag", "positive"], ["fox", 12], ["", 0]];
  assert.deepEqual(parseCsv(toCsv(rows)), [["tag", "positive"], ["fox", "12"], ["", "0"]]);
});

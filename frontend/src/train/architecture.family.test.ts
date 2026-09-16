/**
 * How the Models page names and orders a family of checkpoints.
 *
 * `util.test.ts` covers the VRAM estimate — the arithmetic everybody thinks
 * of as util.ts — and left this half untouched: `commonPrefix`, `wholeWords`,
 * `architectureLabel`, `groupByArchitecture` and `byArchitectureLabel` had no
 * test of any kind. The Python suite's
 * `test_models_sharing_an_architecture_are_listed_together` asserts a
 * different property (the registry's ORDER) on a different implementation, so
 * nothing was watching these.
 *
 * `wholeWords` is the one that has already gone wrong — the removal of
 * FLUX.2 dev exposed it: two labels sharing "FLUX.2 Klein (base,
 * " leave a heading ending in the comma and open bracket they also share, so
 * the cut has to be at a whole WORD and then has to clean up after itself.
 */

import test from "node:test";
import assert from "node:assert/strict";

import {
  architectureLabel, byArchitectureLabel, commonPrefix, groupByArchitecture,
  wholeWords,
} from "./util.ts";
import type { TrainModelSpec } from "./api.ts";

const spec = (key: string, label: string, engine: string,
              extra: Partial<TrainModelSpec> = {}): TrainModelSpec =>
  ({ key, label, engine, ...extra }) as unknown as TrainModelSpec;

// ---- commonPrefix ----------------------------------------------------------

test("commonPrefix is the longest shared start, character by character", () => {
  assert.equal(commonPrefix(["FLUX.2 Klein (base, 4B)",
                             "FLUX.2 Klein (base, 9B)"]),
               "FLUX.2 Klein (base, ");
  assert.equal(commonPrefix(["Chroma1 HD", "Chroma1 Base"]), "Chroma1 ");
  assert.equal(commonPrefix(["SDXL 1.0"]), "SDXL 1.0");
});

test("commonPrefix answers empty where there is nothing shared", () => {
  assert.equal(commonPrefix([]), "");
  assert.equal(commonPrefix(["SDXL", "Chroma"]), "");
  // A member shorter than the prefix truncates it rather than reading past
  // the end of the string.
  assert.equal(commonPrefix(["Qwen-Image", "Qwen"]), "Qwen");
});

// ---- wholeWords ------------------------------------------------------------

test("wholeWords cuts a prefix back to a whole word", () => {
  // The failure it exists for: a prefix stopping mid-word says nothing the
  // shorter one does not.
  assert.equal(wholeWords("FLUX.2 Kle"), "FLUX.2");
  assert.equal(wholeWords("Qwen-Image Edi"), "Qwen-Image");
});

test("wholeWords drops the punctuation a shared prefix leaves hanging", () => {
  // THE case from the FLUX.2 removal: the two labels share the comma and the
  // open bracket as well as the name, and a heading ending in "(base," is
  // worse than no heading.
  assert.equal(wholeWords("FLUX.2 Klein (base, "), "FLUX.2 Klein");
  assert.equal(wholeWords("Chroma1 "), "Chroma1");
  assert.equal(wholeWords("Qwen-Image Edit — "), "Qwen-Image Edit");
  assert.equal(wholeWords("Z-Image; "), "Z-Image");
});

test("wholeWords keeps a bracket it closes", () => {
  // Only an UNCLOSED bracket is a fragment. "(9B)" is a whole thing and stays.
  assert.equal(wholeWords("FLUX.2 Klein (9B) "), "FLUX.2 Klein (9B)");
});

test("wholeWords leaves an already-whole prefix alone", () => {
  assert.equal(wholeWords("SDXL 1.0"), "SDXL");   // no trailing space: cut back
  assert.equal(wholeWords("SDXL "), "SDXL");
  assert.equal(wholeWords(""), "");
  assert.equal(wholeWords("   "), "");
});

// ---- architectureLabel -----------------------------------------------------

const flux4 = spec("flux2_klein_4b", "FLUX.2 Klein (base, 4B)", "flux2");
const flux9 = spec("flux2_klein_9b", "FLUX.2 Klein (base, 9B)", "flux2");
const chromaHd = spec("chroma_hd", "Chroma1 HD", "chroma");
const chromaBase = spec("chroma_base", "Chroma1 Base", "chroma");
const zimage = spec("zimage", "Z-Image", "zimage");
const sdxl = spec("sdxl", "SDXL 1.0", "sdxl");

test("a family's heading is what its labels share", () => {
  assert.equal(architectureLabel("flux2", [flux4, flux9]), "FLUX.2 Klein");
  assert.equal(architectureLabel("chroma", [chromaHd, chromaBase]), "Chroma1");
});

test("a family of one keeps its own label", () => {
  // Z-Image's heading IS its label; an empty one would leave the group
  // unnamed on a page whose whole job is saying which family a row is in.
  assert.equal(architectureLabel("zimage", [zimage]), "Z-Image");
  assert.equal(architectureLabel("sdxl", [sdxl]), "SDXL 1.0");
});

test("a coincidental short prefix is not a family name", () => {
  // Two unrelated labels sharing two characters would otherwise produce a
  // heading like "Q" over the whole page.
  const a = spec("a", "Qwen-Image", "x");
  const b = spec("b", "Qhroma", "x");
  assert.equal(architectureLabel("x", [a, b]), "Qwen-Image");
});

test("the heading is built from the BUILT-INS, never a user model", () => {
  // A user model is listed UNDER the built-in it is based on, so letting its
  // label into the prefix would let somebody rename a whole family's heading
  // by adding one entry.
  const mine = spec("user:mine", "zzz my finetune", "flux2", { user: true });
  assert.equal(architectureLabel("flux2", [flux4, flux9, mine]),
               "FLUX.2 Klein");
  // …and a group with nothing BUT user models falls back to the engine key,
  // which is at least a name.
  assert.equal(architectureLabel("flux2", [mine]), "flux2");
});

// ---- groupByArchitecture ---------------------------------------------------

test("grouping keeps the registry's order, which IS the grouping", () => {
  const groups = groupByArchitecture([sdxl, flux4, flux9, chromaHd]);
  assert.deepEqual(groups.map(([k]) => k), ["sdxl", "flux2", "chroma"]);
  assert.deepEqual(groups[1][1].map((m) => m.key),
                   ["flux2_klein_4b", "flux2_klein_9b"]);
});

test("a model filed away from its family REJOINS it, at the family's slot", () => {
  // Worth pinning because it is not what the registry rule implies. Python's
  // `test_models_sharing_an_architecture_are_listed_together` refuses a
  // registry that reopens an engine, on the grounds that it would split the
  // family into two headings — but this grouping is a Map, so it gathers the
  // stray back in and the group keeps the position of its FIRST member.
  //
  // So the two guards do different jobs and both are worth having: Python
  // keeps the registry readable, and this says the page does not mis-render
  // one that got past it.
  const groups = groupByArchitecture([flux4, chromaHd, flux9]);
  assert.deepEqual(groups.map(([k]) => k), ["flux2", "chroma"]);
  assert.deepEqual(groups[0][1].map((m) => m.key),
                   ["flux2_klein_4b", "flux2_klein_9b"]);
});

test("a user model sorts under the built-ins of its group", () => {
  const mine = spec("user:mine", "My finetune", "flux2", { user: true });
  const [[, list]] = groupByArchitecture([mine, flux4, flux9]);
  assert.deepEqual(list.map((m) => m.key),
                   ["flux2_klein_4b", "flux2_klein_9b", "user:mine"]);
});

test("a model with no engine falls back to its base, then to its own key", () => {
  const based = spec("user:a", "A", "", { base: "sdxl", user: true });
  const loose = spec("user:b", "B", "", { user: true });
  assert.deepEqual(groupByArchitecture([based, loose]).map(([k]) => k),
                   ["sdxl", "user:b"]);
});

// ---- byArchitectureLabel ---------------------------------------------------

test("the Models page sorts groups by heading, numerically aware", () => {
  // Grouping and ORDER are two questions: the dropdown wants registry order,
  // a page you arrive at with a name in mind wants the alphabet.
  const groups = groupByArchitecture([zimage, flux4, flux9, chromaHd,
                                      chromaBase, sdxl]);
  assert.deepEqual(byArchitectureLabel(groups).map(([e, g]) =>
    architectureLabel(e, g)),
    ["Chroma1", "FLUX.2 Klein", "SDXL 1.0", "Z-Image"]);
});

test("sorting does not mutate the grouping it was handed", () => {
  // `byArchitectureLabel` copies before sorting; the dropdown renders the
  // same array in registry order and would otherwise silently re-order too.
  const groups = groupByArchitecture([zimage, chromaHd, sdxl]);
  const before = groups.map(([k]) => k);
  byArchitectureLabel(groups);
  assert.deepEqual(groups.map(([k]) => k), before);
});

test("numeric awareness puts 2 before 10 rather than after 1", () => {
  const v2 = spec("v2", "Model 2", "e2");
  const v10 = spec("v10", "Model 10", "e10");
  const sorted = byArchitectureLabel(groupByArchitecture([v10, v2]));
  assert.deepEqual(sorted.map(([k]) => k), ["e2", "e10"]);
});

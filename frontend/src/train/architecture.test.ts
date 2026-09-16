/**
 * How the Models tab groups its list.
 *
 * The page groups by ARCHITECTURE — what actually decides whether two entries
 * are interchangeable — rather than by who added them. Pure, so the ordering
 * and heading rules are stated here instead of being read off a screenshot.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  architectureLabel, byArchitectureLabel, commonPrefix,
  groupByArchitecture, nestUserModels, releaseLabel, wholeWords,
} from "./util.ts";
import type { TrainModelSpec } from "./api";

const m = (o: Partial<TrainModelSpec>) => ({
  key: "k", label: "L", repo: "r", default_area: 1024, lora_only: false,
  default_lr: 1e-4, note: "", lora_mb_per_rank: 1, full_gb: 0,
  backbone_gb: 1, aux_gb: 0, act_gb: 0, te_act_gb: 0, ckpt_factor: 0.2,
  ...o,
}) as TrainModelSpec;

const SD = m({ key: "sd15", label: "Stable Diffusion 1.5", engine: "sd" });
const SDXL = m({ key: "sdxl", label: "SDXL 1.0", engine: "sdxl" });
const HD = m({ key: "chroma", label: "Chroma1 HD", engine: "chroma" });
const BASE = m({ key: "chroma_base", label: "Chroma1 Base", engine: "chroma" });

test("the two Chroma releases land in one group", () => {
  const groups = groupByArchitecture([SD, SDXL, HD, BASE]);
  assert.deepEqual(groups.map(([k]) => k), ["sd", "sdxl", "chroma"]);
  assert.deepEqual(groups[2][1].map((x) => x.key), ["chroma", "chroma_base"]);
});

test("groups keep registry order, not alphabetical", () => {
  const groups = groupByArchitecture([SDXL, SD]);
  assert.deepEqual(groups.map(([k]) => k), ["sdxl", "sd"]);
});

test("the Models page orders the groups by heading, numerically aware", () => {
  // The grouping keeps registry order (above); the PAGE sorts what it shows.
  const F1 = m({ key: "flux1_dev", label: "FLUX.1 dev", engine: "flux" });
  const F2 = m({ key: "flux2_klein", label: "FLUX.2 Klein (base, 4B)",
                 engine: "flux2" });
  const groups = byArchitectureLabel(groupByArchitecture([SDXL, F2, SD, F1, HD]));
  assert.deepEqual(groups.map(([k]) => k),
                   ["chroma", "flux", "flux2", "sdxl", "sd"]);
});

test("a user model joins its architecture, listed after the built-ins", () => {
  const mine = m({ key: "user:x", label: "My SDXL mix", engine: "sdxl",
                   user: true });
  const groups = groupByArchitecture([SDXL, mine]);
  assert.equal(groups.length, 1);
  assert.deepEqual(groups[0][1].map((x) => x.key), ["sdxl", "user:x"]);
});

test("a user model added before `engine` existed falls back to its base", () => {
  const old = m({ key: "user:y", label: "Old entry", base: "sdxl", user: true });
  const groups = groupByArchitecture([SDXL, old]);
  assert.equal(groups.length, 1);
  assert.equal(groups[0][0], "sdxl");
});

test("the heading is the shared family name when a group has several", () => {
  assert.equal(architectureLabel("chroma", [HD, BASE]), "Chroma1");
  assert.equal(architectureLabel("sdxl", [SDXL]), "SDXL 1.0");
});

test("a coincidental one-letter overlap is not a family name", () => {
  const a = m({ key: "a", label: "Alpha", engine: "e" });
  const b = m({ key: "b", label: "Awning", engine: "e" });
  assert.equal(architectureLabel("e", [a, b]), "Alpha");
});

test("the family heading is cut at a WHOLE WORD, never mid-token", () => {
  // FLUX.2 is Klein at two sizes over one transformer and one engine, so the
  // heading is what their labels share. They share "FLUX.2 Klein (base, " —
  // and the raw common prefix put `FLUX.2 Klein (base,` at the top of the
  // Models page, comma and unclosed bracket included. It only appeared once
  // FLUX.2 dev was removed and left these two alone in the group, which is
  // how a rule that looked right for a year stopped being right.
  const k4 = m({ key: "flux2_klein", label: "FLUX.2 Klein (base, 4B)",
                 engine: "flux2" });
  const k9 = m({ key: "flux2_klein_9b", label: "FLUX.2 Klein (base, 9B)",
                 engine: "flux2" });
  const group = [k4, k9];
  assert.equal(architectureLabel("flux2", group), "FLUX.2 Klein");
  // …and the rows say what the heading does not. A row left holding nothing
  // but a bracketed aside loses the brackets.
  assert.deepEqual(group.map((x) => releaseLabel(x, "flux2", group)),
                   ["base, 4B", "base, 9B"]);
  // The rule itself, stated on its own.
  assert.equal(wholeWords("FLUX.2 Klein (base, "), "FLUX.2 Klein");
  assert.equal(wholeWords("Chroma1 "), "Chroma1");
  assert.equal(wholeWords("Z-Image Tur"), "Z-Image");
  // A prefix ending exactly on a space is already whole words.
  assert.equal(wholeWords("Qwen-Image Edit "), "Qwen-Image Edit");
});

test("a release named exactly after its family keeps its own label", () => {
  // Z-Image and Z-Image Turbo: the family name IS the base release's whole
  // label, so stripping it would leave that row with an empty name.
  const base = m({ key: "zimage", label: "Z-Image", engine: "zimage" });
  const turbo = m({ key: "zimage_turbo", label: "Z-Image Turbo",
                    engine: "zimage" });
  const group = [base, turbo];
  assert.equal(architectureLabel("zimage", group), "Z-Image");
  assert.equal(releaseLabel(base, "zimage", group), "Z-Image");
  assert.equal(releaseLabel(turbo, "zimage", group), "Turbo");
});

test("a group of only user models still gets a heading", () => {
  const mine = m({ key: "user:z", label: "Mine", engine: "weird", user: true });
  assert.equal(architectureLabel("weird", [mine]), "weird");
});

test("a release is named by what the family name does not already say", () => {
  assert.equal(releaseLabel(HD, "chroma", [HD, BASE]), "HD");
  assert.equal(releaseLabel(BASE, "chroma", [HD, BASE]), "Base");
});

test("with nothing shared to strip, the whole label stands", () => {
  const a = m({ key: "a", label: "Alpha", engine: "e" });
  const b = m({ key: "b", label: "Awning", engine: "e" });
  // architectureLabel refuses the 1-char overlap, so nothing is stripped.
  assert.equal(releaseLabel(b, "e", [a, b]), "Awning");
});

test("the add form offers every built-in, grouped as the list groups them", () => {
  // It used to offer one option per inherited PROFILE, collapsing releases
  // that differ only in native resolution — which the form asks for outright.
  // That reasoning held for Chroma's two and broke the moment FLUX.2 had a 4B
  // and a 9B: a user model inherits a memory profile and whether a full
  // finetune is offered, and the page's own list shows both, so a dropdown
  // showing one made the choice unanswerable from what was on screen. The
  // grouping the form uses is now literally the list's.
  const groups = byArchitectureLabel(groupByArchitecture([SD, SDXL, HD, BASE]));
  assert.deepEqual(
    groups.map(([e, g]) => [architectureLabel(e, g),
                            g.filter((x) => !x.user).map((x) => x.key)]),
    [["Chroma1", ["chroma", "chroma_base"]],
     ["SDXL 1.0", ["sdxl"]],
     ["Stable Diffusion 1.5", ["sd15"]]]);
});

test("a user model is listed under the built-in it is based on", () => {
  const mine = m({ key: "user:x", label: "Mine", engine: "sdxl", user: true,
                   base: "sdxl" });
  assert.deepEqual(
    nestUserModels([SDXL, mine]).map((x) => [x.model.key, x.child]),
    [["sdxl", false], ["user:x", true]]);
});

test("commonPrefix", () => {
  assert.equal(commonPrefix(["Chroma1 HD", "Chroma1 Base"]), "Chroma1 ");
  assert.equal(commonPrefix(["one"]), "one");
  assert.equal(commonPrefix([]), "");
  assert.equal(commonPrefix(["ab", "cd"]), "");
});

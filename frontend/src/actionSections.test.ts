// The three places that offer model actions must offer the SAME ones.
//
// `app/actionSections.ts` is the table the two context menus read. The right
// sidebar does NOT read it — its buttons are hand-written JSX, because each
// carries props the table cannot hold (which ids a sequence expands to, the
// done-model ticks, the "read it, then remove" extra rows, what to
// invalidate afterwards). So the table cannot keep those two in step by
// construction, and every time this has been left to care it has drifted:
// Detect text lived in the Actions tab AND the Text tab while the menus had
// it in neither, Detect watermarks sat under Detect while what it writes is
// tags, and the whole-view panel listed tags and captions under Generate
// while a selection's Actions tab listed them nowhere.
//
// So the JSX is READ. Both sidebar panels declare their kinds as literal
// `kinds={["a", "b"]}` / `ai(["a", "b"])` arrays inside a section whose
// title is one of the table's, which is enough to extract without a parser
// and enough to fail loudly when somebody adds a button to one place.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { ACTION_SECTIONS } from "./app/actionSections.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const PANEL = readFileSync(
  join(HERE, "app/components/PropertiesPanel.tsx"), "utf8");

/** The kinds named inside one section — from its opening tag to its own
 *  closing one. Bounded by the CLOSE rather than by the next section: this
 *  file holds a dozen other components that also name kinds, and slicing to
 *  the next marker swept the lot of them in. */
function kindsIn(src: string, marks: RegExp, close: string,
                 from: string): Set<string> {
  const start = [...src.matchAll(marks)].find((m) => m[1] === from);
  assert.ok(start, `no section "${from}" — the markers moved`);
  const at = start.index! + start[0].length;
  const end = src.indexOf(close, at);
  assert.ok(end > at, `section "${from}" is not closed by ${close}`);
  const out = new Set<string>();
  for (const m of src.slice(at, end)
      .matchAll(/\b(?:kinds=\{|ai\()\[([^\]]*)\]/g)) {
    for (const q of m[1].matchAll(/"([a-z_]+)"/g)) out.add(q[1]);
  }
  return out;
}

// `<CollapsibleSection title="Detect" …>` — the tab a SELECTION gets.
const TAB_MARK = /<CollapsibleSection title="(Edit|Detect|Generate)"/g;
// `<ViewSection title={t("Detect")}>` — the panel for the WHOLE VIEW.
const VIEW_MARK = /<ViewSection title=\{t\("(Edit|Detect|Generate)"\)\}/g;

test("the section table names the sections both panels use", () => {
  assert.deepEqual(ACTION_SECTIONS.map((s) => s.label),
                   ["Edit", "Detect", "Generate"]);
  // Non-vacuous: the markers still match something.
  assert.equal([...PANEL.matchAll(TAB_MARK)].length, 3);
  assert.equal([...PANEL.matchAll(VIEW_MARK)].length, 3);
});

for (const sec of ACTION_SECTIONS) {
  test(`the Actions tab's ${sec.label} section is the table's`, () => {
    assert.deepEqual(
      [...kindsIn(PANEL, TAB_MARK, "</CollapsibleSection>", sec.label)].sort(),
                     [...sec.kinds].sort());
  });

  test(`the whole-view ${sec.label} section is the table's`, () => {
    assert.deepEqual(
      [...kindsIn(PANEL, VIEW_MARK, "</ViewSection>", sec.label)].sort(),
                     [...sec.kinds].sort());
  });
}

// ---- THE MENUS DRAW THE TABLE THROUGH ONE BUILDER ------------------------
//
// `app/aiActionSections.ts` turns the table into the `RowAction` trees the
// two context menus hand to the shared menu. Neither menu may read the
// table itself any more: that is how each grew its own readiness rule, its
// own family grouping and its own copy of the extra-output preference.
import {
  aiActionRows, modelRows, readyModel, taskSections,
} from "./app/aiActionSections.ts";
import type { ModelInfo, TaskInfo } from "./app/api.ts";

const GRID = readFileSync(join(HERE, "app/components/ItemGrid.tsx"), "utf8");
const TREE = readFileSync(join(HERE, "app/components/GroupTree.tsx"), "utf8");

test("neither context menu reads the section table directly", () => {
  for (const [name, src] of [["ItemGrid", GRID], ["GroupTree", TREE]]) {
    assert.ok(!/\bACTION_SECTIONS\b/.test(src), `${name} reads ACTION_SECTIONS`);
    assert.ok(!/\bSECTION_ICON\b/.test(src), `${name} reads SECTION_ICON`);
    assert.ok(!/detectAndRemoveRows/.test(src), `${name} builds its own rows`);
    assert.ok(!/mc\.panelsSeq/.test(src),
              `${name} spells the extra-output key itself`);
    assert.ok(/aiActionRows\(/.test(src), `${name} does not use the builder`);
  }
});

const model = (id: string, o: Partial<ModelInfo> = {}): ModelInfo => ({
  id, name: id, available: true, note: "", url: "", family: "", variant: "",
  family_key: "", family_keys: [], setup_key: "", ...o,
});
const task = (kind: string, models: ModelInfo[], o: Partial<TaskInfo> = {}): TaskInfo => ({
  kind: kind as TaskInfo["kind"], label: kind, icon: "x", result: "image",
  sequence_option: false, models, ...o,
});
const id = (s: string) => s;

test("readiness: available, no reference picker, every source cached", () => {
  const ready = readyModel([
    { key: "a", cached: true } as never, { key: "b", cached: false } as never]);
  assert.equal(ready(model("m1")), true);
  assert.equal(ready(model("m2", { available: false })), false);
  assert.equal(ready(model("m3", { needs_reference: true })), false);
  assert.equal(ready(model("m4", { family_keys: ["a"] })), true);
  assert.equal(ready(model("m5", { family_keys: ["a", "b"] })), false);
});

test("sections keep the table's order and drop what has nothing ready", () => {
  const tasks = [
    task("caption", [model("c1")]),
    task("faces", [model("f1", { available: false })]),
    task("upscale", [model("u1")]),
  ];
  const secs = taskSections(tasks, readyModel([]));
  assert.deepEqual(secs.map((s) => s.label), ["Edit", "Generate"]);
  assert.deepEqual(secs.map((s) => s.rows.map((r) => r.tk.kind)),
                   [["upscale"], ["caption"]]);
  // A menu may refuse a kind for its targets.
  assert.deepEqual(
    taskSections(tasks, readyModel([]), (k) => k !== "upscale").map((s) => s.label),
    ["Generate"]);
});

test("the model panel: switch row only where the task offers one, families in blocks", () => {
  const run: string[] = [];
  const row = {
    // `panels` is the one task with a switch (its "into a sequence"); the
    // kind here only names the rows' run target.
    tk: task("upscale", [], { sequence_option: true }),
    models: [
      model("a", { family: "Alpha", variant: "x2" }),
      model("b", { family: "Alpha", variant: "x4", note: "slow" }),
      model("c", { family: "Solo" }),
    ],
  };
  const rows = modelRows(row, id, (k, m, n) => run.push(`${k}:${m}:${n}`));
  assert.deepEqual(rows.map((r) => r.label),
                   ["Place panels in a sequence", "x2", "x4", "Solo"]);
  assert.equal(rows[0].keepOpen, true);
  assert.equal(typeof rows[0].checked, "boolean");
  assert.deepEqual(rows.map((r) => !!r.separated), [false, true, false, true]);
  assert.equal(rows[2].hint, "slow");
  rows[1].onClick(); rows[3].onClick();
  assert.deepEqual(run, ["upscale:a:Alpha x2", "upscale:c:Solo"]);
  // No switch row without the option, and the first family leads plain.
  const plain = modelRows({ ...row, tk: task("upscale", []) }, id, () => {});
  assert.deepEqual(plain.map((r) => r.label), ["x2", "x4", "Solo"]);
  assert.equal(!!plain[0].separated, false);
});

test("the section rows are three levels deep and carry the count", () => {
  const secs = taskSections([task("caption", [model("c1")])], readyModel([]));
  const rows = aiActionRows(secs, id, () => {}, { trailing: "12", separatedFirst: true });
  assert.equal(rows.length, 1);
  assert.equal(rows[0].label, "Generate");
  assert.equal(rows[0].trailing, "12");
  assert.equal(rows[0].separated, true);
  assert.equal(rows[0].children?.[0].label, "caption");
  assert.equal(rows[0].children?.[0].children?.[0].label, "c1");
});

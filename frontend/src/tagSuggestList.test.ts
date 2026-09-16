/**
 * The tag suggestion list is ONE component, and this is what keeps it one.
 *
 * Three hosts had grown three copies of the same list — the rows, the arrow
 * keys, the Create row — and the copies drifted: one gated Create on the
 * answer being settled and two did not, one had the resting-pointer rule and
 * two did not, none scrolled the highlighted row into view. The shared half
 * is `TagSuggestList.tsx` (`suggestRows.ts` for the pure rule) and the hosts
 * keep only what is genuinely theirs: Escape, Tab, blur, when the list is
 * open. This reads the sources, the way `menuLayers.test.ts` does, so a host
 * that grows an ArrowDown branch or a Create row of its own fails here rather
 * than drifting quietly.
 */
import { strict as assert } from "node:assert";
import { test } from "node:test";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const SRC = fileURLToPath(new URL(".", import.meta.url));
const read = (rel: string) => readFileSync(join(SRC, rel), "utf8");

/** Every field with a suggestion list under it, and which renderer draws
 *  its rows: the app's `TagSuggestList`, or one of its own where the app's
 *  is out of reach (`query/` may not import `app/`). */
const HOST_ROWS: { file: string; renderer: "app" | "own";
  /** Reads names out of a FILE and normalises them — not a field's doing. */
  normalises?: boolean;
  /** A big file holding OTHER fields and words beside the list — the file-wide
   *  checks for a key literal or a Create row would read those. */
  mixed?: boolean;
  /** Its rows come ranked from the SERVER (a paged search), so the one
   *  client ranker has nothing to rank. */
  serverRanked?: boolean }[] = [
  { file: "app/components/TagAutocomplete.tsx", renderer: "app" },
  { file: "app/components/CombinedTagEditor.tsx", renderer: "app" },
  { file: "app/components/QuickTagOverlay.tsx", renderer: "app" },
  { file: "query/builderParts.tsx", renderer: "own" },
  // The sidebar's group and meta-tag adders, and the CSV dialog's mark
  // fields — hand-rolled lists until 2026-09.
  { file: "app/components/PropertiesPanel.tsx", renderer: "app", mixed: true },
  { file: "app/components/TagCsvOverlay.tsx", renderer: "app", normalises: true, mixed: true },
  // The parent pickers (the library's, and the set's remote one) and the
  // set's implies field.
  { file: "app/components/ParentField.tsx", renderer: "app" },
  { file: "app/components/TagSetsView.tsx", renderer: "app", mixed: true, serverRanked: true },
];
const HOSTS = HOST_ROWS.map((h) => h.file);

test("every field drives its suggestions through the one hook", () => {
  for (const { file: h, renderer, serverRanked } of HOST_ROWS) {
    const src = read(h);
    if (renderer === "app") {
      assert.ok(/from "\.\/TagSuggestList"/.test(src), `${h} imports TagSuggestList`);
    } else {
      assert.ok(/from "\.\.\/shared\/useSuggestList"/.test(src),
                `${h} imports the shared hook`);
    }
    // `useSuggestList<Row>(` counts: a host whose rows are a union of kinds
    // (the combined tag/group adder) names the type, and it is the same hook.
    assert.ok(/useSuggestList[<(]/.test(src),
              `${h} drives its list through useSuggestList`);
    // …and ranks and caps through the one ranker, never a literal.
    if (renderer === "app" && !serverRanked) {
      assert.ok(/rankTagMatches\(/.test(src), `${h} ranks its own rows`);
    }
    assert.ok(!/useDebouncedValue\([^)]*, \d+\)/.test(src),
              `${h} debounces with a literal`);
  }
});

test("a host never re-normalises what the field already committed", () => {
  // `tagFieldInput` / `tagFieldName` are the field's own; a host calling
  // `sanitizeTagInput(` or `normalizeTagName(` beside them is a second
  // spelling of the rule, which is how a name got to be one thing on
  // screen and another on the wire.
  for (const { file: h, normalises } of HOST_ROWS) {
    if (normalises) continue;
    const src = read(h);
    assert.ok(!/sanitizeTagInput\(/.test(src), `${h} calls sanitizeTagInput`);
    assert.ok(!/normalizeTagName\(/.test(src), `${h} calls normalizeTagName`);
  }
});

test("no host but the T overlay spells the field's keys itself", () => {
  // Escape, Enter and Tab are `useSuggestList`'s `input` option now
  // (`inputKeyAction`): a host naming them is a host with a second reading
  // of the two-stage Escape. The T overlay keeps its own — a three-stage
  // Escape and a ↓ that arms the tree are genuinely its.
  for (const { file: h, mixed } of HOST_ROWS) {
    if (h.endsWith("QuickTagOverlay.tsx") || mixed) continue;
    const src = read(h).replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
    assert.ok(!/e\.key === "(?:Escape|Enter|Tab)"/.test(src),
              `${h} spells a field key the hook owns`);
    assert.ok(/input: \{/.test(src), `${h} hands the field to the hook`);
  }
});

test("no host walks the list with its own arrow keys", () => {
  // The highlight is the hook's. A host that names the arrow keys is one
  // that has started a highlight of its own — the drift this file is about.
  for (const h of HOSTS) {
    const src = read(h);
    assert.ok(!/setHi\(/.test(src), `${h} keeps no highlight of its own`);
    assert.ok(!/Math\.min\(i \+ 1/.test(src) && !/Math\.max\(i - 1/.test(src),
              `${h} does not step a highlight by hand`);
  }
});

test("only TagSuggestList draws a Create row", () => {
  for (const { file: h, mixed } of HOST_ROWS) {
    if (mixed) continue;
    assert.ok(!/\bCreate[”“ ]/.test(read(h).replace(/\/\*[\s\S]*?\*\//g, "")
                                          .replace(/\/\/.*$/gm, "")),
              `${h} renders no Create row of its own`);
  }
  assert.ok(/t\("Create"\)/.test(read("app/components/TagSuggestList.tsx")));
});

test("there is exactly one rankTagMatches under app/", () => {
  const files: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const p = join(dir, name);
      if (statSync(p).isDirectory()) walk(p);
      else if (/\.tsx?$/.test(name)) files.push(p);
    }
  };
  walk(join(SRC, "app"));
  const defs = files.filter((f) => /export function rankTagMatches/.test(readFileSync(f, "utf8")));
  assert.deepEqual(defs.map((f) => f.slice(SRC.length)), ["app/tagRank.ts"]);
});

/**
 * THE FORM PRIMITIVES ARE ONE EACH — the switch, the field, the select.
 *
 * Four hand-drawn switches (three sizes, two disabled opacities, one that
 * never animated), six local `field` style constants (heights 28 to 34,
 * three radii) and ten `<select>`s each with their own `appearance: none`
 * and chevron were the same three controls drawn over and over. Each is a
 * file in `shared/` now, and this reads the sources so a fifth switch or a
 * seventh field constant fails here rather than drifting quietly.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const SRC = fileURLToPath(new URL(".", import.meta.url));

function sources(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules") continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) sources(p, out);
    else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(p);
  }
  return out;
}

const only = (needle: RegExp, allowed: string[], why: string) => {
  const offenders: string[] = [];
  for (const p of sources(SRC)) {
    const rel = p.slice(SRC.length);
    if (allowed.includes(rel)) continue;
    if (needle.test(readFileSync(p, "utf8"))) offenders.push(rel);
  }
  assert.deepEqual(offenders, [], `${why}:\n  ${offenders.join("\n  ")}`);
};

test("only shared/Switch.tsx draws a switch", () => {
  only(/role="switch"/, ["shared/Switch.tsx"], "draw the knob with <Switch>");
});

test("only shared/Field.tsx defines the field's label and style", () => {
  only(/function FieldLabel\(/, ["shared/Field.tsx"], "use FieldLabel from shared/Field");
  const offenders: string[] = [];
  for (const p of sources(join(SRC, "app"))) {
    if (/const field: React\.CSSProperties/.test(readFileSync(p, "utf8"))) {
      offenders.push(p.slice(SRC.length));
    }
  }
  assert.deepEqual(offenders, [], "use fieldStyle / fieldStyleSm from shared/Field:\n  " + offenders.join("\n  "));
});

test("only shared/Select.tsx strips a select's native arrow", () => {
  // `appearance: none` is the tell of a hand-drawn dropdown: it takes the
  // browser's arrow away and then has to draw one, at its own size, in
  // its own place. The query builder's condition rows keep the native
  // arrow for now (its selects are plain), so they are not in this.
  only(/appearance:\s*"none"/, ["shared/Select.tsx"], "draw the dropdown with <Select>");
});

test("only shared/SettingsRows.tsx defines the settings rows", () => {
  only(/function (?:PrefRow|ToggleRow|SwitchRow|Keep|Choice)\(/,
       ["shared/SettingsRows.tsx",
        // Thin wrappers naming this page's own props over the shared row —
        // the training form's carries its `?` and Unsupported chip.
        "app/components/SettingsStorage.tsx", "app/components/TagSetsView.tsx",
        "train/FormRows.tsx"],
       "compose the row from shared/SettingsRows");
});

test("only ActionToast draws a toast, and nobody runs its timer by hand", () => {
  only(/zIndex: LAYER\.toast/, ["app/components/shared/ActionToast.tsx"],
       "draw the notice with <ActionToast>");
  // PropertiesPanel's one survivor is the whole-view panel's INLINE line,
  // which is not a toast.
  only(/setTimeout\(\(\) => set(?:SelNote|Toast)\(null\)/, [],
       "pass autoDismissMs to <ActionToast> instead of a timer");
  only(/setTimeout\(\(\) => setNote\(null\)/, ["app/components/PropertiesPanel.tsx"],
       "pass autoDismissMs to <ActionToast> instead of a timer");
  const panel = readFileSync(join(SRC, "app/components/PropertiesPanel.tsx"), "utf8");
  assert.equal(panel.match(/setTimeout\(\(\) => setNote\(null\)/g)?.length, 1,
               "the panel keeps exactly the whole-view panel's inline note timer");
});

test("only shared/ProgressBar.tsx draws a track with a percent-wide fill", () => {
  // A fill: a percent-wide box, 100% high, with a background — the grid's
  // mosaic tiles are percent-wide too and have none.
  only(/height: "100%", width: `\$\{[^`]*\}%`,[^}]*background:|width: `\$\{[^`]*\}%`, height: "100%",[^}]*background:/,
       ["shared/ProgressBar.tsx"], "draw the bar with <ProgressBar>");
});

test("waiting and empty are said by the shared components", () => {
  only(/>Loading…</, ["shared/Loading.tsx"], "draw the wait with <Loading>");
  only(/padding: 40, textAlign: "center"/, ["shared/EmptyState.tsx"],
       "say it with <EmptyState>");
});

test("a number a person reads goes through useNum, never toLocaleString", () => {
  only(/\.toLocaleString\(/, ["shared/i18nCore.ts", "shared/i18n.ts", "shared/dateFormat.ts"],
       "format with useNum() (or useDateFormatters for a date)");
});

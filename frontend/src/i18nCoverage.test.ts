// Every string the UI can show must have an entry in the German catalog —
// and, through `i18nCatalogs.test.ts`'s key-parity rule, therefore in EVERY
// language. Translation is keyed by the English source text, so a missing
// entry is INVISIBLE in English and silently shows English elsewhere — which
// is exactly how the Train tab ended up untranslated once already.
//
// Two sources of truth are diffed against the catalogs:
//
//  1. EXTRACTION — every `t("…")` / `tr("…")` / `tn({one, other})` literal in
//     the source, folding the `"a " + "b"` concatenations prettier produces.
//     Binding names are discovered per file (`const tr = useT()` — `t` is a
//     tag-name variable in several scopes), and an argument the extractor
//     cannot read is a HARD FAILURE, not a skip: a template literal or a
//     concatenation with a non-literal can never match a catalog key at
//     runtime either.
//
//  2. HARVEST — strings that reach `t()` as data: the colour-band labels the
//     grid's group headers translate. (The training model registry's
//     `note`/FieldSpec strings arrive from the BACKEND and are kept in the
//     catalog by hand.)
//
// Only ONE direction is asserted (source ⊆ catalog). The reverse would
// false-positive on every `t(someVariable)` table this harvest does not
// enumerate; unused keys cost bytes, not correctness.
//
// The TRAIN catalog is loaded by path URL, not a literal import —
// `boundaries.test.ts` (correctly) reserves `train/…` imports for the lazy
// door, but that boundary protects the BUNDLE, and a test is never bundled.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, join, relative, sep } from "node:path";

import appDe from "./app/locales/de.ts";
import { COLOR_BANDS } from "./app/gridGroups.ts";
import { ACTION_SECTIONS } from "./app/actionSections.ts";
import { GRID_SIZES } from "./app/gridGeom.ts";
import { ACTIONS, UNKNOWN_ACTION } from "./app/historyActions.ts";
import { ARTIFACT_KINDS } from "./app/artifactKinds.ts";
import { STORAGE_ROW_LABELS } from "./app/storageRows.ts";
import { EMBED_STRENGTHS } from "./app/embedModels.ts";
import type { Catalog } from "./shared/i18nCore.ts";

const HERE = dirname(fileURLToPath(import.meta.url));

const trainDe = (await import(
  pathToFileURL(join(HERE, "train", "locales", "de.ts")).href
) as { default: Catalog }).default;

// The compiled field help, through the same door and for the same reason —
// a literal `train/…` import is what the bundle boundary forbids.
const HELP = (await import(
  pathToFileURL(join(HERE, "train", "fieldHelp.ts")).href
) as { HELP: Record<string, string> }).HELP;

// Same door, for the harvest below: the training editor's "unsupported"
// reasons are data, so the rules have to be run to find out what they say.
// Typed structurally rather than with a `typeof import(…)` of that module —
// `boundaries.test.ts` reads any such spelling, comments included, as an
// import of the train chunk, which is the thing it exists to forbid.
interface TrainUtil {
  unsupportedReasons: (
    config: unknown, model: unknown, device: string, slices?: boolean,
  ) => { rows: Record<string, string>;
         values: Record<string, Record<string, string>> };
  defaultTrainingConfig: (model: unknown) => Record<string, unknown>;
}
const { unsupportedReasons, defaultTrainingConfig } = await import(
  pathToFileURL(join(HERE, "train", "util.ts")).href
) as unknown as TrainUtil;

// ---------------------------------------------------------------------------
// Extraction.

function* walk(dir: string): Generator<string> {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      if (name === "locales" || name === "node_modules") continue;
      yield* walk(p);
    } else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) {
      yield p;
    }
  }
}

/** The names bound to a translator in this file: `t`/`tn`/`tr` by
 *  convention, plus whatever `const X = useT()` declares (PropertiesPanel
 *  binds `tr` where `t` is a tag-name variable). */
/** The translator bindings in one file, split by WHICH translator.
 *
 *  Which of the two a name is used to be read off the name itself — anything
 *  starting with `tn` was the plural one — and that is a rule about spelling
 *  rather than about the call. A component binding `const trn = useTn()`
 *  therefore had every one of its `trn({one, other}, n)` calls read by the
 *  SINGULAR branch, which sees a `{` where it wants a string literal and
 *  skips it as dynamic: the whole file's plurals silently unharvested, with
 *  nothing failing. So the hook is what says which, and the name is free. */
function translatorNames(src: string): { one: string[]; many: string[] } {
  const one = new Set(["t", "tr"]);
  const many = new Set(["tn"]);
  for (const m of src.matchAll(/const\s+(\w+)\s*=\s*useT(n?)\(\)/g))
    (m[2] ? many : one).add(m[1]);
  // A name bound to both in one file (there is no such case, but the sets
  // are independent) counts as both, which is the safe direction.
  return { one: [...one], many: [...many] };
}

const STR = String.raw`"(?:[^"\\]|\\.)*"`;
const CHAIN = new RegExp(`^${STR}(?:\\s*\\+\\s*${STR})*`);

function readChain(chain: string): string {
  return chain
    .split(/\s*\+\s*(?=")/)
    .map((piece) => JSON.parse(piece) as string)
    .join("");
}

/** Blank out comments (a doc example `tn({one: "…"})` is not a call site),
 *  preserving offsets and everything inside string/template literals — a
 *  regex cannot do this without eating the `//` in every URL string. */
function stripComments(src: string): string {
  const out = src.split("");
  type S = "code" | "line" | "block" | "dq" | "sq" | "tpl";
  let s: S = "code";
  for (let i = 0; i < src.length; i++) {
    const c = src[i], d = src[i + 1];
    if (s === "code") {
      if (c === "/" && d === "/") s = "line";
      else if (c === "/" && d === "*") s = "block";
      else if (c === '"') s = "dq";
      else if (c === "'") s = "sq";
      else if (c === "`") s = "tpl";
      if (s === "line" || s === "block") { out[i] = " "; }
    } else if (s === "line") {
      if (c === "\n") s = "code"; else out[i] = " ";
    } else if (s === "block") {
      if (c === "*" && d === "/") { out[i] = out[i + 1] = " "; i++; s = "code"; }
      else if (c !== "\n") out[i] = " ";
    } else if (s === "dq" || s === "sq" || s === "tpl") {
      if (c === "\\") i++;
      else if ((s === "dq" && c === '"') || (s === "sq" && c === "'")
               || (s === "tpl" && c === "`")) s = "code";
    }
  }
  return out.join("");
}

/** From `open` (an `{`), the source up to its matching `}` — string-aware. */
function braceBody(src: string, open: number): string | null {
  let depth = 0;
  for (let i = open; i < src.length; i++) {
    const c = src[i];
    if (c === '"') {
      const m = src.slice(i).match(new RegExp(`^${STR}`));
      if (!m) return null;
      i += m[0].length - 1;
    } else if (c === "{") depth++;
    else if (c === "}" && --depth === 0) return src.slice(open + 1, i);
  }
  return null;
}

interface Extracted { used: Map<string, string>; problems: string[] }

/** Every literal handed to a translator in `src`, and every call the
 *  extractor cannot read (which the assertion turns into failures). */
function extract(raw: string, file: string): Extracted {
  const src = stripComments(raw);
  const used = new Map<string, string>();
  const problems: string[] = [];
  const bound = translatorNames(src);
  for (const name of [...bound.many, ...bound.one]) {
    // tn({ one: "…", other: "…" }, …) — the `other` literal is the key.
    if (bound.many.includes(name)) {
      for (const m of src.matchAll(new RegExp(`\\b${name}\\(\\s*\\{`, "g"))) {
        const body = braceBody(src, m.index! + m[0].length - 1);
        const other = body?.match(new RegExp(`other:\\s*(${STR})`));
        const one = body?.match(new RegExp(`one:\\s*(${STR})`));
        if (!body || !other || !one) {
          problems.push(`${file}: ${name}({…}) without literal one+other`);
          continue;
        }
        used.set(JSON.parse(other[1]) as string, file);
      }
      continue;
    }
    for (const m of src.matchAll(new RegExp(`\\b${name}\\(\\s*`, "g"))) {
      const rest = src.slice(m.index! + m[0].length);
      if (rest.startsWith(")")) continue;          // t() — not a call we read
      const first = rest[0];
      if (first === "`" || first === "'") {
        problems.push(
          `${file}: ${name}(${first}…) — a template or single-quoted string `
          + `can never match a catalog key; use a double-quoted literal`);
        continue;
      }
      if (first !== '"') continue;                 // dynamic: t(x), t(f.label)
      const chain = rest.match(CHAIN);
      if (!chain) continue;
      const after = rest.slice(chain[0].length).match(/^\s*\+/);
      if (after) {
        problems.push(
          `${file}: ${name}("…" + <expr>) — concatenation with a non-literal `
          + `can never match a catalog key; use {placeholders}`);
        continue;
      }
      used.set(readChain(chain[0]), file);
    }
  }
  return { used, problems };
}

// ---------------------------------------------------------------------------

test("every translator literal in the source has a catalog entry", () => {
  const missing: string[] = [];
  const problems: string[] = [];
  for (const path of walk(HERE)) {
    // POSIX separators, because the next line asks a question ABOUT A PATH
    // and `relative` answers in the platform's own spelling. On Windows that
    // is `train\Foo.tsx`, so `startsWith("train/")` was false for every file
    // in the package — each one was then checked against the app catalog
    // alone, and all 403 of the train chunk's literals read as untranslated.
    // A whole package's coverage silently unasserted, on one platform.
    const rel = relative(HERE, path).split(sep).join("/");
    const { used, problems: p } = extract(readFileSync(path, "utf8"), rel);
    problems.push(...p);
    const inTrain = rel.startsWith("train/");
    for (const [key, file] of used) {
      // A key the app uses must be in the app's (always-loaded) catalog;
      // the train chunk's lookups reach both, so either carries its keys.
      const ok = key in appDe || (inTrain && key in trainDe);
      if (!ok) missing.push(`${file}: ${JSON.stringify(key)}`);
    }
  }
  assert.deepEqual(problems, [], `${problems.length} unreadable call(s)`);
  assert.deepEqual(missing.slice(0, 40), [],
    `${missing.length} source literal(s) with no catalog entry`);
});

test("the action SECTION headings have catalog entries", () => {
  // The two context menus and the whole-view panel render `t(sec.label)`
  // off `app/actionSections.ts`, so the labels reach `t()` as table values
  // and the extractor above cannot see them — the table is the harvest, the
  // same rule the colour bands and the grid sizes follow.
  const missing = ACTION_SECTIONS.map((s) => s.label)
    .filter((l) => !(l in appDe));
  assert.deepEqual(missing, [],
    "section headings the menus cannot say");
});

test("the grid's colour-band labels have catalog entries", () => {
  const missing = COLOR_BANDS.map((b) => b.label).filter((l) => !(l in appDe));
  assert.deepEqual(missing, [], "colour bands the group headers cannot say");
});

test("the grid's size letters and labels have catalog entries", () => {
  // The size control renders `t(g.letter)` — a CJK catalog says 小/中/大
  // where a Latin one keeps S/M/L — so the letters reach `t()` as data and
  // extraction cannot see them; the table itself is the harvest.
  const missing = GRID_SIZES.flatMap((g) => [g.letter, g.label])
    .filter((s) => !(s in appDe));
  assert.deepEqual(missing, [], "size choices the grid control cannot say");
});

test("every 'unsupported' reason the job editor can show has a catalog entry", () => {
  // The reasons live in a pure module and reach `t()` as data, so extraction
  // cannot see them — the rules themselves are the harvest. Every combination
  // that produces one is driven here, because a reason nobody enumerates is a
  // sentence that shows up in English inside an otherwise translated dialog.
  const models = [
    { key: "sdxl", label: "SDXL", default_area: 1024, default_lr: 1e-4,
      lora_mb_per_rank: 5.6, full_gb: 26, backbone_gb: 5.1, aux_gb: 2.5,
      act_gb: 30, ckpt_factor: 0.08, te_act_gb: 1.2 },
    // The other shape: no text encoder to train, and too big to finetune.
    { key: "chroma", label: "Chroma", default_area: 1024, default_lr: 3e-4,
      lora_mb_per_rank: 4, full_gb: 0, backbone_gb: 17.8, aux_gb: 7.9,
      act_gb: 133, ckpt_factor: 0.3, te_act_gb: 0, lora_only: true },
  ] as Parameters<typeof unsupportedReasons>[1][];

  const said = new Set<string>();
  for (const model of [...models, undefined]) {
    const base = defaultTrainingConfig(model);
    for (const method of ["lora", "full"] as const) {
      for (const device of ["cuda:0", "mps", "cpu"]) {
        for (const slices of [true, false]) {
        // Training the text encoder is what two of the rules are ABOUT, and
        // the harvest never turned it on — so their reasons were reachable
        // on screen and unreachable here, translated only because somebody
        // did it by hand. A sweep that misses a rule is a rule with no
        // ratchet.
        for (const trainTe of [false, true]) {
          const u = unsupportedReasons(
            { ...base, method,
              hyper: { ...base.hyper, train_text_encoder: trainTe } },
            model, device, slices);
          for (const why of Object.values(u.rows)) said.add(why);
          for (const row of Object.values(u.values))
            for (const why of Object.values(row)) said.add(why);
        }
        }
      }
    }
  }
  assert.ok(said.size >= 6, "the harvest stopped reaching the rules");
  const missing = [...said].filter((s) => !(s in trainDe) && !(s in appDe));
  assert.deepEqual(missing, [],
    `${missing.length} unsupported reason(s) with no catalog entry`);
});

test("every training field's help text has a catalog entry", () => {
  // These come from `docs/training/fields/*.md` through
  // `scripts/gen_field_help.py`, so they reach `t()` as table values and the
  // extractor above cannot see them — this table is the harvest. It is also
  // the guard on the round trip: the catalogs are keyed by the English
  // source, so a paragraph re-wrapped in the markdown silently strands all
  // seven translations, and only a check like this notices.
  const missing = Object.entries(HELP)
    .filter(([, text]) => !(text in trainDe) && !(text in appDe))
    .map(([key]) => key);
  assert.deepEqual(missing.slice(0, 20), [],
    `${missing.length} field help text(s) with no catalog entry`);
});

test("every embedder strength line has a catalog entry", () => {
  // The two dialogs offering an embedder word its strength from a table
  // keyed by model family, so the lines reach `t()` as values — the table
  // is the harvest.
  const missing = Object.values(EMBED_STRENGTHS).filter((l) => !(l in appDe));
  assert.deepEqual(missing, [],
    "embedder strengths the dropdowns cannot say");
});

test("every Storage row label has a catalog entry", () => {
  // The Storage page words a KEY the backend sends ("thumbnails"), so the
  // labels reach `t()` as table values and extraction cannot see them — the
  // table is the harvest, like the colour bands above.
  const missing = Object.values(STORAGE_ROW_LABELS).filter((l) => !(l in appDe));
  assert.deepEqual(missing, [],
    "storage rows the settings page cannot name");
});

test("every artifact kind's name has a catalog entry", () => {
  // Same shape one table over: `tn(kind.name, n)` is keyed by the English
  // `other` form, and a kind added without one shows English inside an
  // otherwise translated page.
  const missing = Object.values(ARTIFACT_KINDS)
    .map((k) => k.name.other).filter((o) => !(o in appDe));
  assert.deepEqual(missing, [], "artifact kinds nothing can name");
});

test("every History action verb has a catalog entry", () => {
  // The verbs reach `tn()` as data (`tn(m.verb, n)`), so extraction cannot
  // see them — the table itself is the harvest. The catalog key is the
  // English `other` form, the same rule every `tn()` site follows.
  const verbs = [...Object.values(ACTIONS), UNKNOWN_ACTION].map(
    (m) => m.verb.other);
  const missing = verbs.filter((v) => !(v in appDe));
  assert.deepEqual(missing, [],
    `${missing.length} History verb(s) with no catalog entry`);
});

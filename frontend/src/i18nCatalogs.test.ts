// Cross-language parity over the catalog FILES: every language complete,
// every plural entry carrying the categories its locale fires, every
// placeholder intact. This is what makes "translated by pasting the English"
// and "translated the {placeholder} away" build failures instead of
// invisible runtime fallbacks.
//
// The files are discovered with `readdirSync` and loaded BY PATH URL — not
// with literal `import "./train/locales/de"` specifiers — deliberately:
// `boundaries.test.ts` (correctly) forbids anything outside `train/` from
// importing `train/…`, but that boundary protects the BUNDLE, and a test is
// never bundled. A path built at runtime is invisible to its regex, which is
// the right outcome, not an evasion. It also makes the suite data-driven: a
// new language or package is covered with no test edit.
import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, join } from "node:path";

import { LANGUAGES } from "./shared/i18nCore.ts";
import type { Catalog, Entry, Lang, PluralForms } from "./shared/i18nCore.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const PACKAGES = ["app", "train"] as const;

async function loadCatalogs(): Promise<Map<string, Map<string, Catalog>>> {
  const out = new Map<string, Map<string, Catalog>>();
  for (const pkg of PACKAGES) {
    const dir = join(HERE, pkg, "locales");
    const files = readdirSync(dir).filter((f) => f.endsWith(".ts"));
    const perLang = new Map<string, Catalog>();
    for (const f of files) {
      const mod = await import(pathToFileURL(join(dir, f)).href) as
        { default: Catalog };
      assert.ok(mod.default && typeof mod.default === "object",
        `${pkg}/locales/${f} must default-export a catalog object`);
      perLang.set(f.replace(/\.ts$/, ""), mod.default);
    }
    out.set(pkg, perLang);
  }
  return out;
}

const CATALOGS = await loadCatalogs();

/** The placeholders a string carries, as a sorted list. */
function placeholders(s: string): string[] {
  return [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
}

function isPlural(e: Entry): e is PluralForms {
  return typeof e === "object";
}

/** The CLDR categories that can fire for some n ≠ 1 in `lang` — a plural
 *  form in one of THESE must keep its `{n}`, because the count it renders
 *  is not always 1. French selects `one` for ZERO, so a French `one` form
 *  reading "1 personne" would say "1 personne" for no people at all. */
function categoriesBeyondOne(lang: string): Set<string> {
  const rules = new Intl.PluralRules(lang);
  const out = new Set<string>();
  for (let n = 0; n <= 200; n++) if (n !== 1) out.add(rules.select(n));
  for (const n of [1e3, 1e4, 1e6, 1e7]) out.add(rules.select(n));
  return out;
}

/** Technical terms a translation may legitimately leave untouched. Keep this
 *  SHORT and deliberate — it is the hole in the pasted-English detector. */
const PASS_THROUGH_OK = new Set<string>([
  "LoRA", "VRAM", "GPU", "OK", "Hugging Face", "JPEG", "CRF", "Lanczos",
  "LR", "px",
  // Placeholder EXAMPLES of tag names and query syntax — tags and query
  // atoms never translate, so the "translation" is the same text.
  "jpeg_artifacts, low_quality",
  "masterpiece, absurdres",
  "cat  -dog  !bird",
  "a_tag_name",
  "owner/repo",
  // A proper-noun EXAMPLE in a placeholder (an event's name).
  "San Diego Comic-Con 2014",
  // Path EXAMPLES in placeholders.
  "/path/to/lora.safetensors",
  "/path/to/model (diffusers folder or .safetensors)",
]);

test("every declared language has a catalog file in every package", () => {
  for (const pkg of PACKAGES) {
    const perLang = CATALOGS.get(pkg)!;
    for (const { value } of LANGUAGES) {
      if (value === "en") continue; // English IS the source; no file exists
      assert.ok(perLang.has(value),
        `${pkg}/locales/${value}.ts is missing — the language is declared in `
        + `LANGUAGES, so it must ship complete`);
    }
    for (const name of perLang.keys()) {
      // Extra files beyond LANGUAGES are tolerated (a language mid-landing on
      // a branch); a file that could never be a language tag is not.
      assert.match(name, /^[a-z]{2}(-[A-Za-z]+)?$/,
        `${pkg}/locales/${name}.ts is not named after a BCP-47 tag`);
    }
  }
});

test("key parity: every locale of a package holds the same key set", () => {
  for (const pkg of PACKAGES) {
    const perLang = CATALOGS.get(pkg)!;
    const union = new Set<string>();
    for (const cat of perLang.values())
      for (const k of Object.keys(cat)) union.add(k);
    for (const [lang, cat] of perLang) {
      const missing = [...union].filter((k) => !(k in cat));
      assert.deepEqual(missing.slice(0, 20), [],
        `${pkg}/locales/${lang}.ts is missing ${missing.length} key(s)`);
    }
  }
});

test("no key lives in two packages", () => {
  // The convention (train/i18n.ts says it): a key the app also uses lives in
  // the APP's always-loaded catalog. A duplicate is a silent ambiguity —
  // which copy answers depends on registration order.
  const app = CATALOGS.get("app")!;
  const train = CATALOGS.get("train")!;
  for (const [lang, cat] of train) {
    const appCat = app.get(lang);
    if (!appCat) continue;
    const both = Object.keys(cat).filter((k) => k in appCat);
    assert.deepEqual(both, [],
      `key(s) in both app and train catalogs for ${lang}`);
  }
});

test("shape parity: a key is plural in every locale or in none", () => {
  for (const pkg of PACKAGES) {
    const perLang = CATALOGS.get(pkg)!;
    const pluralIn = new Map<string, string[]>();
    for (const [lang, cat] of perLang)
      for (const [k, v] of Object.entries(cat))
        if (isPlural(v))
          pluralIn.set(k, [...(pluralIn.get(k) ?? []), lang]);
    for (const [k, langs] of pluralIn) {
      for (const [lang, cat] of perLang) {
        if (!(k in cat)) continue; // key parity reports that
        assert.ok(isPlural(cat[k]),
          `${pkg}: "${k}" is a plural entry in [${langs}] but a plain string `
          + `in ${lang} — a translator flattened it`);
      }
    }
  }
});

test("plural entries carry what their locale fires, and nothing it cannot",
  () => {
    for (const pkg of PACKAGES) {
      for (const [lang, cat] of CATALOGS.get(pkg)!) {
        const cats = new Set(
          new Intl.PluralRules(lang).resolvedOptions().pluralCategories);
        for (const [k, v] of Object.entries(cat)) {
          if (!isPlural(v)) continue;
          assert.ok(typeof v.other === "string" && v.other.length > 0,
            `${pkg}/${lang}: "${k}" has no usable other form`);
          if (cats.has("one"))
            assert.ok(typeof v.one === "string",
              `${pkg}/${lang}: "${k}" lacks the one form its locale fires`);
          for (const cat2 of Object.keys(v))
            assert.ok(cats.has(cat2),
              `${pkg}/${lang}: "${k}" carries a "${cat2}" form the locale `
              + `never fires — dead weight, or a copy-paste from a template`);
        }
      }
    }
  });

test("placeholders survive translation", () => {
  for (const pkg of PACKAGES) {
    for (const [lang, cat] of CATALOGS.get(pkg)!) {
      const mustCarryN = categoriesBeyondOne(lang);
      for (const [k, v] of Object.entries(cat)) {
        const inKey = new Set(placeholders(k));
        const forms: [string, string][] = isPlural(v)
          ? Object.entries(v) : [["", v]];
        for (const [cat2, text] of forms) {
          for (const p of placeholders(text))
            assert.ok(inKey.has(p),
              `${pkg}/${lang}: "${k}" (${cat2 || "value"}) invents {${p}}, `
              + `which the key never fills`);
          for (const p of inKey) {
            // A plural form whose category can only fire at n = 1 may write
            // the count out ("1 Person"); every other form keeps every
            // placeholder.
            if (p === "n" && isPlural(v) && cat2 && !mustCarryN.has(cat2))
              continue;
            assert.ok(placeholders(text).includes(p),
              `${pkg}/${lang}: "${k}" (${cat2 || "value"}) dropped {${p}} — `
              + `the value it names can be anything, including not 1`);
          }
        }
      }
    }
  }
});

test("values are non-empty, and edge whitespace matches the key's", () => {
  // Some keys are deliberate sentence FRAGMENTS spliced around a link in JSX
  // (HfWarnings: " and can't be downloaded without one, …"), where the
  // leading space is load-bearing. So the rule is not "trimmed" — it is that
  // a translation keeps exactly the edge whitespace its key has: dropping a
  // splice fragment's space glues two words together on screen, and adding
  // one to a normal string is a paste error.
  const edges = (s: string): [string, string] =>
    [s.slice(0, s.length - s.trimStart().length),
     s.slice(s.trimEnd().length)];
  for (const pkg of PACKAGES) {
    for (const [lang, cat] of CATALOGS.get(pkg)!) {
      for (const [k, v] of Object.entries(cat)) {
        const texts = isPlural(v) ? Object.values(v) : [v];
        for (const text of texts) {
          assert.ok(text.trim().length > 0, `${pkg}/${lang}: "${k}" is empty`);
          assert.deepEqual(edges(text), edges(k),
            `${pkg}/${lang}: "${k.slice(0, 50)}" and its translation disagree `
            + `about edge whitespace`);
        }
      }
    }
  }
});

test("a translation is not the English pasted back", () => {
  // The likeliest failure across ten thousand generated strings, and
  // invisible at runtime (the fallback shows the same thing). German and the
  // Romance languages share real cognates ("Status", "Name"), so only LONG
  // identical strings are suspect there; in a CJK catalog any untranslated
  // Latin sentence is.
  for (const pkg of PACKAGES) {
    for (const [lang, cat] of CATALOGS.get(pkg)!) {
      const cjk = /^(ja|zh|ko)/.test(lang);
      for (const [k, v] of Object.entries(cat)) {
        const texts = isPlural(v) ? Object.values(v) : [v];
        for (const text of texts) {
          if (text !== k) continue;
          if (PASS_THROUGH_OK.has(k)) continue;
          const suspect = cjk ? /[A-Za-z]{4,}/.test(k) : k.length > 25;
          assert.ok(!suspect,
            `${pkg}/${lang}: "${k.slice(0, 60)}" is the English source `
            + `pasted back — translate it or allowlist it deliberately`);
        }
      }
    }
  }
});

test("query keywords survive every translation untouched", () => {
  // `INFO:` etc. are matched CASE-SENSITIVELY by the parser (tree.ts), so a
  // help text whose translation "translates" a keyword teaches a search that
  // finds nothing.
  const KEYWORDS = ["INFO:", "TAG:", "GROUP:", "GROUPONLY:", "PLACE:",
                    "SUBJECT:", "EVENT:", "CAPTION:", "INSTRUCTION:", "LINK:",
                    "LINKEDBY:", "TAKEN:", "VALUE:", "COLORLIKE:"];
  for (const pkg of PACKAGES) {
    for (const [lang, cat] of CATALOGS.get(pkg)!) {
      for (const [k, v] of Object.entries(cat)) {
        const texts = isPlural(v) ? Object.values(v) : [v];
        for (const kw of KEYWORDS) {
          if (!k.includes(kw)) continue;
          for (const text of texts)
            assert.ok(text.includes(kw),
              `${pkg}/${lang}: "${k.slice(0, 60)}…" mentions ${kw} but its `
              + `translation does not — a translated keyword breaks search`);
        }
      }
    }
  }
});

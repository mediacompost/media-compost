// The localization MACHINERY, tested by real import — possible because
// `i18nCore.ts` has zero imports (the React layer next door pulls in
// react-query, which bare `node --test` cannot load; that is why the old
// audit read the dictionaries as text).
//
// The store is module state, so each test that mutates it imports a FRESH
// module instance via a cache-busting query suffix — no test-only reset hook
// in the production module.
import test from "node:test";
import assert from "node:assert/strict";

import { fillVars, formatNumber, normalizeLang, pluralize } from "./i18nCore.ts";
import type { Catalog, Lang, PluralForms } from "./i18nCore.ts";

type Core = typeof import("./i18nCore.ts");

let fresh = 0;
async function freshCore(): Promise<Core> {
  return import(`./i18nCore.ts?fresh=${fresh++}`) as Promise<Core>;
}

/** A loader the test resolves by hand, so "not yet arrived" is a state the
 *  assertions can hold the store in. */
function deferred(catalog: Catalog) {
  let resolve!: () => void;
  let reject!: (e: Error) => void;
  const gate = new Promise<void>((res, rej) => { resolve = res; reject = rej; });
  const loader = () => gate.then(() => ({ default: catalog }));
  return { loader, resolve, reject };
}

const tick = () => new Promise<void>((r) => setTimeout(r, 0));

// ---------------------------------------------------------------------------

test("fillVars fills, repeats, coerces, and leaves the unknown alone", () => {
  assert.equal(fillVars("no vars at all"), "no vars at all");
  assert.equal(fillVars("{a} and {a}", { a: "x" }), "x and x");
  assert.equal(fillVars("{n} items", { n: 3 }), "3 items");
  assert.equal(fillVars("{a} keeps {b}", { a: "x" }), "x keeps {b}");
});

test("normalizeLang answers a Lang for anything", () => {
  assert.equal(normalizeLang("de"), "de");
  assert.equal(normalizeLang("en"), "en");
  assert.equal(normalizeLang("xx"), "en");
  assert.equal(normalizeLang(undefined), "en");
  assert.equal(normalizeLang(null), "en");
  assert.equal(normalizeLang(42), "en");
});

test("pluralize selects by CLDR category and falls back to other", () => {
  const forms: PluralForms = { one: "ein Objekt", other: "{n} Objekte" };
  assert.equal(pluralize("de", forms, 1), "ein Objekt");
  assert.equal(pluralize("de", forms, 0), "{n} Objekte");
  assert.equal(pluralize("de", forms, 2), "{n} Objekte");
  // A category the entry does not spell out falls back to `other`.
  assert.equal(pluralize("en", { other: "{n} things" }, 1), "{n} things");
});

test("the ICU this runs on has real plural data, not the small build", () => {
  // Without full ICU every locale answers only `other` and the whole plural
  // suite would pass vacuously. French has three categories; if this fails,
  // the Node running the tests is built without full-icu.
  assert.ok(
    new Intl.PluralRules("fr").resolvedOptions().pluralCategories.length > 1,
    "Node without full ICU cannot validate plural handling");
});

test("the CLDR facts the design leans on hold", () => {
  // Verified at design time; pinned so an ICU update cannot silently move
  // them from under the catalogs. ja/zh/ko: one form. fr/pt-BR: `one` fires
  // for ZERO, so a translated `one` form must keep its {n}.
  for (const l of ["ja", "zh-Hans", "ko"])
    assert.deepEqual(new Intl.PluralRules(l).resolvedOptions().pluralCategories,
                     ["other"], l);
  for (const l of ["fr", "pt-BR"])
    assert.equal(new Intl.PluralRules(l).select(0), "one", l);
  for (const l of ["en", "de", "es"])
    assert.equal(new Intl.PluralRules(l).select(0), "other", l);
});

test("formatNumber writes the language's separators", () => {
  assert.equal(formatNumber("en", 1234567), "1,234,567");
  assert.equal(formatNumber("de", 1234567), "1.234.567");
  assert.equal(formatNumber("de", 1.5), "1,5");
});

// --- the store -------------------------------------------------------------

test("translate falls back to English until the catalog lands, then flips once",
  async () => {
    const core = await freshCore();
    const d = deferred({ "Library": "Bibliothek" });
    core.registerCatalogs("app", { de: d.loader });

    const v0 = core.getVersion();
    core.setWantedLang("de");
    // Asked for, not yet in force: everything still reads English.
    assert.equal(core.activeLang(), "en");
    assert.equal(core.translate("de", "Library"), "Library");

    d.resolve();
    await tick();
    assert.equal(core.activeLang(), "de");
    assert.equal(core.translate("de", "Library"), "Bibliothek");
    assert.equal(core.translate("de", "not a key"), "not a key");
    assert.equal(core.getVersion(), v0 + 1, "exactly one bump for the flip");
  });

test("the flip waits for EVERY registered package", async () => {
  const core = await freshCore();
  const app = deferred({ "Library": "Bibliothek" });
  const train = deferred({ "New training job": "Neuer Trainingsauftrag" });
  core.registerCatalogs("app", { de: app.loader });
  core.registerCatalogs("train", { de: train.loader });

  core.setWantedLang("de");
  app.resolve();
  await tick();
  // One package in, one still loading: no half-translated frame.
  assert.equal(core.activeLang(), "en");

  train.resolve();
  await tick();
  assert.equal(core.activeLang(), "de");
});

test("late registration kicks its own load (the lazy train chunk)", async () => {
  const core = await freshCore();
  const app = deferred({ "Library": "Bibliothek" });
  core.registerCatalogs("app", { de: app.loader });
  core.setWantedLang("de");
  app.resolve();
  await tick();
  assert.equal(core.activeLang(), "de");

  // The train chunk evaluates NOW, long after the language resolved.
  // Registration itself must fetch its catalog — nothing else would.
  const train = deferred({ "New training job": "Neuer Trainingsauftrag" });
  const v = core.getVersion();
  core.registerCatalogs("train", { de: train.loader });
  train.resolve();
  await tick();
  assert.equal(core.translate("de", "New training job"),
               "Neuer Trainingsauftrag");
  assert.equal(core.getVersion(), v + 1, "the late catalog bumps once");
});

test("a failed load still flips (English fallback), and a re-ask retries",
  async () => {
    const core = await freshCore();
    const bad = deferred({});
    core.registerCatalogs("app", { de: bad.loader });
    core.setWantedLang("de");
    bad.reject(new Error("network"));
    await tick();
    // The language is in force — dates, numbers, plural rules are German —
    // and the missing catalog reads as English source, today's missing-key
    // behavior.
    assert.equal(core.activeLang(), "de");
    assert.equal(core.translate("de", "Library"), "Library");

    // Nothing was cached, so asking again retries the loader.
    const good = deferred({ "Library": "Bibliothek" });
    core.registerCatalogs("app", { de: good.loader });
    core.setWantedLang("de");
    good.resolve();
    await tick();
    assert.equal(core.translate("de", "Library"), "Bibliothek");
  });

test("a stale load must not beat a newer choice", async () => {
  const core = await freshCore();
  const de = deferred({ "Library": "Bibliothek" });
  core.registerCatalogs("app", { de: de.loader });
  core.setWantedLang("de");
  // The user flips back to English while German is still in flight.
  core.setWantedLang("en");
  assert.equal(core.activeLang(), "en");
  de.resolve();
  await tick();
  // The late arrival is cached for next time but does not flip the UI.
  assert.equal(core.activeLang(), "en");
});

test("asking for the current language again does not bump", async () => {
  const core = await freshCore();
  const d = deferred({ "Library": "Bibliothek" });
  core.registerCatalogs("app", { de: d.loader });
  core.setWantedLang("de");
  d.resolve();
  await tick();
  const v = core.getVersion();
  core.setWantedLang("de");
  await tick();
  assert.equal(core.getVersion(), v);
});

test("the snapshot is identical to itself (the recent.ts identity trap)",
  async () => {
    const core = await freshCore();
    assert.equal(core.getVersion(), core.getVersion());
    assert.equal(typeof core.getVersion(), "number");
  });

test("translateN selects, translates, and formats {n}", async () => {
  const core = await freshCore();
  const d = deferred({
    "{n} people": { one: "1 Person", other: "{n} Personen" } as const,
    "{n} of {total}": "{n} von {total}",
  });
  core.registerCatalogs("app", { de: d.loader });
  core.setWantedLang("de");
  d.resolve();
  await tick();

  const src = { one: "1 person", other: "{n} people" };
  assert.equal(core.translateN("de", src, 1), "1 Person");
  assert.equal(core.translateN("de", src, 2), "2 Personen");
  assert.equal(core.translateN("de", src, 1234), "1.234 Personen");
  // English never consults a catalog and formats its own way.
  assert.equal(core.translateN("en", src, 1), "1 person");
  assert.equal(core.translateN("en", src, 1234), "1,234 people");
  // A missing entry answers the ENGLISH forms under English rules.
  const miss = { one: "1 box", other: "{n} boxes" };
  assert.equal(core.translateN("de", miss, 1), "1 box");
  assert.equal(core.translateN("de", miss, 3), "3 boxes");
  // Extra vars fill beside the auto-{n}.
  assert.equal(
    core.translateN("de", { one: "{n} of {total}", other: "{n} of {total}" },
                    5, { total: 9 }),
    "5 von 9");
});

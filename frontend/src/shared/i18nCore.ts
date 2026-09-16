import { storage } from "../shared/storage.ts";
// The localization CORE: the language set, the catalog store, and the pure
// lookup functions. ZERO imports, deliberately — that is what lets bare
// `node --test` import it (the React layer next door pulls in react-query,
// which the test runner cannot load), lets `train/recommend.ts` share
// `fillVars` instead of carrying a duplicate, and lets the per-language
// catalog files stay pure data.
//
// Strings are translated by their English SOURCE text (`t("Library")`), so
// wrapping existing UI text is low-friction and any string without a
// translation gracefully falls back to English. The dictionaries live with
// their owners as `locales/<lang>.ts` files — pure `export default {…}`
// modules — and are REGISTERED here as dynamic-import loaders
// (`registerCatalogs`): `app/i18n.ts` names the app's seven in the main
// bundle, `train/i18n.ts` names the trainer's inside the lazy train chunk.
// Vite therefore emits one chunk per (package, language): English downloads
// zero dictionary bytes, and another language fetches exactly its own two.

/** The UI languages. Every code is valid BCP-47, so the same string is what
 *  `Intl` formatters take — no second mapping table. */
export type Lang =
  "en" | "de" | "ja" | "zh-Hans" | "ko" | "es" | "pt-BR" | "fr";

export const DEFAULT_LANG: Lang = "en";

/** Labelled with the ENDONYM: someone who cannot read the current UI
 *  language has to be able to find their own in the list. */
export const LANGUAGES: readonly { value: Lang; label: string }[] = [
  { value: "en", label: "English" },
  { value: "de", label: "Deutsch" },
  { value: "ja", label: "日本語" },
  { value: "zh-Hans", label: "简体中文" },
  { value: "ko", label: "한국어" },
  { value: "es", label: "Español" },
  { value: "pt-BR", label: "Português (Brasil)" },
  { value: "fr", label: "Français" },
];

/** Whatever the wire or storage handed us, as a `Lang` — unknown is English.
 *  The backend coerces an unknown code the same way (`settings._LANGUAGES`),
 *  so the two sides cannot disagree about what a bad value means. */
export function normalizeLang(v: unknown): Lang {
  return LANGUAGES.some((l) => l.value === v) ? (v as Lang) : DEFAULT_LANG;
}

/** A translated plural entry: one string per CLDR category the language
 *  actually uses. Only `other` is required — Japanese needs nothing else,
 *  and `many` in the Romance languages only fires at 10^6 and may simply
 *  fall back. NOTE (enforced by `i18nCatalogs.test.ts`): a form must keep
 *  its `{n}` if its category can fire for any n ≠ 1 in that locale — French
 *  selects `one` for ZERO, so a French `one` reading "1 personne" would
 *  render "1 personne" for no people at all. */
export type PluralForms =
  { other: string } & Partial<Record<Intl.LDMLPluralRule, string>>;

/** A catalog value: a plain translation, or one string per plural category. */
export type Entry = string | PluralForms;

/** One language's dictionary for one package, keyed by the English source —
 *  a singular string for `t()` keys, the English `other` form for `tn()`
 *  keys. */
export type Catalog = Readonly<Record<string, Entry>>;

/** The ENGLISH source at a `tn()` call site. Both forms are REQUIRED — the
 *  call site is where English gets its singular, and making it optional is
 *  how "1 items" ships. */
export type PluralSource =
  { one: string; other: string } & Partial<Record<Intl.LDMLPluralRule, string>>;

type Pkg = "app" | "train";
type CatalogLoader = () => Promise<{ default: Catalog }>;

// ---------------------------------------------------------------------------
// The store. Loaded catalogs live in module state so `translate` can stay
// synchronous; React reads it through `useSyncExternalStore` in `i18n.ts`.
// The SNAPSHOT is a plain number (`getVersion`) — trivially identical to
// itself, so the identity trap `app/subjects/recent.ts` documents (a snapshot
// built fresh per call re-renders forever) cannot happen by construction.

const LOADERS = new Map<Pkg, Partial<Record<Lang, CatalogLoader>>>();
const LOADED = new Map<Lang, Map<Pkg, Catalog>>();
const INFLIGHT = new Map<string, Promise<void>>();
const listeners = new Set<() => void>();

let wanted: Lang = DEFAULT_LANG;
let active: Lang = DEFAULT_LANG;
let version = 0;

function bump(): void {
  version++;
  for (const cb of listeners) cb();
}

export function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

/** The `useSyncExternalStore` snapshot: bumps exactly when a catalog lands or
 *  the active language flips, so a `useMemo` keyed on it invalidates exactly
 *  when a lookup could answer differently. */
export function getVersion(): number {
  return version;
}

/** The language actually IN FORCE — loaded and applied, not merely asked
 *  for. Everything on screen (strings, plural selection, `Intl` output)
 *  reads this, so a switch lands in one commit: never a frame of French
 *  dates around English sentences. */
export function activeLang(): Lang {
  return active;
}

/** Kick the loads for `lang`'s catalogs; `active` flips once every registered
 *  package has settled. A package whose load FAILED still counts as settled —
 *  its strings fall back to the English source (exactly the missing-key
 *  behavior) while the rest of the language works — and is retried on the
 *  next `setWantedLang`, since a failure caches nothing. */
function ensure(lang: Lang): void {
  if (lang === DEFAULT_LANG) {
    if (active !== DEFAULT_LANG) { active = DEFAULT_LANG; bump(); }
    return;
  }
  const pending: Promise<void>[] = [];
  for (const [pkg, loaders] of LOADERS) {
    if (LOADED.get(lang)?.has(pkg)) continue;
    const key = `${pkg}:${lang}`;
    let p = INFLIGHT.get(key);
    if (!p) {
      const loader = loaders[lang];
      if (!loader) continue; // this package has no catalog for the language
      p = loader()
        .then((m) => {
          let map = LOADED.get(lang);
          if (!map) LOADED.set(lang, (map = new Map()));
          map.set(pkg, m.default);
        })
        .catch(() => { /* fall back to English source; retried next switch */ })
        .finally(() => { INFLIGHT.delete(key); });
      INFLIGHT.set(key, p);
    }
    pending.push(p);
  }
  if (!pending.length) {
    if (wanted === lang && active !== lang) { active = lang; bump(); }
    return;
  }
  void Promise.all(pending).then(() => {
    // Only flip if this is still the language being asked for — a fast
    // de→fr→de dance must not land on fr because its load finished last.
    if (wanted !== lang) return;
    active = lang;
    bump(); // even if active already === lang: a late catalog just landed
  });
}

/** Ask for a language. Idempotent and cheap; the flip happens when the
 *  catalogs are in (see `ensure`). Also persists the choice as the reload
 *  hint. */
export function setWantedLang(lang: Lang): void {
  wanted = lang;
  writeHint(lang);
  ensure(lang);
}

/**
 * Declare a package's per-language catalog chunks. Called at module load by
 * `app/i18n.ts` (main bundle) and `train/i18n.ts` (inside the lazy train
 * chunk). The tail matters: the train chunk evaluates long after the
 * language was resolved, so registration itself must kick the load for the
 * language already in force — nothing else would.
 */
export function registerCatalogs(
  pkg: Pkg, loaders: Partial<Record<Lang, CatalogLoader>>,
): void {
  LOADERS.set(pkg, loaders);
  if (wanted !== DEFAULT_LANG && !LOADED.get(wanted)?.has(pkg)) ensure(wanted);
}

// --- The reload hint -------------------------------------------------------
// The language lives in the per-user settings on the SERVER; localStorage
// only remembers the last answer so a returning user's catalogs start
// loading before `/api/settings` comes back — without it every non-English
// user reads English for the first round trip of every load. Stale (changed
// on another device) costs a de→fr flash instead of an en→fr flash: no worse.

const HINT_KEY = "mc.lang";

function readHint(): Lang {
  try {
    if (typeof localStorage !== "undefined")
      return normalizeLang(storage.get(HINT_KEY));
  } catch { /* storage disabled */ }
  return DEFAULT_LANG;
}

function writeHint(lang: Lang): void {
  try {
    if (typeof localStorage !== "undefined")
      storage.set(HINT_KEY, lang);
  } catch { /* storage disabled */ }
}

wanted = readHint();

// ---------------------------------------------------------------------------
// Lookup.

/** Translate `text` into `lang`, falling back to the (English) source. A
 *  plural entry met here answers with its `other` form — the singular path
 *  has no count to select with. */
export function translate(lang: Lang, text: string): string {
  if (lang === DEFAULT_LANG) return text;
  const map = LOADED.get(lang);
  if (map) {
    for (const cat of map.values()) {
      const hit = cat[text];
      if (hit !== undefined) return typeof hit === "string" ? hit : hit.other;
    }
  }
  return text;
}

const RULES = new Map<string, Intl.PluralRules>();
function rulesFor(lang: string): Intl.PluralRules {
  let r = RULES.get(lang);
  if (!r) RULES.set(lang, (r = new Intl.PluralRules(lang)));
  return r;
}

/** Pick the right form for `n` under `lang`'s CLDR rules, falling back to
 *  `other` for a category the entry does not spell out. */
export function pluralize(lang: Lang, forms: PluralForms, n: number): string {
  return forms[rulesFor(lang).select(n)] ?? forms.other;
}

/**
 * The `tn()` engine: look the English `other` form up in `lang`'s catalogs,
 * select the plural form for `n`, and fill `{n}` (locale-formatted — a
 * French UI reads "1 234") plus any extra `vars`. A miss uses the English
 * source forms, selected under ENGLISH rules — English wording must not
 * inflect by another language's categories.
 */
export function translateN(
  lang: Lang, src: PluralSource, n: number,
  vars?: Record<string, string | number>,
): string {
  let forms: PluralForms | null = null;
  if (lang !== DEFAULT_LANG) {
    const map = LOADED.get(lang);
    if (map) {
      for (const cat of map.values()) {
        const hit = cat[src.other];
        if (hit !== undefined) {
          forms = typeof hit === "string" ? { other: hit } : hit;
          break;
        }
      }
    }
  }
  const text = forms
    ? pluralize(lang, forms, n)
    : pluralize(DEFAULT_LANG, src, n);
  return fillVars(text, { n: formatNumber(lang, n), ...vars });
}

/** Substitute `{placeholders}` AFTER translation.
 *
 *  Translation is keyed by the English SOURCE string, so a sentence built by
 *  interpolation could never be looked up — and word order around a slotted
 *  value differs per language anyway. The source string therefore keeps fixed
 *  `{name}` placeholders, and they are filled in once the lookup has
 *  happened. Values pass through `String()` untouched — uids, paths and
 *  model names must not pick up thousands separators; a NUMBER the reader
 *  should see formatted goes through `formatNumber` first (`tn()` does that
 *  for its own `{n}`).
 */
export function fillVars(
  text: string, vars?: Record<string, string | number>,
): string {
  if (!vars) return text;
  return Object.keys(vars).reduce(
    (out, k) => out.split(`{${k}}`).join(String(vars[k])), text);
}

const NUMFMT = new Map<string, Intl.NumberFormat>();

/** A number as `lang` writes one — `1 234,5` in French, `1.234,5` in German.
 *  Cached per (lang, options): this renders in 500-row lists. */
export function formatNumber(
  lang: string, n: number, opts?: Intl.NumberFormatOptions,
): string {
  const key = opts ? `${lang} ${JSON.stringify(opts)}` : lang;
  let f = NUMFMT.get(key);
  if (!f) NUMFMT.set(key, (f = new Intl.NumberFormat(lang, opts)));
  return f.format(n);
}

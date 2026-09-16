// The trainer's localization FACADE — the half that rides INSIDE the lazy
// train chunk, so the main bundle does not carry it and a deployment that
// never opens a training tab never fetches a byte of it. The machinery (and
// the app's own catalogs) is `shared/i18n.ts`; the dictionaries are pure-data
// files under `locales/`, one chunk per language. Entries whose keys the app
// also uses live in the APP's catalog, which is always loaded, so lookup here
// can never miss.
//
// Registration happens at module load — which for this package is whenever
// the train chunk first evaluates, long after the language was resolved.
// `registerCatalogs` knows that and kicks the load for the language already
// in force; the Train tab reads English for one round trip the first time it
// opens in a non-English session, which is the honest cost of lazy.

import { registerCatalogs } from "../shared/i18n";
import type { Catalog, Lang } from "../shared/i18n";

export { fillVars, formatNumber, useErrText, useLang, useNum, useT, useTn }
  from "../shared/i18n";
export type { Lang, PluralSource, TFn, TnFn } from "../shared/i18n";

const LOADERS: Record<
  Exclude<Lang, "en">, () => Promise<{ default: Catalog }>
> = {
  de: () => import("./locales/de"),
  ja: () => import("./locales/ja"),
  "zh-Hans": () => import("./locales/zh-Hans"),
  ko: () => import("./locales/ko"),
  es: () => import("./locales/es"),
  "pt-BR": () => import("./locales/pt-BR"),
  fr: () => import("./locales/fr"),
};

registerCatalogs("train", LOADERS);

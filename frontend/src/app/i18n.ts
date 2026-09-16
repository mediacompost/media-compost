// The app's localization FACADE. The machinery lives in `shared/i18n.ts`
// (the query builder and the chrome translate without importing the app);
// the dictionaries are pure-data files under `locales/`, one per language,
// REGISTERED here as dynamic-import loaders so Vite emits each as its own
// chunk — English downloads zero dictionary bytes, another language fetches
// exactly its own. This module re-exports the machinery so the app's ~50
// import sites keep their spelling.
//
// The loader table is a TOTAL Record over the non-English languages: adding
// a tag to `Lang` without a catalog here is a `tsc -b` error, so a language
// lands complete or not at all.

import { registerCatalogs } from "../shared/i18n";
import type { Catalog, Lang } from "../shared/i18n";

export {
  LANGUAGES, fillVars, formatNumber, translate,
  useErrText, useLang, useNum, useT, useTn,
} from "../shared/i18n";
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

registerCatalogs("app", LOADERS);

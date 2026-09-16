// The REACT layer of localization: hooks binding the pure core next door
// (`i18nCore.ts` — the store, the lookup, `fillVars`) to the settings query
// and to `useSyncExternalStore`. Owned by `shared/` so the query builder and
// the chrome can translate without importing the app; the DICTIONARIES live
// with their owners under `app/locales/` and `train/locales/` and register
// through `registerCatalogs` — the app's in the main bundle, the trainer's
// inside the lazy train chunk, each language a chunk of its own that only a
// user of that language ever fetches.

import { useEffect, useMemo, useSyncExternalStore } from "react";
import { useQuery } from "@tanstack/react-query";

import { ApiError, api } from "./api";
import {
  activeLang, fillVars, formatNumber, getVersion, normalizeLang,
  setWantedLang, subscribe, translate, translateN,
} from "./i18nCore";
import type { Lang, PluralSource } from "./i18nCore";

export * from "./i18nCore";

/** A bound `t()`: translate by English source, then fill `{placeholders}`. */
export type TFn =
  (text: string, vars?: Record<string, string | number>) => string;

/** A bound `tn()`: plural-select by count, translate, fill `{n}` + vars. */
export type TnFn = (
  src: PluralSource, n: number, vars?: Record<string, string | number>,
) => string;

/**
 * The current UI language — the one actually LOADED and in force, which is
 * what everything on screen must read so a switch lands in one commit (see
 * `i18nCore.activeLang`). Also the one place the settings answer reaches the
 * store: `setWantedLang` is idempotent, so every mounted `useLang` pushing it
 * costs nothing, and there is no separate "sync" hook to forget to mount.
 */
export function useLang(): Lang {
  const { data } = useQuery({ queryKey: ["settings"], queryFn: api.getSettings });
  const lang = normalizeLang(data?.language);
  useEffect(() => {
    // Only once settings actually ANSWERED: `undefined` normalizes to "en",
    // and pushing that while the request is in flight would undo the
    // localStorage hint that has the right catalogs already loading.
    if (data) setWantedLang(lang);
  }, [data, lang]);
  useSyncExternalStore(subscribe, getVersion, getVersion);
  return activeLang();
}

/** A `t()` bound to the current UI language, for use in components.
 *
 *  MEMOIZED on (language, catalog version) — the version bumps exactly when
 *  a lookup could answer differently, so `t` is a stable identity the rest
 *  of the time and is safe (and meaningful) in dependency arrays. */
export function useT(): TFn {
  const lang = useLang();
  const version = useSyncExternalStore(subscribe, getVersion, getVersion);
  return useMemo(
    () => (text, vars) => fillVars(translate(lang, text), vars),
    [lang, version],
  );
}

/** A `tn()` bound to the current UI language: the plural-aware `t`.
 *
 *      tn({ one: "1 person", other: "{n} people" }, count)
 *
 *  The catalog key is the English `other` form; `{n}` arrives already
 *  locale-formatted. See `i18nCore.translateN`. */
export function useTn(): TnFn {
  const lang = useLang();
  const version = useSyncExternalStore(subscribe, getVersion, getVersion);
  return useMemo(
    () => (src, n, vars) => translateN(lang, src, n, vars),
    [lang, version],
  );
}

/** A number formatter bound to the current UI language — for counts and
 *  measures a PERSON reads. Machine tokens (CSS values, SVG paths, URL
 *  params, `<input>` values) must keep `String()`/`toFixed()`. */
export function useNum(): (n: number, opts?: Intl.NumberFormatOptions) => string {
  const lang = useLang();
  return useMemo(() => (n, opts) => formatNumber(lang, n, opts), [lang]);
}

/** A backend refusal, in the UI language.
 *
 *  An `ApiError` carrying its template (`detail_key`/`detail_vars` on the
 *  wire) is looked up and re-filled; anything else has its message tried as
 *  its OWN key — a static refusal ("a tag cannot imply itself") is its own
 *  template, so putting the English sentence in the catalog translates it
 *  with no backend change at all. A message the catalog has never heard of
 *  falls through unchanged, which is exactly the old behavior. */
export function useErrText(): (e: unknown) => string {
  const t = useT();
  return useMemo(() => (e: unknown) => {
    if (e instanceof ApiError && e.key) return t(e.key, e.vars);
    return t(e instanceof Error ? e.message : String(e));
  }, [t]);
}

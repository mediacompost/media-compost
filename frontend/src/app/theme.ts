import { storage } from "../shared/storage.ts";
// Light / dark / system theme handling. The chosen *preference* is persisted;
// the *resolved* theme (light|dark) is written to <html data-theme> so the CSS
// overrides in tokens.css apply. "system" follows the OS setting live.
export type ThemePref = "light" | "dark" | "system";

const KEY = "mc.theme";

export function loadThemePref(): ThemePref {
  const v = storage.get(KEY);
  return v === "light" || v === "dark" || v === "system" ? v : "dark";
}

function systemPrefersDark(): boolean {
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function resolveTheme(pref: ThemePref): "light" | "dark" {
  return pref === "system" ? (systemPrefersDark() ? "dark" : "light") : pref;
}

function apply(pref: ThemePref) {
  document.documentElement.dataset.theme = resolveTheme(pref);
}

export function setThemePref(pref: ThemePref) {
  try {
    storage.set(KEY, pref);
  } catch {
    /* ignore */
  }
  apply(pref);
}

// Apply the stored preference on startup and keep following the OS while the
// preference is "system". Called once from main.tsx (in every window).
export function initTheme() {
  apply(loadThemePref());
  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", () => {
      if (loadThemePref() === "system") apply("system");
    });
}

import React, { useEffect, useState } from "react";
import { storage } from "../../../shared/storage";
import { Icon } from "../../../shared/Icon";
import { loadThemePref, resolveTheme } from "../../theme";
import { CHROME_BTN } from "./iconButtons";
import { RowMenu } from "../../../shared/RowMenu";

/**
 * The image editor's and the annotator's theme control. Each window can be
 * light or dark on its own — judging an image against the opposite background
 * is half of why the control exists — or follow the app, which is the default.
 *
 * "Default" really does FOLLOW: the app's setting lives in localStorage, so a
 * change made in the main window arrives here as a `storage` event, and a
 * "system" preference is re-resolved when the OS flips. A window set to light
 * or dark stays put through both.
 */
export type WindowTheme = "default" | "light" | "dark";

export type ThemeOption<V extends string> = { value: V; label: string; icon: string };

const OPTIONS: ThemeOption<WindowTheme>[] = [
  { value: "default", label: "Default", icon: "contrast" },
  { value: "light", label: "Light", icon: "light_mode" },
  { value: "dark", label: "Dark", icon: "dark_mode" },
];

function read(key: string): WindowTheme {
  try {
    const v = storage.get(key);
    return v === "light" || v === "dark" ? v : "default";
  } catch {
    return "default";
  }
}

/** Each window remembers its own choice (the editor and the annotator use
 *  different storage keys), both defaulting to following the app. */
export function useWindowTheme(storageKey = "mc.editorTheme"):
    [WindowTheme, (v: WindowTheme) => void] {
  const [pref, setPref] = useState<WindowTheme>(() => read(storageKey));
  useEffect(() => {
    try { storage.set(storageKey, pref); } catch { /* ignore */ }
    const root = document.documentElement;
    const apply = () => {
      root.dataset.theme = pref === "default" ? resolveTheme(loadThemePref()) : pref;
    };
    apply();
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", apply);
    window.addEventListener("storage", apply);
    return () => {
      media.removeEventListener("change", apply);
      window.removeEventListener("storage", apply);
      root.dataset.theme = resolveTheme(loadThemePref());
    };
  }, [pref, storageKey]);
  return [pref, setPref];
}

/** The item window's theme button: the shared chrome square, tinted while this
 *  window is holding a theme of its own. The three headers each spelled this
 *  out and had drifted — one of them left the icon grey when it was active. */
const THEME_BTN = (active: boolean): React.CSSProperties => ({
  ...CHROME_BTN,
  background: active ? "var(--accent-dim)" : "transparent",
  color: active ? "var(--accent)" : "var(--text-2)",
});

export function ThemeMenu<V extends string = WindowTheme>({
  value, onChange, options, buttonStyle = THEME_BTN, iconSize = 19, t, title,
}: {
  value: V;
  onChange: (v: V) => void;
  /** The choices — the item window's default / light / dark unless a host
   *  passes its own (the app's top bar: light / dark / system). */
  options?: ThemeOption<V>[];
  /** A host with a toolbar of another shape. The item window's three headers
   *  are one header and take the default. */
  buttonStyle?: (active: boolean) => React.CSSProperties;
  iconSize?: number;
  /** REQUIRED — an optional translator is a silent-English hole. A
   *  deliberately-English window passes an identity. */
  t: (s: string) => string;
  title?: string;
}) {
  const opts = (options ?? (OPTIONS as unknown as ThemeOption<V>[]));
  const current = opts.find((o) => o.value === value) ?? opts[0];
  // One tick per row, the way every choice in a menu here is shown.
  return (
    <RowMenu always icon={current.icon} title={title ?? t("Theme for this window")}
      minWidth={140}
      buttonStyle={{ ...buttonStyle(value !== opts[0].value), fontSize: iconSize > 17 ? undefined : undefined }}
      actions={opts.map((o) => ({
        checked: o.value === value, label: t(o.label), onClick: () => onChange(o.value),
      }))} />
  );
}

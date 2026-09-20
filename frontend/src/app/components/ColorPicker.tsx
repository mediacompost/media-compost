import React, { useEffect, useMemo, useRef, useState } from "react";
import { storage } from "../../shared/storage";
import { SectionHeading } from "../../shared/SectionHeading";
import { Icon } from "../../shared/Icon";
import { useMenuDismiss } from "../../shared/useMenuDismiss";

/**
 * Custom color-picker popover for the image editor's swatches: an SV square +
 * hue and alpha sliders, editable values in RGB / HSL / HSV / Hex (all with
 * alpha), and a persistent "recent colors" row. Native <input type=color> has
 * no alpha, no HSL/HSV entry and no recents — and no transparent state.
 */

const RECENT_KEY = "mc.recentColors";
const RECENT_MAX = 12;

// ---- conversions -----------------------------------------------------------

function hsvToRgb(h: number, s: number, v: number): [number, number, number] {
  const c = (v / 100) * (s / 100);
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = v / 100 - c;
  const [r, g, b] =
    h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x]
    : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return [Math.round((r + m) * 255), Math.round((g + m) * 255), Math.round((b + m) * 255)];
}

function rgbToHsv(r: number, g: number, b: number): [number, number, number] {
  const rn = r / 255, gn = g / 255, bn = b / 255;
  const max = Math.max(rn, gn, bn), min = Math.min(rn, gn, bn);
  const d = max - min;
  let h = 0;
  if (d > 0) {
    h = max === rn ? ((gn - bn) / d) % 6 : max === gn ? (bn - rn) / d + 2 : (rn - gn) / d + 4;
    h = (h * 60 + 360) % 360;
  }
  return [h, max === 0 ? 0 : (d / max) * 100, max * 100];
}

function hsvToHsl(h: number, s: number, v: number): [number, number, number] {
  const l = (v / 100) * (1 - s / 200);
  const sl = l === 0 || l === 1 ? 0 : ((v / 100) - l) / Math.min(l, 1 - l);
  return [h, sl * 100, l * 100];
}

function hslToHsv(h: number, s: number, l: number): [number, number, number] {
  const v = l / 100 + (s / 100) * Math.min(l / 100, 1 - l / 100);
  const sv = v === 0 ? 0 : 2 * (1 - l / 100 / v);
  return [h, sv * 100, v * 100];
}

function parseHex(hex: string): [number, number, number, number] | null {
  const m = hex.trim().replace(/^#/, "");
  if (!/^[0-9a-fA-F]{3}$|^[0-9a-fA-F]{6}$|^[0-9a-fA-F]{8}$/.test(m)) return null;
  if (m.length === 3) {
    return [parseInt(m[0] + m[0], 16), parseInt(m[1] + m[1], 16), parseInt(m[2] + m[2], 16), 1];
  }
  const r = parseInt(m.slice(0, 2), 16), g = parseInt(m.slice(2, 4), 16), b = parseInt(m.slice(4, 6), 16);
  const a = m.length === 8 ? parseInt(m.slice(6, 8), 16) / 255 : 1;
  return [r, g, b, a];
}

function toHex(r: number, g: number, b: number, a: number): string {
  const p = (n: number) => Math.round(n).toString(16).padStart(2, "0");
  const base = `#${p(r)}${p(g)}${p(b)}`;
  return a >= 1 ? base : base + p(a * 255);
}

function loadRecents(): string[] {
  try {
    const v = JSON.parse(storage.get(RECENT_KEY) || "[]");
    return Array.isArray(v) ? v.filter((x) => typeof x === "string").slice(0, RECENT_MAX) : [];
  } catch { return []; }
}

/**
 * Put `hex` at the head of the recent colours.
 *
 * Exported because the popover is not the only place a colour is CHOSEN:
 * the pipette picks one off the picture without the popover being open at
 * all, and a colour taken that way is exactly the kind the row exists to
 * keep — it is the one you cannot get back by remembering a number.
 * Whoever calls it owes the row the same rule the popover keeps: once per
 * act, with the colour that act ended on, never per intermediate step.
 */
export function recordRecentColor(hex: string) {
  try {
    const list = [hex, ...loadRecents().filter((c) => c.toLowerCase() !== hex.toLowerCase())];
    storage.set(RECENT_KEY, JSON.stringify(list.slice(0, RECENT_MAX)));
  } catch { /* ignore */ }
}

const CHECKER = "repeating-conic-gradient(#9a9aa2 0% 25%, #dcdce2 0% 50%) 0 / 10px 10px";

type Mode = "hex" | "rgb" | "hsl" | "hsv";

// ---- component ---------------------------------------------------------------

export function ColorPickerPopover({
  value,
  onPick,
  onClose,
  anchor,
}: {
  value: string;            // #rrggbb or #rrggbbaa
  onPick: (hex: string) => void;   // live, on every change
  onClose: () => void;             // commit: also records the recent color
  /** The swatch that opened it: a press on it is the caller's toggle, not
   *  a press outside. */
  anchor?: React.RefObject<HTMLElement | null>;
}) {
  // Keep HSV as the source of truth so the SV square doesn't jump when the
  // RGB round-trip is lossy (e.g. at s=0 every hue maps to the same grey).
  const init = parseHex(value) ?? [255, 255, 255, 1];
  const [hsv0] = useState(() => rgbToHsv(init[0], init[1], init[2]));
  const [h, setH] = useState(hsv0[0]);
  const [s, setS] = useState(hsv0[1]);
  const [v, setV] = useState(hsv0[2]);
  const [a, setA] = useState(init[3]);
  const [mode, setMode] = useState<Mode>("hex");
  const [recents, setRecents] = useState<string[]>(loadRecents);
  const [hexDraft, setHexDraft] = useState<string | null>(null);

  const [r, g, b] = useMemo(() => hsvToRgb(h, s, v), [h, s, v]);
  const hex = toHex(r, g, b, a);
  const hexRef = useRef(hex);
  hexRef.current = hex;

  const apply = (nh: number, ns: number, nv: number, na: number) => {
    setH(nh); setS(ns); setV(nv); setA(na);
    const [nr, ng, nb] = hsvToRgb(nh, ns, nv);
    onPick(toHex(nr, ng, nb, na));
  };

  // Record the final color once on close (Escape, outside click, ✕).
  const close = () => {
    recordRecentColor(hexRef.current);
    onClose();
  };
  // A press elsewhere closes it (recording the recent colour) — the one
  // rule, `useMenuDismiss`, which also takes Escape; the swatch that opened
  // it is the caller's and is named `within` so its own press is a toggle.
  const panel = useRef<HTMLDivElement>(null);
  useMenuDismiss(true, close, { within: [panel, ...(anchor ? [anchor] : [])] });

  // Shared drag handler for the SV square and the two sliders.
  const dragArea = (
    onAt: (fx: number, fy: number) => void,
  ) => (e: React.MouseEvent) => {
    e.preventDefault();
    const el = e.currentTarget as HTMLElement;
    const move = (ev: MouseEvent) => {
      const rct = el.getBoundingClientRect();
      onAt(
        Math.min(1, Math.max(0, (ev.clientX - rct.left) / rct.width)),
        Math.min(1, Math.max(0, (ev.clientY - rct.top) / rct.height)),
      );
    };
    move(e.nativeEvent);
    const up = () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };

  const [hl, sl, ll] = hsvToHsl(h, s, v);
  const numField = (val: number, max: number, set: (n: number) => void, label: string) => (
    <label key={label} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2, flex: 1 }}>
      <input
        value={Math.round(val)}
        onChange={(e) => {
          const n = Number(e.target.value);
          if (Number.isFinite(n)) set(Math.min(max, Math.max(0, n)));
        }}
        style={{ width: "100%", height: 24, borderRadius: "var(--r-2)", border: "1px solid var(--border-strong)", background: "var(--search-field-bg)", color: "var(--text)", fontSize: "var(--fs-2)", textAlign: "center", fontFamily: "var(--mono)" }}
      />
      <span style={{ fontSize: "var(--fs-0)", color: "var(--muted-2)", fontWeight: 700 }}>{label}</span>
    </label>
  );

  const alphaField = numField(a * 100, 100, (n) => apply(h, s, v, n / 100), "A%");

  return (
    <>
      <div
        ref={panel}
        onMouseDown={(e) => e.stopPropagation()}
        style={{
          position: "absolute", left: "calc(100% + 10px)", top: 0, zIndex: 31, width: 232,
          background: "var(--surface-float)", border: "1px solid var(--menu-border)",
          borderRadius: "var(--r-7)", boxShadow: "var(--shadow-2)", padding: 10,
          display: "flex", flexDirection: "column", gap: 8,
        }}
      >
        {/* SV square. Picking a color at 0% alpha would be invisible — moving
            the point restores full opacity so the pick always shows. */}
        <div
          onMouseDown={dragArea((fx, fy) => apply(h, fx * 100, (1 - fy) * 100, a === 0 ? 1 : a))}
          style={{
            position: "relative", height: 140, borderRadius: "var(--r-4)", cursor: "crosshair",
            background: `linear-gradient(to top, #000, rgba(0,0,0,0)), linear-gradient(to right, #fff, hsl(${h}, 100%, 50%))`,
          }}
        >
          <div style={{
            position: "absolute", left: `${s}%`, top: `${100 - v}%`, width: 12, height: 12,
            transform: "translate(-6px, -6px)", borderRadius: "50%",
            border: "2px solid #fff", boxShadow: "var(--ring-shadow)",
            background: toHex(r, g, b, 1),
          }} />
        </div>
        {/* Hue */}
        <div
          onMouseDown={dragArea((fx) => apply(fx * 360, s, v, a))}
          style={{
            position: "relative", height: 14, borderRadius: "var(--r-3)", cursor: "ew-resize",
            background: "linear-gradient(to right, #f00, #ff0, #0f0, #0ff, #00f, #f0f, #f00)",
          }}
        >
          <div style={{ position: "absolute", left: `${(h / 360) * 100}%`, top: -2, width: 6, height: 18, transform: "translateX(-3px)", borderRadius: 3, background: "#fff", boxShadow: "var(--ring-shadow)" }} />
        </div>
        {/* Alpha */}
        <div
          onMouseDown={dragArea((fx) => apply(h, s, v, Math.round(fx * 100) / 100))}
          style={{ position: "relative", height: 14, borderRadius: "var(--r-3)", cursor: "ew-resize", background: CHECKER, overflow: "hidden" }}
        >
          <div style={{ position: "absolute", inset: 0, background: `linear-gradient(to right, transparent, ${toHex(r, g, b, 1)})` }} />
          <div style={{ position: "absolute", left: `${a * 100}%`, top: -2, width: 6, height: 18, transform: "translateX(-3px)", borderRadius: 3, background: "#fff", boxShadow: "var(--ring-shadow)" }} />
        </div>
        {/* Mode + values */}
        <div style={{ display: "flex", alignItems: "flex-start", gap: 6 }}>
          <select
            value={mode}
            onChange={(e) => { setMode(e.target.value as Mode); setHexDraft(null); }}
            style={{ height: 24, borderRadius: "var(--r-2)", border: "1px solid var(--border-strong)", background: "var(--search-field-bg)", color: "var(--text-2)", fontSize: "var(--fs-2)" }}
          >
            <option value="hex">Hex</option>
            <option value="rgb">RGB</option>
            <option value="hsl">HSL</option>
            <option value="hsv">HSV</option>
          </select>
          <div style={{ flex: 1, display: "flex", gap: 4 }}>
            {mode === "hex" && (
              <label style={{ flex: 1, display: "flex", flexDirection: "column", gap: 2, alignItems: "center" }}>
                <input
                  value={hexDraft ?? hex}
                  onChange={(e) => {
                    setHexDraft(e.target.value);
                    const p = parseHex(e.target.value);
                    if (p) {
                      const [hh, ss, vv] = rgbToHsv(p[0], p[1], p[2]);
                      apply(hh, ss, vv, p[3]);
                    }
                  }}
                  onBlur={() => setHexDraft(null)}
                  spellCheck={false}
                  style={{ width: "100%", height: 24, borderRadius: "var(--r-2)", border: "1px solid var(--border-strong)", background: "var(--search-field-bg)", color: "var(--text)", fontSize: "var(--fs-2)", textAlign: "center", fontFamily: "var(--mono)" }}
                />
                <span style={{ fontSize: "var(--fs-0)", color: "var(--muted-2)", fontWeight: 700 }}>#RRGGBB(AA)</span>
              </label>
            )}
            {mode === "rgb" && (
              <>
                {numField(r, 255, (n) => { const [hh, ss, vv] = rgbToHsv(n, g, b); apply(hh, ss, vv, a); }, "R")}
                {numField(g, 255, (n) => { const [hh, ss, vv] = rgbToHsv(r, n, b); apply(hh, ss, vv, a); }, "G")}
                {numField(b, 255, (n) => { const [hh, ss, vv] = rgbToHsv(r, g, n); apply(hh, ss, vv, a); }, "B")}
                {alphaField}
              </>
            )}
            {mode === "hsl" && (
              <>
                {numField(hl, 360, (n) => { const [hh, ss, vv] = hslToHsv(n, sl, ll); apply(hh, ss, vv, a); }, "H")}
                {numField(sl, 100, (n) => { const [hh, ss, vv] = hslToHsv(hl, n, ll); apply(hh, ss, vv, a); }, "S")}
                {numField(ll, 100, (n) => { const [hh, ss, vv] = hslToHsv(hl, sl, n); apply(hh, ss, vv, a); }, "L")}
                {alphaField}
              </>
            )}
            {mode === "hsv" && (
              <>
                {numField(h, 360, (n) => apply(n, s, v, a), "H")}
                {numField(s, 100, (n) => apply(h, n, v, a), "S")}
                {numField(v, 100, (n) => apply(h, s, n, a), "V")}
                {alphaField}
              </>
            )}
          </div>
        </div>
        {/* Recent colors */}
        {recents.length > 0 && (
          <div>
            <SectionHeading sm style={{ marginBottom: 4 }}>Recent</SectionHeading>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {recents.map((c) => (
                <button
                  key={c}
                  title={c}
                  onClick={() => {
                    const p = parseHex(c);
                    if (!p) { setRecents(loadRecents()); return; }
                    const [hh, ss, vv] = rgbToHsv(p[0], p[1], p[2]);
                    apply(hh, ss, vv, p[3]);
                  }}
                  style={{ width: 20, height: 20, borderRadius: "var(--r-1)", border: "1px solid var(--border-strong)", padding: 0, cursor: "pointer", background: CHECKER, overflow: "hidden", position: "relative" }}
                >
                  <span style={{ position: "absolute", inset: 0, background: c }} />
                </button>
              ))}
            </div>
          </div>
        )}
        {/* Footer: live preview + done */}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ width: 26, height: 26, borderRadius: "var(--r-3)", border: "1px solid var(--border-strong)", background: CHECKER, overflow: "hidden", position: "relative" }}>
            <span style={{ position: "absolute", inset: 0, background: hex }} />
          </div>
          <span style={{ flex: 1, fontFamily: "var(--mono)", fontSize: "var(--fs-2)", color: "var(--muted)" }}>{hex}</span>
          <button
            onClick={close}
            style={{ height: 26, padding: "0 12px", borderRadius: "var(--r-3)", border: "none", background: "var(--accent)", color: "var(--on-accent)", fontSize: "var(--fs-2)", fontWeight: 600, cursor: "pointer", display: "flex", alignItems: "center", gap: 5 }}
          >
            <Icon name="check" size={14} />Done
          </button>
        </div>
      </div>
    </>
  );
}

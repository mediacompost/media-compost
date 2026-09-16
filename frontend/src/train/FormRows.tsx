// Form primitives for the training job editor: labeled rows in a bordered
// panel list (visually matching SettingsOverlay's PrefRow/ToggleRow, which are
// module-private there), each with an optional explanation line underneath.
import React, { useEffect, useRef, useState } from "react";
import { MenuRow } from "../shared/MenuRow";
import { Chip } from "../shared/Chip";
import { SectionHeading } from "../shared/SectionHeading";
import { IconButton } from "../shared/IconButton";
import { RowShell as SharedRowShell, Section as SharedSection } from "../shared/SettingsRows";
import { Select } from "../shared/Select";
import { Switch } from "../shared/Switch";
import { useMenuDismiss } from "../shared/useMenuDismiss";
import { Icon } from "../shared/Icon";
import { useT } from "./i18n";
import { AnchoredDropdown, useAnchorRect } from "../shared/AnchoredDropdown";
import { HelpMark } from "../shared/HelpMark";

/** A titled card of rows. The title is OPTIONAL: a page whose only section
 *  would repeat the page's own name in the nav says it twice, so those omit it
 *  and lead with the hint instead (the same rule the properties panel uses for
 *  a single-section tab). */
/** The shared section, with this form's spacing under it. */
export function Section({ label, hint, bare, children }: {
  label?: string; hint?: string;
  /** No panel around the children — for a section whose content brings its
   *  own boxes (the dataset queries), where the panel would be a border
   *  drawn around a stack of borders. */
  bare?: boolean;
  children: React.ReactNode;
}) {
  return (
    <SharedSection title={label} hint={hint} bare={bare} style={{ marginBottom: 22 }}>
      {children}
    </SharedSection>
  );
}

/** A SENTENCE inside a settings card — a warning, or what the choice above
 *  means. It is not a row (there is nothing to set), but it lives among rows,
 *  so it takes their inset and their dividing line: written as a bare div it
 *  ran to the card's edge while every label beside it was 16 px in. */
export function NoteRow({ tone = "muted", last, children }: {
  tone?: "muted" | "warn";
  last?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="mc-copy" style={{
      padding: "10px 16px",
      borderBottom: last ? "none" : "1px solid var(--border-soft)",
      fontSize: "var(--fs-2)", lineHeight: 1.5,
      color: tone === "warn" ? "var(--yellow-text)" : "var(--muted-2)",
    }}>
      {children}
    </div>
  );
}

export function RowShell({ label, hint, details, last, unsupported, children }: {
  label: string; hint?: string; details?: string; last?: boolean;
  /** Why what this row is SET TO can't run here ("needs an NVIDIA GPU").
   *  The chip says only "Unsupported" and the reason is its title: the chips
   *  used to carry the reason itself, which made one row say "NVIDIA only"
   *  and the next "LoRA only" for the same kind of fact, in two different
   *  vocabularies, at 9.5 px. The trainer enforces all of them anyway — but
   *  minutes into a run, which is what this is for. */
  unsupported?: string;
  children: React.ReactNode;
}) {
  const t = useT();
  // The shared row, with what is this form's own beside the label: the `?`
  // (`details` is the long-form explanation, a popover from that mark so
  // the form stays one scannable column) and the Unsupported chip.
  return (
    <SharedRowShell label={label} hint={hint} last={last}
      extra={<>
        {details && <HelpMark heading={label} text={details}
                              tooltip={t("What does this do?")} />}
        {unsupported && (
          <Chip tone="warn" size="sm" round bordered title={unsupported}>
            {t("Unsupported")}
          </Chip>
        )}
      </>}>
      {children}
    </SharedRowShell>
  );
}

export const inputStyle: React.CSSProperties = {
  height: 32, padding: "0 10px", background: "var(--bg)",
  border: "1px solid var(--border-strong)", borderRadius: "var(--r-4)",
  color: "var(--text)", fontSize: "var(--fs-3)", fontFamily: "inherit", outline: "none",
};

export function SelectRow({ label, hint, details, value, onChange, options, groups, last, disabled, unsupported, cannot }: {
  label: string; hint?: string; details?: string; value: string;
  onChange: (v: string) => void;
  options?: readonly (readonly [string, string])[];
  /** Headed sections, for a list long enough that a flat one is a scroll.
   *  Given instead of `options`; a group with an empty heading renders its
   *  entries bare, so a list that is only partly grouped still reads. */
  groups?: readonly (readonly [string, readonly (readonly [string, string])[]])[];
  last?: boolean; disabled?: boolean; unsupported?: string;
  /** Option value → why this machine cannot run it. Those entries stay in the
   *  list, disabled, with the reason after their label: a list that DROPS them
   *  cannot say the machine is what is missing, and somebody comparing this
   *  editor with a guide written elsewhere would be looking for a setting that
   *  appears not to exist. A value already stored (a job configured on another
   *  machine) still shows as the selection, which is why the entry has to be
   *  rendered at all. */
  cannot?: Record<string, string>;
}) {
  const opt = ([v, lbl]: readonly [string, string]) => {
    const why = cannot?.[v];
    return (
      <option key={v} value={v} disabled={!!why} title={why}>
        {why ? `${lbl} — ${why}` : lbl}
      </option>
    );
  };
  return (
    <RowShell label={label} hint={hint} details={details} last={last}
              unsupported={unsupported ?? cannot?.[value]}>
      <Select value={value} disabled={disabled} onChange={onChange} minWidth={170}>
        {groups
          ? groups.map(([heading, entries]) => (
            heading
              ? <optgroup key={heading} label={heading}>
                  {entries.map(opt)}
                </optgroup>
              : entries.map(opt)
          ))
          : (options ?? []).map(opt)}
      </Select>
    </RowShell>
  );
}

export function ToggleRow({ label, hint, details, checked, onChange, last, disabled, unsupported }: {
  label: string; hint?: string; details?: string; checked: boolean;
  onChange: (v: boolean) => void; last?: boolean; disabled?: boolean;
  unsupported?: string;
}) {
  return (
    <RowShell label={label} hint={hint} details={details} last={last}
              unsupported={unsupported}>
      <Switch checked={checked} onChange={onChange} disabled={disabled} title={label} />
    </RowShell>
  );
}

/** The up/down pair beside a numeric field, styled like a system stepper: one
 *  bordered, field-height capsule split by a hairline rather than two loose
 *  arrows. Held down, it repeats (long press → accelerating auto-repeat). */
function Stepper({ onBump, disabled }: { onBump: (dir: 1 | -1) => void; disabled?: boolean }) {
  const [hover, setHover] = useState<1 | -1 | 0>(0);
  const timers = useRef<number[]>([]);
  // Each bump reads the field's current text, so a repeat must call the LATEST
  // callback — the one captured when the press started is a step behind.
  const cb = useRef(onBump);
  cb.current = onBump;
  const stop = () => { timers.current.forEach(clearTimeout); timers.current = []; };
  useEffect(() => stop, []);
  const hold = (dir: 1 | -1) => {
    cb.current(dir);
    let delay = 400;
    const tick = () => {
      cb.current(dir);
      delay = Math.max(40, delay * 0.75);
      timers.current.push(window.setTimeout(tick, delay));
    };
    timers.current.push(window.setTimeout(tick, delay));
  };
  const half = (dir: 1 | -1) => (
    <button
      onMouseDown={(e) => { e.preventDefault(); if (!disabled) hold(dir); }}
      onMouseUp={stop}
      onMouseLeave={() => { stop(); setHover(0); }}
      onMouseEnter={() => setHover(dir)}
      disabled={disabled}
      tabIndex={-1}
      title={dir > 0 ? "Increase" : "Decrease"}
      style={{
        display: "flex", alignItems: "center", justifyContent: "center",
        width: 20, height: 15, padding: 0, border: "none",
        borderTop: dir > 0 ? "none" : "1px solid var(--border-strong)",
        background: hover === dir && !disabled ? "var(--surface-float)" : "transparent",
        color: hover === dir && !disabled ? "var(--text-2)" : "var(--muted-2)",
        cursor: disabled ? "default" : "pointer",
      }}
    >
      <Icon name={dir > 0 ? "arrow_drop_up" : "arrow_drop_down"} size={16} />
    </button>
  );
  return (
    <div style={{
      display: "flex", flexDirection: "column", overflow: "hidden",
      height: 32, background: "var(--panel-3)",
      border: "1px solid var(--border-strong)", borderRadius: "var(--r-3)",
      opacity: disabled ? 0.5 : 1,
    }}>
      {half(1)}
      {half(-1)}
    </div>
  );
}

/** Numeric input that commits parsed values and re-syncs on blur.
 *  With `placeholder`, the field is shown EMPTY whenever the value equals
 *  `emptyValue` (default 0) and clearing it commits that value back — so
 *  "automatic"/"no limit" defaults read as placeholder text instead of a 0. */
export function NumRow({ label, hint, details, value, onChange, last, min, max, step, disabled, suffix, placeholder, emptyValue = 0 }: {
  label: string; hint?: string; details?: string; value: number;
  onChange: (v: number) => void; last?: boolean;
  min?: number; max?: number; step?: number; disabled?: boolean;
  suffix?: string; placeholder?: string; emptyValue?: number;
}) {
  const shown = (v: number) => (placeholder !== undefined && v === emptyValue ? "" : String(v));
  const [text, setText] = useState(shown(value));
  useEffect(() => { setText(shown(value)); }, [value]);
  const commit = () => {
    if (placeholder !== undefined && text.trim() === "") {
      setText("");
      if (value !== emptyValue) onChange(emptyValue);
      return;
    }
    const v = Number(text.replace(",", "."));
    if (!isFinite(v)) { setText(shown(value)); return; }
    let out = v;
    if (min !== undefined) out = Math.max(min, out);
    if (max !== undefined) out = Math.min(max, out);
    if (step === 1) out = Math.round(out);
    setText(shown(out));
    if (out !== value) onChange(out);
  };
  // Steppers appear whenever a `step` is given — for fields where nudging is
  // meaningful (counts, ranks, ratios) but not for free-form values like a
  // learning rate, where a fixed increment makes no sense.
  const bump = (dir: 1 | -1) => {
    if (disabled || step === undefined) return;
    const base = placeholder !== undefined && text.trim() === "" ? emptyValue : Number(text.replace(",", "."));
    const cur = isFinite(base) ? base : value;
    let out = cur + dir * step;
    if (min !== undefined) out = Math.max(min, out);
    if (max !== undefined) out = Math.min(max, out);
    // Kill float drift from repeated 0.05-style steps.
    out = Math.round(out * 1e6) / 1e6;
    setText(shown(out));
    if (out !== value) onChange(out);
  };
  return (
    <RowShell label={label} hint={hint} details={details} last={last}>
      <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <input
            value={text}
            placeholder={placeholder}
            inputMode="decimal"
            disabled={disabled}
            onChange={(e) => setText(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === "Enter") (e.target as HTMLInputElement).blur();
              else if (step !== undefined && e.key === "ArrowUp") { e.preventDefault(); bump(1); }
              else if (step !== undefined && e.key === "ArrowDown") { e.preventDefault(); bump(-1); }
            }}
            style={{ ...inputStyle, width: step === undefined ? 96 : 74, textAlign: "right", opacity: disabled ? 0.5 : 1 }}
          />
          {step !== undefined && <Stepper onBump={bump} disabled={disabled} />}
        </div>
        {suffix && <span style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>{suffix}</span>}
      </div>
    </RowShell>
  );
}

/** Two stepped numbers multiplied together — "N × M", with the product spelled
 *  out beside them.
 *
 *  It exists for batches × batch size, where the two used to be separate rows
 *  ("Images", then "Batch size" capped by it) and the relationship between
 *  them had to be inferred. A batch is what the GPU actually does in one go,
 *  so it is the unit worth asking for; the total is then a consequence, and
 *  showing it is cheaper than making the user multiply. */
export function ProductRow({ label, hint, details, last, a, b, aMax, bMax,
                            aLabel, bLabel, total, onChange }: {
  label: string; hint?: string; details?: string; last?: boolean;
  a: number; b: number; aMax: number; bMax: number;
  /** Named under each field, since "3 × 2" alone doesn't say which is which. */
  aLabel: string; bLabel: string;
  /** Rendered to the right, e.g. "= 6 images". */
  total: string;
  onChange: (a: number, b: number) => void;
}) {
  const field = (val: number, max: number, sub: string, isA: boolean) => (
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
        <input
          key={`${isA ? "a" : "b"}${val}`}
          defaultValue={String(val)}
          inputMode="numeric"
          onBlur={(e) => {
            const v = Math.round(Number(e.target.value));
            const out = isFinite(v) ? Math.min(max, Math.max(1, v)) : val;
            e.target.value = String(out);
            if (out !== val) onChange(isA ? out : a, isA ? b : out);
          }}
          onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
          style={{ ...inputStyle, width: 56, textAlign: "right" }}
        />
        <Stepper onBump={(dir) => {
          const out = Math.min(max, Math.max(1, val + dir));
          if (out !== val) onChange(isA ? out : a, isA ? b : out);
        }} />
      </div>
      <span style={{ fontSize: "var(--fs-1)", color: "var(--muted-3)", textAlign: "center" }}>
        {sub}
      </span>
    </div>
  );
  return (
    <RowShell label={label} hint={hint} details={details} last={last}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 7 }}>
        {field(a, aMax, aLabel, true)}
        <span style={{ color: "var(--muted-2)", fontSize: "var(--fs-2)", paddingTop: 7 }}>×</span>
        {field(b, bMax, bLabel, false)}
        <span style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", paddingTop: 7 }}>
          {total}
        </span>
      </div>
    </RowShell>
  );
}

/** One row holding a closed RANGE — two number fields with an en dash between.
 *
 *  Every ranged parameter is this one row type rather than each method
 *  inventing its own pair of fields, and typing the same value into both ends
 *  is how a range becomes a fixed value: there is no separate mode to find.
 *  The ends are not sorted here — the backend does that on save, so typing the
 *  bigger number first does not fight the cursor halfway through.
 */
export function RangeRow({ label, hint, details, lo, hi, min, max, step,
                          decimals = 0, onChange, last, unsupported }: {
  label: string; hint?: string; details?: string;
  lo: number; hi: number;
  min: number; max: number; step?: number; decimals?: number;
  onChange: (lo: number, hi: number) => void;
  last?: boolean; unsupported?: string;
}) {
  const show = (v: number) => (decimals ? v.toFixed(decimals) : String(v));
  const commit = (raw: string, other: number, isLo: boolean) => {
    const v = Number(raw);
    if (!isFinite(v)) return;
    const c = Math.min(max, Math.max(min, decimals ? v : Math.round(v)));
    onChange(isLo ? c : other, isLo ? other : c);
  };
  const field = (val: number, other: number, isLo: boolean) => (
    <input
      key={`${isLo ? "lo" : "hi"}${val}`}
      defaultValue={show(val)}
      inputMode="decimal"
      step={step}
      onBlur={(e) => commit(e.target.value, other, isLo)}
      onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
      style={{ ...inputStyle, width: 66, textAlign: "right" }}
    />
  );
  return (
    <RowShell label={label} hint={hint} details={details} last={last}
              unsupported={unsupported}>
      <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
        {field(lo, hi, true)}
        <span style={{ color: "var(--muted-2)", fontSize: "var(--fs-2)" }}>–</span>
        {field(hi, lo, false)}
      </div>
    </RowShell>
  );
}

// Grouped size presets for width/height fields: the standard SDXL bucket list
// (constant ~1MP area) and the common SD 1.5 sizes.
export const SIZE_PRESETS: [string, [number, number][]][] = [
  ["1024 px (SDXL, Chroma, FLUX.2)", [
    [1024, 1024], [1152, 896], [896, 1152], [1216, 832], [832, 1216],
    [1344, 768], [768, 1344], [1536, 640], [640, 1536],
  ]],
  ["SD 1.5 (512)", [
    [512, 512], [768, 512], [512, 768], [640, 512], [512, 640], [768, 768],
  ]],
];

/** One row with width × height inputs and an icon button opening a grouped
 *  preset menu. `placeholder` (e.g. the model's native size) lets both fields
 *  be left empty, which commits 0 = "use the default". */
export function SizeRow({ label, width, height, onChange, placeholder, hint, details, last }: {
  label: string;
  width: number; height: number;
  onChange: (w: number, h: number) => void;
  placeholder?: string; hint?: string; details?: string; last?: boolean;
}) {
  // The menu is portaled to <body>: the surrounding Section clips its children
  // (rounded corners) and the page scrolls, so an in-flow popup gets cut off.
  const t = useT();
  const [open, setOpen] = useState(false);
  const sizeAnchor = useRef<HTMLButtonElement>(null);
  const sizeRect = useAnchorRect(sizeAnchor, open);
  // A press elsewhere, Escape, and a scroll of the page close it — the one
  // rule (`useMenuDismiss`), in place of a click-catcher behind the panel.
  useMenuDismiss(open, () => setOpen(false), { within: [sizeAnchor] });
  const num = (v: number) => (placeholder !== undefined && v === 0 ? "" : String(v));
  const commit = (raw: string, other: number, isWidth: boolean) => {
    if (placeholder !== undefined && raw.trim() === "") {
      onChange(isWidth ? 0 : other, isWidth ? other : 0);
      return;
    }
    const v = Math.round(Number(raw));
    if (!isFinite(v) || v < 64 || v > 4096) return;
    onChange(isWidth ? v : other, isWidth ? other : v);
  };
  const field = (val: number, isWidth: boolean) => (
    <input
      key={`${isWidth ? "w" : "h"}${val}`}
      defaultValue={num(val)}
      placeholder={placeholder}
      inputMode="numeric"
      onBlur={(e) => commit(e.target.value, isWidth ? height : width, isWidth)}
      onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
      style={{ ...inputStyle, width: 66, textAlign: "right" }}
    />
  );
  return (
    <RowShell label={label} hint={hint} details={details} last={last}>
      <div style={{ display: "flex", alignItems: "center", gap: 7, position: "relative" }}>
        {field(width, true)}
        <span style={{ color: "var(--muted-2)", fontSize: "var(--fs-2)" }}>×</span>
        {field(height, false)}
        <button ref={sizeAnchor}
          title={t("Size presets")}
          onClick={() => setOpen((v) => !v)}
          style={{
            ...inputStyle, width: 34, padding: 0, cursor: "pointer",
            display: "flex", alignItems: "center", justifyContent: "center",
            background: open ? "var(--accent-dim)" : "var(--bg)",
            color: open ? "var(--accent)" : "var(--muted)",
          }}
        >
          <Icon name="aspect_ratio" size={17} />
        </button>
        {open && (
            <AnchoredDropdown rect={sizeRect} minWidth={200}>
              {SIZE_PRESETS.map(([group, sizes]) => (
                <div key={group}>
                  <SectionHeading sm style={{ padding: "6px 9px 3px" }}>
                    {group}
                  </SectionHeading>
                  {sizes.map(([w, h]) => (
                    <MenuRow active={w === width && h === height}
                      key={`${w}x${h}`}
                      onClick={() => { setOpen(false); onChange(w, h); }}>
                      {/* Tiny aspect proxy so the shape is readable at a glance. */}
                      <span style={{
                        flex: "0 0 auto", width: 18, height: 18, display: "flex",
                        alignItems: "center", justifyContent: "center",
                      }}>
                        <span style={{
                          width: w >= h ? 16 : Math.max(6, Math.round(16 * w / h)),
                          height: h >= w ? 16 : Math.max(6, Math.round(16 * h / w)),
                          border: "1.5px solid var(--muted-2)", borderRadius: 2,
                        }} />
                      </span>
                      <span style={{ fontFamily: "var(--mono)" }}>{w} × {h}</span>
                    </MenuRow>
                  ))}
                </div>
              ))}
            </AnchoredDropdown>
          
)}
      </div>
    </RowShell>
  );
}

export function TextRow({ label, hint, details, value, onChange, last,
                         placeholder, wide, suggest }: {
  label: string; hint?: string; details?: string; value: string;
  onChange: (v: string) => void; last?: boolean; placeholder?: string;
  wide?: boolean;
  /** Terms this field commonly holds, offered as chips under it and TOGGLED
   *  — the field stays free text, because the value is a substring and the
   *  suggestions can only ever be the common ones. Comma-separated, which is
   *  what every field that passes this holds. */
  suggest?: string[];
}) {
  const [text, setText] = useState(value);
  useEffect(() => { setText(value); }, [value]);
  const terms = splitTerms(text);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement | null>(null);
  const rect = useAnchorRect(box, open);
  useMenuDismiss(open, () => setOpen(false), { within: [box] });
  const toggle = (term: string) => {
    const next = terms.includes(term)
      ? terms.filter((x) => x !== term) : [...terms, term];
    const joined = next.join(", ");
    setText(joined);
    onChange(joined);
  };
  const w = wide ? 340 : 200;
  return (
    <RowShell label={label} hint={hint} details={details} last={last}>
      {/* A CHEVRON ON THE FIELD, NOT CHIPS UNDER IT. The offered terms were a
          row of toggles below the input, which is a second place the value is
          shown and the taller of the two — on the adapter's two layer fields
          that is a dozen module names standing open under a field most runs
          leave empty. Behind the chevron they are a list you go to, and the
          TICK says the same thing the lit chip said: this term is in the
          field. The field stays free text either way, because what it holds
          is a SUBSTRING of a module path and the list can only ever be the
          common ones. */}
      <div ref={box} style={{ position: "relative", width: w }}>
        <input
          value={text}
          placeholder={placeholder}
          onChange={(e) => setText(e.target.value)}
          onBlur={() => { if (text !== value) onChange(text); }}
          onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
          style={{
            ...inputStyle, width: "100%",
            // Room for the chevron, so a long value runs under nothing.
            ...(suggest?.length ? { paddingRight: 26 } : null),
          }}
        />
        {!!suggest?.length && (
          <IconButton icon="expand_more" size={20} glyph={16} color={open ? "var(--accent)" : "var(--muted-2)"}
            onClick={() => setOpen((o) => !o)}
            title={label} style={{ position: "absolute", right: 4, top: "50%", transform: "translateY(-50%)" }} />
        )}
      </div>
      {open && !!suggest?.length && (
        <>
          <AnchoredDropdown rect={rect} minWidth={w}>
            {suggest.map((term) => {
              const on = terms.includes(term);
              return (
                <div key={term} onClick={() => toggle(term)}
                  style={{
                    display: "flex", alignItems: "center", gap: 6,
                    padding: "4px 7px", borderRadius: "var(--r-2)", cursor: "pointer",
                    fontFamily: "var(--mono)", fontSize: "var(--fs-2)",
                    color: on ? "var(--text)" : "var(--muted)",
                    background: on ? "var(--accent-dim)" : "transparent",
                  }}>
                  {/* The tick's gutter stays whether or not it is drawn, or
                      every unticked name steps sideways as the list is used. */}
                  <span style={{ width: 14, display: "flex", flex: "0 0 auto",
                                 color: "var(--accent)" }}>
                    {on && <Icon name="check" size={14} />}
                  </span>
                  {term}
                </div>
              );
            })}
          </AnchoredDropdown>
        </>
      )}
    </RowShell>
  );
}

/** A comma-separated field's terms, trimmed and without the empties — the
 *  same split `splitTags` does for the value that is sent. */
function splitTerms(text: string): string[] {
  return text.split(",").map((s) => s.trim()).filter(Boolean);
}


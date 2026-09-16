// A prompt textarea (form-row style) with library-tag autocomplete on the
// token at the caret (comma- or newline-separated). The suggestion list is
// the same tag catalog the Tags tab shows (non-alias tags with their item
// counts), matched underscore/space-insensitively (prompts write tags with
// spaces), and the popup opens at the caret position. Used by the Evaluate
// tab and the training job's sampling prompts.
import React, { useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { Icon } from "../shared/Icon";
import { inputStyle } from "./FormRows";
import { LAYER } from "../shared/layers";

interface TokenAt { start: number; end: number; q: string }

function tokenAt(text: string, caret: number): TokenAt {
  // Tokens are separated by commas or newlines (prompt syntax).
  let start = caret;
  while (start > 0 && !",\n".includes(text[start - 1])) start--;
  let end = caret;
  while (end < text.length && !",\n".includes(text[end])) end++;
  return { start, end, q: text.slice(start, caret).trim() };
}

// Tags are stored booru-style (red_fox) but typed into prompts with spaces —
// compare both sides with underscores flattened.
const norm = (s: string) => s.toLowerCase().replace(/_/g, " ");

/** Pixel position of a caret index inside a textarea, via a hidden mirror
 *  element that replicates the textarea's text layout up to the caret. */
function caretPixelPos(
  ta: HTMLTextAreaElement, index: number
): { left: number; top: number; lineH: number } {
  const style = window.getComputedStyle(ta);
  const div = document.createElement("div");
  for (const prop of [
    "fontFamily", "fontSize", "fontWeight", "letterSpacing", "lineHeight",
    "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
    "borderTopWidth", "borderRightWidth", "borderBottomWidth",
    "borderLeftWidth", "boxSizing",
  ] as const) {
    div.style[prop] = style[prop];
  }
  div.style.position = "absolute";
  div.style.visibility = "hidden";
  div.style.whiteSpace = "pre-wrap";
  div.style.wordWrap = "break-word";
  div.style.width = `${ta.clientWidth}px`;
  div.textContent = ta.value.slice(0, index);
  const marker = document.createElement("span");
  marker.textContent = ta.value.slice(index, index + 1) || ".";
  div.appendChild(marker);
  document.body.appendChild(div);
  const lineH = parseFloat(style.lineHeight) || 18;
  const pos = {
    left: marker.offsetLeft,
    top: marker.offsetTop + lineH - ta.scrollTop,   // the caret LINE's bottom
    lineH,
  };
  document.body.removeChild(div);
  return pos;
}

const POPUP_W = 240;

export function PromptArea({ label, hint, value, onChange, placeholder, rows, last, icon, bare }: {
  label: string;
  hint?: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  rows?: number;
  last?: boolean;
  // Compact variant used by the test-sample prompt list: `bare` drops the
  // label/padding wrapper and `icon` sits inside the field (the + / ⊘ glyph is
  // what tells a prompt from its negative — the fields themselves stay plain,
  // so a long list of them does not read as a wall of red and green).
  icon?: string;
  bare?: boolean;
}) {
  const [text, setText] = useState(value);
  const [open, setOpen] = useState(false);
  // WHETHER THIS FIELD HAS THE KEYBOARD, which is what makes the arrow keys
  // and Enter reliable. They are handled on the textarea, so a suggestion list
  // on screen while focus is somewhere else is a list nothing can drive — and
  // there are two of these fields per prompt row (the prompt and its negative)
  // plus one popup portalled to <body> per field, so the list you are looking
  // at was not necessarily the one your keys reach. Closing on blur alone was
  // not enough: it is DELAYED by 150 ms so a click on a suggestion lands
  // first, and in that window the list belongs to the field you have just
  // left.
  const [focused, setFocused] = useState(false);
  // …and the delayed close has to be cancellable, or coming straight back to
  // the field (a click out and back, Tab away and Tab in) lets a timer armed
  // by the old blur close the list the new typing has just reopened.
  const closeTimer = useRef<number | null>(null);
  const [index, setIndex] = useState(0);
  const [caret, setCaret] = useState(0);
  // Viewport coordinates: the popup is portaled to <body> and fixed, because
  // every ancestor here clips it — the field wrapper, the Section's rounded
  // box, the scrolling page.
  const [popupPos, setPopupPos] = useState<{ left: number; top: number; lineH: number }>({
    left: 0, top: 0, lineH: 18,
  });
  const ref = useRef<HTMLTextAreaElement | null>(null);
  React.useEffect(() => { setText(value); }, [value]);

  const { data: tags } = useQuery({ queryKey: ["tags"], queryFn: api.tags });
  const catalog = useMemo(
    () => (tags ?? []).filter((t) => !t.alias_of)
      .map((t) => ({ name: t.name, count: t.numbers?.positive ?? 0 }))
      .sort((a, b) => b.count - a.count),
    [tags]
  );

  const token = useMemo(() => tokenAt(text, caret), [text, caret]);
  const items = useMemo(() => {
    const q = norm(token.q);
    if (q.length < 2) return [];
    return catalog.filter((t) => norm(t.name).includes(q)).slice(0, 8);
  }, [token, catalog]);
  const show = open && focused && items.length > 0;
  // Row height + the 1px borders; used to decide whether the list fits below
  // the caret and, when it doesn't, how far to lift it.
  const popupHeight = items.length * 27 + 2;
  const flipUp = popupPos.top + popupHeight + 12 > window.innerHeight;

  // A fixed popup no longer moves with the field when an ancestor scrolls (the
  // training editor's prompt list lives in a scrolling overlay), so follow the
  // caret instead of letting the popup drift away from it.
  React.useEffect(() => {
    if (!show) return;
    const follow = () => { const el = ref.current; if (el) trackCaret(el); };
    window.addEventListener("scroll", follow, true);
    window.addEventListener("resize", follow);
    return () => {
      window.removeEventListener("scroll", follow, true);
      window.removeEventListener("resize", follow);
    };
  }, [show]);

  const commitText = () => { if (text !== value) onChange(text); };

  const trackCaret = (el: HTMLTextAreaElement) => {
    const pos = el.selectionStart ?? 0;
    setCaret(pos);
    const at = caretPixelPos(el, pos);
    const r = el.getBoundingClientRect();
    // Keep the popup beside the caret but inside the window, and clamp the
    // vertical anchor to the field so a scrolled-away caret can't drag it off.
    setPopupPos({
      left: Math.max(8, Math.min(r.left + at.left,
                                 window.innerWidth - POPUP_W - 8)),
      top: r.top + Math.max(0, Math.min(at.top, r.height)),
      lineH: at.lineH,
    });
  };

  const pick = (name: string) => {
    // Inserted the way prompts are written: underscores spelled out as
    // spaces, followed by the comma+space separator.
    const insert = name.replace(/_/g, " ") + ", ";
    // Preserve one leading space after a comma separator.
    const lead = text.slice(token.start, token.end).match(/^\s*/)?.[0] ?? "";
    // Swallow an existing following comma so picking mid-prompt doesn't
    // double the separator — but never a newline (prompts are line-separated).
    const rest = text.slice(token.end).replace(/^[ \t]*,?[ \t]*/, "");
    const next = text.slice(0, token.start) + lead + insert + rest;
    const pos = token.start + lead.length + insert.length;
    setText(next);
    setOpen(false);
    requestAnimationFrame(() => {
      const el = ref.current;
      if (el) { el.focus(); el.setSelectionRange(pos, pos); setCaret(pos); }
    });
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!show) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setIndex((i) => Math.min(i + 1, items.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setIndex((i) => Math.max(i - 1, 0)); }
    else if (e.key === "Enter" || e.key === "Return" || e.key === "Tab") { e.preventDefault(); pick(items[Math.min(index, items.length - 1)].name); }
    else if (e.key === "Escape") { e.preventDefault(); setOpen(false); }
  };

  return (
    <div style={bare ? { position: "relative" } : {
      padding: "10px 16px",
      borderBottom: last ? "none" : "1px solid var(--border-soft)",
    }}>
      {!bare && <div style={{ fontSize: "var(--fs-3)", color: "var(--text-2)", marginBottom: 6 }}>{label}</div>}
      {hint && !bare && (
        <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", marginBottom: 6 }}>{hint}</div>
      )}
      <div style={{ position: "relative" }}>
        {icon && (
          <Icon
            name={icon} size={15} color="var(--muted-2)"
            style={{ position: "absolute", left: 8, top: 8, pointerEvents: "none" }}
          />
        )}
        <textarea
          ref={ref}
          value={text}
          placeholder={placeholder}
          rows={rows ?? 3}
          onChange={(e) => {
            setText(e.target.value);
            trackCaret(e.target);
            setOpen(true);
            setIndex(0);
          }}
          onKeyDown={onKeyDown}
          onKeyUp={(e) => trackCaret(e.target as HTMLTextAreaElement)}
          onClick={(e) => trackCaret(e.target as HTMLTextAreaElement)}
          onScroll={(e) => trackCaret(e.target as HTMLTextAreaElement)}
          onFocus={(e) => {
            if (closeTimer.current != null) {
              clearTimeout(closeTimer.current);
              closeTimer.current = null;
            }
            setFocused(true);
            trackCaret(e.target);
          }}
          onBlur={() => {
            setFocused(false);
            // Delay so a click on a suggestion lands before the popup closes.
            closeTimer.current = window.setTimeout(() => {
              closeTimer.current = null;
              setOpen(false);
            }, 150);
            commitText();
          }}
          spellCheck={false}
          style={{
            ...inputStyle, width: "100%", boxSizing: "border-box",
            height: "auto", padding: icon ? "7px 10px 7px 28px" : "8px 10px",
            resize: "vertical", lineHeight: 1.45,
          }}
        />
        {show && createPortal(
          <div style={{
            position: "fixed", zIndex: LAYER.popover, width: POPUP_W,
            left: popupPos.left,
            // Below the caret's line, or above it (clearing the line itself)
            // when the window has no room underneath.
            top: popupPos.top + 2 + (flipUp ? -(popupHeight + popupPos.lineH + 4) : 0),
            background: "var(--surface-float)",
            border: "1px solid var(--menu-border)", borderRadius: "var(--r-5)",
            overflow: "hidden", boxShadow: "var(--shadow-2)",
          }}>
            {items.map((t, i) => (
              <div
                key={t.name}
                onMouseDown={(e) => { e.preventDefault(); pick(t.name); }}
                onMouseEnter={() => setIndex(i)}
                style={{
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "6px 11px", fontSize: "var(--fs-3)", cursor: "pointer",
                  background: i === index ? "var(--border)" : "transparent",
                  color: "var(--text)",
                }}
              >
                <span style={{
                  flex: 1, minWidth: 0, whiteSpace: "nowrap",
                  overflow: "hidden", textOverflow: "ellipsis",
                }}>
                  {t.name}
                </span>
                <span style={{
                  fontSize: "var(--fs-1)", color: "var(--muted)",
                  fontVariantNumeric: "tabular-nums", flex: "0 0 auto",
                }}>
                  {t.count}
                </span>
              </div>
            ))}
          </div>,
          document.body,
        )}
      </div>
    </div>
  );
}

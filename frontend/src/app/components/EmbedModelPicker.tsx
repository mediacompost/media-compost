/** WHICH EMBEDDER, with the one line that actually decides it.
 *
 * The choice is between kinds of likeness — DINOv2 groups by how a picture
 * LOOKS (style, linework, composition) and CLIP by what it DEPICTS — and a
 * model name says none of that. A native `<select>` cannot carry a second
 * line, so the strength was crammed onto the option after a dash, where it
 * is the least readable part of the longest row in the dialog.
 *
 * ONE component, because two dialogs offer the choice (the import overlay's
 * index option and the Tag batch chooser) and two hand-written menus would
 * drift — which is the same reason `embedModels.ts` holds the lines.
 *
 * Shown even when there is only ONE model: with one option the menu is a
 * formality, but the SUBTITLE is the thing worth reading, and hiding it left
 * the Tag batch chooser saying nothing at all about what it was about to
 * index with.
 *
 * `multi` is the IMPORT overlay's mode. Indexing is not choosing — the two
 * spaces are indexed independently and never mixed, so an import can
 * perfectly well fill both and the picture is only encoded once per space
 * either way. A SESSION still picks one: it scores in the space it is
 * handed. So the menu toggles rather than replaces there, stays open across
 * a tick (picking two is two clicks), and refuses to empty itself — the row
 * above it is the on/off switch, and "on, with nothing" is a state it has no
 * way to show.
 */
import React, { useEffect, useRef, useState } from "react";

import { AnchoredDropdown, useAnchorRect } from "../../shared/AnchoredDropdown";
import { Icon } from "../../shared/Icon";
import { EMBED_STRENGTHS } from "../embedModels";
import { useMenuDismiss } from "../../shared/useMenuDismiss";

export interface EmbedModelOption {
  id: string;
  name: string;
  family?: string;
}

/** The ids in a picker value. ONE spelling of the split, mirrored by
 *  `imports.embedder_ids` on the server: the value is comma-separated all the
 *  way from this menu through the remembered options to the form field, so
 *  nothing in between has to convert it, and a bare id — what every caller
 *  wrote before multi-selection — is the one-element list it always was. */
export function embedderIds(value: string): string[] {
  const out: string[] = [];
  for (const p of (value ?? "").split(",")) {
    const id = p.trim();
    if (id && !out.includes(id)) out.push(id);
  }
  return out;
}

export function EmbedModelPicker({ models, value, onChange, t, multi }: {
  models: EmbedModelOption[];
  /** The chosen id, or — with `multi` — the chosen ids comma-separated. */
  value: string;
  onChange: (id: string) => void;
  t: (s: string) => string;
  multi?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const rect = useAnchorRect(ref, open);
  useMenuDismiss(open, () => setOpen(false), { within: [ref] });
  if (models.length === 0) return null;
  const chosen = embedderIds(value).filter((id) => models.some((m) => m.id === id));
  const picked = models.find((m) => m.id === chosen[0]) ?? models[0];
  const on = (m: EmbedModelOption) =>
    multi ? chosen.includes(m.id) : m.id === picked.id;
  const toggle = (m: EmbedModelOption) => {
    if (!multi) { onChange(m.id); setOpen(false); return; }
    // Never down to nothing: the switch above owns "off".
    if (chosen.includes(m.id)) {
      if (chosen.length === 1) return;
      onChange(chosen.filter((id) => id !== m.id).join(","));
    } else {
      // Registry order, so the value reads the same however it was clicked.
      onChange(models.filter((x) => x.id === m.id || chosen.includes(x.id))
                     .map((x) => x.id).join(","));
    }
  };
  const line = (m: EmbedModelOption) => {
    const s = EMBED_STRENGTHS[m.family ?? ""];
    return s ? t(s) : "";
  };
  // With several picked the strength lines describe different models, so no
  // one of them can be the subtitle; what is worth saying instead is that
  // they do not combine into a third thing.
  const shownPicked = multi && chosen.length > 1
    ? models.filter((m) => chosen.includes(m.id))
    : [picked];
  const title = shownPicked.map((m) => m.name).join(" + ");
  const subtitle = shownPicked.length > 1
    ? t("Each space is indexed separately")
    : line(picked);
  return (
    <>
      <div
        ref={ref}
        onClick={(e) => { e.stopPropagation(); setOpen((o) => !o); }}
        style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 8,
                 padding: "6px 8px", borderRadius: "var(--r-3)", cursor: "pointer",
                 background: "var(--bg)", color: "var(--text)",
                 border: "1px solid var(--border-strong)", maxWidth: "100%" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: "var(--fs-3)", overflow: "hidden",
                        textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {title}
          </div>
          {subtitle && (
            <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)",
                          overflow: "hidden", textOverflow: "ellipsis",
                          whiteSpace: "nowrap" }}>
              {subtitle}
            </div>
          )}
        </div>
        <Icon name="expand_more" size={16} color="var(--muted-2)" />
      </div>
      {open && (
        <AnchoredDropdown rect={rect} minWidth={260}>
          {models.map((m) => {
            const lit = on(m);
            return (
              <div key={m.id} className="hoverable"
                onClick={(e) => { e.stopPropagation(); toggle(m); }}
                style={{ display: "flex", alignItems: "flex-start", gap: 8,
                         padding: "7px 10px", borderRadius: "var(--r-3)",
                         cursor: "pointer" }}>
                <span style={{ width: 16, display: "flex", marginTop: 1 }}>
                  {lit && <Icon name="check" size={16} color="var(--accent)" />}
                </span>
                <span style={{ minWidth: 0 }}>
                  <span style={{ display: "block", fontSize: "var(--fs-3)",
                                 color: lit ? "var(--accent)" : "var(--text)" }}>
                    {m.name}
                  </span>
                  {line(m) && (
                    <span style={{ display: "block", fontSize: "var(--fs-2)",
                                   color: "var(--muted-2)" }}>
                      {line(m)}
                    </span>
                  )}
                </span>
              </div>
            );
          })}
        </AnchoredDropdown>
      )}
    </>
  );
}

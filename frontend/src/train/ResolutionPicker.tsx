// WHICH SIZES A RUN TRAINS AT, as one multi-select.
//
// The sizes are a SET with no first among them, so the control is a set:
// a field showing what is picked, and a list of ticks behind the chevron —
// `TextRow`'s suggestion list, which says the same thing the same way.
//
// There is no "base" here and there is none in the config either. It existed
// for a day as one size the run was somehow about, plus the others beside
// it, and nothing was ever true of it that was not true of them (see
// `BucketConfig.resolutions`).
//
// THE MODEL'S OWN SIZE IS A ROW LIKE THE REST, wearing a mark. The config's
// 0 means "whichever number that is" rather than a size of its own, so it
// belongs ON the row for that number: as a row of its own ("Model default
// (1024 px)") it was possible to tick it AND 1024 and see one size twice,
// spending two of the five slots on one bucket family. Ticking the marked
// row stores the 0, which is what makes a job follow the model if somebody
// points it at another one.
//
// CUSTOM SIZES JOIN THE LIST. The ladder below is the common one, and the
// last row opens a field for anything else; a size added that way is picked
// straight away and keeps its row for as long as it stays picked, so it can
// be unticked and re-ticked like any other.
import { useEffect, useRef, useState } from "react";
import { SectionHeading } from "../shared/SectionHeading";
import { useMenuDismiss } from "../shared/useMenuDismiss";

import { useT } from "./i18n";
import { Icon } from "../shared/Icon";
import { AnchoredDropdown, useAnchorRect } from "../shared/AnchoredDropdown";
import { RowShell, inputStyle } from "./FormRows";
import { MAX_RESOLUTIONS, resolutionList } from "./util";

/** The ladder the list offers: the sizes the models here are trained at and
 *  the halves between them. Anything else goes in through Custom, so this is
 *  a convenience rather than a policy — a number missing from it costs two
 *  more clicks, not a setting. */
const LADDER = [256, 384, 512, 640, 768, 896, 1024, 1280, 1536];

export function ResolutionPicker({ value, native, hint, details, onChange }: {
  /** The stored list. 0 is a member and means the model's own size. */
  value: number[];
  /** The model's native area: what a 0 resolves to, and therefore which row
   *  of the list is the marked one. */
  native: number;
  hint?: string;
  details?: string;
  onChange: (v: number[]) => void;
}) {
  const t = useT();
  const box = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const rect = useAnchorRect(box, open);
  useMenuDismiss(open, () => setOpen(false), { within: [box] });
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");
  useEffect(() => { if (!open) { setAdding(false); setDraft(""); } }, [open]);

  // `key(v)` is what makes the model's own size ONE row (see the header):
  // the stored list may hold 0, or that number, or — from the API — both,
  // and every one of them is this row picked.
  const key = (v: number) => (v === native ? 0 : v);
  const picked = new Set(value.map(key));
  const full = picked.size >= MAX_RESOLUTIONS;
  // The ladder, the model's own size (which need not be on it — a user
  // model can be trained at anything) and whatever else is picked, so a
  // custom size is a row for as long as it is in use and disappears once it
  // is not, which is what keeps the list from growing for ever.
  const rows = [...new Set([native, ...LADDER,
                            ...value.filter((v) => v > 0)])]
    .sort((a, b) => a - b);

  const toggle = (v: number) => {
    const k = key(v);
    if (picked.has(k)) {
      // NEVER EMPTY: a run trains at some size, and the config would
      // normalize an empty list back to the model's own anyway — better to
      // refuse the last untick than to answer it with a silent substitution.
      if (picked.size > 1) {
        onChange(resolutionList(value.filter((x) => key(x) !== k)));
      }
    } else if (!full) {
      // The model's own size is stored AS the 0: that is what makes a job
      // set to it follow the model when somebody changes which model it
      // trains, which is the whole reason the sentinel exists.
      onChange(resolutionList([...value, k]));
    }
  };

  const addCustom = () => {
    const n = Math.round(Number(draft.trim()));
    setDraft("");
    setAdding(false);
    if (Number.isFinite(n) && n > 0 && !full) {
      onChange(resolutionList([...value, Math.min(4096, n)]));
    }
  };

  const label = (v: number) => t("{n} px", { n: String(v) });
  // What the field itself says: the sizes in order, with the model's own
  // named by the number it resolves to — the summary is about what the run
  // will do, and "0" is not a size anybody trains at.
  //
  // THROUGH `key` FIRST, so it says what the LIST says. Switching a job's
  // model can make the 0 and a named size the same number (an SDXL job at
  // [0, 512] pointed at SD 1.5), and the collapse the rows do has to reach
  // here too — otherwise one ticked row read as "512, 512" until a save
  // settled the stored list.
  const shown = [...new Set(value.map(key))]
    .map((v) => (v === 0 ? native : v))
    .sort((a, b) => a - b);
  const summary = shown.length ? shown.join(", ") : String(native);

  return (
    <RowShell label={t("Resolutions")} hint={hint} details={details}>
      <div ref={box} style={{ position: "relative", width: 220 }}>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          style={{
            ...inputStyle, width: "100%", textAlign: "left", cursor: "pointer",
            display: "flex", alignItems: "center", gap: 6,
          }}
        >
          <span style={{ flex: 1, overflow: "hidden",
                         textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {summary}
          </span>
          <span style={{ color: "var(--muted-2)", flex: "0 0 auto" }}>px</span>
          <Icon name="expand_more" size={16}
                color={open ? "var(--accent)" : "var(--muted-2)"} />
        </button>
        {open && (
          <>
            <AnchoredDropdown rect={rect} minWidth={220}>
              {rows.map((v) => {
                const on = picked.has(key(v));
                // A tick that cannot be given (the cap) or taken back (the
                // last one) is drawn dim rather than hidden: the row is the
                // answer to "why not", and a list that changed length as it
                // filled would be harder to read, not easier.
                const stuck = on ? picked.size === 1 : full;
                return (
                  <div key={v} onClick={() => toggle(v)}
                    title={stuck
                      ? (on ? t("A run trains at one size at least.")
                            : t("A run trains at up to five sizes — each one "
                                + "is another pass over the dataset per "
                                + "epoch."))
                      : v === native
                      ? t("This model's own size. A job set to it follows "
                          + "whichever model it is pointed at.")
                      : undefined}
                    style={{
                      display: "flex", alignItems: "center", gap: 6,
                      padding: "4px 7px", borderRadius: "var(--r-2)",
                      cursor: stuck ? "default" : "pointer",
                      fontSize: "var(--fs-2)", opacity: stuck && !on ? 0.45 : 1,
                      color: on ? "var(--text)" : "var(--muted)",
                      background: on ? "var(--accent-dim)" : "transparent",
                    }}>
                    {/* The tick's gutter stays whether or not it is drawn, or
                        every unticked size steps sideways as the list is
                        used. */}
                    <span style={{ width: 14, display: "flex",
                                   flex: "0 0 auto", color: "var(--accent)" }}>
                      {on && <Icon name="check" size={14} />}
                    </span>
                    {label(v)}
                    {v === native && (
                      <SectionHeading sm style={{ marginLeft: "auto", paddingLeft: 8 }}>
                        {t("default")}
                      </SectionHeading>
                    )}
                  </div>
                );
              })}
              <div style={{ borderTop: "1px solid var(--border-soft)",
                            margin: "4px 0 0", paddingTop: 4 }}>
                {adding ? (
                  <div style={{ display: "flex", alignItems: "center", gap: 6,
                                padding: "0 7px 2px" }}>
                    <input
                      value={draft}
                      autoFocus
                      inputMode="numeric"
                      placeholder={t("e.g. 704")}
                      onChange={(e) => setDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") addCustom();
                        else if (e.key === "Escape") {
                          setAdding(false);
                          setDraft("");
                        }
                      }}
                      style={{ ...inputStyle, height: 26, width: 90,
                               textAlign: "right" }}
                    />
                    <span style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>
                      px
                    </span>
                    <span style={{ flex: 1 }} />
                    <button type="button" onClick={addCustom}
                      style={{ ...inputStyle, height: 26, cursor: "pointer",
                               background: "transparent", fontSize: "var(--fs-2)" }}>
                      {t("Add")}
                    </button>
                  </div>
                ) : (
                  <div onClick={() => !full && setAdding(true)}
                    style={{
                      display: "flex", alignItems: "center", gap: 6,
                      padding: "4px 7px", borderRadius: "var(--r-2)", fontSize: "var(--fs-2)",
                      cursor: full ? "default" : "pointer",
                      opacity: full ? 0.45 : 1, color: "var(--muted)",
                    }}>
                    <span style={{ width: 14, display: "flex",
                                   flex: "0 0 auto" }}>
                      <Icon name="add" size={14} />
                    </span>
                    {t("Another size…")}
                  </div>
                )}
              </div>
            </AnchoredDropdown>
          </>
        )}
      </div>
    </RowShell>
  );
}

// The Value-rules section of the job editor's Prompt page.
//
// A rule turns a numeric VALUE tag into words at prompt time: where `height`
// is > 190cm, write "tall". A raw `height:172cm` token teaches nothing a text
// encoder can read, so a matching tag is REPLACED by the rule's text (a
// per-rule toggle keeps the raw tag alongside). Ranges may overlap; the FIRST
// matching rule wins, so the rows are reorderable and their order is part of
// the configuration. A value tag no rule matches passes through unchanged —
// visible behavior, never silent dropping.
//
// The rules resolve to a finished tag → text map when the dataset is
// materialized (`dataset._value_map`), so the trainer never learns what a
// value is — the meta-tag resolver's pattern.
import { useEffect, useRef, useState } from "react";
import { storage } from "../shared/storage";
import { useMenuDismiss } from "../shared/useMenuDismiss";
import { AnchoredDropdown, useAnchorRect } from "../shared/AnchoredDropdown";
import { useInlineEdit } from "../shared/useInlineEdit";

import type { TrainValueRule } from "./api";
import { useT } from "./i18n";
import { Icon } from "../shared/Icon";
import { Section, inputStyle } from "./FormRows";
import { HelpMark } from "../shared/HelpMark";
import { parseValue } from "../shared/tagvalue";
import { HELP } from "./fieldHelp";

const SETS_KEY = "mc.trainValueRuleSets";

type RuleSet = { id: string; name: string; rules: TrainValueRule[] };

function loadSets(): RuleSet[] {
  try {
    const v = JSON.parse(storage.get(SETS_KEY) || "[]");
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

function storeSets(sets: RuleSet[]) {
  try { storage.set(SETS_KEY, JSON.stringify(sets)); } catch { /* ignore */ }
}

const OPS: [TrainValueRule["op"], string][] = [
  ["=", "="], ["!=", "≠"], [">", ">"], [">=", "≥"], ["<", "<"], ["<=", "≤"],
];

const btn: React.CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 5, height: 28,
  padding: "0 10px", borderRadius: "var(--r-3)", border: "1px solid var(--border)",
  background: "transparent", color: "var(--text-2)", fontSize: "var(--fs-3)",
  cursor: "pointer",
};

/** The rendered value+unit of a rule, with the canonical dot decimal. */
function ruleValueText(r: TrainValueRule): string {
  return `${r.value}${r.unit}`;
}

/** One rule row's value+unit field: one input for one token ("190cm"), the
 *  query builder's rule — text is kept locally and only what parses commits,
 *  so a keystroke that can never become a value never reaches the config. */
function ValueField({ rule, onCommit }: {
  rule: TrainValueRule;
  onCommit: (value: number, unit: string) => void;
}) {
  const [text, setText] = useState(ruleValueText(rule));
  useEffect(() => {
    const v = parseValue(text.replace(",", "."));
    if (!v || v.value !== rule.value || v.unit !== rule.unit) {
      setText(ruleValueText(rule));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rule.value, rule.unit]);
  return (
    <input value={text} placeholder="190cm"
      onChange={(e) => {
        const raw = e.target.value;
        if (!/^-?[\d.,a-z%°µ]*$/.test(raw)) return;
        setText(raw);
        const v = parseValue(raw.replace(",", "."));
        if (v) onCommit(v.value, v.unit);
      }}
      onBlur={() => setText(ruleValueText(rule))}
      style={{ ...inputStyle, width: 76 }} />
  );
}

/** Save / load named rule lists — the variant-sets menu one page away, with
 *  one difference: loading ADDS the set's missing rules rather than replacing
 *  the list, so a house rule set can be folded into a job that already has
 *  its own rows. */
function RuleSetsMenu({ rules, onLoad }: {
  rules: TrainValueRule[];
  onLoad: (add: TrainValueRule[]) => void;
}) {
  const t = useT();
  const [sets, setSets] = useState<RuleSet[]>(loadSets);
  const [menu, setMenu] = useState(false);
  const menuAnchor = useRef<HTMLButtonElement>(null);
  const menuRect = useAnchorRect(menuAnchor, menu);
  // A press elsewhere, Escape, and a scroll of the page close it — the one
  // rule (`useMenuDismiss`), in place of a click-catcher behind the panel.
  useMenuDismiss(menu, () => setMenu(false), { within: [menuAnchor] });
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameVal, setRenameVal] = useState("");
  const renameRef = useRef<HTMLInputElement>(null);
  useEffect(() => { if (renameId) renameRef.current?.select(); }, [renameId]);

  const commit = (next: RuleSet[]) => { setSets(next); storeSets(next); };
  const commitRename = () => {
    if (!renameId) return;
    const v = renameVal.trim();
    if (v) commit(sets.map((s) => (s.id === renameId ? { ...s, name: v } : s)));
    setRenameId(null);
  };
  const renameKeys = useInlineEdit({ commit: commitRename,
                                     cancel: () => setRenameId(null) });
  const saveSet = () => {
    const taken = new Set(sets.map((s) => s.name));
    let n = sets.length + 1;
    while (taken.has(`${t("Set")} ${n}`)) n++;
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const name = `${t("Set")} ${n}`;
    commit([{ id, name, rules: rules.map((r) => ({ ...r })) }, ...sets]);
    setRenameId(id);
    setRenameVal(name);
  };
  const hasContent = rules.length > 0;

  return (
    <div>
      <button ref={menuAnchor} style={btn} onClick={() => setMenu((v) => !v)} title={t("Save the current rules, or load a saved set")}>
        <Icon name="bookmarks" size={15} />{t("Rule sets")}
        <Icon name="expand_more" size={13} style={{ opacity: 0.7 }} />
      </button>
      {menu && (
          <AnchoredDropdown rect={menuRect} minWidth={250} focusable>
            <div className={hasContent ? "hoverable" : undefined}
              title={hasContent
                ? t("Remember the current rules — name the set in this list afterwards")
                : t("Add a rule first")}
              onClick={() => { if (hasContent) saveSet(); }}
              style={{
                display: "flex", alignItems: "center", gap: 8, padding: "6px 9px",
                borderRadius: "var(--r-3)", fontSize: "var(--fs-3)", color: "var(--text-2)",
                opacity: hasContent ? 1 : 0.45,
                cursor: hasContent ? "pointer" : "default",
              }}>
              <Icon name="bookmark_add" size={14} color="var(--muted)" />
              <span style={{ flex: 1 }}>{t("Save current rules")}</span>
            </div>
            {sets.length > 0 && (
              <div style={{ height: 1, background: "var(--menu-border)", margin: "4px 2px" }} />
            )}
            {sets.map((s) => (
              <div key={s.id} style={{
                display: "flex", alignItems: "center", gap: 2, minHeight: 34,
                borderRadius: "var(--r-3)",
              }}>
                {renameId === s.id ? (
                  <input ref={renameRef} value={renameVal}
                    onChange={(e) => setRenameVal(e.target.value)}
                    onBlur={renameKeys.onBlur}
                    onKeyDown={renameKeys.onKeyDown}
                    style={{ ...inputStyle, height: 26, flex: 1, margin: "0 4px" }} />
                ) : (<>
                  <div className="hoverable" style={{
                    flex: 1, padding: "6px 9px", borderRadius: "var(--r-3)", fontSize: "var(--fs-3)",
                    cursor: "pointer", color: "var(--text-2)",
                  }}
                    title={t("Add this set's rules to the job — rows it already has stay put")}
                    onClick={() => { onLoad(s.rules.map((r) => ({ ...r }))); setMenu(false); }}>
                    {s.name}
                    <span style={{ color: "var(--muted-2)", marginLeft: 6 }}>
                      {s.rules.length}
                    </span>
                  </div>
                  <button style={{ ...btn, border: "none", height: 24, padding: "0 6px" }}
                    title={t("Rename")}
                    onClick={() => { setRenameId(s.id); setRenameVal(s.name); }}>
                    <Icon name="edit" size={13} />
                  </button>
                  <button style={{ ...btn, border: "none", height: 24, padding: "0 6px",
                                   color: "var(--red)" }}
                    title={t("Delete this set")}
                    onClick={() => commit(sets.filter((x) => x.id !== s.id))}>
                    <Icon name="close" size={13} />
                  </button>
                </>)}
              </div>
            ))}
          </AnchoredDropdown>
        
)}
    </div>
  );
}

export function ValueRulesSection({ rules, onChange }: {
  rules: TrainValueRule[];
  onChange: (next: TrainValueRule[]) => void;
}) {
  const t = useT();
  const set = (i: number, patch: Partial<TrainValueRule>) =>
    onChange(rules.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const dragFrom = useRef<number | null>(null);
  const ruleKey = (r: TrainValueRule) =>
    `${r.namespace}\u0000${r.op}\u0000${r.value}\u0000${r.unit}\u0000${r.text}`;

  return (
    <Section label={t("Value rules")}
      hint={t("Turn numeric value tags (height:172cm) into words at prompt time. The first matching rule wins — drag rows to reorder.")}>
      <div style={{ padding: "10px 14px", display: "flex",
                    flexDirection: "column", gap: 6 }}>
        {rules.map((r, i) => (
          <div key={i} draggable
            onDragStart={(e) => {
              dragFrom.current = i;
              e.dataTransfer.setData("text/plain", String(i));
            }}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const from = dragFrom.current;
              dragFrom.current = null;
              if (from === null || from === i) return;
              const next = [...rules];
              const [moved] = next.splice(from, 1);
              next.splice(i, 0, moved);
              onChange(next);
            }}
            style={{ display: "flex", alignItems: "center", gap: 6,
                     flexWrap: "wrap" }}>
            {/* No connective words ("where … is … write …"): a fill-in-the-
                blanks sentence cannot survive eight word orders, so the row
                is columns and an arrow — the shape needs no grammar. */}
            <Icon name="drag_indicator" size={15} color="var(--muted-2)" />
            <input value={r.namespace} placeholder={t("namespace, e.g. height")}
              onChange={(e) => set(i, {
                namespace: e.target.value.replace(/\s+/g, "_")
                  .replace(/:+$/, "").toLowerCase() })}
              style={{ ...inputStyle, width: 110 }} />
            <select value={r.op}
              onChange={(e) => set(i, { op: e.target.value as TrainValueRule["op"] })}
              style={{ ...inputStyle, width: 52, padding: "0 4px" }}>
              {OPS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
            <ValueField rule={r}
              onCommit={(value, unit) => set(i, { value, unit })} />
            <span style={{ fontSize: "var(--fs-4)", color: "var(--muted)" }}>→</span>
            <input value={r.text} placeholder="tall"
              onChange={(e) => set(i, { text: e.target.value })}
              style={{ ...inputStyle, flex: "1 1 120px", minWidth: 100 }} />
            <label title={t("Keep the raw tag in the prompt beside the rule's text")}
              style={{ display: "inline-flex", alignItems: "center", gap: 4,
                       fontSize: "var(--fs-3)", color: "var(--muted)", cursor: "pointer" }}>
              <input type="checkbox" checked={r.keep_raw}
                onChange={(e) => set(i, { keep_raw: e.target.checked })} />
              {t("keep tag")}
            </label>
            <button style={{ ...btn, border: "none", padding: "0 4px",
                             color: "var(--red)" }}
              title={t("Remove this rule")}
              onClick={() => onChange(rules.filter((_, j) => j !== i))}>
              <Icon name="close" size={14} />
            </button>
          </div>
        ))}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button style={btn}
            onClick={() => onChange([...rules, {
              namespace: "", op: ">=", value: 0, unit: "", text: "",
              keep_raw: false }])}>
            <Icon name="add" size={15} />{t("Add rule")}
          </button>
          <span style={{ flex: 1 }} />
          <HelpMark heading={t("Value rules")} tooltip={t("What does this do?")}
            text={t(HELP["value-rules.value-rules"])} />
          <RuleSetsMenu rules={rules}
            onLoad={(add) => {
              const have = new Set(rules.map(ruleKey));
              onChange([...rules, ...add.filter((r) => !have.has(ruleKey(r)))]);
            }} />
        </div>
      </div>
    </Section>
  );
}

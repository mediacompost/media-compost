// Folding several selected subjects into one.
//
// The same shape as the tag merge, and for the same reason: two rows for one
// person is a thing you notice in the LIST, not while editing one of them. The
// single-subject merge lives in the edit overlay, where it is what "rename onto
// a name that is taken" means; this is the other way in.
//
// The target must be one of the selected subjects — unlike tags, a subject
// cannot be conjured from a typed name here, because a new one would have no
// identity tag and folding real subjects into an empty shell is never what
// somebody meant.
import React, { useState } from "react";
import { RECORD_ICON } from "../../shared/metaEnums";
import { rowBackground } from "../../shared/Row";
import { SectionHeading } from "../../shared/SectionHeading";
import { api, SubjectRow } from "../api";
import { Icon } from "../../shared/Icon";
import { useT, useErrText } from "../i18n";
import { Overlay } from "../../shared/Overlay";
import { Button } from "../../shared/Button";

export function SubjectMergeOverlay({ sources, onClose, onMerged }: {
  sources: SubjectRow[];
  onClose: () => void;
  onMerged: (into: string, events: number[]) => void;
}) {
  const t = useT();
  const errText = useErrText();
  const [targetId, setTargetId] = useState(sources[0]?.id ?? 0);
  const [keepAlias, setKeepAlias] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const target = sources.find((s) => s.id === targetId) ?? null;
  const folded = sources.filter((s) => s.id !== targetId);
  const label = (s: SubjectRow) => s.display_name || s.tag || t("unnamed");

  const run = async () => {
    if (!target || folded.length === 0) return;
    setBusy(true);
    try {
      // One call per source, so each fold is its own event and the whole
      // thing reverts a step at a time — the same contract the tag merge has.
      const events: number[] = [];
      for (const src of folded) {
        const res = await api.mergeSubject(src.id, target.id, keepAlias);
        events.push(...(res.event_ids ?? []));
      }
      onMerged(label(target), events);
      onClose();
    } catch (e) {
      setError(errText(e));
      setBusy(false);
    }
  };

  return (
    <Overlay error={error}
      icon="merge"
      title={t("Merge subjects")}
      subtitle={`${sources.length} ${t("selected")}`}
      width={520}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t("Cancel")}</Button>
          <Button variant="primary" icon="merge" onClick={() => void run()}
            disabled={busy || !target || folded.length === 0}>
            {t("Merge")} {folded.length}
          </Button>
        </>
      }
    >
      <div style={{ padding: 18, display: "flex", flexDirection: "column", gap: 14 }}>
        <div>
          <SectionHeading style={{ marginBottom: 4 }}>
            {t("Keep")}
          </SectionHeading>
          <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", marginBottom: 8 }}>
            {t("The one that survives. The others' faces, pictures and dates move onto it.")}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {sources.map((s) => (
              <label key={s.id} className="hoverable" style={{
                display: "flex", alignItems: "center", gap: 8, padding: "6px 8px",
                borderRadius: "var(--r-4)", cursor: "pointer",
                border: `1px solid ${s.id === targetId ? "var(--accent)" : "var(--border)"}`,
                background: rowBackground(s.id === targetId, "var(--panel-2)"),
              }}>
                <input type="radio" checked={s.id === targetId}
                  onChange={() => setTargetId(s.id)} style={{ cursor: "pointer" }} />
                <Icon name={RECORD_ICON.subject} size={15} color="var(--muted-2)" />
                <span style={{ fontSize: "var(--fs-3)", color: "var(--text)" }}>{label(s)}</span>
                {s.comment && (
                  <span style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>· {s.comment}</span>
                )}
                <span style={{ flex: 1 }} />
                <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)", color: "var(--muted-3)" }}>
                  {s.tag || "—"}
                </span>
                <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-1)", color: "var(--muted-3)", width: 34, textAlign: "right" }}>
                  {s.items}
                </span>
              </label>
            ))}
          </div>
        </div>

        <label style={{ display: "flex", alignItems: "center", gap: 7, cursor: "pointer" }}>
          <input type="checkbox" checked={keepAlias}
            onChange={(e) => setKeepAlias(e.target.checked)} style={{ cursor: "pointer" }} />
          <span style={{ fontSize: "var(--fs-2)", color: "var(--muted)" }}>
            {t("Keep each old tag as an alias, so anything still using it finds the merged subject")}
          </span>
        </label>
      </div>
    </Overlay>
  );
}

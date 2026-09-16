// Folding several selected tags into one.
//
// The single-tag merge lives in the edit overlay, where it is what "rename onto
// a name that is taken" means. This is the other way in: pick N rows in the
// list and say what they should all become. The target may be one of them, an
// existing tag, or a name that does not exist yet — in which case it is created
// and everything is folded into it.
import React, { useMemo, useState } from "react";
import { SectionHeading } from "../../shared/SectionHeading";
import { api, TagRow } from "../api";
import { Icon } from "../../shared/Icon";
import { useT, useErrText } from "../i18n";
import { Overlay } from "../../shared/Overlay";
import { Button } from "../../shared/Button";
import { TagAutocomplete } from "./TagAutocomplete";
import { tagCount } from "../tags";

export function TagMergeOverlay({ sources, allTags, onClose, onMerged }: {
  sources: TagRow[];
  allTags: TagRow[];
  onClose: () => void;
  onMerged: (into: string, events: number[]) => void;
}) {
  const t = useT();
  const errText = useErrText();
  const [target, setTarget] = useState(sources[0]?.name ?? "");
  const [keepAlias, setKeepAlias] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // A name that MATCHES an existing tag is used verbatim (a legacy library
  // may hold mixed case); only a NEW name takes the full field rules —
  // `trim + \s+ → _` alone was half of them, so the Merge button could create
  // `Foo` or send a trailing-colon name the API refuses where Enter in the
  // same field commits `foo`.
  // The field commits its own form (`tagFieldName`), so what is typed IS
  // the clean name; an existing tag is matched by that.
  const typed = target.trim();
  const existing = useMemo(
    () => allTags.find((x) => x.name === typed) ?? null, [allTags, typed]);
  const clean = existing ? existing.name : typed;
  const options = useMemo(
    () => allTags.filter((x) => x.alias_of == null)
      .map((x) => ({ name: x.name, comment: x.comment ?? "", uses: tagCount(x),
                     metaCounts: x.meta_counts ?? undefined,
                     metaTags: x.meta_tags ?? undefined })),
    [allTags]);
  // Merging into a name none of them has means creating that tag first.
  const isNew = !!clean && existing == null;
  const folded = sources.filter((s) => s.name !== clean);

  const run = async () => {
    if (!clean || folded.length === 0) return;
    setBusy(true);
    try {
      let into = existing;
      if (into == null) into = await api.createTag({ name: clean });
      const events: number[] = [];
      for (const src of folded) {
        const res = await api.mergeTag(src.id, into.name, keepAlias);
        events.push(...(res.event_ids ?? []));
      }
      onMerged(into.name, events);
      onClose();
    } catch (e) {
      setError(errText(e));
      setBusy(false);
    }
  };

  return (
    <Overlay error={error}
      icon="merge"
      title={t("Merge tags")}
      subtitle={`${sources.length} ${t("selected")}`}
      width={520}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t("Cancel")}</Button>
          <Button variant="primary" icon="merge" onClick={() => void run()}
            disabled={busy || !clean || folded.length === 0}>
            {t("Merge")} {folded.length}
          </Button>
        </>
      }
    >
      <div style={{ padding: 18, display: "flex", flexDirection: "column", gap: 14 }}>
        <div>
          <SectionHeading style={{ marginBottom: 6 }}>
            {t("Merge into")}
          </SectionHeading>
          <TagAutocomplete
            value={target}
            onChange={setTarget}
            onCommit={setTarget}
            suggestions={options}
            placeholder={t("a tag name")}
            autoFocus
            inputStyle={{
              width: "100%", height: 34, padding: "0 11px", background: "var(--bg)",
              border: "1px solid var(--border-strong)", borderRadius: "var(--r-4)",
              color: "var(--text)", fontSize: "var(--fs-4)", fontFamily: "var(--mono)",
              outline: "none", boxSizing: "border-box",
            }}
            minWidth={280}
          />
          <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", marginTop: 6 }}>
            {isNew
              ? t("No tag has this name yet — it is created, and everything is folded into it.")
              : t("One of the selected tags, or any other: everything is folded into it.")}
          </div>
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {sources.map((s) => {
            const isTarget = s.name === clean;
            return (
              <span key={s.id} style={{
                display: "inline-flex", alignItems: "center", gap: 4,
                height: 22, padding: "0 8px", borderRadius: "var(--r-2)",
                fontFamily: "var(--mono)", fontSize: "var(--fs-2)",
                background: isTarget ? "var(--accent-dim)" : "var(--panel-2)",
                border: `1px solid ${isTarget ? "var(--accent)" : "var(--border)"}`,
                color: isTarget ? "var(--accent)" : "var(--muted)",
              }}>
                {isTarget && <Icon name="check" size={12} />}
                {s.name}
              </span>
            );
          })}
        </div>

        <label style={{
          display: "flex", alignItems: "flex-start", gap: 9, cursor: "pointer",
          padding: "10px 12px", borderRadius: "var(--r-5)",
          background: "var(--panel)", border: "1px solid var(--border)",
        }}>
          <input type="checkbox" checked={keepAlias}
            onChange={(e) => setKeepAlias(e.target.checked)}
            style={{ marginTop: 2, cursor: "pointer" }} />
          <span>
            <span style={{ fontSize: "var(--fs-3)", color: "var(--text-2)" }}>
              {t("Keep the old names as aliases")}
            </span>
            <span style={{ display: "block", fontSize: "var(--fs-2)", color: "var(--muted-2)", marginTop: 2 }}>
              {keepAlias
                ? t("Anything still using an old name finds the merged tag.")
                : t("The old names disappear; anything using them will not resolve.")}
            </span>
          </span>
        </label>

        <div style={{ fontSize: "var(--fs-2)", color: "var(--muted)", lineHeight: 1.55 }}>
          {t("Every item assignment (with its tag groups, boxes and time ranges), implication and group tag moves onto the target. Each item's change is recorded separately, so this can be undone.")}
        </div>
      </div>
    </Overlay>
  );
}

// The meta-tag counterpart of TagEditOverlay: a name, a comment, a
// description, and the
// same rule that renaming onto a name that already exists is a MERGE.
//
// It is a separate component rather than a mode of the item-tag one because a
// meta tag has none of what that overlay is mostly about — no implications, no
// aliases, no positive/negative assignments. What it has instead is three
// carriers (links, captions, per-item tag groups), which is what the subtitle
// and the merge explanation talk about.
import React, { useEffect, useMemo, useRef, useState } from "react";
import { useFrozen } from "../../shared/useFrozen";
import { api, LinkTagRow } from "../api";
import { useT, useTn, type TnFn, useErrText } from "../i18n";
import { sanitizeLinkTagInput } from "../tags";
import { Overlay, fieldStyle as field, FieldLabel as Label } from "../../shared/Overlay";
import { Button } from "../../shared/Button";
import { noteStyle } from "./TagEditOverlay";
import { DescriptionField } from "./DescribedFields";

/** "3 links · 1 caption · 0 tag groups · 2 tags" — the row's own columns,
 *  spelled out. All FOUR carriers: the library's own tags carry meta tags
 *  too, and a summary naming three of them beside a count summing four read
 *  as arithmetic that did not add up. */
export function carrierSummary(r: LinkTagRow, tn: TnFn) {
  return [
    tn({ one: "1 link", other: "{n} links" }, r.links),
    tn({ one: "1 caption", other: "{n} captions" }, r.captions),
    tn({ one: "1 tag group", other: "{n} tag groups" }, r.tag_groups),
    tn({ one: "1 tag", other: "{n} tags" }, r.tags),
  ].join(" · ");
}

export function MetaTagEditOverlay({ tag, allTags: allTagsLive, onClose, onChanged, onMerged }: {
  /** Null CREATES one: this is the edit dialog with nothing filled in, the
   *  same rule the item-tag Add follows. A meta tag is a name, a comment and
   *  a description, which is exactly this form — the inline strip it replaced
   *  could take only the first of the three. */
  tag: LinkTagRow | null;
  allTags: LinkTagRow[];
  onClose: () => void;
  onChanged: () => void;
  /** A merge takes the old name away, so the caller can offer an Undo. */
  onMerged: (into: string) => void;
}) {
  // The catalog as it was when the dialog opened (`useFrozen`).
  const allTags = useFrozen(allTagsLive, tag?.name) ?? allTagsLive;
  const t = useT();
  const errText = useErrText();
  const tn = useTn();
  const [name, setName] = useState(tag?.name ?? "");
  const [comment, setComment] = useState(tag?.comment ?? "");
  // The long form, behind the ? beside the name — see `DescribedFields`.
  const [description, setDescription] = useState(tag?.description ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [mergeInto, setMergeInto] = useState<LinkTagRow | null>(null);
  const firstRef = useRef<HTMLInputElement>(null);
  useEffect(() => { firstRef.current?.focus(); }, []);

  const clean = sanitizeLinkTagInput(name.trim());
  const renaming = !!tag && clean !== tag.name;
  const clash = useMemo(
    () => allTags.find((x) => x.name === clean && x.name !== tag?.name) ?? null,
    [allTags, clean, tag?.name]
  );

  const save = async () => {
    setError("");
    if (!clean) { setError(t("A tag needs a name.")); return; }
    // On a NEW one a clash is simply a refusal — there is nothing to merge
    // yet, and creating is idempotent, so saving would silently adopt
    // somebody else's tag and its comment.
    if (clash && !tag) { setError(t("already exists")); return; }
    if (clash) { setMergeInto(clash); return; }
    setBusy(true);
    try {
      // One call carries all three; the backend logs the rename, the comment
      // and the description as separate, separately revertible events.
      if (!tag) await api.createLinkTag(clean, { comment, description });
      else await api.updateLinkTag({
        name: tag.name,
        ...(renaming ? { new_name: clean } : {}),
        ...(comment !== (tag.comment ?? "") ? { comment } : {}),
        ...(description !== (tag.description ?? "") ? { description } : {}),
      });
      onChanged();
      onClose();
    } catch (e) {
      setError(errText(e));
      setBusy(false);
    }
  };

  const doMerge = async () => {
    if (!mergeInto || !tag) return;
    setBusy(true);
    try {
      await api.updateLinkTag({ name: tag.name, new_name: mergeInto.name });
      onMerged(mergeInto.name);
      onClose();
    } catch (e) {
      setError(errText(e));
      setBusy(false);
      setMergeInto(null);
    }
  };

  if (mergeInto && tag) {
    return (
      <Overlay error={error}
        icon="merge"
        title={t("Merge meta tags?")}
        subtitle={`${tag.name} → ${mergeInto.name}`}
        width={480}
        onClose={() => setMergeInto(null)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setMergeInto(null)}>{t("Cancel")}</Button>
            <Button variant="primary" icon="merge" onClick={() => void doMerge()} disabled={busy}>
              {t("Merge")}
            </Button>
          </>
        }
      >
        <div style={{ padding: 18, fontSize: "var(--fs-3)", color: "var(--text-2)", lineHeight: 1.6 }}>
          <p style={{ margin: "0 0 10px" }}>
            <b style={{ fontFamily: "var(--mono)" }}>{mergeInto.name}</b> {t("already exists.")}{" "}
            {t("Merging moves everything")} <b style={{ fontFamily: "var(--mono)" }}>{tag.name}</b>{" "}
            {t("labels onto it: every link, caption and tag group carrying the old name carries the new one instead (a carrier holding both keeps one).")}
          </p>
          <p style={{ margin: "0 0 10px", color: "var(--muted)" }}>
            {t("A meta tag has no aliases, so the old name simply goes.")}
          </p>
          <p style={{ margin: 0, color: "var(--muted)" }}>
            {t("This is recorded, so it can be undone from the History tab.")}
          </p>
        </div>
      </Overlay>
    );
  }

  return (
    <Overlay onSubmit={() => void save()} error={error}
      icon="link"
      title={tag ? t("Edit meta tag") : t("New meta tag")}
      unsaved={{
        dirty: name !== (tag?.name ?? "") || comment !== (tag?.comment ?? "")
          || description !== (tag?.description ?? ""),
        onSave: () => void save(), t,
      }}
      subtitle={tag ? carrierSummary(tag, tn)
        : t("A label for links, captions, tag groups and tags")}
      width={520}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t("Cancel")}</Button>
          <Button variant="primary" icon={clash && tag ? "merge" : "check"}
            onClick={() => void save()}
            disabled={busy || (!tag && (!clean || !!clash))}>
            {!tag ? t("Create") : clash ? t("Merge…") : t("Save")}
          </Button>
        </>
      }
    >
      <div style={{ padding: 18, display: "flex", flexDirection: "column", gap: 16 }}>
        <div>
          <Label>{t("Name")}</Label>
          <input
            ref={firstRef}
            value={name}
            onChange={(e) => setName(sanitizeLinkTagInput(e.target.value))}
            
            style={{ ...field, borderColor: clash ? "var(--accent)" : "var(--border-strong)" }}
          />
          {/* Under the FIELD and only when it says something new — the same
              rule as the item-tag editor, whose comment explains it. */}
          {clash && !tag ? (
            <div style={{ ...noteStyle, color: "var(--red-text)" }}>
              {t("already exists")}
            </div>
          ) : clash ? (
            <div style={{ ...noteStyle, color: "var(--accent)" }}>
              {t("A meta tag with this name already exists — saving offers to merge the two.")}
            </div>
          ) : renaming && tag && tag.count > 0 ? (
            <div style={noteStyle}>
              {tn({ one: "On save, the carrier of this meta tag is updated.",
                    other: "On save, all {n} carriers of this meta tag are updated." },
                  tag.count)}
            </div>
          ) : null}
        </div>

        <div>
          <Label>{t("Comment")}</Label>
          <input
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            
            placeholder={t("What this tag is for…")}
            style={field}
          />
        </div>

        <DescriptionField value={description} onChange={setDescription} />
      </div>
    </Overlay>
  );
}

/** Folding several selected meta tags into one — the list-side counterpart of
 *  the rename-onto-a-taken-name merge above. */
export function MetaTagMergeOverlay({ sources, allTags, onClose, onMerged }: {
  sources: LinkTagRow[];
  allTags: LinkTagRow[];
  onClose: () => void;
  onMerged: (into: string) => void;
}) {
  const t = useT();
  const errText = useErrText();
  const [target, setTarget] = useState(sources[0]?.name ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const clean = sanitizeLinkTagInput(target.trim());
  const existing = useMemo(
    () => allTags.find((x) => x.name === clean) ?? null, [allTags, clean]);
  const isNew = !!clean && existing == null;
  const folded = sources.filter((s) => s.name !== clean);

  const run = async () => {
    if (!clean || folded.length === 0) return;
    setBusy(true);
    try {
      // A rename onto the target IS the merge — the same call the edit
      // overlay makes, once per source.
      if (isNew) await api.createLinkTag(clean);
      for (const src of folded) {
        await api.updateLinkTag({ name: src.name, new_name: clean });
      }
      onMerged(clean);
      onClose();
    } catch (e) {
      setError(errText(e));
      setBusy(false);
    }
  };

  return (
    <Overlay error={error}
      icon="merge"
      title={t("Merge meta tags")}
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
          <Label hint={isNew
            ? t("No meta tag has this name yet — it is created, and everything is folded into it.")
            : t("One of the selected meta tags, or any other: everything is folded into it.")}>
            {t("Merge into")}
          </Label>
          <input
            autoFocus
            value={target}
            onChange={(e) => setTarget(sanitizeLinkTagInput(e.target.value))}
            style={field}
          />
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {sources.map((s) => {
            const isTarget = s.name === clean;
            return (
              <span key={s.name} style={{
                display: "inline-flex", alignItems: "center", gap: 4,
                height: 22, padding: "0 8px", borderRadius: "var(--r-2)",
                fontFamily: "var(--mono)", fontSize: "var(--fs-2)",
                background: isTarget ? "var(--accent-dim)" : "var(--panel-2)",
                border: `1px solid ${isTarget ? "var(--accent)" : "var(--border)"}`,
                color: isTarget ? "var(--accent)" : "var(--muted)",
              }}>
                {s.name}
              </span>
            );
          })}
        </div>

        <div style={{ fontSize: "var(--fs-2)", color: "var(--muted)", lineHeight: 1.55 }}>
          {t("Every link, caption and tag group carrying one of these names carries the target instead; a carrier that held two of them keeps one. Each rename is recorded, so this can be undone.")}
        </div>
      </div>
    </Overlay>
  );
}

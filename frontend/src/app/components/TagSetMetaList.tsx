/** A TAG SET'S OWN META TAGS — the labels it puts on its NAMES.
 *
 *  The right-hand pane of the Sets tab while the sidebar's **Meta tags** row
 *  is picked, and the set's answer to the library's Meta list: same
 *  namespace shape, one tag set along. A meta tag says something about a
 *  NAME — "character", "noflip", "from a booru" — and never about a picture,
 *  which is why it is its own kind of row rather than a tag: `red` the tag
 *  and `red` the meta tag are two different names and always were.
 *
 *  A set carries its own because a tag set that knows `hatsune_miku` is a
 *  `character` is saying something a library has to be told once per name
 *  otherwise; the door carries it over when it CREATES the tag, exactly as
 *  it carries what the name implies.
 *
 *  `uses` is how many of the SET's entries wear the label — the only count a
 *  set can honestly give. What the library does with a label of that name is
 *  the library's own row, in the library's own Meta list.
 */
import React, { useMemo, useState } from "react";
import { EmptyState } from "../../shared/EmptyState";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, type TagSetMetaTagOut } from "../api";
import { useT, useTn, useErrText } from "../i18n";
import { sanitizeLinkTagInput } from "../tags";
import { Icon } from "../../shared/Icon";
import { RowMenu } from "./shared/RowMenu";
import { TOOLBAR_GAP, TOOLBAR_H, TOOLBAR_TOP, toolbarBtn } from "./TagsSidebar";
import { Overlay, fieldStyle as field, FieldLabel as Label } from "../../shared/Overlay";
import { Button } from "../../shared/Button";

/** The three fields a meta tag has, in the dialog every other catalog row
 *  gets. `row` null CREATES one — the same rule the entry editor follows. */
function MetaEditor({ setId, row, taken, onClose, onSaved }: {
  setId: number;
  row: TagSetMetaTagOut | null;
  taken: TagSetMetaTagOut[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useT();
  const errText = useErrText();
  const [name, setName] = useState(row?.name ?? "");
  const [comment, setComment] = useState(row?.comment ?? "");
  const [description, setDescription] = useState(row?.description ?? "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const clean = sanitizeLinkTagInput(name.trim());
  const clash = useMemo(
    () => taken.find((x) => x.name.toLowerCase() === clean.toLowerCase()
                       && x.id !== row?.id) ?? null,
    [taken, clean, row?.id]);
  const dirty = clean !== (row?.name ?? "") || comment !== (row?.comment ?? "")
    || description !== (row?.description ?? "");

  const save = async () => {
    setError("");
    if (!clean) { setError(t("A tag needs a name.")); return; }
    // A CLASH IS A REFUSAL HERE, not a merge: two labels of one tag set
    // are two things somebody wrote down, and folding one into the other
    // would take a comment away without saying so.
    if (clash) { setError(t("already exists")); return; }
    setBusy(true);
    try {
      if (row) {
        await api.updateTagSetMetaTag(setId, row.id,
                                      { name: clean, comment, description });
      } else {
        await api.createTagSetMetaTag(setId, { name: clean, comment, description });
      }
      onSaved();
      onClose();
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Overlay icon="linked_services" width={520}
             title={row ? t("Edit meta tag") : t("Add meta tag")}
             subtitle={t("A label on a NAME, never on a picture.")}
             onClose={onClose}
             unsaved={{ dirty, onSave: save, t }}
             footer={<>
               <Button variant="ghost" onClick={onClose}>{t("Cancel")}</Button>
               <Button variant="primary" icon="check" onClick={save} disabled={busy}>
                 {t("Save")}
               </Button>
             </>}>
      <Label>{t("Name")}</Label>
      <input autoFocus value={name} style={field}
             onChange={(e) => setName(sanitizeLinkTagInput(e.target.value))}
             onKeyDown={(e) => { if (e.key === "Enter") void save(); }} />
      <Label>{t("Comment")}</Label>
      <input value={comment} style={field}
             onChange={(e) => setComment(e.target.value)}
             onKeyDown={(e) => { if (e.key === "Enter") void save(); }} />
      <Label>{t("Description")}</Label>
      <textarea value={description} rows={4}
                style={{ ...field, resize: "vertical" }}
                onChange={(e) => setDescription(e.target.value)} />
      {error && (
        <div style={{ marginTop: 8, color: "var(--red-text)", fontSize: "var(--fs-3)" }}>
          {error}
        </div>
      )}
    </Overlay>
  );
}

export function TagSetMetaList({ setId, readOnly, maxHeight }: {
  setId: number;
  /** A locked set shows its labels and edits none of them. */
  readOnly?: boolean;
  maxHeight?: number;
}) {
  const t = useT();
  const tn = useTn();
  const qc = useQueryClient();
  const [editing, setEditing] = useState<TagSetMetaTagOut | "new" | null>(null);
  const { data: rows } = useQuery({
    queryKey: ["tag-sets", setId, "meta"],
    queryFn: () => api.tagSetMetaTags(setId),
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["tag-sets"] });
  };
  const remove = useMutation({
    mutationFn: (id: number) => api.deleteTagSetMetaTag(setId, id),
    onSuccess: refresh,
  });

  const list = rows ?? [];
  return (
    // THE TAB'S OWN BAND (`TagsSidebar`): this list stands where the tag
    // list does, beside the same tree, so it wears the same toolbar box —
    // the top padding the list toolbar has inside it, the buttons' own
    // height, and the gap its bottom padding leaves. It had none of the
    // three, and started ten pixels above everything around it.
    <div style={{ display: "flex", flexDirection: "column", gap: TOOLBAR_GAP,
                  paddingTop: TOOLBAR_TOP, boxSizing: "border-box",
                  maxHeight, minHeight: 0 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8,
                    minHeight: TOOLBAR_H }}>
        {!readOnly && (
          <button style={toolbarBtn()} onClick={() => setEditing("new")}>
            <Icon name="add" size={15} />{t("Add meta tag…")}
          </button>
        )}
        {/* No count over an empty list: the empty state below already
            says what there is none of. */}
        {list.length > 0 && (
          <div style={{ marginLeft: "auto", color: "var(--muted-2)",
                        fontSize: "var(--fs-3)" }}>
            {tn({ one: "{n} meta tag", other: "{n} meta tags" }, list.length)}
          </div>
        )}
      </div>

      <div style={{ border: "1px solid var(--border)", borderRadius: "var(--r-6)",
                    background: "var(--panel)", overflow: "auto",
                    minHeight: 0, flex: "1 1 auto" }}>
        {list.length === 0 ? (
          <MetaTagsEmpty t={t}
            line={t("This tag set contains no meta tags yet.")} />
        ) : list.map((m) => (
          <div key={m.id}
               style={{ display: "grid", alignItems: "center",
                        gridTemplateColumns: "minmax(0, 2fr) minmax(0, 3fr) 70px 28px",
                        gap: 10, padding: "0 10px", height: 34,
                        borderBottom: "1px solid var(--border)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6,
                          minWidth: 0 }}>
              <Icon name="linked_services" size={14} />
              <span style={{ overflow: "hidden", textOverflow: "ellipsis",
                             whiteSpace: "nowrap" }}>{m.name}</span>
            </div>
            <span title={m.comment}
                  style={{ color: "var(--muted-2)", fontSize: "var(--fs-3)",
                           overflow: "hidden", textOverflow: "ellipsis",
                           whiteSpace: "nowrap" }}>{m.comment}</span>
            {/* HOW MANY OF THIS SET'S ENTRIES WEAR IT — never the library's,
                which is a different tag set's business. */}
            <span style={{ textAlign: "right", color: "var(--muted-2)",
                           fontSize: "var(--fs-3)", fontVariantNumeric: "tabular-nums" }}>
              {m.uses || ""}
            </span>
            {readOnly ? <span /> : (
              <RowMenu title={t("What to do with this meta tag")}
                actions={[
                  { icon: "edit", label: t("Edit…"),
                    onClick: () => setEditing(m) },
                  { icon: "delete", label: t("Delete"), danger: true,
                    separated: true,
                    onClick: () => remove.mutate(m.id) },
                ]} />
            )}
          </div>
        ))}
      </div>

      {editing && (
        <MetaEditor setId={setId} row={editing === "new" ? null : editing}
                    taken={list} onClose={() => setEditing(null)}
                    onSaved={refresh} />
      )}
    </div>
  );
}

/** NOTHING HERE YET, AND WHAT THE THING IS.
 *
 *  Both meta lists open on this — the library's own and a tag set's — so
 *  the word is explained the same way wherever somebody first meets it. An
 *  empty list of something most people have not met is the one place the
 *  word has to carry itself: "no meta tags yet" names the room, not the
 *  thing in it.
 *
 *  A quiet CARD rather than a line of muted prose: centred, with the glyph
 *  the meta capsules wear, so it reads as a note somebody wrote rather than
 *  as a list that failed to load. */
export function MetaTagsEmpty({ line, t }: {
  /** The first line — what is empty, in the caller's own words. */
  line: string;
  t: (s: string) => string;
}) {
  // NO BOX (owner 2026-09). The list this stands in is already a panel with
  // a border of its own, and a second rounded rect inside the first read as
  // a card sitting in an empty list rather than as the list saying what it
  // is for. The glyph and the centring are what make it a note.
  return (
    <EmptyState icon="linked_services" line={line}
      style={{ padding: "44px 16px 48px", color: "var(--text-2)" }}
      hint={<>
        <div style={{ color: "var(--muted-2)" }}>
          {t("Tags describe items. Meta tags describe what describes them — what sort of tag it is, or how it should be treated later: the tag “text” might carry a “not_flippable” meta tag.")}
        </div>
        <div>
          {t("They sit on tags, captions, links and tag groups, never on an item.")}
        </div>
      </>} />
  );
}

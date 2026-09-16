/** WHICH TAG SETS THERE ARE, AND IN WHAT ORDER.
 *
 *  This list was a section of Settings → Tagging (owner 2026-09). Settings
 *  is for preferences; a tag set is library CONTENT — a list of names somebody
 *  imported, with names and counts and categories in it — and the place to
 *  manage the row of them is the row of them, which is the shelf above the
 *  Tags tab's list. So the shelf's "+" became a pencil, and everything it
 *  offered came in here with the rest.
 *
 *  THE LIBRARY'S OWN SET IS PINNED AND IS NOT ONE OF THE OTHERS. It has no
 *  handle, no switch and no delete: it cannot be hidden from itself, it
 *  cannot be moved off the front, and deleting it would mean deleting the
 *  library's tags. The Settings list never read `row.library`, so it offered
 *  all three — against the synthesized id 0 they 404, and against the real
 *  row nothing on the server refused them. `TagSetOut.library` has carried
 *  the words "Not hideable, not deletable, not draggable" the whole time;
 *  this is the first list to act on them.
 *
 *  EVERY VERB A WHOLE SET HAS IS HERE (owner 2026-09) — the pills above the
 *  Tags list carried a ⋯ with the same rows, which could only ever act on a
 *  set whose pill was on screen.
 *
 *  REORDERING APPLIES AT ONCE, as hiding, duplicating and deleting here
 *  already do. A Save button for the order alone, beside four verbs that do
 *  not wait for one, is the split that makes somebody press Cancel and lose
 *  something they thought was done.
 */
import { useState } from "react";
import { dropHalf, gripProps } from "../../shared/useDragRow";
import { Chip } from "../../shared/Chip";
import { EmptyState } from "../../shared/EmptyState";
import { useQueryClient } from "@tanstack/react-query";

import { api, TagSetOut, TagSetTemplateOut } from "../api";
import { compactCount } from "../format";
import { downloadBlob } from "../csv";
import { useErrText, useT, useTn } from "../i18n";
import { bumpEdits } from "../invalidation";
import { Icon } from "../../shared/Icon";
import { Overlay } from "../../shared/Overlay";
import { Button } from "../../shared/Button";
import { RowMenu } from "./shared/RowMenu";
import { Switch } from "../../shared/Switch";

export function TagSetManageOverlay({
  sets, templates, onClose, onNew, onTemplate, onImport, onProperties,
  onExportLibrary, onGone, onChanged,
}: {
  sets: TagSetOut[];
  /** The shipped sets, drawn as rows of the Add menu (see the footer). */
  templates: TagSetTemplateOut[];
  onClose: () => void;
  /** MAKING A SET IS THE MENU ENTRY, not a form (owner 2026-09). Both of
   *  these name the set themselves — an empty one takes a default, a
   *  template takes the template's own — so what was a dialog with a name
   *  field and a template picker in it is the press that made it. */
  onNew: () => Promise<void>;
  onTemplate: (key: string) => Promise<void>;
  onImport: () => void;
  onProperties: (s: TagSetOut) => void;
  /** THE LIBRARY EXPORTS THROUGH ITS OWN ROUTE, never `exportTagSet(id)`:
   *  its set row is lazy and its id may still be the synthesized 0, which
   *  answered 500 — the red number this list used to grow under itself. */
  onExportLibrary: () => void;
  /** A set that has just been deleted, so the shelf can stop showing it. */
  onGone: (id: number) => void;
  onChanged: () => void;
}) {
  const t = useT();
  const tn = useTn();
  const qc = useQueryClient();
  const errText = useErrText();
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<TagSetOut | null>(null);
  //: WHAT THE ADD MENU IS WRITING, if anything. A template is up to 110,868
  //  entries and takes seconds; the dialog this replaced said so with a
  //  spinner, and a footer that simply sat there would read as a press that
  //  had not landed.
  const [making, setMaking] = useState<string | null>(null);
  //: WHICH ROW IS BEING CARRIED, and which it is over — the second with the
  //  edge it would land on, so the line is drawn on the side the row is
  //  travelling towards.
  const [dragId, setDragId] = useState<number | null>(null);
  const [over, setOver] = useState<{ id: number; after: boolean } | null>(null);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["tag-sets"] });
    // The `?` popover's order is per-user and names sets by KEY; a set that
    // arrives or leaves changes what that list can hold, so it is swept too.
    // The old pill drag never did, which left the popover naming a set that
    // had gone until something else invalidated it.
    qc.invalidateQueries({ queryKey: ["tag-set-order"] });
    qc.invalidateQueries({ queryKey: ["tags"] });
    bumpEdits();
    onChanged();
  };
  const run = async (f: () => Promise<unknown>) => {
    try { setError(null); await f(); refresh(); }
    catch (e) { setError(errText(e)); }
  };

  const library = sets.find((s) => s.library) ?? null;
  const rest = sets.filter((s) => !s.library);

  const exportSet = (s: TagSetOut) => void run(async () => {
    const text = await api.exportTagSet(s.id);
    downloadBlob(`${s.key}.json`, new Blob([text], { type: "application/json" }));
  });

  /** `base`, or `base 2`, `base 3`… — a name no set here has. The server
   *  refuses a taken one, and for the library's copy we are the ones
   *  choosing it. */
  const freeName = (base: string) => {
    const taken = new Set(sets.map((x) => x.name.trim().toLowerCase()));
    if (!taken.has(base.toLowerCase())) return base;
    for (let i = 2; ; i++) if (!taken.has(`${base} ${i}`.toLowerCase())) return `${base} ${i}`;
  };

  /** THE LIBRARY'S COPY IS ITS EXPORT, IMPORTED (owner 2026-09), not
   *  `duplicateTagSet`: that reads the SET ROW's entries, and the library's
   *  row holds none — its names are the `tags` table — so it would have
   *  made an empty set and said nothing. The file the Export beside it
   *  writes is exactly what a copy should hold, so the copy is that file
   *  going straight back in. */
  const duplicateLibrary = (s: TagSetOut) => void run(async () => {
    const doc = await api.exportLibrary();
    await api.importTagSet({ ...doc, name: freeName(t("{name} (copy)", { name: s.name })) });
  });

  /** Move the carried set to where it was dropped, and write every position
   *  the move changed. */
  const drop = (overId: number, after: boolean) => {
    const from = dragId;
    setDragId(null);
    setOver(null);
    if (from == null || from === overId) return;
    const order = rest.map((x) => x.id);
    const a = order.indexOf(from);
    if (a < 0) return;
    order.splice(a, 1);
    const b = order.indexOf(overId);
    if (b < 0) return;
    order.splice(b + (after ? 1 : 0), 0, from);
    void run(async () => {
      for (const [i, id] of order.entries()) {
        const was = rest.find((x) => x.id === id);
        if (was && was.position !== i) await api.updateTagSet(id, { position: i });
      }
    });
  };

  /** How far a set that is not offering its names recedes. */
  const DIMMED = 0.55;

  /** One of the Add menu's makers, with its spinner and its error. */
  const makeSet = async (label: string, make: () => Promise<void>) => {
    if (making !== null) return;
    setMaking(label);
    setError(null);
    try { await make(); }
    catch (e) { setError(errText(e)); }
    finally { setMaking(null); }
  };

  const rowStyle = (last: boolean): React.CSSProperties => ({
    display: "flex", alignItems: "center", gap: 10, padding: "10px 14px",
    minHeight: 46,
    borderBottom: last ? "none" : "1px solid var(--border-soft)",
  });

  return (
    <Overlay icon="edit" title={t("Tag sets")} width={560} onClose={onClose}
      /* THE TWO WAYS ANOTHER SET ARRIVES, in ONE menu, and it is the only
         thing in the footer (owner 2026-09). They were two ghost buttons
         over the list with a line of prose under them — three rows of
         chrome above a list that is the point of the dialog. A footer is
         where a dialog's verbs live, and "another set" is one question with
         two answers. It sits at the RIGHT end, where a footer lays its
         children out from: a Close button stood there and is gone, being
         the ✕ in the header said a second time. */
      footer={
        <div style={{ display: "flex", alignItems: "center", gap: 10,
                      marginLeft: "auto" }}>
          {making !== null && (
            <span style={{ display: "flex", alignItems: "center", gap: 6,
                           fontSize: "var(--fs-3)", color: "var(--muted-2)" }}>
              <Icon name="progress_activity" size={15}
                    spin />
              {making ? t("Writing the template's entries…") : t("Creating…")}
            </span>
          )}
          <RowMenu always title={t("Add a tag set")} icon="add"
            label={t("Add")}
            buttonStyle={{
              width: "auto", height: 32, padding: "0 12px", gap: 6,
              borderRadius: "var(--r-4)", border: "1px solid var(--border-strong)",
              background: "var(--panel-2)", color: "var(--text)", fontSize: "var(--fs-3)",
            }}
            color="var(--text)"
            actions={[
              { icon: "note_add", label: t("New empty set"),
                onClick: () => void makeSet("", onNew) },
              { icon: "upload", label: t("Import from file…"),
                onClick: onImport },
              // THE SHIPPED SETS, IN THE MENU (owner 2026-09). They were a
              // picker inside the form this menu replaced, which meant
              // reaching a template was: open the menu, open the dialog,
              // open the picker, pick, press Create. They are what the menu
              // is mostly FOR, so they are its rows — each named, described
              // and sized, since which one to take is the whole question.
              ...templates.map((tp, i) => ({
                icon: "menu_book",
                label: tp.name,
                hint: tp.description,
                trailing: tn({ one: "{n} tag", other: "{n} tags" }, tp.entries,
                             { n: compactCount(tp.entries) }),
                separated: i === 0,
                onClick: () => void makeSet(tp.name, () => onTemplate(tp.key)),
              })),
            ]} />
        </div>
      }>
      <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
        <div style={{ border: "1px solid var(--border-soft)", borderRadius: "var(--r-6)",
                      overflow: "hidden" }}>
          {/* The library, above the rule — a heading rather than row zero. */}
          {library && (
            <div style={{ ...rowStyle(false),
                          background: "var(--panel-2)" }}>
              {/* Where the others have a handle, so the names line up. */}
              <span style={{ width: 16, flex: "0 0 auto" }} />
              <Icon name="grid_view" size={16} color="var(--muted-2)" />
              <div style={{ flex: "1 1 0", minWidth: 0, display: "flex",
                            alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: "var(--fs-3)", color: "var(--text)", overflow: "hidden",
                               textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {library.name}
                </span>
                <span style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", flex: "0 0 auto" }}>
                  {tn({ one: "1 entry", other: "{n} entries" }, library.entries,
                      { n: compactCount(library.entries) })}
                </span>
              </div>
              {/* THE SAME ⋯ THE OTHERS WEAR, LESS THE DELETE — and no
                  hints under the rows either: they said what "Duplicate"
                  and "Export" say, in a menu whose other copy two rows
                  below says them in one word each, so the library's read
                  as a different menu rather than the same one short of a
                  verb. No switch, no handle, no delete: it cannot be
                  hidden from itself, moved off the front, or got rid of
                  without getting rid of the library's tags. */}
              <RowMenu always title={t("More")} actions={[
                { icon: "content_copy", label: t("Duplicate"),
                  onClick: () => duplicateLibrary(library) },
                { icon: "download", label: t("Export"),
                  onClick: onExportLibrary },
              ]} />
            </div>
          )}

          {rest.map((row, i) => (
            <div key={row.id} data-tagsetrow
              onDragOver={(e) => {
                if (dragId == null) return;
                e.preventDefault();
                e.dataTransfer.dropEffect = "move";
                setOver({ id: row.id, after: dropHalf(e) === "after" });
              }}
              onDrop={(e) => {
                e.preventDefault();
                drop(row.id, over?.id === row.id ? over.after : false);
              }}
              // A CARRIED row ghosts WHOLE; a DISABLED one dims only what
              // the switch is about (owner 2026-09) — the icon, the name
              // and the words under it. Over the row it took the handle,
              // the buttons and the switch itself with it, so the one
              // control that says "off" was drawn half-off, and the way
              // back was the faintest thing on the row.
              style={{ ...rowStyle(i === rest.length - 1),
                       opacity: dragId === row.id ? 0.4 : 1,
                       boxShadow: over && over.id === row.id && dragId != null
                         ? (over.after ? "0 3px 0 0 var(--accent)"
                                       : "0 -3px 0 0 var(--accent)")
                         : undefined }}>
              {/* THE HANDLE IS PAINTED, NOT REVEALED ON HOVER. Every hover
                  reveal in this app is scoped to `body:not(.mc-dragging)`
                  (`tokens.css`), so a revealed grip turns invisible the
                  instant its own drag starts and WebKit cancels the drag.
                  It sets data and its own drag image, or the ghost is the
                  glyph and Chrome may decline the drag outright. */}
              <span title={t("Drag to reorder")}
                {...gripProps({ payload: `tagset:${row.id}`, rowAttr: "[data-tagsetrow]",
                                enabled: rest.length > 1,
                                onStart: () => setDragId(row.id),
                                onEnd: () => { setDragId(null); setOver(null); } })}
                style={{ display: "flex", alignItems: "center", flex: "0 0 auto",
                         color: "var(--muted-2)",
                         cursor: rest.length > 1 ? "grab" : "default",
                         visibility: rest.length > 1 ? "visible" : "hidden" }}>
                <Icon name="drag_indicator" size={16} />
              </span>
              <span style={{ display: "flex", flex: "0 0 auto",
                             opacity: row.enabled ? 1 : DIMMED }}>
                <Icon name={row.builtin ? "inventory_2" : "menu_book"}
                      size={16} color="var(--muted-2)" />
              </span>
              <div style={{ flex: "1 1 0", minWidth: 0,
                            opacity: row.enabled ? 1 : DIMMED }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8,
                              minWidth: 0 }}>
                  <span style={{ fontSize: "var(--fs-3)", color: "var(--text)", overflow: "hidden",
                                 textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {row.name}
                  </span>
                  {row.builtin && (
                    <Chip size="sm" upper bordered style={{ background: "transparent" }}>{t("Built-in")}</Chip>
                  )}
                  <span style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", flex: "0 0 auto" }}>
                    {tn({ one: "1 entry", other: "{n} entries" }, row.entries,
                        { n: compactCount(row.entries) })}
                  </span>
                </div>
                {row.description && (
                  <div className="mc-copy" style={{
                    fontSize: "var(--fs-2)", color: "var(--muted)", lineHeight: 1.45, marginTop: 2,
                    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                  }}>{row.description}</div>
                )}
              </div>
              {/* PROPERTIES IS ITS OWN BUTTON (owner 2026-09): it is the
                  one verb here that opens the set rather than acting on it
                  — the name, the description and the two advice switches —
                  and it was a row deep in a menu beside four things that
                  happen on the spot. */}
              <span className="hoverable" role="button" title={t("Properties…")}
                    onClick={() => onProperties(row)}
                    style={{ display: "flex", alignItems: "center",
                             justifyContent: "center", width: 20, height: 20,
                             borderRadius: "var(--r-2)", flex: "0 0 auto", cursor: "pointer",
                             color: "var(--muted-2)" }}>
                <Icon name="tune" size={16} />
              </span>
              {/* THE ⋯ SITS BEFORE THE SWITCH, not after it: the switch is
                  the one control on this row that answers with a state, so
                  it belongs at the end where the eye reads down a column of
                  them. NO Move up / Move down either — the handle beside the
                  name is the reorder now, and two ways to do it is one of
                  them going stale. */}
              <RowMenu always title={t("More")} actions={[
                { icon: "content_copy", label: t("Duplicate"),
                  hint: row.builtin ? t("A copy you can edit") : undefined,
                  onClick: () => void run(() => api.duplicateTagSet(
                    row.id, t("{name} (copy)", { name: row.name }))) },
                { icon: "download", label: t("Export"),
                  onClick: () => exportSet(row) },
                { icon: "delete", label: t("Delete"), danger: true, separated: true,
                  onClick: () => setConfirm(row) },
              ]} />
              <Switch checked={row.enabled}
                      onChange={(v) => void run(() => api.setTagSetEnabled(row.id, v))}
                      title={row.enabled ? t("Enabled") : t("Disabled")} />
            </div>
          ))}

          {rest.length === 0 && (
            <EmptyState dense line={t("No tag sets imported yet.")}
                        style={{ padding: "14px 16px", fontSize: "var(--fs-3)" }} />
          )}
        </div>

        {error && (
          <div style={{ fontSize: "var(--fs-2)", color: "var(--red-text)" }}>{error}</div>
        )}
      </div>

      {confirm && (
        <Overlay icon="delete" title={t("Delete tag set")} width={420}
          onClose={() => setConfirm(null)}
          footer={<>
            <Button variant="ghost" onClick={() => setConfirm(null)}>{t("Cancel")}</Button>
            <Button variant="danger" icon="delete" onClick={() => {
              const row = confirm;
              setConfirm(null);
              void run(async () => {
                await api.deleteTagSet(row.id);
                onGone(row.id);
              });
            }}>{t("Delete")}</Button>
          </>}>
          <div className="mc-copy" style={{ padding: 18, fontSize: "var(--fs-3)",
                                            color: "var(--text-2)", lineHeight: 1.55 }}>
            {t("Delete “{name}”? Its categories and entries go with it. The library's tags are untouched.",
               { name: confirm.name })}
          </div>
        </Overlay>
      )}
    </Overlay>
  );
}

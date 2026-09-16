/** THE RANKING EDITOR — a ranking's name, its rating scale and its pools.
 *
 *  All that is left of what was the Rankings sub-tab (owner 2026-09). That
 *  page was a table of three or four rows with a search box over it, and a
 *  histogram of 54-pixel thumbnails folded out of each — thumbnails whose own
 *  comment conceded they were "not enough to answer the question the
 *  histogram is read to ask: whether this one really belongs at 9". The
 *  pictures were the answer, so a ranking is a VIEW of the library now (the
 *  sidebar's Rankings row), its standings are the grid's own sections, and
 *  what it IS reads in the right-hand panel.
 *
 *  This dialog survived all of it unchanged, because it was never part of
 *  that page: it is opened from the grid's Rate row when there is no ranking
 *  to rate on, from the Rate chooser, and from a ranking row's own menu.
 */
import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { dropHalf, gripProps } from "../../shared/useDragRow";
import { filterNumeric } from "../../shared/useNumericText";
import { FieldLabel, fieldStyleSm } from "../../shared/Field";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, RankingBucketOut, RankingItemRef, RankingRow } from "../api";
import { exactFirst } from "../exactFirst";
import { Icon } from "../../shared/Icon";
import { useT, useTn, useErrText } from "../i18n";
import { Overlay } from "../../shared/Overlay";
import { Button } from "../../shared/Button";
import { tagFieldName } from "../tags";
import { RowMenu } from "./shared/RowMenu";
import { useUI } from "../store";

// The field and its label are the shared ones (`shared/Field.tsx`).
const field = fieldStyleSm;
const Label = FieldLabel;

const slugify = (name: string) =>
  name.trim().toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "_")
    .replace(/^_|_$/g, "").replace(/:/g, "_");


/** One row of the editor's Pools list. `initial` is the name the dialog
 *  opened with — null for a row added here, which must be named before the
 *  dialog can save; "" for the unnamed default, which may stay unnamed. */
type PoolDraft = { id: number | null; name: string; initial: string | null;
                     judgments: number };

export function RankingEditOverlay({ ranking, onClose, onSaved }: {
  /** null = a new ranking. */
  ranking: RankingRow | null;
  onClose: () => void;
  /** Called with the list the API answered with — a caller that has to act
   *  on the row just made (the grid's Rate batch) has no other way to name
   *  it, since create answers with the whole catalog. */
  onSaved: (rows?: RankingRow[]) => void;
}) {
  const t = useT();
  const tn = useTn();
  const errText = useErrText();
  const [name, setName] = useState(ranking?.name ?? "");
  /** THE LEAGUES, edited as a list and diffed at Save — deletes first (they
   *  free names), then renames, then the rows added here. A new ranking
   *  starts with one row standing for the unnamed pool `create` makes:
   *  naming it is a rename after the create, and every row after it is a
   *  pool of its own. Always at least one row. */
  // THE UNNAMED LEAGUE'S ROW HOLDS "Default" AS ITS VALUE — the word it is
  // listed under everywhere — rather than as a placeholder, which read as
  // a ranking with no pool at all. Saving that word back (or clearing
  // it) leaves the pool unnamed; any other word is a rename.
  const initialPools: PoolDraft[] = ranking
    ? (ranking.pools ?? []).map((l) => ({ id: l.id,
                                           name: l.name || t("Default"),
                                           initial: l.name,
                                           judgments: l.judgments }))
    : [{ id: null, name: t("Default"), initial: "", judgments: 0 }];
  const [pools, setPools] = useState<PoolDraft[]>(initialPools);
  // The drag: which row is in the hand, and where it would land — the tag
  // batch chooser's list, one dialog over.
  const [dragIdx, setDragIdx] = useState<number | null>(null);
  const [over, setOver] = useState<{ idx: number; after: boolean } | null>(
    null);
  const dropAt = (idx: number, after: boolean) => {
    if (dragIdx == null) return;
    let to = after ? idx + 1 : idx;
    if (to > dragIdx) to -= 1;
    if (to === dragIdx) return;
    setPools((cur) => {
      const next = cur.slice();
      const [moved] = next.splice(dragIdx, 1);
      next.splice(to, 0, moved);
      return next;
    });
  };
  const poolsOk = pools.every((l) => l.name.trim() || l.initial === "");
  /** COMPARISONS THAT GO with the pools taken off the list. Removing a
   *  pool that has been rated in deletes its judgments, and that cannot
   *  be undone — so the row's ✕ never asks (a browser prompt at a click
   *  that only edits a draft, and one that some browsers never show);
   *  instead the SAVE turns red and asks once, in the dialog, for the lot. */
  const pendingDeletes = initialPools
    .filter((l) => l.id != null && !pools.some((x) => x.id === l.id))
    .reduce((n, l) => n + l.judgments, 0);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const poolsDirty = JSON.stringify(pools.map((l) => [l.id, l.name.trim()]))
    !== JSON.stringify(initialPools.map((l) => [l.id, l.name.trim()]));
  const [lo, setLo] = useState(String(ranking?.bucket_lo ?? 0));
  const [hi, setHi] = useState(String(ranking?.bucket_hi ?? 9));
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  // The number-field rule: an empty field is "not yet", anything that is not
  // a whole number never lands in the state.
  const whole = (v: string) => filterNumeric(v, { integer: true, maxLen: 3 });
  const loN = lo === "" ? null : Number(lo);
  const hiN = hi === "" ? null : Number(hi);
  const rangeOk = loN !== null && hiN !== null && loN < hiN
    && loN >= 0 && hiN <= 100;

  const dirty = ranking
    ? name !== ranking.name
      || loN !== ranking.bucket_lo || hiN !== ranking.bucket_hi
      || poolsDirty
    : !!name.trim() || poolsDirty;

  const save = async (confirmed = false) => {
    if (saving || !name.trim() || !rangeOk || !poolsOk) return;
    if (pendingDeletes > 0 && !confirmed) { setConfirmDelete(true); return; }
    setConfirmDelete(false);
    setSaving(true);
    setError("");
    try {
      let rid: number;
      let current: PoolDraft[] = pools;
      if (ranking) {
        await api.updateRanking(ranking.id, { name: name.trim(),
                                              bucket_lo: loN ?? undefined,
                                              bucket_hi: hiN ?? undefined });
        rid = ranking.id;
        for (const l of initialPools) {
          if (l.id != null && !pools.some((x) => x.id === l.id)) {
            await api.deleteRankingPool(rid, l.id);
          }
        }
      } else {
        const rows = await api.createRanking({ name: name.trim(),
                                               bucket_lo: loN ?? 0,
                                               bucket_hi: hiN ?? 9 });
        const made = rows.find((r) => r.name === name.trim());
        if (!made) throw new Error("the ranking was not created");
        rid = made.id;
        // The first row IS the unnamed pool the create made.
        const born = made.pools?.[0];
        current = pools.map((l, i) => (i === 0 && born
          ? { ...l, id: born.id, initial: "" } : l));
      }
      let rows: RankingRow[] | null = null;
      for (const l of current) {
        const nm = l.name.trim();
        if (l.id != null) {
          const unnamedStill = l.initial === "" && nm === t("Default");
          if (nm && nm !== (l.initial ?? "") && !unnamedStill) {
            rows = await api.renameRankingPool(rid, l.id, nm);
          }
        } else if (nm) {
          rows = await api.createRankingPool(rid, nm);
        }
      }
      // THE ORDER, last: the rows as they stand in the dialog, a row made a
      // moment ago found by its name in the list the create answered with.
      rows = rows ?? await api.rankings();
      const mine = rows.find((r) => r.id === rid);
      if (mine) {
        const byName = new Map(mine.pools.map((l) => [l.name, l.id]));
        const order = current.map((l) => l.id ?? byName.get(l.name.trim()))
          .filter((x): x is number => x != null);
        const now = mine.pools.map((l) => l.id);
        if (order.length === now.length
            && order.some((x, i) => x !== now[i])) {
          await api.reorderRankingPools(rid, order);
        }
      }
      onSaved(await api.rankings());
    } catch (e) {
      setError(errText(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Overlay icon="leaderboard" onSubmit={() => void save()}
      title={ranking ? t("Edit ranking") : t("New ranking")}
      width={460} onClose={onClose}
      unsaved={{ dirty, onSave: () => save(true), t }}
      footer={confirmDelete ? (
        // THE QUESTION, in the dialog: what goes, and the one red way on.
        <>
          <span style={{ flex: 1, fontSize: "var(--fs-3)", color: "var(--red-text)",
                         lineHeight: 1.4 }}>
            {tn({ one: "Removing the pool deletes 1 comparison — this cannot be undone.",
                  other: "Removing the pool deletes {n} comparisons — this cannot be undone." },
                pendingDeletes)}
          </span>
          <Button variant="ghost" onClick={() => setConfirmDelete(false)}>
            {t("Cancel")}
          </Button>
          <Button variant="danger" icon="delete" onClick={() => void save(true)}
            disabled={saving}>
            {saving ? t("Saving…") : t("Delete and save")}
          </Button>
        </>
      ) : (
        <>
          <Button variant="ghost" onClick={onClose}>{t("Cancel")}</Button>
          <Button variant={pendingDeletes > 0 ? "danger" : "primary"}
            icon={pendingDeletes > 0 ? "delete" : "check"}
            onClick={() => void save()}
            disabled={!name.trim() || !rangeOk || !poolsOk || saving}>
            {saving ? t("Saving…") : ranking ? t("Save") : t("Create")}
          </Button>
        </>
      )}>
      <div style={{ padding: 16, display: "flex", flexDirection: "column",
                    gap: 14 }}>
        <div>
          <Label>{t("Name")}</Label>
          <input style={field} value={name} autoFocus
            placeholder={t("Quality")}
            onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          {/* THE SCALE. It was headed "Buckets" beside a tag prefix, and
              the pair read as the names of the tags the ranking would mint.
              It mints nothing (rung v31): this is the range the standings
              are spread over, and what the Assign-ratings rules are
              written against. */}
          <Label>{t("Rating scale")}</Label>
          <div style={{ marginTop: -2, marginBottom: 7, fontSize: "var(--fs-2)",
                        color: "var(--muted-2)", lineHeight: 1.45 }}>
            {t("The numbers this axis counts in. The best picture reads as the top of the range and the worst as the bottom, however many there are.")}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input style={{ ...field, width: 72, textAlign: "right",
                            fontFamily: "var(--mono)" }}
              value={lo} inputMode="numeric"
              onChange={(e) => { const v = whole(e.target.value);
                                 if (v !== null) setLo(v); }} />
            <span style={{ color: "var(--muted-2)" }}>…</span>
            <input style={{ ...field, width: 72, textAlign: "right",
                            fontFamily: "var(--mono)" }}
              value={hi} inputMode="numeric"
              onChange={(e) => { const v = whole(e.target.value);
                                 if (v !== null) setHi(v); }} />
          </div>
        </div>
        <div>
          <Label>{t("Pools")}</Label>
          <div style={{ marginTop: -2, marginBottom: 7, fontSize: "var(--fs-2)",
                        color: "var(--muted-2)", lineHeight: 1.45 }}>
            {t("Every pool has its own buckets — items rated in it are sorted apart from the other pools.")}
          </div>
          {/* The populations the ranking is computed over — each with
              standings of its own under the one scale. One row is always
              there (the unnamed default, which may stay unnamed); a row
              added here has to be named. Deleting one takes its
              comparisons with it, so it asks. */}
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {pools.map((l, i) => (
              <div key={l.id ?? `new-${i}`} data-poolrow=""
                onDragOver={(e) => {
                  if (dragIdx == null) return;
                  e.preventDefault();
                  e.dataTransfer.dropEffect = "move";
                  const after = dropHalf(e) === "after";
                  if (!over || over.idx !== i || over.after !== after) {
                    setOver({ idx: i, after });
                  }
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  if (over) dropAt(over.idx, over.after);
                  setDragIdx(null); setOver(null);
                }}
                style={{ display: "flex", alignItems: "center", gap: 6,
                         borderRadius: "var(--r-4)",
                         opacity: dragIdx === i ? 0.4 : 1,
                         // The insertion line as a shadow on the row's
                         // edge, so nothing moves while the drag is in hand.
                         boxShadow: over && over.idx === i && dragIdx != null
                           ? (over.after ? "0 3px 0 0 var(--accent)"
                                         : "0 -3px 0 0 var(--accent)")
                           : undefined }}>
                {/* THE GRIP drags (only while there is something to
                    reorder). It sets data and its own drag image — a
                    drag carrying nothing may be declined, and the ghost
                    would otherwise be the glyph. */}
                {pools.length > 1 && (
                  <span title={t("Drag to reorder")}
                    {...gripProps({ payload: String(i), rowAttr: "[data-poolrow]",
                                    onStart: () => setDragIdx(i),
                                    onEnd: () => { setDragIdx(null); setOver(null); } })}
                    style={{ display: "flex", alignItems: "center",
                             cursor: "grab", color: "var(--muted-2)",
                             flex: "0 0 auto" }}>
                    <Icon name="drag_indicator" size={16} />
                  </span>
                )}
                {/* The scores switch is NOT here: it acts at once, and it
                    lives in the detail's pool heading, beside the
                    histogram it is about. One control with two behaviours —
                    an eye that takes effect on Save in one place and on the
                    click in another — is worse than one place to press it. */}
                <input style={field} value={l.name}
                  placeholder={l.initial === "" ? t("Default") : t("Name")}
                  onChange={(e) => setPools((cur) => cur.map((x, j) =>
                    j === i ? { ...x, name: e.target.value } : x))} />
                {pools.length > 1 && (
                  <span className="hoverable"
                    title={t("Remove this pool")}
                    onClick={() => setPools((cur) =>
                      cur.filter((_, j) => j !== i))}
                    style={{ display: "flex", width: 26, height: 26,
                             alignItems: "center", justifyContent: "center",
                             borderRadius: "var(--r-2)", cursor: "pointer",
                             color: "var(--muted-2)", flex: "0 0 auto" }}>
                    <Icon name="close" size={15} />
                  </span>
                )}
              </div>
            ))}
            <span className="hoverable"
              onClick={() => setPools((cur) => [...cur,
                { id: null, name: "", initial: null, judgments: 0 }])}
              style={{ display: "inline-flex", alignItems: "center", gap: 5,
                       alignSelf: "flex-start", padding: "4px 8px",
                       borderRadius: "var(--r-2)", cursor: "pointer", fontSize: "var(--fs-3)",
                       color: "var(--accent)" }}>
              <Icon name="add" size={15} />
              {t("Add pool")}
            </span>
          </div>
        </div>
        {error && (
          <div style={{ fontSize: "var(--fs-3)", color: "var(--red-text)" }}>{error}</div>
        )}
      </div>
    </Overlay>
  );
}

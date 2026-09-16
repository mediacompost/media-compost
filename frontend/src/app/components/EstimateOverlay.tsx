/** ESTIMATE RATINGS — a ranking's scale carried to the pictures it has never
 *  been shown, and tags written where somebody says the number matters.
 *
 *  Not a session: an ordinary dialog that makes ONE bulk write. The rating
 *  overlay asks a pair at a time and the answers ARE the evidence; this
 *  spends that evidence — the standings, over the same embedding spaces the
 *  tag batch orders by — on the rest of the library.
 *
 *  It does not write score tags, and cannot: those are derived rows with one
 *  writer (`ops/rankings.rebuild`), refit from the judgments whenever
 *  anything moves, so a guess written as one would be silently rewritten by
 *  the next refit — and would claim the axis had been RATED there. The rules
 *  write ordinary tags and group memberships, exactly as configured.
 *
 *  The FOOTER is a preview, always: the same request with `preview`, so the
 *  counts on screen are the counts the button would write, by the only route
 *  there is.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { storage } from "../../shared/storage";
import { Chip } from "../../shared/Chip";
import { filterNumeric } from "../../shared/useNumericText";
import { fieldStyleSm } from "../../shared/Field";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api, RankingEstimateOut, RankingItemRef, RankingRow } from "../api";
import { Icon } from "../../shared/Icon";
import { ConfirmModal } from "../../shared/ConfirmModal";
import { useT, useTn, useErrText } from "../i18n";
import { Overlay } from "../../shared/Overlay";
import { Button } from "../../shared/Button";
import { AnchoredDropdown, useAnchorRect } from "../../shared/AnchoredDropdown";
import { EmbedModelPicker } from "./EmbedModelPicker";
import { CombinedTagEditor } from "./CombinedTagEditor";
import { flattenGroupTree } from "./GroupSelect";
import { fetchTagNameSuggestions } from "./TagAutocomplete";
import { card, OptionRow, sectionLabel } from "./ImportOverlay";
import { parseQuickWord } from "../quickTags";
import { FUSED, embeddersOf } from "../tagSort";
import { useViewScope } from "../useItems";
import { useUI } from "../store";
import { useDebouncedValue } from "../../shared/useDebounced";
import { useBackdropDismiss } from "../../shared/Backdrop";
import { LAYER } from "../../shared/layers";
import { useMenuDismiss } from "../../shared/useMenuDismiss";

/** One rule: a comparison on the ranking's own scale, and what to write
 *  where it holds. The write is quick assign's own shape — tags with a
 *  sign, and groups to join — because it IS that: a stamp over whatever
 *  the estimate claims. */
interface Rule {
  /** React key, session-local. */
  id: string;
  /** Where this BAND STARTS. The bands are the rules sorted by this
   *  number, each running up to the next one's start and the last with no
   *  top, so they partition the scale and a picture is in exactly one. It
   *  was a pair of inclusive ends ("8 and up", "between 4 and 6") — two
   *  fields somebody had to keep from overlapping by hand, in a shape
   *  where one picture could be claimed by three rules at once. */
  lo: string;
  pos: string[];
  neg: string[];
  groups: number[];
}

const mintId = () =>
  `r${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

const emptyRule = (lo = ""): Rule => ({ id: mintId(), lo,
                                        pos: [], neg: [], groups: [] });

/** ONE ROW PER BUCKET, which is what a fresh dialog opens on: the scale's
 *  own numbers, each band covering exactly its own bucket. Filling them in
 *  is then typing the tags, not working out where the bands go. */
const defaultRules = (lo: number, hi: number): Rule[] =>
  Array.from({ length: Math.max(1, hi - lo + 1) },
             (_x, i) => emptyRule(String(lo + i)));

const num = (v: string): number | null =>
  (v.trim() === "" ? null : Number(v));

/** A rule as the API takes it: the sign rides in the NAME, the importer's
 *  leading `-`. */
function wireRule(r: Rule) {
  return { min: num(r.lo),
           tags: [...r.pos, ...r.neg.map((n) => `-${n}`)],
           groups: r.groups };
}

/** A rule the request can carry: it has to say WHERE its band starts.
 *
 *  A band with nothing to write in it still travels — the server writes
 *  nothing for it, and leaving it out would silently widen its neighbours,
 *  which is not what the row on screen says. */
const ruleIsSet = (r: Rule) => r.lo.trim() !== "";

/** The rules in BAND ORDER — the same arithmetic the server does, so the
 *  row can say what it takes — HIGHEST FIRST, which is how a rating scale
 *  is read and what lets the card read as the scale itself. */
function banded(rules: Rule[]): { rule: Rule; hi: number | null }[] {
  const up = rules.filter(ruleIsSet)
    .sort((a, b) => Number(a.lo) - Number(b.lo));
  return up.map((r, i) => ({
    rule: r, hi: i + 1 < up.length ? Number(up[i + 1].lo) : null })).reverse();
}

/** THE RULES, REMEMBERED PER RANKING — per viewer, in this browser, the way
 *  the T field's history and the pane widths are. A set of bands with tags
 *  in them is a page of typing and it is the same page every time the same
 *  axis is spent. */
const RULES_KEY = "mc.estimate.rules";

function readEstimateRules(rid: number): Rule[] | null {
  try {
    const all = JSON.parse(storage.get(RULES_KEY) || "{}");
    const got = all?.[String(rid)];
    if (!Array.isArray(got) || got.length === 0) return null;
    // Minted afresh: the id is a REACT KEY and two dialogs in one session
    // would otherwise share one.
    return got.map((r: Partial<Rule>) => ({
      id: mintId(), lo: String(r.lo ?? ""),
      pos: Array.isArray(r.pos) ? r.pos.map(String) : [],
      neg: Array.isArray(r.neg) ? r.neg.map(String) : [],
      groups: Array.isArray(r.groups) ? r.groups.map(Number) : [],
    }));
  } catch { return null; }
}

function writeEstimateRules(rid: number, rules: Rule[]): void {
  try {
    const all = JSON.parse(storage.get(RULES_KEY) || "{}");
    all[String(rid)] = rules.map(({ lo, pos, neg, groups }) =>
      ({ lo, pos, neg, groups }));
    storage.set(RULES_KEY, JSON.stringify(all));
  } catch { /* a private window, or site data turned off */ }
}

/** The rule cards' compact field: the shared dense field, one step
 *  shorter and on the deep ground the cards sit on. */
const compactField: React.CSSProperties = {
  ...fieldStyleSm, width: undefined, height: 28, padding: "0 8px",
  background: "var(--bg-deep)", border: "1px solid var(--border)", borderRadius: "var(--r-3)",
};

/** A row of one of the cards — the import overlay's seam rule: the row
 *  ABOVE owns the line, and the last row of a card draws none. */
const rowStyle = (last?: boolean): React.CSSProperties => ({
  padding: "10px 14px",
  borderBottom: last ? "none" : "1px solid var(--border-soft)",
});

export function EstimateOverlay() {
  const open = useUI((s) => s.estimateOpen);
  const setOpen = useUI((s) => s.setEstimateOpen);
  if (!open) return null;
  return <EstimateDialog onClose={() => setOpen(false)} />;
}

function EstimateDialog({ onClose }: { onClose: () => void }) {
  const t = useT();
  const tn = useTn();
  const errText = useErrText();
  const qc = useQueryClient();
  const view = useViewScope(true);
  const selected = useUI((s) => s.selectedItems);

  const { data: rankings } = useQuery({ queryKey: ["rankings"],
                                        queryFn: () => api.rankings() });
  const rows: RankingRow[] = rankings ?? [];
  const [rankingId, setRankingId] = useState<number | null>(null);
  const ranking = rows.find((r) => r.id === rankingId) ?? rows[0] ?? null;
  useEffect(() => {
    if (rankingId == null && rows.length) setRankingId(rows[0].id);
  }, [rankingId, rows]);

  /** WHICH LEAGUES the standings are read from — empty is every one of
   *  them, which is what a ranking with one pool always means. Kept per
   *  ranking, so switching back does not lose the pick. */
  const [poolsBy, setPoolsBy] = useState<Record<number, number[]>>({});
  const pools = ranking ? (poolsBy[ranking.id] ?? []) : [];
  const setPools = (ids: number[]) => {
    if (ranking) setPoolsBy((m) => ({ ...m, [ranking.id]: ids }));
  };

  /** THE RULES, KEPT PER RANKING AND PER VIEWER. A set of bands with tags
   *  in them is a page of typing, and it is the same page every time the
   *  same axis is spent — so it comes back. Its own state, not the
   *  library's: it is what THIS person wants written, the way the T
   *  field's history and the sidebar widths are (`localStorage`). */
  const [rulesBy, setRulesBy] = useState<Record<number, Rule[]>>({});
  const rules = ranking ? (rulesBy[ranking.id] ?? []) : [];
  const setRules = (f: (cur: Rule[]) => Rule[]) => {
    if (!ranking) return;
    setRulesBy((m) => ({ ...m, [ranking.id]: f(m[ranking.id] ?? []) }));
    setQueued(false);
  };
  // A ranking with nothing stored opens on ONE ROW PER BUCKET.
  useEffect(() => {
    if (!ranking || rulesBy[ranking.id]) return;
    const kept = readEstimateRules(ranking.id);
    setRulesBy((m) => ({
      ...m,
      [ranking.id]: kept
        ?? defaultRules(ranking.bucket_lo, ranking.bucket_hi) }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ranking?.id]);
  useEffect(() => {
    if (ranking && rulesBy[ranking.id]) {
      writeEstimateRules(ranking.id, rulesBy[ranking.id]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ranking?.id, rules]);
  /** WHETHER THE BANDS ARE STILL THE ONES A FRESH DIALOG OPENS ON — one per
   *  bucket, nothing written in any of them. What the Reset button hangs on:
   *  a button that would change nothing reads as one that does. Compared by
   *  the BANDS in order rather than by the array, since a row added later
   *  sits at the end of it and is still the same set of bands. */
  const atDefaultRules = useMemo(() => {
    if (!ranking) return true;
    const want = defaultRules(ranking.bucket_lo, ranking.bucket_hi)
      .map((r) => r.lo);
    const have = [...rules].sort((a, b) => Number(a.lo) - Number(b.lo));
    return have.length === want.length
      && have.every((r, i) => Number(r.lo) === Number(want[i])
                    && !r.pos.length && !r.neg.length && !r.groups.length);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ranking?.id, ranking?.bucket_lo, ranking?.bucket_hi, rules]);
  //: RESETTING ASKS FIRST. The bands are a page of typing somebody may have
  //  built up over several sessions (they are remembered per ranking), and
  //  one press putting all of it back to empty is not something to find out
  //  about afterwards — there is no undo for a dialog's own state.
  const [resetting, setResetting] = useState(false);
  /** GUESS AT THE PICTURES THE RANKING HAS NOT PLACED as well. Off, only
   *  the ones it HAS are covered, each at its own standing — the honest
   *  floor of the action: what somebody actually judged, written down. It
   *  was a three-way "Apply to"; the question is one thing being turned
   *  on, and the third answer ("only the guesses") was one nobody wants —
   *  the pictures you rated are the ones you are surest about. */
  const [estimateUnranked, setEstimateUnranked] = useState(true);
  const [embedder, setEmbedder] = useState(FUSED);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  /** The write has been QUEUED — the dialog's last state. Not "what was
   *  written": a background job answers that in the task list, over the
   *  minutes it takes, and a dialog claiming a total the moment it queued
   *  would be making one up. */
  const [queued, setQueued] = useState(false);

  // ---- the embedders, the tag grid's own picker over the same list -------
  const { data: mlModels } = useQuery({ queryKey: ["ml-models"],
                                        queryFn: api.mlModels });
  const { data: modelCache } = useQuery({ queryKey: ["model-cache"],
                                          queryFn: api.modelCache });
  const embedModels = useMemo(() => {
    const cached = new Map((modelCache?.models ?? [])
      .map((m) => [m.key, m.cached]));
    const task = (mlModels?.tasks ?? []).find((tk) => tk.kind === "embed");
    return (task?.models ?? []).map((m) => ({
      id: m.id, name: m.name, family: m.family,
      ready: m.available
        && (m.family_keys ?? []).every((k) => cached.get(k) !== false),
    }));
  }, [mlModels, modelCache]);
  const pickerModels = useMemo(() => {
    const list = embedModels.map((m) => ({ id: m.id, name: m.name,
                                           family: m.family }));
    if (embedModels.length >= 2) {
      list.push({ id: FUSED,
                  name: embedModels.map((m) => m.name).join(" + "),
                  family: "fused" });
    }
    return list;
  }, [embedModels]);
  const embedders = embeddersOf(embedder, embedModels.map((m) => m.id));
  const embedderChoice = embedder === FUSED && embedModels.length >= 2
    ? FUSED : (embedders[0] ?? embedder);

  // ---- the groups a rule can put a picture in ----------------------------
  const { data: tree } = useQuery({ queryKey: ["groups"],
                                    queryFn: api.groups });
  const groupOptions = useMemo(() => flattenGroupTree(tree ?? []), [tree]);

  /** The scope, frozen when the dialog opens — the grid can page under it,
   *  and what the footer counted has to be what the button writes. The
   *  SELECTION is frozen with it, for the same reason. */
  const scopeRef = useRef<Record<string, unknown> | null>(null);
  const pickedRef = useRef<number[] | null>(null);
  if (scopeRef.current == null) {
    scopeRef.current = { ...(view.req as object) };
    pickedRef.current = [...selected];
  }
  const picked = pickedRef.current ?? [];
  /** ONLY THE SELECTED PICTURES — off by default. The other two things this
   *  menu opens are SESSIONS, where a selection leads the queue and never
   *  fences it; this is one bulk write, so a selection could only mean
   *  "just these" — and taking that silently made the action a different
   *  action depending on what happened to be lit in the grid behind the
   *  dialog. It says so and asks instead. */
  const [onlyPicked, setOnlyPicked] = useState(false);
  const items = onlyPicked && picked.length > 0 ? picked : undefined;

  const wire = useMemo(() => rules.filter(ruleIsSet).map(wireRule), [rules]);
  const ready = ranking != null && wire.length > 0 && embedders.length > 0;

  // THE FOOTER IS THE SAME REQUEST. A preview of a different shape would be
  // a second answer to argue with; this is the button's own, with the write
  // withheld. DEBOUNCED, because a preview is the whole estimate: the fit
  // over every rated picture and a prediction over the scope.
  const previewKey = useDebouncedValue(
    JSON.stringify([ranking?.id, wire, estimateUnranked, embedders,
                    items ?? null, pools]), 400);
  const keyReady = useMemo(() => {
    const [rid, rs, , spaces] = JSON.parse(previewKey);
    return rid != null && rs.length > 0 && spaces.length > 0;
  }, [previewKey]);
  const { data: preview, error: previewError, isFetching } = useQuery({
    queryKey: ["estimate-preview", previewKey],
    // THE KEY IS THE REQUEST. Read back out of it rather than off the live
    // state, or the debounce would show one thing and ask for another.
    queryFn: () => {
      const [rid, rs, to, spaces, only, lg] = JSON.parse(previewKey);
      return api.estimateRanking(rid, {
        ...(scopeRef.current as object ?? {}),
        ...(only ? { items: only } : {}),
        embedders: spaces, rules: rs, estimate_unranked: to,
        pool_ids: lg,
      } as unknown as Parameters<typeof api.estimateRanking>[1]);
    },
    enabled: ready && keyReady && !queued,
    retry: false,
    placeholderData: (prev) => prev,
  });

  // THE WRITE IS A BACKGROUND JOB. The scope is the library: a rule that
  // takes half of a million-item library is hundreds of thousands of tag
  // rows and minutes of work, which is not something to hold a dialog open
  // for with nothing but a disabled button to show for it. What comes back
  // is the job; the task list carries its progress and its cancel, and what
  // it has written when a cancel lands stays.
  const apply = async () => {
    if (!ready || saving) return;
    setSaving(true);
    setError("");
    try {
      await api.applyEstimate(ranking!.id, {
        ...(scopeRef.current as object ?? {}),
        ...(items ? { items } : {}),
        embedders, rules: wire, estimate_unranked: estimateUnranked,
        pool_ids: pools,
      } as unknown as Parameters<typeof api.applyEstimate>[1]);
      setQueued(true);
      // The job writes as it goes, so the poll that watches it refreshes
      // the library; this is the first sweep, for the rows it has already
      // stamped by the time the dialog closes.
      qc.invalidateQueries({ queryKey: ["ml-jobs"] });
    } catch (e) {
      setError(errText(e));
    } finally {
      setSaving(false);
    }
  };

  const patch = (id: string, next: Partial<Rule>) =>
    setRules((cur) => cur.map((r) => (r.id === id ? { ...r, ...next } : r)));

  const shown = preview ?? null;
  /** THE ANSWER PER RULE, BY THE RULE'S OWN ID. The request carries only
   *  the rules that were SET, so an answer read by position would land on
   *  a half-typed row's neighbour the moment one in the middle was being
   *  edited. */
  const shownFor = useMemo(() => {
    const out = new Map<string, RankingEstimateOut["rules"][number]>();
    const set = rules.filter(ruleIsSet);
    (shown?.rules ?? []).forEach((r, i) => {
      const id = set[i]?.id;
      if (id) out.set(id, r);
    });
    return out;
  }, [shown, rules]);
  /** The bands in ORDER, which is what the rows are drawn in — the number
   *  is edited in place and the row slides to where it belongs, the same
   *  arithmetic the server does. */
  const ordered = useMemo(() => banded(rules), [rules]);
  const trouble = error || (previewError ? errText(previewError) : "");

  return (
    <Overlay icon="query_stats" title={t("Assign ratings")}
      subtitle={t("Guess a ranking's scale for pictures it has not rated, and tag on it")}
      width={580} onClose={onClose}
      footer={queued ? (
        <>
          <span style={{ flex: 1, fontSize: "var(--fs-3)", color: "var(--muted)" }}>
            {t("Writing the tags in the background — the task list has it")}
          </span>
          <Button variant="primary" icon="check" onClick={onClose}>
            {t("Done")}
          </Button>
        </>
      ) : (
        <>
          <span style={{ flex: 1, fontSize: "var(--fs-2)", color: "var(--muted-2)",
                         lineHeight: 1.4 }}>
            {trouble ? (
              <span style={{ color: "var(--red-text)" }}>{trouble}</span>
            ) : shown ? (<>
              {t("{rated} rated · {estimated} estimated · {unindexed} not indexed",
                 { rated: String(shown.rated),
                   estimated: String(shown.estimated),
                   unindexed: String(shown.unindexed) })}
              {/* A PREVIEW SAYS WHEN IT ONLY SAMPLED. Its counts are exact
                  over what it looked at and nothing more — and the write
                  that follows walks the lot, so the numbers can only grow
                  from here. */}
              {shown.partial && (
                <span style={{ display: "block", marginTop: 2 }}>
                  {t("Counted over {n} of {total} pictures — writing covers them all",
                     { n: String(shown.scanned),
                       total: String(shown.total ?? shown.scanned) })}
                </span>
              )}
            </>) : " "}
          </span>
          <Button variant="ghost" onClick={onClose}>{t("Cancel")}</Button>
          <Button variant="primary" icon="label" onClick={() => void apply()}
            disabled={!ready || saving || isFetching}>
            {saving ? t("Writing…") : t("Write the tags")}
          </Button>
        </>
      )}>
      <div style={{ padding: 16, display: "flex", flexDirection: "column",
                    gap: 14 }}>
        <div>
          <div style={sectionLabel}>{t("Ranking")}</div>
          <div style={card}>
            <div style={rowStyle(rows.length < 2 && (ranking?.pools?.length ?? 0) < 2)}>
              <RankingPicker rows={rows} value={ranking}
                onPick={(r) => { setRankingId(r.id); setQueued(false); }} t={t}
                tn={tn} />
            </div>
            {/* THE LEAGUES, where there is more than one. A pool is a
                population with standings of its own under the one prefix,
                so which of them the scale is read from is a real question —
                and with one pool it is not, so the row is absent. */}
            {(ranking?.pools?.length ?? 0) > 1 && (
              <PoolPicker ranking={ranking!} value={pools}
                onChange={(ids) => { setPools(ids); setQueued(false); }}
                t={t} tn={tn} />
            )}
          </div>
          {rows.length === 0 && (
            <div style={{ marginTop: 6, fontSize: "var(--fs-2)",
                          color: "var(--muted-2)" }}>
              {t("There is no ranking yet — rate some pictures first.")}
            </div>
          )}
        </div>

        {/* THE RULES: the scale cut into BANDS, and what to write in each.
            The range is the row's LEFT COLUMN and the tags stand beside it,
            so a row reads across as one sentence — this stretch of the
            scale, these tags — and the card reads down as the scale itself,
            HIGHEST BAND FIRST, the way a rating scale is read. That
            arrangement is what says the bands are contiguous and cover
            everything; there used to be a line under the card explaining it
            in words, which is what a layout says when it is not saying it
            itself.

            A row's ✚ SPLITS ITS OWN BAND in half and sits beside its ✕: the
            two things you do to a row are the same kind of thing and belong
            in the same place. */}
        <div>
          {/* THE SECTION'S OWN VERB, at the right of its heading: put the
              bands back to one per bucket. Hidden while they ARE that, since
              a button that would change nothing reads as one that does. */}
          <div style={{ ...sectionLabel, display: "flex",
                        alignItems: "center", gap: 8, minHeight: 18 }}>
            <span>{t("Rules")}</span>
            <span style={{ flex: 1 }} />
            {ranking && !atDefaultRules && (
              <Chip size="md" upper bordered icon="restart_alt" onClick={() => setResetting(true)}
                    title={t("Put the bands back to one per bucket")}
                    style={{ background: "transparent", color: "var(--muted)", borderColor: "var(--border-strong)" }}>
                {t("Reset")}
              </Chip>
            )}
          </div>
          <div style={card}>
            {ordered.map(({ rule: r, hi }, i) => (
              <RuleRow key={r.id} rule={r} hi={hi} last={i === ordered.length - 1}
                // WHERE THE SCALE ITSELF ENDS, for the band that has no band
                // above it: "and up" said nothing about how far up, and the
                // ranking's own top is the answer. Its bound is INCLUSIVE —
                // an estimate is clamped to the scale, so a picture really
                // does land on it — which is why that row alone says `..≤`.
                topBound={hi == null ? (ranking?.bucket_hi ?? null) : null}
                groupOptions={groupOptions}
                onPatch={(next) => patch(r.id, next)}
                onRemove={ordered.length > 1
                  ? () => setRules((c) => c.filter((x) => x.id !== r.id))
                  : undefined}
                // HALF WAY ALONG this band — a number worth starting from
                // and one keystroke from any other. The topmost band ends at
                // the SCALE's top, so it halves that stretch; where it starts
                // AT the top there is no stretch and nothing to split.
                onSplit={() => setRules((c) => {
                  const lo = Number(r.lo);
                  const top = hi ?? ranking?.bucket_hi ?? (lo + 1);
                  if (!(top > lo)) return c;
                  const at = Math.round((lo + top) * 50) / 100;
                  if (c.some((x) => Number(x.lo) === at)) return c;
                  return [...c, emptyRule(String(at))];
                })}
                // BY THE RULE'S OWN ID, never by position: a half-typed row
                // is not sent at all, so a positional read would put its
                // neighbour's answer on it.
                found={shownFor.get(r.id)}
                t={t} tn={tn} />
            ))}
            {ordered.length === 0 && (
              <div className="hoverable"
                onClick={() => setRules(() => ranking
                  ? defaultRules(ranking.bucket_lo, ranking.bucket_hi)
                  : [emptyRule("0")])}
                style={{ display: "flex", alignItems: "center", gap: 6,
                         padding: "10px 14px", cursor: "pointer",
                         fontSize: "var(--fs-3)", color: "var(--muted)",
                         fontWeight: 500 }}>
                <Icon name="add" size={16} />
                {t("Add a band")}
              </div>
            )}
          </div>
        </div>

        <div>
          <div style={sectionLabel}>{t("Options")}</div>
          <div style={card}>
            {picked.length > 0 && (
              <OptionRow
                title={t("Only the selected pictures")}
                desc={tn({ one: "Off, the estimate covers everything the grid is showing rather than the 1 picture selected.",
                           other: "Off, the estimate covers everything the grid is showing rather than the {n} pictures selected." },
                         picked.length)}
                checked={onlyPicked}
                onToggle={() => { setOnlyPicked((v) => !v); setQueued(false); }} />
            )}
            {/* THE PICTURES THE RANKING PLACED ARE ALWAYS COVERED, each
                at its own standing — never at the fit's guess about it,
                which would be NEAR the standing rather than it. What this
                turns on is the REST. */}
            <OptionRow
              title={t("Estimate a score for unrated pictures")}
              desc={t("Off, only the pictures the ranking has placed are tagged, each at the standing you gave it.")}
              checked={estimateUnranked}
              onToggle={() => { setEstimateUnranked((v) => !v);
                                setQueued(false); }}
              last />
          </div>
        </div>

        <div>
          <div style={sectionLabel}>{t("Sorting")}</div>
          <div style={{ ...card, padding: 14 }}>
            <div style={{ fontSize: "var(--fs-3)", color: "var(--text-2)",
                          fontWeight: 500 }}>
              {t("Judge likeness by")}
            </div>
            <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", marginTop: 3,
                          marginBottom: 10, lineHeight: 1.45 }}>
              {t("Which spaces carry the ranking to the unrated pictures. Each is fitted on its own and the answers averaged.")}
            </div>
            <EmbedModelPicker models={pickerModels} value={embedderChoice}
              onChange={(id) => { setEmbedder(id); setQueued(false); }} t={t} />
            {shown != null && shown.unindexed > 0 && (
              <IndexRemaining n={shown.unindexed} embedders={embedders}
                scope={() => ({ ...(scopeRef.current as object ?? {}),
                                ...(items ? { items } : {}) })}
                t={t} tn={tn} />
            )}
          </div>
        </div>

      </div>
      {resetting && ranking && (
        <ConfirmModal t={t}
          title={t("Put the bands back to one per bucket?")}
          body={tn({ one: "The rule you have written here goes with it.",
                     other: "The {n} rules you have written here go with them." },
                   rules.length)}
          answer={{ label: t("Reset"), danger: true }}
          onResult={(r) => {
            if (r === "answer") setRules(() => defaultRules(ranking.bucket_lo, ranking.bucket_hi));
            setResetting(false);
          }} />
      )}
    </Overlay>
  );
}



/** ONE RULE: the comparison, then what it writes. The write is quick
 *  assign's editor — the same chips, the same one adder for tags and
 *  groups — because a rule IS a stamp, over whatever the estimate claims. */
function RuleRow({ rule, hi, topBound, last, groupOptions, onPatch, onRemove, onSplit,
                   found, t, tn }: {
  rule: Rule;
  /** Where this band ENDS — the next number UP, null for the topmost. */
  hi: number | null;
  /** The SCALE's own top, handed to the highest band alone — the one that
   *  has no band above it to end at. Inclusive, so it is drawn `..≤`. */
  topBound?: number | null;
  /** The bottom row of the card, which draws no seam. */
  last?: boolean;
  groupOptions: ReturnType<typeof flattenGroupTree>;
  onPatch: (next: Partial<Rule>) => void;
  onRemove?: () => void;
  /** Cut this band in two. */
  onSplit: () => void;
  /** What the preview says THIS rule takes — absent until one lands. */
  found?: { matched: number; sample: RankingItemRef[];
            sample_scores: number[] };
  t: (s: string, vars?: Record<string, string>) => string;
  tn: (forms: { one: string; other: string }, n: number,
       vars?: Record<string, string>) => string;
}) {
  const act: React.CSSProperties = {
    display: "flex", width: 24, height: 24, alignItems: "center",
    justifyContent: "center", borderRadius: "var(--r-2)", cursor: "pointer",
    color: "var(--muted-2)", flex: "0 0 auto",
  };
  return (
    <div style={rowStyle(last)}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
        {/* THE RANGE, the row's LEFT COLUMN: its own number — editable, the
            number-field rule holding, and editing it slides the row to
            where it belongs since the bands ARE the rules in order of it —
            and the next one up, which the row does not carry and has to be
            told or the card reads as a list of thresholds. */}
        <div style={{ flex: "0 0 auto", display: "flex", alignItems: "center",
                      gap: 6, width: 124, minHeight: 28 }}>
          <input value={rule.lo} inputMode="decimal"
            placeholder={t("from")}
            onChange={(e) => {
              const v = filterNumeric(e.target.value, { maxLen: 3, decimals: 2 });
              if (v != null) onPatch({ lo: v });
            }}
            style={{ ...compactField, width: 56, textAlign: "right",
                     fontFamily: "var(--mono)" }} />
          <span style={{ fontSize: "var(--fs-3)", color: "var(--muted-2)",
                         fontFamily: "var(--mono)", whiteSpace: "nowrap" }}>
            {/* `..<` because a band runs UP TO the next one's start and
                stops short of it — a dash reads as "between these two", and
                the two neighbouring rows would then both claim the number
                where they meet. The highest band is the exception: nothing
                starts above it, so it ends AT the scale's own top and
                includes it. */}
            {hi != null ? `..< ${hi}`
             : topBound == null ? t("and up")
             // A band somebody typed ABOVE the scale's top catches nothing —
             // an estimate is clamped to the scale — so it says it begins and
             // ends in the same place rather than claiming a bound under its
             // own start.
             : `..\u2264 ${Math.max(topBound, Number(rule.lo) || topBound)}`}
          </span>
        </div>
        {/* …AND WHAT IT WRITES, beside it and left-aligned, so the row
            reads across as one sentence: this stretch, these tags. */}
        <div style={{ flex: 1, minWidth: 0 }}>
        <CombinedTagEditor
          pos={rule.pos} neg={rule.neg}
          fetchSuggestions={fetchTagNameSuggestions}
          onAdd={(raw) => {
            const op = parseQuickWord(raw);
            if (!op) return;
            // The editor committed the field's form already.
            const name = op.name;
            if (!name) return;
            onPatch(op.negative
              ? { pos: rule.pos.filter((x) => x !== name),
                  neg: [...new Set([...rule.neg, name])] }
              : { pos: [...new Set([...rule.pos, name])],
                  neg: rule.neg.filter((x) => x !== name) });
          }}
          onFlip={(name) => onPatch({
            pos: rule.pos.includes(name)
              ? rule.pos.filter((x) => x !== name) : [...rule.pos, name],
            neg: rule.neg.includes(name)
              ? rule.neg.filter((x) => x !== name) : [...rule.neg, name],
          })}
          onRemove={(name) => onPatch({
            pos: rule.pos.filter((x) => x !== name),
            neg: rule.neg.filter((x) => x !== name) })}
          groups={rule.groups} groupOptions={groupOptions}
          onAddGroup={(gid) => onPatch({
            groups: [...new Set([...rule.groups, gid])] })}
          onRemoveGroup={(gid) => onPatch({
            groups: rule.groups.filter((g) => g !== gid) })}
          addersBelow
        />
        </div>
        {found != null && (
          <span style={{ flex: "0 0 auto", fontSize: "var(--fs-2)", minHeight: 28,
                         display: "flex", alignItems: "center",
                         color: "var(--muted-2)", whiteSpace: "nowrap" }}>
            {tn({ one: "1 picture", other: "{n} pictures" }, found.matched)}
          </span>
        )}
        {/* THE TWO THINGS YOU DO TO A ROW, side by side: cut this band in
            two, or take it out — its neighbour above widens to cover what
            it held. */}
        <div style={{ flex: "0 0 auto", display: "flex", alignItems: "center",
                      gap: 1, minHeight: 28 }}>
          <span className="hoverable" title={t("Split this band in two")}
                onClick={onSplit} style={act}>
            <Icon name="add" size={15} />
          </span>
          {onRemove ? (
            <span className="hoverable" title={t("Remove")}
                  onClick={onRemove} style={act}>
              <Icon name="close" size={15} />
            </span>
          ) : <span style={{ width: 24 }} />}
        </div>
      </div>
      {/* WHAT THIS RULE TAKES, before anything is written — the highest of
          them with their numbers. A rule is a claim about pictures, and the
          only way to see whether the claim travelled is to look at what IT
          claims; one strip for the whole dialog said nothing about which
          rule was about to write. A press opens the preview over the
          dialog. */}
      {found != null && found.sample.length > 0 && (
        <div style={{ marginTop: 8, display: "flex", gap: 6,
                      flexWrap: "wrap" }}>
          {found.sample.map((x, i) => (
            <span key={x.item_id}
              title={t("Open the preview")}
              onClick={() => useUI.getState().openQuickLook(
                found.sample.map((y) => y.item_id),
                { start: i, raised: true })}
              style={{ position: "relative", width: 54, height: 54,
                       cursor: "pointer" }}>
              <img src={x.file_id != null
                ? api.thumbUrl(x.file_id, 0, x.thumb_token) : undefined}
                style={{ width: 54, height: 54, objectFit: "cover",
                         borderRadius: "var(--r-2)", background: "var(--bg-deep)",
                         border: "1px solid var(--border-soft)" }} />
              <span style={{ position: "absolute", right: 2, bottom: 2,
                             padding: "0 4px", borderRadius: 4,
                             // A scrim: the thumbnail's own corner, which
                             // has to read over whatever the picture puts
                             // behind it, in either theme.
                             background: "var(--scrim-3)",
                             color: "var(--on-scrim)", fontSize: "var(--fs-1)",
                             fontFamily: "var(--mono)" }}>
                {found.sample_scores[i]}
              </span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}


/** THE RANKING, with what there is to know about it under the name: a
 *  `<select>` can hold one line, and which ranking to spend is a question
 *  about how much evidence each one has. */
function RankingPicker({ rows, value, onPick, t, tn }: {
  rows: RankingRow[];
  value: RankingRow | null;
  onPick: (r: RankingRow) => void;
  t: (s: string, vars?: Record<string, string>) => string;
  tn: (forms: { one: string; other: string }, n: number,
       vars?: Record<string, string>) => string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLButtonElement>(null);
  const rect = useAnchorRect(ref, open);
  useMenuDismiss(open, () => setOpen(false), { within: [ref] });
  /** THE COUNTS, and only those — how much evidence this axis carries is
   *  the question the subtitle answers. */
  const under = (r: RankingRow) => [
    tn({ one: "1 comparison", other: "{n} comparisons" }, r.judgments),
    tn({ one: "1 item", other: "{n} items" }, r.items),
    ...((r.pools?.length ?? 0) > 1
      ? [tn({ one: "1 pool", other: "{n} pools" }, r.pools.length)] : []),
  ].join(" · ");
  /** THE NAME, and after it the tags its range mints — the same line,
   *  because the tags ARE what this ranking is called in the library, and
   *  under the name they read as one more statistic. */
  const named = (r: RankingRow) => (
    <span style={{ display: "flex", alignItems: "baseline", gap: 8,
                   minWidth: 0 }}>
      <span style={{ flex: "0 1 auto", fontSize: "var(--fs-3)", color: "var(--text)",
                     overflow: "hidden", textOverflow: "ellipsis",
                     whiteSpace: "nowrap" }}>
        {r.name}
      </span>
      <span style={{ flex: "0 20 auto", minWidth: 0, fontSize: "var(--fs-2)",
                     fontFamily: "var(--mono)", color: "var(--muted-2)",
                     overflow: "hidden", textOverflow: "ellipsis",
                     whiteSpace: "nowrap" }}>
        {r.bucket_lo} … {r.bucket_hi}
      </span>
    </span>
  );
  return (
    <>
      <button ref={ref} onClick={() => setOpen((o) => !o)}
        style={{ display: "flex", alignItems: "center", gap: 10,
                 width: "100%", padding: "6px 8px", borderRadius: "var(--r-4)",
                 border: "1px solid var(--border)",
                 background: "var(--bg-deep)", cursor: "pointer",
                 fontFamily: "inherit", textAlign: "left" }}>
        <span style={{ flex: 1, minWidth: 0 }}>
          {value ? named(value) : (
            <span style={{ display: "block", fontSize: "var(--fs-3)",
                           color: "var(--text)" }}>
              {t("No ranking")}
            </span>
          )}
          {value && (
            <span style={{ display: "block", marginTop: 2, fontSize: "var(--fs-2)",
                           color: "var(--muted-2)", overflow: "hidden",
                           textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {under(value)}
            </span>
          )}
        </span>
        <Icon name="expand_more" size={17} color="var(--muted-2)" />
      </button>
      {open && (
        <AnchoredDropdown rect={rect}>
          {rows.map((r) => (
            <div key={r.id} className="hoverable"
              onClick={() => { onPick(r); setOpen(false); }}
              style={{ padding: "7px 10px", borderRadius: "var(--r-3)",
                       cursor: "pointer", minWidth: 0,
                       background: r.id === value?.id
                         ? "var(--accent-dim)" : undefined }}>
              {named(r)}
              <div style={{ marginTop: 2, fontSize: "var(--fs-2)",
                            color: "var(--muted-2)" }}>
                {under(r)}
              </div>
            </div>
          ))}
        </AnchoredDropdown>
      )}
    </>
  );
}


/** WHICH LEAGUES the scale is read from — none picked means all of them,
 *  which is what a ranking with one pool has always meant. */
function PoolPicker({ ranking, value, onChange, t, tn }: {
  ranking: RankingRow;
  value: number[];
  onChange: (ids: number[]) => void;
  t: (s: string, vars?: Record<string, string>) => string;
  tn: (forms: { one: string; other: string }, n: number,
       vars?: Record<string, string>) => string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLButtonElement>(null);
  const rect = useAnchorRect(ref, open);
  useMenuDismiss(open, () => setOpen(false), { within: [ref] });
  const all = ranking.pools ?? [];
  const label = value.length === 0
    ? t("Every pool")
    : all.filter((l) => value.includes(l.id))
         .map((l) => l.name || t("Default")).join(", ");
  const toggle = (id: number) => {
    const next = value.includes(id)
      ? value.filter((x) => x !== id) : [...value, id];
    // Every one picked IS every one, which is what none picked already
    // says — so it collapses back to the plainer answer.
    onChange(next.length === all.length ? [] : next);
  };
  return (
    <div style={{ ...rowStyle(true), display: "flex", alignItems: "center",
                  gap: 16 }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: "var(--fs-3)", color: "var(--text)" }}>
          {t("Pools")}
        </div>
        <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", marginTop: 3,
                      lineHeight: 1.45 }}>
          {t("A pool is a population with standings of its own. Picked ones are fitted together, as one scale.")}
        </div>
      </div>
      <button ref={ref} onClick={() => setOpen((o) => !o)}
        style={{ display: "flex", alignItems: "center", gap: 6, height: 26,
                 padding: "0 8px", borderRadius: "var(--r-3)", cursor: "pointer",
                 fontSize: "var(--fs-3)", maxWidth: 200, flex: "0 0 auto",
                 background: "var(--bg-deep)",
                 border: "1px solid var(--border)",
                 color: "var(--text)", fontFamily: "inherit" }}>
        <span style={{ overflow: "hidden", textOverflow: "ellipsis",
                       whiteSpace: "nowrap" }}>{label}</span>
        <Icon name="expand_more" size={15} color="var(--muted-2)" />
      </button>
      {open && (
        <AnchoredDropdown rect={rect} minWidth={200}>
          {all.map((l) => (
            <div key={l.id} className="hoverable"
              onClick={() => toggle(l.id)}
              style={{ display: "flex", alignItems: "center", gap: 8,
                       padding: "7px 10px", borderRadius: "var(--r-3)",
                       cursor: "pointer", fontSize: "var(--fs-3)",
                       color: "var(--text-2)" }}>
              <input type="checkbox" readOnly
                checked={value.length === 0 || value.includes(l.id)}
                style={{ pointerEvents: "none" }} />
              <span style={{ flex: 1, minWidth: 0, overflow: "hidden",
                             textOverflow: "ellipsis",
                             whiteSpace: "nowrap" }}>
                {l.name || t("Default")}
              </span>
              <span style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>
                {tn({ one: "1 comparison", other: "{n} comparisons" },
                    l.judgments ?? 0)}
              </span>
            </div>
          ))}
        </AnchoredDropdown>
      )}
    </div>
  );
}


/** INDEX WHAT IS MISSING, from here: the estimate can only answer for a
 *  picture that carries a vector, and the alternative was to close the
 *  dialog, find the tag batch and start an indexing run from its chooser. */
function IndexRemaining({ n, embedders, scope, t, tn }: {
  n: number;
  embedders: string[];
  scope: () => Record<string, unknown>;
  t: (s: string, vars?: Record<string, string>) => string;
  tn: (forms: { one: string; other: string }, n: number,
       vars?: Record<string, string>) => string;
}) {
  const [queued, setQueued] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      let total = 0;
      for (const embedder of embedders) {
        const got = await api.tagSortIndex({
          ...scope(), embedder,
        } as Parameters<typeof api.tagSortIndex>[0]);
        total += got.queued;
      }
      setQueued(total);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10,
                  marginTop: 10 }}>
      <span style={{ flex: 1, fontSize: "var(--fs-2)", color: "var(--muted-2)",
                     lineHeight: 1.45 }}>
        {queued != null
          ? tn({ one: "{n} picture queued for indexing — the estimate covers it once the job is done",
                 other: "{n} pictures queued for indexing — the estimate covers them once the job is done" },
               queued)
          : tn({ one: "1 picture in this scope carries no vector yet, so the estimate cannot answer for it",
                 other: "{n} pictures in this scope carry no vector yet, so the estimate cannot answer for them" },
               n)}
      </span>
      {queued == null && (
        <button onClick={() => void run()} disabled={busy}
          title={t("Index the unindexed items as a background task")}
          style={{ height: 24, padding: "0 10px", borderRadius: "var(--r-3)",
                   border: "1px solid var(--border-strong)",
                   background: "var(--panel-2)", color: "var(--text-2)",
                   cursor: busy ? "default" : "pointer",
                   fontFamily: "inherit", fontSize: "var(--fs-2)",
                   flex: "0 0 auto" }}>
          {busy ? t("Queueing…") : t("Index remaining")}
        </button>
      )}
    </div>
  );
}

// Settings → Storage: where the library's disk went, and the one action that
// gives some of it back.
//
// THE UNIT IS A TYPE, not a file. "Which of my 40 000 pictures is big" is a
// question the grid answers (sort by size); the question this page exists for
// is the one nothing could answer — why a library is 200 GB when its pictures
// are 60, which turns out to be a warmed latent cache for four models and a
// training run nobody cleaned up. So every row is a TYPE, and the delete
// button acts on all of it.
//
// The numbers come from the DB for anything the library records (a file and
// an artifact each carry their own byte count) and from a directory walk for
// the rest; the split is the backend's, and the page just words the keys.
import React, { useEffect, useState } from "react";
import { Button } from "../../shared/Button";
import { EmptyState } from "../../shared/EmptyState";
import { ProgressBar } from "../../shared/ProgressBar";
import { filterNumeric } from "../../shared/useNumericText";
import { PrefRow, Section, ToggleRow } from "../../shared/SettingsRows";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { StorageArtifactRow, StorageOut, StoragePruneJob, StoragePruneRule,
         StorageRow, api } from "../api";
import { artifactKind } from "../artifactKinds";
import { formatBytes } from "../format";
import { STORAGE_ROW_ICONS, storageRowLabel } from "../storageRows";
import { Icon } from "../../shared/Icon";
import { confirm } from "../../shared/ConfirmModal";
import { Overlay } from "../../shared/Overlay";
import { useErrText, useT, useTn } from "../i18n";
import { bumpLibrary } from "../invalidation";
import { useTrainingOffered } from "../training";


/** A row's share of everything measured, as a bar. The denominator is the
 *  WHOLE page rather than the section, so a 12 GB training folder and a 12 GB
 *  video library draw the same bar — which is the comparison somebody opening
 *  this page is making. */
function Share({ bytes, of }: { bytes: number; of: number }) {
  const pct = of > 0 ? Math.min(100, (100 * bytes) / of) : 0;
  return <ProgressBar value={pct} width={64} track="var(--bg-deep)" transitionMs={0} />;
}

/** The colours of the summary bar, in the order the segments are laid out.
 *  Fixed hues rather than shades of the accent: the point of the bar is
 *  telling the segments APART, and six steps of one colour cannot. */
const SEG_COLORS: Record<string, string> = {
  image: "#4f8cff",       // the accent — pictures are what the library is for
  video: "#7d5cff",
  sequence: "#3fb6c9",
  artifacts: "#e0b84f",
  training: "#e07a4f",
  evaluate: "var(--magenta-text)",
  database: "#9c6ade",
  thumbnails: "#4fc98a",
  rest: "#7a7a86",        // whatever is left, in the muted grey it deserves
};

interface Segment { key: string; label: string; bytes: number; color: string }

/** The share a segment needs to be drawn and named in its own right; smaller
 *  ones are summed into "Other". */
const SEGMENT_FLOOR = 0.05;

/** One bar for the whole library, and the line above it reads the segment
 *  under the pointer.
 *
 *  A bar per row (the `Share` column) answers "how big is this compared with
 *  everything"; what it cannot show is how the whole thing is DIVIDED, which
 *  is the question somebody opens this page with. Hovering rather than
 *  labelling in place, because six labels do not fit across a 400 px bar and
 *  the ones that would fit are the ones you can already see are big.
 *
 *  The default reading is the TOTAL, so the line says something before the
 *  pointer arrives and goes back to saying it afterwards. */
function TotalBar({ segments, total, totalLabel }: {
  segments: Segment[]; total: number; totalLabel: string;
}) {
  const [at, setAt] = useState<number | null>(null);
  const shown = at != null ? segments[at] : null;
  return (
    <div style={{ padding: "12px 14px" }}>
      {/* FIXED HEIGHT: the right half gains a percentage on hover, and a row
          that grows moves the whole page under the pointer reading it. No
          colour swatch here — the legend under the bar is where a colour is
          matched to a name, and a chip that came and went in front of the
          title made the words jump sideways as the pointer crossed. */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        gap: 12, height: 18, marginBottom: 8,
      }}>
        <span style={{
          fontSize: "var(--fs-3)", color: "var(--text)", display: "flex",
          alignItems: "center", gap: 7, minWidth: 0,
        }}>
          <span style={{ overflow: "hidden", textOverflow: "ellipsis",
                         whiteSpace: "nowrap" }}>
            {shown ? shown.label : totalLabel}
          </span>
        </span>
        <span style={{
          fontSize: "var(--fs-3)", color: "var(--text-2)", flex: "0 0 auto",
          fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap",
        }}>
          {/* The share FIRST: it is what the segment under the pointer is
              being asked, and the bytes are the detail behind it. A segment
              that rounds to zero is not zero — "0%" reads as a bug. */}
          {shown && total > 0 && (
            <span style={{ color: "var(--muted-2)", marginRight: 6 }}>
              {(100 * shown.bytes) / total < 0.5
                ? "<1%" : `${Math.round((100 * shown.bytes) / total)}%`}
            </span>
          )}
          {formatBytes(shown ? shown.bytes : total)}
        </span>
      </div>
      <div
        onMouseLeave={() => setAt(null)}
        style={{
          display: "flex", height: 14, borderRadius: "var(--r-3)", overflow: "hidden",
          background: "var(--bg-deep)", gap: 1,
        }}
      >
        {segments.map((seg, i) => (
          <div
            key={seg.key}
            title={seg.label}
            onMouseEnter={() => setAt(i)}
            style={{
              // `flexGrow` by bytes rather than a percentage width: with a
              // 1 px gap between segments, percentages of the FULL width add
              // up to more than there is and the last one is clipped.
              flexGrow: Math.max(seg.bytes, 1),
              flexBasis: 0,
              minWidth: 2,
              background: seg.color,
              opacity: at == null || at === i ? 1 : 0.45,
              transition: "opacity .12s ease",
              cursor: "default",
            }}
          />
        ))}
      </div>
      {/* The legend, because a colour with no name is a colour: the bar's
          smallest slivers are a couple of pixels wide and nobody is going to
          find them with a pointer to read what they are. Same order as the
          bar — largest first — so the two are read together. */}
      <div
        onMouseLeave={() => setAt(null)}
        style={{
          display: "flex", flexWrap: "wrap", gap: "5px 14px", marginTop: 9,
        }}
      >
        {segments.map((seg, i) => (
          <span
            key={seg.key}
            onMouseEnter={() => setAt(i)}
            style={{
              display: "flex", alignItems: "center", gap: 6, fontSize: "var(--fs-2)",
              color: at == null || at === i ? "var(--text-2)" : "var(--muted-2)",
              cursor: "default",
            }}
          >
            <span style={{
              width: 8, height: 8, borderRadius: 2.5, flex: "0 0 auto",
              background: seg.color,
            }} />
            {seg.label}
          </span>
        ))}
      </div>
    </div>
  );
}

/** One line: icon, name, what it is made of, its share, its size — and,
 *  where the caller gave one, the action that removes the lot. */
function Row({ icon, label, sub, count, bytes, of, action, last }: {
  icon: string; label: string; sub?: string;
  count: number; bytes: number; of: number;
  action?: React.ReactNode; last?: boolean;
}) {
  const tn = useTn();
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12, padding: "10px 14px",
      borderBottom: last ? "none" : "1px solid var(--border-soft)",
    }}>
      <Icon name={icon} size={16} color="var(--muted-2)" />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: "var(--fs-3)", color: "var(--text)", whiteSpace: "nowrap",
          overflow: "hidden", textOverflow: "ellipsis",
        }}>
          {label}
        </div>
        <div style={{ fontSize: "var(--fs-1)", color: "var(--muted-2)", marginTop: 1 }}>
          {sub ? `${sub} · ` : ""}{tn({ one: "{n} file", other: "{n} files" }, count)}
        </div>
      </div>
      <Share bytes={bytes} of={of} />
      <div style={{
        width: 74, textAlign: "right", fontSize: "var(--fs-3)",
        fontVariantNumeric: "tabular-nums", color: "var(--text-2)",
      }}>
        {formatBytes(bytes)}
      </div>
      <div style={{ width: 96, display: "flex", justifyContent: "flex-end" }}>
        {action}
      </div>
    </div>
  );
}

/** The delete button of one artifact type.
 *
 *  The confirmation is the one confirm sheet, which is what every other
 *  irreversible action in this app asks with (deleting items for good,
 *  removing a sequence) — an in-row Delete/Cancel pair was a second dialect
 *  of "are you sure", and it put the confirming button exactly where the
 *  pointer already was.
 *
 *  What the question says is HOW MUCH and WHAT IT COSTS, because those are
 *  the two things the row cannot say once a dialog is covering it: a cache is
 *  re-encoded by the next run that wants it, and anything else means running
 *  its model again. */
function DeleteArtifacts({ row, label, onDone }: {
  row: StorageArtifactRow; label: string; onDone: () => void;
}) {
  const t = useT();
  const tn = useTn();
  const errText = useErrText();
  const [error, setError] = useState("");
  const del = useMutation({
    // `model` is sent even when empty: "" means the rows naming no model,
    // which is a different question from "every model of this kind".
    mutationFn: () => api.deleteStorageArtifacts(row.kind, row.model),
    onSuccess: () => { setError(""); onDone(); },
    onError: (e) => setError(errText(e)),
  });

  if (del.isPending) {
    return <span style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>
      {t("Deleting…")}
    </span>;
  }
  const ask = async () => {
    const what = tn({
      one: "Delete {label}? That is 1 file, {size}.",
      other: "Delete {label}? That is {n} files, {size}.",
    }, row.count, { label, size: formatBytes(row.bytes) });
    const cost = row.cache
      ? t("The next training run re-encodes whatever it needs.")
      : t("Producing them again means running that model again.");
    if (!(await confirm({ title: what, body: cost,
                          answer: { label: t("Delete"), danger: true } }))) return;
    setError("");
    del.mutate();
  };
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      {error && (
        <span title={error} style={{ display: "inline-flex" }}>
          <Icon name="error" size={14} color="var(--red)" />
        </span>
      )}
      <Button variant="soft" size="xs" onClick={ask}>
        <Icon name="delete" size={13} /> {t("Delete")}
      </Button>
    </div>
  );
}

/** The delete button of the backups row.
 *
 *  Offered at all because the automatic pruning only runs after a SUCCESSFUL
 *  upgrade (`migrations.prune_backups`), so a library that has not migrated
 *  since keeps every copy it ever made — and until now nothing in the app
 *  could say so, let alone give the space back.
 *
 *  It asks like the artifact rows do, and what the question says is what this
 *  one costs, because it is the only thing on this page that cannot be made
 *  again: an artifact is its model run a second time, and a backup is the way
 *  back from an upgrade that went wrong. */
/** A ROW'S DELETE in "Everything else": a question first, then one request.
 *  The backups, the thumbnails, the Evaluate results and the finished
 *  training jobs each empty a different place with a different catch, so the
 *  question is the caller's; what asking and deleting look like is one. */
function RowDelete({ question, detail, run, onDone }: {
  question: string;
  detail: string;
  run: () => Promise<unknown>;
  onDone: () => void;
}) {
  const t = useT();
  const errText = useErrText();
  const [error, setError] = useState("");
  const del = useMutation({
    mutationFn: run,
    onSuccess: () => { setError(""); onDone(); },
    onError: (e) => setError(errText(e)),
  });

  if (del.isPending) {
    return <span style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>
      {t("Deleting…")}
    </span>;
  }
  const ask = async () => {
    if (!(await confirm({
      title: question, body: detail,
      answer: { label: t("Delete"), danger: true },
    }))) return;
    setError("");
    del.mutate();
  };
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      {error && (
        <span title={error} style={{ display: "inline-flex" }}>
          <Icon name="error" size={14} color="var(--red)" />
        </span>
      )}
      <Button variant="soft" size="xs" onClick={ask}>
        <Icon name="delete" size={13} /> {t("Delete")}
      </Button>
    </div>
  );
}

/** What each deletable row asks, and the request it makes — the Evaluate
 *  and training rows only where this server offers training at all. */
function useRowDelete(onDone: () => void) {
  const t = useT();
  const tn = useTn();
  const qc = useQueryClient();
  const training = useTrainingOffered();
  return (r: StorageRow): React.ReactNode => {
    const size = formatBytes(r.bytes);
    if (r.key === "backups") {
      return <RowDelete onDone={onDone} run={api.deleteStorageBackups}
        question={tn({
          one: "Delete the backup left by a schema upgrade? That is 1 file, {size}.",
          other: "Delete the {n} backups left by schema upgrades? That is {size}.",
        }, r.count, { size })}
        detail={t("A backup is how a library is put back if an upgrade goes wrong. Nothing here can make one again.")} />;
    }
    if (r.key === "thumbnails") {
      return <RowDelete onDone={onDone} run={api.deleteStorageThumbnails}
        question={t("Delete all thumbnails? That is {size}.", { size })}
        detail={t("Each one is made again the next time it is shown, which takes a moment. A video's hand-picked thumbnail frame goes back to the default one.")} />;
    }
    if (r.key === "evaluate" && training) {
      return <RowDelete onDone={() => {
          qc.invalidateQueries({ queryKey: ["eval-runs"] });
          onDone();
        }} run={api.deleteStorageEvaluate}
        question={t("Delete every Evaluate result? That is {size}.", { size })}
        detail={t("The pictures leave the Evaluate grid too. A generation that is still running is left alone.")} />;
    }
    if (r.key === "training" && training) {
      return <RowDelete onDone={() => {
          qc.invalidateQueries({ queryKey: ["train-jobs"] });
          onDone();
        }} run={api.deleteStorageTraining}
        question={t("Delete every finished training job?")}
        detail={t("Completed, failed and canceled jobs go, with their checkpoints and samples. Drafts and queued, paused or running jobs stay, and a locked checkpoint is kept as one of your adapters.")} />;
    }
    return undefined;
  };
}

/** A switch row inside the prune card. Spelled out here rather than imported
 *  from `SettingsOverlay`, for the reason `Section` below is — that file
 *  renders this page, so the import would be a cycle. */
/** A rule's switch — the shared toggle row. */
const Keep = ToggleRow;

/** A row that CHOOSES rather than measures — the shared preference row. */
function Choice({ label, value, options, onChange, last }: {
  label: string; value: string; onChange: (v: string) => void;
  options: { value: string; label: string }[]; last?: boolean;
}) {
  return (
    <PrefRow label={label} value={value} onChange={onChange} last={last}
             minWidth={0} options={options.map((o) => [o.value, o.label] as const)} />
  );
}

/** A threshold row: a number, its unit, and nothing else.
 *
 *  THE FIELD REJECTS THE KEYSTROKE rather than storing `NaN` — the query
 *  builder's rule, and for the same reason: the value travels to a rule that
 *  DELETES, and a field that reads back the literal word "NaN" would send a
 *  threshold nothing can compare. Empty is "not set", which is why the state
 *  is the typed TEXT and not a number: "0" and "" are the same rule and a
 *  half-typed "0." must survive the next keystroke.
 *
 *  Exported: the import overlay asks the same three questions the other way
 *  round (what to LEAVE OUT of a library rather than what to remove from
 *  one), and two spellings of one row is two places for the units, the
 *  widths and that keystroke rule to drift. */
export function Threshold({ label, unit, value, onChange, last, onRemove }: {
  label: string; unit: string; value: string;
  onChange: (v: string) => void; last?: boolean;
  /** Take this rule away entirely. The import dialog's rules are ADDED one
   *  at a time (a card of five thresholds is five questions asked of every
   *  import), so there each row needs a way back out; the Storage page's
   *  three are fixed and pass none. */
  onRemove?: () => void;
}) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 16, padding: "10px 14px",
      borderBottom: last ? "none" : "1px solid var(--border-soft)",
    }}>
      <div style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-3)",
                    color: "var(--text)" }}>{label}</div>
      <div style={{ display: "flex", alignItems: "center", gap: 6,
                    flex: "0 0 auto" }}>
        <input
          value={value}
          inputMode="decimal"
          placeholder="—"
          onChange={(e) => {
            if (filterNumeric(e.target.value) == null) return;
            onChange(e.target.value);
          }}
          style={{
            width: 72, height: 26, padding: "0 8px", textAlign: "right",
            background: "var(--bg-deep)", border: "1px solid var(--border)",
            borderRadius: "var(--r-3)", color: "var(--text)", fontSize: "var(--fs-3)",
            fontVariantNumeric: "tabular-nums",
          }}
        />
        <span style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", width: 24 }}>
          {unit}
        </span>
        {onRemove && <RemoveRuleBtn onClick={onRemove} />}
      </div>
    </div>
  );
}

/** The ✕ that takes a rule off a card. Shared so the thresholds and the
 *  file-types row cannot drift into two shapes of the same button. */
export function RemoveRuleBtn({ onClick }: { onClick: () => void }) {
  return (
    <span className="hoverable" title="Remove this filter"
      onClick={onClick}
      style={{ display: "flex", alignItems: "center", justifyContent: "center",
               width: 22, height: 22, borderRadius: "var(--r-2)", cursor: "pointer",
               color: "var(--muted-2)", flex: "0 0 auto" }}>
      <Icon name="close" size={14} />
    </span>
  );
}

/** What a running prune has done so far: a bar, and the two figures the page
 *  was already showing before it started — files and bytes — so the numbers
 *  somebody decided on are the numbers that count up.
 *
 *  The bar is the FILE count and not the bytes: `total` is a file count the
 *  preview can answer exactly, where the bytes freed depend on which files a
 *  chunk happens to reach and so would run ahead of or behind themselves.
 *  Before the first poll lands there is no run to describe, and the bar is
 *  simply empty — never a spinner, which would say "working" in a row that
 *  is about to say how much. */
function PruneProgress({ job }: { job?: StoragePruneJob }) {
  const t = useT();
  const tn = useTn();
  const done = job?.files ?? 0;
  const total = job?.total ?? 0;
  const pct = total > 0 ? Math.min(100, (done / total) * 100) : 0;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <ProgressBar value={pct} width={96} height={4} track="var(--border-soft)" />
      <span style={{ minWidth: 0 }}>
        {total > 0
          ? tn({ one: "Removing… {done} of {n} file, {size} freed",
                 other: "Removing… {done} of {n} files, {size} freed" },
               total, { done, size: formatBytes(job?.bytes ?? 0) })
          : t("Removing…")}
      </span>
    </div>
  );
}

/** The prune run this session is watching, if any.
 *
 *  Module scope rather than state: closing the dialog stops the watching and
 *  never the work — the run is a background task on the server — so reopening
 *  has to find it again, and there is no endpoint that lists runs. Cleared
 *  when the run ends, and a page reload legitimately forgets it (the run goes
 *  on; the next open simply shows the library as it then is). */
let activePrune = "";

/** Remove files from items by a RULE, rather than one at a time.
 *
 *  The rest of this page deletes a TYPE — every latent, every depth map. What
 *  it could not touch is the commonest reason a picture library is twice the
 *  size it should be: an item carrying four versions of one picture, because
 *  the same folder was imported at four sizes or a crawl kept a thumbnail
 *  beside every original. Those are FILES OF AN ITEM, and the only thing in
 *  the app that could remove one was the Sources list, one file at a time.
 *
 *  The rule is a matcher (the thresholds) with guards (the two switches), and
 *  it is previewed LIVE — the numbers that matter are how many files, how
 *  many bytes and how many ITEMS the rule empties, and none of them can be
 *  guessed from the rule. The preview is the whole safety story: the confirm
 *  dialog repeats it, but by then the decision has been made.
 *
 *  IT IS A DIALOG, where the rest of the page is a report. Everything else
 *  under Storage answers "where did the disk go" and is read; this composes
 *  an irreversible instruction out of five fields, which is a job you come
 *  to deliberately and leave when it is done. In the flow of the page it was
 *  a form somebody could half-fill and scroll away from, and its footer —
 *  the count and the button — had to be told apart from the rule rows above
 *  it by hand. A dialog has a footer already. */
function PruneOverlay({ onClose, onDone }: {
  onClose: () => void; onDone: () => void;
}) {
  const t = useT();
  const tn = useTn();
  const errText = useErrText();
  const [keepActive, setKeepActive] = useState(true);
  const [keepEdited, setKeepEdited] = useState(true);
  const [minMp, setMinMp] = useState("");
  const [minEdge, setMinEdge] = useState("");
  const [minLong, setMinLong] = useState("");
  const [kind, setKind] = useState<StoragePruneRule["kind"]>("");
  const [error, setError] = useState("");

  const num = (s: string) => {
    const n = Number(s);
    return s.trim() === "" || !Number.isFinite(n) || n < 0 ? 0 : n;
  };
  const rule: StoragePruneRule = {
    keep_active: keepActive, keep_edited: keepEdited,
    min_megapixels: num(minMp), min_short_edge: Math.round(num(minEdge)),
    min_long_edge: Math.round(num(minLong)),
    kind,
  };
  // The one rule that means the whole library — no threshold and nothing
  // kept. ALLOWED, and previewed and run like any other: it is a real thing
  // to want, and the count beside the button says how big it is. What it
  // still gets is a line saying so in as many words, because "614 files"
  // does not by itself read as "all of them".
  const everything = rule.min_megapixels === 0 && rule.min_short_edge === 0
    && rule.min_long_edge === 0 && !keepActive && !keepEdited;

  // Keyed on the rule, so typing a digit asks a new question and React Query
  // keeps the previous answer under the old key rather than blanking the
  // line. `placeholderData` is what stops the numbers flickering to nothing
  // between two keystrokes — a preview that empties as you type reads as a
  // rule that has stopped matching.
  const preview = useQuery({
    queryKey: ["file-prune-preview", rule],
    queryFn: () => api.previewFilePrune(rule),
    placeholderData: (prev) => prev,
    refetchOnWindowFocus: false,
  });

  // The id of the run in flight. A prune over a large library is minutes of
  // committed chunks, so the dialog holds only this and asks the server what
  // has happened — which is what makes Cancel possible at all, and what lets
  // the run outlive the dialog: closing this stops the watching, never the
  // work, so reopening picks the same run back up (`activePrune`).
  const [jobId, setJobId] = useState(activePrune);
  const watch = (id: string) => { activePrune = id; setJobId(id); };

  const start = useMutation({
    mutationFn: () => api.runFilePrune(rule),
    onSuccess: (job) => { setError(""); watch(job.id); },
    onError: (e) => setError(errText(e)),
  });

  // `refetchIntervalInBackground`: removing gigabytes is exactly the wait
  // somebody spends in another window, and a poll that stops when the tab is
  // hidden leaves the bar frozen at whatever it last saw.
  const job = useQuery({
    queryKey: ["file-prune", jobId],
    queryFn: () => api.filePruneStatus(jobId),
    enabled: jobId !== "",
    refetchInterval: (q) =>
      q.state.data && q.state.data.status !== "running" ? false : 700,
    refetchIntervalInBackground: true,
  });

  const running = start.isPending
    || (jobId !== "" && (!job.data || job.data.status === "running"));

  // The run has ended: report what it says, refresh the page's figures, and
  // forget it. Keyed on the id as well as the status, or a second prune whose
  // first poll has not landed would be finished by the previous one's effect.
  const ended = job.data && job.data.status !== "running" ? job.data : null;
  useEffect(() => {
    if (!ended || ended.id !== jobId) return;
    setError(ended.status === "error" ? ended.message : "");
    watch("");
    onDone();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ended, jobId, onDone]);

  const found = preview.data;
  const ask = async () => {
    if (!found || found.files === 0) return;
    const what = tn({
      one: "Remove 1 file, {size}?",
      other: "Remove {n} files, {size}?",
    }, found.files, { size: formatBytes(found.bytes) });
    const cost = found.items > 0
      ? tn({
          one: "1 item is left with no file at all and is deleted with it. This cannot be undone.",
          other: "{n} items are left with no file at all and are deleted with them. This cannot be undone.",
        }, found.items)
      : t("This cannot be undone.");
    if (!(await confirm({ title: what, body: cost,
                          answer: { label: t("Remove"), danger: true } }))) return;
    setError("");
    start.mutate();
  };

  // The dialogs' own footer: whatever has to be said on the left at `flex: 1`,
  // then a ghost and a primary. Not a bordered mini-button of this page's own
  // — a footer is chrome, and the one place every dialog in the app agrees.
  const footer = (
    <>
      {/* WHAT GOES, then WHAT IT COSTS — on two lines, because the second is
          the one somebody has to actually read and appended after a " · " it
          was the tail of a sentence about bytes. The two warnings share the
          line and never both appear: "every file in the library" says what
          the item count would have, and more plainly. */}
      <div style={{ flex: 1, alignSelf: "center", minWidth: 0, fontSize: "var(--fs-3)",
                    color: "var(--text-2)", textAlign: "left" }}>
        {running ? <PruneProgress job={job.data} />
          : !found ? t("Counting…")
          : found.files === 0 ? t("Nothing matches this rule.")
          : (
            <>
              <div>
                {tn({ one: "{n} file, {size}",
                      other: "{n} files, {size}" },
                    found.files, { size: formatBytes(found.bytes) })}
              </div>
              {(everything || found.items > 0) && (
                <div style={{ color: "var(--yellow-text)", marginTop: 2 }}>
                  {everything
                    ? t("Matches every file in the library.")
                    : tn({ one: "1 item will be deleted",
                           other: "{n} items will be deleted" },
                         found.items)}
                </div>
              )}
            </>
          )}
      </div>
      {error && (
        <span title={error} style={{ display: "inline-flex",
                                     alignSelf: "center" }}>
          <Icon name="error" size={16} color="var(--red)" />
        </span>
      )}
      {running ? (
        // STOP, not Cancel: Cancel is the button beside it that closes a
        // dialog having done nothing, and this one stops work already under
        // way — the chunks it has committed stay removed. Two buttons reading
        // "Cancel" and meaning different things is worse than a second verb.
        <Button variant="ghost" icon="close"
                     onClick={() => { if (jobId) void api.cancelFilePrune(jobId); }}>
          {t("Stop")}
        </Button>
      ) : (
        <>
          <Button variant="ghost" onClick={onClose}>{t("Cancel")}</Button>
          <Button variant="primary" icon="delete" onClick={ask}
                         disabled={!found || found.files === 0}>
            {t("Remove")}
          </Button>
        </>
      )}
    </>
  );

  return (
    // NOT guarded with `unsaved`: a rule is a question, not work. Nothing here
    // is written until Remove, and closing a half-filled rule loses a few
    // keystrokes — arguing about that is what the guard is for elsewhere.
    <Overlay icon="delete_sweep" title={t("Remove files by rule")}
             width={520} onClose={onClose} footer={footer}>
      {/* The body has no padding of its own — that is each dialog's to give,
          and 20 is what the header and the footer already use. */}
      <div style={{ padding: "18px 20px", display: "flex",
                    flexDirection: "column", gap: 16 }}>
        {/* WHAT MATCHES, then WHAT IS SPARED — two sections, in the page's
            own shape, because they are two different questions and not two
            halves of one list. A threshold left empty is not a rule that
            matches nothing: with all three empty the matcher takes every
            file and Keep is the whole rule, which is how "every version but
            the active one" is said. */}
        <Section title={t("Remove when")}>
          {/* FIRST, because it says what the thresholds under it are asked
              ABOUT. A sequence container owns no file of its own and is
              reached by none of these, whichever this is set to. */}
          <Choice
            label={t("Media kind")} value={kind}
            onChange={(v) => setKind(v as StoragePruneRule["kind"])}
            options={[{ value: "", label: t("Images and videos") },
                      { value: "image", label: t("Images only") },
                      { value: "video", label: t("Videos only") }]} />
          <Threshold label={t("Resolution under")}
                     unit={t("MP")} value={minMp} onChange={setMinMp} />
          <Threshold label={t("Shortest edge under")}
                     unit={t("px")} value={minEdge} onChange={setMinEdge} />
          <Threshold label={t("Longest edge under")} last
                     unit={t("px")} value={minLong} onChange={setMinLong} />
        </Section>
        <Section title={t("Keep")}>
          <Keep label={t("The active file")}
                checked={keepActive} onChange={setKeepActive} />
          <Keep label={t("Edited files")} last
                checked={keepEdited} onChange={setKeepEdited} />
        </Section>
        <div style={hint}>
          {t("Every item in the library is considered, the Trash included — and every file of it, not only the one on show. Removing a file takes the artifacts generated from it as well.")}
        </div>
      </div>
    </Overlay>
  );
}

export function StoragePage() {
  const t = useT();
  const tn = useTn();
  const qc = useQueryClient();
  const [pruning, setPruning] = useState(false);
  const { data, isLoading } = useQuery<StorageOut>({
    queryKey: ["library-storage"],
    queryFn: api.libraryStorage,
    // A walk of the training folder is not free, so this is asked for when
    // the page opens and when something on it changes — never on a timer.
    refetchOnWindowFocus: false,
  });

  const rowDelete = useRowDelete(() => refresh());
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["library-storage"] });
    // The sidebar's footer counts the same bytes.
    void qc.invalidateQueries({ queryKey: ["library-stats"] });
    // AND THE LIBRARY ITSELF: a prune deletes every item it leaves with no
    // file, so the grid behind this dialog is showing pictures that are
    // gone — cards that never fill, counts that no longer add up, until a
    // reload. `bumpLibrary` is the sweep a background process goes through
    // (an import batch, a finished job), which is exactly what this is.
    bumpLibrary();
    // And the prune's own line, which is a statement about the library and
    // is therefore wrong the moment one runs: it is keyed on the RULE, so
    // nothing about a finished run invalidates it by itself, and it would go
    // on promising the files that run had just removed. Cancelling is what
    // makes that unmissable — a part-done prune leaves a count nobody can
    // reconcile — but a finished one was just as stale.
    void qc.invalidateQueries({ queryKey: ["file-prune-preview"] });
  };

  if (isLoading || !data) {
    return (
      <div className="mc-settings-page" style={page}>
        <div style={{ fontSize: "var(--fs-3)", color: "var(--muted)" }}>{t("Measuring…")}</div>
      </div>
    );
  }

  const sum = (rows: { bytes: number }[]) =>
    rows.reduce((n, r) => n + r.bytes, 0);
  const total = sum(data.items) + sum(data.artifacts) + sum(data.other);

  // The bar's segments: one per item kind, then the artifacts as ONE (they
  // are broken out row by row below, and eight thin slivers of yellow would
  // say less than one), then the three named directories, then whatever is
  // left over. Empty segments are dropped — a zero-width slice is a colour
  // in the legend that nothing on the bar corresponds to.
  const otherAt = (key: string) =>
    data.other.find((r) => r.key === key)?.bytes ?? 0;
  const named = ["training", "evaluate", "database", "thumbnails"];
  const candidates: Segment[] = [
    ...data.items.map((r) => ({
      key: r.key, label: t(storageRowLabel(r.key)), bytes: r.bytes,
      color: SEG_COLORS[r.key] ?? SEG_COLORS.rest,
    })),
    { key: "artifacts", label: t("Generated artifacts"),
      bytes: sum(data.artifacts), color: SEG_COLORS.artifacts },
    ...named.map((key) => ({
      key, label: t(storageRowLabel(key)), bytes: otherAt(key),
      color: SEG_COLORS[key] ?? SEG_COLORS.rest,
    })),
    { key: "leftover", label: "", color: SEG_COLORS.rest,
      bytes: sum(data.other) - named.reduce((n, k) => n + otherAt(k), 0) },
  ].filter((seg) => seg.bytes > 0).sort((a, b) => b.bytes - a.bytes);

  // ANYTHING UNDER A TWENTIETH GOES INTO "Other". A segment at 0.3% is two
  // pixels of colour and a legend entry as wide as the ones that matter — it
  // costs the bar more room in the reading than it takes on it. The threshold
  // is on the SHARE rather than a count, so a library with six even parts
  // keeps all six and one dominated by its films keeps two.
  //
  // Other is LAST, not sorted in with the rest: it is a bucket rather than a
  // peer, and its size says nothing about any one thing in it. Anything with
  // no name of its own (the leftover directories) is in it by construction.
  const big = candidates.filter(
    (seg) => seg.label && total > 0 && seg.bytes / total >= SEGMENT_FLOOR);
  const restBytes = total - big.reduce((n, seg) => n + seg.bytes, 0);
  const segments: Segment[] = restBytes > 0
    ? [...big, { key: "rest", label: t("Other"), bytes: restBytes,
                 color: SEG_COLORS.rest }]
    : big;

  return (
    <div className="mc-settings-page" style={page}>
      <Section
        title={t("This library")}
        action={<span style={{ fontSize: "var(--fs-3)", color: "var(--text-2)" }}>
          {formatBytes(total)}
        </span>}
      >
        {/* The bar FIRST: it is the answer, and the two facts under it are
            where and on what. */}
        <TotalBar segments={segments} total={total}
                  totalLabel={t("Library")} />
        {/* Two facts, each on its own line with its own label — the path was
            a sentence with a 60-character mono string wrapped into the middle
            of it, which reads as a mistake wherever the line happens to
            break. A path is a value, so it is laid out as one. */}
        <Fact label={t("Library folder")} first>
          <span style={{
            fontFamily: "var(--mono)", fontSize: "var(--fs-2)",
            overflowWrap: "anywhere",
            userSelect: "text", WebkitUserSelect: "text",
          }}>
            {data.data_dir}
          </span>
        </Fact>
        {data.disk_total > 0 && (
          <Fact label={t("Free on this volume")} last>
            {formatBytes(data.disk_free)}
          </Fact>
        )}
      </Section>

      {/* The prune's door sits on ITEMS, because item FILES are what it
          removes — the sections below it are types the app generated and
          each already has its own Delete. */}
      <Section
        title={t("Items")}
        action={
          <Button variant="soft" size="xs" onClick={() => setPruning(true)}>
            <Icon name="delete_sweep" size={13} /> {t("Remove files…")}
          </Button>
        }
      >
        {data.items.map((r, i) => (
          <Row key={r.key} icon={STORAGE_ROW_ICONS[r.key] ?? "description"}
               label={t(storageRowLabel(r.key))} count={r.count} bytes={r.bytes}
               of={total} last={i === data.items.length - 1} />
        ))}
        {data.items.length === 0 && <Empty text={t("Nothing imported yet")} />}
      </Section>
      {data.trashed.count > 0 && (
        <div style={{ ...hint, marginTop: -8 }}>
          {t("Of that, {size} belongs to items in the trash — emptying it gives that back.",
             { size: formatBytes(data.trashed.bytes) })}
        </div>
      )}

      <Section
        title={t("Generated artifacts")}
        action={<span style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>
          {formatBytes(sum(data.artifacts))}
        </span>}
      >
        {data.artifacts.map((r, i) => {
          const kind = artifactKind(r.kind);
          return (
            <Row
              key={`${r.kind}:${r.model}`}
              icon={kind.icon}
              label={tn(kind.name, r.count)}
              sub={r.model || undefined}
              count={r.count} bytes={r.bytes} of={total}
              last={i === data.artifacts.length - 1}
              action={<DeleteArtifacts row={r} label={tn(kind.name, r.count)}
                                       onDone={refresh} />}
            />
          );
        })}
        {data.artifacts.length === 0 && (
          <Empty text={t("No model has produced anything yet")} />
        )}
      </Section>
      <div style={hint}>
        {t("A cached training latent is re-encoded by the next run that needs it; anything else here means running its model again.")}
      </div>

      <Section title={t("Everything else")}>
        {data.other.map((r, i) => (
          <Row key={r.key} icon={STORAGE_ROW_ICONS[r.key] ?? "folder"}
               label={t(storageRowLabel(r.key))} count={r.count} bytes={r.bytes}
               of={total} last={i === data.other.length - 1}
               // The rows with something to do about them: the backups, the
               // thumbnails (made again on demand), and — where training is
               // offered — the Evaluate results and the finished training
               // jobs. Scratch is the app's own and the database is the
               // library; the kept adapters are the user's.
               action={rowDelete(r)} />
        ))}
        {data.other.length === 0 && <Empty text={t("Nothing here")} />}
      </Section>

      {pruning && (
        <PruneOverlay onClose={() => setPruning(false)} onDone={refresh} />
      )}
    </div>
  );
}

/** A labelled value in the summary panel: the label in the left column, the
 *  value free to be as long as it is. */
function Fact({ label, children, first, last }: {
  label: string; children: React.ReactNode;
  first?: boolean; last?: boolean;
}) {
  return (
    <div style={{
      display: "flex", gap: 12, padding: "9px 14px", fontSize: "var(--fs-3)",
      color: "var(--text-2)", alignItems: "baseline",
      borderTop: first ? "1px solid var(--border-soft)" : undefined,
      borderBottom: last ? "none" : "1px solid var(--border-soft)",
    }}>
      <div style={{ flex: "0 0 128px", color: "var(--muted)" }}>{label}</div>
      <div style={{ flex: 1, minWidth: 0 }}>{children}</div>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <EmptyState dense line={text} style={{ padding: "12px 14px", fontSize: "var(--fs-3)" }} />;
}

/** The settings pages' own section frame. Spelled out here rather than
 *  imported from `SettingsOverlay`, which would be a cycle — that file
 *  renders this page. */
// The section is the shared one (`shared/SettingsRows`).

const page: React.CSSProperties = {
  flex: 1, padding: 20, display: "flex", flexDirection: "column", gap: 16,
  overflowY: "auto",
};
const hint: React.CSSProperties = {
  fontSize: "var(--fs-2)", color: "var(--muted)", lineHeight: 1.55,
  userSelect: "text", WebkitUserSelect: "text",
};
/** The page's secondary button — every Delete, and Remove until the rule is
 *  about to empty an item.
 *
 *  It RISES off the row: `--surface-float` is the raised token, and it does
 *  the right thing in both themes for opposite reasons — lighter than the
 *  panel in the dark one, still white against white in the light one, where
 *  a defined border is what says "button". Transparent, `--border` and
 *  `--muted` was the old spelling, and that is what a DISABLED control looks
 *  like everywhere else in this app: these read as greyed out beside rows
 *  that were not. The border, the text colour and the weight are the
 *  Overlay's own secondary button, so the page agrees with every dialog. */

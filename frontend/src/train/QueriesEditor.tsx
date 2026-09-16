// The job editor's dataset section: one weighted item query per row, each with
// an embedded QueryBuilder (prop-driven, local state) and a live match count.
import React from "react";
import { IconButton } from "../shared/IconButton";
import { Button } from "../shared/Button";
import { useQuery } from "@tanstack/react-query";
import { api, TrainDatasetQuery } from "./api";
import { tryParse, toRequest } from "../query/tree";
import { QueryBuilder } from "../query/QueryBuilder";
import { Icon } from "../shared/Icon";
import { useT, useTn } from "./i18n";
import { inputStyle } from "./FormRows";

// A small square +/- button flanking the weight field.
function StepButton({ icon, onClick }: { icon: "add" | "remove"; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        width: 22, height: 28, flex: "0 0 auto", display: "flex",
        alignItems: "center", justifyContent: "center", borderRadius: "var(--r-2)",
        border: "1px solid var(--border-strong)", background: "var(--panel-2)",
        color: "var(--muted)", cursor: "pointer",
      }}
    >
      <Icon name={icon} size={14} />
    </button>
  );
}

function MatchCount({ search }: { search: string }) {
  const t = useT();
  const tn = useTn();
  const parsed = tryParse(search);
  const tree = parsed ? toRequest(parsed) : null;
  const { data, isFetching } = useQuery({
    queryKey: ["train-qcount", search],
    queryFn: () => api.itemsQuery({ query: tree, page: 1, page_size: 1 }),
    enabled: parsed !== null || search.trim() === "",
    staleTime: 15_000,
  });
  if (search.trim() !== "" && parsed === null) {
    return <span style={{ fontSize: "var(--fs-2)", color: "var(--red-text)" }}>{t("invalid query")}</span>;
  }
  return (
    <span style={{ fontSize: "var(--fs-2)", color: "var(--muted)", fontVariantNumeric: "tabular-nums" }}>
      {isFetching ? "…"
        : data != null ? tn({ one: "1 item", other: "{n} items" }, data.total)
        : ""}
    </span>
  );
}

/** Which regularization queries will contribute NOTHING to the run.
 *
 *  A reminder pool whose every picture is also matched by a training query is
 *  empty, because a training query wins — the run reports it in its log, which
 *  is long after somebody queued it and walked away. Answered by the SERVER
 *  (`dataset.regularization_ids`) rather than worked out here: a warning that
 *  could disagree with what the run does is worse than no warning at all.
 *
 *  Keyed on the queries alone plus the two config fields that move the scope,
 *  not on the whole config — otherwise every keystroke in the learning rate
 *  refetches a set difference over the library.
 */
function useEmptyRegPools(queries: TrainDatasetQuery[], config: any): Set<number> {
  const anyReg = queries.some((q) => q.regularize);
  const key = JSON.stringify([
    queries.map((q) => [q.tree, !!q.regularize]),
    config?.video?.include ?? false, config?.captions?.source ?? "",
  ]);
  const { data } = useQuery({
    queryKey: ["train-reg-preview", key],
    queryFn: () => api.trainQueriesPreview(config),
    // Only worth asking when there IS a reminder pool AND something for it to
    // lose against: one query alone can never be fully overlapped.
    enabled: anyReg && queries.length > 1,
    staleTime: 15_000,
  });
  const out = new Set<number>();
  (data?.queries ?? []).forEach((q, i) => {
    if (queries[i]?.regularize && q.matched > 0 && q.contributes === 0) out.add(i);
  });
  return out;
}


export function QueriesEditor({ queries, onChange, config }: {
  queries: TrainDatasetQuery[];
  onChange: (qs: TrainDatasetQuery[]) => void;
  /** The config being edited. Only the preview uses it, and it needs the whole
   *  thing: which pictures a query can reach depends on `video.include` and on
   *  whether captions come from instructions. */
  config: unknown;
}) {
  const t = useT();
  const empty = useEmptyRegPools(queries, config);

  const update = (i: number, patch: Partial<TrainDatasetQuery>) => {
    const next = queries.slice();
    next[i] = { ...next[i], ...patch };
    onChange(next);
  };
  const setSearch = (i: number, search: string) => {
    const parsed = tryParse(search);
    update(i, { search, tree: parsed ? toRequest(parsed) : null });
  };

  return (
    <div>
      {queries.map((q, i) => (
        <div
          key={i}
          style={{
            background: "var(--panel)", border: "1px solid var(--border)",
            borderRadius: "var(--r-7)", padding: 12, marginBottom: 10,
          }}
        >
          <div style={{
            display: "flex", alignItems: "center", gap: 10, marginBottom: 8,
          }}>
            <span style={{ fontSize: "var(--fs-2)", fontWeight: 600, color: "var(--text-2)" }}>
              {t("Query")} {i + 1}
            </span>
            <MatchCount search={q.search} />
            <div style={{ flex: 1 }} />
            {/* WHAT THIS POOL IS FOR. A checkbox rather than a second kind of
                row: it is the same query over the same library, and only what
                the run does with the pictures differs. Named the standard way
                so a guide written elsewhere is findable here, with the plain
                explanation in the tooltip and in the docs.

                `!!` on the checkbox because a job saved before this field
                existed has queries without it: the backend fills missing keys
                per SECTION, and a query is an entry in a LIST, which is
                carried over whole. An `undefined` there would make React
                switch the input from uncontrolled to controlled on the first
                click. */}
            <label style={{
              display: "flex", alignItems: "center", gap: 5,
              fontSize: "var(--fs-2)", color: q.regularize ? "var(--accent)" : "var(--muted)",
              cursor: "pointer",
            }}
              title={t("Pictures that remind the model what it already knows, instead of teaching it something new — they stop what you are training from spreading to everything else of the same kind. They never get the trigger word.")}>
              <input
                type="checkbox"
                checked={!!q.regularize}
                onChange={(e) => update(i, { regularize: e.target.checked })}
                style={{ accentColor: "var(--accent)", cursor: "pointer" }}
              />
              {t("Regularization")}
            </label>
            <label style={{
              display: "flex", alignItems: "center", gap: 6,
              fontSize: "var(--fs-2)", color: "var(--muted)",
            }}>
              {t("Weight")}
              <div style={{ display: "flex", alignItems: "center", gap: 3 }}
                title={t("Relative sampling probability: a weight-2 query's images are drawn twice as often as a weight-1 query's.")}>
                <StepButton icon="remove"
                  onClick={() => update(i, { weight: Math.max(0.5, Math.round((q.weight - 0.5) * 100) / 100) })} />
                <input
                  value={String(q.weight)}
                  inputMode="decimal"
                  onChange={(e) => {
                    const v = Number(e.target.value.replace(",", "."));
                    if (isFinite(v) && v > 0) update(i, { weight: v });
                  }}
                  style={{ ...inputStyle, width: 46, height: 28, textAlign: "right" }}
                />
                <StepButton icon="add"
                  onClick={() => update(i, { weight: Math.round((q.weight + 0.5) * 100) / 100 })} />
              </div>
            </label>
            <IconButton icon="delete" size={28} glyph={16} tone="muted" disabled={queries.length === 1}
              title={t("Remove query")}
              onClick={() => onChange(queries.filter((_, k) => k !== i))} />
          </div>
          <QueryBuilder search={q.search} setSearch={(s: string) => setSearch(i, s)} />
          {q.search.trim() === "" && (
            <div className="mc-copy" style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", marginTop: 6 }}>
              {t("Empty query = every image in the library.")}
            </div>
          )}
          {q.regularize && (
            <div className="mc-copy" style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", marginTop: 6 }}>
              {t("These pictures hold the model's existing idea of the subject in place: pick the same KIND of thing you are training, but not the thing itself. You do not need to exclude your training pictures — anything an ordinary query matches stays a training picture. A reminder query that matches only training pictures leaves this pool empty, and the run says so in its log.")}
            </div>
          )}
          {/* AMBER, not red: nothing here is invalid — the run trains
              perfectly well, it simply is not regularized — and this is the
              app's colour for "a machine worked this out and it is waiting on
              you". It sits under the help text that predicts it, so the
              sentence and the instance of it read as one thing. */}
          {empty.has(i) && (
            <div style={{
              display: "flex", alignItems: "flex-start", gap: 7, marginTop: 7,
              padding: "7px 9px", borderRadius: "var(--r-4)",
              background: "var(--yellow-dim)",
              border: "1px solid var(--yellow)",
            }}>
              <Icon name="warning" size={14} style={{ color: "var(--yellow-text)", flex: "0 0 auto", marginTop: 1 }} />
              <span className="mc-copy" style={{ fontSize: "var(--fs-2)", lineHeight: 1.45, color: "var(--text-2)" }}>
                {t("Every picture this finds is also matched by a training query, so it contributes nothing and the run will not be regularized. Narrow it to pictures the run is NOT about.")}
              </span>
            </div>
          )}
        </div>
      ))}
      <Button variant="ghost" size="sm"
    onClick={() => onChange([...queries,
     { tree: null, search: "", weight: 1, regularize: false }])}>
        <Icon name="add" size={16} />
        {t("Add query")}
      </Button>
    </div>
  );
}

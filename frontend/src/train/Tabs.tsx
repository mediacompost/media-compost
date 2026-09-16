/** The Train / Evaluate / Models pill box in the top bar.
 *
 * It lives HERE rather than in TopBar because its pollers speak the trainer's
 * API — the app may not import that, so the whole box crosses the boundary
 * through the same lazy entry as the pages. The app mounts it only when the
 * deployment trains at all, which is also why the pollers need no `enabled`
 * guard of their own: unmounted is disabled.
 */

import React from "react";
import { useQuery } from "@tanstack/react-query";

import { Icon } from "../shared/Icon";
import { api } from "./api";
import { useT } from "./i18n";

/** A quiet corner dot on the icon, not a spinner next to the label — enough
 *  to say "something is running" without wobbling the tab's layout. */
function ActivityDot() {
  return (
    <span style={{
      position: "absolute", top: -1, right: -2,
      width: 6, height: 6, borderRadius: "50%",
      background: "var(--accent)",
      boxShadow: "0 0 0 2px var(--bg)",
    }} />
  );
}

export function TrainTabs({ view, setView, tabStyle }: {
  view: string;
  setView: (v: "train" | "evaluate" | "models") => void;
  /** TopBar's own tab styling, passed in so the two pill boxes stay one
   *  visual system however either side restyles. */
  tabStyle: (active: boolean) => React.CSSProperties;
}) {
  const t = useT();
  // A running training job shows on the Train tab from anywhere. Same query
  // key as the Train tab's list, so this is one shared cache entry — the
  // slow poll here only matters while that tab is closed.
  const { data: trainJobs } = useQuery({
    queryKey: ["train-jobs"], queryFn: api.trainJobs,
    refetchInterval: 15000,
  });
  const trainingActive = (trainJobs?.jobs ?? []).some(
    (j) => j.status === "running" || j.status === "pausing");
  // Same arrangement for Evaluate: a generation can be queued behind a
  // training run for a long time, which is exactly when you are not looking
  // at that tab.
  const { data: evalRuns } = useQuery({
    queryKey: ["eval-runs"], queryFn: api.evalRuns,
    refetchInterval: 15000,
  });
  const evalActive = (evalRuns?.runs ?? []).some(
    (r) => r.status === "running" || r.status === "queued");
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 2,
        background: "var(--bg)",
        border: "1px solid var(--border)",
        borderRadius: "var(--r-5)",
        padding: 3,
        // Pull against the row's 16px gap so the two pill boxes sit close
        // together (they form one navigation cluster).
        marginLeft: -10,
      }}
    >
      <button onClick={() => setView("train")} style={tabStyle(view === "train")}
        title={trainingActive ? t("A training job is running") : undefined}>
        <span style={{ position: "relative", display: "inline-flex" }}>
          <Icon name="psychiatry" size={17} />
          {trainingActive && <ActivityDot />}
        </span>
        {t("Train")}
      </button>
      <button onClick={() => setView("evaluate")} style={tabStyle(view === "evaluate")}
        title={evalActive ? t("Images are being generated") : undefined}>
        <span style={{ position: "relative", display: "inline-flex" }}>
          <Icon name="science" size={17} />
          {evalActive && <ActivityDot />}
        </span>
        {t("Evaluate")}
      </button>
      <button onClick={() => setView("models")} style={tabStyle(view === "models")}>
        <Icon name="deployed_code" size={17} />
        {t("Models")}
      </button>
    </div>
  );
}

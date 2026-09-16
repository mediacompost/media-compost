/** The three training views behind one lazy door.
 *
 * `index.tsx` is the only module the app imports from this directory, and it
 * is imported exactly once, through `React.lazy` — which is what keeps these
 * ~10k lines out of the main bundle and off the wire entirely on a deployment
 * that does not train.
 */

import React from "react";

import { ErrorBoundary } from "../shared/ErrorBoundary";
import { useT } from "./i18n";
import { EvaluateView } from "./EvaluateView";
import { ModelsView } from "./ModelsView";
import { TrainView } from "./TrainView";

export function TrainPages({ view, jobUid, onSelectJob }: {
  view: string;
  jobUid: string | null;
  onSelectJob: (uid: string | null) => void;
}) {
  const t = useT();
  // Per view, not just at the root: a crash in one tab leaves the rest of
  // the app usable, and says what happened instead of going blank.
  return view === "train" ? (
    <ErrorBoundary key={view} what={t("The Train tab")} t={t}>
      <TrainView jobUid={jobUid} onSelectJob={onSelectJob} />
    </ErrorBoundary>
  ) : view === "evaluate" ? (
    <ErrorBoundary key={view} what={t("The Evaluate tab")} t={t}><EvaluateView /></ErrorBoundary>
  ) : (
    <ErrorBoundary key={view} what={t("The Models tab")} t={t}><ModelsView /></ErrorBoundary>
  );
}

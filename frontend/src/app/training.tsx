/** Everything the app knows about training, in one file.
 *
 * This is the ONLY module that names `../train` (`boundaries.test.ts` holds
 * the whole tree to that), and it names it exclusively inside `React.lazy` —
 * so the train UI is a chunk of its own: the main bundle stops carrying its
 * ~10k lines, and a deployment that does not train never fetches them at all.
 *
 * It also owns `useTrainingOffered`, which used to be `features.ts`: what
 * this deployment offers, as opposed to what the user prefers. A setting is
 * a choice; this is a fact about the machine the server runs on, fixed at
 * launch (`MEDIA_COMPOST_TRAINING=0`). Three callers ask it for three
 * reasons — whether to draw the tabs, whether to mount the pages behind
 * them, and where to send somebody who arrives at `/train` from a bookmark.
 */

import React, { Suspense } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "./api";
import { useUI } from "./store";

/** Whether Train / Evaluate / Models exist here.
 *
 * Defaults to TRUE while the answer is in flight: a machine that trains is
 * the assumption, and flashing the tabs away a moment after the app opens is
 * worse than showing them a moment late on the rare deployment that has none.
 */
export function useTrainingOffered(): boolean {
  const { data } = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    // A launch-time fact cannot change under a running server, so this is
    // fetched once and never refetched or expired.
    staleTime: Infinity,
    gcTime: Infinity,
    refetchOnWindowFocus: false,
  });
  return data?.training ?? true;
}

const Pages = React.lazy(() => import("../train"));
const Tabs = React.lazy(() =>
  import("../train").then((m) => ({ default: m.TrainTabs })));

/** The Train / Evaluate / Models views (App mounts this for those three).
 *
 * The selected job stays in the APP's store — it is routing state, the
 * `?job=` parameter `location.ts` reads and writes — and reaches the train
 * package as props, which is what keeps that package free of the app's
 * store.
 */
export function TrainingPages({ view }: { view: string }) {
  const jobUid = useUI((s) => s.trainJobUid);
  const setJobUid = useUI((s) => s.setTrainJobUid);
  return (
    <Suspense fallback={null}>
      <Pages view={view} jobUid={jobUid} onSelectJob={setJobUid} />
    </Suspense>
  );
}

/** The top bar's training pill box — absent, not disabled, on a deployment
 *  that does not train: tabs leading to a machine that could never finish a
 *  run are tabs of false promise. Mounting is also the poll gate, so the
 *  15-second pollers inside never fire against refused routes. */
export function TrainingTabs(props: {
  view: string;
  setView: (v: "train" | "evaluate" | "models") => void;
  tabStyle: (active: boolean) => React.CSSProperties;
}) {
  const offered = useTrainingOffered();
  if (!offered) return null;
  return (
    <Suspense fallback={null}>
      <Tabs {...props} />
    </Suspense>
  );
}

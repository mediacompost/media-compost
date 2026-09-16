/** The three judging sessions' waiting and failing states — `shared/Loading`
 *  in its overlay tone, named for the sessions so a fourth one reaches for
 *  the same two. */
import React from "react";
import { Loading, Trouble } from "../../../shared/Loading";

export function SessionWait({ label }: { label: string }) {
  return <Loading tone="overlay" label={label} />;
}

export function SessionTrouble({ message, detail, onRetry, t }: {
  /** What did not happen, in the session's own words. */
  message: string;
  /** The server's reason, when there is one. */
  detail: string | null;
  onRetry: () => void;
  t: (str: string) => string;
}) {
  return <Trouble tone="overlay" message={message} detail={detail}
                  onRetry={onRetry} retryLabel={t("Try again")} />;
}

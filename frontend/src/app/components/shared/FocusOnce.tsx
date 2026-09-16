/** Clears a "land here" flag once the row it names has been shown.
 *
 * A jump between tabs names a tab AND a row, and the row is flashed on
 * arrival — but the flag has to go, or the next visit to that tab flashes
 * something nobody asked about. Its own component rather than an effect in
 * each section, because there are four of them now and the timing (long
 * enough for the animation, short enough not to outlive the visit) is one
 * decision.
 */
import { useEffect } from "react";

/** Slightly longer than `.mc-flash`, so the clear never cuts the fade off. */
const HOLD_MS = 1800;

export function FocusOnce({ onDone }: { onDone: () => void }) {
  useEffect(() => {
    const id = window.setTimeout(onDone, HOLD_MS);
    return () => window.clearTimeout(id);
  }, [onDone]);
  return null;
}

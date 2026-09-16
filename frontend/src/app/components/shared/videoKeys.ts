/** THE TRANSPORT'S KEYBOARD, shared by the video editor and the annotator.
 *
 * One map for both, because they are two halves of one window over one film:
 * a key that paused in one and did nothing in the other would be one feature
 * wearing two behaviours. The conventions are the ones every editor has —
 * anybody who has used one already knows them, which is the whole reason to
 * take the keys at all:
 *
 *   Space / K   play or pause
 *   ← / →       one frame back / forward (Shift: one second)
 *   J / L       shuttle back / forward; again the same way doubles the speed
 *   Home / End  the first / last frame
 *   , / .       one frame back / forward, the other spelling
 *
 * PURE, and it decides only WHICH action a key is — the transport performs
 * it. That is what lets the two windows differ where they must: the annotator
 * gives Space and ←/→ back to panning and its tab strip when the tab being
 * annotated is a PICTURE, which it can only do by asking for the action and
 * declining it.
 */
export type VideoKey =
  | { kind: "play" }
  | { kind: "step"; frames: number }
  | { kind: "seconds"; by: number }
  | { kind: "shuttle"; dir: number }
  | { kind: "edge"; to: 0 | 1 };

/** What this keystroke means to a film, or null for "not ours".
 *
 * A modifier means the key belongs to somebody else (⌘Z, ⌘S, ⌘←) — SHIFT
 * excepted, which is this map's own "further" modifier.
 */
export function videoKeyAction(e: {
  key: string; code?: string; shiftKey?: boolean;
  metaKey?: boolean; ctrlKey?: boolean; altKey?: boolean;
}): VideoKey | null {
  if (e.metaKey || e.ctrlKey || e.altKey) return null;
  const k = e.key.toLowerCase();
  if (e.code === "Space" || e.key === " " || k === "k") return { kind: "play" };
  if (k === "arrowleft" || k === ",")
    return e.shiftKey ? { kind: "seconds", by: -1 } : { kind: "step", frames: -1 };
  if (k === "arrowright" || k === ".")
    return e.shiftKey ? { kind: "seconds", by: 1 } : { kind: "step", frames: 1 };
  if (k === "j") return { kind: "shuttle", dir: -1 };
  if (k === "l") return { kind: "shuttle", dir: 1 };
  if (k === "home") return { kind: "edge", to: 0 };
  if (k === "end") return { kind: "edge", to: 1 };
  return null;
}

/** Perform one, against a transport. Kept beside the map so the two windows
 *  cannot drift into two readings of the same keystroke. */
export function runVideoKey(
  action: VideoKey,
  play: {
    togglePlay: () => void;
    stepFrame: (dir: number) => void;
    seek: (t: number) => void;
    nowTime: () => number;
    shuttle: (dir: number) => void;
    duration: number;
  },
) {
  switch (action.kind) {
    case "play": play.togglePlay(); break;
    case "step": play.stepFrame(action.frames); break;
    case "seconds": play.seek(play.nowTime() + action.by); break;
    case "shuttle": play.shuttle(action.dir); break;
    // The LAST frame rather than the duration: a seek to the duration is
    // past the end, where a `<video>` shows nothing at all.
    case "edge": play.seek(action.to === 0 ? 0
      : Math.max(0, play.duration - 0.001)); break;
  }
}

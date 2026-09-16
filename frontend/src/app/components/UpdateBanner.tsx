import { useState, useSyncExternalStore } from "react";
import {
  restartServer, serverHasUpdated, serverNeedsRestart, subscribeToUpdates,
  type RestartBusy,
} from "../../shared/build";
import { useT } from "../i18n";
import { LAYER } from "../../shared/layers";

/**
 * "The app was updated — reload."
 *
 * It does NOT reload for you, and that is the whole design. This banner can
 * appear over the image editor with an unsaved buffer in it, over the
 * annotator with a box half-drawn, or over a caption somebody is typing; a
 * reload takes all of that with it. A stale page is a small problem and losing
 * work is a large one, so the choice stays with whoever knows what is on
 * screen.
 *
 * Mounted ONCE in `main.tsx`, above the whole tree, so it shows over the
 * library and the item-window overlay alike — every half of the app makes the
 * same writes, and the server refuses them all on the same rule.
 *
 * It sits top-CENTRE. The bottom is where this app puts things that belong to
 * what you are doing — the selection and undo bars, the toasts, the video
 * transport — and a message about the SERVER is not one of them; at the top it
 * reads as coming from outside the work, which is where it comes from.
 *
 * No icon. It carried a `material-symbols-rounded` glyph, which is a FONT:
 * wherever that font has not loaded yet the browser renders the ligature's
 * source text instead, so the banner announced itself with the word "sync" in
 * large accent letters beside a sentence that already says what happened.
 *
 * IT SAYS WHICH OF THE TWO UPDATES THIS IS, because reloading only fixes one
 * of them. A rebuild while the tab sat open leaves the page behind the server:
 * reload and it is over. A package UPDATE replaces the files under a running
 * process, so the reload lands on the new bundle and then talks to the old
 * server — the banner used to advise the one action that cannot work, and the
 * report that prompted this said exactly that. `serverNeedsRestart()` asks the
 * server which case it is, and the button then does what is needed: reload, or
 * restart and then reload.
 */
export function UpdateBanner() {
  const t = useT();
  const stale = useSyncExternalStore(subscribeToUpdates, serverHasUpdated,
                                     () => false);
  const needsRestart = useSyncExternalStore(subscribeToUpdates,
                                            serverNeedsRestart, () => null);
  // "" while idle; otherwise what the server said about it.
  const [busy, setBusy] = useState<RestartBusy | null>(null);
  const [phase, setPhase] = useState<"idle" | "restarting" | "failed">("idle");
  if (!stale) return null;

  const go = (force: boolean) => {
    if (!needsRestart) { window.location.reload(); return; }
    setPhase("restarting");
    setBusy(null);
    restartServer(force)
      .then(() => window.location.reload())
      .catch((e: Error & { busy?: RestartBusy }) => {
        // A refusal naming work in flight is an offer, not a failure: the
        // button comes back reading "Restart anyway".
        if (e.busy) { setBusy(e.busy); setPhase("idle"); return; }
        setPhase("failed");
      });
  };
  const message = phase === "failed"
    ? t("The server could not be restarted — restart it yourself to finish the update.")
    : busy
      ? t("Work is still running ({jobs} jobs, {imports} imports). Restarting stops it.",
          { jobs: String(busy.jobs), imports: String(busy.imports) })
      : needsRestart
        ? t("Media Compost was updated. The server is still running the old version.")
        : t("The backend was updated. Please reload the page.");
  const label = phase === "restarting"
    ? t("Restarting…")
    : busy
      ? t("Restart anyway")
      : needsRestart
        ? t("Restart & reload")
        : t("Reload");
  return (
    <div
      role="status"
      style={{
        position: "fixed", top: 16, left: "50%", translate: "-50%",
        zIndex: LAYER.banner, display: "flex", alignItems: "center", gap: 12,
        padding: "10px 12px 10px 14px", borderRadius: "var(--r-6)",
        background: "var(--panel)", color: "var(--text)",
        border: "1px solid var(--accent)",
        boxShadow: "var(--shadow-2)",
        font: "inherit", fontSize: "var(--fs-4)",
      }}
    >
      <span>{message}</span>
      <button
        disabled={phase === "restarting"}
        onClick={() => go(busy !== null)}
        style={{
          height: 26, padding: "0 12px", borderRadius: "var(--r-3)", border: "none",
          background: "var(--accent)", color: "var(--on-accent)",
          fontWeight: 600, fontSize: "var(--fs-3)",
          cursor: phase === "restarting" ? "default" : "pointer",
          opacity: phase === "restarting" ? 0.7 : 1,
          fontFamily: "inherit",
        }}
      >
        {label}
      </button>
    </div>
  );
}

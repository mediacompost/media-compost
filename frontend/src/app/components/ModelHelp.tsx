import { useEffect } from "react";
import { api } from "../api";
import { useT } from "../i18n";
import { useSetupRun } from "../../shared/useSetupRun";
import { renderAnsi } from "../../shared/ansi";
import { Icon } from "../../shared/Icon";
import { Overlay } from "../../shared/Overlay";

/** The minimal shape needed to offer a model's setup. Both ModelInfo (action
 *  menu) and ModelCacheInfo (Settings) satisfy it. */
export interface ModelHelpTarget {
  name: string;
  note?: string;
  url?: string;
  // Plugin key whose setup the server can run itself.
  setup_key?: string;
}

/** The "Run setup" panel: starts the server-side setup runner for a plugin,
 *  streams its combined command log while polling, and — once the server
 *  re-execs itself on success — waits for /api/health to come back and reloads
 *  the page so the freshly detected packages/envs show up everywhere. */
function SetupRunner({ pluginKey }: { pluginKey: string }) {
  const t = useT();
  const { phase, log, error, logRef, start, busy } = useSetupRun({
    status: () => api.setupStatus(pluginKey),
    run: () => api.runSetup(pluginKey),
    key: pluginKey,
  });
  return (
    <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <button
          onClick={start}
          disabled={busy}
          style={{
            display: "inline-flex", alignItems: "center", gap: 7, padding: "7px 14px",
            borderRadius: "var(--r-4)", border: "none", cursor: busy ? "default" : "pointer",
            background: busy ? "var(--bg-deep)" : "var(--accent)",
            color: busy ? "var(--muted)" : "var(--on-accent)", fontSize: "var(--fs-3)", fontWeight: 600,
            fontFamily: "inherit",
            // THE BUTTON KEEPS ITS OWN WIDTH; the sentence beside it takes what
            // is left. A flex item shrinks by default, so the explanation was
            // squeezing the one control in this dialog until "Run setup" broke
            // over two lines — and the label grows with the phase ("Restarting
            // the server…"), so it is the wrong element to give the slack to.
            flexShrink: 0, whiteSpace: "nowrap",
          }}
        >
          <Icon
            name={phase === "restarting" ? "restart_alt" : busy ? "progress_activity" : "terminal"}
            size={15}
            // Both busy glyphs are circular and the whole busy stretch is a
            // wait, so the spin runs through the restart too — a still circle
            // in a disabled button reads as a run that has stalled.
            spin={busy}
          />
          {phase === "restarting" ? t("Restarting the server…")
            : phase === "running" ? t("Running setup…")
            : phase === "error" ? t("Retry setup")
            : t("Run setup")}
        </button>
        <span style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-2)", color: "var(--muted-2)" }}>
          {/* "the commands above" was true when this button sat under a list
              of them. It installs the packages AND downloads the weights now,
              and the second half is what makes it take a while — worth saying
              before somebody presses it, not after. */}
          {phase === "restarting"
            ? t("The page reloads when the server is back.")
            : phase === "running"
            ? t("Installing packages and downloading weights — this can take a while.")
            : pluginKey === "all"
            ? t("Installs everything each model needs, downloads their weights, then restarts the server once at the end.")
            : t("Installs everything this model needs, downloads its weights, then restarts the server.")}
        </span>
      </div>
      {error && (
        <div style={{ marginTop: 8, fontSize: "var(--fs-3)", color: "var(--red-text)" }}>
          {error}
        </div>
      )}
      {log && (
        <pre
          ref={logRef}
          style={{
            margin: "10px 0 0", padding: "9px 10px", maxHeight: 200, overflowY: "auto",
            background: "var(--bg-deep)", border: "1px solid var(--border)", borderRadius: "var(--r-4)",
            fontFamily: "var(--mono)", fontSize: "var(--fs-2)", lineHeight: 1.5,
            color: "var(--text-2)", whiteSpace: "pre-wrap", overflowWrap: "anywhere",
            userSelect: "text", WebkitUserSelect: "text",
          }}
        >
          {/* pip colourises its output and draws a progress bar with cursor
              control. Rendered raw, every escape it emits showed up as an
              unrenderable glyph followed by its parameters. */}
          {renderAnsi(log)}
        </pre>
      )}
    </div>
  );
}

/** ENABLING A MODEL IS ONE BUTTON. Behind it is one command —
 *  `-m media_compost.ui.plugins.setup_action <key>` — which installs the packages, builds the
 *  dedicated environment if there is one, picks the torch index this machine
 *  needs, and downloads the weights. So this panel is Run and its log.
 *
 *  THE BY-HAND STEPS ARE GONE, and their absence is the point. They were the
 *  whole overlay once — a page of prose and half a dozen copyable commands —
 *  then a disclosure that started closed, kept because a plugin's `install`
 *  text was the only place several of them said what they actually needed.
 *  What that bought was two descriptions of one procedure: prose written per
 *  plugin, beside the script that does it. Prose cannot be run, so nothing
 *  catches it drifting from `framework.setup_commands`, and every sentence of
 *  it is a string somebody would have to translate into eight languages to
 *  say what the button already does. The one command worth knowing is
 *  `-m media_compost.ui.plugins.setup_action <key>`, which is what the button runs — and it is
 *  documented where a person driving their own environment would look, not in
 *  a modal.
 *
 *  A model with no `setup_key` shows its note and its model card and nothing
 *  else. That branch used to print the `install` prose instead, which it could
 *  never actually do: the registry looked prose and setup key up from the same
 *  plugin, so no key meant no prose either, and the only thing that path could
 *  render was the "No install instructions" placeholder. The field is gone
 *  from the wire and from the plugin manifests now. */
export function ModelHelpOverlay({ model, onClose }: { model: ModelHelpTarget; onClose: () => void }) {
  return (
    // 640 rather than 560: with the button no longer shrinking, the sentence
    // explaining it gets whatever is left, and at 560 that was a four-line
    // column beside a one-line button.
    <Overlay icon="download" title={`Enable ${model.name}`} width={640}
             onClose={onClose}>
      {/* Selectable, so the commands can be copied (the app suppresses
          selection globally). */}
      <div className="mc-copy">
        {model.note && (
          <p style={{ margin: "0 0 12px", fontSize: "var(--fs-3)", color: "var(--muted)" }}>{model.note}</p>
        )}
        {model.setup_key && <SetupRunner pluginKey={model.setup_key} />}
        {model.url && (
          <a
            href={model.url}
            target="_blank"
            rel="noreferrer"
            style={{ display: "inline-flex", alignItems: "center", gap: 6, marginTop: 14, fontSize: "var(--fs-3)", color: "var(--accent)", textDecoration: "none", fontWeight: 600 }}
          >
            <Icon name="open_in_new" size={15} />
            Open the model card
          </a>
        )}
      </div>
    </Overlay>
  );
}

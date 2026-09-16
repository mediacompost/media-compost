// Shown when the dedicated training venv is missing: explains the one-time
// setup and runs `-m media_compost.hub.setup_env training` with the same
// poll-restart-reload flow as the ML plugin setup (ModelHelp's SetupRunner).
import React from "react";
import { api } from "./api";
import { Icon } from "../shared/Icon";
import { useT } from "./i18n";
import { useSetupRun } from "../shared/useSetupRun";

export function TrainSetupBanner() {
  const t = useT();
  const { phase, log, error, logRef, start, busy } = useSetupRun({
    status: () => api.trainSetupStatus(),
    run: () => api.trainSetupStart(),
  });
  return (
    <div
      style={{
        padding: "12px 14px", marginBottom: 10,
        background: "var(--panel)", border: "1px solid var(--yellow-text)",
        borderRadius: "var(--r-7)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <Icon name="build" size={18} color="var(--yellow-text)" />
        <div style={{ flex: 1, fontSize: "var(--fs-3)", color: "var(--text-2)" }}>
          <div style={{ fontWeight: 600, color: "var(--text)", marginBottom: 2 }}>
            {t("Training environment not set up")}
          </div>
          {t("Training needs its own Python environment (PyTorch, diffusers, peft — a few GB, one time). Model weights download later, on a job's first run.")}
        </div>
        <button
          onClick={start}
          disabled={busy}
          style={{
            display: "inline-flex", alignItems: "center", gap: 7,
            padding: "7px 14px", borderRadius: "var(--r-4)", border: "none",
            cursor: busy ? "default" : "pointer",
            background: busy ? "var(--bg-deep)" : "var(--accent)",
            color: busy ? "var(--muted)" : "var(--on-accent)",
            fontSize: "var(--fs-3)", fontWeight: 600, fontFamily: "inherit",
            flex: "0 0 auto",
          }}
        >
          {busy && <Icon name="progress_activity" size={15} spin />}
          {phase === "restarting" ? t("Restarting…")
            : phase === "running" ? t("Installing…") : t("Run setup")}
        </button>
      </div>
      {error && (
        <div style={{ marginTop: 8, fontSize: "var(--fs-2)", color: "var(--red-text)" }}>{error}</div>
      )}
      {log && phase !== "idle" && (
        <pre
          ref={logRef}
          style={{
            margin: "10px 0 0", padding: "8px 10px", maxHeight: 160,
            overflow: "auto", fontSize: "var(--fs-1)", lineHeight: 1.5,
            fontFamily: "var(--mono)", background: "var(--bg-deep)",
            border: "1px solid var(--border)", borderRadius: "var(--r-4)",
            whiteSpace: "pre-wrap", color: "var(--text-2)",
          }}
        >
          {log}
        </pre>
      )}
    </div>
  );
}

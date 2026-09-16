// The poll → restart → reload state machine both setup runners share.
//
// The server side was consolidated long ago (server/setup_runner.py serves the
// plugin setup AND /api/train/setup); the client half lived as two ~45-line
// copies in ModelHelp's SetupRunner and TrainSetupBanner, differing only in
// which endpoints they call. This hook is that machine, once.
import { useEffect, useRef, useState } from "react";
import { api } from "./api";

export type SetupPhase = "idle" | "running" | "restarting" | "error";

export interface SetupStatus {
  running: boolean;
  ok: boolean;
  error: string;
  log: string;
}

export function useSetupRun(opts: {
  /** Poll the run's status (setupStatus(pluginKey) / trainSetupStatus()). */
  status: () => Promise<SetupStatus>;
  /** Start the run (runSetup(pluginKey) / trainSetupStart()). */
  run: () => Promise<unknown>;
  /** Re-arms the resume probe when the target changes (the plugin key). */
  key?: string;
}) {
  const [phase, setPhase] = useState<SetupPhase>("idle");
  const [log, setLog] = useState("");
  const [error, setError] = useState("");
  const logRef = useRef<HTMLPreElement | null>(null);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  // The callbacks ride in a ref so no effect depends on their identity —
  // they close over props and are new every render (the useReportSelection
  // lesson).
  const cb = useRef(opts);
  cb.current = opts;

  // Resume the view if a run is already going (the overlay was closed and
  // reopened, or the tab switched away and back, mid-run).
  useEffect(() => {
    cb.current.status().then((s) => {
      if (!alive.current || !s.running) return;
      setLog(s.log);
      setPhase("running");
    }).catch(() => { /* ignore */ });
  }, [opts.key]);

  // Keep the log scrolled to the bottom as output streams in.
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [log]);

  // Poll the run status once a second while running.
  useEffect(() => {
    if (phase !== "running") return;
    const iv = setInterval(async () => {
      try {
        const s = await cb.current.status();
        if (!alive.current) return;
        // A blank default reply means the server already re-exec'd itself and
        // lost the in-memory run (setup runs restart on success) — don't
        // mistake it for a failure; wait for the restart instead.
        if (!s.running && !s.ok && !s.error && !s.log) { setPhase("restarting"); return; }
        setLog(s.log);
        if (s.running) return;
        if (s.ok) setPhase("restarting");
        else { setError(s.error || "setup failed"); setPhase("error"); }
      } catch { /* server may already be restarting */ }
    }, 1000);
    return () => clearInterval(iv);
  }, [phase, opts.key]);

  // After a successful run the server re-execs itself (~1 s grace + startup).
  // Wait past the old process, then poll /api/health until the new one answers
  // and reload so every "needs setup" badge refreshes.
  useEffect(() => {
    if (phase !== "restarting") return;
    let stop = false;
    const poll = async () => {
      while (!stop) {
        await new Promise((r) => setTimeout(r, 1000));
        try { await api.health(); if (!stop) window.location.reload(); return; }
        catch { /* still restarting */ }
      }
    };
    const timer = setTimeout(poll, 2500);
    return () => { stop = true; clearTimeout(timer); };
  }, [phase]);

  const start = async () => {
    setError("");
    setLog("");
    setPhase("running");
    try { await cb.current.run(); }
    catch (e) {
      // 409 = already running — just keep polling; anything else is an error.
      if (String(e).includes("409")) return;
      setError(String(e));
      setPhase("error");
    }
  };

  return { phase, log, error, logRef, start,
           busy: phase === "running" || phase === "restarting" };
}

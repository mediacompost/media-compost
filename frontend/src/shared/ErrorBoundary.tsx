// A render error used to unmount the whole tree, leaving a completely blank
// window with the reason only in the console — the worst possible failure to
// report or debug ("the page just goes blank"). This catches it, keeps the
// rest of the app alive where it wraps a single view, and shows the message
// and stack so they can be copied into a bug report.
import React from "react";
import { Button } from "../shared/Button";
import { Icon } from "./Icon";

interface Props {
  children: React.ReactNode;
  /** Names what broke, already translated — "The Tags tab". */
  what?: string;
  /** The host translates: a class component has no hook, and the root
   *  boundary in main.tsx sits above the language provider (it passes the
   *  identity). */
  t: (text: string, vars?: Record<string, string | number>) => string;
}
interface State { error: Error | null; info: string }

export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null, info: "" };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // Still log it: the console is where a developer looks first.
    console.error("render error", error, info);
    this.setState({ info: info.componentStack || "" });
  }

  render() {
    const { error, info } = this.state;
    if (!error) return this.props.children;
    const { t } = this.props;
    const what = this.props.what || t("This view");
    return (
      <div style={{
        flex: 1, minHeight: 0, overflowY: "auto", padding: 24,
        display: "flex", alignItems: "flex-start", justifyContent: "center",
      }}>
        <div style={{
          maxWidth: 720, width: "100%", padding: 18, borderRadius: "var(--r-7)",
          background: "var(--panel)", border: "1px solid var(--red-text)",
        }}>
          <div style={{
            display: "flex", alignItems: "center", gap: 8, marginBottom: 8,
            color: "var(--red-text)", fontWeight: 600, fontSize: "var(--fs-4)",
          }}>
            <Icon name="error" size={18} />
            {t("{what} ran into an error", { what })}
          </div>
          <div style={{ fontSize: "var(--fs-3)", color: "var(--muted)", marginBottom: 12 }}>
            {t("The rest of the app keeps working. Reloading usually clears it — if it comes back, the details below say what happened.")}
          </div>
          <pre style={{
            margin: 0, padding: 12, borderRadius: "var(--r-5)", maxHeight: 260,
            overflow: "auto", background: "var(--bg-deep)", fontSize: "var(--fs-2)",
            lineHeight: 1.5, fontFamily: "var(--mono)", color: "var(--text-2)",
            whiteSpace: "pre-wrap",
            userSelect: "text", WebkitUserSelect: "text", cursor: "text",
          }}>
            {String(error.stack || error.message || error)}
            {info ? `\n${info}` : ""}
          </pre>
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <Button variant="ghost" size="sm"
       onClick={() => this.setState({ error: null, info: "" })}>
              {t("Try again")}
            </Button>
            <Button variant="primary" size="sm"
       onClick={() => window.location.reload()}>
              {t("Reload")}
            </Button>
          </div>
        </div>
      </div>
    );
  }
}

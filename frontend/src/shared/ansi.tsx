// Rendering terminal output in the browser. Both log viewers in the app (the
// background-task log in the left sidebar and the training log) show output
// produced by real processes, which colorize it — so the escapes have to be
// understood here or they show up as `[1;36m` litter.
import type { ReactNode } from "react";
import { terminalText } from "./terminalText";

// ANSI SGR foreground colors → theme-aware CSS variables (readable on both the
// light and dark log background — see the --ansi-* tokens in tokens.css).
const ANSI_FG: Record<number, string> = {
  30: "var(--ansi-black)", 31: "var(--ansi-red)", 32: "var(--ansi-green)",
  33: "var(--ansi-yellow)", 34: "var(--ansi-blue)", 35: "var(--ansi-magenta)",
  36: "var(--ansi-cyan)", 37: "var(--ansi-white)",
  90: "var(--ansi-black)", 91: "var(--ansi-red)", 92: "var(--ansi-green)",
  93: "var(--ansi-yellow)", 94: "var(--ansi-blue)", 95: "var(--ansi-magenta)",
  96: "var(--ansi-cyan)", 97: "var(--ansi-white)",
};

// eslint-disable-next-line no-control-regex
const ANSI_RE = /\x1b\[([0-9;]*)m/g;

/** Parse a log string with ANSI SGR escapes into colored React spans. Supports
 *  the 8/16-color foreground set and bold; unknown codes are ignored. */
export function renderAnsi(raw: string): ReactNode[] {
  // Everything that is not colour is dealt with first: a scrolling log cannot
  // honour cursor moves, and passing them through printed them as glyphs.
  const log = terminalText(raw);
  const out: ReactNode[] = [];
  let fg: string | undefined;
  let bold = false;
  let last = 0;
  let key = 0;
  const push = (text: string) => {
    if (!text) return;
    if (fg || bold) {
      out.push(
        <span key={key++} style={{ color: fg, fontWeight: bold ? 700 : undefined }}>
          {text}
        </span>,
      );
    } else {
      out.push(text);
    }
  };
  let m: RegExpExecArray | null;
  ANSI_RE.lastIndex = 0;
  while ((m = ANSI_RE.exec(log)) !== null) {
    push(log.slice(last, m.index));
    last = m.index + m[0].length;
    const codes = m[1] === "" ? [0] : m[1].split(";").map((c) => parseInt(c, 10));
    for (const c of codes) {
      if (c === 0) { fg = undefined; bold = false; }
      else if (c === 1) bold = true;
      else if (c === 22) bold = false;
      else if (c === 39) fg = undefined;
      else if (ANSI_FG[c]) fg = ANSI_FG[c];
    }
  }
  push(log.slice(last));
  return out;
}

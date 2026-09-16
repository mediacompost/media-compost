/** Turning a captured terminal stream into the text a terminal would show.
 *
 * `ansi.tsx` colours SGR escapes (`\x1b[31m`). Everything ELSE a real program
 * emits — hide the cursor, erase the line, move up — is not colour, and was
 * passed straight through as literal text: a pip install rendered a run of
 * unrenderable glyphs followed by `[?25l` and `[2K`. Measured on one
 * `pip install onnxruntime`: 123 escapes, of which 11 are not colour.
 *
 * Pure and string-in/string-out so it can be unit-tested under `node --test`,
 * which cannot load the renderer's JSX.
 */

// Any CSI sequence: ESC [ , parameter and intermediate bytes, one final byte.
// SGR (final `m`) is colour and is left for the renderer; the rest is cursor
// and screen control, which a scrolling log cannot honour.
// eslint-disable-next-line no-control-regex
const CSI = /\x1b\[[0-9;?]*[ -/]*[@-~]/g;
// OSC (window titles, hyperlinks): ESC ] … BEL, or ESC ] … ESC \.
// eslint-disable-next-line no-control-regex
const OSC = /\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g;
// A lone ESC with its following byte (charset selection and friends). It must
// not see an ESC that opens a CSI or OSC: `[` sits inside the final-byte range,
// so an unguarded pattern eats the `\x1b[` of a colour code and leaves a bare
// `32m` behind as visible text.
// eslint-disable-next-line no-control-regex
const ESC_PAIR = /\x1b(?![[\]])[ -/]*[0-~]/g;

// An erase-line — optionally after some cursor movement — at the START of a
// line. Everything a progress bar redraws is announced this way.
// eslint-disable-next-line no-control-regex
const REDRAW = /^(?:\x1b\[[0-9;?]*[A-HJ])*\x1b\[[012]?K/;
// Hiding the cursor is a writer announcing that it is taking over the line.
// eslint-disable-next-line no-control-regex
const OPENS_LIVE = /\x1b\[\?25l/;

/** Drop every escape that is not colour. */
function stripControl(text: string): string {
  return text
    .replace(OSC, "")
    .replace(CSI, (m) => (m.endsWith("m") ? m : ""))
    .replace(ESC_PAIR, "");
}

/** What a carriage return leaves behind: whatever was written after it.
 *
 *  A terminal would overlay rather than replace, so a shorter redraw would
 *  leave the tail of the longer one behind it. That tail is the ghost of a
 *  progress bar and nobody wants it in a log, so the last write wins outright.
 */
function applyCarriageReturns(line: string): string {
  if (!line.includes("\r")) return line;
  const parts = line.split("\r");
  while (parts.length > 1 && parts[parts.length - 1] === "") parts.pop();
  return parts[parts.length - 1];
}

/**
 * Collapse a captured stream to what is worth reading.
 *
 * A progress bar redraws one line over and over — pip writes ten frames for a
 * 19 MB wheel — and each announces itself with an erase-line. Those frames
 * collapse to the one it finished on.
 *
 * A redraw only ever replaces a line belonging to the SAME live display, which
 * a writer opens by hiding the cursor. Replacing whatever happened to come
 * before would eventually eat a real message — and the log where that matters
 * most is the one somebody is reading because a setup just failed.
 */
export function terminalText(log: string): string {
  if (!log) return "";
  const out: string[] = [];
  let live = false;   // inside a run of frames the writer is redrawing
  for (const raw of log.replace(/\r\n/g, "\n").split("\n")) {
    const redraw = REDRAW.test(raw);
    const line = stripControl(applyCarriageReturns(raw));
    if (redraw && live && out.length > 0) out[out.length - 1] = line;
    else out.push(line);
    live = OPENS_LIVE.test(raw) || (live && redraw);
  }
  return out.join("\n");
}

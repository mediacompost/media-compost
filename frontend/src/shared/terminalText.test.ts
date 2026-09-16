import test from "node:test";
import assert from "node:assert/strict";
import { terminalText } from "./terminalText.ts";

const ESC = "\x1b";

test("colour survives — that is the renderer's job, not this one's", () => {
  const line = `${ESC}[32m0.0/19.1 MB${ESC}[0m`;
  assert.equal(terminalText(line), line);
});

test("the escapes that are not colour are dropped", () => {
  // Every non-SGR pip emits, verbatim: hide cursor, erase line, show cursor.
  assert.equal(terminalText(`${ESC}[?25lhello`), "hello");
  assert.equal(terminalText(`a\n${ESC}[?25hb`), "a\nb");
  assert.equal(terminalText(`${ESC}[2Kx`), `${ESC}[2Kx`.replace(`${ESC}[2K`, ""));
  // …and the ones it does not: cursor moves, window title, charset select.
  assert.equal(terminalText(`${ESC}[1Aup`), "up");
  assert.equal(terminalText(`${ESC}]0;a title${ESC}\\kept`), "kept");
  assert.equal(terminalText(`${ESC}(Bplain`), "plain");
  assert.ok(!terminalText(`${ESC}[?25l${ESC}[2K${ESC}[?25h`).includes(ESC));
});

test("a progress bar collapses to the frame it finished on", () => {
  // The shape pip actually produces (captured from `pip install onnxruntime`):
  // a message, one frame with no erase-line, then a frame per redraw.
  const log = [
    "Using cached onnxruntime.whl (19.1 MB)",
    `${ESC}[?25l   ━━━━ 0.0/19.1 MB`,
    `${ESC}[2K   ━━━━ 9.2/19.1 MB`,
    `${ESC}[2K   ━━━━ 19.1/19.1 MB`,
    `${ESC}[?25hInstalling collected packages: onnxruntime`,
  ].join("\n");
  assert.equal(terminalText(log), [
    "Using cached onnxruntime.whl (19.1 MB)",
    "   ━━━━ 19.1/19.1 MB",
    "Installing collected packages: onnxruntime",
  ].join("\n"));
});

test("a redraw outside a live display never eats the line above it", () => {
  // No cursor-hide, so nothing here claimed the line — a writer that erases
  // defensively before each write must not cost us its earlier output.
  const log = `Downloading\n${ESC}[2Kfirst\n${ESC}[2Ksecond`;
  assert.equal(terminalText(log), "Downloading\nfirst\nsecond");
});

test("an erase-line with nothing before it starts the log", () => {
  assert.equal(terminalText(`${ESC}[2Konly`), "only");
});

test("a live display ends when the cursor comes back", () => {
  const log = [
    `${ESC}[?25lframe 0`,
    `${ESC}[2Kframe 1`,
    `${ESC}[?25hdone`,
    `${ESC}[2Kafter`,      // a new erase-line, but the display is over
  ].join("\n");
  assert.equal(terminalText(log), "frame 1\ndone\nafter");
});

test("a carriage-return redraw keeps the last write, whole", () => {
  assert.equal(terminalText("10%\r55%\r100%"), "100%");
  // A trailing \r is the writer parking the cursor, not an empty redraw.
  assert.equal(terminalText("done\r"), "done");
  assert.equal(terminalText("a\r\nb"), "a\nb");
});

test("ordinary output is returned untouched", () => {
  const plain = "Collecting insightface\n  Building wheel…\nSuccessfully installed";
  assert.equal(terminalText(plain), plain);
  assert.equal(terminalText(""), "");
});

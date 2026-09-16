/**
 * A browser may not turn a stored picture.
 *
 * This library records a file's RAW width and height and serves its bytes
 * untransformed, so an EXIF Orientation tag is indexed metadata rather than an
 * instruction — but `image-orientation: from-image` is the CSS default, so an
 * `<img>` applies it anyway and the picture comes out turned inside a box
 * shaped by the dimensions the app recorded. `tokens.css` carries the one rule
 * that stops it; this is the ratchet under it.
 *
 * A ratchet because the failure is INVISIBLE in this repository: no test
 * library holds a picture with the tag, the demo library holds none either,
 * and every other picture renders identically with the rule and without it.
 * Deleting the rule while tidying the stylesheet would cost nothing anybody
 * could see until somebody imported a photograph off a phone.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const SRC = fileURLToPath(new URL(".", import.meta.url));
// Comments are stripped first: this file's own rule is explained in one, and
// a declaration quoted in prose is not a declaration.
const css = readFileSync(SRC + "shared/tokens.css", "utf8")
  .replace(/\/\*[\s\S]*?\*\//g, "");

/** The declaration, with whatever whitespace a formatter leaves behind. */
const RULE = /(^|\})\s*img\s*\{[^}]*\bimage-orientation\s*:\s*none\b/;

test("every img ignores the file's own EXIF orientation", () => {
  assert.ok(
    RULE.test(css),
    "tokens.css must carry a bare `img { image-orientation: none }`: the " +
      "app records raw pixel dimensions, so a browser applying the tag draws " +
      "the picture turned inside a correctly shaped box.",
  );
});

test("nothing hands the orientation back", () => {
  // `from-image` is the default, so writing it anywhere is either a no-op or
  // an exemption that re-opens the bug for whatever it selects.
  assert.equal(
    /image-orientation\s*:\s*from-image/.test(css),
    false,
    "an `image-orientation: from-image` re-applies the tag the rule above " +
      "exists to ignore",
  );
});

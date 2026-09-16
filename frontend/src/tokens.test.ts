/**
 * Tokens and the one spelling of each drawn thing.
 *
 * `shared/tokens.css` names the colours and the animations; a site that
 * writes the value out instead of the name is one that will not follow the
 * theme, or the fix, when either moves. These are ratchets: what they guard
 * is silent, since a spinner spelled inline spins just the same until the
 * day the keyframes are renamed — which happened once, and left five sites
 * naming a class that did not exist (`tokens.css`, the `.mc-spin` note).
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const SRC = fileURLToPath(new URL(".", import.meta.url));

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (/\.(ts|tsx|css)$/.test(entry) && !/\.test\.tsx?$/.test(entry)) {
      out.push(full);
    }
  }
  return out;
}

const sources = () => walk(SRC).map((f) => ({
  rel: f.slice(SRC.length), text: readFileSync(f, "utf8"),
}));

test("the spinner is `Icon spin`, never an inline animation or a bare class", () => {
  const offenders: string[] = [];
  for (const { rel, text } of sources()) {
    if (rel === "shared/Icon.tsx" || rel === "shared/tokens.css") continue;
    if (/animation:\s*["']mc-spin/.test(text)) offenders.push(`${rel}: inline animation`);
    if (/className="mc-spin"/.test(text)) offenders.push(`${rel}: className="mc-spin"`);
  }
  assert.deepEqual(offenders, [],
    "spell a spinner as <Icon spin />:\n  " + offenders.join("\n  "));
  // Non-vacuous: the prop exists and is what puts the class on.
  const icon = readFileSync(join(SRC, "shared", "Icon.tsx"), "utf8");
  assert.match(icon, /spin \? "mc-spin" : ""/);
});

test("nothing names a class tokens.css does not define", () => {
  // `.mc-indeterminate` was defined for a year and used by nothing; the
  // reverse — a class used and never defined — is the silent failure. Every
  // `mc-` class a source file names must be a rule in tokens.css.
  const css = readFileSync(join(SRC, "shared", "tokens.css"), "utf8");
  const defined = new Set([...css.matchAll(/\.(mc-[a-z0-9-]+)/g)].map((m) => m[1]));
  const offenders: string[] = [];
  for (const { rel, text } of sources()) {
    if (rel.endsWith(".css")) continue;
    for (const m of text.matchAll(/["' ](mc-[a-z0-9-]+)["' ]/g)) {
      if (!defined.has(m[1])) offenders.push(`${rel}: ${m[1]}`);
    }
  }
  assert.deepEqual([...new Set(offenders)], [], "classes with no rule behind them");
  assert.ok(defined.has("mc-spin"));
  assert.ok(!defined.has("mc-indeterminate"), ".mc-indeterminate was deleted with its last (zero) users");
});

/** Every `--name:` definition in tokens.css (any block) plus every custom
 *  property a component sets inline (`"--row-wash": …`). */
function definedTokens(): Set<string> {
  const css = readFileSync(join(SRC, "shared", "tokens.css"), "utf8");
  const out = new Set([...css.matchAll(/(--[a-z0-9-]+)\s*:/g)].map((m) => m[1]));
  for (const { rel, text } of sources()) {
    if (rel.endsWith(".css")) continue;
    for (const m of text.matchAll(/["'](--[a-z0-9-]+)["']\s*:/g)) out.add(m[1]);
  }
  return out;
}

function block(css: string, selector: string): Set<string> {
  const at = css.indexOf(selector + " {");
  assert.ok(at >= 0, `tokens.css has no ${selector} block`);
  const end = css.indexOf("\n}", at);
  return new Set([...css.slice(at, end).matchAll(/(--[a-z0-9-]+)\s*:/g)].map((m) => m[1]));
}

test("a token is read by name alone — no `var(--x, fallback)` anywhere", () => {
  // The tokens are global, so a fallback is either dead or wrong. Forty-eight
  // of them carried the DARK theme's hex beside a token whose light value
  // differs, two of them two different values for one token, and the next
  // person to copy the line into a context without the token got a
  // light-mode regression for free.
  const offenders: string[] = [];
  for (const { rel, text } of sources()) {
    for (const m of text.matchAll(/var\((--[a-z0-9-]+),/g)) offenders.push(`${rel}: ${m[1]}`);
  }
  assert.deepEqual(offenders, [], "drop the fallback:\n  " + offenders.join("\n  "));
});

test("every token a source file reads is defined", () => {
  // `--text-1` was read in seven places and defined nowhere: the labels
  // rendered in inherited colour and nothing said so.
  const defined = definedTokens();
  const offenders: string[] = [];
  for (const { rel, text } of sources()) {
    for (const m of text.matchAll(/var\((--[a-z0-9-]+)/g)) {
      if (!defined.has(m[1])) offenders.push(`${rel}: ${m[1]}`);
    }
  }
  assert.deepEqual([...new Set(offenders)], [], "undefined tokens");
  assert.ok(defined.has("--text") && defined.has("--danger-dim"));
});

test("the light theme overrides every colour the dark theme defines", () => {
  const css = readFileSync(join(SRC, "shared", "tokens.css"), "utf8");
  const root = block(css, ":root");
  const light = block(css, ':root[data-theme="light"]');
  // A light-only token would be one the default theme cannot see.
  assert.deepEqual([...light].filter((n) => !root.has(n)), [], "light defines what :root does not");
  // What :root defines and light leaves alone is a stated list: the accent
  // and the two kind tints read on both grounds, and the fonts are not
  // colours. A colour added to :root and forgotten in light fails here.
  // The scrims and what is written on them sit on PICTURES and on the
  // sessions' fixed-dark backdrops, which have no theme; the accent lift,
  // the two kind tints and the fonts are not theme colours either.
  const THEME_INVARIANT = new Set([
    "--accent", "--accent-bright", "--movie", "--archive", "--mono", "--sans",
    "--scrim-1", "--scrim-2", "--scrim-3", "--scrim-4",
    "--on-scrim", "--on-scrim-2", "--on-scrim-3", "--on-scrim-4",
    "--overlay-chrome", "--overlay-chrome-accent", "--overlay-hairline", "--overlay-wash",
    "--ring-shadow", "--muted-dim",
    "--fs-0", "--fs-1", "--fs-2", "--fs-3", "--fs-4", "--fs-5", "--fs-6", "--fs-7",
    "--r-1", "--r-2", "--r-3", "--r-4", "--r-5", "--r-6", "--r-7", "--r-round",
  ]);
  const unoverridden = [...root].filter((n) => !light.has(n) && !THEME_INVARIANT.has(n));
  assert.deepEqual(unoverridden, [], "these :root tokens have no light-theme value");
  assert.ok(root.size > 40 && light.size > 40);
});

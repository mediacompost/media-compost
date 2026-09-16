/**
 * The frontend's package boundaries, held as source tests.
 *
 * `src/` is four directories with a contract: `shared/` and `query/` may
 * import neither `app/` nor `train/`; `train/` may additionally not import
 * `app/`; and nothing imports `train/` at all except the ONE lazy door
 * (`app/training.tsx`) — which is what keeps the train UI a chunk of its own
 * that an install without `[training]` never fetches.
 *
 * Directory boundaries with no enforcement are boundaries only until the
 * first convenient import; this is the same trick `noRawApiFetch.test.ts`
 * uses, because what it guards is silent — a stray import compiles, runs,
 * and quietly moves ten thousand lines back into the main bundle.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, dirname, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const SRC = fileURLToPath(new URL(".", import.meta.url));

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (/\.(ts|tsx)$/.test(entry)) out.push(full);
  }
  return out;
}

/** Every import (or re-export) in `file`, resolved src-relative.
 *
 * Anchored at line starts: the word "import" appears in prose comments too,
 * and an unanchored scan once consumed a real `import type` line from inside
 * a match that began in the docstring above it. Multi-line import lists
 * still work — the lazy `[\s\S]*?` only starts after a REAL keyword.
 *
 * Only RELATIVE specs (leading ".") are captured, which is sound while
 * vite.config.ts and tsconfig.json define no path aliases — an alias like
 * "@train/x" would slip past every check here. If aliases are ever added,
 * teach this regex to resolve them too.
 */
function importsOf(file: string): { spec: string; typeOnly: boolean }[] {
  const text = readFileSync(file, "utf8");
  const out: { spec: string; typeOnly: boolean }[] = [];
  const re = /^(?:import|export)(\s+type)?[\s\S]*?from\s+["'](\.[^"']+)["']|import\(\s*["'](\.[^"']+)["']\s*\)/gm;
  for (const m of text.matchAll(re)) {
    const spec = m[2] ?? m[3];
    if (!spec) continue;
    const abs = normalize(join(dirname(file), spec));
    out.push({
      spec: relative(SRC, abs).split("\\").join("/"),
      typeOnly: !!m[1],
    });
  }
  return out;
}

const top = (p: string) => relative(SRC, p).split("\\").join("/").split("/")[0];

test("only the lazy door imports from train/", () => {
  const offenders: string[] = [];
  for (const file of walk(SRC)) {
    if (top(file) === "train") continue;
    const rel = relative(SRC, file).split("\\").join("/");
    for (const imp of importsOf(file)) {
      // First segment, not startsWith("train/"): a bare `import ... from
      // "../train"` resolves to spec "train" with no slash, and it pulls the
      // whole package into the main bundle exactly like a deep import does.
      if (imp.spec.split("/")[0] === "train" && rel !== "app/training.tsx") {
        offenders.push(`${rel} -> ${imp.spec}`);
      }
    }
  }
  assert.deepEqual(offenders, [],
    "train/ is reachable only through app/training.tsx's React.lazy — " +
    "anything else puts its ~10k lines back into the main bundle");
});

test("query/ imports only itself and shared/", () => {
  const offenders: string[] = [];
  for (const file of walk(join(SRC, "query"))) {
    for (const imp of importsOf(file)) {
      const root = imp.spec.split("/")[0];
      if (root !== "query" && root !== "shared") {
        offenders.push(`${relative(SRC, file)} -> ${imp.spec}`);
      }
    }
  }
  assert.deepEqual(offenders, []);
});

test("shared/ imports only itself (plus type-only shapes from query/)", () => {
  // The one sanctioned reach: `shared/api.ts` needs the TYPE of a condition
  // tree (the wire format), which `query/tree.ts` owns. Type-only, so it is
  // erased at build time and cannot create a runtime cycle.
  const offenders: string[] = [];
  for (const file of walk(join(SRC, "shared"))) {
    for (const imp of importsOf(file)) {
      const root = imp.spec.split("/")[0];
      if (root === "shared") continue;
      if (root === "query" && imp.typeOnly) continue;
      offenders.push(`${relative(SRC, file)} -> ${imp.spec}`);
    }
  }
  assert.deepEqual(offenders, []);
});

test("train/ never imports the app", () => {
  const offenders: string[] = [];
  for (const file of walk(join(SRC, "train"))) {
    for (const imp of importsOf(file)) {
      if (imp.spec.split("/")[0] === "app") {
        offenders.push(`${relative(SRC, file)} -> ${imp.spec}`);
      }
    }
  }
  assert.deepEqual(offenders, [],
    "the trainer's UI reaches the app only through props handed across " +
    "the lazy entry (see TrainView's jobUid)");
});

test("the door is lazy", () => {
  // Naming ../train in a PLAIN import from the door file would defeat the
  // whole arrangement while passing the reachability test above.
  const door = readFileSync(join(SRC, "app", "training.tsx"), "utf8");
  assert.match(door, /React\.lazy\(\(\) => import\("\.\.\/train"\)\)/);
  assert.doesNotMatch(door, /^import .* from "\.\.\/train"/m);
});

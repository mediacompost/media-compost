/**
 * Every call to the API goes through `apiFetch`.
 *
 * That wrapper is what attaches this page's build and reads the server's back,
 * so a request made with a bare `fetch` is one the server never learns is
 * stale and one that never notices the server has moved on. Six multipart
 * uploads build their own `FormData` and so cannot use `req()` — they are
 * exactly the calls most likely to be written fresh and forget.
 *
 * A ratchet rather than a convention, for the same reason the backend's is
 * one: what it guards is silent. Nothing breaks when a call skips the wrapper;
 * it just quietly stops being covered.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

// `fileURLToPath`, not `.pathname` — the same conversion corpus.test.ts
// already uses. On Windows a file URL's pathname is
// "/C:/…/src/", with a leading slash, so `join` produced "C:\C:\…\src\api.ts"
// and every read here failed with ENOENT.
const SRC = fileURLToPath(new URL(".", import.meta.url));

/** `build.ts` is where the one real `fetch` lives — it IS the wrapper. */
const ALLOWED = new Set(["build.ts"]);

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) out.push(...walk(full));
    else if (/\.(ts|tsx)$/.test(entry) && !/\.test\.tsx?$/.test(entry)) {
      out.push(full);
    }
  }
  return out;
}

test("no source file calls fetch() on the API outside apiFetch", () => {
  const offenders: string[] = [];
  for (const file of walk(SRC)) {
    const rel = file.slice(SRC.length);
    if (ALLOWED.has(rel)) continue;
    const text = readFileSync(file, "utf8");
    // `fetch(` — but not `apiFetch(`, and not the word inside a comment about
    // one. Only calls naming an /api/ path matter; fetching a blob URL or an
    // external resource is not an API call.
    for (const m of text.matchAll(/(?<![A-Za-z])fetch\(\s*([`"'])([^`"']*)/g)) {
      if (m[2].startsWith("/api/") || m[2].includes("/api/")) {
        offenders.push(`${rel}: fetch("${m[2]}")`);
      }
    }
  }
  assert.deepEqual(
    offenders, [],
    "these call the API with a bare fetch, so they neither send this page's " +
    "build nor notice the server's:\n  " + offenders.join("\n  ") +
    "\nUse `apiFetch` from ./build instead.",
  );
});

test("the wrapper is actually reachable from the client", () => {
  // `req()` — the choke point for every JSON call — lives in shared/api.ts
  // now; if it regressed to a bare fetch the test above would not catch it
  // (the url is a variable). The app's client both spreads the shared one and
  // uses apiFetch directly for its multipart uploads.
  const shared = readFileSync(join(SRC, "shared", "api.ts"), "utf8");
  assert.match(shared, /import \{ apiFetch \} from "\.\/build"/);
  assert.match(shared, /const r = await apiFetch\(url, \{/);
  const app = readFileSync(join(SRC, "app", "api.ts"), "utf8");
  assert.match(app, /import \{ apiFetch \} from "\.\.\/shared\/build"/);
});

/**
 * Which build this page is running, and noticing when the server has moved on.
 *
 * The app ships as one artifact — the backend serves this bundle — so the
 * content-hashed entry file names the pair. This page reads it off its own
 * `<script>` tag; the server reads the same string out of the `index.html` it
 * would serve. Equal means the tab is running the JavaScript the server hands
 * out; different means somebody updated underneath it.
 *
 * Read from the DOM rather than from `import.meta.url`, deliberately: with
 * code splitting `import.meta.url` names whatever CHUNK this module ended up
 * in, which is not the file `index.html` points at, so the two sides would
 * compare different things and disagree forever.
 *
 * Everything here degrades to silence. Under the Vite dev server the entry is
 * `/src/main.tsx` and there is no hash to find, so the build reads `""`, no
 * header is sent, and the server (which treats an absent header as fine)
 * enforces nothing. That is the intended dev behaviour, not a hole: a rebuild
 * happens every few seconds there, and a banner — or worse, a refused write —
 * on every one of them is noise.
 */

/** The header, in both directions. Must match `server/build.py: HEADER`. */
const HEADER = "X-MC-Build";

function readOwnBuild(): string {
  if (typeof document === "undefined") return "";
  const el = document.querySelector<HTMLScriptElement>(
    'script[src*="/assets/index-"]');
  const src = el?.getAttribute("src") ?? "";
  // "/assets/index-BGxEQlGY.js" -> "index-BGxEQlGY.js". The hash may contain
  // hyphens (`index-B-wWBlGs.js`), so take the whole file name.
  return src.split("/").pop() ?? "";
}

/** This page's build, resolved once — the script tag cannot change. */
export const OWN_BUILD = readOwnBuild();

let updated = false;
const listeners = new Set<() => void>();

/** True once the server has answered with a build that is not ours. Latching:
 *  it never goes back to false, because the page cannot become current again
 *  without reloading, and a banner that flickered away would be worse than
 *  one that stays. */
export function serverHasUpdated(): boolean {
  return updated;
}

export function subscribeToUpdates(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** null until the server has been asked; then whether a RELOAD is enough. */
let needsRestart: boolean | null = null;

/**
 * Whether reloading would actually help.
 *
 * A mismatch has two causes and they want opposite actions. An ordinary
 * rebuild while the tab sat open leaves the page old and the server current:
 * reload and you are done. A package update (`pip install -U`, a rebuilt
 * bundle, a swapped volume) replaces the FILES under a running process, so the
 * tab reloads into the new bundle and then talks to a server still running the
 * old code — reloading is exactly the thing that cannot help, which is what
 * the banner had been advising. `/api/build` is the server saying which it is.
 */
export function serverNeedsRestart(): boolean | null {
  return needsRestart;
}

function noteServerBuild(theirs: string | null): void {
  if (updated || !theirs || !OWN_BUILD || theirs === OWN_BUILD) return;
  updated = true;
  for (const fn of listeners) fn();
  // Asked ONCE, and only now: before the mismatch there is nothing to ask
  // about, and the answer cannot change without the process changing.
  void apiFetch("/api/build")
    .then((r) => (r.ok ? r.json() : null))
    .then((info) => {
      needsRestart = !!info?.restart_required;
      for (const fn of listeners) fn();
    })
    .catch(() => { /* an older server has no such route: reload is the answer */ });
}

/** What a restart would interrupt — jobs and imports die with the process. */
export interface RestartBusy { jobs: number; imports: number }

/**
 * Ask the server to re-exec into the version on disk.
 *
 * Resolves once it is answering again (so the caller can reload into it);
 * rejects with the server's own refusal — including the one naming work still
 * running, which `force` overrides.
 */
export async function restartServer(force = false): Promise<void> {
  const r = await apiFetch(`/api/restart${force ? "?force=true" : ""}`,
                           { method: "POST" });
  if (!r.ok) {
    const body = await r.json().catch(() => null);
    const err = new Error("restart refused") as Error & { busy?: RestartBusy };
    const detail = body?.detail;
    if (detail && typeof detail === "object" && detail.busy) err.busy = detail.busy;
    throw err;
  }
  // The process re-execs about a second AFTER replying, so for that second the
  // old one is still answering — waiting for health to come back would be
  // satisfied by the very process being replaced. So wait for the ANSWER to
  // change instead: `restart_required` is false again exactly when the new
  // process is the one on the socket. (Measured against a real re-exec, where
  // a health probe 1.5 s in still reached the outgoing server.)
  for (let i = 0; i < 60; i++) {
    await new Promise((done) => setTimeout(done, 500));
    try {
      const info = await apiFetch("/api/build", { cache: "no-store" })
        .then((x) => (x.ok ? x.json() : null));
      if (info && !info.restart_required) return;
    } catch { /* down for a moment — that is what a restart looks like */ }
  }
  throw new Error("the server did not come back");
}

/**
 * `fetch` for the API: sends this page's build, and watches the reply for the
 * server's.
 *
 * EVERY call to `/api/...` goes through here — including the multipart uploads
 * that build their own `FormData` and so cannot use `req()`. That is not
 * tidiness: a request that skipped it would be one the server never learns is
 * stale, and `src/noRawApiFetch.test.ts` fails the build if one appears.
 */
export async function apiFetch(
  url: string, opts: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(opts.headers ?? {});
  if (OWN_BUILD) headers.set(HEADER, OWN_BUILD);
  const r = await fetch(url, { ...opts, headers });
  noteServerBuild(r.headers.get(HEADER));
  return r;
}

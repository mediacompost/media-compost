// Central, debounced query invalidation. The storm sources — import batches
// finishing, background jobs completing — each used to fire a dozen broad
// invalidations immediately, and a burst of them meant a burst of O(library)
// refetches. They now funnel through one coalescer per urgency class, so a
// storm costs one refetch sweep.
//
// Wired once from main.tsx via setInvalidationClient — a module-level client,
// so non-React code (the import engine) can invalidate too.
import type { QueryClient } from "@tanstack/react-query";
import { makeCoalescer } from "./coalesce";

let qc: QueryClient | null = null;

export function setInvalidationClient(client: QueryClient): void {
  qc = client;
}

// Everything a background process can change. This is the UNION of the key
// lists the storm sources used to invalidate individually
// (importManager.invalidateAfterBatch, JobList's job-count-drop effect, a
// background job finishing) — a superset per caller, so no coverage is lost
// by sharing one list.
const LIBRARY_KEYS = [
  // "item-groups" is the grid's section runs. Missing here fails QUIETLY: the
  // pages refetch, the headers keep their old counts, and the layout then
  // describes an index space that no longer exists — placeholder cards that
  // never fill, under a scrollbar longer than the content.
  "items", "item-groups", "item", "item-metadata", "facets", "groups", "tags",
  "library-stats", "sequences", "relationships",
  // The multi-selection Tags tab's own read (`/api/items/details` under
  // ["item-slim-tags", ids]). Missing here — and from EDIT_KEYS — failed
  // quietly: with two items selected the grouped sections preferred the
  // stale slims over the refreshed grid cache, so removing a tag (or adding
  // one through the quick tag overlay) changed nothing on screen.
  "item-slim-tags",
  "faces", "faces-named", "faces-unnamed", "subjects", "places", "events",
  // The detected-text tree. Missing here failed quietly: a finished OCR job
  // updated the Text tab's BADGE (that count rides on ["item"]) while the
  // open tab's list stayed empty until a reload.
  "text",
  // Enabling or importing a tag set changes what every tags read carries
  // (capsules, descriptions, set-only suggestions), so the sets' own list
  // is swept with the library — an import running beside the app can add
  // one, and the `tags` prefix above already covers the rows themselves.
  "tag-sets",
] as const;

// What a single hand edit (tag/group/link/caption change, hide, trash) can
// touch beyond the item's own detail — the union of PropertiesPanel's and
// ItemGrid's per-edit invalidation lists. Deliberately NOT the broad ["item"]
// prefix: the touched items' details go through bumpItem() immediately, and
// an edit to item A never changes item B's detail — invalidating every cached
// detail per keystroke-sized edit was the storm this narrows.
const EDIT_KEYS = [
  "items", "item-groups", "item-metadata", "facets", "groups", "tags",
  "library-stats", "sequences",
  // The multi-selection Tags tab's slim details — keyed by the selected id
  // set, so this refetches the one mounted selection, not every cached
  // detail (see LIBRARY_KEYS' entry for the failure its absence was).
  "item-slim-tags",
  // The OPEN sequence's member list (["sequence", id]) — a different key
  // from the list above it, and an edit can change membership without going
  // through the sequence endpoints at all: trashing a page takes it out of
  // its chapters now.
  "sequence",
] as const;

// What a REVERT can put back. Reverting is the one action whose reach is not
// known in advance — the events being undone were written by any endpoint at
// all — so this is deliberately the widest list plus the catalogs a plain
// library sweep leaves out.
//
// It exists because the two undo bars each carried a hand-written copy of it
// and they had drifted: the annotator's was missing `relationships`, so
// undoing a link removal put the link back in the database and left the list
// on screen exactly as it was. One list, one place, and `useUndoBar` calls it
// itself rather than trusting each caller to remember.
const REVERT_KEYS = [
  ...LIBRARY_KEYS,
  "history", "item-suggestions", "item-sequences", "sequence",
  // The meta-tag catalog and its per-carrier rows: a reverted meta tag is one
  // of the things that changes here and nothing else refetches them.
  "link-tags", "link-tag-rows",
  "stills", "tracks", "frame-markers",
] as const;

function invalidateAll(keys: readonly string[]): void {
  if (!qc) return;
  noteOwnChange();
  for (const k of keys) qc.invalidateQueries({ queryKey: [k] });
}

const libraryCoalescer = makeCoalescer(
  () => invalidateAll(LIBRARY_KEYS),
  { wait: 400, maxWait: 2000 }
);
const editsCoalescer = makeCoalescer(
  () => invalidateAll(EDIT_KEYS),
  { wait: 150, maxWait: 1000 }
);

/** A background process (import batch, job finish) changed the library.
 *  Coalesced: one sweep per burst, at most every 2 s. */
export function bumpLibrary(): void {
  libraryCoalescer.call();
}

/** A hand edit changed list/catalog state. Shorter coalesce than bumpLibrary
 *  — a person is waiting to see their own edit. Pair with bumpItem(id) for the
 *  touched items' details, which refresh immediately. */
export function bumpEdits(): void {
  editsCoalescer.call();
}

/** A revert (or redo) just landed. NOT coalesced: somebody pressed Undo and
 *  is looking at the row they expect to come back. */
export function bumpReverted(): void {
  invalidateAll(REVERT_KEYS);
}

/** Refresh one item's detail right now (prefix match, so ["item", id, ...]
 *  subkeys refresh too). The broad ["item"] prefix is covered — later — by the
 *  coalescers; this is the immediate, narrow half of an edit's feedback. */
export function bumpItem(id: number): void {
  noteOwnChange();
  qc?.invalidateQueries({ queryKey: ["item", id] });
}

// ---- external-writer detection ---------------------------------------------
//
// Every /api/items/query page and /api/items/groups answer carries `rev`, a
// fingerprint of the library state it describes. A grid window ASSEMBLED from
// two different revisions is broken by construction: offset pagination under
// a newest-first sort means an insert shifts every later page, so a stale
// page and a fresh one overlap — the same card twice, clicks selecting what
// the layout has since moved. The app's own writes invalidate their way out
// of this; a SCRIPT importing in another process sends nothing, which is
// exactly the reported "grid breaks after a background import until reload".
// The queries report their revs here; a mismatch triggers one coalesced
// re-sync of the view queries, which converges as soon as the writer pauses
// — and while it keeps writing, the grid follows it at the coalescer's pace.

let seenRev: string | null = null;

// WHEN THIS APP LAST CHANGED THE LIBRARY ITSELF, and why that has to be
// remembered here: every write moves the revision, so without it the app's own
// edits looked exactly like the external writer this is watching for. Removing
// one tag from the sidebar then cost THREE full rounds of page fetches — the
// edit's own invalidation, the coalescer's, and this re-sync's a second later
// — each aborting the last, and on a million-item library each round is a
// half-second walk per mounted page. Measured there: ten `POST
// /api/items/query` for a window of three pages, six of them abandoned, the
// live ones answering 503 after two seconds, the sidebar's own counts five
// seconds behind.
//
// A re-sync we skip here loses nothing: this is a heal for a writer that sends
// no invalidation, and an edit of OURS has just invalidated the very same keys
// (`EDIT_KEYS` / `LIBRARY_KEYS` are supersets of the four below). The revision
// is adopted either way, so a genuine external write after the window still
// reads as a mismatch and still heals.
const OWN_CHANGE_WINDOW = 5_000;
let ownChangeAt = 0;

/** This app just changed the library — the next revision move is ours. */
function noteOwnChange(): void {
  ownChangeAt = Date.now();
}

const resyncCoalescer = makeCoalescer(
  () => {
    if (!qc) return;
    // The grid pages and layout, plus the counts beside them — a fresh grid
    // under a sidebar still counting the old library is half a heal.
    for (const k of ["items", "item-groups", "facets", "library-stats"]) {
      void qc.invalidateQueries({ queryKey: [k] });
    }
  },
  { wait: 1000, maxWait: 4000 }
);

export function reportLibraryRev(rev: string | undefined): void {
  if (!rev) return;
  if (seenRev === null) { seenRev = rev; return; }
  if (rev !== seenRev) {
    seenRev = rev;
    if (Date.now() - ownChangeAt < OWN_CHANGE_WINDOW) return;
    resyncCoalescer.call();
  }
}

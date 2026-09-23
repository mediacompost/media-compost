// What each Storage-page row key is CALLED, and which glyph it wears.
//
// A pure module for the same reason `artifactKinds.ts` is one: the backend
// sends a KEY ("thumbnails") and the page words it, so these strings reach
// `t()` as table values where the i18n extractor cannot see them — the table
// itself is what `i18nCoverage.test.ts` harvests, and a `.tsx` file is not
// something `node --test` can import to do it.
export const STORAGE_ROW_LABELS: Record<string, string> = {
  // Items, by the kind of item the file belongs to.
  image: "Pictures",
  video: "Videos",
  sequence: "Sequences",
  // Everything in the library folder that is not an item's own bytes.
  thumbnails: "Thumbnails",
  training: "Training runs",
  evaluate: "Evaluate images",
  scratch: "Scratch files",
  backups: "Backups from schema upgrades",
  database: "Database",
};

export const STORAGE_ROW_ICONS: Record<string, string> = {
  image: "image", video: "movie", sequence: "auto_stories",
  thumbnails: "grid_view", training: "model_training",
  evaluate: "science", scratch: "cached",
  backups: "backup", database: "database",
};

/** A key this build has never heard of — the rows come from the library and
 *  the table is the UI's — reads as itself rather than as nothing. */
export function storageRowLabel(key: string): string {
  return STORAGE_ROW_LABELS[key] ?? key;
}

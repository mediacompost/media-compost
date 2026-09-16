/** A TAG LIST FROM A CSV, read into the rows a tag set's bulk import takes —
 *  the pure half of the Tag sets tab's "Import CSV…".
 *
 *  A booru dump is the case this exists for: one row per tag, a name, a post
 *  count, a category NUMBER and, with luck, a wiki excerpt and the aliases
 *  that redirect to it. The header is GUESSED by the words a column is
 *  usually called and the person corrects the guess in the dialog; the rows
 *  are then normalized the way every tag field normalizes a typed name (a
 *  malformed name is what the API refuses, and a refused row ended an import
 *  before), deduplicated by lowercase name (a dump has one row per tag, a
 *  hand-made file need not), and rows under a MINIMUM COUNT are left out —
 *  a dump lists every tag ever used once, and the ones worth describing
 *  are the ones used often. A category is kept as the file spells it: a
 *  set's categories are its own, and a table of one site's numbering was
 *  a fact about that site. Pure, so `node --test` states the whole of it. */

import { tagFieldName } from "./tags.ts";
import type { TagSetBulkRowIn } from "./api";

export type CsvField = "name" | "description" | "count" | "category" | "aliases"
  | "implies";
export const CSV_FIELDS: readonly CsvField[] =
  ["name", "description", "count", "category", "aliases", "implies"];

/** Column index per field, or absent: what the header suggests. */
export type ColumnMap = Partial<Record<CsvField, number>>;

const HEADER_WORDS: Record<CsvField, readonly string[]> = {
  name: ["name", "tag", "tag_name", "tagname", "title", "consequent", "consequent_name"],
  description: ["description", "wiki", "wiki_page", "desc", "about", "body", "summary"],
  count: ["count", "post_count", "posts", "uses", "postcount", "tag_count"],
  category: ["category", "group", "type", "kind", "path"],
  aliases: ["aliases", "alias", "antecedent", "antecedents", "antecedent_name",
            "other_names", "other_name", "synonyms"],
  implies: ["implies", "implications", "implied", "parents"],
};

/** Which column is which, from the header row alone: an exact word per
 *  field first (so `tag_count` is the count and not the name), then a column
 *  CONTAINING the word, each column claimed once. */
export function guessColumns(headers: readonly string[]): ColumnMap {
  const norm = headers.map((h) => h.trim().toLowerCase().replace(/[\s-]+/g, "_"));
  const out: ColumnMap = {};
  const taken = new Set<number>();
  for (const f of CSV_FIELDS) {
    const i = norm.findIndex((h, k) => !taken.has(k) && HEADER_WORDS[f].includes(h));
    if (i >= 0) { out[f] = i; taken.add(i); }
  }
  for (const f of CSV_FIELDS) {
    if (out[f] != null) continue;
    const i = norm.findIndex((h, k) => !taken.has(k)
      && HEADER_WORDS[f].some((w) => h.includes(w)));
    if (i >= 0) { out[f] = i; taken.add(i); }
  }
  return out;
}

/** Does the first row read as a header — no cell that is a plain number and
 *  at least one that a header word matches. A dump with no header starts
 *  with a tag name and a count. */
export function looksLikeHeader(first: readonly string[]): boolean {
  if (first.some((c) => /^\d+$/.test(c.trim()))) return false;
  return Object.keys(guessColumns(first)).length > 0;
}

/** A list cell — aliases, implied names — split on commas AND whitespace: a
 *  tag name holds neither, so both are separators wherever they appear. */
export function splitList(cell: string): string[] {
  return cell.split(/[,\s]+/).map((n) => tagFieldName(n)).filter(Boolean);
}

export interface CsvToRows {
  rows: TagSetBulkRowIn[];
  /** Rows dropped: a blank or malformed name, or a name seen already. */
  skipped: number;
  /** Rows dropped for a count under `minCount`. A row with NO count is
   *  kept — the rule is about the figure, and a missing one says nothing. */
  belowMin: number;
}

/**
 * The CSV as bulk rows. `hasHeader` drops the first row; `minCount` drops a
 * row whose count is under it (the count column has to be mapped for it to
 * mean anything). Every optional field is written only when its column is mapped, so an
 * unmapped description is "not mentioned" rather than "" — the bulk op's
 * `existing: "replace"` clears a field a row carries EMPTY, and a file with
 * no description column must not wipe every description in the set.
 */
export function csvToBulkRows(
  table: readonly (readonly string[])[], map: ColumnMap,
  opts: { hasHeader: boolean; minCount?: number },
): CsvToRows {
  const rows: TagSetBulkRowIn[] = [];
  const seen = new Set<string>();
  let skipped = 0, belowMin = 0;
  const min = opts.minCount ?? 0;
  const cell = (r: readonly string[], f: CsvField) =>
    map[f] == null ? undefined : (r[map[f]!] ?? "").trim();
  for (const r of table.slice(opts.hasHeader ? 1 : 0)) {
    if (r.every((c) => !c.trim())) continue;
    const raw = cell(r, "name") ?? "";
    const name = tagFieldName(raw);
    if (!name || seen.has(name)) { skipped += 1; continue; }
    seen.add(name);
    const row: TagSetBulkRowIn = { name };
    const d = cell(r, "description");
    if (d != null) row.description = d;
    const c = cell(r, "count");
    if (c != null) {
      const n = Number(c.replace(/[,\s]/g, ""));
      row.count = c !== "" && Number.isFinite(n) ? Math.max(0, Math.round(n)) : null;
      if (row.count != null && row.count < min) { belowMin += 1; seen.delete(name); continue; }
    }
    // ONE cell has to hold the whole trail, so here — and only here — a
    // '/' separates two category names. That is the documented price of a
    // spreadsheet column (`docs/tag-sets.md`): a category whose own name
    // holds a slash is made in the Sets tab or in a tag-set file, not by
    // CSV. Nothing round-trips through this: the export is the JSON file.
    const cat = cell(r, "category");
    if (cat != null && cat !== "") {
      const trail = cat.split("/").map((p) => p.trim()).filter(Boolean);
      if (trail.length) row.category = trail;
    }
    const al = cell(r, "aliases");
    if (al) row.aliases = splitList(al).filter((a) => a !== name);
    const im = cell(r, "implies");
    if (im) row.implies = splitList(im).filter((a) => a !== name);
    rows.push(row);
  }
  return { rows, skipped, belowMin };
}

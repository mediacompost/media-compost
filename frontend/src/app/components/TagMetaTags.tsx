// WHAT THE TAG SET SAYS ABOUT A TAG, edited.
//
// A meta tag on a tag — "noflip", "character", "from a booru" — annotates the
// TAG rather than any picture carrying it (see `db.TagMetaTag`), so it belongs
// in the four dialogs where what a tag IS gets changed: the tag editor, and
// the subject / place / event editors, each of which edits extra data ON a
// tag. ONE component for all four, or four dialogs would grow four dialects of
// one list.
//
// It is CONTROLLED and applies nothing: like the implications above it, the
// list is edited locally and the parent diffs it at Save, so Cancel means
// "never mind" rather than "close a dialog half of which already happened".
// `syncTagMetaTags` is that diff, and it takes the tag by NAME because two of
// the four callers create the tag in the same save and only learn its id
// afterwards.
//
// A row also carries the assignment's own COUNT — pictures the tag has where
// that meta tag says, "tumblr 900" — which is the number the capsules and the
// autocomplete hover show. It was written by the CSV import and the Python
// API only, so a figure that had gone stale (or arrived wrong) could be read
// everywhere and corrected nowhere. Edited HERE because it is a fact about
// the assignment this list is of, and by the same diff-at-Save rule: the map
// is sparse (nonzero only, the shape `TagRow.meta_counts` already has), so an
// emptied field IS a zero and a zero IS no count.
import React, { useMemo, useState } from "react";
import { filterNumeric } from "../../shared/useNumericText";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api";
import { tagFieldName } from "../tags";
import { useT } from "../i18n";
import { NameList } from "./TagEditOverlay";
import { TagAutocomplete } from "./TagAutocomplete";

/** The editor. `names` is the desired list; the parent applies it. */
export function TagMetaTagsField({ names, counts, onChange, onCounts }: {
  names: string[];
  /** The desired per-assignment counts, keyed by meta-tag name — sparse, so
   *  a name that is absent carries no count. */
  counts: Record<string, number>;
  onChange: (next: string[]) => void;
  onCounts: (next: Record<string, number>) => void;
}) {
  const t = useT();
  const [adding, setAdding] = useState("");
  // The namespace's own names, so a meta tag is picked rather than re-typed —
  // and a typo is a new meta tag nobody meant to make.
  const { data: known } = useQuery({
    queryKey: ["link-tags"], queryFn: api.linkTags,
  });
  const suggestions = useMemo(
    () => (known ?? [])
      .filter((n) => !names.includes(n))
      .map((n) => ({ name: n, comment: "", uses: 0 })),
    [known, names]
  );
  const add = (raw: string) => {
    const v = tagFieldName(raw);
    if (!v || names.includes(v)) return;
    setAdding("");
    onChange([...names, v]);
  };
  const setCount = (name: string, n: number) => {
    const next = { ...counts };
    if (n > 0) next[name] = n; else delete next[name];
    onCounts(next);
  };
  return (
    <NameList
      label={t("Meta tags")}
      icon="label"
      names={names}
      onRemoved={(gone) => {
        onChange(names.filter((n) => !gone.has(n)));
        // The count goes with the assignment it was about — the diff reads
        // only the names that stay, so a leftover would be inert, but it
        // would also come back with the name if it were added again.
        onCounts(Object.fromEntries(
          Object.entries(counts).filter(([n]) => !gone.has(n))));
      }}
      removeTitle={t("Remove this meta tag")}
      removeManyTitle={t("Remove the selected meta tags")}
      empty={t("Nothing is said about this tag yet.")}
      trailing={(n) => (
        <MetaCount value={counts[n] ?? 0}
                   onChange={(v) => setCount(n, v)}
                   placeholder={t("no count")}
                   title={t("Pictures the tag has where this meta tag says")} />
      )}
      adder={
        <TagAutocomplete
          value={adding}
          onChange={setAdding}
          onCommit={(v) => add(v)}
          suggestions={suggestions}
          placeholder={t("Add a meta tag…")}
        />
      }
    />
  );
}

/** Do two count maps say the same thing? Over the UNION of their keys,
 *  because both are SPARSE: a name that is absent and a name at zero are one
 *  statement, so a plain deep-equal would call a dialog dirty for having
 *  typed a number and taken it out again. The three editors' unsaved-changes
 *  guards share it. */
export function sameMetaCounts(a: Record<string, number>,
                              b: Record<string, number>): boolean {
  return [...new Set([...Object.keys(a), ...Object.keys(b)])]
    .every((k) => (a[k] ?? 0) === (b[k] ?? 0));
}

/** One assignment's count, in the row.
 *
 *  Its own text state, because the map is SPARSE: rendering `counts[n] ?? 0`
 *  would put a "0" in every uncounted row, and clearing the field would read
 *  back as one. Mounted per row (`NameList` keys those by name), so it starts
 *  from the count the list opened with and never has to chase the prop.
 *
 *  The row underneath is a selectable one — press-and-drag paints the
 *  selection — so both pointer events stop here, or typing into the field
 *  would pick the row it is in. */
function MetaCount({ value, onChange, placeholder, title }: {
  value: number;
  onChange: (n: number) => void;
  placeholder: string;
  title: string;
}) {
  const [text, setText] = useState(value ? String(value) : "");
  return (
    <input
      value={text}
      inputMode="numeric"
      placeholder={placeholder}
      title={title}
      onMouseDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
      onChange={(e) => {
        // The one number-field rule: a keystroke that is not a digit is
        // refused, never stripped.
        const v = filterNumeric(e.target.value, { integer: true, maxLen: 12 });
        if (v == null) return;
        setText(v);
        onChange(v === "" ? 0 : Number(v));
      }}
      style={{
        width: 78, height: 22, padding: "0 7px", textAlign: "right",
        background: "var(--bg)", border: "1px solid var(--border)",
        borderRadius: "var(--r-2)", color: "var(--text-2)", fontFamily: "var(--mono)",
        fontSize: "var(--fs-2)", outline: "none", boxSizing: "border-box",
      }}
    />
  );
}

/**
 * Apply the difference between what the dialog holds and what the tag had.
 *
 * By NAME rather than by id: the place and event editors CREATE the tag in the
 * same save, so the id does not exist while the form is being filled in. The
 * catalog is re-read only when there is something to apply — a dialog nobody
 * touched the list in costs nothing.
 */
export async function syncTagMetaTags(
  tagName: string, want: string[], was: string[],
  counts: Record<string, number> = {},
  wasCounts: Record<string, number> = {},
): Promise<void> {
  const removed = was.filter((n) => !want.includes(n));
  // ONE loop for "added" and "its count changed": the endpoint is idempotent
  // and sets the figure either way (`tagcatalog.add_meta_tag`), so an
  // assignment that stays needs no call of its own — and a fresh one whose
  // count is 0 writes the very event a countless add always wrote.
  const put = want.filter((n) => !was.includes(n)
    || (counts[n] ?? 0) !== (wasCounts[n] ?? 0));
  if (!put.length && !removed.length) return;
  const row = (await api.tags()).find((x) => x.name === tagName);
  if (!row) return;
  for (const n of removed) await api.removeTagMetaTag(row.id, n);
  for (const n of put) await api.addTagMetaTag(row.id, n, counts[n] ?? 0);
}

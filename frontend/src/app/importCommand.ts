// The import overlay's settings, written out as the `media-compost import`
// command that does the same thing.
//
// It exists because the two doors are not equally good at scale: a browser
// import uploads every byte through the server and stages it on disk before
// the importer reads it, while the CLI reads the files where they lie. For a
// handful of pictures that costs nothing; for a folder of thousands it is the
// difference between an afternoon and a coffee.
//
// Pure, so the exact spelling of every flag is a test rather than a claim —
// this string is meant to be pasted into a shell, and a wrong quote or a
// missing `=` is a command that fails or, worse, quietly does something else.

/** How many roots to name before the command becomes unreadable. Past this
 *  it is one placeholder: a command listing forty folders is not one anybody
 *  edits, and every path in it is a placeholder anyway. */
export const MAX_ROOTS = 6;

export interface ImportCommandOpts {
  /** The library's data directory, from the stats endpoint. */
  dataDir?: string;
  /** Relative paths as the browser reported them ("folder/sub/a.png"). */
  rels: string[];
  /** The parent group's name — used only when it is UNAMBIGUOUS. */
  parentGroup?: string;
  /** Its id, for when the name is not: `Group.name` is not unique, so a
   *  library can hold "abc" inside "abc" and `-g abc` cannot say which. */
  parentGroupId?: number | null;
  /** True when another group shares `parentGroup`'s name. */
  parentAmbiguous?: boolean;
  /** A group of this run's own INSIDE the parent; an empty name leaves the
   *  CLI to use its own default, which is the same one this dialog would
   *  have got. */
  newGroup?: boolean;
  newGroupName?: string;
  foldersAsGroups: boolean;
  archivesAsGroups: boolean;
  archiveSequences: boolean;
  minMegapixels: number;
  minShortEdge: number;
  minLongEdge: number;
  /** The aspect range, width/height; 0 is "not set" on each side. */
  minAspect: number;
  maxAspect: number;
  ignoreKinds: string[];
  /** Which half of a sequence joins the groups: both | container | members. */
  sequenceGrouping: string;
  tags: string[];
  tagsImage: string[];
  tagsVideo: string[];
  tagsSequence: string[];
  tagsExisting: boolean;
}

/** POSIX quoting: leave a plain word alone, single-quote anything else.
 *  A single quote inside is closed, escaped and reopened — the one form that
 *  works in every POSIX shell. */
export function shellQuote(s: string): string {
  // A comma is in the safe set: `--ignore-kinds video,archive` is one word
  // to every POSIX shell, and quoting it would only make the line noisier.
  if (s !== "" && /^[A-Za-z0-9._/@:=+,-]+$/.test(s)) return s;
  return `'${s.replace(/'/g, `'\\''`)}'`;
}

/** The paths to hand the command.
 *
 *  A browser never says where a dropped file came from — only its path
 *  RELATIVE to what was dropped — so these are the dropped things' own names
 *  under a placeholder the reader replaces. That is the one part of this
 *  command that cannot be filled in from here, and saying so with an obvious
 *  `/path/to/` beats guessing. */
export function commandRoots(rels: string[]): string[] {
  const seen: string[] = [];
  const known = new Set<string>();
  for (const rel of rels) {
    const top = rel.split("/")[0];
    if (!top || known.has(top)) continue;
    known.add(top);
    seen.push(top);
    if (seen.length > MAX_ROOTS) return ["/path/to/folder"];
  }
  if (seen.length === 0) return ["/path/to/folder"];
  return seen.map((name) => `/path/to/${name}`);
}

/** What one of these commands is made of.
 *
 *  TWO PARTS, because only one of them is real — `command` is the part that
 *  is true of this machine and is what the Copy button puts on the
 *  clipboard, while `paths` are placeholders nobody can fill in from here —
 *  shown in the panel in their own colour, LAST, where the real paths go,
 *  and deliberately left out of the copy: a pasted command that would run
 *  against `/path/to/folder` is one that does the wrong thing quietly.
 */
export interface ImportCommand {
  /** Everything that is really this run: the binary, the library and every
   *  flag that differs from the CLI's own default. Copyable as-is. */
  command: string;
  /** The placeholder paths, quoted, in the order they were dropped. */
  paths: string[];
}

/** The command for these settings — only what DIFFERS from the CLI's own
 *  defaults, so the line stays readable and every flag in it means something.
 */
export function buildImportCommand(o: ImportCommandOpts): ImportCommand {
  const parts = ["media-compost", "import"];
  if (o.dataDir) parts.push("--data-dir", shellQuote(o.dataDir));
  // A NAME while it identifies one group — readable, and portable to a
  // library that has no such group yet, since the CLI creates it — and the
  // ID the moment it does not.
  if (o.parentGroup && o.parentAmbiguous && o.parentGroupId != null) {
    parts.push("--parent-group-id", String(o.parentGroupId));
  } else if (o.parentGroup) {
    parts.push("-g", shellQuote(o.parentGroup));
  }
  // The NAME implies the flag on the CLI side, so one word covers the
  // common case and the bare flag is only for an unnamed box.
  if (o.newGroup) {
    if (o.newGroupName?.trim()) {
      parts.push("--new-group-name", shellQuote(o.newGroupName.trim()));
    } else {
      parts.push("--new-group");
    }
  }
  if (!o.foldersAsGroups) parts.push("--no-folders-as-groups");
  // ON is the flag now: the CLI's own default is off (a comic archive is
  // already a sequence, so a group around the same pages says less).
  if (o.archivesAsGroups) parts.push("--archives-as-groups");
  if (o.archiveSequences) parts.push("--archive-sequences");
  if (o.minMegapixels > 0) parts.push("--min-resolution", String(o.minMegapixels));
  if (o.minShortEdge > 0) parts.push("--min-short-edge", String(o.minShortEdge));
  if (o.minLongEdge > 0) parts.push("--min-long-edge", String(o.minLongEdge));
  if (o.minAspect > 0) parts.push("--min-aspect", String(o.minAspect));
  if (o.maxAspect > 0) parts.push("--max-aspect", String(o.maxAspect));
  if (o.ignoreKinds.length) {
    parts.push("--ignore-kinds", shellQuote(o.ignoreKinds.join(",")));
  }
  if (o.sequenceGrouping && o.sequenceGrouping !== "both") {
    parts.push("--sequence-grouping", o.sequenceGrouping);
  }
  // `--tag=NAME`, always with the `=`: a negative tag travels as a leading
  // "-", which argparse reads as an option wherever the value is a separate
  // word.
  const tagFlag = (flag: string, names: string[]) => {
    for (const n of names) parts.push(`${flag}=${shellQuote(n)}`);
  };
  tagFlag("--tag", o.tags);
  tagFlag("--tag-image", o.tagsImage);
  tagFlag("--tag-video", o.tagsVideo);
  tagFlag("--tag-sequence", o.tagsSequence);
  if (!o.tagsExisting) parts.push("--no-tag-existing");
  // The paths come LAST — where a hand types them, and where they can be
  // shown apart from the rest. argparse takes positionals after options.
  return { command: parts.join(" "),
           paths: commandRoots(o.rels).map(shellQuote) };
}

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Collapse } from "../../shared/Collapse";
import { storage } from "../../shared/storage";
import { rowBackground } from "../../shared/Row";
import { SECTION_LABEL } from "../../shared/SectionHeading";
import { IconButton } from "../../shared/IconButton";
import { Button } from "../../shared/Button";
import { pickNext } from "../../shared/pickList";
import { Switch } from "../../shared/Switch";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { formatBytes } from "../format";
import { Icon } from "../../shared/Icon";
import { useLang, useT, useTn } from "../i18n";
import { useUI } from "../store";
import { Overlay } from "../../shared/Overlay";
import { GroupSelect, flattenGroupTree } from "./GroupSelect";
import { addImportTask } from "../importManager";
import { CombinedTagEditor } from "./CombinedTagEditor";
import { fetchTagNameSuggestions, TagSuggestion } from "./TagAutocomplete";
import { useWindowedList } from "../useWindowedList";
import { buildImportCommand } from "../importCommand";
import { RemoveRuleBtn, Threshold } from "./SettingsStorage";
import { EmbedModelPicker, embedderIds } from "./EmbedModelPicker";
import { useMenuDismiss } from "../../shared/useMenuDismiss";
import { AnchoredDropdown, useAnchorRect }
  from "../../shared/AnchoredDropdown";

//: The dialog body's own padding, and the gap between the left column's
//: rows. `GRID_PAD` is named because the column's height is COMPUTED from it
//: (see `columnHeight`): a literal that drifted from the padding would size
//: the column against a layout that is not the one on screen.
const GRID_PAD = 20;
const COL_GAP = 16;

// One staged row: minHeight 28 content + 1px separator.
const STAGED_ROW_H = 29;

const IMAGE = /\.(jpg|jpeg|png|webp|bmp|gif|tif|tiff|heic|heif|avif)$/i;
const VIDEO = /\.(mp4|mov|m4v|avi|mkv|webm)$/i;
const COMIC = /\.(cbz|cbr)$/i;
const ARCHIVE = /\.(zip|7z|cbz|cbr)$/i;
// A PDF is a container of pictures exactly as a comic archive is: every page
// becomes an image item and the pages become a sequence. It reads as its own
// kind here only because its icon should say "document".
const PDF = /\.pdf$/i;

function kindOf(name: string): { tag: string; icon: string; color: string } {
  if (PDF.test(name)) return { tag: "pdf", icon: "picture_as_pdf", color: "var(--archive)" };
  if (COMIC.test(name)) return { tag: "archive", icon: "menu_book", color: "var(--archive)" };
  if (ARCHIVE.test(name)) return { tag: "archive", icon: "folder_zip", color: "var(--archive)" };
  if (VIDEO.test(name)) return { tag: "video", icon: "movie", color: "var(--movie)" };
  if (IMAGE.test(name)) return { tag: "image", icon: "image", color: "var(--accent)" };
  return { tag: "other", icon: "description", color: "var(--muted-2)" };
}

function isCompatible(name: string): boolean {
  return kindOf(name).tag !== "other";
}

function relPathOf(f: File): string {
  return (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;
}

/** What identifies one staged file — its path as dropped plus its size. */
const keyOf = (f: File) => `${relPathOf(f)}:${f.size}`;

// THE STAGED DROP OUTLIVES THE DIALOG. The app has one overlay slot, so the
// "Set up" button on an unavailable detector CLOSES this dialog to open
// Settings — and a list of four thousand files that vanished on the way to
// installing a detector would be worse than no button at all. Held in the
// module rather than the store: they are `File` handles for this session, the
// same thing `importManager` holds for a running task, and nothing else in
// the app has any business reading them. Cleared when the import starts or
// the list is cleared by hand.
let heldStaged: File[] = [];

// --- Drag-and-drop folder expansion -----------------------------------------
// A plain drop only exposes `dataTransfer.files`, which lists dropped folders as
// unusable entries. The (webkit) filesystem-entry API lets us recurse into them.

/* eslint-disable @typescript-eslint/no-explicit-any */
function readAllEntries(reader: any): Promise<any[]> {
  return new Promise((resolve, reject) => {
    const acc: any[] = [];
    const pump = () =>
      reader.readEntries((batch: any[]) => {
        if (batch.length === 0) resolve(acc);
        else {
          acc.push(...batch);
          pump();
        }
      }, reject);
    pump();
  });
}

async function walkEntry(entry: any, prefix: string, out: File[],
                        onCount?: (n: number) => void): Promise<void> {
  if (entry.isFile) {
    const file: File = await new Promise((res, rej) => entry.file(res, rej));
    const rel = prefix ? `${prefix}/${file.name}` : file.name;
    try {
      Object.defineProperty(file, "webkitRelativePath", { value: rel, configurable: true });
    } catch {
      /* ignore — falls back to the bare file name */
    }
    out.push(file);
    onCount?.(out.length);
  } else if (entry.isDirectory) {
    const childPrefix = prefix ? `${prefix}/${entry.name}` : entry.name;
    for (const child of await readAllEntries(entry.createReader())) {
      await walkEntry(child, childPrefix, out, onCount);
    }
  }
}

/** Every file under what was dropped, reporting the running count.
 *
 *  The count is what the drop zone SAYS while this runs: walking a folder of
 *  thousands takes seconds during which the dialog looks exactly as it did
 *  before the drop, and a headline swapping one line of text for another is
 *  easy to miss. A number going up is not. */
async function filesFromDrop(dt: DataTransfer,
                             onCount?: (n: number) => void): Promise<File[]> {
  const entries = Array.from(dt.items || [])
    .filter((it) => it.kind === "file")
    .map((it) => (it.webkitGetAsEntry ? it.webkitGetAsEntry() : null))
    .filter((e): e is any => !!e);
  if (entries.length === 0) return Array.from(dt.files || []); // no entry API
  const out: File[] = [];
  for (const entry of entries) await walkEntry(entry, "", out, onCount);
  return out;
}
/* eslint-enable @typescript-eslint/no-explicit-any */

// The two toggle settings persist across dialog reopens/reloads; the parent
// group is always reset to the current single selection (see below).
const OPTS_KEY = "mc.importOptions";
interface ImportOpts {
  foldersAsGroups: boolean; archivesAsGroups: boolean;
  archiveSequences: boolean;
  /** Which half of a SEQUENCE joins the run's groups: both | container |
   *  members. A book is two things at once — the item the library shows and
   *  the pages inside it — and which of them somebody wants in their groups
   *  is a real choice. */
  sequenceGrouping: string;
  /** What the run leaves alone. Remembered like the grouping toggles —
   *  "not the thumbnails again" is a preference, not a per-drop decision.
   *  The three numbers are kept as TEXT, because "" and "0" are the same
   *  rule and a half-typed "0." has to survive the next keystroke. */
  minMegapixels: string;
  minShortEdge: string;
  minLongEdge: string;
  /** The aspect RANGE, width/height, kept as text for the same reason: a
   *  picture narrower than `minAspect` or wider than `maxAspect` is left
   *  out, and an empty end is one nobody set. */
  minAspect: string;
  maxAspect: string;
  ignoreKinds: string[];
  /** WHICH filter rows are on the Ignore card, in `IGNORE_FILTERS` order.
   *  Kept apart from the values because a row that has just been added has
   *  no value yet — and because "" and "0" are the same rule, so the value
   *  cannot say whether somebody asked the question. */
  ignoreFilters: string[];
  /** A group of this run's own, inside "Where it goes". The name is empty
   *  for the backend's own default (a timestamp), which is where that
   *  answer lives so the dialog and the CLI cannot drift. */
  newGroup: boolean;
  newGroupName: string;
  /** Model key to detect faces with on everything imported; "" = don't. */
  detectFaces: string;
  /** Embedder ids to index the imported pictures with (the tag batch's smart
   *  ordering), COMMA-SEPARATED; "" = don't. Several is several runs: the
   *  spaces are indexed independently and never mixed. The same spelling all
   *  the way to the form field, so a value remembered as one bare id — every
   *  one written before multi-selection — still means what it meant. */
  indexEmbeddings: string;
}
const DEFAULT_OPTS: ImportOpts = {
  // Archives-as-groups is OFF: a comic archive is already a SEQUENCE, which
  // is the thing that holds its pages in order and the thing the library
  // shows, so a group around the same pages is a second container saying
  // less — and a folder of forty chapters made forty of them.
  foldersAsGroups: true, archivesAsGroups: false, archiveSequences: false,
  sequenceGrouping: "both",
  minMegapixels: "", minShortEdge: "", minLongEdge: "",
  minAspect: "", maxAspect: "", ignoreKinds: [], ignoreFilters: [],
  newGroup: false, newGroupName: "",
  detectFaces: "", indexEmbeddings: "",
};

/** The rules the Ignore card can hold, in the order they appear once added.
 *
 *  They are ADDED one at a time rather than all shown at once: five
 *  thresholds and a type picker is six questions asked of every import, and
 *  almost every import answers none of them. What is on the card is what
 *  this library actually filters on.
 */
const IGNORE_FILTERS = [
  { key: "mp", label: "Resolution under", unit: "MP" },
  { key: "short", label: "Shortest edge under", unit: "px" },
  { key: "long", label: "Longest edge under", unit: "px" },
  // The last two thresholds are a RANGE rather than two more minimums, and
  // they are width÷height throughout: 1 is square, 0.5 twice as tall as
  // wide, 2 twice as wide as tall. Each end stands alone — "no panoramas" is
  // the second by itself — which is why the wording is "under" and "over".
  { key: "amin", label: "Aspect ratio under", unit: "w/h" },
  { key: "amax", label: "Aspect ratio over", unit: "w/h" },
  // The sixth is not a threshold: which TYPES to leave alone.
  { key: "kinds", label: "Ignored file types", unit: "" },
] as const;
/** The four buckets an import can be handed — the partition
 *  `ImportOptions.ignore_kinds` names, in the app's own words and icons for
 *  them (the grid's own three, plus the archive that scatters). */
const IGNORE_KINDS = [
  { kind: "image", label: "Images", icon: "image" },
  { kind: "video", label: "Videos", icon: "movie" },
  { kind: "sequence", label: "Sequences", icon: "collections_bookmark" },
  { kind: "archive", label: "Archives", icon: "folder_zip" },
] as const;
function loadImportOpts(): ImportOpts {
  try {
    const o = JSON.parse(storage.get(OPTS_KEY) || "{}");
    return { ...DEFAULT_OPTS, ...o };
  } catch {
    return { ...DEFAULT_OPTS };
  }
}

/** The command that does this import from a terminal.
 *
 *  Collapsed by default and always offered — a browser import uploads every
 *  byte to the server and stages it on disk before the importer reads one,
 *  where the CLI reads them where they lie, and which of those somebody
 *  wants is not something a file count can decide. (It used to appear only
 *  past 500 files, which is the same guess made worse by being invisible
 *  until then.)
 *
 *  THE PLACEHOLDERS ARE SHOWN AND NOT COPIED. A browser is never told where
 *  a dropped file came from — only its path relative to what was dropped —
 *  so the paths are the one part of this line nobody can fill in from here:
 *  they sit LAST, in their own colour, and the Copy button leaves them out
 *  rather than handing over a command that would quietly run against
 *  `/path/to/folder`.
 */
function CliHint({ command, paths, note, t }:
  { command: string; paths: string[]; note: string; t: (s: string) => string }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const copy = () => {
    try {
      navigator.clipboard?.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch { /* the command is on screen either way */ }
  };
  return (
    // ONE BOX, open or shut — the title is its top row rather than a line
    // floating above it, so a collapsed panel is a thing on the page instead
    // of a stray sentence with a frame that appears underneath it.
    <div style={{
      border: "1px solid var(--border-strong)", borderRadius: "var(--r-6)",
      background: "var(--panel-3)", padding: "10px 12px",
      display: "flex", flexDirection: "column",
    }}>
      {/* THE HEADER ROW IS THE SAME HEIGHT EITHER WAY. Its padding and the
          row's own height are fixed, so opening the panel does not nudge the
          title it was clicked on — the Copy button that appears beside it is
          taller than the words, and without a floor the line moved under the
          pointer. */}
      <div style={{ display: "flex", alignItems: "center", gap: 5,
                    minHeight: 22 }}>
        <div
          onClick={() => setOpen((v) => !v)}
          style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "center",
                   gap: 5, cursor: "pointer", fontSize: "var(--fs-2)",
                   color: "var(--muted)", fontWeight: 600, userSelect: "none" }}
        >
          <Icon name={open ? "expand_more" : "chevron_right"} size={15} />
          {t("Import from terminal (faster)")}
        </div>
        {/* Only while it is open: a Copy button on a folded panel offers
            something nobody can see. */}
        {open && (
          <span
            onClick={copy}
            title={t("Copy the command (without the paths)")}
            style={{ display: "flex", alignItems: "center", gap: 4,
                     height: 22, padding: "0 7px", borderRadius: "var(--r-2)",
                     cursor: "pointer", fontSize: "var(--fs-2)", flex: "0 0 auto",
                     color: copied ? "var(--green)" : "var(--muted)" }}
          >
            {/* The tick and the green ARE the feedback — "Copied" is the
                train package's key, and one key may not live in two. */}
            <Icon name={copied ? "check" : "content_copy"} size={14} />
            {t("Copy")}
          </span>
        )}
      </div>
      {/* THE HOUSE COLLAPSE (`0fr` → `1fr` with a transition; the same one
          the properties panel's sections and the sidebar's stats use). The
          drop zone above is a flex sibling of this box, so it gives up
          exactly what the panel takes on every frame of this — the two move
          together instead of the panel appearing and everything jumping. */}
      <Collapse open={open}>
        {/* The space above the command is the pre's own MARGIN, not this
            wrapper's padding: padding sits on the wrapper's box, which the
            0fr row does not shrink — so a closed panel kept 7px of it and
            the box had more air under its title than over it. A margin is
            content, and content is what `overflow: hidden` clips. */}
        <div style={{ overflow: "hidden", minHeight: 0, display: "flex",
                      flexDirection: "column", gap: 7 }}>
          <pre style={{
            margin: "7px 0 0", padding: "8px 10px", background: "var(--bg-deep)",
            border: "1px solid var(--border)", borderRadius: "var(--r-4)",
            fontFamily: "var(--mono)", fontSize: "var(--fs-2)", lineHeight: 1.5,
            color: "var(--text-2)", whiteSpace: "pre-wrap",
            overflowWrap: "anywhere", userSelect: "text",
            WebkitUserSelect: "text",
          }}>
            {command}{" "}
            {/* The half nobody can fill in from here, in the colour this app
                uses for "somebody should look at this". */}
            <span style={{ color: "var(--yellow-text)" }}>
              {paths.join(" ")}
            </span>
          </pre>
          {note && (
            <div style={{ fontSize: "var(--fs-1)", color: "var(--muted-2)",
                          lineHeight: 1.45 }}>{note}</div>
          )}
        </div>
      </Collapse>
    </div>
  );
}

export function ImportOverlay() {
  const t = useT();
  const tn = useTn();
  const lang = useLang();
  const setOverlay = useUI((s) => s.setOverlay);
  const selectedGroups = useUI((s) => s.selectedGroups);
  const { data: tree } = useQuery({ queryKey: ["groups"], queryFn: api.groups });

  // The parent group always resets to the currently-selected group (if exactly
  // one is selected) or none — it is deliberately not persisted.
  const [parentId, setParentId] = useState<number | null>(
    selectedGroups.length === 1 ? selectedGroups[0] : null
  );
  const initialOpts = loadImportOpts();
  const [foldersAsGroups, setFoldersAsGroups] = useState(initialOpts.foldersAsGroups);
  const [archivesAsGroups, setArchivesAsGroups] = useState(initialOpts.archivesAsGroups);
  const [archiveSequences, setArchiveSequences] = useState(initialOpts.archiveSequences);
  const [sequenceGrouping, setSequenceGrouping] =
    useState(initialOpts.sequenceGrouping);
  // The gate, as TEXT: an empty field is a field being typed into, not a 0
  // that silently turns the option off under the hand doing it. What the run
  // gets is the parsed number.
  const [minMp, setMinMp] = useState(initialOpts.minMegapixels);
  const [minShort, setMinShort] = useState(initialOpts.minShortEdge);
  const [minLong, setMinLong] = useState(initialOpts.minLongEdge);
  const [minAspect, setMinAspect] = useState(initialOpts.minAspect);
  const [maxAspect, setMaxAspect] = useState(initialOpts.maxAspect);
  const [ignoreKinds, setIgnoreKinds] = useState<string[]>(
    initialOpts.ignoreKinds);
  // WHICH rules are on the Ignore card. Seeded from the stored list, plus
  // any rule that has a VALUE — so options written before the card asked
  // this question (or by a hand-edited entry) still show the rule they set,
  // rather than filtering on something with no row to see it in.
  const [ignoreFilters, setIgnoreFilters] = useState<string[]>(() => {
    const set = new Set(initialOpts.ignoreFilters ?? []);
    const has: Record<string, boolean> = {
      mp: !!initialOpts.minMegapixels, short: !!initialOpts.minShortEdge,
      long: !!initialOpts.minLongEdge, amin: !!initialOpts.minAspect,
      amax: !!initialOpts.maxAspect,
      kinds: (initialOpts.ignoreKinds ?? []).length > 0,
    };
    for (const f of IGNORE_FILTERS) if (has[f.key]) set.add(f.key);
    return IGNORE_FILTERS.filter((f) => set.has(f.key)).map((f) => f.key);
  });
  const num = (v: string) => Math.max(0, parseFloat(v) || 0);
  // A group of this run's own, inside whatever "Where it goes" names.
  const [newGroup, setNewGroup] = useState(initialOpts.newGroup);
  const [newGroupName, setNewGroupName] = useState(initialOpts.newGroupName);
  const [detectFaces, setDetectFaces] = useState(initialOpts.detectFaces);
  const [indexEmbeddings, setIndexEmbeddings] =
    useState(initialOpts.indexEmbeddings);
  // Tags for everything the run creates, plus per-kind lists behind a
  // disclosure. Deliberately NOT persisted, like the parent group: a stale
  // "batch1" quietly riding next month's import is a footgun, where
  // re-picking a grouping behavior is a preference.
  const [tags, setTags] = useState<SignedTags>(NO_TAGS);
  const [tagsImage, setTagsImage] = useState<SignedTags>(NO_TAGS);
  const [tagsVideo, setTagsVideo] = useState<SignedTags>(NO_TAGS);
  const [tagsSequence, setTagsSequence] = useState<SignedTags>(NO_TAGS);
  const [byKindOpen, setByKindOpen] = useState(false);
  // Whether the run's tags also land on items it MATCHED rather than created
  // (exact duplicates, near-dup folds). Default on: a re-import of a folder
  // is how a batch gets a tag after the fact.
  const [tagsExisting, setTagsExisting] = useState(true);

  // Which face detectors this machine can actually run. Same rule the action
  // menus use: the plugin's dependencies are installed AND every weight family
  // it needs is downloaded.
  const { data: mlModels } = useQuery({ queryKey: ["ml-models"], queryFn: api.mlModels });
  const { data: modelCache } = useQuery({ queryKey: ["model-cache"], queryFn: api.modelCache });
  const readyModels = React.useCallback((kind: string) => {
    const cached = new Map((modelCache?.models ?? []).map((m) => [m.key, m.cached]));
    const task = (mlModels?.tasks ?? []).find((tk) => tk.kind === kind);
    return (task?.models ?? []).filter(
      (m) => m.available && (m.family_keys ?? []).every((k) => cached.get(k) !== false)
    );
  }, [mlModels, modelCache]);
  const faceModels = React.useMemo(() => readyModels("faces"), [readyModels]);
  // The embedders behind the tag batch's smart ordering — indexing on import
  // is what saves the "Index remaining" wait the chooser otherwise offers.
  const embedModels = React.useMemo(() => readyModels("embed"), [readyModels]);
  // THE WAY OUT OF A DISABLED ROW. A detector nobody has installed left both
  // Detect rows switched off with a sentence naming a page to go to — an
  // errand, where the sidebar's own actions put a **Set up** chip right on
  // the thing that is not ready. This is that chip: it lands on the Actions
  // page with the model's own card highlighted (the AiActionButtons
  // pattern). The app has one overlay slot, so opening Settings closes this
  // dialog — which is why the staged drop is held in the module above.
  const setUpModel = (kind: string) => {
    const first = (mlModels?.tasks ?? [])
      .find((tk) => tk.kind === kind)?.models[0];
    const st = useUI.getState();
    const key = first?.family_keys?.[0];
    if (key) {
      st.setSettingsFocusModel(key);
      st.setSettingsFocusWarning(false);
    }
    st.setSettingsPage("actions");
    st.setOverlay("settings");
  };
  /** Rendered in a disabled Detect row's children — where the way out of the
   *  disabled state belongs. Nothing at all when the app knows no model of
   *  that kind: there would be nothing for Settings to show. */
  const setUpButton = (kind: string) => {
    const known = (mlModels?.tasks ?? [])
      .find((tk) => tk.kind === kind)?.models.length ?? 0;
    if (!known) return null;
    return (
      <button
        onClick={(e) => { e.stopPropagation(); setUpModel(kind); }}
        style={{ display: "flex", alignItems: "center", gap: 5, marginTop: 8,
                 height: 26, padding: "0 10px", borderRadius: "var(--r-3)",
                 border: "1px solid var(--border-strong)",
                 background: "var(--panel-2)", color: "var(--text-2)",
                 cursor: "pointer", fontFamily: "inherit", fontSize: "var(--fs-2)" }}
      >
        <Icon name="download" size={14} />
        {t("Set up")}
      </button>
    );
  };

  // A model that has gone away (uninstalled since the choice was remembered)
  // must not silently mean "the first one".
  useEffect(() => {
    if (detectFaces && mlModels && !faceModels.some((m) => m.id === detectFaces)) {
      setDetectFaces("");
    }
  }, [faceModels, detectFaces, mlModels]);
  useEffect(() => {
    if (!indexEmbeddings || !mlModels) return;
    // A LIST now, so an embedder that has gone away takes only itself out of
    // it — clearing the lot would switch the row off because the other one
    // is no longer installed.
    const keep = embedderIds(indexEmbeddings)
      .filter((id) => embedModels.some((m) => m.id === id));
    if (keep.length !== embedderIds(indexEmbeddings).length) {
      setIndexEmbeddings(keep.join(","));
    }
  }, [embedModels, indexEmbeddings, mlModels]);

  // Remember the toggles for next time the dialog opens (or the page reloads).
  useEffect(() => {
    try {
      storage.set(OPTS_KEY, JSON.stringify({
        foldersAsGroups, archivesAsGroups, archiveSequences, sequenceGrouping,
        minMegapixels: minMp, minShortEdge: minShort, minLongEdge: minLong,
        minAspect, maxAspect,
        ignoreKinds, ignoreFilters, newGroup, newGroupName,
        detectFaces, indexEmbeddings }));
    } catch {
      /* ignore */
    }
  }, [foldersAsGroups, archivesAsGroups, archiveSequences, sequenceGrouping,
      minMp, minShort, minLong, minAspect, maxAspect, ignoreKinds,
      ignoreFilters, newGroup, newGroupName, detectFaces,
      indexEmbeddings]);
  const [dragOver, setDragOver] = useState(false);
  const [scanning, setScanning] = useState(false);
  // How many files the folder walk has reached — the drop zone's live proof
  // that a big drop is being read rather than ignored.
  const [scanCount, setScanCount] = useState(0);
  // Dropped files WAIT here until Import is pressed. A drop used to start
  // straight away, which read as "too late" the moment you noticed a setting
  // was wrong — the options are on the same screen, so they should still be
  // worth reading when the files arrive. Unsupported files stage TOO — greyed
  // and struck through rather than counted in a corner, so a folder of RAWs
  // reads as a list of files this app cannot read, not as a bare number — and
  // only the supported ones are what Import sends.
  const [_staged, _setStaged] = useState<File[]>(() => heldStaged);
  const staged = _staged;
  const ready = useMemo(() => staged.filter((f) => isCompatible(f.name)),
                        [staged]);
  // THE HOLD IS WRITTEN HERE, not in an effect. It was one — and an effect
  // does not run for a render that never commits, which is exactly what
  // `startImport` does: it clears the list and closes the dialog in the same
  // batch, so React unmounted this component before the effect could write
  // the empty list back. The files stayed in the module, and reopening the
  // dialog after starting an import showed every one of them again, still
  // staged, as though nothing had been sent.
  const setStaged = useCallback(
    (next: File[] | ((cur: File[]) => File[])) => {
      _setStaged((cur) => {
        const value = typeof next === "function" ? next(cur) : next;
        heldStaged = value;
        return value;
      });
    }, []);

  const fileInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);

  // What is already staged, as a persistent Set appended per drop — rebuilding
  // it from the whole list on every drop made staging a big folder O(n²).
  // Dropping the same folder twice is a slip, not a request for two copies.
  const stagedKeys = useRef<Set<string>>(new Set(heldStaged.map(keyOf)));
  const stage = (files: File[]) => {
    const fresh: File[] = [];
    for (const f of files) {
      const k = keyOf(f);
      if (stagedKeys.current.has(k)) continue;
      stagedKeys.current.add(k);
      fresh.push(f);
    }
    if (fresh.length) setStaged((prev) => [...prev, ...fresh]);
  };
  // Rows are picked with the app's list gestures (plain click replaces,
  // ⌘/Ctrl toggles, shift extends, clicking the only picked row puts it
  // down) and removed together; the per-row ✕ still takes one out alone.
  const [selKeys, setSelKeys] = useState<Set<string>>(new Set());
  const selAnchor = useRef<string | null>(null);
  const removeFiles = (files: File[]) => {
    const gone = new Set(files.map(keyOf));
    for (const k of gone) stagedKeys.current.delete(k);
    setStaged((prev) => prev.filter((x) => !gone.has(keyOf(x))));
    setSelKeys((prev) => {
      const next = new Set([...prev].filter((k) => !gone.has(k)));
      return next.size === prev.size ? prev : next;
    });
  };
  const clearStaged = () => {
    stagedKeys.current.clear();
    setStaged([]);
    setSelKeys(new Set());
    selAnchor.current = null;
  };
  // The one click rule (`shared/pickList.ts`), over the staged rows' keys.
  const pickRow = (i: number, e: React.MouseEvent) => {
    const k = keyOf(staged[i]);
    setSelKeys((prev) => {
      const r = pickNext([...prev], k, { meta: e.metaKey || e.ctrlKey, shift: e.shiftKey },
                         staged.map(keyOf), selAnchor.current);
      selAnchor.current = r.anchor;
      return new Set(r.next);
    });
  };

  // The staged list is windowed: a folder drop can stage tens of thousands of
  // rows, and only a viewport's worth mounts. Rows are a fixed height.
  const stagedScrollRef = useRef<HTMLDivElement>(null);
  const stagedWin = useWindowedList({
    count: staged.length, rowHeight: STAGED_ROW_H, scrollRef: stagedScrollRef,
    minCount: 80,
  });

  // Everything staged becomes ONE import background task (see importManager)
  // that keeps running even after this overlay is closed — so the dialog has
  // nothing left to say and closes itself. Progress belongs where it can be
  // watched while working: the task list in the left sidebar.
  const startImport = () => {
    if (ready.length === 0) return;
    addImportTask(ready, relPathOf, {
      parentId, newGroup, newGroupName,
      foldersAsGroups, archivesAsGroups, archiveSequences,
      sequenceGrouping,
      minMegapixels: num(minMp), minShortEdge: num(minShort),
      minLongEdge: num(minLong), minAspect: num(minAspect),
      maxAspect: num(maxAspect), ignoreKinds,
      detectFaces,
      indexEmbeddings,
      // Negative assignments travel with a "-" prefix, the compact spelling
      // the importer reads back.
      tagsExisting,
      tags: signedList(tags), tagsImage: signedList(tagsImage),
      tagsVideo: signedList(tagsVideo), tagsSequence: signedList(tagsSequence),
    });
    clearStaged();
    setOverlay(null);
  };

  // Closing never cancels — imports keep running as background tasks.
  const handleClose = () => setOverlay(null);

  // WHAT THIS DIALOG WOULD LOOK LIKE ON A FRESH INSTALL, which is what the
  // footer's reset offers to go back to. The toggles are remembered across
  // opens (that is the point of remembering them) and the fields are not, so
  // after a few imports it is genuinely hard to say what is still set —
  // hence a button, offered only when there IS something to undo.
  //
  // The parent group's default is the sidebar's own single selection rather
  // than "none": that is what a fresh open picks, and resetting to something
  // this dialog never starts at would be a third state.
  const defaultParent = selectedGroups.length === 1 ? selectedGroups[0] : null;
  const noTags = (v: SignedTags) => v.pos.length === 0 && v.neg.length === 0;
  const atDefaults =
    parentId === defaultParent
    && foldersAsGroups === DEFAULT_OPTS.foldersAsGroups
    && archivesAsGroups === DEFAULT_OPTS.archivesAsGroups
    && archiveSequences === DEFAULT_OPTS.archiveSequences
    && sequenceGrouping === DEFAULT_OPTS.sequenceGrouping
    && minMp === DEFAULT_OPTS.minMegapixels
    && minShort === DEFAULT_OPTS.minShortEdge
    && minLong === DEFAULT_OPTS.minLongEdge
    && minAspect === DEFAULT_OPTS.minAspect
    && maxAspect === DEFAULT_OPTS.maxAspect
    && ignoreKinds.length === 0
    && ignoreFilters.length === 0
    && newGroup === DEFAULT_OPTS.newGroup
    && newGroupName === DEFAULT_OPTS.newGroupName
    && detectFaces === DEFAULT_OPTS.detectFaces
    && indexEmbeddings === DEFAULT_OPTS.indexEmbeddings
    && tagsExisting
    && noTags(tags) && noTags(tagsImage) && noTags(tagsVideo)
    && noTags(tagsSequence);
  const resetSettings = () => {
    setParentId(defaultParent);
    setFoldersAsGroups(DEFAULT_OPTS.foldersAsGroups);
    setArchivesAsGroups(DEFAULT_OPTS.archivesAsGroups);
    setArchiveSequences(DEFAULT_OPTS.archiveSequences);
    setSequenceGrouping(DEFAULT_OPTS.sequenceGrouping);
    setMinMp(DEFAULT_OPTS.minMegapixels);
    setMinShort(DEFAULT_OPTS.minShortEdge);
    setMinLong(DEFAULT_OPTS.minLongEdge);
    setMinAspect(DEFAULT_OPTS.minAspect);
    setMaxAspect(DEFAULT_OPTS.maxAspect);
    setIgnoreKinds([]);
    setIgnoreFilters([]);
    setNewGroup(DEFAULT_OPTS.newGroup);
    setNewGroupName(DEFAULT_OPTS.newGroupName);
    setDetectFaces(DEFAULT_OPTS.detectFaces);
    setIndexEmbeddings(DEFAULT_OPTS.indexEmbeddings);
    setTagsExisting(true);
    for (const set of [setTags, setTagsImage, setTagsVideo, setTagsSequence]) {
      set(NO_TAGS);
    }
  };

  // The same run, spelled as a terminal command. The library path comes from
  // the stats query the sidebar already holds, so asking for it costs nothing.
  const { data: libStats } = useQuery({
    queryKey: ["library-stats"], queryFn: api.libraryStats,
  });
  const cli = useMemo(() => {
    const all = flattenGroupTree(tree ?? []);
    const parent = all.find((g) => g.id === parentId);
    return buildImportCommand({
      dataDir: libStats?.data_dir,
      rels: ready.map(relPathOf),
      parentGroup: parent?.name,
      parentGroupId: parent?.id ?? null,
      // `Group.name` is not unique — a library can hold "abc" inside "abc" —
      // so a name only names a group while nothing else answers to it.
      parentAmbiguous: !!parent
        && all.filter((g) => g.name === parent.name).length > 1,
      newGroup, newGroupName,
      foldersAsGroups, archivesAsGroups, archiveSequences, sequenceGrouping,
      minMegapixels: num(minMp), minShortEdge: num(minShort),
      minLongEdge: num(minLong), minAspect: num(minAspect),
      maxAspect: num(maxAspect), ignoreKinds,
      tags: signedList(tags), tagsImage: signedList(tagsImage),
      tagsVideo: signedList(tagsVideo), tagsSequence: signedList(tagsSequence),
      tagsExisting,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, tree, parentId, libStats, foldersAsGroups, archivesAsGroups,
      archiveSequences, sequenceGrouping, minMp, minShort, minLong, minAspect,
      maxAspect, ignoreKinds, tags, tagsImage, tagsVideo, tagsSequence,
      tagsExisting]);
  // What the command CANNOT carry, said out loud rather than dropped: the
  // detectors run as background jobs in the app, and the CLI has no worker to
  // run them on. A command that silently did less than the dialog it came
  // from would be the worst of both.
  const cliNote = detectFaces || indexEmbeddings
    ? t("Face detection and indexing are app-only background tasks.") : "";

  // THE LEFT COLUMN IS CAPPED TO WHAT IS VISIBLE, and the drop zone then
  // fills whatever the terminal panel under it leaves — which is what
  // `flex: 1` means and why the cap is the only thing measured.
  //
  // The cap is needed because the two columns stretch to the TALLER of them:
  // on a long options column an uncapped zone grew past the bottom of the
  // dialog and took the panel under it out of sight. The BODY's height is
  // what it should fit in, and nothing in CSS here can name that.
  //
  // MEASURING THE PANEL INSTEAD IS WHAT MADE IT JUMP: the panel grew first
  // and the zone shrank a frame later, so opening it pushed everything down
  // and yanked it back. Flexbox re-solves in the SAME pass — and on every
  // frame of the panel's own height transition — so the zone now gives up
  // exactly what the panel takes, as it takes it.
  const columnRef = useRef<HTMLDivElement>(null);
  const [columnHeight, setColumnHeight] = useState<number | null>(null);
  useEffect(() => {
    const col = columnRef.current;
    const body = col?.closest("[data-overlay-body]");
    if (!col || !body) return;
    const measure = () =>
      setColumnHeight(Math.max(220, Math.round(
        body.clientHeight - 2 * GRID_PAD)));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(body);
    return () => ro.disconnect();
  }, []);

  const onDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    setScanning(true);
    setScanCount(0);
    // THROTTLED, or the walk renders once per file: a folder of fifty
    // thousand would spend the whole scan re-rendering the dialog it is
    // trying to keep responsive. A tenth of a second is faster than anybody
    // reads a number anyway.
    let last = 0;
    try {
      stage(await filesFromDrop(e.dataTransfer, (n) => {
        const now = performance.now();
        if (now - last < 100) return;
        last = now;
        setScanCount(n);
      }));
    } finally {
      setScanning(false);
    }
  };

  const addFiles = (list: FileList | null) => {
    if (list) stage(Array.from(list));
  };

  return (
    <Overlay
      icon="upload_file"
      title={t("Import Files")}
      subtitle={t("Duplicates are skipped · archives extracted · video frames matched to images")}
      width={900}
      // FIXED at the maximum, so expanding "Tags by type" (or adding chips)
      // never resizes the dialog around the pointer.
      height="88%"
      onClose={handleClose}
      onDragOver={(e) => { e.preventDefault(); if (!dragOver) setDragOver(true); }}
      onDragLeave={(e) => {
        // The backdrop covers the whole window; only clear once the pointer has
        // actually left it (not when moving over the modal or its children).
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragOver(false);
      }}
      onDrop={onDrop}
      footer={
        <>
          {/* Far left, behind a spacer: a reset sitting beside Import is a
              misclick away from throwing the settings out on the way to
              pressing the button you meant. Shown only when there is
              something to undo, so an untouched dialog says nothing. */}
          {!atDefaults && (
            <Button variant="ghost" size="md"
       onClick={resetSettings}
       title={t("Put every setting on this screen back to its default")} style={{ marginRight: "auto" }}>
              <Icon name="restart_alt" size={16} />
              {t("Reset to defaults")}
            </Button>
          )}
        <Button variant="primary" size="md"
     onClick={startImport}
     disabled={ready.length === 0}
     title={ready.length
      ? t("Import the files below with the settings on the right")
      : t("Drop some files first")}>
          <Icon name="upload" size={16} />
          {ready.length
            ? tn({ one: "Import 1 file", other: "Import {n} files" },
                 ready.length)
            : t("Import")}
        </Button>
        </>
      }
    >
      {/* The whole window (backdrop + modal) is the drop target — the drag
          handlers live on the Overlay backdrop, so files can be dropped anywhere,
          including the dimmed area around the modal.

          Two columns: doing the thing on the left, deciding how on the right.
          One column made the options a wall between the drop zone and the files
          waiting to go, and the settings themselves are read once and then left
          alone.

          The columns STRETCH, and whichever side of the left column matters
          takes the slack: the drop zone while it is still a drop zone, the list
          of files once there are any. */}
      <div style={{
        display: "grid", gridTemplateColumns: "minmax(0, 1fr) 340px",
        alignItems: "stretch", gap: 20, padding: GRID_PAD,
        // The Overlay's content wrapper is a block scroller, not a flex
        // column, so `flex: 1` meant nothing there and the columns sat at
        // content height over a hole. 100% of the wrapper fills the fixed
        // dialog; taller content still scrolls.
        minHeight: "100%", boxSizing: "border-box", position: "relative",
      }}>
        <div
          ref={columnRef}
          style={{ minWidth: 0, minHeight: 0, display: "flex",
            flexDirection: "column", gap: COL_GAP,
            // Only with nothing staged: once there is a file list it wants
            // the room, and the dialog scrolls to it.
            height: staged.length ? undefined : (columnHeight ?? undefined) }}>
          {/* Drop zone first — the thing you actually came here to do. */}
          <div
            style={{
              // A SCAN LOOKS LIKE A DRAG STILL IN PROGRESS, deliberately: the
              // zone stays lit from the moment the pointer is over it to the
              // moment the files are staged, so the drop never reads as
              // having landed nowhere.
              border: `2px dashed ${dragOver || scanning ? "var(--accent)" : "var(--border-strong)"}`,
              borderRadius: "var(--r-7)", padding: "38px 24px",
              display: "flex", flexDirection: "column", alignItems: "center",
              justifyContent: "center", gap: 8,
              // Nothing staged yet: the drop zone is the whole point, so it
              // takes what the capped column leaves — see `columnHeight`.
              // With files staged it is back to its own size and the list
              // below takes the rest.
              flex: staged.length ? "none" : 1, minHeight: 150,
              background: dragOver || scanning ? "var(--accent-dim)" : "var(--bg)",
              textAlign: "center",
              transition: "border-color 0.12s, background 0.12s",
            }}
          >
            {/* THE ICON IS THE SIGNAL. Walking a dropped folder takes seconds
                during which nothing else on screen moves, and a headline
                swapping one line of text for another is easy to miss — which
                read as a drop that had done nothing at all. */}
            <Icon name={scanning ? "progress_activity" : "cloud_upload"} size={34}
                  color="var(--accent)"
                  spin={scanning} />
            <div style={{ fontSize: "var(--fs-4)", fontWeight: 500 }}>
              {scanning ? t("Scanning folders…")
                : ready.length ? tn({
                    one: "1 file ready — press Import when the settings are right",
                    other: "{n} files ready — press Import when the settings are right",
                  }, ready.length)
                : t("Drop files or folders to import")}
            </div>
            {/* The second line is the count while scanning — a number going up
                is the one thing nobody reads as "stuck" — and the ways in
                otherwise. Both are one line tall, so the zone holds still. */}
            <div style={{ fontSize: "var(--fs-2)", color: scanning ? "var(--accent)" : "var(--muted-2)" }}>
              {scanning ? tn({ one: "{n} file found so far",
                               other: "{n} files found so far" }, scanCount) : (
                <>
                  {t("or")}{" "}
                  <span style={{ color: "var(--accent)", cursor: "pointer" }} onClick={() => fileInput.current?.click()}>
                    {t("browse files")}
                  </span>{" "}
                  ·{" "}
                  <span style={{ color: "var(--accent)", cursor: "pointer" }} onClick={() => folderInput.current?.click()}>
                    {t("pick a folder")}
                  </span>{" "}
                  · {t("images, videos, archives")}
                </>
              )}
            </div>
            <input ref={fileInput} type="file" multiple hidden onChange={(e) => addFiles(e.target.files)} />
            <input
              ref={folderInput}
              type="file"
              hidden
              // @ts-expect-error non-standard directory attributes
              webkitdirectory=""
              directory=""
              onChange={(e) => addFiles(e.target.files)}
            />
          </div>

          {/* Above the list rather than below it: with a big drop staged the
              list is scrolled, and a line at the bottom of a thousand rows is
              one nobody meets. */}
          <CliHint command={cli.command} paths={cli.paths} note={cliNote}
                   t={t} />

          {/* As tall as its rows and no taller: three files should read as
              three files, not as a mostly-empty panel the height of the
              dialog. `0 1 auto` is the whole rule — content height while there
              is room, shrinking (and scrolling) once there is not. */}
          {staged.length > 0 && (
            <div style={{ flex: "0 1 auto", minHeight: 0, display: "flex", flexDirection: "column" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <span style={{ ...sectionLabel, marginBottom: 0 }}>{t("Files")}</span>
                <span style={{ flex: 1 }} />
                {selKeys.size > 0 && (
                  <span
                    onClick={() => removeFiles(staged.filter(
                      (f) => selKeys.has(keyOf(f))))}
                    style={{ fontSize: "var(--fs-2)", color: "var(--red)", cursor: "pointer", marginBottom: 7 }}
                  >
                    {tn({ one: "Remove 1", other: "Remove {n}" }, selKeys.size)}
                  </span>
                )}
                <span
                  onClick={clearStaged}
                  style={{ fontSize: "var(--fs-2)", color: "var(--accent)", cursor: "pointer", marginBottom: 7 }}
                >
                  {t("Clear")}
                </span>
              </div>
              <div ref={stagedScrollRef}
                style={{ ...card, flex: "0 1 auto", minHeight: 0, overflowY: "auto" }}>
                <div
                  ref={stagedWin.containerRef}
                  style={stagedWin.windowed
                    ? { height: stagedWin.totalHeight, position: "relative" }
                    : undefined}
                >
                  <div style={stagedWin.windowed
                    ? { position: "absolute", top: stagedWin.topOffset, left: 0, right: 0 }
                    : undefined}
                  >
                    {staged.slice(stagedWin.start, stagedWin.end).map((f, j) => {
                      const i = stagedWin.start + j;
                      const kind = kindOf(f.name);
                      const ok = kind.tag !== "other";
                      const picked = selKeys.has(keyOf(f));
                      return (
                        <div key={keyOf(f)} className="hoverable"
                          onMouseDown={(e) => {
                            // The ✕ keeps its click to itself.
                            if ((e.target as HTMLElement).closest(".row-action")) return;
                            pickRow(i, e);
                          }}
                          style={{ display: "flex", alignItems: "center", gap: 8,
                            padding: "6px 10px", minHeight: 28, cursor: "default",
                            userSelect: "none",
                            background: rowBackground(picked, "transparent"),
                            borderBottom: i === staged.length - 1 ? "none" : "1px solid var(--border-soft)" }}>
                          <Icon name={kind.icon} size={15}
                            color={ok ? kind.color : "var(--muted-3)"} />
                          <span style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-2)",
                            color: ok ? "var(--text-2)" : "var(--muted-3)",
                            textDecoration: ok ? undefined : "line-through",
                            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                            direction: "rtl", textAlign: "left" }}
                            title={relPathOf(f)}>
                            {relPathOf(f)}
                          </span>
                          <span style={{ flex: "0 0 auto", fontSize: "var(--fs-1)",
                            color: "var(--muted-2)", whiteSpace: "nowrap" }}>
                            {ok ? formatBytes(f.size, lang) : t("Not supported")}
                          </span>
                          <IconButton icon="close" size={20} glyph={14} reveal="hover" tone="danger"
                            onClick={() => removeFiles([f])}
                            title={t("Leave this one out")} />
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            </div>
          )}

        </div>

        {/* The options, grouped by the question each one answers: where the
            items land, what becomes a group, and what is read out of the files
            themselves. */}
        <div style={{ minWidth: 0, minHeight: 0, overflowY: "auto",
                      display: "flex", flexDirection: "column", gap: 16 }}>
          <div>
            <div style={sectionLabel}>{t("Where it goes")}</div>
            <GroupSelect tree={tree ?? []} value={parentId} onChange={setParentId}
              ungroupedLabel={t("Ungrouped")} />
            {/* A box for THIS import, inside whatever the picker names.
                Here rather than under Grouping because it modifies the
                answer directly above it: "on that shelf, in a box of its
                own". The name field is the row's `children` — the slot that
                stays legible — and it is optional, since the backend names
                an unnamed one after the moment the run started (one
                definition, so this dialog and the CLI cannot drift). Like a
                folder's group it is LAZY: a run that imports nothing leaves
                no empty box behind. */}
            <div style={{ ...card, marginTop: 8 }}>
              <OptionRow
                title={t("Put them in a new group")}
                desc={t("Made inside the group above, holding just this import.")}
                checked={newGroup}
                onToggle={() => setNewGroup((v) => !v)}
                last
              >
                {newGroup && (
                  <input
                    value={newGroupName}
                    onChange={(e) => setNewGroupName(e.target.value)}
                    onClick={(e) => e.stopPropagation()}
                    placeholder={t("Name (default: the date and time)")}
                    style={{ marginTop: 8, width: "100%", height: 28,
                             padding: "0 8px", borderRadius: "var(--r-3)",
                             background: "var(--bg-deep)", color: "var(--text)",
                             border: "1px solid var(--border)",
                             fontFamily: "inherit", fontSize: "var(--fs-3)" }}
                  />
                )}
              </OptionRow>
            </div>
          </div>

          <div>
            {/* WHAT NOT TO BRING IN. The thresholds are the Storage page's
                file-prune rule read the other way round — the same words,
                the same "0 is not set" — because "which files do I not
                want" is one question this app should not answer twice.
                They are ADDED one at a time: six rules shown at once is six
                questions asked of every import, and almost every import
                answers none of them. */}
            <div style={sectionLabel}>{t("Ignore")}</div>
            <div style={card}>
              <IgnoreRules
                rows={ignoreFilters}
                onRows={setIgnoreFilters}
                values={{ mp: minMp, short: minShort, long: minLong,
                          amin: minAspect, amax: maxAspect }}
                setValue={{ mp: setMinMp, short: setMinShort,
                            long: setMinLong, amin: setMinAspect,
                            amax: setMaxAspect }}
                kinds={ignoreKinds}
                onKinds={setIgnoreKinds}
              />
            </div>
          </div>
          <div>
            <div style={sectionLabel}>{t("Tags")}</div>
            <div style={{ ...card, padding: 10 }}>
              {/* Titled, because unlabelled it was a bare row of chips whose
                  only clue was the disclosure BELOW it saying "Tags by type"
                  — and titled in the ROWS' own type (`OptionRow`'s), not in
                  `ImportTagsField`'s small label, which belongs to the three
                  by-kind fields nested under that disclosure. */}
              <div style={{ fontSize: "var(--fs-3)", color: "var(--text-2)",
                            fontWeight: 500, marginBottom: 6 }}>
                {t("Add tags")}
              </div>
              <ImportTagsField value={tags} onChange={setTags} />
              {/* Per-kind tags, behind a disclosure: three more fields is a
                  lot of dialog for something most imports never set. */}
              <div
                onClick={() => setByKindOpen((v) => !v)}
                style={{ display: "flex", alignItems: "center", gap: 5,
                         marginTop: 8, cursor: "pointer", fontSize: "var(--fs-2)",
                         color: "var(--muted)", fontWeight: 600,
                         userSelect: "none" }}>
                <Icon name={byKindOpen ? "expand_more" : "chevron_right"}
                  size={15} />
                {t("Tags by type")}
                {!byKindOpen && (signedList(tagsImage).length
                                 + signedList(tagsVideo).length
                                 + signedList(tagsSequence).length) > 0 && (
                  <span style={{ fontWeight: 400, color: "var(--muted-2)" }}>
                    {signedList(tagsImage).length + signedList(tagsVideo).length
                     + signedList(tagsSequence).length}
                  </span>
                )}
              </div>
              {byKindOpen && (
                <div style={{ display: "flex", flexDirection: "column",
                              gap: 8, marginTop: 8 }}>
                  <ImportTagsField value={tagsImage} onChange={setTagsImage}
                    label={t("Images")} />
                  <ImportTagsField value={tagsVideo} onChange={setTagsVideo}
                    label={t("Videos")} />
                  <ImportTagsField value={tagsSequence}
                    onChange={setTagsSequence}
                    label={t("Sequences")} />
                </div>
              )}
              <div style={{ height: 1, background: "var(--border)",
                            margin: "10px -10px 0" }} />
              {/* The row escapes the card's own 10px padding on three sides,
                  so it sits flush like every OptionRow in the other cards —
                  inside the padding it left a bare band under itself. */}
              <div style={{ margin: "0 -10px -10px" }}>
                <OptionRow
                  title={t("Also tag skipped items")}
                  desc={t("A duplicate the import recognized gets the tags too.")}
                  checked={tagsExisting}
                  onToggle={() => setTagsExisting((v) => !v)}
                  last
                />
              </div>
            </div>
          </div>

          <div>
            <div style={sectionLabel}>{t("Grouping")}</div>
            <div style={card}>
              <OptionRow
                title={t("Folders become groups")}
                desc={t("Each imported folder becomes a group holding its files; nested folders become nested groups.")}
                checked={foldersAsGroups}
                onToggle={() => setFoldersAsGroups((v) => !v)}
              />
              <OptionRow
                title={t("Archives become groups")}
                desc={t("Each archive (zip, cbz, …) becomes its own group. Off: its files join whatever group the archive itself would have.")}
                checked={archivesAsGroups}
                onToggle={() => setArchivesAsGroups((v) => !v)}
              />
              <OptionRow
                title={t("Archives become sequences")}
                desc={t("Also collect an archive's images into a reading order. Comic archives (cbz/cbr) always do this regardless.")}
                checked={archiveSequences}
                onToggle={() => setArchiveSequences((v) => !v)}
              />
              {/* NOT a toggle: a book is two things at once — the item the
                  library shows and the pages inside it — and which of them
                  belongs in the groups a run makes is a choice with three
                  answers, not an on/off. */}
              <ChoiceRow
                title={t("Sequences join groups as")}
                desc={t("A comic, a PDF or an animated GIF comes in as one sequence holding the items inside it.")}
                value={sequenceGrouping}
                onChange={setSequenceGrouping}
                options={[
                  ["both", t("The sequence and its items")],
                  ["container", t("The sequence only")],
                  ["members", t("The items only")],
                ]}
                last
              />
            </div>
          </div>

          <div>
            <div style={sectionLabel}>{t("Detect")}</div>
            <div style={card}>
              {/* Detection runs afterwards, as a background job over what was
                  imported — so the import itself finishes at its own speed and
                  the detector can be cancelled from the task list. */}
              <OptionRow
                title={t("Detect faces")}
                desc={faceModels.length === 0
                  ? t("No face detector is set up yet — install one in Settings → Actions.")
                  : t("Runs face detection on every imported picture as a background task. Nobody is named; the faces wait in the Faces tab.")}
                checked={!!detectFaces}
                disabled={faceModels.length === 0}
                onToggle={() => setDetectFaces((v) => (v ? "" : faceModels[0]?.id ?? ""))}
              >
                {faceModels.length === 0 && setUpButton("faces")}
                {faceModels.length > 0 && !!detectFaces && (
                  <select
                    value={detectFaces}
                    onChange={(e) => setDetectFaces(e.target.value)}
                    onClick={(e) => e.stopPropagation()}
                    style={{
                      marginTop: 8, height: 28, padding: "0 8px", borderRadius: "var(--r-3)",
                      background: "var(--bg)", color: "var(--text)",
                      border: "1px solid var(--border-strong)",
                      fontFamily: "inherit", fontSize: "var(--fs-3)", maxWidth: "100%",
                    }}
                  >
                    {faceModels.map((m) => (
                      <option key={m.id} value={m.id}>{m.name}</option>
                    ))}
                  </select>
                )}
              </OptionRow>
              {/* Indexing on import is what saves the Tag batch chooser's
                  "Index remaining" wait later — the same after-the-import,
                  cancellable background job shape as the faces row. */}
              <OptionRow
                title={t("Index for smart ordering")}
                desc={embedModels.length === 0
                  ? t("No embedder is set up yet — install one in Settings → Actions.")
                  : t("Indexes every imported picture as a background task, so the tagging sessions can order their queue by likeness without an indexing wait. Several embedders are several runs — the spaces never mix.")}
                checked={!!indexEmbeddings}
                disabled={embedModels.length === 0}
                // Switched on, it starts with EVERY embedder that is set
                // up: the tag batch and the tag grid fuse both spaces by
                // default now, and a library indexed in one of them would
                // have the chooser asking for the other index on every
                // session. The picker below takes one back out.
                onToggle={() => setIndexEmbeddings(
                  (v) => (v ? "" : embedModels.map((m) => m.id).join(",")))}
                last
              >
                {embedModels.length === 0 && setUpButton("embed")}
                {embedModels.length > 0 && !!indexEmbeddings && (
                  <EmbedModelPicker models={embedModels} multi
                    value={indexEmbeddings} onChange={setIndexEmbeddings}
                    t={t} />
                )}
              </OptionRow>
            </div>
          </div>
        </div>
      </div>
    </Overlay>
  );
}

// Exported: the Tag batch chooser builds its options from the same three
// pieces, so the two dialogs read as the same app rather than two dialects
// of "a card of toggles".
export const sectionLabel: React.CSSProperties = { ...SECTION_LABEL, marginBottom: 7 };

/** The bordered list a group of option rows sits in — the settings overlay's
 *  panel, so the two dialogs read as the same app. */
export const card: React.CSSProperties = {
  background: "var(--panel)",
  border: "1px solid var(--border)",
  borderRadius: "var(--r-7)",
  overflow: "hidden",
};

/** WHICH FILE TYPES THE RUN LEAVES ALONE — the grid's "All media" control in
 *  the options card's terms: a button naming what is selected, and a menu of
 *  checkable rows behind it.
 *
 *  Not that component: it carries the grid's own scope toggles and its
 *  none-or-all rule ("no filter" and "every kind checked" are one state
 *  there), and here there is no "all" to collapse to — an empty selection
 *  ignores nothing, and every kind checked would import nothing at all.
 *
 *  The menu is PORTALLED (`AnchoredDropdown`), because the card it sits in is
 *  `overflow: hidden` and would otherwise clip it to a 24 px button — the
 *  FileChip's own scar, one card along. */
/** The Ignore card's contents: the rules that have been added, then the row
 *  that adds one.
 *
 *  A rule LEAVES with its value, or removing a row would keep filtering on
 *  what it said with nothing on screen saying so — the one way this control
 *  could lie. The add row disappears once every rule is on the card (a menu
 *  with nothing in it is a button that does nothing), and with no rules at
 *  all the card is that row alone, which is what says the card is a list.
 */
function IgnoreRules({ rows, onRows, values, setValue, kinds, onKinds }: {
  rows: string[];
  onRows: (next: string[]) => void;
  values: Record<string, string>;
  setValue: Record<string, (v: string) => void>;
  kinds: string[];
  onKinds: (next: string[]) => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const rect = useAnchorRect(ref, open);
  useMenuDismiss(open, () => setOpen(false), { within: [ref] });
  const has = (k: string) => rows.includes(k);
  const add = (k: string) => {
    setOpen(false);
    onRows(IGNORE_FILTERS.filter((f) => f.key === k || has(f.key))
                         .map((f) => f.key));
  };
  const remove = (k: string) => {
    onRows(rows.filter((x) => x !== k));
    if (k === "kinds") onKinds([]);
    else setValue[k]("");
  };
  const missing = IGNORE_FILTERS.filter((f) => !has(f.key));
  const shown = IGNORE_FILTERS.filter((f) => has(f.key));
  return (
    <>
      {shown.map((f, i) => {
        const last = i === shown.length - 1 && missing.length === 0;
        return f.key === "kinds" ? (
          <IgnoreKindsRow key={f.key} value={kinds} onChange={onKinds}
            onRemove={() => remove(f.key)} last={last} />
        ) : (
          <Threshold key={f.key} label={t(f.label)} unit={t(f.unit)}
            value={values[f.key]} onChange={setValue[f.key]}
            onRemove={() => remove(f.key)} last={last} />
        );
      })}
      {missing.length > 0 && (
        <div ref={ref} className="hoverable"
          onClick={() => setOpen((o) => !o)}
          style={{ display: "flex", alignItems: "center", gap: 6,
                   padding: "10px 14px", cursor: "pointer", fontSize: "var(--fs-3)",
                   color: "var(--muted)", fontWeight: 500 }}>
          <Icon name="add" size={16} />
          {t("Add a filter")}
        </div>
      )}
      {open && (
        <AnchoredDropdown rect={rect} minWidth={200}>
          {missing.map((f) => (
            <div key={f.key} className="hoverable"
              onClick={() => add(f.key)}
              style={{ display: "flex", alignItems: "center", gap: 8,
                       padding: "7px 10px", borderRadius: "var(--r-3)", cursor: "pointer",
                       fontSize: "var(--fs-3)", color: "var(--text-2)" }}>
              {t(f.label)}
              {f.unit && (
                <span style={{ marginLeft: "auto", fontSize: "var(--fs-2)",
                               color: "var(--muted-2)" }}>{t(f.unit)}</span>
              )}
            </div>
          ))}
        </AnchoredDropdown>
      )}
    </>
  );
}


function IgnoreKindsRow({ value, onChange, onRemove, last }: {
  value: string[];
  onChange: (next: string[]) => void;
  onRemove?: () => void;
  /** `Threshold`'s rule, so one card cannot draw its seams two ways: the row
   *  ABOVE owns the line, and the last row of the card draws none. Without
   *  it this row (always the last of the six) left no seam above the
   *  "Add a filter" row, which is why that row used to draw one of its own —
   *  and a seam drawn from both sides is a 2px line. */
  last?: boolean;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLButtonElement>(null);
  const rect = useAnchorRect(ref, open);
  useMenuDismiss(open, () => setOpen(false), { within: [ref] });
  const label = value.length === 0
    // The same "—" the thresholds above show for a limit nobody set.
    ? "—"
    : IGNORE_KINDS.filter((k) => value.includes(k.kind))
        .map((k) => t(k.label)).join(", ");
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 16,
                  padding: "10px 14px",
                  borderBottom: last ? "none" : "1px solid var(--border-soft)" }}>
      <div style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-3)",
                    color: "var(--text)" }}>{t("Ignored file types")}</div>
      <button
        ref={ref}
        onClick={() => setOpen((o) => !o)}
        style={{
          display: "flex", alignItems: "center", gap: 6, height: 26,
          padding: "0 8px", borderRadius: "var(--r-3)", cursor: "pointer", fontSize: "var(--fs-3)",
          maxWidth: 180, flex: "0 0 auto",
          background: "var(--bg-deep)", border: "1px solid var(--border)",
          color: value.length ? "var(--text)" : "var(--muted-2)",
        }}
      >
        <span style={{ overflow: "hidden", textOverflow: "ellipsis",
                       whiteSpace: "nowrap" }}>{label}</span>
        <Icon name="expand_more" size={16} color="var(--muted-2)" />
      </button>
      {onRemove && <RemoveRuleBtn onClick={onRemove} />}
      {open && (
        <AnchoredDropdown rect={rect} minWidth={180}>
          {IGNORE_KINDS.map((k) => {
            const on = value.includes(k.kind);
            return (
              <div
                key={k.kind}
                className="hoverable"
                onClick={() => onChange(on
                  ? value.filter((x) => x !== k.kind) : [...value, k.kind])}
                style={{
                  display: "flex", alignItems: "center", gap: 8,
                  padding: "7px 10px", borderRadius: "var(--r-3)", cursor: "pointer",
                  fontSize: "var(--fs-3)",
                  color: on ? "var(--accent)" : "var(--text-2)",
                }}
              >
                <span style={{ width: 16, display: "flex" }}>
                  {on && <Icon name="check" size={16} />}
                </span>
                <Icon name={k.icon} size={16}
                      color={on ? "var(--accent)" : "var(--muted)"} />
                {t(k.label)}
              </div>
            );
          })}
        </AnchoredDropdown>
      )}
    </div>
  );
}

/** One option: what it does on the left, a switch on the right, the whole row
 *  clickable. The switch (rather than the checkbox this dialog used to draw
 *  itself) is the settings overlay's, which is where people have already
 *  learnt what a setting looks like here.
 *
 *  `children` is for an option that needs a second control once it is on — the
 *  face detector's model picker — which belongs inside the row it qualifies. */
/** OptionRow's shape for a choice with more than two answers: the same
 *  words on the left, a `<select>` where the switch would be. Its own
 *  component rather than an OptionRow with `children`, because the control
 *  belongs BESIDE the words — a row whose answer is under its own
 *  explanation reads as a second setting. */
export function ChoiceRow({ title, desc, value, onChange, options, last }: {
  title: string;
  desc: string;
  value: string;
  onChange: (v: string) => void;
  options: readonly (readonly [string, string])[];
  last?: boolean;
}) {
  return (
    <div style={{
      padding: "12px 14px",
      borderBottom: last ? "none" : "1px solid var(--border-soft)",
    }}>
      <div style={{ fontSize: "var(--fs-3)", color: "var(--text-2)", fontWeight: 500 }}>{title}</div>
      <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", marginTop: 3, lineHeight: 1.45 }}>{desc}</div>
      {/* UNDER the words, not beside them — the same place the Detect rows
          put their model pickers. This column is 340 px wide and these
          answers are sentences; beside the text the select was two words and
          an ellipsis, with the explanation squeezed into a gutter. */}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          marginTop: 8, height: 28, padding: "0 8px", borderRadius: "var(--r-3)",
          background: "var(--bg)", color: "var(--text)",
          border: "1px solid var(--border-strong)", fontFamily: "inherit",
          fontSize: "var(--fs-3)", maxWidth: "100%",
        }}
      >
        {options.map(([v, label]) => (
          <option key={v} value={v}>{label}</option>
        ))}
      </select>
    </div>
  );
}

export function OptionRow({ title, desc, checked, onToggle, last, disabled, children }: {
  title: string;
  desc: string;
  checked: boolean;
  onToggle: () => void;
  last?: boolean;
  disabled?: boolean;
  children?: React.ReactNode;
}) {
  const [animate, setAnimate] = useState(false);
  return (
    <div
      onClick={() => { if (!disabled) { setAnimate(true); onToggle(); } }}
      style={{
        padding: "12px 14px",
        borderBottom: last ? "none" : "1px solid var(--border-soft)",
        cursor: disabled ? "default" : "pointer",
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: 14 }}>
        {/* Only the words and the switch dim on a disabled row — `children`
            stay crisp, because that is where the way OUT of the disabled
            state lives (the Tag batch chooser's "Set up in Settings →
            Models" button). Children render BELOW this line at the row's
            full width, so a trailing control in them ends at the card's own
            inset rather than a switch-column short of it. */}
        <div style={{ flex: 1, minWidth: 0, opacity: disabled ? 0.55 : 1 }}>
          <div style={{ fontSize: "var(--fs-3)", color: "var(--text-2)", fontWeight: 500 }}>{title}</div>
          <div style={{ fontSize: "var(--fs-2)", color: "var(--muted-2)", marginTop: 3, lineHeight: 1.45 }}>{desc}</div>
        </div>
        {/* An INDICATOR: the row owns the click. */}
        <Switch checked={checked} size="sm" title={title} animate={animate}
                style={{ marginTop: 1, opacity: disabled ? 0.55 : 1 }} />
      </div>
      {children}
    </div>
  );
}


/** The cheap typing-driven suggestion source (`/api/tags/names`) — the one
 *  shared definition, aliased for this file's call sites. */
const fetchImportTagSuggestions = fetchTagNameSuggestions;

/** Tags to put on what an import creates, with a SIGN apiece. */
export interface SignedTags { pos: string[]; neg: string[] }
const NO_TAGS: SignedTags = { pos: [], neg: [] };

/** `["cat", "-blurry"]` — the sign rides a "-" prefix on the wire. */
const signedList = (v: SignedTags): string[] =>
  [...v.pos, ...v.neg.map((n) => "-" + n)];

/** One import-tags field: the ordinary `CombinedTagEditor` (chips with the
 *  +/- flip and the ✕, remote suggestions), so the sign works exactly as it
 *  does everywhere else the element appears. */
/** THE SIGNED TAG-CHIPS FIELD — autocomplete in, a ✕ per chip, and a +/−
 *  flip that makes an assignment negative. Exported because the tag GRID
 *  writes the same shape for its two answers, and two fields that both mean
 *  "these tags, with these signs" must not be two components. */
export function ImportTagsField({ value, onChange, label }: {
  value: SignedTags;
  onChange: (v: SignedTags) => void;
  label?: string;
}) {
  const add = (name: string) => {
    if (!value.pos.includes(name) && !value.neg.includes(name)) {
      onChange({ ...value, pos: [...value.pos, name] });
    }
  };
  const flip = (name: string) => {
    if (value.pos.includes(name)) {
      onChange({ pos: value.pos.filter((n) => n !== name),
                 neg: [...value.neg, name] });
    } else if (value.neg.includes(name)) {
      onChange({ pos: [...value.pos, name],
                 neg: value.neg.filter((n) => n !== name) });
    }
  };
  const remove = (name: string) => onChange({
    pos: value.pos.filter((n) => n !== name),
    neg: value.neg.filter((n) => n !== name),
  });
  return (
    <div>
      {label && (
        <div style={{ fontSize: "var(--fs-1)", color: "var(--muted-2)",
                      fontWeight: 600, marginBottom: 4 }}>{label}</div>
      )}
      <CombinedTagEditor
        pos={value.pos}
        neg={value.neg}
        fetchSuggestions={fetchImportTagSuggestions}
        onAdd={add}
        onFlip={flip}
        onRemove={remove}
      />
    </div>
  );
}

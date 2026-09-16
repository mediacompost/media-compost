/** WHERE EACH MODEL ACTION BELONGS, once.
 *
 * The right sidebar's whole-view panel, the grid's context menu and the
 * group tree's menu all offer the same runs, and they used to each hold
 * their own list of which action sits under which heading. Three copies of
 * one table is three chances for a menu to disagree with the others — which
 * is what happened, and the drift was invisible until they were read side
 * by side.
 *
 * Three sections, by WHAT AN ACTION LEAVES BEHIND:
 *
 * * **Edit** — a new source file on the item (or a new item carrying it).
 * * **Detect** — something FOUND in the picture: faces, text, watermarks,
 *   panels. Nothing is rewritten; what comes back is a record to review.
 * * **Generate** — something MADE from the picture that was not in it:
 *   its tags, its caption, and the ControlNet control images.
 *
 * A SELECTION reaches most of these through the tab that shows what they
 * found instead (Generate tags at the head of the Tags tab, Detect faces at
 * the head of Subjects, and so on) — that is what a tab is for, and it is
 * the one place that can also show the answer. This table is for the two
 * places with no tabs to put them in: a context menu, and the panel that
 * acts on a whole view.
 */

export interface ActionSection {
  /** The heading. */
  label: string;
  /** Task kinds, in the order they are listed. */
  kinds: string[];
}

export const ACTION_SECTIONS: ActionSection[] = [
  { label: "Edit", kinds: ["bg_removal", "watermark_removal", "text_removal",
                           "upscale", "restore", "colorize", "descreen"] },
  { label: "Detect", kinds: ["panels", "faces", "ocr", "watermark_detect"] },
  { label: "Generate", kinds: ["tag", "caption",
                               "depth", "pose", "canny", "lineart"] },
];

/** The glyph beside each section row in the two context menus. Here rather
 *  than in a component, beside the table it names. */
export const SECTION_ICON: Record<string, string> = {
  Edit: "auto_fix_high",
  Detect: "search",
  Generate: "auto_awesome",
};

/** Kinds that take a sequence CONTAINER: the server expands one into its
 *  pages (the batch kinds), plus `panels`, which walks the pages itself.
 *  Everything else is stills only.
 *
 *  Named rather than derived from whichever section list happens to hold
 *  them — it is a fact about the SERVER, and tying it to a menu heading is
 *  what made moving an action between headings change what it runs on. */
export const SEQ_OK = new Set(["panels", "faces", "watermark_detect",
                               "tag", "ocr"]);

/** The kinds whose "already run" the SERVER can answer, so a run over a
 *  group or a whole view can leave those items out. Three record a per-item
 *  run (`ItemFaceRun`, `ItemTextRun`, and an embedding row); `caption` needs
 *  no such table because it always writes a row and the row names the model
 *  that wrote it. Named once — it was spelled out at two call sites and they
 *  drifted the moment a fourth kind could answer. */
export const SKIP_DONE_KINDS = new Set<string>(
  ["faces", "ocr", "embed", "caption"]);

/** …and the kinds that skip even over an EXPLICIT SELECTION, where "I picked
 *  these" would otherwise be the statement. Only `caption`, because only its
 *  re-run leaves a MESS: a second, nearly identical description sitting
 *  beside the first with nothing to tell them apart, which somebody then has
 *  to read and delete one of. A detector reconciles (a re-run refreshes the
 *  face it already found), an embedder overwrites its own vector, and an
 *  editor's output is a new file somebody asked for. */
export const SKIP_DONE_ALWAYS = new Set<string>(["caption"]);

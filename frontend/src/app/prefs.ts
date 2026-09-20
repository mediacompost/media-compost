// THE APP'S PERSISTED PREFERENCES, IN ONE PLACE. Every `mc.…` key the app
// writes to `localStorage` is named here with what it holds, so a key is
// never invented twice and its bounds sit beside it (`prefs.test.ts` holds
// every literal in the source to this table). The typed ones are read and
// written through `shared/storage`; the rest are still read at their
// sites through `storage.get`/`set`, listed here so the index is whole.
import { boolPref, numPref, strPref } from "../shared/storage.ts";

/** The floor a side panel may be dragged to — the library's right panel
 *  and the annotator's sidebar share it. */
export const PANEL_MIN_W = 260;

/** The Image menu's blur, in pixels of gaussian radius. Past this the picture
 *  is a wash of colour and the pad the clamped blur adds is most of the
 *  work — the slider and the stored value share the ceiling. */
export const BLUR_IMAGE_MAX = 100;

/** Sharpening's two numbers, the same way. The amount is per cent — 100 adds
 *  the detail back once over — and the radius is the SIZE of the detail being
 *  lifted, small by default because sharpening a photograph means its texture
 *  and a wide radius is a contrast control wearing sharpening's name. */
export const SHARPEN_AMOUNT = 80;
export const SHARPEN_AMOUNT_MAX = 300;
export const SHARPEN_RADIUS = 2;
export const SHARPEN_RADIUS_MAX = 20;

export const APP_PREFS = {
  sidebarWidth: numPref("mc.sidebarWidth", { def: 266, min: 198, max: 520 }),
  rightWidth: numPref("mc.rightWidth", { def: 322, min: PANEL_MIN_W, max: 560 }),
  sidebarPreviewH: numPref("mc.sidebarPreviewH", { def: 240, min: 80, max: 640 }),
  sidebarPreviewBack: numPref("mc.sidebarPreviewBack", { def: 240, min: 80, max: 640 }),
  sidebarPreviewSmall: boolPref("mc.sidebarPreviewSmall", false),
  qaHeight: numPref("mc.qaHeight", { def: 220, min: 1 }),
  qaCollapsed: boolPref("mc.qaCollapsed", false),
  foldSequenced: boolPref("mc.foldSequenced", true),
  showHiddenItems: boolPref("mc.showHiddenItems", false),
  qaEnabled: boolPref("mc.qaEnabled", true),
  qaMode: boolPref("mc.qaMode", false),
  /** WHAT THE SIDEBAR'S TAB BUTTONS CARRY: the icon and the tab's name, one
   *  or the other. It was a boolean "icons only", whose off position had no
   *  name of its own and no room for the third answer. */
  sidebarTabsShow: strPref<"both" | "icon" | "name">(
    "mc.sidebarTabsShow", "both", ["both", "icon", "name"]),
  /** The boolean it replaced, READ ONCE to carry an existing setting over —
   *  "1" is the `icon` answer. Nothing writes it any more. */
  sidebarTabsIconsOnly: boolPref("mc.sidebarTabsIconsOnly", false),
  // The tree's open branches: "0" has always meant SHUT, so these invert.
  kindsOpen: boolPref("mc.kindsOpen", true, { inverted: true }),
  pendingOpen: boolPref("mc.pendingOpen", true, { inverted: true }),
  ranksOpen: boolPref("mc.ranksOpen", true, { inverted: true }),
  quickLookInfo: boolPref("mc.quickLookInfo", false),
  // THE IMAGE EDITOR'S TOOL SETTINGS. A tolerance somebody dialled in by
  // dragging is an answer about the pictures they are working on, and the
  // whole set of them is usually one job — so they outlive the window, as
  // they do in every editor this one is modelled on. The two tolerances go
  // together because they ARE one control: the fill and the wand share a
  // gesture, a label and the drag that sets them.
  fillTolerance: numPref("mc.editor.fillTolerance", { def: 30, min: 0, max: 100 }),
  wandTolerance: numPref("mc.editor.wandTolerance", { def: 30, min: 0, max: 100 }),
  // Whole pixels, and NEGATIVE shrinks — hence a min below zero.
  wandGrow: numPref("mc.editor.wandGrow", { def: 0, min: -500, max: 500 }),
  // The Selection menu's two dialogs, remembered apart: growing by two and
  // shrinking by one are different habits, and one number would make each
  // press retype the other's.
  growSelectionPx: numPref("mc.editor.growPx", { def: 2, min: 1, max: 500 }),
  shrinkSelectionPx: numPref("mc.editor.shrinkPx", { def: 2, min: 1, max: 500 }),
  /** How far the selection's own EDGE is softened (Blur selection). */
  blurSelectionPx: numPref("mc.editor.blurSelectionPx", { def: 4, min: 1, max: 500 }),
  /** The Image menu's Blur — how far the PICTURE is softened. The panel
   *  opens on it and previews it straight away, the way every blur dialog
   *  does: the radius is the whole question, and one somebody set for these
   *  pictures is the likeliest answer for the next of them. */
  blurImagePx: numPref("mc.editor.blurImagePx", { def: 6, min: 0, max: BLUR_IMAGE_MAX }),
  /** The Image menu's Sharpen, the same way: per cent, and the size of the
   *  detail it lifts. */
  sharpenAmount: numPref("mc.editor.sharpenAmount", { def: SHARPEN_AMOUNT, min: 0, max: SHARPEN_AMOUNT_MAX }),
  sharpenRadiusPx: numPref("mc.editor.sharpenRadiusPx", { def: SHARPEN_RADIUS, min: 1, max: SHARPEN_RADIUS_MAX }),
  /** THE TOOL THE PALETTE OPENS ON. A tool is the job in hand — cropping a
   *  hundred scans, painting out a hundred logos — and the editor is opened
   *  once per picture, so starting every window on the hand tool made the
   *  first gesture of each of them be picking the tool again. The value is
   *  checked against `TOOLS` where that list lives, not by a closed list
   *  here: a tool that has been renamed away reads as the default. */
  editorTool: strPref<string>("mc.editor.tool", "hand"),
};


/** Every other app key, with what it holds — read at its site. */
export const APP_PREF_KEYS: Record<string, string> = {
  "mc.theme": "the UI theme (theme.ts)",
  "mc.editorTheme": "the item window's own theme (ThemeMenu)",
  "mc.settingsPage": "the Settings page last open",
  "mc.expandedGroups": "which sidebar groups are unfolded (JSON)",
  "mc.qaSets": "the quick-assign sets (qaSets.ts)",
  "mc.qaSelected": "which quick-assign set is picked",
  "mc.sidebarTabs": "the sidebar's open tabs (JSON)",
  "mc.sidebarTabsHidden": "the sidebar's hidden tabs (JSON)",
  "mc.sec.": "prefix: whether a sidebar section is open",
  "mc.hideNegativeTags": "the sidebar's negative-tag fold (inverted)",
  "mc.showNegativeTags": "the sidebar's negative-tag reveal (inverted)",
  "mc.panelsSeq": "extra output: the panels job makes a sequence",
  "mc.ctxLastAction": "the grid menu's last AI action (ctxLastUsed.ts)",
  "mc.importOptions": "the import dialog's settings (JSON)",
  "mc.tagExportColumns": "the tag CSV export's column order (JSON)",
  "mc.tagExportPicked": "the tag CSV export's picked columns (JSON)",
  "mc.metaTagExportColumns": "the meta-tag CSV export's column order (JSON)",
  "mc.metaTagExportPicked": "the meta-tag CSV export's picked columns (JSON)",
  "mc.tags.sidebarW": "the Tags tab's sidebar width",
  "mc.tags.collapsedNs": "the Tags list's folded namespaces (JSON)",
  "mc.tags.collapsedAliases": "the Tags list's folded alias rows (JSON)",
  "mc.faces.sidebarW": "the Faces tab's sidebar width",
  "mc.tagSort": "the tag batch's config (tagSort.ts)",
  "mc.tagSortPresets": "the tag batch's presets",
  "mc.tagSortInfo": "the tag batch's details panel",
  "mc.tagGrid": "the tag grid's config (tagGrid.ts)",
  "mc.rateRanking": "the rate session's last ranking",
  "mc.ratePools": "the rate session's last pools",
  "mc.rateSkipSequenced": "the rate session's skip-sequenced switch",
  "mc.estimate.rules": "the estimate dialog's rules per ranking (JSON)",
  "mc.recentColors": "the colour picker's recent swatches (JSON)",
  "mc.recentSubjects": "the recently named subjects (JSON)",
  "mc.textEngine": "which OCR reading is shown per item (JSON)",
  "mc.quickTagHistory": "the T field's last five lines (JSON)",
  "mc.annotatorTimelineH": "the annotator's timeline height",
  "mc.annotatorSidebarW": "the annotator's sidebar width",
  "mc.annotatorTime": "the annotator's playhead per film (JSON)",
  "mc.annotatorTab": "the annotator's open sidebar tabs (JSON)",
  "mc.annotatorTheme": "the annotator window's own theme",
  "mc.annotator.drawShape": "the annotator's box shape mode",
  "mc.annotator.subjectDraw": "the annotator's face|person outline mode",
  "mc.stillsEvery": "the every-N-seconds stills interval",
};

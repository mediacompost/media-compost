/** The pure half of the Text tab: order, flattening, grouping, geometry.
 *
 * Pure, so `node --test` can exercise it — the section and the annotator
 * only render what this decides. One derivation feeds BOTH the render and
 * the row selection's key list: two spellings of "what order are these in"
 * is a shift-range that picks a run nobody was shown (the lesson
 * `placesOnItem` and `faceGroups.ordered` both record).
 */
import type { TextRegion } from "../api";

/** One rendered row of the section — a block, or a line inside an expanded
 *  block. Word and character regions are never rows: they are BOXES (the
 *  mask's smallest unit, and the outlines the annotator draws under a picked
 *  row), and their text is the engine's reading rather than something to
 *  correct one word at a time. */
export interface RenderRow {
  region: TextRegion;
  depth: number;
  parentId: number | null;
}

/** The live top-level regions, in reading order. */
export function liveRoots(tree: TextRegion[]): TextRegion[] {
  return tree.filter((r) => !r.dismissed);
}

/** The dismissed top-level regions — the Hidden text disclosure. A dismissed
 *  CHILD is not here: it is drawn greyed in place inside its parent, because
 *  nested disclosures are the tree this design avoids. */
export function dismissedRoots(tree: TextRegion[]): TextRegion[] {
  return tree.filter((r) => r.dismissed);
}

/** Whether a region's children render as ROWS (lines) or are BOXES only
 *  (words, chars). A line is a sentence and gets a row of its own; a word is
 *  geometry. */
export function childrenAreRows(r: TextRegion): boolean {
  return r.children.some((c) => c.level === "line" || c.level === "block");
}

/** The finest boxes under a region — what the annotator outlines beneath a
 *  PICKED row, and the same leaves the removal mask is built from
 *  (`jobs._text_region_quads`, server-side). Empty when the engine gave no
 *  breakdown: there is nothing finer to show, and drawing the region's own
 *  box a second time inside itself says nothing. */
export function subBoxes(r: TextRegion): TextRegion[] {
  const out: TextRegion[] = [];
  const visit = (n: TextRegion): void => {
    for (const c of n.children) {
      if (c.dismissed) continue;
      if (c.children.length) visit(c);
      else out.push(c);
    }
  };
  visit(r);
  return out;
}

/** The rendered rows in reading order, honouring which blocks are expanded.
 *  Chip-level children are NOT rows — they live inside their parent's row —
 *  so expanding a block of words adds no rows here. */
export function flattenText(tree: TextRegion[],
                            expanded: Set<number>): RenderRow[] {
  const out: RenderRow[] = [];
  const visit = (r: TextRegion, depth: number,
                 parentId: number | null): void => {
    out.push({ region: r, depth, parentId });
    if (!expanded.has(r.id) || !childrenAreRows(r)) return;
    for (const c of r.children) {
      if (c.level === "line" || c.level === "block") visit(c, depth + 1, r.id);
    }
  };
  for (const r of tree) visit(r, 0, null);
  return out;
}

/** What a region's row shows. ONE definition, because the row, the copy
 *  action and the saved-comparison all need the same string.
 *
 *  THE REGION'S OWN TEXT WINS, at every level. A word is a BOX now, not an
 *  editable unit: its text is the engine's reading and the finer boxes exist
 *  for the inpainting mask and for showing where a picked line sits, while
 *  the correctable string is the LINE's. (The words were briefly the only
 *  editable thing here, which put a row of little fields where a sentence
 *  belongs and made correcting one line a word at a time.) Children fill in
 *  only for a region that has no text of its own — joined by a space for
 *  words, a newline for lines. */
export function regionText(r: TextRegion): string {
  if (r.text) return r.text;
  if (!r.children.length) return "";
  const sep = childrenAreRows(r) ? "\n" : " ";
  return r.children.map(regionText).filter(Boolean).join(sep);
}

export interface RegionCounts {
  lines: number;
  words: number;
  chars: number;
}

/** What the subtitle and the chevron say — how much finer structure the
 *  engine actually produced. */
export function regionCounts(r: TextRegion): RegionCounts {
  const out = { lines: 0, words: 0, chars: 0 };
  const visit = (n: TextRegion): void => {
    for (const c of n.children) {
      if (c.level === "line") out.lines += 1;
      else if (c.level === "word") out.words += 1;
      else if (c.level === "char") out.chars += 1;
      visit(c);
    }
  };
  visit(r);
  return out;
}

/** The engine a region's row files under — the FIRST model that read it
 *  (the credit order), "" for one drawn by hand. */
export function engineOf(r: TextRegion): string {
  return r.models[0] ?? "";
}

/** The engines with regions on this item, in first-seen order — what the
 *  detector dropdown offers. Hand-drawn regions belong to no engine and
 *  ride along with whichever is active. */
export function enginesOf(roots: TextRegion[]): string[] {
  const out: string[] = [];
  for (const r of roots) {
    const m = engineOf(r);
    if (m && !out.includes(m)) out.push(m);
  }
  return out;
}

export interface EngineGroup {
  /** The model id, or "" for hand-drawn regions. */
  model: string;
  regions: TextRegion[];
}

/** Top-level regions grouped by the engine that read them, in first-seen
 *  order. Two engines read one page two ways and neither clobbers the other
 *  — the display says which reading is whose. A region two engines agree on
 *  is filed under the FIRST that read it (the credit order the row's own
 *  subtitle spells out in full); hand-drawn regions group under "". One
 *  group means no headings are worth drawing — the caller checks length. */
export function groupByEngine(roots: TextRegion[]): EngineGroup[] {
  const groups: EngineGroup[] = [];
  const byModel = new Map<string, EngineGroup>();
  for (const r of roots) {
    const model = r.models[0] ?? "";
    let g = byModel.get(model);
    if (!g) {
      g = { model, regions: [] };
      byModel.set(model, g);
      groups.push(g);
    }
    g.regions.push(r);
  }
  return groups;
}

/** Point-in-quad, the annotator's hit test — `inFaceOutline`'s rule
 *  restated: a click must agree with what is DRAWN, and slanted text draws
 *  its quad, so a corner of the bounding box belonging to nothing must not
 *  select it. Ray casting; x/y and the quad share one coordinate space. */
export function inQuad(x: number, y: number,
                       quad: [number, number][]): boolean {
  if (quad.length < 3) return false;
  let inside = false;
  for (let i = 0, j = quad.length - 1; i < quad.length; j = i++) {
    const [xi, yi] = quad[i];
    const [xj, yj] = quad[j];
    if ((yi > y) !== (yj > y)
        && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

/** Whether a point is in the region's drawn shape — the quad when there is
 *  one, else the box. */
export function inRegion(x: number, y: number,
                         r: Pick<TextRegion, "x" | "y" | "w" | "h" | "quad">,
                         ): boolean {
  if (r.quad.length === 4) return inQuad(x, y, r.quad);
  return x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h;
}

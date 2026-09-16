/** THE CARD GRID — one windowed, box-selectable grid of square cards.
 *
 *  The library's grid of pictures and the Faces tab's grid of crops are the
 *  same thing: a fixed-size card per index, as many columns as the track
 *  holds, a size control, a box you can drag over them to select, and
 *  optional SECTIONS with a heading each. They were two implementations —
 *  one windowed and grouped, one a `flex-wrap` with a hard-coded 132 px card
 *  and no box selection at all — which is why the smaller one kept not
 *  having whatever the bigger one had just grown.
 *
 *  What lives here is everything that is about the GEOMETRY rather than
 *  about what a card shows: the column count (sticky, `gridGeom.columnsFor`),
 *  the window (only the rows near the viewport are mounted), the absolute
 *  layout the window needs, the marquee and its hit-testing, and the scaled
 *  spacer a million-card grid needs. The pure arithmetic is `gridGeom.ts`,
 *  unit-tested without a DOM; this is the React around it.
 *
 *  WHAT A HOST STILL OWNS: the cards themselves (`renderCard`), the
 *  selection (this only reports what a box covered), the headings' contents,
 *  and every gesture on a card — a press on a card is deliberately NOT the
 *  start of a marquee, so a card's own click, drag and paint are untouched.
 */
import React from "react";
import { SegmentedControl } from "../../shared/SegmentedControl";

import { useT } from "../i18n";
import { GRID_SIZES, type GroupLayout, type GroupRun } from "../gridGeom";
import { useCardGrid } from "./useCardGrid";

/** The S/M/L segmented control, drawn the same in every grid that has one. */
export function GridSizeControl({ size, onSize }: {
  size: number;
  onSize: (px: number) => void;
}) {
  const t = useT();
  return (
    <SegmentedControl<number>
      value={size}
      onChange={onSize}
      options={GRID_SIZES.map((g) => ({
        value: g.px, label: t(g.letter), width: 28,
        title: `${t(g.label)} ${t("thumbnails")}`,
      }))}
    />
  );
}

export interface CardGridGeom {
  columns: number;
  /** One cell's width — also the thumbnail band's height, since a card is a
   *  square thumb plus a fixed meta block. */
  cellW: number;
  rowStride: number;
  layout: GroupLayout | null;
}

export function CardGrid({
  count, size, metaH = 0, gap = 10, pad = 0,
  scrollRef, runs, headerH = 34, groupGap = 10, rowBuffer = 2,
  renderCard, renderHeader, onMarquee, onMarqueeStart, marquee = true,
  empty, style,
}: {
  /** How many cards there are, loaded or not. */
  count: number;
  /** The minimum column width — one of `GRID_SIZES`' px values. */
  size: number;
  /** A fixed block under the square thumb (name, counts): part of the card's
   *  height, and therefore of the geometry. */
  metaH?: number;
  gap?: number;
  /** Inset from the wrapper's own edges. The host's page padding is usually
   *  the better place for this; it exists because the marquee's coordinates
   *  and the column arithmetic both have to agree about it. */
  pad?: number;
  /** The scroller the grid lives in — the page's, or the grid's own. The
   *  window is computed against it, so it must be the element that actually
   *  scrolls these cards. */
  scrollRef: React.RefObject<HTMLElement | null>;
  /** Sections, as runs of the flat order. Null (the default) is one block. */
  runs?: GroupRun[] | null;
  headerH?: number;
  groupGap?: number;
  /** Rows mounted above and below the viewport. */
  rowBuffer?: number;
  renderCard: (index: number, geom: CardGridGeom) => React.ReactNode;
  renderHeader?: (run: GroupRun, section: number) => React.ReactNode;
  /** A box was dragged over these indices. `additive` is shift/⌘ held at the
   *  press — the host decides what that means for its own selection. */
  onMarquee?: (indices: number[], additive: boolean) => void;
  /** The press that begins a box, before any hit is known: where a host
   *  wants to take focus or put a menu away. */
  onMarqueeStart?: (e: React.MouseEvent) => void;
  /** False where a box selection means nothing (a list of one row). */
  marquee?: boolean;
  /** Drawn instead of the grid when there is nothing in it. */
  empty?: React.ReactNode;
  style?: React.CSSProperties;
}) {
  const grid = useCardGrid({
    count, size, metaH, gap, pad, scrollRef, runs, headerH, groupGap, rowBuffer,
    marquee, onMarquee, onMarqueeStart,
  });
  const { wrapRef, columns, cellW, rowStride, layout, win, gwin, physH, yShift, fillH, box,
          onMouseDown } = grid;

  if (count === 0 && empty) {
    return <div ref={wrapRef} style={style}>{empty}</div>;
  }

  return (
    <div ref={wrapRef} onMouseDown={onMouseDown}
         style={{ position: "relative", minHeight: fillH, ...style }}>
      <div style={{ height: physH, position: "relative" }}>
        {layout && gwin && gwin.slices.map((sl) => {
          const s = layout.sections[sl.section];
          return (
            <React.Fragment key={s.key}>
              {sl.header && renderHeader && (
                // Outside the card grid, and a HARD height: a header that
                // could wrap would change the rows the geometry counted on.
                <div style={{ position: "absolute", top: s.headerTop + yShift,
                              left: pad, right: pad, height: headerH,
                              overflow: "hidden", display: "flex",
                              alignItems: "center", gap: 8 }}>
                  {renderHeader({ key: s.key, count: s.count } as GroupRun,
                                sl.section)}
                </div>
              )}
              {sl.endIdx > sl.startIdx && (
                // ONE absolutely-positioned block PER SECTION: a single block
                // for everything would flow the next section's first card
                // into the previous section's partial last row.
                <div style={{
                  position: "absolute", top: sl.offsetTop + yShift,
                  left: pad, right: pad, display: "grid",
                  gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
                  gap, alignContent: "start" }}>
                  {Array.from({ length: sl.endIdx - sl.startIdx }, (_, k) =>
                    renderCard(sl.startIdx + k, { columns, cellW, rowStride, layout }))}
                </div>
              )}
            </React.Fragment>
          );
        })}
        {!layout && (
          <div style={{
            position: "absolute", top: win.offsetTop + yShift,
            left: pad, right: pad, display: "grid",
            // minmax(0, 1fr) — NOT plain 1fr, whose auto minimum is the
            // card's own content width: a full row could then overflow the
            // track and clip its last column.
            gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
            gap, alignContent: "start" }}>
            {Array.from({ length: Math.max(0, win.endIdx - win.startIdx) },
              (_, k) => renderCard(win.startIdx + k,
                                   { columns, cellW, rowStride, layout }))}
          </div>
        )}
        {box && (
          <div style={{
            position: "absolute", left: box.left, top: box.top + yShift,
            width: box.width, height: box.height,
            background: "var(--accent-dim)", border: "1px solid var(--accent)",
            borderRadius: 2, pointerEvents: "none", zIndex: 5 }} />
        )}
      </div>
    </div>
  );
}

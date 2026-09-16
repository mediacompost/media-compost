import React, { useEffect, useRef, useState } from "react";
import { api, ItemOut } from "../api";
import { useLang } from "../i18n";
import { compactCount } from "../format";

/** How many pictures are worth resolving for the strip. More than a row can
 *  ever hold at the field's width, so the cap never decides what is shown —
 *  the measurement below does. */
export const STRIP_MAX = 24;
const THUMB = 52;
const THUMB_GAP = 6;

/**
 * WHAT IS ABOUT TO BE TAGGED, as one row of thumbnails — shared by the two
 * full-window keyboard overlays (T's quick tag, Q's quick assign).
 *
 * It replaced a single picture with a "12 items" badge in its corner, which
 * showed one of the twelve and said the number — so the one question the strip
 * exists to answer ("which twelve?") was answered with the wrong picture.
 *
 * How many fit is MEASURED rather than assumed: the row is the field's width,
 * which is `min(90vw, 560px)` and so depends on the window. Past what fits,
 * the last tile is a **+N** — the count is exact even when the pictures cannot
 * be, which is the whole point over a view of a million items where only the
 * first page is even loaded.
 */
export function ThumbStrip({ items, total, label, size = THUMB }: {
  items: ItemOut[];
  /** How many are being tagged — not how many pictures there are to show. */
  total: number;
  label: string;
  /** Tile edge, px. The quick tag overlay passes a larger one — its strip is
   *  the only thing on screen about WHICH pictures, and at 52 px "which"
   *  was a guess. */
  size?: number;
}) {
  const lang = useLang();
  const box = useRef<HTMLDivElement>(null);
  const [fit, setFit] = useState(0);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const measure = () => {
      const w = el.clientWidth;
      setFit(Math.max(1, Math.floor((w + THUMB_GAP) / (size + THUMB_GAP))));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [size]);

  // The +N tile costs a slot, so it is only worth taking when there is
  // genuinely more than the row can hold.
  const overflow = total > items.length || items.length > fit;
  const shown = overflow ? items.slice(0, Math.max(0, fit - 1)) : items.slice(0, fit);
  const rest = total - shown.length;

  return (
    <div
      ref={box}
      style={{ width: "min(90vw, 560px)", flex: "0 0 auto", display: "flex",
        gap: THUMB_GAP, height: size, overflow: "hidden" }}
    >
      {shown.map((it) => (
        <img
          key={it.id}
          src={it.active_file_id != null
            ? api.thumbUrl(it.active_file_id, it.rotation, it.thumb_token) : ""}
          alt=""
          title={it.name}
          style={{ width: size, height: size, flex: "0 0 auto",
            objectFit: "cover", borderRadius: "var(--r-4)", background: "var(--panel-2)",
            boxShadow: "var(--shadow-2)" }}
        />
      ))}
      {overflow && rest > 0 && (
        <div
          title={`${total} ${label}`}
          style={{ width: size, height: size, flex: "0 0 auto",
            borderRadius: "var(--r-4)", background: "var(--accent)",
            color: "var(--on-accent)", display: "flex", alignItems: "center",
            justifyContent: "center", fontSize: "var(--fs-3)",
            fontWeight: 700, boxShadow: "var(--shadow-2)" }}
        >
          +{compactCount(rest, lang)}
        </div>
      )}
    </div>
  );
}

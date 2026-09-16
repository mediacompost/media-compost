/** The whole picture a text region was read from, with the region outlined.
 *
 * `FacesInPicture`'s counterpart with a different drawer: a text region is
 * drawn as a RECTANGLE (unlike a head, it really is one) — or as the
 * engine's own four-point QUAD where there is one, because an axis-aligned
 * rectangle over slanted text is a picture that lies. Several levels draw at
 * once, weighted: the region itself at 2px accent, its children as
 * hairlines, so per-word geometry is legible in the one place it can be.
 */
import React from "react";
import { api, TextRegion } from "../../api";
import { FloatingInPicture } from "./InPicture";

function Outline({ r, main }: { r: TextRegion; main: boolean }) {
  const stroke = main ? "var(--accent)" : "var(--text-3)";
  const width = main ? 2 : 1;
  if (r.quad.length === 4) {
    const points = r.quad.map(([x, y]) => `${x * 100},${y * 100}`).join(" ");
    return (
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{
        position: "absolute", inset: 0, width: "100%", height: "100%",
        overflow: "visible", pointerEvents: "none",
      }}>
        {/* The dark ring first, so a light outline stays readable on a
            white manga page — boxShadow's job on the rectangles. */}
        <polygon points={points} fill="none" style={{ stroke: "var(--scrim-3)" }}
          strokeWidth={width + 2} vectorEffect="non-scaling-stroke" />
        <polygon points={points} fill="none" stroke={stroke}
          strokeWidth={width} vectorEffect="non-scaling-stroke" />
      </svg>
    );
  }
  return (
    <div style={{
      position: "absolute",
      left: `${r.x * 100}%`, top: `${r.y * 100}%`,
      width: `${r.w * 100}%`, height: `${r.h * 100}%`,
      border: `${width}px solid ${stroke}`, borderRadius: 2,
      boxShadow: "var(--ring-shadow)", pointerEvents: "none",
    }} />
  );
}

/** The image with the region (and its children, as hairlines) outlined.
 *  Callers own the positioning. */
export function TextInPicture({ region, max = 220 }: {
  region: TextRegion;
  max?: number;
}) {
  const fileId = region.file_id;
  if (fileId == null) return null;
  return (
    <div style={{ position: "relative", lineHeight: 0 }}>
      <img src={api.thumbUrl(fileId)} alt=""
        style={{ display: "block", maxWidth: max, maxHeight: max,
                 borderRadius: "var(--r-2)" }} />
      {region.children.map((c) => <Outline key={c.id} r={c} main={false} />)}
      <Outline r={region} main />
    </div>
  );
}

export function FloatingTextInPicture({ region, rect, max = 240 }: {
  region: TextRegion | null;
  rect: DOMRect | null;
  max?: number;
}) {
  if (!region) return null;
  return (
    <FloatingInPicture rect={rect} max={max}>
      <TextInPicture region={region} max={max} />
    </FloatingInPicture>
  );
}

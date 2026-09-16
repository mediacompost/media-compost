import React from "react";
import { Icon } from "../../../shared/Icon";
import type { ZoomPan } from "../../useZoomPan";

/**
 * Bottom-right zoom cluster shared by the editor and annotator: zoom-out, the
 * live percentage, zoom-in, and a single fit ↔ actual-size toggle. Presentation
 * only — it reads and drives a `useZoomPan` model, so both windows stay in sync
 * visually without sharing their surrounding layout.
 */
/** `t` is REQUIRED — an optional translator is a silent-English hole. A
 *  deliberately-English window passes an identity. */
export function ZoomControls({ zp, t, style }: {
  zp: ZoomPan; t: (s: string) => string;
  /** Where it sits. The default is the bottom-right of the nearest
   *  positioned ancestor (the editors' canvas); Quick Look pins it to the
   *  OVERLAY's corner instead, beside its other corner buttons. */
  style?: React.CSSProperties;
}) {
  return (
    <div style={{ position: "absolute", right: 14, bottom: 12, display: "flex", alignItems: "center", gap: 2, padding: 3, background: "var(--surface-float)", border: "1px solid var(--border)", borderRadius: "var(--r-5)", boxShadow: "var(--shadow-2)", ...style }}>
      <button title={t("Zoom out")} onClick={() => zp.zoomBy(0.9)} style={zbtn}><Icon name="zoom_out" size={18} /></button>
      <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)", color: "var(--muted-2)", width: 44, textAlign: "center" }}>{zp.percent}%</span>
      <button title={t("Zoom in")} onClick={() => zp.zoomBy(1.1)} style={zbtn}><Icon name="zoom_in" size={18} /></button>
      <button
        title={zp.atActualSize ? t("Fit to screen") : t("Actual size (100%)")}
        onClick={() => (zp.atActualSize ? zp.fitToScreen() : zp.actualSize())}
        style={zbtn}
      >
        <Icon name={zp.atActualSize ? "fit_screen" : "crop_original"} size={18} />
      </button>
    </div>
  );
}

const zbtn: React.CSSProperties = {
  width: 30, height: 30, borderRadius: "var(--r-3)", border: "none", background: "transparent",
  color: "var(--text-2)", cursor: "pointer", display: "flex", alignItems: "center",
  justifyContent: "center",
};

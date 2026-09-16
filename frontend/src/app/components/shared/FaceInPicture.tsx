/** The whole picture a face was found in, with the face outlined.
 *
 * A crop says what a face looks like; only the picture says where it is, and
 * in a library of manga pages "where" is most of the answer — the same haircut
 * belongs to a different person in a different panel. Both face lists and the
 * sidebar section show this on hover rather than making it a click, because
 * the question it answers ("wait, which one is that?") comes up while the
 * pointer is already moving.
 *
 * Several faces at once is the same picture with more rectangles on it, which
 * is what a tag row wants: "where is this person here" is usually more than one
 * place.
 */
import React, { useEffect, useState } from "react";
import { IconButton } from "../../../shared/IconButton";
import { createPortal } from "react-dom";
import { api, FaceRow } from "../../api";
import { FACE_OUTLINE_RADIUS } from "../../faceOutline";
import { Icon } from "../../../shared/Icon";
import { FloatingInPicture } from "./InPicture";
import { LAYER } from "../../../shared/layers";
import { useEscape } from "../../../shared/useEscape";

/** The image with a box per face. Callers own the positioning. */
export function FacesInPicture({ faces, max = 220 }: {
  faces: FaceRow[];
  max?: number;
}) {
  // Every face of one item is in the same file, so the first one names the
  // picture; a face with no file recorded cannot be drawn on anything.
  const fileId = faces.find((f) => f.file_id != null)?.file_id ?? null;
  if (fileId == null) return null;
  return (
    <div style={{ position: "relative", lineHeight: 0 }}>
      <img src={api.thumbUrl(fileId)} alt=""
        style={{ display: "block", maxWidth: max, maxHeight: max, borderRadius: "var(--r-2)" }} />
      {faces.filter((f) => f.file_id === fileId).map((f) => (
        <div key={f.id} style={{
          position: "absolute",
          left: `${f.x * 100}%`, top: `${f.y * 100}%`,
          width: `${f.w * 100}%`, height: `${f.h * 100}%`,
          border: "2px solid var(--accent)", borderRadius: FACE_OUTLINE_RADIUS,
          // A light outline vanishes on a white manga page; the dark ring
          // either side of it keeps the rectangle readable on anything.
          boxShadow: "var(--ring-shadow)",
        }} />
      ))}
    </div>
  );
}

/** Floating beside `rect` — for a grid of crops or a row of tags, where the
 *  preview has to follow the one under the pointer rather than sit in a fixed
 *  place. The portal/placement shell is `InPicture.tsx`, shared with the
 *  text preview. */
export function FloatingFacesInPicture({ faces, rect, max = 240 }: {
  faces: FaceRow[];
  rect: DOMRect | null;
  max?: number;
}) {
  if (faces.length === 0) return null;
  return (
    <FloatingInPicture rect={rect} max={max}>
      <FacesInPicture faces={faces} max={max} />
    </FloatingInPicture>
  );
}

export function FloatingFaceInPicture({ face, rect, max = 240 }: {
  face: FaceRow;
  rect: DOMRect | null;
  max?: number;
}) {
  return <FloatingFacesInPicture faces={[face]} rect={rect} max={max} />;
}

/** The picture on its own, big, with the face outlined.
 *
 * The hover preview answers "which one is that?" while the pointer is already
 * moving; this answers "what is going on in that picture?", which is worth a
 * click and is no use at thumbnail size.
 *
 * It is NOT QuickLook, and deliberately looks exactly like it. QuickLook is
 * built around the grid: it owns the Space key, steps a multi-item selection
 * with the arrows, and previews whatever the grid has selected. Mounting it in
 * the Tags tab to show one face's picture would drag all of that into a view
 * where the grid selection means nothing — so this borrows the look (the same
 * dark blurred backdrop, the same close button, the same caption under the
 * picture) and owns nothing but the one image.
 */
export function FacePreviewOverlay({ faces, title, onClose }: {
  faces: FaceRow[];
  /** What the picture is of — shown under it, where QuickLook puts the name. */
  title: string;
  onClose: () => void;
}) {
  useEscape(onClose);
  //: WHICH FACE IS SHOWN (owner 2026-09). Handed a cluster, the preview
  //  walks it: ←/→ (and ↑/↓) step a crop at a time, each on the picture it
  //  came from, and the counter says where in the cluster you are. Handed
  //  several faces of ONE picture (a pick in the grid), stepping is the same
  //  walk — the picture stays and the ring moves.
  const [at, setAt] = useState(0);
  useEffect(() => { setAt(0); }, [faces]);
  const n = faces.length;
  const step = (d: number) => setAt((i) => (n ? (i + d + n) % n : 0));
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code === "Space") { e.preventDefault(); onClose(); return; }
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); step(1); }
      else if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); step(-1); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onClose, n]);
  const current = faces[Math.min(at, Math.max(0, n - 1))];

  const fileId = current?.file_id ?? null;
  const arrow = (d: -1 | 1) => (
    <IconButton icon={d < 0 ? "chevron_left" : "chevron_right"} size={36}
      tone="text" bordered fill="float" glyph={22}
      onMouseDown={(e) => { e.stopPropagation(); step(d); }}
      title={d < 0 ? "Previous face (←)" : "Next face (→)"}
      style={{ position: "fixed", top: "50%", marginTop: -18,
               [d < 0 ? "left" : "right"]: 16, zIndex: 1 }} />
  );
  return createPortal(
    <div data-dismiss-anywhere
      onMouseDown={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: LAYER.popover,
        background: "var(--scrim-4)", backdropFilter: "blur(6px)",
        display: "flex", flexDirection: "column", alignItems: "center",
        justifyContent: "center", padding: 40, gap: 14,
      }}
    >
      <IconButton icon="close" size={36} tone="text" bordered fill="float"
        onMouseDown={(e) => { e.stopPropagation(); onClose(); }}
        title="Close (Space or Esc)" style={{ position: "fixed", top: 16, right: 16 }} />
      <div onMouseDown={(e) => e.stopPropagation()}
        style={{ position: "relative", lineHeight: 0, maxHeight: "calc(100vh - 150px)" }}>
        {fileId != null && (
          <img src={api.fileUrl(fileId)} alt=""
            style={{ display: "block", maxWidth: "100%",
              maxHeight: "calc(100vh - 150px)", objectFit: "contain" }} />
        )}
        {/* THE CURRENT FACE RINGS IN ACCENT; the others of this walk that
            sit in the same picture ring dimmer, so a step within one
            picture reads as the ring moving. */}
        {faces.filter((f) => f.file_id === fileId).map((f) => (
          <div key={f.id} style={{
            position: "absolute",
            left: `${f.x * 100}%`, top: `${f.y * 100}%`,
            width: `${f.w * 100}%`, height: `${f.h * 100}%`,
            border: "2px solid var(--accent)", borderRadius: FACE_OUTLINE_RADIUS,
            opacity: f.id === current?.id ? 1 : 0.4,
            boxShadow: "var(--ring-shadow)", pointerEvents: "none",
          }} />
        ))}
      </div>
      {n > 1 && arrow(-1)}
      {n > 1 && arrow(1)}
      {/* Fixed light, not theme vars: it sits on the dark backdrop in both
          themes, exactly as QuickLook's caption does. */}
      <div onMouseDown={(e) => e.stopPropagation()}
        style={{ color: "var(--on-scrim)", fontSize: "var(--fs-4)", maxWidth: "100%",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          display: "flex", alignItems: "baseline", gap: 10 }}>
        <span>{title}</span>
        {n > 1 && (
          <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)",
                         color: "var(--on-scrim-3)" }}>
            {at + 1} / {n}
          </span>
        )}
      </div>
    </div>,
    document.body,
  );
}

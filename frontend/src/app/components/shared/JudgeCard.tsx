/** The session overlays' picture card, and their keycap chip.
 *
 * One card for the Rate and Tag batch overlays — the same letterbox, the
 * same transparency checker, the same playing video and sequence pager — so
 * the two sessions cannot drift into two dialects of "show me this item
 * large". What differs between them is the FOOTER (a rating card carries a
 * keycap and Not applicable, a tag card carries the item's name alone), so
 * each overlay keeps its own and wraps this.
 *
 * Rendering rules carried over verbatim from the rating card:
 * - The thumbnail card's two-layer rule at card size: a SOLID letterbox
 *   around the picture, and the checkerboard exactly behind it — the
 *   aspect-ratio wrapper already is the image's box, so the checker class
 *   rides on it and never bleeds into the letterbox.
 * - A film PLAYS — muted and looping — WITH its controls, so it can be
 *   scrubbed and unmuted; the element keeps its clicks to itself (a scrub
 *   must never answer), while the letterbox around it still picks.
 * - A sequence flips: the pager floats over the picture's bottom edge and
 *   keeps its clicks, since the card around it means "this one".
 */
import React, { useEffect, useState } from "react";
import { api, RankingItemRef } from "../../api";
import { Icon } from "../../../shared/Icon";
import { useRotate } from "./useRotate";

export function Cap({ children }: { children: React.ReactNode }) {
  return (
    <span style={{ display: "inline-block", minWidth: 18, padding: "1px 5px",
                   border: "1px solid currentColor", borderRadius: 4,
                   fontFamily: "var(--mono)", fontSize: "var(--fs-1)",
                   textAlign: "center", opacity: 0.8 }}>
      {children}
    </span>
  );
}

export function JudgeCard({ side, busy, onPick, title, onRotated }: {
  side: RankingItemRef;
  busy?: boolean;
  /** A click on the letterbox — the card's own answer. Omit for a card that
   *  is only looked at (the tag session answers from the keyboard). */
  onPick?: () => void;
  title?: string;
  /** Refresh what the session is holding after a rotation lands. Omit and
   *  the card carries no rotate buttons. */
  onRotated?: () => void;
}) {
  // A sequence card flips through its pages; the page index is per card and
  // resets with the item it is showing.
  const [page, setPage] = useState(0);
  useEffect(() => setPage(0), [side.item_id]);
  const members = side.members ?? [];
  const isSeq = side.kind === "sequence" && members.length > 0;
  const shown = isSeq
    ? members[Math.min(page, members.length - 1)] : side;
  const flip = (d: number) => setPage((p) =>
    Math.min(members.length - 1, Math.max(0, p + d)));

  /* NO ZOOM HERE. A judgement is often about a detail — is that hand drawn
   * right, is this scan sharp — and the card is a thumbnail of a page; it
   * used to zoom on the wheel and pan on a drag, its own copy of the
   * preview's model. SPACE opens the preview over the session now (owner
   * 2026-09), and the preview zooms, so the card stays a card: a click on
   * it is the answer and nothing else. */
  // TURNING THE PICTURE, from the session it is being judged in. A sideways
  // photograph is not one anybody can rate or tag, and leaving the session to
  // fix it is leaving the session. The page's OWN item is what turns inside a
  // sequence — the sideways thing is the page you are looking at.
  const [hover, setHover] = useState(false);
  const { rotate, css } = useRotate(
    onRotated ? shown.item_id : null, shown.rotation ?? 0,
    onRotated ?? (() => {}));
  const turn = (dir: "left" | "right", icon: string, label: string) => (
    <span className="hoverable" title={label}
      onClick={(e) => { e.stopPropagation(); rotate(dir); }}
      style={{ width: 30, height: 30, borderRadius: "var(--r-4)", cursor: "pointer",
               display: "flex", alignItems: "center", justifyContent: "center",
               background: "var(--overlay-chrome)", color: "var(--on-scrim)",
               border: "1px solid var(--overlay-hairline)",
               backdropFilter: "blur(3px)" }}>
      <Icon name={icon} size={17} />
    </span>
  );
  return (
    <div
      onClick={() => { if (!busy && onPick) onPick(); }}
      title={title}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{ flex: 1, minHeight: 0, display: "flex", position: "relative",
               alignItems: "center", justifyContent: "center",
               borderRadius: "var(--r-7)", border: "1px solid var(--overlay-hairline)",
               background: "var(--panel-3)",
               // A pointer over a card that refuses the click is the same
               // lie a keycap for a refused key tells — while `busy` (a
               // write in flight, or a picture ticked "not applicable")
               // there is nothing here to press.
               cursor: onPick && !busy ? "pointer" : "default",
               overflow: "hidden" }}>
      {shown.file_id != null && (
        <div className="mc-checker"
          style={{ position: "relative", maxWidth: "100%", maxHeight: "100%",
                   aspectRatio: shown.width && shown.height
                     ? `${shown.width} / ${shown.height}` : undefined }}>
          {shown.kind === "video" ? (
            <video src={api.fileUrl(shown.file_id)}
              autoPlay muted loop playsInline controls
              onClick={(e) => e.stopPropagation()}
              style={{ display: "block", width: "100%", height: "100%",
                       maxWidth: "100%", objectFit: "contain" }} />
          ) : (
            // The URL carries what the server has BAKED; `css` is the part it
            // has not caught up with yet, so the two never double up.
            <img src={api.fileUrl(shown.file_id, shown.rotation ?? 0)}
              draggable={false}
              style={{ display: "block", width: "100%", height: "100%",
                       maxWidth: "100%",
                       transform: css ? `rotate(${css}deg)` : undefined,
                       transition: "transform 0.12s ease",
                       objectFit: "contain" }} />
          )}
        </div>
      )}
      {/* ON HOVER, top-right — clear of the sequence pager at the bottom and
          of the letterbox click that answers the pair. A film is not turned
          here: its rotation is the video editor's, applied to a render. */}
      {onRotated && hover && shown.kind !== "video" && (
        <div onClick={(e) => e.stopPropagation()}
          style={{ position: "absolute", top: 10, right: 10, display: "flex",
                   gap: 6, cursor: "default" }}>
          {turn("left", "rotate_left", "Rotate left")}
          {turn("right", "rotate_right", "Rotate right")}
        </div>
      )}
      {isSeq && (
        <div onClick={(e) => e.stopPropagation()}
          style={{ position: "absolute", bottom: 10, left: "50%",
                   transform: "translateX(-50%)", display: "flex",
                   alignItems: "center", gap: 6, padding: "3px 8px",
                   borderRadius: "var(--r-4)", background: "var(--scrim-3)",
                   color: "var(--on-scrim)", fontSize: "var(--fs-3)", cursor: "default" }}>
          <span className="hoverable"
            onClick={() => flip(-1)}
            style={{ display: "flex", padding: 3, borderRadius: "var(--r-1)",
                     cursor: page > 0 ? "pointer" : "default",
                     opacity: page > 0 ? 1 : 0.35 }}>
            <Icon name="chevron_left" size={16} />
          </span>
          <span style={{ fontVariantNumeric: "tabular-nums" }}>
            {page + 1} / {members.length}
          </span>
          <span className="hoverable"
            onClick={() => flip(1)}
            style={{ display: "flex", padding: 3, borderRadius: "var(--r-1)",
                     cursor: page < members.length - 1
                       ? "pointer" : "default",
                     opacity: page < members.length - 1 ? 1 : 0.35 }}>
            <Icon name="chevron_right" size={16} />
          </span>
        </div>
      )}
    </div>
  );
}

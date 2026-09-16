// Quick-look style preview overlay for generated images (training samples /
// evaluation results). These aren't library items, so the item QuickLook
// doesn't apply — this is a lightweight lightbox with the same feel:
// Escape/backdrop closes, ←/→ (and on-screen arrows) navigate. Images that
// carry a `group` (the training samples: one group per prompt slot) also
// navigate with ↑/↓ — the same prompt at the previous/next sampled step,
// which is how you watch one prompt evolve over the run.
import React, { useEffect } from "react";
import { Icon } from "../shared/Icon";
import { useT } from "./i18n";
import { useBackdropDismiss } from "../shared/Backdrop";
import { useEscape } from "../shared/useEscape";
import { LAYER } from "../shared/layers";

export interface LightboxImage {
  url: string;
  label?: string;    // caption under the image (e.g. the prompt)
  sublabel?: string; // smaller second line (e.g. "Step 150")
  /** Same-prompt identity across steps, for ↑/↓ navigation. */
  group?: string;
}

export function Lightbox({ images, index, onIndex, onClose, footer,
                           openUrl }: {
  images: LightboxImage[];
  index: number;
  onIndex: (i: number) => void;
  onClose: () => void;
  /** Rendered under the image — the Evaluate tab's run-settings card, which
   *  used to open inline under the grid row from a tile's ⓘ and lives with
   *  the preview now: the settings are about the picture on screen. */
  footer?: React.ReactNode;
  /** The picture's own file — offered as a button beside the ✕, the
   *  library preview's shape, so the full-size image can be opened in a
   *  tab of its own. */
  openUrl?: string;
}) {
  const t = useT();
  const at = images[Math.min(index, images.length - 1)];
  // An entry with NO url is a place in the list with nothing to draw — the
  // Evaluate grid's slot for a failed or not-yet-generated picture — so the
  // arrows still reach it and only the picture stands down.
  const img = at && at.url ? at : undefined;
  const many = images.length > 1;

  // The nearest image of the same group before/after the current one — the
  // list is in timeline order (newest step first), so "up" walks toward
  // newer steps and "down" toward older ones, matching the page layout.
  const sibling = (dir: -1 | 1): number | null => {
    const g = images[index]?.group;
    if (!g) return null;
    for (let i = index + dir; i >= 0 && i < images.length; i += dir) {
      if (images[i].group === g) return i;
    }
    return null;
  };

  useEscape(onClose);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Space closes — the overlay opens quick-look style, so the quick-look
      // key dismisses it (Escape does too, through the stack). preventDefault
      // also keeps the page from scrolling behind AND stops the still-focused
      // thumbnail button from re-activating on keyup, which would reopen
      // what space closed.
      if (e.key === " " || e.code === "Space") {
        e.preventDefault();
        onClose();
      }
      else if (e.key === "ArrowRight") {
        e.preventDefault();
        onIndex(Math.min(index + 1, images.length - 1));
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        onIndex(Math.max(index - 1, 0));
      } else if (e.key === "ArrowUp" || e.key === "ArrowDown") {
        e.preventDefault();
        const to = sibling(e.key === "ArrowUp" ? -1 : 1);
        if (to != null) onIndex(to);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, images, onIndex, onClose]);

  // NO IMAGE and a footer is a preview of the card alone — a generation
  // that failed, or a picture still to come, has settings worth reading and
  // nothing to draw above them. With neither there is nothing to show.
  if (!img && !footer) return null;

  const arrow = (dir: -1 | 1, disabled: boolean) => (
    <button
      onClick={(e) => {
        e.stopPropagation();
        onIndex(Math.max(0, Math.min(index + dir, images.length - 1)));
      }}
      disabled={disabled}
      style={{
        width: 40, height: 40, borderRadius: "50%", border: "none",
        // Fixed light-on-dark: this overlay dims the page to near-black in
        // both themes, so a theme-following colour turns dark-on-dark and
        // the arrows disappear in light mode.
        background: "var(--overlay-chrome)", color: "var(--on-scrim)",
        display: "flex", alignItems: "center", justifyContent: "center",
        cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.25 : 1,
        flex: "0 0 auto",
      }}
    >
      <Icon name={dir < 0 ? "chevron_left" : "chevron_right"} size={24} />
    </button>
  );

  const backdrop = useBackdropDismiss(onClose);
  return (
    <div
      {...backdrop}
      style={{
        position: "fixed", inset: 0, zIndex: LAYER.preview,
        background: "var(--scrim-4)",
        display: "flex", alignItems: "center", justifyContent: "center",
        gap: 14, padding: 22,
      }}
    >
      {many && arrow(-1, index <= 0)}
      <div
        style={{
          display: "flex", flexDirection: "column", alignItems: "center",
          gap: 10, maxWidth: "calc(100% - 140px)", maxHeight: "100%",
          minWidth: 0,
          // With a footer the column can outgrow the window; the image
          // yields first (its own maxHeight below) and the rest scrolls.
          overflowY: footer ? "auto" : undefined,
        }}
      >
        {img && <img
          src={img.url}
          alt={img.label ?? ""}
          style={{
            maxWidth: "100%",
            maxHeight: footer ? "56vh" : "calc(100vh - 130px)",
            objectFit: "contain", borderRadius: "var(--r-7)",
            boxShadow: "var(--shadow-3)",
            background: "var(--bg-deep)",
          }}
        />}
        {/* No caption under the image while a FOOTER is there: the card
            says what the picture is (its prompt, its seed) and a line above
            it saying the same thing twice was noise. */}
        {!footer && img && (img.label || img.sublabel || images.length > 1) && (
          <div style={{ textAlign: "center", maxWidth: 640 }}>
            {img.label && (
              <div style={{ fontSize: "var(--fs-3)", color: "var(--on-scrim)", lineHeight: 1.5 }}>
                {img.label}
              </div>
            )}
            <div style={{ fontSize: "var(--fs-2)", color: "var(--on-scrim-2)", marginTop: 2 }}>
              {img.sublabel}
              {img.sublabel && images.length > 1 && " · "}
              {images.length > 1 && `${index + 1} / ${images.length}`}
              {/* The same prompt exists at other steps — say the keys exist. */}
              {(sibling(-1) != null || sibling(1) != null) &&
                ` · ${t("↑↓ same prompt, other steps")}`}
            </div>
          </div>
        )}
        {footer && (
          <div onClick={(e) => e.stopPropagation()}
            style={{ width: "min(760px, 100%)", flex: "0 0 auto" }}>
            {footer}
          </div>
        )}
      </div>
      {many && arrow(1, index >= images.length - 1)}
      {openUrl && (
        <a
          href={openUrl}
          target="_blank"
          rel="noreferrer"
          onMouseDown={(e) => e.stopPropagation()}
          title={t("Open the image in a new tab")}
          style={{
            position: "absolute", top: 16, right: 58, width: 34, height: 34,
            borderRadius: "var(--r-5)", background: "var(--overlay-chrome)",
            color: "var(--on-scrim)", display: "flex", alignItems: "center",
            justifyContent: "center", cursor: "pointer",
            textDecoration: "none",
          }}
        >
          <Icon name="open_in_new" size={18} />
        </a>
      )}
      <button
        onClick={onClose}
        style={{
          position: "absolute", top: 16, right: 16, width: 34, height: 34,
          borderRadius: "var(--r-5)", border: "none", background: "var(--overlay-chrome)",
          color: "var(--on-scrim)", display: "flex", alignItems: "center",
          justifyContent: "center", cursor: "pointer",
        }}
      >
        <Icon name="close" size={19} />
      </button>
    </div>
  );
}

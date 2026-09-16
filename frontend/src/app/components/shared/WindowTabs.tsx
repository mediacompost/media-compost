/** The tab strip the item window's halves use when several items are open.
 *
 * The image editor had one and the annotator had previous/next arrows instead,
 * which answered a different question: the arrows walk the whole grid, so the
 * two items you actually meant to compare could be forty apart, and there was
 * no way to see which ones were open. A window opened on a selection now shows
 * exactly that selection, one tab each.
 */
import React from "react";
import { IconButton } from "../../../shared/IconButton";
import { useQuery } from "@tanstack/react-query";
import { ItemDetail, api } from "../../api";
import { Icon } from "../../../shared/Icon";
import { shortTime } from "../../timecode";

/**
 * A film's tab says where it is parked (`clip.mp4@1:23`), so a window holding
 * two of them answers "which one was I in the middle of" without switching.
 *
 * Both halves of the item window build this, and they must build it the same
 * way: the tab strip is the same strip, and a suffix that appeared in one half
 * and vanished in the other reads as the window forgetting the position rather
 * than as two components disagreeing.
 */
export function filmTabSuffix(
  play: { time: number; positionFor: (src: string) => number | undefined },
  activeId: number | null,
): (id: number, detail: ItemDetail | undefined) => string | null {
  return (id, d) => {
    const f = d?.files.find((x) => x.active) ?? d?.files[0];
    if (!f || !(d?.kind === "video" || (f.duration ?? null) != null)) return null;
    const remembered = play.positionFor(api.fileUrl(f.id));
    // The ACTIVE tab reads its LIVE playhead — but only once there is one.
    // Switching between the window's halves mounts a fresh `<video>`, whose
    // time is zero until its metadata arrives and the remembered position is
    // put back, and reading that zero took the suffix off the tab for the
    // length of the load: the tab you were looking at appeared to forget where
    // the film was, at the exact moment nothing had moved.
    const at = id === activeId ? (play.time || remembered) : remembered;
    // Nothing to say about a film nobody has moved: "@0:00" on every tab is a
    // column of noise, and the beginning is where a film starts.
    return at != null && at >= 1 ? `@${shortTime(at)}` : null;
  };
}

export function WindowTabs({ ids, active, onSelect, onClose, suffix, t }: {
  ids: number[];
  active: number | null;
  onSelect: (id: number) => void;
  onClose: (id: number) => void;
  /** A quiet second half for a tab's text — the annotator puts a film's
   *  playback position there, so a window holding two of them says where each
   *  one is parked without switching to it. Takes the item's detail because
   *  the tab has already fetched it and the caller has not. */
  suffix?: (id: number, detail: ItemDetail | undefined) => string | null;
  /** REQUIRED — an optional translator is a silent-English hole. A
   *  deliberately-English window passes an identity. */
  t: (s: string) => string;
}) {
  // HIDDEN for a single tab. It was shown then too, on the argument that it is
  // where the window says which item it is on and carries the ✕ that closes
  // it — but the header says the name already (and says it better, with the
  // size and duration under it), so on a one-item window the strip was a
  // second copy of the title in a 34 px band across the top. The ✕ moved into
  // the header instead (`WindowCloseBtn`), which is what makes dropping this
  // safe: without it a lone tab would have no visible way out.
  if (ids.length <= 1) return null;
  return (
    // The bottom line is an INSET shadow, not a border: the active tab's opaque
    // background (the same colour as the header below) paints over it, so tab
    // and header merge seamlessly while the line stays under the inactive tabs
    // and the empty remainder of the bar.
    <div style={{ display: "flex", alignItems: "stretch", height: 34,
      flex: "0 0 34px", background: "var(--bg)",
      boxShadow: "inset 0 -1px 0 var(--border-soft)", overflowX: "auto" }}>
      {ids.map((id) => (
        <WindowTab key={id} id={id} active={id === active} suffix={suffix}
          onSelect={() => onSelect(id)} onClose={() => onClose(id)} t={t} />
      ))}
    </div>
  );
}

function WindowTab({ id, active, suffix, onSelect, onClose, t }: {
  id: number;
  active: boolean;
  suffix?: (id: number, detail: ItemDetail | undefined) => string | null;
  onSelect: () => void;
  onClose: () => void;
  t: (s: string) => string;
}) {
  const tr = t;
  const { data } = useQuery({
    queryKey: ["item", id], queryFn: () => api.item(id), enabled: id >= 0,
  });
  const text = data?.name ?? "…";
  const extra = suffix?.(id, data) ?? null;
  return (
    <div
      onClick={onSelect}
      title={extra ? `${text}${extra}` : text}
      style={{
        display: "flex", alignItems: "center", gap: 6, padding: "0 8px 0 12px",
        flex: "0 0 auto", cursor: "pointer",
        borderRight: "1px solid var(--border-soft)",
        background: active ? "var(--panel)" : "transparent",
        color: active ? "var(--text-bright)" : "var(--muted)",
        borderTop: `2px solid ${active ? "var(--accent)" : "transparent"}`,
      }}
    >
      <span style={{ whiteSpace: "nowrap", fontSize: "var(--fs-3)", fontFamily: "var(--mono)" }}>
        {text}
        {/* A step quieter than the name, and only on the ACTIVE tab: an
            inactive one is already drawn in the muted colour throughout, so
            dimming part of it again would say something the difference cannot
            carry. */}
        {extra && (
          <span style={{ color: active ? "var(--muted)" : undefined }}>
            {extra}
          </span>
        )}
      </span>
      <IconButton icon="close" size={18} glyph={14} reveal="hover"
        onClick={(e) => { e.stopPropagation(); onClose(); }}
        title={tr("Close tab")} />
    </div>
  );
}

import React, { useState } from "react";
import { Icon } from "../../../shared/Icon";
import { MediaTrack } from "../../api";
import { useTn } from "../../i18n";

/**
 * The media-stream (video/audio/subtitle/attachment) list shared by the tag
 * annotator's Video-file panel and the properties Info tab: one expandable
 * box per stream whose own metadata rows (dimensions, frame rate, bitrate,
 * channels, …) show below its header, with attachment streams (often dozens of
 * embedded fonts) hidden behind a reveal button.
 */
// Track metadata is reference info you'll want to copy (a codec, a language, a
// bitrate), so it is explicitly selectable even where the app disables it.
const SELECTABLE: React.CSSProperties = { userSelect: "text", WebkitUserSelect: "text", cursor: "text" };

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 8, fontSize: "var(--fs-2)", ...SELECTABLE }}>
      <span style={{ color: "var(--muted-2)" }}>{label}</span>
      <span style={{ flex: 1, textAlign: "right", fontFamily: "var(--mono)", color: "var(--text-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{value}</span>
    </div>
  );
}

function TrackBox({ track }: { track: MediaTrack }) {
  const icon = track.kind === "video" ? "movie" : track.kind === "audio" ? "graphic_eq"
    : track.kind === "subtitle" ? "subtitles" : "data_object";
  return (
    <div style={{ marginTop: 3, borderRadius: "var(--r-2)", background: "var(--panel-3)", border: "1px solid var(--border)", overflow: "hidden" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "5px 8px", ...SELECTABLE }}>
        <Icon name={icon} size={14} color="var(--muted-2)" />
        <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-0)", color: "var(--accent)", textTransform: "uppercase" }}>{track.kind}</span>
        {/* The track's name (e.g. a "Signs" subtitle) takes the lead when it has
            one; the codec falls to the right. */}
        {track.title
          ? <span style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-2)", color: "var(--text-2)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{track.title}</span>
          : <span style={{ flex: 1, fontFamily: "var(--mono)", fontSize: "var(--fs-2)", color: "var(--text-3)" }}>{track.codec}</span>}
        {track.title && <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-1)", color: "var(--muted-2)" }}>{track.codec}</span>}
        {/* Default-enabled track indicator. */}
        {track.default && (
          <span title="Enabled by default" style={{ display: "flex", color: "var(--accent)" }}>
            <Icon name="check_circle" size={13} />
          </span>
        )}
      </div>
      {track.meta.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 2, padding: "0 8px 7px" }}>
          {track.meta.map((m, i) => <Row key={i} label={m.label} value={m.value} />)}
        </div>
      )}
    </div>
  );
}

export function MediaTracksView({ tracks }: { tracks: MediaTrack[] }) {
  // Each track's metadata is always shown (no collapse). Attachment AND data
  // streams (embedded fonts, binary/metadata tracks — often several) are hidden
  // behind a reveal button.
  const [showHidden, setShowHidden] = useState(false);
  const tn = useTn();
  if (tracks.length === 0) return null;
  const isHidden = (t: MediaTrack) => t.kind === "attachment" || t.kind === "data";
  const main = tracks.filter((t) => !isHidden(t));
  const hidden = tracks.filter(isHidden);
  // Keep the familiar "attachments" wording when that's all that's hidden.
  // Whole sentences per (verb × noun): a slotted noun cannot inflect once the
  // sentence is translated.
  const allAttachments = hidden.every((t) => t.kind === "attachment");
  const toggleLabel = (n: number) => allAttachments
    ? (showHidden
        ? tn({ one: "Hide 1 attachment", other: "Hide {n} attachments" }, n)
        : tn({ one: "Show 1 attachment", other: "Show {n} attachments" }, n))
    : (showHidden
        ? tn({ one: "Hide 1 hidden track", other: "Hide {n} hidden tracks" }, n)
        : tn({ one: "Show 1 hidden track", other: "Show {n} hidden tracks" }, n));
  return (
    <div>
      {main.map((tr) => <TrackBox key={tr.index} track={tr} />)}
      {hidden.length > 0 && (
        <>
          <button
            onClick={() => setShowHidden((v) => !v)}
            style={{ marginTop: 6, fontSize: "var(--fs-2)", color: "var(--accent)", background: "transparent", border: "none", cursor: "pointer", padding: "2px 0", display: "flex", alignItems: "center", gap: 4 }}
          >
            <Icon name={showHidden ? "expand_less" : "expand_more"} size={15} />
            {toggleLabel(hidden.length)}
          </button>
          {showHidden && hidden.map((tr) => <TrackBox key={tr.index} track={tr} />)}
        </>
      )}
    </div>
  );
}

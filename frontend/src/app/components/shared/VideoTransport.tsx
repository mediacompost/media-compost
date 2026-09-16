/**
 * The video TRANSPORT — the controls under a film, and the pieces they are
 * made of.
 *
 * These lived in the annotator, which was the only window with a film in it.
 * The video editor is the second, and its controls have to be the SAME ones
 * rather than a second dialect of play/step/scrub/in/out: the two windows sit
 * over the same file, and a timecode field that behaved differently in one of
 * them would be one feature wearing two behaviours. So they moved here whole,
 * unchanged, and both windows import them.
 *
 * `TransportBar` is the row itself — jump, step, play, the current timecode,
 * and the in/out pair — with slots for what each window puts either side of
 * it.
 */
import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { MediaTrack } from "../../api";
import { Icon } from "../../../shared/Icon";
import { useAnchorRect } from "../../../shared/AnchoredDropdown";
import { LAYER } from "../../../shared/layers";
import {
  TC_SEGMENTS, formatTimecode, getSegment, parseTimecode, segmentAt,
  segmentMax, setSegment,
} from "../../timecode";
import { nextStop } from "../../videoTracks";
import { useT } from "../../i18n";
import { VideoPlayback } from "./useVideoPlayback";
import { useEscape } from "../../../shared/useEscape";
import { useMenuDismiss } from "../../../shared/useMenuDismiss";

// Video transport button (play/pause, frame step, jump, and the popover
// controls). `text` renders a short label instead of an icon; `active` marks a
// non-default setting (a changed speed, subtitles on).
export function VBtn({ icon, title, onClick, text, active, btnRef, flat }: {
  icon?: string; title: string; onClick: (e: React.MouseEvent) => void;
  text?: string; active?: boolean; btnRef?: React.Ref<HTMLButtonElement>;
  /** Borderless, for use inside the floating media bar (like the zoom cluster). */
  flat?: boolean;
}) {
  return (
    <button
      ref={btnRef}
      title={title}
      onClick={onClick}
      style={{
        width: flat ? 30 : 32, height: 30, flex: "0 0 auto", borderRadius: "var(--r-3)",
        border: flat ? "none" : `1px solid ${active ? "var(--accent)" : "var(--border-strong)"}`,
        background: flat ? "transparent" : "var(--panel-2)",
        color: active ? "var(--accent)" : "var(--text-2)",
        cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center",
      }}
    >
      {text != null
        ? <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-1)", lineHeight: 1 }}>{text}</span>
        : <Icon name={icon!} size={17} />}
    </button>
  );
}

/** A popover hanging ABOVE a transport button — the transport is the bottom
 *  edge of the window, so there is never room below. Portalled so the transport
 *  row can't clip it; closes on an outside click or Escape. */
export function TransportPopover({ anchor, open, onClose, children }: {
  anchor: React.RefObject<HTMLElement | null>;
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const rect = useAnchorRect(anchor, open);
  const panel = useRef<HTMLDivElement>(null);
  // Through the stack: opened last, the popover answers Escape before the
  // window's own bubble-phase handler, which would close the WINDOW.
  useMenuDismiss(open, onClose, { within: [panel, anchor] });
  if (!open || !rect) return null;
  return createPortal(
    <div
      ref={panel}
      style={{
        position: "fixed", bottom: window.innerHeight - rect.top + 6,
        // Aligned by the near EDGE rather than centred on the button: the media
        // bar sits in the corner, and a centred panel would hang off the side
        // of the window (its width isn't known before it renders, so there is
        // nothing to clamp a centre against).
        ...(rect.left + rect.width / 2 < window.innerWidth / 2
          ? { left: Math.max(8, rect.left) }
          : { right: Math.max(8, window.innerWidth - rect.right) }),
        zIndex: LAYER.popover,
        background: "var(--surface-float)", border: "1px solid var(--menu-border)",
        borderRadius: "var(--r-5)", padding: 4, boxShadow: "var(--shadow-3)",
        display: "flex", flexDirection: "column", alignItems: "stretch", gap: 2,
      }}
    >
      {children}
    </div>,
    document.body
  );
}

/** One row in a transport popover menu (a speed, a subtitle track). A disabled
 *  row is still listed — it says what the file holds even where the browser
 *  can't select it. */
export function PopRow({ label, selected, onClick, disabled }: {
  label: string; selected: boolean; onClick: () => void; disabled?: boolean;
}) {
  return (
    <button
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      style={{
        display: "flex", alignItems: "center", gap: 6, minWidth: 120, height: 26,
        padding: "0 7px", borderRadius: "var(--r-2)", border: "none",
        cursor: disabled ? "default" : "pointer",
        background: selected ? "var(--accent-dim)" : "transparent",
        color: disabled ? "var(--muted-3)" : selected ? "var(--accent)" : "var(--text-2)",
        fontSize: "var(--fs-2)", textAlign: "left", whiteSpace: "nowrap",
      }}
    >
      <Icon name={selected ? "check" : "remove"} size={13} color={selected ? "var(--accent)" : "transparent"} />
      <span style={{ flex: 1 }}>{label}</span>
    </button>
  );
}

/** Prev/next chevrons that walk a sorted set of moments — where the tag set
 *  changes, where a still was taken. Disabled at the ends, so the pair also
 *  says whether there is anything further that way. */
export function JumpBtns({ times, now, fps, onJump, prevTitle, nextTitle }: {
  times: number[];
  now: number;
  fps: number;
  onJump: (dir: 1 | -1) => void;
  /** The two tooltips, whole. Not a fragment slotted into a frame: the words
   *  around it move in other languages, so each direction is its own sentence
   *  (the same rule the training guide's reasons follow). */
  prevTitle: string;
  nextTitle: string;
}) {
  const t = useT();
  // The SAME question the jump asks — "is there a stop that way?" — so a lit
  // button always moves. Answering it with a looser tolerance than the jump
  // used is what left both chevrons lit on a film with a single still.
  const hasPrev = nextStop(times, now, -1, fps) != null;
  const hasNext = nextStop(times, now, 1, fps) != null;
  const btn = (dir: 1 | -1, on: boolean, icon: string) => (
    <button
      onClick={() => onJump(dir)}
      disabled={!on}
      title={dir > 0 ? nextTitle : prevTitle}
      style={{
        width: 22, height: 20, display: "flex", alignItems: "center", justifyContent: "center",
        borderRadius: "var(--r-2)", border: "1px solid var(--border-strong)", background: "transparent",
        color: on ? "var(--text-2)" : "var(--muted-3)", cursor: on ? "pointer" : "default",
        opacity: on ? 1 : 0.5,
      }}
    >
      <Icon name={icon} size={15} />
    </button>
  );
  return (
    <span style={{ display: "flex", gap: 3 }}>
      {btn(-1, hasPrev, "chevron_left")}
      {btn(1, hasNext, "chevron_right")}
    </span>
  );
}


// Monospace timecode input used for the current time and the in/out points
// (wide enough for a full SMPTE HH:MM:SS:FF).
const tcInput: React.CSSProperties = {
  width: 92, height: 28, boxSizing: "border-box", padding: "0 6px", borderRadius: "var(--r-3)",
  border: "1px solid var(--border-strong)", background: "var(--bg)", color: "var(--text-2)",
  fontFamily: "var(--mono)", fontSize: "var(--fs-2)", outline: "none", textAlign: "center",
};

/** Which timecode field a click landed on, measured rather than read back from
 *  the caret: focusing the input already forced the selection onto a field, so
 *  by the time a mouse handler runs the browser's own caret says nothing about
 *  where the pointer was. The text is centred and monospaced, so its position
 *  follows from its measured width. */
let _tcCanvas: HTMLCanvasElement | null = null;
function segmentFromClick(el: HTMLInputElement, clientX: number): number {
  const text = el.value || "00:00:00:00";
  const r = el.getBoundingClientRect();
  _tcCanvas = _tcCanvas ?? document.createElement("canvas");
  const ctx = _tcCanvas.getContext("2d");
  if (!ctx) return 0;
  const cs = getComputedStyle(el);
  ctx.font = `${cs.fontSize} ${cs.fontFamily}`;
  const w = ctx.measureText(text).width || r.width;
  const left = r.left + (r.width - w) / 2;
  const idx = Math.round(((clientX - left) / w) * text.length);
  return segmentAt(Math.max(0, Math.min(text.length, idx)));
}

/**
 * Editable SMPTE timecode field, edited **one field at a time**: clicking the
 * seconds selects the seconds, typed digits fill that field and roll into the
 * next, ↑/↓ step it and ←/→ move between them. Typing a whole timecode over a
 * free-text field meant retyping the parts you didn't want to change, and a
 * mistyped separator threw the lot away; here the value stays a valid timecode
 * at every keystroke. Enter (or leaving the field) commits, Escape reverts.
 */
export function TimecodeField({ value, fps, onCommit, title, allowNull, width }: {
  value: number | null; fps: number; onCommit: (t: number | null) => void;
  title?: string; allowNull?: boolean; width?: number;
}) {
  const [focused, setFocused] = useState(false);
  const [draft, setDraft] = useState("");
  const [seg, setSeg] = useState(0);
  const [dirty, setDirty] = useState(false);
  // Digits typed so far into the current field; a second one shifts the first
  // left ("5" then "9" → 59), and the field then advances.
  const typed = useRef("");
  const input = useRef<HTMLInputElement>(null);
  const shown = value == null ? "" : formatTimecode(value, fps);

  // Keep the browser's selection on the active field after every render — a
  // click, a keystroke and a re-render would each otherwise leave a plain caret.
  useEffect(() => {
    if (!focused || !input.current) return;
    const [a, b] = TC_SEGMENTS[seg];
    if (input.current.selectionStart !== a || input.current.selectionEnd !== b) {
      input.current.setSelectionRange(a, b);
    }
  });

  const goto = (i: number) => {
    typed.current = "";
    setSeg(Math.max(0, Math.min(TC_SEGMENTS.length - 1, i)));
  };
  const commit = () => {
    setFocused(false);
    typed.current = "";
    if (!dirty) return;               // nothing typed — leave the value (and null) alone
    const t = parseTimecode(draft, fps);
    if (t != null) onCommit(t);
  };

  return (
    <input
      ref={input}
      value={focused ? draft : shown}
      placeholder={allowNull ? "—" : "00:00:00:00"}
      title={title}
      // Read-only to the browser's own editing: every change goes through the
      // key handler below, so the text can never stop being a timecode.
      onChange={() => {}}
      onFocus={() => {
        setFocused(true);
        setDirty(false);
        setDraft(shown || formatTimecode(0, fps));
        goto(0);
      }}
      onMouseUp={(e) => goto(segmentFromClick(e.currentTarget, e.clientX))}
      onBlur={commit}
      onKeyDown={(e) => {
        const key = e.key;
        if (key === "Enter") { commit(); e.currentTarget.blur(); return; }
        if (key === "Escape") {
          setFocused(false); setDirty(false); typed.current = "";
          e.stopPropagation(); e.currentTarget.blur();
          return;
        }
        if (key === "ArrowLeft") { e.preventDefault(); goto(seg - 1); return; }
        if (key === "ArrowRight" || key === ":" || key === "." || key === "Tab") {
          if (key === "Tab" && seg === TC_SEGMENTS.length - 1) return;  // out of the field
          e.preventDefault();
          goto(seg + 1);
          return;
        }
        if (key === "ArrowUp" || key === "ArrowDown") {
          e.preventDefault();
          typed.current = "";
          const next = getSegment(draft, seg) + (key === "ArrowUp" ? 1 : -1);
          const max = segmentMax(seg, fps);
          setDraft(setSegment(draft, seg, next < 0 ? max : next > max ? 0 : next, fps));
          setDirty(true);
          return;
        }
        if (key === "Backspace" || key === "Delete") {
          e.preventDefault();
          typed.current = "";
          setDraft(setSegment(draft, seg, 0, fps));
          setDirty(true);
          return;
        }
        if (!/^[0-9]$/.test(key)) return;
        e.preventDefault();
        const digits = (typed.current + key).slice(-2);
        typed.current = digits;
        setDraft(setSegment(draft, seg, Number(digits), fps));
        setDirty(true);
        // Two digits fill a field, so move on — and a first digit that can't
        // start a valid two-digit value (a 7 in the minutes) moves on too.
        if (digits.length === 2 || Number(digits) * 10 > segmentMax(seg, fps)) {
          if (seg < TC_SEGMENTS.length - 1) goto(seg + 1); else typed.current = "";
        }
      }}
      style={{ ...tcInput, width: width ?? tcInput.width }}
    />
  );
}

/** A labelled in/out point: a "set to playhead" button plus an editable field. */
export function RangeField({ label, value, fps, onCommit, onNow, nowTitle, fieldTitle }: {
  label: string; value: number | null; fps: number;
  onCommit: (t: number | null) => void; onNow: () => void;
  /** Whole sentences, not the label slotted into a frame — the words around it
   *  move in other languages (the same rule JumpBtns follows). */
  nowTitle: string; fieldTitle: string;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
      <button onClick={onNow} title={nowTitle} style={{ height: 28, padding: "0 8px", borderRadius: "var(--r-3)", border: "1px solid var(--border-strong)", background: "var(--panel-2)", color: "var(--text-2)", cursor: "pointer", fontSize: "var(--fs-2)", fontWeight: 600 }}>{label}</button>
      <TimecodeField value={value} fps={fps} onCommit={onCommit} allowNull title={fieldTitle} />
    </div>
  );
}

// Playback speed: a square button showing the current rate, opening a menu.
export function SpeedControl({ rate, onRate }: { rate: number; onRate: (r: number) => void }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  return (
    <>
      <VBtn btnRef={btn} flat text={`${rate}×`} title={t("Playback speed")} active={rate !== 1}
        onClick={() => setOpen((v) => !v)} />
      <TransportPopover anchor={btn} open={open} onClose={() => setOpen(false)}>
        {[2, 1.5, 1, 0.75, 0.5, 0.25].map((r) => (
          <PopRow key={r} label={`${r}×`} selected={r === rate}
            onClick={() => { onRate(r); setOpen(false); }} />
        ))}
      </TransportPopover>
    </>
  );
}

// A subtitle stream's menu label: its language and/or title (e.g. "Signs").
export function subtitleLabel(tr: MediaTrack): string {
  const lang = tr.language ? tr.language.toUpperCase() : "";
  return [lang, tr.title].filter(Boolean).join(" · ") || `Track ${tr.index}`;
}

// An audio stream's menu label: its language and/or name (e.g. "German Audio").
function audioLabel(tr: MediaTrack, i: number): string {
  const lang = tr.language ? tr.language.toUpperCase() : "";
  return [lang, tr.title].filter(Boolean).join(" · ") || `Audio ${i + 1}`;
}

/** The bits of the element's `AudioTrackList` this needs (it is absent from
 *  TypeScript's DOM lib, since most engines don't implement it). */
interface AudioTrackListLike {
  length: number;
  [i: number]: { label?: string; language?: string; enabled: boolean };
}

// Subtitle on/off + track picker (extracted WebVTT) and an audio-track picker.
// Both are built from the file's OWN probed streams, so the buttons are there
// whenever the file has the tracks. Switching audio needs the browser's
// `audioTracks` API, which only Safari implements; elsewhere the menu still
// names every track — you can see what the file holds — but the ones that
// can't be reached are disabled, with a line saying why.
export function TrackControls({ videoRef, subTracks, audioTracks }: {
  videoRef: React.RefObject<HTMLVideoElement | null>;
  subTracks: MediaTrack[];
  audioTracks: MediaTrack[];
}) {
  const t = useT();
  const [activeSub, setActiveSub] = useState(-1); // -1 = off, else index into subTracks
  // What the ELEMENT exposes: empty where `audioTracks` is unimplemented.
  const [native, setNative] = useState<{ label: string; enabled: boolean }[]>([]);
  // The playing track: whichever the container marks default until switched.
  const [audioIdx, setAudioIdx] = useState(() =>
    Math.max(0, audioTracks.findIndex((t) => t.default)));

  // Read the element's own audio tracks. Safari fills that list ASYNCHRONOUSLY
  // and not necessarily by `loadedmetadata`, so the list's own addtrack/change
  // events are what this hangs on — polling `loadedmetadata` alone found it
  // empty and reported "can't switch" on a browser that can.
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const list = (v as unknown as {
      audioTracks?: AudioTrackListLike & {
        addEventListener?: (t: string, f: () => void) => void;
        removeEventListener?: (t: string, f: () => void) => void;
      };
    }).audioTracks;
    const read = () => {
      if (!list) { setNative([]); return; }
      const out: { label: string; enabled: boolean }[] = [];
      let on = -1;
      for (let i = 0; i < list.length; i++) {
        const a = list[i];
        out.push({
          label: a.label || (a.language ? a.language.toUpperCase() : `Audio ${i + 1}`),
          enabled: !!a.enabled,
        });
        if (a.enabled) on = i;
      }
      setNative(out);
      if (on >= 0) setAudioIdx(on);
    };
    read();
    v.addEventListener("loadedmetadata", read);
    list?.addEventListener?.("addtrack", read);
    list?.addEventListener?.("removetrack", read);
    list?.addEventListener?.("change", read);
    return () => {
      v.removeEventListener("loadedmetadata", read);
      list?.removeEventListener?.("addtrack", read);
      list?.removeEventListener?.("removetrack", read);
      list?.removeEventListener?.("change", read);
    };
  }, [videoRef]);

  // Switching works as soon as the element exposes more than one track. It is
  // NOT required to expose exactly as many as ffprobe found: a browser lists
  // only the tracks it can decode, and demanding a match made Safari — which
  // does support this — report the same "unsupported" note as Chromium.
  const canSwitch = native.length > 1;
  // Prefer the probed names ("German Audio", from the container's udta) and
  // fall back to the element's own labels when the two lists disagree in
  // length, since then they can't be lined up by index.
  const rows = canSwitch && native.length !== audioTracks.length
    ? native.map((n) => n.label)
    : audioTracks.map(audioLabel);

  const pickAudio = (i: number) => {
    if (!canSwitch) return;
    const at = (videoRef.current as unknown as { audioTracks?: { length: number; [j: number]: { enabled: boolean } } } | null)?.audioTracks;
    if (!at || i >= at.length) return;
    for (let j = 0; j < at.length; j++) at[j].enabled = j === i;
    setAudioIdx(i);
  };

  // Drive the <track> text tracks from the selection (they can populate a beat
  // after mount, so re-apply on `addtrack` too).
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    const apply = () => {
      const tt = v.textTracks;
      for (let i = 0; i < tt.length; i++) tt[i].mode = i === activeSub ? "showing" : "hidden";
    };
    apply();
    v.textTracks.addEventListener?.("addtrack", apply);
    return () => v.textTracks.removeEventListener?.("addtrack", apply);
  }, [activeSub, videoRef, subTracks.length]);

  if (subTracks.length === 0 && audioTracks.length <= 1) return null;
  return (
    <>
      {subTracks.length > 0 && (
        <MenuButton icon="closed_caption" title={t("Subtitles")} active={activeSub >= 0}>
          {(close) => (
            <>
              <PopRow label={t("Off")} selected={activeSub < 0} onClick={() => { setActiveSub(-1); close(); }} />
              {subTracks.map((tr, i) => (
                <PopRow key={tr.index} label={subtitleLabel(tr)} selected={i === activeSub}
                  onClick={() => { setActiveSub(i); close(); }} />
              ))}
            </>
          )}
        </MenuButton>
      )}
      {rows.length > 1 && (
        <MenuButton icon="graphic_eq" title={t("Audio track")}>
          {(close) => (
            <>
              {rows.map((label, i) => (
                <PopRow
                  key={i} label={label} selected={i === audioIdx}
                  disabled={!canSwitch && i !== audioIdx}
                  onClick={() => { pickAudio(i); close(); }}
                />
              ))}
              {!canSwitch && (
                <div style={{ padding: "5px 8px 3px", maxWidth: 210, fontSize: "var(--fs-1)", lineHeight: 1.4, color: "var(--muted-2)", borderTop: "1px solid var(--menu-border)" }}>
                  {t("This browser can't switch a video's audio track. Safari can.")}
                </div>
              )}
            </>
          )}
        </MenuButton>
      )}
    </>
  );
}

/** A square transport button whose popover holds a menu. */
export function MenuButton({ icon, title, active, children }: {
  icon: string; title: string; active?: boolean;
  children: (close: () => void) => React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const close = () => setOpen(false);
  return (
    <>
      <VBtn btnRef={btn} flat icon={icon} title={title} active={active} onClick={() => setOpen((v) => !v)} />
      <TransportPopover anchor={btn} open={open} onClose={close}>{children(close)}</TransportPopover>
    </>
  );
}

// Volume: a square button opening a vertical slider (with mute) above it.
export function VolumeControl({ muted, volume, onToggle, onVolume }: {
  muted: boolean; volume: number; onToggle: () => void; onVolume: (v: number) => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const off = muted || volume === 0;
  const icon = off ? "volume_off" : volume < 0.5 ? "volume_down" : "volume_up";
  return (
    <>
      <VBtn btnRef={btn} flat icon={icon} title={t("Volume")} active={off}
        onClick={() => setOpen((v) => !v)} />
      <TransportPopover anchor={btn} open={open} onClose={() => setOpen(false)}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6, padding: "6px 2px 2px" }}>
          <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-1)", color: "var(--muted-2)" }}>
            {Math.round((off ? 0 : volume) * 100)}
          </span>
          {/* Vertical slider: `writing-mode` is the standard way to turn a range
              input upright; the -webkit-appearance is the fallback for the
              Safari versions that predate it. */}
          <input
            type="range" min={0} max={1} step={0.02}
            value={off ? 0 : volume}
            onChange={(e) => onVolume(Number(e.target.value))}
            title={t("Volume")}
            style={{
              writingMode: "vertical-lr", direction: "rtl",
              WebkitAppearance: "slider-vertical" as React.CSSProperties["WebkitAppearance"],
              width: 22, height: 96, accentColor: "var(--accent)", cursor: "pointer",
            }}
          />
          <button
            onClick={onToggle}
            title={muted ? t("Unmute") : t("Mute")}
            style={{ width: 26, height: 24, display: "flex", alignItems: "center", justifyContent: "center", borderRadius: "var(--r-2)", border: "none", background: "transparent", color: off ? "var(--accent)" : "var(--muted-2)", cursor: "pointer" }}
          >
            <Icon name={icon} size={15} />
          </button>
        </div>
      </TransportPopover>
    </>
  );
}

/**
 * THE PLAYBACK BAR, FLOATING OVER THE PICTURE'S BOTTOM EDGE: jump, step,
 * play, and the current timecode against the duration.
 *
 * It sat in the panel under the canvas with the in/out fields at the far end
 * of the same row. Two things were wrong with that. Play, step and the
 * timecode are about the PICTURE — how it is running and where it is — which
 * is exactly what the speed, volume, subtitle and zoom clusters already float
 * over the picture to say; and being at the LEFT end of a full-width row put
 * the play button as far as it can be from the middle of the screen you are
 * watching. Centred on the bottom edge it sits between the media bar and the
 * zoom cluster, in the corner-and-centre arrangement the rest of that edge
 * already uses.
 *
 * Both windows show exactly this one, which is the point: the two sit over the
 * same file, and a transport that behaved differently in one of them would be
 * one feature wearing two behaviours.
 */
/** How much of each bottom corner belongs to something else.
 *
 *  MEASURED in the video editor: the media bar bottom-left is 70 px with its
 *  two usual buttons (speed, volume), the zoom cluster bottom-right is 148,
 *  and both sit at the canvas inset of 14.
 *
 *  **They are not equal, and an equal reserve is worse than none.** Tried
 *  first, at the larger of the two: on a 620 px window the bar then pinned at
 *  x=160 — 76 px to the RIGHT of where plain centring had put it — and so
 *  overlapped the zoom cluster by more than before. A reserve is a claim
 *  about one corner; averaging two corners is a claim about neither.
 *
 *  The left one is the soft number: the media bar grows to four buttons on a
 *  file with subtitle and audio tracks. Reserving for two is deliberate — the
 *  reserve decides where the bar STOPS sliding left, and stopping a little
 *  early costs nothing, while assuming the widest case wastes that room on
 *  every ordinary file. */
const RESERVE_LEFT = 96;
const RESERVE_RIGHT = 162;

export function PlaybackBar({ play, fps, t }: {
  play: VideoPlayback;
  fps: number;
  t: (s: string, vars?: Record<string, string | number>) => string;
}) {
  return (
    // TWO PILLS, not one: what you PRESS and what you READ are different kinds
    // of thing, and the same "one pill per group" rule the canvas bars at the
    // top follow. In one pill the timecode field read as a sixth button in a
    // row of five.
    // SPANS THE CANVAS AND CENTRES ITS CONTENT, rather than being pinned at
    // `left: 50%` and pulled back by half its own width. That looked the same
    // and was not: an absolutely positioned box with `left: 50%` and no width
    // may only be as wide as the space to its RIGHT, i.e. half the canvas —
    // so in a narrow window the two pills were laid out inside half a window
    // and the total timecode broke in two, the "/" on one line and the
    // timecode under it. (Reported exactly that way.)
    //
    // AUTO MARGINS are the other half, and they are what makes the centring
    // SAFE: a pair of `margin: auto` either side splits the leftover space
    // evenly, and when there is none left to split they resolve to zero, so
    // the pills start at the left edge instead of hanging off both. (`justify-
    // content: safe center` says the same thing in one word and is not old
    // enough to rely on; where it is unsupported the whole declaration is
    // dropped and the row silently left-aligns at every width, which is the
    // design changing on somebody else's browser.) The frame takes no pointer
    // events — it covers the whole width now, and the gap between the pills
    // would otherwise be a dead strip over the picture.
    <div
      style={{ position: "absolute", left: 0, right: 0, bottom: 12,
        zIndex: 11, pointerEvents: "none",
        // …between the two CORNER clusters it shares this edge with: the
        // media bar bottom-left, the zoom cluster bottom-right. So it is
        // centred in what is LEFT rather than in the whole canvas — the image
        // editor's properties bar was moved for exactly this reason, and an
        // overlap is the one thing neither of two floating things can notice
        // about the other. Past the point where even that space runs out the
        // auto margins collapse and the bar pins to the left reserve, using
        // the room that is there instead of sliding under the zoom controls.
        paddingLeft: RESERVE_LEFT, paddingRight: RESERVE_RIGHT,
        display: "flex", alignItems: "center", gap: 8 }}
    >
      <div
        onMouseDown={(e) => e.stopPropagation()}
        style={{ display: "flex", alignItems: "center", gap: 3, padding: 3,
        pointerEvents: "auto", marginLeft: "auto", flex: "0 0 auto",
        background: "var(--surface-float)", border: "1px solid var(--border)",
        borderRadius: "var(--r-5)", boxShadow: "var(--shadow-2)" }}>
        <VBtn flat icon="replay_5" title={t("Back 5s")} onClick={() => play.seek(play.time - 5)} />
        <VBtn flat icon="chevron_left" title={t("Previous frame")} onClick={() => play.stepFrame(-1)} />
        <VBtn flat icon={play.playing ? "pause" : "play_arrow"} title={t("Play / pause")} onClick={play.togglePlay} />
        <VBtn flat icon="chevron_right" title={t("Next frame")} onClick={() => play.stepFrame(1)} />
        <VBtn flat icon="forward_5" title={t("Forward 5s")} onClick={() => play.seek(play.time + 5)} />
      </div>
      <div
        onMouseDown={(e) => e.stopPropagation()}
        style={{ display: "flex", alignItems: "center", gap: 4,
        padding: "3px 8px 3px 3px", pointerEvents: "auto", flex: "0 0 auto",
        marginRight: "auto",
        background: "var(--surface-float)", border: "1px solid var(--border)",
        borderRadius: "var(--r-5)", boxShadow: "var(--shadow-2)" }}>
        {/* Full current timecode (HH:MM:SS:FF) — editable to seek. */}
        <TimecodeField value={play.time} fps={fps}
          onCommit={(v) => v != null && play.seek(v)}
          title={t("Current time — type a timecode to seek")} />
        {/* The slash and the duration are ONE token — a line break between
            them reads as two different numbers. */}
        <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)",
          color: "var(--muted-3)", whiteSpace: "nowrap" }}>
          / {formatTimecode(play.duration, fps)}
        </span>
      </div>
    </div>
  );
}

/**
 * THE IN/OUT PAIR that marks a range, and the ✕ that clears it.
 *
 * It stays in the panel under the picture — a marked range is what the
 * actions in that panel act on, and it belongs beside them rather than over
 * the film — and it stays in the bottom-RIGHT corner, one row further down now
 * that the playback controls have left the row above.
 */
export function RangeFields({
  play, fps, inPoint, outPoint, onIn, onOut, onClear, t,
}: {
  play: VideoPlayback;
  fps: number;
  inPoint: number | null;
  outPoint: number | null;
  onIn: (t: number | null) => void;
  onOut: (t: number | null) => void;
  onClear: () => void;
  t: (s: string, vars?: Record<string, string | number>) => string;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6,
      flex: "0 0 auto" }}>
      <RangeField label={t("In")} value={inPoint} fps={fps}
        onCommit={onIn} onNow={() => onIn(play.nowTime())}
        nowTitle={t("Set the in point to the current time")}
        fieldTitle={t("In point — type a timecode")} />
      <RangeField label={t("Out")} value={outPoint} fps={fps}
        onCommit={onOut} onNow={() => onOut(play.nowTime())}
        nowTitle={t("Set the out point to the current time")}
        fieldTitle={t("Out point — type a timecode")} />
      {(inPoint != null || outPoint != null) && (
        <VBtn icon="close" title={t("Clear range")} onClick={onClear} />
      )}
    </div>
  );
}

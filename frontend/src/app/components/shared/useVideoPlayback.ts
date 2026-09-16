import { useEffect, useRef, useState } from "react";

import { VideoPositions } from "../../videoPosition";

/**
 * Video playback state + controls shared by the video editor and the tag
 * annotator: play/pause, seek, and frame-by-frame stepping via the file's frame
 * rate. Attach `videoRef` to a `<video>`; the hook mirrors its time/duration and
 * play state into React so the UI (timeline, controls) can render from them.
 */
export interface VideoPlayback {
  videoRef: React.RefObject<HTMLVideoElement>;
  /** Current playback time (seconds), mirrored from the element. */
  time: number;
  /** Duration (seconds) — falls back to `fallbackDuration` until metadata loads. */
  duration: number;
  playing: boolean;
  /** Live time straight off the element (state lags a programmatic seek a tick). */
  nowTime: () => number;
  seek: (t: number) => void;
  /** Step `dir` frames (±1) — pauses first, then seeks by 1/fps. */
  stepFrame: (dir: number) => void;
  togglePlay: () => void;
  /** J / L — the SHUTTLE. `dir` is -1 (back) or 1 (forward): pressing it in
   *  the direction already running doubles the speed, pressing the other
   *  direction starts again at 1x that way. `shuttleRate` is the signed
   *  multiplier, 0 while nothing is shuttling.
   *
   *  Forward is ordinary playback at a raised `playbackRate`. BACKWARD is
   *  not: no browser implements a negative `playbackRate`, so it is driven
   *  by seeking the element back a frame's worth of time per animation
   *  frame — which is what every web player does and what makes J an
   *  approximation of an NLE's reverse shuttle rather than the thing itself
   *  (there is no audio, and the smoothness is the decoder's seek). */
  shuttle: (dir: number) => void;
  shuttleRate: number;
  /** Playback speed multiplier (1 = normal). */
  rate: number;
  setRate: (r: number) => void;
  /** Volume 0..1 and mute state (mirrored to the element). */
  volume: number;
  setVolume: (v: number) => void;
  muted: boolean;
  toggleMuted: () => void;
  /** True when the <video> failed to load/decode (unsupported format/codec). */
  error: boolean;
  /** Where a source was last left, for a caller that has to say something
   *  about a film that is NOT the one on screen — the annotator's tab strip
   *  puts each film's position in its tab. `src` is the same URL the element
   *  would load; undefined for one never shown in this window. */
  positionFor: (src: string) => number | undefined;
}

/**
 * WHERE EACH FILM WAS LEFT, per WINDOW rather than per hook.
 *
 * It was a `useRef(new VideoPositions())`, which is one memory per mounted
 * hook — fine while one window meant one of them, and wrong the moment the
 * item window grew two halves: switching between Annotate and Edit unmounts
 * one overlay and mounts the other, so the hook holding the position went with
 * it and the film restarted from the beginning. Nothing about a playhead is a
 * fact about which half you are looking through.
 *
 * A module-level singleton is exactly the scope that is right here: a browser
 * window is one document is one module instance, and the two halves never
 * render at once, so there is no second reader to race. (`pos.key` — which
 * source the current position is about — is per ELEMENT, and every mount
 * re-establishes it from the element it binds to; see the bind effect.)
 */
const positions = { current: new VideoPositions() };

export function useVideoPlayback(fps: number, fallbackDuration = 0): VideoPlayback {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState(false);
  const [rate, setRateState] = useState(1);
  const [volume, setVolumeState] = useState(1);
  const [muted, setMuted] = useState(false);
  const dur = duration || fallbackDuration;

  // The element the listeners are currently on, and how to take them off again.
  const bound = useRef<HTMLVideoElement | null>(null);
  const detach = useRef<(() => void) | null>(null);

  // The latest rate/volume/mute, readable from listeners that outlive the
  // render that attached them. The HTML load algorithm resets playbackRate to
  // defaultPlaybackRate on every new source, and a replaced <video> starts at
  // the defaults — so a state-deps effect alone never re-applied them (its
  // deps don't change when the element or its src does): 0.5× silently played
  // at 1× after a tab switch while the control still read 0.5×.
  const av = useRef({ rate, volume, muted });
  av.current = { rate, volume, muted };
  const applyAv = (v: HTMLVideoElement) => {
    v.playbackRate = av.current.rate;
    v.volume = av.current.volume;
    v.muted = av.current.muted;
  };

  // WHERE EACH SOURCE WAS LEFT, so coming back to a video resumes instead of
  // restarting. The element is UNMOUNTED whenever the window is showing
  // something else — the annotator renders a `<video>` only while the active
  // tab is a film — and a fresh one starts at zero, so returning to a tab
  // threw away the position along with the element. The same class of thing
  // the rate/volume note above describes, and the same answer: remember it
  // here and put it back when an element appears.
  //
  // The rule lives in `videoPosition.ts` because it is subtle and pure: which
  // source a reported position BELONGS to is not always the one the element
  // currently names, and getting that wrong silently loses the position (see
  // the class's own note). Here it is only wired to the events.
  const pos = positions;
  const srcOf = (v: HTMLVideoElement) => v.currentSrc || v.src || "";
  const mark = (v: HTMLVideoElement) => pos.current.record(v.currentTime);

  const attach = (v: HTMLVideoElement) => {
    const onTime = () => { setTime(v.currentTime); mark(v); };
    // `timeupdate` fires about four times a second, so a switch made between
    // two of them would remember a stale moment; a seek is exactly when
    // somebody has just chosen where they are.
    const onSeeked = () => mark(v);
    const onMeta = () => setDuration(v.duration);
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    // The element errors when it can't fetch/decode the source; some browsers
    // instead just never produce a video track, so treat "metadata loaded but
    // zero dimensions" as an error too.
    const onError = () => setError(true);
    const onLoaded = () => {
      onMeta();
      if (v.videoWidth === 0 && v.videoHeight === 0) setError(true);
      else setError(false);
      applyAv(v);
      // From here the position means something, and it means it about THIS
      // source.
      pos.current.loaded(srcOf(v));
      // Back where it was left. Here rather than at mount, because seeking
      // needs the duration — before `loadedmetadata` an assignment to
      // `currentTime` on a fresh element has nothing to seek within.
      const to = pos.current.resumeTo(srcOf(v), v.currentTime, v.duration);
      if (to != null) {
        v.currentTime = to;
        setTime(to);
      }
    };
    // Clear any previous failure when a new source starts loading (navigation)
    // — and push the playback settings back, since the load reset them. The
    // position stops belonging to anything until the new metadata says so.
    const onLoadStart = () => { pos.current.detached(); setError(false); applyAv(v); };
    // Same, one step earlier: `emptied` is the element being reset, and on some
    // paths it is what fires first.
    const onEmptied = () => pos.current.detached();
    v.addEventListener("timeupdate", onTime);
    v.addEventListener("seeked", onSeeked);
    v.addEventListener("loadedmetadata", onLoaded);
    v.addEventListener("loadstart", onLoadStart);
    v.addEventListener("emptied", onEmptied);
    v.addEventListener("play", onPlay);
    v.addEventListener("pause", onPause);
    v.addEventListener("error", onError);
    // If it's already errored by the time we attach (fast local failure), catch it.
    if (v.error) setError(true);
    return () => {
      // The last chance to see where it was: this runs while the element is
      // still there, and it is about to go (a tab switch unmounts it).
      mark(v);
      v.removeEventListener("timeupdate", onTime);
      v.removeEventListener("seeked", onSeeked);
      v.removeEventListener("loadedmetadata", onLoaded);
      v.removeEventListener("loadstart", onLoadStart);
      v.removeEventListener("emptied", onEmptied);
      v.removeEventListener("play", onPlay);
      v.removeEventListener("pause", onPause);
      v.removeEventListener("error", onError);
    };
  };

  // Bind on EVERY render, not once on mount: the <video> usually mounts later
  // than this hook (the annotator renders it only once the item detail has
  // loaded), so a mount-only effect would find a null ref and attach its
  // listeners to nothing — the play/pause icon and the time readout then never
  // moved while the video played. Cheap: it returns straight away unless the
  // element identity actually changed.
  useEffect(() => {
    const v = videoRef.current;
    if (v === bound.current) return;
    detach.current?.();
    bound.current = v;
    // A DIFFERENT element's position is not this one's — a fresh `<video>` has
    // loaded nothing, so until its metadata arrives there is no source its
    // `currentTime` is about. (The detach above has already banked the old
    // one's, which is what makes coming back to it resume.)
    if (v && v.readyState >= 1) pos.current.loaded(srcOf(v));
    else pos.current.detached();
    detach.current = v ? attach(v) : null;
    if (v) {
      // Adopt whatever state the element is already in (it may have loaded, or
      // even started playing, before we got here) — and push OUR settings onto
      // it: a freshly mounted element is at the defaults, whatever the
      // controls say.
      //
      // A element with NO metadata yet is at zero because it has not loaded,
      // not because that is where playback is: the position it will resume to
      // is the remembered one, and reading the raw zero here dropped the
      // timecode, the "At this frame" list and the stills list back to the
      // first frame for the moment before `loadedmetadata` arrived.
      const pending = v.readyState === 0 ? pos.current.recall(srcOf(v)) : undefined;
      setTime(pending ?? v.currentTime);
      setPlaying(!v.paused);
      if (v.readyState >= 1) setDuration(v.duration);
      applyAv(v);
    }
  });
  useEffect(() => () => { detach.current?.(); detach.current = null; }, []);

  // `timeupdate` fires only about four times a second — far too coarse for a
  // playhead and a frame-accurate timecode — so the time is read per frame
  // while playing. (setTime with an unchanged value is a no-op in React.)
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    const tick = () => {
      const v = videoRef.current;
      if (v) setTime(v.currentTime);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  const nowTime = () => videoRef.current?.currentTime ?? time;
  const seek = (t: number) => {
    const v = videoRef.current;
    if (!v) return;
    const clamped = Math.max(0, Math.min(dur || v.duration || 0, t));
    v.currentTime = clamped;
    setTime(clamped);
  };
  // ---- the J / L shuttle ---------------------------------------------------
  // `shuttleRate` is signed; the ref is what the rAF loop reads, since that
  // loop outlives every render it was started in.
  const [shuttleRate, setShuttleRate] = useState(0);
  const shuttleRef = useRef(0);
  const raf = useRef(0);
  const lastTick = useRef(0);
  const stopShuttle = () => {
    if (raf.current) { cancelAnimationFrame(raf.current); raf.current = 0; }
    if (shuttleRef.current !== 0) {
      shuttleRef.current = 0;
      setShuttleRate(0);
      const v = videoRef.current;
      if (v) v.playbackRate = av.current.rate;
    }
  };
  const shuttle = (dir: number) => {
    const v = videoRef.current;
    if (!v || !dir) return;
    const cur = shuttleRef.current;
    // Same way again doubles; the other way starts over at 1x that way. The
    // cap is 8, which is where a frame every other one stops reading as
    // motion at all.
    const next = cur !== 0 && Math.sign(cur) === Math.sign(dir)
      ? Math.sign(dir) * Math.min(8, Math.abs(cur) * 2)
      : dir;
    shuttleRef.current = next;
    setShuttleRate(next);
    if (next > 0) {
      if (raf.current) { cancelAnimationFrame(raf.current); raf.current = 0; }
      v.playbackRate = next;
      void v.play();
      return;
    }
    // Backwards: the element stays PAUSED and the playhead is walked back.
    if (!v.paused) v.pause();
    // ALWAYS re-arm rather than trusting `raf.current`. `requestAnimationFrame`
    // does not fire while the page is HIDDEN, so a shuttle running when the
    // tab went away simply stops — and the id it left behind would make every
    // later J read as "already running" and start nothing.
    if (raf.current) cancelAnimationFrame(raf.current);
    lastTick.current = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(0.25, (now - lastTick.current) / 1000);
      lastTick.current = now;
      const el = videoRef.current;
      const rate = shuttleRef.current;
      if (!el || rate >= 0) { raf.current = 0; return; }
      const at = Math.max(0, el.currentTime + rate * dt);
      el.currentTime = at;
      setTime(at);
      if (at <= 0) { stopShuttle(); return; }
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
  };
  // Nothing may outlive the window it was started in — and a shuttle stops
  // when the page does: `requestAnimationFrame` is not delivered to a hidden
  // tab, so a reverse shuttle left running there would sit frozen with its
  // speed still showing, waiting for a frame that never comes.
  useEffect(() => {
    const gone = () => { if (document.hidden) stopShuttle(); };
    document.addEventListener("visibilitychange", gone);
    return () => {
      document.removeEventListener("visibilitychange", gone);
      if (raf.current) cancelAnimationFrame(raf.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const stepFrame = (dir: number) => {
    const v = videoRef.current;
    stopShuttle();
    if (v && !v.paused) v.pause();
    seek(nowTime() + dir / (fps > 0 ? fps : 25));
  };
  const togglePlay = () => {
    const v = videoRef.current;
    if (!v) return;
    stopShuttle();
    if (v.paused) v.play(); else v.pause();
  };

  const setRate = (r: number) => {
    setRateState(r);
    if (videoRef.current) videoRef.current.playbackRate = r;
  };
  const setVolume = (val: number) => {
    const v = Math.max(0, Math.min(1, val));
    setVolumeState(v);
    setMuted(v === 0);
    if (videoRef.current) { videoRef.current.volume = v; videoRef.current.muted = v === 0; }
  };
  const toggleMuted = () => {
    setMuted((m) => {
      const next = !m;
      if (videoRef.current) videoRef.current.muted = next;
      return next;
    });
  };

  // Push STATE changes onto the element. (Re)mounts and source swaps are
  // covered above — this effect's deps don't change then, so it cannot be.
  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    v.playbackRate = rate;
    v.volume = volume;
    v.muted = muted;
  }, [rate, volume, muted]);

  // Absolute, because that is what the element reports and therefore what the
  // memory is keyed by; a caller holds the app-relative path.
  const absolute = (src: string) => {
    try { return new URL(src, window.location.href).href; } catch { return src; }
  };
  const positionFor = (src: string) => pos.current.recall(absolute(src));

  return {
    videoRef, time, duration: dur, playing, nowTime, seek, stepFrame, togglePlay,
    shuttle, shuttleRate,
    rate, setRate, volume, setVolume, muted, toggleMuted, error, positionFor,
  };
}

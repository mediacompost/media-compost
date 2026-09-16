/**
 * Where each video source was left, so coming back to one resumes instead of
 * restarting.
 *
 * Pure (no DOM), because the rule is small and the way to get it wrong is
 * not: a `<video>` reports its position and its source through the same
 * element, and there is a window during a source swap when the two disagree.
 * `videoPosition.test.ts` drives exactly that window.
 *
 * The annotator needs this because it renders a `<video>` only while the tab
 * being annotated is a film. Switching tabs therefore either UNMOUNTS the
 * element (an image tab) or hands the same one a different `src` (another
 * film tab), and both start at zero.
 */

/** The position is recorded against the source it BELONGS to, which is not
 *  always the one the element currently names.
 *
 *  When a `src` changes, the element resets `currentTime` to 0 and can fire a
 *  `timeupdate` while it is between sources. Recorded against whatever the
 *  element said at that instant, the zero lands on one of the two films and
 *  wipes the place it was left — the bug this class exists to make
 *  impossible. So a key is adopted only where a source is known to be loaded
 *  (`loaded`), and dropped the moment a load begins (`detached`); in between,
 *  nothing is written. */
export class VideoPositions {
  private marks = new Map<string, number>();
  /** The source the current position is about, or "" for none. */
  private key = "";

  /** Metadata for `src` has loaded: from here its position means something. */
  loaded(src: string): void {
    this.key = src || "";
  }

  /** A load has begun, the element was reset, or a different element took
   *  over — whatever position is reported now is about nothing. */
  detached(): void {
    this.key = "";
  }

  /** Remember where the current source is. Zero counts: it is where somebody
   *  rewound to. Ignored while no source is loaded. */
  record(time: number): void {
    if (this.key) this.marks.set(this.key, time);
  }

  /** Where `src` was left, or undefined for one never seen. */
  recall(src: string): number | undefined {
    return src ? this.marks.get(src) : undefined;
  }

  /** The position to seek `src` to on load, or null to leave it alone.
   *
   *  Null for a source never seen, for one left at the very beginning (it is
   *  already there), and for one already at the remembered moment — a seek
   *  that changes nothing still costs a re-decode. Clamped to `duration`,
   *  since a file can be replaced by a shorter one under the same URL. */
  resumeTo(src: string, current: number, duration: number): number | null {
    const want = this.recall(src);
    if (want == null || want <= 0) return null;
    const to = duration > 0 ? Math.min(want, duration) : want;
    return Math.abs(current - to) > 0.01 ? to : null;
  }
}

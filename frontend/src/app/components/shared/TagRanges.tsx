/** When, in a film, a tag applies — as a row's subtitle.
 *
 *  A SUBJECT, a PLACE and an EVENT are each extra data on a tag, so over a
 *  film they are timed exactly as that tag is: somebody is on screen in one
 *  stretch and not in another, and the ranges saying so are the tag's own
 *  time-only boxes. The tag list already showed them — one row per range —
 *  and the three people lists showed nothing at all, so the same fact was
 *  visible or invisible depending on which list you happened to be reading.
 *
 *  A row here is the PERSON, not the stretch (you remove the person, not one
 *  of their appearances on the timeline), so unlike a tag row it carries
 *  every range — ONE PER LINE, counting the rest past the third. On one line
 *  they were two truncated halves of two timecode pairs, which is a sidebar's
 *  whole width spent saying neither.
 *
 *  Empty is "the whole film", not "never": a tag with no ranges applies
 *  throughout, and a subtitle claiming otherwise would be a lie on almost
 *  every row. So there is nothing to draw, and `useTagRangeLabel` answers
 *  null.
 */
import React from "react";

import { ItemDetail } from "../../api";
import { spanLines } from "../../timecode";
import { coverageOfAll, tagRanges } from "../../videoTracks";
import { useT } from "../../i18n";

function filmFps(detail: ItemDetail | null | undefined): number {
  const file = detail?.files.find((f) => f.active) ?? detail?.files[0] ?? null;
  return file?.frame_rate && file.frame_rate > 0 ? file.frame_rate : 25;
}

/** "Which stretches does this tag cover on this item", or null where the
 *  question does not arise. The one place the film test and the several-
 *  placements fold are written, so the two readers below cannot disagree. */
function useTagRangeSpans(
  detail: ItemDetail | null | undefined
): ((tag: string) => ReturnType<typeof tagRanges>) | null {
  const file = detail?.files.find((f) => f.active) ?? detail?.files[0] ?? null;
  // The same test the annotator makes: a duration is what a film has.
  const isFilm = detail?.kind === "video" || (file?.duration ?? null) != null;
  if (!detail || !isFilm) return null;
  // A tag may sit in several groups, and its ranges are the tag's rather
  // than any one placement's — so the stretches of all of them, in order.
  return (tag: string) => tagRanges(
    (detail.tag_instances ?? [])
      .filter((i) => i.name === tag)
      .flatMap((i) => i.boxes ?? []));
}

/** A reader of "when does this tag apply on this item", or null for an item
 *  where the question does not arise (anything that is not a film). */
export function useTagRangeLabel(
  detail: ItemDetail | null | undefined
): ((tag: string) => string[] | null) | null {
  const t = useT();
  const spansOf = useTagRangeSpans(detail);
  const fps = filmFps(detail);
  if (!spansOf) return null;
  return (tag: string) => {
    const spans = spansOf(tag);
    if (spans.length === 0) return null;
    return spanLines(spans, fps, 3,
      (n) => t("+{n} more", { n: String(n) }));
  };
}

/** The same reader for a tag NOBODY ASSIGNED — one entailed by tags that are
 *  assigned, whose stretches it inherits.
 *
 *  An implied tag has no boxes of its own (it is not an assignment at all), so
 *  `useTagRangeLabel` sees nothing and the row read as "the whole film" —
 *  which is a claim about a film where the tag entailing it covers a minute.
 *  `coverageOfAll` is the rule; this only turns it into lines.
 */
export function useImpliedRangeLabel(
  detail: ItemDetail | null | undefined
): ((via: string[]) => string[] | null) | null {
  const t = useT();
  const spansOf = useTagRangeSpans(detail);
  const fps = filmFps(detail);
  if (!spansOf) return null;
  return (via: string[]) => {
    const covered = coverageOfAll(via.map(spansOf));
    if (!covered || covered.length === 0) return null;
    return spanLines(covered, fps, 3,
      (n) => t("+{n} more", { n: String(n) }));
  };
}

/** The subtitle itself — the tag rows' own treatment, so one fact looks the
 *  same in every list that states it. One LINE per stretch; the `title` still
 *  carries the lot, since a row narrowed past a timecode pair truncates. */
export function TagRangeLine({ label, indent = 0 }: {
  label: string[] | null;
  /** Lined up under the row's text rather than its icon. */
  indent?: number;
}) {
  if (!label || label.length === 0) return null;
  return (
    <span style={{ paddingLeft: indent, display: "flex",
      flexDirection: "column", minWidth: 0 }}
      title={label.join("\n")}>
      {label.map((line, i) => (
        <span key={i} style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-1)",
          color: "var(--muted-2)", overflow: "hidden",
          textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {line}
        </span>
      ))}
    </span>
  );
}

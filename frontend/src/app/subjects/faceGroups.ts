/** How a cluster's face crops are laid out — the grid's sections.
 *
 * Pure, so `node --test` can exercise the whole answer space — the grid
 * itself only renders what this decides.
 *
 * THREE AXES, ONE AT A TIME (owner 2026-09). Which one is a choice, because
 * they answer different questions about the same crops and a grid can only
 * be laid out one way:
 *
 *  - by AGE, the original and the default: "group by whatever there is more
 *    than one of, and otherwise don't". A strip of one person at one age has
 *    nothing to say and gets no headers; somebody who appears at six and at
 *    twelve has two groups. (Grouping by who played them went with "played
 *    by": a face is simply several people at once, and which of its names is
 *    the actor is not something the data says.)
 *  - by SEQUENCE — which book, chapter or film the crop's picture is a page
 *    of. `Item.main_sequence_id`'s, so it is the same sequence the library
 *    grid counts pages in.
 *  - by TAG, over the tags somebody has TICKED. Not one group per tag: a
 *    crop belongs to exactly one group, and that group is the COMBINATION it
 *    carries (owner 2026-09). With `smile` and `frown` ticked the groups are
 *    "smile, frown", "smile", "frown" and the catch-all — which keeps every
 *    crop in one place, so the selection, the marquee and the frozen order
 *    (`faceOrder.ts`, one slot per crop) are all untouched by it.
 */
import type { FaceRow } from "../api";
import { ageAt } from "../../query/subjects/when.ts";

export interface FaceGroup {
  /** Stable key for React, and the reason the group exists. */
  key: string;
  /** Header text, empty for the single ungrouped catch-all. */
  label: string;
  faces: FaceRow[];
}

/** The age to sort and group a face by.
 *
 *  A face may be several people, each with an age; the FIRST claim's is the
 *  one shown, since the strip a face is being read in belongs to one person
 *  and that person's claim sorts first. Null when nobody has said. */
export function faceAge(face: FaceRow, sinceDate: number | null): number | null {
  const when = face.subjects[0];
  if (!when) return null;
  if (when.when_age != null) return when.when_age;
  if (when.when_date != null && sinceDate) return ageAt(sinceDate, when.when_date);
  return null;
}

function byArea(a: FaceRow, b: FaceRow): number {
  return b.w * b.h - a.w * a.h;
}

/** One section holding everything, biggest crop first — what every axis
 *  answers when it has nothing to say, and what "not grouped" always is. */
export function flatGroup(faces: FaceRow[]): FaceGroup[] {
  return [{ key: "all", label: "", faces: [...faces].sort(byArea) }];
}

/** How the grid is laid out. `age` is what it has always done. */
export type FaceGrouping = "age" | "sequence" | "none";

/** WHAT THE OPEN CLUSTER'S PICTURES SAY, per crop — the server's answer
 *  (`POST /api/faces/grouping`) in the shape this module reads it. */
export interface FaceFacts {
  /** face id -> the sequence its picture is a page of, "" for none. */
  sequence: Map<number, string>;
  /** face id -> the ticked tags it carries, as a SET of names. */
  tags: Map<number, Set<string>>;
}

export const noFacts = (): FaceFacts =>
  ({ sequence: new Map(), tags: new Map() });

/** The crops under the tags somebody ticked, one group per COMBINATION.
 *
 *  `picked` is in the capsule bar's own order (most crops first), and that
 *  order is what orders the groups: a combination is read as a bit per
 *  ticked tag, most significant first, sorted DOWNWARDS — so with
 *  `[smile, frown]` ticked the sections are "smile, frown", then "smile",
 *  then "frown", then the crops carrying neither. Which is both the order
 *  somebody reading the capsules expects and the one that keeps the fullest
 *  answers at the top.
 */
export function groupByTags(
  faces: FaceRow[], picked: string[], facts: FaceFacts,
): FaceGroup[] {
  if (!picked.length) return flatGroup(faces);
  const by = new Map<number, { names: string[]; faces: FaceRow[] }>();
  for (const f of faces) {
    const has = facts.tags.get(f.id);
    let mask = 0;
    const names: string[] = [];
    picked.forEach((n, i) => {
      if (has?.has(n)) { mask |= 1 << (picked.length - 1 - i); names.push(n); }
    });
    const slot = by.get(mask) ?? by.set(mask, { names, faces: [] }).get(mask)!;
    slot.faces.push(f);
  }
  return lastly([...by.entries()]
    .sort((a, b) => b[0] - a[0])
    .map(([mask, g]) => ({
      key: `t${mask}`,
      // The catch-all wears no label, which is what `lastly` reads and what
      // the grid draws as a plain section.
      label: g.names.join(", "),
      faces: [...g.faces].sort(byArea),
    })));
}

/** WHAT THE TICKED TAGS DO WHEN THEY ARE NOT GROUPING — the crops left.
 *
 *  `filter` keeps a crop carrying EVERY ticked tag; `exclude` drops one
 *  carrying ANY of them. The two are deliberately not each other's opposite:
 *  both are what somebody means by them ("the ones that are both smiling and
 *  indoors"; "anything with a watermark, gone"), and an `any`/`all` pair
 *  written the other way round answers neither question.
 *
 *  Nothing ticked is everything, in the order it arrived. */
export function narrowByTags(
  faces: FaceRow[], picked: string[], facts: FaceFacts,
  mode: "filter" | "exclude",
): FaceRow[] {
  if (!picked.length) return faces;
  return faces.filter((f) => {
    const has = facts.tags.get(f.id);
    return mode === "filter"
      ? picked.every((n) => has?.has(n))
      : !picked.some((n) => has?.has(n));
  });
}

/** The crops by the book, chapter or film their picture is a page of. */
export function groupBySequence(
  faces: FaceRow[], facts: FaceFacts,
): FaceGroup[] {
  const by = new Map<string, FaceRow[]>();
  for (const f of faces) {
    const name = facts.sequence.get(f.id) ?? "";
    (by.get(name) ?? by.set(name, []).get(name)!).push(f);
  }
  // A cluster whose crops are all in one place (or all in none) has nothing
  // to group BY, which is the age rule one axis along: a heading over
  // everything is a heading in the way.
  if (by.size < 2) return flatGroup(faces);
  return lastly([...by.entries()]
    // By name, so the sections do not move when a crop is answered; the
    // pictures-in-no-sequence group carries no label and `lastly` puts it
    // at the end.
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([name, list]) => ({
      key: `s${name}`, label: name, faces: [...list].sort(byArea),
    })));
}

/**
 * Group `faces` for display under one subject.
 *
 * Returns a single unlabelled group when there is nothing to group by, which
 * is what keeps the common case looking exactly as it did.
 */
export function groupFaces(
  faces: FaceRow[],
  sinceDate: number | null = null,
): FaceGroup[] {
  return lastly(build(faces, sinceDate));
}

/** The catch-all goes LAST, whatever produced it. "Nobody said" is not a
 *  point on the scale, so it cannot sit among the ones that are — and a
 *  heading you have to read past to reach the answers is a heading in the
 *  way. */
function lastly(groups: FaceGroup[]): FaceGroup[] {
  const named = groups.filter((g) => g.label);
  const rest = groups.filter((g) => !g.label);
  return named.length && rest.length ? [...named, ...rest] : groups;
}

function build(
  faces: FaceRow[],
  sinceDate: number | null = null,
): FaceGroup[] {
  const flat = flatGroup(faces);
  if (faces.length < 2) return flat;

  // How old they are in it.
  const ages = new Set(faces.map((f) => faceAge(f, sinceDate)));
  if (ages.size > 1 && [...ages].some((a) => a != null)) {
    const by = new Map<number | null, FaceRow[]>();
    for (const f of faces) {
      const age = faceAge(f, sinceDate);
      (by.get(age) ?? by.set(age, []).get(age)!).push(f);
    }
    return [...by.entries()]
      // Youngest first, and "nobody said" last — it is not an age, so it does
      // not belong anywhere on the scale.
      .sort((a, b) => (a[0] ?? Infinity) - (b[0] ?? Infinity))
      .map(([age, list]) => ({
        key: `a${age ?? "none"}`,
        label: age == null ? "" : `age ${age}`,
        faces: [...list].sort(byArea),
      }));
  }

  return flat;
}

import test from "node:test";
import assert from "node:assert/strict";
import { faceAge, groupByTags, groupBySequence, groupFaces, narrowByTags,
         noFacts, type FaceFacts } from "./faceGroups.ts";
import type { FaceRow } from "../api.ts";

let next = 1;

/** A face carrying ONE claim — the strip a face is read in belongs to one
 *  person, and it is that person's age the grouping is about. */
function face(when: { when_date?: number | null; when_age?: number | null } = {},
              p: Partial<FaceRow> = {}): FaceRow {
  return {
    id: next++, item_id: 1, item_uid: "", file_id: null,
    x: 0, y: 0, w: 0.2, h: 0.2, det_score: 0.9, models: [],
    subjects: [{
      id: next, subject_id: 1, name: "Kaguya", comment: "", tag: "kaguya",
      since_date: null, assigned_by: "user", match_score: null,
      when_date: when.when_date ?? null, when_age: when.when_age ?? null,
      when_derived: false,
    }],
    dismissed: false, has_embedding: false, embedded_by: [],
    ...p,
  } as FaceRow;
}

test("nothing to group by leaves one unlabelled group", () => {
  const groups = groupFaces([face(), face(), face()]);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].label, "");
  assert.equal(groups[0].faces.length, 3);
});

test("a single face is never grouped", () => {
  assert.equal(groupFaces([face({ when_age: 6 })]).length, 1);
});

test("several ages group by age, youngest first", () => {
  const groups = groupFaces([
    face({ when_age: 12 }), face({ when_age: 6 }), face({ when_age: 12 }),
  ]);
  assert.deepEqual(groups.map((g) => g.label), ["age 6", "age 12"]);
  assert.deepEqual(groups.map((g) => g.faces.length), [1, 2]);
});

test("an undated face sorts last — it is not a point on the scale", () => {
  const groups = groupFaces([face(), face({ when_age: 30 })]);
  assert.deepEqual(groups.map((g) => g.label), ["age 30", ""]);
});

test("an age is derived from a date and the subject's since-date", () => {
  assert.equal(faceAge(face({ when_date: 20220000 }), 20100000), 12);
  assert.equal(faceAge(face({ when_age: 6, when_date: 20220000 }), 20100000), 6,
               "what was typed wins over what can be worked out");
  assert.equal(faceAge(face({ when_date: 20220000 }), null), null);
  assert.equal(faceAge(face(), 20100000), null);
});

test("dates alone group as ages once they can be derived", () => {
  const groups = groupFaces(
    [face({ when_date: 20160000 }), face({ when_date: 20220000 })], 20100000);
  assert.deepEqual(groups.map((g) => g.label), ["age 6", "age 12"]);
});


// ---------------------------------------------------------------------------
// The other two axes: by the book a crop's picture is a page of, and by the
// tags somebody ticked.

/** `facts` built from a plain table, so a case reads as what it is about. */
function facts(rows: { face: FaceRow; seq?: string; tags?: string[] }[]): FaceFacts {
  const out = noFacts();
  for (const r of rows) {
    out.sequence.set(r.face.id, r.seq ?? "");
    out.tags.set(r.face.id, new Set(r.tags ?? []));
  }
  return out;
}

const drawn = (gs: ReturnType<typeof groupByTags>) =>
  gs.map((g) => `${g.label || "-"}:${g.faces.length}`);

test("a ticked tag groups by the COMBINATION, so a crop is in one place", () => {
  const a = face(), b = face(), c = face(), d = face();
  const f = facts([{ face: a, tags: ["smile", "frown"] },
                   { face: b, tags: ["smile"] },
                   { face: c, tags: ["frown"] },
                   { face: d, tags: ["hat"] }]);
  // The capsule bar's order is the group order: both, then the first alone,
  // then the second, then the crops carrying neither.
  assert.deepEqual(drawn(groupByTags([a, b, c, d], ["smile", "frown"], f)),
                   ["smile, frown:1", "smile:1", "frown:1", "-:1"]);
  // Every crop is in exactly one group — which is what leaves the frozen
  // order and the selection alone.
  const total = groupByTags([a, b, c, d], ["smile", "frown"], f)
    .reduce((n, g) => n + g.faces.length, 0);
  assert.equal(total, 4);
});

test("ticking one tag is two groups, and the catch-all is last", () => {
  const a = face(), b = face();
  const f = facts([{ face: a, tags: ["smile"] }, { face: b, tags: [] }]);
  assert.deepEqual(drawn(groupByTags([a, b], ["smile"], f)),
                   ["smile:1", "-:1"]);
});

test("a combination nothing carries is not a section", () => {
  const a = face(), b = face();
  const f = facts([{ face: a, tags: ["smile"] }, { face: b, tags: ["frown"] }]);
  // No crop carries both, and none carries neither: two sections, not four.
  assert.deepEqual(drawn(groupByTags([a, b], ["smile", "frown"], f)),
                   ["smile:1", "frown:1"]);
});

test("with nothing ticked the tag axis is one flat group", () => {
  const a = face(), b = face();
  assert.deepEqual(drawn(groupByTags([a, b], [], noFacts())), ["-:2"]);
});

test("the order of the capsules is the order of the sections", () => {
  const a = face();
  const f = facts([{ face: a, tags: ["smile", "frown"] }]);
  // Reading the ticks the other way round labels the group the other way
  // round — the bar is the authority on which is first.
  assert.deepEqual(drawn(groupByTags([a], ["frown", "smile"], f)),
                   ["frown, smile:1"]);
});

test("sequences group by name, and pictures in none come last", () => {
  const a = face(), b = face(), c = face();
  const f = facts([{ face: a, seq: "Volume 2" }, { face: b, seq: "Volume 1" },
                   { face: c, seq: "" }]);
  assert.deepEqual(drawn(groupBySequence([a, b, c], f)),
                   ["Volume 1:1", "Volume 2:1", "-:1"]);
});

test("one sequence for everything is nothing to group by", () => {
  const a = face(), b = face();
  const f = facts([{ face: a, seq: "Volume 1" }, { face: b, seq: "Volume 1" }]);
  assert.deepEqual(drawn(groupBySequence([a, b], f)), ["-:2"]);
  // …and so is no sequence at all.
  assert.deepEqual(drawn(groupBySequence([a, b], noFacts())), ["-:2"]);
});


test("filter keeps a crop carrying EVERY ticked tag", () => {
  const both = face(), one = face(), none = face();
  const f = facts([{ face: both, tags: ["smile", "frown"] },
                   { face: one, tags: ["smile"] },
                   { face: none, tags: [] }]);
  const kept = narrowByTags([both, one, none], ["smile", "frown"], f, "filter");
  assert.deepEqual(kept.map((x) => x.id), [both.id]);
  // One ticked tag is the ordinary case, and it keeps both that carry it.
  assert.deepEqual(
    narrowByTags([both, one, none], ["smile"], f, "filter").map((x) => x.id),
    [both.id, one.id]);
});

test("exclude drops a crop carrying ANY ticked tag", () => {
  const both = face(), one = face(), none = face();
  const f = facts([{ face: both, tags: ["smile", "frown"] },
                   { face: one, tags: ["smile"] },
                   { face: none, tags: [] }]);
  // NOT the opposite of filter: `both` and `one` both go.
  assert.deepEqual(
    narrowByTags([both, one, none], ["smile", "frown"], f, "exclude")
      .map((x) => x.id),
    [none.id]);
  assert.deepEqual(
    narrowByTags([both, one, none], ["frown"], f, "exclude").map((x) => x.id),
    [one.id, none.id]);
});

test("nothing ticked narrows nothing, in the order it arrived", () => {
  const a = face(), b = face();
  for (const m of ["filter", "exclude"] as const) {
    assert.deepEqual(narrowByTags([a, b], [], noFacts(), m).map((x) => x.id),
                     [a.id, b.id]);
  }
});

test("a crop the facts have never heard of carries no tag", () => {
  // The facts arrive a moment after the crops do, and a crop that arrived
  // with the last answer has none yet. It is not in `filter`'s answer and
  // it survives `exclude`'s — neither of which is a claim about it.
  const a = face();
  assert.deepEqual(narrowByTags([a], ["smile"], noFacts(), "filter"), []);
  assert.deepEqual(narrowByTags([a], ["smile"], noFacts(), "exclude")
                     .map((x) => x.id), [a.id]);
});

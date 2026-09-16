import { test } from "node:test";
import assert from "node:assert/strict";

import { freshOrder, stableGroups } from "./faceOrder.ts";
import type { FaceGroup } from "./faceGroups.ts";

/** A crop, thin enough for the ordering to be the only thing under test. */
const face = (id: number) => ({ id } as unknown as FaceGroup["faces"][number]);
const group = (key: string, ids: number[]): FaceGroup =>
  ({ key, label: key === "all" ? "" : key, faces: ids.map(face) });

/** What the grid would draw: group key, then the ids with a † on a ghost. */
const drawn = (gs: ReturnType<typeof stableGroups>["groups"]) =>
  gs.map((g) => `${g.key}:${g.faces.map((f) => f.face.id + (f.gone ? "†" : ""))
    .join(",")}`);

test("the first look is the order, exactly as it arrives", () => {
  const { groups, frozen } = stableGroups(
    [group("all", [3, 1, 2])], freshOrder(), "c1");
  assert.deepEqual(drawn(groups), ["all:3,1,2"]);
  assert.equal(frozen.key, "c1");
});

test("a crop that leaves stays where it was, as a ghost", () => {
  // The clustering answers with a different order AND without 1 — which is
  // what a re-cluster after an answer looks like.
  const a = stableGroups([group("all", [3, 1, 2])], freshOrder(), "c1");
  const b = stableGroups([group("all", [2, 3])], a.frozen, "c1");
  assert.deepEqual(drawn(b.groups), ["all:3,1†,2"]);
});

test("a ghost stays a ghost while the cluster is open", () => {
  const a = stableGroups([group("all", [1, 2])], freshOrder(), "c1");
  const b = stableGroups([group("all", [2])], a.frozen, "c1");
  const c = stableGroups([group("all", [2])], b.frozen, "c1");
  assert.deepEqual(drawn(c.groups), ["all:1†,2"]);
});

test("a crop that comes back stops being a ghost, in its own place", () => {
  // Undo is the case: the crop returns, and it returns where it was rather
  // than on the end.
  const a = stableGroups([group("all", [1, 2, 3])], freshOrder(), "c1");
  const b = stableGroups([group("all", [2, 3])], a.frozen, "c1");
  assert.deepEqual(drawn(b.groups), ["all:1†,2,3"]);
  const c = stableGroups([group("all", [3, 1, 2])], b.frozen, "c1");
  assert.deepEqual(drawn(c.groups), ["all:1,2,3"]);
});

test("a newcomer is APPENDED, so nothing on screen moves", () => {
  const a = stableGroups([group("all", [1, 2])], freshOrder(), "c1");
  // The re-cluster puts 9 first; the grid must not.
  const b = stableGroups([group("all", [9, 1, 2])], a.frozen, "c1");
  assert.deepEqual(drawn(b.groups), ["all:1,2,9"]);
  // …and two arrivals keep the order the grouping gave them.
  const c = stableGroups([group("all", [7, 9, 1, 2, 8])], b.frozen, "c1");
  assert.deepEqual(drawn(c.groups), ["all:1,2,9,7,8"]);
});

test("each group keeps its own order, and a ghost stays in its group", () => {
  const a = stableGroups(
    [group("6", [1, 2]), group("12", [3, 4])], freshOrder(), "c1");
  assert.deepEqual(drawn(a.groups), ["6:1,2", "12:3,4"]);
  const b = stableGroups(
    [group("6", [2]), group("12", [4, 3])], a.frozen, "c1");
  assert.deepEqual(drawn(b.groups), ["6:1†,2", "12:3,4"]);
});

test("a ghost whose group has gone goes with it", () => {
  // A heading over nothing but departures is a heading about no one.
  const a = stableGroups(
    [group("6", [1]), group("12", [3, 4])], freshOrder(), "c1");
  const b = stableGroups([group("12", [3, 4])], a.frozen, "c1");
  assert.deepEqual(drawn(b.groups), ["12:3,4"]);
});

test("another cluster starts over", () => {
  const a = stableGroups([group("all", [1, 2])], freshOrder(), "c1");
  const b = stableGroups([group("all", [5, 4])], a.frozen, "c2");
  // Neither the old order nor its ghosts follow you into the next cluster.
  assert.deepEqual(drawn(b.groups), ["all:5,4"]);
  assert.equal(b.frozen.key, "c2");
});

test("the frozen order handed in is never mutated", () => {
  const a = stableGroups([group("all", [1, 2])], freshOrder(), "c1");
  const before = [...a.frozen.slot.keys()];
  stableGroups([group("all", [1, 2, 3])], a.frozen, "c1");
  assert.deepEqual([...a.frozen.slot.keys()], before);
});

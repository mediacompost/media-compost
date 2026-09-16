/** The tag-batch session's pure rules — the set's shape (groups, never
 *  fewer than one), the toggles (an exclusive group holds one lit tag), the
 *  commit plan (what each answer writes: lit tags, counter tags, the groups'
 *  negatives), the drags (a tag within or between groups, a group among
 *  groups), the queue merge, the codec with its old-shape migrations, the
 *  presets (the set alone) and the summary counts. */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DEFAULT_CONFIG, FIRST_GROUP_ID, FUSED, applyPreset, chosenOf, clearTags,
  counterOf, embeddersOf, fillKeys, keyOf, maxKey, mergeQueue, modeOf,
  moveEntry, moveGroup, moveTagTo, nextFreeKey, parseTagSortConfig,
  parseTagSortPresets, planCommit, planNone, planSingle, presetOf,
  serializeTagSortConfig, serializeTagSortPresets, sessionNegatives,
  summarize, tagNames, tagsForKey, toggleTags, renameTag, updateGroup, wireCounters,
  wireGroups, withCounter, withGroup, withoutGroup, withoutTag, withTag,
  writesUnlit, withGroupRow, groupRowName, plainTags, rowLabel, rowLabels,
} from "./tagSort.ts";
import type { TagSortConfig, TagSortGroup } from "./tagSort.ts";

const group = (id: string, names: (string | [string, string])[],
               exclusive = true, negatives = true): TagSortGroup =>
  ({ id, exclusive, negatives,
     tags: names.map((n) => typeof n === "string"
       ? { name: n, negative: "" } : { name: n[0], negative: n[1] }) });
const cfg = (groups: TagSortGroup[], keys: Record<string, number> = {},
             ): TagSortConfig =>
  ({ ...DEFAULT_CONFIG, groups, keys });

test("the set reads group by group, and one tag is a yes/no session", () => {
  const c = cfg([group("g", ["a"]), group("h", ["b", "c"])]);
  assert.deepEqual(tagNames(c), ["a", "b", "c"]);
  assert.equal(modeOf(c), "multi");
  assert.equal(modeOf(cfg([group("g", ["only"])])), "single");
  assert.equal(modeOf(cfg([group("g", [])])), "single");
});

test("a tag's digit is its own entry, else its position — and digits may be shared", () => {
  const c = cfg([group("g", ["a"]), group("h", ["b", "c"])], { c: 1 });
  assert.equal(keyOf(c, "a"), 1);
  assert.equal(keyOf(c, "b"), 2);
  assert.equal(keyOf(c, "c"), 1, "set by hand, whatever its position");
  assert.deepEqual(tagsForKey(c, 1), ["a", "c"]);
  assert.deepEqual(tagsForKey(c, 3), []);
  assert.equal(maxKey(c), 2);
  const filled = { ...c, keys: fillKeys(c.keys, tagNames(c)) };
  assert.deepEqual(filled.keys, { a: 1, b: 2, c: 1 });
  // A reorder moves the rows and never the keys.
  const moved = moveGroup(filled, 0, 1);
  assert.deepEqual(tagNames(moved), ["b", "c", "a"]);
  assert.equal(keyOf(moved, "a"), 1, "a keeps its digit across the move");
});

test("a new tag goes in the group named or the last, and takes no digit of its own", () => {
  const c = cfg([group("g", ["a"]), group("h", ["b"])], { a: 1, b: 3 });
  assert.equal(nextFreeKey(c), 2);
  const d = withTag(c, "x", "g");
  assert.deepEqual(tagNames(d), ["a", "x", "b"]);
  // NO ENTRY IN `keys`: that map holds the digits somebody CHOSE, and an
  // entry there is what makes a digit stick through a reorder. A tag nobody
  // has re-keyed answers to its POSITION, so moving rows renumbers exactly
  // the rows nobody has an opinion about.
  assert.equal(d.keys.x, undefined);
  assert.equal(keyOf(d, "x"), 2, "its position in the set");
  const e = withTag(c, "y");
  assert.deepEqual(tagNames(e), ["a", "b", "y"], "no group named: the last");
  assert.equal(withTag(d, "x", "h"), d, "already there: unchanged, wherever");
  const nine = cfg([group("g", "123456789".split(""))]);
  assert.equal(tagNames(withTag(nine, "ten", "g")).length, 9, "nine is the cap");
});

test("removing, clearing and editing the set — never without a group", () => {
  const c = cfg([group("g", [["a", "not_a"]]), group("h", ["b", "c"])],
                { a: 1, b: 2, c: 3 });
  assert.deepEqual(tagNames(withoutTag(c, "b")), ["a", "c"]);
  assert.deepEqual(withoutTag(c, "b").keys, { a: 1, c: 3 });
  assert.deepEqual(tagNames(withoutGroup(c, "h")), ["a"]);
  assert.deepEqual(withoutGroup(c, "h").keys, { a: 1 });
  const lone = withoutGroup(withoutGroup(c, "h"), "g");
  assert.equal(lone.groups.length, 1, "the last group leaves an empty one");
  assert.deepEqual(lone.groups[0].tags, []);
  assert.deepEqual(lone.keys, {});
  const cleared = clearTags(c);
  assert.equal(cleared.groups.length, 1);
  assert.deepEqual(cleared.groups[0].tags, []);
  assert.deepEqual(cleared.keys, {});
  const g = updateGroup(c, "h", { exclusive: false });
  assert.deepEqual(g.groups[1], group("h", ["b", "c"], false, true));
  assert.equal(counterOf(withCounter(c, "c", " low_c "), "c"), "low_c");
  assert.equal(counterOf(withCounter(c, "a", ""), "a"), "");
  assert.equal(counterOf(withCounter(c, "a", "a"), "a"), "",
               "a tag's own name is the default negative again");
  // A rename keeps the slot, the digit and the counter; a taken or empty
  // name changes nothing; a counter equal to the new name is the default.
  const r = renameTag(c, "b", "bee");
  assert.deepEqual(tagNames(r), ["a", "bee", "c"]);
  assert.deepEqual(r.keys, { a: 1, bee: 2, c: 3 });
  assert.equal(renameTag(c, "b", "c"), c);
  assert.equal(renameTag(c, "b", " "), c);
  assert.equal(renameTag(c, "nope", "x"), c);
  assert.equal(counterOf(renameTag(c, "a", "not_a"), "not_a"), "");
  assert.equal(withGroup(c).groups.length, 3);
  assert.deepEqual(withGroup(c).groups[2].tags, []);
});

test("a tag drags within its group and into another; a group among groups", () => {
  const c = cfg([group("g", ["a", "b", "c"]), group("h", ["d"])]);
  // Within: slot indexes count the list as it is, the moved tag included.
  assert.deepEqual(moveTagTo(c, "a", "g", 3).groups[0].tags.map((t) => t.name),
                   ["b", "c", "a"], "to the end");
  assert.deepEqual(moveTagTo(c, "c", "g", 0).groups[0].tags.map((t) => t.name),
                   ["c", "a", "b"], "to the front");
  assert.deepEqual(moveTagTo(c, "a", "g", 2).groups[0].tags.map((t) => t.name),
                   ["b", "a", "c"], "after b: slot 2 with a still in front");
  assert.equal(moveTagTo(c, "b", "g", 1), c, "onto its own slot: unchanged");
  assert.equal(moveTagTo(c, "b", "g", 2), c, "the slot after itself: unchanged");
  // Between: the tag leaves one group and lands in the other's slot.
  const across = moveTagTo(c, "b", "h", 0);
  assert.deepEqual(across.groups.map((g) => g.tags.map((t) => t.name)),
                   [["a", "c"], ["b", "d"]]);
  assert.deepEqual(moveTagTo(c, "d", "g", 9).groups.map(
    (g) => g.tags.map((t) => t.name)), [["a", "b", "c", "d"], []],
    "past the end lands at the end; a group may be left empty");
  assert.equal(moveTagTo(c, "nope", "g", 0), c);
  assert.equal(moveTagTo(c, "a", "nope", 0), c);
  assert.deepEqual(moveGroup(c, 1, 0).groups.map((g) => g.id), ["h", "g"]);
  assert.deepEqual(moveGroup(c, 0, 5).groups, c.groups, "out of range: unchanged");
});

test("lighting a tag in an exclusive group puts the others out", () => {
  const c = cfg([group("r", ["a"], false, false), group("g", ["b", "c"], true),
                 group("h", ["d", "e"], false)]);
  let lit = toggleTags(c, new Set(), ["b"]);
  assert.deepEqual([...lit], ["b"]);
  lit = toggleTags(c, lit, ["c"]);
  assert.deepEqual([...lit], ["c"], "c replaces b — one of the group");
  lit = toggleTags(c, lit, ["c"]);
  assert.deepEqual([...lit], [], "pressing the lit one puts it out");
  lit = toggleTags(c, new Set(["d"]), ["e", "a"]);
  assert.deepEqual([...lit].sort(), ["a", "d", "e"],
                   "an independent group stacks");
  assert.deepEqual([...toggleTags(c, new Set(["a"]), ["nope"])], ["a"]);
});

test("the commit writes lit tags, then what each unlit tag's group says", () => {
  const c = cfg([group("r", ["root", ["hi", "lo"]], false, true),
                 group("g", ["x", "y"], true, true),
                 group("h", ["p", "q"], false, false)]);
  // Nothing lit: under a group's switch every counter and every negative;
  // nothing for a group without it.
  assert.deepEqual(planNone(c), { positive: ["lo"],
                                  negative: ["root", "x", "y"], groups: [] });
  assert.deepEqual(planCommit(c, new Set(["hi", "y", "p"])),
                   { positive: ["hi", "y", "p"], negative: ["root", "x"], groups: [] });
  assert.deepEqual(chosenOf(c, new Set(["p", "hi"])), ["hi", "p"],
                   "in the list's order");
  assert.equal(planNone(cfg([group("h", ["p"], false, false)])), null,
               "only silent tags: a commit with nothing lit writes nothing");
  assert.equal(writesUnlit(c, "root"), true);
  assert.equal(writesUnlit(c, "hi"), true);
  assert.equal(writesUnlit(c, "p"), false);
});

test("a counter tag is the negative side's answer, and only under the switch", () => {
  const on = cfg([group("g", [["good", "bad"], "other"], true, true)]);
  assert.deepEqual(planCommit(on, new Set(["other"])),
                   { positive: ["other", "bad"], negative: [], groups: [] });
  assert.deepEqual(planCommit(on, new Set(["good"])),
                   { positive: ["good"], negative: ["other"], groups: [] });
  const off = cfg([group("g", [["good", "bad"], "other"], true, false)]);
  assert.deepEqual(planCommit(off, new Set(["other"])),
                   { positive: ["other"], negative: [], groups: [] });
  assert.equal(planNone(off), null);
});

test("single mode: yes assigns, no writes the counter or the group's negative", () => {
  assert.deepEqual(planSingle(cfg([group("g", ["cat"])]), true),
                   { positive: ["cat"], negative: [], groups: [] });
  assert.deepEqual(planSingle(cfg([group("g", ["cat"])]), false),
                   { positive: [], negative: ["cat"], groups: [] });
  assert.deepEqual(planSingle(cfg([group("g", [["cat", "dog"]])]), false),
                   { positive: ["dog"], negative: [], groups: [] });
  // Neither: a "no" writes nothing — a skip in effect.
  assert.equal(planSingle(cfg([group("g", ["cat"], true, false)]), false), null);
  assert.equal(planSingle(cfg([group("g", [])]), true), null);
});

test("a lit tag survives a reorder and dies with its tag", () => {
  const lit = new Set(["hat"]);
  assert.deepEqual(planCommit(cfg([group("g", ["hat", "scarf"], false)]), lit),
                   { positive: ["hat"], negative: ["scarf"], groups: [] });
  assert.deepEqual(planCommit(cfg([group("g", ["scarf", "hat"], false)]), lit),
                   { positive: ["hat"], negative: ["scarf"], groups: [] });
  assert.deepEqual(planCommit(cfg([group("g", ["scarf"], false)]), lit),
                   { positive: [], negative: ["scarf"], groups: [] });
});

test("the fit is told the implicit negatives the library never sees", () => {
  const c = cfg([group("r", ["root", ["hi", "lo"]], false, false),
                 group("g", ["x"], true, true)]);
  const judged = [
    { ref: { item_id: 1 }, chosen: ["hi"], eventIds: [1] },
    { ref: { item_id: 2 }, chosen: ["root", "x"], eventIds: [2] },
  ];
  // Both of the silent group's tags: hi's counter is not written either,
  // with the switch off.
  assert.deepEqual(sessionNegatives(c, judged), { root: [1], hi: [2] });
  assert.equal(sessionNegatives(cfg([group("g", ["x"])]), judged), undefined);
});

test("the wire carries the groups with tags and every counter", () => {
  const c = cfg([group("r", [["a", "not_a"]], false, true),
                 group("g", ["b", "c"], true),
                 group("empty", []), group("h", [["d", "not_d"]], false, false)]);
  assert.deepEqual(wireGroups(c), [{ tags: ["a"], exclusive: false },
                                   { tags: ["b", "c"], exclusive: true },
                                   { tags: ["d"], exclusive: false }]);
  assert.deepEqual(wireCounters(c), { a: "not_a" },
                   "a counter under a switch that is off is not written");
  assert.deepEqual(wireCounters(cfg([group("g", [["a", "a"]])])), {},
                   "a tag as its own counter is no counter");
});

test("the queue merge keeps the on-screen item and replaces the tail", () => {
  const r = (id: number) => ({ item_id: id });
  const current = [r(1), r(2), r(3)];
  const incoming = [r(5), r(1), r(4), r(6)];
  const merged = mergeQueue(current, incoming, new Set([6]));
  assert.deepEqual(merged.map((x) => x.item_id), [1, 5, 4]);
  assert.deepEqual(mergeQueue([], incoming, new Set([1]))
    .map((x) => x.item_id), [5, 4, 6]);
});

test("the codec round-trips and tolerates garbage", () => {
  const c = cfg([group("g", [["a", "not_a"]]), group("h", ["b", "c"], false)],
                { a: 1, b: 2, c: 1 });
  assert.deepEqual(parseTagSortConfig(serializeTagSortConfig(c)), c);
  assert.deepEqual(parseTagSortConfig(null), DEFAULT_CONFIG);
  assert.deepEqual(parseTagSortConfig("not json"), DEFAULT_CONFIG);
  assert.equal(parseTagSortConfig("{}").groups[0].id, FIRST_GROUP_ID,
               "a set with nothing in it is one empty group");
  const messy = parseTagSortConfig(JSON.stringify({
    groups: [{ id: "g", tags: ["a", "a", null, { name: "" }, 3] },
             { id: "g", tags: ["b"] }, null, "x"],
    keys: { a: 12 } }));
  assert.deepEqual(tagNames(messy), ["a", "b"], "duplicates and junk dropped");
  assert.equal(messy.groups.length, 2);
  assert.notEqual(messy.groups[1].id, "g", "a duplicated id is re-minted");
  assert.deepEqual(messy.keys, { a: 1, b: 2 },
                   "an out-of-range digit falls back to the position");
  const many = JSON.stringify({ groups: [{ tags: "abcdefghijkl".split("") }] });
  assert.equal(tagNames(parseTagSortConfig(many)).length, 9,
               "the digit keys cap the set");
  assert.equal(parseTagSortConfig('{"groups": []}').smart, true);
  assert.equal(parseTagSortConfig('{"smart": false}').smart, false);
  assert.equal(parseTagSortConfig('{"kind": "video"}').kind, "video");
  assert.equal(parseTagSortConfig('{"kind": "nonsense"}').kind, "image");
});

test("a preset is the set alone, and loading one leaves the session's settings", () => {
  const c = { ...cfg([group("g", [["a", "not_a"]], false), group("h", ["b"])],
                     { a: 2, b: 1 }),
              kind: "video" as const, smart: false, skipSequenced: true };
  const p = presetOf(c, "p1", "shirts");
  assert.deepEqual(p, { id: "p1", name: "shirts", groups: c.groups,
                        keys: { a: 2, b: 1 } });
  const other = { ...cfg([group("z", ["zzz"])]), embedder: "clip_vit_b32" };
  const loaded = applyPreset(other, p);
  assert.deepEqual(loaded.groups, c.groups);
  assert.deepEqual(loaded.keys, { a: 2, b: 1 });
  assert.equal(loaded.kind, "image", "the session's own kind stays");
  assert.equal(loaded.embedder, "clip_vit_b32");
  assert.equal(loaded.smart, true);
});

test("the presets codec round-trips and tolerates garbage", () => {
  const list = [{ id: "a1", name: "shirts",
                  groups: [group("g", ["blue_shirt", "red_shirt"], false)],
                  keys: { blue_shirt: 1, red_shirt: 2 } }];
  assert.deepEqual(parseTagSortPresets(serializeTagSortPresets(list)), list);
  assert.deepEqual(parseTagSortPresets(null), []);
  assert.deepEqual(parseTagSortPresets("not json"), []);
  const messy = JSON.stringify([
    { name: "ok", groups: [{ id: "g", tags: ["a", 3] }] },
    { groups: [] },
    null,
  ]);
  const parsed = parseTagSortPresets(messy);
  assert.equal(parsed.length, 1);
  assert.deepEqual(parsed[0].groups, [group("g", ["a"])]);
  assert.deepEqual(parsed[0].keys, { a: 1 });
  assert.ok(parsed[0].id.length > 0, "a missing id is minted");
  assert.deepEqual(Object.keys(parsed[0]).sort(), ["groups", "id", "keys", "name"],
                   "nothing but the set survives");
});

test("the summary counts decided items per tag, plus none-of-these", () => {
  const judged = [
    { ref: 0, chosen: ["a"], eventIds: [1] },
    { ref: 0, chosen: ["a", "c"], eventIds: [2, 3] },
    { ref: 0, chosen: [], eventIds: [4, 5] },
  ];
  assert.deepEqual(summarize(judged, ["a", "b", "c"]),
                   { decided: 3, perTag: [2, 0, 1], none: 1 });
  assert.deepEqual(summarize(judged, ["c", "b", "a"]),
                   { decided: 3, perTag: [1, 0, 2], none: 1 });
  assert.deepEqual(summarize(judged, ["a", "d"]),
                   { decided: 3, perTag: [2, 0], none: 1 });
});

test("moving an entry is a move, and an impossible one changes nothing", () => {
  const list = ["a", "b", "c"];
  assert.deepEqual(moveEntry(list, 2, 0), ["c", "a", "b"]);
  assert.deepEqual(moveEntry(list, 0, 1), ["b", "a", "c"]);
  assert.deepEqual(moveEntry(list, 1, 1), list);
  assert.deepEqual(moveEntry(list, -1, 0), list);
  assert.deepEqual(moveEntry(list, 0, 3), list);
  assert.deepEqual(list, ["a", "b", "c"]);
});

test("fused is the default, and a named space is kept", () => {
  assert.equal(parseTagSortConfig(null).embedder, FUSED);
  assert.equal(parseTagSortConfig(JSON.stringify(
    { groups: [], embedder: "clip_vit_b32" })).embedder, "clip_vit_b32");
  assert.deepEqual(embeddersOf(FUSED, ["dinov2_small", "clip_vit_b32"]),
                   ["dinov2_small", "clip_vit_b32"]);
});

test("a reorder renumbers the rows nobody has re-keyed, and leaves the rest", () => {
  // The digits are what the hand on the keyboard has learned, so a set
  // whose rows have been dragged into a new order should read down the
  // list as 1, 2, 3 — unless somebody said otherwise about a row, in which
  // case that row keeps what they said.
  const c = cfg([group("g", ["a", "b", "c"])]);
  assert.deepEqual(["a", "b", "c"].map((n) => keyOf(c, n)), [1, 2, 3]);

  const moved = { ...c, groups: [{ ...c.groups[0], tags: [
    c.groups[0].tags[2], c.groups[0].tags[0], c.groups[0].tags[1]] }] };
  assert.deepEqual(tagNames(moved), ["c", "a", "b"]);
  assert.deepEqual(["c", "a", "b"].map((n) => keyOf(moved, n)), [1, 2, 3],
                   "the order is the keyboard");

  // …and a row somebody chose a digit for keeps it wherever it goes.
  const chosen = { ...moved, keys: { a: 7 } };
  assert.equal(keyOf(chosen, "a"), 7);
  assert.equal(keyOf(chosen, "c"), 1);
});

test("a group left out of the session is invisible to every reader", () => {
  const c = cfg([group("g", ["a", "b"]), group("h", ["c"])]);
  assert.deepEqual(tagNames(c), ["a", "b", "c"]);
  const off = { ...c, groups: [{ ...c.groups[0], enabled: false }, c.groups[1]] };
  // Not offered, and takes no digit — so the one live tag is `1`.
  assert.deepEqual(tagNames(off), ["c"]);
  assert.equal(keyOf(off, "c"), 1);
  // …and it is set ASIDE, not deleted: the group and its tags are still
  // written down, ready to come back.
  assert.equal(off.groups.length, 2);
  assert.deepEqual(off.groups[0].tags.map((x) => x.name), ["a", "b"]);
});

test("a LIBRARY GROUP is a row like a tag, and writes a membership", () => {
  // Picked into the same question as the tags, it takes its turn in the
  // reading order and its own digit — a group row is answered exactly the
  // way a tag is; only what it WRITES is different.
  const c = withGroupRow(cfg([group("g", ["cat", "dog"])]), 7, "Cats");
  const key = groupRowName(7);
  assert.deepEqual(tagNames(c), ["cat", "dog", key]);
  assert.deepEqual(plainTags(c), ["cat", "dog"],
                   "the classifier is told about tags only");
  assert.equal(keyOf(c, key), 3);
  assert.equal(rowLabel(c, key), "Cats");
  assert.deepEqual(rowLabels(c), ["cat", "dog", "Cats"]);

  // Lit: the membership rides beside the tags, and the unlit tag still
  // writes its negative.
  assert.deepEqual(planCommit(c, new Set(["cat", key])),
                   { positive: ["cat"], negative: ["dog"], groups: [7] });
  // UNLIT IT WRITES NOTHING — "not in that group" is not a thing to record,
  // so the negatives switch passes it by and it never becomes a negative.
  assert.deepEqual(planCommit(c, new Set(["cat"])),
                   { positive: ["cat"], negative: ["dog"], groups: [] });
  assert.equal(writesUnlit(c, key), false);
  // A group row alone IS something to write, so it is not a silent commit.
  const only = withGroupRow(cfg([group("g", [])]), 4, "Keep");
  assert.deepEqual(planCommit(only, new Set([groupRowName(4)])),
                   { positive: [], negative: [], groups: [4] });
  assert.equal(planNone(only), null, "nothing lit, nothing written");
  // And it never reaches the wire: the ordering is over tags.
  assert.deepEqual(wireGroups(c), [{ tags: ["cat", "dog"], exclusive: true }]);
});

test("a group row is the same group twice over, and survives the codec", () => {
  const once = withGroupRow(cfg([group("g", [])]), 7, "Cats");
  assert.equal(tagNames(withGroupRow(once, 7, "Cats")).length, 1,
               "the same group is not added twice");
  // KEYED BY ID, not by name: the group being renamed must not lose the row
  // (nor two groups sharing a name collapse into one).
  const back = parseTagSortConfig(serializeTagSortConfig(
    withGroupRow(once, 8, "Cats")));
  assert.deepEqual(back.groups[0].tags.map((x) => x.group), [7, 8]);
  assert.deepEqual(back.groups[0].tags.map((x) => x.name),
                   [groupRowName(7), groupRowName(8)]);
  assert.equal(rowLabel(back, groupRowName(8)), "Cats");
  // A row taken out takes its digit with it, as a tag's does.
  const gone = withoutTag({ ...once, keys: { [groupRowName(7)]: 4 } },
                          groupRowName(7));
  assert.deepEqual(gone.groups[0].tags, []);
  assert.deepEqual(gone.keys, {});
});

test("a group row is not renamed and takes no counter tag", () => {
  const c = withGroupRow(cfg([group("g", [])]), 7, "Cats");
  const key = groupRowName(7);
  assert.equal(renameTag(c, key, "cats"), c, "a group is named in the library");
  assert.equal(counterOf(c, key), "", "no counter — there is no negative");
  assert.equal(sessionNegatives(c, [{ ref: { item_id: 1 }, chosen: [],
                                      eventIds: [] }]),
               undefined, "a group row is no implicit negative either");
});

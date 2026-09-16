import { strict as assert } from "node:assert";
import { test } from "node:test";
import { composeViewQuery } from "./viewQuery.ts";
import { tryParse } from "../query/tree.ts";

const base = {
  search: "",
  mediaKinds: [] as string[],
  untagged: false,
  groupNames: [] as string[],
};

test("no filters means exactly the typed search", () => {
  assert.equal(composeViewQuery({ ...base, search: "portrait" }), "portrait");
  assert.equal(composeViewQuery(base), "");
});

test("one kind is a plain INFO term, several become an OR group", () => {
  assert.equal(composeViewQuery({ ...base, mediaKinds: ["image"] }),
               "INFO:type=image");
  assert.equal(composeViewQuery({ ...base, mediaKinds: ["video", "image"] }),
               "(INFO:type=image|INFO:type=video)");
});

test("all three kinds checked is no filter at all", () => {
  assert.equal(
    composeViewQuery({ ...base, mediaKinds: ["image", "video", "sequence"] }),
    "");
});

test("the typed search is wrapped only beside other terms", () => {
  assert.equal(
    composeViewQuery({ ...base, search: "a|b", mediaKinds: ["image"] }),
    "(a|b) INFO:type=image");
  assert.equal(composeViewQuery({ ...base, search: "a|b" }), "a|b");
});

test("a group name with spaces is a quoted atom that parses back", () => {
  const q = composeViewQuery({ ...base, groupNames: ["My Folder"] });
  assert.equal(q, '"GROUP:My Folder"');
  const g = tryParse(q);
  assert.ok(g);
  assert.equal((g!.children[0] as { name: string }).name, "My Folder");
});

test("several groups OR together", () => {
  assert.equal(composeViewQuery({ ...base, groupNames: ["a", "b"] }),
               "(GROUP:a|GROUP:b)");
});

test("untagged says what the view showed", () => {
  assert.equal(composeViewQuery({ ...base, untagged: true }),
               "INFO:tag_count=0");
});

test("everything at once still parses", () => {
  const q = composeViewQuery({
    search: "portrait !draft",
    mediaKinds: ["image", "sequence"],
    untagged: true,
    groupNames: ["Trips", "New Group"],
  });
  assert.ok(tryParse(q), q);
});

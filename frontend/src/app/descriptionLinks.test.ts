import { test } from "node:test";
import assert from "node:assert/strict";

import { linkedTags, parseDescription, tagLink } from "./descriptionLinks.ts";

test("prose with no link is one piece of text", () => {
  assert.deepEqual(parseDescription("Exactly one girl."),
    [{ kind: "text", text: "Exactly one girl." }]);
  assert.deepEqual(parseDescription(""), []);
});

test("a tag link is the '#' spelling, and keeps its own label", () => {
  assert.deepEqual(parseDescription("see [open_mouth](#open_mouth) instead"), [
    { kind: "text", text: "see " },
    { kind: "tag", text: "open_mouth", name: "open_mouth" },
    { kind: "text", text: " instead" },
  ]);
  // The label need not be the name — a sentence reads better than a slug.
  assert.deepEqual(parseDescription("[an open mouth](#open_mouth)"),
    [{ kind: "tag", text: "an open mouth", name: "open_mouth" }]);
});

test("a tag name may hold parentheses, which is why the scan is balanced", () => {
  // Booru names carry them as a matter of course, and this is the case the
  // whole balanced-paren walk exists for.
  assert.deepEqual(parseDescription("[her](#traveler_(genshin_impact)) again"), [
    { kind: "tag", text: "her", name: "traveler_(genshin_impact)" },
    { kind: "text", text: " again" },
  ]);
});

test("a tag name may end in a colon, like any other", () => {
  assert.deepEqual(parseDescription("compare [d:](#d:)"), [
    { kind: "text", text: "compare " },
    { kind: "tag", text: "d:", name: "d:" },
  ]);
});

test("a web link is http(s), and nothing else is a link at all", () => {
  assert.deepEqual(parseDescription("the [wiki](https://example.org/a_b) says"), [
    { kind: "text", text: "the " },
    { kind: "web", text: "wiki", href: "https://example.org/a_b" },
    { kind: "text", text: " says" },
  ]);
  // NOT a link, and not mangled either: the prose stands as written.
  for (const s of ["[see also] (the wiki)", "[a](javascript:alert(1))",
                   "[a](mailto:x@y.z)", "[a](/local/path)", "[a]()", "[](#x)",
                   "an [unclosed link", "[a](#x", "[a](#x\nb)"]) {
    const got = parseDescription(s);
    assert.equal(got.every((p) => p.kind === "text"), true, s);
    assert.equal(got.map((p) => p.text).join(""), s, s);
  }
});

test("several links in one description, in order", () => {
  const got = parseDescription("[a](#a), [b](https://b.example), and [c](#c).");
  assert.deepEqual(got.map((p) => p.kind),
    ["tag", "text", "web", "text", "tag", "text"]);
  assert.deepEqual(linkedTags("[a](#a), [b](https://b.example), and [c](#c)."),
    ["a", "c"]);
  // Deduped, in first-mention order.
  assert.deepEqual(linkedTags("[x](#a) [y](#b) [z](#a)"), ["a", "b"]);
});

test("what the linker writes is what the parser reads", () => {
  const line = `see ${tagLink("open_mouth", "open_mouth")}`;
  assert.deepEqual(parseDescription(line)[1], {
    kind: "tag", text: "open_mouth", name: "open_mouth" });
});

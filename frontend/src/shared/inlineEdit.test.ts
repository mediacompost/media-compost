import { test } from "node:test";
import assert from "node:assert/strict";
import { inlineEditAction } from "./inlineEdit.ts";

const k = (key: string, meta = false) => ({ key, metaKey: meta, ctrlKey: false });

test("Enter commits and Escape cancels", () => {
  assert.equal(inlineEditAction(k("Enter")), "commit");
  assert.equal(inlineEditAction(k("Escape")), "cancel");
  assert.equal(inlineEditAction(k("a")), null);
});

test("a multi-line field commits only on ⌘/Ctrl+Enter", () => {
  assert.equal(inlineEditAction(k("Enter"), { metaEnter: true }), null);
  assert.equal(inlineEditAction(k("Enter", true), { metaEnter: true }), "commit");
  assert.equal(inlineEditAction(k("Escape"), { metaEnter: true }), "cancel");
});

import { test } from "node:test";
import assert from "node:assert/strict";
import { offeredLastAction, parseLastAction, serializeLastAction } from "./ctxLastUsed.ts";

const faces = { kind: "faces", model: "insightface_faces", task: "Detect faces", name: "InsightFace" };

test("the record round-trips and garbage reads as nothing", () => {
  assert.deepEqual(parseLastAction(serializeLastAction(faces)), faces);
  assert.equal(parseLastAction(null), null);
  assert.equal(parseLastAction("{"), null);
  assert.equal(parseLastAction(JSON.stringify({ kind: "faces" })), null);
  assert.equal(parseLastAction(JSON.stringify({ ...faces, model: "" })), null);
});

test("it is offered only while the menu offers the kind AND that model", () => {
  const rows = [
    { tk: { kind: "faces" }, models: [{ id: "insightface_faces" }, { id: "anime_face_magi" }] },
    { tk: { kind: "tag" }, models: [{ id: "wd_tagger" }] },
  ];
  assert.equal(offeredLastAction(faces, rows)?.row, rows[0]);
  // A video selection offers no face detector: no row.
  assert.equal(offeredLastAction(faces, [rows[1]]), null);
  // The model has gone (removed, or no longer ready): no row.
  assert.equal(offeredLastAction({ ...faces, model: "gone" }, rows), null);
  assert.equal(offeredLastAction(null, rows), null);
});

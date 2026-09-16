/**
 * Which repo ids get a Hugging Face link in the Models tab.
 *
 * The field holds a hub id for a built-in or hub-added model and a
 * FILESYSTEM PATH for one added as local, so linking it blindly points at a
 * page that cannot exist. Pure, so the shapes are stated rather than clicked.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { hubUrl } from "./util.ts";

test("a plain owner/name id links to its model page", () => {
  assert.equal(hubUrl("stabilityai/stable-diffusion-xl-base-1.0"),
    "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0");
  assert.equal(hubUrl("lodestones/Chroma1-HD"),
    "https://huggingface.co/lodestones/Chroma1-HD");
});

test("a local model never links, whatever its path looks like", () => {
  // A POSIX path has the same one-slash shape as a repo id.
  assert.equal(hubUrl("models/my-sdxl", true), "");
  assert.equal(hubUrl("C:\\models\\sdxl", true), "");
});

test("anything path-shaped is left as text", () => {
  assert.equal(hubUrl("C:\\models\\sdxl"), "");
  assert.equal(hubUrl("/home/me/models/sdxl"), "");
  assert.equal(hubUrl("D:/models/sdxl"), "");
  // Too many or too few segments to be an id.
  assert.equal(hubUrl("owner/name/extra"), "");
  assert.equal(hubUrl("justaname"), "");
  // A single-file checkpoint is a file, not a repo page.
  assert.equal(hubUrl("owner/model.safetensors"), "");
});

test("blank input yields no link", () => {
  assert.equal(hubUrl(""), "");
  assert.equal(hubUrl("   "), "");
});

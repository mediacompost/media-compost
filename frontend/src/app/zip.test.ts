// Run with: npm test  (Node's built-in test runner + type stripping).
// Validates the archive bytes structurally and cross-checks the CRCs against
// Node's own zlib.crc32, so a broken header can't slip through unnoticed.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  MAX_ENTRIES, ZipBuilder, crc32, crcFinal, crcInit, crcUpdate,
} from "./zip.ts";

const enc = (s: string) => new TextEncoder().encode(s) as Uint8Array<ArrayBuffer>;

async function bytesOf(blob: Blob): Promise<DataView> {
  return new DataView(await blob.arrayBuffer());
}

test("crc32 matches the standard values", () => {
  assert.equal(crc32(enc("")), 0);
  assert.equal(crc32(enc("123456789")), 0xcbf43926);
  assert.equal(crc32(enc("The quick brown fox jumps over the lazy dog")), 0x414fa339);
});

test("archive has local headers, a central directory and a valid EOCD", async () => {
  const z = new ZipBuilder();
  z.add("1.json", enc('{"id":1}'));
  z.add("1.png", enc("PNGDATA"));
  assert.equal(z.count, 2);
  const view = await bytesOf(z.finish());

  // First local file header.
  assert.equal(view.getUint32(0, true), 0x04034b50);
  assert.equal(view.getUint16(8, true), 0, "stored, not deflated");
  assert.equal(view.getUint32(14, true), crc32(enc('{"id":1}')));
  assert.equal(view.getUint32(18, true), 8, "compressed size = raw size");

  // End of central directory sits in the last 22 bytes.
  const eocd = view.byteLength - 22;
  assert.equal(view.getUint32(eocd, true), 0x06054b50);
  assert.equal(view.getUint16(eocd + 8, true), 2, "two entries on this disk");
  assert.equal(view.getUint16(eocd + 10, true), 2);
  const dirSize = view.getUint32(eocd + 12, true);
  const dirStart = view.getUint32(eocd + 16, true);
  assert.equal(dirStart + dirSize, eocd, "central directory ends where the EOCD starts");
  assert.equal(view.getUint32(dirStart, true), 0x02014b50);
});

test("central directory offsets point at their local headers", async () => {
  const z = new ZipBuilder();
  z.add("a.txt", enc("aaaa"));
  z.add("bb.txt", enc("bbbbbbbb"));
  const view = await bytesOf(z.finish());
  const eocd = view.byteLength - 22;
  let p = view.getUint32(eocd + 16, true);
  for (const [name, size] of [["a.txt", 4], ["bb.txt", 8]] as const) {
    assert.equal(view.getUint32(p, true), 0x02014b50);
    assert.equal(view.getUint32(p + 24, true), size);
    const nameLen = view.getUint16(p + 28, true);
    const local = view.getUint32(p + 42, true);
    assert.equal(view.getUint32(local, true), 0x04034b50, "offset lands on a local header");
    const localNameLen = view.getUint16(local + 26, true);
    const bytes = new Uint8Array(view.buffer, local + 30, localNameLen);
    assert.equal(new TextDecoder().decode(bytes), name);
    p += 46 + nameLen;
  }
});

test("size tracks the bytes written, so callers can split on it", async () => {
  const z = new ZipBuilder();
  assert.equal(z.size, 0);
  z.add("x", enc("12345"));
  // local header (30) + name (1) + data (5)
  assert.equal(z.size, 36);
});

test("streaming CRC equals the one-shot on random buffers, any chunking", () => {
  // Deterministic PRNG so a failure reproduces.
  let s = 12345;
  const rand = () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32);
  for (let round = 0; round < 25; round++) {
    const len = Math.floor(rand() * 4096);
    const buf = new Uint8Array(len);
    for (let i = 0; i < len; i++) buf[i] = Math.floor(rand() * 256);
    let state = crcInit();
    let at = 0;
    while (at < len) {
      const n = 1 + Math.floor(rand() * 700);
      state = crcUpdate(state, buf.subarray(at, at + n));
      at += n;
    }
    assert.equal(crcFinal(state), crc32(buf), `round ${round}, len ${len}`);
  }
  assert.equal(crcFinal(crcInit()), crc32(new Uint8Array(0)), "empty input");
});

test("a Blob entry with precomputed crc/size is byte-identical to the bytes path", async () => {
  const when = new Date(2024, 5, 14, 12, 30, 20);
  const payload = enc("PRETEND-IMAGE-DATA");
  const json = enc('{"uid":"abc"}');

  const a = new ZipBuilder();
  a.add("x.png", payload, when);
  a.add("x.json", json, when);
  const wantBytes = new Uint8Array(await a.finish().arrayBuffer());

  const b = new ZipBuilder();
  b.add("x.png", new Blob([payload]), { crc: crc32(payload), size: payload.length }, when);
  b.add("x.json", json, when);
  const gotBytes = new Uint8Array(await b.finish().arrayBuffer());
  assert.deepEqual(gotBytes, wantBytes);
});

test("a Blob entry's central directory parses like any other", async () => {
  const data = enc("blob-bytes-here");
  const z = new ZipBuilder();
  z.add("b.bin", new Blob([data]), { crc: crc32(data), size: data.length });
  const view = await bytesOf(z.finish());
  const eocd = view.byteLength - 22;
  assert.equal(view.getUint32(eocd, true), 0x06054b50);
  assert.equal(view.getUint16(eocd + 8, true), 1);
  const p = view.getUint32(eocd + 16, true);
  assert.equal(view.getUint32(p, true), 0x02014b50);
  assert.equal(view.getUint32(p + 16, true), crc32(data), "stored CRC");
  assert.equal(view.getUint32(p + 24, true), data.length, "uncompressed size");
  const local = view.getUint32(p + 42, true);
  assert.equal(view.getUint32(local, true), 0x04034b50);
  const nameLen = view.getUint16(local + 26, true);
  const body = new Uint8Array(view.buffer, local + 30 + nameLen, data.length);
  assert.deepEqual(body, data, "payload bytes are in place");
});

test("a Blob whose size disagrees with the declared size is refused", () => {
  const z = new ZipBuilder();
  assert.throws(
    () => z.add("x", new Blob([enc("1234")]), { crc: 0, size: 99 }),
    /size/);
  assert.throws(
    () => z.add("x", new Blob([enc("1234")]) as unknown as Blob),
    /crc, size/);
});

test("the entry count is capped below the EOCD's uint16", () => {
  const z = new ZipBuilder();
  const empty = new Uint8Array(0) as Uint8Array<ArrayBuffer>;
  for (let i = 0; i < MAX_ENTRIES; i++) z.add("e", empty);
  assert.equal(z.count, MAX_ENTRIES);
  assert.throws(() => z.add("one-too-many", empty), /entry limit/);
});

test("UTF-8 names survive the round trip", async () => {
  const z = new ZipBuilder();
  z.add("äöü — 猫.json", enc("{}"));
  const view = await bytesOf(z.finish());
  assert.equal(view.getUint16(6, true) & 0x0800, 0x0800, "UTF-8 flag set");
  const nameLen = view.getUint16(26, true);
  const name = new TextDecoder().decode(new Uint8Array(view.buffer, 30, nameLen));
  assert.equal(name, "äöü — 猫.json");
});

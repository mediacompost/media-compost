// A minimal ZIP writer for the grid's in-browser export.
//
// Entries are STORED (no compression): the payload is already-compressed
// image/video data plus small JSON files, so deflate would cost CPU for
// almost nothing. Each entry's bytes are handed to a Blob part immediately
// and never kept as an ArrayBuffer — a caller can pass a Blob directly (with
// the CRC/size it computed while streaming), so part bytes may live in Blobs
// the browser is free to spill to disk. Memory stays close to one file at a
// time no matter how big the archive gets.
//
// Only ZIP32 structures are emitted — callers split archives well below the
// 4 GB limit, and `add` REFUSES the 65,535th entry rather than writing an
// EOCD whose uint16 entry count silently wrapped.

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[i] = c >>> 0;
  }
  return t;
})();

// ---- streaming CRC-32 ------------------------------------------------------
// The one-shot crc32() below is crcFinal(crcUpdate(crcInit(), bytes)); the
// split form lets a caller fold in a download chunk by chunk without ever
// holding the whole file.

export function crcInit(): number {
  return 0xffffffff;
}

export function crcUpdate(state: number, chunk: Uint8Array): number {
  let c = state >>> 0;
  for (let i = 0; i < chunk.length; i++) c = CRC_TABLE[(c ^ chunk[i]) & 0xff] ^ (c >>> 8);
  return c >>> 0;
}

export function crcFinal(state: number): number {
  return (state ^ 0xffffffff) >>> 0;
}

export function crc32(bytes: Uint8Array): number {
  return crcFinal(crcUpdate(crcInit(), bytes));
}

/** DOS date/time pair (ZIP's original timestamp format). */
function dosTime(d: Date): { time: number; date: number } {
  return {
    time: (d.getHours() << 11) | (d.getMinutes() << 5) | (Math.floor(d.getSeconds() / 2)),
    date: ((d.getFullYear() - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate(),
  };
}

interface Entry {
  nameBytes: Uint8Array<ArrayBuffer>;
  crc: number;
  size: number;
  offset: number;
  time: number;
  date: number;
}

/** The EOCD's entry counts are uint16, so one archive holds at most this many
 *  entries — past it `add` throws and the caller must split. */
export const MAX_ENTRIES = 65534;

export class ZipBuilder {
  private parts: BlobPart[] = [];
  private entries: Entry[] = [];
  private offset = 0;

  /** Bytes written so far (data + headers) — used to decide when to split. */
  get size(): number { return this.offset; }
  get count(): number { return this.entries.length; }

  /** Append one stored entry. `data` may be raw bytes (CRC/size are computed
   *  here) or a Blob — then `meta` must carry the CRC and byte size the caller
   *  computed while collecting it (crcInit/crcUpdate/crcFinal). */
  add(
    name: string,
    data: Uint8Array<ArrayBuffer> | Blob,
    metaOrWhen?: { crc: number; size: number } | Date,
    when: Date = new Date(),
  ) {
    if (this.entries.length >= MAX_ENTRIES) {
      throw new Error(
        `ZIP entry limit reached (${MAX_ENTRIES}); split into another archive`);
    }
    const meta = metaOrWhen instanceof Date || metaOrWhen == null ? null : metaOrWhen;
    if (metaOrWhen instanceof Date) when = metaOrWhen;
    let crc: number;
    let size: number;
    if (data instanceof Blob) {
      if (!meta) throw new Error("Blob entries need a precomputed { crc, size }");
      crc = meta.crc;
      size = meta.size;
      if (data.size !== size) {
        throw new Error(`Blob size ${data.size} != declared size ${size} for ${name}`);
      }
    } else {
      crc = meta ? meta.crc : crc32(data);
      size = data.length;
    }
    const nameBytes = new TextEncoder().encode(name);
    const { time, date } = dosTime(when);
    const header = new DataView(new ArrayBuffer(30));
    header.setUint32(0, 0x04034b50, true);  // local file header signature
    header.setUint16(4, 20, true);          // version needed (2.0 = store)
    header.setUint16(6, 0x0800, true);      // flags: UTF-8 names
    header.setUint16(8, 0, true);           // method: store
    header.setUint16(10, time, true);
    header.setUint16(12, date, true);
    header.setUint32(14, crc, true);
    header.setUint32(18, size, true);
    header.setUint32(22, size, true);
    header.setUint16(26, nameBytes.length, true);
    header.setUint16(28, 0, true);          // extra field length
    this.parts.push(header.buffer, nameBytes, data);
    this.entries.push({ nameBytes, crc, size, offset: this.offset, time, date });
    this.offset += 30 + nameBytes.length + size;
  }

  /** Close the archive and return it as a Blob (the builder is spent after). */
  finish(): Blob {
    const dirStart = this.offset;
    for (const e of this.entries) {
      const rec = new DataView(new ArrayBuffer(46));
      rec.setUint32(0, 0x02014b50, true);   // central directory signature
      rec.setUint16(4, 20, true);           // version made by
      rec.setUint16(6, 20, true);           // version needed
      rec.setUint16(8, 0x0800, true);       // flags: UTF-8 names
      rec.setUint16(10, 0, true);           // method: store
      rec.setUint16(12, e.time, true);
      rec.setUint16(14, e.date, true);
      rec.setUint32(16, e.crc, true);
      rec.setUint32(20, e.size, true);
      rec.setUint32(24, e.size, true);
      rec.setUint16(28, e.nameBytes.length, true);
      rec.setUint16(30, 0, true);           // extra
      rec.setUint16(32, 0, true);           // comment
      rec.setUint16(34, 0, true);           // disk number
      rec.setUint16(36, 0, true);           // internal attrs
      rec.setUint32(38, 0, true);           // external attrs
      rec.setUint32(42, e.offset, true);    // local header offset
      this.parts.push(rec.buffer, e.nameBytes);
      this.offset += 46 + e.nameBytes.length;
    }
    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true);     // end of central directory
    end.setUint16(4, 0, true);
    end.setUint16(6, 0, true);
    end.setUint16(8, this.entries.length, true);
    end.setUint16(10, this.entries.length, true);
    end.setUint32(12, this.offset - dirStart, true);
    end.setUint32(16, dirStart, true);
    end.setUint16(20, 0, true);             // comment length
    this.parts.push(end.buffer);
    const blob = new Blob(this.parts, { type: "application/zip" });
    this.parts = [];
    this.entries = [];
    return blob;
  }
}

// "Download the current view" — builds ZIP archives in the BROWSER (nothing is
// generated on the server) containing, per item, its active file. THE MEDIA
// AND NOTHING ELSE.
//
// It used to write a JSON sidecar of the same name beside every picture,
// carrying the item's groups, links, tags and captions. That is gone (owner
// decision, 2026-09) and is not coming back: a second, frozen description of
// the library, shaped by whatever this one dialog happened to export, is the
// sidecar idea the storage layer already deleted once. What it was for is the
// PYTHON API — `open_library()` reads and edits everything the UI does, so a
// script writes exactly the export somebody actually needs (see
// docs/python-api.md).
//
// Archives are split at ~1 GB: each item's bytes go straight into a Blob part
// and the builder is finished/downloaded once it crosses the limit, so RAM
// stays near one file at a time however large the library is.
import React, { useRef, useState } from "react";
import { IconButton } from "../../shared/IconButton";
import { api, ItemOut } from "../api";
import { Icon } from "../../shared/Icon";
import { confirm } from "../../shared/ConfirmModal";
import { useNum, useT } from "../i18n";
import { downloadBlob } from "../csv";
import { ZipBuilder, crcFinal, crcInit, crcUpdate } from "../zip";

const SPLIT_BYTES = 1024 * 1024 * 1024; // 1 GB per archive
// Entries per archive — one per item now that nothing rides beside the media.
// Well under the ZIP EOCD's uint16 limit, which ZipBuilder enforces by
// throwing.
const SPLIT_ENTRIES = 60_000;
// Past this many items the export asks first — it downloads every file in the
// view, which on a big library is a long, bandwidth-heavy run.
const CONFIRM_OVER = 200;

function extOf(name: string, format: string): string {
  const dot = name.lastIndexOf(".");
  if (dot > 0 && dot > name.length - 7) return name.slice(dot + 1).toLowerCase();
  return (format || "bin").toLowerCase();
}

export function GridExportButton({ items, total, iterate }: {
  // Items already loaded in the grid (used when everything is loaded).
  items: ItemOut[];
  total: number;
  // Streams the FULL current view page by page (the grid is windowed), so the
  // export never holds the whole view's metadata in one array.
  iterate: (pageSize?: number) => AsyncGenerator<ItemOut, void, void>;
}) {
  const t = useT();
  const num = useNum();
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(0);
  const [ofN, setOfN] = useState(0);
  const [part, setPart] = useState(1);
  const [error, setError] = useState("");
  const cancelled = useRef(false);

  const run = async () => {
    const exporting = items.length >= total ? items.length : total;
    if (exporting > CONFIRM_OVER) {
      const archives = Math.max(1, Math.ceil(exporting / SPLIT_ENTRIES));
      if (!(await confirm({
        title: t("Export {n} items (~{m} archives)?",
                 { n: num(exporting), m: String(archives) }),
        body: t("This downloads every file in the view."),
        answer: { label: t("Export") },
      }))) return;
    }
    setBusy(true);
    setError("");
    setDone(0);
    setPart(1);
    cancelled.current = false;
    try {
      // Everything loaded → walk the in-memory list; otherwise stream the view
      // through the async generator (for-await accepts both).
      const source: AsyncGenerator<ItemOut, void, void> | ItemOut[] =
        items.length >= total ? items : iterate();
      setOfN(items.length >= total ? items.length : total);
      const stamp = new Date().toISOString().slice(0, 10);
      let zip = new ZipBuilder();
      let partNo = 1;
      let inPart = 0;
      const flush = () => {
        if (inPart === 0) return;
        downloadBlob(`media-compost-${stamp}-part${partNo}.zip`, zip.finish());
        zip = new ZipBuilder();
        partNo++;
        inPart = 0;
        setPart(partNo);
      };
      let done = 0;
      for await (const it of source) {
        if (cancelled.current) break;
        // The item's own detail, for the ACTIVE FILE alone: the archive's
        // entry name is the file's extension, and `ItemOut` carries the
        // item's name rather than the active file's — which differ the
        // moment an editor save adds a WebP under an item still called
        // ".png".
        const detail = await api.item(it.id);
        const active = detail.files.find((f) => f.id === detail.active_file_id) ?? detail.files[0];
        if (!active) continue;
        // Stream the body chunk by chunk: the CRC folds in as chunks arrive
        // and the bytes land in a Blob (which the browser may spill to disk)
        // instead of one Uint8Array held until finish().
        const resp = await fetch(api.fileUrl(active.id));
        if (!resp.ok) throw new Error(`fetch failed (${resp.status}) for item ${detail.uid || detail.id}`);
        let crc = crcInit();
        let size = 0;
        const chunks: BlobPart[] = [];
        if (resp.body) {
          const reader = resp.body.getReader();
          for (;;) {
            const { done: eof, value } = await reader.read();
            if (eof) break;
            crc = crcUpdate(crc, value);
            size += value.byteLength;
            chunks.push(value);
          }
        } else {
          const bytes = new Uint8Array(await resp.arrayBuffer());
          crc = crcUpdate(crc, bytes);
          size = bytes.length;
          chunks.push(bytes);
        }
        // Named by the item's stable uid, so the file keeps its identity
        // independently of this library's internal numbering.
        const base = detail.uid || String(detail.id);
        zip.add(`${base}.${extOf(active.names?.[0]?.name ?? "", active.format)}`,
          new Blob(chunks), { crc: crcFinal(crc), size });
        inPart += size;
        done += 1;
        setDone(done);
        // Split once this archive crossed a limit. The entry cap keeps every
        // part legal ZIP32 — the EOCD's entry count is uint16, and ZipBuilder
        // throws rather than wrapping it.
        if (zip.size >= SPLIT_BYTES || zip.count >= SPLIT_ENTRIES) flush();
      }
      flush();
    } catch (e) {
      setError(String(e).replace(/^Error:\s*/, ""));
    }
    setBusy(false);
  };

  if (total === 0) return null;
  return (
    <>
      <IconButton icon={busy ? "close" : "download"} size={22} glyph={16} color={busy ? "var(--accent)" : "var(--muted-2)"} active={busy}
        onClick={() => (busy ? (cancelled.current = true) : void run())}
        title={busy ? t("Cancel the export") : t("Download every item in this view as ZIP archives")} style={{ marginRight: 2 }} />
      {busy && (
        <span style={{ fontFamily: "var(--mono)", fontSize: "var(--fs-2)", color: "var(--accent)", marginRight: 6 }}>
          {ofN ? `${done}/${ofN}` : t("preparing…")}{part > 1 ? ` · ${t("part")} ${part}` : ""}
        </span>
      )}
      {error && (
        <span title={error} style={{ fontSize: "var(--fs-2)", color: "var(--red-text)", marginRight: 6,
                                     maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis",
                                     whiteSpace: "nowrap" }}>
          {t("Export failed")}: {error}
        </span>
      )}
    </>
  );
}

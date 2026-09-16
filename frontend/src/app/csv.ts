// Minimal RFC 4180 CSV reader/writer for the tag import/export. Handles
// quoted fields (with doubled quotes and embedded separators/newlines) and
// auto-detects the delimiter, since spreadsheets export comma, semicolon or
// tab depending on locale.

export function detectDelimiter(text: string): string {
  // Count candidates in the first non-empty line that is OUTSIDE quotes.
  const line = text.split(/\r?\n/).find((l) => l.trim() !== "") ?? "";
  let best = ",", bestN = 0;
  for (const d of [",", ";", "\t", "|"]) {
    let n = 0, quoted = false;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (c === '"') quoted = !quoted;
      else if (!quoted && c === d) n++;
    }
    if (n > bestN) { best = d; bestN = n; }
  }
  return best;
}

/** Parse CSV text into rows of cells. Empty trailing lines are dropped. */
export function parseCsv(text: string, delimiter?: string): string[][] {
  const d = delimiter ?? detectDelimiter(text);
  const src = text.replace(/^﻿/, ""); // strip BOM
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < src.length; i++) {
    const c = src[i];
    if (quoted) {
      if (c === '"') {
        if (src[i + 1] === '"') { cell += '"'; i++; }
        else quoted = false;
      } else cell += c;
      continue;
    }
    if (c === '"' && cell === "") { quoted = true; continue; }
    if (c === d) { row.push(cell); cell = ""; continue; }
    if (c === "\n" || c === "\r") {
      if (c === "\r" && src[i + 1] === "\n") i++;
      row.push(cell); cell = "";
      rows.push(row); row = [];
      continue;
    }
    cell += c;
  }
  if (cell !== "" || row.length > 0) { row.push(cell); rows.push(row); }
  return rows.filter((r) => r.some((v) => v.trim() !== ""));
}

function quoteCell(v: string, d: string): string {
  return v.includes(d) || v.includes('"') || v.includes("\n") || v.includes("\r")
    ? `"${v.replace(/"/g, '""')}"`
    : v;
}

export function toCsv(rows: (string | number)[][], delimiter = ","): string {
  return rows
    .map((r) => r.map((v) => quoteCell(String(v ?? ""), delimiter)).join(delimiter))
    .join("\r\n");
}

/** Trigger a browser download of `text` as `filename`. */
export function downloadText(filename: string, text: string, mime = "text/csv") {
  // The BOM keeps Excel from mangling non-ASCII tag names.
  const blob = new Blob(["﻿" + text], { type: `${mime};charset=utf-8` });
  downloadBlob(filename, blob);
}

export function downloadBlob(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoke late: Safari cancels an in-flight download when the URL dies early.
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

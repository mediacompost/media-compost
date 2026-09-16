/** IMPORT A CSV AS A NEW TAG SET — a booru dump, or any spreadsheet with a
 *  name column. The file arrives from the Sets tab's "Import from file…"
 *  (`useTagSetFileImport` hands a CSV here and a JSON export to the
 *  importer); name the set, correct the header guess (`tagSetCsv.ts` made
 *  it), press Import: the set is CREATED and the rows go to
 *  `POST /{id}/entries/bulk` in chunks of 2000, one request at a time, with a
 *  Stop between them. What has landed by then stays — each chunk is its own
 *  logged, revertible write, and the set is one whether or not the run
 *  finished. From the "+" pill a CSV makes a NEW set; from the list's Add
 *  entry menu (`into`) it lands in the set on screen, and the "existing
 *  entry" rule below is then about that set's rows as well as a name the
 *  file lists twice. */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { SectionHeading } from "../../shared/SectionHeading";
import { ProgressBar } from "../../shared/ProgressBar";
import { filterNumeric } from "../../shared/useNumericText";
import { RowShell } from "../../shared/SettingsRows";
import { fieldStyleSm } from "../../shared/Field";

import { api, TagSetOut } from "../api";
import { chunks, runBulk } from "../bulk";
import { parseCsv } from "../csv";
import { useErrText, useT, useTn } from "../i18n";
import {
  CSV_FIELDS, ColumnMap, CsvField, csvToBulkRows, guessColumns, looksLikeHeader,
} from "../tagSetCsv";
import { Icon } from "../../shared/Icon";
import { Overlay } from "../../shared/Overlay";
import { Button } from "../../shared/Button";
import { Switch } from "../../shared/Switch";

const csvField: React.CSSProperties = { ...fieldStyleSm, width: undefined };

const CHUNK = 2000;

export function TagSetCsvOverlay({ file, into = null, taken, onClose, onDone }: {
  /** The picked file; the dialog opens over it already parsed. */
  file: File;
  /** The set to import INTO; null makes a new one, named in the dialog. */
  into?: TagSetOut | null;
  /** The other sets' names, lowercased — a set's name is unique, and the
   *  dialog says so before the server does. */
  taken: readonly string[];
  onClose: () => void;
  /** The set the run made — picked in the list, whether or not every row
   *  landed. */
  onDone: (set: TagSetOut) => void;
}) {
  const t = useT();
  const tn = useTn();
  const errText = useErrText();
  const fileRef = useRef<HTMLInputElement>(null);
  const [table, setTable] = useState<string[][] | null>(null);
  const [filename, setFilename] = useState("");
  // The set's name, prefilled from the file's — "danbooru-tags.csv" is a
  // set called "danbooru-tags" until somebody says otherwise.
  const [name, setName] = useState(file.name.replace(/\.[^.]+$/, ""));
  const made = useRef<TagSetOut | null>(into);
  const [map, setMap] = useState<ColumnMap>({});
  const [hasHeader, setHasHeader] = useState(true);
  // The count floor, as typed — "" is none. Only meaningful with a count
  // column mapped, and shown only then.
  const [minCount, setMinCount] = useState("");
  const [existing, setExisting] = useState<"keep" | "update" | "replace">("keep");
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null);
  const [result, setResult] = useState<{ created: number; updated: number; errors: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  const load = async (f: File) => {
    const rows = parseCsv(await f.text()).filter((r) => r.some((c) => c.trim()));
    setFilename(f.name);
    setTable(rows);
    const header = rows.length > 0 && looksLikeHeader(rows[0]);
    setHasHeader(header);
    setMap(header ? guessColumns(rows[0]) : { name: 0 });
    setResult(null);
    setError(null);
  };
  useEffect(() => { void load(file); }, [file]);  // eslint-disable-line react-hooks/exhaustive-deps

  const width = table?.[0]?.length ?? 0;
  const minN = map.count != null && /^\d+$/.test(minCount.trim()) ? Number(minCount.trim()) : 0;
  const parsed = useMemo(
    () => table ? csvToBulkRows(table, map, { hasHeader, minCount: minN }) : null,
    [table, map, hasHeader, minN]);
  // The preview: the first rows as they will be imported, one column per
  // MAPPED field — the item-tag import's shape, and the one way to see
  // that the header guess was right before 40,000 rows go in.
  const previewFields = CSV_FIELDS.filter((f) => map[f] != null);
  const preview = (parsed?.rows ?? []).slice(0, 4);
  const previewGrid = `repeat(${previewFields.length}, minmax(90px, 1fr))`;
  const previewCell = (r: (typeof preview)[number], f: CsvField): string =>
    f === "name" ? r.name
    : f === "description" ? r.description ?? ""
    : f === "count" ? (r.count == null ? "" : String(r.count))
    // The preview says what the cell WILL MEAN, so it shows the trail the
    // way the app draws one — the row already holds the split names.
    : f === "category" ? (r.category ?? []).join(" › ")
    : f === "implies" ? (r.implies ?? []).join(", ")
    : (r.aliases ?? []).join(", ");
  const busy = progress != null;
  const nameTaken = !into && taken.includes(name.trim().toLowerCase());
  const canImport = !!parsed && parsed.rows.length > 0 && map.name != null && !busy
    && (into != null || (name.trim() !== "" && !nameTaken && made.current == null));

  const start = async () => {
    if (!parsed || !canImport) return;
    const ctrl = new AbortController();
    abort.current = ctrl;
    const batches = chunks(parsed.rows, CHUNK);
    let created = 0, updated = 0, errors = 0;
    setProgress({ done: 0, total: parsed.rows.length });
    setError(null);
    try {
      // The set first, then its rows: once it exists the run has somewhere
      // to land, and a Stop mid-way leaves a real set holding what arrived.
      const set = made.current ?? await api.createTagSet({ name: name.trim() });
      made.current = set;
      const r = await runBulk(batches, async (batch) => {
        const out = await api.bulkTagSetEntries(set.id, batch, existing);
        created += out.created; updated += out.updated; errors += out.errors.length;
      }, {
        chunk: 1, signal: ctrl.signal,
        onProgress: (done) => setProgress({
          done: Math.min(parsed.rows.length, done * CHUNK), total: parsed.rows.length }),
      });
      setResult({ created, updated, errors });
      if (!r.aborted && errors === 0) onDone(set);
    } catch (e) {
      setError(errText(e));
    } finally {
      setProgress(null);
      abort.current = null;
    }
  };

  const columnName = (i: number) => hasHeader && table?.[0]?.[i]
    ? table[0][i] : t("Column {n}", { n: String(i + 1) });
  const label: Record<CsvField, string> = {
    name: t("Tag"), description: t("Description"), count: t("Count"),
    category: t("Category"), aliases: t("Aliases"), implies: t("Implies"),
  };

  return (
    <Overlay icon="upload_file" title={t("Import CSV")}
      subtitle={into ? into.name : t("A new set from the file")} width={620}
      onClose={() => made.current ? onDone(made.current) : onClose()}
      footer={
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, alignItems: "center" }}>
          {error && <span style={{ color: "var(--red-text)", fontSize: "var(--fs-3)", marginRight: "auto" }}>{error}</span>}
          {result && !error && (
            <span style={{ color: "var(--muted)", fontSize: "var(--fs-3)", marginRight: "auto" }}>
              {t("{created} added, {updated} updated, {errors} refused", {
                created: String(result.created), updated: String(result.updated),
                errors: String(result.errors) })}
            </span>
          )}
          {busy ? (
            <Button variant="ghost" onClick={() => abort.current?.abort()} icon="stop">{t("Stop")}</Button>
          ) : (
            <Button variant="ghost" onClick={() => made.current ? onDone(made.current) : onClose()} icon="close">
              {result ? t("Close") : t("Cancel")}
            </Button>
          )}
          <Button variant="primary" onClick={() => void start()} icon="upload_file" disabled={!canImport}>
            {parsed ? tn({ one: "Import {n} entry", other: "Import {n} entries" }, parsed.rows.length)
                    : t("Import")}
          </Button>
        </div>
      }>
      <div style={{ display: "flex", flexDirection: "column", gap: 14, padding: 18 }}>
        <input ref={fileRef} type="file" accept=".csv,.tsv,.txt,text/csv" style={{ display: "none" }}
               onChange={(e) => { const f = e.target.files?.[0]; if (f) void load(f); e.target.value = ""; }} />
        <div
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f) void load(f); }}
          onClick={() => fileRef.current?.click()}
          style={{ border: "1px dashed var(--border-strong)", borderRadius: "var(--r-6)", padding: "14px 16px",
                   display: "flex", alignItems: "center", gap: 10, cursor: "pointer",
                   color: "var(--muted)", fontSize: "var(--fs-3)" }}>
          <Icon name="upload_file" size={18} />
          {filename
            ? <span><b style={{ color: "var(--text)" }}>{filename}</b> · {tn({ one: "{n} row", other: "{n} rows" }, (table?.length ?? 0) - (hasHeader ? 1 : 0))}</span>
            : t("Drop a CSV here, or click to choose one — a booru tag dump, or any sheet with a tag column.")}
        </div>

        {table && (
          <>
            {!into && <div>
              <div style={{ fontSize: "var(--fs-3)", marginBottom: 6 }}>{t("Name")}</div>
              <input value={name} onChange={(e) => setName(e.target.value)}
                     placeholder={t("My tags")} disabled={busy || made.current != null}
                     style={{ ...csvField, width: "100%",
                              borderColor: nameTaken ? "var(--red)" : undefined }} />
              {nameTaken && (
                <div style={{ fontSize: "var(--fs-2)", color: "var(--red-text)", marginTop: 4 }}>
                  {t("A set with that name already exists.")}
                </div>
              )}
            </div>}
            <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "8px 12px", alignItems: "center" }}>
              {CSV_FIELDS.map((f) => (
                <React.Fragment key={f}>
                  <span style={{ fontSize: "var(--fs-3)", color: f === "name" ? "var(--text)" : "var(--muted)" }}>
                    {label[f]}{f === "name" ? "" : ` (${t("optional")})`}
                  </span>
                  <select value={map[f] ?? ""} style={csvField}
                          onChange={(e) => setMap((m) => {
                            const n = { ...m };
                            if (e.target.value === "") delete n[f]; else n[f] = Number(e.target.value);
                            return n;
                          })}>
                    <option value="">—</option>
                    {Array.from({ length: width }, (_, i) => (
                      <option key={i} value={i}>{columnName(i)}</option>
                    ))}
                  </select>
                </React.Fragment>
              ))}
            </div>
            <Row label={t("First row is a header")}><Switch checked={hasHeader} onChange={setHasHeader} title={t("First row is a header")} /></Row>
            {map.count != null && (
              // A dump lists every tag ever used once; the floor is how
              // the ones worth describing are kept. A row with no count
              // stays — the rule is about the figure.
              <Row label={t("Minimum count")}>
                <input value={minCount} inputMode="numeric" placeholder="0"
                       onChange={(e) => { if (filterNumeric(e.target.value, { integer: true }) != null) setMinCount(e.target.value); }}
                       style={{ ...csvField, width: 110, textAlign: "right", fontFamily: "var(--mono)" }} />
              </Row>
            )}
            {into && (
              // Only INTO a set: a new set is empty, so the question has no
              // answer there and was one more control on every import.
              <Row label={t("An entry the set already has")}>
                <select value={existing} onChange={(e) => setExisting(e.target.value as typeof existing)} style={csvField}>
                  <option value="keep">{t("keeps what it says")}</option>
                  <option value="update">{t("takes the file's non-empty fields")}</option>
                  <option value="replace">{t("becomes the file's row")}</option>
                </select>
              </Row>
            )}
            {parsed && (
              <div style={{ fontSize: "var(--fs-3)", color: "var(--muted)" }}>
                {tn({ one: "{n} entry to import", other: "{n} entries to import" }, parsed.rows.length)}
                {parsed.skipped > 0 && ` · ${tn({ one: "{n} row skipped (blank or repeated name)", other: "{n} rows skipped (blank or repeated names)" }, parsed.skipped)}`}
                {parsed.belowMin > 0 && ` · ${tn({ one: "{n} row under the minimum count", other: "{n} rows under the minimum count" }, parsed.belowMin)}`}
              </div>
            )}
            {parsed && previewFields.length > 0 && (
              <div>
                <SectionHeading style={{ margin: "0 2px 8px" }}>
                  {t("Preview")}
                </SectionHeading>
                <div style={{ background: "var(--panel)", border: "1px solid var(--border)", borderRadius: "var(--r-7)", overflow: "auto" }}>
                  <div style={{ display: "grid", gridTemplateColumns: previewGrid, gap: 8, padding: "8px 14px",
                                fontSize: "var(--fs-1)", fontWeight: 700, letterSpacing: "0.04em", textTransform: "uppercase",
                                color: "var(--muted-2)", borderBottom: "1px solid var(--border-soft)" }}>
                    {previewFields.map((f) => <div key={f}>{label[f]}</div>)}
                  </div>
                  {preview.map((r, i) => (
                    <div key={i} style={{ display: "grid", gridTemplateColumns: previewGrid, gap: 8, padding: "7px 14px",
                                          fontSize: "var(--fs-3)", color: "var(--text-2)",
                                          borderBottom: i === preview.length - 1 ? "none" : "1px solid var(--border-soft)" }}>
                      {previewFields.map((f) => (
                        <div key={f} title={previewCell(r, f)}
                             style={{ fontFamily: f === "name" || f === "count" ? "var(--mono)" : undefined,
                                      color: f === "name" ? undefined : "var(--muted)",
                                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {previewCell(r, f) || "—"}
                        </div>
                      ))}
                    </div>
                  ))}
                  {preview.length === 0 && (
                    <div style={{ padding: "12px 14px", fontSize: "var(--fs-3)", color: "var(--muted-2)" }}>
                      {t("No rows — check the columns above.")}
                    </div>
                  )}
                </div>
              </div>
            )}
            {progress && (
              <ProgressBar value={progress.total ? (100 * progress.done) / progress.total : 0} />
            )}
          </>
        )}
      </div>
    </Overlay>
  );
}

/** The shared settings row — it gained the family's hairline between rows. */
function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return <RowShell label={label} hint={hint} pad="8px 0">{children}</RowShell>;
}

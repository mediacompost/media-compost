/** IMPORTING A TAG SET FROM ITS JSON FILE — the hidden input, the parse, the
 *  mutation and its invalidations, in one hook. The Tag sets manager's Add
 *  menu is the one door now (`TagSetShelf`); the Settings page this file was
 *  named for is gone, and with it the rows and the Import button it drew.
 *  The hook hands back the `<input>` to mount and `pick()` to open it. */
import React, { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { TagSetOut, api } from "../api";
import { bumpEdits } from "../invalidation";
import { useT, useErrText } from "../i18n";

export function useTagSetFileImport(onDone?: (set: TagSetOut) => void,
                                    onCsv?: (file: File) => void) {
  const t = useT();
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const errText = useErrText();
  const importer = useMutation({
    mutationFn: (doc: unknown) => api.importTagSet(doc, "create"),
    onSuccess: (res) => {
      setError(null);
      setDone(res.set.name);
      qc.invalidateQueries({ queryKey: ["tag-sets"] });
      qc.invalidateQueries({ queryKey: ["tag-set-order"] });
      bumpEdits();
      onDone?.(res.set);
    },
    onError: (e) => { setDone(null); setError(errText(e)); },
  });
  const input = (
    <input
      ref={fileRef}
      type="file"
      // A CSV is taken too where the caller can make a set out of one (the
      // Sets tab's import): the same door for both files a set comes in as.
      accept={onCsv ? ".json,.csv,.tsv,.txt,application/json,text/csv" : ".json,application/json"}
      style={{ display: "none" }}
      onChange={async (e) => {
        const f = e.target.files?.[0];
        e.target.value = "";
        if (!f) return;
        if (onCsv && /\.(csv|tsv|txt)$/i.test(f.name)) {
          setError(null);
          onCsv(f);
          return;
        }
        let doc: unknown;
        try {
          doc = JSON.parse(await f.text());
        } catch {
          setDone(null);
          setError(t("Not a tag set file"));
          return;
        }
        importer.mutate(doc);
      }}
    />
  );
  return { input, pick: () => fileRef.current?.click(), error, done };
}

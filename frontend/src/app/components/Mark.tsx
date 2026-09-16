// THE MATCHING PART OF A NAME, LIT — one definition, because two lists
// showing the same kind of row for the same kind of search must light it the
// same way. The items tag list had it first; the Sets sub-tab's entry list
// asks the same question of the same names.
//
// Case-insensitive, every occurrence, and the ORIGINAL text is what is
// drawn — only the span boundaries come from the lowercased haystack, so a
// name's own capitals survive being searched for in lower case.

import React from "react";

export function Mark({ text, q }: { text: string; q: string }) {
  const needle = q.trim().toLowerCase();
  if (!needle) return <>{text}</>;
  const parts: React.ReactNode[] = [];
  const hay = text.toLowerCase();
  let at = 0;
  for (let i = hay.indexOf(needle); i >= 0; i = hay.indexOf(needle, at)) {
    if (i > at) parts.push(text.slice(at, i));
    parts.push(
      <span key={i} style={{
        background: "var(--accent-dim)", color: "var(--accent)",
        borderRadius: 3, padding: "0 1px",
      }}>{text.slice(i, i + needle.length)}</span>
    );
    at = i + needle.length;
  }
  if (at === 0) return <>{text}</>;
  if (at < text.length) parts.push(text.slice(at));
  return <>{parts}</>;
}

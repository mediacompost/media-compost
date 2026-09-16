// WHERE A TAG SET FILES A TAG, drawn as the names down to it.
//
// A trail is a LIST of names, never a joined path: a category name may hold
// a `/` (owner decision, 2026-09), so there is no character left that could
// separate two names without also appearing inside one. The separator is
// therefore drawn, not written — a chevron between the names, which is what
// the slash was standing in for.
//
// The chevron is a Material Symbols LIGATURE, so it carries `userSelect:
// none`: without it, copying a row's category would paste the literal word
// `chevron_right` between the names (`tokens.css` says the same about the
// ligatures inside `.mc-copy`).
//
// Inline, not flex, so a container that clips with `text-overflow: ellipsis`
// still can.

import React from "react";
import { Icon } from "../../shared/Icon";

export function CategoryTrail({ trail, size = 11, onPick, pickTitle }: {
  /** The names down to the category, outermost first. */
  trail: readonly string[];
  size?: number;
  /** Makes each name a way INTO that category. The index is its depth. */
  onPick?: (index: number) => void;
  pickTitle?: string;
}) {
  return (
    <>
      {trail.map((name, i) => (
        <React.Fragment key={i}>
          {i > 0 && (
            <Icon name="chevron_right" size={size + 2} aria-hidden="true"
                  style={{ verticalAlign: "-2px", color: "var(--muted-3)", userSelect: "none", margin: "0 1px" }} />
          )}
          {onPick ? (
            <span role="button" title={pickTitle}
                  onMouseDown={(ev) => ev.stopPropagation()}
                  onClick={(ev) => { ev.stopPropagation(); onPick(i); }}
                  style={{ cursor: "pointer", textUnderlineOffset: 2 }}
                  onMouseEnter={(ev) => {
                    ev.currentTarget.style.textDecoration = "underline";
                    ev.currentTarget.style.color = "var(--text-2)";
                  }}
                  onMouseLeave={(ev) => {
                    ev.currentTarget.style.textDecoration = "none";
                    ev.currentTarget.style.color = "";
                  }}>
              {name}
            </span>
          ) : name}
        </React.Fragment>
      ))}
    </>
  );
}

/** The same trail as ONE string, for a `title` tooltip or anywhere else that
 *  cannot hold elements. Never parsed back — see the note above. */
export const trailLabel = (trail: readonly string[]): string =>
  trail.join(" › ");

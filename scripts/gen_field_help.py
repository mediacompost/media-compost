#!/usr/bin/env python3
"""Compile the training help texts from the DOCS into the app.

THE DOCUMENTATION IS THE SOURCE. The long explanations behind every ⓘ in the
job editor were TypeScript string literals, which meant the website's training
page either repeated them — two copies, drifting, and one of them did (its
LoRA/LoKr section was months out of date and wrong about ComfyUI) — or simply
did not have them. They live in `docs/training/fields/*.md` now: one file per
section of the editor, one `##` heading per field, ordinary prose underneath.

    docs/training/fields/*.md
        │
        ├── this script ──> frontend/src/train/fieldHelp.ts   (the app)
        └── a snippet include ──> docs/training.md            (the website)

The app cannot read the docs at runtime — it is offline-first and the wheel
ships no markdown — so a build step is the only way either direction, and this
is the direction that puts the words where they are edited as words.

BYTE-IDENTICAL IS THE REQUIREMENT, not a nicety: every one of these strings is
an i18n catalog KEY with seven translations behind it, so re-wrapping a single
paragraph strands all seven. Hence the deliberately dull format — paragraphs
separated by blank lines, joined back with "\\n\\n", and nothing else. No
lists, no bold, no line breaks inside a paragraph: markdown that renders as
more than one paragraph shape cannot survive the round trip.

Usage:
    scripts/gen_field_help.py            # write the module
    scripts/gen_field_help.py --check    # exit 1 if it is stale (the test)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIELDS = ROOT / "docs/training/fields"
OUT = ROOT / "frontend/src/train/fieldHelp.ts"

HEADER = """\
// GENERATED — DO NOT EDIT.
//
// The words live in `docs/training/fields/*.md`, which is what the website's
// training page includes as well; `scripts/gen_field_help.py` compiles them
// into this table. Editing here is editing a copy: the next run overwrites
// it, and `tests/test_field_help.py` fails in the meantime.
//
// The values reach `t()` as data, so the i18n extractor cannot see them —
// `i18nCoverage.test.ts` harvests THIS table instead, which is why every
// paragraph here must stay byte-identical to its catalog key.
export const HELP: Record<string, string> = {
"""


def slug(s: str) -> str:
    s = s.lower().replace("\u2019", "").replace("'", "")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def read_fields() -> "dict[str, str]":
    """Every `## heading` in every section file, as `section.field` → text."""
    out: dict[str, str] = {}
    for path in sorted(FIELDS.glob("*.md")):
        section = path.stem
        blocks = re.split(r"^### ", path.read_text(encoding="utf-8"), flags=re.M)
        for block in blocks[1:]:
            head, _, body = block.partition("\n")
            key = "%s.%s" % (section, slug(head.strip()))
            n = 2
            while key in out:
                key, n = "%s.%s-%d" % (section, slug(head.strip()), n), n + 1
            paragraphs = [p.strip() for p in body.strip().split("\n\n")]
            out[key] = "\n\n".join(p for p in paragraphs if p)
    return out


def render(fields: "dict[str, str]") -> str:
    lines = [HEADER]
    for key, text in fields.items():
        lines.append("  %s:\n    %s,\n"
                     % (json.dumps(key), json.dumps(text, ensure_ascii=False)))
    lines.append("};\n")
    return "".join(lines)


def main() -> int:
    fields = read_fields()
    if not fields:
        print("no fields found in %s" % FIELDS, file=sys.stderr)
        return 1
    text = render(fields)
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print("fieldHelp.ts is stale — run scripts/gen_field_help.py",
                  file=sys.stderr)
            return 1
        print("fieldHelp.ts is up to date (%d fields)" % len(fields))
        return 0
    OUT.write_text(text, encoding="utf-8")
    print("wrote %s (%d fields)" % (OUT.relative_to(ROOT), len(fields)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

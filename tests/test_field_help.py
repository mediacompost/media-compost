"""The training help texts are compiled from the docs, and stay that way.

`docs/training/fields/*.md` is the source: `scripts/gen_field_help.py` writes
`frontend/src/train/fieldHelp.ts` from it and `docs/training.md` includes the
same files. What can go wrong is the generated file falling behind the
markdown — an edit to the docs that never reaches the app looks exactly like
an edit that did nothing.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIELDS = ROOT / "docs/training/fields"
GEN = ROOT / "scripts/gen_field_help.py"
OUT = ROOT / "frontend/src/train/fieldHelp.ts"


def test_the_compiled_help_matches_the_docs():
    """Run the generator's own `--check`, which is the whole contract."""
    proc = subprocess.run([sys.executable, str(GEN), "--check"],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_every_key_the_editor_asks_for_exists():
    """`HELP["adapter.rank"]` is a string lookup, so a heading renamed in the
    markdown does not fail to compile — it renders `undefined` in a dialog."""
    keys = set(re.findall(r'"([a-z0-9.-]+)":\n',
                          OUT.read_text(encoding="utf-8")))
    used = set()
    for name in ("TrainJobEditor.tsx", "DegradeSection.tsx"):
        src = (ROOT / "frontend/src/train" / name).read_text(encoding="utf-8")
        used |= set(re.findall(r'HELP\["([^"]+)"\]', src))
    assert used, "the editor stopped reading the compiled table"
    assert used <= keys, "missing help: %s" % sorted(used - keys)


def test_the_markdown_stays_round_trippable():
    """The format is dull on purpose: these strings are i18n catalog KEYS, so
    anything markdown would render as more than plain paragraphs changes the
    string and strands seven translations. Headings and prose only."""
    offenders = []
    for path in sorted(FIELDS.glob("*.md")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.startswith("#"):
                continue
            if re.match(r"\s*([-*+]\s|\d+\.\s|>|```|\|)", line):
                offenders.append("%s:%d: %s" % (path.name, n, line[:60]))
            # BOLD too, which the block rule above cannot see: the app
            # renders these paragraphs as PLAIN TEXT in a popover, so what
            # the website styles shows there as its own asterisks — one
            # reached the help before this line did. Backticks are NOT
            # banned: five files name a tag shape or a setting with them, and
            # a bare backtick reads as the quoting it is.
            if "**" in line:
                offenders.append("%s:%d: bold: %s" % (path.name, n, line[:60]))
    assert offenders == [], "\n".join(offenders)


def test_the_training_page_includes_every_section():
    """A section file nobody includes is help the website does not have —
    which is the state this whole arrangement was built to end."""
    page = (ROOT / "docs/training.md").read_text(encoding="utf-8")
    included = set(re.findall(r'--8<--\s+"training/fields/([a-z0-9-]+)\.md"',
                              page))
    on_disk = {p.stem for p in FIELDS.glob("*.md")}
    assert on_disk - included == set(), sorted(on_disk - included)
    assert included - on_disk == set(), sorted(included - on_disk)

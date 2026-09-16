"""A META TAG IS A NAME IN A TAG SET, and the library's is one of them.

Meta tags are `tags` rows (`kind = 'meta'`) since the fold of `link_tags`, so
a TAG SET can carry the meta tags it wants its entries labelled with — its own
rows, with its `tag_set_id`.

That is the one thing the discriminator cannot say for itself. `select(Tag)`
and `select(TagSetEntry)` scope themselves to one tag set because their
kind IS the tag set; `select(MetaTag)` spans every set's, so every read
that means THE LIBRARY'S own meta namespace — the four carriers, and
everything that mints or renames a name in it — has to add `db.LIB_META`.

This is the grep that says nobody forgot. It reads the SOURCE, because a
missed clause is not a crash: it is one set's private label answering a
question about the library, months later, in a library nobody can reproduce.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "media_compost"

#: `select(LinkTag)` / `select(MetaTag.name, …)` — the whole statement, which
#: may be wrapped over several lines. `LIB_META` must be inside it.
SELECT = re.compile(r"select\(\s*(?:LinkTag|MetaTag)\b")


def _statements(text: str):
    """Every `select(LinkTag…)` with the text up to the end of its call."""
    for m in SELECT.finditer(text):
        depth, i = 0, m.end() - 1
        while i < len(text):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        # …plus whatever is chained onto it, which is where a `.where()` sits.
        end = text.find("\n", i)
        while end != -1 and text[end + 1:end + 40].lstrip().startswith("."):
            end = text.find("\n", end + 1)
        yield m.start(), text[m.start():end if end != -1 else len(text)]


def test_every_read_of_the_meta_namespace_says_whose_it_is():
    missing = []
    for path in sorted(ROOT.rglob("*.py")):
        if path.name == "db.py":
            continue                      # where the clause is defined
        text = path.read_text(encoding="utf-8")
        for at, stmt in _statements(text):
            # …or names a SET, which is the other honest answer: a
            # tag set's own labels are read by `tag_set_id`.
            if "LIB_META" not in stmt and "tag_set_id" not in stmt:
                line = text.count("\n", 0, at) + 1
                missing.append(f"{path.relative_to(ROOT.parent)}:{line}")
    assert missing == [], (
        "these read the meta namespace without saying whose it is — add "
        "`db.LIB_META`, or name the `tag_set_id` whose labels they mean: "
        + ", ".join(missing))

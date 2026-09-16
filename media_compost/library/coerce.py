"""Whatever a caller passed, as the condition tree the evaluator wants.

The tree is the Pydantic models `media_compost.query` holds, and their JSON is
the wire format. A caller writes a **query string** — the same one the search
bar takes, parsed by `media_compost.querystring` — and that is the documented
way in; the models are public, so a caller assembling one by hand works too.

(There was a `Q` builder here, an operator-overloading front end that
constructed those same models: `Q.tag("portrait") & ~Q.tag("lowres")`. It went
before the first release rather than shipping unproven — it had no callers
anywhere in this repository, so nothing but its own tests exercised it, and
adding it back on request costs less than promising an API nobody had used.
What went with it is the one thing strings genuinely cannot do: a value
holding a comma, a colon or a leading `!` has to be escaped into a query
string, and `querystring.escape_name` is what does it.)
"""

from __future__ import annotations

from typing import Optional

from .. import query as _q


def as_group(value) -> Optional[_q.Group]:
    """Accepts a query STRING, a raw `Group`, a bare condition, a list
    (implicit AND), or None. Returns None for "match everything", which is
    what an empty tree means everywhere else in the codebase.
    """
    if value is None:
        return None
    if isinstance(value, str):
        from .. import querystring

        got = querystring.parse(value)
        return None if _q.is_empty(got) else got
    if isinstance(value, (list, tuple)):
        if not value:
            return None
        return _q.Group(op="and", children=list(value))
    if isinstance(value, _q.Group):
        return None if _q.is_empty(value) else value
    return _q.Group(op="and", children=[value])

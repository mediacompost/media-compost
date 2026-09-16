"""``{placeholder}`` substitution — the Python twin of the frontend's
``fillVars`` (``shared/i18nCore.ts``), the sixth mirrored pure module after
``partialdate.py``, ``tagname.py``, ``num_tolerance``, ``places/formats.ts``
and ``querystring.py``: the rule has to hold on both sides of the wire,
because the backend WRITES templates (an error's message, a history entry's
summary) that the frontend re-renders in another language by looking the
template up and filling the same slots.

Split/join on the literal ``{name}``, deliberately NOT ``str.format``: the
texts these templates carry include curly quotes and user-typed values, and
``str.format`` would give them brace-escaping rules nobody asked for — a tag
named ``{x}`` must ride through as text, not crash the formatter. A
placeholder with no value stays as written, which is also what the frontend
does; values pass through ``str()`` untouched.
"""

from __future__ import annotations

from typing import Mapping, Optional


def fillvars(text: str, vars: Optional[Mapping[str, object]] = None) -> str:
    """``fillvars("no tag named “{name}”", {"name": "x"})``."""
    if not vars:
        return text
    for key, value in vars.items():
        text = str(value).join(text.split("{%s}" % key))
    return text

"""The search query language, in Python.

A **mirror of** ``frontend/src/query/tree.ts`` — the fifth pure module this
project keeps on both sides, after `partialdate.py`, `tagname.py`,
`query.num_tolerance` and `places/formats.ts`. The frontend keeps its own copy
because the query builder is two-way bound to the text field: it re-parses on
every keystroke and re-serializes on every dropdown change, and a round trip to
the server in that loop is lag on every click.

They are held level by a **shared golden corpus** —
``tests/golden/query_corpus.json``, asserted by `pytest` here and by
`node --test` there. Adding a condition kind means adding corpus rows, and
either side falling behind fails its own suite. That is stronger than the
by-hand lockstep this project asked for before, which had already produced a
live bug: `subject:@1910` was decoded as year 0, month 19, day 10 and matched
nothing, silently.

Nothing here touches a session. `parse` decides an `INFO:` value's type from
the literal's own syntax, not from the metadata catalog, so the whole grammar
is a pure function of the string.

## The grammar, briefly

    portrait                     a tag
    !portrait                    ...that the item does NOT carry
    -portrait                    ...carried as a NEGATIVE assignment
    TAG:noflip,!draft            ...any tag the TAG SET marks that way
    a b c                        AND (whitespace)
    a|b                          OR
    (a b)|c                      grouping
    !(a b)                       none of these
    INFO:width>=800              metadata
    GROUP:Trips                  in that group or any group under it
    GROUPONLY:Trips              filed in that group itself
    PLACE:Shibuya  PLACE=Tokyo  the address of a place it is at
    SUBJECT:alice@1921#12        a person, dated / aged
    EVENT:comic_con@2014..2016   an event, by its own span
    TAKEN:@2020-01-01..2020-01-07
    CAPTION:en,!draft            a caption, narrowed by meta tags
    INSTRUCTION:                 ...and the same over instructions
    LINK:edit    LINKEDBY:edit

**Keywords are UPPERCASE and matched case-sensitively.** That is not
decoration: the Behaviors settings put subjects, places and events into
namespaces of exactly the shape `place:berlin`, so a case-insensitive `place:`
would swallow the tags the app itself invents. Shouting the keywords hands the
whole lowercase space back to tag names, permanently.
"""

from __future__ import annotations

import math
import re
from typing import Optional

from . import query as q

#: Longest-first, so `>=` is found before `>` and `!~` before `~`. The same
#: order `tree.ts: META_OPS` uses, and for the same reason.
META_OPS = (">=", "<=", "!=", "!~", ">", "<", "=", "~")

__all__ = ["parse", "try_parse", "serialize", "QueryStringError"]


class QueryStringError(ValueError):
    """The string is not a query."""


# ---- escaping ---------------------------------------------------------------
#
# A tag name may legitimately contain the characters the grammar uses as
# syntax: a comma separates the tags of a link/caption list, and a leading `!`
# (or `-`) negates. A backslash escapes the next character.


def split_escaped(text: str, sep: str = ",") -> list[str]:
    """Split on ``sep``, honouring backslash escapes.

    The pieces come back **still escaped** — the caller strips its own prefixes
    (an exclusion `!`) first and unescapes after, or `\\!name` would read as
    "exclude name".
    """
    out: list[str] = []
    cur = ""
    i = 0
    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text):
            cur += c + text[i + 1]
            i += 2
            continue
        if c == sep:
            out.append(cur)
            cur = ""
            i += 1
            continue
        cur += c
        i += 1
    out.append(cur)
    return out


def unescape_name(text: str) -> str:
    """Drop one level of escaping (``\\,`` → ``,``, ``\\\\`` → ``\\``)."""
    return re.sub(r"\\(.)", r"\1", text)


def escape_name(text: str) -> str:
    """Escape a name so parsing reads it back verbatim."""
    out = text.replace("\\", "\\\\").replace(",", "\\,")
    if out.startswith("!") or out.startswith("-"):
        out = "\\" + out
    return out


# ---- numbers and dates ------------------------------------------------------


def _is_numeric(v: str) -> bool:
    return re.fullmatch(r"-?\d+(?:\.\d+)?", v) is not None


def num_tolerance(raw: str) -> float:
    """Half of the last decimal place a searched number was written to.

    `0.7` means "about 0.7" (±0.05); `0.75` narrows that to ±0.005; a whole
    number gets ±0.5 (a no-op for integer-valued fields like width). The same
    rule as `query.num_tolerance` and `tree.ts: numTolerance`.
    """
    dot = raw.find(".")
    decimals = 0 if dot < 0 else len(raw) - dot - 1
    return 0.5 * (10 ** -decimals)


def meta_value_text(cond: q.MetaCond) -> str:
    """Render a numeric value with the decimals its tolerance implies, so a
    deliberate `0.70` survives the trip through the query string."""
    if cond.mtype != "numeric" or not isinstance(cond.value, (int, float)) \
            or not cond.tol:
        return str(cond.value)
    decimals = max(0, round(-math.log10(cond.tol * 2)))
    return f"{float(cond.value):.{decimals}f}"


def _parse_when(raw: str) -> Optional[int]:
    """A typed date to the `YYYYMMDD` partial encoding.

    `2014` is a YEAR, and the encoding has zeros for what is unknown — so it
    becomes 20140000. Passing the bare number through was a live bug in
    `subject:@1910`, decoded as year 0, month 19, day 10. Length is the
    precision: 4 digits a year, 6 a month, 8 a day.
    """
    try:
        n = int(raw)
    except ValueError:
        return None
    if n <= 0:
        return None
    if len(raw) <= 4:
        return n * 10000
    if len(raw) <= 6:
        return n * 100
    return n


def _parse_taken(raw: str) -> Optional[int]:
    """The same for a capture date, two levels finer: digits read as
    `YYYY[MM[DD[HH[MM[SS]]]]]` and zero-padded. Separators are ignored, which
    is what lets somebody type `2020-01-07`."""
    digits = re.sub(r"\D", "", raw)[:14]
    if len(digits) < 4:
        return None
    return int(digits.ljust(14, "0"))


def _format_taken(v: int) -> str:
    """The shortest form that reads back the same — `2020`, not fourteen
    digits, and `2020-01-07` rather than `20200107000000`."""
    d = str(int(v)).rjust(14, "0")
    keep = 4
    for start in (4, 6, 8, 10, 12):
        if d[start:start + 2] != "00":
            keep = start + 2
    head = "-".join(
        [p for p in (d[0:4], d[4:6], d[6:8])[:min(3, math.ceil(keep / 2) - 1)]
         if p]
    )
    if keep <= 8:
        return head
    time = ":".join((d[8:10], d[10:12], d[12:14])[:(keep - 8) // 2])
    return f"{head}T{time}"


def _format_when(v: int) -> str:
    """The shortest form that reads back as the same date — `2014`, not
    `20140000`. A query string is typed by hand as often as generated."""
    if v % 10000 == 0:
        return str(v // 10000)
    if v % 100 == 0:
        return str(v // 100)
    return str(v)


def _parse_span(raw: Optional[str], when: bool = False,
                fine: bool = False) -> tuple[Optional[int], Optional[int]]:
    """A `lo..hi` range, a bare value (both ends), or one open side."""
    if not raw:
        return None, None

    def one(s: Optional[str]) -> Optional[int]:
        if s is None or s == "":
            return None
        if fine:
            return _parse_taken(s)
        if when:
            return _parse_when(s)
        try:
            return int(s)
        except ValueError:
            return None

    parts = raw.split("..")
    a = parts[0]
    b = parts[1] if len(parts) > 1 else None
    lo = one(a)
    hi = lo if b is None else one(b)
    return lo, hi


def _span_text(a: Optional[int], b: Optional[int], when: bool = False,
               fine: bool = False) -> str:
    def show(v: int) -> str:
        return _format_taken(v) if fine else (_format_when(v) if when else str(v))

    if a is not None and b is not None and a != b:
        return f"{show(a)}..{show(b)}"
    if a is not None:
        return show(a)
    if b is not None:
        return f"..{show(b)}"
    return ""


# ---- tokenizing -------------------------------------------------------------

_SEP = re.compile(r"\s")
_BREAK = re.compile(r"[\s()|]")


def _tokenize(src: str) -> list[tuple[str, str]]:
    toks: list[tuple[str, str]] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if _SEP.match(c):
            toks.append(("sep", ""))
            i += 1
            continue
        if c in "()|":
            toks.append((c, ""))
            i += 1
            continue
        # `!` is the NOT operator ONLY directly before a group; otherwise it is
        # part of an atom (a has-not tag, a negative link direction, a `!=`).
        if c == "!" and i + 1 < n and src[i + 1] == "(":
            toks.append(("not", ""))
            i += 1
            continue
        # One atom. It runs until whitespace / paren / pipe and may contain
        # double-quoted segments; the quote is not a token boundary, so a
        # prefix like `!` or `INFO:` stays OUTSIDE the quotes.
        #
        # A quote pair is a WRAPPER (stripped) only when it protects
        # whitespace — the sole reason the serializer ever quotes. Around a
        # whitespace-free segment the quotes are literal, so a tag really
        # named `"ball"` stays distinct from the plain tag `ball`.
        v = ""
        while i < n and not _BREAK.match(src[i]):
            if src[i] == '"':
                j = i + 1
                while j < n and src[j] != '"':
                    j += 1
                end = j + 1 if j < n else n
                inner = src[i + 1:j]
                v += inner if _SEP.search(inner) else src[i:end]
                i = end
            else:
                v += src[i]
                i += 1
        toks.append(("atom", v))
    # Collapse separator runs and trim the ends.
    out: list[tuple[str, str]] = []
    for t in toks:
        if t[0] == "sep" and (not out or out[-1][0] == "sep"):
            continue
        out.append(t)
    while out and out[0][0] == "sep":
        out.pop(0)
    while out and out[-1][0] == "sep":
        out.pop()
    return out


# ---- one atom ---------------------------------------------------------------


def _tag_refs(body: str) -> list[q.LinkTagRef]:
    """The tag list of a link/caption condition: comma-separated, `!`
    excludes, and either may be backslash-escaped to appear in a name."""
    if not body:
        return []
    out = []
    for raw in split_escaped(body):
        piece = raw.strip()
        if not piece:
            continue
        if piece.startswith("!"):
            out.append(q.LinkTagRef(name=unescape_name(piece[1:]), exclude=True))
        else:
            out.append(q.LinkTagRef(name=unescape_name(piece), exclude=False))
    return out


def atom_node(tok: str):
    """One atom token as a condition node."""
    # Metadata: INFO:name<op>value.
    #
    if tok.startswith("INFO:"):
        body = tok[5:]
        for op in META_OPS:
            idx = body.find(op)
            if idx > 0:
                name = body[:idx]
                raw = body[idx + len(op):]
                mtype = ("text" if op in ("~", "!~")
                         else "numeric" if _is_numeric(raw) else "text")
                if mtype == "numeric":
                    return q.MetaCond(name=name, mtype=mtype, op=op,
                                      value=float(raw),
                                      tol=num_tolerance(raw))
                return q.MetaCond(name=name, mtype=mtype, op=op, value=raw)
        # No operator found — an equality on the whole remainder.
        return q.MetaCond(name=body, mtype="text", op="=", value="")

    m = re.fullmatch(r"(!)?GROUPONLY:(.*)", tok)
    if m:
        return q.GroupCond(name=unescape_name(m.group(2)),
                           mode="notonly" if m.group(1) else "only")
    m = re.fullmatch(r"(!)?GROUP:(.*)", tok)
    if m:
        return q.GroupCond(name=unescape_name(m.group(2)),
                           mode="hasnot" if m.group(1) else "has")
    # A place has ONE searchable field, its name — to ask for one
    # particular place, search its TAG, which is what the item carries.
    m = re.fullmatch(r"(!)?PLACE([:=])(.*)", tok)
    if m:
        return q.PlaceCond(op="=" if m.group(2) == "=" else "~",
                           value=unescape_name(m.group(3)),
                           have=not m.group(1))
    m = re.fullmatch(r"(!)?SUBJECT:([^@#]*)(?:@([^#]*))?(?:#(.*))?", tok)
    if m:
        d_from, d_to = _parse_span(m.group(3), when=True)
        a_from, a_to = _parse_span(m.group(4))
        return q.SubjectCond(name=unescape_name(m.group(2)).lower(),
                             have=not m.group(1), date_from=d_from,
                             date_to=d_to, age_from=a_from, age_to=a_to)
    m = re.fullmatch(r"(!)?EVENT:([^@]*)(?:@(.*))?", tok)
    if m:
        d_from, d_to = _parse_span(m.group(3), when=True)
        return q.EventCond(name=unescape_name(m.group(2)).lower(),
                           have=not m.group(1), date_from=d_from, date_to=d_to)
    m = re.fullmatch(r"(!)?TAKEN:(?:@(.*))?", tok)
    if m:
        d_from, d_to = _parse_span(m.group(2), when=True, fine=True)
        return q.TakenCond(have=not m.group(1), date_from=d_from, date_to=d_to)
    # COLORLIKE:<uid>[~<tol>]. The uid is an item's, never a row id — refs
    # are uids everywhere here, which is what lets a saved search survive.
    # `~n` is a Hamming distance over the colour signature; without it
    # `query.DEFAULT_COLOR_TOL` applies. (A `SIMILAR:` keyword stood beside
    # it over the perceptual hash and was removed with the grid action that
    # was its only door — the importer folds a re-encode or a crop onto the
    # item it matches, so the search reliably found that item and nothing
    # else. The token is nobody's keyword now and reads as a tag name, which
    # matches nothing: a search that visibly finds no pictures, rather than
    # one quietly answering a different question.)
    m = re.fullmatch(r"(!)?COLORLIKE:([^~]*)(?:~(-?\d+))?", tok)
    if m:
        return q.SimilarCond(
            uid=unescape_name(m.group(2)),
            tol=int(m.group(3)) if m.group(3) is not None else None,
            have=not m.group(1))
    # VALUE:<namespace><op><number>[unit] — tags read as numbers. The number
    # takes a dot OR comma decimal (the parser is total over what a library
    # can hold; the serializer writes the dot), and `tol` is the metadata
    # rule — half the last typed decimal place, computed HERE while the text
    # still shows it.
    m = re.fullmatch(
        r"(!)?VALUE:(.+?)(>=|<=|!=|=|>|<)(-?\d+(?:[.,]\d+)?)([a-z%°µ]*)", tok)
    if m:
        raw = m.group(4).replace(",", ".")
        return q.ValueCond(name=unescape_name(m.group(2)).lower(),
                           op=m.group(3), value=float(raw),
                           unit=m.group(5), tol=num_tolerance(raw),
                           have=not m.group(1))
    m = re.fullmatch(r"(!)?(CAPTION|INSTRUCTION):(.*)", tok)
    if m:
        return q.CaptionCond(
            mode="hasnot" if m.group(1) else "has",
            caption_kind=("instruction" if m.group(2) == "INSTRUCTION"
                          else "caption"),
            caption_tags=_tag_refs(m.group(3)))
    m = re.fullmatch(r"(!)?(LINK|LINKEDBY):(.*)", tok)
    if m:
        neg = bool(m.group(1))
        incoming = m.group(2) == "LINKEDBY"
        direction = ("notlinkedby" if neg else "linkedby") if incoming else \
                    ("hasnot" if neg else "has")
        return q.LinkCond(direction=direction, link_tags=_tag_refs(m.group(3)))

    # A tag described by what the TAG SET says about it:
    # [!][-]TAG:meta,!meta — the CAPTION: shape, over the item's own tags.
    m = re.fullmatch(r"(!)?(-)?TAG:(.*)", tok)
    if m:
        return q.TagCond(name="", have=not m.group(1),
                         sign="neg" if m.group(2) else "pos",
                         meta_tags=_tag_refs(m.group(3)))

    # Tag: [!][-]name — an escaped `\!` / `\-` is part of the NAME.
    have, sign, name = True, "pos", tok
    if name.startswith("!"):
        have, name = False, name[1:]
    if name.startswith("-"):
        sign, name = "neg", name[1:]
    return q.TagCond(name=unescape_name(name).lower(), have=have, sign=sign)


# ---- parse ------------------------------------------------------------------


def parse(src: str) -> q.Group:
    """A query string as a condition tree. Raises `QueryStringError`."""
    toks = _tokenize(src)
    pos = 0

    def peek():
        return toks[pos] if pos < len(toks) else None

    def parse_atom():
        nonlocal pos
        t = peek()
        if t is None:
            raise QueryStringError("unexpected end of query")
        if t[0] == "(":
            pos += 1
            inner = parse_and()
            if peek() is None or peek()[0] != ")":
                raise QueryStringError("missing ')'")
            pos += 1
            return inner
        if t[0] == "not":
            pos += 1
            inner = parse_atom()
            if isinstance(inner, q.Group):
                return inner.model_copy(update={"neg": not inner.neg})
            return q.Group(op="and", neg=True, children=[inner])
        if t[0] != "atom":
            raise QueryStringError(f"unexpected token {t[0]!r}")
        pos += 1
        return atom_node(t[1])

    def parse_or():
        nonlocal pos
        items = [parse_atom()]
        while peek() is not None and peek()[0] == "|":
            pos += 1
            items.append(parse_atom())
        return q.Group(op="or", neg=False, children=items) if len(items) > 1 \
            else items[0]

    def parse_and():
        nonlocal pos
        items = [parse_or()]
        while peek() is not None and peek()[0] == "sep":
            pos += 1
            if peek() is None or peek()[0] == ")":
                break
            items.append(parse_or())
        return q.Group(op="and", neg=False, children=items) if len(items) > 1 \
            else items[0]

    if not toks:
        return q.Group(op="and", neg=False, children=[])
    node = parse_and()
    if pos != len(toks):
        raise QueryStringError("unexpected trailing token")
    return node if isinstance(node, q.Group) \
        else q.Group(op="and", neg=False, children=[node])


def try_parse(src: str) -> Optional[q.Group]:
    """Parse leniently: the tree, or None when the string does not parse."""
    try:
        return parse(src)
    except QueryStringError:
        return None


# ---- serialize --------------------------------------------------------------

_NEEDS_QUOTE = re.compile(r"\s")


def _quoted(atom: str) -> str:
    return f'"{atom}"' if _NEEDS_QUOTE.search(atom) else atom


def _serialize_cond(c) -> str:
    if isinstance(c, q.TagCond):
        prefix = ("" if c.have else "!") + ("-" if c.sign == "neg" else "")
        if c.meta_tags:
            tags = ",".join(("!" if t.exclude else "") + escape_name(t.name)
                            for t in c.meta_tags)
            return _quoted(f"{prefix}TAG:{tags}")
        return prefix + escape_name(c.name)
    if isinstance(c, q.MetaCond):
        return _quoted(f"INFO:{c.name}{c.op}{meta_value_text(c)}")
    if isinstance(c, q.GroupCond):
        neg = "!" if c.mode in ("hasnot", "notonly") else ""
        kw = "GROUPONLY" if c.mode in ("only", "notonly") else "GROUP"
        return _quoted(f"{neg}{kw}:{escape_name(c.name)}")
    if isinstance(c, q.PlaceCond):
        sep = "=" if c.op == "=" else ":"
        return _quoted(f"{'' if c.have else '!'}PLACE{sep}{escape_name(c.value)}")
    if isinstance(c, q.SubjectCond):
        d = _span_text(c.date_from, c.date_to, when=True)
        g = _span_text(c.age_from, c.age_to)
        atom = f"{'' if c.have else '!'}SUBJECT:{escape_name(c.name)}"
        atom += f"@{d}" if d else ""
        atom += f"#{g}" if g else ""
        return _quoted(atom)
    if isinstance(c, q.EventCond):
        d = _span_text(c.date_from, c.date_to, when=True)
        atom = f"{'' if c.have else '!'}EVENT:{escape_name(c.name)}"
        return _quoted(atom + (f"@{d}" if d else ""))
    if isinstance(c, q.TakenCond):
        d = _span_text(c.date_from, c.date_to, when=True, fine=True)
        return _quoted(f"{'' if c.have else '!'}TAKEN:" + (f"@{d}" if d else ""))
    if isinstance(c, q.ValueCond):
        # The number re-renders with the decimals `tol` implies, the
        # `meta_value_text` rule, so `VALUE:height=1.70m` round-trips.
        if c.tol:
            decimals = max(0, round(-math.log10(c.tol * 2)))
            num = f"{float(c.value):.{decimals}f}"
        else:
            num = f"{c.value:g}"
        return _quoted(f"{'' if c.have else '!'}VALUE:"
                       f"{escape_name(c.name)}{c.op}{num}{c.unit}")
    if isinstance(c, q.SimilarCond):
        atom = f"{'' if c.have else '!'}COLORLIKE:{escape_name(c.uid)}"
        # No `~n` when the tolerance is the default: writing it out would
        # freeze today's number into a saved search that should follow it,
        # and the two forms must round-trip to different trees.
        return _quoted(atom + ("" if c.tol is None else f"~{c.tol}"))
    if isinstance(c, q.CaptionCond):
        tags = ",".join(("!" if t.exclude else "") + escape_name(t.name)
                        for t in c.caption_tags)
        kw = ("INSTRUCTION" if c.caption_kind == "instruction"
              else "CAPTION")
        return _quoted(f"{'!' if c.mode == 'hasnot' else ''}{kw}:{tags}")
    # link
    kw = "LINKEDBY" if c.direction in ("linkedby", "notlinkedby") else "LINK"
    neg = c.direction in ("hasnot", "notlinkedby")
    tags = ",".join(("!" if t.exclude else "") + escape_name(t.name)
                    for t in c.link_tags)
    return f"{'!' if neg else ''}{kw}:{tags}"


def _serialize_node(n, root: bool) -> str:
    if not isinstance(n, q.Group):
        return _serialize_cond(n)
    sep = "|" if n.op == "or" else " "
    inner = sep.join(_serialize_node(c, False) for c in n.children)
    if n.neg:
        return f"!({inner})"
    if root:
        return inner
    return f"({inner})" if len(n.children) > 1 else inner


def serialize(root: q.Group) -> str:
    """The canonical query string for a tree."""
    return _serialize_node(root, True)

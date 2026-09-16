"""Inventing a tag name for a subject, a place or an event.

The three identity kinds all do the same thing: turn a display name into a
slug, put the library's namespace prefix on it, and pick a free variant when
that name is taken. Each router had its own copy — `subjects.slugify` /
`subject_slug` / `free_slug`, and a `_slugify` / `_prefixed` pair in both
`places.py` and `events.py` — which is three implementations of one rule and
two of them subtly shorter than the first.

A tag the user TYPES is never touched by any of this. The prefix exists for
the name the app makes up, so that `place:berlin` and a plain `berlin` meaning
something else can both exist; what somebody typed is exactly what they asked
for.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import Tag
from ..prefs import read_tag_prefix

#: The kinds that have a namespace prefix setting.
KINDS = ("subject", "place", "event")


def slugify(name: str) -> str:
    """A display name as a tag name: lowercase, underscores, no punctuation.

    "Albert Einstein" -> albert_einstein. The result is only ever a SUGGESTION
    — the editor shows it and the user may change it — so this stays blunt
    rather than clever about scripts it does not know.
    """
    return re.sub(r"[^\w]+", "_", name.strip().lower(), flags=re.UNICODE).strip("_")


def prefixed(session: Session, kind: str, name: str) -> str:
    """The tag name to INVENT for a `kind` called `name`.

    Carries the library's namespace prefix for that kind (Settings →
    Behaviors), so a library that wants people in their own namespace gets
    `subject:albert_einstein` without anybody typing it. Empty when the name
    slugs to nothing.
    """
    slug = slugify(name)
    return f"{read_tag_prefix(session, kind)}{slug}" if slug else ""


def free_slug(session: Session, base: str, *, fallback: str = "subject") -> str:
    """``base``, or ``base_2``/``base_3``… when it is taken.

    Two people really can share a name; their records differ by comment and
    their tags differ by this suffix, which the user never has to type.
    """
    base = base or fallback
    taken = set(session.execute(
        select(Tag.name).where(Tag.name.like(f"{base}%"))
    ).scalars().all())
    if base not in taken:
        return base
    n = 2
    while f"{base}_{n}" in taken:
        n += 1
    return f"{base}_{n}"

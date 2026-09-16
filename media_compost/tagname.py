"""Tag names, and the NAMESPACE a colon reads out of one.

A namespace is not a thing. There is no table, no column and no migration: it
is the text before the first colon of an ordinary tag name, read on demand.
``costume:tiger`` and ``costume:dog`` are two tags that happen to share a
prefix, and everything the library already does with tags — search, facets,
counts, implications, aliases, sidecars, export — carries on knowing nothing
about it.

That the lowercase ``something:`` space is free for this is not an accident.
The query grammar matches its keywords UPPERCASE and case-SENSITIVELY
(``PLACE:``, ``SUBJECT:``) precisely so a lowercase ``place:berlin`` stays a
tag name, and the app's own minted subject / place / event tags already live
in namespaces by exactly this convention.

Mirrored on the frontend by ``frontend/src/app/tags.ts`` — like
``partialdate.py`` and ``subjects/when.ts``, both sides are pure and
unit-tested, and the rules below are the single definition of what a tag name
may look like.

Nothing READS a namespace today. It is a naming convention that
:func:`normalize` protects and the API enforces; the two lists that grouped by
it (the tag autocomplete, the Tags tab's filter) were both taken out again,
because "which tag" is a question a tag answers. :func:`namespace` and
:func:`basename` stay as the definition of what the colon rule is for.

Reading is TOTAL and writing is CONSTRAINED. :func:`namespace` and
:func:`basename` answer for any string at all, because a library restored from
a sidecar written before these rules can hold anything; :func:`normalize` is
what an input path applies, and the API refuses what it would have changed.
"""

from __future__ import annotations

import re

#: What separates a namespace from the rest of the name.
SEP = ":"

_WS = re.compile(r"\s+")


def normalize(name: str) -> str:
    """A typed tag name as it is stored.

    Whitespace collapses to underscores. That is the WHOLE rule: a colon is
    an ordinary character wherever it stands.

    A LEADING colon is KEPT (owner decision, 2026-09). It was dropped for a
    round, on the argument that ``:foo`` and ``foo`` render alike in every
    list — and the argument lost to the booru tag set, where the
    most-used expression tags are emoticons spelled ``:d``, ``:o``, ``:3``,
    ``:p``, and a rule that turned every one of them into a letter made the
    template unable to hold what a tagger writes most. Such a name simply
    has NO namespace (:func:`namespace` answers ``""`` for it, as it always
    did for a stored one), and the query grammar never reads it as a
    keyword: the keywords are UPPERCASE and anchored at the token's start,
    so ``:o`` in a search is the tag ``:o``, with ``!``/``-`` in front of
    it exactly as for any other name (the corpus pins it).

    **A TRAILING colon is KEPT too** (owner decision, 2026-09, the same
    argument one step further). It was dropped on the reading that
    ``costume:`` is half a name and storing it would put an empty row under
    a namespace — true of a half-typed prefix, and false of the tag set
    this library is built to hold: Danbooru spells three of its expression
    tags ``d:``, ``3:`` and ``c:``, and the rule silently turned each of
    them into a bare letter that collides with nothing anyone would ever
    search for. A name is what a tagger writes; the app does not get to
    decide that ``d:`` means ``d``. The cost is accepted and small: a field
    holding a half-typed ``costume:`` now offers to create exactly that
    tag, and a lone ``:`` is a legal (if silly) name. Nothing reads the
    namespace of ``d:`` — :func:`namespace` answers ``d`` and
    :func:`basename` ``""``, which is what a name ending in the separator
    means and no caller acts on.

    **INTERIOR colons are kept, however many there are.** They used to be
    turned into underscores past the first, on the argument that ``a:b:c``
    invites reading a hierarchy and this library already retired one. That
    argument was about what a namespace MEANS, and it was answered in the
    wrong place: nothing reads a namespace, nothing walks one, and refusing to
    store a name somebody typed does not stop them thinking in hierarchies —
    it only stops them writing ``costume:hat:straw`` at all, and silently
    turns it into something else. :func:`namespace` still splits on the FIRST
    colon and always did, so ``a:b:c`` reads as namespace ``a`` exactly as an
    old library's did.
    """
    return _WS.sub("_", name.strip())


def is_normalized(name: str) -> bool:
    """Whether :func:`normalize` would leave this name alone."""
    return name == normalize(name)


def namespace(name: str) -> str:
    """The part before the first colon, or ``""`` for a tag without one.

    Total on purpose: a name that predates the rules above still reads, and
    ``a:b:c`` is simply namespace ``a``. Case is preserved, because tag names
    preserve case — ``Costume:`` and ``costume:`` are two namespaces, which the
    autocomplete surfaces the moment both exist rather than quietly merging
    them behind the library's back.
    """
    head, sep, _rest = name.partition(SEP)
    return head if sep and head else ""


def basename(name: str) -> str:
    """The part after the first colon, or the whole name when there is none."""
    _head, sep, rest = name.partition(SEP)
    return rest if sep and _head else name

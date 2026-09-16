"""The structured search condition tree and its evaluator.

The query is parsed entirely in the frontend and sent to the backend as this
already-structured tree, so there is no query-string parser here — only an
evaluator. The same models are used by the web endpoints (parsed from JSON) and
by the scripting module (constructed in Python), and both call :func:`evaluate`.

A node is one of:

* :class:`Group` — ``op`` (``and``/``or``) over children, optionally negated
  (``neg`` — expresses the UI's "None of the following").
* :class:`TagCond` — an item tag, with ``have`` (has / has-not) and ``sign``
  (positive / negative assignment). The four combinations map to the legacy
  ``tag`` / ``!tag`` / ``-tag`` / ``!-tag`` atoms.
* :class:`LinkCond` — a relationship condition: ``direction`` picks
  outgoing/incoming and has/has-not, ``link_tags`` are required/excluded tags.
* :class:`MetaCond` — a typed metadata comparison; ``name`` is an intrinsic
  (live) or indexed (static) metadata name, resolved against the context.
* :class:`GroupCond` — group membership by group NAME (matched
  case-insensitively; group names are not unique, so any group with the name
  counts). ``mode``: ``has`` = the item is DIRECTLY in such a group,
  ``hasnot`` = it is not, ``ancestor`` = a strict ancestor of one of the
  item's groups carries the name (the item sits somewhere inside that
  group's subtree without being a direct member).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from . import grouppath
from . import partialdate as pdate
from .metadata_catalog import INTRINSIC, INTRINSIC_NAMES

# ---- request models --------------------------------------------------------


class CondModel(BaseModel):
    """A node of the condition tree, and therefore a REQUEST BODY — so it
    refuses unknown fields, exactly as `schemas.RequestModel` does one level
    up.

    The tree is INSIDE a body that was already strict, which is why this was
    missed: `ItemSearchRequest` refuses a misspelled `query`, and then hands
    what it finds to models that quietly dropped anything they did not
    recognise. Both directions of that were reproduced against a real library
    of 393 items:

    * `{"type": "group", "op": "and", "nodes": [...]}` — the field is
      `children` — answered 200 with all 393. An ignored `nodes` leaves an
      EMPTY group, and an empty group matches everything, so a request meaning
      "the ones at this place" meant "the library".
    * `{"type": "subject", "part": "tag", "op": "=", "value": "hinata"}` —
      `SubjectCond` has `name` and the date/age bounds and nothing else —
      answered with every item carrying ANY subject (26), where the right
      spelling answers 8. Every one of the three keys was dropped and `name`
      fell back to "", which is what "any subject" is spelled as.

    Neither said anything. A search that answers the wrong question with a 200
    is worse than one that refuses, because nothing downstream can tell.

    WHAT IT COSTS is the same thing `RequestModel` costs, in a place where it
    is likelier: a browser tab open across a deploy that also DROPS a field
    posts a tree carrying it and gets a 422, where before it got an answer.
    `PlaceCond.part` went that way today. Accepted deliberately — such a tab
    already has the update banner over it saying the backend has moved, and a
    grid that visibly fails is readable where a grid quietly showing the wrong
    pictures is not. Nothing PERSISTED holds an old tree: a saved search
    stores the query STRING (`schemas.SavedSearch`) and the address carries
    the text too, so both are re-parsed by whichever frontend is loaded.
    """

    model_config = ConfigDict(extra="forbid")


class LinkTagRef(CondModel):
    name: str
    # True = the relationship must NOT carry this tag (excluded); else required.
    exclude: bool = False


class TagCond(CondModel):
    """A tag on the item — named, or described by what the TAG SET says
    about it.

    ``meta_tags`` is the second form: with any, the condition stops asking
    about ``name`` and asks whether the item carries a tag whose own meta tags
    match (required / excluded, the shape :class:`CaptionCond` and
    :class:`LinkCond` already use). That is the whole of `TAG:noflip` — "a tag
    somebody marked noflip is on this picture" — and it needs no condition
    type of its own, because everything else about it (has/has-not, positive
    or negative assignment, implications, group grants) is what a tag
    condition already means.
    """

    type: Literal["tag"] = "tag"
    name: str
    have: bool = True  # False = "has not" (NOT the assignment)
    sign: Literal["pos", "neg"] = "pos"  # which assignment: positive or negative
    meta_tags: list[LinkTagRef] = []


class LinkCond(CondModel):
    type: Literal["link"] = "link"
    # has/hasnot = outgoing links; linkedby/notlinkedby = incoming links.
    direction: Literal["has", "hasnot", "linkedby", "notlinkedby"] = "has"
    link_tags: list[LinkTagRef] = []


class CaptionCond(CondModel):
    """Captions, optionally narrowed by meta tags — the caption-side twin of
    :class:`LinkCond` (same tag namespace, same required/excluded semantics).

    ``caption_kind`` picks WHICH list is asked about: descriptions of the
    picture, or the instructions saying how it was made from others. One
    condition with a kind rather than two condition types — they are one row
    type carrying the same meta tags, and the operators are identical. The
    default is "caption", so a query written before instructions existed keeps
    meaning exactly what it meant.
    """

    type: Literal["caption"] = "caption"
    # has = the item has a caption (matching the tags); hasnot = its negation.
    mode: Literal["has", "hasnot"] = "has"
    caption_kind: Literal["caption", "instruction"] = "caption"
    caption_tags: list[LinkTagRef] = []


class MetaCond(CondModel):
    type: Literal["meta"] = "meta"
    name: str
    mtype: Literal["numeric", "text", "date"] = "numeric"
    # numeric/date: > >= < <= = != ; text: = != ~ !~ (is/isnot/contains/not).
    op: str = "="
    value: Union[float, str] = ""
    # Half-width of the window a numeric "=" / "!=" accepts around `value`,
    # computed by the parser from the precision of the typed literal (see
    # `num_tolerance`). 0 = exact comparison; ignored by every other operator.
    tol: float = 0.0


class SubjectCond(CondModel):
    """A subject on the item, optionally narrowed by the STATE of that
    assignment.

    A subject is a tag, so "has this subject" is already `tag:`. This condition
    exists for what a tag cannot say: how old the subject was, or when the
    picture is from. An empty name asks whether the item has any subject at
    all.
    """

    type: Literal["subject"] = "subject"
    # The identity TAG's name (what the item actually carries). Empty = any.
    name: str = ""
    have: bool = True  # False = "has not"
    # Partial dates (YYYYMMDD with zeros, see partialdate) bounding the
    # assignment's date, and whole years bounding its age. None = unbounded.
    date_from: Optional[int] = None
    date_to: Optional[int] = None
    age_from: Optional[int] = None
    age_to: Optional[int] = None


class PlaceCond(CondModel):
    """Where the item is: a substring of the ADDRESS of a place it is at.

    ONE field, where there were eleven. The typed components went first, then
    the country; the identity TAG went last and for a different reason — a
    place IS a tag, so `PLACE.tag=tokyo` was the tag search wearing a second
    spelling, and the plain tag condition already answers it (better, in fact:
    it folds sequence containers, which this deliberately does not).

    Containment is a PARENT and needs nothing here: a place inside another
    implies it, so an item at Tokyo Tower already carries `tokyo` and `japan`
    by the time a query runs. A FIELD NAME still parses — `PLACE.city:Tokyo`,
    `PLACE.country=Japan`, `PLACE.tag=tokyo` are what a bookmark and a saved
    search hold — and is dropped: what is left matches the address, which is
    where those words now live.
    """

    type: Literal["place"] = "place"
    op: Literal["=", "~"] = "~"   # is | contains
    value: str = ""    # empty = "has any location at all"
    have: bool = True  # False = "has not"


class EventCond(CondModel):
    """An event on the item, optionally narrowed by WHEN the event was.

    An event is a tag, so "carries this event" is already `tag:`. This exists
    for what a tag cannot say: which events overlap a year. The date bounds the
    EVENT's own span, not the assignment's — `ItemTagWhen` dates an assignment
    and `subject:` is what reads that.
    """

    type: Literal["event"] = "event"
    # The identity TAG's name (what the item actually carries). Empty = any.
    name: str = ""
    have: bool = True  # False = "has not"
    # Partial dates (YYYYMMDD with zeros, see partialdate). None = unbounded.
    date_from: Optional[int] = None
    date_to: Optional[int] = None


class TakenCond(CondModel):
    """WHEN THE PICTURE WAS TAKEN — a window, not a point.

    Every item that has a capture date at all has a WINDOW, because a date
    knows how much of itself is known: "2020" is the whole year, "5 March 2020
    14:30" is one minute. The match is an OVERLAP, so a search for the first
    week of January finds a picture dated 2020.

    An item nobody dated falls back to **the span of the events it carries**: a
    photograph from a convention that ran 5–10 January was taken then, which is
    the most anyone can say and is enough to find it. A picture with a date of
    its own never uses that fallback — the specific answer wins over the
    inherited one, which is the whole point of having typed it.
    """

    type: Literal["taken"] = "taken"
    have: bool = True  # False = "nothing says when this was taken"
    # Partial YYYYMMDDHHMMSS values, like the metadata index's dates: fewer
    # components mean a wider window. None = unbounded on that side.
    date_from: Optional[int] = None
    date_to: Optional[int] = None


#: Largest colour tolerance accepted, over the 56-bit signature — a
#: usefulness bound, refused rather than clamped so a caller asking for more
#: is told rather than quietly answered with something else.
MAX_SIMILAR_TOL = 16

#: What a bare ``COLORLIKE:`` means. MEASURED, on the demo library's real
#: signatures — deliberately the worst case for colour, since it is mostly
#: greyscale manga, where colour-diverse content measures ~10x tighter.
#: Two things bracket it. The same picture re-encoded lands at
#: distance 0 (182,944 of 182,968 same-item file pairs), so 2 is already
#: well past "the same picture" and into "a similar palette", which is what
#: this asks. And it is the last value before the neighbourhood more than
#: doubles: 2 admits 2.75% of unrelated pairs where 3 admits 6.54% and 4
#: admits 11.80%.
#:
#: It USED to be the library's ``phash_threshold`` (10), a 256-bit near-dup
#: setting read against a 56-bit palette hash — which admitted **72% of all
#: unrelated pairs**, so "find similar colours" on a million-item library
#: answered with three quarters of it. That is what made the feature both
#: useless and slow (see `searchctx.load_similar_sets`).
DEFAULT_COLOR_TOL = 2


class SimilarCond(CondModel):
    """Pictures whose PALETTE is like one particular picture's.

    Similarity is PAIRWISE, so unlike every other condition here this one
    names a pivot: an item uid, plus how far from it still counts. That is
    also why it is a condition rather than a sort — a sort has nowhere to put
    the pivot, while a condition composes with every other filter, survives in
    a saved search, and goes through the one search endpoint.

    ``by`` HAS ONE VALUE, and the field survives because a stored tree
    carries it. There was a second, "visual", over the 256-bit perceptual
    hash — the same one dedup matches on — and it was removed with the grid
    action that was its only door: the importer FOLDS a re-encode, a crop and
    a rotation onto the item they match, so by the time a library has been
    imported the visually-near-identical pictures are one item and the search
    reliably found that item and nothing else. Keeping the field as a
    one-value Literal is what makes an old ``by: "visual"`` node a 422 naming
    it rather than a silently different answer.

    ``tol`` is a Hamming distance over the 56-bit colour signature; None
    means :data:`DEFAULT_COLOR_TOL`.
    """

    type: Literal["similar"] = "similar"
    by: Literal["color"] = "color"
    uid: str = ""
    tol: Optional[int] = None
    have: bool = True

    def key(self) -> str:
        """Identity of the SET this condition asks about.

        The resolved id set is the same for every node with these three
        values, and a query may hold several of them (two pivots, or one
        pivot in both spaces), so the context carries membership per key
        rather than one flat "is similar" flag."""
        return f"{self.by}:{self.uid}:{'' if self.tol is None else self.tol}"


class ValueCond(CondModel):
    """Tags read as NUMBERS — the ``<name>:<number><unit>`` convention.

    ``name`` is a NAMESPACE, not a tag: ``VALUE:height>190cm`` matches an
    item carrying ANY tag ``height:<something>`` whose basename parses as a
    value satisfying the comparison (`tagvalue.py` is the one definition of
    what parses and which units convert). The tags themselves are ordinary —
    assigned, implied, granted — so the match is read off the item's
    effective positive tags, exactly as a tag condition is.

    Which names match is a question about the CATALOG, not the item, so it is
    resolved once per search (`searchctx.load_value_sets`) and rides on the
    context as a name set per :meth:`key` — the ``SIMILAR:`` shape, which is
    also what lets the SQL compiler and the residue evaluator read one
    answer.

    ``tol`` is the metadata rule: half the last decimal place the literal was
    typed to, applied by ``=``/``!=`` as a half-open window, computed while
    the text still shows the decimals (a JSON number has already lost them).
    It is in the literal's own unit and converts with it.
    """

    type: Literal["value"] = "value"
    name: str = ""
    op: Literal["=", "!=", ">", ">=", "<", "<="] = ">="
    value: float = 0.0
    unit: str = ""
    tol: float = 0.0
    have: bool = True

    def key(self) -> str:
        """Identity of the resolved name set (same literal → same set)."""
        return f"{self.name}:{self.op}:{self.value}:{self.unit}:{self.tol}"


class GroupCond(CondModel):
    # "ingroup" because the boolean node already owns the "group" type tag.
    type: Literal["ingroup"] = "ingroup"
    name: str
    # has = in that group OR in any group under it — what selecting the group
    # in the sidebar shows (owner 2026-09: `GROUP:c` missed the pictures
    # filed in `c/d`; it had been direct membership since the keyword was
    # made); hasnot = its negation. only = filed in that group ITSELF
    # (`GROUPONLY:`), notonly = its negation.
    mode: Literal["has", "hasnot", "only", "notonly"] = "has"


class Group(CondModel):
    type: Literal["group"] = "group"
    op: Literal["and", "or"] = "and"
    neg: bool = False  # negate the whole group ("None of the following")
    children: "list[Node]" = []


Node = Annotated[
    Union[Group, TagCond, LinkCond, CaptionCond, MetaCond, GroupCond,
          SubjectCond, PlaceCond, EventCond, TakenCond, SimilarCond,
          ValueCond],
    Field(discriminator="type"),
]
Group.model_rebuild()


#: Every condition model by its `type` discriminator. One list, so a kind
#: added to `Node` without a line here is caught by the union's own tests.
_BY_TYPE: dict[str, type[BaseModel]] = {
    m.model_fields["type"].default: m
    for m in (Group, TagCond, LinkCond, CaptionCond, MetaCond, GroupCond,
              SubjectCond, PlaceCond, EventCond, TakenCond, SimilarCond,
              ValueCond)
}


def _child_model(annotation: object) -> Optional[type[BaseModel]]:
    """The model a field holds, where that is ONE model.

    `list[LinkTagRef]` answers `LinkTagRef`. `list[Node]` is a discriminated
    UNION and answers None — the recursion then reads each child's own `type`,
    which is the whole point of the discriminator.
    """
    from typing import get_args, get_origin

    seen: list[type[BaseModel]] = []
    todo = [annotation]
    while todo:
        at = todo.pop()
        if isinstance(at, type) and issubclass(at, BaseModel):
            seen.append(at)
        elif get_origin(at) is not None or get_args(at):
            todo.extend(get_args(at))
    return seen[0] if len(seen) == 1 else None


def prune_unknown(node: object, model: Optional[type[BaseModel]] = Group) -> object:
    """A STORED tree with the keys today's models no longer declare removed.

    For a REQUEST this is exactly what `CondModel` refuses to do: a key nobody
    recognises is a question nobody answered, and answering it anyway is the
    silence that rule exists to end. For a tree already ON DISK it is the only
    alternative to unreadable — a training job keeps its dataset selection as
    a `Group` inside its own `config.json` (`train.spec.DatasetQuery.tree`),
    written by whatever build made that job, so a field dropped since then
    would stop the job being opened, edited or run rather than merely making
    it imperfect. `PlaceCond.part` went that way the day the models became
    strict.

    The MIRROR of `train.manager._fill_defaults`, which is the same problem
    from the other side (a config written before a setting existed lacks that
    key, and every reader wants today's default). Both belong to reading a
    file some other build wrote.

    A node whose `type` nothing recognises is left ALONE, so the union still
    refuses it BY NAME — "there is no such condition" is a real answer, and
    quietly deleting the node would not be.
    """
    if isinstance(node, list):
        return [prune_unknown(x, model) for x in node]
    if not isinstance(node, dict):
        return node
    kind = node.get("type")
    if kind is not None:
        model = _BY_TYPE.get(kind)
    if model is None:
        return node
    out: dict = {}
    for key, value in node.items():
        field_info = model.model_fields.get(key)
        if field_info is None:
            continue        # a key this build no longer declares
        out[key] = prune_unknown(value, _child_model(field_info.annotation))
    return out



# ---- evaluation context ----------------------------------------------------


@dataclass
class MetaVal:
    """An item's indexed value for one metadata name."""
    mtype: str
    num: Optional[float] = None
    text: Optional[str] = None


@dataclass
class QueryCtx:
    """Everything an item's predicate is evaluated against.

    ``nums`` holds intrinsic (live-computed) metadata; ``meta`` holds indexed
    static metadata by name; ``out_links``/``in_links`` are the link-tag sets of
    the item's outgoing/incoming relationships (one frozenset per relationship).

    ``meta`` is a LIST per name, because an item genuinely answers with more
    than one: what its active file says, plus whatever has been promoted to the
    item itself. `searchctx.load_indexed_meta` is the one place that union is
    built.
    """
    tags: frozenset[str] = frozenset()
    neg: frozenset[str] = frozenset()
    nums: dict[str, float] = field(default_factory=dict)
    texts: dict[str, str] = field(default_factory=dict)  # intrinsic text (e.g. type)
    meta: dict[str, list[MetaVal]] = field(default_factory=dict)
    out_links: list[frozenset[str]] = field(default_factory=list)
    in_links: list[frozenset[str]] = field(default_factory=list)
    # Meta-tag sets of the item's captions — one frozenset per caption (empty
    # for an untagged caption), so "has a caption" is simply a non-empty list.
    # Instructions are their OWN list: they are the same row type carrying the
    # same meta tags, so folding them together would make a search for "has a
    # caption" answer yes for an item that only says how it was made.
    captions: list[frozenset[str]] = field(default_factory=list)
    instructions: list[frozenset[str]] = field(default_factory=list)
    # Lowercased names of the item's DIRECT groups (the "only" mode), and of
    # the strict ancestors of those groups; "has" is the union of the two.
    groups: frozenset[str] = frozenset()
    group_ancestors: frozenset[str] = frozenset()
    #: The same two as full PATHS, which is what a condition naming one of
    #: several same-named groups is matched against (`grouppath`).
    group_paths: frozenset[str] = frozenset()
    group_ancestor_paths: frozenset[str] = frozenset()
    # The item's subjects: identity tag name -> every (date, age) claimed for
    # it here, either half of which may be None ("carried, but nobody said
    # when"). A LIST because one picture can hold several answers — the
    # assignment's own, plus one per dated face — and a page showing somebody
    # at two ages has two, neither truer than the other.
    subjects: dict[str, list[tuple[Optional[int], Optional[int]]]] = field(
        default_factory=dict)
    # The item's places: one ADDRESS LINE per place it is at, "" for a place
    # that has none (a photo's bare GPS, and a place whose only identity is
    # its tag) — which still counts for the bare `PLACE:`.
    places: list[str] = field(default_factory=list)
    # The item's events: identity tag name -> that event's own (start, end)
    # partial dates, either of which may be None. A plain tuple rather than a
    # list of them, unlike `subjects`: a subject's state lives on the
    # ASSIGNMENT and a second answer arrives from each dated face, while an
    # event's span lives on the catalog row — one occasion, one span, and a
    # list whose second element could never exist is a lie about the shape.
    events: dict[str, tuple[Optional[int], Optional[int]]] = field(
        default_factory=dict)
    # When the picture was taken, as an inclusive [low, high] window over the
    # YYYYMMDDHHMMSS space — the item's own date if it has one, else the span
    # of its events. None when nothing says.
    taken: Optional[tuple[int, int]] = None
    # The `SimilarCond.key()` of every likeness condition this item satisfies.
    # Membership rather than a hash, because "close to that picture" is a
    # question about the whole library and cannot be answered from one item's
    # own row — `searchctx.load_similar_sets` resolves each pivot once per
    # query and this records which of the answers the item is in.
    similar: frozenset[str] = frozenset()
    # What the tag set says about each tag NAME: tag -> its meta tags.
    # CATALOG-wide and shared by every item's context rather than per item,
    # because that is what it is — the answer for `TAG:noflip` is then read
    # off the item's own `tags`/`neg`, with no second per-item load.
    tag_meta: dict[str, frozenset[str]] = field(default_factory=dict)
    # Each `ValueCond.key()` resolved to the CATALOG's matching tag names
    # (`searchctx.load_value_sets`). Shared like `tag_meta` — which names
    # satisfy `height>190cm` is a fact about the tag set, and the item's
    # answer is then read off its own effective `tags`.
    value_tags: dict[str, frozenset[str]] = field(default_factory=dict)


# ---- comparison helpers ----------------------------------------------------

_NUM_OPS = {
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "=": lambda a, b: abs(a - b) < 1e-9,
    "!=": lambda a, b: abs(a - b) >= 1e-9,
}
# Operators that hold true for an item lacking the metadata value entirely
# ("is not X" / "doesn't contain X" / "!= X" are satisfied by an absent value).
_NEG_OPS = {"!=", "!~"}
#: The POSITIVE twin of each negative operator. A metadata name can hold several
#: values (the active file's, plus any pinned to the item), and there "not X"
#: has to mean "no value is X" rather than "some value is not X" — the latter is
#: satisfied by any second value at all, so an item pinned to two makers would
#: match `INFO:camera_make!=Canon` while plainly being a Canon. So a negative is
#: evaluated by asking its positive form and inverting the whole answer, which
#: also subsumes the absent-value case: nothing to match, so the negative holds.
_POSITIVE_OF = {"!=": "=", "!~": "~"}


def num_tolerance(text: str) -> float:
    """Half of the last decimal place a searched value was *written* to.

    Numeric equality is *precision-aware*, mirroring how dates already work
    (searching ``2026`` matches the whole year): the number of decimals the
    user typed states how precisely they mean it. ``0.7`` means "about 0.7"
    and tolerates ±0.05, while ``0.75`` narrows that to ±0.005 — so a stored
    value matches exactly when it would round to what was searched for.
    Whole numbers get ±0.5, which changes nothing for integer-valued fields
    (widths, counts) but makes ``mp=8`` mean "about 8 megapixels".

    This lives here as the definition of the rule, but the *evaluator never
    calls it*: precision is a property of the typed literal, and a JSON
    number has already lost it (``0.70`` arrives indistinguishable from
    ``0.7``). The frontend parser therefore computes the window while it
    still has the text and sends it along as ``MetaCond.tol``; this helper
    exists for callers that build conditions from strings themselves
    (scripting, tests) and mirrors ``numTolerance`` in ``query/tree.ts``.
    """
    text = str(text).strip()
    if "e" in text.lower():          # scientific notation: compare exactly
        return 0.0
    decimals = len(text.split(".", 1)[1]) if "." in text else 0
    return 0.5 * (10.0 ** -decimals)


def _num_cmp(op: str, a: float, b: float, tol: float = 0.0) -> bool:
    # Equality windows are half-open at the top so a value sitting exactly on
    # the midpoint belongs to the higher bucket, like ordinary rounding:
    # 0.75 matches 0.8, not 0.7. Ordered comparisons stay strict — only
    # "is it this value" is fuzzy, "is it bigger than" is not.
    if tol > 0 and op in ("=", "!="):
        inside = b - tol <= a < b + tol
        return inside if op == "=" else not inside
    fn = _NUM_OPS.get(op)
    return bool(fn(a, b)) if fn else False


def _text_cmp(op: str, actual: str, target: str) -> bool:
    a, t = actual.lower(), target.lower()
    if op == "=":
        return a == t
    if op == "!=":
        return a != t
    if op == "~":
        return t in a
    if op == "!~":
        return t not in a
    return False


def _date_bounds(value) -> Optional[tuple[int, int]]:
    """Parse a date value into an inclusive ``[low, high]`` window over the
    sortable ``YYYYMMDDHHMMSS`` space, at whatever precision the caller gave.

    Separators are ignored, so ``2026-07-12T22:12:16``, ``20260712221216``,
    ``2026-07-12`` and ``20260712`` are all accepted. Fewer components = a wider
    window: ``2026-07-12`` covers the whole day, ``2026-07`` the whole month,
    ``2026`` the whole year. The bounds pad the given prefix with 0s (low) and 9s
    (high) — since the decimal representation is chronologically ordered, this
    brackets exactly the requested period. Returns None if there aren't at least
    a 4-digit year to work with."""
    # Pydantic stores numeric values as float; render integral ones without the
    # trailing ".0" so the fractional zero isn't mistaken for a date component.
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    digits = re.sub(r"\D", "", str(value))[:14]
    if len(digits) < 4:
        return None
    low = int(digits + "0" * (14 - len(digits)))
    high = int(digits + "9" * (14 - len(digits)))
    return low, high


def _date_cmp(op: str, actual: float, value) -> bool:
    """Compare an item's ``YYYYMMDDHHMMSS`` date against a (possibly lower-
    precision) target. ``=`` matches when the item falls anywhere in the target's
    period; the ordered operators compare against the near/far edge of it."""
    bounds = _date_bounds(value)
    if bounds is None:
        try:
            return _num_cmp(op, actual, float(value))
        except (TypeError, ValueError):
            return False
    low, high = bounds
    a = int(actual)
    if op == "=":
        return low <= a <= high
    if op == "!=":
        return not (low <= a <= high)
    if op == ">":
        return a > high
    if op == ">=":
        return a >= low
    if op == "<":
        return a < low
    if op == "<=":
        return a <= high
    return False


def _eval_meta(node: MetaCond, ctx: QueryCtx) -> bool:
    if node.name in INTRINSIC_NAMES:
        kind = INTRINSIC.get(node.name)
        if kind == "text":
            return _text_cmp(node.op, ctx.texts.get(node.name, ""), str(node.value))
        actual = ctx.nums.get(node.name, 0.0)
        if kind == "date":
            return _date_cmp(node.op, actual, node.value)
        try:
            return _num_cmp(node.op, actual, float(node.value), node.tol)
        except (TypeError, ValueError):
            return False
    # An item answers with SEVERAL values for one name: what its active file
    # says, plus whatever has been pinned to the item. So a positive operator
    # is "any of them matches" and a negative one is "NONE of them matches its
    # positive form" — the same reading `_eval_caption` gives a list of
    # captions, and a strict generalisation of the single-value behaviour that
    # came before it, absent-value case included (no values, nothing to match,
    # so only the negatives are satisfied).
    values = ctx.meta.get(node.name) or []
    positive = _POSITIVE_OF.get(node.op, node.op)
    hit = any(_meta_one(positive, mv, node) for mv in values)
    return (not hit) if node.op in _NEG_OPS else hit


def _meta_one(op: str, mv: MetaVal, node: MetaCond) -> bool:
    """Whether ONE indexed value satisfies a POSITIVE comparison."""
    if mv.mtype == "text":
        return _text_cmp(op, mv.text or "", str(node.value))
    if mv.mtype == "date":
        return _date_cmp(op, mv.num or 0.0, node.value)
    try:
        return _num_cmp(op, mv.num or 0.0, float(node.value), node.tol)
    except (TypeError, ValueError):
        return False


def _eval_caption(node: CaptionCond, ctx: QueryCtx) -> bool:
    required = {t.name.lower() for t in node.caption_tags if not t.exclude}
    excluded = {t.name.lower() for t in node.caption_tags if t.exclude}
    rows = (ctx.instructions if node.caption_kind == "instruction"
            else ctx.captions)
    if not node.caption_tags:
        matched = len(rows) > 0
    else:
        matched = any(
            required <= tagset and not (excluded & tagset)
            for tagset in rows
        )
    return (not matched) if node.mode == "hasnot" else matched


def _any_tag_with_meta(node: TagCond, pool: frozenset[str],
                       ctx: QueryCtx) -> bool:
    """Whether any tag in ``pool`` carries the asked-for meta tags.

    Required / excluded per TAG, not across the item: `TAG:en,!draft` means
    "a tag marked en and not draft", the same reading `CAPTION:en,!draft` has
    over one caption. An item whose `hair` is en and whose `pose` is draft
    therefore matches — two tags, and the first satisfies the condition.
    """
    required = {t.name.lower() for t in node.meta_tags if not t.exclude}
    excluded = {t.name.lower() for t in node.meta_tags if t.exclude}
    for name in pool:
        metas = {m.lower() for m in ctx.tag_meta.get(name, ())}
        if required <= metas and not (excluded & metas):
            return True
    return False


def _eval_link(node: LinkCond, ctx: QueryCtx) -> bool:
    outgoing = node.direction in ("has", "hasnot")
    negate = node.direction in ("hasnot", "notlinkedby")
    links = ctx.out_links if outgoing else ctx.in_links
    required = {t.name.lower() for t in node.link_tags if not t.exclude}
    excluded = {t.name.lower() for t in node.link_tags if t.exclude}
    if not node.link_tags:
        matched = len(links) > 0
    else:
        matched = any(
            required <= tagset and not (excluded & tagset) for tagset in links
        )
    return (not matched) if negate else matched


def evaluate(node: "Node", ctx: QueryCtx) -> bool:
    """True if the item described by ``ctx`` satisfies the condition ``node``."""
    if isinstance(node, Group):
        if not node.children:
            val = True  # an empty group matches everything
        elif node.op == "or":
            val = any(evaluate(c, ctx) for c in node.children)
        else:
            val = all(evaluate(c, ctx) for c in node.children)
        return (not val) if node.neg else val
    if isinstance(node, TagCond):
        pool = ctx.neg if node.sign == "neg" else ctx.tags
        if node.meta_tags:
            present = _any_tag_with_meta(node, pool, ctx)
        else:
            present = node.name.lower() in pool
        return present if node.have else (not present)
    if isinstance(node, SimilarCond):
        present = node.key() in ctx.similar
        return present if node.have else (not present)
    if isinstance(node, ValueCond):
        names = ctx.value_tags.get(node.key(), frozenset())
        present = not names.isdisjoint(ctx.tags) if names else False
        return present if node.have else (not present)
    if isinstance(node, MetaCond):
        return _eval_meta(node, ctx)
    if isinstance(node, CaptionCond):
        return _eval_caption(node, ctx)
    if isinstance(node, LinkCond):
        return _eval_link(node, ctx)
    if isinstance(node, SubjectCond):
        return _eval_subject(node, ctx)
    if isinstance(node, PlaceCond):
        return _eval_place(node, ctx)
    if isinstance(node, EventCond):
        return _eval_event(node, ctx)
    if isinstance(node, TakenCond):
        return _eval_taken(node, ctx)
    if isinstance(node, GroupCond):
        direct = _group_hit(node.name, ctx.groups, ctx.group_paths)
        above = _group_hit(node.name, ctx.group_ancestors,
                           ctx.group_ancestor_paths)
        present = direct if node.mode in ("only", "notonly") else (
            direct or above)
        return present if node.mode in ("has", "only") else not present
    return True


def _group_hit(value: str, names: frozenset[str],
               paths: frozenset[str]) -> bool:
    """`prefilter._compile_group`'s rule, read off the item's own sets: the
    value is a FULL PATH from the root (`grouppath.hit`), so `names` — the
    bare-name sets kept for the facets — take no part in it. The two must
    stay the same answer — `test_search_equivalence` drives both."""
    del names
    return grouppath.hit(value, paths)


def _eval_place(node: "PlaceCond", ctx: QueryCtx) -> bool:
    """Whether the item is at a place whose ADDRESS matches.

    An empty value asks whether the item has ANY location — the same shape
    `caption:` uses for "has a caption at all" — and a place with no address
    at all (a photo's bare GPS) answers that one and no other.
    """
    needle = node.value.strip().lower()
    if not needle:
        present = bool(ctx.places)
        return present if node.have else (not present)

    def hit(address: str) -> bool:
        v = (address or "").lower()
        if not v:
            return False
        return v == needle if node.op == "=" else needle in v

    present = any(hit(p) for p in ctx.places)
    return present if node.have else (not present)


def _span_overlaps(node: "EventCond",
                   span: tuple[Optional[int], Optional[int]]) -> bool:
    """The event's span against the query's, by what each COVERS.

    OVERLAP, not containment: an event running 30 Dec 2014 – 2 Jan 2015 answers
    `event:@2014` and `event:@2015` both, because it did. A bound only ever
    narrows, the same rule `_state_matches` applies to a subject's age — an
    event nobody dated cannot satisfy one.

    `pdate.bounds`, never `_date_bounds` below: that one decodes the metadata
    index's YYYYMMDDHHMMSS, and shadowing the two broke date search once.
    """
    start, end = span
    if start is None and end is None:
        return False
    # A half-open span is read as a point: "from July 2014" with no end covers
    # July 2014, which is the only thing actually known.
    lo = pdate.bounds(start or end)[0]
    hi = pdate.bounds(end or start)[1]
    if node.date_from is not None and hi < pdate.bounds(node.date_from)[0]:
        return False
    if node.date_to is not None and lo > pdate.bounds(node.date_to)[1]:
        return False
    return True


def _eval_event(node: "EventCond", ctx: QueryCtx) -> bool:
    """Whether the item carries the event, in the span asked for."""
    name = node.name.strip().lower()
    hits = [span for tag, span in ctx.events.items() if not name or tag == name]
    if node.date_from is not None or node.date_to is not None:
        hits = [span for span in hits if _span_overlaps(node, span)]
    present = bool(hits)
    return present if node.have else (not present)


def taken_window(value) -> tuple[int, int]:
    """The inclusive ``[low, high]`` a partial YYYYMMDDHHMMSS covers.

    **Trailing zeros are the unknown part**, exactly as `partialdate` reads a
    YYYYMMDD — so `20200000000000` is the whole of 2020. That is what makes a
    search for the first week of January find a picture dated only "2020", and
    it is why this is not `_date_bounds`: that one reads a SHORT value as
    coarse (it is given "2026-07" and pads), while a stored capture date is
    always fourteen digits wide and says its precision with zeros.

    Padded on the right, so a value given at any width reads the same: an
    event's YYYYMMDD and an item's YYYYMMDDHHMMSS are the same date.
    """
    digits = str(int(value)).ljust(14, "0")[:14]
    keep = 4
    for start in (4, 6, 8, 10, 12):
        if digits[start:start + 2] != "00":
            keep = start + 2
    return (int(digits[:keep] + "0" * (14 - keep)),
            int(digits[:keep] + "9" * (14 - keep)))


def _eval_taken(node: "TakenCond", ctx: QueryCtx) -> bool:
    """Whether the item's capture window overlaps the one asked for."""
    if ctx.taken is None:
        return not node.have
    lo, hi = ctx.taken
    want_lo = taken_window(node.date_from)[0] if node.date_from else None
    want_hi = taken_window(node.date_to)[1] if node.date_to else None
    if want_lo is not None and hi < want_lo:
        return not node.have
    if want_hi is not None and lo > want_hi:
        return not node.have
    return node.have


def _eval_subject(node: "SubjectCond", ctx: QueryCtx) -> bool:
    """Whether the item carries the subject, in the state asked for.

    A state bound only ever NARROWS: an assignment nobody dated cannot satisfy
    "aged 10 to 14", because the honest answer is that we do not know.
    """
    name = node.name.strip().lower()
    hits = ([(k, v) for k, v in ctx.subjects.items() if k == name] if name
            else list(ctx.subjects.items()))
    bounded = any(x is not None for x in
                  (node.date_from, node.date_to, node.age_from, node.age_to))
    if bounded:
        # ANY of the states the item claims for that subject will do.
        hits = [(k, v) for k, v in hits
                if any(_state_matches(node, st) for st in v)]
    present = bool(hits)
    return present if node.have else (not present)


def _state_matches(node: "SubjectCond",
                   state: tuple[Optional[int], Optional[int]]) -> bool:
    date, age = state
    if node.date_from is not None or node.date_to is not None:
        if date is None:
            return False
        # A partial date is compared by what it COVERS: a picture dated 1921
        # is inside 1910..1920 only if the whole year is. (`partialdate.bounds`,
        # NOT the metadata `_date_bounds` above — these are different encodings
        # and shadowing one with the other quietly broke date search once.)
        lo, hi = pdate.bounds(date)
        if node.date_from is not None and hi < pdate.bounds(node.date_from)[0]:
            return False
        if node.date_to is not None and lo > pdate.bounds(node.date_to)[1]:
            return False
    if node.age_from is not None or node.age_to is not None:
        if age is None:
            return False
        if node.age_from is not None and age < node.age_from:
            return False
        if node.age_to is not None and age > node.age_to:
            return False
    return True


# ---- tree inspection (which data must the search path load?) ---------------


def _walk(node: "Node"):
    yield node
    if isinstance(node, Group):
        for c in node.children:
            yield from _walk(c)


def references_places(node: "Node") -> bool:
    """True if any condition needs the item's places loaded."""
    return any(isinstance(n, PlaceCond) for n in _walk(node))


def references_events(node: "Node") -> bool:
    """True if any condition needs the item's events loaded."""
    return any(isinstance(n, EventCond) for n in _walk(node))


def references_taken(node: "Node") -> bool:
    """True if any condition needs the item's capture window loaded."""
    return any(isinstance(n, TakenCond) for n in _walk(node))


def references_similar(node: "Node") -> bool:
    """True if the tree asks about likeness to a pivot picture — resolving one
    is a question about the whole library, so it is only paid for when asked."""
    return any(isinstance(n, SimilarCond) for n in _walk(node))


def similar_conditions(node: "Node") -> list["SimilarCond"]:
    """Every similarity condition in the tree, for the loader to resolve."""
    return [n for n in _walk(node) if isinstance(n, SimilarCond)]


def references_values(node: "Node") -> bool:
    """True if the tree reads any tag as a number — resolving which names
    match is a pass over the catalog, so it is only paid for when asked."""
    return any(isinstance(n, ValueCond) for n in _walk(node))


def value_conditions(node: "Node") -> list["ValueCond"]:
    """Every value condition in the tree, for the loader to resolve."""
    return [n for n in _walk(node) if isinstance(n, ValueCond)]


def references_subjects(node: "Node") -> bool:
    """True if any condition needs the item's subjects loaded — the set is one
    query over the whole library, so it is only paid for when asked for."""
    return any(isinstance(n, SubjectCond) for n in _walk(node))


def referenced_indexed_meta(node: "Node") -> bool:
    """True if any MetaCond names a non-intrinsic (indexed) metadata name."""
    return any(
        isinstance(n, MetaCond) and n.name not in INTRINSIC_NAMES
        for n in _walk(node)
    )


def references_links(node: "Node") -> bool:
    """True if the tree contains any link condition."""
    return any(isinstance(n, LinkCond) for n in _walk(node))


def references_captions(node: "Node") -> bool:
    """True if the tree contains any caption condition (so the search only
    loads caption meta tags when something asks about them)."""
    return any(isinstance(n, CaptionCond) for n in _walk(node))


def references_groups(node: "Node") -> bool:
    """True if the tree contains any group-membership condition."""
    return any(isinstance(n, GroupCond) for n in _walk(node))


def references_tag_meta(node: "Node") -> bool:
    """True if any tag condition asks what the tag set says about a tag —
    the one map that is catalog-wide rather than per item, so it is read only
    when something asks."""
    return any(isinstance(n, TagCond) and n.meta_tags for n in _walk(node))


def referenced_meta_names(node: "Node") -> frozenset[str]:
    """Every metadata name the tree compares against (intrinsic or indexed)."""
    return frozenset(n.name for n in _walk(node) if isinstance(n, MetaCond))


def is_empty(node: "Node") -> bool:
    """True for a query that matches everything (an empty root group)."""
    return isinstance(node, Group) and not node.children

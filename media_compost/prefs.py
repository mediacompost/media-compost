"""Library-GLOBAL settings, read straight from the key/value store.

These are the settings that shape the shared library rather than one person's
view of it: what a newly-invented subject/place/event tag is prefixed with, and
how alike two faces must be before a detection names itself. Two people tagging
one library into two different namespaces is not a preference, it is a mess —
so unlike language, date format and the double-click actions (which live
per-user in the settings router), these are one value for everybody.

They live HERE rather than in ``server/routers/settings.py`` because core reads
them. ``facevec.py`` needs the face threshold and the subject/place/event
routers need the prefixes; with the readers in a router, a core module had to
import from ``server/`` to get at them, which points the dependency arrow the
wrong way round. Nothing in this module imports ``server``.

The settings router still owns WRITING these (it validates the whole
``AppSettings`` payload) and re-exports the readers, so its callers are
unchanged.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from .db import get_setting

# ---- setting keys -----------------------------------------------------------
# Every key the `settings` table holds, in one place. `PREFS` and
# `SAVED_SEARCHES` are per-user BASES (see `server.routers.settings.user_key`);
# the other two are global.
MODEL_PATHS = "model_paths"        # global: deployment-level model path overrides
PREFS = "prefs"                    # per-user base: personal UI prefs
PREFS_GLOBAL = "prefs_global"      # global: tag prefixes, face threshold, Florence
SAVED_SEARCHES = "saved_searches"  # per-user base
TAG_SET_ORDER = "tag_set_order"    # per-user base: which set describes a tag first


def read_json(s: Session, key: str) -> dict:
    """A settings value parsed as a JSON object, or ``{}`` for anything else.

    Never raises: an unset key, invalid JSON and a non-object payload all read
    as empty, because a settings blob is not worth failing a request over.
    """
    raw = get_setting(s, key, "")
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


# ---- tag prefixes -----------------------------------------------------------

# What a newly-invented tag of each kind is prefixed with. A namespace per kind
# is the point: `place:berlin` and `berlin` can then both exist, one naming a
# where and one naming whatever else somebody means by it.
TAG_PREFIX_DEFAULTS = {
    "subject": "subject:", "place": "place:", "event": "event:",
}


def read_tag_prefix(s: Session, kind: str) -> str:
    """What a newly-invented tag of `kind` is prefixed with, e.g. "place:".

    Global rather than per-user: it decides what the tag catalog looks like,
    and two people tagging one library into two different namespaces is not a
    preference, it is a mess. Whitespace only would prefix nothing, so it is
    stripped away to "".

    A MISSING key takes the default; a key stored as "" means somebody asked
    for no prefix. `or ""` would conflate the two and quietly re-namespace a
    library that had opted out.

    LOWERCASED, like every tag this app mints from a typed name: the prefix is
    the front of a tag name, and `Subject:alice` beside `subject:alice` is two
    namespaces nobody meant to make. Applied on the way OUT as well as on the
    way in (the settings router lowercases what it stores) so a value written
    by an older build still mints the right thing without being re-saved
    first.
    """
    default = TAG_PREFIX_DEFAULTS.get(kind, "")
    raw = read_json(s, PREFS_GLOBAL).get(f"{kind}_tag_prefix", default)
    return str(raw or "").strip().lower()


# ---- namespaces kept out of the autocomplete --------------------------------

def read_hidden_namespaces(s: Session) -> list[str]:
    """The namespaces whose tags are not SUGGESTED, lowercased.

    A namespace is the text before a tag name's first colon and nothing
    else — no column, no table (`tagname.py`) — so the list of hidden ones
    is a SETTING rather than a flag on rows that do not exist. Global, like
    the prefixes and for the same reason: which tag set a library offers
    while you type is a fact about the library, not a personal view of it.

    Stored WITHOUT the colon, the way `tagname.namespace` answers, so the
    two cannot disagree about whether `character` and `character:` are the
    same thing.
    """
    raw = read_json(s, PREFS_GLOBAL).get("hidden_namespaces", [])
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for n in raw:
        clean = str(n or "").strip().lower().rstrip(":")
        if clean and clean not in out:
            out.append(clean)
    return out


# ---- detection tag names ----------------------------------------------------

#: What the watermark detector tags what it finds with. The box-driven
#: watermark REMOVAL reads the same name, which is what makes the two halves
#: one workflow: detect writes the boxes, remove inpaints them.
WATERMARK_TAG_DEFAULT = "watermark"


def read_watermark_tag(s: Session) -> str:
    """The tag detected watermarks are recorded under (with their boxes).

    Global like the prefixes: it decides what lands in the shared catalog.
    Empty falls back to the default rather than switching the feature off —
    the box-driven removal needs A name to read, and a detect action that
    silently tagged nothing would read as a detector that finds nothing.
    """
    from . import tagname

    raw = read_json(s, PREFS_GLOBAL).get("watermark_tag",
                                         WATERMARK_TAG_DEFAULT)
    return (tagname.normalize(str(raw or "").strip().lower())
            or WATERMARK_TAG_DEFAULT)


def read_text_tag(s: Session) -> str:
    """The tag an OCR run additionally records its regions' boxes under.

    OPTIONAL, unlike the watermark tag: "" (the default) means OCR writes
    text regions only, which is what it always did.
    """
    from . import tagname

    raw = read_json(s, PREFS_GLOBAL).get("text_tag", "")
    return tagname.normalize(str(raw or "").strip().lower())


# ---- faces ------------------------------------------------------------------


def read_face_match_threshold(s: Session) -> float:
    """How alike two faces must be before a detection is named by itself.

    Global for the same reason the tag prefix is: it decides what lands in the
    shared catalog. Out-of-range values fall back to the built-in default
    rather than being clamped silently to something nobody asked for — a 0
    here would name every face after the first person in the library.
    """
    # Imported lazily: `faces` pulls in numpy and is the heavier module, and
    # this keeps `prefs` importable from anywhere without dragging it along.
    from . import faces as facelib

    raw = read_json(s, PREFS_GLOBAL).get("face_match_threshold")
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return facelib.MATCH_DEFAULT
    return value if 0.3 <= value <= 0.99 else facelib.MATCH_DEFAULT

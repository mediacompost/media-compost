"""What the Python API raises.

Every one of these subclasses a builtin where the builtin says the same thing,
so ordinary Python handling works: a missing key is a `KeyError`, a bad value
is a `ValueError`. That follows `json.JSONDecodeError(ValueError)` and
`io.UnsupportedOperation(OSError, ValueError)` rather than inventing a
parallel world.
"""

from __future__ import annotations

from ..db import LibraryVersionError as _LibraryVersionError
from ..ops.errors import Conflict, Invalid, NotFound as _OpNotFound, OpError, Refused


class MediaCompostError(Exception):
    """Base class for everything this API raises."""


class LibraryError(MediaCompostError):
    """Something about the library as a whole."""


class LibraryVersionError(LibraryError, _LibraryVersionError):
    """The library on disk was written by a different build (see
    `db.SCHEMA_VERSION`). Refused rather than opened, because a library this
    build cannot read must be left exactly as it was found."""


class ReadOnlyError(LibraryError):
    """A write on a library opened with ``mode="r"``."""


class NotFound(MediaCompostError, KeyError):
    """No such row.

    Subclasses `KeyError` so a Mapping behaves as one — but with a readable
    `str()`, because `KeyError`'s repr-of-the-argument turns a sentence into
    a quoted mess.
    """

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.args[0] if self.args else ""


class ObjectDeleted(NotFound):
    """The row behind this handle is gone.

    Raised on the next read AND on any write, never silently tolerated: an
    exporter that keeps writing files for an item somebody deleted mid-run is
    a bug you find in the output rather than the traceback.
    """


class AmbiguousName(MediaCompostError, LookupError):
    """Several rows answer to that name, and this lookup wants one."""


class ValidationError(MediaCompostError, ValueError):
    """The input is malformed."""


class InvalidTagName(ValidationError):
    """A name `tagname.normalize` would change.

    Refused rather than quietly fixed: silently storing something else is how
    a caller ends up with a tag it cannot find again. Whitespace is what a
    name may not hold — a space outright, any other kind naming the form that
    WOULD be accepted. A colon is an ordinary character at either end
    (`d:` and `:d` are two tags), and `media_compost.normalize_tag` is
    exported for normalizing deliberately.
    """


class InvalidDate(ValidationError):
    """Not a partial date this library can store."""


class ConflictError(MediaCompostError):
    """It would collide with something that already exists."""


class DuplicateName(ConflictError):
    """That name is taken. For tags, `merge()` is the other answer."""


class GroupCycleError(ConflictError):
    """A group cannot be moved under its own subtree."""


class InvalidLink(ConflictError):
    """A self-link, a duplicate, or one that would close a cycle."""


class ImportFailed(MediaCompostError):
    """An import could not read or store a source.

    NOT called `ImportError` — that name is a builtin, and shadowing it in a
    package people do `from media_compost import *` on would be unkind.
    """


class UnsupportedOperation(MediaCompostError, ValueError):
    """The object does not do that — `frames()` on a still, say."""


class MediaUnreadable(MediaCompostError, OSError):
    """ffmpeg could not read these bytes.

    Its own class because a caller walking a whole library has to be able to
    skip one broken film without catching everything: one unreadable file is
    a line in a log, not the end of a run. `Item.frames()` translates the
    core media error into this, so nothing outside the package has to know
    that error exists.
    """


#: How an `ops.OpError` becomes one of the above. The ops layer speaks in HTTP
#: statuses because the routers need them; a script wants Python exceptions,
#: and the `code` is what carries the meaning across.
_BY_CODE = {
    "tag_name_spaces": InvalidTagName,
    "tag_name_shape": InvalidTagName,
    "tag_exists": DuplicateName,
    "group_cycle": GroupCycleError,
    "link_cycle": InvalidLink,
    "invalid_date": InvalidDate,
}


def translate(exc: OpError) -> MediaCompostError:
    """Re-raise an ops refusal in the API's own tag set."""
    cls = _BY_CODE.get(exc.code)
    if cls is None:
        if isinstance(exc, _OpNotFound):
            cls = NotFound
        elif isinstance(exc, Conflict):
            cls = ConflictError
        elif isinstance(exc, Invalid):
            cls = ValidationError
        else:  # Refused, and any future sibling
            cls = ConflictError if isinstance(exc, Refused) else MediaCompostError
    out = cls(exc.message)
    out.code = exc.code  # type: ignore[attr-defined]
    return out

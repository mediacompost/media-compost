"""What an operation raises when it refuses.

The routers used to raise ``HTTPException`` directly from inside the logic, so
the logic could only ever be called over HTTP. These are the same refusals with
the HTTP knowledge lifted out: an op raises one of these, ``server/app.py``
turns it back into the identical status code and ``{"detail": …}`` body, and a
script catches it as an ordinary Python exception.

``status`` is the HTTP code the web layer answers with, and it is the ONLY
HTTP-shaped thing in this package — it lives here rather than in a mapping
table in the server so that adding a subclass cannot forget it. The mapping
from today's calls is mechanical:

    HTTPException(400, …) -> Invalid  or  Refused
    HTTPException(404, …) -> NotFound
    HTTPException(409, …) -> Conflict

``Invalid`` and ``Refused`` share a status on purpose. The split is not for the
web layer, which cannot tell them apart and does not need to; it is for a
SCRIPT, where "you passed something malformed" and "the library will not do
that" are different bugs and cost nothing to distinguish.

``code`` is a stable machine-readable slug (``"tag_not_found"``). Message text
is for people and may be reworded; ``code`` is what a caller branches on.
"""

from __future__ import annotations

from typing import Mapping, Optional

from ..fillvars import fillvars


class OpError(Exception):
    """Base class for every refusal an operation can make.

    The first argument is a TEMPLATE — a fixed English sentence with
    ``{placeholders}`` — and ``vars`` fills them. For the ~110 static
    messages the two are the same string and nothing changes; an
    interpolating site passes the values separately so the UI can look the
    TEMPLATE up in its translation catalog and fill the same slots in
    another language (``key``/``vars`` travel beside the interpolated
    ``detail`` string in the HTTP body — see ``server/app.py``). ``message``
    stays the filled English sentence, byte-identical to what the f-strings
    produced, which is what keeps every test that pins one green.
    """

    #: HTTP status the web layer answers with. Subclasses override.
    status = 400

    def __init__(self, template: str,
                 vars: Optional[Mapping[str, object]] = None, *,
                 code: str = "", detail: Optional[dict] = None):
        message = fillvars(template, vars)
        super().__init__(message)
        self.message = message
        #: The unfilled template — what a translation catalog is keyed by.
        self.key = template
        #: The slot values, for re-filling after a lookup.
        self.vars = dict(vars) if vars else {}
        self.code = code
        #: Structured extras for a caller that wants more than the sentence.
        #: Never reaches the HTTP body — the wire shape is `{"detail": message}`
        #: exactly as `HTTPException` produced it, so no client changes.
        self.detail = detail or {}

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


class Invalid(OpError):
    """The input is malformed — a name with a space, a box outside 0..1, an
    operator that does not exist."""

    status = 400


class Refused(OpError):
    """The input is well formed and the library will not do it anyway — alias a
    tag to itself, merge an item into itself, drop a group into its own
    descendant."""

    status = 400


class NotFound(OpError):
    """A named row does not exist."""

    status = 404


class Conflict(OpError):
    """It would collide with something that already exists — a taken tag name,
    a tag another subject already claims."""

    status = 409

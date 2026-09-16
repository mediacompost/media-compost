"""The value types the API hands back and takes in.

Small, immutable, and none of them a database row. `PartialDate` is the one
that carries real weight: this library's dates know how much of themselves is
known, and a `datetime` cannot say "1975, month unknown".
"""

from __future__ import annotations

from datetime import date as _date, datetime
from typing import NamedTuple, Optional, Union

from .. import partialdate as _pd
from ..db import TAKEN_NONE


class _Never:
    """The sentinel for "somebody looked, and there is no date".

    `item.taken` has THREE states and Python has one `None`: nobody has said
    (fall back to EXIF, then to the events the picture carries), somebody
    typed one, and somebody established there is none — a scanned print
    carrying the scanner's date, a drawing, a screenshot of a screenshot.
    Without the third, a wrong date could be replaced but never removed.

    A module-level sentinel in the tradition of `dataclasses.MISSING`.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "NEVER"

    def __bool__(self) -> bool:
        return False


#: See :class:`_Never`.
NEVER = _Never()


class Rect(NamedTuple):
    """A rectangle in the item's reference frame, as fractions of it."""

    x: float
    y: float
    w: float
    h: float


class TimeRange(NamedTuple):
    """A stretch of a film, in seconds."""

    start: float
    end: Optional[float] = None


class GroupedTags(NamedTuple):
    """One per-item tag group, flattened — what `ItemSet.tag_groups()` hands
    back for a whole result at once.

    A frozen record rather than an `ItemTagGroup` handle, because the point of
    the bulk read is that nothing here costs another query: `tags` is already
    the positive names in placement order, `subjects` already the display
    names. `item.tag_groups` is the live, editable view of the same thing.
    """

    id: int
    name: str
    system: bool
    tags: tuple
    meta_tags: tuple
    subjects: tuple


class Phash:
    """A picture's perceptual hash — the one thing this library compares when
    it asks whether two pictures are the same one.

    `File.phash` is the stored form of this (a hex string, and it stays a
    string: scripts read it and the golden pins it). `Phash.of(image)` is how
    a consumer gets one for pixels that are NOT in the library — a video
    frame it just decoded, a derived copy it just made — so that its idea of
    "the same picture" is the importer's idea rather than a second one. Pair
    it with `Library.phash_threshold` and the two agree by construction.
    """

    __slots__ = ("_value",)

    def __init__(self, value: int):
        self._value = int(value)

    @classmethod
    def of(cls, image) -> "Phash":
        """The hash of a PIL image."""
        from .. import dedup

        return cls(dedup.phash_to_int(dedup.compute_phash_image(image)))

    @classmethod
    def parse(cls, hexstr: str) -> "Phash":
        """The hash `File.phash` stored."""
        from .. import dedup

        return cls(dedup.phash_to_int(hexstr))

    def distance(self, other: "Phash") -> int:
        """How many bits apart — the Hamming distance."""
        return int(self._value ^ int(other)).bit_count()

    def near(self, other: "Phash", threshold: int) -> bool:
        """Whether these are the same picture, at that tolerance."""
        return self.distance(other) <= threshold

    def __int__(self) -> int:
        return self._value

    def __str__(self) -> str:
        return f"{self._value:x}"

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"Phash({self})"

    def __eq__(self, other) -> bool:
        if isinstance(other, Phash):
            return self._value == other._value
        if isinstance(other, int):
            return self._value == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._value)


class PartialDate:
    """A date that knows how much of itself is known.

    Stored as the sortable integer this library uses — `YYYYMMDD` for a
    subject's or an event's date, `YYYYMMDDHHMMSS` for a capture time — with
    **zeros for whatever is unknown**. The zeros ARE the precision: `19750000`
    is the year 1975 and nothing narrower, and a range query over it stays an
    integer comparison.
    """

    __slots__ = ("_value",)

    def __init__(self, value: int):
        self._value = int(value)

    # -- construction --------------------------------------------------------

    @classmethod
    def parse(cls, text: str) -> "PartialDate":
        """From "2019", "2019-04", "2019-04-08" or "14 March 1879"."""
        got = _pd.parse_en(text) if not text[:1].isdigit() else None
        if got is None:
            digits = "".join(c for c in text if c.isdigit())
            if len(digits) not in (4, 6, 8, 12, 14):
                raise ValueError(f"not a partial date: {text!r}")
            got = int(digits.ljust(8, "0")) if len(digits) <= 8 else int(digits)
        return cls(got)

    @classmethod
    def of(cls, when: Union[datetime, _date]) -> "PartialDate":
        if isinstance(when, datetime):
            return cls(int(when.strftime("%Y%m%d%H%M%S")))
        return cls(int(when.strftime("%Y%m%d")))

    @classmethod
    def coerce(cls, value) -> Optional["PartialDate"]:
        """Whatever a caller passed, as a PartialDate (or None)."""
        if value is None or value is NEVER:
            return None
        if isinstance(value, PartialDate):
            return value
        if isinstance(value, (datetime, _date)):
            return cls.of(value)
        if isinstance(value, int):
            return cls(value)
        if isinstance(value, str):
            return cls.parse(value)
        raise TypeError(f"cannot read {value!r} as a date")

    # -- reading -------------------------------------------------------------

    def _digits(self) -> str:
        text = str(self._value)
        return text.rjust(14, "0") if len(text) > 8 else text.rjust(8, "0")

    def _part(self, start: int, end: int) -> Optional[int]:
        chunk = self._digits()[start:end]
        return int(chunk) if chunk and int(chunk) else None

    @property
    def year(self) -> Optional[int]:
        return self._part(0, 4)

    @property
    def month(self) -> Optional[int]:
        return self._part(4, 6)

    @property
    def day(self) -> Optional[int]:
        return self._part(6, 8)

    @property
    def hour(self) -> Optional[int]:
        return self._part(8, 10) if len(self._digits()) > 8 else None

    @property
    def minute(self) -> Optional[int]:
        return self._part(10, 12) if len(self._digits()) > 8 else None

    @property
    def second(self) -> Optional[int]:
        return self._part(12, 14) if len(self._digits()) > 8 else None

    @property
    def precision(self) -> str:
        """How much is known: year | month | day | hour | minute | second."""
        for name in ("second", "minute", "hour", "day", "month"):
            if getattr(self, name) is not None:
                return name
        return "year"

    def range(self) -> tuple[int, int]:
        """The window this value covers, as (lo, hi) in its own encoding —
        what an overlap search compares."""
        return _pd.bounds(self._value)

    # -- protocol ------------------------------------------------------------

    def __int__(self) -> int:
        return self._value

    def __str__(self) -> str:
        parts = [f"{self.year:04d}"] if self.year else ["????"]
        if self.month:
            parts.append(f"{self.month:02d}")
        if self.day:
            parts.append(f"{self.day:02d}")
        text = "-".join(parts)
        if self.hour is not None:
            text += f" {self.hour:02d}:{self.minute or 0:02d}"
        return text

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"PartialDate({self._value})"

    def __eq__(self, other) -> bool:
        if isinstance(other, PartialDate):
            return self._value == other._value
        if isinstance(other, int):
            return self._value == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._value)

    def __lt__(self, other) -> bool:
        return self._value < int(other)


def taken_to_stored(value) -> Optional[int]:
    """What `item.taken = …` writes: None to fall back, -1 for NEVER, else the
    sortable integer. The ops layer widens a date-width value to the column's
    own ``YYYYMMDDHHMMSS`` (`db.normalize_taken`), so a `PartialDate` of
    either width stores the same date."""
    if value is NEVER:
        return TAKEN_NONE
    got = PartialDate.coerce(value)
    return None if got is None else int(got)


def stored_to_taken(value: int) -> PartialDate:
    """A stored 14-digit capture date, as the `PartialDate` a reader expects.

    A capture date that carries no time IS a date, so it comes back at date
    width — which is what makes ``item.taken == PartialDate.parse("2019-04")``
    hold after the round trip, and what hands `partialdate.bounds` (which
    reads the 8-digit encoding) a value it can answer for. One with a real
    time keeps its full width; midnight and "no time" are the same value,
    the price the encoding's own docstring already names.
    """
    v = int(value)
    if v >= 10_000_000_000 and v % 1_000_000 == 0:
        return PartialDate(v // 1_000_000)
    return PartialDate(v)

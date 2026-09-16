"""Dates that know how much of themselves is known.

"Born 1879", "built July 1999", "taken 14 March 1879" are all dates, and a
subject's timeline needs whichever of the three the user actually has. They are
stored as the sortable number **YYYYMMDD with zeros for the unknown parts** —
``19750000`` is the year 1975, ``19990700`` is July 1999, ``18790314`` is one
day — so the encoding carries its own precision (the zeros ARE the precision,
there is no second column to keep in step) and a range query stays a plain
integer comparison.

Deliberately tiny and pure: the frontend mirrors it in ``src/subjects/when.ts``
for the same reason ``query.num_tolerance`` is mirrored in ``tree.ts``.
"""

from __future__ import annotations

from typing import Optional


def encode(year: int, month: int = 0, day: int = 0) -> int:
    return year * 10000 + month * 100 + day


def decode(value: int) -> tuple[int, int, int]:
    return value // 10000, (value // 100) % 100, value % 100


def is_valid(value: Optional[int]) -> bool:
    """A year in a plausible range, and a month/day that exist — with a day
    only meaningful when a month is known."""
    if value is None:
        return False
    year, month, day = decode(value)
    if not 1 <= year <= 9999 or not 0 <= month <= 12 or not 0 <= day <= 31:
        return False
    return not (day and not month)


def bounds(value: int) -> tuple[int, int]:
    """The [first, last] the partial date covers, for range comparisons.

    ``1975`` covers the whole year, ``July 1999`` the whole month — the same
    rule the metadata search already applies to capture dates, so searching a
    year means the year.
    """
    year, month, day = decode(value)
    if month == 0:
        return encode(year, 1, 1), encode(year, 12, 31)
    if day == 0:
        return encode(year, month, 1), encode(year, month, 31)
    return value, value


def age_at(since: Optional[int], when: Optional[int]) -> Optional[int]:
    """Whole years between two partial dates, or None when either is missing.

    Unknown months and days are read as "the start of what is known", which is
    the only reading that cannot overstate an age: a subject that exists since
    1975 is 0 during 1975, not 1.
    """
    if not since or not when:
        return None
    sy, sm, sd = decode(since)
    wy, wm, wd = decode(when)
    years = wy - sy
    # Subtract a year when the anniversary has not been reached yet. Comparing
    # the (month, day) pairs with zeros in them does the right thing: an unknown
    # month sorts before any known one, so the anniversary is assumed passed.
    if (wm, wd) < (sm, sd):
        years -= 1
    return years if years >= 0 else None


def date_from_age(since: Optional[int], age: Optional[int]) -> Optional[int]:
    """The year a subject reached ``age``, given when it came to be.

    Year precision only — an age says nothing about the month.
    """
    if not since or age is None or age < 0:
        return None
    year, _, _ = decode(since)
    return encode(year + age)


def format_en(value: Optional[int]) -> str:
    """Human-readable, for logs and event summaries (the UI formats its own,
    localized, in ``when.ts``)."""
    if not value:
        return ""
    year, month, day = decode(value)
    if month == 0:
        return str(year)
    name = ("January", "February", "March", "April", "May", "June", "July",
            "August", "September", "October", "November", "December")[month - 1]
    return f"{name} {year}" if day == 0 else f"{day} {name} {year}"

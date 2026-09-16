"""The modification log, and the way back from a mistake.

The single most valuable thing a scripting API can offer: a script that
mis-tagged ten thousand items needs `lib.history[:5].revert()` more than it
needs anything else here.

The log row is called `Change` rather than `Event`, because `Event` in this
API is the thing that HAPPENED at a place on a date. The ORM has the same
collision and resolves it the other way (`Occasion` for the happening); this
is the side of it a script sees, so it takes the word people use.
"""

from __future__ import annotations

from typing import Iterator, Optional

from sqlalchemy import select

from .. import history as _history
from ..db import Event as _EventRow
from ._base import Handle
from .errors import ReadOnlyError


class Change(Handle):
    """One entry in the log."""

    _model = _EventRow
    _what = "change"

    @property
    def created_at(self):
        return self._r.created_at

    @property
    def action(self) -> str:
        return self._r.action

    @property
    def source(self) -> str:
        """web | cli | ai — where the change came from."""
        return self._r.source

    @property
    def username(self) -> str:
        return self._r.username or ""

    @property
    def summary(self) -> str:
        return self._r.summary or ""

    @property
    def data(self) -> dict:
        return _history.load_data(self._r)

    @property
    def reverted(self) -> bool:
        return self._r.reverted_at is not None

    @property
    def revertible(self) -> bool:
        return _history.can_revert(self._lib._session, self._r)

    def revert(self) -> bool:
        """Undo this change. Returns whether anything was undone.

        The reversal is ITSELF logged and itself revertible, which is how redo
        works: reverting a revert replays the original.
        """
        if self._lib.readonly:
            raise ReadOnlyError('this library was opened with mode="r"')
        out = _history.revert_event(self._lib._session, self._r,
                                    source=self._lib.source,
                                    store=self._lib._store)
        if self._lib._depth == 0:
            self._lib.commit()
        return out is not None

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<Change {self.action} {self.summary!r}>"


class History:
    """`lib.history` — newest first."""

    __slots__ = ("_lib",)

    def __init__(self, lib):
        self._lib = lib

    def _rows(self, limit: Optional[int] = None, offset: int = 0) -> list:
        stmt = (select(_EventRow).order_by(_EventRow.id.desc())
                .offset(offset))
        if limit is not None:
            stmt = stmt.limit(limit)
        return [Change(self._lib, r.id, r)
                for r in self._lib._session.execute(stmt).scalars().all()]

    def __iter__(self) -> Iterator[Change]:
        return iter(self._rows())

    def __len__(self) -> int:
        from sqlalchemy import func

        return int(self._lib._session.execute(
            select(func.count(_EventRow.id))).scalar_one())

    def __getitem__(self, key):
        if isinstance(key, slice):
            start = key.start or 0
            stop = key.stop
            return self._rows(None if stop is None else stop - start, start)
        rows = self._rows(1, key)
        if not rows:
            raise IndexError(key)
        return rows[0]

    def since(self, change_id: int, limit: int | None = None) -> list[Change]:
        """Everything logged after ``change_id`` — the watermark pattern the
        UI's Undo bar uses: note the newest id, do the thing, ask what
        happened.

        Unbounded by default, deliberately: the point of the watermark is
        ``revert(since(mark))``, and a cap would silently undo only the newest
        slice of a big run. Pass ``limit`` to page instead.
        """
        stmt = (select(_EventRow).where(_EventRow.id > change_id)
                .order_by(_EventRow.id.desc()))
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = self._lib._session.execute(stmt).scalars().all()
        return [Change(self._lib, r.id, r) for r in rows]

    def revert(self, changes) -> int:
        """Undo several, newest first — which is the order that works, since a
        later change may depend on an earlier one."""
        if isinstance(changes, Change):
            changes = [changes]
        done = 0
        for change in sorted(changes, key=lambda c: c.id, reverse=True):
            if change.revert():
                done += 1
        return done

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<History {len(self)} changes>"

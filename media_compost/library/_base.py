"""What every handle shares.

A handle is a thin thing: the library it belongs to and a primary key. It reads
its row lazily and re-reads it after a commit, so an object held across a
`transaction()` boundary is never stale — and a row that has since been deleted
raises rather than answering with whatever it last saw.
"""

from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar

from .errors import ObjectDeleted

T = TypeVar("T")


class Handle(Generic[T]):
    """A live reference to one row."""

    #: The ORM class. Subclasses set it.
    _model: Any = None
    #: What to call it when it is gone.
    _what = "row"

    __slots__ = ("_lib", "_id", "_row", "_gen")

    def __init__(self, lib, row_id: int, row: Optional[T] = None):
        self._lib = lib
        self._id = int(row_id)
        self._row = row
        self._gen = lib._generation

    # -- the row -------------------------------------------------------------

    @property
    def _r(self) -> T:
        """The row, re-read if the library has committed since it was loaded.

        `expire_on_commit=False` on the sessionmaker is what makes holding one
        across a commit safe at all; the generation counter is what makes it
        CURRENT rather than merely usable.
        """
        if self._row is None or self._gen != self._lib._generation:
            self._row = self._lib._session.get(self._model, self._id)
            self._gen = self._lib._generation
        if self._row is None:
            raise ObjectDeleted(f"this {self._what} has been deleted")
        return self._row

    def refresh(self) -> None:
        """Drop the cached row; the next read goes to the database."""
        self._row = None
        self._lib._session.expire_all()

    @property
    def exists(self) -> bool:
        """Whether the row is still there — the non-raising probe."""
        return bool(self)

    def __bool__(self) -> bool:
        try:
            self._r
        except ObjectDeleted:
            return False
        return True

    # -- identity ------------------------------------------------------------
    #
    # By (class, primary key), NOT by the cached row: two handles reached by
    # different routes are the same thing, and an item has to work as a dict
    # key and a set member for any grouping a script does.

    @property
    def id(self) -> int:
        return self._id

    def __eq__(self, other) -> bool:
        if isinstance(other, Handle):
            return type(self) is type(other) and self._id == other._id
        return NotImplemented

    def __hash__(self) -> int:
        return hash((type(self).__name__, self._id))

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<{type(self).__name__} {self._id}>"

    # -- writing -------------------------------------------------------------

    def _write(self, fn, *args, **kw):
        """Run one op inside the library's transaction discipline.

        The row is probed first, so a write through a deleted handle raises
        `ObjectDeleted` — the promise the class docstring makes — rather than
        the ops layer's plain `NotFound` for a row that never existed.
        """
        self._r
        return self._lib._do(fn, *args, **kw)

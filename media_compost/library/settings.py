"""The settings that shape the LIBRARY, not one person's view of it.

The tag prefixes decide what the app invents when it mints a tag for a subject,
a place or an event, and the face threshold decides what lands in the shared
catalog — so both are global, and a script that creates subjects has to be able
to read them. Language, date format and the double-click actions are per-user
preferences and are deliberately absent.
"""

from __future__ import annotations

import json

from .. import prefs
from ..db import set_setting
from .errors import ReadOnlyError


class Settings:
    """`lib.settings`."""

    __slots__ = ("_lib",)

    def __init__(self, lib):
        self._lib = lib

    def _write(self, key: str, value) -> None:
        if self._lib.readonly:
            raise ReadOnlyError('this library was opened with mode="r"')
        s = self._lib._session
        blob = prefs.read_json(s, prefs.PREFS_GLOBAL)
        blob[key] = value
        set_setting(s, prefs.PREFS_GLOBAL, json.dumps(blob))
        if self._lib._depth == 0:
            self._lib.commit()

    @property
    def subject_tag_prefix(self) -> str:
        return prefs.read_tag_prefix(self._lib._session, "subject")

    @subject_tag_prefix.setter
    def subject_tag_prefix(self, value: str) -> None:
        self._write("subject_tag_prefix", value)

    @property
    def place_tag_prefix(self) -> str:
        return prefs.read_tag_prefix(self._lib._session, "place")

    @place_tag_prefix.setter
    def place_tag_prefix(self, value: str) -> None:
        self._write("place_tag_prefix", value)

    @property
    def event_tag_prefix(self) -> str:
        return prefs.read_tag_prefix(self._lib._session, "event")

    @event_tag_prefix.setter
    def event_tag_prefix(self, value: str) -> None:
        self._write("event_tag_prefix", value)

    @property
    def face_match_threshold(self) -> float:
        """How alike two faces must be before a detection names itself."""
        return prefs.read_face_match_threshold(self._lib._session)

    @face_match_threshold.setter
    def face_match_threshold(self, value: float) -> None:
        self._write("face_match_threshold", float(value))

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (f"<Settings subject={self.subject_tag_prefix!r} "
                f"place={self.place_tag_prefix!r} "
                f"event={self.event_tag_prefix!r} "
                f"faces={self.face_match_threshold}>")

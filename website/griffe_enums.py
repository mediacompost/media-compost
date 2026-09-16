"""Badge Enum subclasses as `enum` in the API reference.

mkdocstrings already badges a dataclass with a `dataclass` label; an enum
got nothing but its "Bases: StrEnum" line, so `ImportStatus` read as an
ordinary class with six attributes. This griffe extension adds the label
`enum` to any class whose direct bases name an enum type, and the theme's
existing label rendering does the rest — every enum in the API, present and
future, with nothing to declare per class.

Wired in `mkdocs.yml` under the mkdocstrings handler's `extensions`.
"""

from __future__ import annotations

import griffe

_ENUM_BASES = {
    "Enum", "StrEnum", "IntEnum", "Flag", "IntFlag",
    "enum.Enum", "enum.StrEnum", "enum.IntEnum", "enum.Flag", "enum.IntFlag",
}


class EnumLabel(griffe.Extension):
    def on_class_instance(self, *, node, cls, **kwargs) -> None:  # noqa: ARG002
        if any(str(base) in _ENUM_BASES for base in cls.bases):
            cls.labels.add("enum")

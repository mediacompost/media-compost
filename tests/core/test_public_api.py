"""The Python API's public surface, so a break is deliberate rather than noticed.

``media_compost.library`` is published in ``docs/python-api.md`` and people
write scripts against it. Unlike the on-disk formats it is not a hard promise
— a script can be edited, a library cannot be un-broken — so there is no
deprecation machinery here and none is wanted. What there is, is a record: a
change to any name or signature below fails this test, and passing it again
means regenerating the golden on purpose.

Regenerate with ``MEDIA_COMPOST_UPDATE_GOLDEN=1``, and say in the commit what
a script written against the old shape has to do now.
"""

from __future__ import annotations

import inspect
import json
import os
from pathlib import Path

import pytest

import media_compost.library as lib

GOLDEN = Path(__file__).resolve().parent / "golden" / "public_api.json"
UPDATE = bool(os.environ.get("MEDIA_COMPOST_UPDATE_GOLDEN"))


def _signature(fn) -> str:
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):  # pragma: no cover - builtins
        return "(?)"
    # Annotations are dropped: they are a type-checker's business and get
    # rewritten wholesale (`Optional[int]` to `int | None`) without anything
    # about the call changing.
    return str(sig.replace(
        parameters=[p.replace(annotation=inspect.Parameter.empty)
                    for p in sig.parameters.values()],
        return_annotation=inspect.Signature.empty))


def _defines(cls: type, attr: str) -> str:
    """The module of the class in `cls`'s MRO that actually defines `attr`."""
    for klass in cls.__mro__:
        if attr in vars(klass):
            return getattr(klass, "__module__", "") or ""
    return ""


def _surface() -> dict[str, object]:
    out: dict[str, object] = {"__all__": sorted(lib.__all__)}
    for name in sorted(lib.__all__):
        obj = getattr(lib, name)
        if inspect.isclass(obj):
            members = {}
            for attr in dir(obj):
                if attr.startswith("_"):
                    continue
                # Only what WE define. `dir()` also reports what a base class
                # brings, and for the error types that base is BaseException —
                # so `add_note`, `args` and `with_traceback` were in here,
                # describing CPython rather than this API. They are also the
                # one part of it that MOVES: 3.12 exposes no signature for
                # `add_note` (recorded as "(?)") where 3.13 gives
                # `(self, object, /)`, so the golden failed on the Python
                # version rather than on anything a script could notice.
                if not _defines(obj, attr).startswith("media_compost"):
                    continue
                value = inspect.getattr_static(obj, attr, None)
                if isinstance(value, property):
                    members[attr] = "property"
                elif callable(value):
                    members[attr] = _signature(value)
                else:
                    members[attr] = type(value).__name__
            out[name] = members
        elif callable(obj):
            out[name] = _signature(obj)
    return out


def test_the_public_python_api_is_what_it_was():
    got = _surface()
    if UPDATE:
        GOLDEN.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n",
                          encoding="utf-8")
        pytest.skip("golden regenerated")

    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    gone = sorted(set(golden["__all__"]) - set(got["__all__"]))
    assert not gone, f"these names left `library.__all__`: {gone}"

    for name in golden["__all__"]:
        want, have = golden.get(name), got.get(name)
        if not isinstance(want, dict):
            assert want == have, f"{name}: the signature changed"
            continue
        for attr, sig in want.items():
            assert attr in have, f"{name}.{attr} is gone"
            assert have[attr] == sig, (
                f"{name}.{attr} was `{sig}` and is now `{have[attr]}`. A "
                f"script written against it breaks. If that is intended, "
                f"regenerate with MEDIA_COMPOST_UPDATE_GOLDEN=1 and say so in "
                f"the commit; `docs/python-api.md` probably needs the same "
                f"edit.")


def test_the_golden_covers_the_documented_entry_point():
    """Not vacuous — the surface really is the one the docs describe."""
    got = _surface()
    assert "open_library" in got["__all__"]
    assert "data_dir" in str(got["open_library"])
    for expected in ("Library", "Item", "Tag", "LibraryVersionError"):
        assert expected in got["__all__"], expected

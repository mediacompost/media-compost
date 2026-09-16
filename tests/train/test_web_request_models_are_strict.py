"""Every training request body refuses unknown fields.

The trainer's `web/schemas.py` declares its own `RequestModel` rather than
borrowing the app's, because after the UI is carved out that would be another
package's. Two base classes is a real risk, and this is what makes it safe: the
rule is enforced here rather than remembered there.

The rule was learned expensively. Pydantic IGNORES an unrecognized key by
default, so a caller spelling a body field wrong gets the field's default and a
200 — the request succeeds, meaning something else. On a search body that was
total and silent: a caller who wrote `conditions` instead of `query` got NO
filter, so a request meaning "the portraits" answered with the whole library.

A RATCHET, because the failure it guards is invisible by construction.
"""

from __future__ import annotations

import inspect

import pytest
from fastapi.routing import APIRoute
from pydantic import BaseModel

from media_compost.train.web import routes


def _body_models() -> list[tuple[str, str, type]]:
    """(method+path, model name, model) for every route taking a body.

    Through FastAPI's own resolved `body_field` rather than the signature:
    `routes.py` uses `from __future__ import annotations`, so every annotation
    there is a STRING and an `isinstance` check over them silently finds
    nothing — a test that passes by inspecting an empty list.
    """
    out = []
    for route in routes.router.routes:
        if not isinstance(route, APIRoute) or route.body_field is None:
            continue
        model = getattr(route.body_field.field_info, "annotation", None)
        if not (inspect.isclass(model) and issubclass(model, BaseModel)):
            continue
        # FastAPI SYNTHESIZES a model per multipart/Form endpoint. We neither
        # declare nor configure those, and an unknown form field is a
        # different question from an unknown JSON key.
        if model.__module__.startswith("fastapi"):
            continue
        out.append((f"{sorted(route.methods)[0]} {route.path}",
                    model.__name__, model))
    return out


def test_there_are_body_models_to_check():
    """A test that silently checks nothing is worse than no test — which is
    exactly what the signature-based version of this did."""
    assert len(_body_models()) >= 5


@pytest.mark.parametrize(
    "where,name,model", _body_models(),
    ids=[n for _w, n, _m in _body_models()])
def test_a_request_body_refuses_unknown_fields(where, name, model):
    assert model.model_config.get("extra") == "forbid", (
        f"{name} is the body of {where} but accepts unknown fields, so a "
        f"misspelled key would silently take its default. Inherit from "
        f"`web.schemas.RequestModel`.")

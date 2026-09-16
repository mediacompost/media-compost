"""Every request body refuses unknown fields.

Pydantic ignores an unrecognized key by default, and for a REQUEST BODY that is
the worst possible direction: the value lands nowhere, the field's default
applies, and the call succeeds while meaning something else. The case that
prompted this is `POST /api/items/query` — a caller spelling the condition tree
`conditions` instead of `query` got no filter at all, so a request meaning "the
portraits" answered with the whole library, 200 OK.

It is not hypothetical either way round: `tests/test_sidecar.py` posted `tags`
to `/api/tags/quick-assign`, which takes `positive`/`negative`. It assigned
nothing, and the test passed on a sidecar write the touch produced by itself.

So this walks the real routes and holds every body model to `extra="forbid"`.
A ratchet rather than a convention, because the failure it guards is silent by
construction — nobody notices the endpoint that forgot.

RESPONSE models are deliberately NOT covered: several are built from dicts that
carry more than the model publishes (`EvalRunOut` from a training job's own
JSON), and validating our own output is a different question.

AND THE TREE INSIDE THE BODY IS COVERED TOO, because a strict body handing its
contents to permissive models is the same silence one level down — see
`query.CondModel` for the two cases that were reproduced against a real
library.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel

from media_compost import query as q
from media_compost.ui.config import UiConfig
from media_compost.importer import Importer, ImportOptions
from media_compost.ui.server import deps
from media_compost.ui.server.app import app
from media_compost.ui.server.deps import Library, get_library

from media_compost.ui.server.routers import (
    artifacts, captions, editor, events, faces, files, groups, history,
    imports, items, metadata, ml, ocr, places, query, relationships,
    sequences, settings, stats, subjects, tags, video,
)

ROUTERS = [
    artifacts, captions, editor, events, faces, files, groups, history,
    imports, items, metadata, ml, ocr, places, query, relationships,
    sequences, settings, stats, subjects, tags, video,
]

# The trainer's routes are deliberately NOT appended here: they are another
# package's, may not be installed, and `tests/train/` holds them to the same
# rule with a walker of its own.


@pytest.fixture
def client(tmp_path: Path, images: Path):
    cfg = UiConfig(data_dir=tmp_path / "data")
    lib = Library(cfg)
    with lib.db.session() as s:
        Importer(s, lib.store, cfg).import_paths([images], ImportOptions())
    app.dependency_overrides[get_library] = lambda: lib
    deps.reset_library()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _body_models() -> list[tuple[str, str, type]]:
    """(method+path, model name, model) for every route taking a body."""
    out = []
    for module in ROUTERS:
        for route in module.router.routes:
            if not isinstance(route, APIRoute) or route.body_field is None:
                continue
            model = getattr(route.body_field.field_info, "annotation", None)
            if not (inspect.isclass(model) and issubclass(model, BaseModel)):
                continue
            # FastAPI SYNTHESIZES a model per multipart/Form endpoint
            # (`Body_upload_ref_api_ml_refs_post`). We do not declare those and
            # cannot configure them; an unknown form field is also a different
            # question from an unknown JSON key.
            if model.__module__.startswith("fastapi"):
                continue
            out.append((f"{sorted(route.methods)[0]} {route.path}",
                        model.__name__, model))
    return out


def test_there_are_body_routes_to_check():
    """If the introspection breaks, every assertion below passes vacuously."""
    assert len(_body_models()) >= 60


@pytest.mark.parametrize(
    "where,name,model", _body_models(),
    ids=[f"{n}" for _w, n, _m in _body_models()])
def test_a_request_body_refuses_unknown_fields(where, name, model):
    assert model.model_config.get("extra") == "forbid", (
        f"{name} is the body of {where} but accepts unknown fields, so a "
        f"misspelled key is silently dropped and its default applies.\n\n"
        f"Inherit from `schemas.RequestModel` instead of `BaseModel`."
    )


def test_the_query_endpoint_refuses_a_misspelled_filter(client):
    """The case that prompted the rule, end to end: it used to answer 200 with
    every item in the library."""
    got = client.post("/api/items/query", json={
        "conditions": {"type": "group", "op": "and", "neg": False,
                       "children": []},
    })
    assert got.status_code == 422
    assert "conditions" in got.text


def test_a_correct_query_still_works(client):
    got = client.post("/api/items/query", json={
        "query": {"type": "group", "op": "and", "neg": False, "children": []},
    })
    assert got.status_code == 200
    assert "items" in got.json()


# ---- the tree INSIDE the body ----------------------------------------------

#: Every node type a query tree can hold. Read off the union rather than
#: listed, so a condition kind added without a strict base fails here.
CONDITION_MODELS = [
    m for m in vars(q).values()
    if inspect.isclass(m) and issubclass(m, BaseModel)
    and m is not q.CondModel and issubclass(m, q.CondModel)
]


def test_there_are_condition_models_to_check():
    assert len(CONDITION_MODELS) >= 12


@pytest.mark.parametrize("model", CONDITION_MODELS,
                         ids=[m.__name__ for m in CONDITION_MODELS])
def test_a_condition_refuses_unknown_fields(model):
    assert model.model_config.get("extra") == "forbid", (
        f"{model.__name__} is part of a request body — the condition tree — "
        f"but accepts unknown fields, so a misspelled key is dropped and the "
        f"search silently answers a different question.\n\n"
        f"Inherit from `query.CondModel` instead of `BaseModel`."
    )


def test_a_MISSPELLED_GROUP_KEY_IS_REFUSED_RATHER_THAN_MATCHING_EVERYTHING(client):
    """`nodes` instead of `children`. It used to leave an EMPTY group, and an
    empty group matches everything — so a request meaning "the ones at this
    place" answered with the whole library, 200 OK."""
    whole = client.post("/api/items/query", json={"query": None}).json()["total"]
    assert whole > 0, "nothing imported, so this proves nothing"

    got = client.post("/api/items/query", json={
        "query": {"type": "group", "op": "and", "nodes": [
            {"type": "place", "op": "~", "value": "nowhere", "have": True}]},
    })
    assert got.status_code == 422
    assert "nodes" in got.text


def test_A_MISSPELLED_CONDITION_KEY_IS_REFUSED_RATHER_THAN_WIDENING(client):
    """`SubjectCond` has `name` and the date/age bounds — no `part`, `op` or
    `value`. All three used to be dropped and `name` fell back to "", which is
    how "has ANY subject at all" is spelled: a question about one person
    answered for everybody."""
    got = client.post("/api/items/query", json={
        "query": {"type": "group", "op": "and", "children": [
            {"type": "subject", "part": "tag", "op": "=", "value": "alice",
             "have": True}]},
    })
    assert got.status_code == 422
    assert "part" in got.text

    # The right spelling still works.
    ok = client.post("/api/items/query", json={
        "query": {"type": "group", "op": "and", "children": [
            {"type": "subject", "name": "alice", "have": True}]},
    })
    assert ok.status_code == 200


def test_THE_CORPUS_TREES_ALL_VALIDATE(client):
    """The mirrored grammar's own recording, through the endpoint: every tree
    `tree.ts` and `querystring.py` agree on has to remain postable, or
    strictness has broken the one client there is."""
    import json
    corpus = json.loads(
        (Path(__file__).resolve().parents[1] / "core" / "golden"
         / "query_corpus.json").read_text(encoding="utf-8"))
    for row in corpus["rows"]:
        got = client.post("/api/items/query",
                          json={"query": row["tree"], "page_size": 1})
        assert got.status_code == 200, f"{row['query']}: {got.text}"

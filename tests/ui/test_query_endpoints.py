"""`/api/query/parse` and `/api/query/serialize`.

Driven by the SAME golden corpus that binds `querystring.py` to `tree.ts`, so
the endpoints cannot answer differently from either parser: a row that the two
implementations agree on and the wire disagrees with would mean the HTTP layer
had introduced a third dialect.

They exist for the CLI and for clients in other languages. The query builder
deliberately does not call them — see the router's docstring.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from media_compost import querystring
from media_compost.ui.server.app import app

CORPUS = (pathlib.Path(__file__).resolve().parents[1]
          / "core" / "golden" / "query_corpus.json")


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def _rows() -> list[dict]:
    return json.loads(CORPUS.read_text(encoding="utf-8"))["rows"]


def test_parse_answers_what_the_corpus_says(client):
    for row in _rows():
        got = client.post("/api/query/parse", json={"q": row["query"]})
        assert got.status_code == 200, row["query"]
        body = got.json()
        assert body["canonical"] == row["canonical"], row["query"]
        # The tree is the wire format, so it must match key for key.
        assert _prune(body["tree"]) == _prune(row["tree"]), row["query"]


def test_serialize_answers_what_the_corpus_says(client):
    for row in _rows():
        got = client.post("/api/query/serialize", json={"tree": row["tree"]})
        assert got.status_code == 200, row["query"]
        assert got.json()["q"] == row["canonical"], row["query"]


def test_the_two_directions_are_inverses(client):
    for row in _rows():
        tree = client.post("/api/query/parse",
                           json={"q": row["query"]}).json()["tree"]
        back = client.post("/api/query/serialize",
                           json={"tree": tree}).json()["q"]
        assert back == row["canonical"], row["query"]


def test_an_empty_query_is_an_empty_group(client):
    got = client.post("/api/query/parse", json={"q": ""}).json()
    assert got["tree"]["children"] == []
    assert got["canonical"] == ""


def test_a_syntax_error_is_a_400_with_a_reason(client):
    got = client.post("/api/query/parse", json={"q": "(unclosed"})
    assert got.status_code == 400
    assert got.json()["detail"]


def test_the_endpoint_and_the_module_never_disagree(client):
    """The point of the endpoints: they are `querystring.py` on the wire, not
    a reimplementation of it."""
    for row in _rows():
        mine = querystring.parse(row["query"])
        wire = client.post("/api/query/parse",
                           json={"q": row["query"]}).json()["tree"]
        assert _prune(json.loads(mine.model_dump_json())) == _prune(wire)


def _prune(node):
    """Drop keys the models default in, so two dumps of one tree compare equal
    however each side chose to serialize its defaults."""
    if isinstance(node, dict):
        return {k: _prune(v) for k, v in sorted(node.items())
                if v is not None}
    if isinstance(node, list):
        return [_prune(v) for v in node]
    return node

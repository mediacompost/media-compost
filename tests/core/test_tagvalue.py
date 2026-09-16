"""`tagvalue.py` and `frontend/src/shared/tagvalue.ts` must agree.

Two implementations of one convention — the backend evaluates and compiles
VALUE: conditions, the frontend's builder row and serializer read the same
rules — and `golden/value_corpus.json` is the contract both suites assert
(this one and `frontend/src/shared/tagvalue.test.ts`). A unit added or a
family factor moved on one side fails the other side's suite.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from media_compost import tagvalue as tv

CORPUS = json.loads(
    (pathlib.Path(__file__).parent / "golden" / "value_corpus.json")
    .read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CORPUS["cases"],
                         ids=[c["basename"] or "<empty>"
                              for c in CORPUS["cases"]])
def test_parse_matches_the_corpus(case):
    got = tv.parse(case["basename"])
    if case["value"] is None:
        assert got is None
        return
    assert got is not None
    assert got.value == pytest.approx(case["value"])
    assert got.unit == case["unit"]
    sp, canon = tv.canon(got)
    assert sp == case["space"]
    assert canon == pytest.approx(case["canon"])


@pytest.mark.parametrize("m", CORPUS["matches"],
                         ids=[f"{m['basename']}{m['op']}{m['value']}{m['unit']}"
                              for m in CORPUS["matches"]])
def test_matches_the_corpus(m):
    assert tv.matches(m["basename"], m["op"], m["value"], m["unit"],
                      m["tol"]) is m["hit"]


def test_matching_names_reads_the_namespace_and_nothing_else():
    names = ["height:172cm", "height:1.72m", "height:2.10m", "height:tall",
             "width:172cm", "plain", "height:80kg"]
    got = tv.matching_names(names, "height", ">", 1.5, "m", 0.0)
    # The mass value shares the namespace and not the SPACE, so it stays out;
    # so does the same number under another namespace.
    assert got == {"height:172cm", "height:1.72m", "height:2.10m"}
    assert tv.matching_names(names, "height", ">", 2.0, "m", 0.0) \
        == {"height:2.10m"}

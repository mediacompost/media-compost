"""Converting between a query STRING and the condition tree.

`media_compost/querystring.py` mirrors `frontend/src/query/tree.ts`, and these
two endpoints expose it — for the CLI, for a client in another language, and as
a second checker of the shared golden corpus.

**The query builder does not call them.** `serialize()` runs on every
structural edit of a condition row and the text field has to follow the instant
a dropdown changes, so a round-trip there is visible lag on every click; the
parse direction is initialized synchronously (`useState(() => tryParse(…))`)
and its tree is the React Query cache key. The UI keeps `tree.ts`, and the
corpus is what keeps the two equal.

They are stateless: parsing touches no session, because a condition's type is
decided by the literal's own syntax rather than by the metadata catalog.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from media_compost import querystring
from media_compost.ops.errors import Invalid
from media_compost.query import Group
from ..schemas import RequestModel

router = APIRouter(prefix="/api/query", tags=["query"])


class ParseIn(RequestModel):
    q: str = ""


class ParseOut(BaseModel):
    tree: Group
    # What the string looks like once it has been round-tripped. Two spellings
    # of one query canonicalize to the same text, which is what makes it usable
    # as a cache key.
    canonical: str


class SerializeIn(RequestModel):
    tree: Group


class SerializeOut(BaseModel):
    q: str


@router.post("/parse", response_model=ParseOut)
def parse_query(body: ParseIn) -> ParseOut:
    try:
        tree = querystring.parse(body.q)
    except querystring.QueryStringError as exc:
        raise Invalid(str(exc), code="query_syntax") from exc
    return ParseOut(tree=tree, canonical=querystring.serialize(tree))


@router.post("/serialize", response_model=SerializeOut)
def serialize_query(body: SerializeIn) -> SerializeOut:
    return SerializeOut(q=querystring.serialize(body.tree))

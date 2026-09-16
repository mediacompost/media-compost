"""What "everything the grid is showing" means, resolved server-side.

With nothing selected, an action in the right sidebar is about the VIEW, and
a view can be the whole library. A million ids is not something a request
body can carry and enumerating them in the browser would mean paging the
library first — so the SCOPE travels (an `ItemSearchRequest`, the same words
`POST /api/items/query` takes) and this resolves it.

**There is ONE resolution and everything goes through it.** The rule the app
already learned about `QueryCtx` applies here in a second shape: a whole-view
write that resolved its own scope would be a second definition of what the
grid is showing, and the two would drift in exactly the flags nobody thinks
about (hidden items, sequence containers, the trash). So `view_ids` is the
only place a search request becomes a list of ids, and `chunks` is the only
place that list becomes transactions.
"""

from __future__ import annotations

from typing import Iterator

from sqlalchemy.orm import Session

from media_compost.ops import search
from media_compost.resolve import Resolver

from .deps import Library
from .schemas import ItemSearchRequest

#: One batch of a whole-view write. The transaction around a batch is the
#: endpoint's, and a write over the whole library is a long-held write lock
#: and a rollback nobody wanted if it is one transaction — the same bargain
#: `ops.artifacts.delete_kind` and the file prune both take.
VIEW_CHUNK = 500


def view_ids(s: Session, lib: Library, body: ItemSearchRequest) -> list[int]:
    """Every item id the view described by ``body`` is showing.

    ``page`` / ``page_size`` / ``sort`` ride along on the request and are
    ignored: an order does not change which items an action lands on, and a
    page is what the GRID needs rather than what the action is about.
    """
    res = Resolver(s)
    base = search.search_filtered(
        s, **search.scope_of(body), query=body.query, resolver=res)
    return (list(s.execute(base.ids_select()).scalars().all())
            if base.residue is None else base.matched_ids(s, res))


def chunks(ids: list[int]) -> Iterator[list[int]]:
    """``ids`` in committed-batch sized pieces. The caller commits between
    them — see `VIEW_CHUNK`."""
    for at in range(0, len(ids), VIEW_CHUNK):
        yield ids[at:at + VIEW_CHUNK]

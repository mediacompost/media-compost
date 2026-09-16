"""The library's service layer: every mutation, without the HTTP.

For most of this project's life the mutation logic lived inside FastAPI router
bodies — ``routers/tags.py:assign_item_tag`` *was* the implementation of
"tag an item", get-or-create and upsert and ``touch_items`` and ``log_event``
all inline. That made the logic reachable only over HTTP, and it made the
duplication that followed inevitable: ``history.py`` had to reimplement
trash/restore to revert them, ``routers/ml.py`` reached into
``routers/tags.py``'s private helpers to approve a pending tag, and
``jobs.py`` hand-rolled a fourth ``ItemTag`` insert.

This package is that logic, extracted. Its consumers — the routers, the
revert layer, the Python scripting API, the jobs worker and the app's own
``media_compost.ui.ops`` modules — all sit above it, and it knows about none
of them. (One hand-rolled ``ItemTag`` deliberately survives in ``jobs.py``:
a face guess assigns its subject's tag as a PLACEMENT-LESS pending row, the
shape ``_recompute_pending`` and the amber UI read as "a machine said this" —
see ``_pending_subject_tag`` there.)

## The shape

Every operation is::

    verb_noun(ctx: Ctx, <domain args>, *, <options>) -> <domain value>

``Ctx`` (see :mod:`.context`) carries the session, the acting user and the
History badge. Ops return domain values — a row, a count, a bool — never
HTTP-shaped dicts; ``{"ok": True}`` is the router's tag set and stays there.

## The four rules

1. **Ops never commit, never roll back, never close.** Whoever owns the
   session owns its cadence. Ops may ``flush()`` — several must, to hand out
   ids before returning.
2. **Ops raise** :class:`~media_compost.ops.errors.OpError`, never
   ``HTTPException``. ``server/app.py`` maps it back to the identical status
   and body.
3. **Bulk operations extract as bulk operations.** ``merge_tag`` pre-loads
   five maps to avoid being O(assignments²) and ``quick_assign`` chunk-loads
   the whole items×tags grid. Rewriting either as a loop over the single-item
   op is observably identical and a large silent regression that no
   correctness test catches — only ``pytest -m perf`` would.
4. **Never rename an action string.** See :mod:`.actions`.

## What does NOT live here

Reads and serialization. ``_item_out``, ``_tag_rows``, ``_page_response`` and
their kin stay in the routers: that is presentation, it is shaped by Pydantic
response models, and the scripting API wants none of it.
"""

from __future__ import annotations

from .context import Ctx, ctx_for
from .errors import Conflict, Invalid, NotFound, OpError, Refused

__all__ = ["Ctx", "ctx_for", "OpError", "Invalid", "Refused", "NotFound", "Conflict"]

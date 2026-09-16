"""The modification log itself — the one operation that acts on the history.

Everything else in ``ops/`` writes an event as a side effect of changing the
library. This changes the events, which makes it the odd one out and worth its
own module rather than a function tucked into a neighbour.

The log is otherwise APPEND-ONLY on purpose: per-item events are what a bulk
undo is made of, so their number is the feature and not waste. What justifies a way to empty it is that the log is also a RECORD OF
WHAT WAS DONE, kept forever, in a library somebody may want to hand to
somebody else — and until now the only way to be rid of it was to start a new
data directory.
"""

from __future__ import annotations

from sqlalchemy import delete, func, select

from ..db import Event
from . import actions
from .context import Ctx


def clear(ctx: Ctx) -> int:
    """Delete every entry in the modification log. Returns how many.

    **This is what makes the library un-undoable**, and the caller is expected
    to have said so: a revert reads the event it is undoing, so an empty log
    is a library where nothing that has already happened can be taken back.
    Nothing else is touched — the items, tags, groups and files the log
    describes are exactly as they were.

    It leaves ONE entry behind, saying it happened. A log that is simply empty
    is indistinguishable from a library nobody has ever edited, and somebody
    coming back to find no history at all deserves the sentence explaining it
    rather than the doubt. That entry is not revertible; there is nothing to
    put back.
    """
    n = int(ctx.session.execute(
        select(func.count()).select_from(Event)).scalar_one())
    ctx.session.execute(delete(Event))
    # Flushed before the new row goes in, or the entry that explains the
    # deletion is itself deleted by it.
    ctx.session.flush()
    ctx.log(action=actions.CLEAR_HISTORY, entity_type="library",
            entity_id=None,
            summary=("Cleared the history — 1 entry deleted" if n == 1
                     else "Cleared the history — {n} entries deleted"),
            summary_vars={"n": f"{n:,}"} if n != 1 else None,
            data={"deleted": n})
    return n

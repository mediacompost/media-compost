"""The one bundle every operation takes.

An op is ``verb_noun(ctx, <domain args>, *, <options>) -> <domain value>``. The
``Ctx`` carries the four things that cut across all of them — the session, who
is acting, which badge the History shows, and (for the ops that touch bytes)
the item store — so that adding a fifth does not mean editing 146 signatures.

**`source` has to survive nesting**, which is the real reason this is one token
rather than loose keyword arguments. ``merge_tag`` writes ``add_tag`` and
``remove_tag`` events; ``delete_subject(with_tag=True)`` calls ``delete_tag``;
``update_subject`` calls ``update_tag``. Threading ``source="script"`` by hand
through every nested call is exactly the thing that gets forgotten once and
then silently labels a script's changes as web edits — which is the bug this
whole layer exists to fix. A token that is passed down cannot be half-passed.

**Ops never commit, never roll back and never close.** Whoever owns the session
owns its cadence: ``server/deps.py:get_session`` per request, the scripting
library per call or per ``transaction()``, the importer and jobs worker their
own. Ops may ``flush()`` — several must, to hand out ids.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from sqlalchemy.orm import Session

from ..history import log_event

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..config import Config
    from ..db import Event
    from ..storage import ItemStore


# The History badge. "web" is a browser, "cli" a local process against the
# library (the CLI and the scripting API both mean this), "ai" the jobs worker
# applying a model's output.
SOURCES = ("web", "cli", "ai")


@dataclass(frozen=True, eq=False)
class Ctx:
    """Session + caller identity + the store, for one unit of work."""

    session: Session
    source: str = "web"
    username: str = ""
    # Optional because most ops never touch disk, and a test wants to build a
    # Ctx without standing up a store. `store` / `config` below raise a clear
    # error rather than silently inventing a data dir.
    _store: "Optional[ItemStore]" = None
    _config: "Optional[Config]" = None

    def __post_init__(self) -> None:
        # `history.log_event` reads the acting user off the session rather than
        # taking it per call, so every op attributes automatically. Setting it
        # here is what makes that true for scripts, which never had one.
        #
        # Only ever WIDENS the attribution: an empty username leaves whatever
        # the session already carries alone. Otherwise `Ctx(session=s)` built
        # inside a request — where `get_session` has already stashed the real
        # user — would quietly wipe it and log the change as anonymous.
        if self.username:
            self.session.info["username"] = self.username
        else:
            self.session.info.setdefault("username", "")

    # ---- the pieces some ops need ------------------------------------------

    @property
    def store(self) -> "ItemStore":
        """The item store, for ops that move or delete bytes."""
        if self._store is not None:
            return self._store
        if self._config is not None:
            from ..storage import ItemStore

            return ItemStore(self._config)
        raise RuntimeError(
            "this operation touches stored files, so its Ctx needs a store or "
            "a config: Ctx(session, _store=lib.store) "
            "or Ctx(session, _config=cfg)"
        )

    @property
    def config(self) -> "Config":
        if self._config is not None:
            return self._config
        if self._store is not None:
            return self._store.cfg
        raise RuntimeError(
            "this operation needs the library config: pass Ctx(session, "
            "_config=cfg)"
        )

    # ---- history ------------------------------------------------------------

    def log(self, *, action: str, entity_type: str = "",
            entity_id: Optional[int] = None, summary: str = "",
            summary_vars: Optional[dict] = None,
            data: Optional[dict] = None) -> "Event":
        """Append one event to the log, attributed to this Ctx's source and
        user. Does not commit (see the module docstring). ``summary`` is a
        TEMPLATE and ``summary_vars`` fills it — see ``history.log_event``."""
        return log_event(
            self.session, source=self.source, action=action,
            entity_type=entity_type, entity_id=entity_id, summary=summary,
            summary_vars=summary_vars, data=data,
        )

    # ---- derivation ---------------------------------------------------------

    def with_source(self, source: str) -> "Ctx":
        """The same context under a different History badge."""
        return Ctx(session=self.session, source=source, username=self.username,
                   _store=self._store, _config=self._config)


def ctx_for(session: Session, source: str = "web", **kw) -> Ctx:
    """A Ctx over a session that already carries its caller.

    For a writer that holds a bare ``Session`` and needs to call an op — a
    router not yet converted, the jobs worker, the importer. The username is
    read back off the session rather than re-resolved, so attribution is
    whatever the session's owner already established.
    """
    return Ctx(session=session, source=source,
               username=session.info.get("username", ""), **kw)

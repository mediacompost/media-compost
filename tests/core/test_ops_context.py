"""`Ctx` — the bundle every operation takes.

Three of its rules are the kind that fail silently if they regress, so they get
tests rather than comments: it must never *narrow* the attribution already on a
session, its `source` must reach the log, and the ops package must never
commit.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from media_compost.db import Database, Event
from media_compost.ops import Ctx, actions
from media_compost.testing import COMMIT_RULE, commit_offenders

_OPS_DIR = pathlib.Path(
    __import__("media_compost.ops", fromlist=["ops"]).__file__
).parent


@pytest.fixture
def session():
    db = Database.in_memory()
    with db.session() as s:
        yield s


def test_ctx_sets_the_username_for_history(session):
    Ctx(session=session, source="cli", username="alice")
    assert session.info["username"] == "alice"


def test_an_anonymous_ctx_never_wipes_an_identity_already_on_the_session(session):
    """The trap: `Ctx(session=s)` built inside a request — where `get_session`
    has already stashed the real user — would otherwise log the change as
    anonymous. A Ctx only ever widens the attribution."""
    session.info["username"] = "alice"
    Ctx(session=session)  # no username given
    assert session.info["username"] == "alice"


def test_a_ctx_on_a_bare_session_leaves_log_event_a_value_to_read(session):
    Ctx(session=session)
    assert session.info["username"] == ""


def test_the_source_reaches_the_log(session):
    ctx = Ctx(session=session, source="cli", username="alice")
    ctx.log(action=actions.ADD_TAG, entity_type="item", entity_id=1,
            summary="Tagged item #1 +portrait",
            data={"item_id": 1, "tag": "portrait"})
    session.flush()
    ev = session.query(Event).one()
    assert (ev.source, ev.username, ev.action) == ("cli", "alice", "add_tag")


def test_with_source_keeps_everything_else(session):
    ctx = Ctx(session=session, source="web", username="alice")
    ai = ctx.with_source("ai")
    assert (ai.source, ai.username, ai.session) == ("ai", "alice", session)


def test_asking_for_the_store_without_one_says_what_to_pass(session):
    """A programming error, so a RuntimeError — not an OpError, which the web
    layer would turn into a 400 blaming the caller for the server's bug."""
    with pytest.raises(RuntimeError, match="needs a store or a config"):
        _ = Ctx(session=session).store


def test_a_ctx_with_only_a_config_can_build_its_own_store(tmp_path):
    from media_compost.config import Config

    cfg = Config(data_dir=tmp_path / "data")
    db = Database(cfg)
    with db.session() as s:
        ctx = Ctx(session=s, _config=cfg)
        assert ctx.store.item_dir("abc").is_absolute()
        assert ctx.config is cfg


def test_ops_never_commit():
    """The one rule the whole layering rests on: whoever owns the session owns
    its cadence. An op that commits would break `with lib.transaction():`,
    break the request's rollback-on-error, and split one History entry into
    several.

    The scan is `testing.commit_offenders`, shared with the app suite: the
    app's own two ops modules and its `editor.py` are held to the same rule by
    `tests/ui/test_ops_ratchet.py`, and the two used to spell it out
    separately."""
    offenders = commit_offenders(sorted(_OPS_DIR.rglob("*.py")))
    assert not offenders, COMMIT_RULE + "\n".join(offenders)

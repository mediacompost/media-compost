"""The Pending category's tags/captions split."""

from __future__ import annotations

from media_compost.db import Caption, Item, ItemTag, Tag
from media_compost.ops.search import pending_item_ids as _pending_item_ids


def test_pending_kind_split(lib):
    _cfg, db, _store = lib
    with db.session() as s:
        tag = Tag(name="x")
        s.add(tag)
        a, b, c = Item(name="a"), Item(name="b"), Item(name="c")
        s.add_all([a, b, c])
        s.flush()
        # a: pending tag only; b: pending caption only; c: both.
        s.add(ItemTag(item_id=a.id, tag_id=tag.id, pending=True))
        s.add(Caption(item_id=b.id, text="cap", pending=True))
        s.add(ItemTag(item_id=c.id, tag_id=tag.id, pending=True))
        s.add(Caption(item_id=c.id, text="cap", pending=True))
        s.commit()

        assert _pending_item_ids(s, "tags") == {a.id, c.id}
        assert _pending_item_ids(s, "captions") == {b.id, c.id}
        assert _pending_item_ids(s, "") == {a.id, b.id, c.id}

"""What a query MEANS is the same here as in the search field.

Every consumer — the web search, the Python API, the training dataset
builder — funnels through the ONE `QueryCtx` built in `ops/search.py` now,
and the trap that forced that consolidation is the ctx itself: a condition
kind whose loader is not wired in does not fail, it silently matches nothing.
That is the regression the subject/place cases below guard — a scripted
selection returning zero items with no error to read, while the same query
worked in the app.
"""

from __future__ import annotations

from pathlib import Path

from media_compost import MetaCond, QueryGroup, TagCond, open_library
from tests.core.conftest import make_jpeg_with_exif


def _seed(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    make_jpeg_with_exif(src / "a.jpg", seed=1)
    make_jpeg_with_exif(src / "b.jpg", seed=2)
    lib = open_library(tmp_path / "data")
    lib.import_folder(src, folders_as_groups=False)
    tagged = lib.query(sort="name").first()
    tagged.tags.add("portrait")
    return lib, tagged.id


def test_a_query_reads_files_dimensions_and_metadata(tmp_path: Path):
    lib, tagged_id = _seed(tmp_path)
    with lib:
        items = list(lib.query())
        assert len(items) == 2
        v = lib.items[tagged_id]
        assert v.path is not None and v.path.exists()
        assert v.width == 640 and v.height == 480
        assert "portrait" in v.tags
        assert v.metadata["camera_make"] == "TestMake"
        assert v.metadata["width"] == 640.0


def test_a_hand_built_tree_narrows_the_same_way_the_search_field_does(
    tmp_path: Path,
):
    """The condition models ARE the wire format, so assembling one is a
    supported way in — and the way a caller builds a query out of variables,
    where a string would need `querystring.escape_name` around every value."""
    lib, tagged_id = _seed(tmp_path)
    with lib:
        def both(width: int):
            return QueryGroup(op="and", children=[
                TagCond(name="portrait"),
                MetaCond(name="width", mtype="numeric", op=">=", value=width),
            ])

        # width is 640, so the width bound excludes the tagged item.
        assert list(lib.query(both(800))) == []
        assert lib.query(both(600)).ids() == [tagged_id]


def test_a_query_string_says_the_same_thing_as_a_hand_built_tree(tmp_path: Path):
    """The string spelling is the primary one, and it goes through the same
    parser the search field's grammar is mirrored from — so the operators are
    that grammar's, not SQL's: a SPACE is AND, `|` is OR, `!` negates, and a
    metadata comparison needs its `INFO:` keyword (bare `width>=600` is a tag
    name, since every lowercase word is one)."""
    lib, tagged_id = _seed(tmp_path)
    with lib:
        assert lib.query("portrait INFO:width>=600").ids() == [tagged_id]
        assert lib.query("portrait INFO:width>=800").ids() == []
        assert lib.query("!portrait").ids() == [
            i for i in lib.query().ids() if i != tagged_id]
        # `|` is the other separator, and one arm is enough to match.
        assert sorted(lib.query("portrait|nothing_at_all").ids()) == [tagged_id]


def test_a_subject_and_a_place_condition_mean_here_what_they_mean_in_the_app(
    tmp_path: Path,
):
    """They used to match NOTHING. `QueryCtx` was built without `subjects=` or
    `places=`, so both fields defaulted empty and every such condition quietly
    evaluated false."""
    lib, tagged_id = _seed(tmp_path)
    with lib:
        alice = lib.create_subject("Alice", since="1975")
        tokyo = lib.create_place(name="Tokyo, Japan")
        item = lib.items[tagged_id]
        item.tags.add(alice.tag.name)
        item.tags.add(tokyo.tag.name)

        assert lib.query("SUBJECT:").ids() == [tagged_id]
        assert lib.query(f"SUBJECT:{alice.tag.name}").ids() == [tagged_id]
        # ONE text field: `=` is the whole line, `:` is anywhere in it — and
        # a field name that is not `address` or `tag` reads the address, which
        # A place is matched on its one line, of which the city is part.
        assert lib.query("PLACE:Tokyo").ids() == [tagged_id]
        assert lib.query('PLACE:Japan').ids() == [tagged_id]
        # And a bound still narrows: nobody dated this assignment.
        assert lib.query("SUBJECT:#10..14").ids() == []

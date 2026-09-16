"""The import command's one line of output, and its one way out.

Both of these are about a NAME BEING DATA — it comes off somebody's disk and
may hold anything — and about a terminal being a fixed grid rather than a
stream of messages.
"""

from __future__ import annotations

import pytest
from rich.cells import cell_len

from media_compost import cli


@pytest.fixture(autouse=True)
def fixed_width(monkeypatch):
    """A known terminal, so the arithmetic is the test's rather than the
    machine's."""
    monkeypatch.setattr(type(cli.console), "width",
                        property(lambda self: 60))


def test_every_line_is_the_SAME_width_so_none_can_leave_debris():
    """`end="\\r"` erases nothing. A short name after a long one used to
    leave the tail of the long one on screen for the rest of the run."""
    long = cli._one_line(
        9, "a/deep/path/with/a/really/quite/unreasonably/long/name/"
           "page-0012.png")
    short = cli._one_line(10, "b.png")
    assert cell_len(long) == cell_len(short) == 59
    # …and the long one is CUT rather than wrapped: a name wider than the
    # terminal wrapped, after which the carriage return went to the start of
    # the LAST row and everything above it stayed for good.
    assert "page-0012.png" in long, "the cut keeps the end, which is the name"
    assert "…" in long, "and says that it was cut"


def test_the_width_is_CELLS_and_not_characters():
    """A CJK name is two columns per character. Measured in `len()` it would
    be cut to half the terminal and padded to twice it — the same debris by
    another route."""
    line = cli._one_line(1, "佐藤秀峰 - ブラックジャックによろしく完全版.pdf")
    assert cell_len(line) == 59
    assert len(line) != cell_len(line), "the case has to be a wide one"


def test_a_name_is_DATA_and_never_markup(capsys):
    """`[HorribleSubs] ep01.mkv` is an ordinary file name. Handed to rich as
    markup it is swallowed, or raises out of the progress printer — the
    failure `_tolerate_unprintable_names` records, one class along."""
    cli._print_progress(3, "[HorribleSubs] brackets [1080p].png")
    out = capsys.readouterr().out
    assert "[HorribleSubs] brackets [1080p].png" in out


def test_ctrl_c_is_an_ANSWER_rather_than_a_crash(capsys, monkeypatch):
    """A traceback through whatever frame the interrupt landed in says
    nothing the person did not already know, and buries the one thing they
    do want to hear: that the work up to here is theirs to keep."""
    def boom(_args):
        raise KeyboardInterrupt

    args = cli._parser().parse_args(["import", "--data-dir", "/tmp/x", "/tmp/y"])
    args.func = boom
    monkeypatch.setattr(cli, "_parser",
                        lambda: type("P", (), {
                            "parse_args": staticmethod(lambda *_: args)})())

    code = cli.main([])
    out = capsys.readouterr().out
    assert code == 130, "130 is what a shell reports for a SIGINT'd command"
    assert "Interrupted" in out
    assert "Traceback" not in out

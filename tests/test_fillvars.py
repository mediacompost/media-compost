"""``fillvars`` against the same cases the TS twin's tests pin — the two
implementations must agree or a template written here renders differently
after the frontend's lookup."""

from media_compost.fillvars import fillvars


def test_no_vars_is_identity():
    assert fillvars("no vars at all") == "no vars at all"
    assert fillvars("keeps {name}", None) == "keeps {name}"
    assert fillvars("keeps {name}", {}) == "keeps {name}"


def test_fills_repeats_and_coerces():
    assert fillvars("{a} and {a}", {"a": "x"}) == "x and x"
    assert fillvars("{n} items", {"n": 3}) == "3 items"


def test_unknown_placeholder_stays():
    assert fillvars("{a} keeps {b}", {"a": "x"}) == "x keeps {b}"


def test_curly_quotes_and_braces_ride_through():
    # The messages carry curly quotes, and a user-typed value may carry
    # braces — neither may acquire escaping rules (the str.format trap).
    assert (fillvars("no tag named “{name}” to alias to", {"name": "a{b}"})
            == "no tag named “a{b}” to alias to")


def test_substitution_runs_per_key_over_the_whole_string():
    # A value that LOOKS like a later placeholder is expanded by that later
    # key's pass — a quirk of split/join-per-key, pinned here because the TS
    # twin answers the same and the two must agree, quirks included.
    assert fillvars("{a} {b}", {"a": "{b}", "b": "x"}) == "x x"

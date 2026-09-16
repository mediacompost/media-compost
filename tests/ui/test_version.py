"""The version is written in four files, and this is what holds them equal.

`pyproject.toml`, `media_compost/__init__.py`, `frontend/package.json` and
`website/mkdocs.yml` each carry the number, nothing derives one from another,
and a release bump is the moment they drift: the wheel then says one thing and
the app running out of it another, silently. `scripts/bump_version.py` owns
the list of files and rewrites them together; this test imports that list, so
a fifth copy added to the script is covered here without a second list.

It moves `CHANGELOG.md`'s top section on the same two gestures, and that is
held here too: the release renames `## Unreleased` to the number, the dev bump
opens an empty one, and a release with nothing written under that heading is
refused before any file is touched.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]


def _script():
    spec = importlib.util.spec_from_file_location("bump_version", REPO / "scripts" / "bump_version.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_every_copy_of_the_version_agrees():
    found = _script().read_all(REPO)
    assert len(found) == 4, found
    assert len(set(found.values())) == 1, found


def test_the_version_is_a_shape_pip_orders():
    """X.Y.Z or X.Y.Z.devN — what makes a main build sort between two releases."""
    mod = _script()
    version = next(iter(mod.read_all(REPO).values()))
    assert mod.VERSION_RE.match(version), version


def test_the_package_reports_the_same_number():
    import media_compost

    assert media_compost.__version__ == next(iter(_script().read_all(REPO).values()))


def test_the_bump_rewrites_every_copy_and_nothing_else(tmp_path):
    """Round trip over a copy of the four files: the number moves, the rest is bytes-identical."""
    mod = _script()
    before: dict[str, str] = {}
    for rel, _ in mod.SPELLINGS:
        src = REPO / rel
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        before[rel] = dst.read_text(encoding="utf-8")
    current = next(iter(mod.read_all(tmp_path).values()))
    mod.write_all("9.8.7.dev3", tmp_path)
    assert set(mod.read_all(tmp_path).values()) == {"9.8.7.dev3"}
    for rel, _ in mod.SPELLINGS:
        after = (tmp_path / rel).read_text(encoding="utf-8")
        assert after.replace("9.8.7.dev3", current, 1) == before[rel], rel
    mod.write_all(current, tmp_path)
    for rel, _ in mod.SPELLINGS:
        assert (tmp_path / rel).read_text(encoding="utf-8") == before[rel], rel


@pytest.mark.parametrize(
    "fn, args, expected",
    [
        ("next_dev", ("1.0.0",), "1.0.1.dev0"),
        ("next_dev", ("2.4.9",), "2.4.10.dev0"),
        ("release_of", ("1.0.1.dev0",), "1.0.1"),
        ("release_of", ("1.0.1.dev4",), "1.0.1"),
        ("release_of", ("1.0.1.dev0", "minor"), "1.1.0"),
        ("release_of", ("1.0.1.dev0", "major"), "2.0.0"),
    ],
)
def test_the_two_steps_of_a_release(fn, args, expected):
    assert getattr(_script(), fn)(*args) == expected


def test_the_dev_bump_sorts_below_every_release_it_could_become():
    """The reason the bump is the PATCH: a main build must upgrade to whatever
    ships next, and pip refuses a downgrade. `1.1.0.dev0` would sit above a
    `1.0.1` patch."""
    from packaging.version import Version

    mod = _script()
    dev = Version(mod.next_dev("1.0.0"))
    for level in ("patch", "minor", "major"):
        assert Version("1.0.0") < dev < Version(mod.release_of(str(dev), level)), level


@pytest.mark.parametrize(
    "fn, args",
    [("next_dev", ("1.0.1.dev0",)), ("release_of", ("1.0.0",)), ("release_of", ("1.0.1.dev0", "huge"))],
)
def test_the_two_steps_refuse_the_wrong_direction(fn, args):
    with pytest.raises(SystemExit):
        getattr(_script(), fn)(*args)


LOG = """# Changelog

## Unreleased

- something a user would notice

## 1.0.0

First release
"""


def test_a_release_renames_the_unreleased_section():
    mod = _script()
    out = mod.rename_unreleased(LOG, "1.1.0")
    assert "## 1.1.0\n\n- something a user would notice" in out
    assert "Unreleased" not in out
    # Everything else is untouched, the older section included.
    assert out == LOG.replace("## Unreleased", "## 1.1.0", 1)


@pytest.mark.parametrize(
    "text",
    [
        "# Changelog\n\n## 1.0.0\n\nFirst release\n",          # never opened
        "# Changelog\n\n## Unreleased\n\n## 1.0.0\n\nx\n",     # opened, nothing written
        "# Changelog\n\n## Unreleased\n",                        # opened, end of file
    ],
)
def test_a_release_refuses_a_missing_or_empty_unreleased(text):
    """The failure it exists to prevent is silent: nobody re-reads the entry
    for the release they have just cut."""
    with pytest.raises(SystemExit):
        _script().rename_unreleased(text, "1.1.0")


def test_the_dev_bump_reopens_the_section_and_only_once():
    mod = _script()
    shipped = mod.rename_unreleased(LOG, "1.1.0")
    out = mod.reopen_unreleased(shipped)
    assert out.index("## Unreleased") < out.index("## 1.1.0")
    assert out.replace("## Unreleased\n\n", "", 1) == shipped
    assert mod.reopen_unreleased(out) == out


def _tree(mod, tmp_path, log=LOG):
    for rel, _ in mod.SPELLINGS:
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text((REPO / rel).read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / mod.CHANGELOG).write_text(log, encoding="utf-8")
    mod.ROOT = tmp_path
    return tmp_path


def test_the_changelog_and_the_version_move_together(tmp_path):
    mod = _script()
    _tree(mod, tmp_path)
    mod.write_all("1.0.1.dev0", tmp_path)

    assert mod.main(["--release"]) == 0
    assert set(mod.read_all(tmp_path).values()) == {"1.0.1"}
    assert "## 1.0.1" in (tmp_path / mod.CHANGELOG).read_text()

    assert mod.main(["--next-dev"]) == 0
    assert set(mod.read_all(tmp_path).values()) == {"1.0.2.dev0"}
    log = (tmp_path / mod.CHANGELOG).read_text()
    assert log.index("## Unreleased") < log.index("## 1.0.1")


def test_a_refused_changelog_leaves_the_version_alone(tmp_path):
    """Why the changelog is worked out before write_all: half a bump is worse
    than no bump, and this is the only thing that can refuse one."""
    mod = _script()
    _tree(mod, tmp_path, log="# Changelog\n\n## 1.0.0\n\nFirst release\n")
    mod.write_all("1.0.1.dev0", tmp_path)
    with pytest.raises(SystemExit):
        mod.main(["--release"])
    assert set(mod.read_all(tmp_path).values()) == {"1.0.1.dev0"}


def test_a_dev_version_has_somewhere_to_write_the_next_entry():
    """main between releases carries `X.Y.Z.devN`, which `--next-dev` reopened
    the section in the same commit as."""
    mod = _script()
    version = next(iter(mod.read_all(REPO).values()))
    if not version.endswith(tuple(f"dev{n}" for n in range(10))):
        pytest.skip(f"{version} is a release commit")
    assert "## Unreleased" in (REPO / mod.CHANGELOG).read_text(encoding="utf-8")


def test_one_version_s_entry_is_what_the_release_says():
    mod = _script()
    assert mod.section_of(LOG, "1.0.0") == "First release"
    assert mod.section_of(LOG, "Unreleased") == "- something a user would notice"


@pytest.mark.parametrize(
    "version, text",
    [
        ("1.1.0", LOG),                                             # no such section
        ("1.0.0", "# Changelog\n\n## 1.0.0\n\n## 0.9.0\n\nx\n"),  # there, says nothing
        ("1.0.0", "## 1.0.0\n\na\n\n## 1.0.0\n\nb\n"),           # twice: which one?
    ],
)
def test_a_release_with_nothing_written_about_it_is_refused(version, text):
    """draft.yml asks this before it builds, because past the upload it is
    not a mistake anybody can take back — PyPI will not replace a version."""
    with pytest.raises(SystemExit):
        _script().section_of(text, version)


def test_the_release_workflow_asks_this_script_for_the_notes():
    """The flag is load-bearing for a workflow that runs a few times a year:
    renamed here, it would fail on release day and nowhere else."""
    workflow = (REPO / ".github" / "workflows" / "draft.yml").read_text(encoding="utf-8")
    assert "bump_version.py --section" in workflow


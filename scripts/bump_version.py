#!/usr/bin/env python3
"""Move the package version, in every file that spells it.

THE NUMBER LIVES IN FIVE PLACES and nothing derives one from another:
`pyproject.toml` (the wheel), `media_compost/__init__.py` (`__version__`,
which the server's own title and the trainer's `adapter_config.json` read),
`frontend/package.json` (the bundle), `frontend/package-lock.json` (npm's
copy of that one, twice over) and `website/mkdocs.yml`
(`extra.version_number`, what the site's install commands and footer say).
Five edits on release day is how they drift, and the drift is silent: a
wheel says one thing and the app running out of it says another.

THE LOCK IS HERE BECAUSE IT WAS THE COPY NOBODY MOVED. It is not hand-edited
— npm rewrites it from `package.json` — so it drifted the moment a release
bumped the four and then sat wrong until somebody happened to run `npm`, which
rewrote it as an unexplained change in whatever they were doing. It carries
the number TWICE, at the top and again under `packages.""`, and it is matched
through the `"name"` line above each: every dependency in the file has a
`"version"` line of its own, 55 of them here, and an indentation-anchored
pattern would have rewritten all of them.

    scripts/bump_version.py                 print the five numbers
    scripts/bump_version.py --check         exit 1 unless they agree (the test)
    scripts/bump_version.py 1.1.0.dev0      set every copy
    scripts/bump_version.py --next-dev      1.0.0 -> 1.0.1.dev0, the post-release bump
    scripts/bump_version.py --release       1.0.1.dev0 -> 1.0.1, the release commit
    scripts/bump_version.py --release minor 1.0.1.dev0 -> 1.1.0
    scripts/bump_version.py --release major 1.0.1.dev0 -> 2.0.0
    scripts/bump_version.py --section 1.1.0   print that version's changelog entry

THE TWO RELEASE GESTURES ALSO MOVE `CHANGELOG.md`, because its top section
turns on exactly them: `--release` renames `## Unreleased` to the number being
shipped, and `--next-dev` opens an empty one above it for the next round. An
explicit version does not, and neither does `--check` — the changelog is not a
copy of the version, it is a document that changes hands on the same day. A
`--release` whose `## Unreleased` is missing or empty is REFUSED before a
single version file is written, since the alternative is shipping a release
that says nothing about itself and finding out never: nobody re-reads the
changelog for the release they have just cut.

The workflow this serves: tag `vX.Y.Z` on the commit carrying that number, and
the next commit on main is `--next-dev`. A build from main then sorts ABOVE the
release under PEP 440 and BELOW the next one, so `pip install` upgrades a
release to a test build and a test build to the next release, in that order,
and the unreleased docs mike publishes from main name a version that does not
claim to be a release. A bare `1.1.0` on main would do neither.

THE DEV BUMP IS THE PATCH, and what the next release is called is decided on
release day (`--release minor`). The order is the reason: `1.0.1.dev0` sorts
below BOTH `1.0.1` and `1.1.0`, so whichever ships is an upgrade from every
main build in between; `1.1.0.dev0` sorts ABOVE `1.0.1`, so a patch shipped
after that bump would refuse to install over a main build, and the number on
main would have to go down — which reads as a mistake in every log that has it.

Stdlib only, and `tests/ui/test_version.py` imports it by file path, so the
file list here is the one the test holds — a sixth copy added to the tree
needs to be added HERE, and the test then covers it.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

# (path, the line that carries the number — anchored, one capture group — and
# HOW MANY lines in that file carry it). The count is explicit rather than
# "at least one": a pattern that started matching a line it was not written
# for is the failure this list exists to prevent, and it is caught by the
# number changing rather than by somebody reading the diff.
SPELLINGS: list[tuple[str, str, int]] = [
    ("pyproject.toml", r'^version = "([^"]+)"$', 1),
    ("media_compost/__init__.py", r'^__version__ = "([^"]+)"$', 1),
    ("frontend/package.json", r'^  "version": "([^"]+)",$', 1),
    ("frontend/package-lock.json",
     r'^ *"name": "media-compost-frontend",\n *"version": "([^"]+)",$', 2),
    ("website/mkdocs.yml", r'^  version_number: "([^"]+)"$', 1),
]

# PEP 440's public shape as this project uses it: X.Y.Z, optionally .devN.
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:\.dev(\d+))?$")

# The changelog is deliberately NOT in SPELLINGS: that list is what `read_all`
# and `--check` hold equal, and a heading is not a copy of the number.
CHANGELOG = "CHANGELOG.md"
UNRELEASED = "Unreleased"
SECTION = re.compile(r"^## +(.+?) *$", re.M)

# A VERSION IS A `##` HEADING AND NOTHING ELSE. A version's entries are one
# list (`CONTRIBUTING.md`), but a `###` heading inside a section is invisible
# to `SECTION` by construction — `## +` wants a SPACE after two hashes and a
# third hash is not one — so if one is ever written, the body is that heading
# and its entries together rather than the section stopping short of them.
# That body is what `--section` prints and what the release notes say.
GROUP = re.compile(r"^#{3,} +.*$", re.M)


def read_all(root: pathlib.Path | None = None) -> dict[str, str]:
    """Each file's number, keyed by its repo-relative path.

    Raises if a file has lost the line — a version nothing can read is worse
    than a disagreement, and a regex that silently matched nothing would
    report the file as agreeing with everything.
    """
    root = ROOT if root is None else root
    found: dict[str, str] = {}
    for rel, pattern, count in SPELLINGS:
        text = (root / rel).read_text(encoding="utf-8")
        hits = re.findall(pattern, text, flags=re.M)
        if len(hits) != count:
            raise SystemExit(f"{rel}: expected {count} version line(s), found {len(hits)}")
        # A file that spells it twice must agree with itself before it is
        # compared with anything else.
        if len(set(hits)) != 1:
            raise SystemExit(f"{rel}: its own copies disagree: {sorted(set(hits))}")
        found[rel] = hits[0]
    return found


def write_all(version: str, root: pathlib.Path | None = None) -> None:
    root = ROOT if root is None else root
    for rel, pattern, count in SPELLINGS:
        path = root / rel
        text = path.read_text(encoding="utf-8")

        def keep_shape(m: re.Match[str]) -> str:
            # Replace only the captured number, so quotes and commas stay put.
            return m.group(0)[: m.start(1) - m.start(0)] + version + m.group(0)[m.end(1) - m.start(0):]

        new, n = re.subn(pattern, keep_shape, text, flags=re.M)
        if n != count:
            raise SystemExit(f"{rel}: expected {count} version line(s), found {n}")
        path.write_text(new, encoding="utf-8")


def next_dev(version: str) -> str:
    m = VERSION_RE.match(version)
    if not m:
        raise SystemExit(f"not a version this script understands: {version!r}")
    if m.group(4) is not None:
        raise SystemExit(f"{version} is already a dev version")
    return f"{m.group(1)}.{m.group(2)}.{int(m.group(3)) + 1}.dev0"


def release_of(version: str, level: str = "patch") -> str:
    """The release a dev version becomes: its own number, or a bigger one.

    `patch` strips the suffix — the number the dev bump already chose.
    `minor` and `major` raise that number, because the bump only ever
    promises the smallest next release and the real one is decided here.
    """
    m = VERSION_RE.match(version)
    if not m:
        raise SystemExit(f"not a version this script understands: {version!r}")
    if m.group(4) is None:
        raise SystemExit(f"{version} is not a dev version")
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if level == "patch":
        return f"{major}.{minor}.{patch}"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    if level == "major":
        return f"{major + 1}.0.0"
    raise SystemExit(f"not a release level: {level!r} (patch, minor or major)")


def rename_unreleased(text: str, version: str) -> str:
    """`## Unreleased` becomes `## X.Y.Z`, keeping everything written under it.

    Refuses a changelog with no such section and one whose section is empty.
    Both mean a release about to go out with nothing said about it, which is
    the whole failure the section exists to prevent, and it is silent
    afterwards — the person who cut the release is the last person who will
    read its entry.
    """
    found = [m for m in SECTION.finditer(text) if m.group(1) == UNRELEASED]
    if len(found) != 1:
        raise SystemExit(
            f"{CHANGELOG}: expected one '## {UNRELEASED}' heading, found {len(found)}"
        )
    head = found[0]
    if not _says_something(_body_under(text, head)):
        raise SystemExit(
            f"{CHANGELOG}: '## {UNRELEASED}' holds no entry — write what "
            f"{version} changed before releasing it"
        )
    return text[: head.start()] + f"## {version}" + text[head.end():]


def _body_under(text: str, head: re.Match[str]) -> str:
    """What a `## ` heading holds: down to the next one, or the end."""
    after = SECTION.search(text, head.end())
    return text[head.end(): after.start() if after else len(text)]


def _says_something(body: str) -> bool:
    """Does this section say anything — with any `###` HEADING discounted.

    A body of headings and nothing under them is not empty as a string, and
    shipping it is exactly the silence the two checks below exist to catch.
    Discounting the headings rather than demanding a list item, because a
    section may legitimately be one line of prose (the first release's is).
    """
    return bool(GROUP.sub("", body).strip())


def section_of(text: str, version: str) -> str:
    """One version's entry, without its heading — the release's own notes.

    `publish.yml` runs this against the tag BEFORE it builds anything, so a
    release nobody wrote an entry for fails while that is still a mistake
    somebody can take back. Past the upload it is not: PyPI does not let a
    version be replaced, so the alternative is a release on the index whose
    changelog says nothing and never will.
    """
    found = [m for m in SECTION.finditer(text) if m.group(1) == version]
    if len(found) != 1:
        raise SystemExit(
            f"{CHANGELOG}: expected one '## {version}' heading, found {len(found)}"
        )
    body = _body_under(text, found[0]).strip("\n")
    if not _says_something(body):
        raise SystemExit(f"{CHANGELOG}: '## {version}' is there and says nothing")
    return body


def reopen_unreleased(text: str) -> str:
    """An empty `## Unreleased` above the newest version. Already open: unchanged."""
    if any(m.group(1) == UNRELEASED for m in SECTION.finditer(text)):
        return text
    first = SECTION.search(text)
    at = first.start() if first else len(text)
    return text[:at] + f"## {UNRELEASED}\n\n" + text[at:]


def main(argv: list[str]) -> int:
    found = read_all()
    if not argv or argv == ["--check"]:
        for rel, v in found.items():
            print(f"{v:<14} {rel}")
        if len(set(found.values())) != 1:
            print("the copies disagree", file=sys.stderr)
            return 1
        return 0
    if argv[0] == "--section" and len(argv) == 2:
        print(section_of((ROOT / CHANGELOG).read_text(encoding="utf-8"), argv[1]))
        return 0
    current = next(iter(found.values()))
    if len(set(found.values())) != 1:
        raise SystemExit("the copies disagree; set an explicit version first")
    arg = argv[0]
    # Worked out BEFORE write_all, so a changelog that refuses the release
    # leaves the four version files untouched rather than half-bumped.
    log = (ROOT / CHANGELOG).read_text(encoding="utf-8")
    moved: str | None = None
    if arg == "--next-dev" and len(argv) == 1:
        target = next_dev(current)
        moved = reopen_unreleased(log)
    elif arg == "--release" and len(argv) <= 2:
        target = release_of(current, argv[1] if len(argv) == 2 else "patch")
        moved = rename_unreleased(log, target)
    elif len(argv) == 1 and VERSION_RE.match(arg):
        target = arg
    elif len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    else:
        print(f"not a version: {arg!r} (expected X.Y.Z or X.Y.Z.devN)", file=sys.stderr)
        return 2
    write_all(target)
    if moved is not None and moved != log:
        (ROOT / CHANGELOG).write_text(moved, encoding="utf-8")
        said = f"## {target}" if arg == "--release" else f"## {UNRELEASED}"
        print(f"{current} -> {target}   ({CHANGELOG}: {said})")
        return 0
    if moved is not None:
        print(f"{current} -> {target}   ({CHANGELOG}: already open)")
        return 0
    print(f"{current} -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

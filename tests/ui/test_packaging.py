"""The built app has to be inside the artifact somebody installs.

`_web_dist/` is generated and gitignored, and it holds no `__init__.py` — so
`packages.find` never sees it and a wheel built without `package-data` carries
no frontend at all. It still installs, still starts, still answers every API
call, and serves a blank page: the failure is completely silent, which is why
it is worth a test rather than a habit.

This one is FAST and builds nothing: it checks that the declared patterns
cover every file Vite actually emitted. That is the part that rots — a bundler
upgrade adding `_web_dist/chunks/` would slip past a hand-written glob list and
ship an app missing a chunk.

`scripts/package.sh` does the other half, on the real artifact, and refuses to
hand over a wheel it cannot find the UI inside.
"""

from __future__ import annotations

import fnmatch
import pathlib
import re
import tomllib

import pytest

# The packaging metadata sits at the REPO ROOT, while the bundle it is about
# lives inside the app subpackage.
REPO = pathlib.Path(__file__).resolve().parents[2]
WEB_DIST = REPO / "media_compost" / "ui" / "_web_dist"


def _patterns() -> list[str]:
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    return data["tool"]["setuptools"]["package-data"]["media_compost.ui"]


def test_package_data_is_declared_at_all():
    """Without this key the wheel silently contains no frontend."""
    assert any("_web_dist" in p for p in _patterns())


def test_the_manifest_covers_the_sdist_too():
    """An sdist is assembled separately from the wheel and needs its own say."""
    manifest = (REPO / "MANIFEST.in").read_text(encoding="utf-8")
    assert "media_compost/ui/_web_dist" in manifest


def test_no_setup_command_names_a_checkout_file():
    """A setup command must resolve on a WHEEL install, which has no checkout
    and no `scripts/` directory — `{python} scripts/setup_action.py` was the
    exact string that made every in-app "Run setup" fail there with a
    missing-file error. Commands name modules (`{python} -m media_compost.…`)
    — the wrapper scripts that once lived under `scripts/` are gone."""
    offenders = []
    for path in (REPO / "media_compost").rglob("*.py"):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "{python} scripts/" in line or "{pip} scripts/" in line:
                offenders.append(f"{path.relative_to(REPO)}:{i}")
    assert not offenders, (
        "setup command(s) reference a checkout-relative script, which a "
        "wheel install does not have:\n  " + "\n  ".join(offenders))


def test_the_env_requirements_ship_inside_the_package():
    """`media_compost/hub/setup_env.py` reads `requirements-<env>-env.txt`
    from beside itself, so the wheel and the sdist must both carry them —
    they lived at the repo root once, which a wheel install does not have."""
    hub = REPO / "media_compost" / "hub"
    envs = ("training", "florence", "magi")
    for env in envs:
        assert (hub / f"requirements-{env}-env.txt").is_file(), env

    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = data["tool"]["setuptools"]["package-data"]["media_compost.hub"]
    for env in envs:
        name = f"requirements-{env}-env.txt"
        assert any(fnmatch.fnmatch(name, pat) for pat in patterns), (
            f"{name} matches no media_compost.hub package-data pattern "
            f"({patterns}) — the wheel would ship setup_env.py without it")

    manifest = (REPO / "MANIFEST.in").read_text(encoding="utf-8")
    assert "media_compost/hub/requirements-" in manifest


def test_the_trainer_ships_inside_the_package():
    """`train/paths.py: TRAIN_SCRIPTS` points beside itself, so the wheel
    must carry the trainer's scripts as package-data — they lived at the
    checkout root as `training_scripts/`, which a wheel install does not
    have, so a wheel-installed server could set the training env up but
    never spawn a run. And they must stay DATA: `scripts/` carrying an
    `__init__.py` would let `packages.find` see it and let the torch-heavy
    modules be imported into the torch-free server."""
    from media_compost.train.paths import TRAIN_SCRIPTS

    scripts = REPO / "media_compost" / "train" / "scripts"
    assert TRAIN_SCRIPTS == scripts
    assert not (scripts / "__init__.py").exists(), (
        "train/scripts must stay package-DATA, never a package")

    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = data["tool"]["setuptools"]["package-data"]["media_compost.train"]
    for rel in ("scripts/train.py", "scripts/generate.py",
                "scripts/compose.py", "scripts/engines/sd.py",
                "scripts/engines/__init__.py"):
        assert (REPO / "media_compost" / "train" / rel).is_file(), rel
        assert any(fnmatch.fnmatch(rel, pat) for pat in patterns), (
            f"{rel} matches no media_compost.train package-data pattern "
            f"({patterns}) — the wheel would ship a trainer missing it")

    manifest = (REPO / "MANIFEST.in").read_text(encoding="utf-8")
    assert "media_compost/train/scripts" in manifest


@pytest.mark.skipif(not WEB_DIST.is_dir(),
                    reason="frontend not built (_web_dist is gitignored)")
def test_every_built_file_is_covered_by_a_pattern():
    patterns = _patterns()
    uncovered = []
    for path in WEB_DIST.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(WEB_DIST.parent).as_posix()
        if not any(fnmatch.fnmatch(rel, pat) for pat in patterns):
            uncovered.append(rel)
    assert not uncovered, (
        f"{len(uncovered)} built file(s) match no package-data pattern, so "
        f"they would be missing from the installed app:\n  "
        + "\n  ".join(sorted(uncovered)[:10])
        + f"\n\nPatterns: {patterns}"
    )


@pytest.mark.skipif(not WEB_DIST.is_dir(),
                    reason="frontend not built (_web_dist is gitignored)")
def test_the_pieces_the_server_actually_serves_are_there():
    """A sanity floor: the page, its bundle, and the self-hosted fonts (the
    app works offline, so they are not optional)."""
    assert (WEB_DIST / "index.html").is_file()
    assert list((WEB_DIST / "assets").glob("index-*.js"))
    assert list((WEB_DIST / "fonts").glob("*.woff2"))


def test_the_extras_keep_the_base_small():
    """The dependency contract, held where it is declared: the BASE is nine
    packages and no server, `[train]` stands alone (a headless box trains
    without fastapi), and `[full]` is the app on top of it. A server package
    drifting into the base would not fail anything by itself — every dev venv
    has all of it — which is what makes it a ratchet."""
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    base = {d.split(">")[0].split("=")[0].split("[")[0] for d in data["project"]["dependencies"]}
    assert base == {"sqlalchemy", "pydantic", "pillow", "pillow-heif",
                    "imagehash", "numpy", "py7zr", "pypdfium2", "rich"}
    extras = data["project"]["optional-dependencies"]
    # Two install shapes and a dev one. The finer extras were names for
    # subsets nobody asked for alone, and `[ui]` resolved to `[full]` exactly.
    assert set(extras) == {"train", "full", "dev"}
    train_names = {d.split(">")[0].split(";")[0].split("=")[0].strip()
                   for d in extras["train"]}
    # The hub plumbing the manager needs, and NVML for the Train tab's stats
    # boxes — NVIDIA's own binding, pure Python and dependency-free. It earns
    # its place by giving an ABSOLUTE temperature threshold, which nvidia-smi
    # on a current driver does not (it reports margins), and without which the
    # temperature has no ceiling to draw a bar against.
    assert train_names == {"huggingface_hub", "nvidia-ml-py"}
    # …and NOT on macOS, where no supported configuration has an NVIDIA GPU.
    # It is harmless there (the probe catches LibraryNotFound), so this is
    # about not shipping an NVIDIA package to Apple silicon.
    assert any('platform_system != "Darwin"' in d for d in extras["train"]
               if d.startswith("nvidia-ml-py"))
    full = " ".join(extras["full"])
    assert "fastapi" in full and "faiss-cpu" in full and "imageio-ffmpeg" in full
    assert "media-compost[train]" in extras["full"]
    # The trainer must NOT drag the app in: that is what a headless GPU box
    # installs, and fastapi on it would be the whole point of `[train]` lost.
    assert "fastapi" not in str(extras["train"])
    # PDF rendering is a BASE dependency, not an extra — reading a PDF is not
    # a specialism a picture library opts into, and `pypdfium2` ships a
    # self-contained wheel.
    assert "pdf" not in extras
    # torch stays OUT of every extra: PyPI's Windows wheel is CPU-only, and a
    # specifier cannot name the index the CUDA builds live on.
    assert "torch" not in str(extras)


def test_ci_installs_extras_that_exist():
    """The extras-matrix job verifies the packaging claims — so it has to
    install something.

    pip only WARNS on an extra a distribution does not provide ("does not
    provide the extra 'ui'") and installs the base instead, exit code 0. So a
    renamed extra does not fail where it is written; it fails one step later,
    on an import that was supposed to succeed, and reads as a broken package
    rather than a stale workflow. All three steps of that job were installing
    `[ui]` and `[training]` — neither of which has existed since the extras
    became train/full/dev — so the job that exists to prove the extras work
    was proving nothing about them.

    Read out of the workflow rather than kept in step by hand, because the
    whole failure is that nothing connects the two files.
    """
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8")
    declared = set(tomllib.loads(
        (REPO / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["optional-dependencies"])

    # Every `…[a,b]` an install line names, wheel path or source dir alike.
    named = {name.strip()
             for spec in re.findall(r"pip install[^\n]*?\[([a-z,\s]+)\]",
                                    workflow)
             for name in spec.split(",")}
    assert named, "no extras installed in CI at all — did the job move?"
    unknown = sorted(named - declared)
    assert not unknown, (
        f"ci.yml installs {unknown}, which pyproject.toml does not declare "
        f"(it has {sorted(declared)}). pip warns and installs the BASE, so "
        f"the step fails on whatever it imports next instead of here.")


def test_a_marker_ci_does_not_run_says_where_it_does():
    """Every marker `addopts` hides is either run by a CI step or WRITTEN DOWN.

    `addopts = -m 'not perf and not slow'` is about a DEVELOPER's inner loop:
    two files spend 167 s of a 314 s suite waiting on a tick thread and a torch
    subprocess, and paying that on every edit to something else buys nothing.
    CI used to ask for both back. It no longer does (owner 2026-09: a hosted
    runner repeating the long half of a suite that passed here before the push
    buys a queue), and the danger that argued for those steps is unchanged —
    the job goes on passing, in less time, having stopped testing the trainer's
    whole lifecycle, and nothing about a green run says so.

    So the rule moved rather than went: a hidden marker CI does not run has to
    be NAMED in `ci.yml`'s header, beside the command that runs it. Read out of
    the two files rather than kept in step by hand, for the same reason
    `test_ci_installs_extras_that_exist` is: the whole failure is that nothing
    connects them. Adding a marker to `addopts` and telling nobody fails HERE.
    """
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8")
    addopts = tomllib.loads(
        (REPO / "pyproject.toml").read_text(encoding="utf-8")
    )["tool"]["pytest"]["ini_options"]["addopts"]

    hidden = set(re.findall(r"not\s+(\w+)", addopts))
    assert hidden, f"addopts deselects nothing: {addopts!r} — did it move?"

    # Every `-m` a CI pytest step passes, quoted or bare.
    exprs = [q or s or bare for q, s, bare in re.findall(
        r"pytest[^\n]*?-m\s+(?:\"([^\"]+)\"|'([^']+)'|(\S+))", workflow)]
    assert exprs, "no CI pytest step passes -m at all — did the jobs move?"

    def selects(expr: str, marker: str) -> bool:
        """Whether `expr` matches a test carrying ONLY `marker`.

        The expressions really are boolean, so they are evaluated as boolean
        rather than pattern-matched: `not perf` selects a `slow` test, and
        `perf` does not, and no amount of substring searching gets both of
        those right (`not perf` mentions neither `slow` nor `not slow`)."""
        env = {m: (m == marker) for m in hidden}
        return bool(eval(expr, {"__builtins__": {}}, env))  # noqa: S307

    # The header is the comment block above `name:` — the one place a reader
    # meets the file, and so the only place "we do not run this" can be said.
    header = workflow.split("\nname:", 1)[0]
    spoken = {m for m in hidden
              if re.search(rf"^#.*pytest.*{re.escape(m)}", header,
                           re.MULTILINE)
              or re.search(rf"^#.*`{re.escape(m)}`", header, re.MULTILINE)}

    silent = sorted(m for m in hidden
                    if not any(selects(e, m) for e in exprs)
                    and m not in spoken)
    assert not silent, (
        f"addopts hides {sorted(hidden)}; CI runs none of {silent} and its "
        f"header does not say where they DO run. Give the marker a step, or "
        f"name it in the header beside the command — a marker nobody runs and "
        f"nobody mentions is a test that has quietly stopped existing.")


def test_every_redistributed_third_party_thing_is_attributed():
    """The attribution has to travel with the ARTIFACT, not with the repo.

    A wheel is often the only thing a user has, so a notices file pointing at
    a GitHub page is an attribution nobody can read. This holds the three
    obligations that are easy to satisfy once and then quietly break: the
    licence texts the notices file points at exist, `license-files` actually
    ships them, and the FONTS carry their own licence a second time beside
    the .woff2 files — those are served to a browser, which never sees
    dist-info.

    It does NOT check the notices file's prose. What it checks is that every
    file it references is really there.
    """
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    proj = data["project"]
    assert proj["license"] == "AGPL-3.0-or-later"
    # PEP 639's `license` string is silently ignored below setuptools 77 — a
    # wheel whose dist-info carries no licence at all, which nothing else here
    # would notice.
    assert 'setuptools>=77' in " ".join(data["build-system"]["requires"])

    declared = proj["license-files"]
    assert "LICENSE" in declared and "THIRD-PARTY-NOTICES.md" in declared
    notices = REPO / "THIRD-PARTY-NOTICES.md"
    assert (REPO / "LICENSE").is_file() and notices.is_file()

    # Every `licenses/*.txt` the notices file names must exist, and every text
    # that exists must be named — an orphan is a licence nobody is told about.
    text = notices.read_text(encoding="utf-8")
    on_disk = {p.name for p in (REPO / "licenses").glob("*.txt")}
    assert on_disk, "no licence texts at all"
    for name in on_disk:
        assert name in text, f"licenses/{name} is not mentioned in the notices"

    # The fonts, beside the files they cover. `public/` is what Vite copies
    # into `_web_dist`, so this is the source of the served copy.
    fonts = REPO / "frontend" / "public" / "fonts"
    for name in ("LICENSE-IBM-Plex.txt", "LICENSE-Material-Symbols.txt"):
        assert (fonts / name).is_file(), f"{name} missing from {fonts}"
    if WEB_DIST.is_dir():  # absent in a fresh clone, like the tests above
        for name in ("LICENSE-IBM-Plex.txt", "LICENSE-Material-Symbols.txt"):
            assert (WEB_DIST / "fonts" / name).is_file(), \
                f"{name} did not reach the built bundle — rebuild the frontend"


def test_no_unlicensed_third_party_code_is_vendored():
    """A ratchet on the one thing that is not paperwork.

    `colorize_mangav2.py` used to carry ~240 lines copied from a repository
    that publishes no licence — no grant, so no right to redistribute. It
    fetches that source at setup time now. This fails if the copy comes back,
    and it keys on the SHA pin rather than on line count: an unpinned fetch is
    the other way this breaks (an architecture that moves under a cached
    checkpoint fails deep inside `load_state_dict`).
    """
    plug = (REPO / "media_compost" / "ui" / "plugins" / "impl"
            / "colorize_mangav2.py").read_text(encoding="utf-8")
    assert "_UPSTREAM_SHA" in plug and len(
        [ln for ln in plug.splitlines()
         if ln.strip().startswith("_UPSTREAM_SHA")][0].split('"')[1]) == 40
    assert "class Generator" not in plug and "class FFDNet" not in plug, \
        "the unlicensed networks are vendored again — they may not be shipped"

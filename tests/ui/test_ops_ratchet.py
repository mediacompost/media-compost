"""The ratchet: mutation logic must not grow back inside the routers.

The extraction moves the writes into `media_compost/ops/` (and the app's own
two into `media_compost.ui/ops/`). Nothing stops the
next person — or the next me — from adding one more `log_event` call to a
router body, and in a year the layer is back where it started. So each router
is listed here as either CONVERTED or NOT, and a converted one is not allowed
to contain the three things that mark a mutation living in the wrong place:

    log_event(        writing history from the transport layer
    source="web"      the History badge hardcoded, so the same code path
                      cannot be reached by a script or the CLI
    HTTPException(    a refusal only an HTTP caller can catch

`PENDING` is empty: the extraction is done, and this test is now the permanent
guard rather than a burndown list. `OUT_OF_SCOPE` names the routers that hold
no library writes at all — read-only ones, and the ones about machine state
(jobs, models, training, deployment), which the Python API deliberately omits
for the same reason.

Read endpoints may still raise `HTTPException` — a 404 for an unknown id on a
GET is transport, not logic — so `TRANSPORT_HTTP_OK` lists the converted
routers where that is still expected, with the STATUS CODES each may use and
the reason. Per code rather than per router: exempting the whole marker left
twelve of the sixteen converted routers free to raise anything at all, which
is three quarters of the surface the marker exists to watch.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from media_compost.testing import COMMIT_RULE, commit_offenders

UI_PKG = pathlib.Path(__file__).resolve().parents[2] / "media_compost" / "ui"
ROUTERS = UI_PKG / "server" / "routers"

# Routers whose mutation logic now lives in `media_compost/ops/`. Move a name
# here in the same commit that converts it.
CONVERTED: set[str] = {"tags.py", "items.py", "subjects.py", "places.py",
                       "events.py", "faces.py", "captions.py",
                       "groups.py", "relationships.py", "files.py",
                       "sequences.py", "editor.py", "video.py",
                       "artifacts.py", "query.py", "ocr.py", "rankings.py",
                       "tagsets.py", "estimate.py"}

# Converted routers that may still raise `HTTPException`, with the STATUS
# CODES each is allowed and the reason.
#
# The marker exists to catch a REFUSAL that belongs to the logic — "that tag
# name is taken", "you cannot merge an item into itself" — leaking back into
# the transport layer where a script can never catch it. A 404 on a GET and a
# 413 on an oversized body are not that: they are facts about the REQUEST, and
# an ops function has no business deciding one.
#
# It used to exempt the MARKER rather than the codes, which meant twelve of
# the sixteen converted routers were free to raise anything at all: the one
# marker that catches a leaked refusal was unchecked over three quarters of
# the surface it covers. Naming the codes is what makes the exemption say
# what it means — a new 400 in `faces.py` is now a failure, where a 404 on a
# crop that does not exist stays fine.
TRANSPORT_HTTP_OK = {
    "items.py": ({404, 413},
                 "404 on GET /{id}, and the id cap on the bulk-details POST"),
    "captions.py": ({413},
                    "the id cap on the bulk add — a fact about the REQUEST, "
                    "exactly as items.py's is"),
    "events.py": ({404}, "404 on GET /suggestions/{item_id}"),
    "faces.py": ({404},
                 "the crop GET — no such face, or no image behind it"),
    "ocr.py": ({404},
               "the crop GET — no such region, or no image behind it"),
    "groups.py": ({404}, "404 on GET /{id}"),
    "files.py": ({404}, "serving bytes, a thumb or a subtitle stream"),
    "sequences.py": ({404}, "the two sequence GETs"),
    "relationships.py": ({404}, "GET /items/{id}/relationships"),
    "video.py": ({400, 404, 409},
                 "404s on the stills and frame-marker GETs; the 409s that "
                 "refuse a second render or stills run, and the 400 for a "
                 "cutlist that keeps nothing — all three are about the JOB "
                 "QUEUE or the request itself rather than about the library"),
    "artifacts.py": ({404}, "serving an artifact's bytes"),
}

# Routers that will never be converted, and why. Every one of them is either
# read-only or about MACHINE state — jobs, models, training, deployment — which
# is not library data and so is deliberately absent from the Python API too.
#
# This used to be a shrinking list of work left. It is empty of those now: the
# extraction is finished, so a router landing here is a claim that it holds no
# library writes at all, not a promissory note.
OUT_OF_SCOPE = {
    "imports.py": ("the import logic IS `importer.Importer`; this router is "
                   "the background-job wrapper around it"),
    "ml.py": ("job queue and model cache — machine state. Its two library "
              "writes, approving a pending caption and a pending tag "
              "placement, DID convert and call ops directly"),
    "settings.py": "deployment and personal preferences",
    "history.py": "it IS the revert layer — ops' third consumer",
    "metadata.py": "read-only",
    "stats.py": "read-only",
    "tagsort.py": ("the session feed is read-only and the index trigger only "
                   "enqueues a background job — every library write of a tag "
                   "session goes through the assign endpoint in tags.py"),
    "taggrid.py": ("the batch feed is read-only — it scores and sorts, and "
                   "every write of a tag-grid session goes through the assign "
                   "endpoint in tags.py"),
}

# Nothing is waiting to be converted any more. Kept as a named empty set
# rather than deleted, so a future extraction has somewhere to list its work.
PENDING: dict[str, str] = {}

MARKERS = (
    (re.compile(r"\blog_event\("), "writes history from the transport layer"),
    (re.compile(r'source="web"'), "hardcodes the History badge"),
    (re.compile(r"\bHTTPException\("), "raises a refusal only HTTP can catch"),
)


def _statuses(text: str) -> tuple[set[int], int]:
    """The status codes a module's `HTTPException(...)` calls name, and how
    many name none readably.

    Counted per CALL rather than by two independent regexes: a raise wrapped
    across a line break (`HTTPException(\\n    413, ...)`) makes a naive
    "not followed by three digits" lookahead fire on the newline, which is
    how the first version of this reported `items.py` as unreadable.
    """
    codes: set[int] = set()
    bare = 0
    for m in re.finditer(r"\bHTTPException\(", text):
        after = re.match(r"\s*(\d{3})\b", text[m.end():])
        if after:
            codes.add(int(after.group(1)))
        else:
            bare += 1
    return codes, bare


def _router_files() -> list[pathlib.Path]:
    return sorted(p for p in ROUTERS.glob("*.py") if p.name != "__init__.py")


def test_the_router_list_is_complete():
    """A new router must be classified, or it silently escapes the ratchet."""
    known = CONVERTED | set(PENDING) | set(OUT_OF_SCOPE)
    actual = {p.name for p in _router_files()}
    assert actual == known, (
        f"unclassified routers: {sorted(actual - known)}; "
        f"stale entries: {sorted(known - actual)}"
    )


@pytest.mark.parametrize("name", sorted(CONVERTED))
def test_a_converted_router_holds_no_mutation_logic(name):
    text = (ROUTERS / name).read_text(encoding="utf-8")
    found = [f"{name}: {why}" for pattern, why in MARKERS
             if pattern.pattern != r"\bHTTPException\(" and pattern.search(text)]
    assert not found, (
        "\n".join(found)
        + f"\n\n{name} is listed as CONVERTED, so its writes belong in "
        "media_compost/ops/. Move the logic, or take it out of CONVERTED."
    )


@pytest.mark.parametrize("name", sorted(CONVERTED))
def test_a_converted_router_raises_only_TRANSPORT_statuses(name):
    """The other half of the same rule, and the half that had no teeth.

    A converted router may still say "no such id" — that is a fact about the
    request. It may not say "that name is taken", because a script calling the
    op directly could never catch one. So the exemption is per STATUS CODE,
    and a code nobody has justified fails here rather than being waved through
    with the rest of the file.
    """
    text = (ROUTERS / name).read_text(encoding="utf-8")
    raised, bare = _statuses(text)
    allowed, why = TRANSPORT_HTTP_OK.get(name, (set(), ""))
    # An HTTPException raised with no literal status is unreadable from here
    # and is not something any of these do — flag it rather than ignore it.
    assert not bare, (
        f"{name} raises HTTPException with a non-literal status, so this "
        f"check cannot read it. Spell the code out.")
    extra = sorted(raised - allowed)
    assert not extra, (
        f"{name} raises {extra}, which TRANSPORT_HTTP_OK does not allow"
        + (f" (it permits {sorted(allowed)}: {why})" if allowed else
           " — it is not listed there at all")
        + ".\n\nA refusal belongs in ops/ as an OpError, where a script can "
          "catch it and `app.py`'s one handler still maps it to this status. "
          "If it really is a fact about the REQUEST, add the code with a "
          "reason.")


def test_the_transport_exemptions_are_all_still_used():
    """A stale exemption is a hole nobody knows is open.

    `subjects.py` and `places.py` were both listed as raising an
    `HTTPException` — a 500-id cap and a part-kind guard — and neither raises
    one at all any more (`places.py` does not even use the import). Both were
    silently permitting anything a future edit might add.
    """
    unused = []
    for name, (allowed, _why) in TRANSPORT_HTTP_OK.items():
        raised, _bare = _statuses((ROUTERS / name).read_text(encoding="utf-8"))
        gone = sorted(allowed - raised)
        if gone:
            unused.append(f"{name}: {gone} no longer raised")
    assert not unused, (
        "these exemptions have outlived what they excused:\n  "
        + "\n  ".join(unused)
        + "\n\nTake them out — an exemption for a status nothing raises is a "
          "hole held open for the next edit to fall into.")


def test_the_ratchet_only_ever_tightens():
    """A router cannot be in both lists, and the pending list cannot grow a
    name that was already converted."""
    assert not (CONVERTED & set(PENDING)), sorted(CONVERTED & set(PENDING))
    assert not (CONVERTED & set(OUT_OF_SCOPE)), \
        sorted(CONVERTED & set(OUT_OF_SCOPE))


def test_nothing_below_the_server_imports_it():
    """The layering, asserted rather than assumed.

    `ops/`, `library/` and the core modules must never import from `server/`.
    That direction is what the extraction exists to remove, and it grows back
    silently: `library/handles.py` reached into `server/routers/items.py` for
    `_taken` — the one read the public API could not compute itself — so the
    Python API depended on a FastAPI request handler, exactly the way
    `facevec.py` once depended on the settings router.

    (`media-compost serve` still names the app by STRING for uvicorn — a
    runtime reference rather than an import — but that lives in core's
    `cli.py` now, outside this walk; the core boundary test records it.)
    """
    root = pathlib.Path(__file__).resolve().parents[2] / "media_compost" / "ui"
    pattern = re.compile(
        r"^\s*(?:from|import)\s+\.*(?:media_compost\.ui\.)?server\b"
        r"|^\s*from\s+\.+server\b", re.M)
    offenders = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if rel.parts[0] == "server":
            continue
        for line in pattern.findall(path.read_text(encoding="utf-8")):
            offenders.append(f"{rel}: {line.strip()}")
    assert not offenders, (
        "these import from server/, inverting the layering:\n  "
        + "\n  ".join(offenders)
        + "\n\nMove what they need down into ops/ or a core module."
    )


def test_the_apps_own_ops_never_commit():
    """The same rule core's `test_ops_context.py` applies to
    `media_compost/ops/`, over the two ops modules that live with the app —
    plus `editor.py`, whose writers are invoked only through them and where a
    commit evaded the core sweep for exactly that reason once.

    The SCAN is shared (`testing.commit_offenders`); only the paths differ.
    The two used to carry a copy each of the regex, the `noqa` escape and the
    message, which is the duplication `ops/` exists to prevent, applied to the
    guard instead of to the code."""
    offenders = commit_offenders(
        sorted((UI_PKG / "ops").rglob("*.py")) + [UI_PKG / "editor.py"])
    assert not offenders, COMMIT_RULE + "\n".join(offenders)

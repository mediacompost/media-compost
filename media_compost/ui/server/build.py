"""Which build of the SPA this server is serving, and whether yours matches.

The app ships as one artifact — the backend serves the bundle out of
`_web_dist` — so "frontend version" and "server version" are the same question,
and the honest answer is already written down: the content-hashed entry bundle
`index.html` names. A browser reads it off its own `<script>` tag, this reads
it out of the same file, and the two strings are equal exactly when the tab is
running the JavaScript this process would hand out.

**Derived, never declared.** `FastAPI(version=...)` read `0.1.0` from the first
commit until the 1.0 release, which is what a hand-bumped version number always
converges to — nobody remembers, so a check keyed on one silently stops
checking. (It follows `media_compost.__version__` now, so it cannot drift from
the distribution again; it still moves once a release rather than once a build,
which is why it could never answer this question.) A hash nobody types cannot
rot.

**It FAILS OPEN, everywhere.** No `_web_dist` (a dev server, a source checkout),
an `index.html` that names no bundle, an unreadable file — every one of those
yields `""`, which means "do not enforce" rather than "reject everything". The
failure this guards is a stale tab making one confusing request; the failure it
must not introduce is a packaging quirk locking a working library out of every
write it has.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

#: The header a client sends to say which build it is, and the server sends
#: back to say which build it is. One name, both directions — a client
#: comparing them is doing exactly what the middleware does.
HEADER = "X-MC-Build"

#: `<script type="module" crossorigin src="/assets/index-BGxEQlGY.js">`.
#: The hash may contain hyphens (`index-B-wWBlGs.js`), so this takes everything
#: up to the extension rather than a character class.
_ENTRY = re.compile(r'<script[^>]+src="([^"]*/index-[^"]+\.js)"')


def read_build_id(web_dist: Path) -> str:
    """The entry bundle's file name, or `""` when there is nothing to compare.

    The whole path is deliberately NOT hashed: the point is to name what the
    browser loaded, and the browser only ever sees this string.
    """
    try:
        html = (web_dist / "index.html").read_text(encoding="utf-8")
    except OSError:
        return ""
    found = _ENTRY.search(html)
    if not found:
        return ""
    return found.group(1).rsplit("/", 1)[-1]


#: The one WRITE a stale page is allowed to make, because it is how the page
#: stops being stale: after a package update the files on disk are new and this
#: process is not, so no reload can help and the banner's button has to be able
#: to reach the server it is asking to restart. Nothing else belongs here — it
#: is gated a second time in the handler, which refuses unless the build on
#: disk really has moved.
STALE_ALLOWED = frozenset({"/api/restart"})


def disk_build_id(web_dist: Path) -> str:
    """What `index.html` names RIGHT NOW, cache bypassed.

    `build_id` answers what this process started with; this answers what a
    browser would be handed if it reloaded. They differ exactly when the
    bundle on disk has been replaced under a running server — a
    `pip install -U`, a `scripts/build.sh`, a swapped container volume — which
    is the state where reloading cannot help, because the page comes back new
    and the process is still old.
    """
    return read_build_id(web_dist)


def restart_required(web_dist: Path) -> bool:
    """True when the files on disk have moved on from this process.

    Fails CLOSED on "no answer", like everything else here: an empty disk id
    (no `_web_dist`, a dev server, an unreadable file) is not evidence of an
    update, so it never asks anybody to restart on a hunch.
    """
    disk = disk_build_id(web_dist)
    return bool(disk) and disk != build_id(web_dist)


@lru_cache(maxsize=4)
def build_id(web_dist: Path) -> str:
    """`read_build_id`, cached — this is read on every mutating request.

    Cached for the life of the process rather than watched: a rebuild that
    replaces `_web_dist` under a running server is a development loop, and there
    the browser is on the Vite dev server sending no header at all. The setup
    re-exec (`hub/setup.py: restart_process`) starts a new process, so a build
    applied that way is picked up.
    """
    return read_build_id(web_dist)


#: POSTs that only READ. A stale page may still make these, because refusing
#: them would stop it rendering at all — and a page that cannot draw is a page
#: whose banner nobody reads.
#:
#: They are listed rather than derived because the HTTP method is the wrong
#: signal in this app and there is no right one. `POST /api/items/query` is THE
#: search endpoint (the condition tree is a body, so it could never be a GET),
#: and "takes no `Ctx`" does not mean "reads" either — the training, model and
#: settings routes mutate plenty without one.
#:
#: Default-DENY is what makes the list safe to be a list: a new write is
#: covered the moment it exists, and a new read-only POST left out of it is
#: merely refused for a stale page — annoying, never wrong.
#: `tests/test_frontend_build.py` asserts every path here still exists, so a
#: rename re-arms the block loudly instead of silently.
READ_ONLY_POSTS = frozenset({
    "/api/items/query",       # the search — the only one there is
    "/api/items/groups",      # the grid's section runs, same body as the search
    "/api/items/details",     # the grid's batched per-item detail read
    # The ids of one stretch of the view's order — what a shift+click asks
    # for when the other end has scrolled out of the loaded pages. Same body
    # as the search, and it writes nothing.
    "/api/items/ids",
    # Where one item sits in the view's order — what a bookmark needs to
    # scroll to what it points at. The same body again, and it writes
    # nothing.
    "/api/items/index",
    # The tag-grid overlay's batch feed — the tag-batch session feed's
    # sibling, and a read for the same reason: it scores and sorts, and
    # every write of a session goes through the assign endpoint.
    "/api/taggrid/next",
    # What the open face cluster's pictures say, so its crops can be grouped
    # — the sequence each is in and the tags on it. A POST because a cluster
    # is hundreds of face ids; a READ like `odd-ones-out` beside it.
    "/api/faces/grouping",
    "/api/query/parse",       # pure string <-> tree, touches no session
    "/api/query/serialize",
    # The job editor's "what does each query contribute" preview. A POST
    # because it carries a config, and a pure READ: it resolves the queries
    # and counts, writing nothing. Left out, it 409s on a stale page and the
    # empty-reminder-pool warning silently never appears — which is the third
    # time this list has cost exactly that, after the search and the grid's
    # section runs.
    "/api/train/queries/preview",
    # The tag-batch overlay's session feed: the scope rides in it exactly as
    # the search body does, and it resolves + orders without writing a byte.
    # Its sibling /api/tagsort/index is a WRITE (it enqueues a job) and is
    # deliberately not here.
    "/api/tagsort/next",
    # Settings → Storage's file-prune preview: the RULE rides in the
    # body and it counts what the rule would match, writing nothing.
    # Its sibling /api/library/storage/file-prune is the deletion and is
    # deliberately not here.
    "/api/library/storage/file-prune/preview",
    # The Tags tab's window: a body of ids because a window is a hundred of
    # them, and a pure read. Left out, a stale page draws an empty tag list.
    "/api/tags/rows",
    # "Which of these crops look more like the ones just moved out" — two id
    # lists, so a POST, and an OFFER: it scores and answers, writing nothing.
    "/api/faces/odd-ones-out",
})

#: Read-only POSTs whose path carries a VARIABLE segment, which a set of
#: literal paths cannot name. Same default-deny bargain: each pattern is one
#: named route, never a prefix that would quietly exempt a family.
READ_ONLY_POST_PATTERNS = (
    # The rating overlay's "next pair" — a POST because it carries the
    # session's scope (the search request), and a pure read: it resolves the
    # pool and picks, writing nothing. Left out, a stale page's overlay would
    # 409 on its very first pair.
    re.compile(r"^/api/rankings/\d+/pair$"),
    # The estimate dialog's footer — the same request as the write with the
    # write withheld, run on every edit of a rule. The WRITE is a second
    # path (`/estimate/apply`), which is what lets this one be listed: a
    # stale tab may read the numbers, and the press that stamps the tags is
    # default-denied like everything else.
    re.compile(r"^/api/rankings/\d+/estimate$"),
)


def writes(method: str, path: str) -> bool:
    """Would this request change something?

    Anything but a read is a write until proven otherwise — see
    `READ_ONLY_POSTS` for why the exemptions are named rather than derived.
    """
    if method in ("GET", "HEAD", "OPTIONS"):
        return False
    if path in READ_ONLY_POSTS:
        return False
    return not any(p.match(path) for p in READ_ONLY_POST_PATTERNS)


def is_stale(theirs: str, ours: str) -> bool:
    """Is a caller's build one this server should refuse to take writes from?

    Both empty answers are "no". A caller that sends NOTHING is the CLI, a
    script, `curl`, or a dev-server frontend — none of which have a bundle to
    be stale — and a server that cannot name its own build has nothing to
    compare. Only two present, different strings are a mismatch.
    """
    return bool(theirs) and bool(ours) and theirs != ours

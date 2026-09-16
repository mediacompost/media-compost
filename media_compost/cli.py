"""Command-line entry point: ``media-compost serve | import |
merge-library | migrate | prune-storage``.

``merge-library`` was ``restore-library`` (and before that ``import-folder``),
renamed with what it reads: another LIBRARY's folder — its ``media.db``
directly — folded item by item into the current one. The old names are simply
gone rather than kept as aliases: a script that still says one gets
``invalid choice`` and the list of real commands, which is the loud kind of
failure.

There were four BACKFILL commands here too — ``reindex-metadata``,
``reindex-frames``, ``backfill-phashes`` and ``backfill-colors`` — each the
one-off repair for a library written before some derived column or index
existed. They are gone. What they leave behind is a real gap and it is
written down rather than papered over: a library from before those columns
opens and works, but its colour sort, its ``COLORLIKE:`` searches, its
metadata search index and its frame index stay as that older build left them,
and re-importing the same files does NOT rebuild them (an exact duplicate is
recognised and stored again nowhere). The values are all derived, so nothing
is WRONG — only absent.

``serve`` is the ONE sanctioned crossing of the core→app boundary, and it
crosses by STRING: ``uvicorn.run("media_compost.ui.server.app:app", …)`` is a
runtime reference the import-boundary walk deliberately does not see, every
import it needs is deferred into the command body, and on an install without
``[full]`` it refuses with the install line — so ``import media_compost.cli``
stays exactly as light as the base install promises. (It was a separate
``media-compost-ui`` script for a while, on the argument that the library's
CLI should name the app nowhere at all; one tool won.)

argparse, deliberately. It was typer, which bought authoring convenience at
the price of two base dependencies (typer and the click it brings) in an
install that advertises how few it needs; the parsing here is subcommands
with plain options, which is exactly what the stdlib does. ``rich`` stays —
it is what draws the output, not what parses the arguments.

Shares the exact same importer core as the web backend, so a bulk CLI import
produces an identical library to a UI import.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Callable, Optional

import sys

from rich.cells import cell_len
from rich.console import Console
from rich.markup import escape

from .config import Config
from .db import Database, Group, LibraryVersionError
from .importer import SEQUENCE_GROUPINGS, Importer, ImportOptions
from .storage import ItemStore


def _tolerate_unprintable_names() -> None:
    """Never let a FILE NAME kill the import that is reading it.

    The progress line prints the name of the file being imported, and a name
    is data off somebody's disk — it may hold anything Unicode does. On
    Windows the standard streams default to the LOCALE encoding (cp1252 on a
    Western install), so `rich` encoding that line raised UnicodeEncodeError
    and took the whole run down with it: measured here, a folder of 41
    pictures imported 38 and then died on a PDF with a Japanese title, with a
    traceback through the progress printer and nothing saying that the FAILURE
    WAS THE DISPLAY rather than the file. The bytes were fine; nobody could
    say so on this console.

    `errors="replace"` rather than forcing UTF-8: a genuine cp1252 console
    cannot show those characters however they are encoded, and forcing the
    encoding turns "cannot display" into mojibake on every OTHER name too.
    A "?" is the honest answer for one line of progress. Wrapped in a
    try/except because this is a nicety — a stream that cannot be
    reconfigured (already wrapped, or replaced by a test harness) must not be
    the new way the CLI fails to start.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, OSError, ValueError):
            pass


_tolerate_unprintable_names()

console = Console()


def _one_line(count: int, name: str) -> str:
    """One progress line that OVERWRITES the last one, whatever the two are.

    ``end="\r"`` returns the cursor to column 0 and erases nothing, so a
    short name printed after a long one left the tail of the long one on
    screen for the rest of the run — and a name wider than the terminal
    WRAPPED, after which the carriage return went to the start of the last
    row and everything above it stayed for good.

    So the line is cut to the terminal's width and then padded back out to
    it: cut so it cannot wrap, padded so it cannot leave anything behind.

    The cut takes the FRONT of a long name, because what is worth reading in
    ``a/very/deep/path/page-012.png`` is the end of it.

    Widths are CELLS, not characters: the names this prints are data off
    somebody's disk, and a CJK title is two columns per character — measured
    in `len()` it would be cut to half the terminal and padded to twice it,
    which is the same debris by another route.
    """
    width = max(20, console.width) - 1
    head = f"{count:>6} "
    room = width - cell_len(head)
    if cell_len(name) > room:
        # Trim from the left until it fits, then say that it was trimmed.
        while name and cell_len(name) > room - 1:
            name = name[1:]
        name = "…" + name
    line = head + name
    return line + " " * max(0, width - cell_len(line))


def _print_progress(count: int, name: str) -> None:
    """…and print it. `escape`, because a NAME IS DATA: rich reads square
    brackets as markup, and `[HorribleSubs] ep01.mkv` is an ordinary file
    name that would otherwise be swallowed or raise out of the progress
    printer — the failure `_tolerate_unprintable_names` records, one class
    along."""
    line = _one_line(count, name)
    console.print(f"[dim]{line[:6]}[/dim]{escape(line[6:])}",
                  end="\r", highlight=False, markup=True, soft_wrap=True)


def _prune_progress() -> Callable[[int, str], None]:
    """The prune sweep's reporter: how much has gone, and where it is looking.

    Sweeping is per-FOLDER work and each folder is a directory listing, so the
    events arrive orders of magnitude faster than an import's per-file ones —
    a print each would make the printing the slow half of the command. So it
    is throttled to a readable rate and the count carries the meaning: what
    the line is for is saying that a long sweep of a large library is still
    moving.
    """
    last = 0.0

    def report(removed: int, where: str) -> None:
        nonlocal last
        now = time.monotonic()
        if now - last < 0.05:
            return
        last = now
        _print_progress(removed, where)

    return report


def _open_library(data_dir: Optional[Path]) -> tuple[Config, Database, ItemStore]:
    cfg = Config(data_dir=data_dir.resolve()) if data_dir else Config()
    try:
        db = Database(cfg)
    except LibraryVersionError as e:
        # The one refusal worth a sentence rather than a traceback: it is the
        # message that stops somebody re-running the command until it works.
        console.print(f"[red]{e}[/red]")
        raise SystemExit(2) from None
    store = ItemStore(cfg)
    return cfg, db, store


def _resolve_parent_group(session, name: Optional[str],
                         group_id: Optional[int] = None) -> Optional[int]:
    """The group everything imported goes under: by NAME (created when there
    is none) or by ID.

    Two ways in because a name is not an identity here — `Group.name` is
    indexed and NOT unique, so a library can hold "abc" inside "abc" and a
    name cannot say which was meant. `--parent-group` stays the readable one
    (and the portable one: it makes the group when it is missing), and
    `--parent-group-id` is what the app's own suggested command uses when the
    name it would print is ambiguous. An id must EXIST — inventing a group
    with a chosen id is not a thing — so a stale one is refused by name
    rather than silently importing into the wrong place."""
    from sqlalchemy import select

    if group_id is not None:
        if session.get(Group, group_id) is None:
            raise SystemExit(f"no group with id {group_id} in this library")
        return group_id
    if not name:
        return None

    gid = session.execute(
        select(Group.id).where(Group.name == name)
    ).scalars().first()
    if gid is None:
        g = Group(name=name, icon="folder")
        session.add(g)
        session.flush()
        gid = g.id
    return gid


def _cmd_import(args: argparse.Namespace) -> None:
    """Import large numbers of files, deduplicating as it goes."""
    cfg, db, store = _open_library(args.data_dir)
    with db.session() as s:
        parent_id = _resolve_parent_group(s, args.parent_group,
                                          args.parent_group_id)
        s.commit()

        last = {"name": ""}

        def on_progress(stats, name):
            processed = (
                stats.imported + stats.skipped_duplicate
                + stats.added_alternative + stats.ignored
            )
            _print_progress(processed, name)
            last["name"] = name

        imp = Importer(s, store, cfg, on_progress=on_progress)
        stats = imp.import_paths(args.paths, ImportOptions(
            parent_group_id=parent_id,
            new_group=args.new_group or bool(args.new_group_name.strip()),
            new_group_name=args.new_group_name,
            folders_as_groups=args.folders_as_groups,
            recursive=args.recursive,
            archives_as_groups=args.archives_as_groups,
            sequence_grouping=args.sequence_grouping,
            archive_sequences=args.archive_sequences,
            min_megapixels=args.min_megapixels,
            min_short_edge=args.min_short_edge,
            min_long_edge=args.min_long_edge,
            min_aspect=args.min_aspect,
            max_aspect=args.max_aspect,
            ignore_kinds=tuple(
                k for k in (args.ignore_kinds or "").split(",") if k.strip()),
            tags_existing=args.tag_existing,
            tags=tuple(args.tag),
            tags_image=tuple(args.tag_image),
            tags_video=tuple(args.tag_video),
            tags_sequence=tuple(args.tag_sequence),
        ))
        # Record the run in the History log (source="cli").
        from .importer import import_event
        ev = import_event(stats, parent_id)
        if ev is not None:
            from .history import log_event
            log_event(
                s, source="cli", **ev,
            )
            s.commit()

    console.print()
    console.rule("[bold]Import complete")
    console.print(f"  New items        : [green]{stats.imported}[/green]")
    console.print(f"  Alternatives     : [cyan]{stats.added_alternative}[/cyan]")
    console.print(f"  Skipped (dupes)  : [yellow]{stats.skipped_duplicate}[/yellow]")
    if stats.ignored:
        # Only when the run turned something away: a line reading 0 on every
        # ordinary import is a line nobody reads. Its own line rather than
        # folded into the duplicates, which is a different answer — and it no
        # longer says "(small)", since a source is left out for its size, its
        # SHAPE or its type, and the entry beside it says which.
        console.print(f"  Ignored (filters): [yellow]{stats.ignored}[/yellow]")
    console.print(f"  Videos split     : {stats.videos_split} "
                  f"({stats.frames_extracted} frames)")
    console.print(f"  Archives expanded: {stats.archives_expanded}")
    console.print(f"  Groups created   : {stats.groups_created}")
    if stats.errors:
        console.print(f"  [red]Errors: {len(stats.errors)}[/red]")
        for e in stats.errors[:10]:
            console.print(f"    [red]- {e}[/red]")


def _cmd_prune_storage(args: argparse.Namespace) -> None:
    """Sweep stray files inside item folders, folders of deleted items, and
    orphaned thumbnails. The database is the record; this makes the disk
    agree with it."""
    _cfg, db, store = _open_library(args.data_dir)
    with db.session() as s:
        removed = store.prune_all(s, on_progress=_prune_progress())
    console.print()
    console.rule("[bold]Storage prune complete")
    console.print(f"  Pruned entries   : [yellow]{removed}[/yellow]")


def _cmd_migrate(args: argparse.Namespace) -> None:
    """Bring a library's format up to what this build writes.

    Opening a library upgrades it anyway — this command is for doing it
    deliberately: with the server down, before a big import, or from an update
    script that wants to know first.

    ``--check`` and ``--dry-run`` must NOT go anywhere near ``_open_library``:
    constructing a ``Database`` is what performs the upgrade, so the two
    read-only modes would perform the very thing they claim to be reporting
    on. They read the header off the file directly instead.
    """
    import os

    from . import migrations

    cfg = Config(data_dir=args.data_dir.resolve()) if args.data_dir else Config()
    if args.check or args.dry_run:
        found = migrations.inspect(cfg.db_path)
        if not found.exists:
            console.print(f"[dim]No library at {cfg.db_path} yet — one will be "
                          f"created at format {found.current}.[/dim]")
            raise SystemExit(0)
        if found.problem:
            console.print(f"[red]{cfg.db_path}: {found.problem}[/red]")
            raise SystemExit(0 if args.dry_run else 2)
        if found.up_to_date:
            console.print(f"[green]Up to date[/green] — format "
                          f"{found.current}.")
            raise SystemExit(0)
        console.print(f"Format [yellow]{found.found}[/yellow] → "
                      f"[green]{found.current}[/green], "
                      f"{len(found.plan)} step(s):")
        for m in found.plan:
            console.print(f"  [dim]{m.version}[/dim]  {m.summary}")
        for line in migrations.advice_for(found.plan):
            console.print(f"  [yellow]afterwards:[/yellow] {line}")
        raise SystemExit(0 if args.dry_run else 1)

    if args.no_backup:
        os.environ[migrations.SKIP_BACKUP_VAR] = "1"
    before = migrations.inspect(cfg.db_path)
    # Opening it IS the upgrade — the printing happens inside `_run_ladder`,
    # so that a server start and this command say the same things in the same
    # order.
    _cfg, db, _store = _open_library(args.data_dir)
    db.engine.dispose()
    if before.up_to_date or not before.exists:
        console.print(f"[green]Nothing to do[/green] — format "
                      f"{migrations.CURRENT}.")


def _cmd_merge_library(args: argparse.Namespace) -> None:
    """Merge every item of ANOTHER library folder into this one.

    The source is a complete library — its ``media.db`` is read directly and
    file bytes are copied out of its item folders. Items already present
    (same uid) are skipped, visually/byte-matching ones are merged,
    everything else is created preserving its uid; the source's tag set
    (tags with their implications and aliases, groups with their tree,
    subjects, places, events, rankings) is get-or-created first, existing
    definitions winning. Idempotent: re-running is a no-op. The source is
    opened read-only and must already be at this build's format — open it
    once with this build to upgrade it first.

    Named apart from ``import`` on purpose: that one takes pictures from
    anywhere and adds them, this one takes a library and folds it in.
    """
    from .libimport import merge_library

    cfg, db, store = _open_library(args.data_dir)
    with db.session() as s:
        stats = merge_library(s, store, cfg, args.path, dry_run=args.dry_run)
    console.rule("[bold]Library merge "
                 + ("(dry run) " if args.dry_run else "") + "complete")
    console.print(f"  Items scanned : {stats.scanned}")
    console.print(f"  Created       : [green]{stats.created}[/green]")
    console.print(f"  Merged        : [cyan]{stats.merged}[/cyan]")
    console.print(f"  Skipped (uid) : [yellow]{stats.skipped}[/yellow]")
    console.print(f"  Files added   : {stats.files_added}")
    if stats.errors:
        console.print(f"  [red]Errors: {len(stats.errors)}[/red]")
        for e in stats.errors[:10]:
            console.print(f"    [red]- {e}[/red]")


# Dataset export has been removed in favor of the Python API — write a small
# script with ``media_compost.open_library(...).query(...)`` to select items
# and export them however you like (see docs/python-api.md). This keeps the
# query grammar in one place (the frontend / the structured condition tree)
# rather than a second string parser on the backend.


# ---------------------------------------------------------------------------
# serve — the web app (folded in from the retired `media-compost-ui` script).


def _port_free(host: str, port: int) -> bool:
    """Whether starting a server here would land on top of another one.

    Checked BEFORE the browser thread starts: a taken port used to open a tab
    over whatever OTHER application was living there, with uvicorn's traceback
    arriving underneath it.

    **CONNECTING is the question; binding was the wrong one, and on Windows it
    could not answer at all.** This used to probe the way uvicorn binds —
    `SO_REUSEADDR`, so a socket lingering in TIME_WAIT does not read as taken
    — and that option does not mean the same thing on both platforms. On POSIX
    it permits exactly the TIME_WAIT case. On Windows it permits binding on
    top of a LIVE LISTENER, which is POSIX's `SO_REUSEPORT`: so the probe
    bound successfully beside the running server and reported the port free,
    every time. The refusal above never fired there, which is the whole of
    what it exists for.

    Binding cannot be repaired by dropping the option, either, because uvicorn
    sets it unconditionally — so on Windows "can uvicorn bind" is genuinely
    YES while another server is listening, and answering that question
    faithfully still opens a browser tab over somebody else's app. The
    question worth asking is the one the error message already asks: is
    something LISTENING there. A connect answers it identically on every
    platform, and a TIME_WAIT socket — the case the option was for — accepts
    no connection, so it correctly reads as free.

    A bind probe stays as the second half, for a port BOUND BUT NOT LISTENING
    (which refuses connections yet would still fail uvicorn's own bind on
    POSIX). It keeps `SO_REUSEADDR` only where that means what it says.
    """
    import socket

    try:
        family, kind, proto, _, addr = socket.getaddrinfo(
            host, port, type=socket.SOCK_STREAM)[0]
    except OSError:
        return True   # unresolvable host — let uvicorn report that itself

    # Is anybody listening? A refused connection is the answer we want, and it
    # comes back immediately on a local address; the timeout is for a host that
    # silently drops instead (a filtered address), where waiting buys nothing.
    with socket.socket(family, kind, proto) as s:
        s.settimeout(0.25)
        try:
            s.connect(addr)
        except OSError:
            pass          # nothing accepted — fall through to the bind probe
        else:
            return False

    if sys.platform == "win32":
        # Every remaining case is one Windows cannot distinguish: its bind
        # would succeed regardless. Nothing answered, so nothing is serving.
        return True
    with socket.socket(family, kind, proto) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(addr)
        except OSError:
            return False
    return True


def _open_when_ready(url: str, stop) -> None:
    """Open the browser once THIS server answers its own health check.

    What ran before was a one-second timer, and it opened a tab onto
    whatever the port held at that moment. A cold start imports the whole
    backend before it binds — longer than any guessed delay — so the tab
    could land on a dead port and render the browser's stale cache of
    whichever app last lived there: an empty page, 404-ing against routes
    this server never had, that a reload "fixes". So: poll `/api/health`,
    require THIS app's shape (`ok` plus `schema_version` — a stranger on
    the port gets no tab), and give up the moment `stop` is set, which
    `serve` does as soon as uvicorn returns for any reason.

    THERE IS NO DEADLINE, and there used to be one: sixty seconds, after
    which the thread quietly gave up. A schema upgrade runs inside the
    server's startup — the backup alone is a `VACUUM INTO` of the whole
    library, then the rungs — and uvicorn accepts no connection until that
    startup is over, so on any library big enough to take longer than a
    minute the tab `serve --open` was asked for simply never appeared, with
    nothing printed to say why. The deadline guarded a server that never
    comes up, and `stop` already covers the one shape of that which matters
    (uvicorn returned); a process still starting is one worth waiting for,
    and the thread is a daemon, so it costs nothing when the process ends."""
    import json
    import urllib.request
    import webbrowser

    while not stop.is_set():
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=1) as r:
                data = json.load(r)
        except (OSError, ValueError):
            stop.wait(0.25)
            continue
        if data.get("ok") is True and "schema_version" in data:
            webbrowser.open(url)
        return


def _cmd_serve(args: argparse.Namespace) -> None:
    """Run the local web app."""
    import os
    import threading

    # Entry points install with the distribution whatever the extras, so this
    # command exists on a base-only install too — where the right answer is
    # the install line, not a ModuleNotFoundError traceback. Every import the
    # app needs is deferred to here for the same reason.
    try:
        import uvicorn
    except ImportError:
        # `escape`, for the reason `_print_progress` gives one class along:
        # rich reads `[full]` as a STYLE TAG and swallows it, so the line the
        # person on a base install was handed read `pip install
        # 'media-compost'` — the command that installs what they already have.
        # `soft_wrap`, because rich's own wrap puts a REAL newline in: at 80
        # columns the line breaks after "pip install", and a command copied
        # out of it pastes as two, the second of which is not a command.
        console.print("the app needs its dependencies — install them with: "
                      + escape("pip install 'media-compost[full]'"),
                      soft_wrap=True)
        raise SystemExit(1) from None

    if not _port_free(args.host, args.port):
        console.print(
            f"[red]port {args.port} on {args.host} is already in use[/red] — "
            f"another server (or another Media Compost) is listening there. "
            f"Pick a different port with --port, or stop the other process "
            f"first.")
        raise SystemExit(1)

    if args.data_dir:
        os.environ["MEDIA_COMPOST_DATA"] = str(args.data_dir.resolve())

    # The library lock, taken HERE rather than left to the startup hook — for
    # the same reason the port is probed above, and with the same shape. The
    # app takes it in a FastAPI lifespan, so a library another server holds
    # surfaced as an unhandled exception inside uvicorn: five frames of
    # traceback, "Application startup failed", and the carefully written
    # sentence — which names the other server's pid, when it started and what
    # it is serving — as the last line of it. `LibraryVersionError` is already
    # spared that a few lines up, on the same reasoning.
    #
    # Taking it early is free rather than merely harmless: a lease is
    # idempotent per process, so the hook's own call finds it held and does
    # nothing, and the kernel drops it on any exit at all.
    from . import instance
    try:
        instance.acquire_server_lock(Config().data_dir)
    except instance.AnotherServerRunning as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1) from None

    stop = threading.Event()
    if args.open_browser:
        threading.Thread(target=_open_when_ready,
                         args=(f"http://{args.host}:{args.port}", stop),
                         daemon=True).start()
    try:
        # The app named by STRING — a runtime reference for uvicorn, and the
        # one sanctioned crossing of the core→app boundary (see the module
        # docstring; the import-boundary test records it too).
        uvicorn.run("media_compost.ui.server.app:app",
                    host=args.host, port=args.port)
    finally:
        stop.set()


# ---------------------------------------------------------------------------
# The parser. One subparser per command; each function's docstring is its
# --help text, so the two cannot drift.


def _add_data_dir(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--data-dir", type=Path, default=None, metavar="PATH",
                    help="Library data directory (default: MEDIA_COMPOST_DATA, "
                         "else ./_data).")


def _sub(subparsers, name: str, func,
         interrupted: str = "") -> argparse.ArgumentParser:
    """Register a subcommand.

    ``interrupted`` is the sentence Ctrl+C prints after "Interrupted." — what
    is left behind, in this command's own terms. It rides on the parser as a
    DEFAULT rather than in a table keyed by command name, so the answer sits
    beside the command it is about and a new command cannot inherit another
    one's claim by omission (no sentence means the bare word, which is at
    least never wrong).
    """
    doc = (func.__doc__ or "").strip()
    # The command list shows the docstring's first SENTENCE, not its first
    # physical line — a wrapped sentence cut at the line break reads as
    # "...on-disk data the database no longer".
    first = " ".join(doc.split("\n\n")[0].split())
    short = first.split(". ")[0].rstrip(".") + "."
    sp = subparsers.add_parser(
        name, help=short, description=doc,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sp.set_defaults(func=func, interrupted=interrupted)
    return sp


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="media-compost",
                                description="Media Compost CLI")
    sub = p.add_subparsers(metavar="COMMAND", required=True)

    sp = _sub(sub, "serve", _cmd_serve,
              "The server is stopped.")
    sp.add_argument("--host", default="127.0.0.1")
    sp.add_argument("--port", type=int, default=8000)
    # OPT-IN, deliberately: the terminal that runs `serve` usually belongs to
    # somebody who already has (or does not want) a tab — a browser stealing
    # focus on every restart was the complaint. `--no-open` stays accepted so
    # older invocations keep meaning what they said.
    sp.add_argument("--open", dest="open_browser", default=False,
                    action=argparse.BooleanOptionalAction,
                    help="Open the browser once the server is up "
                         "(off unless asked).")
    _add_data_dir(sp)

    # An import commits every 20 files (and each file releases its own
    # savepoint), so what has been counted is in the library; only the chunk
    # in flight is lost.
    sp = _sub(sub, "import", _cmd_import,
              "Everything imported before this is in the library.")
    sp.add_argument("paths", nargs="+", type=Path,
                    help="Files or folders to import.")
    parent = sp.add_mutually_exclusive_group()
    parent.add_argument("-g", "--parent-group", default=None, metavar="NAME",
                        help="Attach imports under this group, created if "
                             "there is none by that name.")
    parent.add_argument("--parent-group-id", default=None, type=int,
                        metavar="ID",
                        help="Attach imports under the group with this id — "
                             "what to use when a NAME would be ambiguous "
                             "(two groups may share one).")
    # A box of this run's own, INSIDE whatever --parent-group names. Two
    # flags rather than one optional-argument flag: `--new-group NAME` with
    # `nargs="?"` sits in front of a `nargs="+"` positional, so
    # `--new-group photos/` would silently eat the path instead of importing
    # it. Naming one implies the other, so the common case is one flag.
    sp.add_argument("--new-group", default=False,
                    action=argparse.BooleanOptionalAction,
                    help="Put this run's items in a group of their own, "
                         "inside the parent group.")
    sp.add_argument("--new-group-name", default="", metavar="NAME",
                    help="What to call it (implies --new-group). Default: "
                         "the date and time the run started.")
    sp.add_argument("--folders-as-groups", default=True,
                    action=argparse.BooleanOptionalAction,
                    help="Recreate folder structure as nested groups.")
    sp.add_argument("--recursive", default=True,
                    action=argparse.BooleanOptionalAction,
                    help="Descend into subfolders.")
    sp.add_argument("--archives-as-groups", default=False,
                    action=argparse.BooleanOptionalAction,
                    help="Give each archive its own group (else contents go "
                         "to its parent).")
    sp.add_argument("--sequence-grouping", default="both",
                    choices=SEQUENCE_GROUPINGS, metavar="WHICH",
                    help="Which half of a sequence (a comic, a PDF, an "
                         "animated GIF) joins the run's groups: both (the "
                         "default), container (the sequence alone) or "
                         "members (the items inside it alone).")
    sp.add_argument("--archive-sequences", default=False,
                    action=argparse.BooleanOptionalAction,
                    help="Make sequences from (non-comic) archive contents.")
    # The Storage page's file-prune rule, read the other way round: three
    # minimums a file must clear, 0 for "not set". Same three questions, the
    # same words for them.
    sp.add_argument("--min-resolution", dest="min_megapixels", type=float,
                    default=0.0, metavar="MP",
                    help="Ignore pictures and videos under this many "
                         "megapixels (0: no minimum).")
    sp.add_argument("--min-short-edge", type=int, default=0, metavar="PX",
                    help="Ignore anything under this many pixels on its "
                         "shorter side.")
    sp.add_argument("--min-long-edge", type=int, default=0, metavar="PX",
                    help="Ignore anything under this many pixels on its "
                         "longer side. A sequence is kept whole — it is "
                         "imported when any page clears the minimums.")
    # A RANGE where the three above are minimums, and width/height throughout
    # — 1.0 square, 0.5 twice as tall as wide, 2.0 twice as wide as tall. Each
    # end stands alone, so "no panoramas" is `--max-aspect 2` by itself.
    sp.add_argument("--min-aspect", type=float, default=0.0, metavar="W/H",
                    help="Ignore anything narrower than this width-to-height "
                         "ratio (0.5 is twice as tall as it is wide).")
    sp.add_argument("--max-aspect", type=float, default=0.0, metavar="W/H",
                    help="Ignore anything wider than this width-to-height "
                         "ratio (2 is twice as wide as it is tall). A "
                         "sequence is kept whole — it is imported when any "
                         "page clears the filters.")
    sp.add_argument("--ignore-kinds", default="", metavar="LIST",
                    help="Comma-separated file types to leave alone: image, "
                         "video, sequence (a PDF, an animated GIF or a comic), "
                         "archive (a zip that scatters into items).")
    # The web import's Tags card, in flags. Repeatable rather than
    # comma-separated: a tag name cannot hold a space but nothing stops one
    # holding a comma, and this is the field a booru dump is pasted into.
    # SPELL A NEGATIVE WITH `=`: `--tag=-blurry`. A leading "-" is an option
    # to argparse wherever the value is a separate word, so `--tag -blurry`
    # is a parse error rather than a negative assignment.
    sp.add_argument("--tag", action="append", default=[], metavar="NAME",
                    help="Tag everything the run CREATES (repeatable). "
                         "`--tag=-name` assigns it negatively.")
    sp.add_argument("--tag-image", action="append", default=[], metavar="NAME",
                    help="Tag only the images the run creates.")
    sp.add_argument("--tag-video", action="append", default=[], metavar="NAME",
                    help="Tag only the videos the run creates.")
    sp.add_argument("--tag-sequence", action="append", default=[],
                    metavar="NAME",
                    help="Tag only the sequence containers the run creates.")
    sp.add_argument("--tag-existing", default=True,
                    action=argparse.BooleanOptionalAction,
                    help="Also tag items the run MATCHED rather than created "
                         "(a duplicate, a near-dup fold).")
    _add_data_dir(sp)

    # The whole merge is ONE transaction — nothing is committed until the
    # last item — so an interrupted one leaves the library exactly as it was.
    sp = _sub(sub, "merge-library", _cmd_merge_library,
              "Nothing was merged — the library is as it was.")
    sp.add_argument("path", type=Path,
                    help="Another library folder (holding media.db and "
                         "items/) whose items are merged into this one.")
    sp.add_argument("--dry-run", action="store_true",
                    help="Report what would happen without writing.")
    _add_data_dir(sp)

    # Each step stamps the library as its last statement, so an interrupted
    # one rolls back whole and the version still names the step before it.
    sp = _sub(sub, "migrate", _cmd_migrate,
              "The library is at the last step that finished — run migrate "
              "again to carry on.")
    sp.add_argument("--check", action="store_true",
                    help="Report only, for scripts: exit 0 up to date, 1 "
                         "upgrade pending, 2 unopenable.")
    sp.add_argument("--dry-run", action="store_true",
                    help="Print what would run and change nothing. Always "
                         "exits 0.")
    sp.add_argument("--no-backup", action="store_true",
                    help="Skip the pre-upgrade backup. If the upgrade goes "
                         "wrong the library cannot be put back.")
    _add_data_dir(sp)

    sp = _sub(sub, "prune-storage", _cmd_prune_storage,
              "Files swept before this are gone; the database was not "
              "touched.")
    _add_data_dir(sp)

    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.func(args) or 0
    except KeyboardInterrupt:
        # Ctrl+C is somebody ANSWERING, not a crash: a traceback through
        # whatever frame the interrupt landed in says nothing they did not
        # already know, and it buries the one thing they do want to hear —
        # what the work up to here left behind.
        #
        # And that answer is PER COMMAND: it read "Everything imported before
        # this is in the library" whatever had been running, which is wrong in
        # both directions — a merge is one transaction and keeps nothing, a
        # prune deletes files and imports nothing at all. Each command carries
        # its own sentence (see `_sub`), and a command with none says only the
        # word, rather than another command's promise.
        #
        # A NEWLINE FIRST, because a progress line ends in a carriage return
        # with the cursor parked at column 0 — without it this sentence would
        # be written over the name it is about.
        console.print()
        tail = getattr(args, "interrupted", "")
        console.print("[yellow]Interrupted.[/yellow]"
                      + (f" {tail}" if tail else ""))
        # 130 is what a shell reports for a command ended by SIGINT, and what
        # `set -e` and a CI step read as "cancelled" rather than "failed".
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

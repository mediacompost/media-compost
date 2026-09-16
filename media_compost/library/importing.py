"""Bringing files into the library.

`Importer` already does the work — dedup, near-duplicate detection, EXIF,
places from GPS, rotation detection, archives, sequences. This is the handle-
shaped face of it, and the one thing it adds is an ANSWER: what each source
turned out to be, as handles, so a script that just imported one picture can
go on to say something about it without searching the library for what it
did a moment ago.

The shape for anything more than a file or two is ONE RUN — the importer
commits on its own cadence, and the whole run is one History entry (one
revert). A crawler feeding downloads straight from memory looks like this:

    from collections import deque
    from media_compost import ImportBytes, open_library

    pending, urls, tags = deque(), [], []

    def sources():
        for body, name, url, when, site in downloads():
            pending.append((url, when, site))
            yield ImportBytes(data=body, name=name)

    with open_library(path) as lib:
        with lib.importing() as run:
            for got in run.add_many(sources()):
                url, when, site = pending.popleft()
                if not got:
                    print("failed:", got.error)
                    continue
                urls += [(f, url, when) for f in got.files]
                tags += [(it, site) for it in got.all_items]
                if len(urls) >= 500:
                    lib.add_file_urls(urls); urls.clear()
                    lib.assign_tags(tags); tags.clear()
            lib.add_file_urls(urls)
            lib.assign_tags(tags)

An `ImportBytes` is a pure stand-in for a file — data plus a name — and the
provenance is recorded OFF THE RESULT, through the bulk ops
(`Library.add_file_urls`, `Library.assign_tags`; a few hundred rows to a
transaction costs about what the importer's own batching would). The two
walks are the whole trick: ``got.files`` is every stored file the source's
bytes went into — the existing file for a duplicate, one per page for a
book, never a derived frame — and ``got.all_items`` every item it produced
or landed on, a book's sequence container included. Nothing reads the
result's shape by hand, which is where the mistakes lived.

The shape itself is `ImportResult` → flat ``entries`` → ``children``, fixed
at that depth however deeply an archive nests: one result per source, one
entry per file-shaped thing it contained, one child per page or matched
frame. `ImportEntry` says the rules (and the one content rule that keeps
the depth fixed: a book inside a book is a flat sibling entry, never a
member of the outer sequence).

When the sources can be listed up front, [`ImportRun.add_many`]
[media_compost.library.importing.ImportRun.add_many] reads, decodes and
hashes upcoming sources on worker threads while the serial half works, and
yields the same per-source results. It can use worker PROCESSES instead,
which a caller asks for explicitly — see `ImportRun.add_many` for the guard
that requires and what it is worth.
"""

from __future__ import annotations

import enum
import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Optional

from ..dedup_index import ThumbLRU
from ..importer import (ImportBytes, ImportOptions, Importer,
                        ImportSource, ImportStats, prepare_source,
                        prepare_source_slim, worth_prefetching)
from ..history import log_event
from .errors import ReadOnlyError


#: How much SOURCE data the in-flight window may hold. A queued slot keeps
#: its source alive, and an `ImportBytes` source is its whole body — so the
#: window is bounded in bytes as well as slots, or a run of films would
#: park gigabytes between the caller and the import. The same reasoning,
#: and the same figure, as a crawl reader's own hand-off buffer.
WINDOW_BYTES = 256 * 1024 * 1024


def _pool_shape(prefetch: Optional[int], processes: bool,
                cpus: int) -> "tuple[int, int]":
    """(workers, in-flight window) for `add_many`'s prefetch pool.

    THE TWO USED TO BE ONE NUMBER, and that is why a deeper prefetch made
    the process path SLOWER: ``prefetch=64`` spawned 64 interpreter starts
    (measured 2.0 s -> 4.7 s over 198 pictures) when what a deeper window is
    for is smoothing the IN-ORDER consumption — results must come back in
    source order, so one slow picture at the head parks every worker whose
    answers are already in. Workers cap at min(8, cpus) either way; more
    measured slower (the serial half is the floor, and extra workers only
    contend for it).

    The window is where the two pools differ, because what a queued slot
    HOLDS differs: a thread bundle carries its decoded pixels (megabytes,
    so the window stays at the worker count — the documented memory bound),
    a process bundle is the slim answers (~10 KB, so the window widens to
    4x the workers, which is what actually absorbs the variance — measured
    2.00 s -> 1.83 s at 8 workers). An explicit ``prefetch`` is the window,
    and still bounds the workers below the cap so ``prefetch=2`` means what
    it always did.
    """
    workers = min(8, cpus)
    if prefetch:  # 0 and None both mean "the default", as they always did
        workers = max(1, min(workers, prefetch))
    window = prefetch or (4 * workers if processes else workers)
    return workers, window


class ImportStatus(enum.StrEnum):
    """What happened to ONE source —
    [`ImportResult.status`][media_compost.library.importing.ImportResult.status].

    A `str` subclass, so ``got.status == "imported"`` and f-strings keep
    working; the enum is for the tab completion and the spelled-out list.
    """

    IMPORTED = "imported"
    """A new item now holds these bytes."""

    ALTERNATIVE = "alternative"
    """They joined an existing item as another version of it (a near-duplicate
    at another size or encoding, or a rotation/flip of it)."""

    DUPLICATE = "duplicate"
    """The library already had them byte for byte; nothing was stored, and the
    existing file merely learned another name (or URL)."""

    MULTI = "multi"
    """Several things, or a thing standing for several: a folder or plain
    archive that scattered into entries, a book whose entry carries its
    pages as ``children``. Read ``entries``."""

    SKIPPED = "skipped"
    """Nothing the importer handles (an unsupported file type)."""

    IGNORED = "ignored"
    """The run's own minimums left it out (`ImportOptions.min_megapixels` and
    its two siblings). Its own status because all three of "this app cannot
    read it", "you already have it" and "you told me not to take it" store
    nothing, and only the last one is a decision the run was given."""

    ERROR = "error"
    """It failed; see ``error``."""


@dataclass(frozen=True)
class ImportEntry:
    """One file-shaped thing a source turned out to contain.

    A source yields a FLAT list of these, however deeply nested it physically
    was — a zip of PDFs is one entry per PDF, a zip inside a zip flattens,
    and a book found inside a book is a flat sibling entry rather than a
    member of the outer sequence (the rule that keeps the depth fixed).
    ``children`` go exactly one level further: the pages of a book, the
    frames a video matched — children of children do not exist.
    """

    status: ImportStatus = ImportStatus.SKIPPED
    """This entry's own outcome. ``imported``/``alternative``/``duplicate``
    for a landing, ``multi`` for a book (read ``children``), ``skipped`` for
    a member nothing imports, ``ignored`` for one the run's minimums left
    out, ``error`` when it failed (see ``error``)."""

    item: Any = None
    """The item: the picture, the video, or — for a ``multi`` book — the
    sequence CONTAINER standing for the whole of it (None when the book
    minted none, e.g. a plain zip whose images became flat entries)."""

    file: Any = None
    """The stored file these bytes landed on — the EXISTING file for a
    duplicate, which is the case worth recording. None for a book entry (a
    container owns no file) and for ``skipped``/``error``."""

    name: str = ""
    """What the thing was called where it was found: the member's path
    inside its archive, a page's name, the source's own filename."""

    error: str = ""
    """Why, when something went wrong — set with status ``error``, and on a
    book entry whose read failed partway (its ``children`` then hold what
    landed before the failure)."""

    derived: bool = False
    """True for a file DERIVED from the source rather than a copy of its
    bytes — a matched video frame materialized onto an existing item. Such
    a file is excluded from `ImportResult.files`, the provenance walk."""

    children: tuple = ()
    """This book's pages or this video's matched frames, in source order —
    `ImportEntry` rows themselves, always with empty ``children`` of their
    own."""

    def __bool__(self) -> bool:
        return self.status is not ImportStatus.ERROR


@dataclass
class ImportResult:
    """What one source turned out to be — exactly one per source, in order.

    ``status`` says what happened to the source as a whole (an
    [`ImportStatus`][media_compost.library.importing.ImportStatus], string-
    compatible; falsy only on error, so ``if got:`` reads correctly), and
    ``entries`` is the flat list of file-shaped things it contained. For the
    ordinary single picture there is exactly one entry and ``item``/``file``
    mirror it; for a PDF or GIF the one entry is the book, so ``item`` is
    the sequence container — the thing the library shows for it.
    """

    status: ImportStatus = ImportStatus.SKIPPED
    """What happened to the source: a landing status for a single file,
    ``multi`` for anything that contained several, ``error`` when the source
    itself could not be read."""

    item: Any = None
    """The one item standing for the source, when there is one: the image
    item, the video item, a book's sequence container. None when the source
    scattered into several entries (or none)."""

    file: Any = None
    """The one stored file, when there is one — the single entry's own."""

    entries: tuple = ()
    """One [`ImportEntry`][media_compost.library.importing.ImportEntry] per
    file-shaped thing the source contained, flat, in the order they were
    met."""

    stats: Optional[ImportStats] = None
    """The whole RUN's counters so far, shared by every result of the run."""

    error: str = ""
    """Why, when ``status == "error"``."""

    @property
    def files(self) -> tuple:
        """Every stored file the source's BYTES went into — the provenance
        targets, where a web URL belongs (`Library.add_file_urls`). Walks
        entries and children; a duplicate's existing file counts (one
        picture at a second address is the case provenance exists for), a
        DERIVED file (a materialized video frame) does not."""
        out = []
        for e in self.entries:
            for rec in (e, *e.children):
                if rec.file is not None and not rec.derived:
                    out.append(rec.file)
        return tuple(dict.fromkeys(out))

    @property
    def all_items(self) -> tuple:
        """Every item the source produced or landed on, deduplicated, in
        order — created items, book containers, and the existing items a
        duplicate, near-duplicate or matched frame reached. The set a
        statement about "everything from this address" (a crawl's site tag,
        `Library.assign_tags`) applies to."""
        out = []
        for e in self.entries:
            for rec in (e, *e.children):
                if rec.item is not None:
                    out.append(rec.item)
        return tuple(dict.fromkeys(out))

    def __bool__(self) -> bool:
        return self.status is not ImportStatus.ERROR

    def __iter__(self) -> Iterator:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"<ImportResult {self.status} {len(self.entries)} entries>"


class ImportRun:
    """An open import — see
    [`Library.importing`][media_compost.library.Library.importing]."""

    __slots__ = ("_lib", "_imp", "_options")

    def __init__(self, lib, imp: Importer, options: ImportOptions):
        self._lib = lib
        self._imp = imp
        self._options = options

    @property
    def stats(self) -> ImportStats:
        """The run's counters so far (final once it has closed)."""
        return self._imp.stats

    @property
    def items(self) -> tuple:
        """Every item this run has created so far."""
        from .handles import Item

        return tuple(Item(self._lib, i)
                     for i in self._imp.stats.imported_item_ids)

    def add(self, source: ImportSource, *,
            move: Optional[bool] = None) -> ImportResult:
        """Import one [`ImportSource`][media_compost.importer.ImportSource]:
        a path (a file, a folder, an archive, a video) or an
        [`ImportBytes`][media_compost.importer.ImportBytes] for in-memory
        data — ``run.add(ImportBytes(data=body, name="cat.png"))``. Bytes get
        the identical pipeline a file on disk gets; the name's extension
        decides how they are read, and a usable one is sniffed from the
        content when it is missing.

        Where in-memory bytes CAME FROM is recorded afterwards, on the
        result: ``got.file`` is the stored file they landed on — the
        EXISTING one for a duplicate, which is the case worth recording —
        and ``got.file.add_url(url, accessed_at=fetched)`` is the same
        web-URL source the Source list adds by hand, idempotent per
        (url, time) so a re-crawl needs no bookkeeping.

        ``move`` — for path sources — removes the source once it is safely
        ingested. It defaults to the RUN's setting: None, not False, because
        `False` here would silently override a run opened with `move=True`.
        """
        opts = self._options
        if move is not None and move != opts.move:
            opts = ImportOptions(**{**opts.__dict__, "move": move})
            self._imp._move_sources = move
        return self._result(self._imp.add_source(source, opts))

    def add_many(self, sources: Iterable[ImportSource], *,
                 prefetch: Optional[int] = None,
                 processes: Optional[bool] = None) -> Iterator[ImportResult]:
        """Import an iterable of sources, hashing ahead on workers.

        Yields one
        [`ImportResult`][media_compost.library.importing.ImportResult] per
        source, in order — the same results the same sources would get from
        a loop of [`add`][media_compost.library.importing.ImportRun.add], and
        the same single-writer import underneath. What is parallel is only
        the per-source arithmetic that reads no library state: the sha256,
        the decode, the perceptual hash, the colour signature, the eight
        orientation hashes and the metadata read of upcoming STILL IMAGES are
        computed on workers while the serial half stores the current one.
        Folders, archives, PDFs and videos take the serial path unchanged.

        ``prefetch`` is how many sources may be in flight at once (default:
        the worker count for threads; 4x it for processes, whose queued
        bundles are kilobytes). A thread bundle holds its decoded pixels in
        memory until its turn, so a run of very large images may want it
        small; the worker count follows it downward, capped at min(8, CPUs)
        — see `_pool_shape`.

        ``processes`` runs that half in worker PROCESSES instead of threads,
        so the prefetch stops competing with the importing thread for the
        GIL — measured over four crawl archives, the serial half alone runs
        0.92 s where the same loop under 8 prefetch THREADS takes 1.66 s:
        the workers' GIL slices come straight out of the importing thread.
        **It is off unless asked, and the caller must have an**
        ``if __name__ == "__main__":`` **guard** — the pool has to be
        `spawn` (forking this process would fork a live SQLite connection
        and the library's own daemon threads into a child that never runs
        them), and a spawned worker re-imports its parent's ``__main__``.
        Without the guard a script re-runs its own import in every worker,
        which starts more workers: a fork bomb, instantly. Nothing here can
        detect that, which is why this cannot default to True.

        What it costs is a one-time ~0.4 s pool start (every spawned worker
        imports the package) and about a millisecond a picture of executor
        traffic, so a handful of files gains nothing; a real run does —
        measured over the same archives, 1.85 s of thread pipeline becomes
        1.38 s warm, and the gap widens with everything that loads the
        parent's GIL (a bigger library's probes, a reader thread, near-dups).

        A process may not send a decoded picture back (it is 4.7 MB pickled
        against ~10 KB for everything else), so `prepare_source_slim` returns
        the ANSWERS — the near-dup verify and the orientation record read
        the bundle's own small vectors — and `Importer._ingest_image`
        decodes the file again only for the rare exact-pixel film-frame
        check. Both paths are asserted to produce identical libraries, down
        to every metadata row.

        Lazy: nothing is imported until the iterator is consumed. Abandoning
        it keeps what was already imported, like the run itself.
        """
        from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
        from collections import deque

        use_procs = bool(processes)
        workers, window = _pool_shape(prefetch, use_procs,
                                      os.cpu_count() or 1)
        it = iter(sources)
        if use_procs:
            import multiprocessing
            # SPAWN, EXPLICITLY. On Linux the default is still `fork`, and
            # forking this process means forking a live SQLite connection and
            # the library's own daemon threads (the smart-group sweeper) into
            # a child that will never run them — the
            # classic way to get a corrupt file out of a working program.
            fn, make = prepare_source_slim, lambda: ProcessPoolExecutor(
                max_workers=workers, mp_context=multiprocessing.get_context("spawn"))
        else:
            fn, make = prepare_source, lambda: ThreadPoolExecutor(max_workers=workers)

        with make() as pool:
            pending: deque = deque()
            pending_bytes = 0
            warned = False

            def _fill() -> None:
                nonlocal pending_bytes
                while len(pending) < window:
                    # The window is also bounded in BYTES: a slot holds its
                    # source, and an `ImportBytes` source holds its body —
                    # so a run of films at the widened process window would
                    # otherwise park gigabytes in the queue. Never below
                    # one in flight, so a single oversized body still flows.
                    if pending and pending_bytes >= WINDOW_BYTES:
                        return
                    try:
                        src = next(it)
                    except StopIteration:
                        return
                    if isinstance(src, ImportBytes):
                        pending_bytes += len(src.data)
                    # What the NAME already rules out is never submitted:
                    # through a process pool a submit pickles the whole
                    # body across a pipe, and a film's worth of bytes must
                    # not travel to a worker whose entire answer is None.
                    pending.append((src, pool.submit(fn, src)
                                    if worth_prefetching(src) else None))

            _fill()
            while pending:
                src, fut = pending.popleft()
                if isinstance(src, ImportBytes):
                    pending_bytes -= len(src.data)
                try:
                    prepared = fut.result() if fut is not None else None
                except Exception:  # noqa: BLE001
                    # A worker that died takes one source's PREFETCH with it,
                    # never the source: the serial path reads and reports it
                    # exactly as it does for anything with no bundle. Said
                    # ONCE in the log, because `prepare_source` itself
                    # answers None for anything it cannot read — a future
                    # that RAISES is the pool breaking (an unpicklable
                    # source, a killed worker), and a whole run silently
                    # falling back to serial looks exactly like the prefetch
                    # not working.
                    if not warned:
                        import logging
                        logging.getLogger(__name__).warning(
                            "import prefetch failed; continuing serially",
                            exc_info=True)
                        warned = True
                    prepared = None
                out = self._imp.add_source(src, self._options,
                                           prepared=prepared)
                _fill()
                yield self._result(out)

    def _result(self, outcome) -> ImportResult:
        """Build the source's result from the records the importer kept.

        The importer collects one flat record per file-shaped thing the
        source contained (`Importer._entries` — `add_source` says the rules),
        taken and cleared here so the next source starts clean. The
        ``item``/``file`` conveniences mirror the lone entry when there is
        exactly one — which for a PDF or GIF is the book, so ``item`` is its
        sequence container, the thing the library shows for it.
        """
        from .handles import File, Item

        imp = self._imp
        recs, imp._entries = imp._entries, []
        imp._leaf_sink = imp._entries

        def _entry(rec: dict) -> ImportEntry:
            iid, fid = rec.get("item_id"), rec.get("file_id")
            return ImportEntry(
                status=ImportStatus(rec["status"]),
                item=Item(self._lib, iid) if iid else None,
                file=File(self._lib, fid) if fid else None,
                name=rec.get("name", ""),
                error=rec.get("error") or "",
                derived=bool(rec.get("derived")),
                children=tuple(_entry(c) for c in rec.get("children", ())),
            )

        entries = tuple(_entry(r) for r in recs)
        if outcome.status == "error":
            return ImportResult(status=ImportStatus.ERROR,
                                error=outcome.error, entries=entries,
                                stats=imp.stats)
        item = file = None
        if len(entries) == 1:
            item, file = entries[0].item, entries[0].file
        return ImportResult(status=ImportStatus(outcome.status),
                            item=item, file=file, entries=entries,
                            stats=imp.stats)


def _options(lib, **kw) -> ImportOptions:
    if lib.readonly:
        raise ReadOnlyError('this library was opened with mode="r"')
    given = kw.pop("options", None)
    if given is not None:
        return given
    known = {f for f in ImportOptions.__dataclass_fields__}
    bad = set(kw) - known
    if bad:
        raise TypeError(f"unknown import option {sorted(bad)[0]!r}; "
                        f"try one of {', '.join(sorted(known))}")
    return ImportOptions(**kw)


@contextmanager
def import_run(lib, **kw) -> Iterator[ImportRun]:
    """One run: the importer's own commit cadence and a single History
    entry when it closes."""
    opts = _options(lib, **kw)
    imp = Importer(lib._session, lib._store, lib.config,
                   shared_thumbs=_thumbs_of(lib))
    imp.begin_run(opts)
    run = ImportRun(lib, imp, opts)

    def _close() -> None:
        stats = imp.finish_run()
        _log(lib, stats, opts)
        lib.commit()

    try:
        yield run
    except BaseException:
        # An abandoned run KEEPS what it already imported — the importer
        # commits as it goes, so the last few files would otherwise be lost —
        # but a failure closing it must not replace the error being raised.
        try:
            _close()
        except Exception:  # noqa: BLE001
            lib.rollback()
        raise
    _close()


def import_one(lib, source, *, move: bool = False, **kw) -> ImportResult:
    with import_run(lib, move=move, **kw) as run:
        got = run.add(source)
    return got


def import_many(lib, sources, **kw) -> ImportResult:
    """One aggregate result over many sources — `import_all`'s engine. A
    single source mirrors its own result; several concatenate their entries
    under ``multi`` (per-source boundaries are what `Library.importing` +
    `add_many` are for)."""
    with import_run(lib, **kw) as run:
        results = [ImportResult()]
        for got in run.add_many(sources):
            results.append(got)
        results = results[1:] or [ImportResult(stats=run.stats)]
    if len(results) == 1:
        return results[0]
    entries = tuple(e for r in results for e in r.entries)
    item = file = None
    if len(entries) == 1:
        item, file = entries[0].item, entries[0].file
    return ImportResult(status=ImportStatus.MULTI, item=item, file=file,
                        entries=entries, stats=run.stats)


def _thumbs_of(lib) -> ThumbLRU:
    """One rotate/flip thumb cache for the library's whole life, so a script
    importing a thousand pictures one at a time keeps its candidates decoded.
    (The near-dup index itself needs no such sharing any more — it is the
    band-key columns, probed in SQL, primed by nothing.)"""
    got = getattr(lib, "_thumb_cache", None)
    if got is None:
        got = ThumbLRU()
        lib._thumb_cache = got  # type: ignore[attr-defined]
    return got


def _log(lib, stats: ImportStats, options: ImportOptions) -> None:
    """One History entry per run, the shape the CLI and the web import log —
    which is also what makes the whole run revertible from the History view."""
    from ..importer import import_event

    ev = import_event(stats, options.parent_group_id)
    if ev is None:
        return
    log_event(lib._session, source=lib.source, **ev)

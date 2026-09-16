# Compatibility

A library written by an older build must open under a newer one. That is the
promise, it starts at the format the first release writes, and it is not
negotiable: a script can be edited and a browser tab can be reloaded, but
somebody's library is the only copy of years of work and there is no version
of "sorry, start again" that is acceptable.

Everything below is either a contract or explicitly not one. When you are
about to change something and it is not on this page, it is probably a
contract you have not noticed yet — check before you rename it.

**The first release writes format 37, and the ladder above it is empty.** The
number is a counter, not a count of releases: it had been climbing through
development, and the numbers below it are formats that were never published.
Rather than renumber — which would make every file already stamped read as
coming from the *future*, the one failure this number cannot explain — the
count simply carries on. So a library stamped 1 to 36, or carrying no stamp at
all, was made by a checkout of this repository rather than by a release, and
is refused untouched with a sentence saying so: start a new data directory and
import into it. There is no upgrade path from a shape nobody ever had, and
adopting one at the baseline would let `create_all` bake an unknown mixture in,
which is the silent failure the number exists to prevent.

From here each change to the on-disk format is a step appended to
`migrations.MIGRATIONS`, frozen the day it is written, and a library at any
version from 37 up is climbed through every rung it is missing on its first
open. `SCHEMA_VERSION` is derived from that list, so appending to it *is* the
version bump and the two cannot drift apart. The machinery is exercised
against a synthetic ladder in `tests/core/test_migrations.py`, and the rung
tests sit there armed and empty, waiting for the first real step.

**A tag-set file carries its own version**, and it is not the library's.
`format_version` stands at 1: an entry names its category as the list of names
down to it rather than as a slash path, and the category tree is whatever the
entries imply rather than a block of its own (see [tag sets](tag-sets.md)).
The two numbers are independent because the two things are different: a
library is a file somebody owns and upgrades in place, while a tag-set file is
a document this build reads and writes. A file from a *newer* build is refused
with a sentence naming both numbers, the same way a library from the future is.

A library stamped **above** the current version — written by a newer build
than the one opening it — reads as a library from the future and is refused,
untouched. That is deliberate: no stamp can simply be rewritten to open one,
because the newer shape is exactly what the older build cannot read.

## What is a contract

| Surface | Where it lives | What keeps it honest |
|---|---|---|
| Database schema | `media_compost/db.py`, versioned in SQLite's `user_version` | `migrations.py` + `tests/core/test_migrations.py` |
| Training job folders | `training/<uid>/{job,config,manifest,state}.json` | `tests/ui/golden/stored_vocabularies.json`, `JOB_DEFAULTS` |
| Stored tag sets | training model keys, settings keys and their values | `tests/ui/golden/stored_vocabularies.json` |
| The query grammar | saved searches store a query *string* | `tests/core/golden/query_corpus.json`, append-only |
| The tag-set file | `media_compost/tagsetformat.py`, at `format_version` 1 | `tests/core/test_tag_sets.py` |
| Data directory layout | `Config`'s path properties | `tests/ui/test_stored_vocabularies.py` |

## What is not

**The HTTP API.** It has no version and needs none: the app ships as one
artifact — the backend serves the frontend bundle it was built with — so
"which frontend" and "which server" are the same question. The only gap is a
browser tab left open across an update, and `server/build.py` already closes
it by comparing the bundle hash on every `/api/` request and refusing writes
from a stale page. Nothing else speaks this API, so it is free to change.

**The Python API** (`media_compost.library`) is a soft contract. It is
published in `docs/python-api.md` and people write scripts against it, so a
break should be deliberate — `tests/core/golden/public_api.json` records the
surface and fails when it moves — but a script can be edited and a library
cannot, so when the two conflict the library wins.

**Where a bare run looks for its library.** With no `--data-dir` and no
`MEDIA_COMPOST_DATA`, the default is `./_data`, unconditionally — it is never
guessed at from what happens to be lying beside the binary. The guarantee is
about opening a library you have NAMED, so point at one with `--data-dir` or
`MEDIA_COMPOST_DATA`.

**Derived data** is not a contract at any level: thumbnails, latents, the
metadata index, phashes, the dedup index. If the shape of one changes, delete
and rebuild it.

## The rules

1. **Add. Never rename, never repurpose.** A new key, column or value is
   free. A renamed one is a silent failure, because every reader here is
   written to tolerate absence — the merge reader takes each item-dict
   field through `.get()` with a default, so a renamed key is not an error,
   it is that field reset on every merged item. The sharpest case is a
   History action string: it is the key `history._REVERT` is looked up by, so
   renaming one does not raise, it quietly stops offering the Undo button on
   every event already written. The ordinary answer is the one `Occasion`
   (the model behind "Event") and `Location.address` (the column behind a
   place's "name") both take: **move the word a person reads and leave the
   string on disk alone.**
2. **A schema change ships a migration in the same commit.** Appending to
   `migrations.MIGRATIONS` *is* the version bump: `SCHEMA_VERSION` is derived
   from the list, so the two cannot drift apart.
3. **A format change regenerates its golden, and the commit message says
   why.** `MEDIA_COMPOST_UPDATE_GOLDEN=1` regenerates. Regenerating to make a
   red test green, without reading what changed, defeats the entire
   arrangement — these files exist to make you stop for a moment.
4. **When something must go, keep reading it long after you stop writing
   it.** Rename a key and the new build writes the new name while every file
   already on disk — a `config.json`, a preset in somebody's browser, a body
   from a stale tab — still says the old one. Read both and write one; the
   reader is a line, and the alternative is a field that silently resets.
   Delete the reader only when no file that could hold it still exists.
5. **Dropping a table means re-pointing whatever referenced it.** A foreign
   key is a reference somebody *else* holds, and SQLite resolves the parent
   at statement time — so a table whose key names a dropped one reads
   perfectly well and fails on the first write. `create_all` never alters an
   existing table, so only a migrated library carries the fault, and it can
   sit there unnoticed for as long as nothing writes. It has happened here:
   a rung folded one table into another and left a third pointing at the
   table it had dropped, which surfaced five rungs later as a 500 from
   deleting a tag set — and only in MIGRATED libraries, so the ladder's own
   shape test, whose fixture starts from `create_all`, could not see it.
   Before a rung drops a table, read `PRAGMA foreign_key_list` over every
   other one, and compare `fks` and not only columns.

## Adding a migration step

```python
def _v38_rating(conn):
    add_column(conn, "items", "rating", "INTEGER")

MIGRATIONS = (
    Migration(version=38, summary="items carry a rating",
              run=_v38_rating, touches=frozenset({"items"})),
)
```

The next rung appends to the list, and `CURRENT` follows the list by itself.

Four things to know, each of which has already caused a bug somewhere:

- **The DDL is frozen literal SQL, never derived from a model.** A step must
  go on producing the shape it produced the day it was written. Reach for
  `Item.__table__` and a version-37 library upgraded under a future build takes
  a different route than it takes today and lands somewhere no step describes.
  `migrations.py` imports nothing from `db.py`, and a test enforces that.
- **The ladder runs before `create_all`,** so a step may not assume any table
  exists that only the current models declare. If it needs one, it creates it
  with frozen DDL.
- **`touches` names the tables the step may change.** Everything else is
  asserted to come through byte-identical, which makes the blast radius a
  reviewable one-liner.
- **`mode="raw"` for a table rebuild.** `PRAGMA foreign_keys` is silently
  *ignored* inside a transaction, so a rebuild needs its own connection mode,
  its own `BEGIN`/`COMMIT` and its own version stamp — `rebuild_table` does
  all three. Everything else is `mode="txn"`, where the driver wraps the step
  and stamps it, and a crash rolls the whole thing back.

A change that only adds a *table* still gets a step and a bump, even though
`create_all` supplies the table for free. The ladder is the changelog of the
on-disk format: a gap in it cannot be told from a forgotten step, and the
number is the only handle a future step has on "libraries from before that
table existed".

An index needs no step at all. `_ensure_indexes` creates every model-declared
index on every open, idempotently.

## What the version numbers mean

| `user_version` | Meaning |
|---|---|
| `0` | Nobody said. An empty file is this build's own and is stamped `CURRENT`; one with tables in it was written before the format number existed — before the first release — and is refused, untouched. |
| `< BASELINE` | Refused, untouched, with a sentence saying how far back this build reaches. |
| `BASELINE … CURRENT - 1` | Backed up and upgraded on open. |
| `CURRENT` | Opened as it is. |
| `> CURRENT` | Refused, untouched. A library upgrades but never downgrades. |

`BASELINE` is 37 and moves forward only when nobody could still be on an
older number — raising it is this build declaring it can no longer read a
library it shipped. While the ladder is empty `BASELINE` and `CURRENT` are the
same number, so the "backed up and upgraded" row below describes the first
rung's future rather than anything that happens today.

## Upgrading, in practice

Opening a library upgrades it — the server, the CLI, `open_library()`. A
backup is taken first with `VACUUM INTO` (a filesystem copy is wrong under
WAL) into `<data>/backups/media-v<N>-<timestamp>.db`, the newest three are
kept, and each step prints as it runs. (`MEDIA_COMPOST_SKIP_MIGRATION_BACKUP`
is the environment form of `migrate --no-backup` and applies to *any* open —
set it only when something else already backs the library up.)

To do it deliberately instead:

```bash
media-compost migrate --data-dir /path/to/library --dry-run
```

`--check` is the same thing for scripts: exit 0 up to date, 1 upgrade pending,
2 unopenable. Neither touches the file — they read the header directly,
because constructing a `Database` *is* the upgrade.

An upgrade with steps to run is refused while a server is running against
the library (its `jobs.lock` is how that is seen — a `migrate` with nothing
to do simply says so), and two processes cannot upgrade at once
(`migrate.lock`).

A **script writing in the background** is handled too: the upgrade takes the
library's write lease, so it waits for the write in flight and then owns the
library until the last step lands (a write still in flight after 30 s is
refused with the holder named, nothing changed). If that script was built
against the *older* format, its next write notices the upgrade and stops
with a clear error instead of quietly writing old-shape rows into the new
format — rerun it with the build that matches the library. What it imported
or changed before the upgrade is untouched.

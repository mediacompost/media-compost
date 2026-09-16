# CLI reference

The `media-compost` command bundles the server launcher, a fast bulk importer, and the library maintenance tools; it shares the same core as the web app, so a CLI import produces exactly the same library a UI import would. A second command, [`media-compost-train`](#media-compost-train), drives training from a terminal.

Both are installed into the backend venv (`.venv/bin/media-compost`) — see [Installation](installation.md).

## Selecting the library

Every command takes `--data-dir <path>` to choose the library it works on. Without it, the library comes from the `MEDIA_COMPOST_DATA` environment variable, or defaults to `./_data`.

```bash
media-compost import ~/Pictures/dataset --data-dir /path/to/library
```

CLI commands can run alongside a running server on the same library, with two exceptions: `migrate` refuses while a server is up (when it actually has steps to run — with nothing to do it just says so), and `media-compost-train` refuses beside an app that has training enabled (one scheduler per library).

## `media-compost serve`

Run the web app.

```bash
media-compost serve
media-compost serve --host 0.0.0.0 --port 8080 --data-dir /path/to/library
media-compost serve --open
```

| Option | Default | Purpose |
| --- | --- | --- |
| `--host` | `127.0.0.1` | Address to listen on |
| `--port` | `8000` | Port to listen on |
| `--data-dir` | `./_data` | Library folder |
| `--open` / `--no-open` | off | Open a browser tab once the server is up. Opt-in, so a restart never steals focus from a tab you already have |

Run it as a single process with one worker, and only one server per library — see [Installation](installation.md) — its [Deployment](installation.md#deployment) section covers serving for real.

## `media-compost import`

Bulk-import files, folders, and archives, deduplicating as it goes. This is the fastest way to bring in a large collection; the web UI's import overlay does the same work with the same options (see [Importing files](import.md)).

```bash
media-compost import ./photos ./more-photos
media-compost import ./comics --parent-group "Comics" --archive-sequences
```

Arguments: one or more files or folders to import.

| Option | Default | Purpose |
| --- | --- | --- |
| `-g`, `--parent-group <name>` | — | Attach everything imported under this group (created if it doesn't exist) |
| `--parent-group-id <id>` | — | The same, by **id** — what to use when a name would be ambiguous, since two groups may share one. The group must exist. The two are mutually exclusive |
| `--new-group` / `--no-new-group` | off | Put this run's items in a group of their own, made **inside** the parent group. Lazy like a folder's: a run that imports nothing leaves no empty group behind |
| `--new-group-name <name>` | the date and time | What to call it (implies `--new-group`) |
| `--folders-as-groups` / `--no-folders-as-groups` | on | Recreate the folder structure as nested groups |
| `--recursive` / `--no-recursive` | on | Descend into subfolders |
| `--archives-as-groups` / `--no-archives-as-groups` | **off** | Give each archive its own group (otherwise its contents go to the archive's parent group) |
| `--archive-sequences` / `--no-archive-sequences` | off | Make ordered sequences from (non-comic) archive contents |
| `--sequence-grouping <which>` | `both` | Which half of a sequence joins the run's groups: `both`, `container` (the sequence alone) or `members` (the items inside it alone) |
| `--min-resolution <mp>` | 0 (no minimum) | Ignore pictures and videos under this many **megapixels** |
| `--min-short-edge <px>` | 0 (no minimum) | Ignore anything under this many pixels on its **shorter** side |
| `--min-long-edge <px>` | 0 (no minimum) | Ignore anything under this many pixels on its **longer** side |
| `--min-aspect <w/h>` | 0 (not set) | Ignore anything **narrower** than this width-to-height ratio (`0.5` is twice as tall as it is wide) |
| `--max-aspect <w/h>` | 0 (not set) | Ignore anything **wider** than this ratio (`2` is twice as wide as it is tall) |
| `--ignore-kinds <list>` | — | File types to leave alone, comma-separated: `image`, `video`, `sequence` (a PDF, an animated GIF or a comic archive), `archive` (a zip that scatters into items) |
| `--tag <name>` | — | Tag everything the run **creates**. Repeatable. Spell a negative assignment with `=`: `--tag=-blurry` |
| `--tag-image <name>` | — | Tag only the images the run creates (on top of `--tag`). Repeatable |
| `--tag-video <name>` | — | Tag only the videos the run creates. Repeatable |
| `--tag-sequence <name>` | — | Tag only the sequence containers the run creates. Repeatable |
| `--tag-existing` / `--no-tag-existing` | on | Also tag items the run **matched** rather than created (a duplicate, a near-dup fold) |
| `--data-dir <path>` | `./_data` | Library folder |

The tag options are the import overlay's **Tags** card in flags, and behave exactly as it does: names are normalized like any tag field, an alias assigns its target, a name the catalog refuses is skipped, and a run that creates nothing tags nothing. They are repeatable rather than comma-separated because a tag name cannot hold a space but nothing stops one holding a comma. **A negative needs the `=` form** — `--tag -blurry` is an option to the argument parser, not a value.

Face detection and embedding indexing are **not** here: they are background tasks the app's job queue runs, and the CLI has no worker to run them on. Import from the terminal, then run them from the library.

A **sequence** — a comic archive, a PDF, an animated GIF — is two things at once: the item the library shows and the items inside it (a comic's pages, a GIF's frames). Each keeps its own level (the items go where the archive's contents go, the sequence to the level the archive file itself sits at, falling back to the archive's own group when that level has none), and `--sequence-grouping` says which of them joins the groups at all.

The three minimums are the Storage page's [file-prune rule](settings.md#remove-files-by-rule) read the other way round: `0` is "not set", a file must clear **every** one that is set, and a **sequence is kept whole** — it is imported when any of its pages clears them, so a book comes in with every page or not at all. What the filters leave out is reported as **ignored**, separately from the duplicates the library already had.

The command prints a live progress line and finishes with a summary: new items, alternatives added to existing items, skipped duplicates, ignored files (a line that appears only when a filter left something out), videos split, archives expanded, groups created, and any errors. A run that created an item, added an alternative or put its tags on existing items is also recorded in the app's [History](history.md) log, tags included, so reverting the entry takes them back; one that only met duplicates and tagged nothing writes no entry.

Re-importing the same files is safe — exact duplicates are merged into the existing items instead of creating copies.

## `media-compost merge-library`

Merge every item of **another library folder** into this one. The source is a complete library — its `media.db` is read directly (never written), and file bytes are copied out of its item folders. Its whole tag set travels first: tags with their comments, aliases, implications and meta-tag counts; the group tree with icons and smart queries; subjects, places and events; the ranking axes. Definitions the current library already has always win.

```bash
media-compost merge-library /path/to/other-library --data-dir /path/to/library
media-compost merge-library /path/to/other-library --dry-run
```

Argument: the other library's folder (holding `media.db` and `items/`).

It is named apart from `import` deliberately: that one takes pictures from anywhere and adds them, this one takes a library and folds it in.

| Option | Default | Purpose |
| --- | --- | --- |
| `--dry-run` | off | Report what would happen without writing anything |
| `--data-dir <path>` | `./_data` | Library folder to merge into |

Items already present (same uid) are skipped, visually or byte-identical ones are merged, and everything else is created preserving its uid. The command is idempotent — re-running it is a no-op — and it finishes with a summary: items scanned, created, merged, skipped, files added, and any errors.

The source must already be at this build's library format: one that is behind is refused untouched, because merging must not change what it reads. Upgrade it first, with the build that matches it:

```bash
media-compost migrate --data-dir /path/to/other-library
```

## `media-compost migrate`

Bring a library's format up to what this build writes. Opening a library upgrades it anyway — the server, the CLI, `open_library()` — so this command is for doing it deliberately: with the server down, before a big import, or from an update script that wants to know first. See [Compatibility](compatibility.md) for what upgrades mean and where the backups go.

```bash
media-compost migrate --data-dir /path/to/library --dry-run
media-compost migrate --data-dir /path/to/library
```

| Option | Default | Purpose |
| --- | --- | --- |
| `--check` | off | Report only, for scripts: exit 0 up to date, 1 upgrade pending, 2 unopenable |
| `--dry-run` | off | Print what would run and change nothing; always exits 0 |
| `--no-backup` | off | Skip the pre-upgrade backup — if the upgrade goes wrong the library cannot be put back |
| `--data-dir <path>` | `./_data` | Library folder |

`--check` and `--dry-run` read the database header directly and never touch the file — constructing the library object is what performs the upgrade, so the read-only modes stay well away from it.

## `media-compost prune-storage`

Remove on-disk data the database no longer references: stray files inside item folders, folders of deleted items, and orphaned thumbnails. The database is the record; this makes the disk agree with it.

It prints a live progress line naming the folder it is sweeping, and finishes with the number of files and folders removed. Nothing in the database is written or changed.

```bash
media-compost prune-storage
```

| Option | Default | Purpose |
| --- | --- | --- |
| `--data-dir <path>` | `./_data` | Library folder |


## `media-compost-train`

The trainer's own command, for running training jobs from a terminal — a headless box with a GPU can take a job config and run it without the app (see [Training](training.md)). The job commands take `-d`/`--data-dir` to select the library (`setup` and `config template` need none). Every job command — `list` and `show` included, not only `run` — refuses beside an app that has training enabled, naming it (one scheduler per library); they all run fine beside an app launched with `MEDIA_COMPOST_TRAINING=0`.

| Command | Purpose |
| --- | --- |
| `setup` | Build the dedicated training virtualenv (torch, diffusers, peft, …) |
| `status` | Whether this machine can train, and what is running |
| `config template [--model KEY] [-o FILE]` | Print a complete default job config, to edit and hand to `create` |
| `create <config.json> [-n NAME] [--start]` | Create a job from a config file; `--start` queues it and turns the queue on |
| `list` / `show <uid>` | Every job, newest first / one job's record and its config |
| `run [--once]` | Work through the queue, here, until you stop it (`--once`: stop when it drains). Ctrl-C **pauses** the running job with a checkpoint rather than killing it |
| `start <uid>` | Run one job now, without turning the whole queue on |
| `pause <uid>` / `cancel <uid>` | Checkpoint and stop, keeping its place in the queue / stop and take it out of the queue |
| `steps <uid> <total>` | Change a job's total step count, including while it runs |
| `queue run` / `queue stop` | The queue's run switch |
| `log <uid> [-f]` / `watch <uid>` | A job's log, optionally followed / a line per change of state until it ends |

The scheduler is a thread and dies with the process holding it, so `create --start` only queues — `run` is the command that actually runs things on a headless box, and the one to put under systemd.

## Exporting datasets

There is no export command. Exports and training pipelines are small Python scripts using the `media_compost` package, which reads and edits everything the app does — see the [Python API](python-api.md).

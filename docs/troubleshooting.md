# Troubleshooting

What to do when something goes wrong: reading the in-app error panel, repairing a library from the command line, and getting a stuck server back up.

## A view shows an error panel

When something in the interface fails to render, the affected tab is replaced by an **error panel** showing what broke — the error message and its stack trace, selectable so you can copy it into a bug report — plus **Try again** and **Reload** buttons. The rest of the app keeps working: only the tab where the error happened is replaced, and the top bar and the other tabs stay usable.

- **Try again** re-renders the view; if the error was transient, you are back where you were.
- **Reload** reloads the whole page.

If the error keeps coming back, copy the message and stack from the panel and report it.

## "Another server is already running"

The server locks its library folder at startup, so starting a second server against the same library fails immediately with a message naming the one already running — its process id, start time, and command. Two servers on one library would corrupt each other's background bookkeeping, so this is a protection, not an error in your setup.

- If you meant to have a second server, point it at a different library with `--data-dir`.
- If the message is unexpected, another server really is running — find it via the pid in the message and stop it first.
- A **stale lock can never block a library**: the lock is released by the operating system however the process exits, even after a crash or a kill. If you see the message, the named process exists.

CLI commands (bulk import, the maintenance commands below) are not affected by the lock and work alongside a running server, with two exceptions. A **format upgrade** refuses while a server holds the library — `media-compost migrate`, or any command whose build is newer than the library's format — so stop the server first. And the trainer's own `media-compost-train` shares the training scheduler's lock: next to a server that offers training it is refused the same way, and runs fine beside one started with `MEDIA_COMPOST_TRAINING=0`.

## Restarting the server

The server is a normal foreground process — stop it with `Ctrl+C` (or by stopping whatever service manager runs it) and start it again:

```bash
.venv/bin/media-compost serve --data-dir /path/to/library
```

Nothing needs cleanup between runs: the library lock releases itself on exit, and imports or background jobs interrupted mid-way can simply be run again.

## The UI looks outdated after an update

After updating the code, rebuild the frontend and restart the server:

```bash
./scripts/build.sh          # from the repo root
# then restart media-compost serve
```

The server tells browsers not to cache the page itself, so a plain reload picks up the new version once the rebuilt bundle is being served. If the interface still looks stale, the server is most likely serving an old build — rerun `scripts/build.sh` and restart.

## Repairing a library

Two CLI commands cover library repair; both take `--data-dir` to select the library. See the [CLI reference](cli.md) for full option tables.

### Disk out of step — `prune-storage`

The database is the record. If item folders hold on-disk leftovers it no longer references — a rolled-back import's bytes, folders of deleted items, orphaned thumbnails — sweep them:

```bash
media-compost prune-storage --data-dir /path/to/library
```

### Bringing another library's items in — `merge-library`

Merge every item of another library into this one. The other library's own database is read directly — its tag set (tags with implications and aliases, groups, people, places, events, rankings) comes across, and its file bytes are copied:

```bash
media-compost merge-library /path/to/old-library --data-dir /path/to/new-library
```

Items are recreated preserving their uids; items already present are skipped or merged, so re-running is a no-op. The source is opened read-only and must already be at this build's library format — run `media-compost migrate --data-dir /path/to/old-library` first if it is older. Use `--dry-run` to see what would happen without writing anything.

## Related pages

- [CLI reference](cli.md) — every command with all options
- [Installation](installation.md) — setup and the build step
- [Deployment](installation.md#deployment) — running on a network, the single-server rule in context

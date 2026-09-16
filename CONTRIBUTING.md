# Contributing

Thanks for looking. This file is the **process**: how the branches work, what
CI checks, and the handful of rules that are not guessable from the code.
Everything else is already written down.

- **`SETUP.md`** — developer setup: the venv and extras, the Vite dev server,
  and the things the app cannot install for you (a real ffprobe on Windows,
  the right torch wheel on CUDA and on ROCm).
- **`docs/`** — the user documentation, published at
  <https://mediacompost.github.io/media-compost/>,
  and the source of truth for what the app does.
- **The source's own docstrings.** This codebase keeps its reasoning next to
  the thing it is about rather than in a design document: read the module's
  or the model's docstring before changing it. Most "why on earth is it done
  this way" questions are answered there — usually with the measurement that
  settled it, and usually because the obvious way was tried first and broke
  something quietly. `migrations.py`, `dedup_index.py`, `prefilter.py` and
  the models in `db.py` are the ones worth reading before you touch anything
  near them.

The project is licensed **AGPL-3.0**. By opening a pull request you offer
your changes under that licence.

## Branches

`main` is the only long-lived branch.

- Work happens on a short-lived branch — in your fork, unless you are a
  maintainer — and lands on `main` through a pull request.
- **A release is a tag on `main`**, named `v1.2.0`, published as a GitHub
  Release. Publishing that release — not pushing the tag — runs `publish.yml`
  (the wheel, to PyPI) and `docs.yml` (the versioned documentation, as
  `/1.2.0/` and `latest`). The unreleased docs at `/dev/` are a hand-started
  run of the same workflow.
- **`gh-pages` is written by machines** (`mike`, from the docs workflow).
  Never commit to it, never branch from it.

## Opening a pull request

1. Branch off current `main`.
2. Make the change, having **read the docstrings of what you are changing**.
3. Run the whole test suite (below) and the frontend checks.
4. Rebase onto `main` before asking for a merge. This matters more here than
   in most projects — see *Schema migrations*.

CI runs **once a day** (03:23 UTC), and only when something has landed since
its last run — a pull request and a hand-started run (*Actions → CI → Run
workflow*) still answer on the spot, but an ordinary push to `main` waits for
the morning. That is deliberate: you have already run the suite here, and what
a hosted runner adds is a different machine, which is a question that keeps
overnight. Reach for the manual run when a push is worth checking now.

The three jobs are every one of them about the MACHINE rather than about the
code, and they fail for reasons a local run does not reproduce:

- **`base`** — a base-only install imports and passes `tests/core` with no
  fastapi, no torch and no huggingface_hub in the venv. If you added an import
  to `media_compost/` (the library root) from the app or the trainer, this is
  what catches it — and, being Linux on x86-64, so is a wheel whose encoder
  answers differently from the one your digests were generated against.
- **`suites`** — the full install runs all three Python suites (less the two
  long markers, below), the frontend typecheck and the Node tests.
- **`wheel`** — the built **wheel** honours its extras: the base refuses
  `serve` with the install line rather than a traceback, `[train]` drives the
  trainer's CLI with no fastapi present, `[full]` imports the app.

**The long tests are yours, not CI's.** `slow`, `perf`, a Vite build and a
real training run all stay local, and `ci.yml`'s header names each one beside
the command that runs it — so a marker CI skips is written down rather than
quietly forgotten (`tests/ui/test_packaging.py` holds it to that).

## Running the tests

```bash
.venv/bin/python -m pytest -q          # the default suite
.venv/bin/python -m pytest -q -n 8     # the same, in parallel (~5x faster)
```

**Run all of it, not the subsystem you touched.** That is a real rule and not
politeness: what this codebase's tests catch is precisely what the file you
edited would not have made you predict — a change confined to the search
compiler last went red in the history golden, the i18n templates and an API
schema. A selection rule is a prediction, and not being able to predict is
why the ratchets exist.

Two markers are deselected by default, for different reasons:

```bash
.venv/bin/python -m pytest -q -m ""        # everything
.venv/bin/python -m pytest -q -m perf      # the scaling tripwires
```

`slow` is about wall clock alone (two files that wait on a tick thread and on
a torch subprocess — together roughly half the suite's runtime). `perf` is
about a synthetic 50k-item library and answers a question nobody asks on an
ordinary edit. **CI runs neither** (owner 2026-09), so these two are the ones
to run here before a push that matters — nothing else will.

Frontend:

```bash
cd frontend
npm ci
npx tsc -b
npm test          # node --test; needs Node >= 23.6 for TypeScript type
                  # stripping. CI uses 24. Node 20 fails with a confusing
                  # "could not find src/**/*.test.ts".
```

## Golden files

Several tests compare against a recorded answer:

| file | what it records |
| --- | --- |
| `tests/ui/golden/history_events.json` | every event ~80 mutating HTTP calls write, in order, plus reverting each one and a final state hash |
| `tests/core/golden/query_corpus.json` | the search grammar, asserted by **both** `pytest` and `node --test` |
| `tests/core/golden/value_corpus.json` | the `VALUE:` unit conventions, likewise both suites |
| `tests/core/golden/public_api.json` | the public Python API's surface |
| `tests/train/golden/training_manifests.json` | sixteen training configs materialized over one library |
| `tests/ui/golden/stored_vocabularies.json` | query syntax somebody may have **saved**, so its rows stay forever |

**Never edit one by hand.** Regenerate:

```bash
MEDIA_COMPOST_UPDATE_GOLDEN=1 .venv/bin/python -m pytest -q
```

…and then **say in the commit message why the recorded answer is now
different**. A golden that moves is the point of the golden: it is the log,
the manifest or the public API saying something it did not say before, and
the commit is where that is justified. If you cannot explain the diff, the
change is not finished.

Two of these have a rule of their own. The query and value corpora are read
by the Python **and** the TypeScript suite, so a condition kind added on one
side without corpus rows fails the other side's tests — that is deliberate,
and it is what keeps the two parsers equal. And rows never leave
`stored_vocabularies.json`: it holds syntax a user may have in a saved search
or a bookmark, so dropping one is a compatibility break and fails loudly
rather than quietly.

## Generated files

Never edit these by hand:

- **`media_compost/ui/_web_dist/`** — the built SPA the backend serves.
  Gitignored; `scripts/build.sh` produces it.
- **`frontend/src/train/fieldHelp.ts`** — committed, but compiled from
  `docs/training/fields/*.md` by `scripts/gen_field_help.py`. **Edit the
  markdown.** The strings are byte-identical on purpose — each is a
  translation catalog key — so keep them dull: paragraphs separated by blank
  lines, no lists, no bold, no line break inside a paragraph.
  `scripts/gen_field_help.py --check` exits 1 when it is stale, and a test
  runs that.

There is also a naming convention worth knowing: **any directory a program
writes is named `_something`** — `_dist`, `_build`, `_web_dist`, `_data`. If
you add a build step, name its output that way, and gitignore it.

## Schema migrations

This is the one place where two independently-correct pull requests can be
jointly wrong, so it has rules.

A library written by an older build must open under a newer one, from format
version 37 — the first release's — onward (`docs/compatibility.md`).
`media_compost/migrations.py` is the ladder that delivers that, and
**`db.SCHEMA_VERSION` is derived from it** — `CURRENT = MIGRATIONS[-1].version`
— so *appending a step is the version bump*. There is no constant to remember.
The ladder is EMPTY at the release, so the first step appended is v38.

**Open one migration pull request at a time.** If a second lands first,
rebase and renumber yours: the version appears in the `version=` field and in
the step function's `_vNN_` name, and nowhere else. The number is assigned at
**merge**, not when you write the step. Sequential integers are load-bearing
here — opening a library runs every rung above its stored version, in order,
and a test holds them to being unique and consecutive — so timestamps or
hashes, which is how frameworks with unordered migration graphs dodge this,
are not available.

Writing the step:

- **The SQL is frozen literal SQL**, and `migrations.py` imports nothing from
  `db.py` (a test enforces it). A step must go on producing the shape it
  produced the day it was written, or a version-19 library upgraded under a
  future build takes a different route than it takes today.
- **Declare `touches`** — the tables the step writes.
- **`mode="raw"` for a table rebuild**, because `PRAGMA foreign_keys` is
  silently ignored inside a transaction. Rebuild rather than
  `ALTER TABLE … DROP COLUMN`, which needs SQLite 3.35 and this app runs on
  whatever a NAS ships. A raw step that rebuilds several tables stamps only
  on the **last** one, or a crash leaves it half-applied at the new version.
- **A step may not decode every image in the library.** It runs inside a
  startup hook. Where values have to be recovered later, name it in `ADVICE`
  and let the user run it when they have a minute.
- Index-only additions need **no** version bump — `Database._ensure_indexes`
  creates them idempotently on every open. The version guard is for changes
  that make a library *read* wrong, and an index changes plans, never
  meaning.

**And run `tests/core/test_migrations.py` after rebasing onto current `main`,
not only on your branch.** The invariants it holds are properties of the
whole ladder rather than of your step: versions are unique and consecutive,
and every rung leaves exactly the shape the models declare — nothing extra,
nothing missing. Two rungs that each pass alone can fail together. The bad
case is not two steps numbered 16, which conflicts loudly; it is two steps
that both touch one table, where the frozen-SQL rule means the earlier rung
goes on emitting that table as it stood the day it was written and silently
drops the column the later one added. That has happened before, and it is why
the ladder test exists.

## Ratchets

A number of tests exist to make a silent failure loud. They tend to surprise
first-time contributors, so they are worth naming; each one's own docstring
explains what it is protecting.

- **Import boundaries** — core imports neither the app nor the trainer; the
  trainer may import `media_compost` and `media_compost.hub` and nothing
  else. Checked by reading the source, because a deferred import inside a
  rare branch is exactly what an import graph misses.
- **Frontend boundaries** (`src/boundaries.test.ts`) — `app/`, `query/`,
  `shared/` and `train/` may only reach each other in stated directions.
- **`apiFetch` is the only `fetch` that may touch `/api/`**, layer numbers
  for portalled menus, backdrop-dismiss behaviour, strict request models —
  all enforced by tests that discover their own inputs, so a new file is
  covered the moment it exists.
- **i18n coverage** — every `t("…")` literal needs an entry in each catalog.
  Strings that reach `t()` from a data table are invisible to the harvest and
  need their entries added by hand. See `docs/translating.md`.

## Documentation and the spec

- A change a user would notice updates the relevant page in `docs/`, and
  gets its line under `## Unreleased` in `CHANGELOG.md`. That section is
  written as the changes land and is renamed to the version on release
  day — a changelog reconstructed from the log that morning is a list of
  commit subjects, which is the thing it exists not to be.
- A decision whose reasoning would otherwise be lost — especially "the
  obvious way was tried and it broke X", and most especially a number that
  settled an argument — goes in the docstring of the thing it is about.

## Commit messages

Read `git log` before writing one. The subject is a plain statement of what
changed, sometimes prefixed with the area — *"Rankings: a league's scores can
be hidden without stopping the rating"*. **Not Conventional Commits**: there
is no `feat:` or `fix:` here.

The body is where the value is. Say **why**, and if a number settled it, give
the number. A commit that moves a golden, changes a default or removes a
feature says what the new answer is and what made it right.

## Making a release

The artifact is **one wheel** carrying the built web app inside it, so a
release is a build, a tag, and the docs that describe it. Two things about it
are easy to get wrong and silent when you do: a wheel built from a tree whose
frontend has not been rebuilt serves a blank page, and the docs site's version
switcher is built against `site_url`.

```bash
# 1. Everything green, from a clean tree.
./.venv/bin/python -m pytest -q
cd frontend && npx tsc -b && npm test && cd ..

# 2. Read CHANGELOG.md's `Unreleased` section once as a whole. It was written
#    as the changes landed and it IS the release's notes, word for word; the
#    bump below renames that heading to X.Y.Z, and refuses if it is empty.
#    (`bump_version.py --section X.Y.Z` prints what the release will say.)

# 3. Turn the dev version into the release. main carries `X.Y.Z.dev0` between
#    releases; `--release` strips the suffix (a patch), `--release minor` or
#    `--release major` picks a bigger number. The script rewrites every file
#    that spells the version — pyproject.toml, `__version__`, package.json
#    and the docs site — plus the changelog heading, and
#    `tests/ui/test_version.py` holds them equal.
./.venv/bin/python scripts/bump_version.py --release        # -> X.Y.Z

# 4. Build the artifact HERE FIRST — not because this is the copy that ships
#    (publish.yml runs this same script on the tag and uploads what IT
#    builds), but because the script refuses a wheel with no UI inside, and
#    learning that now beats learning it with a release already published.
./scripts/package.sh                    # -> _dist/media_compost-X.Y.Z-*.whl

# 5. Check the artifact by installing it somewhere clean and opening the app.
python3 -m venv /tmp/mc-check
/tmp/mc-check/bin/pip install _dist/media_compost-X.Y.Z-*.whl
/tmp/mc-check/bin/media-compost serve --data-dir /tmp/mc-check-lib
#    The library page must render — a blank page means the bundle is missing.

# 6. Commit and tag on main.
git commit -am "Release X.Y.Z"
git tag -a vX.Y.Z -m "X.Y.Z"
git push && git push --tags

# 7. PUBLISH THE RELEASE ON GITHUB — the tag on its own does nothing. Both
#    workflows trigger on `release: published`, so this one gesture is what
#    uploads the wheel to PyPI (publish.yml, trusted publishing, no token)
#    and puts the documentation up as /X.Y.Z/ with `latest` moved to it
#    (docs.yml). Draft it against the tag and publish it EMPTY: the notes are
#    CHANGELOG.md's `## X.Y.Z` section, which publish.yml reads before it
#    builds anything — a version with no entry fails there, while the release
#    is still something you can delete — and writes into the release when it
#    is done. The wheel and the sdist attach themselves too, the same files
#    PyPI got rather than a rebuild. (Committing them is not an option:
#    content-hashed filenames make every rebuild a new ~1.3 MB blob in a
#    history that is forever.)

# 8. Move main past the release AT ONCE, so a build from main never carries
#    the released number: pip would refuse to install it over the release.
#    `X.Y.(Z+1).dev0` sorts between this release and any next one — patch,
#    minor or major — so every main build upgrades to whatever ships next.
#    It reopens the changelog in the same breath: an empty `## Unreleased`
#    above the version just shipped.
./.venv/bin/python scripts/bump_version.py --next-dev       # -> X.Y.(Z+1).dev0
git commit -am "Start X.Y.(Z+1).dev0"
git push
```

**Checklist**

- [ ] `scripts/bump_version.py --release` run — the four copies of the
      version agree (`--check`) and none of them says `.dev` any more.
- [ ] A migration step appended to `migrations.MIGRATIONS` **if** the database
      schema changed — that append *is* the version bump, since
      `db.SCHEMA_VERSION` is derived from the list.
      `tests/core/test_migrations.py` fails when a model moves without one.
      See `docs/compatibility.md`.
- [ ] Any regenerated golden (`MEDIA_COMPOST_UPDATE_GOLDEN=1`) explained in
      its commit message — those files exist to make a format change
      deliberate, and regenerating one to turn a test green defeats them.
- [ ] `docs/` updated for anything a user would notice; `mkdocs build --strict
      -f website/mkdocs.yml` passes (CI runs it before publishing).
- [ ] Backend and frontend test suites pass.
- [ ] `./scripts/package.sh` succeeded — it refuses a wheel with no frontend.
- [ ] The wheel installed into a clean venv serves the app, not a blank page.
- [ ] `CHANGELOG.md`'s `Unreleased` section is now headed `X.Y.Z` (the bump
      does it, and refuses to release an empty one).
- [ ] Tag `vX.Y.Z` pushed **and the GitHub release published** — the release
      is the trigger, not the tag. It runs `publish.yml` (the wheel, to PyPI)
      and `docs.yml`, which publishes `/X.Y.Z/` and moves the `latest` alias
      to it. `/dev/` is a hand-started run of the same workflow and is as old
      as the last one.
- [ ] The release page carries the changelog's entry as its notes, and the
      wheel and the sdist as its files — `publish.yml` writes all three after
      the upload, so a release still empty means something went wrong.
- [ ] `scripts/bump_version.py --next-dev` committed on `main` right after,
      with an empty `Unreleased` reopened above `X.Y.Z`.

**The documentation site** (`website/mkdocs.yml` over `docs/`, published by
`.github/workflows/docs.yml` through `mike`) — how to preview it locally, how
the API reference is generated, what `site_url` decides and how the screenshots
are made — is *The website* in `SETUP.md`.

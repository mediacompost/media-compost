<img src="https://raw.githubusercontent.com/mediacompost/media-compost/main/docs/assets/icon.svg" alt="" width="96">

# Media Compost

**Compost, for media.** A local web app that turns a pile of images and
videos into datasets: import without duplicates, tag and caption at scale,
search and organize, and train a model on the result — or read the library
from your own Python scripts.

## Install

```bash
python3 -m venv media-compost-venv
media-compost-venv/bin/pip install "media-compost[full]"
media-compost-venv/bin/media-compost serve --open
```

## Requirements

- **Python 3.11+**
- **Node 18+** — only to build the frontend yourself. A release wheel already
  contains it, so installing that way needs no Node.
- The AI model actions are **optional** and need extra packages/weights — see
  [AI models](#ai-models-optional).

## Screenshots

<p><a href="https://raw.githubusercontent.com/mediacompost/media-compost/main/docs/assets/screenshots/search.webp"><img src="https://raw.githubusercontent.com/mediacompost/media-compost/main/docs/assets/screenshots/search-thumb.webp" alt="The query builder" width="32%"></a> <a href="https://raw.githubusercontent.com/mediacompost/media-compost/main/docs/assets/screenshots/annotator.webp"><img src="https://raw.githubusercontent.com/mediacompost/media-compost/main/docs/assets/screenshots/annotator-thumb.webp" alt="The annotation editor" width="32%"></a> <a href="https://raw.githubusercontent.com/mediacompost/media-compost/main/docs/assets/screenshots/training.webp"><img src="https://raw.githubusercontent.com/mediacompost/media-compost/main/docs/assets/screenshots/training-thumb.webp" alt="The Train tab" width="32%"></a></p>

## Install a release

One distribution, extras deciding what an install can do:

| you want | install | gives you |
|---|---|---|
| read/write libraries from Python | `pip install media-compost` | the `media_compost` API + `media-compost` CLI, nine dependencies |
| headless training | `pip install "media-compost[train]"` | `media-compost-train` (its torch venv comes later, via `media-compost-train setup`) |
| the web app, and everything else | `pip install "media-compost[full]"` | `media-compost serve` + all of the above |

There are only those two extras, because there are only two questions: does
this machine train, and does it serve. `[full]` includes `[train]`, so a
machine running the app can also train on it.

The wheel carries the built web app inside it, so none of them needs Node or
a build step. A wheel downloaded from the
[releases page](https://github.com/mediacompost/media-compost/releases)
installs the same way, by path or URL in place of the name.

## Install from source

```bash
git clone <this-repo> media-compost
cd media-compost

# 1. Backend (the app, no AI-model packages — those are set up from the app)
python3 -m venv .venv
.venv/bin/pip install -e ".[full]"

# 2. Frontend (build once; bundled into the app package)
./scripts/build.sh

# 3. Run
.venv/bin/media-compost serve     # http://127.0.0.1:8000 (--open opens a tab)
```

Prefer [uv](https://docs.astral.sh/uv/)? Every pip command in these docs
works verbatim as `uv pip …` (`uv venv .venv` first). uv is never required —
pip stays the default everywhere — and the app's own "Run setup" buttons
handle a uv-made venv, which ships no pip, by falling back to `uv pip`.

`scripts/package.sh` builds the two together into a wheel you can hand to
somebody else — it runs the frontend build first and refuses to produce an
artifact with no web app inside.

`serve` options: `--host`, `--port`, `--data-dir <library folder>` (default
`./_data`), `--open`. The library location can also be set with the
`MEDIA_COMPOST_DATA` environment variable. Run it as a **single process** (one
worker) — see `SETUP.md` for why, for the frontend dev-server workflow, and
for the multi-user / reverse-proxy setup.

## Importing files

**Web UI:** drag files or folders anywhere into the window (or use the import
button in the sidebar). Archives (zip/7z/cbz/…) are unpacked, duplicates are
detected against the whole library, and folder structure can become groups.

**CLI** (faster for large imports):

```bash
media-compost import ~/Pictures/dataset --data-dir /path/to/library
```

Useful options:

- `-g, --parent-group <name>` — attach everything under this group
- `--folders-as-groups / --no-folders-as-groups` — recreate the folder
  structure as nested groups (default on)
- `--recursive / --no-recursive` — descend into subfolders (default on)
- `--archives-as-groups / --no-archives-as-groups` — give each archive its own
  group (default off: a comic archive already comes in as a sequence)
- `--archive-sequences / --no-archive-sequences` — make ordered sequences from
  (non-comic) archive contents
- `--sequence-grouping <both|container|members>` — which half of a sequence
  (a comic, a PDF, an animated GIF) joins the run's groups
- `--min-resolution <mp>`, `--min-short-edge <px>`, `--min-long-edge <px>` —
  minimums a file must clear to be imported at all
- `--min-aspect <w/h>`, `--max-aspect <w/h>` — the shape range, width÷height:
  ignore anything narrower or wider than these (either end alone is fine)
- `--tag NAME` — tag everything the run creates (`--tag-image`, `--tag-video`,
  `--tag-sequence` narrow it; `--tag=-name` assigns negatively)

Re-importing the same files is safe: exact duplicates are merged into the
existing items instead of creating copies.

### Merging whole libraries

Another library folds into this one with `merge-library`: its own database is
read (never written) and its file bytes are copied across.

```bash
media-compost merge-library /path/to/other-library --data-dir /path/to/library
media-compost merge-library ... --dry-run        # report only, write nothing
```

Items are matched by uid (skip), then by content (merge); everything else is
created keeping its uid. The source's whole catalog — tags with their
comments, aliases and implications, groups, people, places, events, rankings —
comes across first, existing definitions winning. Re-running is a no-op.

## Scripting (Python API)

There is no fixed export format, and no dataset export step (the grid can
zip a view's media, named by uid, and that is all): the library is a Python
package as well as a web app, so **everything the UI can read or edit, a script
can read or edit** — and the files stay where they are, because a script asks
an item for its path.

```python
from media_compost import open_library

with open_library("/path/to/library") as lib:
    # Portrait items at least 800px wide. Tag matching includes group-inherited
    # and implied tags, exactly like the app — it is the same search.
    for item in lib.query("portrait INFO:width>=800"):
        print(item.uid, item.name, item.path)
        print("  tags:", sorted(item.effective_tags))
        print("  meta:", item.metadata.get("format"), item.width, item.height)
```

Queries take the same string the search bar takes, so one worked out in the app
can be pasted straight in; the condition models it parses to are exported, so
a query can be assembled instead of written when the values come from
variables.

Editing is the obvious spelling, and everything is logged and revertible:

```python
with open_library("/path/to/library", user="my-script") as lib:
    with lib.transaction():                  # one commit, one History entry
        for item in lib.query("INFO:width<800"):
            item.tags.add("lowres")

    lib.history[0].revert()                  # …if that was a mistake
```

Copy files wherever a pipeline needs them:

```python
import shutil
from pathlib import Path

out = Path("./export")
out.mkdir(exist_ok=True)
with open_library("/path/to/library", mode="r") as lib:
    for item in lib.query().prefetch("tags", "files"):
        if item.path is not None:
            shutil.copy(item.path, out / f"{item.uid}{item.path.suffix}")
            (out / f"{item.uid}.txt").write_text(
                ", ".join(sorted(item.effective_tags)))
```

`mode="r"` refuses every write before touching the database, which is the safe
way to run a long export beside a live server.

Video items can be turned into frames on the fly (nothing is written into the
library):

```python
for idx, ts, pil_image in item.frames(fps=1.0):   # 1 frame per second
    pil_image.save(out / f"{item.uid}-{idx:05d}.png")
```

Importing, tags, groups, subjects, faces, places, events, captions, sequences
and links are all reachable the same way — see
[docs/python-api.md](https://github.com/mediacompost/media-compost/blob/main/docs/python-api.md).

## AI models (optional)

The app runs fine without any ML packages — each model action just shows as
"needs setup" until its requirements are installed. Three ways to set up:

1. **In the app** — open a model's setup panel (Settings → Models, or the
   action menu) and click **Run setup**: the server installs the packages,
   fetches the weights, restarts itself and the page reloads.
2. **Everything at once** — `pip install -r requirements.txt` (from
   the repo root) installs the app *and* every model that runs in the main
   environment; `requirements-ai.txt` is the optional half on its own, for
   adding the models to an install you already have. The smallest working
   install of the app is `pip install -e ".[full]"` — no ML packages at all.
3. **Dedicated environments** — Florence-2 and Magi v3 (panel detection) need
   an older pinned `transformers`, so they run out-of-process in their own
   venvs: run `python -m media_compost.hub.setup_env florence` / `... magi`
   (`media_compost/hub/requirements-<env>-env.txt` lists each one's
   packages).

Model **weights** are downloaded from the app's **Settings → Models** panel
into the shared Hugging Face cache — models only ever run offline, from that
cache.

## CLI reference

| Command | Purpose |
| --- | --- |
| `media-compost serve` | Run the web app (`--host`, `--port`, `--data-dir`, `--open`) |
| `media-compost import <paths…>` | Bulk-import files, folders and archives |
| `media-compost merge-library <path>` | Fold another library's items into this one (reads its own database, copies its file bytes) |
| `media-compost migrate` | Upgrade a library's format deliberately (`--check` / `--dry-run` report only, `--no-backup`); opening a library upgrades it anyway |
| `media-compost prune-storage` | Sweep on-disk data the database no longer references (stray files, folders of deleted items, orphaned thumbnails) |

All commands take `--data-dir` to select the library (default `./_data`).

## More documentation

- [`docs/README.md`](https://github.com/mediacompost/media-compost/blob/main/docs/README.md) — the user documentation index: guides to
  every part of the app.
- `SETUP.md` — developer setup: the venv, the frontend dev server, the
  multi-user proxy configuration, the documentation site.
- `CONTRIBUTING.md` — the process: branches, what CI checks, golden files,
  schema migrations, commit messages, and how a release is cut.

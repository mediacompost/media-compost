# Media Compost — Developer Setup

A local, primarily single-user media library that deduplicates images,
organizes them with groups/tags/captions, and feeds AI-training pipelines
through its Python API. Python backend + React frontend, plus a CLI for bulk
import.

## Layout

- `media_compost/` — the Python package: the library API and CLI at the root
  (`config, db, storage, media, dedup, importer, resolve, ops/, library/`,
  `cli.py`), the web app as the `ui/` subpackage (FastAPI server, AI
  plugins), and the trainer as `train/`.
- `frontend/` — Vite + React + TypeScript SPA.
- `scripts/build.sh` — builds the SPA and bundles it into the backend package.
- `scripts/package.sh` — the above, then a wheel carrying it, for people
  who should not need Node. It refuses an artifact with no web app inside:
  `_web_dist/` is generated and gitignored, so a wheel built from an unbuilt
  tree installs and runs perfectly while serving a blank page.

## Backend

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[full,dev]"
.venv/bin/pytest            # tests/core, tests/ui, tests/train, plus a few root-level modules
```

(Or with uv, never required: `uv venv .venv && uv pip install -e ".[full,dev]"`
— the app's setup buttons cope with the pip-less venv uv creates by falling
back to `uv pip`.)

On **Windows** the venv puts its interpreter in `Scripts\` rather than `bin/`,
so the same three commands are:

```
py -m venv .venv
.\.venv\Scripts\pip install -e ".[full,dev]"
.\.venv\Scripts\pytest
```

Things the app cannot supply for you (the first two are Windows, the third is
Linux):

- **ffmpeg** — `imageio-ffmpeg` provides an ffmpeg binary but **no ffprobe**,
  and without one every video imports with no duration, no frame rate, no
  audio/subtitle tracks and no colour metadata (all probes are best-effort, so
  nothing errors). Install a full build — `winget install Gyan.FFmpeg` — or
  point `MEDIA_COMPOST_FFPROBE` at one.
- **CUDA torch** — PyPI's Windows `torch` wheel is CPU-only, so a plain
  `pip install torch` gives an environment that trains on the CPU with nothing
  saying why. `python -m media_compost.hub.setup_env` handles this for the
  dedicated envs; for
  the main venv install it explicitly:
  `pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128`
  (cu128 or newer for RTX 50-series / Blackwell).
- **AMD GPUs (Linux/ROCm)** — the same trap in a different spelling: PyPI's
  *Linux* wheel carries CUDA, not ROCm, so on an AMD box it installs fine and
  trains on the CPU. `python -m media_compost.hub.setup_env` routes to the
  ROCm index when it
  finds a ROCm stack and no NVIDIA driver; the explicit form is
  `pip install torch torchvision --index-url https://download.pytorch.org/whl/rocm7.1`.
  Windows + AMD is not supported.

## Frontend (dev, two processes)

```bash
# terminal 1 — API on :8000
.venv/bin/media-compost serve                # or: uvicorn media_compost.ui.server.app:app

# terminal 2 — Vite dev server on :5173 (proxies /api -> :8000)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

`scripts/build.sh` needs bash; on Windows the three steps are `python
scripts/gen_field_help.py` (the editor's help texts, compiled from the docs),
`npx tsc -b && npx vite build`, then copy `frontend\_dist` over
`media_compost\ui\_web_dist`.

## Production / single-process run

```bash
./scripts/build.sh          # builds SPA -> media_compost/ui/_web_dist
media-compost serve         # serves SPA + API on :8000 (--open opens a tab)
```

Run as a **single process / single worker** — several in-memory singletons (the
near-dup cache, import lock, job queue) are per-process and not shared. Multiple
concurrent users are fine on one worker (SQLite runs in WAL mode).

## Multi-user (shared library behind an auth proxy)

The app doesn't authenticate; put an authenticating reverse proxy (HTTP Basic) in
front and let the app read the caller's identity. It attributes History entries
and scopes each user's saved searches + language/date/clock/double-click prefs; the library
content and Models/Florence settings stay shared. Environment variables:

- `MEDIA_COMPOST_REQUIRE_AUTH=1` — reject requests with no resolvable user
  (`401`). Default off = **anonymous access allowed**.
- `MEDIA_COMPOST_USER_HEADER=X-Remote-User` — read the username from this trusted
  header (set by the proxy). Unset = derive it from the `Authorization: Basic`
  header (the password is ignored; auth happens upstream).

Example nginx: `auth_basic` on a `location /`, then either pass the `Authorization`
header through (default) or `proxy_set_header X-Remote-User $remote_user;` and set
`MEDIA_COMPOST_USER_HEADER=X-Remote-User`.

## CLI

Every command takes `--data-dir PATH` (or `MEDIA_COMPOST_DATA`) to select the
library; the default is `./_data`. The commands and their options are the
*CLI reference* in `README.md` and, in full, `docs/cli.md`.

## Scripting a library

The library is a Python package as well as a web app: `open_library()` reads
and edits everything the UI does, queries take the search bar's own string,
and an import from a script — from paths or from in-memory bytes — runs the
same pipeline a dropped file gets. The tour is *Scripting (Python API)* in
`README.md`; the full surface, importing included, is `docs/python-api.md`.

## The website

`website/mkdocs.yml` publishes `docs/` — the same Markdown the repository
carries — as the project site, with a landing page (`docs/index.md`) and a
feature tour (`docs/features.md`) on top of it. MkDocs Material rather than
Sphinx because these pages were already plain Markdown cross-linked by file
name, which is what MkDocs reads and what Sphinx would need MyST plus a toctree
per page to accept.

**`website/` is the site's tooling; `docs/` is the prose.** The config, its
Python requirements and `website/overrides/` — the one Jinja template that is
the landing page — sit together there, while the Markdown stays at `docs/`,
where somebody browsing the repository looks. Every path inside `mkdocs.yml` is
relative to the config file, which is what makes that split cost nothing.

Run the commands from the repository ROOT; `-f` is not optional.

```bash
python3 -m venv .venv-docs
.venv-docs/bin/pip install -r website/requirements.txt
.venv-docs/bin/mkdocs serve -f website/mkdocs.yml --watch-theme   # :8000
.venv-docs/bin/mkdocs build --strict -f website/mkdocs.yml        # what CI runs
```

**`--watch-theme` is not optional while editing `website/overrides/`.**
`mkdocs serve` watches `docs/` and the config and nothing else by default, so
an edit to the header or the landing-page template changes nothing on the page
and says nothing in the log — indistinguishable from a change that had no
effect. The startup line lists exactly what is being watched; read it if a
template edit seems to do nothing.

**The API reference is generated from the source** (`docs/api/`, one page per
module of `media_compost/library/`, rendered by mkdocstrings). It is a third
top-level destination beside Home and Docs, and it cannot fall behind the code:
a class added to `library/handles.py` appears on the next build with nobody
adding it anywhere. `docs/python-api.md` stays as the hand-written guide — what
to reach for first and why the API is shaped as it is, which no extractor
produces — and the two link to each other.

The extraction is STATIC: mkdocstrings reads the source through griffe rather
than importing it, so the docs venv needs neither `media_compost` nor any of its
dependencies, and the CI job installs no part of the app to document it. If that
ever changes to a dynamic handler, the docs build inherits the whole dependency
tree — including the AI extras — so keep it static.

`overrides/` holds two templates. `home.html` is the landing page, and
`partials/header.html` is **the header, for every page** — one template
rather than a landing page drawing its own, so the links, the GitHub label
and the site name cannot drift apart between them. Material's own chrome
(search, the theme control, the drawer) is kept and
restyled rather than replaced; the theme
control is a three-state menu whose entries are labels pointing at Material's
own palette radios, so Material still owns applying and persisting the choice.

`.github/workflows/docs.yml` publishes it to GitHub Pages: **`mkdocs build
--strict`** in the runner, then GitHub's own `upload-pages-artifact` and
`deploy-pages` actions — no branch holds the built site. **One site, for the
version people can install**: no
version in the address, no switcher, no `latest` alias — a link to a page is
a link to the current documentation and stays one. It was `mike`, a directory
per minor series with a switcher over them, which made four URLs for one page
and an archive nobody asked for.

It runs FROM A TAG, always — `publish.yml` calls it with the tag it has just
published, and *Actions → Docs → Run workflow* takes one too, which is how a
documentation fix reaches the site without a release to carry it. There is no
build from a branch: the site would then describe code nobody can install, and
`mkdocs serve` above is how unreleased prose is read. It runs on RELEASES
ONLY — republishing the whole site for a typo in a docstring put a job in the
queue behind every push and changed nothing anybody had installed.
Set *Settings → Pages → Source* to **GitHub Actions** once; the deploy is
refused otherwise. The `github-pages` environment that setting creates takes
the default branch only, which both ways in satisfy (each run belongs to
`main`; the tag is only what it checks out).

`site_url` and `repo_url` in `website/mkdocs.yml` name the published site
(<https://mediacompost.github.io/media-compost/>) and the repository
(`mediacompost/media-compost`); the canonical links and the sitemap are built
against the first, so a wrong one is every page claiming to live somewhere it
does not — including the trailing `/media-compost/`, since a project site is
served from a subdirectory and joining a page's path onto an address with no
trailing slash replaces that last segment. A custom domain would be a setting
in the repository's Pages page and this line moving with it — and nothing
else: deploying from Actions needs no `CNAME` file. The version in the site's footer is
`extra.version_number`, moved by `scripts/bump_version.py` with the package's
own three copies. The screenshots under `docs/assets/screenshots/` are real captures of
the app — WebP at 2560×1600 (a 1280×800 window at 2×), with 640×400 `-thumb`
copies for the five the landing page's gallery shows as thumbnails; see
`scripts/capture_screenshots.py` for how they are remade.

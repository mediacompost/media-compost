# Installation

This page walks you through installing Media Compost — from PyPI or from
source — and running it on your own machine.

## One distribution, three parts

Media Compost ships as **one pip distribution** holding one Python package in
three parts — the library at the root, the app and the trainer as
subpackages — with extras deciding what a given install can do:

| package | is | costs |
|---|---|---|
| `media_compost` | the public Python API and the `media-compost` CLI — read and write libraries from a script | nine dependencies, no server |
| `media_compost.ui` | the web app: the server, the frontend, the image/video editors, the AI actions | `[full]` — fastapi, uvicorn, python-multipart, faiss-cpu, imageio-ffmpeg, and `[train]` |
| `media_compost.train` | the trainer, drivable from `media-compost-train` or the app's Train tab | `[train]` — the Hugging Face plumbing and, off macOS, the NVIDIA management library the GPU stats read; the torch stack lives in a venv of its own |

| you want | install |
|---|---|
| read/write libraries from Python | `pip install media-compost` |
| headless training | `pip install "media-compost[train]"` |
| the web app, and everything else | `pip install "media-compost[full]"` |

There are only those two extras, because there are only two questions: does
this machine train, and does it serve. A machine that serves also trains — the
trainer's own dependency is one small package — so `[full]` is the answer to
everything except a scripting install and a headless GPU box.

`[full]` bundles an ffmpeg (`imageio-ffmpeg`) for video import and editing,
and the bundled binary is what gets used when it is installed — an ffmpeg on
PATH is the fallback for installs without it. To prefer a system ffmpeg (or
ffprobe — the bundled wheel ships none, so video probing wants one on PATH
anyway), point `MEDIA_COMPOST_FFMPEG` / `MEDIA_COMPOST_FFPROBE` at the
binaries.

**The AI model actions are deliberately not an extra.** Their stacks are built
around torch, and a Python dependency specifier cannot name a package index —
which matters because PyPI's torch wheel is **CPU-only on Windows** (the CUDA
builds live on `download.pytorch.org`). An extra listing torch would install a
build that reads as a hang on exactly the machines people buy GPUs for. So the
actions are set up from the app instead (**Settings → Actions → Run setup**) or
with `python -m media_compost.ui.plugins.setup_action <action>` (`--list`
names them), which is
the same thing that button runs: packages, the dedicated environment if there
is one, the right torch index for this machine (overridable with
`MEDIA_COMPOST_TORCH_INDEX`), then the weights. Until then each action shows in the app as "needs
setup" — or is hidden entirely, if you turn on *Settings → Actions → Hide
actions that need setting up*.

Because `[full]` includes `[train]`, an app install always satisfies what the
trainer declares, so the Train tabs appear (pointing you at the
training-environment setup). If a machine should not offer training at
all, the explicit switch is `MEDIA_COMPOST_TRAINING=0` — see
[Turning training off](#turning-training-off) below.

## Requirements

- **Python 3.11 or newer**
- **Node 24** — only to build the frontend yourself, and the version
  everything here is tested on.
  A released wheel already contains it, so installing that way needs no Node
  at all.
- No ML packages are required to run the app.

## Install a release (no Node)

The wheel on PyPI carries the built web app inside it, so this is everything:

```bash
python3 -m venv media-compost-venv
media-compost-venv/bin/pip install "media-compost[full]"
media-compost-venv/bin/media-compost serve --open
```

That starts the server on `http://127.0.0.1:8000` and, with `--open`, opens your browser on it.
Skip to [Choosing the data directory](#choosing-the-data-directory).

A wheel from the [releases page](https://github.com/mediacompost/media-compost/releases) installs the same way — give pip
the path or URL in place of the name, and keep the extra on the end:

```bash
media-compost-venv/bin/pip install "<path-or-url-to-the-wheel>[full]"
```

Install from source instead if you want to change the app — the rest of this
page covers that.

## Install from source

Clone the repository, then create a virtual environment at the repo root and
install the package into it:

```bash
git clone <this-repo> media-compost
cd media-compost
python3 -m venv .venv
.venv/bin/pip install -e ".[full]"
```

pip is the supported default, but [uv](https://docs.astral.sh/uv/) works
everywhere pip is shown (`uv venv .venv`, then `uv pip …` for any pip command
in these docs) — the app's setup buttons handle a uv-made venv, which ships
no pip, by falling back to `uv pip`.

This installs both commands into the venv: `media-compost` (the CLI,
including `serve`) and `media-compost-train` (headless training) — see the
[CLI reference](cli.md).

## Build the frontend

The server serves a prebuilt copy of the web app, so build it once:

```bash
./scripts/build.sh
```

This builds the SPA and bundles it into the app package
(`media_compost/ui/_web_dist`). Rerun it after updating the code — the
server serves whatever `scripts/build.sh` last produced, so a frontend change
you have not rebuilt is a change you will not see.

To produce a wheel other people can install without Node, run
`scripts/package.sh`: it builds the frontend first, packages everything
together, and refuses to hand you an artifact with no web app inside it.

## Run the app

```bash
.venv/bin/media-compost serve
```

This starts the server on `http://127.0.0.1:8000`. Options:

- `--host` / `--port` — where to listen (default `127.0.0.1:8000`)
- `--data-dir <path>` — which library to open (see below)
- `--open` — open a browser tab once the server is up (off by default, so a
  restart never steals focus from a tab you already have)

## Choosing the data directory

A **library** is a folder holding everything Media Compost stores: the
database, every item's files and artifacts, thumbnails, and training jobs.
Pick it with either:

- the `--data-dir` option: `media-compost serve --data-dir /path/to/library`
- the `MEDIA_COMPOST_DATA` environment variable

If neither is set, the library defaults to `./_data` (relative to where you
start the command). Every CLI command takes the same `--data-dir` option, so a
bulk import and the server can point at the same library.

## Run as a single process

Run the server as **one process with one worker** — several in-memory
components (the thumbnail cache, the import lock, the background job
queue) live per-process and are not shared. One worker is fine for several
concurrent users; see [Deployment](#deployment) below for serving a shared
library on a network.

Related: **one server per library.** The server locks its library folder at
startup, and a second server pointed at the same library refuses to start with
a message naming the one already running; the lock is released however the
process exits, so a stale lock file can never block a library. CLI commands
work alongside a running server, with two exceptions: `migrate` refuses while
a server is up (when it actually has steps to run), and `media-compost-train`
refuses beside an app that has training enabled — see the
[CLI reference](cli.md). See [Troubleshooting](troubleshooting.md) if you hit
the lock message.

## Development mode (two processes)

If you are changing the frontend, run the Vite dev server instead of
rebuilding after every change:

```bash
# terminal 1 — API on :8000
.venv/bin/media-compost serve

# terminal 2 — Vite dev server on :5173 (proxies /api to :8000)
cd frontend
npm install
npm run dev
```

Then open `http://localhost:5173`. For normal use, the single-process
production run above is all you need.

## Optional: AI model environments

The core app runs without any ML packages. If you want the optional pieces:

- Most AI models install into the main venv — the app's **Settings → Actions**
  page can run the setup for you, or use `pip install -r requirements.txt`
  from the repo root (the app plus every optional model;
  `requirements-ai.txt` is the optional half alone, and
  `requirements-core.txt` the library alone). See [Settings](settings.md).
- Two model families need their own pinned environments, built by
  `python -m media_compost.hub.setup_env florence` (Florence-2 captioning) and
  `python -m media_compost.hub.setup_env magi` (the Magi models: comic-panel
  and illustrated-face detection). To use an environment you built yourself,
  point `MEDIA_COMPOST_FLORENCE_PYTHON` / `MEDIA_COMPOST_MAGI_PYTHON` /
  `MEDIA_COMPOST_TRAINING_PYTHON` at its interpreter.
- LoRA training uses its own environment too: `media-compost-train setup`
  (or `python -m media_compost.hub.setup_env training`).
  See [Training](training.md).

## Deployment

The rest of this page is about running the app for real: serving a shared
library on your network — directly or in Docker — multi-user access behind an
authenticating proxy, turning training off, and what needs a network
connection.

### Serving on a network

The [single-process run above](#run-as-a-single-process) is already the
production shape; to make the server reachable from other machines, bind it to
a network interface:

```bash
media-compost serve --host 0.0.0.0 --port 8000 --data-dir /path/to/library
```

The app has no authentication of its own, so don't expose it directly to an
untrusted network — put a reverse proxy in front (see
[Multi-user access](#multi-user-access) below).

### Docker / Podman

The repository root carries a `Dockerfile` and a `compose.yaml`. The image is self-contained: the frontend is compiled inside the build, so the host needs neither Node nor Python — only Docker or Podman.

```bash
docker compose up -d        # build and run on http://localhost:8000
```

Or without Compose:

```bash
docker build -t media-compost .
docker run -d -p 8000:8000 -v mc-library:/data -v mc-models:/models media-compost
```

(`podman build` / `podman run` work the same; the image runs as a non-root user.)

Two volumes matter:

- **`/data`** is the library — items, thumbnails, the database. To serve an existing library, bind-mount it there (`-v /path/to/library:/data`).
- **`/models`** is the Hugging Face cache. Model weights downloaded from Settings → Actions land here and survive image updates.

Everything in this Deployment section applies unchanged inside the container: one process and one worker (the image's default command already does that), one server per library, the reverse-proxy setup for multi-user access, and `MEDIA_COMPOST_TRAINING=0` for machines that should not offer training.

Two container-specific notes:

- **The optional AI environments live in the container's filesystem.** The in-app "Set up" buttons work — they create `.venv-<env>` inside the container and restart the server in place — and the result survives restarts, but not a container *recreation* (an image update). Re-run the setup afterwards, or bake the environments into a derived image (`RUN python -m media_compost.hub.setup_env florence` and friends).
- **No GPU is visible unless you pass one through.** On Linux with an NVIDIA card, install the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/) and add `--gpus all` to `docker run`. (The old `nvidia-docker` / `nvidia-docker2` wrapper commands are obsolete; the toolkit plus `--gpus` is the current spelling.) macOS containers have no GPU access at all — for training or heavy AI work on a Mac, run the app natively instead.

    **With Compose it is a block rather than a flag**, which is why `compose.yaml` carries it commented out:

    ```yaml
    services:
      media-compost:
        deploy:
          resources:
            reservations:
              devices:
                - driver: nvidia
                  count: all
                  capabilities: [gpu]
    ```

    A recent Compose also takes the shorthand `gpus: all`; the block above works on both.

    Nothing extra is needed *inside* the container: on Linux the torch the AI setup installs is the CUDA build already (which is also why a GPU-less Linux image still pulls several GB of `nvidia-*` wheels — see `MEDIA_COMPOST_TORCH_INDEX` if you want a CPU-only one).

#### HTTPS and basic auth in front of the container

The app itself speaks plain HTTP and never authenticates, so anything beyond
localhost wants a reverse proxy in front that does both. In Docker the proxy is
just a second container; the official [`nginx`](https://hub.docker.com/_/nginx)
image plus two small files is the whole setup.

`compose.yaml` — the app as above, but with **no published port** of its own;
only the proxy is reachable:

```yaml
services:
  media-compost:
    build: .
    environment:
      MEDIA_COMPOST_REQUIRE_AUTH: "1"   # reject anything the proxy let through unauthenticated
    volumes:
      - library:/data
      - models:/models
    restart: unless-stopped

  proxy:
    image: nginx:alpine
    ports:
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ./htpasswd:/etc/nginx/htpasswd:ro
      - ./certs:/etc/nginx/certs:ro
    depends_on:
      - media-compost
    restart: unless-stopped

volumes:
  library:
  models:
```

`nginx.conf` — TLS, basic auth, and the proxy pass. nginx forwards the
`Authorization` header by default, and the app reads the username out of it, so
History attribution and per-user settings work with nothing further:

```nginx
server {
    listen 443 ssl;
    server_name media.example.com;

    ssl_certificate     /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;

    # Imports upload whole files — don't let the proxy cap the body size.
    client_max_body_size 0;

    # COMPRESS WHAT COMPRESSES. The app sends everything raw, and over
    # anything slower than a LAN that is the difference between a snappy
    # library and a sluggish one: the tag catalog alone is megabytes of JSON
    # that gzips about sixteen times over, and it is re-fetched whenever the
    # library changes.
    gzip            on;
    gzip_vary       on;
    gzip_min_length 1000;
    # WITHOUT THIS NOTHING IS COMPRESSED — nginx leaves a PROXIED response
    # alone unless told otherwise, and everything here is proxied.
    gzip_proxied    any;
    # Only the text types. Pictures and video are already compressed, and
    # gzip also disables byte-range serving for what it touches, which is
    # what a `<video>` scrubs with — leaving them off this list is what keeps
    # both facts true.
    gzip_types      application/json text/javascript text/css text/plain
                    text/vtt image/svg+xml;

    location / {
        auth_basic           "Media Compost";
        auth_basic_user_file /etc/nginx/htpasswd;
        proxy_pass           http://media-compost:8000;
    }
}
```

Create the two credential files once, then `docker compose up -d` and open
`https://<your-host>/`:

```bash
# one line per user in ./htpasswd (repeat for more users; needs no local
# install — the official httpd image carries the htpasswd tool)
docker run --rm httpd:alpine htpasswd -nbB alice 'their-password' >> htpasswd

# a self-signed certificate in ./certs, until a real one replaces it
mkdir -p certs && openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout certs/privkey.pem -out certs/fullchain.pem -subj /CN=media.example.com
```

For a certificate browsers trust without a warning, point a real domain at the
host and swap the `certs/` mount for one issued by
[Let's Encrypt](https://letsencrypt.org/) (certbot, or a proxy that renews for
you — Caddy and Traefik both do, at the cost of a little more configuration
than the few directives above). Everything in
[Multi-user access](#multi-user-access) below applies unchanged — the nginx
there is this nginx, running on the host instead of in a container.

**This setup is for a trusted network — a home or an office LAN — not for the
open internet.** The proxy adds encryption and a password, nothing more:
there is no brute-force protection or rate limiting on the basic-auth prompt,
no lockout, and no audit trail of failed attempts, so a reachable password
prompt can be hammered indefinitely. The app behind it trusts every
authenticated caller completely — any signed-in user can edit or delete
everything, and the server itself has not been hardened against hostile
traffic. For access from outside, put the whole thing behind a VPN
(WireGuard, Tailscale) instead of forwarding the port.

### Multi-user access

Media Compost is primarily a single-user app, but the one shared library can be served to several people at once. The model:

- **The app never authenticates.** It sits behind a reverse proxy that does (HTTP Basic), and only *reads* who the caller is.
- The username comes from a trusted header the proxy sets, configured with `MEDIA_COMPOST_USER_HEADER` (for example `X-Remote-User`) — checked first when configured — or, failing that, from the `Authorization: Basic` header (the password is ignored; it was already checked upstream).
- **Anonymous access is allowed by default.** Set `MEDIA_COMPOST_REQUIRE_AUTH=1` to reject requests with no resolvable user (`401`). **`GET /api/health` is the one exception** and answers unauthenticated whatever this is set to — the container's own `HEALTHCHECK` polls it, and a health probe that needed credentials would mark every container unhealthy. It reports only whether the server is up, whether training is offered, and the library's format version.

Knowing the caller does two things:

- **History attribution** — every change in the [History](history.md) log carries the username of whoever made it, shown as a chip.
- **Personal settings** — each person's saved searches and Language & Region / double-click preferences are their own.

Everything else is **shared**: the library content (items, tags, groups, captions), the Actions page, and the model checkpoint settings. Everyone sees the same library; concurrent edits to the same thing resolve last-write-wins. A signed-in user is shown as a small chip in the top bar (hidden on an anonymous install).

#### Example nginx setup

Authenticate with HTTP Basic and pass the identity through. The simplest form forwards the `Authorization` header (the default nginx behavior), and the app reads the username from it:

```nginx
server {
    listen 443 ssl;
    server_name media.example.com;
    ssl_certificate     /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;

    # Imports upload whole files — don't let the proxy cap the body size.
    client_max_body_size 0;

    # COMPRESS WHAT COMPRESSES. The app sends everything raw, and over
    # anything slower than a LAN that is the difference between a snappy
    # library and a sluggish one: the tag catalog alone is megabytes of JSON
    # that gzips about sixteen times over, and it is re-fetched whenever the
    # library changes.
    gzip            on;
    gzip_vary       on;
    gzip_min_length 1000;
    # WITHOUT THIS NOTHING IS COMPRESSED — nginx leaves a PROXIED response
    # alone unless told otherwise, and everything here is proxied.
    gzip_proxied    any;
    # Only the text types. Pictures and video are already compressed, and
    # gzip also disables byte-range serving for what it touches, which is
    # what a `<video>` scrubs with — leaving them off this list is what keeps
    # both facts true.
    gzip_types      application/json text/javascript text/css text/plain
                    text/vtt image/svg+xml;

    location / {
        auth_basic           "Media Compost";
        auth_basic_user_file /etc/nginx/htpasswd;
        proxy_pass           http://127.0.0.1:8000;
    }
}
```

Alternatively, have the proxy set an explicit header and tell the app to trust it:

```nginx
    location / {
        auth_basic           "Media Compost";
        auth_basic_user_file /etc/nginx/htpasswd;
        proxy_set_header     X-Remote-User $remote_user;
        proxy_pass           http://127.0.0.1:8000;
    }
```

```bash
MEDIA_COMPOST_USER_HEADER=X-Remote-User \
MEDIA_COMPOST_REQUIRE_AUTH=1 \
media-compost serve --host 127.0.0.1
```

Only use a trusted header when the app is reachable exclusively through the proxy — the app believes whatever the header says.

### Turning training off

On a machine that could never finish a training run — a NAS, an old laptop — launch with:

```bash
MEDIA_COMPOST_TRAINING=0 media-compost serve
```

The **Train**, **Evaluate**, and **Models** tabs disappear entirely (not greyed out — absent), the API behind them is turned off with them (so a leftover bookmark or an old browser tab cannot start a run), and opening `/train` lands you in the Library. Everything else keeps working, including the AI actions that only look at one picture at a time. See [Training](training.md) for what the tabs do when enabled.

### Network access

Day-to-day use fetches nothing — AI models run from weights already on disk.
A connection is needed in exactly three situations:

- **Downloading model weights**, from **Settings → Actions** (the AI actions)
  and the Train tab's Models page (training base models), into the shared
  Hugging Face cache.
- **Setting up an AI action or the trainer** — **Run setup** installs Python
  packages (and torch from its own index), building a dedicated environment
  where a model needs one.
- **A Hugging Face access token**, for the few gated training base models
  (FLUX.1 dev and Kontext, FLUX.2 Klein 9B) whose licenses have to be
  accepted on Hugging Face first — picked up from the environment or from
  `hf auth login`. No bundled AI action needs one.

If the environment **forces Hugging Face offline mode** (for example
`HF_HUB_OFFLINE`), the app respects it: everything already downloaded keeps
working, and the Settings → Actions and Train → Models pages show a warning card naming the
variable, with a one-click way to unset it for the session.

See [Settings](settings.md) for the Actions page and its download controls.

## Next steps

- [Getting started](getting-started.md) — a first tour of the app
- [Importing files](import.md) — the import overlay and its options
- [CLI reference](cli.md) — bulk import and library maintenance from the terminal
- [Troubleshooting](troubleshooting.md) — error screens, the library lock message, and common issues

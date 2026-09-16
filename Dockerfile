# Media Compost — server image (Docker / Podman).
#
# Build from the repo root:
#   docker build -t media-compost .
# Run with a persistent library and model cache:
#   docker run -p 8000:8000 -v mc-library:/data -v mc-models:/models media-compost
#
# The frontend is compiled inside the build (stage 1), so neither the host nor
# the running container needs Node.
#
# The image keeps the repository layout (/app/media_compost) instead of
# installing into site-packages: the optional AI plugin environments
# (.venv-<env>) are created beside the package. An editable pip install
# preserves that while still providing the `media-compost` command. (The
# setup machinery and the trainer — setup_env, setup_action, the
# requirements-<env>-env.txt lists, media_compost/train/scripts — all ship
# INSIDE the package now, so a wheel install works too; the editable
# install here is convenience, not a requirement.)

# --- Stage 1: build the SPA ---------------------------------------------------
FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: runtime ---------------------------------------------------------
FROM python:3.12-slim-bookworm

# ffmpeg from apt also provides ffprobe, which the bundled imageio-ffmpeg wheel
# does not — video probing (tracks, duration, subtitles) degrades without it.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# THE LICENCE FILES ARE PART OF THE BUILD CONTEXT, not decoration. `pyproject`
# declares `license-files = [LICENSE, THIRD-PARTY-NOTICES.md, licenses/*.txt]`,
# and setuptools resolves those at build time — MISSING ONES ARE NOT AN ERROR,
# it simply writes a wheel without them and without the `License-File:`
# headers. So leaving them out of the COPY produced an image whose installed
# package carried neither the AGPL text nor the attributions the bundled
# fonts, the JS bundle and the vendored model code require, which for a §13
# server image is the artifact those obligations are most about.
COPY pyproject.toml MANIFEST.in requirements*.txt LICENSE THIRD-PARTY-NOTICES.md ./
COPY licenses/ licenses/
COPY media_compost/ media_compost/
COPY --from=frontend /build/_dist media_compost/ui/_web_dist

RUN pip install --no-cache-dir -e ".[full]"

# Non-root. /app stays writable by the app user: the optional AI setup creates
# .venv-<env> in the checkout root. /data and /models are created here
# so the mountpoints belong to the app user rather than root.
RUN useradd --create-home --uid 1000 compost \
 && mkdir -p /data /models \
 && chown -R compost /app /data /models
USER compost

# /data holds the library; /models persists downloaded model weights (the
# Hugging Face cache) across container replacements.
ENV MEDIA_COMPOST_DATA=/data \
    HF_HOME=/models
VOLUME ["/data", "/models"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

# One process, one worker — the job queue, import lock and near-dup cache are
# per-process (see docs/installation.md, the Deployment section).
CMD ["media-compost", "serve", "--host", "0.0.0.0", "--port", "8000", "--no-open"]

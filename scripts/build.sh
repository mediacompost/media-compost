#!/usr/bin/env bash
# Build the frontend and bundle it into the app package so
# `media-compost serve` can serve the SPA from a single process.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# The job editor's help texts are compiled from the docs, so they are
# generated BEFORE the bundle that carries them — a build that shipped
# yesterday's wording would look exactly like an edit that did nothing.
echo "==> Compiling the training help from docs/training/fields"
python3 "$ROOT/scripts/gen_field_help.py"

echo "==> Building frontend"
cd "$ROOT/frontend"
npm install
npm run build

echo "==> Bundling into the app package (media_compost/ui/_web_dist)"
rm -rf "$ROOT/media_compost/ui/_web_dist"
cp -R "$ROOT/frontend/_dist" "$ROOT/media_compost/ui/_web_dist"

echo "==> Done. Run:  media-compost serve"

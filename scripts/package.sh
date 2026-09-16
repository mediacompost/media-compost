#!/usr/bin/env bash
# Build a release artifact: the frontend, bundled into the core package,
# packaged as a wheel somebody can `pip install` without Node.
#
# The ORDER is the whole point. `_web_dist/` is generated and gitignored, so a
# wheel built from a tree that has not been built carries no frontend at all —
# and it installs, starts and answers the API perfectly well while serving a
# blank page. That failure is silent, so this script refuses to hand over an
# artifact it cannot find the UI inside.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/_dist"

bash "$ROOT/scripts/build.sh"

echo "==> Building the wheel"
rm -rf "$OUT"
mkdir -p "$OUT"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
"$PY" -m pip wheel --no-deps --wheel-dir "$OUT" "$ROOT" >/dev/null

# setuptools stages a full copy of the package under _build/ while it works
# (setup.cfg is what moves it off its default `build/`); it is pure litter once
# the wheel exists, and leaving it around is how a stale copy of the source
# ends up in the root for months. Both names, in case a tool ran without the
# config.
rm -rf "$ROOT/_build" "$ROOT/build"

WHEEL="$(ls "$OUT"/*.whl)"

echo "==> Checking the artifact actually contains the app"
"$PY" - "$WHEEL" <<'PY'
import sys, zipfile

names = zipfile.ZipFile(sys.argv[1]).namelist()
ui = [n for n in names if "/_web_dist/" in n]
missing = []
if not any(n.endswith("_web_dist/index.html") for n in names):
    missing.append("_web_dist/index.html")
if not any("/_web_dist/assets/" in n and n.endswith(".js") for n in names):
    missing.append("_web_dist/assets/*.js")
if missing:
    sys.exit(
        "REFUSING this wheel: it has no frontend in it (" + ", ".join(missing)
        + ").\nIt would install and run and serve a blank page. Check "
        "[tool.setuptools.package-data] in pyproject.toml."
    )
print(f"    {len(ui)} frontend files bundled")
PY

echo "==> Done: $WHEEL"
echo "    Install it anywhere with:  pip install '$WHEEL'"

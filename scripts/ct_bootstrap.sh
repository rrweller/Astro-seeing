#!/usr/bin/env bash
# One-time (idempotent) setup on CT 350. Safe to re-run: it only creates missing
# directories and never deletes or overwrites anything under /data.
set -euo pipefail
cd "$(dirname "$0")/.."

say() { printf '\n== %s\n' "$*"; }

say "pixi"
if ! command -v pixi >/dev/null; then
  echo "pixi not found. Install it (user-level, no root):"
  echo "  curl -fsSL https://pixi.sh/install.sh | sh && exec \$SHELL -l"
  exit 1
fi
pixi --version
pixi install --locked

say "directories"
DATA_ROOT=${ASTRO_DATA_ROOT:-/data/astro}
STAGING=${ASTRO_STAGING:-/staging}
STATE=${ASTRO_STATE_DIR:-$HOME/.local/state/astro}
for d in static terrain era5/pl era5/sl era5/static validation derived products manifest-exports; do
  mkdir -p "$DATA_ROOT/$d"
done
mkdir -p "$STAGING/grib" "$STAGING/tmp" "$STATE" logs
pixi run python - <<PY
from pathlib import Path
from astroseeing.paths import filesystem_type, assert_local_filesystem
for p in ("$DATA_ROOT", "$STAGING", "$STATE"):
    print(f"{p:40s} {filesystem_type(Path(p))}")
assert_local_filesystem(Path("$STATE"))  # SQLite must not be on NFS
print("state dir is local: ok")
PY
df -h "$DATA_ROOT" "$STAGING" "$STATE"

say "CDS credentials (content not printed)"
if [[ -f ~/.cdsapirc ]]; then
  stat -c '%a %n' ~/.cdsapirc
  [[ $(stat -c '%a' ~/.cdsapirc) == 600 ]] || echo "WARNING: run chmod 600 ~/.cdsapirc"
  grep -q '^url: https://cds.climate.copernicus.eu/api' ~/.cdsapirc && echo "url line ok" || echo "WARNING: url line not as expected"
else
  echo "~/.cdsapirc missing — Riley creates it (AGENTS.md 'Things only Riley can do')"
fi

say "ephemeris (DE440s, checksum-verified)"
pixi run fetch-ephemeris

say "tests"
pixi run lint
pixi run test

say "done"

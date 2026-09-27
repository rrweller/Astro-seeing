#!/usr/bin/env bash
# Download → verify → ingest loop for everything planned in the manifest (validation
# boxes). Resumable and safe to re-run: each stage only moves requests forward, and
# nothing under /data is ever overwritten. Raw GRIB is kept; run `astro cleanup-raw`
# separately once the stores have been used.
#
#   tmux new -s boxes 'bash scripts/run_boxes.sh 2>&1 | tee -a logs/run_boxes.log'
#
# MAX_ACTIVE (default 4) requests are in flight at the CDS at once.
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.pixi/bin:$PATH"

remaining() {
  pixi run -q python -c '
from astroseeing.manifest import Manifest
from astroseeing.paths import Paths
c = Manifest(Paths.from_env().manifest).counts()
print(sum(c.get(k, 0) for k in ("planned", "submitted", "downloaded", "verified")))'
}

while true; do
  pixi run astro download --max-active "${MAX_ACTIVE:-4}" --poll 30 --max-hours 0.5
  rc_d=$?
  pixi run astro verify
  rc_v=$?
  pixi run astro ingest
  rc_i=$?
  left=$(remaining)
  echo "$(date -u +%FT%TZ) run_boxes: download=$rc_d verify=$rc_v ingest=$rc_i remaining=$left"
  if [[ "$left" == "0" ]]; then
    break
  fi
  if [[ $rc_d -ne 0 && $rc_v -ne 0 && $rc_i -ne 0 ]]; then
    sleep 60  # everything failing at once (e.g. network): back off before retrying
  fi
done
pixi run astro status

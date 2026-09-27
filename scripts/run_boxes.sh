#!/usr/bin/env bash
# Download → verify → ingest loop for everything planned in the manifest (validation
# boxes and areas). Resumable and safe to re-run: each stage only moves requests
# forward, and nothing under /data is ever overwritten. Raw GRIB is kept; run
# `astro cleanup-raw` separately once the stores have been checked.
#
# Failed requests are retried up to MAX_ATTEMPTS (default 5) times, for transient CDS,
# network or NAS problems; a request that keeps failing stays failed for a person to
# look at (the notify watcher reports it). A round that makes no progress backs off.
# The loop ends when nothing is left to do.
#
# On CT 350 it runs as the systemd service astro-boxes.service
# (scripts/systemd/system/, installed by scripts/install_services.sh); by hand:
#   tmux new -s boxes 'bash scripts/run_boxes.sh 2>&1 | tee -a logs/run_boxes.log'
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.pixi/bin:$PATH"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-5}"

# Requests still to finish: in flight, plus failed ones that will be retried.
remaining() {
  pixi run -q python - "$MAX_ATTEMPTS" <<'PY'
import sys

from astroseeing.manifest import Manifest
from astroseeing.paths import Paths

m = Manifest(Paths.from_env().manifest)
c = m.counts()
retryable = sum(1 for r in m.by_state("failed") if r.attempts < int(sys.argv[1]))
print(sum(c.get(k, 0) for k in ("planned", "submitted", "downloaded", "verified")) + retryable)
PY
}

while true; do
  t0=$(date +%s)
  pixi run astro retry-failed --max-attempts "$MAX_ATTEMPTS"
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
  # A round shorter than 5 minutes had nothing to wait for (e.g. every submission
  # failing while the CDS or the network is down): back off before retrying.
  if (( $(date +%s) - t0 < 300 )); then
    sleep 600
  fi
done
pixi run astro status

#!/usr/bin/env bash
# One-off (2026-10-30): release the held TMT requests (D37) once Chile's extra single
# levels (sl/chile@vars-...) have all left the queue, so the Chile subset goes first
# (by_state submits in id order and the TMT requests have lower ids). Run hourly by
# astro-release-tmt.timer; it disables that timer after releasing. Idempotent.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.pixi/bin:$PATH"
left=$(pixi run -q python - <<'PY'
from astroseeing.manifest import Manifest
from astroseeing.paths import Paths

m = Manifest(Paths.from_env().manifest)
busy = ("planned", "submitted", "downloaded", "verified")
print(sum(1 for r in m.by_state(*busy) if r.key.startswith("sl/chile@vars-")))
PY
)
if [[ "$left" != "0" ]]; then
  echo "$(date -u +%FT%TZ) release_tmt: $left Chile subset requests still queued; waiting"
  exit 0
fi
for p in pl/chile/ sl/chile/ pl/tmt_ sl/tmt_ static/tmt_; do
  pixi run astro release "$p"
done
echo "$(date -u +%FT%TZ) release_tmt: released; $(pixi run -q astro status | tr -d '\n ')"
# run_boxes.sh exits when nothing is left, which may already have happened.
systemctl is-active --quiet astro-boxes.service || systemctl start astro-boxes.service
systemctl disable --now astro-release-tmt.timer

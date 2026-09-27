#!/usr/bin/env bash
# Clone Haslebacher et al.'s code (GPL-3.0) into external/ — run it from there only,
# never copy it into src/ (AGENTS.md "Secrets and licences"). external/ is gitignored.
set -euo pipefail
cd "$(dirname "$0")/.."
dest=external/haslebacher
if [[ -d "$dest/.git" ]]; then
  echo "already cloned: $dest"; git -C "$dest" fetch --quiet origin code
else
  mkdir -p external
  git clone --branch code https://github.com/CarolineHaslebacher/Astroclimate-future-project "$dest"
fi
commit=$(git -C "$dest" rev-parse HEAD)
echo "$commit" > external/haslebacher.COMMIT
echo "Haslebacher code at commit $commit (recorded in external/haslebacher.COMMIT)"
head -n 3 "$dest/LICENSE" 2>/dev/null || echo "WARNING: no LICENSE file found"
find "$dest" -name 'calc_model_seeing_values.py' -print

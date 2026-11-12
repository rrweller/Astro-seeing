# CT runbook: commands to run on CT 350

These are the steps from phase 1 that need the real machine (`/data`, `/staging`,
CDS credentials). Claude Code on the CT runs them (see `docs/handoff_ct.md`);
only the credential steps need Riley. Run them in order, as the normal user, in
`tmux` for anything long. Every command is safe to re-run: nothing under `/data` is deleted or
overwritten.

Paths below assume the repo is cloned at `~/astro-seeing`. If it lives
elsewhere, change `WorkingDirectory=` in `scripts/systemd/*.service` too.

## 0. Get the code

The bootstrap is merged into `main`. Day-to-day work happens on the `dev`
branch; `main` only receives checkpoints that Riley approves.

```bash
git clone https://github.com/rrweller/Astro-seeing ~/astro-seeing
cd ~/astro-seeing
git switch dev 2>/dev/null || { git switch -c dev && git push -u origin dev; }
```

## 1. Bootstrap (about 5 minutes)

```bash
command -v pixi || { curl -fsSL https://pixi.sh/install.sh | sh; exec $SHELL -l; }
cd ~/astro-seeing
sudo mkdir -p /staging && sudo chown "$USER": /staging   # only if /staging isn't writable yet
bash scripts/ct_bootstrap.sh 2>&1 | tee logs/bootstrap.log
```

What it checks: `pixi install --locked`; creates any missing
`/data/astro/{static,terrain,era5/{pl,sl,static},validation,derived,products,manifest-exports}`,
`/staging/{grib,tmp}` and `~/.local/state/astro`; prints each path's
filesystem type and refuses a state directory on NFS; checks that `~/.cdsapirc`
exists with mode 600 (without printing it); downloads the DE440s ephemeris
(checksum-verified); runs `ruff` and the full test suite (97 tests, about 2 min).

**Expected:** `/data/astro` shows `nfs4`, `~/.local/state/astro` shows a local
filesystem, and the last lines say `97 passed`. Send me `logs/bootstrap.log` if
not.

## 2. Papers and Haslebacher's code (about 5 minutes)

```bash
pixi run python scripts/fetch_papers.py 2>&1 | tee logs/fetch_papers.log
bash scripts/clone_haslebacher.sh
```

`papers/INDEX.md` lists each file with its page count and SHA-256. The Bi et al.
PDF (MDPI) was blocked from the cloud container, so check that it downloaded
here; if MDPI refuses it again, save it from a browser as
`papers/bi2023_remotesensing.pdf` and re-run the script to index it. Add Racine
2005 and the García-Lorenzo corrigendum by hand if you can get them.

## 3. CDS smoke test (phase 1 step 2; minutes to hours, depending on the queue)

Prerequisites (only you can do these): `~/.cdsapirc` with
`url: https://cds.climate.copernicus.eu/api` and `key: <token>`, `chmod 600`,
and the licences accepted on the ERA5 pressure-levels, single-levels and
complete dataset pages.

```bash
tmux new -s smoke
cd ~/astro-seeing
pixi run astro cds-smoke-test 2>&1 | tee logs/cds_smoke_test.log
```

It requests **one hour** (2023-06-21 00 UTC) of pressure levels (29 levels × 5
variables) and single levels (17 variables) for a 5×5-point box at Paranal, in
GRIB, through the manifest. It records queue time, processing time, file size and
throughput, verifies both files, and asks the CDS what one *global day* of each
dataset would cost (no download). Output: `reports/cds_smoke_test.json`.

- Exit code 2 plus `"authentication": {"ok": false}` in the report means a token
  or licence problem: that's an [ASK] for me to raise with you.
- Commit the report (`git add reports/cds_smoke_test.json && git commit -m "CDS smoke test"`)
  or send it to me; the phase 1 plan's volume and time numbers get updated from it.

## 4. After the smoke test: a first validation box

Validation boxes use one request per month (decision D16; `plan-box` defaults to
`month`). Check the smoke test's cost estimates first. Example:

```bash
pixi run astro plan-box --region paranal --lat -24.63 --lon -70.40 \
    --start 2023-06-01 --end 2023-06-30 --kinds pl,sl,static
pixi run astro status
pixi run astro download                    # one CDS job at a time (D39); resumable; Ctrl-C is safe
pixi run astro verify
pixi run astro ingest
pixi run astro cleanup-raw                  # deletes staging GRIB only after re-verifying the store
```

## 5. Long runs as systemd user services (optional, for later)

```bash
mkdir -p ~/.config/systemd/user
cp scripts/systemd/*.service scripts/systemd/*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now astro-manifest-export.timer    # nightly manifest copy to /data
systemctl --user start astro-download@download.service         # resumable download loop
journalctl --user -u astro-download@download -f
sudo loginctl enable-linger "$USER"   # keep user services running after logout
```

## 6. Validation areas, holds and notifications (added 2026-09-27)

On this CT everything runs as root from `/home/astro-seeing`; pixi and tmux are in
`/root/.pixi/bin` (add it to `PATH` in non-interactive shells).

```bash
# Plan downloads for an area in configs/validation_areas.yaml (prints fields and CDS time)
pixi run astro plan-area chile --start 2021-01-01 --end 2025-12-31 --kinds pl --hours night
pixi run astro plan-area timau --start 2002-01-01 --end 2021-12-31 --kinds pl \
    --variables z,t,u,v --levels 37 --day-step 4

# Pause, resume or drop planned requests by key prefix (kind/region/period)
pixi run astro hold pl/paranal/202
pixi run astro release pl/paranal/202
pixi run astro cancel pl/paranal/202 --reason "superseded by the Chile area"

# Long-running loops: on CT 350 these run as system services (D32):
#   bash scripts/install_services.sh; systemctl status astro-boxes astro-notify
# or by hand in tmux:
tmux new -d -s boxes  'bash scripts/run_boxes.sh 2>&1 | tee -a logs/run_boxes.log'
tmux new -d -s notify 'pixi run astro notify-watch 2>&1 | tee -a logs/notify_watch.log'
pixi run astro notify "test message"   # one-off; topic URL in ~/.config/astro/notify.env
```

The watcher sends ntfy messages on finish, on problems (failures, 3 h without
progress, the download loop stopped, NAS not answering) and a daily summary at
06:00 UTC. Its memory is `~/.local/state/astro/notify_state.json`.

## 7. A one-off CDS measurement (global hour; ticket #10, D50)

A measurement request is downloaded under the CDS gate (one job at a time, D39) and
verified like any request, then ends in the state `measured`. It is never ingested, so
it never raises a "refused" alert, and nothing is written under `/data`. Its timings
are in the manifest like any request's (`submitted_at`, `cds_started_at`,
`cds_finished_at`, and the file row's `size` and `download_seconds`). The raw GRIB stays
in `/staging/grib`; nothing deletes it automatically, because it has no ingest.

The downloader submits planned requests in the order they were added, so a new
measurement waits behind everything already planned. To give it its turn, hold the
other planned requests, then release exactly those afterwards (Riley, 2026-11-12: no
queue-order code). Holds are taken by request id with the download loop stopped,
and only those ids are released afterwards. The job already at the CDS, if any,
finishes first.

```bash
cd /home/astro-seeing && export PATH=/root/.pixi/bin:$PATH

# 1. Plan it: one global hour, 29 levels x z,t,u,v,cc = 145 fields (~300 MB)
pixi run astro plan-measure --kind pl --date 2023-06-21 --hours 0

# 2. The TMT release timer releases the TMT holds once no Chile subset request is
#    *planned*, so holding the Chile subset would trigger it. Stop it for the test.
systemctl is-active astro-release-tmt.timer && systemctl stop astro-release-tmt.timer

# 3. Stop the download loop and wait until no `astro download` runs. The downloader
#    submits to the CDS first and records the job after; a hold landing in between
#    would leave that job unrecorded (Copilot review of PR #32).
systemctl stop astro-boxes
while pgrep -f "astro download" >/dev/null; do sleep 10; done

# 4. Hold everything else that is planned, by request id, and save exactly those ids
pixi run -q python - <<'PY'
import json
from pathlib import Path

from astroseeing.manifest import Manifest
from astroseeing.paths import Paths

saved = Path("logs/held_for_measure.json")
if saved.exists():
    raise SystemExit(f"{saved} exists: release that earlier hold (step 6) first")
m = Manifest(Paths.from_env().manifest)
ids = [r.id for r in m.by_state("planned") if r.purpose != "measure"]
for i in ids:
    m.transition(i, ["planned"], "held", detail="held for a measurement (runbook 7)")
saved.write_text(json.dumps(ids))
print(f"held {len(ids)} requests; ids in {saved}")
PY

# 5. Start the loop: it submits the measurement next. Wait until `astro status`
#    shows it `measured`.
systemctl start astro-boxes
pixi run astro status

# 6. Release exactly the ids step 4 held (only those still held; other holds stay),
#    then make sure the loop runs and restart the timer if step 2 stopped it
pixi run -q python - <<'PY'
import datetime as dt
import json
from pathlib import Path

from astroseeing.manifest import Manifest
from astroseeing.paths import Paths

saved = Path("logs/held_for_measure.json")
m = Manifest(Paths.from_env().manifest)
n = 0
for i in json.loads(saved.read_text()):
    if m.get(i).state == "held":
        m.transition(i, ["held"], "planned", detail="released after a measurement (runbook 7)")
        n += 1
saved.rename(saved.with_name(f"held_for_measure.done-{dt.datetime.now(dt.UTC):%Y%m%dT%H%M%SZ}.json"))
print(f"released {n} requests")
PY
systemctl is-active --quiet astro-boxes || systemctl start astro-boxes
systemctl start astro-release-tmt.timer   # only if step 2 stopped it

# 7. Read the timings for ticket #11
pixi run -q python - <<'PY'
from astroseeing.manifest import Manifest
from astroseeing.paths import Paths

m = Manifest(Paths.from_env().manifest)
for r in m.conn.execute(
    "SELECT r.key, r.state, r.submitted_at, r.cds_started_at, r.cds_finished_at,"
    " f.size, f.download_seconds FROM requests r LEFT JOIN files f ON f.request_id = r.id"
    " WHERE r.purpose = 'measure'"
):
    print(dict(r))
PY
```

While only held requests remain, `run_boxes.sh` exits and the watcher may send
"Finished (N on hold)"; that is expected. Once the timings are recorded, the raw file
can be deleted by hand from `/staging/grib`.

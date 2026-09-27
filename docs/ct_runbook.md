# CT runbook: commands for Riley to run on CT 350

These are the steps from phase 1 that need the real machine (`/data`, `/staging`,
CDS credentials). Run them in order, as your normal user, in `tmux` for anything
long. Every command is safe to re-run: nothing under `/data` is deleted or
overwritten.

Paths below assume the repo is cloned at `~/astro-seeing`. If it lives
elsewhere, change `WorkingDirectory=` in `scripts/systemd/*.service` too.

## 0. Get the code

The cloud session could not push to GitHub (no write access for that session),
so the branch may reach you as a git bundle instead. Pick the one that applies:

```bash
# (a) if branch claude/awesome-goodall-yadxpa is on GitHub
git clone https://github.com/rrweller/Astro-seeing ~/astro-seeing
cd ~/astro-seeing && git checkout claude/awesome-goodall-yadxpa

# (b) from the bundle file (astro-seeing-phase1.bundle)
git clone -b claude/awesome-goodall-yadxpa astro-seeing-phase1.bundle ~/astro-seeing
cd ~/astro-seeing && git remote set-url origin https://github.com/rrweller/Astro-seeing
git push -u origin claude/awesome-goodall-yadxpa     # pushes the work to GitHub
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
(checksum-verified); runs `ruff` and the full test suite (96 tests, about 2 min).

**Expected:** `/data/astro` shows `nfs4`, `~/.local/state/astro` shows a local
filesystem, and the last lines say `96 passed`. Send me `logs/bootstrap.log` if
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

## 4. After the smoke test: a first validation box (only after Riley OKs granularity)

Example, not to run yet (see `reports/phase1_plan.md` §6, decision D16):

```bash
pixi run astro plan-box --region paranal --lat -24.63 --lon -70.40 \
    --start 2023-06-01 --end 2023-06-30 --kinds pl,sl,static --granularity month
pixi run astro status
pixi run astro download --max-active 4      # resumable; Ctrl-C is safe
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

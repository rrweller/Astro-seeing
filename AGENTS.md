# AGENTS.md — astro-seeing

Instructions for coding agents (Claude Code) working in this repository.

At the start of every session:
- Read this file in full.
- Read `docs/RESEARCH.md` in full before any work on physics, data selection, validation or thresholds.

Don't edit this file yourself: propose changes to Riley in a report.

## Mission

Build a self-hostable web app: a 3D globe you can drag and zoom, with toggleable layers.

- **Main layer:** the average number of *good astronomical viewing nights per year*, for every land location (land plus a 1 km buffer).
- **A good night needs:**
  1. at least 2 h of astronomical darkness (Sun more than 18° below the horizon);
  2. clear sky;
  3. good seeing.
- **Component layers:** dark hours, clear nights, median seeing, best month.

No free or cheap source has multi-year global historical seeing. So seeing is computed from ERA5 reanalysis profiles, and validated againast published papers and observatory measurements before scaling up.

**Correct results matter more than speed.** Multi-day compute is fine; unverified numbers are not.

## Working with Riley (owner)

**Stop and ask [ASK] before:**
- starting a new phase;
- any download campaign expected to exceed 50 GB or 24 h of wall time, unless it's already listed with its size in an approved plan;
- deleting or overwriting anything under `/data`;
- changing a method or constant that validated results depend on;
- adding a data source with new licence terms;
- anything that costs money.

**Within an approved phase:** work through the tasks yourself. At each milestone, write a short report in `reports/` covering the numbers, plots, and what's uncertain.

**Riley's standing preferences (always apply):**
- Verify that every link loads and says what you cite before you cite it.
- Prefer peer-reviewed papers and primary documentation. Never use Grokipedia or other AI-generated sites.
- Check sources before stating facts, and don't assume. Say plainly when you're unsure, and double-check yourself.

**Decision log:** record every non-trivial decision in `docs/decisions.md` (date, options, evidence, choice, who decided).

## Environment (as of 2026-09-26)

- **Container:** Proxmox LXC CT 350 `astro-seeing` on node `procyon` (i7-10700T, 8 cores, no hyper-threading). The CT has 6 cores, 24 GB RAM and 8 GB swap, runs Ubuntu 26.04 and is unprivileged. Use at most 5 worker processes. Everything runs in UTC.
- **`/data` (the NAS):** QNAP NAS over NFSv4.1, hard-mounted on the host and bind-mounted into the CT; ~3.4 TB, ~110 MB/s.
  - It's the durable store, with no snapshots or backups, so treat it as the only copy.
  - Files show as `nobody:nogroup`. Never `chown` there or rely on ownership.
  - If the NAS drops, I/O hangs rather than failing, so long jobs need timeouts or watchdogs.
- **`/staging`:** local SSD, 150 GB, for downloads in flight and temp files; not backed up. One global day of hourly profiles is about 7 GB in GRIB.
- **Root disk (64 GB):** repo, environment, logs and SQLite state. Never put SQLite databases on `/data` (network-filesystem locking; see `docs/RESEARCH.md` §9).
- **No GPU needed:** the project is download-bound, and the physics runs in hours on CPU.
- **Network:** no data cap (Riley, 2026-09-26). The Copernicus Climate Data Store (CDS) queue and its throughput are the bottleneck; measure them.

## Things only Riley can do

- **CDS access:** create the account, put the personal access token in `~/.cdsapirc` (`chmod 600`), and accept the licences on the pages for ERA5 pressure levels, ERA5 single levels and ERA5 complete. If a small test request fails with a licence or authentication error, [ASK].
- **GitHub:** the repo and push credentials for this container.
- **TMT site-testing database:** a free login, needed for phase 1 calibration. [ASK] when you get there.
- **Proxmox host and QNAP:** any change there.

## Non-negotiable rules

**Correctness**
- **Tests:** every equation gets a known-answer unit test (`docs/RESEARCH.md` §4.9) and property tests (e.g. monotonic in height). Phase 1 site results become golden tests that later changes must keep passing, unless Riley approves the change.
- **Reproducing papers:** reproduce each paper with *its own* constants and choices first (e.g. Bi et al.: λ = 550 nm, coefficient 5.25). Only then switch to ours, and record both.
- **Units:** SI internally, but pass each formula the units it expects (Tatarskii and Osborn–Sarazin use P in hPa). Heights are metres above mean sea level (EGM2008 or geopotential height).
- **Interpolation:** never interpolate seeing in time or space. Interpolate J = ∫Cₙ²dz (or Cₙ² profiles), then convert.
- **No silent fixes:** never clip, fill or smooth silently. Count and log every masked or clipped value.
- **Source of truth:** if `docs/RESEARCH.md` disagrees with a paper PDF, the PDF wins. Fix the note, log it, and tell Riley.

**Data safety**
- **Downloads:** GRIB, day-sized requests, each tracked in the SQLite manifest (request → file → checksum → verification → ingest). Downloads must be resumable and idempotent.
- **Verify before ingest:** check field count, grid, levels, times, and fill/NaN counts. Delete a raw GRIB only after its ingested Zarr data has been verified.
- **What gets stored:** only land cells (with the 1 km buffer) and night hours (Sun below −12°). Validation boxes keep all hours.
- **Writes:** atomic (write temp → verify → rename). Never delete or overwrite `/data` content without [ASK].
- **Provenance:** every product records the git commit, config hash, input manifest IDs and software versions.

**Secrets and licences**
- **Never commit:** `~/.cdsapirc`, tokens, `papers/`, `external/`, or data. Keep `.gitignore` current.
- **Papers:** stay local in `papers/`; most aren't licensed for redistribution.
- **Haslebacher et al.'s code is GPL-3.0:** run it from `external/` to compare results; don't copy it into `src/`.
- **Attribution:** products carry the ERA5 (CC-BY 4.0) and Copernicus DEM attributions (text in `docs/RESEARCH.md` §7).

**Code**
- **Environment:** Python ≥ 3.12 in a conda-forge environment managed by pixi, with `pixi.toml` and a committed `pixi.lock`. Use `ruff` for lint and format; `pytest` with `hypothesis` for tests.
- **Git:** small commits on branches, pushed to origin. Never force-push `main`.
- **Long jobs:** run under systemd user services or `tmux`, log to `logs/`, and can resume after interruption.

## Architecture

Pipeline: `download → verify → ingest (land/night mask → Zarr on /data) → physics (profiles) → nightly (per cell, per height) → aggregate → tiles/web`

- **Weather:** ERA5 on its 0.25° grid (native resolution ~31 km). Exact CDS variable names are in `docs/RESEARCH.md` §7.
  - Pressure levels 1000–50 hPa (29 levels): geopotential, temperature, u and v wind, and cloud fraction (`cc`).
  - Single levels: total/low/mid/high cloud, cloud base height, surface pressure, 2 m temperature and dewpoint, skin temperature, 10 m and 100 m wind, boundary-layer height, friction velocity, instantaneous sensible heat flux, water vapour column.
  - Model levels (ERA5 complete) for validation boxes only.
- **Terrain:** Copernicus DEM GLO-30 (30 m DSM, EGM2008). GLO-90 is a fallback for quick work.
- **Terrain-aware downscaling** (`docs/RESEARCH.md` §5):
  - For each ERA5 cell and hour, compute seeing and cloud *as functions of height h*: the turbulence integral from h upward (plus the cell's ground-layer term), and the cloud cover above h.
  - Both can only shrink as h rises, so each night has a lowest height h* at which it counts as good.
  - A pixel's value is a lookup of its 30 m elevation in the cell's height tables, blended between neighbouring cells so no 25–30 km blocks appear.
- **Rendering:** don't store global 30 m rasters for each layer. Store per-cell height tables and generate pixels at render time, or pre-render only the low zooms. Phase 2 decides which.
- **Storage:** Zarr v3 with sharding (chunks ≥ 1 MB, few files on NFS).
  ```
  /data/astro/{static,terrain,era5/pl,era5/sl,validation,derived,products,manifest-exports}
  /staging/{grib,tmp}
  ~/.local/state/astro/manifest.sqlite    # copy an export to /data/astro/manifest-exports nightly
  ```
- **Repo:**
  ```
  src/astroseeing/{download,verify,ingest,physics,solar,terrain,nightly,aggregate,tiles}/
  tests/  notebooks/ (one per paper reproduction)  reports/  configs/  scripts/  web/
  docs/{RESEARCH.md,decisions.md}  papers/ (gitignored)  external/ (gitignored)
  ```

## Phases and gates

### Phase 1: foundations and paper checks (small data, under ~100 GB)

1. **Bootstrap.**
   - Set up the pixi environment and lockfile, the repo skeleton, `.gitignore` and tests.
   - Fetch the papers into `papers/` (list in `docs/RESEARCH.md` §10) and check each one opens.
   - Clone Haslebacher et al.'s repo (`code` branch) into `external/`.
   - Write `reports/phase1_plan.md` with the tasks, data volumes and order. Share it with Riley, then start.
2. **CDS smoke test.** Request one hour over a small box in GRIB. Record queue time, throughput and any request-size limits you hit.
3. **Core code.** Physics module with tests (`docs/RESEARCH.md` §4); darkness checked against Skyfield; land mask; manifest, downloader and ingest for small boxes.
4. **Validation targets** (`docs/RESEARCH.md` §6):
   - Bi et al. (7 sites).
   - Priyatikanto et al. (Timau).
   - Haslebacher et al. (8 sites): run their code and match their outputs.
   - Osborn & Sarazin: the free-atmosphere vs total split at Paranal.
   - TMT (5 sites): DIMM, MASS and ground-layer medians.
   - ESO Paranal and La Silla DIMM/MASS for 2021–2025. These overlap our period, so use them for calibration with held-out data.
5. **Experiments.**
   - Pressure levels vs model levels (ERA5 complete, about 1 year, a few boxes).
   - Terrain-aware vs cell-average (Paranal, Mauna Kea, La Palma, Lenghu, TMT sites).
   - Cloud-above-height vs total cloud (Mauna Kea, La Palma, Paranal).
   - How much 3-hourly instead of hourly profiles change the nightly results.
   - Ground-layer options: none, Osborn–Sarazin relocation, W71, or a calibrated constant.
6. **Good-night proposal.** Propose the good-night definition and default thresholds, with evidence (Riley chose this route). [ASK]
7. **Projections.** From measured numbers, estimate phase 2 and 3 download time, disk use and compute.

**Gate 1** (`reports/phase1.md`). Riley approves before phase 2. The report must show:
- All known-answer and property tests pass.
- The Haslebacher et al. reproduction matches.
- Bi et al. and Priyatikanto et al. match within stated tolerances, or every difference is explained.
- Calibration is fitted and checked on held-out data.
- Experiment results, each with a recommendation.
- The good-night proposal.
- A phase 2 plan with numbers.

### Phase 2: viewer and regional runs

1. **Regional data.** About 20°×20° each, 2021–2025:
   - Regions: Tibetan Plateau/Qinghai, Atacama, SW USA/Baja, Hawaii, Canaries/Iberia, South Africa, SE Australia, Timau/Nusa Tenggara.
   - Pressure levels (with `cc`) and single levels, hourly unless phase 1 showed 3-hourly is enough. [ASK] if over 50 GB.
2. **Terrain.** GLO-30 for the regions; per-cell terrain statistics; a display terrain pyramid (measure its size at each zoom).
3. **Products.** Nightly height tables and aggregates; component layers: dark hours, clear nights, median seeing, best month.
4. **Viewer.**
   - Prototype both MapLibre GL JS v5 (globe; `addProtocol` can generate tiles in the browser) and CesiumJS, then pick one and give reasons. Riley delegated this choice.
   - Static hosting, threshold toggles, click-to-inspect, attributions.
5. **Checks.** No seams at cell or region edges; seasonal patterns physically sensible; phase 1 numbers unchanged; NAS budget worked out for phase 3.

**Gate 2** (`reports/phase2.md`): a demo plus numbers, and a recommendation on cadence (hourly or 3-hourly) and number of years for phase 3. [ASK]

### Phase 3: global run

- **Downloader:** a resumable service fetching one global day per request, then verify → ingest → delete raw. There's no data cap, but respect CDS etiquette and concurrency limits.
- **Terrain:** process GLO-30 globally, streamed tile by tile, keeping only derived products.
- **Products:** physics, nightly tables, aggregates, tiles.
- **Done when:**
  - every day is present and verified;
  - the phase 2 regions match the global run cell for cell;
  - spot checks against Open-Meteo's ERA5 agree;
  - golden tests pass;
  - the site builds reproducibly from a clean checkout.

## Decisions already made (2026-09-26)

- **Data source:** ERA5 via CDS in GRIB. Pressure levels for the global run; model levels only for validation.
- **Terrain:** the per-pixel terrain-aware method, using GLO-30. Riley: "minimum 100 m, ideally finer".
- **Clouds:** cloud above a height comes from the pressure-level cloud fraction `cc`. This adds about 25% to the profile download.
- **Layers:** good nights per year plus the component layers. Not now: moonlight, light pollution, τ₀/θ₀ layers.
- **Period:** 2021–2025 (5 full years) unless changed at gate 2. Keep the data source swappable: ERA6 (~14 km) starts releasing from late 2027.
- **Seeing convention:** 500 nm at zenith. Store J and J(h) so other wavelengths and airmasses can be derived.
- **Coverage:** land plus a 1 km buffer, Antarctica included.
- **Delegated to the agent:** proposing the good-night rule (after phase 1) and choosing the globe library (in phase 2).

## Open decisions ([ASK] with evidence)

- Good-night definition and thresholds.
- Ground-layer treatment.
- Hourly vs 3-hourly profiles, and the number of years.
- Viewer rendering approach, maximum zoom and hosting.

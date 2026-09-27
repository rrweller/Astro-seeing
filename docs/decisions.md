# Decision log

Format: date · decision · options · evidence · choice · who decided. "Agent
(provisional)" means the agent chose it inside the approved phase 1 bootstrap
and it is open to Riley's review; anything marked **[ASK]** waits for Riley.

Decisions made before this log existed are in AGENTS.md "Decisions already made
(2026-09-26)".

---

## 2026-09-27 — Phase 1 bootstrap (cloud session, no CT access)

### D1. Environment: Python 3.13 on conda-forge via pixi, lock for linux-64
- **Options:** Python 3.12 or 3.13; lock for linux-64 only, or also macOS/Windows.
- **Evidence:** every dependency (python-eccodes 2.48, zarr 3.4, skyfield 1.54, cdsapi 0.7.7, ecmwf-datastores-client 0.5.3) resolved for 3.13 on conda-forge; the CT is linux-64.
- **Choice:** Python 3.13, linux-64 only, pixi 0.81 workspace, `pixi.lock` committed. Add platforms later if Riley wants to run on another machine.
- **Who:** agent (provisional).

### D2. CDS client: ecmwf-datastores-client, used asynchronously
- **Options:** `cdsapi.Client().retrieve()` (blocking), or submit/poll/download by request id with `ecmwf.datastores.Client`, the library `cdsapi 0.7.7` wraps for the current CDS.
- **Evidence:** a blocking retrieve cannot resume a request still queued at the CDS after a restart; the datastores client exposes `submit`, `get_remote(id).status`, `get_results(id).download` and `estimate_costs` (read from the installed source).
- **Choice:** the async path; the CDS request id is stored in the manifest the moment the CDS accepts a request. Credentials are read from `~/.cdsapirc` (mode 600 enforced); the key is never logged or stored. `cdsapi` stays installed.
- **Who:** agent (provisional).

### D3. Column discretisation
- **Choice:** Cₙ² constant per slab between neighbouring valid levels; T_mid = mean of the two levels, P_mid = √(p₁p₂) (log-p midpoint), θ_mid = T_mid(1000/P_mid)^0.286; gradients by finite difference; S² = (Δu/Δz)² + (Δv/Δz)². Levels with p > surface pressure or Z ≤ orography are masked and counted. Non-increasing heights in valid slabs raise an error instead of being repaired.
- **Evidence:** RESEARCH §4.3 prescribes slabs and the log-p midpoint; the rest is our choice.
- **Who:** agent (provisional).

### D4. Troposphere/stratosphere switch for HMNSP99
- **Options:** WMO lapse-rate tropopause with or without a pressure bound; how to handle ERA5's sparse levels near the tropopause.
- **Evidence:** the WMO definition (RESEARCH §4.4). A deep low-level isothermal layer satisfies the WMO criterion without a bound (tested).
- **Choice:** the lowest level with p ≤ **500 hPa** whose lapse rate to the next level is ≤ 2 K/km, and whose average lapse rate to every level within 2 km, and to T linearly interpolated at +2 km, is ≤ 2 K/km. If none is found, all slabs use troposphere coefficients and the column is counted (`tropopause_not_found`). Slabs whose base is at or above the tropopause level use stratosphere coefficients. The 500 hPa bound is our choice and needs checking against the polar winter tropopause *[check]*.
- **Who:** agent (provisional).

### D5. Osborn–Sarazin unstable layers (N² ≤ 0)
- **Options:** `zero` (Cₙ² = 0), `abs` (use |∂θ/∂z|), `nan`.
- **Evidence:** in the stable closed form Cₙ² ∝ S^(4/3) |∂θ/∂z|^(4/3), so Cₙ² → 0 continuously as N² → 0⁺ under both `zero` and `abs`. The O&S paper does not say.
- **Choice:** default `zero`, count firings (`os_unstable_layers`). Compare `zero` and `abs` in the phase 1 ground-layer experiment.
- **Who:** agent (provisional).

### D6. Cloud-above-height overlap
- **Choice:** implement random, maximum and maximum-random (Geleyn & Hollingsworth 1979); default max-random until the phase 1 consistency check (C at the ERA5 surface vs ERA5 `tcc`) picks one. cc outside [0, 1] is clipped and counted; invalid levels count as clear and are counted.
- **Who:** agent (provisional); final rule **[ASK]** with phase 1 evidence.

### D7. O&S ground-layer relocation generalised to any height
- **Choice:** J(h) = I(max(h, z_g + 1 km)) + [I(z_g) − I(z_g + 1 km)], with I(x) = ∫ₓ^top Cₙ² dz. This equals O&S at the site (h ≥ z_g + 1 km), gives the full model column for valley pixels (no double counting), and stays continuous and non-increasing in h (property-tested).
- **Evidence:** O&S §5.4 (relocation of 926–1926 m to 2635–3635 m at Paranal); the split at 1 km is from their §5.7.
- **Who:** agent (provisional); ground-layer treatment itself remains an open **[ASK]**.

### D8. Darkness and the night mask
- **Choice:** Sun GHA and declination from Skyfield (DE440s, SHA-256 pinned), tabulated every 10 min and interpolated (error < 0.5″, tested); geometric altitude, no refraction (as Skyfield's `dark_twilight_day`). Dark minutes counted at minute midpoints of each night window (local mean noon to local mean noon, keyed by evening date). **Ingest night mask:** keep hour t if the Sun is below −12° at any minute in [t − 30 min, t + 30 min), so every hour that touches astronomical darkness is kept with margin (tested).
- **Evidence:** vs Skyfield `almanac.dark_twilight_day` at 9 sites × 6 dates: crossings within 3.7 s, minute counts within 0.96 min.
- **Who:** agent (provisional).

### D9. Unix time → Skyfield time
- **Choice:** pass whole days plus seconds of day to `ts.utc`. `ts.utc(1970, 1, 1, 0, 0, u)` counts leap seconds and lands 27 s early in 2023 (found and tested).
- **Who:** agent.

### D10. Zarr layout for ingested ERA5
- **Options:** one store per request, per month, or per year; append vs write-once.
- **Choice (phase 1):** one Zarr v3 store per manifest request at `/data/astro/era5/{kind}/{region}/{period}.zarr`, written once to a temp directory, read back bit-for-bit, fsynced, renamed, and read back again. Never overwritten (same content → no-op; different content → error). float32 (GRIB is 16-bit packed, so nothing is lost), Blosc zstd level 5 with byte shuffle, chunks ≤ 4 MB with time and level whole, one shard per array (one file per variable per request); the shard is the array shape rounded up to whole chunks, because Zarr v3 needs shards to be multiples of chunks (e.g. 721 latitudes → 23-row chunks → 736-row shard; found in PR review). No consolidated metadata (not in the v3 spec). A `cells` layout (land cells plus a counted night mask) is implemented for phase 2/3. Whether day-sized stores are right for the global run is a phase 2 decision.
- **Who:** agent (provisional).

### D11. Manifest location and export
- **Choice:** `~/.local/state/astro/manifest.sqlite` (WAL mode); opening it on a network filesystem raises. The nightly export backs up to a local temp file with the SQLite backup API, then copies, fsyncs and renames onto `/data/astro/manifest-exports/manifest-<UTC stamp>.sqlite`. SQLite never writes on NFS.
- **Evidence:** RESEARCH §9 pitfall 16.
- **Who:** agent (provisional).

### D12. Raw GRIB deletion
- **Choice:** delete a raw GRIB only if it is under the staging directory, its ingest is recorded as verified, and the store still matches the arrays rebuilt from that GRIB bit-for-bit at deletion time. The file row and the `raw_deleted` state are then written in one transaction. If a run dies between deleting the file and that write, the next run checks the store against its recorded content hash and finishes the transition (or skips it if the check fails). Nothing under `/data` is ever deleted by code.
- **Who:** agent.

### D13. c_p
- **Choice:** c_p = 3.5 R_d (R_d = 287.06), so g/c_p = 9.7607e-3 K/m. It only enters through g/c_p; RESEARCH §4.9's O&S values (N² = 1.279e-4, Ri = 5.12) are reproduced with it. *[check]* that 3.5 R_d is the IFS convention.
- **Who:** agent (provisional).

### D14. ERA5 attribution text
- **Choice:** copy the wording from the CDS dataset pages' "Citation and attribution" block (read via the CDS catalogue API) into `provenance.py` and RESEARCH §7; every store carries it. The first version of `provenance.py` had text written from memory; it was replaced with the verified wording before any commit.
- **Who:** agent.

### D15. Corrections to docs/RESEARCH.md from the PDFs (Riley to review)
1. §3.3: the O&S free-atmosphere/ground-layer split is **1 km** above the observatory (O&S §5.7, Fig. 9), not "about 1–2 km".
2. §3.4: Haslebacher et al. use **ε = 0.976 λ/r₀** at 500 nm (eqs. 5–6); Euler-forward integration; Table 4 lower levels recorded.
3. §3.2: Priyatikanto et al. interpolated linearly to 5 hPa steps (10–1000 hPa) before computing, and their printed eqs. 4, 6 and 7 differ from §4.4 (sign of a₃, ∂θ/∂h with P/T², θ with 100 hPa). All three variants are implemented (`Cn2Model`) for the reproduction.
4. §6.4: TMT Table 2 checked; Mauna Kea 13N θ₀ = 2.69″ filled in.
5. §7: CDS variable names confirmed on the live forms; attribution text and request keys added.
6. §4.1: measured nights-per-year added next to the estimates.
- **Not verified here:** Bi et al. 2023 (MDPI blocks this container, HTTP 403). Check §3.1 and §4.4 against the PDF on the CT.
- **Who:** agent; Riley to confirm.

### D16. Request granularity for validation boxes **[ASK]**
- **Options:** day-sized requests (AGENTS.md) or month-sized for small boxes.
- **Evidence:** phase 1 needs roughly 20,000 box-days (see `reports/phase1_plan.md`); at one request per day per dataset that is about 40,000 CDS requests, each queued separately. A 5×5-point month of pressure levels is 29 × 5 × 24 × 31 ≈ 108,000 fields; whether the CDS accepts that is what the smoke test's cost estimate will tell.
- **Choice:** code supports both (`--granularity month`); the default stays `day` until Riley decides.
- **Decided 2026-09-27 (Riley): month-sized requests for validation boxes.** `astro plan-box` now defaults to `month` (`configs/era5.yaml: request.validation_box_granularity`); global and regional runs stay one day per request. AGENTS.md still says "day-sized requests"; the exception for boxes is proposed in `reports/phase1_plan.md` §9 for Riley to add. If the CDS rejects a month-sized box request (cost limits), fall back to `--granularity day` and record it.
- **Who:** Riley.

### D17. Missing values in ERA5 GRIB
- **Choice:** a bitmap-missing value fails verification, except for variables where missing is physically expected. For now that is only `cbh` (no cloud → no cloud base). Those counts are recorded as warnings, decoded to NaN, and stored in the Zarr `qc` attribute (`grib_missing_values_<var>`). The grid-size check uses `numberOfDataPoints`, because `numberOfValues` excludes missing points (found by the test). If the smoke test shows other variables with legitimate gaps, they get added here explicitly, never silently.
- **Who:** agent (provisional).

### D18. No unmasked ingest outside validation boxes
- **Options:** let the CLI ingest any request on the full grid, or require the land/night mask for anything that is not a validation box.
- **Evidence:** AGENTS.md "What gets stored": only land cells (with the 1 km buffer) and night hours; validation boxes keep all hours. The land mask is not built yet (its source is an open [ASK]). Copilot's review of PR #1 flagged that the CLI would store any request unmasked.
- **Choice:** without a mask function, `ingest_pending` stores only requests of at most 121 grid points (11×11, i.e. validation boxes). Larger requests stay in `verified`, are logged and counted (`refused_unmasked`), and the CLI exits non-zero. Cleanup refuses to delete the raw file of a `cells`-layout store unless it is given the same mask function. `download`, `verify`, `ingest` and `cleanup-raw` now exit non-zero when anything failed, so systemd and scripts see it.
- **Who:** agent (provisional).

### D19. Reproduction tolerances approved
- **Choice:** the tolerances in `reports/phase1_plan.md` §5 are fixed before any reproduction runs (Bi ±0.05″ on medians and quartiles; Priyatikanto 0.79″ ± 0.03″; O&S ±0.1″ on the Table 3 ECMWF medians; Haslebacher: their published precision, and ≤0.1% between our code and theirs; calibration bias ≤0.10″ free atmosphere, ≤0.15″ total on held-out data).
- **Who:** Riley, 2026-09-27 ("I think the tolerances are fine").

### D20. Land-mask source: `global-land-mask`
- **Options:** `global-land-mask` (PyPI) or OSM land polygons (ODbL).
- **Evidence (checked 2026-09-27):**
  - Package v1.0.0, MIT licence. Its mask is NOAA GLOBE 1 km (30″) elevation, with GLOBE's no-data cells as sea; shape 21600 × 43200, nearest-neighbour lookup.
  - GLOBE data terms: the "Unrestricted" version has "no copyright or security distribution restrictions" (NOAA NCEI ETOPO page, which covers GLOBE). Cite: National Geophysical Data Center, 1999, Global Land One-kilometer Base Elevation (GLOBE) v.1, Hastings & Dunbar, doi:10.7289/V52R3PMS.
  - Behaviour: every validation site tested is land (Paranal, Mauna Kea 13N, La Palma, Timau, Lenghu, Dome C, South Pole), as are small islands (Tristan da Cunha, Easter Island, Lord Howe) and lakes (Superior, Caspian, Titicaca, Qinghai, Victoria, Great Salt Lake). Open ocean is sea. **Floating ice shelves (e.g. the Ross Ice Shelf) are sea.**
  - Land area 28.905% of Earth; 365,088 ERA5 0.25° cells contain land before the 1 km buffer (RESEARCH §8 estimated 28.91% and 367,051 with the buffer).
- **Choice:** use `global-land-mask`, add the GLOBE citation to product attributions, and treat ice shelves as sea unless Riley wants them included (they would need another source).
- **Who:** Riley approved the source ("use the global-land-mask package assuming it works well for our case"); the checks above are the agent's.

### D21. Second Copilot review of PR #1
- **Re-ingesting identical data:** if a store with byte-identical content already exists, it is kept with its original provenance (the run that wrote it); the manifest now records that provenance, plus this run's git commit and config hash under `this_run`. A config or code change that alters the content is refused (never overwritten without Riley). Rejected alternative: treating any provenance change as a conflict, which would make every re-run after an unrelated commit fail.
- **Empty land masks:** a request with no land cells produces a valid empty store (zero-length `cell` dimension; chunks and shards forced to ≥ 1), not a crash.
- **Smoke test:** exits 1 unless every smoke request ends `verified`; the report includes the download summary and an `ok` flag.
- **Configs in the wheel:** `configs/*.yaml` are packaged as `astroseeing/configs`. Lookup order is `$ASTRO_CONFIG_DIR`, then the repo checkout, then the packaged copy. Logs go to `$ASTRO_LOG_DIR`, else `logs/` in a checkout, else the state directory. Checked by building the wheel and loading the configs from a clean virtualenv.
- **Who:** agent.

---

## 2026-09-27 — First session on CT 350 (Claude Code on the CT)

### D22. Land-mask buffer: distance to the nearest point of a land cell
- **Options:** a 30″ cell is in the 1 km buffer if its centre is within 1 km of (a) a land cell's *centre* or (b) the *nearest point* of a land cell (the land cell as an area).
- **Evidence:** both built on the full GLOBE grid (`reports/landmask.md`). (a) 29.066% of Earth's area, 366,305 ERA5 cells kept, 4-neighbours at the equator; (b) 29.131%, 366,604 cells, 8-neighbours at the equator. RESEARCH §8 estimated 29.19% and 367,051 without recording its method; neither variant reproduces it. (b) is "within 1 km of land" taken literally.
- **Choice:** (b), `measure: edge` in `configs/landmask.yaml`. Great-circle distance on a sphere of the WGS84 mean radius (2a + b)/3. ERA5 cells are ±0.125° boxes centred on the grid points; a cell is kept if it holds any land-or-buffer cell. Stores: `/data/astro/static/landmask/*_v1.zarr` (commit a2e97dc). The unbuffered count is 365,100, 12 cells more than the cloud session's 365,088, whose method wasn't recorded (two plausible alternatives give 364,408 and 365,113).
- **Who:** agent (provisional).

### D23. Request size: split to the CDS cost limit (amends D16's fallback)
- **Evidence (smoke test, `reports/cds_smoke_test.json`):** the CDS "cost" of a request is its number of fields (variables × levels × hours × days) whatever the area. ECMWF staff define an ERA5 "item" as one variable on one 2-D field at one level and one time step (forum.ecmwf.int/t/cdsapi-limitations-and-restrictions/1639, 2019). Limits today: 60,000 fields for pressure levels, 121,000 for single levels. A month of a 5×5 box on 29 levels × 5 variables is 107,880 fields, over the limit; single levels (12,648) fit.
- **Options:** D16's stated fallback, day-sized requests (31 per month); or split each month into the fewest runs of days under the limit (2 for pressure levels, 1 for single levels).
- **Choice:** split to the limit (`plan_requests(split=True)`, limits in `configs/era5.yaml: request.max_fields`). It keeps D16's aim (few queued jobs) with ~15× fewer requests than daily; content and verification are unchanged. Partial months are now labelled `first_last` (e.g. `2023-01-01_2023-01-16`) so chunks can never share a store path.
- **Who:** agent (provisional); Riley to confirm, since D16's fallback said "day".

### D24. CDS concurrency: at most 4 in flight; queue-limit rejections are transient
- **Evidence:** the first real run submitted 29 requests at once (a downloader bug: `limit=0` meant "no limit"; fixed in fa1c95a with a regression test). The CDS accepted 5 and rejected 24 with "Number queued requests for this dataset is temporarily limited. Please configure your scripts accordingly". Of the 5 accepted, the CDS ran one at a time, and a single-level request submitted while a pressure-level one ran stayed queued for 15 minutes: one running request per user across datasets. The first half-month pressure-level chunk (52,200 fields) ran 1,669 s (31.3 fields/s); the average of the first 9 was 33 min (26.4 fields/s). I found no published per-user limit, so these are observations, not documented limits.
- **Choice:** keep `--max-active 4` (below the observed 5 accepted). A rejection carrying that message sends the request back to `planned` (the remote job is deleted); any other rejection still fails the request. Rejected jobs raise `requests.HTTPError`, not `ProcessingFailedError`; the backend now records the server's message either way (previously the downloader kept polling dead jobs).
- **Who:** agent.

### D25. The CDS pressure-level time-series dataset is not a substitute for validation boxes
- **Evidence:** `reanalysis-era5-pressure-levels-timeseries` (published 2026-08-07, CC-BY) serves long point time series cheaply, but only on 13 levels (1000, 925, 850, 700, 600, 500, 400, 300, 250, 200, 150, 100, 50 hPa) and without cloud fraction `cc` (catalogue form read 2026-09-27). Our method and every paper we reproduce use the 25 hPa spacing near the surface, and vertical resolution changes Cₙ² directly.
- **Choice:** don't use it for reproductions or calibration. It may serve quick sanity checks later.
- **Who:** agent.

### D26. Running on the CT: root, tmux from conda-forge, repo at /home/astro-seeing
- **Facts:** the CT has one login user, `root`; the repo is at `/home/astro-seeing` (HOME is `/root`, so `~/astro-seeing` in the runbook and `%h/astro-seeing` in the systemd units are wrong here). `systemctl --user` has no user manager for root (no lingering). tmux wasn't installed.
- **Choice:** pixi (user-level installer, runbook §1) and `pixi global install tmux` (conda-forge tmux 3.7c in `~/.pixi`), so nothing was installed system-wide. Long jobs run in tmux with logs in `logs/`. The systemd units are unchanged until Riley decides on a user (question in `reports/ct_first_run.md`).
- **Who:** agent.

### D27. Haslebacher et al.: what their code needs, and what can be reproduced **[ASK]**
- **Evidence (their code at commit 1da3712, `code` branch; paper arXiv:2208.04918):**
  - Inputs: ERA5 u, v, t, z on up to 28 pressure levels (no 70 hPa; the Chile download lists 27, also without 975), hourly, all 24 hours, **1979–2020**, nearest grid point to each site; plus surface pressure to pick the lowest level (the level closest to the site's time-mean ERA5 surface pressure).
  - The in-situ seeing that sets each site's calibration (`mean_insitu`) and all skill scores is **not published**. Their `data` branch holds only skill-score CSVs, trend posteriors and PRIMAVERA IDs. The in-situ data come from observatory archives and private communication (their Table 2).
  - Calibration scales seeing (not J) by mean in-situ / mean ERA5 seeing over all loaded hours. Comparison periods differ from Table 2 (e.g. Paranal 2000–2016 in code vs 2000–2019 in the table). La Palma's lower level is 975 hPa in their site table but 1000 hPa in the paper's Table 4.
- **Consequence:** the approved tolerance "reproduces their published numbers (skill scores ±0.01)" needs their in-situ series. Without it, what can be reproduced is (1) their code vs ours on the same ERA5 input (≤ 0.1%, D19), (2) Table 4's lower levels from ERA5 surface pressure, and (3) the ERA5 trends of Tables A.13–A.14 up to the unknown calibration factor. A full 1979–2020 download for 8 sites is roughly 35–50 GB and, at the measured CDS speed, days to weeks of queue time (`reports/ct_first_run.md`).
- **Who:** open, for Riley.

### D28. Riley's answers to the first CT report (2026-09-27, evening)
- **Haslebacher et al. (D27):** approved: reproduce (a) their code vs ours on the same ERA5 (≤ 0.1%), (b) Table 4's lower levels from ERA5 surface pressure, and (c) a written account of what can't be reproduced and why. This replaces "published skill scores ±0.01" in `reports/phase1_plan.md` §5.
- **Land mask (D22):** Riley doesn't mind which buffer measure. The requirement is "only land plus a small buffer of sea, to include shoreline weather phenomena and smaller islands". D22 stays; small islands to be checked explicitly.
- **Request splitting (D23):** approved ("splitting as you did is fine").
- **CT user (D26):** keep root.
- **ESO ambient data:** approved as a source (CC BY 4.0, ESO acknowledgement).
- **Download schedule:** not decided. Riley asked for a review of the CDS speed first: parallel requests, larger requests, the effect on the global run, and how Haslebacher et al. got 42 years.
- **Later:** Bi et al. PDF (Riley will upload it), TMT login, CDS key rotation, PR to `main`.
- **Who:** Riley.

### D29. Download review (Riley asked: parallel requests, larger requests, the global run, Haslebacher's 42 years)
- **Facts (2026-09-27 evening; RESEARCH §7):** one processing slot per user shared by ERA5 pressure and single levels; one account per user (CDS terms, Art. 2); requests are already 87% of the 60,000-field limit and time scales with fields, not requests (overhead ~10–15 s). The single-level **time-series product runs in its own slot, takes seconds, and matches our data**. The mirrors (NCAR, Google) are whole-globe per hour. Bandwidth 21–47 MB/s.
- **Consequences:** larger requests and extra accounts won't help. Single levels for validation should come from the time-series product (except lcc/mcc/hcc, zust, ishf and tcwv, needed only for the cloud-layer and W71 experiments), so the slot is used only for pressure levels. The global run is ~7.1 M fields (~3.1 days of CDS processing) plus ~13 TB of transfer (~3–7 days at the measured bandwidth); it is not worse than phase 1.
- **Haslebacher et al.'s 42 years:** their scripts send one request per pressure level per year (4 variables, ~35,000 fields) for each site box, and start ~27 downloads at once (one terminal per level), on the old CDS (replaced in September 2024). With today's one slot, that plan is ~5 months for us.
- **Choice:** pending Riley (options in `reports/ct_first_run.md` §8). ERA5-complete (MARS) as a possible second slot is untested: its cost estimator returned HTTP 500s, and a real test is a tape request that can take hours.
- **Who:** agent (facts); Riley (choice).

### D30. Land mask: GLOBE for choosing ERA5 cells; the 30 m Copernicus DEM for pixels (phase 2)
- **Evidence (2026-09-27):** of 22 small islands tested, all from 1 km² up are in the mask (Tromelin 1.0, Surtsey 1.3, Howland, Baker, Johnston, Nightingale, Jarvis, Pitcairn, Clipperton, Midway, Wake, … St Helena, Christmas Island); only Rockall (a 0.001 km² rock) is missing. But GLOBE places some small islands kilometres off: **Norfolk Island is drawn ~9 km east** of its true position (GLOBE centroid 29.027° S 168.043° E vs 29.03° S 167.95° E). Its ERA5 cell is still kept.
- **Choice:** keep GLOBE + 1 km for selecting ERA5 cells (robust at 25 km scale). For the pixel-level mask in phase 2, use the Copernicus DEM (30 m, which we process anyway) and add any island it has that GLOBE lacks to the cell selection. Meets Riley's requirement (D28): land plus a small sea buffer, including small islands.
- **Who:** agent (provisional).

### D31. Phase 1 download schedule: option C (Riley, 2026-09-27)
- **Choice:** option C of `reports/ct_first_run.md` §8, ~10 days of CDS processing for pressure levels:
  - shared areas for co-located sites (Chile: Paranal, La Silla, Tololo, Armazones, Tolar, Tolonchar; Tibet/Qinghai: Ali, Daocheng, Muztagh-ata, Lenghu, Da Qaidam);
  - cloud fraction only where clouds are studied;
  - Priyatikanto's 2002–2021 sampled every 4th day;
  - **night hours only** where every comparison is at night (ESO and TMT DIMM/MASS, O&S SCIDAR);
  - single levels from the CDS time-series product where it has the variables (D29).
- **Exception approved:** night-only downloads for those validation areas, although AGENTS.md says validation boxes keep all hours. Riley was told this when choosing C; the AGENTS.md wording change is his to make.
- **Already running:** the Paranal 5×5 box for O&S's 2016-04..2018-01 continues with all hours. Its 2021–2025 part (180 requests) is `held`, to be replaced by the Chile area.
- **Who:** Riley.

### D32. Unattended running: system-level services, bounded retries, alerts only when retries run out
- **Why:** Riley will close the chat session and wants downloads and notifications to keep going by themselves (2026-09-27).
- **Choice:**
  - The download loop, the ntfy watcher and the nightly manifest export run as **system-level systemd services** (the CT runs everything as root, D26; user units would need lingering). They start at boot and restart after crashes. Units are in `scripts/systemd/system/`, installed by `scripts/install_services.sh`.
  - `scripts/run_boxes.sh` retries failed requests up to 5 times, counts retryable failures as unfinished, and backs off 10 min when a round makes no progress, so a CDS or network outage neither stops nor spins the loop.
  - The watcher alerts only when a request has used up its 5 attempts (earlier failures are retried), and it never says "finished" while a retry is pending. Stalls (3 h without progress), a stopped loop and an unresponsive NAS still alert.
- **Who:** agent, on Riley's instruction.

### D33. Copilot review of PR #2 (first round, 4 findings, all addressed)
- **Refusals (amends D18):** a request that mustn't be stored unmasked now moves to a new **`refused`** state instead of staying `verified`. It is not a failure (never retried or re-downloaded) and not pending work, so the unattended loop doesn't wait on it; the watcher reports it; `astro requeue-refused` puts it back to `verified` once a mask exists. Mask functions signal it with `RefusedUnmasked`.
- **Stale requests:**
  - the watcher's stall clock counts only real progress (a finished download or later) and the plan times of *pending* requests, so holds, cancellations and retries don't hide a stall;
  - a separate alert fires for any request sitting at the CDS for more than 12 h.
- **Smoke-test report:** the split-month cost estimates were added with the current code (estimate calls only: 55,680 and 52,200 of 60,000), marked as added after the original run.
- **First-run report:** the systemd text now describes the D32 services.
- **Who:** agent (fixes), Copilot (findings).
- **Second round (4 more findings, all addressed):**
  - the site-box mask compares longitudes modulo 360, and ingest refuses loudly (a failure, not a silent empty store) if an area's mask doesn't select exactly its site-box points;
  - `notify.env` must be mode 600, like `~/.cdsapirc`;
  - `build-landmask --dry-run` writes no summary unless `--summary-out` is given;
  - the finish estimate counts failed requests that will be retried.
- **Third round (3 findings, all addressed):**
  - ingest refuses undeclared large requests *before* decoding them (`mask_fn.preflight`), so a global day can't be loaded into memory just to be refused;
  - problem alerts are per event (request + time), so a requeue and a new refusal inside one check interval still alert;
  - a queue that drains with failed or refused requests is reported as "finished with problems";
  - the watcher's saved state ignores fields from older versions.
- **Fourth round (3 findings, all addressed):** "finished with problems" is also sent when every request failed or was refused; `max_active` must be ≥ 1; the report's test count is updated (167).
- **Fifth round (4 findings, all addressed):** the installer creates `logs/`; the export and download services require the `/data/astro` mount (`RequiresMountsFor`), and the export checks the NAS answers (child-process probe with a timeout) before writing; the report and plan now show the download schedule as decided (option C) rather than an open question.
- **Sixth round:** no new findings on the diff; one previously missed item fixed (the finish estimate counts downloaded/verified requests still awaiting ingest). Merged after this round.

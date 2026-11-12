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

## 2026-10-17 — Second CT session

### D34. A job the CDS no longer knows (HTTP 404) is submitted again
- **Evidence:** three Tibet requests submitted on 2026-10-12 (`pl/tibet/2019-04-16_2019-04-30`, `…2019-05-01_2019-05-16`, `…2019-05-17_2019-05-31`) returned **404 Not Found** for their job IDs from about an hour after submission. A 3 h stall the same afternoon suggests a CDS-side incident. The downloader logged each 404 as "poll failed, will retry" and polled the dead jobs for 5 days (39,504 polls). The watcher's "stuck at the CDS" alert fired every 12 h, as designed. All other 469 requests completed meanwhile.
- **Choice:** `DatastoresBackend.info` maps HTTP 404 to status `deleted`, which the downloader already treats as GONE: it plans the request again (not counted as a failure) and logs why. Other HTTP errors while polling stay transient. Regression tests added.
- **Outcome:** after the restart, the three requests were submitted again at 10:43 UTC on 2026-10-17 and ingested at 11:14, 12:15 and 12:35 UTC. All 472 requests are now ingested (`reports/validation_downloads.md`).
- **Who:** agent.

### D35. Bi et al. 2023 checked against the PDF (plan task 3)
- **Evidence:** `papers/bi2023_remotesensing.pdf` (Riley, 12 pages; SHA-256 in `papers/INDEX.md`).
  - λ = 550 nm, ε = 5.25 λ^(−1/5) J^(3/5), eq. 4–6 (P in hPa, HMNSP99 coefficients) and Tables 2–3 match RESEARCH §3.1, §4.4 and §6.1.
  - The Rongcheng coordinates in the sea are printed that way in the paper itself (Table 2 and the Figure 1 caption).
  - The paper doesn't say: whether it used pressure or model levels (the text says model levels, Table 1 gives the pressure-level range); which ERA5 hours Table 3 uses; how the troposphere/stratosphere switch is made; or the DIMM site altitudes (these are in its refs [44], [45], [5]).
- **Choice:**
  - RESEARCH §3.1 and §6.1 updated: the unstated points are marked [check], plus the balloon details (29/30/14 profiles; launches in the early morning or late evening local time).
  - The reproduction will try all hours, night hours and the launch hours, and both level types.
  - Our pressure-level downloads for Bi stop at 50 hPa. Measured at Timau (24 stores, 193,536 columns, all 37 levels, Bi's model), the 50–1 hPa slabs add a median 0.7% to J (max 1.2%), that is +0.0024″ of seeing at 550 nm (max +0.0032″). That is far below the ±0.05″ tolerance (D19), so no extra download is needed. Tibet itself wasn't measured: the P² factor in Cₙ² makes the contribution small at any site, but this is an estimate.
- **Who:** agent.

## 2026-10-24 — Wrap-up before the planning pivot

### D36. TMT option A queued; Chile's extra single levels not queued (needs a code change)
- **Riley's answers (2026-10-24) to `reports/validation_downloads.md` §7:** TMT terms approved (Riley registers and saves the login in `/root/.config/astro/tmt.env`); TMT ERA5 option A; PR #3 as the checkpoint; CDS token rotated (new one checked: authentication OK); the AGENTS.md wording is handled in the cloud planning session.
- **TMT option A, checked against what phase 1 needs at those sites:**
  - **Seeing:** z, t, u, v on 29 levels; 50–1 hPa adds ~0.002″ (D35).
  - **Cloud above a height:** `cc` at Mauna Kea, an experiment site. `plan-box` has no variable choice, so San Pedro Mártir gets `cc` too (+0.28 M fields).
  - **Ground-layer options and underground-level masking:** all 17 single-level variables (sp, 2t, 10 m and 100 m wind, zust, ishf, blh, …), night hours.
  - **Terrain experiment:** static z, lsm, sdor for the two new boxes. Chile's static store already covers the Chile rectangle.
  - **Not included:** model levels (a separate experiment).
- **Queued (2026-10-24 21:48 UTC), 146 requests, 4.34 M fields (+20% on the 3.6 M estimate, inside Riley's 25%), ~2 GB:**
  - `astro plan-area chile --start 2006-01-01 --end 2007-12-31 --kinds pl,sl --variables z,t,u,v --hours night` (UTC 23, 0–11): pressure levels 1.10 M fields, single levels 0.16 M;
  - `astro plan-box --region tmt_spm --lat 31.0456 --lon -115.4691 … --kinds pl,sl,static --hours 2-14` (UTC): pressure levels 1.38 M fields, single levels 0.16 M;
  - `astro plan-box --region tmt_mauna_kea --lat 19.833 --lon -155.481 … --kinds pl,sl,static --hours 4-16` (UTC): pressure levels 1.38 M fields, single levels 0.16 M.
  - The Haslebacher et al. San Pedro Mártir and Mauna Kea sites fall in the same 5×5 boxes.
- **Not queued:** Chile's extra single levels (lcc, mcc, hcc, zust, ishf, tcwv). `astro plan-area` ignores `--variables` for single levels, and `plan-box` has no `--variables`. Selecting 6 variables needs a code change, which Riley asked not to write in this session.
  - Queuing all 17 variables instead would be 0.40 M fields (11–30 h), and 11 of them should come from the time-series product. Left for a ticket (`docs/handoff_pivot.md`).
- **Who:** Riley (choices); agent (plan check).

### D37. TMT queue held: the CDS now wants sequential requests and rejects our parallel ones
- **Evidence (2026-10-24, 21:48–22:05 UTC):** within minutes of starting the TMT queue, the CDS rejected 29 jobs (all 24 Chile pressure-level months and 5 single-level months). The message was new: "Maximum number queued requests for this dataset has been reached. Please configure your scripts to request data sequentially". 3 single-level jobs were accepted.
  - Our D24 matcher only knows the old wording ("…is temporarily limited"), so each rejection counted as a failure, and `run_boxes.sh` resubmitted at once.
  - ECMWF announced on 2026-10-22 (forum.ecmwf.int/t/15481, "Data Stores Service protection measures…"): "Submit requests sequentially, rather than in parallel or in large batches", and "Repeated submission of invalid requests may result in your account being disabled". The same week a user reported their account disabled after repeated submit/delete cycles (forum.ecmwf.int/t/15487).
- **What I did:**
  - stopped `astro-boxes`;
  - moved the failed requests back to planned and **held all 143 TMT requests** (`astro hold`);
  - am collecting only the 3 accepted jobs, with a one-off `astro download --max-active 1` (no retries, nothing new submitted), then verify and ingest.
  - Nothing has been resubmitted since 22:05 UTC.
- **Needs a code change (not written; Riley asked for no new code this session):**
  - sequential submission (`max_active` 1 by default);
  - the new wording treated as a queue-limit rejection;
  - a backoff after any rejection (e.g. 30–60 min) with a cap on rejections per day, and an alert when it fires.
  - Then release the holds (`astro release pl/chile/2006` etc.) and start `astro-boxes`.
- **At one request at a time:** expect roughly the 5.6 fields/s measured when only one job was in flight (D34 period), so ~9–10 days for the 4.34 M fields.
- **Also (licence, Riley):** the CDS terms of use change on 2026-10-28 (Art. 1); using the CDS after that date counts as accepting them. Anyone who doesn't accept must tell ECMWF before 27 Oct (forum.ecmwf.int/t/15374).
- **Who:** agent (hold and investigation); Riley (the fix and the terms).

### D38. CDS terms of use of 2026-10-28 accepted (Riley, 2026-10-30)
- **Context:** the CDS terms of use changed on 2026-10-28 (Art. 1); continued use counts as acceptance (forum.ecmwf.int/t/15374, flagged in D37).
- **Choice:** Riley accepts the new terms. Continued use would count as acceptance anyway.
- **Who:** Riley.

### D39. One CDS job at a time: the downloader's gate, backoff and pause
- **Why:** since 2026-10-22 the CDS wants requests one after another, and it may disable accounts that keep sending invalid ones (forum.ecmwf.int/t/15481; D37). In that thread, a user was disabled with "up to two concurrent monthly requests", so one is a hard limit (Riley, 2026-10-30).
- **Options:** (a) keep `max_active` as a setting with default 1; (b) a hard limit of 1, plus a check that the account has nothing else queued; (c) also back off and pause after rejections. Riley asked for (b) + (c).
- **Design** (`download/downloader.py`, state in the manifest):
  - **At most one job queued or running per account, in any dataset.** `Downloader` refuses `max_active` above 1, and changing that needs Riley's OK. Before each submission, our own job is counted from its status, and `active_jobs()` (the CDS job list, status accepted or running) must also be empty. That catches a job left over from a crash, a submission that timed out after the CDS took it, or another process. If either can't be read, nothing is submitted.
  - **Pipelined:** a step polls first, submits the next request as soon as the previous job has finished at the CDS, and only then downloads the finished result. The CDS queue still holds one job.
  - **Rejections:** any job the CDS rejected or failed, and any submit error, is a rejection. Both queue-limit wordings (2026-09: "…is temporarily limited"; 2026-10: "Maximum number queued requests for this dataset has been reached") send the request back to planned without counting as a failure. Other rejections and submit errors fail the request, so it shows in `astro status` and its attempts count; `retry-failed` replans it, but the backoff and the pause still apply.
  - **Backoff:** after a rejection, nothing is submitted for 60 min, doubling with each rejection in the last 24 h. With the pause at 3, that is 60 then 120 min. The 4 h cap only matters if the pause threshold is ever raised.
  - **Pause:** 3 rejections within 24 h pause all submissions until a person runs `astro cds-resume --reason …`. Rejections before the resume no longer count. The notify watcher sends a high-priority alert once, saying what to check and how to resume, and `astro status` shows the pause.
  - **Lost jobs (D34):** a request whose job the CDS loses (HTTP 404, deleted, expired) is submitted again at most twice, then fails. After `retry-failed`, each further loss fails it at once, so the total is bounded.
  - **Can't be bypassed:** the rejections and the pause are rows in the manifest (`cds_rejections`, `cds_control`), so they survive restarts. `run_boxes.sh` no longer passes `MAX_ACTIVE`. `retry-failed` only moves requests to planned. `astro download` submits nothing and returns while backing off or paused. The smoke test runs one at a time too.
- **Counting failed jobs:** a job that failed in processing (not only "rejected") also counts. That is conservative: it costs an hour's pause now and then, against an account that is our only route to ERA5.
- **Tests (`tests/test_cds_gate.py`, fake backend):** one job in flight under random status sequences, poll errors and clock steps (hypothesis; it fails if the gate is removed); both wordings; nothing submitted during a backoff, even after `retry-failed`; the doubling; a stray job at the CDS blocks submission; an unreadable job list blocks submission; a submit error counts; 3 in 24 h pause and alert, and the pause holds until resumed; rejections older than 24 h don't count; lost-job resubmission is bounded; the next job goes in before the finished one is downloaded.
- **Who:** Riley (the rules); agent (the design).
- **Known limits, accepted:**
  - If a submission times out after the CDS has taken it, that job is orphaned: we have no id for it. The job-list check still blocks any parallel submission, so the cost is only that the CDS does that request twice.
  - A request the CDS keeps rejecting for its own reasons trips the pause instead of letting the queue move on. That is wanted: repeated invalid requests are what gets accounts disabled.
- **Review (2026-10-30):** Copilot didn't take the review request on PR #4. The API accepted it, but no request was recorded (on PR #3 it was), so an independent code review was run in its place. It had 10 findings and 8 were fixed: submit errors now fail the request (visible, counted); poll-time rejections count in the run summary; the stall alert is suppressed while paused; `--max-active` accepts only 1; a rejection in the same second as a resume counts; the backoff text matches the code; the lost-job count is commented; one shared test clock. The 2 others are the known limits above.

### D40. `plan-area --variables` for single levels; planning rate from config
- **Why:** `plan-area` passed `--variables` only for pressure levels, so Chile's extra single levels couldn't be planned without all 17 variables (D36, handoff §2). The time estimate it printed used the first-day rate, 26.4 fields/s (D24), which one job at a time (D39) can't reach.
- **Choice:**
  - `--variables` now applies to every kind in `--kinds`. A name the kind doesn't have stops with an error before anything is planned, so a mixed pl,sl plan with one list fails loudly instead of being ignored or half-planned.
  - A subset of a kind's default variables gets its own region suffix, like `@every4d`: e.g. `chile@vars-lcc-mcc-hcc-zust-ishf-tcwv`. Its keys and stores then never collide or mix with full-set requests for the same months (e.g. the 17-variable `sl/chile/2006-*`). A key already planned as a different request is refused before anything is added. The TMT `pl/chile/2006-*` requests (z,t,u,v, D36) were planned before this rule and keep the plain `chile` name.
  - The rate is `request.fields_per_s` in `configs/era5.yaml`, set to 5.6 fields/s. That was measured on 12–17 Oct 2026, when only one of our jobs was running (D34), and it is pressure levels only. I'll update it from the first days of the sequential queue.
- **Review (2026-10-30):** Copilot again took no request, so an independent review ran instead. Fixed: no partial plans, subset regions, and the estimate now says the rate is a pressure-level one. Its other findings were about D39 code already merged, and were either deliberate (submit errors and failed jobs count as rejections, as Riley asked) or minor. They're listed in handoff §6.
- **Who:** Riley (asked for both); agent (details).

## 2026-10-30 — Cloud planning session: switch to Matt Pocock's skills

### D41. Planning skills set up: tickets in GitHub Issues, one decision log
- **Options (tickets):** GitHub Issues; local Markdown in `.scratch/` committed to the repo; another tracker (Linear, Notion, …).
- **Evidence:** both sides must read and update tickets. The cloud session reaches GitHub Issues through its GitHub tools; the CT has `gh` logged in as rrweller. Committed Markdown would need a commit and push for every update, with the cloud session and the CT editing the same files on different branches. The cloud session can't set GitHub's native "blocked by" links (no `gh`, no raw API), but it can create sub-issues.
- **Choice:**
  - Tickets live in GitHub Issues on `rrweller/Astro-seeing` (`docs/agents/issue-tracker.md`). The wayfinder map is one issue labelled `wayfinder:map`; tickets are its sub-issues.
  - Blocking is a `Blocked by: #n` line at the top of each ticket body; that line is the source of truth, and the CT may mirror it as a native dependency.
  - Every ticket carries `runs-on:cloud` or `runs-on:ct`.
  - Default triage labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`).
  - `CLAUDE.md` starts with `@AGENTS.md` and holds the skills' config; AGENTS.md stays Riley's.
  - `docs/decisions.md` stays the only decision log: skills that would write an ADR to `docs/adr/` add a D-entry here instead (`docs/agents/domain.md`).
- **Who:** Riley.

### D42. AGENTS.md wording updated (proposals from `docs/handoff_pivot.md` §4)
- **Applied (Riley approved all six, 2026-10-30):**
  1. Data safety → Downloads: one CDS job queued or running per account (D39, replacing the "at most 4 in flight" of the old proposal, which D37 made obsolete); month-sized validation-box requests split to the CDS cost limit (D16, D23), limits read from config and re-checked before a campaign, because the CDS changes them with its workload (forum.ecmwf.int/t/15337); after a pause, read the CDS announcements and check that one request is accepted before queuing more (the lesson of D37); global and regional runs one day per request unless gate 1 changes it.
  2. What gets stored: night-only validation areas allowed (D31).
  3. Code → Environment: the CDS client (D2).
  4. Environment and Code → Long jobs: repo at `/home/astro-seeing`, root, system-level services (D26, D32), pixi's path.
  5. Working with Riley: planning in cloud sessions, the CT works from GitHub Issues tickets (D41).
  6. A typo ("againast").
- **Evidence for 1:** ECMWF's announcement of 2026-10-22 asks for sequential requests and warns that repeated invalid submissions may get an account disabled (forum.ecmwf.int/t/15481). An ECMWF staff reply of 2026-10-16 says the limits "are changed from time to time according to the current workload of the system" (forum.ecmwf.int/t/15337). Neither thread gives a number. Both were read on 2026-10-30.
- **Who:** Riley.

## 2026-11-05 — Cloud planning session: the forecast track

### D43. A forecast track alongside the historical one, on one shared engine
- **Context:** Riley's experience: Yr said clear, meteoblue's astronomy page showed 10–20% low cloud, and the sky was clear. Riley wants several forecasts side by side for tonight, with seeing computed by the methods of the papers being reproduced, and later a public site (handoff of 2026-11-05 §3). AGENTS.md's phases are historical-only, so this is a new phase [ASK].
- **Options (gate 1 map #6):** pause it; keep it as the historical track and work both in parallel; close it and move its tickets to a forecast map.
- **Evidence:**
  - The physics is shared: both Cₙ² models, the integrals, cloud overlap and calibration already exist in `src/astroseeing/physics/`. The paper reproductions on #6 are what show that physics works, for either track.
  - ERA5 is a reanalysis, so forecasts don't use the CDS and don't compete with the CT's downloads.
  - Global-model seeing forecasts are weak for total seeing: at Paranal, O&S got r = 0.64 for the free atmosphere but 0.30 for total seeing; Ye 2011 reports errors of 0.2–0.4″ (RESEARCH §1, §3.3, §3.5).
  - Kongsberg (59.669° N, 9.652° E; en.wikipedia.org/wiki/Kongsberg) has no astronomical darkness from 22 Apr to 19 Aug, and the Sun never gets below −12° from 13 May to 29 Jul (NOAA solar approximation, 1-minute steps, 2026; 239 nights with ≥2 dark hours, as in RESEARCH §4.1). The night mask would leave the forecast empty for 11 weeks.
- **Choice (Riley, 2026-11-05):**
  1. **Two tracks in parallel, one engine.** The forecast track and the historical track share the physics code; they differ in data and UI. #6 stays open as the historical track.
  2. **Area:** the user picks a place on the map; Kongsberg is the default. Each run computes a fixed large domain (northern Europe first, global once download sizes are known), and picking a place only chooses where to look. Places covered by fewer forecast models show fewer.
  3. **Inputs:** raw output from open forecast models only, never other services' finished forecasts. Each new source is a licence [ASK].
  4. **v1 shows, per forecast model, side by side:** low, mid, high and total cloud each hour; model agreement on cloud class (clear ≤10%, some cloud 10–50%, cloudy >50% total cloud; placeholders, in config). No claim to beat Yr or meteoblue; a combining method comes later.
  5. **Seeing:** both Cₙ² models (O&S K = 6 as the main figure, Tatarskii + HMNSP99 in the detail), per forecast model with enough pressure levels, plus 200 hPa wind and the height of the most turbulent layer. Labelled "uncalibrated" until the historical track's calibration (#15) exists.
  6. **Hours:** all 24, in local time (stored in UTC), shaded for daylight, twilight and dark time. The night mask stays a historical-track rule. A night with no dark time says so and still shows cloud and seeing.
  7. **Moon:** rise, set, phase and hourly altitude. No sky-brightness model; "not now: moonlight" still applies to the historical layers.
  8. **Windward/lee seeing:** later, after a research ticket. v1 uses model-cell values or the height-only method (RESEARCH §5).
  9. **Hosting:** private, on CT 350 as its own systemd service, writing to `/data/astro/forecast/` and logging downloads in the manifest. Each run's derived hourly values for the default area are kept indefinitely (the record a combining method will need); raw downloads are deleted once processed. Later public via Pangolin on Riley's domain. Free sources first; paid only if nothing free has the data, cheapest first.
  10. **Globe display:** two throwaway prototypes (an hourly time slider, and a "tonight" summary map) before the spec. Seeing is never blended between hours.
  11. **Seeing measurements:** research which observatory, amateur or citizen-science sources measure seeing and could validate either track.
  12. **AGENTS.md:** the mission names both products; the forecast track gets milestones F1 (Kongsberg default, multi-model timeline, private), F2 (any place in the domain, the globe), F3 (global, public); phases 1–3 stay as the historical track. Diff to follow for Riley's approval.
- **Who:** Riley.

### D44. Forecast sources, levels, F1 area, storage, and seeing checks
- **Evidence:** `docs/research/forecast-sources.md` and `docs/research/seeing-measurements.md` (branches `research/forecast-sources`, `research/seeing-measurements`; primary sources read 2026-11-05). The prototype is on branch `prototype/forecast-views`.
- **Choice (Riley, 2026-11-05):**
  1. **Sources (licence [ASK], approved):**
     - NOAA GFS 0.25° (US open data);
     - DWD ICON-EU (CC BY 4.0);
     - MET Norway MEPS (CC BY 4.0 / NLOD);
     - ECMWF IFS open data 0.25° (CC BY 4.0).
     - Only raw output. No paid ECMWF tier (cheapest band €500/yr). IFS is 3-hourly, so its in-between hours stay blank.
     - **Riley prefers global sources**, so the same ones apply everywhere. Where only a regional source has what's needed, blend it on the globe, and the table shows which sources cover the clicked place. Every source must carry the data the site needs.
  2. **Seeing levels:** pressure levels for every model in v1, with each model's level count shown beside its seeing (GFS 39, ICON-EU 20, MEPS 13, IFS 13 between 1000 and 50 hPa). A model-level path (MEPS 65, ICON-EU 74) is a later ticket, tied to the historical track's pressure-vs-model-levels experiment.
  3. **F1 area and cadence:**
     - F1 computes the box 4.65–14.65° E × 54.67–64.67° N around Kongsberg;
     - four runs a day per model (00/06/12/18 UTC);
     - F2 widens the area once timings are measured.
  4. **Storage (NAS space is shared with the historical track):**
     - download only the fields needed;
     - raw files go to `/staging` and are deleted as soon as the derived values are computed and verified;
     - keep computed values only (retention: D45).
  5. **Paranal as a seeing check in F1:** forecast it with the global models, compare each night with ESO's DIMM and MASS (already approved, D28), and archive the comparison.
  6. **Other monitors** (Maunakea MKWC, ING R2D2, Calar Alto): **internal verification only, no permission e-mails.** Never published or redistributed. Riley expects to stop using them once the models are verified.
  7. **Seeing at Kongsberg:** nothing local for F1. A research ticket on a DIY DIMM with Riley's own telescope and camera. A commercial monitor would be an [ASK].
  8. **Attribution (when public):** one "Data sources" panel with each provider's exact wording, plus a short credit beside each model's row.
  9. **Prototype verdict:** layouts and visuals approved in general; UI details and wording come later. **B (tonight summary map) is the landing view, C's table opens when a place is clicked, and A's hour slider is an optional layer.**
- **Who:** Riley.

### D45. Global model families, blending, retention, and how the two tracks share the work
- **Evidence:** `docs/research/forecast-sources.md`. Of the D44 sources, only GFS and IFS are global. DWD's ICON global is the only other free global source with profiles: ~13 km icosahedral grid, 17 pressure levels 1000–50 hPa, total/low/mid/high cloud, hourly to 78 h, CC BY 4.0, ~9.3 GB per run as whole-globe files. AIFS is 6-hourly; the UK Met Office feed has stopped and is CC BY-SA.
- **Choice (Riley, 2026-11-05):**
  1. **ICON global approved** (licence [ASK]; same DWD terms as ICON-EU), from F2 on. F1's box lies inside ICON-EU.
  2. **A forecast model is a family.** A regional version and its global parent (ICON-EU, ICON) are one forecast model; each place uses the finest version that covers it.
  3. **Model agreement, the globe and the verdict count the global families only** (GFS, IFS, ICON: 3 everywhere), so the map has no seams and the globe and table agree. Regional-only models (MEPS) appear as extra rows in the table, marked "regional, not counted".
  4. **Blending:** a regional version fades into its global parent across a 2°-wide band inside the regional domain's edge. Cloud fractions and J are blended on a common grid, and seeing is computed from the blended J, never blended itself. The width can be tuned in F2.
  5. **Retention:**
     - raw downloads are deleted once derived values are verified;
     - for each place (Kongsberg, Paranal, and any saved later), every run's hourly values per model are kept forever: cloud layers, J and seeing, 200 hPa wind, most turbulent layer;
     - for area grids, only the latest run of each model, plus each day's tonight summary map for 7 days. If space gets tight, the 7-day summaries go first.
     - Sizes *[estimate, from grid sizes]*: ~46 KB per place per day (~17 MB/year); F1 grids under 1 GB; a global F3 ~1 GB per model run. Replace with measured numbers in F1.
  6. **Who does what:** cloud sessions put F1 first (code only: no CDS, no NAS). CT sessions take historical-track tickets on data already on the NAS while the downloads run.
- **Who:** Riley.

### D46. AGENTS.md wording for the forecast track (proposal in `reports/agents_md_forecast_proposal.md`)
- **Applied (Riley approved all seven, 2026-11-05):**
  1. Mission: two products on one shared engine (D43).
  2. [ASK] before adding a forecast or seeing-measurement source beyond D44/D45.
  3. Storage: forecast downloads to `/staging`, raw deleted once derived values are verified, retention per D45; the night mask is historical-only.
  4. Validation-only monitors (MKWC, ING, Calar Alto) for internal checks; anything published uses ESO's data or our own.
  5. The forecast pipeline under Architecture.
  6. "Forecast track: milestones" (F1–F3, each approved before the next), and phases 1–3 renamed "Historical track: phases and gates" with their text unchanged.
  7. Decisions already made: forecast data sources; Moon times in the forecast.
- **Who:** Riley.

## 2026-11-05 — Cloud planning session: seeing in F1

### D47. Seeing in F1: observer height, limits, ground layer, numbers and labels (map #20, ticket #21)
- **Evidence:**
  - Ground heights at Kongsberg (59.669° N, 9.652° E), read from the 2026-11-05 00 UTC runs: Copernicus GLO-30 **162 m** (the town is in the valley); GFS `HGT:surface` 327 m (point 59.75° N 9.75° E); IFS open-data `z`/g₀ 261 m (same point); ICON-EU `HSURF` 347 m (59.688° N 9.625° E); MEPS `surface_geopotential`/g₀ 231 m (59.660° N 9.662° E). In the 0.25° cell around the town, GLO-30 runs 61–829 m (median 322 m).
  - GFS surface pressure there was ≈992 hPa, so 1000 hPa is below ground in every model. Lowest level above the model ground: GFS 975, ICON-EU 950, MEPS and IFS 925 hPa, roughly 0.15, 0.35 and 0.55 km above it *[estimate]*.
  - Ground-layer inputs for W71: GFS has `SHTFL` and `FRICV`; ICON-EU has `ashfl_s` and the momentum fluxes `aumfl_s`/`avmfl_s`; IFS open data has `ewss`/`nsss` but **no heat flux** (step-0 index, 2026-11-05 00z); MEPS not checked.
  - Free atmosphere vs total at Paranal: r = 0.64 vs 0.30 (O&S 2018; RESEARCH §3.3).
  - Effective turbulence altitude: Kornilov et al. 2007 §2.1 (arXiv:0709.2081) give θ₀ = 0.31 r₀/H̄, with H̄ the "Cₙ²-weighted average … altitude above site (Roddier, 1981)". From RESEARCH §4.5, H̄ = [∫Cₙ² h^(5/3) dh / ∫Cₙ² dh]^(3/5) and θ₀ = 0.314 r₀/H̄ ((0.423/2.914)^(3/5) = 0.3141). ESO's MASS data carries `MASS Turb Altitude [m]` (`docs/research/seeing-measurements.md`); how ESO computes it is *[check]* in the Paranal comparison ticket.
- **Choice (Riley, 2026-11-05):**
  1. **Observer height:** each place's real elevation from the DEM (GLO-30), raised to the model ground where it lies below it (counted, never silent). Kongsberg town (162 m) is below all four model grounds, so its values are at each model's ground.
  2. **Limits:** from the lowest pressure level above the model ground up to 50 hPa. Levels with p > surface pressure are masked and counted. The gap between the model ground and that level is not filled; its depth is shown per model.
  3. **Ground layer: none in F1** ("straightforward calculations directly from the research papers"; better ground-layer methods come later). Exception: Paranal also gets a second series with O&S 2018's own relocation of the model's lowest 1 km, as the paper did.
  4. **Numbers, for both Cₙ² models (O&S K = 6 and Tatarskii + HMNSP99):** free-atmosphere seeing (above observer + 1 km), total seeing, and the effective turbulence altitude H̄ in km above the observer, over the column from the observer up. **Headline: O&S free-atmosphere seeing.**
     - H̄ **replaces D43 item 5's "height of the most turbulent layer"** (Riley delegated the definition to the agent's research): it is a standard published quantity, it can be checked against ESO MASS, and it doesn't jump with each model's level placement as a single "most turbulent slab" would.
  5. **Labels:** every seeing value carries (1) "uncalibrated", (2) the Cₙ² model, (3) the forecast model's level count (GFS 39, ICON-EU 20, MEPS 13, IFS 13), (4) the observer height used, including the raise to the model ground, (5) for total seeing, "no ground layer; the column starts N km above the model ground", (6) for free-atmosphere seeing, "above observer + 1 km". Items 1–2 also sit on the headline figure. Exact wording comes with the UI (D44 item 9).
  6. **Historical-track defaults kept:** unstable layers set to zero and counted per model (D5); WMO lapse-rate tropopause for every model (GFS's own tropopause not used); 500 nm, zenith, exact 5.307 form.
- **Who:** Riley (items 1–3, 4's headline, 5, 6); agent (H̄ as the definition in item 4, delegated by Riley).

## 2026-11-06 — Cloud planning session: the F1 verdict

### D48. F1 verdict and model agreement: the exact rules (map #20, ticket #22)
- **Evidence:**
  - Prototype rules: `tonight()` in `web/prototype-forecast-views/core.js` (branch `prototype/forecast-views`) counts dark hours, falling back to Sun below −12°, then below the horizon. An hour is "mostly clear" when `count.clear * 2 > n` over the models that cover the place. Its seeing figure is a median of per-hour cross-model medians.
  - Value timing (`docs/research/forecast-sources.md`): GFS publishes total and low/mid/high cloud both instantaneous and as 6-hour averages. ICON-EU, MEPS and IFS values are instantaneous. IFS open data is 3-hourly (steps 0–144 h every 3 h).
  - Latency after run time: ICON-EU +2.7–3.0 h, MEPS +2.3–4.1 h, GFS +3.6 h, IFS +7.6 h (0.25°). So just before its next run lands, an IFS run is normally up to ~14 h old.
  - Seeing ∝ J^(3/5) is monotonic in J, so the median of an odd number of seeing values equals the seeing of the median J.
- **Choice (Riley, 2026-11-06):**
  1. **Hour:** a forecast model's instantaneous value at hh:00 UTC stands for hh−0:30 to hh+0:30. The hour's Sun class is the Sun's altitude at hh:00. GFS uses its instantaneous cloud fields, never the 6-hour averages.
  2. **Counted hours:** the dark hours (Sun below −18°) of Tonight. Only when Tonight has **zero** dark hours, fall back to hours with the Sun below −12°, then below the horizon (−0.833°). The verdict names the basis. A short dark time (even 1 hour) stays the basis.
  3. **Past hours:** the verdict counts from the current hour to the end of Tonight. The current hour is the one containing now (a step at hh:00 counts until hh:30). Past hours are greyed in the table and not counted.
  4. **Model agreement:** per hour, over the global families (GFS, IFS, ICON; ICON-EU in the F1 box) that have a value for that hour:
     - **mostly clear** when more than half of them put it in the clear class, with at least 2 families;
     - fewer than 2 families: **incomplete**, counted as neither clear nor not clear;
     - each hour also gets a majority class (clear, some cloud or cloudy), or **split** when no class has a strict majority;
     - the table shows count and denominator ("2/2 clear", "2/3 clear");
     - nothing is carried forward or filled: IFS's in-between hours stay blank (D44).
  5. **Runs:** each family uses its latest complete, verified run, and the page shows each run's time and age. A run more than **24 h** past its run time is **stale**: shown, but not counted. A partial run counts only for its verified steps; its missing steps are missing hours under item 4.
  6. **Cloud classes:** keep D43's placeholders (in config): clear T ≤ 10%, some cloud 10% < T ≤ 50%, cloudy T > 50% of total cloud, classified on the **unrounded** value. Revisit with evidence from the Paranal comparison and Kongsberg nights.
  7. **Seeing in the verdict:** one value per counting global family, its median O&S free-atmosphere seeing (D47 headline) over the counted hours, shown as a range ("0.5–0.8″, O&S, free atmosphere, 3 models", "uncalibrated"). The median is taken on J and converted to seeing (for an even count, the mean of the two middle Js). A family with no seeing for any counted hour drops out of the range. If none has seeing: "Seeing: no model has it tonight".
  8. **Template** (wording final with the UI, D44 item 9; the rules are fixed here):
     - **headline:** "x of n dark hours look clear on most models". It says "left" once Tonight has started, names the fallback basis when used ("night hours (Sun below −12°)", "(Sun down)"), and adds "(k hours incomplete)" when there are any;
     - **strip:** consecutive counted hours merged into chips (Clear, Some cloud, Cloudy, Split, Incomplete), in local time;
     - **meta line:** the seeing range with "uncalibrated", the basis, Moon rise, set and phase, and each run with its age, stale runs marked "stale, not counted".
  9. **MEPS:** a separate, visibly secondary line under the headline, "MEPS (regional, not counted): x of n clear", using the same counted hours and the clear rule on MEPS alone. It is not in the strip, the counts or the globe (D45 item 3).
  10. **Nothing to count:**
      - counted hours over before sunrise: "Dark time ended at hh:mm"; the table stays, and Tonight still changes at sunrise (glossary unchanged);
      - every remaining counted hour incomplete: "Not enough models for a verdict: …", naming each family's state (stale, missing), with no counts.
  11. **Landing map (B):**
      - clear layer: the headline count (mostly clear counted hours left tonight), computed by exactly these rules; hatched where there are no counted hours, shaded differently where all are incomplete;
      - seeing layer: a model picker (default GFS, the most levels) showing that family's median per item 7;
      - dark-hours-left layer.
  12. **Glossary:** Counted hours, Mostly clear, Incomplete hour, Stale run and Verdict added to `CONTEXT.md`.
- **Testability:** each item is meant to be checked against a hand-made night: given Sun altitudes, per-family total cloud and J per hour, and run times, the expected counts, chips, range and texts follow uniquely.
- **Who:** Riley (all items; agreed in a grilling session on ticket #22).

## 2026-11-10 — Cloud planning session: fog, and a general tool

### D49. Fog and low cloud in the forecast, and the forecast is a general tool (map #20, research ticket #31)
- **Context:** Riley saw Yr forecast a clear night while meteoblue showed nearly 100% low cloud, and meteoblue was right. On another day, a clear Kongsberg had thick fog in the Skollenborg–Darbu valley. Riley asked whether fog can be predicted from terrain and other weather signals with established, verified science, and set the rule: nothing meteorologists can't do.
- **Evidence:** `docs/research/valley-fog.md` (branch `research/valley-fog`; key sources re-checked by the main session).
  - Yr's 2–3-day forecast for Norway is MEPS; meteoblue's Kongsberg model list has no MEPS.
  - MET Norway's verification reports document MEPS under-forecasting low stratus under subsidence inversions (METinfo 20/2026), with IFS "usually" closer in those cases, and missing inland radiation fog at 1 h lead time (METinfo 14/2023).
  - ECMWF FUG §9.4.1: 10 km models "cannot be expected to handle" patchy fog; site skill "can be very low".
  - Established elsewhere, each with limits:
    - the models' own fog and visibility outputs (low site skill);
    - statistical post-processing at stations with long observation records (e.g. NOAA LAMP, "a statistical system", with ceiling and visibility guidance for "over 2000 stations", vlab.noaa.gov/web/mdl/lamp);
    - observation-threshold nowcasts (hours, not tonight);
    - satellite detection of existing fog.
  - **Not established:** forecasting valley fog from terrain plus model output. DEM cold-air-pool maps are verified for minimum temperature only, not fog, and sub-km models are research-grade with valley biases.
- **Choice (Riley, 2026-11-10):**
  1. **A general tool, not a Kongsberg predictor.** The forecast track must work the same way for every place on the globe. Better regional models or data are used wherever they exist (D44, D45: finest version of each family, regional-only models as extra rows), accepting that coverage differs between regions. No method, threshold or feature is specific to a town or small region. Kongsberg (and its box) is the test location while building F1, and Riley's own observations there are test data.
  2. **D45 item 3 and D48 unchanged:** the verdict counts total cloud from the global families only. The evidence doesn't favour counting MEPS for low cloud: its documented gap is exactly low stratus and fog.
  3. **Fog signals row:** per forecast model and hour, the model's own fog, visibility and low-cloud outputs, wherever that model provides them, labelled experimental and **not counted** in the verdict or the map's clear layer. Models without a field show it as absent, never filled. For the F1 sources (fields as listed in the research, section 3):
     - MEPS: `fog_area_fraction`, `visibility_in_air`, `low_type_cloud_area_fraction`;
     - ICON-EU: `VIS`, `WW` codes 45/48, `CLCL`;
     - GFS: `VIS`, `LCDC`;
     - IFS open data: `lcc` and the 2 m dewpoint depression.
     - No combined fog score until one has been verified.
  4. **Terrain caveat, computed per place:** wherever a place's real elevation lies below a model's ground (D47 item 1 already finds this), the page says by how much, and that fog or cold air pooling in terrain below the model ground is not forecast by that model. The same rule applies everywhere; nothing is written for one town.
  5. **No terrain-based fog prediction:** unresolved science, so not built.
  6. **Fog log (test data):** Riley logs observed fog and low-cloud nights (date, time, place, what Yr and meteoblue showed, what happened) while F1 is tested. It is used to judge whether any model's fog signals are worth showing more prominently. It is not a product feature.
  7. **Later, as research tickets (F2 or after), each general rather than local:**
     - statistical fog and visibility post-processing wherever station records allow (the established LAMP-style route), using station observations as a new source [ASK];
     - verification of fog signals against satellite fog and low-stratus products (e.g. EUMETSAT NWC SAF; other regions need their own satellites), also a new source [ASK].
- **Who:** Riley (all items). The agent drafted the wording of items 3 and 4 from Riley's direction.

## 2026-11-12 — Cloud session: measurement-only CDS requests

### D50. Measurement-only requests: a `measured` state, and their turn by hold/release (ticket #10)
- **Why:** ticket #11 needs the cost and transfer time of one global hour (29 levels × z, t, u, v, cc = 145 fields, ~300 MB) at one CDS job at a time. A global request can't be ingested without a land/night mask (D18), so ingest would refuse it and the watcher would raise a "refused" alert (D33).
- **Options (marking):** a region-name convention only; a `purpose` column on the request. **(After verify):** leave it `verified`, which `run_boxes.sh` and the watcher count as pending forever; or a terminal state. **(Queue turn):** the downloader submits measurement requests first; or no code, using `astro hold` / `astro release`.
- **Choice:**
  - Requests carry `purpose` (`store`, the default, or `measure`). Opening a manifest made by an older version adds the column with `store` for every existing row; nothing else changes.
  - `astro plan-measure` plans one (default the whole globe, the kind's default variables and levels, region `measure-<label>`, default `measure-global`, so keys never mix with stored requests).
  - It downloads under the D39 gate like any request. Verify checks it fully and moves it straight from `downloaded` to the new terminal state **`measured`** in one transition, so it can never sit in `verified` for ingest. Nothing is written under `/data`, and the raw GRIB stays in `/staging` (never deleted automatically, because there is no ingest).
  - The watcher counts `measured` as progress, never as pending work or a refusal.
  - **Queue turn:** no code. The CT holds the other planned requests by key, then releases exactly those, with the TMT release timer stopped meanwhile (`docs/ct_runbook.md` §7).
- **Tests:** `tests/test_measure.py`, against the fake CDS backend: the CLI end to end (one submission, `measured`, no store, timings and verification recorded), the watcher (no alert, not pending, counts as progress), the planner (a global hour is 145 fields), and the upgrade of an old manifest.
- **Who:** Riley (the test points and the hold/release route, 2026-11-12); agent (the design).


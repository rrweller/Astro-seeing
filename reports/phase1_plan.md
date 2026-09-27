# Phase 1 plan

- **Status:** approved by Riley (D16, D19, D20); work continues on the CT. Measured CDS numbers and the download-schedule question are in §6.0 (2026-09-27).
- **Written:** 2026-09-27, from a cloud session with no access to the CT, `/data`, `/staging` or the CDS.
- **Decision log:** `docs/decisions.md` (D1–D21). **Commands for the CT:** `docs/ct_runbook.md`.
- **Tags:** *[estimate]* = my arithmetic, to be replaced by measurements; **[ASK]** = needs Riley.

---

## 1. Summary

- **Done here, tested:** the bootstrap (pixi environment and lock, repo skeleton, `.gitignore`), the physics module, darkness, and the download → verify → ingest → cleanup pipeline. 97 tests pass, `ruff` is clean.
- **Every known-answer value in RESEARCH §4.9 is reproduced** to the precision printed there.
- **Darkness matches Skyfield:** crossings within 3.7 s, dark minutes within 0.96 min (9 sites × 6 dates).
- **Checked against the PDFs:** several RESEARCH.md details changed (§3 below). The Bi et al. PDF could not be fetched here, because MDPI refuses this container.
- **Not done (needs the CT):** fetch the papers there, clone Haslebacher's code, the CDS smoke test, and every data task. Scripts and exact commands are in `docs/ct_runbook.md`.
- **Push:** the session could not push to GitHub (no write access). The work is on branch `claude/awesome-goodall-yadxpa` as local commits and in a git bundle; `docs/ct_runbook.md` §0 covers both.
- **Riley's answers (2026-09-27):** month-sized requests for validation boxes (D16), tolerances approved (D19), land mask from `global-land-mask` (D20). Work continues on the CT (`docs/handoff_ct.md`).

## 2. What exists now

| Area | Module | What it does | Tests |
|---|---|---|---|
| Physics | `physics/column.py` | Slabs between valid levels; underground levels masked and counted | structural + masks |
| | `physics/cn2.py` | Tatarskii + HMNSP99 (Bi form and Priyatikanto's printed form); Osborn–Sarazin with a choice of unstable-layer rule | §4.9 values; stable form = eq. 7 |
| | `physics/tropopause.py` | WMO lapse-rate tropopause, vectorised; checked against a reference loop | hypothesis |
| | `physics/integrate.py` | Exact J, J(h) with partial slabs, θ₀ and V₀ moments | monotone in h, adding a layer never lowers J |
| | `physics/optics.py` | r₀, ε (ours 0.98; Bi 5.25; Haslebacher 0.976), λ scaling, θ₀, τ₀, V₀ | §4.9 values, round trips |
| | `physics/cloud.py` | C(h) with random, maximum and max-random overlap | C(h) never increases with h; rules ordered |
| | `physics/groundlayer.py` | O&S relocation for any h (D7); W71 | equals O&S at the site, no double counting |
| | `physics/modellevels.py` | Model-level heights (Simmons–Burridge) | isothermal exact; bottom subset = full column |
| | `physics/profile.py` | Levels → Cₙ² → J, J(h) in one call, for any paper's constants | end to end |
| Darkness | `solar/sun.py`, `solar/darkness.py` | Sun table from Skyfield; dark minutes per night; −12° night mask for ingest | vs Skyfield `dark_twilight_day` |
| Data | `manifest.py` | SQLite state machine and event log; refuses NFS; NFS-safe export | idempotency, compare-and-set |
| | `download/` | CDS request builder (keys checked on the live forms); resumable async downloader | fake CDS: resume, reject, expire, truncate |
| | `verify/grib.py` | Field count, every var × level × time exactly once, grid, missing/NaN counts (missing allowed only for `cbh`, D17) | drop, duplicate, shifted grid, bitmap, cbh gaps |
| | `ingest/` | GRIB → Zarr v3 (sharded), temp → read-back → fsync → rename → re-verify; land-cell layout with counted night mask | tamper, overwrite, failed write |
| CLI | `astro` | `plan-box`, `download`, `verify`, `ingest`, `cleanup-raw`, `retry-failed`, `export-manifest`, `cds-smoke-test`, `status` | end to end on fake CDS |

## 3. What checking the sources changed

Details in D15 and RESEARCH.md (all edits dated 2026-09-27):

- **O&S split height:** 1 km above the observatory (their §5.7 and Fig. 9), not "about 1–2 km". Their Tables 2–3 confirm RESEARCH's statistics; ECMWF median seeing at Paranal is 0.62″ total, 0.41″ free atmosphere and 0.45″ ground layer (SCIDAR: 0.61″, 0.34″, 0.42″).
- **Haslebacher et al.:** they use **ε = 0.976 λ/r₀** at 500 nm, not 0.98, with Euler-forward integration. Their Table 4 lower integration levels are now in `configs/sites.yaml`.
- **Priyatikanto et al.** interpolated linearly to 5 hPa steps before computing. Their printed equations differ from §4.4 in three places: the sign of a₃, ∂θ/∂h with P/T², and θ with 100 hPa. All three variants are implemented, so the reproduction can find which one gives their 0.79″.
- **TMT Table 2** checked; Mauna Kea 13N θ₀ = 2.69″ filled in.
- **ERA5:** all variable names are on the live CDS forms. The CDS attribution wording is copied from the dataset pages (my first draft of it, written from memory, was replaced before commit).
- **Nights per year with ≥2 h darkness**, measured: 365.2 / 349.6 / 308.8 / 268.0 / 237.2 / 210.6 at 45 / 47.5 / 50 / 55 / 60 / 65°. The §4.1 estimates were 1–3 nights high at 55–65°.
- **Still unverified:** the Bi et al. PDF (§3.1, §4.4); whether c_p = 3.5 R_d and T_v = T(1 + 0.608q) match ECMWF's own recipe; the cos ζ factor in RESEARCH's τ₀ formula (our product is zenith-only, so it doesn't matter yet).

## 4. Tasks and order

| # | Task | Where | Needs | Output |
|---|---|---|---|---|
| 1 | Bootstrap, tests | CT | — | `logs/bootstrap.log` (97 pass) |
| 2 | Papers + Haslebacher code | CT | — | `papers/INDEX.md`, `external/haslebacher.COMMIT` |
| 3 | Verify Bi et al. against RESEARCH §3.1/§4.4 | agent | step 2 | RESEARCH fix or note |
| 4 | CDS smoke test | CT | Riley: `~/.cdsapirc`, licences | `reports/cds_smoke_test.json` |
| 5 | Update this plan with measured queue time, throughput and cost limits | agent | step 4 | revised §6 |
| 6 | Read Haslebacher's code: inputs, periods, levels | agent | step 2 | their data volume → **[ASK]** if over 50 GB |
| 7 | Land mask (1 km + 1 km buffer) and cell list; check the 367,051 estimate | agent | source decided: `global-land-mask` (D20) | `static/landmask` + report |
| 8 | Downloads for validation boxes (§6 table), month-sized requests (D16) split to the CDS limit (D23), in this order: Paranal (O&S + ESO 2021–2025), Timau/Eltari, Bi's 7 sites, TMT, Haslebacher. **Paranal running since 2026-09-27; the rest waits for the §6.0 decision [ASK]** | CT | smoke test done | Zarr stores + manifest |
| 9 | Reproductions, one notebook each: Haslebacher (their code, then ours) → Bi → Priyatikanto → O&S | agent | 6, 8 | notebooks + golden tests |
| 10 | Model levels (ERA5 complete): ~1 year, 3 boxes (Paranal, Mauna Kea, La Palma) | CT | licence | pl-vs-ml experiment |
| 11 | Experiments (AGENTS phase 1 step 5) | agent | 8–10 | one recommendation each |
| 12 | Calibration on ESO 2021–2025 + TMT, held-out years | agent | Riley: TMT login **[ASK]** | fitted K and skill |
| 13 | Good-night proposal **[ASK]** | agent | 11, 12 | proposal with evidence |
| 14 | Phase 2/3 projections from measured numbers | agent | 4, 8 | `reports/phase1.md` (gate 1) |

## 5. Tolerances: what counts as "matching" (RESEARCH §11 Q10) **[ASK]**

Proposed before any reproduction runs, so they can't be tuned to the results:

| Target | Criterion |
|---|---|
| Known-answer tests (§4.9) | Value rounds to the printed digits. **Met.** |
| Darkness vs Skyfield | Within 1 minute. **Met** (3.7 s crossings, 0.96 min counts). |
| Haslebacher: their code on our ERA5 | ~~Reproduces their published numbers (skill scores ±0.01)~~ Not possible: their in-situ data are unpublished and 1979–2020 is ~5 months of CDS time (D27). **Replaced (Riley, D28):** their code vs ours (row below), their Table 4 lower levels from ERA5 surface pressure, and a written account of what can't be reproduced. |
| Haslebacher: our code vs theirs, same inputs | Monthly mean seeing within 0.1% (numerical noise only). Settings: 0.976, 500 nm, k per site, Table 4 lower level, 28 levels without 70 hPa. |
| Bi et al. | Each site's median and quartiles within ±0.05″ of their ERA5 column (§6.1), with pressure and/or model levels. If fewer than 5 of 7 sites match, every difference is explained. |
| Priyatikanto et al. | Timau ERA5 median 0.79″ ± 0.03″, with at least one printed-equation variant; seasonal pattern matches qualitatively (best in March and December). The Eltari ratio (0.76) needs their radiosondes; reproduce it only if BMKG data turn out to be obtainable. |
| O&S | Not reproducible exactly (06/18 UT forecasts, SCIDAR). In O&S mode (K = 6), our Paranal medians are within ±0.1″ of their ECMWF column: 0.62″ total, 0.41″ free atmosphere, 0.45″ ground layer (Table 3), over the SCIDAR campaign dates. |
| Calibration (ESO 2021–2025, TMT) | On held-out years/sites, nightly-median bias ≤ 0.10″ for free atmosphere and ≤ 0.15″ for total. Report RMSE and r but don't gate on them (O&S found r = 0.64 and 0.30). |

## 6. Data volumes and requests

### 6.0 Measured on the CT, 2026-09-27 (supersedes the estimates below where they differ) **[ASK]**

Sources: `reports/cds_smoke_test.json`, the first Paranal downloads, decisions D23–D24; details in `reports/ct_first_run.md` §7–8.

- **CDS cost = number of fields** (variables × levels × hours × days), whatever the area. Limits: 60,000 per request (pressure levels), 121,000 (single levels). A month of a 5×5 box with 29 levels × 5 variables is 107,880, so each month is **2 pressure-level requests + 1 single-level request** (D23).
- **Processing speed: 26.4 fields/s** on average (9 half-month files of 52,200 fields, 27–45 min each; single levels 16.9 fields/s), **one request at a time per user, across datasets**; the CDS rejects queued requests beyond about 5 per dataset. Processing, not bandwidth, is the bottleneck for boxes: a 5×5 box costs the CDS as much as the whole globe per field.
- **Bytes: 0.60 MB per 5×5 box-day** (GRIB1, 16-bit; ~153 B per field), vs 0.8 MB estimated. Volume is not a concern: the plan's list is ~11 GB.
- **Time: the plan's list is ~72 M pressure-level fields ≈ 37 days of CDS processing including single levels**, vs "1–3.5 days" below. Over the 24 h threshold, so the schedule needs Riley's decision. Options (`reports/ct_first_run.md` §8):
  - **A (as planned):** 72 M fields, ~37 days, 11 GB.
  - **B (recommended):** shared rectangles for co-located sites (Chile: Paranal, La Silla, Tololo, Armazones, Tolar, Tolonchar; Tibet/Qinghai: Bi's five western sites); `cc` only where cloud work is planned; Priyatikanto's 20 years sampled 1 day in 4. 35 M fields, ~18 days, ~54 GB of GRIB.
  - **C:** B plus night hours only for the DIMM/MASS calibration targets (ESO, TMT). ~24 M fields, ~12 days; needs an exception to "validation boxes keep all hours".
- **Running meanwhile:** the Paranal 5×5 box (O&S 2016-04..2018-01 and ESO 2021–2025; 2,497 box-days, ~4.5 CDS-days). It is in every option. Nothing else is queued.

### 6.1 Original estimates (cloud session) *[estimate]*

**What this data is for.** Before scaling up, phase 1 checks our seeing calculation against published papers and observatory measurements (AGENTS.md phase 1 step 4). That needs ERA5 weather profiles only at those sites, for the periods the papers or instruments cover. A **validation box** is the small patch of ERA5 grid we download around one site: 5×5 grid points (about 110 km across), with hourly pressure-level profiles (temperature, wind, geopotential and cloud fraction on 29 levels) and single-level fields (cloud cover, surface pressure, winds, heat flux, …).

**What a request is.** A request is one job submitted to the Copernicus Climate Data Store (CDS). The CDS queues every job separately, so the number of jobs sets how long the downloads take. AGENTS.md specifies one request per day of data. For a whole-globe day (~7 GB) that's right, but a box-day is under 1 MB, so the queue wait would dominate. Asking for a month per request fetches exactly the same data in ~30× fewer jobs, with the same checks and verification.

Box = 5×5 ERA5 points around a site (the Timau box, 24 points, also covers Eltari). Per box-day: pressure levels (29 levels × 5 variables × 24 h) plus single levels (17 variables × 24 h) ≈ 3,900 GRIB1 messages of ~200 bytes ≈ **0.8 MB** (synthetic GRIB of the same shape: 158 bytes per message; real ERA5 headers to be measured by the smoke test).

| Target | Period | Box-days |
|---|---|---|
| Bi et al. (7 sites) | Aug 2020; Mar–Apr 2018; Nov 2018; 3 × Mar 2017–Feb 2019; Oct 2018–Dec 2020 | 3,135 |
| Priyatikanto (Timau + Eltari) | 2002–2021 | 7,305 |
| TMT (4 boxes; Armazones shares Paranal's) | ≤ 2004–2007 each (campaign dates to check) | ≤ 5,844 |
| ESO Paranal + La Silla | 2021–2025 | 3,652 |
| **Subtotal** | | **≈ 19,900 → ≈ 16 GB GRIB** |
| Haslebacher (8 sites) | unknown until their code is read; 1979–2020 would be 122,700 box-days ≈ 95 GB | **[ASK]** |
| Model levels (3 boxes × 12 months) | 2023 | ≈ 2 GB; MARS tape, hours to days per request |

- **Request count:** day-sized requests mean ≈ 39,900 CDS jobs (pressure + single levels). Month-sized requests mean ≈ 1,310. The CDS queues each job separately, so this is the main schedule risk. A 5×5 month of pressure levels is ≈ 108,000 fields; the smoke test's `estimate_costs` will say whether that is allowed. **[ASK] D16:** allow month-sized requests for validation boxes (the global run keeps one day per request).
- **Disk:** within phase 1's ~100 GB unless Haslebacher's periods are long. Ingested Zarr should be smaller than the GRIB (to be measured).
- **Time:** unknown until the smoke test measures queue time. At 1,310 jobs and a guessed 5–15 minutes each with 4 in flight, that's about 1–3.5 days of wall time *[estimate]*.

## 7. Uncertainties and risks

- **CDS queue and cost limits:** unmeasured; they set the phase 1 schedule. The smoke test measures them.
- **Bi et al.'s data source** (pressure vs model levels) is ambiguous (§3.1). The reproduction tests both.
- **HMNSP99 can give extreme L₀** (RESEARCH §9.21). The phase 1 notebooks will histogram L₀ and Cₙ² per site. Nothing is clipped.
- **Tropopause bound** (D4) and the **O&S unstable rule** (D5) are provisional; each is counted wherever it fires.
- **Zarr layout for the global run** (D10) is only decided for phase 1.
- **NFS hangs:** ingest probes `/data` in a child process with a timeout first. A hang during a write still blocks that process; the systemd unit's restart and the manifest's resumability are the recovery path.

## 8. Questions for Riley

Status after Riley's answers on 2026-09-27:

1. **Request size (D16): month-sized requests for validation boxes, approved** by Riley; `plan-box` defaults to `month`.
2. **Tolerances (§5): approved** by Riley (D19).
3. **Haslebacher volume [ASK]:** read on the CT (D27). Their outputs need ERA5 1979–2020 at 8 sites (~330 M CDS fields, months of processing) *and* their in-situ seeing, which isn't published. Proposed instead: their code vs ours on our ERA5 (done for one hour: agreement 9.4e-7, `reports/haslebacher2022_code_vs_code.json`; to repeat on a month), plus Table 4's lower levels from ERA5 surface pressure.
8. **Download schedule [ASK]:** §6.0 (options A/B/C).
4. **RESEARCH.md edits (D15):** listed for Riley; no decision needed unless he disagrees with one.
5. **GitHub push access: fixed** by Riley; the branch is pushed and PR #1 is open.
6. **Land-mask source: `global-land-mask`**, approved and checked (D20). Note: floating ice shelves count as sea.
7. **Later:** the TMT database login (task 12).

## 9. Proposed AGENTS.md changes (for Riley to make, if agreed)

- Under "Data safety → Downloads", allow month-sized requests for small validation boxes if D16 is approved.
- Under "Code → Environment", note that CDS access uses `ecmwf-datastores-client` (the library behind `cdsapi 0.7.7`) asynchronously, reading `~/.cdsapirc`.

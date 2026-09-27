# First session on CT 350 (2026-09-27)

Claude Code on the CT, continuing from the cloud bootstrap (`docs/handoff_ct.md`). Work is on branch `dev` (pushed); nothing merged to `main`.

## Summary

- **Done:** bootstrap (111 → 167 tests pass, ruff clean); papers (18 of 19); Haslebacher et al.'s code cloned and read; CDS smoke test passed; land mask built and stored on the NAS (phase 1 task 7); first validation-box downloads (Paranal) running.
- **Fixed on real data:** a downloader bug that submitted every planned request at once, and rejected CDS jobs being polled forever (both with regression tests). Also split requests to the CDS cost limit (a month of pressure levels is over it).
- **The big finding:** the CDS processes about **26 fields per second** for us (average of the first 9 files, 27–45 min each), **one request at a time per user**, and charges per field whatever the area. Phase 1 as planned needs about **72 million pressure-level fields: ~37 days of CDS time including single levels**, against 1–3.5 days in the plan. Paranal is continuing; **I have not queued any other site** and need your decision (§8, question 1).
- **Also for you:** the Bi et al. PDF (MDPI blocks non-browser downloads), the scope of the Haslebacher reproduction (their in-situ data aren't published), and a few confirmations (§9).

## 1. Machine

| Item | Value |
|---|---|
| OS | Ubuntu 26.04.1 LTS, kernel 7.0.0-3-pve, unprivileged LXC |
| CPU | i7-10700T, 6 cores visible to the CT (no CPU quota), no hyper-threading |
| RAM | 24 GiB + 8 GiB swap |
| `/` | ext4, 63 GB (57 GB free) |
| `/data` | NFS 4.1 (`hard`, `timeo=600`) from 10.0.1.10, 3.4 TB; files appear as `nobody:nogroup` (root is squashed), writable |
| `/staging` | ext4, 147 GB (140 GB free) |
| State dir | `/root/.local/state/astro` on local ext4 (SQLite manifest) |
| User | **root** (the only login user); repo at **`/home/astro-seeing`**, not `~/astro-seeing` |
| Tools installed | pixi 0.81.0 (user-level installer, runbook §1), tmux 3.7c from conda-forge via `pixi global` (in `~/.pixi`; no `apt`, no system change) |
| Git | `gh` logged in as rrweller, credential helper set; `dev` created from `main` and pushed |

`systemctl --user` has no user manager for root (no lingering), so user units don't work here, and the old units' `%h/astro-seeing` would be `/root/astro-seeing`, which doesn't exist (D26). **Update (D32):** the long jobs now run as system-level services with the real path: `astro-boxes`, `astro-notify` and the nightly `astro-manifest-export` timer (`scripts/systemd/system/`, installed by `scripts/install_services.sh`). They need no open session and restart after a reboot.

## 2. Bootstrap

`bash scripts/ct_bootstrap.sh` (log `logs/bootstrap.log`): `pixi install --locked` fine; `/data/astro` shows `nfs4`, the state directory `ext4` ("state dir is local: ok"); DE440s ephemeris fetched and checksum-verified; ruff clean; **111 passed in 58 s**. `~/.cdsapirc` was missing; I created it with the token you sent (mode 600, written with `umask 077`, never printed or committed).

Tests at the end of the session: **167** (163 fast + 4 slow), all passing. There were 135 before the download review and Copilot's review of PR #2 (D33).

## 3. Papers and the Bi et al. check

- `scripts/fetch_papers.py`: **18 of 19** fetched and opened as PDFs (`papers/INDEX.md`, with SHA-256). Also saved the GLOBE documentation manual (NOAA, 147 pages) as `papers/globe_documentation.pdf`.
- **Bi et al. 2023 failed again:** `www.mdpi.com` answers 403 "Access Denied" from Akamai to any non-browser client. OpenAlex lists no other full-text copy (only MDPI and a DOAJ record). I didn't try to get around the block. **Please save it from a browser as `papers/bi2023_remotesensing.pdf`**; the RESEARCH §3.1/§4.4/§6.1 check waits for it.
- **One Bi et al. problem found without the PDF:** Rongcheng as listed (122.11° E, 36.46° N) is **in the Yellow Sea, 34.6 km from land**, and the listed ERA5 point (122.00° E, 36.50° N) is 36 km from land. 37.46° N would be on land near Weihai. It's either a typo in the paper or in our transcription; marked *[check]* in RESEARCH §6.1.
- Priyatikanto et al. (from the arXiv HTML): **hourly data, all hours, 2002–2021, levels 1000 up to 1 hPa**. That's all 37 ERA5 levels, 8 above our 50 hPa top, and matters for the volume (§8).

## 4. Haslebacher et al.: what their outputs need (D27)

Code: `external/haslebacher` at commit `1da3712` (`code` branch; GPL-3.0 per `main`; run from `external/` only).

- **ERA5 inputs:** u, v, t, z on up to 28 pressure levels (no 70 hPa; the Chile download also has no 975), hourly, all 24 hours, **1979–2020**, at the grid point nearest each site; plus surface pressure, to pick the lowest level (the level closest to the time-mean ERA5 surface pressure).
- **Method details that matter for "our code vs theirs":** T, P and θ at each slab's lower level, not the midpoint; `|Δθ|` in N², so unstable layers count; k = 1; then **seeing** (not J) is scaled by mean in-situ / mean ERA5 over all hours. I added this discretisation to our physics (`HASLEBACHER2022_MODEL`), tested against an independent transcription of their eqs. 13–16 to 1e-12.
- **Their in-situ seeing isn't published.** The `data` branch holds only skill-score CSVs, trend posteriors and PRIMAVERA IDs, and their Table 2 sources are observatory archives and private communication. Without it, neither the calibration factors nor the skill scores (Tables A.6–A.7) can be reproduced. The 1979–2019 ERA5 trends (Tables A.13–A.14) can, but only up to the unknown calibration, at 0.01″/decade precision.
- **Discrepancies:** La Palma's lower level is 1000 hPa in the paper's Table 4 but 975 hPa in their site table; Paranal's seeing comparison period is 2000–2016 in the code vs 2000–2019 in Table 2.
- **Volume:** 1979–2020 for 8 sites is about **330 million CDS fields** (28 levels × 4 variables × 24 h × 15,341 days × 8). At the measured rate that's months. **Over the 50 GB / 24 h thresholds: [ASK], question 2.**
- **Running their code:** `climxa.py` imports cartopy, seaborn, SkillMetrics, netCDF4 and others at module level (2020-era pins). The seeing functions themselves only need numpy/xarray. The comparison calls them unmodified from `external/`, with the plotting imports stubbed, and says so (`notebooks/haslebacher2022_code_vs_code.py`; result in §7).

## 5. CDS smoke test (`reports/cds_smoke_test.json`)

- **Authentication:** ok. Accepted licences: `cc-by`, `terms-of-use-cds`, `data-protection-privacy-statement`. ERA5 *complete* (model levels, task 10) hasn't been tried yet.
- **One hour at Paranal, 5×5:** pressure levels (145 fields) queued 18 s and processed 16 s, 22,156 bytes; single levels (17 fields) queued 40 s and processed 5 s, 2,672 bytes. Both verified. Wall time 48 s.
- **Cost = number of fields, whatever the area** (an ERA5 "item" is one variable × level × time step, per ECMWF staff on the CDS forum). **Limits: 60,000 fields per request for pressure levels, 121,000 for single levels.** A global day costs 3,480 / 408. A month of a 5×5 box on 29 levels × 5 variables costs 107,880, **over the limit**, so D16's month-sized requests only work for single levels. Such months are now split in two (≤ 16 days each; D23).
- **Bytes:** GRIB1 with 16-bit packing, ~153 bytes per 5×5 field, so **0.60 MB per box-day** (0.53 pressure + 0.06 single levels), vs the 0.8 MB estimate.

## 6. Land mask (task 7; `reports/landmask.md`)

`/data/astro/static/landmask/era5_0p25_cells_v1.zarr` (per-cell counts and `keep`) and `globe_30s_land_buffer_v1.zarr` (30″ land and land + buffer), written atomically and verified, with provenance and the GLOBE citation.

- **Registration checked against NOAA.** GLOBE's `a10g.hdr` gives cell centres 1/240° in from the corner, so the package's axes are cell edges.
- **Land 28.905%** of Earth's area, same as D20. **ERA5 cells with land: 365,100** (the cloud session had 365,088; its method wasn't recorded).
- **Buffer = within 1 km of the nearest point of a land cell (D22):** land + buffer 29.131%, **366,604 cells kept** (research estimate 367,051; centre-to-centre would give 366,305).
- All validation sites are kept except Rongcheng (at sea as listed, §3). Small islands are kept, open ocean and the Ross Ice Shelf are not.

## 7. First validation downloads, and what the real CDS taught us

Planned: Paranal 5×5, **2016-04 → 2018-01** (O&S's stereo-SCIDAR campaign, their Table 1: 83 nights from 2016-04-26 to 2018-01-24) and **2021–2025** (ESO calibration), pressure and single levels plus the static fields. That's 247 requests, 2,497 box-days, about 1.5 GB. It runs in tmux `boxes` (`scripts/run_boxes.sh`, log `logs/run_boxes.log`).

What happened:

1. **Downloader bug:** with 4 jobs in flight, the next step asked the manifest for `limit=0` planned requests, and 0 meant "no limit". **It submitted 29 at once.** I stopped it, fixed it (`fa1c95a`) and added a regression test that fails on the old code.
2. **The CDS rejected 24 of the 29** with "Number queued requests for this dataset is temporarily limited", and **ran only one at a time** of the 5 it accepted.
3. **Second bug:** a rejected job raises `requests.HTTPError`, not `ProcessingFailedError`, so the downloader would have polled the 24 dead jobs forever. Now the message is recorded; queue-limit rejections go back to `planned` and other rejections fail the request (`716d16d`, tests added).
4. **Processing time:** the first half-month chunk (`pl/paranal/2016-04-01_2016-04-15`, 52,200 fields) queued 14 s, then **ran 1,669 s (27.8 min): 31.3 fields/s**. It downloaded 7,985,234 bytes in 1.5 s. The other accepted requests waited in turn. **Concurrency test:** I submitted one single-level request while a pressure-level one was running; it stayed queued for the full 15 minutes of watching. So the CDS runs **one request at a time per user, across datasets** (observed today; I found no documentation of it). Paranal alone is 164 pressure-level chunks plus 82 single-level months. **Update 21:00 UTC:** 10 files in, averaging **33 min per half-month file (27–45 min, 26.4 fields/s)**, plus 12.5 min per single-level month, so **~4.2 more days**. I'm letting it run (it's in every option below) and **have not queued any other site**.
5. **First code-vs-code check (Haslebacher):** their unmodified `ERA5_seeing_calc` vs our `HASLEBACHER2022_MODEL` on the smoke-test hour (25 Paranal columns, 900 → 50 hPa): median uncalibrated seeing 0.2044″ both ways, **max relative difference 9.39e-7**. That is exactly their rounded rad→arcsec constant (206265 vs 206264.806), so the methods agree to rounding (`reports/haslebacher2022_code_vs_code.json`). The formal check is on monthly means, next.

## 8. Updated volume and time estimates (revised after the download review, D29)

**How the CDS behaves (measured 2026-09-27):**
- **One processing slot per user**, shared by ERA5 pressure and single levels. The CDS terms allow one account per person, so extra accounts aren't an option.
- **~26 fields/s.** Every field is read whole (~2 MB) whatever the area, so a site box costs as much as the globe per field.
- **Requests are already near the 60,000-field limit**, and time scales with fields, not requests, so bigger requests don't help.
- **The single-level time-series product runs in its own slot in seconds and gives identical values**, so single levels move there. Only lcc/mcc/hcc, friction velocity, instantaneous heat flux and water vapour still need the standard dataset, and only for the cloud-layer and ground-layer experiments.
- **No faster source exists for site boxes.** The mirrors (NCAR on AWS, Google) store the whole globe per hour, and Earthmover's copy is surface-only.
- **So only pressure levels use the slot:**

| Option | What changes | Fields | CDS time |
|---|---|---|---|
| **A** | As planned: 5×5 box per site, all variables, all hours | 72.2 M | ~32 days |
| **B** | One download for nearby sites (Chile ×6, Tibet ×5); cloud fraction only where clouds are studied; Timau's 20 years 1 day in 4 | 34.6 M | ~15 days |
| **C** | B + night hours only where every comparison is at night (DIMM/MASS/SCIDAR sites) | 23.6 M | ~10 days |
| **D** | C + 2 years (not 5) for the ESO calibration + only the TMT campaign years (~2 per site) | 17.7 M | ~8 days |

- **What each gives up.**
  - B: nothing scientific. It means bigger files, plus sampling Timau's 20 years, which I'd check against one full year.
  - C: daytime hours at sites compared only at night. Our product is night-only anyway, but it needs an exception to the AGENTS.md rule that validation boxes keep all hours.
  - D: smaller calibration samples, though still thousands of matched night hours. The 5-year global run gives all years for every site later, so the calibration can be re-checked then.
- **The global run is not worse.** ~7.1 M fields is ~3.1 days of CDS processing (a global field costs the same as a box field), and ~13 TB to transfer is ~3–7 days at the measured 21–47 MB/s. The mirrors have no queue, so they're an option for it later (a new source, so I'd ask first).
- **Haslebacher's 42 years:** their scripts start ~27 downloads at once (one per pressure level, one year per request) on the old CDS, replaced in September 2024. With one slot today that is ~5 months.
- **Disk now:** `/data/astro` 28 MB; `/staging/grib` ~80 MB (raw GRIB kept until the first reproduction confirms the stores).

## 9. Questions for Riley

### Decisions needed now

**1. How to handle the slow downloads (the most important one)**

- **What's going on.** The CDS works on one of our requests at a time (one slot per user; the terms allow one account per person). It handles ~26 maps a second and reads every map in full, so a small site costs as much as the globe per map. Bigger requests don't help, since time scales with maps. Single levels now come from a separate time-series service in seconds, with identical values, so only pressure levels use the slot.
- **Options (the same sites and papers in each; details in §8):**
  - **A:** as planned, ~32 days;
  - **B:** shared downloads for nearby sites, cloud fraction only where needed, Timau 1 day in 4: ~15 days;
  - **C:** B + night hours only where all comparisons are at night: ~10 days (needs an exception to "validation boxes keep all hours");
  - **D:** C + 2 years of ESO calibration and only the TMT campaign years: ~8 days.
- **What I need:** reply **A, B, C or D**. With B, C or D, the Paranal 2021–2025 part (about 18 h from starting) gets replaced by the shared Chile download.

**2. What counts as "reproducing" Haslebacher et al.**

- **What's going on.** You approved "reproduce their published numbers (skill scores to ±0.01)". Having read their code, that isn't possible:
  - their scores compare ERA5 with observatory seeing measurements they got privately and never published;
  - their numbers use 42 years (1979–2020) at 8 sites, which at the measured speed is about five months of server time.
- **What I can do instead:**
  - (a) show that our code gives the same numbers as theirs on the same weather data. Done for one hour: they agree to within 1 part in a million. I'd repeat it on a full month;
  - (b) check their Table 4 (the lowest pressure level used at each site) from ERA5 surface pressure. That's cheap;
  - (c) write down exactly what can't be reproduced, and why.
- **What I need:** reply **"OK, (a)+(b)+(c)"**, or **"no, collect the observatory data"**. The second means new data sources, new licences and weeks of extra work.

**3. The Bi et al. paper**

- **What's going on.** MDPI's website refuses automated downloads, so I don't have the paper. Until I do, I can't check our notes on it, including the Rongcheng coordinates that land in the sea.
- **What I need:** open https://www.mdpi.com/2072-4292/15/9/2225/pdf in your browser and save it where I can read it, for example the top of the NAS share (`Astro-seeing/data`). Tell me the path and I'll copy it into `papers/`.
- **Optional:** Racine 2005 (PASP) and the García-Lorenzo 2011 corrigendum (MNRAS), if you have access.

### Please confirm when you get a chance

**4. Two choices I made myself.** Just reply "keep both", or tell me which to change.

- **Coastline buffer.** "Land plus 1 km" is measured from the edge of land pixels, not their centres. The alternative keeps 299 fewer coastal cells out of 366,604 (0.08%).
- **Splitting downloads.** You approved one request per month, with daily requests as the fallback if the server refused. It does refuse a whole month of pressure-level data (too many maps), so I split each month into two halves instead of 30 days. Same data, 15× fewer requests.

**5. Which user runs the project.**

- **What's going on.** The container only has `root`, and the repo is in `/home/astro-seeing`. The setup notes assumed a normal user running background services, so for now long jobs run in tmux, which works fine.
- **What I need:** reply **"keep root"** (my recommendation, since nothing is blocked), or create a normal user and I'll move things over.

**6. ESO measurement data** (needed for calibration in a week or two).

- **What's going on.** ESO publishes Paranal and La Silla seeing measurements under CC BY 4.0, which only asks that ESO be credited. It's a new data source, so it needs your OK.
- **What I need:** **OK** or **not yet**.

### Later / not urgent

**7. TMT site-testing database.** Free, but it needs an account in your name. It's needed for calibration later, and it also gives the exact campaign dates, which would shrink the TMT downloads.

**8. CDS key.** Because it was pasted in the chat, it's saved in the conversation history. If that bothers you, generate a new one on your CDS profile page and write it yourself: `! printf 'url: https://cds.climate.copernicus.eu/api\nkey: NEW-KEY\n' > ~/.cdsapirc && chmod 600 ~/.cdsapirc`.

**9. Merging to main.** All work is on the `dev` branch (13 commits). Open a pull request to `main` now, or wait until the first paper reproductions work? My recommendation: wait.

## 10. Proposed AGENTS.md changes (for you to make, if you agree)

- **Environment:** the repo is at `/home/astro-seeing` and everything runs as root; long jobs run in tmux (installed via `pixi global`); systemd user units need a non-root user or lingering.
- **Data safety → Downloads:** validation boxes use month-sized requests, **split to the CDS cost limit** (60,000 fields for pressure levels; D16, D23); at most 4 requests in flight (the CDS rejects more queued jobs per dataset, D24).
- **Code → Environment** (from the plan, §9): CDS access uses `ecmwf-datastores-client` asynchronously, reading `~/.cdsapirc`.

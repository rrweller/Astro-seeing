# First session on CT 350 (2026-09-27)

Claude Code on the CT, continuing from the cloud bootstrap (`docs/handoff_ct.md`). Work is on branch `dev` (pushed); nothing merged to `main`.

## Summary

- **Done:** bootstrap (111 → 135 tests pass, ruff clean); papers (18 of 19); Haslebacher et al.'s code cloned and read; CDS smoke test passed; land mask built and stored on the NAS (phase 1 task 7); first validation-box downloads (Paranal) running.
- **Fixed on real data:** a downloader bug that submitted every planned request at once, and rejected CDS jobs being polled forever (both with regression tests). Also split requests to the CDS cost limit (a month of pressure levels is over it).
- **The big finding:** the CDS processes about **31 fields per second** for us, **one request at a time per user**, and charges per field whatever the area. Phase 1 as planned needs about **72 million pressure-level fields: ~27 days of CDS time (~30 with single levels)**, against 1–3.5 days in the plan. Paranal is continuing; **I have not queued any other site** and need your decision (§8, question 1).
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

`systemctl --user` has no user manager for root (no lingering), so long jobs run in tmux with logs in `logs/` (D26). The systemd units use `%h/astro-seeing` = `/root/astro-seeing`, which doesn't exist here.

## 2. Bootstrap

`bash scripts/ct_bootstrap.sh` (log `logs/bootstrap.log`): `pixi install --locked` fine; `/data/astro` shows `nfs4`, the state directory `ext4` ("state dir is local: ok"); DE440s ephemeris fetched and checksum-verified; ruff clean; **111 passed in 58 s**. `~/.cdsapirc` was missing; I created it with the token you sent (mode 600, written with `umask 077`, never printed or committed).

Tests now: **135** (131 fast + 4 slow), all passing.

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
4. **Processing time:** the first half-month chunk (`pl/paranal/2016-04-01_2016-04-15`, 52,200 fields) queued 14 s, then **ran 1,669 s (27.8 min): 31.3 fields/s**. It downloaded 7,985,234 bytes in 1.5 s. The other accepted requests waited in turn. **Concurrency test:** I submitted one single-level request while a pressure-level one was running; it stayed queued for the full 15 minutes of watching. So the CDS runs **one request at a time per user, across datasets** (observed today; I found no documentation of it). Paranal alone is 164 pressure-level chunks × ~28 min plus 82 single-level months × ~7 min ≈ **3.6 days**. I'm letting it run (it's in every option below) and **have not queued any other site**.
5. **First code-vs-code check (Haslebacher):** their unmodified `ERA5_seeing_calc` vs our `HASLEBACHER2022_MODEL` on the smoke-test hour (25 Paranal columns, 900 → 50 hPa): median uncalibrated seeing 0.2044″ both ways, **max relative difference 9.39e-7**. That is exactly their rounded rad→arcsec constant (206265 vs 206264.806), so the methods agree to rounding (`reports/haslebacher2022_code_vs_code.json`). The formal check is on monthly means, next.

## 8. Updated volume and time estimates

Measured: **31.3 fields/s, one request at a time per user, across datasets**; cost = fields whatever the area; 0.60 MB per 5×5 box-day. Field counts use each paper's own levels and variables (Priyatikanto: 37 levels up to 1 hPa, 4 variables; ours: 29 levels, 5 variables with `cc`).

| Option | What | Fields (pl) | CDS time | GRIB |
|---|---|---|---|---|
| **A: as planned** | 5×5 boxes per site, all variables, all hours: Paranal (O&S + ESO), La Silla (ESO), Timau 2002–2021, Bi's 7 sites, TMT 4 boxes × 2004–2007 | 72.2 M | **~27 days** (+3 days of single levels, run serially) | 11 GB |
| **B (recommended)** | **Shared rectangles** for co-located sites, since a bigger area costs the CDS nothing extra: Chile (Paranal, La Silla, Tololo, Armazones, Tolar, Tolonchar; O&S + ESO + TMT periods) and Tibet/Qinghai (Ali, Daocheng, Muztagh-ata, Lenghu, Da Qaidam; 2017-03..2020-12). `cc` only where cloud work is planned. **Priyatikanto's 20 years sampled 1 day in 4** (every season and year; I'd quantify the sampling error on one full year). SPM and Mauna Kea 13N boxes for the TMT period. | 34.6 M | **~13 days** (+~1.5 days of single levels) | 54 GB (36 GB is the Tibet rectangle; transient) |
| **C** | B, plus **night hours only** for the DIMM/MASS calibration targets (ESO, TMT) | ~24 M | ~9 days | ~40 GB |
| Haslebacher, full | 1979–2020 × 8 sites × 28 levels × 4 variables | ~330 M | months | ~50 GB |

- Rectangles need ingest to either store the rectangle as one validation region or cut it into per-site boxes. D18 currently refuses unmasked stores over 121 points; I'd add explicit validation regions.
- TMT campaign dates come from the TMT database (login) and will shrink the TMT rows.
- The cloud-above-height experiment (Mauna Kea, La Palma, Paranal) needs `cc` for periods with observatory cloud records. Paranal is covered; Mauna Kea and La Palma periods are still to be chosen (~2.5 M fields per site-year, no rectangle sharing).
- **Phase 3 implication:** a global day is 3,888 fields, ~2 min of CDS processing, but ~7 GB to download. So phase 3 is bound by bandwidth, not processing, and we haven't measured bandwidth on a large file yet (next step: one global hour, ~300 MB).
- **Disk now:** `/data/astro` 6.8 MB (land mask + first stores), `/staging/grib` 7.7 MB (raw GRIB kept until the first reproduction confirms the stores), root 2.6 GB used of 63 GB.

## 9. Questions for Riley

1. **Phase 1 download schedule (A, B or C, §8).** I recommend **B**: it keeps every paper's variables, levels and hours except Priyatikanto's sampling. Should validation boxes stay all-hours (AGENTS.md), or is C's night-only allowed for calibration targets?
2. **Haslebacher et al. scope (D27).** Their published numbers need their unpublished in-situ seeing plus ~330 M fields of ERA5. May I replace the approved "published skill scores ±0.01" with: (a) their code vs ours on the same ERA5 (≤ 0.1%; already 9.4e-7 on one hour), (b) Table 4's lower levels from ERA5 surface pressure, and (c) a written account of what can't be reproduced? The alternative is collecting observatory in-situ data (ESO, MKWC, ING, CTIO…): new sources and licences.
3. **Bi et al. PDF:** please save it from a browser as `papers/bi2023_remotesensing.pdf` (MDPI blocks scripts). Racine 2005 and the García-Lorenzo 2011 corrigendum too, if you can get them.
4. **Please confirm D22** (land buffer measured to the nearest point of a land cell) **and D23** (split months to the CDS limit instead of D16's day-sized fallback).
5. **CT user:** everything runs as root, in `/home/astro-seeing`. Keep it that way (tmux for long jobs), or create an unprivileged user and move the repo so the systemd user units can be used (you'd run `useradd` and `loginctl enable-linger`)?
6. **CDS token:** it went through the chat, so it's in this conversation's transcript. Consider regenerating it on your CDS profile page at some point. To swap it in without the chat, run `! printf 'url: https://cds.climate.copernicus.eu/api\nkey: <new>\n' > ~/.cdsapirc && chmod 600 ~/.cdsapirc` yourself.
7. **ESO ambient data (task 12):** ESO distributes archive data under **CC BY 4.0** with an ESO provenance acknowledgement (ESO data access policy, 2022-11-07). OK to use for calibration?
8. **TMT database login** (task 12), when convenient: it also gives the exact campaign dates.
9. **Checkpoint to `main`:** `dev` has 13 commits since `main`. A PR now, or at the next milestone (first reproductions)?

## 10. Proposed AGENTS.md changes (for you to make, if you agree)

- **Environment:** the repo is at `/home/astro-seeing` and everything runs as root; long jobs run in tmux (installed via `pixi global`); systemd user units need a non-root user or lingering.
- **Data safety → Downloads:** validation boxes use month-sized requests, **split to the CDS cost limit** (60,000 fields for pressure levels; D16, D23); at most 4 requests in flight (the CDS rejects more queued jobs per dataset, D24).
- **Code → Environment** (from the plan, §9): CDS access uses `ecmwf-datastores-client` asynchronously, reading `~/.cdsapirc`.

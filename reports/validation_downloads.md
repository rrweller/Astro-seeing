# Validation downloads (option C): finished (2026-10-17)

Milestone report for phase 1 task 8 (`reports/phase1_plan.md` §4, schedule D31). Work is on branch `dev`.

## Summary

- **All 472 requests are downloaded, verified and ingested** (the last at 12:35 UTC). They are option C (D31), the Paranal box for O&S, the static fields and the smoke test. The 180 `cancelled` requests are the Paranal 2021–2025 part, replaced by the Chile area (D31).
- **Three Tibet jobs were lost by the CDS** on 12 Oct (HTTP 404), and the downloader kept polling them for 5 days. Fixed: it now submits such jobs again by itself (D34). They finished today.
- **Every store passed an integrity check.** No duplicate times and no missing days. The only NaNs are in cloud base height, where "missing" means no cloud (D17).
- **The CDS was slower than first measured:** 10.3 fields/s on average over the 19 days, 40% of the 26.4 fields/s measured on the first day. Projections for phases 2 and 3 have to use the lower figure (§4).
- **Bi et al. was checked against the PDF (D35).** Our notes match it. Four things the paper doesn't state are now marked [check] in RESEARCH §3.1.

## 1. What is on the NAS

| Area (sites) | Period | UTC hours | Levels | Variables | Stores | Days | Zarr |
|---|---|---|---|---|---|---|---|
| chile (Paranal, La Silla, Tololo, Armazones, Tolar, Tolonchar) | 2021–2025 | 13 (23–11, night) | 29 | z t u v cc | 60 | 1,826 | 738 MB |
| tibet (Ali, Daocheng, Muztagh-ata, Lenghu, Da Qaidam) | 2017-03 – 2020-12 | 24 | 29 | z t u v | 92 | 1,402 | 983 MB |
| timau@every4d (Timau, Eltari) | 2002–2021, every 4th day | 24 | 37 | z t u v | 240 | 1,905 | 607 MB |
| haikou | 2018-03 – 2018-04 | 24 | 29 | z t u v | 4 | 61 | 9 MB |
| rongcheng | 2018-11 | 24 | 29 | z t u v | 2 | 30 | 5 MB |
| paranal, pressure levels (O&S) | 2016-04 – 2018-01 | 24 | 29 | z t u v cc | 44 | 671 | 110 MB |
| paranal, single levels (O&S) | 2016-04 – 2018-01 | 24 | — | 17 variables | 22 | 671 | 29 MB |
| static (z, lsm per area) | — | — | — | — | 6 | — | 3 MB |

- **Cells:** the area stores keep only the 5×5 boxes around each site (125 cells for Tibet, 129 for Chile, where boxes overlap; 42 for Timau and Eltari). The Paranal stores are a plain 5×5 grid.
- **Totals:** `/data/astro` holds 2.6 GB. `/staging/grib` holds 41.6 GB of raw GRIB (472 files).
  - 35.7 GB of that is Tibet, because the CDS sends the whole Tibet rectangle (43 × 105 points) and we keep only the 125 site-box cells.
  - The raw files stay until the reproductions have used the stores, then I delete them. They're on the local SSD, not the NAS.

## 2. Checks

Every store was read back from the NAS with `scripts/survey_stores.py` (read-only; run 2026-10-17 after the last ingest):
- times strictly increasing in every store, and no duplicates across stores;
- every day requested in the manifest is present;
- the expected cells, levels and UTC hours are present;
- **no NaN in any pressure-level variable** (1.28 × 10⁹ values);
- single levels (Paranal): 181,346 NaN, all in `cbh` (45% of hours; no cloud means no cloud base, D17).

## 3. The lost jobs (D34)

- On 12 Oct the CDS stopped knowing three Tibet jobs about an hour after accepting them (HTTP 404). A 3 h stall the same afternoon suggests an incident at the CDS.
- The downloader treated the 404 as a passing error and kept polling: 39,504 polls over 5 days.
- The watcher sent its "stuck at the CDS" alert every 12 h, as designed. Getting the jobs going again took a code change.
- The cost: those three jobs held 3 of our 4 queue places, so the remaining 47 requests (2.0 M fields) went to the CDS one at a time. They ran at 5.6 fields/s, half the 11.4 fields/s of the 5 days before. At the earlier rate, everything would have finished around 14 Oct, so the finish slipped by about 3 days.
- **Fix:** a 404 now counts as a deleted job, which the downloader plans and submits again, logging why. Regression tests were added. After the restart, the three were resubmitted at 10:43 UTC and were ingested at 11:14, 12:15 and 12:35 UTC (CDS processing about 20–60 min each).

## 4. CDS throughput over the whole campaign

Measured from the manifest (`events` and `files` tables):

| Measure | Value |
|---|---|
| Fields downloaded | 16.85 M (pressure levels 16.57 M, single levels 0.27 M, static) |
| Period | 27 Sep 14:44 → 16 Oct 13:31 UTC (the last download before today's resubmission), 18.95 days |
| **Average** | **10.3 fields/s** |
| By day | 5.4–15.9 fields/s on full days; 10–12 on most days from 2 to 12 Oct |
| Submission to download, median per area | 2.5–4.4 h, mostly queueing behind our own earlier jobs (the CDS runs one at a time) |
| By area, while each ran on its own | Paranal (25 points) 16.5–26.3; Chile (608) 12.6; Timau (48) 10.5; Tibet (4,515) 12.7 on 11 Oct, before the lost jobs. Single levels (Paranal) 3.7 fields/s |

- **Area:** no visible effect. Tibet's requests, with 94 times the points of Timau's, ran no slower per field.
- **The earlier figure:** 26.4 fields/s came from the first files on 27 Sep. The rate then fell steadily, probably as the CDS got busier. We can't see its load, so 10.3 is the safer number for planning.

**What this means for phases 2 and 3 [estimate]:**
- **Cost per field, not per area.** The CDS charges and works per field, not per area. So a 20°×20° region costs as much CDS time as the whole globe: 5 years of hourly pressure levels with `cc` plus the 17 single-level variables is ~7.1 M fields either way. That is 8–9.5 days: 8 at 10.3 fields/s, 9.5 if single levels run at the 3.7 fields/s of our one batch of them.
- **Phase 2 as written.** Downloading phase 2's 8 regions separately would be ~57 M fields, **~64–76 days**. Night hours only would make it ~31 M fields, ~35–41 days. That uses about 13 of 24 UTC hours per half-month for a 20°×20° region, measured for 5 of the 8 regions.
- **Whole globe instead.** The same 5 years for the whole globe is the same ~7.1 M fields: **~8–9.5 days** of CDS time, plus ~13 TB of transfer (3–7 days at the measured 21–47 MB/s; it overlaps with the processing).
- **Gate 1 recommendation (expected).** I expect to recommend cutting the phase 2 regions out of global downloads instead of downloading them separately. That would change the phase 2 plan, so it's your decision at gate 1.
- **Test first.** A test request for one global hour (~300 MB) will check that a global field takes the CDS no longer than a small one.

## 5. Bi et al. 2023 against the PDF (D35)

- **Matches:** λ = 550 nm; the 5.25 coefficient; eq. 4–7 with P in hPa; the HMNSP99 coefficients; and every value in Tables 2 and 3.
- **Rongcheng:** the coordinates that fall in the sea are printed that way in the paper (Table 2 and the Figure 1 caption). To reproduce their numbers, we use their ERA5 point.
- **Not stated in the paper**, so the reproduction tries the variants:
  - whether it used pressure or model levels;
  - which ERA5 hours Table 3 uses;
  - how it switches between the troposphere and stratosphere formulas;
  - the DIMM site altitudes, which are in its references.
- **Top of the profile:** our Bi downloads stop at 50 hPa. At Timau, the 50–1 hPa layer adds a median +0.0024″ (max +0.0032″) of seeing, against a ±0.05″ tolerance, so no extra download is needed.

## 6. What's uncertain

- **The CDS rate** depends on its load, which we can't see. 10.3 fields/s is one 19-day average. The single-level rate (3.7 fields/s) rests on 21 requests on one day.
- **Global fields:** whether one costs the CDS the same time as a small-area field is untested (§4).
- **Lost jobs:** the 404 behaviour is handled now, but the CDS may lose jobs in other ways. The watcher's 12 h "stuck" alert is still the backstop.

## 7. Next steps

**What I'll do next** (approved phase 1 work, within the limits; nothing needed from you):
1. **Reproductions** (plan task 9), one notebook each, with golden tests:
   - **Haslebacher (a):** their code and ours already agree to 9.4 × 10⁻⁷ on one hour of real ERA5 (the smoke-test hour). Next, monthly means over Paranal 2016–2018 (tolerance 0.1%).
   - **Priyatikanto:** the Timau median, 0.79″ ± 0.03″.
   - **Bi:** 7 sites, ±0.05″, with the variants in §5.
   - **O&S:** Paranal medians within ±0.1″.
2. **Single levels for every validation site** from the CDS time-series product (D29). The fetcher isn't built yet. That product has its own CDS slot, so it delays nothing. It gives the surface pressure that Haslebacher (b) needs (their Table 4 lower levels), and cloud cover for the clear-sky test.
3. **ESO DIMM/MASS 2021–2025** (source approved, D28): Paranal DIMM and MASS, and La Silla DIMM. The ESO archive's query forms load (checked 2026-10-17) and offer CSV downloads. This is the calibration data (plan task 12).
4. **Two small CDS downloads**, each well under 24 h and 50 GB:
   - Chile's extra single-level variables for the cloud-layer and ground-layer experiments (lcc, mcc, hcc, zust, ishf, tcwv): ~0.14 M fields, ~4 h;
   - one global hour (~300 MB) for the projections in §4. Ingest would refuse it (D18) and the watcher would report that as a problem, so this one needs a measurement-only mode first.

**What needs Riley:**
1. **TMT login.** AGENTS.md says to ask at this point.
   - Account: free, at https://sitedata.tmt.org/register.html. Only a name and a username are needed; TMT assigns the password.
   - Usage conditions (https://sitedata.tmt.org/usage.html): free for analysis. Publications must cite Schöck et al. 2009 (PASP 121, 384–395), and TMT asks for a voluntary email when something is published. These are new licence terms, so they need your OK.
   - What the database has: weather station, DIMM, MASS, dust, sonic anemometer and tower data. It has no all-sky-camera cloud data (data-fields page, checked 2026-10-17).
2. **TMT ERA5 download.** It is over 24 h of CDS time, so it needs your OK. The campaign dates are public (https://sitedata.tmt.org/Available_data/data_availability.html). The data are night hours only, and the Chile area also covers Tolar, Armazones and Tolonchar.
   - **A (recommended): 2006–2007 at all five sites.** ~3.6 M fields, **~4 days**, ~2 GB. This includes cloud fraction at Mauna Kea, which the cloud experiment needs. It gives two full years at every site with DIMM and MASS (Tolar only until March 2007). It's enough for calibration and for the terrain experiment.
   - **B: each site's whole campaign** (between Oct 2003 and Sep 2009). ~7.5 M fields, ~8.5 days, ~5 GB. It would add a check against the published campaign medians (RESEARCH §6.4).
   - **C: no TMT.** We'd calibrate on ESO only. Then Mauna Kea 13N and San Pedro Mártir, our only DIMM/MASS sites outside Chile, couldn't test whether the calibration carries over to other sites.
   - The ERA5 part doesn't need the login, so it can start before you have the account.
3. **Merge to main.** dev has 3 commits since PR #2: the notify fix, D34 and D35, plus this report. The proposal is the same as last time: PR #3, Copilot review, fix what it finds, then merge.
4. **When convenient:**
   - **Rotate the CDS token.** It was pasted into our first chat. Make a new one on your CDS profile page and write it into `/root/.cdsapirc` on the CT yourself, not in the chat.
   - **AGENTS.md wording.** It still says validation boxes keep all hours, but D31 approved night-only downloads for the DIMM/MASS targets. Suggested wording for "What gets stored": "Validation boxes keep all hours, except areas used only for night-time comparisons, which may be night-only (D31)."

**Later** (no decision needed now): La Palma and the model-level experiment (ERA5 complete) need their own downloads. I'll size them after the reproductions.

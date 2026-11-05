# Open forecast sources for a next-night astronomy forecast

No ticket yet (planned forecast feature). Researched 2026-11-05 by the agent. Sources are primary: the providers' own documentation, licence and terms pages, their data servers (directory listings, GRIB `.idx`/`.index` files, OPeNDAP `.dds`/`.das`, STAC/EDR metadata), and one or two small test downloads. Every link below was loaded on 2026-11-05 and says what is cited, except where marked. Times are UTC. "Observed" means I read it off a live server today, from one day's runs.

**Question.** For a next-night forecast (cloud per model, plus seeing computed from the model's T/u/v/z profiles with the Osborn–Sarazin and Tatarskii/HMNSP99 Cₙ² models, RESEARCH §4.3–4.5), which open forecast models give us the raw fields, under what terms? The first target is Kongsberg, Norway (59.67°N, 9.65°E), with global coverage later. v1 shows several models side by side on an hourly timeline. Riley's rules: aggregate only raw output from open models, not other services' finished forecasts; use free sources first; pay only if nothing free has the data, cheapest first.

## Short answer

Four free, raw, redistributable sources cover southern Norway with T, u, v and geopotential on pressure levels, plus cloud:

- **NOAA GFS 0.25°** has by far the best vertical sampling of any free pressure-level product: **39 levels from 1000 to 50 hPa**, every 25 hPa from 1000 to 100 hPa, with cloud cover on 39 levels. Output is hourly to 120 h, available ~3.6 h after the run. The data is US-government open data, and NOMADS cuts out a box on the server.
- **DWD ICON-EU (0.0625°, ~7 km)** has 20 pressure levels including `clc` (cloud cover), plus **74 model levels** with heights (`hhl`). It's hourly to 78 h, ~3 h latency, CC BY 4.0. It is whole-domain files only.
- **MET Norway MEPS (2.5 km)** has 13 pressure levels and **65 model levels** with T, u, v, cloud fraction and TKE. It's hourly to 66 h and runs every 3 h, ~2–4 h latency, CC BY 4.0 / NLOD. OPeNDAP returns exactly the box or profile asked for. Regional only (Nordic).
- **ECMWF IFS open data (0.25°, and 0.1° since 2026-10-20)** has only **14 pressure levels** (13 from 1000 to 50 hPa, plus 10 hPa) and **3-hourly** steps, with no cloud fraction on levels. Latency is long: all steps at once, ~7.5 h after 00/12 UTC. CC BY 4.0, global.

Not suitable as raw inputs:

- **ICON-D2** stops at 58.08°N, so it misses Kongsberg.
- **AIFS** is 6-hourly only.
- **DMI HARMONIE DINI** covers Norway, but its pressure-level temperature has only 11 levels, and its model-level files are 5.1 GB per hour.
- **Open-Meteo, 7Timer!, MET Locationforecast and MET Nordic** are processed or finished products, not raw model output:
  - Open-Meteo interpolates time and derives level cloud from RH.
  - The free tiers of Open-Meteo and 7Timer! are non-commercial only.

Everything listed is free. The only paid option relevant here is ECMWF's full real-time catalogue (e.g. HRES model levels, hourly steps), from **€500/year** (Volume Band 1, ≤1 GiB/day, Basic).

**Vertical resolution caveat:** every free pressure-level product here is coarser than ERA5's 37 levels except GFS (39 between 1000 and 50 hPa). Only model levels (ICON-EU 74, ICON 120, MEPS 65, DINI 90, GFS native 127) come near the >100 levels that O&S and Haslebacher stress (RESEARCH §3.3–3.4). *[inference]* Seeing from 13–20 pressure levels will smooth Cₙ² more than our ERA5 calibration assumes, so each model needs its own calibration or at least its own validation.

## Comparison

Sizes are per run for steps 0–36 h. "Box" is 4.65–14.65°E × 54.67–64.67°N around Kongsberg. Field sets: T, u, v, z on all pressure levels down to 50 hPa, plus the cloud fields listed. Sizes are compressed GRIB2 unless noted.

| | **GFS 0.25°** | **ICON-EU** | **MEPS (MetCoOp)** | **ECMWF IFS open** | **AIFS Single** | **ICON global** | **DMI DINI** |
|---|---|---|---|---|---|---|---|
| Licence | US-gov open data; attribution requested; no endorsement | CC BY 4.0 | CC BY 4.0 + NLOD | CC BY 4.0 + ECMWF terms | CC BY 4.0 + ECMWF terms | CC BY 4.0 | CC BY 4.0 |
| Public derived products | yes | yes, with source note | yes | yes, with set wording | yes | yes | yes |
| Non-commercial limit | no | no | no | no | no | no | no |
| Covers Kongsberg | yes (global) | yes (29.5–70.5°N, 23.5°W–62.5°E) | yes (49.8–75.2°N) | yes (global) | yes | yes | yes (37.7–69.9°N, 43.2°W–40.1°E) |
| Grid | 0.25° lat-lon (model ~13 km) | 0.0625° lat-lon | 2.5 km Lambert | 0.25° and 0.1° lat-lon | 0.25° | icosahedral ~13 km (needs remap) | 2 km |
| Pressure levels 1000–50 hPa (T/u/v/z) | **39** | 20 | 13 | 13 (+10 hPa) | 13 (+10 hPa) | 17 (+30 hPa) | T: 11, z/u/v: 15 (no 50 hPa) |
| Model levels (open) | 127 (native netCDF, 6.8 GB/h global) | **74** + `hhl` | **65** (+ TKE) | no | no | 120 (`clc` on 39–120) + `hhl` | 90 (5.1 GB/h) |
| Cloud on levels | `TCDC` on 39 PL | `clc` on 20 PL and 74 ML | `cloud_area_fraction` on 13 PL and 65 ML | no (only `r`, `q`) | no | `clc` on ML only | no on PL |
| Total/low/mid/high cloud | yes | yes (`clct/clcl/clcm/clch`) | yes | yes | yes | yes | yes |
| 200 hPa wind | yes | yes | yes | yes | yes | yes | yes |
| Steps 0–36 h | hourly (to 120 h) | hourly (to 78 h) | hourly (to 66 h) | **3-hourly** | **6-hourly** | hourly (to 78 h) | hourly (to 60 h) |
| Cycles/day | 4 | 8 | 8 (det) | 4 (06/18 to 144 h) | 4 | 4 | 8 collected |
| Latency (observed) | f000 +3.6 h, f036 +3.7 h | +2.7–3.0 h | +2.3–4.1 h | +7.6 h (0.25°), +9.6 h (0.1°) | +5.8 h | +2.7–2.9 h | PL +2.5 h, ML +3.0 h |
| Online | NOMADS 10 days; AWS from 2021 | latest run per cycle (~1 day) | latest few days; archive from 2016 | portal ~3 days; AWS from 2023-01-18 | same | ~1 day | STAC 48 h, EDR 24 h |
| Subsetting | variable + level + **box on server** (NOMADS filter); byte ranges via `.idx` | none: one file per variable/level/step | **any box/point via OPeNDAP** | byte ranges per field via `.index`; no area | same | none | whole-domain GRIB; EDR (JSON) for PL/SF |
| Box download | ~30 MB *[0.57 MB/step measured for half the fields]* | ~3.3 GB (whole domain) | PL ~1 GB, ML ~3.9 GB (float32) *[estimate]* | 0.46 GB (0.25°), 2.1 GB (0.1°) (global fields) | 0.22 GB | 9.3 GB (global) | PL 18.6 GB, ML ~190 GB |
| Global download | ~7.8 GB | n/a | n/a | 0.46 GB / 2.1 GB | 0.22 GB | 9.3 GB | n/a |
| Cost | free | free | free | free (full catalogue from €500/yr) | free | free | free |

## Findings, each with its source

### ECMWF open data: IFS (HRES and ENS) and AIFS

**Licence and attribution**
- The open-data page says "Creative Commons CC-BY-4.0 licence" plus the ECMWF Terms of Use. It allows redistribution and commercial use "subject to appropriate attribution" (https://www.ecmwf.int/en/forecasts/datasets/open-data). ECMWF's licence overview lists "ECMWF Open Data — Licence: CC BY 4.0" (https://www.ecmwf.int/en/forecasts/accessing-forecasts/licences-available).
- **Wording for a service** built on the data, from the Terms of Use (https://apps.ecmwf.int/datasets/licences/general/, quoted from the raw page):
  - 'Copyright statement: Copyright "This service is based on data and products of the European Centre for Medium-Range Weather Forecasts (ECMWF)". Source www.ecmwf.int Licence Statement: This ECMWF data is published under a Creative Commons Attribution 4.0 International (CC BY 4.0). https://creativecommons.org/licenses/by/4.0/ Disclaimer: ECMWF does not accept any liability whatsoever for any error or omission in the data, their availability, or for any loss or damage arising from their use. Where applicable, an indication if the material has been modified and an indication of previous modifications.'
  - The same page: "Attribution must be displayed prominently", "Users must remove attribution if requested by ECMWF", and the CC BY text "Adapt — remix, transform, and build upon the material for any purpose, even commercially".
  - The page also says users "are required to sign a service agreement with ECMWF" *in order to receive services related to the provision of this dataset*. I read that as covering delivery services, not anonymous download from the open portal, but the page doesn't say so explicitly *[unsure]*.
- **Rate limit:** the portal is limited to "between 500 and 2000 simultaneous connections", a variable limit (open-data page). There is no per-user request rate and no User-Agent rule.

**Variables and levels** (read from the live `.index` files, step 12 h of the 2026-11-05 00z and 2026-11-04 12z runs)
- **IFS `oper`, 0.25°:**
  - Pressure-level params `d, gh, q, r, t, u, v, vo, w, z` on **10, 50, 100, 150, 200, 250, 300, 400, 500, 600, 700, 850, 925, 1000 hPa** (14 levels).
  - Surface: `tcc, lcc, mcc, hcc`, `sp`, `skt`, `2t`, `2d`, `10u/10v`, `100u/100v`, `tcwv` and others.
  - **No cloud fraction on levels**, no boundary-layer height, no friction velocity and no heat flux.
- **IFS 0.1°** (new; published "alongside the existing 0.25°", from 20 October 2026, open-data page): the same 10 pressure-level params on the same 14 levels (`-pl` file), plus a `-sfc` file with `tcc/lcc/mcc/hcc`, `sp`, `skt`, `2t` (`20261104120000-12h-oper-fc-pl.index`).
- **ENS `enfo`, 0.25°:** `d, gh, q, r, t, u, v, vo, w` on the same 14 levels (geopotential height `gh`, not `z`), plus `tcc/lcc/mcc/hcc`. I counted **50 perturbed members** (`type: pf`) in the step-12 index; no `cf` (control) record was in that file *[where the control is published: not checked]*.
- **AIFS Single:** `gh, t, u, v, w, z` on the 14 levels (`q` on 13, no 10 hPa), plus `tcc/lcc/mcc/hcc`, `sp`, `skt`, `2t`, `2d`, `10u/10v`, `100u/100v`.
- The open-data page lists the same 14 levels in its parameter table. **Model levels are not in the open data.** The page calls the open data "a subset of the full Catalogue of ECMWF Real-time Products".

**Grid, steps, cycles** (open-data page, confirmed by the portal listing)
- IFS 0.25° and 0.1°: runs at 00/06/12/18. Steps **0–144 h every 3 h**, then every 6 h to 360 h at 00/12 only. Listing of `20261105/00z/ifs/0p25/oper/`: 0, 3, 6, …, 144, 150, …, 360.
- AIFS: "0–360 h every 6 h", 0.25° only.

**Latency and retention**
- The page says IFS 0.25° "is released at the end of the real-time dissemination schedule" and 0.1° "about two hours after the 0.25° data". AIFS is "released as soon as" produced.
- In the dissemination schedule (https://confluence.ecmwf.int/display/DAC/Dissemination+schedule), the last 00z HRES step goes out at 07:34 and the last 12z step at 19:34. For 06z and 18z (capped at 144 h), it's 12:27 and 00:27.
- **Observed** `Last-Modified` dates:
  - 00z 0.25° step 0, 12 and 144: all **07:34** on 2026-11-05;
  - 12z 0.25° step 12: 19:34 on 2026-11-04; 12z 0.1° `-pl`: **21:34**;
  - AIFS 00z step 12: **05:49**.
- So IFS open data for tonight's 00z run lands at ~07:34, and for the 12z run at ~19:34. That's fine for a next-night product.
- **Retention:** "the most recent 12 forecast runs, roughly 2–3 days" (open-data page). The portal listed 2026-11-02 to 11-05.
- **AWS mirror:** `s3://ecmwf-forecasts` (eu-central-1), "No AWS account required" (https://registry.opendata.aws/ecmwf-forecasts/). An anonymous listing on 2026-11-05 shows dates from **2023-01-18** to 2026-11-05, including `20261104/12z/ifs/0p1/`. So there's a usable archive for verifying our forecasts against past nights.
- **Other mirrors:** the open-data page also names Azure (`ai4edataeuwest.blob.core.windows.net/ecmwf`) and Google (BigQuery) *[not opened]*.

**Access and sizes**
- One GRIB2 file per run, step and stream. The JSON-lines `.index` gives `_offset` and `_length` per field, so one variable or level can be fetched with an HTTP range request. **There is no area subsetting**: each field is global.
- **0.25°, per step:** `t` 3.8 MB, `u` 8.4, `v` 8.5, `z` 12.7 (14 levels each), and `tcc/lcc/mcc/hcc` 1.7 MB in total, so **~35 MB per step**. Steps 0–36 at 3 h make 13 files, **~0.46 GB per run**, which is the same for a box (crop after download) and for the globe.
- **0.1°, per step:** `t` 15.7, `u` 37.0, `v` 40.2, `z` 63.8, clouds 7.8, so **~165 MB per step, ~2.1 GB per run**.
- **AIFS, per step:** t + u + v + z 30.3 MB, clouds 1.3 MB; 7 steps (0–36 by 6) make **~0.22 GB**.
- **ENS 0.25°, step 12:** the whole file is 4.6 GB. `t+u+v+gh` for 50 members is ~1.37 GB per step, so **~18 GB per run** to 36 h *[from the index; not downloaded]*.

**Paid tier (only if we need model levels or hourly steps)**
- ECMWF's Service Charges page (https://confluence.ecmwf.int/spaces/DAC/pages/400498473/Service+Charges+From+01+July+2024) says that from 1 October 2025 the whole Real-Time Catalogue is "made open and available under the CC-BY-4.0 licence". The service charges apply to users who want more than the free open dataset or delivery to their own endpoint.
- The cheapest combination is **Volume Band 1 (0–1 GiB/day average) with the Basic pack: €500 per year**. Band 2 (1–10 GiB/day) costs €1,500 (Basic) or €1,600 (Bronze).
- The older pricing page (https://www.ecmwf.int/en/forecasts/accessing-forecasts/payment-rules-and-options) returned **HTTP 401**.
- *[unverified]*: which HRES model levels and steps a Band 1 subscription can deliver for a 10°×10° box, and whether ≤1 GiB/day is enough. Estimate: 137 levels × 4 variables × 37 hourly steps on 101 × 101 points at 0.1° is ~0.4 GB per run.

### NOAA GFS and GEFS (NOMADS and AWS)

**Licence**
- AWS registry (https://registry.opendata.aws/noaa-gfs-bdp-pds/): "NOAA data disseminated through NODD are open to the public and can be used as desired." It also says "NOAA requests attribution for the use or dissemination of unaltered NOAA data" and "it is not permissible to state or imply endorsement by or affiliation with NOAA".
- No non-commercial restriction. *[My reading]*: derived products on a public site are fine with a "Based on NOAA/NCEP GFS data" credit.

**Rate limits**
- NWS Service Change Notice 21-32 (effective about 2021-04-20, https://www.weather.gov/media/notification/pdf2/scn21-32nomad_changes.pdf, text extracted with `pdftotext`): "The usage policy will restrict individual user access to **120 hits/minute** for only the websites listed above" (nomads, ftp and ftpprd.ncep.noaa.gov), "applied as a sum of hits per user Internet Protocol (IP) address across all sites". I found no newer notice.
- The NWS abusive-use page (https://www.weather.gov/abusive-user-block) says the NWS may "block IP addresses or query types" and asks users to space retries at least a minute apart.
- The AWS bucket has no documented limit.

**Variables and levels** (read from `gfs.t00z.pgrb2.0p25.f012.idx` and `gfs.t00z.pgrb2b.0p25.f012.idx`, 2026-11-05 00z, on NOMADS)
- **`pgrb2` ("most commonly used"):** `TMP`, `UGRD`, `VGRD` and `HGT` on 41 levels: 0.01, 0.02, 0.04, 0.07, 0.1, 0.2, 0.4, 0.7, 1, 2, 3, 5, 7, 10, 15, 20, 30, 40, 50, 70, 100, 150, 200, 250, 300, 350, 400, 450, 500, 550, 600, 650, 700, 750, 800, 850, 900, 925, 950, 975, 1000 hPa.
- **`pgrb2b` ("least commonly used")** adds 125, 175, 225, 275, 325, 375, 425, 475, 525, 575, 625, 675, 725, 775, 825, 875 hPa.
- **Together, between 1000 and 50 hPa: 39 levels**: 50, 70, then every 25 hPa from 100 to 1000. That's more than ERA5's 37 levels over the whole column, and more than the 29 we use.
- **Cloud:**
  - **`TCDC` (cloud cover, %) on pressure levels** 50–1000 (22 levels in `pgrb2`, 17 more in `pgrb2b`: 70, 125, …, 875).
  - `TCDC` for the entire atmosphere, plus `LCDC`/`MCDC`/`HCDC` for the low/middle/high cloud layers, each instantaneous and as 6-hour averages.
  - Also cloud-layer top and base pressures, tropopause pressure and height, max-wind level, `PRES:surface` and `HGT:surface`.
- **Native model levels:** `gfs.t00z.atmfFFF.nc` (NetCDF) is published hourly on NOMADS and AWS at **6.4–6.8 GB per step**, global (listings). The EMC page says the model has "127 vertical layers" and "13 km resolution", and names GFS Version 16 (implemented 2021-03-22) as current (https://www.emc.ncep.noaa.gov/emc/pages/numerical_forecast_systems/gfs.php).
  - *[not checked]*: the chunk layout, i.e. whether a box or point can be range-read from that file.
  - *[unsure]*: whether a newer GFS (v17) is operational by 2026-11. I found no implementation notice for it.

**Steps, cycles, latency, retention**
- The NOMADS listing of `gfs.20261105/00/atmos/` shows `pgrb2.0p25` files **hourly f000–f120**, then 3-hourly to f384.
- The NCO product page lists "FH001-384" with no interval (https://www.nco.ncep.noaa.gov/pmb/products/gfs/).
- Four cycles a day (00/06/12/18; registry).
- **Observed:** 00z `f000` written 03:33, `f036` 03:43, `f120` 04:06 (NOMADS). On AWS, `f012` has `LastModified` 03:37:46, so it's the same within a minute.
- **Retention:** NOMADS keeps 10 days (`gfs.20261027`–`gfs.20261105` listed). The AWS bucket `noaa-gfs-bdp-pds` starts at `gfs.20210101/` (anonymous listing).

**Access and sizes**
- One GRIB2 file per step, with a `.idx` (byte offsets), so range requests work.
- NOMADS also has a **server-side grib filter** (`/cgi-bin/filter_gfs_0p25.pl`) that selects variables, levels and a **lat/lon subregion**. Test: `var_HGT/TMP/UGRD/VGRD/TCDC/LCDC/MCDC/HCDC`, `all_lev`, box 4.65–14.65°E × 54.67–64.67°N, f012. It returned HTTP 200, **0.57 MB**, valid GRIB2 on a 40 × 40 grid at 0.25° (54.75–64.5°N, 4.75–14.5°E, decoded from section 3).
  - The `pgrb2b` part (the 25-hPa in-between levels) needs a second request to `filter_gfs_0p25b`.
  - Box total *[estimate]*: ~0.8 MB per step, **~30 MB per run** for 0–36 h (74 requests, well under 120 hits/min).
- **Global, from the `.idx` byte ranges for step 12:**
  - TMP 46.8 MB, UGRD 46.7, VGRD 45.4, HGT 49.7, TCDC 15.0 (all 57 levels, `pgrb2` + `pgrb2b`), plus surface/layer cloud 8.0 MB: **~212 MB per step, ~7.8 GB per run**.
  - Dropping the levels above 50 hPa would cut this by roughly a third *[estimate]*.
  - The full `pgrb2.0p25.f012` is 539 MB; `pgrb2b` is 235 MB.

**GEFS** (NOMADS `gens/prod/gefs.20261105/00/atmos/`)
- **Members:** `gec00` plus `gep01`–`gep30` (31), and `geavg`/`gespr`, for f012.
- **Steps and resolution:** `pgrb2ap5`/`pgrb2bp5` at **0.5°, 3-hourly** (f000–f048 listed by 3).
- **Levels:** `TMP`, `UGRD`, `VGRD` and `HGT` on **23 levels from 1000 to 50 hPa** (1000, 975, 950, 925, 900, 850, 800, 750, 700, 650, 600, 550, 500, 450, 400, 350, 300, 250, 200, 150, 100, 70, 50).
- **Cloud:** entire-atmosphere `TCDC`, plus low/middle/high/convective/boundary-layer layer cloud. Pressure-level `TCDC` only at 475 hPa.
- **`pgrb2sp25` (0.25°)** has **no pressure-level fields**, only near-surface fields and entire-atmosphere `TCDC` (`.idx` read).
- **Latency and retention:** `gep01` f012 written 03:51; NOMADS keeps 4 days (`gefs.20261102`–`05`). The AWS bucket `noaa-gefs-pds` has 2026-11 runs (listing).

### DWD ICON, ICON-EU, ICON-D2 (opendata.dwd.de)

**Licence and attribution**
- https://www.dwd.de/copyright (German, quoted from the raw page): "Alle frei zugänglichen Geodaten und Geodatendienste sowie die als hochwertige Datensätze / high value datasets (HVD) festgelegten Leistungen des DWD dürfen unter den Bedingungen der Lizenz Creative Commons BY 4.0 (CC BY 4.0) unter Beigabe eines Quellenvermerks weiterverwendet werden. Zu den Geodaten zählen alle bereitgestellten meteorologischen Wetter- und Klimainformationen mit Ortsbezug."
- **Source-note templates** (https://www.dwd.de/DE/service/rechtliche_hinweise/vorlagen_quellenangabe.html):
  - unmodified data: "Quelle: Deutscher Wetterdienst";
  - modified data, e.g. "Datenbasis: Deutscher Wetterdienst, eigene Elemente ergänzt" or "… Einzelwerte gemittelt";
  - for extensive changes, at least a mention in a central source list or imprint.
  - So a seeing product derived from ICON would carry something like "Datenbasis: Deutscher Wetterdienst, eigene Elemente ergänzt".
- **No warranty:** DWD's open-data page says "service and availability levels cannot be guaranteed for this service" (https://www.dwd.de/EN/ourservices/opendata/opendata.html). It names no rate limit and no retention period.

**What's on the server** (directory listings, 2026-11-05)
- **ICON global** (`/weather/nwp/icon/grib/{00,06,12,18}/`): **icosahedral grid only** (files `icon_global_icosahedral_…`). There's no lat-lon version, so it must be remapped (`clat`/`clon` are provided).
  - `t`, `u`, `v`, `fi` (geopotential) on **18 pressure levels**: 30, 50, 70, 100, 150, 200, 250, 300, 400, 500, 600, 700, 800, 850, 900, 925, 950, 1000 hPa. That's 17 from 1000 to 50 hPa.
  - `t` on **120 model levels**; `hhl` (half-level heights) is provided.
  - `clc` on model levels only (levels 39–120); also `clct`, `clcl`, `clcm`, `clch`.
  - Steps hourly 000–078, then 3-hourly; the 00z run goes to 180 h and the 06z run to 120 h.
  - **Observed** 00z: step 0 at 02:39, step 36 at 02:52.
- **ICON-EU** (`/weather/nwp/icon-eu/grib/{00,03,…,21}/`, **8 cycles a day**):
  - **Regular lat-lon**; decoded from `HSURF`: 1377 × 657 points, **0.0625°**, 29.5–70.5°N, 336.5–62.5°E (= 23.5°W–62.5°E). **Covers southern Norway.**
  - `t`, `u`, `v`, `fi` and **`clc` on 20 pressure levels**: 50, 70, 100, 150, 200, 250, 300, 400, 500, 600, 700, 775, 800, 825, 850, 875, 900, 925, 950, 1000 hPa.
  - `t` and `clc` on **74 model levels**, plus `hhl`; also `clct/clcl/clcm/clch`, `ps`, `tke`, `ceiling`.
  - Steps hourly 000–078, then 3-hourly to 120 (00z run). The 03z run stops at 48 h.
  - **Observed** 00z: step 0 at 02:40, step 36 at 03:01.
- **ICON-D2:** regular lat-lon from `hsurf`: 1215 × 746 points, 0.02°, **43.18–58.08°N**, 356.06–20.34°E. **It does not reach Kongsberg (59.67°N).**
  - Pressure levels 200, 250, 300, 400, 500, 600, 700, 850, 950, 975, 1000 hPa; 65 model levels; steps 0–48 h.
- **Retention:** each cycle directory held only the latest run of that cycle (e.g. `icon/grib/06/` held 2026110506), so roughly 24 h. *[observed, not documented: I couldn't find a DWD page that states it]*

**Access and sizes**
- One bzip2-compressed GRIB2 file per variable, level and step. There's no index and no area subsetting, so whole fields are downloaded.
- **ICON-EU, step 12, from listings:**
  - pressure levels: `t` 19.1 MB, `u` 20.9, `v` 20.6, `fi` 15.6, `clc` 10.4 (20 levels each);
  - `clct/clcl/clcm/clch` 4.0 MB;
  - **~90 MB per step, ~3.3 GB per run** (0–36 h, whole domain).
  - Model levels are ~1 MB per field, so `t/u/v` on 74 levels is ~220 MB per step *[estimate from one file]*.
- **ICON global, step 12:** `t` 59.0, `u` 64.5, `v` 65.4, `fi` 48.7 (18 levels), plus clouds 13.9, so **~252 MB per step, ~9.3 GB per run**.

### MET Norway: MEPS (MetCoOp), MET Nordic, Locationforecast

**Licence**
- https://www.met.no/en/free-meteorological-data/Licensing-and-crediting (raw page, modified 1.2.2021):
  - "Data and products are licensed under Norwegian license for public data (NLOD) and Creative Commons 4.0 BY Internasjonal".
  - "Credit should be given to The Norwegian Meteorological institute, shortened “MET Norway”, as the source of data. Some suggestions: «Data from The Norwegian Meteorological Institute», «Based on data from MET Norway»."
  - Caveat: "Exceptions to the free principle apply to customised deliveries and with the dissemination of data produced by partners".
- MEPS is run by MetCoOp (MET Norway, SMHI and FMI). The MEPS files' own `license` attribute points to that same MET page, so I read MEPS on THREDDS as covered. The "partners" exception is the one thing to confirm with MET *[unsure]*.
- **api.met.no Terms of Service** (https://api.met.no/doc/TermsOfService; applies to Locationforecast, not stated for THREDDS):
  - requests must "include an identifying User Agent-string";
  - "Anything over 20 requests/second per application (total, not per client) requires special agreement";
  - honour `Expires` and use `If-Modified-Since`;
  - "truncate all coordinates to max 4 decimals";
  - attribution as CC BY 4.0.
- No terms or rate limits for thredds.met.no were found. The MEPS wiki doesn't state any either.

**MEPS deterministic (control member)** (OPeNDAP `.dds`/`.das` of `mepslatest/meps_det_2_5km_20261105T00Z.ncml`)
- **Grid:** 949 × 1069 points, Lambert, 2.5 km. Global attributes give `geospatial_lat_min/max` **49.8 / 75.2** and lon −18.1 / 54.2. **Covers Kongsberg:** the nearest grid point, index (y 376, x 304), is at 59.660°N 9.662°E.
- **Pressure levels (13):** 50, 100, 150, 200, 250, 300, 400, 500, 700, 800, 850, 925, 1000 hPa, with `air_temperature_pl`, `x_wind_pl`, `y_wind_pl`, `geopotential_pl`, `cloud_area_fraction_pl`, `relative_humidity_pl` and `specific_humidity_pl`.
- **Model levels (65 hybrid),** with `ap`, `b` and `p0` for pressure: `air_temperature_ml`, `x_wind_ml`, `y_wind_ml`, `cloud_area_fraction_ml`, `specific_humidity_ml`, **`turbulent_kinetic_energy_ml`** and `upward_air_velocity_ml`.
- **Surface and other:** `surface_air_pressure`, `surface_geopotential`, `cloud_area_fraction` (total), `low/medium/high_type_cloud_area_fraction`, `cloud_base_altitude`, `cloud_top_altitude`, max-wind level.
- **Winds are grid-relative:** `x_wind`/`y_wind` have `grid_mapping: projection_lambert`, so they must be rotated to east/north. A rotation doesn't change shear magnitude, so for S² only consistency matters *[inference]*.
- **Steps:** 67 hourly steps (0–66 h) in the 00z, 03z and 21z files I checked.
- **Runs:** the MEPS wiki (https://github.com/metno/NWPdocs/wiki/MEPS-dataset) says `meps_det_2_5km` is "updated every 3 hours and archived". `mepslatest` lists 00, 03, …, 21z files.
- **Latency:** the 00z file's `history` attribute says "2026-11-05T02:18:28 creation by fimex". The archive copy `meps25epsarchive/2026/11/05/meps_det_2_5km_20261105T00Z.nc` has modified date 04:09:11Z, and the 03z copy 06:36:37Z.
- **Retention:** `mepslatest` keeps files "for a few days" (wiki). The archive catalogue has years **2016–2026**; the wiki says "archive cleaning began in December 2024" *[archive strategy page not read]*.
- **Access:**
  - OPeNDAP and NCSS on THREDDS. A full archived 00z file is **74.3 GB**, so subsetting is essential. The wiki says `.ncml` files in latest "must be accessed via OPeNDAP, not downloaded directly".
  - **Test:** a profile of `air_temperature_ml`, `x_wind_ml` and `turbulent_kinetic_energy_ml` (65 levels, step 12, one grid point) returned HTTP 200, 9.8 kB of ASCII, in 3.8 s. First value: 207.13 K at the top level.
- **Box size *[estimate]*:** the box covers ~100,000 MEPS points (from a stride-4 lat/lon read), which is ~0.4 MB per field at float32. Pressure levels (5 variables × 13) come to ~26 MB per step, **~1 GB per run**. Model levels (`t/u/v/cc`, 4 × 65) come to ~104 MB per step, **~3.9 GB per run**.
- **Ensemble:** `meps_lagged_6_h_subset_2_5km` has "several surface parameters and some pressure-level parameters". The model levels are "archived only for the control member" (wiki).

**MET Nordic** (`metpplatest/met_forecast_1_0km_nordic_*.nc`)
- 1 km, surface fields only (`cloud_area_fraction`, precipitation, wind, gust, …), 57 steps.
- `summary`: "Based on model data from MEPS (MetCoOp-Ensemble Prediction System) and observations".
- That makes it **post-processed, not raw**, and it has no profiles.

**Locationforecast 2.0**
- **Test** (`/complete?lat=59.67&lon=9.65`, with a User-Agent): HTTP 200; `Expires` 30 min after `Last-Modified`; 83 time steps, hourly at first and 6-hourly later, to 10 days.
- **Variables:** surface variables, including `cloud_area_fraction` and its high/low/medium parts and `fog_area_fraction`. **No profiles.**
- The documentation (https://api.met.no/weatherapi/locationforecast/2.0/documentation) names no source models. It mentions temperature correction with "the internal topography model". It is a **finished, processed forecast**, so it's out of scope as an input under Riley's rule.

### DMI HARMONIE DINI (added: a Nordic regional model)

- **Licence** (https://www.dmi.dk/friedata/dokumentation/terms-of-use): "DMI's Open Data are distributed under the Creative Commons License CC BY 4.0." "The license terms were changed November 30th 2023." "user registration is no longer required". APIs are "subject to fair use guidelines", and DMI "may apply rate limiting, if misuse is detected".
- **Model** (https://www.dmi.dk/friedata/dokumentation/data/forecast-data-weather-model-harmonie-for-dini-and-ig):
  - DINI spans "43°W–40°E and 37°N–70°N"; the STAC `bbox` is −43.17, 37.69, 40.07, 69.91. Resolution 2 km, **90 model levels**.
  - Pressure-level output on up to 16 levels, but each variable only on a subset.
  - DMI "only collects the deterministic run every third hour"; 60-hour forecasts.
- **Pressure-level parameters** (EDR metadata, https://opendataapi.dmi.dk/v1/forecastedr/collections):
  - `temperature` on only **11 levels** (100, 200, 300, 400, 500, 600, 700, 850, 925, 950, 1000);
  - `geopotential`, u/v wind, wind speed and direction on 15 (100–1000; **no 50 hPa**);
  - no cloud on pressure levels.
  - The model-level table on DMI's page lists t, u and v on levels 1–90.
- **Collections** (https://opendataapi.dmi.dk/v1/forecastdata/collections): `harmonie_dini_sf`, `harmonie_dini_pl`, `harmonie_dini_ml`, and EPS means, percentiles and probabilities.
- **Access and latency:**
  - STAC items link to anonymous S3 objects (`dmi-opendata.s3.eu-north-1.amazonaws.com`), hourly steps.
  - The 06z run's step 60 PL file was created 08:31, and the ML file 08:58.
  - Sizes per step (whole domain): **PL 502 MB, ML 5.14 GB, SF 619 MB**.
  - STAC keeps "the latest 48 hours"; EDR (JSON, point/area queries) keeps "the latest 24 hours" (https://www.dmi.dk/friedata/dokumentation/forecast-data).
  - DMI's docs site `opendatadocs.dmi.govcloud.dk` returned **HTTP 404** for the pages search engines index, and the old `dmigw.govcloud.dk` gateway failed through our proxy (502). I used `opendataapi.dmi.dk`, which answered.

### Open-Meteo (API and self-hosting)

- **Terms** (https://open-meteo.com/en/terms):
  - Free API: "Less than 10'000 API calls per day, 5'000 per hour and 600 per minute"; non-commercial only. Commercial examples are "Websites or apps that have subscriptions or display advertisements".
  - "The data obtained through the API is provided under the terms of the CC-BY 4.0 licence".
  - Pricing (https://open-meteo.com/en/pricing): requests "covering more than 10 weather variables" count as several calls. A full profile (19 levels × 4 variables) is ~8 calls per model per location.
- **Attribution** (https://open-meteo.com/en/licence): "You must include a link next to any location Open-Meteo data are displayed", e.g. "Weather data by Open-Meteo.com". It lists each provider's licence: DWD, ECMWF, MET Norway and DMI are CC BY; NOAA has its own; the **UK Met Office is CC BY-SA**. The server code is AGPLv3.
- **Variables** (https://open-meteo.com/en/docs):
  - Up to **19 pressure levels**: 1000, 975, 950, 925, 900, 850, 800, 700, 600, 500, 400, 300, 250, 200, 150, 100, 70, 50, 30 hPa. Variables: temperature, dewpoint, RH, **cloud cover** ("approximated based on relative humidity using Sundqvist et al. (1989)"), wind speed and direction, and geopotential height. **u/v are not listed.**
  - `elevation=nan` turns off downscaling.
- **ECMWF via Open-Meteo** (https://open-meteo.com/en/docs/ecmwf-api):
  - 13 levels (1000–50).
  - "Pressure-level data is available only from the 0.25° open-data models".
  - "The Open-Meteo API dynamically interpolates all data to a consistent 1-hourly time-series".
- **So:** Open-Meteo's hourly profiles from a 3-hourly model are time-interpolated, and its level cloud is derived from RH. **These are processed values, not raw model output.**
- **Self-hosting** (https://github.com/open-meteo/open-data; https://registry.opendata.aws/open-meteo/):
  - Public bucket `s3://openmeteo` (us-west-2), CC BY 4.0, in the `.om` format.
  - Docker `ghcr.io/open-meteo/open-meteo` with `sync` and `serve`.
  - The README's tables list pressure-level variables for `ecmwf_ifs025` on **9 levels**, `dwd_icon_eu` on **17**, `ncep_gfs025` on **38**, and **none** for `metno_nordic_pp`.
  - `data_run` "includes only 13 pressure levels", and run-based data stay public for 3 months.
- **Not verified:** which levels each model actually returns through the API. My one test call was refused with "Daily API request limit exceeded" on our shared egress IP. The docs' 19 levels, the ECMWF page's 13 and the bucket README's 9/17/38 don't agree, so treat any per-model level count as unverified.

### 7Timer!

- **Terms** (https://www.7timer.info/doc.php, raw page): "The weather data distributed in this site are entirely free – you can use or redistribute them as long as you are not using them for commercial purpose. Program developers are asked to notify me when using the data so I can track the server workload." The page says it was last updated in 2012.
- **Model:** GFS-based (RESEARCH §3.5, Ye 2011).
- **Test** (`/bin/api.pl?lon=9.65&lat=59.67&product=astro&output=json`): init `2026110500`, 24 time points **3-hourly from +3 to +72 h**. Values are classes: `cloudcover` 1–9, `seeing` 1–8, `transparency`, `lifted_index`, `rh2m`, 10 m wind, `temp2m`.
- **This is a finished forecast** (classes, no profiles), so it's **out of scope as an input**. It is useful as a comparison: it's what amateur astronomers already look at.

### UK Met Office global (noted, not pursued)

- The AWS registry (https://registry.opendata.aws/met-office-global-deterministic/) gives ~10 km, hourly to 54 h, the licence **CC BY-SA 4.0**, and a "rolling archive of the past two years".
- The bucket has `temperature_on_pressure_levels`, `wind_speed_on_pressure_levels`, `height_ASL_on_pressure_levels` and `cloud_amount_on_height_levels` (key listing of one 2025-12 run).
- **But** the newest `global-deterministic-10km/` run listed on 2026-11-05 is **20260907T1800Z**, with no October or November runs, so the feed looks stopped. The UK 2 km feed's newest is 20260211.
- Share-alike would also bind our derived products. I didn't check its levels.

## Not documented / unsure

- **Latencies are one day's observations** (file timestamps), not service levels. ECMWF and DWD are documented; MEPS and DMI are not.
- **DWD retention** (≈ one run per cycle) and **thredds.met.no limits**: no primary statement found.
- **NOMADS 120 hits/min** comes from a 2021 notice; I found nothing newer either way.
- **GFS version:** EMC's page says v16 (127 layers, ~13 km). I couldn't confirm whether v17 has been implemented.
- **ECMWF open-data service agreement wording:** the Terms of Use say users "are required to sign a service agreement … to receive services related to the provision of this dataset". I read it as not covering anonymous portal downloads, but it isn't stated outright.
- **MET licence "partners" exception:** whether it applies to MEPS (a MetCoOp product). The files point to MET's CC BY/NLOD page.
- **Open-Meteo per-model levels:** the API test was blocked by its daily limit on our shared IP.
- **ECMWF ENS control member** placement in open data, and **AIFS-ENS** levels: not checked.
- **GFS native `atmf` NetCDF**: whether HTTP range reads of a box are practical (chunking not inspected).
- **DINI model-level cloud** fields: not checked.
- **ECMWF paid tier contents:** exactly what Band 1 (€500/yr) delivers (HRES model levels, hourly steps, area cut-out) needs confirming with ECMWF.

## Verdict per source for v1

- **GFS 0.25° — fits.**
  - The most levels (39) with level cloud, hourly, ~3.6 h latency.
  - A server-side box cut keeps downloads to tens of MB, it has a 5-year AWS archive for verification, and it has no licence friction.
- **ICON-EU — fits.**
  - ~7 km, hourly, 20 pressure levels with `clc`, and 74 model levels with `hhl` for a later model-level path. CC BY 4.0, ~3 h latency.
  - Cost: ~3.3 GB per run of whole-domain files.
- **MEPS — fits** (Nordic default).
  - 2.5 km, hourly, every 3 h. 65 model levels with cloud fraction and TKE, through OPeNDAP point/box subsetting. CC BY 4.0 / NLOD.
  - Pressure levels are only 13, so use model levels for seeing.
- **ECMWF IFS open (0.25°/0.1°) — fits as the fourth model**, with caveats: 3-hourly steps, 14 levels, no level cloud, and a ~7.5 h delay.
  - It's the model family behind ERA5, so it's the closest match to our climatology inputs *[inference]*.
  - On an hourly timeline it needs a rule for the in-between hours. Never interpolate seeing (AGENTS.md); show 3-hourly points instead.
- **AIFS Single — doesn't fit v1** (6-hourly).
- **GEFS / ECMWF ENS — later.** Ensembles: 0.5° 3-hourly with 23 levels (GEFS); ~18 GB per run to 36 h (ENS).
- **ICON global — later** (global phase; icosahedral remap; ~9.3 GB per run).
- **ICON-D2 — doesn't fit:** it doesn't cover Kongsberg.
- **DMI DINI — doesn't fit v1 for seeing.**
  - Sparse pressure-level T (11 levels, no 50 hPa) and 5 GB-per-step model levels.
  - Its single-level cloud (619 MB per step, or EDR JSON) could add a fifth cloud opinion later.
- **Open-Meteo — doesn't fit as an input** (processed: time-interpolated, RH-derived level cloud; free API non-commercial). Useful for prototyping and cross-checks, and self-hosting it is possible.
- **7Timer!, Locationforecast, MET Nordic — don't fit** (finished or post-processed products). Possibly comparison panels.
- **UK Met Office — doesn't fit** (feed appears stopped since 2026-09-07; CC BY-SA).

## Open questions for Riley / the planning session

1. **Pressure levels or model levels for seeing:** start v1 with pressure levels everywhere (simple, comparable across models), or go straight to model levels where they're open (MEPS 65, ICON-EU 74)? Pressure levels range from 13 (MEPS/IFS) to 39 (GFS).
2. **Calibration:** our ERA5 calibration assumes ERA5's 29-level sampling. Do forecast-model seeing values get their own calibration, or are they shown uncalibrated, with a label?
3. **Timeline with mixed cadences:** IFS is 3-hourly and the others hourly. Show the native steps only (no interpolation of seeing)?
4. **"Public on Riley's own domain":** CC BY sources need visible attributions (ECMWF's set wording, DWD's "Datenbasis" note, MET and NOAA credits). Is a single attribution panel acceptable?
5. **Paid ECMWF Band 1 (€500/yr):** worth asking ECMWF what it would deliver (HRES model levels, hourly, box), or not until v1 shows a need? [ASK] before any spend.

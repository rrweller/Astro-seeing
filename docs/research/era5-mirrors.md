# ERA5 mirrors for the phase 3 global run: NCAR on AWS and Google ARCO-ERA5

Issue #12 (map: #6). Researched 2026-10-30 by the agent. Sources are primary: dataset pages, the AWS registry entry, the ARCO-ERA5 README and configs, the CDS catalogue, and the files' own metadata. Every link below was loaded on 2026-10-30 and says what is cited, except where marked.

**Question.** Could the NSF NCAR ERA5 copy on AWS (`s3://nsf-ncar-era5`, RDA/GDEX d633000) or Google's ARCO-ERA5 (`gs://gcp-public-data-arco-era5`) replace or supplement the CDS for 2021–2025? We need 29 pressure levels × (z, t, u, v, cc), hourly, plus the 17 single-level variables in RESEARCH §7. The CDS now runs one job at a time per account (D39), at about 5.6 fields/s (D40).

## Short answer

Both mirrors hold every variable we need, on the same 0.25° grid, and all of 2021–2025 is present: I listed every file or chunk. Neither adds a licence restriction beyond CC-BY 4.0 plus a citation request. Neither has a queue. But neither is bit-identical to CDS GRIB:

- **NCAR** is the closer copy. It is float32 converted from GRIB1, with near-lossless 7-significant-digit quantisation plus deflate.
- **ARCO** comes from CDS NetCDF, which was re-packed to 16 bits with one scale per day-file, so the values are quantised twice.

Both are whole-globe, all-37-level chunks, so we would download 8 unused levels. **NCAR looks like the better candidate for the global run.** It needs ~12 TB of transfer, about 3–7 days at the bandwidth we already measured, against ~15 days of CDS processing at 5.6 fields/s. First, an equivalence test against our CDS GRIB is needed, and Riley's OK for a new source and format ([ASK]).

| | **CDS** (current) | **NCAR on AWS** (d633000) | **Google ARCO-ERA5** (`ar/full_37-1h-0p25deg-chunk-1.zarr-v3`) |
|---|---|---|---|
| Licence | CC-BY 4.0 | CC-BY 4.0 (UCAR terms). Asks that you use NCAR's recommended citation (DOI 10.5065/BH6N-5N20) | Data "according to the terms of the Copernicus license". Asks you to cite Carver & Merose 2023 and ERA5. Code is Apache-2.0 |
| Our pressure-level vars (z, t, u, v, **cc**) | yes | yes; `cc` is `128_248_cc` | yes; `fraction_of_cloud_cover` |
| Our 17 single-level vars (incl. **ishf**, **zust**, cbh, lcc/mcc/hcc) | yes | yes. `ishf` is in `an.sfc`; `zust` and `cbh` are in `fc.sfc.instan` (forecast layout) | yes, all 17 |
| Fixed fields (z, lsm, sdor) | yes | yes (`e5.oper.invariant`) | yes, but stored as time-dependent arrays |
| Levels | any of 37 | 37 in every file (1–1000 hPa); 8 unused by us | 37 in every chunk; 8 unused by us |
| Grid | 0.25° regular, regridded by the CDS | 0.25°, 721 × 1440, 90N→90S, 0→359.75E | 0.25° equiangular, 721 × 1440 |
| 2021–2025 complete? | yes | **yes**: 60/60 months, every file present (listed) | **yes**: 43,824/43,824 hourly chunks present for the 8 variables listed |
| Lag | ERA5T ~5 days; final 2–3 months later | "Monthly, with a 3–4 month lag". Latest month 2026-07 (pl, sfc), 2026-06 (instan) | Final ERA5 to 2026-06-30, ERA5T to 2026-10-21 (store metadata) |
| Encoding | GRIB1, 16-bit simple packing per field | NetCDF4, float32, NCO BitGroom NSD = 7, shuffle + deflate 1. One file per variable per day (pl) or month (sfc) | Zarr (v2 format), float32, Blosc-LZ4. Built from CDS **NetCDF** (int16, one scale and offset per day-file) |
| Bit-identical to CDS GRIB? | — | No. Values within float32 / 7-digit rounding of decoded GRIB *[my inference; to be measured]* | No. A second 16-bit quantisation on top of GRIB's *[inference; to be measured]* |
| Access / cost to us | account + licence; free | anonymous HTTPS/S3, not requester-pays; free to us | anonymous HTTPS/GCS; "free" (Google pays hosting) |
| Queue | one job per account | none | none |
| Documented throughput | none (ours: 5.6–26 fields/s) | none (ours, one file, D29: 21 MB/s on 1 stream, 47 MB/s on 6) | none; not measured by us |
| 5-year volume for our variables | ~7.1 M fields, ~13 TB GRIB (RESEARCH §8) | **~11.9 TB** (pl 10.65 TB listed; sl ~1.25 TB from one month) | **~21 TB** (pl 18.9 TB from chunk sizes; sl ~2.2 TB estimate) |

## Findings, each with its source

### Licence and attribution

- **CDS:** the catalogue entry for `reanalysis-era5-pressure-levels` gives `"license": "CC-BY-4.0"` and links https://spdx.org/licenses/CC-BY-4.0 (https://cds.climate.copernicus.eu/api/catalogue/v1/collections/reanalysis-era5-pressure-levels). Our attribution text is in RESEARCH §7 and `provenance.py`.
- **NCAR (data):** the DataCite record for DOI 10.5065/BH6N-5N20 gives rights "Creative Commons Attribution 4.0 International" (SPDX `cc-by-4.0`), publisher "NSF National Center for Atmospheric Research", format NetCDF4, size 711.647 TB (https://api.datacite.org/dois/10.5065/BH6N-5N20).
- **NCAR (terms):** the AWS registry entry names the licence as https://www.ucar.edu/terms-of-use/data. That page grants use of copyrighted material "subject to the terms and conditions of the Creative Commons Attribution 4.0 International license", and the user agrees "to use the recommended data citation format provided by that UCAR data repository". Materials are provided "AS IS". It says nothing about third-party (ECMWF) terms.
- **NCAR citation** (registry entry): "European Centre for Medium-Range Weather Forecasts. 2019, updated monthly. ERA5 Reanalysis (0.25 Degree Latitude-Longitude Grid). Research Data Archive at the National Center for Atmospheric Research, Computational and Information Systems Laboratory. https://doi.org/10.5065/BH6N-5N20." Sources: https://registry.opendata.aws/nsf-ncar-era5/ and https://raw.githubusercontent.com/awslabs/open-data-registry/main/datasets/nsf-ncar-era5.yaml.
- **ARCO:** the README FAQ says "you can use our ERA5 data according to the terms of the Copernicus license". It asks researchers to cite Carver & Merose (2023), "ARCO-ERA5: An Analysis-Ready Cloud-Optimized Reanalysis Dataset", 22nd Conf. on AI for Env. Science, AMS, plus Hersbach et al. and the Copernicus attribution. The repository licence is Apache-2.0; that covers the code (https://github.com/google-research/arco-era5).
  - The README's licence link (`https://cds.climate.copernicus.eu/api/v2/terms/static/licence-to-use-copernicus-products.pdf`) now returns **HTTP 404**. It points to the pre-July-2025 Copernicus licence; the CDS now lists CC-BY-4.0.
- **Google page:** "Google pays for the hosting of these datasets" and the datasets are "available for users to access for free" (https://docs.cloud.google.com/storage/docs/public-datasets). The ERA5 page there names the bucket and states no dataset-specific terms (https://docs.cloud.google.com/storage/docs/public-datasets/era5).
- **So:** neither mirror restricts use beyond CC-BY 4.0. Using one adds a citation to our attribution: NCAR's DOI or Carver & Merose. The Copernicus attribution still applies, because the data is still Copernicus data.

### Variables, levels, grid, completeness

**NCAR**

What I ran: anonymous `ListObjectsV2` on `https://nsf-ncar-era5.s3.us-west-2.amazonaws.com/` (metadata only, no credentials), plus HTTP range reads of the NetCDF4/HDF5 headers of 5 files (~0.6–1 MB each, no data chunks).

- **Layout:** top-level prefixes are `e5.oper.an.pl/`, `e5.oper.an.sfc/`, `e5.oper.an.vinteg/`, `e5.oper.fc.sfc.accumu/`, `e5.oper.fc.sfc.instan/`, `e5.oper.fc.sfc.meanflux/`, `e5.oper.fc.sfc.minmax/` and `e5.oper.invariant/`.
- **Pressure levels:** one file per variable per day, e.g. `e5.oper.an.pl/202306/e5.oper.an.pl.128_248_cc.ll025sc.2023061500_2023061523.nc`. Our five are `128_129_z`, `128_130_t`, `128_131_u` and `128_132_v` (u and v are tagged `ll025uv`), and `128_248_cc`.
  - The `level` coordinate in the cc file holds all 37 levels, 1…1000 hPa. The variable is `(24, 37, 721, 1440)`, chunked `(1, 37, 721, 1440)`. So one hour of one variable is one chunk with every level, and levels can't be read separately.
- **Single levels:** one file per variable per month in `an.sfc`. Our 15 there are tcc, lcc, mcc, hcc, sp, 2t, 2d, skt, 10u, 10v, 100u, 100v, blh, **ishf (`128_231_ishf`)** and tcwv.
  - **zust (`228_003_zust`)** and **cbh (`228_023_cbh`)** are in `fc.sfc.instan`, two files a month, as forecasts: `ZUST(forecast_initial_time=30, forecast_hour=12, 721, 1440)`, with initial times 06 and 18 UTC. A file runs from 06 UTC on the 1st to 06 UTC on the 16th, so the first hours of a month are in the previous month's file.
- **Fixed fields:** `e5.oper.invariant/197901/…128_129_z…`, `…128_172_lsm…` and `…128_160_sdor…` are present.
- **Grid** (variable attribute `grid_specification`): "0.25 degree x 0.25 degree from 90N to 90S and 0E to 359.75E (721 x 1440 Latitude/Longitude)".
- **Completeness 2021-01 → 2025-12:** every month has exactly one file per day for each of z, t, u, v and cc (1,826 each), one file for each of the 15 `an.sfc` variables, and two for zust and cbh. Problems found: 0.
- **Sizes, 2021–2025 (listed):** z 1.94 TB, t 2.34, u 2.86, v 3.10, cc 0.42; **pressure levels 10.65 TB** (per day: z ~1.06 GB, t ~1.28, u ~1.57, v ~1.70, cc ~0.23).
  - Single levels: June 2023's 17 files total 20.9 GB, so 5 years is **~1.25 TB** *[estimate from one month]*.
- **Registry description:** "Atmospheric data on these levels are interpolated to 37 pressure levels (the same levels as in ERA-Interim)" and "The data are provided in CF-compliant NetCDF4 format files" (registry YAML above).

**ARCO**

What I ran:
- an anonymous read of `https://storage.googleapis.com/gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3/.zmetadata` (133 kB);
- anonymous GCS JSON-API object listings (names and sizes only) of the chunks for 2021–2025, for 8 variables;
- a listing of `raw/date-variable-pressure_level/{2022,2025}/06/15/fraction_of_cloud_cover/`;
- the first 8 kB (header) of two raw NetCDF files.

- **Variables:** the store has all of ours as `(time, level=37, 721, 1440)` or `(time, 721, 1440)` float32 arrays: geopotential, temperature, u/v_component_of_wind, **fraction_of_cloud_cover**, total/low/medium/high_cloud_cover, cloud_base_height, surface_pressure, 2m_temperature, 2m_dewpoint_temperature, skin_temperature, 10m/100m u/v, boundary_layer_height, **friction_velocity**, **instantaneous_surface_sensible_heat_flux** and total_column_water_vapour. Fixed fields: geopotential_at_surface, land_sea_mask, standard_deviation_of_orography (stored per hour).
- **README:** levels `1/2/3/5/7/10/20/30/50/70/100/…/975/1000`, "Grid: equiangular lat-lon", chunking `{'time': 1, 'latitude': 721, 'longitude': 1440, 'level': 37}`, "Chunk size (per variable): 154 MB", total size 2.05 PB. "This dataset contains most pressure-level fields and all surface-level field regridded to a uniform 0.25° resolution."
- **Completeness 2021-01-01 00 → 2025-12-31 23:** 43,824 of 43,824 hourly chunk objects are present for geopotential, temperature, u, v, fraction_of_cloud_cover, instantaneous_surface_sensible_heat_flux, friction_velocity and cloud_base_height. Missing: 0. The other 9 single-level variables weren't listed.
- **Compressed chunk sizes (median, per hour):** z 80.3 MB, t 85.0, u 117.5, v 121.6, cc 27.6. That makes 432 MB per hour, **18.9 TB for 5 years of pressure levels**. Single-level chunks are ~2.8–3.3 MB each (ishf, zust, cbh), so 17 variables come to **~2.2 TB** *[estimate]*.
- **Store format:** the metadata is Zarr format 2 (`.zgroup` `zarr_format: 2`), despite the `zarr-v3` in the name. The time axis is pre-allocated (1,323,648 hours), so the valid range must be taken from the attributes.

### Lag

- **CDS:** "ERA5 is updated daily with a latency of about 5 days. In case that serious flaws are detected in this early release (called ERA5T), this data could be different from the final release 2 to 3 months later." The catalogue's temporal extent ended on 2026-10-24 when read on 2026-10-30 (CDS catalogue entry above).
- **NCAR:** "Monthly, with a 3-4 month lag from realtime" (registry).
  - Observed on 2026-10-30: `an.pl` and `an.sfc` run to **2026-07**, uploaded 2026-10-08 (the July t file's history line reads "Wed Oct 7 15:14:03 2026: ncks …"); `fc.sfc.instan` runs to **2026-06**.
  - Whether NCAR ingests ERA5T or only final ERA5 isn't documented. The timing fits final ERA5.
- **ARCO:** "The stable version of ERA5 is updated on a monthly cadence (on roughly the 9th of each month) with a 3 month delay. The preliminary version of ERA5, known as ERA5T is available with approximately 1 week delay" (README).
  - Live metadata on 2026-10-30: `valid_time_stop` 2026-06-30, `valid_time_stop_era5t` 2026-10-21, `last_updated` 2026-10-30 12:24 UTC.
  - Raw files carry `*_ratified` markers (e.g. 2025-06-15, written 2025-11-26). The README describes a job that compares "era5 vs era5t and replace in case of difference".
- **For 2021–2025 the lag doesn't matter:** all of it is final ERA5 in every copy.

### Encoding: are values identical to CDS GRIB?

- **Our CDS data:** GRIB1, 16-bit simple packing, with a reference value and binary scale per field (RESEARCH §7).
- **NCAR (file headers):**
  - `DATA_SOURCE: "ECMWF: https://cds.climate.copernicus.eu, Copernicus Climate Data Store"`;
  - `NETCDF_CONVERSION: "CISL RDA: Conversion from ECMWF GRIB 1 data to netCDF4."`;
  - `original_format: "WMO GRIB 1 with ECMWF local table"`;
  - variables are float32, `_FillValue` 9.999e20, chunks `(1, 37, 721, 1440)`, filters shuffle + gzip level 1;
  - `history` reads `ncks -4 -L 1 --baa=0 --ppc T=7 …` (2025–2026 files) or `--ppc default=7` (a 2023 conversion); `quantization_nsd = 7`.
  - In the NCO manual, `--baa=0` selects "BitGroom (NSD)" and `--ppc` keeps NSD significant digits. Its worked example keeps π as 3.14159262 against an exact float32 3.14159265 at NSD = 7 (https://nco.sourceforge.net/nco.html, "Precision-Preserving Compression").
- **So NCAR, *[inference]*:** each value is the GRIB-decoded value rounded to float32 and then to ~7 significant digits, a relative error of order 1e-7. For T ≈ 250 K that is at most ~5e-5 K. The GRIB 16-bit step (a power of 2 at least range/65535) for a field spanning ~80 K is ~2e-3 K. NCAR's rounding is therefore well below GRIB's own quantisation, but the bits differ from what our decoder gives for CDS GRIB.
  - Not documented: whether NCAR's source GRIB was packed with the same bits per value as the GRIB we get from the CDS today.
- **ARCO, raw (config and headers):** the pressure-level config requests `client=cds`, `dataset=reanalysis-era5-pressure-levels`, `format=netcdf`, `grid=0.25/0.25`, written to `raw/date-variable-pressure_level/{date}/{variable}/{level}.nc` (https://raw.githubusercontent.com/google-research/arco-era5/main/raw/daily/era5_pl_hourly.cfg).
  - The raw headers I read (cc, 500 hPa, 2022-06-15 and 2025-06-15) are NetCDF-3 64-bit-offset. `cc` is **`short`** with `scale_factor` 1.5259e-05 and `add_offset` 0.49999, made by `grib_to_netcdf` (2.25.1 at the CDS in 2023; 2.41.0 run by Google in 2025).
  - Each file is ~49.85 MB, which is 24 × 721 × 1440 × 2 bytes plus a header: 16-bit, uncompressed.
- **ARCO, analysis-ready store:** float32 with Blosc-LZ4 (`.zmetadata`). The README links every variable of the store to these raw configs.
- **So ARCO, *[inference]*:** the analysis-ready values are CDS GRIB re-quantised by `grib_to_netcdf` to 16 bits with one scale and offset per file (a whole day, all 24 hours), then stored as float32. That second quantisation adds up to about half a NetCDF step to each value, the same order as GRIB's own packing error. It's small for the physics, but the values are neither bit-identical to CDS GRIB nor as close as NCAR's.
- **ARCO's word "regridded":** the README says the analysis-ready data is "regridded" to 0.25°. The config shows the 0.25° grid comes from the CDS request (`grid=0.25/0.25`), as with our own data. The CDS itself describes its product as "a regridded subset of the full ERA5 data set on native resolution" (CDS catalogue).
  - Not documented: whether Google did any further regridding for this store.
- **Does it matter?**
  - For seeing, *[inference]* no, not physically: J depends on vertical gradients of T and wind, and both mirrors' rounding is at or below the 16-bit GRIB step.
  - For our rules, yes. Phase 1 golden tests and calibration were made from CDS GRIB, and AGENTS.md says GRIB downloads and [ASK] before changing what validated results depend on. Equivalence must be measured, not assumed (see the recommendation below).

### Access and cost

- **NCAR:** registry: "AWS CLI Access (No AWS account required)" with `aws s3 ls --no-sign-request s3://nsf-ncar-era5/`; region `us-west-2`. There's an SNS topic for new objects.
  - The YAML has no `RequesterPays` entry, and my anonymous listings and range reads worked without credentials.
  - The AWS Open Data Sponsorship Program "covers the cost of storing and sharing publicly available, high-value, cloud-optimized datasets" (https://aws.amazon.com/opendata/open-data-sponsorship-program/). It doesn't say anything explicit about user egress, but with no credentials we can't be billed.
- **ARCO:** "The `gcp-public-data-arco-era5` bucket is stored in the `us-central1` (Iowa) Google Cloud region" (README). Google: "Google pays for the hosting", free to access, and API access "does not require authentication" (Google public-datasets page). Anonymous HTTPS reads worked.
- **Documented throughput:** none for either; nothing on rate limits or etiquette either.

## Not documented / unsure

- **NCAR's dataset page** (https://gdex.ucar.edu/datasets/d633000/, also https://rda.ucar.edu/datasets/d633000/) returned **HTTP 503** on every attempt on 2026-10-30. From the shell, TLS to those hosts also failed to verify. So I couldn't read NCAR's own documentation page (processing notes, update policy, any known-issue list). Their claims above rely on the registry entry, the DataCite record and the files' own attributes. This page should be re-checked before any decision.
- **Packing of NCAR's source GRIB:** whether it had the same bits per value as the CDS's GRIB today, and whether NCAR re-fetches months that ECMWF later corrects.
- **ERA5T or final at NCAR:** which one NCAR loads (the timing suggests final).
- **Further regridding at ARCO:** whether Google did anything beyond the CDS's 0.25° output, and whether every analysis-ready variable for 2021–2025 was built from the `grib_to_netcdf` raw files. I checked one variable's raw headers on two dates. The 2025 file was converted by Google's own `grib_to_netcdf` 2.41.0, so it may have been fetched as GRIB.
- **Throughput:** neither mirror documents throughput or concurrency etiquette. We haven't measured ARCO at all.
- **Volume estimates:** single-level volumes are estimates from one month (NCAR) or three variables (ARCO). The other 9 ARCO single-level variables weren't listed for completeness.
- **ARCO's licence link** is dead (404). Its "Copernicus license" wording predates the CC-BY switch. I read it as "same terms as the CDS", but that's my reading.

## Recommendation: what it would take to measure throughput on the CT *[recommendation, not done]*

All of this stays under the 50 GB / 24 h [ASK] threshold, needs no credentials, and costs nothing:

1. **NCAR bandwidth (~15 GB, under 1 h).** On the CT, fetch one full day of our five pressure-level files: ~5.8 GB, for example 2023-06-15.
   - Use anonymous HTTPS to `/staging/tmp`, with 1, 2, 4 and 6 parallel streams. Do it at two times of day (e.g. 03 and 15 UTC).
   - Record MB/s per run, with timeouts. D29 measured one 1.3 GB file at 21 MB/s (1 stream) and 47 MB/s (6 streams); this tests whether that holds.
2. **ARCO bandwidth (~10 GB).** Read 24 hourly chunks of `temperature` and `u_component_of_wind`, ~4.9 GB, by parallel anonymous GETs on `storage.googleapis.com` (1–8 streams). Record MB/s the same way.
3. **Equivalence with CDS GRIB (the deciding test).** Take one NCAR day and the matching ARCO hours for a day already on `/data` from the CDS: the Chile/Paranal 2021–2025 pressure-level areas.
   - For each variable and level, compute the max and RMS difference against our GRIB-decoded values at the same grid points, and compare it to that field's GRIB packing step.
   - Expected *[inference]*: NCAR within float32 / 7-digit rounding; ARCO within ~0.5 NetCDF step.
   - Then run the phase 1 physics on all three and compare J, seeing and the nightly good/bad flags. The phase 1 golden tests must pass unchanged.
4. **zust / cbh layout check:** map NCAR's (initial time, forecast hour) to valid time for one month boundary, and compare to the CDS hourly values.
5. **If NCAR passes:** at the measured 21–47 MB/s, 5 years (~11.9 TB) is ~3–7 days of transfer with no CDS queue, against ~14.7 days of CDS processing (7.1 M fields at 5.6 fields/s, D40) plus ~13 TB of transfer.
   - The CDS could then serve only what the mirror lacks, or act as a cross-check sample.
   - Before adopting it: [ASK] Riley. It's a new data source, with a citation term and a non-GRIB format, and it touches the downloader (manifest rows per file, checksums, verify on NetCDF), the ingest, provenance and attribution. Record it as a D-number.

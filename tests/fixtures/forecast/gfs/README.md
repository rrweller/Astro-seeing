# GFS test samples

**Credit:** NOAA/NCEP Global Forecast System (GFS) 0.25°, from NOAA's NOMADS server
(https://nomads.ncep.noaa.gov/). US-government open data: "NOAA data disseminated
through NODD are open to the public and can be used as desired"; NOAA requests
attribution, and no endorsement by or affiliation with NOAA is stated or implied
(https://registry.opendata.aws/noaa-gfs-bdp-pds/).

Captured on 2026-11-26 with `scripts/capture_gfs_samples.py 2026-11-26T06` (ticket #51):
the adapter's own grib-filter requests, unaltered responses, paced at one request a
second with the generic `astro-seeing/<version>` User-Agent. Each folder's
`SOURCES.json` lists every file's request, size and SHA-256.

| Folder | Box | Points | Steps | Size |
|---|---|---|---|---|
| `20261126T06Z/box1deg/` | 59.2–60.3° N × 9.2–10.3° E | 5 × 5 | 0–48, hourly | 2.0 MB |
| `20261126T06Z/kongsberg/` | the Kongsberg box, 54.67–64.67° N × 4.65–14.65° E | 40 × 40 | 0 and 1 | 0.9 MB |

Each step is two files: `pgrb2` (23 pressure levels, the cloud layers, surface pressure,
model ground, visibility) and `pgrb2b` (the 16 in-between levels, and cloud cover at
70 hPa).

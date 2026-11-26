# ICON-EU test samples

**Credit:** Datenbasis: Deutscher Wetterdienst, eigene Elemente ergänzt. ICON-EU
forecasts from DWD's open data server (https://opendata.dwd.de/weather/nwp/icon-eu/grib/),
under Creative Commons Attribution 4.0 (CC BY 4.0;
https://www.dwd.de/DE/service/rechtliche_hinweise/vorlagen_quellenangabe.html). The
fields here are cut to a small box by us (below), so they are modified DWD data.

Captured on 2026-11-26 with `scripts/capture_icon_eu_samples.py 2026-11-26T06`
(ticket #55): every file the adapter's plan names for the 06 UTC run, steps 0–48
(SIZE_FILES files, SIZE_RUN GB as downloaded), fetched with the generic
`astro-seeing/<version>` User-Agent, each cut to the box and then deleted.

| Folder | What | Points | Steps | Size |
|---|---|---|---|---|
| `20261126T06Z/box1deg/` | every field the adapter reads, cut to 59.2–60.3° N × 9.2–10.3° E (the GFS samples' box) | 17 × 17 | 0–48, hourly | SIZE_BOX MB |
| `20261126T06Z/whole-domain/` | the step-0 `WW` file exactly as DWD served it (bz2, the whole ICON-EU domain) | 1377 × 657 | 0 | SIZE_WHOLE MB |

**How the cut was made.** Each DWD file holds one GRIB2 message over the whole domain
(29.5–70.5° N × 23.5° W–62.5° E, 0.0625°, CCSDS packing at 16 bits). The capture keeps
the grid points inside the box unchanged, rewrites the grid description to the box, and
lets eccodes pack the values again with DWD's packing; a value can therefore differ from
DWD's by up to one packing step of the box's range, and integer codes such as `WW` come
out exactly. The test with the whole-domain file checks the adapter's own cut against it.

**How they are stored.** One bz2 file per step (`step_<SSS>.grib2.bz2`) holds that
step's 107 cut messages (T, U, V, FI and CLC on the 20 pressure levels; CLCT, CLCL,
CLCM, CLCH, PS, VIS and WW), and `hsurf.grib2.bz2` the model ground. `SOURCES.json`
names, in order, the DWD file each message was cut from, with that file's URL, size and
SHA-256 as downloaded, and the GRIB2 code numbers read from each field. The test helper
(`tests/icon_eu_samples.py`) serves each message as its own bz2 file at DWD's path, as
the real server does.

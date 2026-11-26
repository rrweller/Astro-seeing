# MEPS test samples

**Credit:** Based on data from MET Norway. MEPS deterministic 2.5 km (MetCoOp: MET
Norway, SMHI and FMI), from MET Norway's THREDDS server
(https://thredds.met.no/thredds/catalog/mepslatest/catalog.html). "Data and products are
licensed under Norwegian license for public data (NLOD) and Creative Commons 4.0 BY
Internasjonal"; "Credit should be given to The Norwegian Meteorological institute,
shortened “MET Norway”, as the source of data"
(https://www.met.no/en/free-meteorological-data/Licensing-and-crediting, read
2026-11-26). The files' own `license` attribute points to that page.

Captured on 2026-11-26 with `scripts/capture_meps_samples.py 2026-11-26T06` (ticket #57):
the adapter's own OPeNDAP requests, cut to each box on the server, unaltered responses,
with the generic `astro-seeing/<version>` User-Agent. Each run folder's `SOURCES.json`
lists every file's request, size and SHA-256.

| Folder | Box | Points | Steps | Size |
|---|---|---|---|---|
| `20261126T06Z/kongsberg/` | 59.6–59.72° N × 9.55–9.75° E | 5 × 5 | 0–48, hourly | 0.7 MB |
| `20261126T06Z/box1deg/` | 59.2–60.3° N × 9.2–10.3° E (the GFS samples' box) | 51 × 29 | 16–19 | 1.9 MB |
| `catalogue/` | the `mepslatest` catalogue, and the 06z run's time axis (`.dds?time`) | | | 30 kB |

Each run folder holds:

- `meps_<run>.das`: the dataset's attributes (units, fill values, the Lambert projection);
- `meps_<run>_axes.dods`: the grid's x and y axes (949 and 1069 values);
- `meps_<run>_grid.dods`: the window's latitudes and longitudes;
- `meps_<run>_f<step>.dods`: one step's fields in the window (13 pressure levels of
  geopotential, temperature, x/y wind and cloud fraction; total, low, medium and high
  cloud, surface pressure, surface geopotential, fog fraction and visibility).

The `.dods` files are DAP 2.0 binary responses (DDS text, then XDR data).

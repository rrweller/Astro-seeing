# IFS test samples

**Credit:** based on data and products of the European Centre for Medium-Range Weather
Forecasts (ECMWF), IFS open data 0.25°, from ECMWF's open-data portal
(https://data.ecmwf.int/forecasts/). Licence: Creative Commons Attribution 4.0
International (CC BY 4.0), https://creativecommons.org/licenses/by/4.0/; terms at
https://apps.ecmwf.int/datasets/licences/general/. ECMWF does not accept any liability
whatsoever for any error or omission in the data, their availability, or for any loss or
damage arising from their use.

**Modified:** each field was cut by this project to a small box (see below); nothing
else was changed.

Captured on 2026-11-26 with
`scripts/capture_ifs_samples.py 2026-11-26T06 --raw <folder>` (ticket #56): the adapter's
own `fetch` of the 06 UTC run (an index GET and ranged GETs for the needed fields only,
generic `astro-seeing/<version>` User-Agent), about 28 MB of global fields a step, which
are not kept. The portal has no area cut, so each sample set was then made by cutting
every message to its box with eccodes (same packing and bits per value; the largest
change of any value from re-packing is in `SOURCES.json`: at most 0.004 Pa in surface
pressure, 0.0002 gpm in geopotential height, 0.00002 K in temperatures, none in cloud,
wind or the model ground).

| Folder | Box | Points | Steps | Size |
|---|---|---|---|---|
| `20261126T06Z/box1deg/` | 59.2–60.3° N × 9.2–10.3° E | 5 × 5 | 0–48, every 3 h | 1.1 MB |
| `20261126T06Z/kongsberg/` | the Kongsberg box, 54.67–64.67° N × 4.65–14.65° E | 40 × 40 | 0 and 3 | 0.3 MB |
| `20261126T06Z/paranal/` | the Paranal box, 25.13–24.13° S × 70.90–69.90° W | 4 × 4 | 0 and 3 | 0.1 MB |

Each step is two files, laid out as the portal's so a fake server answers the adapter's
ranged requests as the portal would:

- `<run>-<step>h-oper-fc.grib2`: the needed messages, cut, in the portal's order, with a
  short filler line ("not downloaded: <param>") standing in for each field the adapter
  never asks for;
- `<run>-<step>h-oper-fc.index`: the portal's index for that step, every entry kept,
  with `_offset` and `_length` rewritten for this file.

`SOURCES.json` in each folder lists the raw files' URLs, the byte ranges asked for,
their sizes and SHA-256, the original index's SHA-256, and each sample file's size and
SHA-256.

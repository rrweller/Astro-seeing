# ESO ambient-conditions samples (test fixtures)

Small, unmodified CSV answers from ESO's ambient-conditions archive, saved byte for byte
on 2026-11-27 by the C8 session (ticket #101) for `tests/test_eso.py`. They pin the
column names and the answer layout (blank first line, header, rows, `#` footer with the
record count) that `astroseeing.download.eso` checks.

**Credit:** ESO (European Southern Observatory) ambient-conditions database, ESO Science
Archive Facility, https://archive.eso.org/cms/eso-data/ambient-conditions.html.
"All data in the ESO archive retain ESO's copyright, and are distributed according to
the terms of the Creative Commons Attribution 4.0 International license (CC BY 4.0)"
(https://archive.eso.org/cms/eso-data-access-policy.html, read 2026-11-27). The files
are unmodified, as that page asks of third parties.

All were fetched anonymously with `wdbo=csv` from `https://archive.eso.org/wdb/wdb/asm/`:

| File | Form | `start_date` (UTC) | Column switches | `max_rows_returned` |
|---|---|---|---|---|
| `paranal-dimm.csv` | `dimm_paranal` | `2026-11-14T00:00:00..2026-11-14T00:09:59` | `tab_fwhm`, `tab_airmass` | 200000 |
| `paranal-mass.csv` | `mass_paranal` | `2026-11-14T00:00:00..2026-11-14T00:09:59` | `tab_fwhm`, `tab_alt`, `tab_fracgl`, `tab_turbfwhm` | 200000 |
| `lasilla-dimm.csv` | `ambient_lasilla` | `2025-06-01T00:00:00..2025-06-01T00:09:59` | `tab_fwhm`, `tab_airmass` | 200000 |
| `paranal-dimm-empty.csv` | `dimm_paranal` | `2026-11-14T18:00:00..2026-11-14T18:09:59` (daytime: no rows) | `tab_fwhm`, `tab_airmass` | 200000 |
| `paranal-dimm-truncated.csv` | `dimm_paranal` | as `paranal-dimm.csv` | `tab_fwhm`, `tab_airmass` | 3 (cut on purpose) |

The archive always adds each form's default columns, and puts extra switched-on columns
after them (Paranal DIMM's `Airmass` comes last).

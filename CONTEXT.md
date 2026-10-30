# astro-seeing

How many good astronomical viewing nights a year each land location gets, computed from ERA5 reanalysis profiles and terrain, and validated against published papers and observatory measurements.

## Language

### Time

**Night**:
The span from local mean solar noon to the next local mean solar noon, named by the date of its evening.
_Avoid_: day, date (for this span)

**Dark time**:
The part of a night when the Sun is more than 18° below the horizon (astronomical darkness).
_Avoid_: night hours, darkness hours

**Night mask**:
The rule that decides which ERA5 hours are kept at ingest: an hour is kept if the Sun is below −12° at any minute within 30 minutes of it.
_Avoid_: night hours, night filter

**Night window**:
A fixed set of UTC hours downloaded for a validation area whose comparisons all happen at night (for example 23–11 UTC for Chile).
_Avoid_: night hours, night-only hours

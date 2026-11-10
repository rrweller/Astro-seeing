# Observation logs

Hand-written observations used to **check forecast models**, at any place on the globe (D49 item 6). They are test data for verifying models, not a product feature, and nothing in the forecast is tuned to one place.

## `fog-log.csv`

One row per observation: a night, or part of one, at one place. Fill in what you know and leave the rest empty. Never guess a value to fill a gap.

| Column | What to write | Example |
|---|---|---|
| `night` | The Night's evening date (`CONTEXT.md`: a Night runs from noon to noon and is named by its evening), `YYYY-MM-DD` | `2026-11-09` |
| `start_local`, `end_local` | Local clock times the observation covers, `HH:MM`. An end after midnight is still the same Night. | `21:30`, `23:00` |
| `timezone` | IANA time zone of the place, so times convert to UTC | `Europe/Oslo` |
| `place` | A short name | `Kongsberg`, `Skollenborg valley` |
| `lat`, `lon` | Decimal degrees, **rounded to 0.01°** (about 1 km). This repo may be public, so don't log your exact home position. | `59.67`, `9.65` |
| `elevation_m` | Metres above sea level, if known; otherwise empty (it can be read from GLO-30 later) | `160` |
| `sky` | What the sky overhead was: `clear`, `some cloud`, `cloudy`, `fog`, or `mixed` | `fog` |
| `fog` | Fog at the place: `yes`, `no` or `unsure` | `yes` |
| `fog_extent` | If fog: `valley floor`, `patchy`, `widespread`, or `above me` (seen below from higher ground) | `valley floor` |
| `how_seen` | How you know: `looked up`, `drove through`, `camera`, `telescope session` | `drove through` |
| `forecasts_said` | What forecasts showed for that time and place, if you checked, with the service named | `Yr clear; meteoblue 100% low cloud` |
| `observer` | Who observed (initials are fine) | `RW` |
| `notes` | Anything else: how fast fog formed or cleared, wind, dew, frost | `fog from Skollenborg to Darbu; sunny in town` |

Write values containing commas in double quotes, as CSV does: `"Yr clear, meteoblue cloudy"`.

## How the log is used

- **For each row, compare every model's forecast for that place and hour:** total cloud, low cloud, and its fog signals (D49 item 3). The result is how often each model caught or missed fog and low cloud.
- **Forecast values must exist for that place and night.**
  - F1 keeps every run's hourly values forever only for saved places (D45 item 5: Kongsberg and Paranal, plus any place saved later).
  - Area grids are kept only for the latest run.
  - So save a place in F1 before logging there regularly. A row at an unsaved place can only be scored against what was archived.
- No row is changed or removed silently. A wrong row is corrected in place, with a note of what changed.

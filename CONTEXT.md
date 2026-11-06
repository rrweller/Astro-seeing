# astro-seeing

Astronomical observing conditions from weather models and terrain, in two products on one shared physics engine: a forecast of tonight's cloud and seeing for any place, and a climatology of how many good viewing nights a year each land location gets, both validated against published papers and observatory measurements.

## Language

### Products

**Forecast track**:
The product that shows Tonight's cloud and seeing, forecast model by forecast model, for a place the user picks.
_Avoid_: next-night forecast, Tonight (as a product name)

**Historical track**:
The product that shows the climatology of good nights, dark time, cloud and seeing for every land location, computed from ERA5 reanalysis.
_Avoid_: global run, climatology app

### Time

**Night**:
The span from local mean solar noon to the next local mean solar noon, named by the date of its evening.
_Avoid_: day, date (for this span)

**Tonight**:
The Night that has not yet reached its sunrise; from sunrise on, the Night that begins at the coming sunset.
_Avoid_: next night, coming night

**Dark time**:
The part of a night when the Sun is more than 18° below the horizon (astronomical darkness).
_Avoid_: night hours, darkness hours

**Counted hours**:
The hours of Tonight the verdict counts: its dark time from the current hour on or, if Tonight has no dark time at all, the hours with the Sun below −12°, then below the horizon.
_Avoid_: clear hours, night hours

**Night mask**:
The rule that decides which ERA5 hours are kept at ingest: an hour is kept if the Sun is below −12° at any minute within 30 minutes of it.
_Avoid_: night hours, night filter

**Night window**:
A fixed set of UTC hours downloaded for a validation area whose comparisons all happen at night (for example 23–11 UTC for Chile).
_Avoid_: night hours, night-only hours

### Forecasts

**Forecast model**:
One numerical weather-prediction family whose open output we use, such as GFS, ECMWF IFS or ICON. A regional version and its global parent (ICON-EU and ICON) are one forecast model, and each place uses the finest version that covers it; the members of an ensemble are not separate forecast models either.
_Avoid_: model (alone), source, provider

**Regional-only model**:
A forecast model with no global version, such as MEPS: shown for the places it covers, but not counted in model agreement.
_Avoid_: local model, extra model

**Run**:
One forecast model started at one time, for example IFS from 00 UTC on 5 November.
_Avoid_: cycle, forecast (for this)

**Total cloud**:
The fraction of the sky covered by cloud at any height, as a forecast model reports it. It is not the sum of low, mid and high cloud, because layers overlap.
_Avoid_: cloud cover (unqualified), tcc (outside code)

**Cloud class**:
One of clear, some cloud or cloudy, given to one forecast model's hour from its total cloud.
_Avoid_: cloud category, sky state

**Model ground**:
The ground height a forecast model assumes at a place, smoothed over its grid; it can lie well above or below the real ground.
_Avoid_: model terrain, orography (outside code), surface (alone)

**Model agreement**:
How many of the global forecast models put an hour in the same cloud class.
_Avoid_: consensus, ensemble agreement

**Mostly clear**:
Said of an hour that more than half of the global forecast models with a value for it put in the clear class, with at least two such models.
_Avoid_: consensus, clear (for the combined call)

**Incomplete hour**:
A counted hour that fewer than two global forecast models have a value for; it counts as neither clear nor not clear.
_Avoid_: missing hour, gap

**Stale run**:
A forecast model's latest run whose run time is more than 24 hours old: shown, but left out of model agreement.
_Avoid_: old forecast, expired run

**Verdict**:
The short summary of Tonight at a place: how many counted hours are mostly clear, and the range of seeing across the global forecast models.
_Avoid_: summary, score, rating

### Turbulence

**Cₙ² model**:
A formula that gives the refractive-index structure constant Cₙ² from a temperature and wind profile, such as Osborn–Sarazin or Tatarskii + HMNSP99.
_Avoid_: model (alone), seeing model, turbulence model

**Free-atmosphere seeing**:
The seeing caused by turbulence more than 1 km above the observer; the rest of the column is the ground layer.
_Avoid_: upper seeing, high-altitude seeing

**Effective turbulence altitude**:
The height above the observer of the turbulence, averaged with each layer weighted by its Cₙ² and by height to the 5/3 power (written H̄); the height that sets the isoplanatic angle.
_Avoid_: most turbulent layer, turbulence height, jet-stream layer

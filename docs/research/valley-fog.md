# Valley fog and low cloud: why forecasts disagree, and what F1 can predict

Ticket #31. Researched 2026-11-10 by the agent. Builds on `docs/research/forecast-sources.md` (branch `research/forecast-sources`) and decisions D43–D48 (`docs/decisions.md` on `claude/ecstatic-bohr-kp4csp`). Every link in the sources list was loaded on 2026-11-10. Where a publisher page blocked automated access (Wiley, AMS, MDPI, Springer returned HTTP 403 or a login redirect), I read the abstract and bibliographic record through the OpenAlex or Semantic Scholar APIs, and say so. Those papers are cited for their abstracts only. Times are UTC.

## The question

Riley lives near Kongsberg (59.669° N, 9.652° E). Two observations prompted this ticket:

- One night Yr said clear and meteoblue showed nearly 100% low cloud. The sky matched meteoblue (not always the case).
- Another day Kongsberg was clear and sunny, but south of town at Skollenborg there was thick valley fog along road 286 north to Darbu.

F1 is a private tonight page for a 10°×10° box around Kongsberg, from raw GFS 0.25°, ICON-EU, MEPS 2.5 km and IFS open data 0.25°. Its verdict counts the global families only (GFS, IFS, ICON-EU), on total cloud; MEPS is a "regional, not counted" row (D45 item 3, D48).

Sub-questions:

1. Why do services disagree?
2. How well do models forecast fog and low stratus, especially valley radiation fog?
3. Which fields in the four F1 sources signal fog or low cloud?
4. Can GLO-30 terrain plus model profiles flag valley fog or cold-air pooling?
5. Which observations could check it?
6. What should F1 do, and what should wait?

## Summary

- **Yr and meteoblue use different models.** For Norway, Yr's short-range forecast is MEPS (2.5 km), post-processed by MET Norway. meteoblue's model list for Kongsberg has 17 models (its own NEMS/NMM, IFS, ICON, GFS, ARPEGE, UKMO, GEM, HARMONIE-KNMI, AIFS) and **no MEPS**. So "Yr vs meteoblue" is largely "MEPS vs other models".
- **They also define "low cloud" differently.** Yr: cloud "lower than 2000 m above the ground". meteoblue's weather variables: surface to 2 km. meteoblue's astronomy page: a lowest layer of **0–4 km above sea level**, and fog or very low cloud is **not shown** there.
- **MET Norway documents a recurring MEPS weakness that fits Riley's first night.** Its verification reports say MEPS under-forecasts low stratus under subsidence inversions in high pressure, and that IFS "usually has better agreement to the observed cloudiness" in those cases (Dec 2025–Feb 2026). An autumn 2022 report shows MEPS missing inland radiation fog in southern Norway "even at just 1hr lead time".
- **Fog is hard for every model.** ECMWF's own guide says 10 km models "cannot be expected to handle" patchy fog and that site skill "can be very low". km-scale and sub-km models help but still fail on onset, dissipation and valleys. One sub-km study found valleys too warm and hills too cold, so too little fog in valleys. Reported numbers are low: one ensemble study raised fog skill from ETS 0.06 (single model, essentially no skill) to 0.33 (multi-model ensemble with a better diagnostic).
- **Fields exist, unevenly.** MEPS has fog fraction, visibility, cloud base, low cloud, 2 m RH, BL height and 65 model levels. ICON-EU has visibility, a fog weather code (ww 45/48), ceiling, 2 m dewpoint and model levels. GFS has visibility, cloud ceiling, low cloud, 2 m dewpoint, BL height and some near-surface temperature levels. IFS open data has only low cloud, 2 m T/dewpoint, 10 m wind and pressure levels from 1000 hPa up: **no visibility, cloud base or BL height**.
- **Terrain can map where cold air pools, not when fog forms.** DEM-based cold-air-pool maps exist and were checked against temperatures (error cuts of about 1 °C). None I found was verified as a fog forecast. Kongsberg town (162 m) lies 70–185 m below all four model grounds, so a valley-floor fog layer sits in a part of the terrain none of the models has.
- **Observations:** EUMETSAT SAF products (including NWC SAF cloud type with a "very low cloud" class) are "Core" data under CC BY 4.0; near-real-time Level 1 Meteosat data may carry fees. MET Norway's Frost API serves station observations (client ID required).
- **Recommendation (Riley decides):** keep D45 item 3 and D48 as they are. In F1, add an informational, uncounted low-cloud and fog row using fields F1 can cheaply fetch, label it experimental, and say plainly that valley fog below the model ground is not forecast. Leave terrain-based fog flags until there is local verification (Riley's notes plus satellite low-cloud data), in F2 or later.

## 1. Why services disagree

### Yr (MET Norway)

- **Models.** Yr's help article (updated 2025-12-15): for "the next 2-3 days", "MetCoOp EPS (MEPS) is used for Norway and nearby regions" at 2.5 km; "For mainland Norway" from 3 to 10 days, "ECMWF-ENS with a resolution of 18 km". The developer docs agree: Nordic forecasts come from MEPS; "For medium range forecasts (2 - 10 days) the 51 member ensemble forecast from ECMWF is used."
- **Post-processing.** The help article says "all forecasts are created by a weather model and are post-processed before you see them on Yr", with statistical corrections "mainly in the Scandinavian region".
  - MET Norway's verification reports name what is post-processed: 2 m temperature (downscaled to 1 km and bias-corrected against an analysis that uses "conventional and citizen observations") and 10 m wind (downscaled to 1 km). Cloud is not named.
  - The MET Nordic dataset page (the forecast product that "forms the basis for the forecasts on Yr") describes `cloud_area_fraction` as "Bias corrected using webcameras from Luftambulansen. Correction to forecast 3 hours into the future. Bilinear interpolation from 2.5 km NWP." So **cloud beyond 3 h is MEPS cloud interpolated to 1 km**. The page lists no fog variable.
- **Separate low-cloud and fog products.** Locationforecast (the API behind Yr) has `cloud_area_fraction_low` ("cloud cover lower than 2000m above the ground") and `fog_area_fraction` ("amount of surrounding area covered in fog (horizontal view under a 1000 meters)"), both in `complete.json` only. The docs don't say how either is computed. MEPS files carry a `fog_area_fraction` field (section 3), so these are probably MEPS-based *[inference]*. How Yr's web page uses them: not found.

### meteoblue

- **Models.** meteoblue says its forecasts "are calculated with its own models" based on NMM and NEMS. Its dataset docs list its own models (e.g. NEMS12, Europe, 12 km; NEMSGLOBAL, 30 km) and third-party models (ICON, ICON-EU, IFS, GFS, UKMO, ARPEGE, HARMONIE-KNMI and others).
  - The multimodel page for Kongsberg lists 17 models: NEMS-12, NEMS-30, NEMS2-12, NEMS2-30, NMM-12, IFS-20, ICON-12, ICON-7, HARMN-5 (KNMI), GFS-40, ARPEGE-25, ARPEGE-11, UKMO-10, GEM-15, UKMO-2, AIFS-25, IFS-HRES. **MEPS is not among them.** Whether every listed model actually covers Kongsberg (e.g. UKMO-2, HARMN-5): not checked.
- **How the forecast is combined.** meteoblue says third-party models "are combined - by applying modern machine learning techniques - to a multimodel forecast", and the website "per default offers the dataset with the highest accuracy". Its Learning MultiModel (mLM) is "validated and implemented for air temperature, dew point temperature and wind speed". **How cloud cover is combined: not found** in meteoblue's docs.
- **Cloud definitions.**
  - Weather variables page: "low clouds: from the surface - 2 km"; percentages are "calculated as integral of the preceding forecast period"; total cloud "can not be derived from the cloud cover of individual layers".
  - Astronomy seeing page: "Cloud cover is given for 3 different layers (0-4 km asl, 4-8 km asl, 8-15 km asl)" and "Fog or very low clouds are not shown here (see pictocast for fog)".
  - Pictograms include "Fog/low stratus clouds" (codes 16–18) and "Fog"; the criteria aren't given.
- **meteoblue's own caveats** (Kongsberg multimodel page): "Fog and low clouds are often invisible to most models and to satellites, and as such models may agree despite uncertainty", and the values "are from direct model output and not scaled to the exact altitude and position of the selected place". The clouds page: "A fog or low cloud cover is difficult to forecast, because it often only forms locally."

### What this means for Riley's two observations

- **Night 1 (Yr clear, meteoblue ~100% low, meteoblue right).** Consistent with MEPS missing a low stratus deck that other models had *[inference]*. MET Norway's Dec 2025–Feb 2026 report describes exactly this: "The problems with underforecasting of low or medium stratus in high pressure situations persists"; under a strong subsidence inversion "MEPSctrl is not able to reach saturation in the layers 975 to 900hPa", "found in almost all cases where missing low clouds have been reported"; and "IFS usually has better agreement to the observed cloudiness than MEPSctrl in such situations". The autumn 2022 report calls stratus under weak subsidence inversions "one of the main weaknesses of the fine scale model at MET Norway".
  - Caveat: if Riley read meteoblue's astronomy page, its "low" layer is 0–4 km above sea level, so "100% low" there can include mid-level stratus that Yr would not call low.
- **Day 2 (valley fog at Skollenborg–Darbu, sun in Kongsberg).** A valley-scale feature. No model in F1 resolves it (sections 2 and 4). It is the kind of case where all services can be wrong together, as meteoblue's own caveat says.

## 2. How well models forecast fog and low stratus

### Global models (IFS as the documented example)

From ECMWF's Forecast User Guide (FUG), updated 2026:

- "Fog can be very patchy and 10km-scale models (such as IFS) cannot be expected to handle this well." "Local skill in forecasting the occurrence of fog (e.g. for a specific site) can be very low." (§9.4.1)
- Listed as "initial perceptions" of a product still under assessment, not measured results: radiation fog tends to be "rather too dense", "rather too deep", "to form too slowly" and "to clear too quickly (by about 1-3hr)"; "hill fog is rather under-represented". (§9.4.1)
- Very low visibility depends on "the correct dynamic and thermodynamic conditions in the boundary layer", and these "are often tied to orographic features that are not resolved by the atmospheric model"; the visibility product "should be used with caution; expectations regarding the quality of this product should remain low". (§9.4)
- "Inversions and low cloud can be poorly represented, notably in winter or high pressure areas", which "has an impact on fog extent and persistence and also 2m temperatures"; "Correct prediction of fog dispersal is notoriously difficult". (§9.10)

GFS: **no peer-reviewed verification of GFS fog or low stratus over Europe found.**

ICON (the model behind ICON-EU): Singh et al. (2025, JGR) say many operational models "struggle with slow or no fog formation after sunset and too rapid dissipation in the morning". Over the Swiss Plateau, ICON's operational turbulence scheme (ICON-TKE) dissolved fog too early; a newer scheme kept it longer, and more vertical levels helped only with the newer scheme, "likely due to an overestimation of turbulence mixing" in ICON-TKE. (Abstract.)

### km-scale models (MEPS / AROME / HARMONIE type)

- **MEPS, from MET Norway's own reports** (quarterly verification, forecaster case studies; not peer-reviewed but primary):
  - Missing inland radiation fog in southern Norway, 19 Oct 2022: "MEPSctrl is generally not able to reproduce this fog, even at just 1hr lead time." MET's nowcasting run (MNWC, MEPS with moisture adjusted to observed cloud) "shows only very small improvements in this case", but did better for low cloud over south-east Norway on 3 Oct 2022.
  - Low stratus under subsidence inversions: recurring since at least 2022 and still reported in Feb 2026 (quotes in section 1).
  - Small errors matter: "The same quite small errors in either temperature or dew-point have earlier been reported to have a profound impact of the forecasts for fog." (Dec 2025–Feb 2026.)
  - In stable winter conditions MEPS is "more prone to decoupling from the surface" than AROME-Arctic, so it captures cold minima better but still with "a positive bias" in temperature (same report).
- **AROME vertical resolution** (Philip et al. 2016, WAF; abstract): finer vertical levels change fog onset strongly but barely change the mature and dissipation phases. Over a winter at Paris-CDG they gave "more fog events", many where there were no observations to confirm them. "The ceiling of low clouds is not well simulated by the numerical model no matter what vertical resolution is used."
- **HARMONIE-AROME microphysics** (Contreras Osorio et al. 2022, *Atmosphere*; abstract): droplet sedimentation settings strongly affect modelled fog, and "none of the considered configurations can simultaneously represent all aspects of both cases".
- **COSMO-1, 1.1 km, Swiss Plateau** (Westerhuis et al. 2020, QJRMS; abstract): "a considerable negative FLS bias during wintertime" over four months, checked against satellite. Cause: numerical diffusion in the advection scheme on terrain-following levels mixes cloudy and clear cells and "can become the root cause for too rapid dissipation of FLS during nighttime in complex terrain". Two-moment microphysics and more levels did not help; 550 m grid spacing only delayed dissipation.
- **WRF** (Steeneveld et al. 2015, BLM): models "typically show large biases for the timing of the onset and dispersal of the fog"; "the boundary-layer formulation is critical for forecasting the fog onset"; "for fog dispersal the choice of the microphysical scheme is a key element". Román-Cascón et al. (2016, QJRMS; abstract): WRF simulated radiation fog with sophisticated options and high resolution, "However it failed in simulating the onset, dissipation and the vertical extent of fog (which was overestimated)", and was "extremely sensitive to the spin-up time".

### Sub-km models and valleys

- **LANFEX, UK** (Price et al. 2018, BAMS; abstract): models at about 100 m "are capable of reproducing the local-scale variability" that leads to radiation fog, but showed deficiencies in aerosol activation, turbulence and cloud schemes.
- **Smith et al. 2021, QJRMS** (abstract; Met Office UM at 1.5 km, 333 m, 100 m): sub-km runs agree better with observations, but "MetUM produces valleys that are too warm and hills that are too cold, leading to valleys that do not have enough fog and hills that have too much". Soil heat transfer was too easy, and the soil thermal conductivity setting changed fog onset by "up to a 5‐hr".
- **London Model, 333 m** (Boutle et al. 2016, QJRMS; abstract): similar to the 1.5 km model at short lead times, better at longer lead times and in frequency bias, mostly because of differences in the cloud scheme.
- **Hughes et al. 2015, GMD** (full text, open access): the Clun Valley (1–2 km wide, 100–200 m deep) is "not resolved" at 4 km or 1.5 km; cold pools there give "local temperature differences of 5–10 K between hilltop and valley bottom". At 100 m, the cloud scheme's critical-RH assumption caused long-wave and temperature biases.

### Numbers

Few papers give fog skill scores for operational models:

- **Zhou and Du 2010, WAF** (abstract; NCEP, 15 km WRF ensemble over eastern China, 13 cities, Feb–Sep 2008): from "basically no skill at all [equitable threat score (ETS) = 0.063]" to 0.334, by combining a multi-variable fog diagnostic, ensembles and two models. A diagnostic using liquid water content alone did much worse. (Their "MEPS" is NCEP's Mesoscale Ensemble Prediction System, not MetCoOp's.)
- **Observation-based thresholds** (Izett et al. 2018, BLM, open access; Cabauw, 254 fog events, 2012–2016): a threshold method on RH, net radiation, 10 m wind and cooling rate reached a hit rate over 90% with a false-alarm rate of about 13% at 1 h lead, but false alarms grew fast with lead time (e.g. 42% at 6 h for one scheme). The original Menut et al. (2014) thresholds were RH ≥ 90%, net radiation ≤ −10 W m⁻², 10 m wind ≤ 3 m s⁻¹, and cooling ≤ −0.5 K over 1.5–3 h. These use **observations**, not model output; Izett et al. note that earlier work found model output failed to capture fog conditions.
- MEPS-specific fog hit rates or false-alarm rates: **not found** in peer-reviewed work. MET Norway's reports give cases, not fog scores.

### Known failure modes, in short

- **Resolution and smoothed terrain.** Valleys narrower than a few grid lengths are not in the model; ECMWF says the boundary-layer conditions behind very low visibility are "often tied to orographic features that are not resolved".
- **Boundary-layer and turbulence schemes.** Too much mixing stops fog forming or clears it early (Steeneveld 2015; Singh 2025; Westerhuis 2020).
- **Microphysics.** Droplet settling and number concentration control fog water and dissipation (Contreras Osorio 2022; Steeneveld 2015).
- **Vertical resolution and numerics.** Affect onset and spurious mixing near cloud top (Philip 2016; Westerhuis 2020).
- **Soil and surface.** Soil temperature and conductivity shift onset by hours, and soil moisture "is decisive for the lifting and dissipation time" (Smith 2021; Maronga and Bosveld 2017, LES).
- **Thin margins.** About 1 K in temperature or dewpoint flips the outcome (MET Norway, Feb 2026).

## 3. Fields that signal fog or low cloud, by source

Checked on 2026-11-10 against live listings: the GFS `.idx` for `gfs.t00z.pgrb2.0p25.f012` and `f013` (NOMADS); DWD's `icon-eu/grib/00/` directory listing and DWD's ICON database reference v2.5.6; the MEPS OPeNDAP `.dds`/`.das` of `mepslatest/meps_det_2_5km_20261110T00Z.ncml` (plus a point read near Kongsberg); the ECMWF open-data `.index` for `20261110/00z/ifs/0p25/oper`, step 12.

| Signal | GFS 0.25° (hourly to 120 h) | ICON-EU 0.0625° (hourly to 78 h) | MEPS 2.5 km (hourly to 66 h) | IFS open 0.25° (3-hourly) |
|---|---|---|---|---|
| Low cloud | `LCDC` low cloud layer (instant and averages) | `CLCL` | `low_type_cloud_area_fraction` | `lcc` |
| Fog fraction | no | no field; `WW` = 45 / 48 means fog / depositing rime fog | `fog_area_fraction` (long name "Fog", units 1; method undocumented) | no |
| Visibility | `VIS:surface` | `VIS` ("Near surface visibility in m") | `visibility_in_air` | no |
| Cloud base / ceiling | `HGT:cloud ceiling`; `PRES:low cloud bottom level` (averages only) | `CEILING` (height above MSL where non-convective cloud first exceeds 50%) | `cloud_base_altitude`, `cloud_top_altitude` | no |
| 2 m humidity | `TMP`, `DPT`, `RH`, `SPFH` at 2 m | `T_2M`, `TD_2M`, `RELHUM_2M` | `air_temperature_2m`, `relative_humidity_2m` | `2t`, `2d` |
| Near-surface inversion | `TMP` at surface, 2 m, 80 m, 100 m, 30–0 hPa above ground, 0.995 sigma; pressure levels every 25 hPa | `T` on 74 model levels with `HHL`; `T_G` | `air_temperature_0m`, `_2m`, `_z` (80 and 120 m), 65 model levels; Brunt–Väisälä frequency; `SFX_RI` (Richardson number) | `skt`, `2t`, then pressure levels 1000, 925, 850… only |
| Wind | 10 m `UGRD`/`VGRD`, `GUST`, `FRICV` | `U_10M`, `V_10M`, `VMAX_10M` | 10 m wind, `x/y_wind_z` (80, 120 m), TKE | `10u`, `10v`, `100u`, `100v`, `10fg` |
| BL height | `HPBL` | not in the DWD reference; `MH` is in the listing (meaning not documented there) | `atmosphere_boundary_layer_thickness` | no |
| Soil moisture | not checked | `W_SO` | `SFX_*WG*` layers | `vsw` |

Notes:

- **IFS open data is the weakest source for fog.** Its index has `lcc`, `2t`, `2d`, `skt`, 10 m wind and soil moisture, but no visibility, cloud base, BL height or near-surface levels below 1000 hPa. The FUG documents IFS visibility, but it isn't in the open set.
- **ICON-EU `WW`** is "Significant weather of the last hour", diagnosed by "an independent post-processing method" with WMO thresholds. When no weather code applies it holds total cloud as 0–3. Each single-level field is about 1.0–1.3 MB per step for the whole domain (12 h step, 2026-11-10 00z); `WW` is 0.24 MB.
- **MEPS:** a point read at grid (y 376, x 304), nearest to Kongsberg, returned real values for `fog_area_fraction`, `visibility_in_air`, `low_type_cloud_area_fraction` and `relative_humidity_2m` over steps 0–24 of the 2026-11-10 00z run. All are on the 67 hourly steps and served by OPeNDAP, so a box costs little.
- **GFS:** `VIS`, `LCDC`, `HGT:cloud ceiling` and `HPBL` are in the hourly f013 file as well as f012. How GFS derives `VIS`: not checked.
- **Total cloud includes model fog** wherever a model puts cloud in its lowest level *[inference]*. The FUG says IFS visibility "can fall below 500m where fog is forecast due to cloud water drops in the lowest model layer". So a fog the model does form already shows in F1's cloud classes. The problem is the fog it doesn't form.

## 4. Terrain: can GLO-30 plus model profiles flag valley fog?

### Kongsberg against the models

- From D47: GLO-30 gives Kongsberg town **162 m**. Model grounds are 231 m (MEPS), 261 m (IFS), 327 m (GFS) and 347 m (ICON-EU), so the town is **69–185 m below** every model's ground. The 0.25° cell around town spans 61–829 m in GLO-30.
- Valley cold pools of this depth matter. In a UK valley 1–2 km wide and 100–200 m deep, hilltop-to-valley-bottom differences of 5–10 K were observed, and the valley was "not resolved" at 1.5 km (Hughes et al. 2015).
- *[Inference]* A fog layer filling the valley bottom below the model ground is outside every model column F1 uses. A model column can still carry the ingredients: a near-surface inversion, high 2 m RH, light wind, clear sky above. But it can't say whether the valley floor saturates.

### What the literature offers

- **DEM-based cold-air-pool maps.** Lundquist et al. (2008, JGR; abstract) classify pixels as prone to pooling from DEM slope, curvature and percentile elevation, with an along-valley drainage test. Checked against temperature networks in Colorado, the Pyrenees and Yosemite, they cut interpolation errors by "about 1°C averaged over all sites" (up to 3 °C at single sites). This targets **minimum temperature on clear, calm nights, not fog**.
- **Decoupling.** Daly et al. (2010, IJC; abstract): sheltered valley bottoms are "largely decoupled from, and relatively insensitive to, 700‐hPa flow variations", while ridges follow it. So free-atmosphere model values describe ridges better than valley floors.
- **Satellite fog plus DEM.** Cermak and Bendix (2011, IJRS; abstract) separate ground fog from elevated low stratus by deriving cloud-base height from satellite cloud microphysics: hit rate 81%, threat score 0.62 against 1,030 METAR scenes. Schulz et al. (2016, AMT; open access) detect ground fog in mountains from MODIS where cloud optical thickness falls as terrain rises, i.e. a cloud cut by the terrain. These use terrain to interpret **observed** clouds, not to forecast them.
- **Model downscaling of fog with terrain:** no verified method found for operational use. Sub-km models are the research route (LANFEX; Smith et al. 2021), and they still show valley warm biases.

### Assessment

- *[Inference]* A GLO-30 "cold-air-pool-prone" mask (Lundquist-style) combined with model signals (clear sky, light wind, strong near-surface stability, high 2 m RH or small dewpoint depression) could mark *where fog is possible tonight*. It would be a **risk shading, not a forecast**, and it is unverified for fog anywhere I found.
- It needs a check against observed fog (satellite or Riley's notes) before it carries any weight. Thresholds from observation studies (Menut/Izett) don't transfer directly to model output with known RH and temperature biases.

## 5. Observations as a check (identified only)

- **EUMETSAT Satellite Application Facility (SAF) products.** The EUMETSAT Data Policy (amended 25 Nov 2025): "All SAF products are categorised as 'Core' products", and Core data are "Free and Unrestricted basis under a CC-BY-4.0 licence". SAF software is free "against a licence agreement". Level 1 SEVIRI/FCI data with latency under 1 h are "Recommended" data and "may be subject to fees"; at 1 h or more they are free. Hourly Level 1 imagery is Core.
- **NWC SAF Cloud Type.** Classes include "Very low clouds (cloud top less than 0.5km above ground)" and "Low clouds" (SMHI's product description, PPS/polar version). EUMETSAT's guidance for the geostationary product lists limits: "Very low clouds may be classified as mid-level clouds in case strong thermal inversion"; "Low clouds may not be detected at low sun elevation or even at night-time (infrequent)"; "Snow is not identified at night-time and may be confused as low clouds". Where to get ready-made NWC SAF products for Norway without running the software: **not checked**.
- **Research fog/low-stratus retrievals.** A SEVIRI-based European FLS climatology validated against METAR: Heidke skill score 0.45 (Egli et al. 2017). An infrared-only, day-and-night SEVIRI FLS detector: probability of detection 0.70–0.82 and false-alarm ratio 0.21–0.31 against METAR (Jahani et al. 2025, AMT, open access). Both show what satellite checks can do; neither is an operational feed I found for F1.
- **MET Norway observations (Frost API).** "free access to MET Norway's archive of historical weather and climate data". It needs a client ID tied to an e-mail address; "the license is found in every response"; above about 1 request per second counts as heavy traffic. Which stations near Kongsberg report visibility, cloud base or present weather: **not checked**.
- **Riley's own notes.** Kongsberg and Skollenborg–Darbu fog sightings, with time and place, are the most direct local check *[inference]*.

## 6. Recommendation for F1 and later (Riley decides)

**Does the evidence challenge D45 item 3 or D48?** Not in my reading.

- MEPS is not better at the failure that matters most here. MET Norway's own reports say it misses low stratus under subsidence inversions and inland radiation fog, and that IFS often matches observed low cloud better.
- Counting MEPS would make the Kongsberg verdict lean more on the model with that documented gap, and would bring back the seams D45 avoided.
- Valley fog below the model ground defeats all four models alike.

**For F1 (each item is a proposal; UI wording comes with D44 item 9):**

1. **Keep the verdict rules unchanged** (total cloud, global families, D48).
2. **Show low cloud clearly per model** (already in D43 item 4) and put MEPS's low cloud, fog fraction and visibility in its "regional, not counted" row.
3. **Add an informational "fog / low-cloud signal" row, not counted**, from fields that are cheap to fetch:
   - MEPS `fog_area_fraction`, `visibility_in_air`, `low_type_cloud_area_fraction`;
   - ICON-EU `VIS`, `WW` ∈ {45, 48}, `CLCL`;
   - GFS `VIS`, `LCDC`;
   - IFS `lcc`, and `2t − 2d`.
   - Each shown per model and per hour, labelled "experimental, uncalibrated". No combined score until it has been checked.
   - Fetch cost *[estimate]*: about 1 MB per field per step for ICON-EU, a few hundred kB per step for GFS from the NOMADS box filter, negligible for MEPS via OPeNDAP, and IFS fields already in the index.
4. **A fixed caveat on the Kongsberg page:** the town lies 69–185 m below every model's ground; valley fog and cold pools there are not forecast by any model shown.
5. **Start a log** of observed fog and low-cloud nights (Riley's notes), to score item 3 against later. It costs nothing to keep.

**Later (F2 or after a verification ticket):**

- Score the item 3 signals against Riley's log and a satellite FLS product, and only then decide on any combined flag and thresholds.
- Research ticket: a GLO-30 cold-air-pool mask plus model stability, wind and humidity as a "valley fog possible" shading. Check it against satellite FLS before it appears on the globe.
- If a satellite source is wanted (NWC SAF products, or Meteosat data under 1 h latency), that is a new data source and licence: [ASK] under AGENTS.md.

## Not verified / unsure

- How meteoblue builds its default cloud forecast (which models, what weights): not documented in the pages I read.
- How Yr's web page uses `fog_area_fraction` and `cloud_area_fraction_low`, and how MEPS computes `fog_area_fraction`: not found.
- Whether every model in meteoblue's Kongsberg list covers Kongsberg: not checked.
- GFS fog or low-stratus verification over Europe: not found. How GFS computes `VIS`: not checked.
- ICON-EU `MH` (in the listing): not in DWD's reference v2.5.6, so its meaning is unconfirmed.
- MEPS-specific fog skill scores (hit rate, false-alarm rate): not found in peer-reviewed work.
- Several papers (Westerhuis 2020, Philip 2016, Boutle 2016, Smith 2021, Contreras Osorio 2022, Zhou and Du 2010, Lundquist 2008, Daly 2010, Cermak and Bendix 2011, Price 2018, Maronga and Bosveld 2017, Román-Cascón 2016, Egli 2017, Singh 2025) are cited from their abstracts only, because publisher pages blocked automated access. Full-text details beyond the abstracts were not checked.
- Kongsberg-area geography beyond D47 (valley depth at Skollenborg, the route of road 286): not checked.
- Which Frost stations near Kongsberg report visibility or cloud: not checked.

## Sources

Primary documentation (all loaded 2026-11-10):

- Yr help, "Weather forecasts on Yr - how are they made?" (updated 2025-12-15), read through Zendesk's article API because the HTML page returned 403: https://hjelp.yr.no/api/v2/help_center/en-us/articles/360004008874.json (article: https://hjelp.yr.no/hc/en-us/articles/360004008874-Weather-forecasts-on-Yr-how-are-they-made). Supports: MEPS for 2–3 days, ECMWF-ENS for 3–10 days, post-processing.
- Yr developer docs, Locationforecast data model: https://developer.yr.no/doc/locationforecast/datamodel. Supports: model sources, definitions of `cloud_area_fraction_low` and `fog_area_fraction`.
- MET Norway NWPdocs wiki, MET Nordic dataset: https://github.com/metno/NWPdocs/wiki/MET-Nordic-dataset. Supports: cloud bias-corrected with webcams for 3 h only; basis for Yr; no fog variable.
- MET Norway, METinfo 20/2026, "Verification of Operational Weather Prediction Models, December 2025 to February 2026": https://www.met.no/publikasjoner/met-info/_/attachment/inline/72b46136-5c85-4384-b49c-0b13397e90a5:367c7e5aca011457c817c1169a332bd8deb62117/met-info-20-2026.pdf. Supports: missing low stratus under subsidence inversions; IFS better in those cases; small T/Td errors affect fog; Yr post-processing scope.
- MET Norway, METinfo 14/2023, "Verification … September to November 2022": https://www.met.no/publikasjoner/met-info/_/attachment/download/cdb100e1-ff28-4dec-8126-b4bf2cfb181e:40e98539f428f0f9c19761238113574e741b5ca6/Verification_report_202209-202211.pdf. Supports: missing inland radiation fog in southern Norway; stratus under subsidence as a main weakness; MNWC.
- MET Norway, METinfo 31/2025 (Dec 2024–Feb 2025): https://www.met.no/publikasjoner/met-info/_/attachment/inline/4d41d86b-c200-40da-be43-74b7ef825e5e:13f42d909f3c5620d3e168892abf6ff5a66f66e9/MET-info-31-2025.pdf. Read; no fog or low-cloud case (cited only to say so).
- MEPS OPeNDAP metadata: https://thredds.met.no/thredds/dodsC/mepslatest/meps_det_2_5km_20261110T00Z.ncml.das and `.dds`. Supports: MEPS field list in section 3 (file names change with each run).
- meteoblue, clouds variable page: https://content.meteoblue.com/en/research-education/specifications/weather-variables/clouds. Supports: layer definitions; fog hard to forecast.
- meteoblue, Astronomy Seeing help: https://content.meteoblue.com/en/private-customers/website-help/outdoor-and-sports/astronomy-seeing. Supports: 0–4 km asl lowest layer; fog not shown.
- meteoblue, multimodel page for Kongsberg: https://www.meteoblue.com/en/weather/forecast/multimodel/kongsberg_norway_3149563. Supports: 17-model list without MEPS; fog/low-cloud and direct-output caveats.
- meteoblue, mLM: https://content.meteoblue.com/en/research-education/specifications/data-sources/post-processing/meteoblue-learning-multimodel-mlm/. Supports: mLM covers T, Td and wind only.
- meteoblue, data sources and third-party models: https://content.meteoblue.com/en/research-education/specifications/data-sources/ and https://content.meteoblue.com/en/research-education/specifications/data-sources/weather-simulation-data/third-party-models/. Supports: ML multimodel; "highest accuracy" default.
- meteoblue, weather simulation data: https://content.meteoblue.com/en/research-education/specifications/data-sources/weather-simulation-data. Supports: own NMM/NEMS models.
- meteoblue dataset docs: https://docs.meteoblue.com/en/meteo/data-sources/datasets. Supports: list of own and third-party models.
- meteoblue, symbols and pictograms: https://content.meteoblue.com/en/research-education/specifications/standards/symbols-and-pictograms. Supports: fog/low stratus pictograms.
- ECMWF FUG §9.4 Visibility: https://confluence.ecmwf.int/spaces/FUG/pages/673551698/Section%2B9.4%2BVisibility. Supports: very-low-visibility conditions tied to unresolved orography; low expectations; fog via cloud water in the lowest level.
- ECMWF FUG §9.4.1 Reduction of visibility in fog: https://confluence.ecmwf.int/x/YJUlK. Supports: radiation fog biases; patchy fog at 10 km; low site skill.
- ECMWF FUG §9.10 Summary of some important issues: https://confluence.ecmwf.int/x/9ZQlK. Supports: inversions and low cloud poorly represented in winter and high pressure.
- ECMWF open data page: https://www.ecmwf.int/en/forecasts/datasets/open-data, and the live index https://data.ecmwf.int/forecasts/20261110/00z/ifs/0p25/oper/20261110000000-12h-oper-fc.index. Supports: IFS open parameter list (no vis, cbh, blh).
- GFS index files: https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/gfs.20261110/00/atmos/gfs.t00z.pgrb2.0p25.f012.idx and `…f013.idx`. Supports: GFS fields in section 3 (NOMADS keeps about 10 days).
- DWD ICON-EU listing: https://opendata.dwd.de/weather/nwp/icon-eu/grib/00/ (and the per-variable subdirectories). Supports: ICON-EU fields, steps and file sizes.
- DWD, Database Reference for the Global and Regional ICON and ICON-EPS Forecasting System, v2.5.6 (2026): https://www.dwd.de/DWD/forschung/nwv/fepub/icon_database_main.pdf. Supports: definitions of VIS, CEILING, WW (fog codes 45/48), CLCL.
- EUMETSAT Data Policy (last amended 25 Nov 2025): https://www-cdn.eumetsat.int/files/2026-01/45173%20-%20Data_Policy.pdf. Supports: SAF products are Core under CC BY 4.0; Level 1 data under 1 h latency may carry fees.
- NWC SAF (SMHI), Cloud Type product description: https://nwcsaf.smhi.se/ProductDescriptionCloudType.php. Supports: very low cloud class definition.
- EUMETSAT Convection Working Group, Cloud Type: https://cwg.eumetsat.int/?p=1026. Supports: CT limitations (inversions, night, snow).
- MET Norway Frost API, index and terms: https://frost.met.no/index.html, https://frost.met.no/termsofuse2.html. Supports: observation archive, client ID, licence in each response, traffic guidance.

Peer-reviewed papers (DOI links; "abstract" means read via the OpenAlex or Semantic Scholar API because the publisher page blocked access):

- Westerhuis, Fuhrer, Cermak, Eugster 2020, QJRMS 146:3347–3367, https://doi.org/10.1002/qj.3849 (abstract). COSMO-1 negative FLS bias in winter; advection-scheme diffusion.
- Philip, Bergot, Bouteloup, Bouyssel 2016, Weather and Forecasting 31:1655–1671, https://doi.org/10.1175/WAF-D-16-0074.1 (abstract). AROME vertical resolution; low-cloud ceiling poorly simulated.
- Contreras Osorio et al. 2022, Atmosphere 13:2127, https://doi.org/10.3390/atmos13122127 (abstract). HARMONIE-AROME microphysics and fog.
- Müller et al. 2017, Weather and Forecasting 32:609–627, https://doi.org/10.1175/WAF-D-16-0099.1 (abstract). AROME-MetCoOp description (background for MEPS).
- Steeneveld, Ronda, Holtslag 2015, Boundary-Layer Meteorology 154:265–289, https://doi.org/10.1007/s10546-014-9973-8 (abstract from https://research.wur.nl/en/publications/the-challenge-of-forecasting-the-onset-and-development-of-radiati). Onset and dispersal biases; BL and microphysics roles.
- Román-Cascón et al. 2016, QJRMS 142:1048–1063, https://doi.org/10.1002/qj.2708 (abstract). WRF fails on onset, dissipation and depth; statistical thresholds.
- Singh, Schmidli, Bašták Ďurán, Westerhuis 2025, JGR Atmospheres 130, https://doi.org/10.1029/2024JD042610 (abstract). ICON turbulence schemes and fog over complex terrain.
- Price et al. 2018, BAMS 99:2061–2077, https://doi.org/10.1175/BAMS-D-16-0299.1 (abstract). LANFEX; about 100 m models reproduce local variability.
- Smith et al. 2021, QJRMS 147:746–763, https://doi.org/10.1002/qj.3943 (abstract). Valleys too warm and too little fog; soil conductivity shifts onset up to 5 h.
- Boutle et al. 2016, QJRMS 142:360–371, https://doi.org/10.1002/qj.2656 (abstract). London Model at 333 m.
- Hughes et al. 2015, GMD 8:3105–3117, https://doi.org/10.5194/gmd-8-3105-2015 (full text, open access). Unresolved small valleys; 5–10 K cold pools; critical-RH cloud-scheme bias.
- Maronga and Bosveld 2017, QJRMS 143:2463–2480, https://doi.org/10.1002/qj.3100 (abstract). Soil temperature controls onset; soil moisture controls lifting and dissipation (LES).
- Zhou and Du 2010, Weather and Forecasting 25:303–322, https://doi.org/10.1175/2009WAF2222289.1 (abstract). Fog ETS 0.063 → 0.334 with a multi-variable diagnostic and multi-model ensemble.
- Izett, van de Wiel, Baas, Bosveld 2018, Boundary-Layer Meteorology 169:347–372, https://doi.org/10.1007/s10546-018-0374-2 (full text: https://pmc.ncbi.nlm.nih.gov/articles/PMC6208920). Observation threshold method; hit and false-alarm rates; Menut 2014 thresholds.
- Lundquist, Pepin, Rochford 2008, JGR 113 D22, https://doi.org/10.1029/2008JD009879 (abstract). DEM-based cold-air-pool mapping; about 1 °C error reduction.
- Daly, Conklin, Unsworth 2010, Int. J. Climatology 30:1857–1864, https://doi.org/10.1002/joc.2007 (abstract). Valley-bottom decoupling from 700 hPa flow.
- Cermak and Bendix 2011, Int. J. Remote Sensing 32:3345–3371, https://doi.org/10.1080/01431161003747505 (abstract). Satellite ground-fog vs low-stratus; hit rate 81%, threat score 0.62.
- Schulz, Thies, Chang, Bendix 2016, AMT 9:1135–1152, https://doi.org/10.5194/amt-9-1135-2016 (abstract; open access). Ground fog in mountains from MODIS and terrain.
- Egli et al. 2017, QJRMS 143:530–541, https://doi.org/10.1002/qj.2941 (abstract). European SEVIRI FLS climatology; HSS 0.45.
- Jahani et al. 2025, AMT 18:1927–1941, https://doi.org/10.5194/amt-18-1927-2025 (abstract; open access). Day-and-night SEVIRI FLS detection; POD 0.70–0.82, FAR 0.21–0.31.

## Check by the main session (2026-11-10)

- Re-read and confirmed verbatim: MET Norway METinfo 20/2026 (low stratus under subsidence inversions, saturation at 975–900 hPa, IFS better, small T/Td errors and fog) and METinfo 14/2023 (inland radiation fog missed at 1 h lead time; stratus under weak subsidence inversions "one of the main weaknesses"), by extracting the PDF text locally; the Yr help article and Locationforecast data model; the MET Nordic dataset page; meteoblue's astronomy-seeing help and the Kongsberg multimodel page (no MEPS or MetCoOp named); ECMWF FUG §9.4, §9.4.1 and §9.10.
- Two wordings corrected above: the 1–3 h early clearing is one of ECMWF's "initial perceptions", and the "orographic features" sentence is about the conditions for very low visibility, not "fog and low cloud" as worded before.
- The Kongsberg multimodel page has `domains=HARMONIE` in an image-download link, but no model on the page is labelled MEPS. HARMN-5 is KNMI's model.
- The peer-reviewed papers cited from abstracts were not re-checked.

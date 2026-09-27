# RESEARCH.md: research notes for astro-seeing

- **Origin:** compiled on 2026-09-26 from the research Riley did with Claude. Every link and citation below was checked that day.
- **Source of truth:** the PDFs in `papers/` (see §10). If this file disagrees with a paper, trust the paper, fix this file, and log the correction in `docs/decisions.md`.
- **Confidence tags:**
  - *[verified]*: confirmed against the source.
  - *[estimate]*: our own calculation, to be replaced by measurements.
  - *[check]*: not fully confirmed; resolve in phase 1.

---

## 1. Bottom line

- **No usable API:** nothing free or cheap serves ≥5 years of global historical seeing.
  - meteoblue sells seeing forecasts; its API packages return at most 4 days of history. *[verified 2026-09]*
  - 7Timer! (GFS-based) gives a 72-hour astronomy forecast, with no archive documented. Seeing comes in 8 classes: <0.5″, 0.5–0.75″, 0.75–1″, 1–1.25″, 1.25–1.5″, 1.5–2″, 2–2.5″, >2.5″. *[verified]*
- **What everyone does:** every study that produced historical or global seeing followed the same recipe: reanalysis temperature and wind profiles → a Tatarskii-type Cₙ² model → integrate → seeing. Mostly with ERA5.
- **What to expect:**
  - Free-atmosphere seeing is reproduced reasonably (r = 0.64 at Paranal).
  - Total seeing is reproduced poorly (r = 0.30), because the ground layer (the lowest tens to hundreds of metres) dominates and no global model resolves it.
  - Typical errors are 0.2–0.4″, with biases in both directions.
  - ERA5 distributions come out too narrow.
  - Plan to calibrate, validate, and say clearly what the map shows.
- **Height matters non-linearly:**
  - Height above the local ground matters most, and mainly in the first tens of metres.
  - Site altitude itself correlates only loosely with seeing.

## 2. Altitude and seeing (background)

- **Why the effect is non-linear:** seeing scales as ε ∝ J^(3/5), where J = ∫Cₙ²dz. Halving J improves seeing by about 34%, not 50%.
- **Tokovinin, Baumont & Vasquez 2003 (Cerro Tololo, May–July 2002):** median seeing 0.95″. The first 500 m contribute 60% of total seeing. Free-atmosphere median 0.55″, almost never better than 0.15″. *[verified]*
- **TMT site testing (Schöck et al. 2009):** identical instruments at five sites (table in §6.4).
  - The three Chilean sites span 2290–4480 m in altitude but have the same median seeing (0.63–0.64″).
  - Mauna Kea 13N and San Pedro Mártir are worse because of a stronger ground layer (7–500 m).
  - Precipitable water vapour falls exponentially with altitude. That matters for infrared, not visible seeing. *[verified]*
- **Racine 2005:** 41 campaigns at 23 sites, altitudes 1130–5150 m, instruments 1–30 m above ground. Surface-layer blur decreases with a **3.5 m scale height**. *[verified via abstract index; full text not on arXiv]*
- **Agabi et al. 2006 (Dome C, 75°S 123°E, 3250 m):** a 36 m surface layer holds 87% of the turbulence. Free-atmosphere seeing is 0.36 ± 0.19″ above 30 m, versus 1.3 ± 0.8″ from a DIMM on an 8.5 m tower. *[verified]*
- **Hickson et al. 2013 (Eureka, Canadian Arctic, 610 m):** a weak ground layer makes seeing comparable to the best high sites. They combine layers with ε = (ε_GL^(5/3) + ε_FA^(5/3))^(3/5) (their eq. 6). *[verified]*

## 3. Papers and methods

### 3.1 Bi et al. 2023: global seeing map from ERA5 (primary method reference)
- **Citation:** Bi, Qing, Qian, Luo, Zhu, Weng, "Investigation of the Global Spatio-Temporal Characteristics of Astronomical Seeing", *Remote Sensing* 15(9), 2225 (2023). DOI 10.3390/rs15092225. Open access: https://www.mdpi.com/2072-4292/15/9/2225
- **Method:**
  - Tatarskii Cₙ² with the HMNSP99 outer-scale model (Ruggiero & DeBenedictis 2002, their ref. [36]), driven by ERA5 T, u and v.
  - Seeing ε = 5.25 λ^(−1/5) (∫Cₙ²dh)^(3/5), with **λ = 550 nm**.
  - ERA5 at 0.25°, hourly, using the nearest grid point to each site.
- **Typo:** they print the dry adiabatic lapse rate as 9.8×10³ K/m. The correct value is **9.8×10⁻³ K/m**.
- **Ambiguity [check]:** the text mentions "137 vertical levels", but the paper never says whether they used pressure-level or model-level data. Try both in phase 1 and see which reproduces their Table 3.
- **Findings:** the best seeing is over the Tibetan Plateau and the Andes/Cordillera (the Tibetan Plateau is best in spring). Antarctica is low in all seasons.
- **Validation:** 3 radiosonde campaigns and 4 DIMM sites (§6.1).
  - Medians are within about ±0.2″ of the measurements, with errors in both directions.
  - ERA5 interquartile ranges are much narrower than the measured ones.
  - Their DIMMs sit on towers several metres high.

### 3.2 Priyatikanto et al. 2026: Timau Observatory (Indonesia) from ERA5
- **Citation:** "Seeing at Timau National Observatory Based on ERA5 Dataset", *Experimental Astronomy* 61(3), article 16 (2026). DOI 10.1007/s10686-026-10054-y. arXiv:2604.19023; use the HTML version https://arxiv.org/html/2604.19023 because our fetcher couldn't read text from the PDF.
- **Site:** Timau, 123.9472°E, 9.5971°S, ~1300 m (a 3.8 m telescope is planned).
- **Data:**
  - ERA5 hourly, 2002-01-01 to 2021-12-31, from 1000 hPa to 1 hPa.
  - They write "the interval between pressure levels is 25 hPa". ERA5's standard levels are *not* evenly spaced, so check what they actually used *[check]*.
  - The site value comes from consecutive 1-D cubic interpolation in longitude, latitude and pressure.
  - The cube was downloaded as NetCDF, and before computing they interpolated T and wind *linearly onto 5 hPa steps from 10 to 1000 hPa* (their §II.2; applied to ERA5 and radiosondes alike). *[verified in the arXiv HTML served on 2026-09-27]*
- **Method:** Tatarskii + HMNSP99; ε = 0.98 λ/r₀. λ is given only as "e.g. 500 nm" *[check]*.
- **Printed equations differ from §4.4 in three ways** *[verified in the arXiv HTML served on 2026-09-27]*; the reproduction must try each variant:
  1. Eq. 6: M = −7.9×10⁻⁵ (P/T²) ∂θ/∂h, i.e. P/T² times ∂θ/∂h. Bi et al.'s form is (P/T²)(∂T/∂z + γ) = P/(Tθ) ∂θ/∂z, so the printed form is larger by θ/T.
  2. Eq. 7: θ = T (100/P)^0.286 (100, not 1000). If used literally this scales Cₙ² by 10^(−0.572) ≈ 0.27. Probably a typo.
  3. Eq. 4 writes 10^(a₁ + a₂S − a₃ dT/dh) with a₃ = −192.347 (troposphere), −57.784 (stratosphere), which gives **+**192.347·dT/dh, the opposite sign to §4.4. Probably a typo (a double negative).
- **Radiosonde check:** at Eltari Airport (123.6679°E, 10.1686°S), 2017–2018, 295 soundings around 12 UT. **ERA5 seeing came out at about 76% of the radiosonde-derived value** (R² = 0.51).
- **Results:**
  - Timau ERA5 median **0.79″**, best in March and December, more variable in the dry season (May–September).
  - They recommend multiplying ERA5 by **1.3**, giving **1.03″**.
  - A DIMM measured a median of **0.93″** in July–August 2019 (Akbar et al. 2019), with similar values in 2021.
- **Use:** a reproduction target, and evidence that ERA5 can underestimate seeing.

### 3.3 Osborn & Sarazin 2018: ECMWF turbulence forecast at Cerro Paranal
- **Citation:** "Atmospheric turbulence forecasting with a General Circulation Model for Cerro Paranal", *MNRAS* 480(1), 1278–1299 (2018). DOI 10.1093/mnras/sty1898. arXiv:1809.08005.
- **Data:**
  - Taken from the "ERA5 catalogue": **137 model levels**, 0.3° spacing.
  - These are *forecasts* from the 06 and 18 UT runs, with hourly steps up to 19 h.
  - Interpolated onto the stereo-SCIDAR 250 m grid, from the site up to 25 km.
- **Model:** Cₙ² from potential temperature and wind shear (§4.4), with **one global constant K = 6.0**, fitted to a random 50% of the stereo-SCIDAR data. No altitude-dependent calibration.
- **Terrain fix:** Paranal is at 2635 m, but its model grid cell sits at 926 m. They moved the model's turbulence from 926–1926 m up to 2635–3635 m.
- **Results:**

  | Quantity | Correlation | Bias | RMSE |
  |---|---|---|---|
  | Total seeing | 0.30 | −0.01″ | 0.31″ |
  | Free-atmosphere seeing | 0.64 | +0.08″ | 0.16″ |
  | Ground-layer seeing | 0.24 | −0.05″ | 0.33″ |
  | Isoplanatic angle θ₀ | 0.40 | | |
  | Coherence time τ₀ | 0.63 | | |

  The median profile correlated at 0.98.
- **Split height (resolved 2026-09-27):** O&S use **1 km above the observatory**: "free atmosphere seeing (h>1 km)" and "ground layer seeing (integrated from the ground to h=1 km)" (§5.7, Fig. 9 caption). Haslebacher et al.'s "about 1–2 km" is looser than the PDF.
- **Not printed:** their r₀→ε conversion and wavelength. We assume 0.98 λ/r₀ at 500 nm for comparisons *[check]*.
- **Use:** our alternative Cₙ² model; the ground-layer relocation idea; the free-atmosphere vs total benchmark.

### 3.4 Haslebacher et al. 2022: ERA5 and climate models at 8 observatories
- **Citation:** Haslebacher, Demory, Demory, Sarazin, Vidale, "Impact of climate change on site characteristics of eight major astronomical observatories using high-resolution global climate projections until 2050", *A&A* 665, A149 (2022). DOI 10.1051/0004-6361/202142493. arXiv:2208.04918.
- **Code:** https://github.com/CarolineHaslebacher/Astroclimate-future-project, **GPL-3.0**. The code is on the **`code` branch** (`main` holds only the LICENSE and README). The seeing script is `calc_model_seeing_values.py`.
  - Its ERA5 level list is `[50, 100, 125, 150, 175, 200, 225, 250, 300, 350, 400, 450, 500, 550, 600, 650, 700, 750, 775, 800, 825, 850, 875, 900, 925, 950, 975, 1000]` hPa: 28 levels, no 70 hPa.
  - It contains a commented `# k = 6`.
- **Sites:** table in §6.3.
- **Comparisons:** ERA5 is compared with in situ data as **monthly means**, using a skill score (their eq. 17 and Table 5).
- **Seeing methods:**
  1. "200-hPa-wind-speed seeing" (their eq. 12, from Vernin 1986), described in §4.6. They quote: "seeing below 1 arcsecond requires wind speeds below 20 m s⁻¹ at the tropopause".
  2. The "seeing model": the Osborn & Sarazin Cₙ² formula (their eq. 13), integrated from a site-specific lower pressure level (their Table 4). The calibration factor k was set per site from the *mean in situ seeing* (e.g. 1.32″ at Sutherland); the script's `# k = 6` is commented out.
  - **Seeing conversion:** ε = **0.976** λ/r₀ at λ = 500 nm (their eqs. 5–6), not 0.98. *[verified in the arXiv PDF served on 2026-09-27]*
  - **Integration:** "Euler forward numerical scheme", from the Table 4 level upward.
  - **Table 4, ERA5 seeing-model lower levels (hPa):** Mauna Kea 800, Paranal 900, La Silla 825, Tololo 825, La Palma 1000, Siding Spring 950, Sutherland 850, San Pedro Mártir 850 (also in `configs/sites.yaml`).
- **Seeing results (ERA5 vs in situ, monthly means):**
  - Average skill is "poor": 0.20 for 200-hPa-wind-speed seeing and 0.28 for the seeing model.
  - Best: Mauna Kea, 0.39 (200 hPa). Worst: Paranal, 0.06 (0.07 against Paranal MASS-DIMM).
  - They blame local effects and ERA5's low vertical resolution. O&S "highlight the importance of considering more than 100 vertical levels", and ERA5 has 37 pressure levels.
  - The seeing model's standard deviation is too low.
  - At La Palma, ERA5 puts the seasonal maximum in July–August, while in situ data peak in February; seeing there is dominated by local surface winds around the caldera.
- **Cloud results** (ERA5 night-time total cloud vs observatories' weather-loss logs):
  - Mean skill 0.50 ("mediocre"); Siding Spring 0.72 ("good").
  - **Mauna Kea 0.13 ("poor")**. Using Hawaii's highest ERA5 grid point only raised it to 0.16, while using **high cloud only (above 6 km) raised it to 0.21**.
  - Mauna Kea sits above the trade-wind inversion (~2000 m) and La Palma's observatory above its inversion (~1000 m). ERA5's total cloud counts cloud below the summits.
- **ESO sky definitions** (Kerber et al. 2014, quoted here):
  - Photometric: no visible clouds, transparency variations <2%.
  - Clear: <10% cloud cover, transparency variations <10%.
  - Thin cirrus: transparency variations >10%.
  - Paranal is photometric on 78% of nights.
- **Use:** an exact reproduction target (run their code on our data); evidence for the cloud-above-height approach; a skill-score method we can reuse.

### 3.5 Ye 2011: the forecast model behind 7Timer!
- **Citation:** "Forecasting Cloud Cover and Atmospheric Seeing for Astronomical Observing: Application and Evaluation of the Global Forecast System", *PASP* 123(899), 113–124 (2011). DOI 10.1086/658201. arXiv:1011.3863.
- **Method:** GFS with the Trinquet–Vernin AXP seeing model and the Xu–Randall cloud scheme. Tested at 9 sites, January 2008 to December 2009.
- **Results:** seeing RMSE of 0.2–0.4″ in most cases; the worst errors come from near-ground turbulence.

### 3.6 Masciadri et al. 2017 and Lascaux et al. 2015: site-scale models (why we can't do the ground layer globally)
- **Masciadri et al.:** "Optical turbulence forecast: ready for an operational application", *MNRAS* 466(1), 520–539 (2017). DOI 10.1093/mnras/stw3111. arXiv:1612.00711.
  - Astro-Meso-NH with nested grids at 10, 2.5 and 0.5 km, and 62 vertical levels (the first at 5 m).
  - Initialised and forced every 6 h by ECMWF HRES analyses. Operational at the VLT and ELT sites.
- **Lascaux et al.:** *MNRAS* 449(2), 1664–1678 (2015). DOI 10.1093/mnras/stv332. arXiv:1504.01525. They added a **100 m** domain for surface-layer forecasts at Paranal.

### 3.7 Pierzyna, Basu & Saathof: OTCliM (near-ground Cₙ² climatology from ERA5)
- **Citation:** *Artificial Intelligence for the Earth Systems* 4(2) (2025). DOI 10.1175/AIES-D-24-0076.1. arXiv:2408.00520.
- **Data:** 17 New York State stations with sonic anemometers at 9 m.
- **Results:**
  - Gradient boosting on ERA5 inputs, trained on one year of local measurements per site: ⟨r⟩ = 0.78 ± 0.04.
  - **The W71 physics formula with ERA5 inputs: ⟨r⟩ = 0.30 ± 0.11.**
  - A model trained on in situ data (upper bound): 0.89 ± 0.02.
- **Use:** W71 from ERA5 is a weak ground-layer estimator, and the machine-learning route needs local data at every site, so it can't make a global map.

### 3.8 Aksaker et al. 2020: global site suitability (no seeing)
- **Citation:** "Global Site Selection for Astronomy", *MNRAS* 493(1), 1204–1216 (2020). DOI 10.1093/mnras/staa201. arXiv:1912.01911.
- **Method:** a 1 km global suitability index (SIAS) built from 7 satellite-derived layers (cloud, elevation, artificial light, precipitable water vapour, aerosol optical depth, wind speed, land use) by multi-criteria decision analysis.
- **Use:** a precedent for the layer design.

### 3.9 Wind at 200 hPa as a turbulence indicator
- **García-Lorenzo, Eff-Darwich, Fuensalida, Castro-Almazán 2009**, "Adaptive Optics Parameters connection to wind speed at the Teide Observatory", *MNRAS* 397(3), 1633–1646. DOI 10.1111/j.1365-2966.2009.15071.x. arXiv:0904.0142.
  - **A corrigendum exists:** *MNRAS* 414(2), 801–809 (2011), DOI 10.1111/j.1365-2966.2011.17787.x. Read it before using their numbers.
  - They give formulas for r₀, θ₀, τ₀ and V₀ (§4.5).
  - V₀ = (0.47 ± 0.06)·V₂₀₀ (range 0.41–0.59), versus 0.4 at Paranal/Pachón and 0.56 at San Pedro Mártir.
- **García-Lorenzo, Fuensalida, Muñoz-Tuñón, Mendizabal 2005**, *MNRAS* 356(3), 849–858. DOI 10.1111/j.1365-2966.2004.08542.x. arXiv:astro-ph/0410599. They ranked 5 sites by V₂₀₀ from NCEP/NCAR 1980–2002: La Palma best (22.13 m/s), La Silla worst (33.35 m/s).

### 3.10 Measurement and background papers
| Paper | Reference | arXiv |
|---|---|---|
| Tokovinin, Baumont & Vasquez 2003, Cerro Tololo profiles | MNRAS 340(1), 52–58; DOI 10.1046/j.1365-8711.2003.06231.x | astro-ph/0209432 |
| Schöck et al. 2009, TMT Site Testing I | PASP 121(878), 384–395; DOI 10.1086/599287 | 0904.1183 |
| Els et al. 2009, TMT Site Testing VI: turbulence profiles | PASP 121, 527–543 | 0904.1865 |
| Racine 2005, Altitude, Elevation, and Seeing | PASP 117(830), 401–410; DOI 10.1086/429307 | not on arXiv |
| Agabi et al. 2006, Dome C | PASP 118(840), 344–348 | astro-ph/0510418 |
| Hickson, Gagné, Pfrommer, Steinbring 2013, Eureka | MNRAS 433(1), 307–312; DOI 10.1093/mnras/stt729 | 1305.0615 |
| Aristidi et al., PML turbulence profiler | AO4ELT6 proceedings (2019) | 2002.04947 |

Classic references cited by the papers above; no local copies: Tatarskii 1961 (book); Roddier 1981; Ruggiero & DeBenedictis 2002 (HMNSP99; DoD HPCMP Users Group Conference); Dewan et al. 1993 (PL-TR-93-2043); Vernin 1986; Sarazin & Tokovinin 2002 (V₀ ≈ 0.4·V₂₀₀); Wyngaard, Izumi & Collins 1971 (JOSA 61, 1646); Kerber et al. 2014 (ESO sky definitions).

---

## 4. Equations

### 4.1 Darkness
```
sin a    = sin φ · sin δ + cos φ · cos δ · cos H          a = solar altitude, φ = latitude,
                                                           δ = solar declination, H = hour angle
cos H₁₈  = (sin(−18°) − sin φ · sin δ) / (cos φ · cos δ)
dark h   = 2 · (180° − H₁₈) / 15°                         0 h if cos H₁₈ ≤ −1; 24 h if cos H₁₈ ≥ 1
```
- **Seasonal limits [estimate]:** at the summer solstice (June in the north, December in the south), latitudes above ~47.3° get less than 2 dark hours, and above ~48.6° none.
- **Nights per year with ≥2 dark hours [estimate]:**

  | Latitude | Nights |
  |---|---|
  | ≤45° | 365 |
  | 47.5° | 349 |
  | 50° | 309 |
  | 55° | 269 |
  | 60° | 239 |
  | 65° | 213 |

  These come from the simple declination formula; test against Skyfield.
  - **Measured** with our Skyfield-based module (DE440s, 1-minute resolution, 2021–2025 mean, lon 0°): 365.2, 349.6, 308.8, 268.0, 237.2, 210.6. They agree with the estimates to ≤1 night up to 50°; at 55–65° the precise count is 1–3 nights lower.
- **Implementation:**
  - Compute the Sun's apparent position once per time step (Skyfield), then altitude for every cell in vectorised trig.
  - Compute dark durations at ≤1-minute resolution, not by counting hourly samples.
  - Test against Skyfield `almanac.dark_twilight_day` (codes: 0 dark, 1 astronomical twilight, 2 nautical, 3 civil, 4 day) at sample sites.
- **Night definition:** local mean solar noon to the next noon, keyed by the date of the evening. Everything is stored in UTC.

### 4.2 Clear sky
- **Plain version:** `clear(t) = tcc(t) ≤ c₀`. ESO calls a sky "clear" below 10% cloud, and 7Timer! uses <20% (§3.4, §1).
- **Our version:** `clear(h, t) = C(h, t) ≤ c₀`, where C is the cloud cover *above height h* (§5).
- **Cloud layers:** ERA5 low, medium and high cloud are defined by pressure bands relative to surface pressure; read the ERA5 parameter documentation for the exact bands *[check]*. Haslebacher et al. describe high cloud as "above 6 km".

### 4.3 Preparing each column
```
Z  = Φ / g₀                     geopotential height of a level; g₀ = 9.80665 m s⁻²
θ  = T · (1000 hPa / P)^0.286   potential temperature
N² = (g / θ) · ∂θ/∂z            static stability
S² = (∂u/∂z)² + (∂v/∂z)²        vertical wind shear (S in s⁻¹)
Ri = N² / S²                    turbulence likely where Ri ≲ 0.25
```
- **Underground levels:** ERA5 pressure levels exist below ground as extrapolated values. Mask any level with p > surface pressure, or with Z below the orography.
- **Layers:** work on slabs between neighbouring levels. Take T and P at the slab midpoint (log-p for pressure) and gradients by finite difference. Cₙ² is constant within a slab, and J = Σ Cₙ²_slab · Δz.
- **Model-level heights:** model levels carry no heights. Integrate upward from the surface:
  - Z₂ − Z₁ = (R_d · T̄_v / g₀) · ln(p₁/p₂), with T_v = T(1 + 0.608 q) and R_d = 287.06.
  - Half-level pressures: p_half = a + b · sp.
  - Follow ECMWF's recipe: it needs t and q on the model levels, plus lnsp and surface geopotential z on model level 1. Levels 49–137 are enough when integrating upward; test against a full-column computation *[check]*.

### 4.4 Cₙ² models
**Tatarskii + HMNSP99** (Bi et al.; Priyatikanto et al.)
```
Cₙ² = 2.8 · [ 79×10⁻⁶ · (P/T²) · (∂T/∂z + γ) ]² · L₀^(4/3)      P in hPa, T in K, γ = 9.8×10⁻³ K m⁻¹
L₀^(4/3) = 0.1^(4/3) · 10^(0.362 + 16.728·S − 192.347·∂T/∂z)    troposphere
L₀^(4/3) = 0.1^(4/3) · 10^(0.757 + 13.819·S −  57.784·∂T/∂z)    stratosphere
S in s⁻¹, ∂T/∂z in K m⁻¹, L₀ in m
```
- **Troposphere/stratosphere switch:** use the WMO lapse-rate tropopause: "the lowest level at which the lapse rate decreases to 2 °C/km or less, provided also the average lapse rate between this level and all higher levels within 2 km does not exceed 2 °C/km". *[verified via ACP 2025: https://acp.copernicus.org/articles/25/16053/2025/acp-25-16053-2025.html]* Bi et al. don't say how they switch, so record our choice.
- **Same thing in θ:** 79×10⁻⁶ (P/T²)(∂T/∂z + g/c_p) = 79×10⁻⁶ · P/(T·θ) · ∂θ/∂z. This is exact with γ = g/c_p ≈ 9.76×10⁻³ K m⁻¹; Bi et al. use 9.8×10⁻³.

**Osborn & Sarazin 2018**
```
Cₙ²(z) = K · [ 80×10⁻⁶ · P / (T·θ) ]² · L^(4/3) · (∂θ/∂z)²      P in hPa
L = √( 2E / ((g/θ)·∂θ/∂z) ),  E = S²   ⇒   L = √(2 S² / N²) = √(2 / Ri)
θ = T (P₀/P)^(R/c_p),  R/c_p = 0.286,  P₀ = 1000 hPa,  K = 6.0 (fitted at Paranal)
```
- **Unstable layers:** where N² ≤ 0, L is undefined. Choose a rule, test it, and log how often it fires.
- **Constants differ:** 79×10⁻⁶ in Bi et al. vs 80×10⁻⁶ in O&S. Use each paper's own value when reproducing it.
- **Sanity check:** the two recipes are the same physics with different constants. Both need calibration, because thin turbulent layers are smoothed out by the model's levels.

### 4.5 From Cₙ² to optical parameters
```
J     = ∫ Cₙ² dz                                   from the observer to the top (ERA5 pressure-level top 50 hPa ≈ 20 km)
r₀    = [0.423 · k² · sec ζ · J]^(−3/5),  k = 2π/λ
ε     = 0.98 · λ / r₀                              radians; × 206 265 → arcsec
      = 5.307 · λ^(−1/5) · (sec ζ)^(3/5) · J^(3/5)  (exact combination of the two lines above)
ε_B   = 5.25  · λ^(−1/5) · J^(3/5)                 as printed by Bi et al. (zenith); 1.1% lower
ε(h)  = same with J(h) = ∫_h^top Cₙ² dz            seeing for an observer at height h
ε_tot = (ε_GL^(5/3) + ε_FA^(5/3))^(3/5)            equivalent to adding the J's (Hickson et al. eq. 6)
θ₀    = [2.914 · k² · (sec ζ)^(8/3) · ∫ Cₙ² · h^(5/3) dh]^(−3/5)   h = height above the observer
τ₀    = 0.314 · cos ζ · r₀ / V₀
V₀    = [ ∫ Cₙ² |V|^(5/3) dh / ∫ Cₙ² dh ]^(3/5)
```
- **Wavelength:** ε ∝ λ^(−1/5), so ε(550 nm) = 0.9811 · ε(500 nm).
- **Our product:** λ = 500 nm at zenith, with the exact (5.307) form. Store J and J(h).

### 4.6 Jet-stream shortcut (Haslebacher et al.; Vernin 1986)
```
∫(2–20 km) Cₙ² dz ≈ A · (u₂₀₀² + v₂₀₀²)    ⇒   ε_FA ∝ V₂₀₀^(6/5)
V₀ ≈ c · V₂₀₀                               c ≈ 0.4 Paranal/Pachón, 0.56 SPM, 0.47 ± 0.06 Teide (see corrigendum)
```
- **Uses:** a sanity check and a fast first-look map. A is fitted.

### 4.7 Ground layer (experimental): W71 / Monin–Obukhov similarity (as written in OTCliM)
```
C_T² = (−w′θ′ / u*)² · z^(−2/3) · g(ζ)
g(ζ) = 4.9 · (1 − 6.1 ζ)^(−2/3)      ζ < 0 (unstable)
g(ζ) = 4.9 · (1 + 2.2 ζ^(2/3))       ζ ≥ 0 (stable)
ζ = z / L,   L = −u*³ · T / (κ · g · w′θ′),   κ = 0.4
Cₙ² = (A · P / T²)² · (1 + 0.03/β)² · C_T²,   A ≈ 7.9×10⁻⁵ K hPa⁻¹, β = Bowen ratio
w′θ′ = −H / (ρ c_p),   ρ = P / (R_d T)
```
- **H:** ERA5 instantaneous surface sensible heat flux.
- **Sign check [check]:** ECMWF's sign convention for vertical fluxes has to be *checked on real data*. Daytime heating over land must come out as an upward (positive) w′θ′.
- **u\*:** ERA5 friction velocity.
- **Performance:** with ERA5 inputs this reached ⟨r⟩ = 0.30 ± 0.11 (OTCliM). It was derived for flat terrain, so treat it as an option to test, not a truth.

### 4.8 Calibration
```
J ∝ K   ⇒   ε ∝ K^(3/5)   ⇒   K_new = K_old · (ε_observed / ε_model)^(5/3)
```
- **Timau example:** ERA5 gives ≈0.76 of the radiosonde-derived value, so J needs scaling by (1/0.76)^(5/3) ≈ 1.58.
- **How to fit:** on nightly medians, with held-out years or sites.
  - Report bias, RMSE and correlation.
  - Where MASS data exist, fit the free atmosphere and the ground layer separately.

### 4.9 Known-answer values (λ = 500 nm, zenith unless noted)
| Test | Expected |
|---|---|
| ε, exact form: J = 1e-13 / 3e-13 / 1e-12 m^(1/3) | 0.3158″ / 0.6106″ / 1.2574″ |
| ε, 5.25 form: same J | 0.3125″ / 0.6040″ / 1.2439″ |
| J that gives 1.00″ | 6.83e-13 (exact form); 6.95e-13 (5.25 form) |
| r₀ for ε = 1.00″ | 0.1011 m |
| ε(550 nm) / ε(500 nm) | 0.9811 |
| θ₀, single layer J = 1e-13 at 10 km | 2.07″ |
| τ₀, J = 3e-13 (r₀ = 0.1655 m), V₀ = 20 m/s | 2.60 ms |
| HMNSP99 troposphere, S = 0.005 s⁻¹, ∂T/∂z = −0.0065 K/m | exponent 1.6959; L₀^(4/3) = 2.3044; L₀ = 1.870 m |
| HMNSP99 stratosphere, S = 0.005 s⁻¹, ∂T/∂z = +0.002 K/m | L₀^(4/3) = 0.2383; L₀ = 0.341 m |
| Tatarskii, P = 500 hPa, T = 250 K, ∂T/∂z = −0.0065, γ = 9.8e-3, L₀^(4/3) = 2.3044 | Cₙ² = 2.807e-17 m^(−2/3) |
| O&S, same state, S = 0.005 s⁻¹, K = 6, g/c_p | N² = 1.279e-4 s⁻²; Ri = 5.12; L = 0.625 m; Cₙ² = 1.397e-17 |

Property tests to include:
- J(h) and C(h) never increase with h.
- Adding a layer never lowers J.
- ε round-trips through J.
- Darkness matches Skyfield to within 1 minute at test sites.

---

## 5. Terrain-aware downscaling (our method)

**Goal:** show real mountain-scale detail (30 m terrain) even though the weather is on a 31 km grid. Riley wants terrain of 100 m or finer, so Copernicus GLO-30 is used.

For each ERA5 cell c and hour t:
1. **Height grid:** absolute heights hⱼ every 50 m (for example −500 m to 9000 m). Pixels below the cell's ERA5 surface are treated as sitting at that surface, and counted.
2. **Free atmosphere:** J_FA(h, t) = ∫ₕ^top Cₙ² dz, piecewise over the slabs, including the partial slab that contains h.
3. **Ground layer:** J_GL(c, t), one term per cell, chosen in phase 1 from: none; the Osborn–Sarazin relocation of the model's lowest 1 km; W71; or a calibrated constant. It doesn't depend on h.
4. **Seeing:** ε(h, t) from J_FA(h, t) + J_GL(c, t).
5. **Cloud above h:** C(h, t) combines the pressure-level cloud fractions `cc` above h under an overlap rule (random, maximum, or maximum-random).
   - Pick the rule by a consistency check: at h = the ERA5 surface, C should reproduce ERA5's own total cloud cover. Log the residuals.
6. **Good hour:** dark(t) ∧ C(h, t) ≤ c₀ ∧ ε(h, t) ≤ ε₀.
   - **Good night** (placeholder until phase 1): ≥2 dark hours and ≥N₀ good hours.

**Monotonicity trick:**
- J_FA(h) and C(h) never increase with height; darkness and J_GL don't depend on h. So if a night is good at height h, it is good at every height above h.
- Each night therefore has one number: the lowest good height h*ₙ (∞ if the night is never good).
- A pixel at elevation e counts the night if h*ₙ ≤ e.
- Store h*ₙ per cell, night and threshold set as a uint8 bin index: 367,051 cells × 1,826 nights ≈ **0.67 GB per threshold set**.
- Aggregate to counts per height bin (per year and month) for the viewer.
- Median seeing and clear-night counts are stored as per-cell tables by height bin.

**Pixel values:**
- Evaluate each neighbouring cell's table at the pixel's own GLO-30 elevation (clipped to that cell's surface).
- Blend bilinearly between the 4 surrounding cell centres, so no 25–30 km blocks appear while the terrain detail stays.
- Generate at render time, or pre-render only the low zooms (phase 2 decides).

**Caveats (keep them visible in the UI and reports):**
- The fine detail comes from terrain; the weather behind it is still 31 km.
- There's no pixel-level ground layer.
- Summits far above ERA5's smoothed ground get the cell's ground-layer term.
- Valleys are clipped to the ERA5 surface.

**Phase 1 tests:**
- At summit sites: seeing at the true site altitude vs at the ERA5 surface vs measurements (Paranal, Mauna Kea, La Palma, Lenghu, TMT sites).
- C(h) vs total cloud consistency.
- Cloud above the summit vs site records where available.
- Benchmark against Haslebacher's Mauna Kea result: total-cloud skill 0.13, high cloud only 0.21.

---

## 6. Validation targets

### 6.1 Bi et al. 2023: Tables 2 and 3 (median [25%, 75%], arcsec; λ = 550 nm)
| Site | Site lon, lat | ERA5 grid point | Period (UTC) | Measured | ERA5 (theirs) |
|---|---|---|---|---|---|
| Da Qaidam (~3200 m) | 95.35E, 37.74N | 95.25E, 37.75N | Aug 2020 (radiosondes) | 1.06 [0.72, 1.75] | 0.88 [0.85, 0.93] |
| Haikou (~15 m) | 110.19E, 20.05N | 110.25E, 20.00N | Apr 2018 (radiosondes; text says Mar–Apr) | 1.15 [0.74, 2.32] | 1.17 [1.15, 1.20] |
| Rongcheng (~80 m) | 122.11E, 36.46N | 122.00E, 36.50N | Nov 2018 (radiosondes) | 1.09 [0.98, 1.38] | 1.23 [1.17, 1.30] |
| Ali | 80.06E, 32.31N | 80.00E, 32.25N | Mar 2017 – Feb 2019 (DIMM) | 1.08 [0.88, 1.39] | 0.87 [0.79, 1.00] |
| Daocheng | 100.11E, 29.11N | 100.00E, 29.00N | Mar 2017 – Feb 2019 (DIMM) | 1.01 [0.84, 1.22] | 0.96 [0.85, 1.10] |
| Muztagh-ata | 74.90E, 38.33N | 75.00E, 38.25N | Mar 2017 – Feb 2019 (DIMM) | 0.82 [0.64, 1.06] | 0.85 [0.78, 0.92] |
| Lenghu | 93.89E, 38.61N | 94.00E, 38.50N | "Oct. 2018 to 2020" (DIMM) | 0.75 [0.61, 1.03] | 0.96 [0.88, 1.07] |
- **Balloon timing:** flights were launched in the early morning or late evening local time, so match those hours.
- **Altitudes:** the DIMM site altitudes aren't in these tables; get them from the paper or its references.

### 6.2 Timau (Priyatikanto et al.)
- **Site:** 123.9472E, 9.5971S, ~1300 m.
- **ERA5 (2002–2021):** median 0.79″, ×1.3 → 1.03″.
- **Measured:** DIMM median 0.93″ (July–August 2019).
- **Radiosonde check:** Eltari 123.6679E, 10.1686S, 2017–2018 (ratio 0.76).

### 6.3 Haslebacher et al. 2022: sites (Table 1; pressure = monthly mean in situ ± sd)
| Site | Lon, Lat | Elevation (m) | Pressure (hPa) |
|---|---|---|---|
| Mauna Kea | −155.47, 19.82 | 4200 | 616.28 ± 1.70 |
| Cerro Paranal | −70.40, −24.63 | 2635 | 743.66 ± 0.50 |
| La Silla | −70.73, −29.25 | 2400 | 771.06 ± 2.00 |
| Cerro Tololo | −70.80, −30.17 | 2200 | 781.28 ± 2.66 |
| La Palma | −17.89, 28.76 | 2370 | 771.21 ± 3.10 |
| Siding Spring | 149.07, −31.28 | 1165 | 891.56 ± 4.55 |
| Sutherland | 20.81, −32.38 | 1798 | 826.49 ± 1.50 |
| San Pedro Mártir | −115.46, 31.04 | 2800 | 732.70 ± 3.20 |

Their seeing data include La Palma (IAC/ING, 2004–2019), Siding Spring (AAT, 1993–2019) and San Pedro Mártir (TMT campaign, 10/2004–08/2008). Get the rest from their Table 2.

### 6.4 TMT site testing (Schöck et al. 2009, Tables 1–2; medians in arcsec)
| Site | Lat, Lon | Elev (m) | Total (DIMM) | Best 10% DIMM | Free atm. (MASS) | Best 10% MASS | Ground layer 7–500 m | θ₀ |
|---|---|---|---|---|---|---|---|---|
| Cerro Tolar | −21.9639, −70.0997 | 2290 | 0.63 | 0.42 | 0.44 | 0.24 | 0.34 | 1.93 |
| Cerro Armazones | −24.5800, −70.1833 | 3064 | 0.64 | 0.41 | 0.43 | 0.23 | 0.35 | 2.04 |
| Cerro Tolonchar | −23.9333, −67.9750 | 4480 | 0.64 | 0.44 | 0.48 | 0.25 | 0.32 | 1.83 |
| San Pedro Mártir | 31.0456, −115.4691 | 2830 | 0.79 | 0.50 | 0.37 | 0.17 | 0.58 | 2.03 |
| Mauna Kea 13N | 19.8330, −155.4810 | 4050 | 0.75 | 0.46 | 0.33 | 0.15 | 0.54 | 2.69 |

- **Checked** against Schöck et al. Table 2 (arXiv PDF served on 2026-09-27): all values match. The same table gives τ₀ (ms): 5.2, 4.6, 5.6, 4.2, 5.1 (same site order).
- **Ground-layer column:** DIMM minus MASS.
- **Raw data:** from the TMT site-testing database (free, login required).
- **Why this set matters:** the separate free-atmosphere and ground-layer medians are the best available test of our split.

### 6.5 Other benchmarks
- **Osborn & Sarazin at Paranal:** the statistics in §3.3.
- **Tololo:** median 0.95″; free atmosphere 0.55″; first 500 m = 60%.
- **Dome C:** free atmosphere 0.36″ above 30 m.
- **Eureka:** free atmosphere 0.30″ (MASS).
- **Calibration data for our period (2021–2025):** the ESO ambient conditions database.
  - Paranal: DIMM, MASS, MASS-DIMM and SLODAR query forms.
  - La Silla: ambient query form.
  - It overlaps the phase 2 and 3 years, so hold out some years for testing.

---

## 7. Data sources and access

**ERA5 (Copernicus Climate Data Store)**
- **Datasets:** `reanalysis-era5-pressure-levels`, `reanalysis-era5-single-levels` (1940–present), `reanalysis-era5-complete` (137 model levels).
- **`~/.cdsapirc` format:** `url: https://cds.climate.copernicus.eu/api` and `key: <PERSONAL-ACCESS-TOKEN>`. Requires `cdsapi>=0.7.7`.
- **Terms of use:** you must accept them manually on each dataset page before any download works.
- **Licence:** CC-BY 4.0 since 2 July 2025. Follow the attribution guidance on the dataset pages.
- **Attribution text** (dataset page "Citation and attribution", read via the CDS catalogue API on 2026-09-27): "Generated using or contains modified Copernicus Climate Change Service information <YYYY>. Neither the European Commission nor ECMWF is responsible for any use that may be made of the Copernicus information or data it contains." Also cite the catalogue entries: pressure levels DOI 10.24381/cds.bd0915c6, single levels DOI 10.24381/cds.adbb2d47 (Hersbach et al. 2023). Stored in `src/astroseeing/provenance.py`.
- **Request keys** (live form): `product_type`, `variable`, `year`, `month`, `day`, `time`, `pressure_level`, `area`, `data_format` (`grib`), `download_format` (`unarchived`).
- **Pressure levels used (29):** 50, 70, 100, 125, 150, 175, 200, 225, 250, 300, 350, 400, 450, 500, 550, 600, 650, 700, 750, 775, 800, 825, 850, 875, 900, 925, 950, 975, 1000 hPa. Spacing is 25 hPa near the surface and 50 hPa between 750 and 250 hPa.
- **Pressure-level variables:** `geopotential` (z), `temperature` (t), `u_component_of_wind` (u), `v_component_of_wind` (v), `fraction_of_cloud_cover` (cc). Optional: `specific_humidity` (q).
- **Single-level variables:** `total_cloud_cover` (tcc), `low_cloud_cover`, `medium_cloud_cover`, `high_cloud_cover`, `cloud_base_height` (cbh), `surface_pressure` (sp), `2m_temperature`, `2m_dewpoint_temperature`, `skin_temperature`, `10m_u_component_of_wind`, `10m_v_component_of_wind`, `100m_u_component_of_wind`, `100m_v_component_of_wind`, `boundary_layer_height` (blh), `friction_velocity` (zust), `instantaneous_surface_sensible_heat_flux` (ishf), `total_column_water_vapour` (tcwv). *[verified 2026-09-27: every name here and in the pressure-level list is on the live CDS request forms]*
- **Fixed fields:** `geopotential` (surface z; orography = z/g₀), `land_sea_mask`, `standard_deviation_of_orography`.
- **Request tips:**
  - Use GRIB; NetCDF requests have smaller size limits.
  - Area subsetting is `area: [N, W, S, E]`.
  - Size limits are enforced as "cost" (number of fields); measure what you hit.
  - Phase 3 uses one global day per request.
- **ERA5 complete (model levels):**
  - Stored on MARS tape: expect "several hours to several days" per request.
  - Retrieve one tape at a time: for analyses, that's one month per level type.
  - Pass `grid` (e.g. `0.25/0.25`) to get a lat/lon grid; the default is spectral or reduced Gaussian.
  - Model levels 49–137 (89 levels) run from about 52.9 hPa (≈20.3 km) down to the surface.
- **ARCO-ERA5 (alternative):** Zarr on Google Cloud, `gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3` and `.../model-level-1h-0p25deg.zarr-v1`, stored in us-central1 with anonymous access.
  - Chunks hold one hour × all levels × the whole globe, so pulling a point time series means reading global chunks.
  - Updated monthly with a 3-month lag (ERA5T about 1 week behind).

**Terrain: Copernicus DEM**
- **Products:** GLO-30 (1″, about 30 m) and GLO-90 (3″).
- **Buckets:** `s3://copernicus-dem-30m` and `s3://copernicus-dem-90m`, region eu-central-1, anonymous access (`--no-sign-request`).
- **Format:** Cloud-Optimised GeoTIFF, float32, DEFLATE compression (predictor 3). GLO-30 tiles are 1°×1°, 3600 px tall, named e.g. `Copernicus_DSM_COG_10_N28_00_W018_00_DEM` (the "10" means 1″). Ocean has no tiles (assume height 0).
- **Longitude spacing grows with latitude:** ×1 up to 50°, ×1.5 from 50–60°, ×2 from 60–70°, ×3 from 70–80°, ×5 from 80–85°, ×10 from 85–90°.
- **What it measures:** a digital surface model (it includes forest canopy and buildings), with EGM2008 heights and WGS84 positions, from TanDEM-X data acquired 2011–2015.
- **Versions:** release 2023_1 (Dec 2023) added the previously restricted Armenia, Azerbaijan and Moldova; 2024_1 (Jul 2024) infilled Spain.
  - The AWS "GLO-30 Public" bucket may lag behind, so check for missing tiles and fill from the latest release or GLO-90.
- **Licence:** free, worldwide, perpetual; allows reproduction, distribution, communication to the public and adaptation. It doesn't mention commercial use explicitly, so [ASK] before any commercial use.
- **Attribution for modified products (required):** "produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved"
- **Handbook:** https://dataspace.copernicus.eu/sites/default/files/media/files/2024-06/geo1988-copernicusdem-spe-002_producthandbook_i5.0.pdf
- **ETOPO 2022 (15″):** NOAA's global relief model (ice-surface and bedrock versions); a fallback only.

**Other inputs**
- **Land mask:** `global-land-mask` (GLOBE 1 km, MIT licence) or OSM land polygons (ODbL, attribution required). Add a 1 km buffer. Our numbers are in §8.
  - **Chosen: `global-land-mask` v1.0.0** (Riley, 2026-09-27; decision D20). GLOBE's unrestricted version has "no copyright or security distribution restrictions" (NOAA NCEI ETOPO page). Cite: National Geophysical Data Center, 1999, GLOBE v.1, Hastings & Dunbar, doi:10.7289/V52R3PMS.
  - Checked: lakes count as land, floating ice shelves as sea. Land is 28.905% of Earth, and 365,088 ERA5 cells contain land before the buffer, consistent with the §8 estimates.
- **Skyfield:** the solar-position library (`almanac.dark_twilight_day` for tests).
- **TMT site-testing database:** https://sitedata.tmt.org. Free; login needed to download.
- **ESO ambient conditions database:** https://archive.eso.org/cms/eso-data/ambient-conditions.html (La Silla, Paranal, Chajnantor; query forms).
- **Open-Meteo (spot checks only, never bulk):**
  - The Historical Weather API's default "Best match" mixes ECMWF IFS HRES, ERA5 and ERA5-Land. The IFS data in that mix is a different model, not ERA5.
  - Select the ERA5 model. The docs' model list shows "ERA5"; `models=era5` is used in the wild but isn't in the parameter table, so confirm it.
  - Add `elevation=nan` so their terrain downscaling is switched off.
- **ERA6:** ~14 km resolution. The first decades are due for release towards the end of 2027, and the first four decades by early 2028. Keep our pipeline source-agnostic so it can swap in.
- **Viewer libraries:**
  - MapLibre GL JS v5.0.0 (released around the turn of 2024/25) added globe view, including terrain on the globe. `maplibregl.addProtocol()` can return an `ImageBitmap` computed in the browser, so tiles can be generated client-side from DEM tiles plus per-cell tables.
  - CesiumJS is Apache-2.0; a Cesium ion token is only needed for ion services.

---

## 8. Estimates to replace with measurements *[estimate]*

**Land mask (1 km GLOBE mask plus a 1 km buffer; lakes count as land)**
- Covers 29.19% of Earth's area (land alone: 28.91%).
- ERA5 0.25° cells kept: **367,051 of 1,038,240** (35.4%); Antarctica is 27.9% of them.
- At 0.5° it's 95,798 cells; at 1°, 25,761.
- The native N320 grid equivalent is about 167,828 of 542,080 points.

**Darkness:** the Sun is below −18° in 29% of all hours, and below −12° in 35.9%.

**Five years (2021–2025, 43,824 h), global download vs kept (land, Sun < −12°).** Values are uncompressed at 2 bytes, with cloud fractions at 1 byte:

| Dataset | Download | Kept |
|---|---|---|
| Pressure levels, 29 levels × (z, t, u, v), hourly | 10.6 TB | 1.34 TB |
| Same, 3-hourly | 3.5 TB | 0.45 TB |
| Add `cc` on 29 levels (hourly / 3-hourly) | +2.6 / +0.9 TB | +0.17 / +0.06 TB |
| 10 surface fields, hourly | 0.91 TB | 0.12 TB |
| 4 cloud fields + cbh, hourly | ~0.45 TB | ~0.03 TB |
| Optional fields | 0.18 TB | 0.02 TB |
| **Total, hourly profiles** | **≈14.7 TB** | **≈1.7 TB** |
| **Total, 3-hourly profiles, hourly single levels** | **≈5.9 TB** | **≈0.7 TB** |

- **Per-day size:** one global hour of pressure-level profiles is ~241 MB of GRIB (~300 MB with `cc`), so one day is ~7 GB.
- **Download time:** at a sustained 25 MB/s, 14.7 TB takes ~7 days and 5.9 TB ~3 days. At 5 MB/s it's ~34 and ~14 days.
- **Compression:** measure the real Zarr compression ratio on one month before extrapolating.
- **GLO-30 download:** ~26,500 tiles. Sampled tile sizes: 4.9 MB (La Palma, mostly ocean), 11.3 MB (Dome C), 21.9 MB (Paranal), 43.0 MB (Everest), so the total is roughly 0.3–1 TB. Stream it and keep only derived products.
- **Benchmarks** (sandbox, one core, 2.1 GHz Xeon):
  - Physics on 89 levels × 367k cells: 2.41 s per hour.
  - GRIB decode: 0.67 s per 116-field global hour (~360 MB/s).
  - So 5 years of pressure-level physics is on the order of 10 CPU-hours (more with height tables): hours of wall time on 5 workers.
- **NAS budget (3.4 TB):**
  - ERA5 kept: 0.7–1.7 TB.
  - Terrain display pyramid: to be measured; keep it ≤0.5 TB unless Riley agrees otherwise.
  - Derived tables: well under 0.1 TB.
  - Leave ≥10% free (ScratchSpace is a thin volume).

---

## 9. Pitfalls checklist
1. **Bi et al.'s lapse rate:** printed as 9.8×10³; use 9.8×10⁻³ K/m.
2. **Seeing coefficient:** 5.25 (printed) vs 5.307 (exact), and 550 vs 500 nm. Reproduce each paper with its own choices.
3. **Refractivity constant:** 79×10⁻⁶ vs 80×10⁻⁶; γ = 9.8×10⁻³ vs g/c_p.
4. **Underground levels:** ERA5 pressure levels below ground hold extrapolated values; mask them.
5. **Level spacing:** ERA5 pressure levels aren't evenly spaced; Priyatikanto's "25 hPa" needs checking.
6. **Haslebacher's code:** it uses 28 levels (no 70 hPa) and compares monthly means.
7. **O&S's data:** ERA5 *forecasts* from the 06/18 UT runs on model levels at 0.3°. Our hourly analyses differ; note it.
8. **Model terrain vs real terrain:** e.g. Paranal is 2635 m, its grid cell 926 m.
9. **Heat-flux sign:** verify on data before trusting it.
10. **Unstable layers:** N² ≤ 0 makes O&S's L undefined. Choose a rule, test it, and count how often it fires.
11. **Interpolation:** interpolate J, not ε.
12. **Polar oversampling:** the 0.25° grid oversamples high latitudes relative to the native N320 grid. Weight averages by cell area (cos φ).
13. **GLO-30 quirks:** a DSM, EGM2008 heights, longitude spacing that varies with latitude, possibly missing tiles, no ocean tiles.
14. **Cloud validation data:** night-time cloud skill is poor at islands and summits, and weather-loss logs include downtime for reasons other than cloud.
15. **DIMM height:** DIMMs sit on towers several metres up and miss part of the surface layer.
16. **Storage:** SQLite must not live on NFS ("Rely upon it at your … peril", sqlite.org). The NFS hard mount hangs if the NAS drops.
17. **Open-Meteo's "Best match" isn't pure ERA5:** Riley's HistoricalCloudCover app got IFS data from 2017 onward this way.
18. **GPL code:** don't copy Haslebacher's code into our source.
19. **Paper downloads:** fetch papers one at a time with a pause and a descriptive User-Agent.
20. **Darkness:** hourly samples are too coarse; compute dark durations at ≤1-minute resolution.
21. **HMNSP99 range:** it was fitted to specific sounding campaigns and can produce extreme L₀. Inspect the distributions and never clip silently.

---

## 10. Papers to fetch into `papers/` (gitignored)
Fetch each file, check it opens, and record SHA-256 hashes in `papers/INDEX.md`.

| File | URL |
|---|---|
| bi2023_remotesensing.pdf | https://www.mdpi.com/2072-4292/15/9/2225/pdf |
| priyatikanto2026_timau.pdf (+ save HTML) | https://arxiv.org/pdf/2604.19023 · https://arxiv.org/html/2604.19023 |
| osborn_sarazin2018.pdf | https://arxiv.org/pdf/1809.08005 |
| haslebacher2022.pdf | https://arxiv.org/pdf/2208.04918 |
| ye2011.pdf | https://arxiv.org/pdf/1011.3863 |
| masciadri2017.pdf | https://arxiv.org/pdf/1612.00711 |
| lascaux2015.pdf | https://arxiv.org/pdf/1504.01525 |
| pierzyna_otclim.pdf | https://arxiv.org/pdf/2408.00520 |
| aksaker2020.pdf | https://arxiv.org/pdf/1912.01911 |
| garcialorenzo2009_teide.pdf (+ corrigendum if accessible) | https://arxiv.org/pdf/0904.0142 |
| garcialorenzo2005_v200.pdf | https://arxiv.org/pdf/astro-ph/0410599 |
| tokovinin2003_tololo.pdf | https://arxiv.org/pdf/astro-ph/0209432 |
| schoeck2009_tmt1.pdf | https://arxiv.org/pdf/0904.1183 |
| els2009_tmt6.pdf | https://arxiv.org/pdf/0904.1865 |
| agabi2006_domec.pdf | https://arxiv.org/pdf/astro-ph/0510418 |
| hickson2013_eureka.pdf | https://arxiv.org/pdf/1305.0615 |
| aristidi_pml.pdf | https://arxiv.org/pdf/2002.04947 |
| copernicus_dem_handbook.pdf | (link in §7) |

- **Racine 2005** (DOI 10.1086/429307) isn't on arXiv; Riley adds it by hand if he can get it.
- **Haslebacher's code:** `git clone -b code https://github.com/CarolineHaslebacher/Astroclimate-future-project external/haslebacher`

---

## 11. Open questions for phase 1
1. **Bi et al.'s data:** which ERA5 product and levels did they use? Test both; see which reproduces §6.1.
2. **Priyatikanto et al.:** which levels and wavelength, and where the ×1.3 factor was applied.
3. **O&S:** how to emulate their forecast data with ERA5 analyses. (Split height resolved: 1 km above the observatory, §3.3.)
4. **Haslebacher et al.:** the periods; reproduce exactly with their code. (Table 4 lower levels and the 0.976 coefficient now recorded, §3.4.)
5. **Ground layer:** which treatment (§5 step 3).
6. **Cloud overlap:** which overlap rule for C(h), and how well C(surface) matches total cloud.
7. **Cloud validation:** what data are obtainable (ESO photometric-night fractions, TMT database, observatory logs).
8. **Time resolution:** how much 3-hourly profiles change good-night counts compared with hourly.
9. **Good-night rule:** the definition and default thresholds, proposed with evidence. [ASK]
10. **Tolerances:** what counts as "matching" a paper (write them in `reports/phase1_plan.md` before running).

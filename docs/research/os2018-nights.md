# Osborn & Sarazin 2018: SCIDAR nights, hours, and how to emulate their ECMWF values

Research for issue #8 (map: #6). Written 2026-10-30 by the agent from the paper itself; nothing here changes code or constants.

**Source read:** arXiv:1809.08005**v1** (the only version; its arXiv record says "Published in MNRAS 480 (1). pp. 1278-1299, 2018"). PDF https://arxiv.org/pdf/1809.08005 (22 pages, matching 1278–1299) and HTML https://arxiv.org/html/1809.08005 were both downloaded and checked; the quoted passages are identical in both. The publisher's page (https://doi.org/10.1093/mnras/sty1898 → academic.oup.com) returned HTTP 403 from this container, so **I could not compare the arXiv text with the published version**. Page numbers below are the arXiv PDF's. The HTML numbers the appendix figures 10–20 instead of A1–A6 and B1–B5.

## Short answer

- **Nights:** the paper has no table of individual dates. It gives date *ranges* in three places that disagree with each other:
  - Table 1 (p. 3): 14 month rows, "Totals: 83" nights, 396.97 h, 10 691 profiles. But its ranges add up to **87** days, not 83.
  - Appendix B captions (nightly median profiles, Figs B1–B5, pp. 18–22): **79** "nights beginning", and that matches the 79 panels I counted.
  - Appendix A captions (profile sequences, Figs A1–A6, pp. 12–17): 69 nights listed, 68 panels.
  - The full transcription is below. Union of all lists: 90 nights. Present in Table 1 and in Appendix B: 76.
- **Hours:** not listed. Each ECMWF hour is compared with "the median stereo-SCIDAR measurement from 2.5 minutes either side of the hour" (§5.2). So the samples are on-the-hour UT times when SCIDAR was running. Table 1 gives only total hours per month (about 4.8 h per night on average). The number of hourly samples behind Tables 2–3 is not given.
- **Table 3 medians:** 0.62″ total, 0.41″ free atmosphere and 0.45″ ground layer are the **ECMWF** column. The stereo-SCIDAR column is 0.61″, 0.34″ and 0.42″.
- **How the ECMWF values were made:**
  - ERA5 short **forecasts** from the 06 and 18 UT runs, on **137 model levels**, at 0.3°. They used "best case data … produced at most 11 hours before".
  - Bilinear interpolation from the four nearest grid points to Paranal.
  - Cₙ² from eq. 7 with a single **k = 6.0**.
  - The Cₙ² profile was interpolated onto the SCIDAR **250 m grid, from the observatory up to 25 km above it**.
  - The model's 926–1926 m layer was **added** into 2635–3635 m.
  - Free atmosphere is h > 1 km above the observatory; ground layer is h < 1 km.
- **r₀→ε and wavelength:** **not stated anywhere in O&S 2018.** Their companion SCIDAR paper (Osborn et al. 2018, arXiv:1806.02585) prints ε = 0.98 λ/r₀ and corrects to zenith. It computes response functions at 500 nm, but it doesn't state the λ used for ε. Neither paper states the convention for the ECMWF values.
- **Closest emulation with our data** (my recommendation, details at the end):
  - Use the hourly ERA5 analysis at the same UT hours, over the Appendix B night list.
  - Bilinearly interpolate z, t, u and v to the site, then compute eq. 7 with k = 6.0.
  - Interpolate Cₙ² onto the 250 m grid above 2635 m, and add the relocated layer from z_g to z_g + 1 km.
  - Convert with ε = 0.98 λ/r₀ at 500 nm, zenith.
  - Take pooled Q1/median/Q3 over hours. Run the Table 1 and union night lists, and the hour definitions, as sensitivities.

## Claims and sources

All from arXiv:1809.08005v1 unless marked otherwise.

### Which data the Table 3 medians cover

1. **Campaign:** stereo-SCIDAR "in regular operation at ESO Cerro Paranal … since April 2016 … (table 1). These 83 nights of data from Cerro Paranal, will be used for the validation of the turbulence forecasts." (§2, p. 2.)
2. **Table 1, "ESO Paranal, Stereo-SCIDAR data volume" (p. 3), transcribed exactly:**

   | Year | Month | Days | Hours | Number of Profiles |
   |---|---|---|---|---|
   | 2016 | April | 26 - 29 | 18.43 | 607 |
   | | July | 22 - 26 | 37.12 | 1143 |
   | | October | 30 - 31 | 10.65 | 301 |
   | | November | 1-2 | 10.80 | 302 |
   | | December | 10 - 12 | 11.62 | 308 |
   | 2017 | March | 7-9 | 16.46 | 469 |
   | | April | 12 - 18 | 37.34 | 988 |
   | | May | 5-9 | 16.06 | 419 |
   | | June | 8 - 10 | 19.97 | 511 |
   | | July | 3-9 | 37.60 | 962 |
   | | August | 3-8 | 34.42 | 930 |
   | | November | 4 - 9, 18 - 20, 29 - 30 | 45.63 | 1076 |
   | | December | 1 - 6, 8 - 18 | 56.69 | 1483 |
   | 2018 | January | 13 - 24 | 44.19 | 1192 |
   | Totals: | | 83 | 396.97 | 10691 |

   - **My arithmetic:** the hours (396.98) and profiles (10 691) add up to the totals.
   - **The day ranges don't:** they enumerate to 87 days (4+5+2+2+3; 3+7+5+3+7+6+11+17; 12). The paper doesn't say which 4 are not nights, or whether "Days" means the local evening date or the UT date.
   - **Same table elsewhere:** the companion paper prints the same table, titled "data volume: 2018A" (Osborn et al. 2018, Table 1, p. 4; https://arxiv.org/abs/1806.02585).
3. **Appendix B, "nightly median profiles"** (Figs B1–B5, pp. 18–22). Captions transcribed exactly, with the panel count I made from the rendered pages in brackets:
   - B1: "nights beginning 26th - 29th April, 22nd-26th July, 30th-31st October, 1st-2nd November, 10th-12th December 2016." [16 panels = 16 nights]
   - B2: "nights beginning 7th - 9th March, 12th -18th April, 4th - 9th May and 7th - 10th June 2017." [20 = 20]
   - B3: "nights beginning 2nd - 9th July, 3rd - 8th August and 4th - 9th November 2017." [20 = 20]
   - B4: "nights beginning 18th - 19th November, 29th - 30th November, 1st - 2nd December, 5th December, 8th - 18th December 2017." [18 = 18]
   - B5: "nights beginning 13th - 15th January, 18th - 19th January 2018." [5 = 5]
   - Total: **79 nights**, one panel each. Panels carry no individual date labels.
4. **Appendix A, profile sequences** (Figs A1–A6, pp. 12–17). Each night is a pair of time–height panels (ECMWF, SCIDAR). Captions transcribed exactly:
   - A1: "26th - 29th April, 22nd-25th July, 30th-31st October and 1st-2nd November 2016." [12 pairs = 12 nights]
   - A2: "10th -12th December 2016, 7th - 9th March and 12th - 17th April 2017." [12 = 12]
   - A3: "5th - 9th May, 8th - 10th June and 3rd - 6th July 2017." [12 = 12]
   - A4: "8th July, 3rd - 8th August and 4th - 8th November 2017." [12 = 12]
   - A5: "18th - 19th, 29th - 30th November 2017, 1st, 5th, 8th-13th December." [12 = 12]
   - A6: "14th - 17th December 2017 and 13th - 15th, 18th-19th January 2018." [**8 pairs, but 9 nights listed**]
   - **Copy-paste errors in the appendices:** the captions call these "the median for an individual night", although the panels are time sequences. The appendix texts say "all the stereo-SCIDAR nights at Cerro Paranal in 2016" although the figures run to 2018. Appendix A's text names "Figures A1, A2, A3 and A4" although there are six (p. 11).
5. **How the lists differ** (my comparison; dates are the printed day numbers):
   - In Appendix B but not in Table 1: 2017-05-04, 2017-06-07, 2017-07-02.
   - In Table 1 but in no appendix: 2017-11-20, 2017-12-03, 2017-12-04, 2017-12-06, 2018-01-16, 2018-01-17, 2018-01-20 to 2018-01-24.
   - In Appendix B but not in Appendix A: 2016-07-26, 2017-04-18, 2017-05-04, 2017-06-07, 2017-07-02, 2017-07-07, 2017-07-09, 2017-11-09, 2017-12-02 and 2017-12-18.
   - Every Appendix A night is also in Appendix B and in Table 1.
   - **Union:** 90 nights. **Table 1 ∩ Appendix B:** 76 nights. (Computed by enumerating the printed ranges.)
6. **"Night beginning" and UT:**
   - Fig. 6 (p. 7) shows "the night beginning 24th July 2016" on a "Time (UT)" axis from 0 to 10.
   - So night D appears to cover roughly 00–10 UT on date D+1. The figure starts at 0 UT, so whether D's evening hours before 00 UT are included is not visible. This is my reading of the axis, not a stated rule.
7. **Hourly matching:** "We compare the atmospheric parameters derived from the ECMWF model forecast for the hour with the median stereo-SCIDAR measurement from 2.5 minutes either side of the hour, ie a 5 minute sampling period. The stereo-SCIDAR has the dome contribution automatically subtracted." (§5.2, p. 4.)
8. **The validation set includes the calibration half:** "k is calculated by calibrating the integral turbulence strength from the model with the 50% of the stereo-SCIDAR data (selected at random), in this case k=6.0. The whole dataset (including the 50% calibration data) is used for the validation" (§4, p. 4).
9. **Table 3, "Parameter statistics" (p. 7), seeing rows exactly** (arcsec; no unit is printed for these rows):

   | Parameter | SCIDAR Q1 | Median | Q3 | Std. dev. | ECMWF Q1 | Median | Q3 | χν² |
   |---|---|---|---|---|---|---|---|---|
   | Seeing | 0.4800 | 0.6100 | 0.8700 | 0.0700 | 0.5200 | 0.6200 | 0.8100 | 1.3 |
   | Seeing (FA) | 0.3000 | 0.3400 | 0.4400 | 0.0600 | 0.3100 | 0.4100 | 0.5500 | 2.9 |
   | Seeing (Ground) | 0.3300 | 0.4200 | 0.6000 | 0.0700 | 0.3300 | 0.4500 | 0.6500 | 1.9 |

   - The standard deviation is "of the measurements over the 5 minute sampling period" (§5.7, p. 5).
   - **An inference, not stated:** the companion paper gives the SCIDAR median as 0.64″ (Q1 0.52, Q3 0.85) over all of release 2018A (Osborn et al. 2018, Table 2, p. 5). The SCIDAR column here differs, so O&S's Table 3 is probably computed over the hourly-matched samples rather than over all profiles.

### How the ECMWF values were produced

10. **Source data:** "publicly available data from ECMWF from the ERA5 catalogue … The data has 0.3degree spatial resolution and is only available for the models produced at 06:00 and 18:00 UT, with forecasts for every hour up to 19 hours. Here, we use the best case data, i.e. data that was produced at most 11 hours before (for example, 06:00+11 hours)." (§3.1, p. 3.)
    - §5.8 (p. 10) adds: "The data used is re-anaylsis data and we use the optimum (ie shortest) forecast time available."
    - The data came via MARS: "We also acknowledge ECMWF for access to the weather forecast data through the MARS access system." (Acknowledgements, p. 10.)
    - **ERA5 documentation, for comparison:** ERA5 HRES is 31 km, 0.28125°. Short forecasts are "run twice daily from 06 and 18 UTC, provide hourly output forecast steps from 0 to 18 hours (only steps 1 to 12 hours are available on the CDS disks)". On the CDS, "where single level and pressure level data are available, analyses are provided rather than forecasts". (https://confluence.ecmwf.int/display/CKB/ERA5%3A+data+documentation, Temporal frequency and Spatial grid.)
    - So O&S's "0.3°" is a regridding that the paper doesn't explain. Their "up to 19 hours" is plausibly the 19 outputs at steps 0–18; that is my reading.
11. **Levels:** "For the model levels, forecasts are provided at 137 levels" (§3.1, p. 3), and "We use the model level (137 vertical levels) forecast" (§7, p. 10). The pressure-level list in §3.1 is a description of what ECMWF offers, not what they used.
12. **Horizontal:** "To extract the parameters for the site of Cerro Paranal in the 0.3 degree grid … we linearly interpolate between the four nearest data points." (§3.1, p. 3.) No site latitude or longitude is given.
13. **Cₙ² model:** eq. 7 (p. 4) is Cₙ²(z) = k [80×10⁻⁶ P(z) / (T(z) θ(z))]² L(z)^{4/3} (δθ̄/δz)², with:
    - θ = T (P₀/P)^{R/c_p}, R/c_p = 0.286, P₀ = 1000 mbar (eq. 3);
    - L = √(2E / ((g/θ) δθ̄/δz)) (eq. 5) with E = S², where S is the vertical shear of u and v (eq. 6);
    - "a single value coefficient for the full atmosphere", k = 6.0 (§4, p. 4).
14. **Vertical grid:** "the ECMWF model is interpolated onto the same altitude grid as the stereo-SCIDAR (i.e. 250 m resolution from the observatory level to 25 km above the observatory level)" (§5.2, p. 4).
    - Fig. 5's caption shows that the quantity interpolated is the Cₙ² profile: "the ECMWF model turbulence profile was interpolated onto the same altitude grid as the stereo-SCIDAR profiles" (p. 6).
15. **Site height and relocation:**
    - Heights: "ESO Paranal observatory is located on the summit of cerro Paranal at an altitude of 2635 m above sea level. However … the altitude of the grid corresponding to Paranal is at 926 m (grid altitude)."
    - The fix: "we propose to take the ground layer from the grid altitude (926 m) to 1 km above the grid altitude (1926 m) and add that into the levels corresponding to the observatory altitude (2635 m to 3635 m). This ground layer must be interpolated to take into account the different altitude resolution of the model at the grid altitude and the observatory altitude." (§5.4, p. 5.)
16. **Split:**
    - "the free atmosphere seeing (h>1 km), the ground layer seeing (h<1 km)" (§5.7, p. 5);
    - "ground layer seeing (integrated from the ground to h=1 km)" (§5.7, p. 5);
    - Fig. 9(b): "free atmosphere only (h>1 km above observatory level or 3.6 km above observatory level)" (p. 9). The second "above observatory level" reads like a slip for "above sea level", since 2.6 + 1 = 3.6 km; that is my reading.
    - Fig. 1 (global map) uses "1 km above the model altitude" (p. 4), which is not the Paranal relocation.
17. **Paranal is the only calibration:** "It is not clear whether this normalisation is valid globally" (§7, p. 10).

### r₀→ε and wavelength

18. **Not in O&S 2018:** searching the PDF and HTML text for wavelength, λ, nm, r₀, Fried, 0.98, zenith and airmass finds no conversion and no wavelength.
    - "AOtools" is acknowledged (p. 10) without saying what it computed.
19. **The companion SCIDAR paper** (Osborn et al. 2018, MNRAS 478, 825; https://arxiv.org/abs/1806.02585, cited in O&S as "Osborn J., et al., 2018, MNRAS, submitted"):
    - eq. 1: r₀ = [0.423 (2π/λ)² cos(γ)⁻¹ ∫Cₙ²(h)dh]^(−3/5);
    - eq. 2: ε = 0.98λ/r₀ (§3, p. 3);
    - "We calculate the response functions for a monochromatic wavelength of 500 nm" (§2, p. 3);
    - "The parameters for all instruments are corrected for zenith angle" (§4, p. 5).
    - It lists λ as an input to the calculation but doesn't give its value for ε. It applies to the SCIDAR side only.

## Not stated in the paper

- **Dates:** which 83 of the 87 Table 1 days count as nights; whether "Days" are local evening or UT dates; and why Table 1 and the appendices disagree (items 2–5).
- **Hours:** which UT hours of each night were compared, and how many hourly pairs feed Tables 2–3.
- **Sample:** whether the ECMWF column of Table 3 uses only the hours matched to SCIDAR or every forecast hour of those nights. The text implies matched hours, but I couldn't find it stated.
- **Forecast steps:** the exact steps used. The paper says only "at most 11 hours" after the 06 or 18 UT run. It doesn't say whether step 0 was used or what happens at 06 and 18 UT.
- **The 0.3° grid:** how it was produced from the native ERA5 grid.
- **Interpolated fields:** which fields were interpolated horizontally (T, u, v, P, heights?), and how model-level heights were computed (geometric or geopotential).
- **Gradients:** the finite-difference scheme for δθ̄/δz and S, and what the overbar on θ̄ means in practice.
- **Unstable layers:** how layers with δθ/δz ≤ 0 (undefined L) were handled. Our D5 already notes this.
- **The 250 m grid:** the interpolation method (linear or logarithmic), whether bins are centres or edges, and how they were integrated.
- **The 926 m grid altitude:** how it was derived (bilinear orography? nearest point?).
- **Relocation:** how the relocated ground layer was "interpolated" in detail.
- **How k was fitted:** which statistic (ratio of medians, least squares on J?) and which random 50%.
- **Constants:** the value of g, and the site coordinates.
- **Seeing conversion:** r₀→ε, the wavelength, and any zenith or airmass handling for the model values.

## Recommended emulation with our data

**This is my recommendation, not the paper's.** Our Paranal store holds hourly ERA5 **analyses** on 29 pressure levels (1000–50 hPa, z t u v cc), for all hours from 2016-04 to 2018-01. It is a 5×5 grid of 0.25° points centred on (−24.75, −70.50), so it includes the four points around the site. An exact reproduction is impossible: we have analyses rather than 06/18 UT forecasts, 29 pressure levels rather than 137 model levels, a top near 20.6 km rather than 25 km above the site, and no SCIDAR timestamps. `reports/phase1_plan.md` already says this. The steps below get as close as our data allow, with the paper's own choices first (AGENTS.md "reproduce each paper with its own constants").

1. **Nights:**
   - **Primary:** the 79 Appendix B nights. They are explicitly "nights beginning", and the panel counts confirm them.
   - **Sensitivities:** Table 1's ranges read as nights beginning (87), and the union (90). Report all three; the spread shows how much the date ambiguity matters next to the ±0.1″ tolerance (D19).
2. **Hours:**
   - **Primary:** for night D, the on-the-hour UT times between local noon on D and noon on D+1 with the Sun below −18° at Paranal (our darkness code).
   - **Sensitivity:** Sun below −12°.
   - **Caveat:** SCIDAR averaged about 4.8 h a night, so full dark hours over-weight long winter nights. If per-profile SCIDAR timestamps can be obtained (from the authors or an archive; I didn't check where), use exactly those hours.
3. **Time:**
   - Use the ERA5 analysis valid at that hour, with no interpolation in time.
   - A closer emulation would need ERA5 model-level **forecasts** from MARS (06/18 UT runs, step = valid time − latest run, 0–11 h). That is a new download and would need [ASK].
4. **Horizontal:**
   - Bilinearly interpolate z, t and u, v on each pressure level from the four nearest points to the site (−24.63, −70.40; `configs/sites.yaml`), as O&S did, then compute Cₙ².
   - Interpolating meteorological inputs is not interpolating seeing, so the AGENTS.md rule still holds.
   - **Sensitivity:** compute Cₙ² per column, then bilinearly interpolate the Cₙ² profiles.
5. **Grid altitude:**
   - Take z_g as the bilinear ERA5 surface geopotential ÷ g at the site, and report it next to O&S's 926 m.
   - Run with our z_g (primary, consistent with our data) and with z_g = 926 m (sensitivity).
   - Drop pressure levels below z_g. The ERA5 documentation says values below the surface are extrapolated ("Values below the surface are there for convenience").
6. **Cₙ²:**
   - Eq. 7 exactly as printed, with 80×10⁻⁶, P in hPa, θ with P₀ = 1000 hPa and R/c_p = 0.286, E = S², and k = 6.0.
   - Unstable layers: D5's `zero`, with `abs` as a sensitivity. Count the firings.
   - Heights: geopotential height (AGENTS.md convention).
7. **Vertical grid:**
   - Interpolate Cₙ²(z) linearly onto h = 0, 250, …, 25 000 m above 2635 m.
   - Above our top level, set Cₙ² = 0, and log the missing range (about 20.6–27.6 km above sea level) and the bins it affects.
   - For h < 1000 m, add the relocated Cₙ²(z_g + h).
   - Integrate as Σ Cₙ² × 250 m. This bin rule is my choice, because the paper doesn't give one.
   - This equals D7's J(h) at h = 2635 m, apart from the grid discretisation. As a cross-check, also report the native-layer integral (our standard path).
8. **Split:** free atmosphere is h ≥ 1000 m above the observatory; ground layer is h < 1000 m, including the relocated layer; total is both.
9. **Conversion:**
   - ε = 0.98 λ/r₀ at λ = 500 nm, zenith. This is the companion paper's SCIDAR convention, applied to the model by assumption; it is already `OSBORN_SARAZIN2018` in `constants.py`, marked [check].
   - At 550 nm the values would be about 1.9% lower (ε ∝ λ^(−1/5)), which is under 0.012″ at these medians.
10. **Statistics:**
    - Pooled Q1, median and Q3 over all selected hours (not medians of nightly medians), for total, free atmosphere and ground layer.
    - Compare with the ECMWF column: 0.52/**0.62**/0.81, 0.31/**0.41**/0.55 and 0.33/**0.45**/0.65″. Pass if each median is within ±0.1″ (D19).
    - **Diagnostic only:** also report the k that would bring our total median to 0.62″. It shows how much the pressure-level smoothing weakens Cₙ² relative to 137 model levels. Changing k in any product is an [ASK].

**Possible corrections to `docs/RESEARCH.md` §3.3** (for Riley; not made here):
- The 250 m grid runs "from the observatory level to 25 km above the observatory level", not "from the site up to 25 km".
- Add "0.3°", "bilinear from the four nearest points", "at most 11 h after the run", and "the validation set includes the calibration 50%".
- Add that Table 1's day ranges sum to 87, not 83.

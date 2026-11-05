# DIY seeing monitor at Kongsberg: what a home-built DIMM takes and how accurate it would be

Ticket #27 (child of map #20; D44 item 7). Researched 2026-11-05 by the agent. Builds on `docs/research/seeing-measurements.md` (branch `research/seeing-measurements`), §3 of which covers commercial amateur monitors and Tokovinin 2023; that ground is not repeated here.

Sources are peer-reviewed papers read from their arXiv versions, plus the tools' own repositories and vendor pages. Every link below was loaded on 2026-11-05 and says what is cited, unless marked *[not reached]* or *[unverified]*. Numbers I worked out myself are marked *[my calculation]*. Forum posts are used only as leads and are labelled. Blocked from this cloud: IOPscience (so PASP), ADS, Cloudy Nights (HTTP 403), the CTIO staff pages (TLS failure / HTTP 503), and the GitHub API (repository pages and raw files were readable).

**Question.** Could Riley measure seeing at Kongsberg (59.67°N, 9.65°E) with their own telescope and camera as a do-it-yourself differential image motion monitor (DIMM)? What does it take (method, equipment, software, cost, effort), how accurate would it be, and would the result be good enough to check the forecast?

We don't know Riley's telescope or camera, so the equipment section gives the specs that matter and the values that work, and ends with the list of specs Riley should report.

## Short answer

- **Feasible, with caveats.** A DIMM is a small telescope (in practice ≥ 15–20 cm aperture), a two-hole mask, a small-angle wedge prism, a fast monochrome camera and a tracking mount. Professional DIMMs are built from the same class of gear: Meade LX200 and Celestron C11 telescopes, short-exposure cameras (Kornilov et al. 2007; Aristidi et al. 2014).
- **The hard parts are not the hardware but:**
  1. **the wedge prism.** It must deviate the light by only ~15–30″. I found no catalogue part that small: Edmund's smallest wedge deviates 0.5°. Separating the spots by defocusing instead, as some amateur and early DIMMs did, biases the result (Tokovinin & Kornilov 2007).
  2. **bias control in software.** That means noise subtraction (needs the camera's read noise and gain), exposure-time correction, a pixel scale measured on double stars, and a check on focus and spot quality.
- **Software:** nothing open, maintained and validated exists for a two-hole DIMM.
  - SAAO's `timDIMM` is BSD-3 but last changed in 2014 and is tied to its own hardware.
  - IAO Hanle's `RoboticDIMM` (Python, 12″ Meade, CMOS camera) has no licence file, was last changed in 2023, and reports no validation.
  - Rubin's `ts_dimm` is GPL-3 and is a control-system wrapper; the DIMM code it points to returns 404.
  - The closest validated, partly open alternative is **RINGSS**, Tokovinin's defocused-ring monitor. It runs on a 5-inch Celestron and a ZWO ASI290MM. Its profile-restoration code is BSD-3 (`soar-telescope/ringss_restore_profile`), and it was compared with Stereo-SCIDAR and the ESO MASS-DIMM at Paranal (Griffiths et al. 2024).
  - Writing our own DIMM reduction in Python is a modest job: the formulas and bias recipes are all published.
- **Accuracy:**
  - Statistical error ≈ 2–4% per 1-minute sample.
  - Instrumental biases can exceed 10% if uncontrolled. With careful control, ~10% absolute is the professional best case (Tokovinin & Kornilov 2007).
  - **The surface layer dominates the absolute error at 1–2 m height.** At Paranal in 2023, RINGSS at 1.5 m read a median seeing of 1.10″ while the DIMM on a 7 m tower read 0.75″: a mean ratio of 1.46 and a bias of +0.34″ (Griffiths et al. 2024; part of that is location, not height).
- **Fit for checking the forecast:** good enough for **night-to-night (or hour-to-hour) ranking**. Co-sited monitors at Paranal correlate at r = 0.70–0.83. **Not good enough for absolute values** of free-atmosphere or "observatory" seeing.
  - It would measure the seeing a backyard telescope at Kongsberg actually gets, including a local surface layer that no forecast model resolves.
  - With no professional monitor within ~2,600 km, its absolute scale can only be checked by internal consistency tests, not against a reference.

## Findings, each with its source

### 1. Method

- **Principle.** Two sub-apertures of diameter D, with centres a distance B apart, isolate two patches of the wavefront. The variance of the *difference* of their image positions is set by turbulence alone, because telescope shake and tracking errors move both images together.
  - Variances are taken parallel to the baseline (longitudinal, σ_l²) and perpendicular to it (transverse, σ_t²).
  - Source: Tokovinin & Kornilov 2007, "Accurate seeing measurements with MASS and DIMM", MNRAS 381, 1179, DOI 10.1111/j.1365-2966.2007.12307.x, https://arxiv.org/abs/0708.0195, §4.1. They cite Martin 1987, Sarazin & Roddier 1990 and Tokovinin 2002 for the relation.
- **Standard references.**
  - Sarazin & Roddier 1990 (A&A 227, 294) is the ESO DIMM paper. I could not open it: ADS is blocked and it is not on arXiv. It is cited here through the papers below.
  - Tokovinin 2002, "From differential image motion to seeing" (PASP 114, 1156) gives the modern coefficients and the noise and exposure biases. The journal (IOPscience) is blocked, and the only free copy found (an OCA teaching page) returned HTTP 503 and a reset *[not reached]*. Its equations are restated, with a typo corrected, in Tokovinin & Kornilov 2007, which I read.
- **From image motion to seeing** (Tokovinin & Kornilov 2007, eqs. 9–10; also Kornilov et al. 2007, eq. 6):

  ```
  σ²_{l,t} = K_{l,t} · (λ/D)² · (D/r₀)^{5/3}           σ in radians
  G-tilt (centroid) coefficients, b = B/D:
     K_l = 0.340 (1 − 0.570 b^{−1/3} − 0.040 b^{−7/3})
     K_t = 0.340 (1 − 0.855 b^{−1/3} + 0.030 b^{−7/3})
  ε₀ = 0.98 λ / r₀                                       λ = 500 nm by convention
  ```

  - Worked example from the paper: for b = 2.5, K_l = 0.1956 and K_t = 0.1270.
  - "A 10% error in the response entails a 6% error in seeing."
- **Z-tilt vs G-tilt coefficients.** Aristidi et al. (GDIMM, SPIE 9145, 91453G, 2014; https://arxiv.org/abs/1811.07561, eq. 2) use the Z-tilt coefficients K_l = 0.364 (1 − 0.532 b^{−1/3} − 0.024 b^{−7/3}) and K_t = 0.364 (1 − 0.798 b^{−1/3} + 0.018 b^{−7/3}).
  - Tokovinin & Kornilov 2007 (§4.2) show that the true response depends on the centroid window. A narrow window (radius about 1 λ/D) behaves more like a Z-tilt; a wide window (about 5 λ/D) more like a G-tilt.
  - For b = 2.5, the two sets give seeing about 7% (longitudinal) and 11% (transverse) apart *[my calculation]*. So the coefficient must match the centroid algorithm, and the choice should be recorded.
- **Wavelength.** By that relation, σ² (in radians) does not depend on λ, because r₀^{−5/3} ∝ λ^{−2}; r₀ = [0.423 (2π/λ)² J]^{−3/5} is Table 1 of Tokovinin & Kornilov 2007.
  - So a DIMM measures J, and seeing at 500 nm follows by putting λ = 500 nm into the formula, whatever the camera's passband *[my derivation; it ignores the propagation and chromatic effects in §4]*.
  - This fits the project convention: store J, report 500 nm at zenith.
- **Zenith angle.** ε_zenith = ε_measured · (cos z)^{0.6}. Source: Aristidi et al., eq. 1; Weinberger et al. 2026 (SPIE 14150, 141506R; https://arxiv.org/abs/2610.20143), eq. 1.
- **Exposure-time correction.** A finite exposure averages the image motion, so the seeing comes out *too small*.
  - **Interlaced exposures** (exposure t and 2t alternating): σ²(0) = σ²(t)^{1.75} · σ²(2t)^{−0.75} (Aristidi et al., eq. 8, coefficients "taken from the paper of Tokovinin (2002)"). Tokovinin & Kornilov 2007 eq. 13 gives an equivalent "modified exponential" recipe.
  - **Continuous video:** "an extrapolation to zero-exposure can be done from the variances of time-binned signal" (Tokovinin & Kornilov 2007, §4.5).
  - **Adjacent-frame correlation:** the correction is computed from the correlation between consecutive frames. Kornilov & Safonov 2011 ("Differential image motion in the short exposure regime", MNRAS, DOI 10.1111/j.1365-2966.2011.19604.x, https://arxiv.org/abs/1108.5681) also recommend using the *total* motion σ_l² + σ_t², which depends only weakly (< ±0.02) on wind direction. Averaging longitudinal and transverse seeing under strong wind smoothing "is biased and non-optimal".
  - The wind effect grows as (exposure)² and as D^{−2} (same paper, conclusions iii–iv). Short exposures and not-too-small holes both help.
- **Noise correction.** Each centroid has a noise variance from read noise R and photon noise:

  ```
  σ_c² = (1/I₀²) Σ (x_ij − c_x)² (R² + I_ij/G)          (Tokovinin & Kornilov 2007, eq. 15)
  ```

  - It must be computed per spot and subtracted from the measured differential variance *before* converting to seeing. A fixed "instrumental noise" in arcsec should not be subtracted afterwards.
  - Uncorrected noise makes the transverse seeing larger than the longitudinal (§4.6).
  - Read noise R and gain G must be known (Kornilov et al. 2007, §4.2.3).

### 2. Equipment: what matters, and values that work

| Spec | Why it matters | Values used by working instruments | Source |
|---|---|---|---|
| Sub-aperture D | Larger D means less noise and less wind smoothing (∝ D⁻²), but the defocus tolerance shrinks as D⁻². Small holes are not hurt by the outer scale (< 1% bias on variance for L₀ > 4 m) | 5 cm (Skinakas), 6 cm (GDIMM), 8 cm (MASS-DIMM on LX200; "typical ∼8 cm DIMM apertures are a good compromise"), 9 cm (PEARL), 10 cm (simulation baseline) | Kornilov et al. 2007 §4.1; Tokovinin & Kornilov 2007 §2.2; Aristidi et al. §3.1; Boumis et al. 2001 (https://arxiv.org/abs/astro-ph/0111022); Steinbring et al. 2013 (https://arxiv.org/abs/1305.5807) |
| Baseline B, ratio b = B/D | Sets K_l and K_t; holes must fit inside the clear aperture and miss the central obstruction and spider vanes | B = 14–25 cm, b ≈ 2–3.3 (e.g. 17/8 cm, 20/6 cm, 24.7/5 cm, 25/10 cm) | same as above |
| Telescope aperture | Must hold two holes: aperture ≳ B + D, with the obstruction smaller than ~B − D | ≥ ~15–20 cm in practice *[my calculation from the mask geometry]*; working DIMMs use 25–35 cm SCTs or RCs | Kornilov et al. 2007 Table 1 (Meade LX200 25 cm, C11 28 cm); Steinbring et al. (35 cm LX200) |
| Image separation | A wedge prism over one or both holes separates the two images *in focus* | ≈ 30″ per prism, opposite directions (GDIMM) | Aristidi et al. §3.1 |
| Focal length and pixel scale | Need ≥ 2 pixels per λ/D (Nyquist). λ/D = 1.7″ for 6 cm, 1.0″ for 10 cm; the centroid window should be ≥ 2.5 λ/D in radius | 0.32″/px in the D = 10 cm simulation; 0.52″/px at PEARL (D = 9 cm); ≈ 5 px across the Airy disc of a 10 cm hole (GDIMM, 7.8 m focal length with Barlow). With 2.9 µm pixels, 0.30″/px needs ~2 m focal length *[my calculation]* | Kornilov et al. 2007 §3.2; Tokovinin & Kornilov 2007 §4 and §5; Aristidi et al. §3.2 |
| Pixel scale calibration | The nominal scale is not good enough; the scale enters σ² squared | Measure on double stars of known separation (e.g. θ Ser 22.3″, Mizar 14.5″, Albireo 35″) | Kornilov et al. 2007 §4.2.1; Aristidi et al. §4 |
| Exposure time | Wind moves the turbulence V·τ during an exposure; at 20 m/s that is 2 cm in 1 ms and 10 cm in 5 ms *[my calculation]*, comparable to D | 1 ms (PEARL), 2.5 ms (Mt Shatdzhatmaz), 3–4 ms (GDIMM), 5–10 ms with interlacing (older CCD MASS-DIMMs) | Steinbring et al.; Kornilov & Safonov 2011; Aristidi et al.; Kornilov et al. 2007 |
| Frame rate and sample size | Relative error of the variance ≈ √(2/N). For 2% in seeing you need N > 1800 independent frames, so ≥ 30 Hz for a 1-minute sample | 30 Hz minimum; 90 fps full frame on a Prosilica; "up to 400 frames per second" with a 20–30-row window | Kornilov et al. 2007 §2.2; Kornilov & Safonov 2011 |
| Camera type | **Monochrome only.** Colour (Bayer) sensors "have large periodic errors caused by colour filters on pixels and therefore should be avoided". Low read noise, known gain, short-exposure capable. Rolling shutter is a "minor effect" for RINGSS; for a DIMM, put both spots on the same rows *[my inference]* | Prosilica EC-650 (7.4 µm, 11 e⁻); ZWO ASI290MM (2.9 µm, ~1 e⁻ read noise at high gain, QE 0.80) used by RINGSS; ASI462MM in a RINGSS copy | Kornilov et al. 2007 §3.2; Tokovinin 2021 §6 (https://arxiv.org/abs/2012.13734); uoa-fsoc/RINGSS README |
| Optical quality and focus | Defocus or other aberrations combine with scintillation and bias the result *either way*; keep spot Strehl > 0.5–0.6 and watch focus (spot separation drifts with focus) | Strehl > 0.5 (Wang et al. 2006 via TK07) or > 0.6 (Kornilov et al.); tolerance on spot-separation change ≈ 2.6″ for D = 10 cm, b = 2.5 | Tokovinin & Kornilov 2007 §4.4; Kornilov et al. 2007 §4.1, eq. 10 |
| Mount stability | Differential motion cancels shake, but shake smears spots within an exposure and can push them out of the region of interest | Region of interest 60–80 rows because of "telescope tube vibrations occurring at wind speed greater than ∼7 m s⁻¹"; PEARL could not hold the target reliably as winds approached 8 m/s; SHIMM used a portable windbreak | Kornilov & Safonov 2011; Steinbring et al. §2.3; Perera et al. 2023 §3 |
| Target stars | Brightness sets photon noise | V ≤ 2 preferred, ≤ 3 usable (SHIMM with 4.1 cm sub-apertures); faintest DIMM targets ~3 mag (Kornilov & Safonov); **Polaris** (V = 2) was the only target at PEARL | Perera et al. 2023, https://arxiv.org/abs/2303.00153, §3 and §5.2; Steinbring et al. §2.2 |

Notes on the table:

- **Prism-free tricks are biased.** Boumis et al. (Skinakas, a conference proceeding) separated the images by "slightly out of focus" instead of a wedge. Tokovinin & Kornilov 2007 (refereed) found that "a DIMM working always out-of-focus … will never measure the seeing accurately", because defocus plus scintillation biases the response by up to ±12% even at Strehl 0.91, and more with stronger defocus.
  - By Kornilov et al.'s eq. 10, a defocus large enough to separate two images by tens of arcseconds is far outside the ≈ 2.6″ tolerance *[my inference]*.
  - A forum post about a DIY "Hartmann mask + defocus" tool ("OpenMEI") is a lead only. The thread is blocked (HTTP 403), and I found no repository under that name *[unverified]*.
- **Wedge prisms.**
  - Edmund Optics' wedge-prism catalogue export showed only 0.5° nominal deviation at 12.5 mm diameter (https://www.edmundoptics.co.uk/f/PdfExport/12456). That is ~60× too much deviation and too small a diameter for a 5–8 cm hole.
  - A university report found by search (Tohoku, `astr.tohoku.ac.jp/~h-okita/report/dimm/wedgeprizm.pdf`, not loaded) reportedly specifies a custom 30″-apex BK7 wedge. It is a lead only.
  - Alcor System sells DIMM masks (Ø50/75/100) with a wedge prism, but shows no price (https://www.alcor-system.com/new/SeeingMon/DIMM_Complete.html).
- **Polaris at Kongsberg.** Polaris (Dec ≈ +89.37°) stays at altitude 59.0–60.3°. That is zenith angle ≈ 30.3° and airmass 1.16, so the zenith correction factor is (cos z)^{0.6} ≈ 1/1.09 *[my calculation]*.
  - A Polaris-only setup needs almost no slewing and very slow tracking, as at PEARL. The sky direction stays constant, which helps night-to-night comparison.
  - Brighter, higher stars (Vega, Capella, Deneb) transit at 69–76° altitude at Kongsberg *[my calculation from declinations]*.

**Specs Riley should report** so the setup can be judged:

1. **Telescope:** make and model; type (SCT, Newtonian, RC, refractor); clear aperture; native focal length; central obstruction diameter; spider vanes (number and orientation); focuser (manual or motorised; ASCOM?); any Barlow or reducer.
2. **Mount:** make and model; equatorial or alt-az; GoTo and guiding capability; periodic error if known; tripod or pier; payload margin.
3. **Camera:** make and model; sensor; **mono or colour**; pixel size; read noise and gain (vendor curves); global or rolling shutter; minimum exposure; maximum frame rate at a small region of interest (e.g. 128×64 px); bit depth; interface (USB 3?); cooling.
4. **Computer:** OS, USB 3, whether it can run unattended outdoors.
5. **Site:** where the telescope would stand (lawn, terrace, roof), height of the aperture above the ground, distance to the house and other buildings, trees, paved surfaces, heated windows or chimneys; view of Polaris and of the zenith.
6. **Practicalities:** dew heaters, power, a windbreak, whether the setup can stay out on a pier or must be set up each night.

### 3. Software: what exists today

| Software | What it is | Licence | Maintenance | Inputs | Validated? |
|---|---|---|---|---|---|
| **saltastro/timDIMM** (https://github.com/saltastro/timDIMM) | "Software used in operation the SAAO seeing monitor system": C, Python and Ruby scripts for star selection, mount control (Astro-Physics GTO900), cube grabbing, seeing, statistics, database | BSD-3-style, "Copyright (c) 2009, South African Astronomical Observatory" (LICENSE file read from raw.githubusercontent.com) | Last commit 2014-09-29; 3 stars | Its own camera and mount setup; hard-coded paths (e.g. `/home/massdimm/timDIMM/data/`) | No validation statement in the repository |
| **lsst-ts/ts_dimm** (https://github.com/lsst-ts/ts_dimm) | Rubin "DIMM CSC": a control-system component, not the measurement code | GPL-3.0 (LICENSE read) | 219 commits on `develop`; date not shown | Rubin's control system | — |
| **Rubin DIMM measurement code** | `dimm_tool` (measurement) and `preat` (converts to seeing), per Rubin's ops docs (https://obs-ops.lsst.io/Observatory-Control-System/EAS/DIMM/index.html) | — | — | — | The linked source `github.com/lsst-ts/ts_dimm_app` returned **404** (private or moved) *[not reached]* |
| **tsewangstanzin/RoboticDIMM** (https://github.com/tsewangstanzin/RoboticDIMM; the URL `…/AutomatedDIMM` given in the authors' ASI 2023 abstract, https://astron-soc.in/asi2023/abstractdetails/ASI2023_106, redirects here) | Python 3.6 robotic DIMM from IAO Hanle: acquisition, pointing correction with a webcam, offline seeing analysis of FITS cubes, web plots, Slack posts | **No licence file** found (404 on `main`), so no reuse rights | 167 commits; latest seen 2023-03-05 | Lucid Vision CMOS camera (Arena SDK), Meade LX200 GPS 12″, custom wedge prism and mask (per the abstract) | README cites Sarazin & Roddier and Tokovinin 2002 but reports no comparison with a reference; the abstract reports "a few nights" of data |
| **GDIMM acquisition** (Aristidi et al.) | C++/Qt, real-time seeing and θ₀ | Not published | — | Prosilica camera, AP900 mount | Compared with the GSM at Calern ("a small negative bias", shapes similar) |
| **SHIMM** (Perera et al. 2023) | Shack–Hartmann variant of the DIMM | No public repository found | — | Celestron 9.25″, Point Grey Blackfly (2 ms, 30 Hz, 0.71″/px), lenslet array | Compared with Stereo-SCIDAR at La Palma; seeing generally higher, attributed to local ground turbulence (MNRAS 520, 5475) |
| **RINGSS restoration** (https://github.com/soar-telescope/ringss_restore_profile) | Python scripts restoring turbulence profiles from RINGSS ring-image statistics, "derived from" Tokovinin's code | BSD-3-Clause | 32 commits, no releases | `.stm` statistics files, `par-*.json` site and telescope parameters, a star catalogue, `zmat.json` (empirical, optics-dependent) | The instrument (not this repository specifically) is validated by Griffiths et al. 2024 (below) |
| **uoa-fsoc/RINGSS** (https://github.com/uoa-fsoc/RINGSS) | Acquisition and processing for a RINGSS copy (ZWO ASI462MM, QHY QFocuser via ASCOM); "many of these scripts have been written by" Tokovinin | **No licence file** (404), so no reuse rights | 9 commits | Parameter file, star catalogue, Windows Python paths | None stated |
| **Tokovinin's original RINGSS code** | "experimental software which is not yet ready for public distribution" (IDL; Tokovinin 2021, Data availability) | — | — | — | — |
| **Alcor DIMM software** | Manual and automatic DIMM, text and TCP output | Commercial | Vendor | Alcor hardware | No validation on the vendor page |
| **SharpCap Seeing Monitor**, **Alcor Cyclope** | Relative sharpness score; single-aperture Polaris monitor | Commercial | — | — | Not arcsec-validated (`seeing-measurements.md` §3). Weinberger et al. 2026 say Cyclope "has not yet been fully validated against other standard sensors" and is "sensitive to vibrations" because it is not differential |

- **Verdict on software:** no open DIMM package is maintained and validated against a professional monitor.
- The algorithm is short and fully published (§1). Our own Python reduction is the practical route: per-frame centroids, the eq. 15 noise subtraction, variances, K coefficients, exposure correction from adjacent-frame correlation or time binning, and the zenith correction. Each equation would get a known-answer test, as AGENTS.md requires.
- Acquisition can use the camera vendor's SDK (the uoa-fsoc copy uses the `zwoasi` Python binding; its licence was not checked).

### 4. Accuracy

**Statistical**

- About 2% in seeing for 1800 independent frames, i.e. 1 minute at 30 Hz. Frames are partly correlated and seeing is non-stationary, so the real error is larger (Kornilov et al. 2007 §2.2).
- SHIMM quotes 3–5% for N ≈ 300–1500 (Perera et al. §4.1).

**Instrumental biases** (from Tokovinin & Kornilov 2007, §4–5, unless noted)

- **Exposure time:** biases seeing low. "Short (e.g. 5 ms) exposures reduce the bias, but do not eliminate it completely." At 2.5 ms the correction (their relative wind term) was < 0.015 for 90% of the time on Mt Shatdzhatmaz (Kornilov & Safonov 2011).
- **Noise:** biases seeing high, mainly under good seeing or for faint stars. It is removable if R and G are known.
- **Aberrations plus propagation:** with spot Strehl > 0.5, the bias stays "within ±12%". Turbulence high in the atmosphere is also under-measured through saturation; "a seeing of 1″ coming from 10 km could be measured … with a bias of 0.83".
  - The response to near-ground turbulence is robust: "tolerant to aberrations … provided that the centroid calculation uses a large enough radius, > 2.5λ/D". That matters at Kongsberg, where low turbulence probably dominates *[expectation, not measured]*.
- **Centroid algorithm:** a threshold of 0.1 gave about +10% in K.
- **Coefficient choice:** Z-tilt vs G-tilt differ by ~7–11% in seeing *[my calculation, §1]*.
- **Pixel scale:** must be measured on double stars. For the related pupil magnification, Kornilov et al. require ±3%.
- **Colour sensors:** "large periodic errors" (Kornilov et al. 2007).
- **Best case:** "Seeing measurements with DIMM and MASS can reach absolute accuracy of ∼10% when their biases are carefully controlled" (abstract). Agreement between two DIMMs is "a necessary, but not sufficient condition" for accuracy (§5).
- **The definition itself:** Tokovinin 2023 ("The Elusive Nature of 'Seeing'", *Atmosphere* 14, 1694, DOI 10.3390/atmos14111694; abstract via the DOAJ API, MDPI blocked) adds that seeing "cannot be measured with arbitrary accuracy". He names "a substantial role of the highly variable surface layer, and a potential bias caused by the air flow in the immediate vicinity of the seeing monitors".

**Height above ground: the dominant term for a backyard monitor**

- **Paranal 2023 campaign** (Griffiths et al. 2024, MNRAS, DOI 10.1093/mnras/stae434, https://arxiv.org/abs/2402.09144, Tables 1–2):

  | Instrument | Height | Median seeing |
  |---|---|---|
  | RINGSS | ~1.5 m on a pillar | 1.10″ |
  | 24hSHIMM | ~2 m | 0.89″ |
  | ESO DIMM | 7 m tower | 0.75″ |
  | Stereo-SCIDAR | 5 m axis | 0.76″ |

  - RINGSS vs DIMM: r = 0.76, bias +0.34″, mean ratio 1.46.
  - RINGSS vs Stereo-SCIDAR: r = 0.70, bias +0.40″, ratio 1.59.
  - DIMM vs Stereo-SCIDAR: r = 0.83, bias +0.02″, ratio 1.04.
  - The authors attribute the difference to "local turbulence effects" and lower height. Part of it is location: the old DIMM tower area had a 2010–2015 median of 0.98″, against 0.71″ for the 2016 DIMM.
- **La Palma:** SHIMM on the INT roof read more ground-level turbulence than Stereo-SCIDAR, "likely … local turbulence at the site of the SHIMM … generated by heating and local wind–shear effects caused by the building itself, or turbulence within the closed telescope tube" (Perera et al. 2023 §5.1).
- **Racine 2005:** surface-layer blur decreases with a 3.5 m scale height over instruments 1–30 m above ground (RESEARCH §2, abstract index only).
- **Muztagh-ata:** night-time Cₙ² measured by sonic anemometers at 5 heights on a 30 m tower decreases with height as about h^{−0.48} (Gu et al. 2024, https://arxiv.org/abs/2410.21347, abstract).
- **Dome C:** three DIMMs at different heights were used as a surface-layer profiler (Aristidi et al. 2009, https://arxiv.org/abs/0904.2982, abstract). It is an extreme site.
- **Ali (Tibet):** a 3 m rooftop and a 5 m tower gave "no noticeably different seeing" (RESEARCH §6.1). So the size of the effect is site-specific.
- **What this means for Kongsberg:**
  - A DIMM at 1–2 m will read worse seeing than a professional DIMM at 5–8 m would at the same spot, by an amount that changes with wind, ground cooling and nearby buildings or trees.
  - That is also the seeing Riley's own telescope experiences, so for Riley's observing it is the right quantity.
  - For checking the *model's* seeing it is a confound. Our physics has a separate, still-open ground-layer term (RESEARCH §4.7, open decision), and the forecast models resolve nothing in the lowest metres.

**How it could be checked or calibrated without a reference monitor nearby**

- **Internal consistency:**
  - longitudinal vs transverse seeing (GDIMM: correlation 0.88; a systematic t > l signals unsubtracted noise, per Tokovinin & Kornilov §4.6);
  - interlaced t / 2t exposures, or binning, to check the exposure correction;
  - spot Strehl and separation to watch focus;
  - an artificial-star test for pattern noise (Kornilov et al. Fig. 6);
  - repeated pixel-scale measurements on double stars.
- **Two-height test:** run the same monitor at two heights (e.g. 1 m and on a ladder or terrace at 3–4 m) on stable nights to measure the local surface-layer gradient. This is the Dome C method in miniature *[suggestion]*.
- **Against a professional DIMM:** there is none within ~2,600 km (`seeing-measurements.md` §5). Carrying the monitor to one is the only real absolute calibration, and it would cost money and travel ([ASK]).
- **Against Riley's own long-exposure star FWHM:** a consistency check only. Delivered FWHM includes optics, focus and guiding (`seeing-measurements.md` §2).

### 5. Cost and effort

- **To buy or make (assuming Riley already owns a ≥ 15–20 cm telescope, a tracking mount and a mono planetary camera):**
  - a two-hole mask: cut or 3D-printed, cheap;
  - one or two **custom small-angle wedge prisms**: the uncertain item, see §2. Price not found;
  - dew heaters, a windbreak, and possibly a monochrome camera if Riley's is colour.
  - Prices of these items were not researched in detail *[unverified]*.
- **The RINGSS route** needs different parts: a 10–15 cm telescope, an IMX290/462-class mono camera, a focal-reducer lens chosen to give the right spherical aberration, and ideally a motorised focuser. Tokovinin's prototype was a Celestron NexStar SLT-130 with an ASI290MM, and he calls the hardware "relatively inexpensive, within the reach of an amateur astro-photographer" (Tokovinin 2021 §6 and §8). The software is harder to adopt: restoration is BSD-3 but needs instrument-specific weights and a `zmat.json` matrix.
- **Commercial:** an Alcor DIMM or Cyclope, or the micro-Cyclope (`seeing-measurements.md` §3), costs money ([ASK], D44 item 7). Cyclope is not differential and not yet validated (Weinberger et al. 2026).
- **Software effort:** writing and testing our own DIMM reduction plus acquisition is roughly a ticket-sized coding job *[estimate]*.
- **Data rate:** a 128×64 px 8-bit region of interest at 200 fps is 1.6 MB/s, about 6 GB per hour if raw frames are kept *[my calculation]*. Better to reduce on the fly and keep centroids and fluxes.
- **Per-night setup** *[estimate, not from a source]*:
  - set up and polar-align, or uncover a pier: 15–30 min;
  - focus and check spot quality on a bright star: 10 min;
  - pixel-scale check on a double star: once per setup change;
  - then unattended 1-minute samples for as long as it's clear.
  - A permanent pier would cut this to minutes. The telescope also needs time to reach outside temperature (not quantified here).
- **Season:** at 59.7°N there is no astronomical darkness around midsummer. MASS-DIMM measurements in twilight have been made, and "characteristics of optical turbulence don't change significantly in transition between day and night" (Safonov 2011, https://arxiv.org/abs/1101.2351, abstract). So bright-star DIMM work in summer twilight is plausible *[unverified for Kongsberg]*.
- **Weather limits:** professional monitors stop above 80–85% relative humidity or in strong wind (`seeing-measurements.md` §1). Kongsberg nights are often humid *[expectation]*, so dew control matters and usable hours will be a subset of clear hours. Log every excluded hour (AGENTS "no silent fixes").

### 6. Fit: would it check the forecast?

- **Night-to-night or hour-to-hour ranking: yes, plausibly.**
  - Well-run small monitors at the same site correlate at r = 0.70–0.83 with each other and with Stereo-SCIDAR (Griffiths et al. 2024). That leaves room to see whether a forecast's ranking carries skill.
  - Expect the forecast-vs-DIMM correlation to be much lower. ERA5-based *total* seeing at Paranal correlated only at r = 0.30 with measurements (RESEARCH §1).
  - With ~30 clear nights, a rank correlation has a standard error of roughly ±0.2 (1/√(n−3)) *[my calculation]*. A season of Kongsberg clear nights is needed before drawing conclusions.
- **Absolute values: no.**
  - The instrument is uncertain by ~10% at best and more for a first build.
  - The unknown local surface layer at 1–2 m can plausibly add tens of percent (Paranal: ×1.46 between 1.5 m and 7 m).
  - There is no reference to calibrate against.
  - It could, however, constrain the size of our ground-layer term at a typical backyard site, which is exactly what a user at Kongsberg cares about.
- **Recommendation:** treat a DIY DIMM as a **relative, local check of the forecast track** (and of the ground-layer treatment), never as validation of absolute seeing. ESO Paranal (D28/D44) stays the absolute reference.

## Verdict

- A two-hole DIMM on Riley's telescope is feasible if the telescope is ≥ 15–20 cm, the camera is monochrome and fast, and a small-angle wedge prism can be sourced.
- The method is mature and fully published. The software would be ours (no maintained, validated open DIMM package exists).
- The numbers would be good for ranking nights and hours and for measuring the local ground layer, and poor as absolute seeing.
- If the prism is a problem, or Riley's telescope is small (10–15 cm), RINGSS is the better-validated amateur-hardware alternative, at the cost of harder software.
- A commercial monitor remains an [ASK] option, but Cyclope-type single-aperture units are less trustworthy than either.

## Open questions for Riley

1. **Equipment:** please report the specs listed at the end of §2. The most decisive are aperture and obstruction, mono or colour camera, frame rate at a small region of interest, and mount type.
2. **Spend [ASK]:** are you willing to buy (or commission) a small-angle wedge prism, or a 10–15 cm telescope and focuser for a RINGSS-style build? Neither price is known yet.
3. **Placement:** can the telescope stand on open ground away from the house, ideally on a pier? Could you also do occasional two-height runs (ground and terrace or roof edge)?
4. **Scope:** is the goal (a) a check of the forecast ranking at Kongsberg, (b) your own "what will my telescope see" number, or (c) calibrating the ground-layer term? (a) and (b) are within reach; (c) needs many nights and the two-height runs.
5. **Ticket:** if yes, the next step is a coding ticket (acquisition plus reduction, with known-answer tests for eqs. 9, 10 and 15 and the exposure correction) and a decision-log entry. Our own measurements would be a new seeing-measurement source under AGENTS.md ([ASK], D44/D45).

## What I could not verify

- **Sarazin & Roddier 1990 and Tokovinin 2002 originals:** not opened (ADS and IOPscience blocked; the OCA copy returned HTTP 503). Their equations are taken from Tokovinin & Kornilov 2007 and Kornilov et al. 2007, which restate them (TK07 notes a corrected typo in Tokovinin 2002's eq. 13). Riley could fetch both PDFs into `papers/`.
- **Tokovinin 2023:** abstract only (MDPI blocked).
- **Tokovinin's RINGSS pages** (ctio.noirlab.edu/~atokovin/profiler/): TLS failure and HTTP 503 *[not reached]*.
- **Rubin `ts_dimm_app`:** 404. **OpenMEI:** forum lead only, no repository found. **RoboticDIMM (Hanle):** its reduction script could not be read (raw file 404), so whether it subtracts noise and corrects exposure time is unchecked.
- **Wedge prisms:** no catalogue item near 15–30″ found; price unknown.
- **Licence of the `zwoasi` binding:** not checked.
- **Racine 2005:** abstract index only (not on arXiv).
- **Kongsberg specifics** (humidity, wind, usable hours): not measured; stated as expectations.
- **Prices and setup times:** estimates, not sourced.

# Windward and lee seeing: what the literature says about terrain-driven turbulence

Ticket: #28 (child of map #20). Researched 2026-11-05 by the agent. Every link below was loaded on 2026-11-05 and says what is cited, except where marked. arXiv versions were read in full as PDF text; for papers whose publisher pages are blocked from this cloud (IOP, AMS, AGU, A&A/EDP, OUP all returned 403 or a bot challenge), only the abstract was read, through the OpenAlex API record of the DOI (`https://api.openalex.org/works/doi:<DOI>`). Those are marked *[abstract only]*. *[inference]* marks my own reasoning, not a source's claim.

**Question.** Is there published evidence that seeing differs systematically between the windward and lee sides of mountains and ridges, and what could flag it from forecast or reanalysis data? Riley wants the site fine enough to show windward/lee differences, but our method (RESEARCH §5) varies seeing with height only, so it can't produce them (D43 item 8). The ticket asks for: evidence; indicators (relative wind direction, Froude number, Richardson number, gravity-wave breaking, terrain roughness/slope), each with whether it's been tested against seeing; the horizontal and vertical scales needed, and whether 2.5–13 km forecast models or ERA5 can represent them; and a verdict for F2 or later.

## Short answer

- **Evidence: yes, but site by site, not as a general rule.** At several observatories, measured seeing depends strongly on wind direction:
  - Paranal: the surface layer is strongest with NNE and SSE winds, which ESO attributes to air blown over nearby summits.
  - Mauna Kea 13N: the site sits in the summit ridge's wake when winds are easterly.
  - Javalambre: ~1″ with N/NE winds against ~0.6″ otherwise.
  - Lenghu, Antarctica and La Palma show the same kind of dependence.

  The effect sits mostly in the lowest tens to hundreds of metres, and it is often mixed up with domes, platform edges and buildings, which also make "seeing roses" (seeing binned by wind direction). The sign isn't fixed: the lee isn't always worse. On the one night with a high-resolution profile at Mauna Kea, looking downwind into the expected wake gave the *better* ground layer.
- **Mesoscale models (Meso-NH, MAR) reproduce terrain-driven horizontal structure** in Cₙ², but only at 0.1–1 km grid spacing. Coarser runs got it measurably worse (Dome C: 100 km vs 1 km; Paranal: 500 m vs 100 m).
- **Indicators tested against seeing:**
  - Relative wind direction: only as *measured local* wind at individual sites.
  - Richardson number: only as a *measured* near-surface temperature gradient (Dome A). It is also built into the O&S Cₙ² model we already use.
  - Surface slope (katabatic flow): Antarctica only, with balloon and model support.
  - Froude number, gravity-wave breaking diagnostics and DEM roughness statistics: **I found no test against seeing.**
  - Gravity-wave activity has been tied to radar Cₙ² (monthly means, Colorado/Alaska).
  - Aviation mountain-wave turbulence algorithms built from model wind plus terrain are verified against aircraft eddy-dissipation rates, not against optical turbulence.
- **Scale:** the documented effects live at 0.1–1 km horizontally (wakes, rotors, sub-rotors) and 10–500 m vertically. Lee waves have wavelengths of ~5–15 km.
  - *[inference]* With the ~8-grid-length effective resolution measured for IFS, MEPS (2.5 km) resolves features of ~20 km, ICON-EU ~50 km, IFS 9 km ~70 km, GFS ~100 km and ERA5 ~250 km.
  - None of them resolves wakes or rotors. Only MEPS comes close to the longest lee waves.
- **Verdict: research-grade only; not supported for F1 or F2 as a seeing term.**
  - Nothing in the literature gives a windward/lee correction that transfers between sites.
  - A qualitative "mountain-wave / lee turbulence possible" flag built from model wind plus a DEM could be tried later. Its only precedent is in aviation, it has never been tested against seeing, and it would need our own validation against site DIMM data with wind records.

## Findings, each with its source

### 1. Evidence from measurements

**Paranal (ESO)**
- **Seeing roses:** Sarazin, Melnick, Navarrete & Lombardi 2008, "Seeing is Believing: New Facts about the Evolution of Seeing on Paranal", *The Messenger* 132, 11–17 (https://www.eso.org/sci/publications/messenger/archive/no.132-jun08/messenger-no132-11-17.pdf). ESO's own magazine, not peer-reviewed.
  - They colour-code the Paranal wind rose by the gap between DIMM seeing and UT1 image quality, which measures the surface layer.
  - "The discrepancy is seen to be strongest when the wind comes from the NNE and from the SSE".
  - They suggest "the bad seeing occurs when the wind blows warm turbulent air from nearby summits along the Atacama fault … over the top of the mountain".
  - Conclusions: "The surface layer is strongest when the wind blows from the NNE and from the SSE"; and "Close attention must be paid to the local orography".
- **Recent confirmation:** Griffiths et al. 2024, *MNRAS* (DOI 10.1093/mnras/stae434; https://arxiv.org/abs/2402.09144), §3.5.
  - ESO's archive of the 2016 DIMM shows "a clear increase in median seeing for north-easterly and south-easterly winds for all pointing angles".
  - They attribute some of the direction-dependent bias to instruments "near to the edge of the platform … air from the ground level will be driven up the mountain".
  - The SCIDAR vs MASS-DIMM comparison, both raised away from the edges, "has no identifiable dependence on wind direction".
  - They cite Sarazin et al. 1990 for wakes "produced downwind of large telescope structures". So at Paranal, terrain, platform and buildings all play a part.

**Cerro Tololo**
- Els et al. 2009, "Four years of optical turbulence monitoring at CTIO", *PASP* (DOI 10.1086/605450; https://arxiv.org/abs/0906.3665).
- Ground-layer "seeing roses" (30° bins) show "a seeing bias under northerly winds" for the CTIO DIMM but not for the TMT MASS-DIMM next to it. They trace it to the telescope dome.
- **A caution:** a direction-dependent excess in one monitor can be its own enclosure, not the mountain.

**Mauna Kea 13N and the TMT sites**
- **13N wake:** Els et al. 2009, "TMT Site Testing VI: Turbulence Profiles", *PASP* (DOI 10.1086/599384; https://arxiv.org/abs/0904.1865), §4:
  - "As 13N is located approximately 150 m below the summit ridge of Mauna Kea, it falls below the wake region when winds are coming from eastern directions, as reported in Skidmore et al. (2009)."
  - By contrast, the Chilean sites sit on summits, and Tolonchar's equipment is on the upwind (NW) edge of its plateau, so "the air above that location resembles closely the free air flow".
  - The paper concludes that "the topography and surface properties of the sites dominate the optical TS over the lowest hundred meters above ground".
- **Upwind terrain and higher layers** (same paper, §7):
  - At Armazones, a higher range lies in the prevailing wind direction. "We speculate that these orographic features cause the onset of waves, driving the TS [turbulence strength] at these altitudes" (the 0.5–2 km MASS layers).
  - Summary: "orographic features and surface energy properties on scales of tens of km are important drivers for the turbulence strength at altitudes below the tropopause".
  - This is stated as speculation, not tested.
- **Skidmore et al. 2009, TMT Site Testing V**, *PASP* 121, 1151–1166 (DOI 10.1086/644758) *[abstract only; IOP blocked]*. The abstract says the seeing "is discussed in terms of the geography and meteorological conditions at each site". I couldn't read its wind-direction analysis directly.
- **One night of profiles:** Lai, Withington, Laugier & Chun 2019, AO4ELT6 proceedings (https://arxiv.org/abs/1912.02680), §4. CFHT's multi-WFS profiler gave ~10 m vertical resolution on one night (2012-12-12).
  - They expected a good ground layer "looking into the wind" and wake turbulence looking downwind. "What we found was the exact opposite."
  - A layer ~200 m up appeared while looking upwind. Later, "no sign of wake turbulence".
  - The explanation (air splitting around Maunakea and reconnecting in vortices over the summit) is a private communication, not a result.
  - One night, conference paper: evidence that the windward/lee sign isn't obvious, not a statistic.

**La Palma**
- **Caldera:** Haslebacher et al. 2022, *A&A* 665, A149 (https://arxiv.org/abs/2208.04918).
  - "The convex profile of the Caldera de Taburiente directs air flow around the peak" (§3.3, citing McInnes & Walker 1974).
  - "Seeing on La Palma is mostly defined by surface winds which are highly perturbed by the nearby caldera" (§6, citing Vernin & Muñoz-Tuñón 1994). They give this as the reason ERA5 seeing fails there.
- **Model study:** Masciadri, Vernin & Bougeault 2001, *A&A* 365, 699–708 (DOI 10.1051/0004-6361:20000050) *[abstract only; aanda.org returned 403]*. It used Meso-NH over Roque de los Muchachos. The abstract says 3D simulations show "the horizontal distribution of the optical turbulence is not necessarily uniform, especially in the first 10 km above the ground".
- **Not about direction:** Lombardi et al. 2007, *PASP* (DOI 10.1086/513079; https://arxiv.org/abs/astro-ph/0702570) relates TNG seeing only to wind *speed* ("seeing deteriorates when wind speed is lower than 3.3 m s⁻¹"). Its wind-direction tables aren't related to seeing.

**Sierra de Javalambre (Spain)**
- Moles et al. 2010, *PASP* (DOI 10.1086/651084; https://arxiv.org/abs/0912.3762), from 16,542 DIMM–wind pairs.
- "Only for N and NE directions the seeing increases to near 1″. For all the other directions of the wind rose the typical value is ∼0.60″." N–NE winds occur less than 10% of the time.
- No physical cause is given.

**Lenghu (Tibetan Plateau)**
- Deng et al. 2021, *Nature* 596, 353–356 (DOI 10.1038/s41586-021-03711-z; https://pmc.ncbi.nlm.nih.gov/articles/PMC8373612).
- The site is "at a local summit on Saishiteng Mountain". "The median seeing is below 0.7 arcseconds between wind directions of 255° and 324°" (the prevailing direction is ~280°), plotted in Extended Data Fig. 3.
- No values for other directions in the text, and no orographic explanation.

**Antarctica (slope-driven katabatic flow): the clearest terrain-plus-flow case**
- **South Pole, measured:** Marks et al. 1999, *A&AS* 134, 161–172 (DOI 10.1051/aas:1999100) *[abstract only]*.
  - 15 balloon flights show "a highly turbulent boundary layer (0–220 m)" with a mean seeing of 1.86″, of which the free atmosphere was 0.37″.
  - "The boundary layer winds are of katabatic origin", so seeing could be better at Domes A and C, "where there is little or no katabatic wind".
- **Slope and constancy:** Marks 2002, *A&A* (DOI 10.1051/0004-6361:20020132; https://arxiv.org/abs/astro-ph/0112068).
  - The South Pole sits on a slope of ~1 in 10³, which drives an inversion wind of just over 5 m s⁻¹ with directional constancy ~0.8.
  - At Dome C, "the terrain is almost perfectly flat, and the inversion wind is negligible".
  - Measured afterwards: Dome C's surface layer is ~30–36 m (Agabi et al. 2006, RESEARCH §2), against ~220 m at the Pole.
- **Model maps:** Swain & Gallée 2006, *PASP* 118, 1190–1197 (DOI 10.1086/507153) *[abstract only]*.
  - The MAR regional climate model, nested in ECMWF analyses, quantifies boundary-layer height and seeing "in terms of the surface wind speed".
  - Saunders et al. 2009, *PASP* 121, 976 (https://arxiv.org/abs/0905.4156), summarises their maps: Dome F 18.5 m, near Dome A 21.7 m, Dome C 27.7 m. "The katabatic ridge is offset from the topographic ridge, in the direction of the lower gradient", and at Dome A itself the predicted thickness is over 30 m.
  - So the best spot is set by the flow, not by the highest point.

**Free atmosphere: gravity waves and Cₙ²**
- **Radar:** Nastrom, Gage & Ecklund 1986, *JGR* 91, 6722–6734 (DOI 10.1029/JD091iD06p06722) *[abstract only; AGU blocked]*. MST radar at 4–20 km, Platteville (Colorado) and Poker Flat (Alaska):
  - "During certain periods, Cₙ² also depends on other variables such as boundary layer inversions and gravity wave activity."
  - "Monthly mean values of Cₙ² correlate more closely with an indicator of the intensity of gravity wave activity than with wind speed or the coarse-scale wind shear."
  - The abstract doesn't say how the indicator is defined, or whether the waves were orographic. Platteville lies east of the Rockies, but that link is *[inference]*.
- **Balloons:** Coulman, Vernin & Fuchs 1995, *Applied Optics* 34, 5461 (DOI 10.1364/AO.34.005461) *[abstract only]*. Balloon soundings (Canaries, France, Chile) show that thin "seeing layers" form through hydrodynamic instability "perhaps engendered by the propagation of buoyancy (gravity) or other waves". This is a mechanism, not a windward/lee mapping.
- **Aircraft:** Strauss et al. 2015, *QJRMS* 141, 3207–3225 (DOI 10.1002/qj.2604; https://pmc.ncbi.nlm.nih.gov/articles/PMC4810356/). Airborne in-situ and radar data over the Medicine Bow Mountains (T-REX era):
  - EDR reached 0.50–0.77 m^(2/3) s⁻¹ (severe) inside lee rotors, and ~0.25 in mid-tropospheric wave breaking ~1600 m above the summit.
  - Turbulence was light upstream of the peak.
  - Sub-rotors have length scales of 500–1000 m.
  - This is mechanical turbulence (EDR), not Cₙ². I found no paper that measured Cₙ² or seeing inside a documented rotor or breaking lee wave.
- **Pilot reports:** Wolff & Sharman 2008, *J. Appl. Meteor. Climatol.* 47 (DOI 10.1175/2008JAMC1799.1) *[abstract only; AMS blocked]*. Twelve years of PIREPs show moderate-or-greater turbulence maxima "over mountainous regions in the west" of the US, at 18,000–60,000 ft.

### 2. Evidence from mesoscale models

- **Meso-NH at ESO sites (MOSE):**
  - **Why GCMs fail near mountains:** Masciadri, Lascaux & Fini 2013, MOSE I, *MNRAS* (DOI 10.1093/mnras/stt1708; https://arxiv.org/abs/1309.6775):
    - "GCMs are not reliable in the low part of the atmosphere particularly in proximity of mountain regions because of their too low horizontal resolution and a too smooth orography" (citing Masciadri & Garfias 2001, Masciadri 2003, Hagelin et al. 2010).
    - Hydrostatic models below ~10 km grid spacing distort "the spectrum of the gravity waves, particularly in proximity of mountain regions".
    - Two-way nesting is used so that gravity waves "triggered by the interaction of the atmospheric flow on the Chilean coast" reach the free atmosphere above the summits.
    - Below 5 km a.s.l., "where the orographic effects are more evident", model wind direction has biases of ~20° and RMSE up to 60°.
    - They note that surface wind direction "is one of the atmospheric parameters that are more frequently and easily correlated to the local seeing characteristics".
  - **Grid spacing at the surface:** MOSE II, *MNRAS* (DOI 10.1093/mnras/stt1803; https://arxiv.org/abs/1309.6774). Going from 500 m to 100 m "definitely and substantially improves the model performances", with near-surface wind speed improving by "around 50%".
  - **Setup:** the operational setup (Masciadri et al. 2017, RESEARCH §3.6) is 10 → 2.5 → 0.5 km with 62 levels, the first at 5 m.
- **Mt Graham:** Hagelin, Masciadri & Lascaux 2011, *MNRAS* 412, 2695 (https://arxiv.org/abs/1105.2667). Earlier Meso-NH work "was proved to be sensitive to orographic effects".
- **Dome C:** Lascaux et al. 2010, EAS Publ. Ser. 40, 97 (https://arxiv.org/abs/1002.0245). For 15 winter nights at Dome C, observed surface-layer thickness was 35.3 ± 5.1 m:
  - Meso-NH at **100 km** gave 65.9 ± 8.7 m;
  - Meso-NH **nested to 1 km** gave 48.9 ± 7.6 m.

  The authors stress "the importance of the high horizontal resolution configuration".
- **CFD:** Li & Jiang 2022, *RAA* (DOI 10.1088/1674-4527/ac4e00; https://arxiv.org/abs/2111.09556). Idealised CFD of an observatory site:
  - the windward slope accelerates flow over the summit;
  - on the leeward mountainside, wind speed drops but turbulence intensity rises.
  - They report agreement with DIMM data. Mechanical turbulence intensity, metre-scale geometry, one site.

### 3. Indicators: what has been tested against seeing

| Indicator (from model profiles plus a DEM) | Tested against seeing? | Where, and how |
|---|---|---|
| Wind direction relative to local terrain | **Partly**: measured local wind at single sites, never as a model-plus-DEM indicator across sites | Paranal, CTIO, 13N, Javalambre, Lenghu (§1). Effects are site-specific, and some come from domes or platforms (CTIO, Paranal). |
| Froude number / mountain-wave regime | **No test found** | Textbook regime theory only. Stull, *Practical Meteorology* §17.7 (https://geo.libretexts.org/Bookshelves/Meteorology_and_Climate_Science/Practical_Meteorology_(Stull)/17:_Regional_Winds/17.7:_Mountain_Waves): lee wavelength λ = 2πM/N (e.g. 14.6 km for M = 30 m s⁻¹, N = 0.0129 s⁻¹); Fr ≈ 1 gives "very intense waves" and rotors; Fr ≫ 1 gives a turbulent wake. Searches for Froude number with seeing or Cₙ² found nothing. |
| Richardson number near the summit | **Yes, measured, at one site**; **indirectly in models** | Ma et al. 2020, *Nature* 583, 771 (https://arxiv.org/abs/2007.15365), Dome A: seeing and boundary-layer thickness correlate with T(8 m) − T(0 m). As Ri rises from 0 to 0.8, median seeing improves; for Ri > 0.8 it's ~0.3″. Ri also sits inside the O&S Cₙ² model we use (L = √(2/Ri), RESEARCH §4.4). A Polar WRF Dome A study (*MNRAS* 515, 1788) is said to relate Ri to seeing *[not read; OUP blocked]*. |
| Gravity-wave activity / breaking | **Against radar Cₙ² (monthly)**; **against aircraft EDR**; **not against seeing** | Nastrom et al. 1986 (radar Cₙ²); Coulman et al. 1995 (mechanism). Aviation: Sharman & Pearson 2017, *J. Appl. Meteor. Climatol.* 56, 317–337 (DOI 10.1175/JAMC-D-16-0205.1) *[abstract only; AMS blocked]* present "new mountain-wave-turbulence algorithms", verified against in-situ EDR and pilot reports. I couldn't read the algorithm itself. A secondary 2025 preprint describes it as a near-surface factor of terrain height, terrain gradient and surface wind speed *[unverified]*. ERA5 publishes parameterised gravity-wave dissipation (`gwd`, 197) and surface stress (`lgws`/`mgws`, 195/196) (ERA5 data documentation, https://confluence.ecmwf.int/display/CKB/ERA5%3A+data+documentation). I found no study relating them to seeing. |
| Terrain roughness / slope statistics | **Slope: Antarctica only. Roughness: no test found** | The katabatic slope ↔ boundary-layer depth link is measured (Marks 1999/2002) and modelled (Swain & Gallée 2006). Els et al. 2009 blame SPM's stronger ground layer partly on trees ("increased surface roughness"), qualitatively. ERA5 carries sub-grid orography statistics (`sdor`, `isor`, `anor`, `slor`, `sdfor`; same documentation page), but nobody has tested them against seeing that I found. Global site-selection work uses elevation, not roughness (Aksaker et al. 2020, RESEARCH §3.8). |

### 4. Scale: what resolution these effects need

- **Horizontal scale of the effects:**
  - Wakes and platform effects: 10–150 m (13N sits 150 m below the ridge; platform edges at Paranal).
  - Rotor sub-structure: 0.5–1 km (Strauss et al. 2015).
  - Lee-wave wavelengths: ~5–15 km (Stull; *[inference]* λ = 2πM/N gives 6.3 km for M = 10 m s⁻¹, N = 0.01 s⁻¹).
  - Orographic influence on the 0.5–2 km layers: "tens of km" (Els et al. 2009).
- **Vertical scale:**
  - The Chilean TMT sites' ground layer lies mostly below 40–60 m; 13N and SPM have more up to ~100 m (Els et al. 2009).
  - Racine 2005 gives a 3.5 m scale height for surface-layer blur (RESEARCH §2).
  - Successful site models used a first level at 5 m and 62 levels (MOSE).
- **Model effective resolution:**
  - Abdalla et al. 2013, "Effective spectral resolution of ECMWF atmospheric forecast models", *ECMWF Newsletter* 137, 19–22 (https://www.ecmwf.int/sites/default/files/elibrary/2013/17358-effective-spectral-resolution-ecmwf-atmospheric-forecast-models.pdf): IFS surface wind spectra match altimeter spectra down to ~120 km at 16 km grid spacing, ~75 km at 10 km, and 30–40 km at 5 km. "The model fully resolves scales in excess of about 8 times the grid spacing." This was measured for ocean-surface wind in IFS.
  - The often-quoted ~7Δx for WRF (Skamarock 2004, *Mon. Wea. Rev.* 132, 3019) is only confirmed by secondary sources. The abstract I read (UCAR record) defines effective resolution but gives no number, and the full text was behind a bot challenge.
- **What each model can represent** *[inference: applying ~7–8Δx to models other than the one it was measured on]*:

  | Model | Grid | Smallest well-resolved scale | Lee waves (5–15 km) | Rotors, wakes (≤1 km) |
  |---|---|---|---|---|
  | MEPS | 2.5 km | ~20 km | partly (longest only) | no |
  | ICON-EU | ~7 km | ~50 km | no (forced by smoothed terrain) | no |
  | IFS open | 9 km | ~70 km | no | no |
  | GFS | ~13 km | ~100 km | no | no |
  | ERA5 | ~31 km | ~250 km | no (parameterised drag only) | no |

  - All of them can represent the *synoptic* inputs a flag would need: wind speed and direction at ridge height, stability N, and Fr computed against a DEM.
  - None can represent the resulting turbulence explicitly.
  - Vertically, ERA5's 25 hPa pressure levels near the ground are ~200–300 m apart *[inference from the hydrostatic scale height]*, an order of magnitude too coarse for the 10–100 m ground layer.

## Not verified / unsure

- **Haleakala:** Bradley et al. 2006, *PASP* 118, 172 (DOI 10.1086/497622). The abstract says they "examine the dependence of seeing on wind". A search-engine summary claimed the worst seeing comes with winds crossing the crater; I couldn't read the paper (IOP blocked). **Not cited as evidence.**
- **Skidmore et al. 2009 (TMT V):** the 13N wake statement comes second-hand via Els et al. 2009. Seeing roses by site weren't read.
- **Masciadri, Vernin & Bougeault 1999 (A&AS 137, 185 and 203)**, the first Meso-NH Cₙ² papers with an orography-sensitivity study at Paranal: aanda.org returned 403, and I couldn't confirm their DOIs.
- **Algorithm details I couldn't read:** Sharman & Pearson 2017 (MWT terms and skill), Nastrom et al. 1986 (definition of the gravity-wave indicator), and Swain & Gallée 2006 (MAR grid spacing and validation). All abstract only.
- **Unverified lead:** a WRF Cₙ² parameterisation said to capture "high Cₙ² from breaking mountain waves" (a ResearchGate listing only). Not cited.
- **The lee-wave scale numbers** are textbook theory plus my arithmetic, and the model-resolution table is an inference.

## Verdict

- **F1 (picking the observer's height): no change.**
  - Nothing in the literature gives a windward/lee correction that transfers between sites. Where direction matters, the sign and the cause (upwind summits, ridge wakes, platform edges, domes) are local.
  - Keep the height-only method (RESEARCH §5) and say in the UI that it has no flow-dependent term.
- **F2: not supported as a seeing term.**
  - The turbulence involved is at 0.1–1 km horizontally and 10–500 m vertically, below anything MEPS, ICON-EU, IFS, GFS or ERA5 resolve.
  - Site models that did capture it ran at 100 m–1 km with first levels at 5 m.
  - A Meso-NH/WRF downscaling per place is a research project on its own (one domain per site, hours of compute per night) *[inference]*.
- **Later, research-grade only: a qualitative flag, not a number.**
  - Model wind and stability at ridge height plus GLO-30 can give Fr and the wind direction relative to the local slope and aspect, so a "lee side, mountain waves likely" warning is computable.
  - The precedent is aviation (GTG mountain-wave turbulence, verified against aircraft EDR). It has never been tested against seeing.
  - It would need our own validation before display, for example against ESO Paranal DIMM/MASS with ESO's mast wind (CC BY, D28), where direction effects are documented.
- **Antarctica** is the one region where a terrain-plus-flow term (katabatic slope → boundary-layer depth) has both measurements and model maps behind it. It's still model-specific (MAR) and was calibrated locally.

## Open questions for Riley

1. **Accept the verdict?** No windward/lee term in F1 or F2, and the UI states that seeing varies with height only.
2. **Qualitative flag:** do you want a later research ticket for a "lee / mountain-wave turbulence possible" flag (Fr and relative wind direction from forecast-model winds plus GLO-30), labelled untested until validated against Paranal DIMM + wind? Or drop it?
3. **Papers to fetch by hand** (publisher blocked from the cloud):
   - Bradley et al. 2006 (10.1086/497622);
   - Skidmore et al. 2009 (10.1086/644758);
   - Swain & Gallée 2006 (10.1086/507153);
   - Sharman & Pearson 2017 (10.1175/JAMC-D-16-0205.1);
   - Nastrom et al. 1986 (10.1029/JD091iD06p06722);
   - Masciadri, Vernin & Bougeault 1999 (A&AS 137, 185 and 203);
   - the Polar WRF Dome A paper (*MNRAS* 515, 1788);
   - Skamarock 2004 (*MWR* 132, 3019).

   Want any of them read into this note?

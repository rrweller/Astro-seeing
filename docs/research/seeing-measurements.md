# Measured seeing for validation: observatory monitors, amateur sources, and indirect references

No ticket yet. Researched 2026-11-05 by the agent. Sources are primary where possible: the providers' own pages and data endpoints, arXiv papers, the DOAJ record for papers on blocked publishers (MDPI), and vendor or society pages for amateur tools. Every link below was loaded on 2026-11-05 and says what is cited, unless marked *[not reached]* or *[unverified]*. Where I pulled data to check a claim, I say what I ran. Search-engine summaries were used only as leads and are not cited.

**Question.** What sources of *measured* seeing exist, plus measured Cₙ² profiles, free-atmosphere seeing or turbulence, that we could use to sanity-check (a) the next-night seeing forecast and (b) the 2021–2025 ERA5 climatology? On what terms are they available? Riley is in Kongsberg (59.67°N, 9.65°E), so Scandinavian sources matter most.

RESEARCH §6 already covers the TMT database, the ESO ambient database, Bi et al.'s Chinese sites and Timau. Here I only add whether they have recent or near-real-time data, except for ESO. ESO turned out to be the best source, so it gets a full entry.

## Short answer

- **Four professional monitors publish raw seeing openly and cover 2021–2025, and three of them update within the night.**
  1. **ESO Paranal and La Silla** (DIMM, MASS, MASS-DIMM). Anonymous CSV queries. When I queried at 08:57 UTC, the newest Paranal DIMM point was from 08:54 UTC. The ESO archive is CC BY 4.0.
  2. **Maunakea MKAM** (MASS-DIMM). Nightly text files from 2009.
  3. **ING R2D2 on La Palma** (DIMM, from October 2018). Text output.
  4. **Calar Alto RoboDIMM** (from 2004). Zip download.
- **Licences differ.** Only ESO has a clear licence. ING's legal notice forbids redistribution without authorisation. MKWC and Calar Alto state no data licence. Lenghu gives data on request only.
- **Telescope image quality is a second, weaker check.** ZTF at Palomar has per-exposure FWHM through IRSA TAP, anonymous, to at least July 2026. The LCO network has per-frame FWHM in its archive headers after a 12-month proprietary period. Both measure *delivered image quality*, which includes optics, focus and dome seeing. Use them only for night-to-night correlation, never for absolute values.
- **Seeing forecasts to compare against** come with measurements at two places: MKWC (Maunakea, with its own forecast verification statistics) and the ALTA Center (LBT, Mt Graham, Astro-Meso-NH forced by ECMWF).
- **No usable amateur source exists.** I found no network or shared database of amateur seeing in arcseconds:
  - commercial amateur monitors (Alcor Cyclope and micro-Cyclope) don't publish data;
  - SharpCap's "Seeing Monitor" is a relative sharpness score;
  - the ASCOM `StarFWHM` property exists, but I found nothing that collects it;
  - observing logs use subjective scales (Pickering 0–10, Antoniadi I–V, AstroBin 1–5) or image FWHM that includes the equipment.
- **Nothing measured in Scandinavia.** The nearest open monitor is Calar Alto, about 2,640 km away.
  - Near Kongsberg the indirect references are radiosondes: Oslo-Blindern (67 km, but only 1,270 soundings since 2001), Stavanger/Sola (243 km) and Göteborg/Landvetter (271 km, in IGRA to 2023). They check the *input profiles*, not the Cₙ² model.
  - The only way to get measured seeing near Kongsberg is to measure it ourselves (see open questions).

## Comparison

Ratings: **(a)** for validating a next-night forecast, **(b)** for validating the 2021–2025 climatology. H = high, M = medium, L = low, — = none.

| Source | What | Where | Period found | Access | Terms | (a) | (b) |
|---|---|---|---|---|---|---|---|
| ESO Paranal ASM | DIMM (500 nm, zenith), MASS free-atmosphere seeing, MASS-DIMM Cₙ² ground fraction, SLODAR | Cerro Paranal, 2635 m (§6.3) | DIMM 1998–2016 (old tower), 2016-04-05 → now; MASS 2016 → now | anonymous web form / CSV URL | ESO archive data CC BY 4.0 | **H** | **H** |
| ESO La Silla | DIMM | La Silla, 2400 m (§6.3) | 2025 data checked; start not checked | anonymous CSV | as above | M | M–H |
| MKWC / MKAM | DIMM, MASS, MASS Cₙ² profile; plus MKWC seeing forecasts | Maunakea, 7 m tower between CFHT and Gemini North | 2009-09-22 → now; 42 of 60 sampled 2021–25 nights present | anonymous nightly text files | no licence; "general public is welcome to use" | **H** | **H** |
| ING R2D2 (and RoboDIMM before it) | DIMM | ORM La Palma, near the WHT, 2326 m | R2D2 Oct 2018 → now; RoboDIMM 2002–2018 | anonymous text output | ING legal notice: no redistribution without authorisation | H | H |
| Calar Alto RoboDIMM | DIMM (Johnson V), longitudinal and transverse | Calar Alto, Spain | Aug 2004 → now; 2021-06, 2023-10, 2026-09 checked | anonymous zip via form | "© CAHA"; no licence found | M–H | H |
| Lenghu (NAOC) | DIMM | Lenghu, Qinghai (§6.1) | live plots | data by e-mail request | not stated | L | M (if granted) |
| TMT site-testing DB | DIMM, MASS, etc. | 5 sites (§6.4) | 2–5 years in ~2003–2008; no recent data | free login | "minimal usage and publication restrictions" | — | — (period mismatch; good for method checks) |
| ZTF (IRSA) | per-exposure image FWHM (`seeing`, arcsec) | Palomar | 2018 → at least 2026-07-28 | anonymous TAP | acknowledgement requested; licence not checked | L–M | M (relative only) |
| LCO archive | per-frame `L1FWHM`, autoguider `AGFWHM` (arcsec) | 1 m network: CTIO, SAAO, Siding Spring, Teide, McDonald, Haleakala… | 12-month proprietary, then public | anonymous API for public frames | LCO proprietary policy | — | L–M (relative only) |
| ALTA Center | Astro-Meso-NH seeing forecasts (plus LBT DIMM climatology page) | Mt Graham (LBT) | 2016 → now | public web pages | not checked | M (forecast comparison) | — |
| Radiosondes (IGRA v2) | T, wind and humidity profiles (seeing derived, not measured) | e.g. Oslo-Blindern, Sola, Landvetter | decades → near real time | anonymous | NOAA; licence not checked | L | L–M |
| Amateur logs (AstroBin, ALPO, forums) | subjective scale or equipment-limited FWHM | worldwide | — | mostly no bulk access | per site | — | — |

## Findings, each with its source

### 1. Professional monitors with public data

#### ESO Paranal and La Silla (best overall)

- **Instruments:**
  - the Paranal ASM was upgraded in April 2016;
  - the query forms cover DIMM 1998 (to about six months after April 2016), DIMM 2016, MASS, MASS-DIMM ("Cn2 fraction at ground", seeing, τ₀, θ₀), SLODAR ("Cn2 fraction below 300m/500m") and LHATPRO;
  - MASS "gives the Cn2(h) for 6 layers placed at 0.5, 1, 2, 4, 8 and 16 km above the telescope pupil".

  Source: https://archive.eso.org/cms/eso-data/ambient-conditions/paranal-ambient-query-forms.html
- **DIMM placement and convention:**
  - "since April 5th 2016, the DIMM is located on a 7.5 m high platform";
  - its seeing is "normalized to a unity airmass … and at a wavelength of 500 nm". That matches our convention (500 nm, zenith);
  - "The MASS also provides a seeing estimate in a free atmosphere (above 1 km)". That is the same split height Osborn & Sarazin use (RESEARCH §3.3);
  - the long-term ground-layer fraction is "62%";
  - a Stereo-SCIDAR is also listed.

  Source: https://www.eso.org/sci/facilities/paranal/astroclimate/asm-instruments.html
- **Access (tested):**
  - `https://archive.eso.org/wdb/wdb/asm/dimm_paranal/query?wdbo=csv&start_date=2026-11-04..2026-11-06&tab_fwhm=on&max_rows_returned=5000` returned 783 rows, anonymously. The header is `Date time,DIMM Seeing ["],Relative Flux RMS,…`. The last row was `2026-11-05T08:54:51,0.721`, with the query run at 08:57 UTC. So it is **near-real-time**.
  - The same pattern works for `mass_paranal`. Columns include `Free Atmosphere Seeing ["]`, `MASS-DIMM Cn2 fraction at ground`, `MASS-DIMM Seeing ["]` and `MASS Turb Altitude [m]`.
  - It also works for `ambient_lasilla`, with columns `Date time,DIMM Seeing ["],DIMM Airmass`. I checked rows on 2025-06-01.
- **Licence:** "All data in the ESO archive retain ESO's copyright, and are distributed according to the terms of the Creative Commons Attribution 4.0 International license (CC BY 4.0)" (https://archive.eso.org/cms/eso-data-access-policy.html).
  - The ambient database is part of the ESO archive site. That the sentence covers ASM data is my reading; it doesn't name the ASM.
- **Forecasts:** I found no public ESO seeing-forecast page.
  - The Astro-Meso-NH work for Paranal (MOSE; Masciadri et al. 2017, RESEARCH §3.6) was described as moving towards operations.
  - I did not confirm a public product.

#### Maunakea Weather Center (MKWC) and the MKAM MASS-DIMM

- **Live page:** http://mkwc.ifa.hawaii.edu/current/seeing/ (http; https reset the connection from this cloud). It says:
  - "(Seeing data starts on September 22, 2009)";
  - the latest values were DIMM 0.87″ and MASS 0.28″;
  - the MASS software "can overestimate the turbulence strength of layers … the MASS data are preliminary";
  - the monitor runs only with wind < 50 km/h and humidity < 85%.
- **Nightly raw files**, linked from the night pages:
  - `http://mkwc.ifa.hawaii.edu/current/seeing/dimm/YYYYMMDD.dimm.dat`, rows like `2026 08 27 19 37 14 0.55`;
  - `…/mass/YYYYMMDD.mass.dat`;
  - `…/masspro/YYYYMMDD.masspro.dat` (per-layer Cₙ²·dh plus a seeing value).
  - The timestamps look like local HST: the night labelled 2026-08-28 starts at "2026 08 27 19 37". *[my inference; to be confirmed]*
- **Coverage test:** a HEAD request for the 15th of each month 2021–2025 found 42 of 60 files present. The missing ones cluster in January–April and November.
- **Climate page** (http://mkwc.ifa.hawaii.edu/current/seeing/analysis/climate.cgi): DIMM median 0.65″ over 4,216 nights; MASS median 0.34″ over 3,881 nights.
- **Instrument location:** "installed on a seven-meter tall tower between the Canada-France-Hawaii telescope and the Gemini-North telescope … approximately 150 meters North of the UH88″ telescope". Both instruments report at 500 nm. Source: arXiv:1807.03885 ('Imaka GLAO paper, §2), read from the arXiv PDF.
- **Forecasts:**
  - MKWC's forecast page (http://mkwc.ifa.hawaii.edu/forecast/mko/) gives a seeing range per night, e.g. "seeing near 0.8-1 arcsecond for the night", and a 5-day table with a seeing column;
  - the statistics page (http://mkwc.ifa.hawaii.edu/forecast/mko/stats/) offers forecast-verification tables per variable, including "Seeing", for nights 1–5.
- **Terms:** the disclaimer (http://mkwc.ifa.hawaii.edu/disclaimer.cgi) says "The general public is welcome to use the MKWC" and that products may sometimes be missing. I found no data licence, so ask before republishing anything.

#### ING (La Palma, Roque de los Muchachos)

- **R2D2:** ING's seeing page (https://www.ing.iac.es/astronomy/development/seeing/) says R2D2 "is a copy of the instrument in use at Telescopio Nazionale Galileo (TNG), and began taking data in October 2018. It replaces RoboDIMM, which had worked since 2002".
- **Text output (tested):** `https://astro.ing.iac.es/seeing/r2d2_data.php?date1=2023-06-10&date2=2023-06-11&submit=Submit` returned "Date Time (UT) R2D2 seeing (")" rows about every 36 s.
- **Live page:** the weather page (https://astro.ing.iac.es/weather/) shows "DIMM Seeing" and says "R2D2 live seeing is averaged every 5 minutes".
- **RoboDIMM history** (https://www.ing.iac.es/Astronomy/observing/conditions/):
  - located "a few 10s of m north of the WHT building";
  - median 0.80″ in April–November and 1.07″ in December–March (2012–15);
  - "known to under-detect very good seeing (< 0.5 arcsec)".
- **ORM aggregator:** the NOT hosts a combined page that lists RoboDIMM and R2D2 values for any night from 2011, with links to IAC and TNG DIMMs (https://www.not.iac.es/weather/dimm_index.php?day=10&month=06&year=2023&submit=Raw+Data).
  - The TNG DIMM page (https://tngweb.tng.iac.es/weather/) is a JavaScript app; I could not read data from it *[unverified]*.
- **Terms:** ING's legal notice (https://www.ing.iac.es/legal-notice.html) says reproduction and distribution of website content "without the authorisation of UNITED KINGDOM RESEARCH AND INNOVATION … is expressly prohibited". Users may store it "solely and exclusively for personal and private use".
  - Internal validation is probably fine. Publishing derived comparisons or raw values needs ING's permission.

#### Calar Alto (Spain)

- **Instrument:**
  - a DIMM "since August 2004 … fully automatic";
  - it measures "at the wavelengths corresponding to the Johnson V-band";
  - it was calibrated against an earlier DIMM and a GSM;
  - it closes when humidity is above 80% or wind reaches 12 m/s, "which comprises ∼50% of the time";
  - it gives transverse and longitudinal seeing.

  Source: Sánchez et al. 2007, arXiv:0709.0813, §2.4, read from the arXiv PDF.
- **Download (tested):**
  - the SQDATA form (https://www.caha.es/guindos/SQDATA/sqdata_form.html) posts to `sqdata.php`, which returns a zip;
  - the README gives the RoboDIMM fields as "Timestamp, Date, Time, Star, Longitudinal Seeing (LS), Transversal Seeing (TS), Airmass".

  What I pulled:

  | Month | Rows | Dates | Invalid | Median LS |
  |---|---|---|---|---|
  | 2021-06 | 4,681 | 17 | 35 | 1.28 |
  | 2023-10 | 20,026 | 16 | 25 | 1.13 |
  | 2026-09 | 21,913 | 22 | 0 | 0.70 |

  - The invalid values are written as `-1.#IND00`, and must be counted and masked (AGENTS "no silent fixes").
  - An airmass column is given. Whether LS and TS are already corrected to zenith isn't stated *[check]*.
- **Terms:** the form carries "© 2022 Centro Astronómico Hispano en Andalucía". I found no data licence, so ask.
- **Coordinates:** not checked on a CAHA page. The distance in this note uses 37.22°N, 2.55°W *[unverified]*.

#### Lenghu (Qinghai; Bi et al. site, RESEARCH §6.1)

- The site page (http://lenghu.china-vo.org/seeingstat) shows live DIMM seeing plots and histograms. It says "If you want to download the original data, please contact us", and gives an e-mail address at NAOC.
- The https version has an expired certificate, so I used http.
- **Usefulness:** recent data only by request.

#### ALTA Center (LBT, Mt Graham, Arizona): forecasts with observations

- **What it is** (https://alta.arcetri.inaf.it/): an automatic nightly forecast of Cₙ², seeing, θ₀ and τ₀ for the LBT. It has "Next Night" and "Previous Nights" pages and a "DIMM seeing" climatology page.
- **ECMWF Newsletter 178** (https://www.ecmwf.int/en/newsletter/178/news/optical-turbulence-forecasts-using-ecmwf-products-support-large-binocular, Masciadri, January 2024):
  - Astro-Meso-NH is "fed with initialisation and forcing data coming from ECMWF";
  - it runs "Since 2016";
  - a plot compares forecasts with observations.
- **Open points:** whether the LBT DIMM raw data are public, and the terms of use, were not checked *[unverified]*.
- **Usefulness:** a ready-made, published forecast-vs-observation benchmark at one site. A comparator for (a), not a data source.

#### TMT site-testing database (RESEARCH §6.4)

- https://sitedata.tmt.org/: "data have been gathered for … periods between two and five years". Download needs a login, and "The data are provided free to anybody with minimal usage and publication restrictions".
- The campaign ran about 2003–2008 (Schöck et al. 2009, arXiv:0904.1183, abstract: "the last five years").
- **No recent data.** Useless for 2021–2025 matching; still the best free-atmosphere vs ground-layer check (RESEARCH §6.4).

#### Sites where I found no public feed, or could not reach the page

- **SAAO Sutherland:** a MASS-DIMM "was commissioned in March 2010 to provide continuous monitoring of the seeing conditions" (Catala et al., arXiv:1308.5456, abstract). The live page `suthweather1.saao.ac.za` **is blocked from this cloud** (proxy refused it). Riley could check it, or the host could be allowlisted.
- **CTIO and Cerro Pachón (NOIRLab DIMM1/2/3):**
  - `https://www.ctio.noirlab.edu/noao/content/RoboDIMM` returned HTTP 503 twice *[not reached]*;
  - the LSST technical note RTN-022 (https://rtn-022.lsst.io/) used Pachón DIMM data "from 2004-03-17 to 2019-10-07" and says "The DIMM has significant gaps". It doesn't say where the data came from.
- **Kitt Peak, Apache Point, Siding Spring:** no public DIMM data page found (search only).
- **Teide (IAC):** search led to an IAC FAQ that reportedly lists the Teide DIMM as "coming soon" *[not loaded; unverified]*.
- **Published campaigns only, no data access found:**
  - Maidanak (Tillayev et al. 2023, *Atmosphere* 14, 199, DOI 10.3390/atmos14020199). DIMM 2018–2022, 266 nights, median 0.69″ (abstract via the DOAJ API; MDPI blocked here).
  - Dome C (Aristidi et al.; arXiv:1811.09643).
  - Mt Shatdzhatmaz (Kornilov et al.; arXiv:1006.3528, 1403.6820).
  - Skinakas, Crete (Boumis et al., astro-ph/0111022; 2000–2001).
  - Wendelstein (a 1998 ESO-DIMM campaign, per an LMU PDF found by search; not loaded).

### 2. Survey-telescope image quality (delivered FWHM, not seeing)

- **ZTF (Palomar):**
  - IRSA's TAP schema for `ztf.ztf_current_meta_sci` lists `seeing, arcsec, Seeing FWHM`, plus `obsjd`, `airmass`, `maglimit` and `infobits`.
  - Anonymous `https://irsa.ipac.caltech.edu/TAP/sync` queries returned rows for JD 2459300 (2021-03-26), 2460600 (2024-10) and 2461250 (2026-07-28), and none for JD 2461330 (2026-10-16). The lag is roughly 2–3 months *[from 4 probes]*.
  - Values seen: about 2.3–4.2″. So this is telescope image quality, much larger than DIMM seeing.
  - IRSA's ZTF page (https://irsa.ipac.caltech.edu/Missions/ztf.html) gives an acknowledgement text and "Latest: Data Release 24, 2026-01-22". I did not check the licence.
- **LCO global 1 m network:**
  - The archive API returns public frames anonymously (`https://archive-api.lco.global/frames/?public=true&reduction_level=91&start=…`).
  - The FITS header of a CTIO frame (`lsc1m004-fa03-20240601-0099-e91`) has `L1FWHM = 2.427 / [arcsec] Frame FWHM in arcsec`, `AGFWHM / [arcsec] Autoguider FWHM`, `SCHEDSEE / [arcsec] Estimated seeing when group scheduled`, and weather-station keys `WMS*`.
  - The archive documentation (https://lco.global/documentation/archive-documentation/) says science data have "a 12-month proprietary period". Education and outreach data and calibrations are public at once.
- **Caution:** image FWHM is the convolution of seeing with optics, focus, guiding and dome or mirror seeing, measured at the target's airmass and in the frame's filter. It can support *correlation* tests (does our forecast rank nights the same way?), not absolute validation.

### 3. Amateur and citizen-science sources

- **Commercial monitors:**
  - Alcor System sells the *Cyclope* and *micro-Cyclope*. The micro-Cyclope is a sealed outdoor unit aimed at Polaris, "at latitudes above 15° North", reporting seeing in arcsec at "0.55µm" (https://alcor-system.com/new/SeeingMon/uCyclope.html).
  - The vendor's validation is its own comparison with star FWHM on a 250 mm RC, not a peer-reviewed comparison with a DIMM.
  - I found no shared data network.
  - At Kongsberg, Polaris is about 59.7° up (airmass ≈ 1.16), so the geometry would suit a local unit.
- **Software:**
  - **SharpCap's Seeing Monitor** "analyse[s each frame] for sharpness (contrast)". That is a relative score, not arcsec (https://docs.sharpcap.co.uk/4.0/23_SeeingMonitor.htm).
  - **ASCOM** defines `IObservingConditions.StarFWHM`: "Seeing at the observatory measured as star full width half maximum (FWHM) in arc secs" (https://ascom-standards.org/library/html/P_ASCOM_Common_DeviceInterfaces_IObservingConditions_StarFWHM.htm). So amateur observatory software *can* expose seeing, but I found no service that aggregates it.
- **Observing-log scales are subjective:**
  - ALPO's Mars form uses "the Pickering scale, which is an eleven point scale from 0 to 10, wherein 0 is the worst seeing … 10 is a perfectly steady view", or Antoniadi "V to I", with "opposite" directions (https://alpo-astronomy.org/content/Mars/Forms/How-to-use-ALPO-Mars-obs-form-2020.pdf).
  - AstroBin's acquisition import has `seeing`: "Your estimation of the seeing, whole number 1–5". It also has `meanFwhm`: "Mean Full Width at Half Maximum in arc seconds, a measure of seeing" (https://welcome.astrobin.com/importing-acquisitions-from-csv). Whether these fields can be read in bulk through an API, with locations, was not checked *[unverified]*. Even then, `meanFwhm` includes the equipment.
- **Solar scintillation monitors** (e.g. Airylab SSM; found by search, not loaded) measure *daytime* seeing and do not apply to night-time seeing.
- **Forecast scale for comparison (North America only):** Clear Sky Chart's seeing line is a 5-class CMC forecast, "calibrated for instruments in the 11 to 14 inch range", in 3-hour blocks (https://www.cleardarksky.com/c/WAkey.html). It is a forecast, not a measurement.
- **Measurement uncertainty:** Tokovinin 2023, "The Elusive Nature of 'Seeing'", *Atmosphere* 14, 1694, DOI 10.3390/atmos14111694 (abstract via the DOAJ API; MDPI blocked here). It says seeing "cannot be measured with arbitrary accuracy". Monitor biases (noise, propagation, finite exposure, optics, wind shake) "should be quantified and corrected". This is the reason any amateur or uncalibrated number must not be treated as truth.
- **Leads only (forums, not cited as fact):** Cloudy Nights threads "DIMM Seeing Monitor Anyone?" and "Do it yourself seeing monitor and software?" mention a MaxIm DL DIMM plug-in and DIY DIMMs.
- **Verdict:** no amateur resource gives seeing in arcsec that is calibrated and in bulk. Nothing here is usable as validation data. At most it is anecdotal colour for the forecast.

### 4. Radiosonde and other indirect references

- **IGRA v2** (https://www.ncei.noaa.gov/products/weather-balloon/integrated-global-radiosonde-archive):
  - "about 800 stations" report in near real time;
  - "Vertical extent as well as temporal and vertical resolution also vary among stations and over time".
- **Stations near Kongsberg** (from https://www.ncei.noaa.gov/data/integrated-global-radiosonde-archive/doc/igra2-station-list.txt; distances are mine):

  | Station | Distance | IGRA period | Soundings |
  |---|---|---|---|
  | Oslo-Blindern | 67 km | 2001–2026 | 1,270 (sparse) |
  | Stavanger/Sola | 243 km | 1949–2026 | |
  | Göteborg/Landvetter | 271 km | 1977–2023 | |
  | Karup, DK | 377 km | 1999–2023 | |
  | Ørland | 449 km | 1959–2026 | |
  | Visby | 550 km | 1977–2026 | |

- **What they test:** seeing from a sounding uses the same Tatarskii-type model as ours (Bi et al. and Priyatikanto, RESEARCH §3.1–3.2). So it checks ERA5 and NWP *profiles* and vertical resolution, not the Cₙ² model.
  - Quatresooz, Vanhoenacker-Janvier & Oestges (arXiv:2204.00349) apply a Cₙ² model to "high-density radiosonde profiles at Trappes (France)" and compare it with T-REX thermosonde measurements. That paper is a method reference for a European sonde check.
- **ICOS Hurdal** (NO-Hur, 60.372°N 11.078°E, 111 km from Kongsberg; https://meta.icos-cp.eu/resources/stationentry/NO-Hur):
  - an eddy-covariance flux tower in spruce forest;
  - its L2 products include sensible heat flux;
  - ICOS data are "licensed under the Creative Commons Attribution 4.0 International licence (CC BY 4.0)" (https://www.icos-cp.eu/data-services/about-data-portal/data-license).
  - It could check the *inputs* of the experimental W71 ground layer (H, u*; RESEARCH §4.7) against ERA5, not seeing. The tower sits above a forest canopy, so its relevance to open ground is limited.

### 5. Scandinavia and northern Europe specifically

- **No sources found.** Searches in English, Norwegian and German found no DIMM, MASS or other seeing monitor with data in Norway, Sweden, Denmark or Finland.
- **Harestua** (the University of Oslo's former solar observatory) has no published seeing data that I could find.
- **Nearest open sources:**
  - nearest open monitor: Calar Alto (~2,640 km);
  - nearest published European campaigns: Wendelstein (~1,340 km, 1998) and Skinakas (~2,940 km, 2000–01). Both distances use coordinates I didn't check *[unverified]*.
- **What's left near Kongsberg:**
  - radiosondes, for checking profiles (§4);
  - ICOS fluxes, for checking ground-layer inputs (§4);
  - a monitor of our own (open questions).

## Ranked shortlist

1. **ESO Paranal DIMM + MASS + MASS-DIMM, and La Silla DIMM.**
   - Anonymous CSV, near-real-time, CC BY 4.0. Also checks the free-atmosphere/ground split at 1 km.
   - Already in RESEARCH §6.5 as calibration data. Use it for both (a) and (b).
2. **MKWC MKAM DIMM + MASS (+ MASS profiles), plus MKWC's own seeing forecasts.**
   - Nightly files from 2009 and a professional forecast to benchmark against.
   - The terms need an e-mail.
3. **ING R2D2 (La Palma).** Data from 2018 and live. A third independent site, a Haslebacher and phase 1 target. Redistribution needs ING's permission.
4. **Calar Alto RoboDIMM.** From 2004 and current. The nearest open monitor to Norway and a mid-latitude continental site. Terms unclear. It needs airmass and invalid-value handling.
5. **ZTF per-exposure FWHM (and LCO public frames).** Only for rank or correlation tests of nightly variation at Palomar and the LCO sites.
6. **ALTA Center forecasts.** A published model-vs-DIMM benchmark at the LBT, to compare our forecast skill with.
7. **Lenghu.** By request only. It would add a high-altitude Asian site that Bi et al. used.
8. **Near Kongsberg:** radiosondes (Oslo-Blindern, Sola) and ICOS Hurdal, for checking inputs, not seeing.

## Things to watch when comparing

- **Monitor height.** DIMMs sit on 5–7.5 m towers and miss part of the surface layer (RESEARCH pitfall 15). Compare against our seeing integrated from (site elevation + tower height) upward.
- **Normalisation.** Check each source's wavelength and zenith normalisation:
  - ESO and MKAM: 500 nm, zenith;
  - Calar Alto: V band, with an airmass column;
  - RoboDIMM: zenith-corrected;
  - R2D2: not stated.
- **Time standards.** ESO and ING give UT; MKWC files look like HST; Calar Alto gives a Unix timestamp plus a date.
- **Weather selection.** Monitors close in high wind or humidity (MKAM: wind < 50 km/h, RH < 85%; Calar Alto closes about 50% of the time). Measured statistics are conditional on usable weather. Compare like with like, e.g. only hours when the monitor ran, and log how many hours are excluded.
- **Interpolation.** Following AGENTS, compare by converting our J (or J(h)) to seeing at the monitor's time and height. Never interpolate seeing itself.

## Open questions for Riley

1. **New data sources [ASK].**
   - Adding ESO ASM data adds a source, but its CC BY 4.0 licence is the same as ERA5's.
   - MKWC, ING and Calar Alto have no stated licence, or a restrictive one. Should I draft permission e-mails (MKWC, ING, CAHA, and a data request to Lenghu) before we use them beyond private checks?
2. **A monitor at Kongsberg?**
   - No measured seeing exists anywhere near you. A DIY DIMM (two-hole mask on a small telescope plus a fast camera) or a fixed Polaris unit such as the micro-Cyclope would be the only local truth.
   - Even then, Tokovinin 2023 warns that uncalibrated monitors carry biases. Interested? It costs money, so [ASK].
3. **SAAO.** `suthweather1.saao.ac.za` is blocked from this cloud. Can you open it and tell me whether it shows MASS-DIMM data with an archive? Or allowlist the host.
4. **Image-quality data (ZTF and LCO).** Do you want a correlation test of our nightly forecast against delivered FWHM? It is cheap (anonymous TAP), but only a relative check.

## What I could not verify

- **ESO:** that the CC BY 4.0 sentence covers the ambient database, not only science data.
- **La Silla:** the start date of its DIMM record.
- **MKWC:** the time zone of the raw files (HST is inferred), and the terms of use beyond the disclaimer.
- **ING:** whether R2D2 values are zenith-corrected.
- **Calar Alto:** whether LS and TS are zenith-corrected, and the site coordinates and altitude.
- **TNG DIMM, CTIO/Pachón, SAAO, Teide, Kitt Peak, APO, Siding Spring:** live or archive pages either not reachable or not found.
- **ALTA/LBT:** whether DIMM raw data are public.
- **ZTF:** the exact release lag (inferred from 4 probes), and the licence wording for IRSA ZTF metadata.
- **AstroBin:** API access to `meanFwhm`, `seeing` and location.
- **Papers needing Riley to fetch:** Maidanak (MDPI) and Tokovinin 2023 (MDPI) were read only as abstracts through DOAJ. The Redu (Belgium) ERA5-vs-Cₙ²-model paper turned up in search (MDPI *Electronics* 13(1), 55) and was not read; it is a lead only.

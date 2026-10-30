# Bi et al. 2023: DIMM site altitudes, DIMM heights and the lower integration limit

Research note for issue #9 (map: #6). Written 2026-10-30 by the agent; not yet reviewed by Riley.

Question: Bi et al. 2023 (*Remote Sensing* 15(9), 2225, DOI 10.3390/rs15092225) integrate eq. 7 from h = 0 ("height above ground") but don't give the altitudes of their four DIMM sites. What do their references (Cao et al. 2020, Feng et al. 2020, Deng et al. 2021) say about altitudes, DIMM heights and periods? Does anything say which lower limit, ERA5 levels and ERA5 hours Bi et al. used? Is the Rongcheng position (in the sea) corrected anywhere?

## Short answer

| Site | Altitude (m a.s.l.) | DIMM height above ground | Measurement period | Source |
|---|---|---|---|---|
| Ali | **5100** (site); **5040** for Point A1, where the main instruments were | 3 m roof (to May 2017) → 5 m tower (from May 2017, 3 m used to fill gaps) → 11 m tower once reinforced (date not given). Liu et al. call it a 10 m tower. | 2017-03-10 to 2019-03-10 (457 days of raw data) | Feng 2020 Table 2 and §3, §4.1; Cao 2020 §1, §3; Liu 2020 §3 |
| Daocheng | **4750** (Feng); **4739** (Cao) | 7.5 m platform at Point 2; moved to "a similar Point 1" after April 2018. Song et al. give Point 1's platform as 5 m. | 2017-03-10 to 2019-03-10 (357 days); no DIMM data July–October 2018 | Feng 2020 Table 2, §4.1; Cao 2020 §1, §3; Song 2020 §2 |
| Muztagh-ata | **4526** | French DIMM (main source): ground → 11 m tower from 2017-06-23 (reinforced from 2017-10-08). NIAOT DIMM (backup): ground → 6 m → 11 m. | 2017-03-12 to 2019-03-10 (Cao Table 4); Xu et al. analyse April 2017 – November 2018 | Feng 2020 Table 2; Cao 2020 §1, Table 4; Xu 2020 abstract |
| Lenghu | **4200** (potential locations 4200–4500) | 10 m tower | October 2018 to December 2020 | Deng 2021 Main text and Methods |

- **Lower integration limit, ERA5 levels and ERA5 hours used by Bi et al.:** not stated in any source I could read. The three references predate Bi et al. and don't use ERA5. The two later papers by the same group that use ERA5 (Bi et al. 2023 *MNRAS* 527, 4616; Qing et al. 2023 *MNRAS* 526, 802) were blocked (Cloudflare), and their abstracts don't say.
- **Rongcheng (122.11E, 36.46N, in the sea):** no correction found. Crossref lists no correction or update for the paper. None of the sources I could read mention Rongcheng.
- **Coordinates:** Bi's Daocheng, Muztagh-ata and Lenghu coordinates match the sources to the printed precision. Bi's Ali longitude (80.06E) matches none of them exactly (80.046E Feng; 80.02671E Cao; E80°01′ Liu). Every source position gives the same nearest ERA5 point that Bi lists (80.00E, 32.25N), so this doesn't change the reproduction.
- **Wavelength (found along the way):** the LOT DIMMs measured at 500 nm (Ali and NIAOT DIMMs) or 550 nm (French DIMM). Feng Table 3 says the values were not scaled in wavelength. Bi's Table 3 is labelled 550 nm. The difference is (550/500)^(−1/5) ≈ 0.981, so about 2% (~0.02″ at 1″). Lenghu's DIMM values are at 550 nm.

## Claims and sources

Quotes are short and copied from the PDFs or HTML named here. "Feng 2020" quotes are from the published RAA version; the arXiv v2 text says the same in the parts quoted.

### Feng et al. 2020 (Bi ref. [45]): campaign overview

L. Feng et al., "Site testing campaign for the Large Optical/infrared Telescope of China: overview", *RAA* 20(6), 80 (2020), DOI 10.1088/1674-4527/20/6/80.
Read: publisher PDF from the journal site, https://www.raa-journal.org/issues/all/2020/v20n6/mini/202203/P020220324615028396036.pdf (landing page https://www.raa-journal.org/issues/all/2020/v20n6/mini/202203/t20220323_22170.html), and arXiv https://arxiv.org/abs/2001.11378 (v2).

- **Altitudes and coordinates, Table 2 ("Altitude and Location of the Monitoring Sites"):** Ali 5100 m, 80.046E, 32.306N; Daocheng 4750 m, 100.109E, 29.107N; Muztagh-ata 4526 m, 74.897E, 38.330N.
- **§3, Ali:** "It has an altitude of 5100 m." Two other points on the same ridge (B and C) are at 5160 m and 5380 m and were "still under development".
- **§3, Daocheng:** "The altitude of the site is 4750 m."
- **§3, Muztagh-ata:** "The site's altitude is 4526 m".
- **DIMM heights, Ali (§3):** "Initially, an 11 m tower was built for DIMM measurement", but it was unstable and had to be reinforced. "Meanwhile, another Ali DIMM kept monitoring on the 3 m high roof of the observation building." "A 5 m tower was built in May 2017" and the 3 m DIMM moved onto it.
- **DIMM heights, Ali (§4.1):** "before May 2017, seeing measurements came from the DIMM on the 3 m rooftop". Then mainly the 5 m tower, with 3 m data filling gaps. "After the 11 m tower was reinforced, data completely came from DIMM on the 11 m tower." "Cross comparison results of 3 m and 5 m measurements indicated no noticeable difference." No date is given for the move to 11 m.
- **DIMM heights, Daocheng (§3, §4.1):** instruments "installed on the 7.5 m concrete observation tower"; "Daocheng's seeing was measured from the 7.5 m tower". There was no DIMM data from July to October 2018 ("system failure").
- **DIMM heights, Muztagh-ata (§3, §4.1):** both DIMMs started on the ground. The French DIMM moved to the 11 m tower, the NIAOT DIMM to a 6 m tower, and then to 11 m from 21 September 2018. Comparing ground and 11 m tower measurements taken at the same time, "seeing measurements on the tower were approximately 0.3″ better".
- **Period (§4):** "data gathered between 2017 March 10 and 2019 March 10".
  - The captions of Table 4 and Table 6 say "2017 March 10 and 2018 March 10". The text and the Table 6 note ("two year monthly median values") say two years, so the captions look like a typo. I didn't check this further.
- **DIMMs (Table 3):** the wavelength is 500 nm for the Ali and NIAOT DIMMs and 550 nm for the French DIMM. The Scaling row reads "convert to zenith, no exposure time scaling" for all three, plus "no wavelength scaling" for the French DIMM.
- **Seeing (Table 6, two-year average of monthly medians):** Ali 1.17″, Daocheng 1.01″, Muztagh-ata 0.90″. These are not the same statistic as Bi's Table 3 "measured" medians (1.08, 1.01, 0.82). I haven't worked out where Bi's numbers come from.

### Cao et al. 2020 (Bi ref. [44]): data processing for Ali, Daocheng and Muztagh-ata

Z.-H. Cao et al., "Data processing and data products from 2017 to 2019 campaign of astronomical site testing at Ali, Daocheng and Muztagh-ata", *RAA* 20(6), 82 (2020), DOI 10.1088/1674-4527/20/6/82.
Read: publisher PDF from the journal site, https://www.raa-journal.org/issues/all/2020/v20n6/mini/202203/P020220324615021861118.pdf (landing page https://www.raa-journal.org/issues/all/2020/v20n6/mini/202203/t20220323_22168.html).

- **§1, Ali:** "main instruments were deployed at Point A1 (longitude: 80.02671° E, latitude: 32.32573° N, altitude: 5040 m)". So the instrument point is 60 m below the 5100 m "site" altitude in Feng et al. and Liu et al.
- **§1, Daocheng:** Point 1 and Point 2 ("the main site of interest for night observation") are both printed as "longitude: 100.10890° E, latitude: 29.10695° N, altitude: 4739 m".
  - Identical coordinates for two points look like a copy error. Song et al. 2020 say the two stations are 7 km apart (below). I can't tell which point the printed values belong to.
- **§1, Muztagh-ata:** "longitude: 74.89676° E, latitude: 38.33044° N, altitude: 4526 m".
- **§3, Ali DIMM:** "The seeing data at the Ali site are mainly based on results measured by the Ali DIMM at the top of the 11 m tower." Before reinforcement the tower vibration raised values "by roughly 0.2″". "Meanwhile, another Ali DIMM monitored on the 3 m high roof of the observation building. We combined data sets from these two instruments, and the combined raw data include a total of 457 days from 2017 March 10 to 2019 March 10."
- **§3, Daocheng DIMM:** "The Daocheng site DIMM was on a 7.5 m observation platform at Point 2 and was moved to a similar Point 1 after April 2018." The data are 357 days, 2017 March 10 to 2019 March 10, mainly from the NIAOT DIMM.
- **§3 and Table 4, Muztagh-ata DIMMs** ("French DIMM and NIAOT DIMM Working Conditions"):
  - French DIMM:
    - on the ground, 2017-04-15 to 2017-06-22;
    - on the 11 m tower before reinforcement, 2017-06-23 to 2017-10-07;
    - on the 11 m tower after reinforcement, 2017-10-08 to 2019-03-10.
  - NIAOT DIMM:
    - on the ground, 2017-03-12 to 2017-11-14;
    - on the 6 m tower, 2017-11-15 to 2018-09-20;
    - on the 11 m tower, 2018-09-21 to 2019-03-10.
  - "The French DIMM is the main data source for the seeing", and NIAOT data are used when French data are missing.
- **§3, heights:**
  - Ground NIAOT median 0.97″ against 0.79″ for the French DIMM at 11 m, measured at the same time.
  - "The median values at 6 m and 11 m were both found to be 0.87 arcsec."
  - "the altitude of the near-ground turbulence is below 6 m at the Muztagh-ata and Ali sites."
- **§3:** "we do not apply any corrections to the reported DIMM measurements" (no corrections between DIMMs).
- **Table 2:** centre wavelength 550 nm (French DIMM), 500 nm (NIAOT and Ali DIMMs).

### Liu et al. 2020: Ali site (not cited by Bi; read to cross-check)

L.-Y. Liu et al., "Site testing campaign for the Large Optical Telescope at the Ali site", *RAA* 20(6), 84 (2020), DOI 10.1088/1674-4527/20/6/84.
Read: https://www.raa-journal.org/issues/all/2020/v20n6/mini/202203/P020220324615017915929.pdf (landing page https://www.raa-journal.org/issues/all/2020/v20n6/mini/202203/t20220323_22166.html).

- **§1:** "The site is located at N32° 19′ and E80° 01′, with an altitude of 5100 m. The altitude of vast flat land nearby is around 4300 m."
- **§3:** "Finally, we built a 10-meter tower and started DIMM measurements at P3." This disagrees with the "11 m tower" in Feng et al. and Cao et al. I don't know which is right.
- **§4:** the statistics use "the dataset from March 2017 to March 2019".

### Song et al. 2020: Daocheng site (not cited by Bi; read to cross-check)

T.-F. Song et al., "Site testing campaign for the Large Optical/infrared Telescope of China: general introduction of the Daocheng site", *RAA* 20(6), 85 (2020), DOI 10.1088/1674-4527/20/6/85.
Read: https://www.raa-journal.org/issues/all/2020/v20n6/mini/202203/P020220324615015749259.pdf (landing page https://www.raa-journal.org/issues/all/2020/v20n6/mini/202203/t20220323_22165.html).

- **§2:** "Daocheng site (Mt. WMS, longitude 100° 05′ E, latitude 29° 08′ N)". The Figure 2 caption gives Mt. WMS "an altitude of 4800 m".
- **§2:** "The straight-line distance between the two monitor stations is 7 km." "the elevation of monitoring platforms is set as 5 m for No. 1 monitoring platform and 7.5 m for No. 2 monitoring platform."
  - If Song's No. 1 and No. 2 are Cao's Point 1 and Point 2, the Daocheng DIMM was at about 5 m after April 2018 and at 7.5 m before. Neither paper says so directly. This is my inference.

### Xu et al. 2020: Muztagh-ata seeing (not cited by Bi; read to cross-check)

J. Xu et al., "Site testing at Muztagh-ata site II: seeing statistics", *RAA* 20(6), 87 (2020), DOI 10.1088/1674-4527/20/6/87.
Read: https://www.raa-journal.org/issues/all/2020/v20n6/mini/202203/P020220324615011962562.pdf (landing page https://www.raa-journal.org/issues/all/2020/v20n6/mini/202203/t20220323_22163.html).

- **Abstract:** measurements "from April 2017 to November 2018 at different heights during different periods. The median seeings at 11 m and 6 m are very close but significantly different from that on the ground."
- **§2:** "The central wavelength of light measured by the DIMM is λ = 0.5 µm". Cao's Table 2 gives the French DIMM 550 nm, so the two papers disagree for the French DIMM.

### Deng et al. 2021 (Bi ref. [5]): Lenghu

L. Deng et al., "Lenghu on the Tibetan Plateau as an astronomical observing site", *Nature* 596, 353–356 (2021), DOI 10.1038/s41586-021-03711-z. Open access.
Read: https://www.nature.com/articles/s41586-021-03711-z (full HTML).

- **Methods, "Geographic information":** "Its geographical coordinates are 38.6068° N, 93.8961° E, and it has an elevation of 4,200 m."
- **Abstract:** "The altitudes of the potential locations are between 4,200 and 4,500 metres."
- **Main text:** "As DIMM seeing must be measured in the vicinity of a telescope project and at a similar height from the ground as the telescope, a 10-m tower was built to mount the DIMM."
- **Main text:** "Measurements are calculated for an average wavelength of 550 nm and corrected to the zenith (airmass unity)."
- **Fig. 1 caption:** "The DIMM seeing data are collected from October 2018 to December 2020." The median is 0.75″ from 383,825 valid measurements.
- **Methods, "Turbulence profiles":** three balloon flights "at the Lenghu weather station", at 23:15 UT on 12 August 2020 and at 11:18 UT and 23:44 UT on 16 November 2020. These are separate from Bi's Da Qaidam flights (August 2020). I haven't checked whether the two campaigns overlap.

### Later papers by the same group (abstracts only)

Read only through Crossref metadata (the abstract as deposited by the publisher). The full texts on academic.oup.com were blocked.

- **Bi, Qing, Qian, Zhu, Luo, Li 2023**, "Astroclimatic parameters characterization at Lenghu site with ERA5 products", *MNRAS* 527(3), 4616, DOI 10.1093/mnras/stad3414. Metadata: https://api.crossref.org/works/10.1093/mnras/stad3414
  - Abstract: uses "the 21-yr" ERA5 record with "a general turbulence model". "the median seeing value from ERA5 is 0.72 arcsec, generally consistent with the statistically measured value of 0.75 arcsec."
  - Bi's *Remote Sensing* Table 3 gives 0.96″ for Lenghu from ERA5. So the same group's later Lenghu number is much closer to the DIMM value. The method change behind that is the most likely place to find the lower limit, levels and hours, but the abstract doesn't say. **This is the paper to read next.**
- **Qing, Bi, Zhu, Qian, Kang 2023**, "A global turbulence model shows excellent atmospheric optical turbulence conditions over the Ethiopian plateau during non-rainy season", *MNRAS* 526(1), 802, DOI 10.1093/mnras/stad2795. Metadata: https://api.crossref.org/works/10.1093/mnras/stad2795
  - Abstract: a global r₀ map from ERA5, checked at ESO and Tibetan Plateau sites. It doesn't mention levels, hours or the lower limit.
- **Qing, Luo, Bi, Li, Cui 2021**, "Optical turbulence and wind speed distributions above the Tibetan Plateau from balloon-borne microthermal measurements", *MNRAS* 508(3), 4096, DOI 10.1093/mnras/stab2608. Metadata: https://api.crossref.org/works/10.1093/mnras/stab2608
  - Abstract: balloon campaign "above the Dachaidan site", median seeing 1.04″. This is probably the Da Qaidam campaign behind Bi's Table 2, where the measured median is 1.06″. The abstract doesn't give dates, so I'm not sure.

### Rongcheng

- **Corrections:** Crossref has no correction or update registered against 10.3390/rs15092225 (`https://api.crossref.org/works?filter=updates:10.3390/rs15092225` returned 0 results on 2026-10-30).
- **Other sources:** none of the sources I could read mention Rongcheng. A Crossref search for Rongcheng balloon turbulence papers found nothing relevant.
- **Bi's page:** I couldn't read the MDPI article page, so I couldn't check for a notice there.
- **Status:** the in-sea coordinates stay as in RESEARCH §6.1: uncorrected, and use Bi's listed ERA5 point.

## Not stated anywhere I could read

- **The ERA5 inputs Bi et al. used:** the lower limit of the integral, the ERA5 level type (pressure or model levels), and the hours that went into Table 3.
- **The tropopause switch:** how Bi et al. choose between the troposphere and stratosphere formulas.
- **Ali's move to the 11 m tower:** the date the DIMM moved there (only "after a few months" and "after the 11 m tower was reinforced").
- **Ali tower height:** whether it is 10 m (Liu) or 11 m (Feng, Cao).
- **Daocheng after April 2018:** which platform height the DIMM was on (inferred above as ~5 m, not stated).
- **Daocheng Point 1 and Point 2:** which point the printed coordinates and 4739 m altitude belong to, since Cao prints the same values for both.
- **Bi's "measured" medians:** how Bi et al. got 1.08″ (Ali), 1.01″ (Daocheng) and 0.82″ (Muztagh-ata). These differ from Feng Table 6 for Ali and Muztagh-ata. Whether they rescaled the 500 nm DIMM data to 550 nm is also not stated.
- **Rongcheng:** a corrected position.

## Sources I couldn't access

- **Bi et al. 2023, *Remote Sensing* (mdpi.com):** blocked from this environment (HTTP 403), as expected. I didn't recheck Bi's reference list, and relied on RESEARCH §3.1 and §6.1, which were checked against Riley's PDF (D35).
- **iopscience.iop.org (RAA 20, 082 and 080):** Radware bot-manager captcha. Not bypassed. The same papers were read from the journal's own site, raa-journal.org.
- **NASA ADS (ui.adsabs.harvard.edu):** AWS WAF captcha (HTTP 405). Not bypassed.
- **academic.oup.com (the three *MNRAS* papers above):** Cloudflare challenge (HTTP 403). Not bypassed. Only the Crossref abstracts were read. None of the three is on arXiv (searched by title).
- **Cai, Qing, Luo, Qian, Liu 2026**, "Modeling atmospheric optical turbulence with ERA5 and radiosonde data", Proc. SPIE (CITA 2025), DOI 10.1117/12.3093247: found in Crossref, no abstract, not opened (SPIE is paywalled).

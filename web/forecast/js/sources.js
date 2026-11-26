// The Data sources panel: each provider's own wording (D44 item 8, D52 item 6).
// Each quotation was read from the linked page on 2026-11-26 (D73). Links are shown
// for the reader to follow; the page itself never requests them.

export const SOURCES = [
  {
    id: "gfs",
    provider: "NOAA/NCEP: GFS",
    paragraphs: [
      "Based on the NOAA Global Forecast System (GFS), US government open data. " +
        "Cloud is shown as GFS gives it; seeing and the turbulence altitude are computed " +
        "by this site from GFS's temperature, wind and height fields, so they are not " +
        "original NOAA data.",
      "NOAA's terms: “NOAA data disseminated through NODD are open to the public and " +
        "can be used as desired.” “It is not permissible to state or imply " +
        "endorsement by or affiliation with NOAA.” This site is not endorsed by or " +
        "affiliated with NOAA.",
    ],
    link: "https://registry.opendata.aws/noaa-gfs-bdp-pds/",
  },
  {
    id: "icon",
    provider: "Deutscher Wetterdienst: ICON-EU",
    paragraphs: [
      "Datenbasis: Deutscher Wetterdienst, eigene Elemente ergänzt (data basis: " +
        "Deutscher Wetterdienst, with elements of our own added: the computed seeing).",
      "Licence: Creative Commons Attribution 4.0 (CC BY 4.0).",
    ],
    link: "https://www.dwd.de/DE/service/rechtliche_hinweise/vorlagen_quellenangabe.html",
  },
  {
    id: "meps",
    provider: "MET Norway: MEPS (MetCoOp)",
    paragraphs: [
      "Based on data from MET Norway.",
      "Licence: Norwegian licence for public data (NLOD) and Creative Commons " +
        "Attribution 4.0 (CC BY 4.0).",
    ],
    link: "https://www.met.no/en/free-meteorological-data/Licensing-and-crediting",
  },
  {
    id: "ifs",
    provider: "ECMWF: IFS open data",
    paragraphs: [
      "This service is based on data and products of the European Centre for " +
        "Medium-Range Weather Forecasts (ECMWF). Source: www.ecmwf.int.",
      "Licence: this ECMWF data is published under a Creative Commons Attribution 4.0 " +
        "International (CC BY 4.0) licence, https://creativecommons.org/licenses/by/4.0/.",
      "Disclaimer: ECMWF does not accept any liability whatsoever for any error or " +
        "omission in the data, their availability, or for any loss or damage arising " +
        "from their use.",
      "Modified: cloud is shown as ECMWF gives it; seeing and the turbulence altitude " +
        "are computed by this site from ECMWF's temperature, wind and height fields.",
    ],
    link: "https://apps.ecmwf.int/datasets/licences/general/",
  },
  {
    id: "glo30",
    provider: "Copernicus DEM GLO-30: the saved places' ground heights",
    paragraphs: [
      "Produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence " +
        "and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and " +
        "ESA; all rights reserved.",
    ],
    link: null,
  },
];

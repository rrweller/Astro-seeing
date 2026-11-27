"""Shared code for the paper reproductions (roadmap C9, D57, D66).

The four reproduction notebooks (Haslebacher, Priyatikanto, Bi, Osborn & Sarazin)
call this package on the CT:

* :func:`read_site`: a site's hourly z, T, u, v (and cc) from the ERA5 stores, in
  time order, checked, by the paper's site-value rule, with underground levels
  masked by the static orography (or not, as a variant), masked counts returned;
* rules :class:`Nearest`, :class:`Bilinear`, :class:`PriyatikantoCubic`;
* hour sets :func:`all_hours`, :func:`night_mask`, :func:`dark_time`,
  :func:`solar_time_window`;
* golden results: :func:`summary_statistics`, :class:`GoldenResult`,
  :func:`write_golden`, :func:`load_golden`, :func:`check_golden`, :func:`meets_target`.
"""

from astroseeing.repro.golden import (
    GoldenResult,
    check_golden,
    load_golden,
    meets_target,
    summary_statistics,
    write_golden,
)
from astroseeing.repro.hours import all_hours, dark_time, night_mask, solar_time_window
from astroseeing.repro.reader import HourGrid, SiteColumns, SiteReadError, StoreRef, read_site
from astroseeing.repro.rules import Bilinear, Nearest, PriyatikantoCubic

__all__ = [
    "Bilinear",
    "GoldenResult",
    "HourGrid",
    "Nearest",
    "PriyatikantoCubic",
    "SiteColumns",
    "SiteReadError",
    "StoreRef",
    "all_hours",
    "check_golden",
    "dark_time",
    "load_golden",
    "meets_target",
    "night_mask",
    "read_site",
    "solar_time_window",
    "summary_statistics",
    "write_golden",
]

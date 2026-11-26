"""The forecast track (F1 spec, GitHub issue #47): tonight's cloud and seeing, forecast
model by forecast model, for saved places and a map.

Subpackages follow the spec's modules, so separate tickets can work in separate files:

- ``sources``: one adapter per forecast model behind one interface (``RunFields``)
- ``verify``: run verification and the forecast manifest records
- ``column``: column products (J, H̄, seeing) from the shared physics engine
- ``grid``: the map grid (nearest point, never interpolated)
- ``tonight``: the single implementation of the verdict rules (D48)
- ``store``: per-place daily stores and the expiring SSD products
- ``publish``: the files the page reads, one module per output
- ``tick``: the 15-minute service step that runs everything
- ``alerts``: start/clear alerts through ``astro-notify``
- ``paranal``: the nightly Paranal check against ESO's DIMM and MASS

Shared groundwork (ticket #50): ``settings`` (the forecast settings file), ``http``
(the one HTTP client all forecast code uses) and ``schemas`` (the page-file schemas).
"""

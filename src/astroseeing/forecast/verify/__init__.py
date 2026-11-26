"""Run verification and records (F1 spec Module 2): ``verify_run(fields, expected)``
checks variables, levels, grid, steps and NaN/fill counts against the model's expected
content in the forecast settings, and the ``forecast_runs`` / ``forecast_files`` manifest
tables hold each run's state. Nothing is dropped, filled or regridded silently (D51 item 8).
"""

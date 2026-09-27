"""Provenance records (AGENTS.md: "every product records the git commit, config hash,
input manifest IDs and software versions")."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import platform
import socket
import subprocess
import sys
from importlib import metadata
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

_PACKAGES = (
    "astroseeing",
    "numpy",
    "scipy",
    "xarray",
    "zarr",
    "numcodecs",
    "eccodes",
    "cfgrib",
    "skyfield",
    "cdsapi",
    "ecmwf-datastores-client",
)


def canonical_json(obj: Any) -> str:
    """Deterministic JSON (sorted keys, no whitespace) used for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def config_hash(config: Any) -> str:
    return hashlib.sha256(canonical_json(config).encode()).hexdigest()


def git_state(repo: Path = REPO_ROOT) -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, text=True, check=True, timeout=30
        ).stdout.strip()

    try:
        commit = run("rev-parse", "HEAD")
        dirty = bool(run("status", "--porcelain", "--untracked-files=no"))
        return {"commit": commit, "dirty": dirty}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}


def software_versions() -> dict[str, str | None]:
    out: dict[str, str | None] = {"python": sys.version.split()[0]}
    for p in _PACKAGES:
        try:
            out[p] = metadata.version(p)
        except metadata.PackageNotFoundError:
            out[p] = None
    try:
        import eccodes

        out["eccodes-library"] = eccodes.codes_get_api_version()
    except Exception:  # pragma: no cover - eccodes missing
        out["eccodes-library"] = None
    return out


def provenance(
    config: Any, manifest_ids: dict[str, Any] | None = None, extra: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A provenance dict to store in product attributes."""
    return {
        "created_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "git": git_state(),
        "config_hash": config_hash(config),
        "config": config,
        "manifest": manifest_ids or {},
        "software": software_versions(),
        "host": socket.gethostname(),
        "platform": platform.platform(),
        **(extra or {}),
    }


#: Attribution required on products. ERA5 wording copied from the "Citation and
#: attribution" block of the CDS dataset pages (retrieved via the CDS catalogue API,
#: 2026-09-27); ``{year}`` is the year the product was generated. DEM wording from
#: docs/RESEARCH.md §7.
ERA5_ATTRIBUTION = (
    "Generated using or contains modified Copernicus Climate Change Service information "
    "{year}. Neither the European Commission nor ECMWF is responsible for any use that may "
    "be made of the Copernicus information or data it contains."
)
ERA5_CITATIONS = {
    "reanalysis-era5-pressure-levels": (
        "Hersbach, H., Bell, B., Berrisford, P., Biavati, G., Horányi, A., Muñoz Sabater, J., "
        "Nicolas, J., Peubey, C., Radu, R., Rozum, I., Schepers, D., Simmons, A., Soci, C., "
        "Dee, D., Thépaut, J-N. (2023): ERA5 hourly data on pressure levels from 1940 to "
        "present. Copernicus Climate Change Service (C3S) Climate Data Store (CDS), "
        "DOI: 10.24381/cds.bd0915c6"
    ),
    "reanalysis-era5-single-levels": (
        "Hersbach, H., Bell, B., Berrisford, P., Biavati, G., Horányi, A., Muñoz Sabater, J., "
        "Nicolas, J., Peubey, C., Radu, R., Rozum, I., Schepers, D., Simmons, A., Soci, C., "
        "Dee, D., Thépaut, J-N. (2023): ERA5 hourly data on single levels from 1940 to "
        "present. Copernicus Climate Change Service (C3S) Climate Data Store (CDS), "
        "DOI: 10.24381/cds.adbb2d47"
    ),
}
DEM_ATTRIBUTION = (
    "produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and "
    "Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights "
    "reserved"
)


def era5_attribution(dataset: str, year: int | None = None) -> dict[str, str]:
    """Attribution and citation strings for an ERA5 dataset."""
    year = year or dt.datetime.now(dt.UTC).year
    return {
        "attribution": ERA5_ATTRIBUTION.format(year=year),
        "citation": ERA5_CITATIONS.get(dataset, ""),
        "licence": "CC-BY-4.0",
    }

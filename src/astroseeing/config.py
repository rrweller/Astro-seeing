"""Configuration loading (YAML files under configs/).

Lookup order: ``$ASTRO_CONFIG_DIR``; the repo's ``configs/`` (source checkout or the
editable pixi install); the copy packaged into the wheel as ``astroseeing/configs``
(see ``[tool.hatch.build.targets.wheel.force-include]`` in pyproject.toml).
"""

from __future__ import annotations

import os
from functools import cache
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

import yaml

REPO_CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs"


def config_dir() -> Path | Traversable:
    env = os.environ.get("ASTRO_CONFIG_DIR")
    if env:
        return Path(env)
    if REPO_CONFIG_DIR.is_dir():
        return REPO_CONFIG_DIR
    packaged = resources.files("astroseeing") / "configs"
    if packaged.is_dir():
        return packaged
    raise FileNotFoundError(
        f"no configs found: set ASTRO_CONFIG_DIR, or run from a checkout ({REPO_CONFIG_DIR})"
    )


@cache
def load_config(name: str) -> dict[str, Any]:
    """Load ``<config dir>/<name>.yaml`` (cached; treat the result as read-only)."""
    return yaml.safe_load((config_dir() / f"{name}.yaml").read_text())

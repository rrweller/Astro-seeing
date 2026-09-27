"""Configuration loading (YAML files under configs/)."""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs"


@cache
def load_config(name: str) -> dict[str, Any]:
    """Load ``configs/<name>.yaml`` (cached; treat the result as read-only)."""
    with open(CONFIG_DIR / f"{name}.yaml") as f:
        return yaml.safe_load(f)

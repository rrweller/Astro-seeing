"""The forecast's systemd units (F1 spec #47 Modules 8 and 11, ticket #62; D51 items 1
and 4, D52 items 7-9, D32): the keys the decisions require, then ``systemd-analyze``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

import pytest

from astroseeing.provenance import REPO_ROOT

UNITS = REPO_ROOT / "scripts" / "systemd" / "system"
NEW_UNITS = ("astro-forecast.service", "astro-forecast.timer", "astro-web.service")


def unit(name: str) -> dict[str, dict[str, list[str]]]:
    """``{section: {key: [values in order]}}``; systemd allows a key more than once."""
    sections: dict[str, dict[str, list[str]]] = {}
    current = None
    for raw in (UNITS / name).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("["):
            current = sections.setdefault(line.strip("[]"), {})
            continue
        key, value = line.split("=", 1)
        current.setdefault(key.strip(), []).append(value.strip())
    return sections


def one(section: dict[str, list[str]], key: str) -> str:
    values = section.get(key, [])
    assert len(values) == 1, f"{key}: {values}"
    return values[0]


def systemd_tool(name: str) -> str | None:
    found = shutil.which(name)
    if found is None and os.environ.get("CI"):
        pytest.fail(f"{name} is needed under CI")  # skipping there would hide a broken unit
    return found


def test_the_timer_runs_the_tick_service_every_15_minutes():
    timer = unit("astro-forecast.timer")

    assert one(timer["Timer"], "Unit") == "astro-forecast.service"
    assert one(timer["Timer"], "Persistent") == "true"
    assert one(timer["Install"], "WantedBy") == "timers.target"
    calendar = one(timer["Timer"], "OnCalendar")
    tool = systemd_tool("systemd-analyze")
    if tool is None:
        pytest.skip("systemd-analyze not installed; the keys above were checked")
    out = subprocess.run(
        [tool, "calendar", "--iterations=5", "--base-time=2026-11-27 12:07:00 UTC", calendar],
        capture_output=True, text=True, check=True, env={**os.environ, "TZ": "UTC"},
    ).stdout  # fmt: skip
    times = re.findall(r"(\d\d:\d\d:\d\d) UTC", out.split("Next elapse:", 1)[1])
    assert times[:5] == ["12:15:00", "12:30:00", "12:45:00", "13:00:00", "13:15:00"]


def test_the_tick_service_runs_astro_forecast_tick_on_two_cores_at_normal_priority():
    service = unit("astro-forecast.service")
    s = service["Service"]

    assert one(s, "Type") == "oneshot"
    assert one(s, "ExecStart").endswith(" run astro forecast tick")
    assert one(s, "WorkingDirectory") == "/home/astro-seeing"
    # At most 2 worker processes (D51 item 4): the tick is one process; numeric
    # libraries' thread pools are capped at 2 and the service at two cores' worth of CPU.
    assert one(s, "CPUQuota") == "200%"
    env = " ".join(s["Environment"])
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        assert f"{var}=2" in env.split(), var
    # Normal priority: no nice level, scheduling class or I/O class that would lower it.
    assert one(s, "Nice") == "0"
    for key in ("CPUSchedulingPolicy", "IOSchedulingClass", "IOSchedulingPriority"):
        assert key not in s
    assert "/data/astro" in one(service["Unit"], "RequiresMountsFor").split()
    assert "Install" not in service  # started by the timer only


def test_the_web_service_runs_nginx_as_a_dynamic_user_with_read_only_site_and_products():
    service = unit("astro-web.service")
    s = service["Service"]

    assert "/staging" in one(service["Unit"], "RequiresMountsFor").split()
    exec_start = one(s, "ExecStart").split()
    assert exec_start[0].endswith("/nginx")
    assert not exec_start[0].startswith(("/root", "/home"))  # hidden by ProtectHome
    assert exec_start[exec_start.index("-c") + 1] == "/etc/astro-web/nginx.conf"
    assert one(s, "DynamicUser") == "yes"
    assert one(s, "ProtectSystem") == "strict"
    assert one(s, "ProtectHome") == "yes"
    assert one(s, "NoNewPrivileges") == "yes"
    # /staging is hidden except the two folders nginx serves, bound read-only.
    assert one(s, "TemporaryFileSystem") == "/staging:ro"
    assert one(s, "BindReadOnlyPaths").split() == [
        "/staging/forecast/site", "/staging/forecast/products",
    ]  # fmt: skip
    # Its own temp and log folders, created for the dynamic user, and nothing else.
    assert one(s, "RuntimeDirectory") == "astro-web"
    assert one(s, "LogsDirectory") == "astro-web"
    for key in ("ReadWritePaths", "StateDirectory", "CacheDirectory"):
        assert key not in s
    assert one(service["Install"], "WantedBy") == "multi-user.target"


def test_systemd_analyze_verify_passes_on_the_new_units(tmp_path):
    tool = systemd_tool("systemd-analyze")
    if tool is None:
        pytest.skip("systemd-analyze not installed; the key tests above still ran")
    # `verify` also checks that each Exec binary exists. On the CT they do (pixi, and
    # nginx installed with `pixi global`, F1-21); here each binary's path is prefixed with
    # a temp folder holding an executable stand-in, and nothing else in the unit changes.
    stand_ins = tmp_path / "bin"
    for name in NEW_UNITS:
        text = (UNITS / name).read_text()
        for key, values in unit(name).get("Service", {}).items():
            for v in values if key.startswith("Exec") else []:
                binary = v.lstrip("-@+!:").split()[0]
                stand_in = stand_ins / binary.lstrip("/")
                stand_in.parent.mkdir(parents=True, exist_ok=True)
                stand_in.write_text("#!/bin/sh\n")
                stand_in.chmod(0o755)
                text = text.replace(f"={binary} ", f"={stand_in} ")
        (tmp_path / name).write_text(text)
    out = subprocess.run(
        [tool, "verify", *(str(tmp_path / n) for n in NEW_UNITS)], capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    assert out.stderr == "", out.stderr

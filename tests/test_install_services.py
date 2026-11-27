"""``scripts/install_services.sh`` (D32; ticket #62): run against a temp root folder and
a fake ``systemctl``. The forecast's units and nginx config are installed but not
enabled; the ERA5 services are enabled as before.
"""

from __future__ import annotations

import os
import subprocess

from astroseeing.provenance import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "install_services.sh"
UNITS = REPO_ROOT / "scripts" / "systemd" / "system"


def run_installer(tmp_path):
    # Never let the test reach the real /etc: refuse a script that ignores the overrides.
    text = SCRIPT.read_text()
    assert '"${ASTRO_INSTALL_ROOT:-}"' in text and '"${SYSTEMCTL:-systemctl}"' in text
    calls = tmp_path / "systemctl-calls.txt"
    fake = tmp_path / "systemctl"
    fake.write_text(f'#!/bin/sh\necho "$*" >> {calls}\n')
    fake.chmod(0o755)
    root = tmp_path / "root"
    env = {**os.environ, "ASTRO_INSTALL_ROOT": str(root), "SYSTEMCTL": str(fake)}
    out = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True,
                         timeout=60)  # fmt: skip
    assert out.returncode == 0, out.stderr
    return root, calls.read_text().splitlines(), out.stdout


def test_every_unit_and_the_nginx_config_are_installed_and_the_served_folders_exist(tmp_path):
    root, _, _ = run_installer(tmp_path)

    for unit in sorted(UNITS.iterdir()):
        installed = root / "etc" / "systemd" / "system" / unit.name
        assert installed.read_text() == unit.read_text(), unit.name
        assert installed.stat().st_mode & 0o777 == 0o644
    conf = root / "etc" / "astro-web" / "nginx.conf"
    assert conf.read_text() == (REPO_ROOT / "scripts" / "nginx" / "astro-web.conf").read_text()
    assert conf.stat().st_mode & 0o777 == 0o644
    # astro-web.service binds these read-only; they must exist before it starts.
    for d in ("site", "products"):
        folder = root / "staging" / "forecast" / d
        assert folder.is_dir() and folder.stat().st_mode & 0o777 == 0o755


def test_the_forecast_units_are_not_enabled_and_the_era5_services_are(tmp_path):
    _, calls, stdout = run_installer(tmp_path)

    assert calls[0] == "daemon-reload"
    enabled = [c for c in calls if c.startswith("enable")]
    assert enabled == [
        "enable --now astro-notify.service astro-manifest-export.timer",
        "enable --now astro-boxes.service",
    ]
    assert not [c for c in calls if "astro-forecast" in c or "astro-web" in c]
    assert "systemctl enable --now astro-web.service astro-forecast.timer" in stdout

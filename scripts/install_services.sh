#!/usr/bin/env bash
# Install and start the CT 350 services (system-level systemd, as root): the download
# loop, the notification watcher, and the nightly manifest export. They run without
# any interactive session and come back after a reboot. Idempotent.
#
# Also installs, but does not enable, the forecast's units (astro-forecast.service and
# .timer, astro-web.service) and nginx's config, and creates the two folders nginx
# serves. Enabling them is a separate step (docs/ct_runbook.md, "Forecast page").
#
# Stop any tmux copies of the same loops first (tmux kill-session -t boxes / notify).
#
# Tests only: ASTRO_INSTALL_ROOT puts /etc and /staging under another folder, and
# SYSTEMCTL replaces systemctl.
set -euo pipefail
root="${ASTRO_INSTALL_ROOT:-}"
systemctl="${SYSTEMCTL:-systemctl}"
cd "$(dirname "$0")/.."
mkdir -p logs  # the units append their output here; systemd won't create the directory
install -d -m 755 "$root/etc/systemd/system" "$root/etc/astro-web"
for f in scripts/systemd/system/*.service scripts/systemd/system/*.timer; do
  install -m 644 "$f" "$root/etc/systemd/system/"
done
install -m 644 scripts/nginx/astro-web.conf "$root/etc/astro-web/nginx.conf"
# astro-web.service binds these read-only, so they must exist before it starts.
install -d -m 755 "$root/staging/forecast" "$root/staging/forecast/site" \
  "$root/staging/forecast/products"
"$systemctl" daemon-reload
"$systemctl" enable --now astro-notify.service astro-manifest-export.timer
"$systemctl" enable --now astro-boxes.service
"$systemctl" --no-pager --lines=0 status astro-boxes.service astro-notify.service \
  astro-manifest-export.timer || true
cat <<'EOF'
Forecast units installed, not enabled. Once nginx is installed and the page deployed
(docs/ct_runbook.md, "Forecast page"):
  systemctl enable --now astro-web.service astro-forecast.timer
EOF

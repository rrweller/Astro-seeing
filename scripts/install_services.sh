#!/usr/bin/env bash
# Install and start the CT 350 services (system-level systemd, as root): the download
# loop, the notification watcher, and the nightly manifest export. They run without
# any interactive session and come back after a reboot. Idempotent.
#
# Stop any tmux copies of the same loops first (tmux kill-session -t boxes / notify).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs  # the units append their output here; systemd won't create the directory
for f in scripts/systemd/system/*.service scripts/systemd/system/*.timer; do
  install -m 644 "$f" /etc/systemd/system/
done
systemctl daemon-reload
systemctl enable --now astro-notify.service astro-manifest-export.timer
systemctl enable --now astro-boxes.service
systemctl --no-pager --lines=0 status astro-boxes.service astro-notify.service \
  astro-manifest-export.timer || true

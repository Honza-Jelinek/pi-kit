#!/usr/bin/env bash
# tool:  update
# level: change
# desc:  Aktualizace systému na pozadí (apt full-upgrade), vrátí id jobu
# args:  (žádné)
# Běží jako systemd job, takže doběhne i při výpadku spojení.
# Stav: pi read <zařízení> job <id>. Restart po aktualizaci neprovádí, ukáže ho status.
set -euo pipefail

if systemctl list-units 'pk-job-update-*' --state=activating,active --no-legend --plain 2>/dev/null \
     | grep -q running; then
  echo "Aktualizace už běží:" >&2
  systemctl list-units 'pk-job-update-*' --no-legend --plain >&2
  exit 4
fi

id="pk-job-update-$(date +%Y%m%d-%H%M%S)"
sudo -n systemd-run --quiet --unit="$id" --remain-after-exit \
  --description="pikit: aktualizace systému" \
  --setenv=DEBIAN_FRONTEND=noninteractive \
  /bin/bash -c 'apt-get update && apt-get -y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold full-upgrade && apt-get -y autoremove'
echo "job: $id"
echo "Stav: pi read <zařízení> job $id"

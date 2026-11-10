#!/usr/bin/env bash
# tool:  reboot
# level: change
# desc:  Restart zařízení (za 5 s, ať se stihne vrátit odpověď)
# args:  (žádné)
set -euo pipefail
sudo -n systemd-run --quiet --on-active=5 --unit="pk-reboot-$(date +%s)" /bin/systemctl reboot
echo "Restart za 5 s. Zařízení bude zpátky zhruba za minutu."

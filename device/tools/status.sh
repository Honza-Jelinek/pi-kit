#!/usr/bin/env bash
# tool:  status
# level: read
# desc:  Stav zařízení: model, systém, běh, teplota, napájení, paměť, disk, Tailscale, firewall, služby
# args:  (žádné)
set -uo pipefail

kv() { printf '%s: %s\n' "$1" "$2"; }

kv "zařízení" "$(tr -d '\0' 2>/dev/null </proc/device-tree/model || echo neznámé)"
kv "systém" "$(. /etc/os-release && echo "$PRETTY_NAME"), $(uname -m), jádro $(uname -r)"
kv "běží" "$(uptime -p | sed 's/^up //')"
kv "zátěž" "$(cut -d' ' -f1-3 /proc/loadavg)"
kv "teplota" "$(vcgencmd measure_temp 2>/dev/null | sed 's/temp=//' || echo neznámá)"

thr=$(vcgencmd get_throttled 2>/dev/null | sed 's/throttled=//')
case "$thr" in
  0x0) thr="v pořádku" ;;
  "")  thr="neznámé" ;;
  *)   thr="$thr: podpětí nebo přehřátí někdy od startu (slabý zdroj?)" ;;
esac
kv "napájení" "$thr"

kv "paměť" "$(free -h | awk '/^Mem:/ {print $3 " z " $2}')"
kv "disk" "$(df -h / | awk 'NR==2 {print $3 " z " $2 " (" $5 ")"}')"

ts=$(tailscale status --json 2>/dev/null | grep -m1 -o '"BackendState": *"[^"]*"' | sed 's/.*: *"//; s/"$//')
kv "tailscale" "${ts:-neznámý} $(tailscale ip -4 2>/dev/null)"

fw=$(sudo -n ufw status 2>/dev/null | head -n1 | sed 's/Status: //')
if [ -f /etc/pikit/ssh-tailscale-only ]; then ssh_from="SSH jen přes Tailscale"; else ssh_from="SSH i z místní sítě"; fi
kv "firewall" "${fw:-neznámý}, $ssh_from"

kv "restart" "$([ -f /var/run/reboot-required ] && echo 'čeká na restart po aktualizacích' || echo 'není potřeba')"

failed=$(systemctl --failed --no-legend --plain 2>/dev/null | awk '{print $1}' | paste -sd' ' -)
kv "spadlé služby" "${failed:-žádné}"


kv "hlídač" "$(systemctl is-active pk-netwatch.timer 2>/dev/null || true)"

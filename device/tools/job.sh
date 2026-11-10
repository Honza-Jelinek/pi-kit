#!/usr/bin/env bash
# tool:  job
# level: read
# desc:  Stav jobu na pozadí (např. update); bez id vypíše poslední joby
# args:  [id] [--lines N]
set -euo pipefail

id=""; lines=40
while [ $# -gt 0 ]; do
  case "$1" in
    --lines) lines="${2:-}"; shift 2 ;;
    *)       id="$1"; shift ;;
  esac
done
[[ "$lines" =~ ^[0-9]+$ ]] || { echo "--lines musí být číslo" >&2; exit 2; }

if [ -z "$id" ]; then
  systemctl list-units 'pk-job-*' --all --no-legend --plain 2>/dev/null \
    | awk '{print $1 "  " $3 "/" $4}' || true
  exit 0
fi

id="${id%.service}"
[[ "$id" =~ ^pk-job-[a-z0-9-]+$ ]] || { echo "Neplatné id jobu: $id" >&2; exit 2; }
systemctl show "$id.service" -p ActiveState -p SubState -p Result -p ExecMainStatus \
  -p ExecMainStartTimestamp -p ExecMainExitTimestamp
echo "--- posledních $lines řádků výstupu"
journalctl -u "$id.service" --no-pager -o cat -n "$lines"

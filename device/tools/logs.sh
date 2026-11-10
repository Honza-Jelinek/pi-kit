#!/usr/bin/env bash
# tool:  logs
# level: read
# desc:  Systémové logy, celé nebo jedné služby (journalctl)
# args:  [služba] [--lines N] [--since "1 hour ago"] [--errors]
# Výchozí je posledních 100 řádků, nejvíc 2000.
# Příklady: logs tailscaled --since "30 min ago" | logs --errors | logs -t pikit-tool
set -euo pipefail

unit=""; lines=100; since=""; extra=()
while [ $# -gt 0 ]; do
  case "$1" in
    --lines)  lines="${2:-}"; shift 2 ;;
    --since)  since="${2:-}"; shift 2 ;;
    --errors) extra+=(-p err); shift ;;
    -t)       extra+=(-t "${2:-}"); shift 2 ;;
    -*)       echo "Neznámá volba $1" >&2; exit 2 ;;
    *)        unit="$1"; shift ;;
  esac
done
[[ "$lines" =~ ^[0-9]+$ ]] || { echo "--lines musí být číslo" >&2; exit 2; }
(( lines > 2000 )) && lines=2000

cmd=(journalctl --no-pager -o short-iso -n "$lines")
[ ${#extra[@]} -gt 0 ] && cmd+=("${extra[@]}")
[ -n "$unit" ] && cmd+=(-u "$unit")
[ -n "$since" ] && cmd+=(--since "$since")
exec "${cmd[@]}"

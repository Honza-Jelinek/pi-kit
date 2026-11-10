#!/usr/bin/env bash
# tool:  restart
# level: change
# desc:  Restart služby (pk-*, tailscaled, ssh a služby z /etc/pikit/restartable)
# args:  <služba>
# V /etc/pikit/restartable je na každém řádku jméno služby nebo vzor, např. mojeapp*.
set -euo pipefail

unit="${1:-}"
unit="${unit%.service}"
[ -n "$unit" ] || { echo "Zadej službu." >&2; exit 2; }
[[ "$unit" =~ ^[A-Za-z0-9@._-]+$ ]] || { echo "Neplatné jméno služby." >&2; exit 2; }

allowed=0
case "$unit" in pk-*|tailscaled|ssh) allowed=1 ;; esac
if [ "$allowed" -eq 0 ] && [ -f /etc/pikit/restartable ]; then
  while IFS= read -r pattern; do
    # shellcheck disable=SC2254
    case "$unit" in $pattern) allowed=1 ;; esac
  done < /etc/pikit/restartable
fi
[ "$allowed" -eq 1 ] || { echo "Službu '$unit' tenhle nástroj restartovat nesmí." >&2; exit 2; }

sudo -n systemctl restart "$unit"
systemctl --no-pager --lines=5 status "$unit" || true

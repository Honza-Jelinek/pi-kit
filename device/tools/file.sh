#!/usr/bin/env bash
# tool:  file
# level: read
# desc:  Obsah souboru nebo výpis složky (jen /opt/pikit, /etc, /var/log, /home, /tmp)
# args:  <cesta> [--lines N]
# Čte s právy tvého uživatele, bez sudo. Soubory jako /etc/shadow tedy nepřečte.
set -euo pipefail

path=""; lines=300
while [ $# -gt 0 ]; do
  case "$1" in
    --lines) lines="${2:-}"; shift 2 ;;
    *)       path="$1"; shift ;;
  esac
done
[ -n "$path" ] || { echo "Zadej cestu." >&2; exit 2; }
[[ "$lines" =~ ^[0-9]+$ ]] || { echo "--lines musí být číslo" >&2; exit 2; }

# -s: symlinky nerozbalovat (/etc/os-release vede do /usr/lib), ".." se ale vyhodnotí
real=$(realpath -ms -- "$path")
case "$real" in
  /opt/pikit|/opt/pikit/*|/etc|/etc/*|/var/log|/var/log/*|/home|/home/*|/tmp|/tmp/*) ;;
  *) echo "Cesta $real je mimo povolené složky." >&2; exit 2 ;;
esac

if [ -d "$real" ]; then
  ls -la --time-style=long-iso -- "$real"
elif [ -f "$real" ]; then
  if [ -s "$real" ] && ! grep -Iq . -- "$real"; then
    echo "Binární soubor, $(stat -c %s -- "$real") bajtů."
    exit 0
  fi
  total=$(wc -l < "$real")
  head -n "$lines" -- "$real"
  if (( total > lines )); then echo "... (zobrazeno $lines z $total řádků, víc: --lines N)"; fi
else
  echo "$real neexistuje." >&2; exit 3
fi

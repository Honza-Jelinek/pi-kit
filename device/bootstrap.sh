#!/usr/bin/env bash
# Instalace modulů na Raspberry Pi. Spouští ho `pikit init` z PC, běží pod správcem zařízení
# (sudo bez hesla). Dá se pustit opakovaně.
#
#   MODULES="ssh tailscale" LAN_PORTS="8080" TAILNET_PORTS="" bash bootstrap.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
MODULES="${MODULES:-}"
LAN_PORTS="${LAN_PORTS:-}"
TAILNET_PORTS="${TAILNET_PORTS:-}"

step() { printf '\n\033[1;36m== %s\033[0m\n' "$1"; }
ok()   { printf '   \033[32m%s\033[0m\n' "$1"; }
apt_get() { sudo DEBIAN_FRONTEND=noninteractive apt-get -y \
  -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold "$@"; }

sudo install -d -m 755 /opt/pikit/bin /opt/pikit/tools /etc/pikit /var/lib/pikit

for module in $MODULES; do
  file=$(ls "$HERE"/modules/[0-9]*-"$module".sh 2>/dev/null || true)
  if [ -z "$file" ]; then
    echo "Neznámý modul: $module" >&2
    exit 2
  fi
  step "$module"
  # shellcheck disable=SC1090
  . "$file"
done

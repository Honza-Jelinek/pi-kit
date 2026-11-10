#!/usr/bin/env bash
# tool:  run
# level: danger
# desc:  Libovolný příkaz v bashi (nouzový východ; na zařízeních zákazníků zakázán)
# args:  "<příkaz>"
# Když něco děláš přes run opakovaně, udělej z toho nástroj v pi/device/tools/.
set -uo pipefail
[ $# -gt 0 ] || { echo "Zadej příkaz v uvozovkách." >&2; exit 2; }
exec bash -c "$*"

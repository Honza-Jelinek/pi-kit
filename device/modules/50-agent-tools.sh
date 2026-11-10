# form: Nástroje pro agenta
# default: ano
# requires: ssh
sudo install -m 755 "$HERE/pk-tool" /opt/pikit/bin/
# Společné nástroje z repa. Nástroje specifické pro zařízení zůstanou.
sudo install -m 755 "$HERE"/tools/*.sh /opt/pikit/tools/
ok "Nástroje: $(ls /opt/pikit/tools | sed 's/\.sh$//' | paste -sd' ' -)"

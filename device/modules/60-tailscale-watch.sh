# form: Hlídač Tailscale
# default: ano
# requires: ssh tailscale
sudo install -m 755 "$HERE/pk-netwatch" /opt/pikit/bin/
sudo install -m 644 "$HERE"/systemd/pk-netwatch.service "$HERE"/systemd/pk-netwatch.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pk-netwatch.timer >/dev/null 2>&1
ok "Hlídač běží každé 2 minuty (journalctl -t pikit-netwatch)"

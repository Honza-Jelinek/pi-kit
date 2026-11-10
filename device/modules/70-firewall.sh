# form: Firewall
# default: ano
# requires: ssh
apt_get install ufw
sudo install -m 755 "$HERE/pk-firewall" "$HERE/pk-bootflags" /opt/pikit/bin/
sudo install -m 644 "$HERE/systemd/pk-bootflags.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable pk-bootflags.service >/dev/null 2>&1
printf 'LAN_PORTS="%s"\nTAILNET_PORTS="%s"\n' "$LAN_PORTS" "$TAILNET_PORTS" |
  sudo tee /etc/pikit/firewall.conf >/dev/null
sudo /opt/pikit/bin/pk-firewall apply
ok "Firewall zapnutý${LAN_PORTS:+, do místní sítě otevřeno: $LAN_PORTS}${TAILNET_PORTS:+, přes Tailscale: $TAILNET_PORTS}"

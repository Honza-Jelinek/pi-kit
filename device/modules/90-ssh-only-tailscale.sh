# form: SSH jen přes Tailscale
# default: ano
# requires: ssh tailscale firewall
# phase: verified
# Běží až poté, co PC ověří spojení přes Tailscale, jinak by se dalo odříznout.
sudo /opt/pikit/bin/pk-firewall lock
ok "SSH z místní sítě zavřené"

# form: Tailscale
# default: ano
# requires: ssh
if ! command -v tailscale >/dev/null 2>&1; then
  # Oficiální instalátor Tailscale: přidá jejich apt repozitář a nainstaluje balíček.
  curl -fsSL https://tailscale.com/install.sh | sh
fi
sudo systemctl enable --now tailscaled
if tailscale ip -4 >/dev/null 2>&1; then
  ok "Tailscale už je přihlášený"
else
  echo "   Teď se vypíše odkaz. Otevři ho v prohlížeči a zařízení schval ve svém Tailscale účtu."
  sudo tailscale up --hostname "$(hostname)"
fi
ok "Tailscale IP: $(tailscale ip -4)"

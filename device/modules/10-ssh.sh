# form: SSH
# default: ano
# Přihlášení jen klíčem, root se přihlásit nesmí. Vlastní soubor přežije aktualizace.
sudo tee /etc/ssh/sshd_config.d/10-pikit.conf >/dev/null <<'EOF'
# pikit: přihlášení jen SSH klíčem, root se přihlásit nesmí.
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
sudo sshd -t            # kontrola konfigurace, než ji SSH načte (jinak by se dalo odříznout)
sudo systemctl reload ssh
ok "Heslem se přihlásit nejde, root se přihlásit nejde"

# form: Automatické bezpečnostní záplaty
# default: ano
# requires: ssh
apt_get install unattended-upgrades
echo 'unattended-upgrades unattended-upgrades/enable_auto_updates boolean true' | sudo debconf-set-selections
sudo dpkg-reconfigure -f noninteractive unattended-upgrades
ok "Bezpečnostní záplaty se instalují samy (bez automatického restartu)"

# pi-kit

Nové Raspberry Pi od prázdné karty po vzdálenou správu. Bez monitoru a klávesnice.

Potřebuješ Windows, Python 3.10+, [Raspberry Pi Imager](https://www.raspberrypi.com/software/) 2.x
a čtečku SD karet. Tailscale v PC, pokud ho na Pi chceš používat.

## Postup s agentem

Řekni agentovi „nainstaluj nové Pi“. Vytiskne formulář, ty ho zkopíruješ, doplníš a vložíš zpátky:

```text
Jméno zařízení: dilna-01
Karta (písmeno disku, nebo disk 4): F
SSH (ano/ne): ano
Tailscale (ano/ne): ano
...
```

Agent formulář zkontroluje, ukáže plán a provede ho. Hesla do formuláře nepiš, zadáš je až v terminálu.

## Postup ručně

```bash
python bin/pikit.py form > nove.txt
```

Vyplň `nove.txt` a pak spouštěj kroky, které vypíše plán:

```bash
python bin/pikit.py plan nove.txt
```

## Co se dá vybrat

| Modul | Co dělá | Závisí na |
| --- | --- | --- |
| SSH | Přihlášení jen klíčem, root zakázaný | |
| Aktualizace systému | `apt full-upgrade` při instalaci | SSH |
| Automatické bezpečnostní záplaty | `unattended-upgrades` bez restartů | SSH |
| Tailscale | Přístup odkudkoli | SSH |
| Nástroje pro agenta | `pikit read/change/danger` | SSH |
| Hlídač Tailscale | Obnoví spojení po výpadku | Tailscale |
| Firewall | ufw, otevřené jen vybrané porty | SSH |
| SSH jen přes Tailscale | Zavře SSH z místní sítě, až po ověření Tailscale | Tailscale, Firewall |

Bez SSH se Pi jen nainstaluje a nastaví se mu heslo na konzoli. Na dálku se na něj nedostaneš.

Nový modul je jeden soubor v `device/modules/`. Do formuláře se dostane sám z hlavičky.

## Zápis karty

`pikit flash <jméno>` stáhne oficiální obraz, ověří jeho SHA-256 a zapíše ho přes Imager. Odmítne
systémový disk, interní disky a cokoli nad 512 GB. Nejdřív vypíše, co přesně smaže, a kontrolní kód.
Zápis pustí až s `--confirm <kód>`, a kód přestane platit, když je ve čtečce jiná karta. Windows se
ještě zeptá oknem správce.

## Správa zařízení

```bash
python bin/pikit.py devices
```

Dál `pikit tools`, `help`, `read`, `change`, `danger`. Přidej si `bin` do PATH a stačí `pikit`.
Seznam zařízení je v `devices.csv`, který do repa nepatří.

Přístup z místní sítě po zavření SSH: `pikit unlock-card` zapíše na kartu servisní soubor a Pi při
dalším startu SSH z místní sítě otevře.

## Stav ověření

Testy v `tests/` pokrývají formulář, závislosti modulů, ochranu disků a kontrolu stažení.

- Moduly vznikly rozdělením instalace ověřené na Pi 4 s Raspberry Pi OS Lite Trixie, v nové podobě ale na Pi ještě neběžely.
- Čeká na skutečnou kartu: `pikit flash` a instalace od prázdné karty.
- Nevyzkoušeno: instalace bez SSH, Wi-Fi z formuláře, Pi 3 a Pi 5.

# pi-kit

Instalace a správa Raspberry Pi: systém na kartu, první nastavení, moduly, nástroje pro agenta.
Sada je obecná. Nepřidávej do ní nic specifického pro jeden projekt. Návod pro lidi je v `README.md`.

## Nové zařízení: vždycky začni formulářem

Když uživatel chce nové Pi nebo instalaci, nehádej, co na něm má být.

1. Spusť `bin/pikit form` a výstup vytiskni do chatu **beze změny v bloku kódu**, ať ho jde zkopírovat.
   Napiš, ať ho uživatel vyplní a vloží zpátky. Na nic dalšího se zatím neptej.
2. Vložený formulář ulož do dočasného souboru a spusť `bin/pikit plan <soubor>`. Když vypíše chyby,
   předej je uživateli a počkej na opravu. Formulář neopravuj sám podle odhadu.
3. Ukaž plán. Hesla ani auth klíče po uživateli nechtěj: `pikit card` a Tailscale si je vyžádají
   v terminálu nebo v prohlížeči. Když je uživatel do formuláře přesto napíše, řekni mu, ať je změní.
4. Proveď kroky z plánu v tomto pořadí. Kroky označené „v terminálu“ spusť v terminálovém panelu
   uživatele, kroky „Člověk“ mu popiš a počkej, až je udělá.

## Zápis karty

`pikit flash` nevratně maže disk. Nejdřív ho spusť bez `--confirm`. Uživateli ukaž číslo disku, model
a velikost z výstupu a počkej na jeho výslovný souhlas v chatu. Až potom spusť příkaz s `--confirm`.
Kód nepoužívej znovu pro jiný běh. Kartu nikdy nevybírej odhadem.

## Práce se zařízeními

- Začni `pikit devices`, pak `pikit tools <zařízení>` a `pikit help <zařízení> <nástroj>`.
  Seznam nástrojů si vždycky zjisti, každé zařízení může mít jiné.
- Nástroj spustíš `pikit read|change|danger <zařízení> <nástroj> [argumenty]`. Sloveso musí odpovídat úrovni.
- Přímé `ssh` použij, jen když na úkol žádný nástroj není.
- `env` v `devices.csv`: na `test` smíš všechno. Na `customer` `danger` pikit odmítne a před každým
  `change` řekni uživateli, co a proč uděláš, a počkej na souhlas.
- Síť, firewall, SSH a Tailscale na `customer` neměň bez výslovného souhlasu. I na `test` si nejdřív
  naplánuj návrat: `sudo systemd-run --on-active=120 --unit=pk-rollback /opt/pikit/bin/pk-firewall apply`.
  Po ověření spojení ho zruš: `sudo systemctl stop pk-rollback.timer`.

## Rozšiřování

- Nový modul je soubor `device/modules/NN-jméno.sh`. Hlavička `# form:`, `# default:`, `# requires:`,
  případně `# phase: verified`. Do formuláře se dostane sám, číslo určuje pořadí instalace.
- Nový nástroj je `device/tools/<jméno>.sh` s hlavičkou `tool`, `level`, `desc`, `args`. Úroveň určuje
  nejhorší věc, kterou umí: jen čte = `read`, mění stav = `change`, spouští libovolný kód = `danger`.
- Skripty pro Pi musí mít konce řádků LF.
- Do repa nikdy neukládej soukromé klíče, hesla k Wi-Fi, Tailscale auth klíče ani `devices.csv`.
- Testy: `python -m pytest tests` (potřebují `pytest` a `bash`).

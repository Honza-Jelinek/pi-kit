#!/usr/bin/env python3
"""pikit: instalace a správa Raspberry Pi z jednoho místa.

Nové zařízení
  pikit form                       vypíše formulář, co na zařízení má být
  pikit plan <soubor>              zkontroluje vyplněný formulář a vypíše postup (- = stdin)
  pikit key                        vytvoří SSH klíč (jednou)
  pikit flash <jméno>              nahraje systém na kartu (smaže ji, chce --confirm)
  pikit card <jméno>               zapíše na kartu první nastavení
  pikit init <jméno> [--only a,b]  nainstaluje vybrané moduly na běžící Pi
  pikit sync-ssh                   z devices.csv vygeneruje SSH zkratky
  pikit unlock-card                servisní soubor na kartu: Pi při startu otevře SSH z LAN

Práce se zařízeními (pro člověka i agenta)
  pikit devices                    seznam zařízení a kdo je online
  pikit tools <zařízení>           nástroje, které zařízení nabízí
  pikit help <zařízení> <nástroj>  jak nástroj použít
  pikit read|change|danger <zařízení> <nástroj> [argumenty]

Volba --json (hned za slovesem) vrátí strojově čitelný výstup.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import getpass
import hashlib
import json
import os
import re
import shlex
import string
import subprocess
import sys
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEVICES_CSV = Path(os.environ.get("PIKIT_DEVICES") or ROOT / "devices.csv")
DEVICE_DIR = ROOT / "device"
MODULES_DIR = DEVICE_DIR / "modules"
ACTION_LOG = ROOT / "logs" / "actions.log"
CACHE_DIR = Path.home() / ".cache" / "pikit"
SSH_DIR = Path.home() / ".ssh"
KEY = Path(os.environ.get("PIKIT_KEY") or SSH_DIR / "pikit_ed25519")
SSH_CONFIG = SSH_DIR / "config"
PK_SSH_CONFIG = SSH_DIR / "pikit_config"

COLUMNS = ["name", "env", "user", "lan", "tailscale", "lan_ports", "tailnet_ports", "model",
           "customer", "location", "note", "modules", "flash", "drive", "image",
           "wifi_ssid", "wifi_country"]
ENVS = ("test", "customer")
LEVELS = ("read", "change", "danger")
REMOTE_TOOL = "/opt/pikit/bin/pk-tool"
IMAGES = {
    "lite": "https://downloads.raspberrypi.com/raspios_lite_arm64_latest",
    "desktop": "https://downloads.raspberrypi.com/raspios_arm64_latest",
}
IMAGER = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Raspberry Pi Ltd" / "Imager" / "rpi-imager.exe"
MAX_CARD_GB = 512


def _openssh(name: str) -> str:
    """Na Windows vždy systémové OpenSSH, ať je jedno, odkud se pikit spouští."""
    win = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "OpenSSH" / f"{name}.exe"
    return str(win) if win.exists() else name


SSH = os.environ.get("PIKIT_SSH") or _openssh("ssh")   # PIKIT_SSH jen pro testy
SCP = _openssh("scp")
SSH_KEYGEN = _openssh("ssh-keygen")

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def step(text: str) -> None:
    print(f"\n== {text}")


def info(text: str = "") -> None:
    print(f"   {text}" if text else "")


def fail(text: str, code: int = 1) -> "NoReturn":  # type: ignore[name-defined]
    print(f"Chyba: {text}", file=sys.stderr)
    sys.exit(code)


# --- moduly ---------------------------------------------------------------

@dataclass(frozen=True)
class Module:
    name: str
    order: int
    form: str
    default: bool
    requires: tuple[str, ...]
    phase: str  # bootstrap | verified (až po ověření spojení přes Tailscale)


def load_modules() -> list[Module]:
    """Modul je soubor device/modules/NN-jméno.sh. Formulář vzniká z jeho hlavičky."""
    modules = []
    for path in sorted(MODULES_DIR.glob("*.sh")):
        order, name = path.stem.split("-", 1)
        meta: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"# (form|default|requires|phase):\s*(.*)$", line)
            if m:
                meta[m.group(1)] = m.group(2).strip()
            elif not line.startswith("#"):
                break
        modules.append(Module(name, int(order), meta["form"], meta.get("default", "ne") == "ano",
                              tuple(meta.get("requires", "").split()), meta.get("phase", "bootstrap")))
    return modules


# --- formulář -------------------------------------------------------------

@dataclass(frozen=True)
class Field:
    key: str
    label: str
    default: str = ""


DEVICE_FIELDS = [
    Field("name", "Jméno zařízení"),
    Field("env", "Prostředí (test/customer)", "test"),
    Field("model", "Model (např. Pi 5)"),
    Field("user", "Uživatel", "admin"),
    Field("customer", "Zákazník"),
    Field("location", "Umístění"),
    Field("note", "Poznámka"),
]
SYSTEM_FIELDS = [
    Field("flash", "Nahrát systém na kartu (ano/ne)", "ano"),
    Field("drive", "Karta (písmeno disku, nebo disk 4)"),
    Field("image", "Obraz systému (lite/desktop)", "lite"),
]
NETWORK_FIELDS = [
    Field("wifi", "Wi-Fi (název sítě, nebo ne)", "ne"),
    Field("wifi_country", "Země Wi-Fi", "CZ"),
    Field("lan_ports", "Porty do místní sítě (např. 8080, nebo ne)", "ne"),
    Field("tailnet_ports", "Porty přes Tailscale (např. 8080, nebo ne)", "ne"),
]
ALL_FIELDS = DEVICE_FIELDS + SYSTEM_FIELDS + NETWORK_FIELDS


def render_form() -> str:
    def lines(fields):
        return [f"{f.label}: {f.default}".rstrip() for f in fields]
    modules = [f"{m.form} (ano/ne): {'ano' if m.default else 'ne'}" for m in load_modules()]
    return "\n".join([
        "=== Nové Raspberry Pi ===",
        *lines(DEVICE_FIELDS),
        "",
        "--- Systém ---",
        *lines(SYSTEM_FIELDS),
        "",
        "--- Síť ---",
        *lines(NETWORK_FIELDS),
        "",
        "--- Moduly ---",
        *modules,
        "",
        "# Hesla ani klíče sem nepiš, heslo k Wi-Fi zadáš až v terminálu.",
    ])


def _norm(text: str) -> str:
    text = re.sub(r"\(.*?\)", "", text)
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(plain.lower().split())


def _yes_no(value: str) -> bool | None:
    return {"ano": True, "a": True, "yes": True, "y": True,
            "ne": False, "n": False, "no": False}.get(_norm(value))


def _ports(value: str) -> str | None:
    """Vrátí porty oddělené mezerou, nebo None, když jsou neplatné."""
    if _yes_no(value) is False or not value.strip():
        return ""
    ports = re.split(r"[,\s]+", value.strip())
    for p in ports:
        m = re.fullmatch(r"(\d{1,5})(/(tcp|udp))?", p)
        if not m or not 1 <= int(m.group(1)) <= 65535:
            return None
    return " ".join(ports)


def _valid_name(name: str) -> bool:
    return re.fullmatch(r"[a-z][a-z0-9-]{1,30}[a-z0-9]", name) is not None


def _valid_user(user: str) -> bool:
    return re.fullmatch(r"[a-z_][a-z0-9_-]{0,30}", user) is not None


def _normalize_drive(value: str) -> str | None:
    value = value.strip()
    if re.fullmatch(r"[A-Za-z]:?\\?", value):
        return value[0].upper() + ":"
    m = re.fullmatch(r"(?i)disk\s*(\d+)", value)
    return f"disk {m.group(1)}" if m else None


def parse_form(text: str) -> tuple[dict, list[str]]:
    """Z vyplněného formuláře udělá záznam zařízení. Vrací (záznam, chyby)."""
    errors: list[str] = []
    modules = load_modules()
    field_by_label = {_norm(f.label): f for f in ALL_FIELDS}
    module_by_label = {_norm(m.form): m for m in modules}
    values: dict[str, str] = {}
    choices: dict[str, str] = {}

    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(("#", "===", "---", "```")):
            continue
        if re.search(r"tskey-|BEGIN [A-Z ]*PRIVATE KEY", line):
            errors.append(f"Řádek {number} vypadá jako tajný klíč. Smaž ho, do formuláře nepatří.")
            continue
        if ":" not in line:
            errors.append(f"Řádku {number} nerozumím (chybí dvojtečka).")
            continue
        label, value = (s.strip() for s in line.split(":", 1))
        key = _norm(label)
        if key in field_by_label:
            values[field_by_label[key].key] = value
        elif key in module_by_label:
            choices[module_by_label[key].name] = value
        elif re.search(r"heslo|password|passphrase", key):
            errors.append(f"Řádek {number}: hesla do formuláře nepatří. Smaž ho.")
        else:
            errors.append(f"Neznámá položka '{label}'.")

    for f in ALL_FIELDS:
        values.setdefault(f.key, f.default)

    selected: list[str] = []
    for m in modules:
        answer = _yes_no(choices.get(m.name, "ano" if m.default else "ne"))
        if answer is None:
            errors.append(f"{m.form}: vyber ano, nebo ne.")
        elif answer:
            selected.append(m.name)
    by_name = {m.name: m for m in modules}
    for name in selected:
        for need in by_name[name].requires:
            if need not in selected:
                errors.append(f"{by_name[name].form} potřebuje modul {by_name[need].form}.")

    if not values["name"]:
        errors.append("Jméno zařízení je povinné.")
    elif not _valid_name(values["name"]):
        errors.append("Jméno zařízení: jen malá písmena bez diakritiky, číslice a pomlčka, 3–32 znaků.")
    if values["env"] not in ENVS:
        errors.append("Prostředí: test, nebo customer.")
    if not _valid_user(values["user"]):
        errors.append("Uživatel: malá písmena bez diakritiky, Linux jiné nepřijme.")
    if values["image"] not in IMAGES:
        errors.append("Obraz systému: lite, nebo desktop.")
    if not re.fullmatch(r"[A-Za-z]{2}", values["wifi_country"]):
        errors.append("Země Wi-Fi: dvě písmena, např. CZ.")

    flash = _yes_no(values["flash"])
    if flash is None:
        errors.append("Nahrát systém na kartu: vyber ano, nebo ne.")
    drive = values["drive"]
    if drive:
        drive = _normalize_drive(drive)
        if drive is None:
            errors.append("Karta: zadej písmeno disku (F:), nebo číslo (disk 4).")
    elif flash:
        errors.append("Karta: při nahrání systému je povinná. Zadej písmeno disku (F:), nebo číslo (disk 4).")

    for key, label in (("lan_ports", "Porty do místní sítě"), ("tailnet_ports", "Porty přes Tailscale")):
        ports = _ports(values[key])
        if ports is None:
            errors.append(f"{label}: čísla portů oddělená čárkou, nebo ne.")
        else:
            values[key] = ports

    wifi = values["wifi"].strip()
    ssid = "" if _yes_no(wifi) is False else wifi
    device = {c: "" for c in COLUMNS}
    device.update({k: values[k] for k in ("name", "env", "model", "user", "customer", "location", "note",
                                          "image", "lan_ports", "tailnet_ports")})
    device.update(modules=" ".join(selected), flash="ano" if flash else "ne", drive=drive or "",
                  wifi_ssid=ssid, wifi_country=values["wifi_country"].upper(),
                  lan=f"{values['name']}.local")
    return device, errors


def plan_lines(d: dict) -> list[str]:
    """Postup pro konkrétní zařízení. Co vyžaduje člověka, je označené."""
    selected = d["modules"].split()
    name = d["name"]
    steps = []
    if not KEY.with_suffix(".pub").exists() and "ssh" in selected:
        steps.append("pikit key")
    if d["flash"] == "ano":
        steps.append(f"pikit flash {name}  (SMAŽE kartu {d['drive']}; ukáže kontrolní kód pro --confirm; okno správce)")
    secret = d["wifi_ssid"] or "ssh" not in selected
    steps.append(f"pikit card {name}" + ("  (v terminálu, zeptá se na heslo)" if secret else ""))
    steps.append("Člověk: kartu vysunout, vložit do Pi, připojit síť a napájení, 2–3 minuty počkat.")
    if "ssh" in selected:
        steps.append(f"pikit init {name}" + ("  (v terminálu, vypíše odkaz k přihlášení do Tailscale)"
                                            if "tailscale" in selected else ""))
    if "tailscale" in selected:
        steps.append("Člověk: v Tailscale admin konzoli u zařízení vypnout Key expiry.")
    return steps


def cmd_form(_args) -> None:
    print(render_form())


def cmd_plan(args) -> None:
    text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8-sig")
    device, errors = parse_form(text)
    if errors:
        print("Formulář je potřeba opravit:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(2)

    devices = load_devices()
    old = next((x for x in devices if x["name"] == device["name"]), None)
    if old:
        device["tailscale"] = old["tailscale"]
        devices[devices.index(old)] = device
    else:
        devices.append(device)
    save_devices(devices)
    sync_ssh_config(quiet=True)

    by_name = {m.name: m.form for m in load_modules()}
    step(f"Plán pro {device['name']} ({device['env']})")
    info("Moduly: " + (", ".join(by_name[m] for m in device["modules"].split()) or "žádné"))
    if device["lan_ports"]:
        info("Do místní sítě otevřít: " + device["lan_ports"])
    if device["tailnet_ports"]:
        info("Přes Tailscale otevřít: " + device["tailnet_ports"])
    if device["wifi_ssid"]:
        info("Wi-Fi: " + device["wifi_ssid"])
    print()
    for i, line in enumerate(plan_lines(device), 1):
        info(f"{i}. {line}")


# --- seznam zařízení ------------------------------------------------------

def load_devices() -> list[dict]:
    if not DEVICES_CSV.exists():
        return []
    with DEVICES_CSV.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return [{c: (r.get(c) or "").strip() for c in COLUMNS} for r in rows]


def save_devices(devices: list[dict]) -> None:
    with DEVICES_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, quoting=csv.QUOTE_ALL)
        w.writeheader()
        for d in sorted(devices, key=lambda d: d["name"]):
            w.writerow({c: d.get(c, "") for c in COLUMNS})


def get_device(name: str) -> dict:
    for d in load_devices():
        if d["name"] == name:
            return d
    known = ", ".join(d["name"] for d in load_devices()) or "žádná"
    fail(f"zařízení '{name}' není v devices.csv (známá: {known}). Nové přidej přes pikit plan.")


def public_key() -> str:
    pub = KEY.with_suffix(".pub")
    if not pub.exists():
        fail("chybí SSH klíč. Nejdřív spusť: pikit key")
    return pub.read_text(encoding="utf-8").strip()


# --- SSH ------------------------------------------------------------------

def _ssh_base() -> list[str]:
    return [sys.executable, SSH] if SSH.endswith(".py") else [SSH]


def ssh(host: str, remote: str | None = None, *, batch: bool = True, tty: bool = False,
        capture: bool = True, connect_timeout: int = 10, timeout: float | None = None):
    args = _ssh_base() + ["-o", f"ConnectTimeout={connect_timeout}"]
    if batch:
        args += ["-o", "BatchMode=yes"]
    if tty:
        args.append("-t")
    args.append(host)
    if remote:
        args.append(remote)
    try:
        if capture:
            return subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=timeout)
        return subprocess.run(args, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, "", f"Vypršel čas ({timeout} s).\n")


def remote_cmd(*parts: str) -> str:
    return " ".join(shlex.quote(p) for p in parts)


def remove_known_host(host: str) -> None:
    kh = SSH_DIR / "known_hosts"
    if host and kh.exists():
        subprocess.run([SSH_KEYGEN, "-R", host, "-f", str(kh)], capture_output=True, text=True)


def write_unix(path: Path, text: str) -> None:
    """UTF-8 bez BOM a s LF. cloud-init i OpenSSH jinak soubor špatně přečtou."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def sync_ssh_config(quiet: bool = False) -> None:
    devices = load_devices()
    lines = ["# Vygenerováno příkazem 'pikit sync-ssh' z devices.csv.",
             "# Ruční úpravy se přepíšou.", ""]

    def block(alias: str, host: str, user: str) -> None:
        lines.extend([f"Host {alias}", f"  HostName {host}", f"  User {user}",
                      f"  IdentityFile {KEY.as_posix()}", "  IdentitiesOnly yes",
                      "  StrictHostKeyChecking accept-new", "  ServerAliveInterval 30", ""])

    for d in devices:
        lan = d["lan"] or f"{d['name']}.local"
        block(d["name"], d["tailscale"] or lan, d["user"])
        block(f"{d['name']}-lan", lan, d["user"])

    SSH_DIR.mkdir(parents=True, exist_ok=True)
    write_unix(PK_SSH_CONFIG, "\n".join(lines) + "\n")

    # Include musí být na začátku ~/.ssh/config, jinak by patřil pod předchozí blok Host.
    current = SSH_CONFIG.read_text(encoding="utf-8") if SSH_CONFIG.exists() else ""
    if not re.search(r"(?mi)^\s*Include\s+pikit_config\s*$", current):
        write_unix(SSH_CONFIG, "Include pikit_config\n\n" + current.replace("\r\n", "\n"))
    if not quiet:
        info(f"SSH zkratky pro {len(devices)} zařízení -> {PK_SSH_CONFIG}")


def cmd_key(_args) -> None:
    step("SSH klíč")
    if KEY.exists():
        info(f"Klíč už existuje: {KEY}")
    else:
        SSH_DIR.mkdir(parents=True, exist_ok=True)
        info("ssh-keygen se zeptá na heslo ke klíči. Bez hesla (Enter) funguje i agentovi.")
        r = subprocess.run([SSH_KEYGEN, "-t", "ed25519", "-f", str(KEY), "-C",
                            f"pikit-{os.environ.get('USERNAME', 'user')}@{os.environ.get('COMPUTERNAME', 'pc')}"])
        if r.returncode != 0:
            fail("ssh-keygen selhal.")
    info("Veřejná část:")
    info(public_key())


def cmd_sync(_args) -> None:
    step("SSH zkratky")
    sync_ssh_config()


# --- pikit flash ----------------------------------------------------------

@dataclass(frozen=True)
class Disk:
    number: int
    model: str
    bus: str
    size: int
    serial: str
    is_boot: bool
    is_system: bool

    @property
    def gb(self) -> int:
        return round(self.size / 1024 ** 3)

    @property
    def token(self) -> str:
        """Kontrolní kód: změní se, když je ve čtečce jiná karta nebo se číslo disku posune."""
        digest = hashlib.sha256(f"{self.number}|{self.model}|{self.size}|{self.serial}".encode()).hexdigest()[:4]
        return f"DISK{self.number}-{self.gb}GB-{digest}"


def disk_problem(disk: Disk) -> str | None:
    if disk.is_boot or disk.is_system:
        return "je to systémový disk tohoto PC"
    if disk.bus not in ("USB", "SD", "MMC"):
        return f"není to karta ani USB zařízení (sběrnice {disk.bus})"
    if disk.gb > MAX_CARD_GB:
        return f"má {disk.gb} GB, na SD kartu je to podezřele velké"
    return None


def _powershell(script: str) -> str:
    r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        fail(f"PowerShell selhal: {r.stderr.strip()}")
    return r.stdout.strip()


PS_DISK = ("Select-Object Number,FriendlyName,@{n='Bus';e={[string]$_.BusType}},Size,SerialNumber,IsBoot,IsSystem"
           " | ConvertTo-Json -Compress")


def _to_disk(raw: dict) -> Disk:
    return Disk(int(raw["Number"]), (raw["FriendlyName"] or "").strip(), raw["Bus"], int(raw["Size"]),
                (raw["SerialNumber"] or "").strip(), bool(raw["IsBoot"]), bool(raw["IsSystem"]))


def list_disks() -> list[Disk]:
    out = _powershell("[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); @(Get-Disk) | " + PS_DISK)
    raw = json.loads(out) if out else []
    return [_to_disk(r) for r in (raw if isinstance(raw, list) else [raw])]


def resolve_disk(drive: str) -> Disk:
    m = re.fullmatch(r"disk (\d+)", drive)
    if m:
        number = int(m.group(1))
    else:
        out = _powershell(f"$p=Get-Partition -DriveLetter {drive[0]} -ErrorAction SilentlyContinue;"
                          "if($p){$p.DiskNumber}")
        if not out:
            usable = [d for d in list_disks() if not disk_problem(d)]
            hint = ", ".join(f"disk {d.number} ({d.model}, {d.gb} GB)" for d in usable) or "žádná karta nenalezena"
            fail(f"disk {drive} neexistuje. Možné karty: {hint}.")
        number = int(out)
    found = [d for d in list_disks() if d.number == number]
    if not found:
        fail(f"disk {number} neexistuje.")
    return found[0]


def _fetch_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode("utf-8")


def resolve_image(url: str) -> tuple[str, str]:
    """Skutečná adresa obrazu a jeho oficiální SHA-256."""
    with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=30) as r:
        final = r.geturl()
    return final, _fetch_text(final + ".sha256").split()[0].lower()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def download_image(url: str, expected: str, cache: Path | None = None) -> Path:
    """Stáhne obraz do mezipaměti. Nesouhlasí-li kontrolní součet, soubor zahodí a skončí."""
    cache = cache or CACHE_DIR
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / url.rsplit("/", 1)[1]
    if target.exists() and sha256_file(target) == expected:
        info(f"Obraz už je stažený: {target.name}")
        return target
    partial = target.with_name(target.name + ".part")
    info(f"Stahuji {target.name}")
    with urllib.request.urlopen(url, timeout=60) as r, partial.open("wb") as f:
        while chunk := r.read(1024 * 1024):
            f.write(chunk)
    if sha256_file(partial) != expected:
        partial.unlink()
        fail("stažený obraz nesouhlasí s oficiálním kontrolním součtem.")
    partial.replace(target)
    return target


def cmd_flash(args) -> None:
    d = get_device(args.name)
    if os.name != "nt":
        fail("Zápis karty zatím umí jen Windows.")
    drive = args.drive or d["drive"]
    if not drive:
        fail("není známá karta. Přidej --drive F:")
    drive = _normalize_drive(drive) or fail("neplatná karta, zadej F: nebo disk 4.")

    step("Kontrola karty")
    disk = resolve_disk(drive)
    info(f"Disk {disk.number}: {disk.model}, {disk.bus}, {disk.gb} GB")
    problem = disk_problem(disk)
    if problem:
        fail(f"na disk {disk.number} nezapíšu: {problem}.", 3)
    if args.confirm != disk.token:
        print(f"\nCELÝ obsah disku {disk.number} ({disk.model}, {disk.gb} GB) se nevratně smaže.")
        print(f"Pokud je to správná karta, spusť:\n  pikit flash {d['name']} --confirm {disk.token}")
        sys.exit(6)
    if not IMAGER.exists():
        fail(f"není nainstalovaný Raspberry Pi Imager ({IMAGER}). Stáhni ho z raspberrypi.com/software.")
    if _powershell("@(Get-Process rpi-imager -ErrorAction SilentlyContinue).Count") != "0":
        fail("Raspberry Pi Imager je otevřený. Zavři ho, ať se s ním nepřetahuje o kartu.")

    step(f"Obraz systému ({d['image'] or 'lite'})")
    url, expected = resolve_image(IMAGES[d["image"] or "lite"])
    image = download_image(url, expected)
    info("Kontrolní součet SHA-256 souhlasí.")

    step(f"Zápis na disk {disk.number}")
    info("Potvrď okno správce. Zápis a ověření trvá několik minut.")
    arguments = f'--cli "{image}" "\\\\.\\PhysicalDrive{disk.number}"'
    code = _powershell(
        f"$p=Start-Process -FilePath '{IMAGER}' -ArgumentList '{arguments}' -Verb RunAs -Wait -PassThru "
        "-WindowStyle Hidden; $p.ExitCode")
    if code != "0":
        fail(f"Imager skončil s chybou (kód {code}). Karta může být nedopsaná, spusť zápis znovu.")
    log_action(d["name"], "flash", "flash", [f"disk={disk.number}", image.name], 0)
    info("Zapsáno a ověřeno.")
    info(f"Další krok: pikit card {d['name']}")
    info("Když karta není vidět, vysuň ji a znovu zasuň.")


# --- pikit card -----------------------------------------------------------

def _is_boot(root: str) -> bool:
    return os.path.isfile(os.path.join(root, "config.txt")) and os.path.isfile(os.path.join(root, "cmdline.txt"))


def find_boot(drive: str | None) -> str:
    if drive and not drive.startswith("disk"):
        root = drive.rstrip(":\\/") + ":\\" if os.name == "nt" else drive
        if _is_boot(root):
            return root
    if os.name != "nt":
        fail("Mimo Windows zadej cestu k boot oddílu přes --drive.")
    import ctypes
    ctypes.windll.kernel32.SetErrorMode(1)       # žádné okno „vložte disk“ u prázdných čteček
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    found = [f"{l}:\\" for i, l in enumerate(string.ascii_uppercase) if mask >> i & 1 and _is_boot(f"{l}:\\")]
    if not found:
        fail("nenašel jsem kartu s Raspberry Pi OS. Je v PC? Případně ji vysuň a zasuň, nebo --drive E:")
    if len(found) > 1:
        fail(f"našel jsem víc karet ({', '.join(found)}). Vyber přes --drive.")
    return found[0]


def build_user_data(name: str, user: str, key: str | None, console_password: str | None = None) -> str:
    """cloud-init pro první start. S klíčem jen SSH, bez klíče heslo na konzoli."""
    parts = [f"""#cloud-config
# Vygenerováno příkazem 'pikit card'. Pi ho přečte jen při úplně prvním startu.

hostname: {name}
manage_etc_hosts: true
timezone: Europe/Prague

# Adresa <jméno>.local v místní síti
packages:
  - avahi-daemon
# Pi nemá hodiny s baterií, při prvním startu může mít špatné datum
apt:
  preserve_sources_list: true
  conf: |
    Acquire {{
      Check-Date "false";
    }};

users:
  - name: {user}
    groups: users,adm,dialout,audio,netdev,video,plugdev,cdrom,games,input,gpio,spi,i2c,render,sudo
    shell: /bin/bash
"""]
    if key:
        parts.append(f"""    lock_passwd: true
    ssh_authorized_keys:
      - {key}
    sudo: ALL=(ALL) NOPASSWD:ALL

enable_ssh: true
ssh_pwauth: false
runcmd:
  - [ systemctl, enable, --now, ssh ]
""")
    else:
        parts.append(f"""    lock_passwd: false
    sudo: ALL=(ALL) ALL

# Heslo pro přihlášení na konzoli, při prvním přihlášení se musí změnit.
chpasswd:
  expire: true
  users:
    - name: {user}
      password: {json.dumps(console_password or "", ensure_ascii=False)}
      type: text
ssh_pwauth: false
""")
    return "".join(parts)


NETWORK_CONFIG = """network:
  version: 2
  wifis:
    renderer: NetworkManager
    wlan0:
      dhcp4: true
      regulatory-domain: {country}
      access-points:
        {ssid}:
          password: {password}
      optional: true
"""


def _backup_write(root: Path, fname: str) -> Path:
    src, bak = root / fname, root / f"{fname}.orig"
    if src.exists() and not bak.exists():
        bak.write_bytes(src.read_bytes())
    return src


def cmd_card(args) -> None:
    d = get_device(args.name)
    selected = d["modules"].split()
    use_ssh = "ssh" in selected
    key = public_key() if use_ssh else None

    password = None
    if not use_ssh:
        password = getpass.getpass(f"   Heslo pro uživatele {d['user']} na konzoli: ")
        if not password:
            fail("prázdné heslo.")
    wifi_password = None
    if d["wifi_ssid"]:
        wifi_password = getpass.getpass(f"   Heslo k Wi-Fi '{d['wifi_ssid']}': ")
        if not wifi_password:
            fail("prázdné heslo k Wi-Fi.")

    step("Hledám boot oddíl SD karty")
    root = Path(find_boot(args.drive or d["drive"]))
    info(f"Boot oddíl: {root}")

    step("Zapisuji první nastavení")
    write_unix(_backup_write(root, "user-data"), build_user_data(d["name"], d["user"], key, password))
    # Každý zápis karty má vlastní instance-id, aby se konfigurace opravdu použila.
    instance = f"pikit-{d['name']}-{int(dt.datetime.now().timestamp())}"
    write_unix(_backup_write(root, "meta-data"), f"instance-id: {instance}\n")
    cmdline_path = _backup_write(root, "cmdline.txt")
    cmdline = cmdline_path.read_text(encoding="utf-8").split()
    write_unix(cmdline_path, " ".join([t for t in cmdline if not t.startswith("ds=")]
                                      + [f"ds=nocloud;i={instance}"]) + "\n")
    info(f"Hostname {d['name']}, uživatel {d['user']}, {'SSH klíč' if use_ssh else 'heslo na konzoli'}.")

    if d["wifi_ssid"]:
        q = lambda s: json.dumps(s, ensure_ascii=False)   # JSON řetězec je platný YAML
        write_unix(_backup_write(root, "network-config"),
                   NETWORK_CONFIG.format(country=q(d["wifi_country"] or "CZ"), ssid=q(d["wifi_ssid"]),
                                         password=q(wifi_password)))
        info(f"Wi-Fi {d['wifi_ssid']} nastavena. Heslo je na kartě čitelně, kartu nikde nenechávej.")
    else:
        info("Bez Wi-Fi: Pi se připojí kabelem přes DHCP.")

    # Nová instalace: stará Tailscale adresa a otisky SSH už neplatí.
    devices = load_devices()
    row = next(x for x in devices if x["name"] == d["name"])
    if row["tailscale"]:
        info("Zařízení se instaluje znovu. Starý stroj smaž v Tailscale admin konzoli, jinak se nový přihlásí jako jméno-1.")
        remove_known_host(row["tailscale"])
        row["tailscale"] = ""
    remove_known_host(row["lan"])
    save_devices(devices)
    sync_ssh_config(quiet=True)

    step("Co dál")
    info("Kartu bezpečně vysuň, vlož do Pi, připoj síť a nakonec napájení. První start trvá 2–3 minuty.")
    if use_ssh:
        info(f"Pak: pikit init {d['name']}")


def cmd_unlock_card(args) -> None:
    step("Servisní odemčení SSH z místní sítě")
    root = find_boot(args.drive)
    (Path(root) / "pikit-unlock-ssh").write_text("Smaže se při startu Pi.\n", encoding="utf-8")
    info("Kartu vrať do Pi a zapni ho. Při startu otevře SSH z místní sítě a soubor smaže.")
    info("Pak: ssh <jméno>-lan. Zpátky zavřeš: sudo /opt/pikit/bin/pk-firewall lock")


# --- pikit init -----------------------------------------------------------

def bootstrap_command(modules: list[str], d: dict) -> str:
    env = (f"MODULES={shlex.quote(' '.join(modules))} LAN_PORTS={shlex.quote(d['lan_ports'])} "
           f"TAILNET_PORTS={shlex.quote(d['tailnet_ports'])}")
    return f"{env} bash /tmp/pikit-setup/bootstrap.sh"


def split_phases(selected: list[str], only: list[str] | None) -> tuple[list[str], list[str]]:
    """Moduly k instalaci ve správném pořadí: (hned, až po ověření Tailscale)."""
    known = load_modules()
    names = {m.name for m in known}
    wanted = only if only is not None else selected
    unknown = [w for w in wanted if w not in names]
    if unknown:
        fail(f"neznámé moduly: {', '.join(unknown)}. Známé: {', '.join(sorted(names))}.")
    chosen = [m for m in known if m.name in wanted]
    return ([m.name for m in chosen if m.phase == "bootstrap"],
            [m.name for m in chosen if m.phase == "verified"])


def _upload(alias: str) -> None:
    ssh(alias, "rm -rf /tmp/pikit-setup")
    if subprocess.run([SCP, "-q", "-r", str(DEVICE_DIR), f"{alias}:/tmp/pikit-setup"]).returncode != 0:
        fail("scp selhalo.")


def cmd_init(args) -> None:
    d = get_device(args.name)
    name = d["name"]
    selected = d["modules"].split()
    if "ssh" not in selected and args.only is None:
        fail(f"{name} nemá modul SSH, na dálku se na něj nedostanu.")
    now, verified = split_phases(selected, args.only.split(",") if args.only is not None else None)
    alias = name if d["tailscale"] else f"{name}-lan"

    step(f"Spojení s {alias}")
    if ssh(alias, "true", batch=False, capture=False, connect_timeout=10).returncode != 0:
        info("Nejčastější příčiny: Pi ještě startuje, Windows nezná <jméno>.local (zapiš IP do sloupce lan")
        info("a spusť pikit sync-ssh), nebo je SSH z místní sítě už zavřené.")
        fail(f"SSH na {alias} selhalo.")

    if now:
        step("Moduly: " + ", ".join(now))
        _upload(alias)
        r = ssh(alias, bootstrap_command(now, d) + "; rc=$?; rm -rf /tmp/pikit-setup; exit $rc",
                batch=False, tty=True, capture=False)
        if r.returncode != 0:
            fail(f"instalace skončila chybou (kód {r.returncode}). Výpis je výše, pikit init jde spustit znovu.")

    via = alias
    if "tailscale" in now:
        step("Zapisuji Tailscale adresu")
        out = ssh(alias, "tailscale ip -4").stdout.strip().splitlines()
        ip = out[0].strip() if out else ""
        if not re.fullmatch(r"100\.\d+\.\d+\.\d+", ip):
            fail(f"nepodařilo se zjistit Tailscale IP (dostal jsem '{ip}').")
        devices = load_devices()
        next(x for x in devices if x["name"] == name)["tailscale"] = ip
        save_devices(devices)
        sync_ssh_config(quiet=True)
        info(f"{name} -> {ip}")

    if verified:
        step("Ověřuji spojení přes Tailscale")
        if ssh(name, "true", connect_timeout=15).returncode == 0:
            via = name
            _upload(name)
            r = ssh(name, bootstrap_command(verified, d) + "; rc=$?; rm -rf /tmp/pikit-setup; exit $rc", capture=False)
            if r.returncode != 0:
                info("Modul po ověření selhal, přístup z místní sítě zůstává otevřený.")
        else:
            info(f"Přes Tailscale to zatím nejde, přístup z místní sítě nechávám. Pak spusť pikit init {name} znovu.")

    if args.only is None and sys.stdin.isatty() and ssh(via, "test -f /var/run/reboot-required").returncode == 0:
        if input("   Aktualizace chtějí restart. Restartovat Pi teď? [A/n] ").strip().lower() in ("", "a", "ano", "y", "yes"):
            ssh(via, "sudo systemd-run --on-active=3 /bin/systemctl reboot")

    step("Hotovo")
    info(f"Připojení: ssh {name}")
    if "agent-tools" in selected:
        info(f"Nástroje: pikit tools {name}")
    if "tailscale" in now:
        info("V Tailscale admin konzoli u zařízení vypni Key expiry, jinak se za 180 dní odhlásí.")


# --- pikit devices / tools / help / read / change / danger ---------------

def cmd_devices(args) -> None:
    devices = load_devices()
    if not args.no_check and devices:
        with ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(lambda d: ssh(d["name"], "true", connect_timeout=5, timeout=20).returncode == 0, devices))
        for d, ok in zip(devices, results):
            d["online"] = "online" if ok else "offline"
    if args.json:
        print(json.dumps(devices, ensure_ascii=False, indent=2))
        return
    if not devices:
        info("Žádná zařízení. Začni: pikit form")
    for d in devices:
        place = ", ".join(x for x in (d["customer"], d["location"], d["note"]) if x)
        print(f"{d['name']:<22} {d['env'] or '?':<9} {d.get('online', '-'):<8} "
              f"{'Tailscale' if d['tailscale'] else 'LAN':<10} {d['model']:<6} {place}")


def _remote_error(r, name: str) -> None:
    msg = (r.stderr or r.stdout).strip()
    if r.returncode == 127 or ("pk-tool" in msg and "not found" in msg):
        fail(f"na {name} nejsou nainstalované nástroje. Spusť: pikit init {name} --only agent-tools")
    if r.returncode == 255:
        fail(f"nepřipojil jsem se k {name}: {msg}")
    fail(msg or f"chyba (kód {r.returncode})", r.returncode or 1)


def cmd_tools(args) -> None:
    d = get_device(args.device)
    r = ssh(d["name"], remote_cmd(REMOTE_TOOL, "list"), timeout=30)
    if r.returncode != 0:
        _remote_error(r, d["name"])
    tools = []
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            tools.append({"level": parts[0], "tool": parts[1], "desc": parts[2]})
    if args.json:
        print(json.dumps(tools, ensure_ascii=False, indent=2))
        return
    for t in tools:
        print(f"{t['level']:<7} {t['tool']:<14} {t['desc']}")
    if d["env"] == "customer":
        print("\n(zařízení zákazníka: nástroje úrovně danger pikit odmítne)")


def cmd_help(args) -> None:
    d = get_device(args.device)
    r = ssh(d["name"], remote_cmd(REMOTE_TOOL, "help", args.tool), timeout=30)
    if r.returncode != 0:
        _remote_error(r, d["name"])
    print(r.stdout.rstrip())


def log_action(device: str, level: str, tool: str, tool_args: list[str], code: int) -> None:
    ACTION_LOG.parent.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().isoformat(timespec="seconds")
    with ACTION_LOG.open("a", encoding="utf-8") as f:
        f.write(f"{stamp}\t{device}\t{level}\t{tool}\t{shlex.join(tool_args)}\texit={code}\n")


def cmd_run(args) -> None:
    level = args.level
    d = get_device(args.device)
    if level == "danger" and d["env"] == "customer":
        fail(f"{d['name']} je zařízení zákazníka, nástroje úrovně danger jsou zakázané.", 5)
    r = ssh(d["name"], remote_cmd(REMOTE_TOOL, "run", level, args.tool, *args.args), timeout=args.timeout)
    log_action(d["name"], level, args.tool, args.args, r.returncode)
    if r.returncode in (127, 255) and not r.stdout:
        _remote_error(r, d["name"])
    if args.json:
        print(json.dumps({"device": d["name"], "level": level, "tool": args.tool, "args": args.args,
                          "exit": r.returncode, "output": r.stdout, "error": r.stderr},
                         ensure_ascii=False, indent=2))
    else:
        if r.stdout:
            print(r.stdout, end="" if r.stdout.endswith("\n") else "\n")
        if r.stderr:
            print(r.stderr, end="", file=sys.stderr)
    sys.exit(r.returncode)


# --- argumenty ------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(prog="pikit", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", metavar="příkaz")

    sub.add_parser("form", help="vypíše formulář").set_defaults(func=cmd_form)

    s = sub.add_parser("plan", help="zkontroluje formulář a vypíše postup")
    s.add_argument("file", help="soubor s formulářem, nebo - pro stdin")
    s.set_defaults(func=cmd_plan)

    sub.add_parser("key", help="vytvoří SSH klíč").set_defaults(func=cmd_key)

    s = sub.add_parser("flash", help="nahraje systém na kartu")
    s.add_argument("name")
    s.add_argument("--drive", help="např. F: nebo 'disk 4'")
    s.add_argument("--confirm", help="kontrolní kód, který vypíše běh bez této volby")
    s.set_defaults(func=cmd_flash)

    s = sub.add_parser("card", help="zapíše na kartu první nastavení")
    s.add_argument("name")
    s.add_argument("--drive", help="písmeno boot oddílu, např. E:")
    s.set_defaults(func=cmd_card)

    s = sub.add_parser("unlock-card", help="servisní soubor na kartu: otevře SSH z LAN")
    s.add_argument("--drive", help="písmeno boot oddílu, např. E:")
    s.set_defaults(func=cmd_unlock_card)

    s = sub.add_parser("init", help="nainstaluje moduly na běžící Pi")
    s.add_argument("name")
    s.add_argument("--only", help="jen tyto moduly, oddělené čárkou")
    s.set_defaults(func=cmd_init)

    sub.add_parser("sync-ssh", help="vygeneruje SSH zkratky").set_defaults(func=cmd_sync)

    s = sub.add_parser("devices", help="seznam zařízení")
    s.add_argument("--json", action="store_true")
    s.add_argument("--no-check", action="store_true", help="nezkoušet, kdo je online")
    s.set_defaults(func=cmd_devices)

    s = sub.add_parser("tools", help="nástroje zařízení")
    s.add_argument("--json", action="store_true")
    s.add_argument("device")
    s.set_defaults(func=cmd_tools)

    s = sub.add_parser("help", help="nápověda k nástroji")
    s.add_argument("device")
    s.add_argument("tool")
    s.set_defaults(func=cmd_help)

    for level in LEVELS:
        s = sub.add_parser(level, help=f"spustí nástroj úrovně {level}")
        s.add_argument("--json", action="store_true")
        s.add_argument("--timeout", type=float, default=900, help="max. sekund (výchozí 900)")
        s.add_argument("device")
        s.add_argument("tool")
        s.add_argument("args", nargs=argparse.REMAINDER)
        s.set_defaults(func=cmd_run, level=level)

    args = p.parse_args()
    if not getattr(args, "func", None):
        p.print_help()
        sys.exit(0)
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)

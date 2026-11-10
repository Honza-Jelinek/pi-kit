import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("pikit", ROOT / "bin" / "pikit.py")
pikit = importlib.util.module_from_spec(spec)
sys.modules["pikit"] = pikit
spec.loader.exec_module(pikit)


def filled(**changes):
    """Výchozí formulář s vyplněnými povinnými položkami a změnami podle popisku."""
    lines = pikit.render_form().splitlines()
    changes = {"Jméno zařízení": "pi-01", "Karta": "F:", **changes}
    out = []
    for line in lines:
        for label, value in changes.items():
            if line.startswith(label):
                line = f"{line.split(':', 1)[0]}: {value}"
        out.append(line)
    return "\n".join(out)


def test_default_form_parses():
    device, errors = pikit.parse_form(filled())
    assert errors == []
    assert device["name"] == "pi-01" and device["drive"] == "F:" and device["flash"] == "ano"
    assert device["modules"].split() == ["ssh", "system-update", "auto-updates", "tailscale", "agent-tools",
                                         "tailscale-watch", "firewall", "ssh-only-tailscale"]


def test_empty_form_lists_every_problem():
    _, errors = pikit.parse_form(pikit.render_form())
    assert any("Jméno" in e for e in errors) and any("Karta" in e for e in errors)


def test_user_style_form_with_short_labels():
    device, errors = pikit.parse_form(
        "Jméno zařízení: abc\nSSH: ano\nTailscale: ne\nHlídač Tailscale: ne\n"
        "SSH jen přes Tailscale: ne\nNahrát systém na kartu: ne\n")
    assert errors == []
    assert "tailscale" not in device["modules"].split() and device["flash"] == "ne"


def test_unfilled_choice_is_rejected():
    _, errors = pikit.parse_form(filled(**{"SSH (ano/ne)": "ano/ne"}))
    assert any("SSH: vyber" in e for e in errors)


def test_module_dependencies():
    _, errors = pikit.parse_form(filled(**{"Tailscale (ano/ne)": "ne"}))
    assert any("Hlídač Tailscale potřebuje" in e for e in errors)


def test_ssh_off_requires_all_remote_modules_off():
    labels = ["Aktualizace", "Automatické", "Tailscale (", "Nástroje", "Hlídač", "Firewall", "SSH jen"]
    text = filled(**{"SSH (ano/ne)": "ne", **{l: "ne" for l in labels}})
    device, errors = pikit.parse_form(text)
    assert errors == [] and device["modules"] == ""


@pytest.mark.parametrize("line", ["Heslo k Wi-Fi: tajne", "Password: x", "Auth: tskey-auth-abc"])
def test_secrets_are_refused_without_echo(line):
    _, errors = pikit.parse_form(filled() + "\n" + line)
    assert errors and not any("tajne" in e or "tskey-auth" in e for e in errors)


@pytest.mark.parametrize("value,expected", [("ne", ""), ("8080", "8080"), ("80, 443/tcp", "80 443/tcp")])
def test_ports(value, expected):
    assert pikit._ports(value) == expected


@pytest.mark.parametrize("value", ["99999", "80; rm -rf /", "$(reboot)"])
def test_bad_ports(value):
    assert pikit._ports(value) is None


@pytest.mark.parametrize("value,expected", [("f", "F:"), ("F:", "F:"), ("disk 4", "disk 4"), ("Disk4", "disk 4")])
def test_drive(value, expected):
    assert pikit._normalize_drive(value) == expected


def disk(**changes):
    values = dict(number=4, model="Generic CRW-SD", bus="USB", size=64 * 1024 ** 3, serial="X1",
                  is_boot=False, is_system=False)
    return pikit.Disk(**{**values, **changes})


@pytest.mark.parametrize("changes", [
    {"is_boot": True}, {"is_system": True}, {"bus": "NVMe"}, {"bus": "SATA"}, {"size": 4096 * 1024 ** 3}])
def test_flash_refuses_real_disks(changes):
    assert pikit.disk_problem(disk(**changes))


def test_flash_accepts_card():
    assert pikit.disk_problem(disk()) is None


def test_confirm_token_changes_with_other_card():
    assert disk().token != disk(serial="X2").token
    assert disk().token != disk(number=5).token


def test_flash_needs_token(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(pikit, "get_device", lambda n: {"name": n, "drive": "F:", "image": "lite"})
    monkeypatch.setattr(pikit, "resolve_disk", lambda d: disk())
    monkeypatch.setattr(pikit, "resolve_image", lambda u: pytest.fail("bez kódu se nemá nic stahovat"))
    monkeypatch.setattr(pikit.os, "name", "nt")
    args = type("A", (), {"name": "x", "drive": None, "confirm": "spatny"})
    with pytest.raises(SystemExit) as e:
        pikit.cmd_flash(args)
    assert e.value.code == 6 and disk().token in capsys.readouterr().out


def test_flash_refuses_system_disk_even_with_token(monkeypatch):
    bad = disk(is_system=True)
    monkeypatch.setattr(pikit, "get_device", lambda n: {"name": n, "drive": "C:", "image": "lite"})
    monkeypatch.setattr(pikit, "resolve_disk", lambda d: bad)
    monkeypatch.setattr(pikit.os, "name", "nt")
    with pytest.raises(SystemExit) as e:
        pikit.cmd_flash(type("A", (), {"name": "x", "drive": None, "confirm": bad.token}))
    assert e.value.code == 3


def test_download_verifies_hash(tmp_path):
    source = tmp_path / "os.img.xz"
    source.write_bytes(b"obraz")
    url = source.as_uri()
    good = hashlib.sha256(b"obraz").hexdigest()
    cache = tmp_path / "cache"
    assert pikit.download_image(url, good, cache).read_bytes() == b"obraz"
    source.unlink()  # podruhé jde z mezipaměti
    assert pikit.download_image(url, good, cache).name == "os.img.xz"


def test_download_rejects_wrong_hash(tmp_path):
    source = tmp_path / "os.img.xz"
    source.write_bytes(b"obraz")
    with pytest.raises(SystemExit):
        pikit.download_image(source.as_uri(), "0" * 64, tmp_path / "cache")
    assert not list((tmp_path / "cache").iterdir())


def test_user_data_with_key():
    text = pikit.build_user_data("pi-01", "admin", "ssh-ed25519 AAA x")
    assert "lock_passwd: true" in text and "enable_ssh: true" in text and "ssh-ed25519 AAA x" in text


def test_user_data_console_only():
    text = pikit.build_user_data("pi-01", "admin", None, 'he"slo')
    assert "lock_passwd: false" in text and "expire: true" in text and "enable_ssh" not in text
    assert r'"he\"slo"' in text


def test_phases_and_order():
    now, verified = pikit.split_phases(["firewall", "ssh", "ssh-only-tailscale"], None)
    assert now == ["ssh", "firewall"] and verified == ["ssh-only-tailscale"]


def test_plan_marks_terminal_steps():
    device, _ = pikit.parse_form(filled(**{"Wi-Fi": "Dilna"}))
    text = "\n".join(pikit.plan_lines(device))
    assert "pikit card pi-01  (v terminálu" in text and "SMAŽE kartu F:" in text


@pytest.mark.parametrize("path", sorted(p for p in (ROOT / "device").rglob("*")
                                        if p.is_file() and "systemd" not in p.parts), ids=lambda p: p.name)
def test_device_scripts(path):
    data = path.read_bytes()
    assert b"\r" not in data
    assert subprocess.run(["bash", "-n", path.as_posix()], capture_output=True).returncode == 0

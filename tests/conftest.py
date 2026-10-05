import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GENISO = shutil.which("genisoimage") or shutil.which("mkisofs")
needs_geniso = pytest.mark.skipif(GENISO is None, reason="genisoimage not installed")


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for var in ("VISTAL_HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME",
                "SteamGameId", "SteamAppId", "STEAM_COMPAT_DATA_PATH", "WINEPREFIX",
                "ESDE_APPDATA_DIR", "VISTAL_STEAM_ROOT", "XDG_CURRENT_DESKTOP"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("VISTAL_UI", "none")
    monkeypatch.setenv("VISTAL_NO_MAPPER", "1")
    from vistal import ui
    ui.set_ui(None)
    yield home
    ui.set_ui(None)


def make_tree(root: Path, files: dict[str, bytes | str]) -> Path:
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode())
    return root


def make_iso(out: Path, src: Path, label: str = "TESTDISC", joliet: bool = True, rr: bool = False,
             extra: list[str] | None = None) -> Path:
    args = [GENISO, "-quiet", "-V", label, "-o", str(out)]
    if joliet:
        args += ["-J", "-joliet-long"]
    if rr:
        args += ["-R"]
    args += extra or []
    args.append(str(src))
    subprocess.run(args, check=True)
    return out


def to_raw(iso: Path, out: Path, mode: int = 1, sector: int = 2352) -> Path:
    """Convert a cooked ISO into a raw image (sync + header + data + padding)."""
    data = iso.read_bytes()
    sync = b"\x00" + b"\xff" * 10 + b"\x00"
    with open(out, "wb") as fh:
        for lba in range(len(data) // 2048):
            chunk = data[lba * 2048 : (lba + 1) * 2048]
            m, rem = divmod(lba + 150, 75 * 60)
            s, f = divmod(rem, 75)
            bcd = lambda v: ((v // 10) << 4) | (v % 10)
            header = bytes([bcd(m), bcd(s), bcd(f), mode])
            if mode == 1:
                sec = sync + header + chunk + b"\0" * 288
            else:
                sub = b"\0\0\x08\0" * 2
                sec = sync + header + sub + chunk + b"\0" * 280
            if sector == 2448:
                sec += b"\0" * 96
            fh.write(sec)
    return out


FAKE_PROTON = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
sys.path.insert(0, os.environ["VISTAL_SRC"])
from vistal import lnk

log = Path(os.environ["FAKE_PROTON_LOG"])
verb, program, *args = sys.argv[1:]
compat = Path(os.environ["STEAM_COMPAT_DATA_PATH"])
pfx = compat / "pfx"
dd = pfx / "dosdevices"
if not (pfx / "system.reg").exists():
    (pfx / "drive_c" / "windows" / "system32").mkdir(parents=True, exist_ok=True)
    dd.mkdir(parents=True, exist_ok=True)
    if not (dd / "c:").exists():
        os.symlink("../drive_c", dd / "c:")
    if not (dd / "z:").exists():
        os.symlink("/", dd / "z:")
    (pfx / "system.reg").write_text("WINE REGISTRY Version 2\n")

def unix(win):
    letter, rest = win[0].lower(), win[3:].replace("\\", "/")
    return (dd / f"{letter}:" / rest) if letter != "z" else Path("/" + rest)

entry = {"verb": verb, "program": program, "args": args, "cwd": os.getcwd(),
         "env": {k: v for k, v in os.environ.items() if k.startswith(("PROTON", "STEAM", "WINE", "DXVK", "Steam"))}}
if program == "regedit":
    entry["reg"] = unix(args[1]).read_bytes().decode("cp1252")
elif program.lower().endswith("setup.exe"):
    exe = unix(program)
    entry["installer_exists"] = exe.exists()
    root = unix(program[:3])
    entry["label"] = (root / ".windows-label").read_text().strip()
    entry["serial"] = (root / ".windows-serial").read_text().strip()
    entry["drives"] = sorted(p.name for p in dd.iterdir())
    game = pfx / "drive_c" / "Program Files (x86)" / "Microsoft Games" / "Freelancer"
    (game / "EXE").mkdir(parents=True, exist_ok=True)
    (game / "EXE" / "Freelancer.exe").write_bytes(b"MZ" + b"\0" * 4096)
    (game / "EXE" / "FLServer.exe").write_bytes(b"MZ" + b"\0" * 1024)
    (game / "UNWISE.EXE").write_bytes(b"MZ")
    sm = pfx / "drive_c" / "ProgramData" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Freelancer"
    sm.mkdir(parents=True, exist_ok=True)
    (sm / "Freelancer.lnk").write_bytes(lnk.build("C:\\Program Files (x86)\\Microsoft Games\\Freelancer\\EXE\\Freelancer.exe"))
    (sm / "Uninstall Freelancer.lnk").write_bytes(lnk.build("C:\\Program Files (x86)\\Microsoft Games\\Freelancer\\UNWISE.EXE"))
with open(log, "a") as fh:
    fh.write(json.dumps(entry) + "\n")
sys.exit(int(os.environ.get("FAKE_PROTON_RC", "0")))
'''


@pytest.fixture
def fake_proton(isolated_home, tmp_path, monkeypatch):
    steam = isolated_home / ".steam" / "root"
    common = steam / "steamapps" / "common"
    pdir = common / "Proton 9.0 (Beta)"
    pdir.mkdir(parents=True)
    script = pdir / "proton"
    script.write_text(FAKE_PROTON)
    script.chmod(0o755)
    (pdir / "files" / "bin").mkdir(parents=True)
    log = tmp_path / "proton.jsonl"
    monkeypatch.setenv("FAKE_PROTON_LOG", str(log))
    monkeypatch.setenv("VISTAL_SRC", str(ROOT))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")  # no umu-run
    return {"dir": pdir, "log": log, "steam": steam}


def read_log(path: Path) -> list[dict]:
    import json
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]

"""Integration with emulation frontends.

* ES-DE (EmulationStation Desktop Edition, the frontend EmuDeck installs):
  writes a custom system and a find rule into ~/ES-DE/custom_systems/,
  merging with whatever is already there.
* Classic EmulationStation (RetroPie and friends): es_systems.cfg entry.
* Desktop entries: one .desktop file per installed game, which also makes
  games selectable in Steam's "Add a Non-Steam Game" dialog.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

from . import library, media, paths

SYSTEM_NAME = "gfw"
FULL_NAME = "Games for Windows"
EMULATOR_ID = "VISTAL"


#: Data halves of descriptor/data pairs are left out so a frontend shows one
#: entry per game (.cue not .bin, .mds not .mdf, .img not .ccd). Vistal can
#: still open any of them directly.
FRONTEND_EXTS = media.ROM_EXTS - {".lnk", ".bin", ".mdf", ".ccd"}


def extensions() -> list[str]:
    exts = sorted(FRONTEND_EXTS)
    out = []
    for e in exts:
        out += [e, e.upper()]
    return out


def vistal_command() -> str:
    """Absolute path of the installed launcher script, if we can find it."""
    for cand in (shutil.which("vistal"), Path.home() / ".local" / "bin" / "vistal",
                 paths.PACKAGE_DIR.parent / "bin" / "vistal"):
        if cand and Path(cand).exists():
            return str(Path(cand).absolute())
    return "vistal"


# --------------------------------------------------------------------------
# ES-DE
# --------------------------------------------------------------------------


def esde_home() -> Path:
    env = os.environ.get("ESDE_APPDATA_DIR")
    if env:
        return Path(env).expanduser()
    new = Path.home() / "ES-DE"
    legacy = Path.home() / ".emulationstation"
    if not new.exists() and (legacy / "es_settings.xml").exists():
        return legacy
    return new


def esde_rom_directory(home: Path | None = None) -> Path:
    home = home or esde_home()
    for settings in (home / "settings" / "es_settings.xml", home / "es_settings.xml"):
        if settings.exists():
            m = re.search(r'<string\s+name="ROMDirectory"\s+value="([^"]*)"', settings.read_text(errors="replace"))
            if m and m.group(1).strip():
                return Path(m.group(1).replace("%ESPATH%", str(home)).strip()).expanduser()
    for cand in (Path.home() / "Emulation" / "roms", Path.home() / "ROMs"):
        if cand.exists():
            return cand
    return Path.home() / "ROMs"


def _indent(elem: ET.Element, level: int = 0) -> None:
    pad = "\n" + "    " * level
    if len(elem):
        if not (elem.text or "").strip():
            elem.text = pad + "    "
        for child in elem:
            _indent(child, level + 1)
        if not (child.tail or "").strip():
            child.tail = pad
    if level and not (elem.tail or "").strip():
        elem.tail = pad


def _load_or_new(path: Path, root_tag: str) -> ET.ElementTree:
    if path.exists():
        try:
            tree = ET.parse(path)
            if tree.getroot().tag == root_tag:
                return tree
        except ET.ParseError:
            pass
        backup = path.with_suffix(path.suffix + ".vistal-bak")
        if not backup.exists():
            shutil.copy2(path, backup)
    return ET.ElementTree(ET.Element(root_tag))


def _write(tree: ET.ElementTree, path: Path, comment: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    root = tree.getroot()
    _indent(root)
    body = ET.tostring(root, encoding="unicode")
    path.write_text(f'<?xml version="1.0"?>\n<!-- {comment} -->\n{body}\n', encoding="utf-8")


def esde_system_element(name: str = SYSTEM_NAME, fullname: str = FULL_NAME) -> ET.Element:
    sys_el = ET.Element("system")
    ET.SubElement(sys_el, "name").text = name
    ET.SubElement(sys_el, "fullname").text = fullname
    ET.SubElement(sys_el, "path").text = f"%ROMPATH%/{name}"
    ET.SubElement(sys_el, "extension").text = " ".join(extensions())
    for label, args in (("Vistal (Proton)", "launch"),
                        ("Vistal: reinstall from disc", "launch --reinstall"),
                        ("Vistal: Wine configuration", "winecfg")):
        cmd = ET.SubElement(sys_el, "command", {"label": label})
        cmd.text = f"%EMULATOR_{EMULATOR_ID}% {args} %ROM%"
    ET.SubElement(sys_el, "platform").text = "pc"
    ET.SubElement(sys_el, "theme").text = "windows"
    return sys_el


def install_esde(name: str = SYSTEM_NAME, fullname: str = FULL_NAME, home: Path | None = None,
                 rom_dir: Path | None = None) -> list[str]:
    home = home or esde_home()
    custom = home / "custom_systems"
    report = []

    systems_file = custom / "es_systems.xml"
    tree = _load_or_new(systems_file, "systemList")
    root = tree.getroot()
    for el in list(root.findall("system")):
        if (el.findtext("name") or "").strip() == name:
            root.remove(el)
    root.append(esde_system_element(name, fullname))
    _write(tree, systems_file, "Custom systems. The Vistal entry is managed by 'vistal frontend esde'.")
    report.append(f"System '{name}' written to {systems_file}")

    rules_file = custom / "es_find_rules.xml"
    tree = _load_or_new(rules_file, "ruleList")
    root = tree.getroot()
    for el in list(root.findall("emulator")):
        if el.get("name") == EMULATOR_ID:
            root.remove(el)
    emu = ET.SubElement(root, "emulator", {"name": EMULATOR_ID})
    ET.SubElement(emu, "comment").text = "Vistal - Proton runtime for Windows PC games"
    rule = ET.SubElement(emu, "rule", {"type": "systempath"})
    ET.SubElement(rule, "entry").text = "vistal"
    rule = ET.SubElement(emu, "rule", {"type": "staticpath"})
    for entry in dict.fromkeys([vistal_command(), "~/.local/bin/vistal", "~/Applications/vistal/bin/vistal"]):
        ET.SubElement(rule, "entry").text = entry
    _write(tree, rules_file, "Custom find rules. The VISTAL entry is managed by 'vistal frontend esde'.")
    report.append(f"Find rule for %EMULATOR_{EMULATOR_ID}% written to {rules_file}")

    roms = (rom_dir or esde_rom_directory(home)) / name
    roms.mkdir(parents=True, exist_ok=True)
    info = roms / "systeminfo.txt"
    info.write_text(rom_readme(name))
    report.append(f"ROM folder ready: {roms}")
    return report


def rom_readme(name: str) -> str:
    return f"""System name:
{name}

Full system name:
{FULL_NAME}

Supported file extensions:
{' '.join(extensions())}

Launch command:
%EMULATOR_{EMULATOR_ID}% launch %ROM%

Platform (for scraping):
pc

Theme folder:
windows

Put disc images here (.iso, .cue/.bin, .mdf/.mds, .nrg, .ccd/.img, .chd).
Multi-disc games: create Game.m3u listing one disc file per line.
Already-installed games: create Game.vistal (see the Vistal README).
The first launch runs the game's installer; later launches start the game.
"""


# --------------------------------------------------------------------------
# Classic EmulationStation
# --------------------------------------------------------------------------


def emulationstation_system_xml(rom_path: str, name: str = SYSTEM_NAME) -> str:
    el = ET.Element("system")
    ET.SubElement(el, "name").text = name
    ET.SubElement(el, "fullname").text = FULL_NAME
    ET.SubElement(el, "path").text = rom_path
    ET.SubElement(el, "extension").text = " ".join(extensions())
    ET.SubElement(el, "command").text = f"{shlex.quote(vistal_command())} launch %ROM%"
    ET.SubElement(el, "platform").text = "pc"
    ET.SubElement(el, "theme").text = "pc"
    _indent(el, 1)
    return "    " + ET.tostring(el, encoding="unicode").rstrip()


def install_emulationstation(rom_path: str, name: str = SYSTEM_NAME) -> list[str]:
    cfg = Path.home() / ".emulationstation" / "es_systems.cfg"
    tree = _load_or_new(cfg, "systemList")
    root = tree.getroot()
    for el in list(root.findall("system")):
        if (el.findtext("name") or "").strip() == name:
            root.remove(el)
    root.append(ET.fromstring(emulationstation_system_xml(rom_path, name).strip()))
    _write(tree, cfg, "EmulationStation systems. The Vistal entry is managed by Vistal.")
    Path(os.path.expanduser(rom_path)).mkdir(parents=True, exist_ok=True)
    return [f"System '{name}' written to {cfg}", f"ROM folder: {rom_path}"]


# --------------------------------------------------------------------------
# Desktop entries
# --------------------------------------------------------------------------


def _desktop_escape(arg: str) -> str:
    arg = arg.replace("%", "%%")  # field codes are reserved in Exec=
    if re.fullmatch(r"[A-Za-z0-9_./:=+%-]+", arg):
        return arg
    return '"' + arg.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$") + '"'


def write_desktop_entries(target: Path | None = None) -> list[str]:
    target = target or Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "applications"
    target.mkdir(parents=True, exist_ok=True)
    out = []
    cmd = vistal_command()
    lib_entry = target / "vistal-games.desktop"
    lib_entry.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Vistal Games\n"
        "Comment=Game library for Windows PC games (Proton)\n"
        f"Exec={_desktop_escape(cmd)} gui\n"
        "Icon=applications-games\n"
        "Categories=Game;\n"
        "Terminal=false\n"
    )
    out.append(str(lib_entry))
    for m in library.all_games():
        if not m.installed or not m.rom:
            continue
        f = target / f"vistal-{m.id}.desktop"
        f.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={m.title}\n"
            f"Comment=Windows game via Vistal (Proton)\n"
            f"Exec={_desktop_escape(cmd)} launch {_desktop_escape(m.rom)}\n"
            "Icon=applications-games\n"
            "Categories=Game;\n"
            "Terminal=false\n"
        )
        out.append(str(f))
    return out

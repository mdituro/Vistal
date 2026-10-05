"""Command line interface."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import __version__, discimage, frontends, library, media, paths, profiles, tomlutil, ui
from .log import LOG, setup


def _source(rom: str) -> media.GameSource:
    """Accept a ROM path, or the id of an installed game."""
    p = Path(rom).expanduser()
    if not p.exists():
        m = library.GameDir(rom).load()
        if m and m.rom and Path(m.rom).exists():
            return media.resolve(m.rom)
    return media.resolve(rom)


def _session(rom: str, profile: str | None = None):
    from .launcher import Session
    return Session(_source(rom), profile)


# -- commands ----------------------------------------------------------------


def cmd_launch(a) -> int:
    return _session(a.rom, a.profile).launch(reinstall=a.reinstall)


def cmd_install(a) -> int:
    s = _session(a.rom, a.profile)
    lock = s.game.lock()
    if lock is None:
        raise SystemExit(f"{s.source.title} is already running")
    try:
        return 0 if s.install() else 1
    finally:
        s.release_discs()
        lock.close()


def cmd_run(a) -> int:
    return _session(a.rom).run_program(a.program, a.args)


def cmd_winecfg(a) -> int:
    return _session(a.rom).run_program("winecfg", [])


def cmd_set_exe(a) -> int:
    s = _session(a.rom)
    s.set_exe(a.exe)
    print(f"{s.source.title}: executable set to {s.manifest.exe}")
    return 0


def cmd_info(a) -> int:
    src = _source(a.rom)
    print(f"Title:     {src.title}")
    print(f"Game id:   {src.id}")
    print(f"Type:      {src.kind}")
    for i, d in enumerate(src.discs, 1):
        line = f"Disc {i}:    {d}"
        if d.is_file() and d.suffix.lower() != ".chd":
            try:
                with discimage.Disc(str(d)) as disc:
                    line += f"\n           label {disc.label!r}, serial {disc.serial:08X}, layout {disc.reader.layout}"
                    root = disc.fs.lookup("autorun.inf")
                    if root:
                        auto = discimage.parse_autorun(discimage.decode_text(disc.fs.read_file(root)))
                        if auto.get("open"):
                            line += f"\n           autorun: {auto['open']}"
            except discimage.ImageError as exc:
                line += f"\n           ({exc})"
        print(line)
    label = ""
    if src.discs and src.discs[0].is_file():
        try:
            with discimage.Disc(str(src.discs[0])) as disc:
                label = disc.label
        except discimage.ImageError:
            pass
    m = profiles.match(src.title, src.rom.stem, label)
    prof = profiles.get(m.profile_id) if m else {}
    print(f"Profile:   {prof.get('title', m.profile_id) + ' (' + ', '.join(m.reasons) + ')' if m else 'none (generic settings)'}")
    if prof.get("notes"):
        print("Notes:     " + str(prof["notes"]).strip().replace("\n", "\n           "))
    man = library.GameDir(src.id).load()
    if man and man.exe:
        print(f"Installed: {man.exe} (since {man.installed_at})")
        if man.last_played:
            print(f"Played:    {man.last_played}")
    else:
        print("Installed: no")
    print(f"Prefix:    {library.GameDir(src.id).compat / 'pfx'}")
    return 0


def cmd_list(a) -> int:
    games = library.all_games()
    if not games:
        print("No games installed yet.")
        return 0
    for m in games:
        state = "installed" if m.installed else "not installed"
        print(f"{m.id:<28} {m.title:<36} {state:<14} {m.last_played or ''}")
    return 0


def cmd_profiles(a) -> int:
    for pid, p in sorted(profiles.all_profiles().items()):
        layout = (p.get("controller") or {}).get("layout", "-")
        mode = (p.get("controller") or {}).get("mode", "auto")
        print(f"{pid:<26} {p.get('title', ''):<36} controller: {mode}/{layout}")
    return 0


def cmd_config(a) -> int:
    from .launcher import Session
    s = Session(_source(a.rom))
    print(f"# effective settings for {s.source.id} (profile: {s.profile_id or 'none'})")
    print(f"# per-game overrides go in {paths.game_settings_file(s.source.id)}")
    print(tomlutil.dumps(s.settings))
    return 0


def cmd_disc(a) -> int:
    from .launcher import Session
    s = Session(_source(a.rom))
    n = a.number - 1
    if not (0 <= n < len(s.source.discs)):
        raise SystemExit(f"{s.source.title} has {len(s.source.discs)} disc(s)")
    root = s.game.disc_root(n)
    if not root.exists():
        raise SystemExit("Discs are not prepared; start the game first")
    link = s.prefix.dosdevices / f"{s.letters[0]}:"
    if link.is_symlink():
        link.unlink()
    os.symlink(root, link)
    print(f"Drive {s.letters[0].upper()}: now holds disc {a.number}")
    return 0


def cmd_kill(a) -> int:
    from .launcher import Session
    s = Session(_source(a.rom))
    s.runner.kill()
    return 0


def cmd_uninstall(a) -> int:
    src = _source(a.rom)
    gd = library.GameDir(src.id)
    if not gd.root.exists():
        print("Nothing to remove.")
        return 0
    if not a.yes and not ui.get().confirm("Vistal", f"Delete {src.title} and its saves in {gd.root}?", False):
        return 1
    shutil.rmtree(gd.root)
    print(f"Removed {gd.root}")
    return 0


def cmd_tricks(a) -> int:
    wt = shutil.which("winetricks")
    if not wt:
        raise SystemExit("winetricks is not installed")
    from .launcher import Session
    s = Session(_source(a.rom))
    s.prefix.ensure(s.runner, s.settings)
    wine = s.runner.proton.wine
    if not wine:
        raise SystemExit("Could not find Proton's wine binary")
    env = s.runner.environment({"WINE": str(wine), "WINESERVER": str(s.runner.proton.wineserver or "")})
    return subprocess.call([wt, "-q", *a.verbs], env=env)


def cmd_extract(a) -> int:
    with discimage.Disc(a.image) as disc:
        prog = ui.get().progress("Extracting", disc.label)
        with prog:
            disc.fs.extract(a.dest, lambda d, t, n: prog.update(d / t if t else 1.0, n))
    print(f"Extracted {a.image} ({disc.label}) to {a.dest}")
    return 0


def cmd_ls(a) -> int:
    with discimage.Disc(a.image) as disc:
        print(f"# {disc.label} ({disc.reader.layout}, serial {disc.serial:08X})")
        for e in disc.fs.walk():
            print(f"{'<DIR>' if e.is_dir else e.size:>12}  {e.path}")
    return 0


def cmd_protons(a) -> int:
    from .proton import find_protons, select_proton
    builds = find_protons()
    if not builds:
        print("No Proton builds found.")
        return 1
    default = select_proton()
    for b in sorted(builds, key=lambda b: b.name):
        mark = "*" if b.path == default.path else " "
        print(f"{mark} {b.name:<32} {b.kind:<12} {b.path}")
    return 0


def cmd_frontend(a) -> int:
    if a.target == "esde":
        if a.print:
            import xml.etree.ElementTree as ET
            el = frontends.esde_system_element(a.system_name)
            frontends._indent(el)
            print(ET.tostring(el, encoding="unicode"))
            return 0
        rom_dir = Path(a.rom_dir).expanduser() if a.rom_dir else None
        for line in frontends.install_esde(a.system_name, home=Path(a.esde_home).expanduser() if a.esde_home else None,
                                           rom_dir=rom_dir):
            print(line)
        print("Restart ES-DE to see the new system.")
    elif a.target == "emulationstation":
        rom_path = a.rom_dir or f"~/RetroPie/roms/{a.system_name}"
        if a.print:
            print(frontends.emulationstation_system_xml(rom_path, a.system_name))
            return 0
        for line in frontends.install_emulationstation(rom_path, a.system_name):
            print(line)
    elif a.target == "desktop":
        files = frontends.write_desktop_entries()
        print("\n".join(files) if files else "No installed games yet.")
    return 0


def cmd_controller(a) -> int:
    from .controller import layout as L
    if a.action == "layouts":
        for name, path in L.available().items():
            try:
                lay = L.load(str(path))
                print(f"{name:<14} {lay.description}")
            except L.LayoutError as exc:
                print(f"{name:<14} (invalid: {exc})")
        return 0
    if a.action == "show":
        lay = L.load(a.name or "desktop")
        print("\n".join(lay.describe()))
        return 0
    from .controller.evdev import list_gamepads
    pads = list_gamepads()
    if a.action == "list":
        if not pads:
            print("No gamepads found (check permissions on /dev/input/event*).")
        for p in pads:
            print(f"{p.path:<20} {p.vendor:04x}:{p.product:04x}  {p.name}")
            p.close()
        return 0
    if a.action == "test":
        for p in pads:
            p.close()
        from .controller.engine import Engine, Hotkey
        from .controller.mapper import Mapper

        lay = L.load(a.name) if a.name else None

        print("Press buttons / move sticks. Ctrl+C to stop." +
              (f" Mapping with layout '{lay.name}'." if lay else " (showing inputs only)"))

        class Printer:
            def key(self, code, down): print(f"  key {code} {'down' if down else 'up'}")
            def rel(self, dx, dy): pass
            def wheel(self, n): print(f"  wheel {n}")
            def sync(self): pass
            def close(self): pass

        if lay:
            m = Mapper(lay, [Hotkey.make(["back", "start"], 1.5, "exit")],
                       on_special=lambda n: print(f"  hotkey: {n}"), grab=False)
        else:
            class Echo(Engine):
                def button(self, name, down):
                    print(f"{name:<12} {'pressed' if down else 'released'}")

                def axis(self, name, value):
                    if abs(value) > 0.5 or name in ("lt", "rt"):
                        print(f"{name:<12} {value:+.2f}")

            m = Mapper(None, grab=False, engine_factory=lambda layout, sink, hotkeys, on_special=None: Echo(None, Printer()))
        if not m.start():
            raise SystemExit("Could not start the controller reader")
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            m.stop()
        return 0
    return 1


def cmd_gui(a) -> int:
    from .gui.cairo import CairoUnavailable
    from .gui.sdl import SDLUnavailable
    try:
        if a.screenshot:
            from .gui.app import screenshot
            w, h = (int(v) for v in a.size.lower().split("x"))
            screenshot(a.screenshot, w, h, theme=a.theme, view=a.view, select=a.select, menu=a.menu)
            print(f"Wrote {a.screenshot}")
            return 0
        from .gui.app import App
        return App(theme=a.theme, view=a.view).run()
    except (CairoUnavailable, SDLUnavailable) as exc:
        LOG.error("The game library needs the cairo and SDL2 system libraries: %s", exc)
        return 1


def cmd_doctor(a) -> int:
    from . import doctor
    return doctor.run()


def cmd_cache(a) -> int:
    root = paths.extract_cache()
    if a.action == "clean":
        if root.exists():
            shutil.rmtree(root)
        print(f"Removed extracted discs in {root}")
        return 0
    total = 0
    if root.exists():
        for d in sorted(root.iterdir()):
            size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file() and not f.is_symlink())
            total += size
            print(f"{size / 1e9:7.2f} GB  {d.name}")
    print(f"{total / 1e9:7.2f} GB  total in {root}")
    return 0


def cmd_shortcut(a) -> int:
    """Write a .vistal file for an installed game (e.g. into a ROM folder)."""
    m = library.GameDir(a.game).load()
    if not m or not m.exe:
        raise SystemExit(f"'{a.game}' is not an installed game id (see 'vistal list')")
    out = Path(a.dest).expanduser()
    if out.is_dir():
        out = out / f"{m.title}.vistal"
    data = {"title": m.title, "id": m.id, "exe": m.exe}
    if m.profile:
        data["profile"] = m.profile
    if m.discs:
        data["discs"] = m.discs
    tomlutil.save(out, data, header="# Vistal game shortcut")
    print(f"Wrote {out}")
    return 0


# -- parser ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vistal", description="Run Windows PC games from disc images on SteamOS via Proton.")
    p.add_argument("--version", action="version", version=f"vistal {__version__}")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--ui", choices=["auto", "tty", "zenity", "kdialog", "none"], help="dialog backend")
    sub = p.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def add(name, fn, help_text, rom=True):
        sp = sub.add_parser(name, help=help_text, description=help_text)
        if rom:
            sp.add_argument("rom", help="disc image, .m3u, .vistal file, folder, or installed game id")
        sp.set_defaults(fn=fn)
        return sp

    sp = add("launch", cmd_launch, "install on first use, then play (what frontends call)")
    sp.add_argument("--reinstall", action="store_true", help="run the installer again")
    sp.add_argument("--profile", help="force a game profile")
    sp = add("install", cmd_install, "run the installer only")
    sp.add_argument("--profile", help="force a game profile")
    sp = add("run", cmd_run, "run another program (patch, tool) in the game's prefix")
    sp.add_argument("program")
    sp.add_argument("args", nargs=argparse.REMAINDER)
    add("winecfg", cmd_winecfg, "open Wine configuration for the game's prefix")
    sp = add("set-exe", cmd_set_exe, "choose the executable that starts the game")
    sp.add_argument("exe", help="Windows path (C:\\...) or Linux path")
    add("info", cmd_info, "show what Vistal knows about a game or image")
    add("config", cmd_config, "print the effective settings for a game")
    sp = add("disc", cmd_disc, "put disc N into the first CD drive (multi-disc games)")
    sp.add_argument("number", type=int)
    add("kill", cmd_kill, "stop everything running in the game's prefix")
    sp = add("uninstall", cmd_uninstall, "delete the game's prefix (including saves!)")
    sp.add_argument("-y", "--yes", action="store_true")
    sp = add("tricks", cmd_tricks, "run winetricks verbs in the game's prefix")
    sp.add_argument("verbs", nargs="+")
    add("list", cmd_list, "list installed games", rom=False)
    add("profiles", cmd_profiles, "list built-in and user game profiles", rom=False)
    add("protons", cmd_protons, "list Proton builds (* = default)", rom=False)
    add("doctor", cmd_doctor, "check the system setup", rom=False)
    sp = add("extract", cmd_extract, "extract a disc image", rom=False)
    sp.add_argument("image")
    sp.add_argument("dest")
    sp = add("ls", cmd_ls, "list the files in a disc image", rom=False)
    sp.add_argument("image")
    sp = add("cache", cmd_cache, "show or clean extracted disc cache", rom=False)
    sp.add_argument("action", choices=["show", "clean"], nargs="?", default="show")
    sp = add("shortcut", cmd_shortcut, "write a .vistal launcher file for an installed game", rom=False)
    sp.add_argument("game", help="installed game id")
    sp.add_argument("dest", help="file or folder (e.g. your ROMs/gfw folder)")
    sp = add("frontend", cmd_frontend, "set up an emulation frontend", rom=False)
    sp.add_argument("target", choices=["esde", "emulationstation", "desktop"])
    sp.add_argument("--print", action="store_true", help="print the configuration instead of writing it")
    sp.add_argument("--system-name", default=frontends.SYSTEM_NAME)
    sp.add_argument("--rom-dir", help="ROM root (ES-DE) or system ROM folder (EmulationStation)")
    sp.add_argument("--esde-home", help="ES-DE application data directory (default ~/ES-DE)")
    sp = add("gui", cmd_gui, "open the game library (Windows Vista or Aqua look)", rom=False)
    sp.add_argument("--theme", choices=["vista", "aqua"], help="override the remembered theme")
    sp.add_argument("--view", choices=["extra-large", "large", "medium", "details"])
    sp.add_argument("--screenshot", metavar="PNG", help="render to a PNG file instead of opening a window")
    sp.add_argument("--size", default="1280x800", help="screenshot size (default 1280x800)")
    sp.add_argument("--select", type=int, help="screenshot: index of the selected game")
    sp.add_argument("--menu", help="screenshot: open this menu (organize, views, options, tools, game)")
    sp = add("controller", cmd_controller, "gamepad tools", rom=False)
    sp.add_argument("action", choices=["list", "test", "layouts", "show"])
    sp.add_argument("name", nargs="?", help="layout name for test/show")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.ui:
        os.environ["VISTAL_UI"] = args.ui
    setup(args.verbose)
    from .launcher import LaunchError
    from .controller.layout import LayoutError
    try:
        return int(args.fn(args) or 0)
    except (LaunchError, media.MediaError, discimage.ImageError, tomlutil.ConfigError, LayoutError) as exc:
        LOG.error("%s", exc)
        if args.command in ("launch", "install") and not sys.stdin.isatty():
            ui.get().error("Vistal", str(exc))
        return 1
    except KeyboardInterrupt:
        return 130

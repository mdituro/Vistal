"""`vistal doctor`: check that the machine can run games."""

from __future__ import annotations

import os
import shutil
import sys

from . import frontends, paths
from .controller.evdev import list_gamepads, uinput_status
from .proton import find_protons, find_runtime, find_umu, select_proton, steam_roots, ProtonError


def run() -> int:
    ok_all = True

    def line(ok: bool | None, label: str, detail: str = "") -> None:
        nonlocal ok_all
        mark = {True: "ok ", False: "!! ", None: "-- "}[ok]
        if ok is False:
            ok_all = False
        print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))

    line(sys.version_info >= (3, 11), "Python", sys.version.split()[0] + (" (3.11+ required)" if sys.version_info < (3, 11) else ""))
    roots = steam_roots()
    line(bool(roots) or None, "Steam installation", ", ".join(map(str, roots)) or "not found (Proton can still come from elsewhere)")
    builds = find_protons()
    line(bool(builds), "Proton builds", ", ".join(b.name for b in builds) or "none found")
    try:
        chosen = select_proton()
        line(True, "Default Proton", str(chosen))
        if chosen.runtime_appid:
            rt = find_runtime(chosen.runtime_appid)
            line(bool(rt) or None, "Steam Linux Runtime", str(rt) if rt else
                 f"not installed (app {chosen.runtime_appid}); Proton will run directly on the host")
    except ProtonError as exc:
        line(False, "Default Proton", str(exc))
    umu = find_umu()
    line(None if not umu else True, "umu-launcher", umu or "not installed (optional)")

    ok, why = uinput_status()
    line(ok or None, "Controller mapping (/dev/uinput)", why if not ok else "available")
    try:
        pads = list_gamepads()
        line(None if not pads else True, "Gamepads", ", ".join(p.name for p in pads) or "none detected right now")
        for p in pads:
            p.close()
    except OSError as exc:
        line(None, "Gamepads", str(exc))

    for tool, why in (("fuseiso", "mount images without copying"), ("7z", "UDF-only discs"),
                      ("bsdtar", "UDF-only discs"), ("chdman", ".chd images"),
                      ("zenity", "dialogs when launched from a frontend"),
                      ("gamescope", "display.gamescope option"), ("winetricks", "'vistal tricks'")):
        path = shutil.which(tool)
        line(True if path else None, tool, path or f"not installed (optional: {why})")

    home = frontends.esde_home()
    sysfile = home / "custom_systems" / "es_systems.xml"
    configured = sysfile.exists() and f"<name>{frontends.SYSTEM_NAME}</name>" in sysfile.read_text(errors="replace")
    line(True if configured else None, "ES-DE integration",
         str(sysfile) if configured else "not set up (run: vistal frontend esde)")
    print(f"\nData: {paths.data_root()}\nConfig: {paths.config_root()}\nCache: {paths.cache_root()}")
    if os.environ.get("SteamGameId"):
        print(f"Running under Steam (SteamGameId={os.environ['SteamGameId']})")
    return 0 if ok_all else 1

"""Per-game Wine prefix management on top of Proton."""

from __future__ import annotations

import hashlib
import json
import os
import string
from pathlib import Path
from typing import Any

from .log import LOG
from .proton import Runner, to_windows_path

MAX_DISC_LETTERS = 6


def cd_letters(first: str, count: int) -> list[str]:
    first = (first or "d").lower()[0]
    letters = string.ascii_lowercase
    start = letters.index(first) if first in letters else 3
    out = []
    for ch in letters[start:]:
        if ch in ("c", "z"):
            continue
        out.append(ch)
        if len(out) == count:
            break
    return out


def registry_text(settings: dict[str, Any], letters: list[str]) -> str:
    lines = ["REGEDIT4", "", r"[HKEY_LOCAL_MACHINE\Software\Wine\Drives]"]
    lines += [f'"{l}:"="cdrom"' for l in letters]
    winver = (settings.get("prefix") or {}).get("winver") or ""
    if winver:
        lines += ["", r"[HKEY_CURRENT_USER\Software\Wine]", f'"Version"="{winver}"']
    extra = (settings.get("prefix") or {}).get("registry") or []
    if extra:
        lines.append("")
        lines += [str(x) for x in extra]
    return "\n".join(lines) + "\n"


class Prefix:
    def __init__(self, compat_dir: Path):
        self.compat_dir = compat_dir
        self.pfx = compat_dir / "pfx"
        self.state_file = compat_dir / "vistal-prefix.json"

    @property
    def drive_c(self) -> Path:
        return self.pfx / "drive_c"

    @property
    def dosdevices(self) -> Path:
        return self.pfx / "dosdevices"

    def exists(self) -> bool:
        return (self.pfx / "system.reg").exists()

    def _state(self) -> dict[str, Any]:
        try:
            return json.loads(self.state_file.read_text())
        except (OSError, ValueError):
            return {}

    def _save_state(self, state: dict[str, Any]) -> None:
        self.compat_dir.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, indent=2))

    def ensure(self, runner: Runner, settings: dict[str, Any]) -> None:
        """Create the prefix (first run) and (re)apply Vistal's registry."""
        letters = cd_letters((settings.get("disc") or {}).get("letter", "d"), MAX_DISC_LETTERS)
        reg = registry_text(settings, letters)
        digest = hashlib.sha1(reg.encode()).hexdigest()
        state = self._state()
        if self.exists() and state.get("registry") == digest:
            return
        self.compat_dir.mkdir(parents=True, exist_ok=True)
        reg_file = self.compat_dir / "vistal.reg"
        # regedit wants CRLF and a Windows path
        reg_file.write_bytes(reg.replace("\n", "\r\n").encode("cp1252", errors="replace"))
        if not self.exists():
            LOG.info("Creating Wine prefix (first run takes a minute)...")
        rc = runner.run("regedit", ["/S", to_windows_path(reg_file)], cwd=self.compat_dir)
        if rc != 0:
            LOG.warning("regedit exited with %s; continuing", rc)
        state["registry"] = digest
        self._save_state(state)

    def map_drives(self, mapping: dict[str, Path], owned_root: Path) -> None:
        """Point drive letters at directories. Letters that previously pointed
        into `owned_root` but are no longer wanted are removed."""
        self.dosdevices.mkdir(parents=True, exist_ok=True)
        owned = str(owned_root.resolve())
        for entry in os.listdir(self.dosdevices):
            link = self.dosdevices / entry
            if not link.is_symlink() or len(entry) != 2 or not entry.endswith(":"):
                continue
            letter = entry[0]
            target = os.path.realpath(link)
            if letter not in mapping and target.startswith(owned):
                link.unlink()
        for letter, target in mapping.items():
            link = self.dosdevices / f"{letter}:"
            if link.is_symlink() or link.exists():
                link.unlink()
            os.symlink(target, link)
            # A raw device link (e.g. "d::" -> /dev/sr0 from mountmgr) would make
            # Wine read the physical drive instead of our image.
            dev = self.dosdevices / f"{letter}::"
            if dev.is_symlink():
                dev.unlink()
            LOG.debug("drive %s: -> %s", letter.upper(), target)

    def set_device(self, letter: str, device: str | None) -> None:
        dev = self.dosdevices / f"{letter}::"
        if dev.is_symlink():
            dev.unlink()
        if device:
            os.symlink(device, dev)

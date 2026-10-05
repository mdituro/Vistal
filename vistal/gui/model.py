"""The game library shown by the frontend: installed games plus every
launchable file found in the ROM folders."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .. import art, library, media, profiles
from ..frontends import FRONTEND_EXTS, esde_rom_directory
from ..log import LOG
from ..proton import to_unix_path


@dataclass
class Entry:
    id: str
    title: str
    rom: Path | None = None
    discs: list[Path] = field(default_factory=list)
    installed: bool = False
    exe: Path | None = None
    last_played: str = ""
    installed_at: str = ""
    profile_id: str = ""
    profile: dict[str, Any] = field(default_factory=dict)
    art: art.Art | None = None

    @property
    def info(self) -> dict[str, str]:
        return self.art.info if self.art else {}

    @property
    def display_title(self) -> str:
        return self.info.get("name") or self.profile.get("title") or self.title

    @property
    def publisher(self) -> str:
        return self.info.get("publisher", "")

    @property
    def developer(self) -> str:
        return self.info.get("developer", "")

    @property
    def genre(self) -> str:
        return self.info.get("genre", "")

    @property
    def year(self) -> str:
        date = self.info.get("release_date", "")
        return date[:4] if date else str(self.profile.get("year", "") or "")

    @property
    def status(self) -> str:
        return "Installed" if self.installed else ("Ready to install" if self.discs else "Not installed")

    @property
    def kind(self) -> str:
        if self.rom is None:
            return "Game"
        ext = self.rom.suffix.lower()
        if self.rom.is_dir():
            return "Game folder"
        return {".m3u": f"{len(self.discs)}-disc set", ".vistal": "Vistal shortcut",
                ".exe": "Windows program"}.get(ext, f"Disc image ({ext.lstrip('.').upper()})")


def rom_dirs(settings: dict[str, Any]) -> list[Path]:
    dirs = [Path(d).expanduser() for d in (settings.get("frontend") or {}).get("rom_dirs") or []]
    if not dirs:
        dirs = [esde_rom_directory() / "gfw"]
    return [d for d in dirs if d.is_dir()]


def _scan_dir(d: Path) -> list[Path]:
    out = []
    try:
        names = sorted(os.listdir(d), key=str.lower)
    except OSError:
        return out
    for name in names:
        p = d / name
        if name.startswith(".") or name.lower() == "systeminfo.txt":
            continue
        if p.is_file() and p.suffix.lower() in FRONTEND_EXTS:
            out.append(p)
        elif p.is_dir():
            out.append(p)
    return out


def scan(settings: dict[str, Any]) -> list[Entry]:
    entries: dict[str, Entry] = {}
    all_profiles = profiles.all_profiles()
    for d in rom_dirs(settings):
        for p in _scan_dir(d):
            try:
                src = media.resolve(p)
            except Exception as exc:
                LOG.debug("skipping %s: %s", p, exc)
                continue
            if src.id in entries:
                continue
            m = profiles.match(src.title, src.rom.stem)
            pid = src.spec.get("profile") or (m.profile_id if m else "")
            entries[src.id] = Entry(src.id, src.title, src.rom, list(src.discs), profile_id=pid,
                                    profile=all_profiles.get(pid, {}))
    for man in library.all_games():
        e = entries.get(man.id)
        if e is None:
            rom = Path(man.rom) if man.rom else None
            e = Entry(man.id, man.title, rom if rom and rom.exists() else None,
                      [Path(x) for x in man.discs if Path(x).exists()])
            entries[man.id] = e
        if man.profile:
            e.profile_id = man.profile
            e.profile = all_profiles.get(man.profile, {})
        e.last_played, e.installed_at = man.last_played, man.installed_at
        if man.exe:
            exe = to_unix_path(man.exe, library.GameDir(man.id).compat / "pfx")
            if exe.exists() or (e.rom and e.rom.suffix.lower() in (".exe", ".vistal")):
                e.installed, e.exe = True, exe
    return list(entries.values())


def sort_entries(entries: list[Entry], order: str) -> list[Entry]:
    by_name = sorted(entries, key=lambda e: e.display_title.lower())
    if order == "last-played":
        # timestamps sort lexically; never-played games ("") end up last
        return sorted(by_name, key=lambda e: e.last_played, reverse=True)
    return by_name


def filter_entries(entries: list[Entry], query: str, category: str = "all") -> list[Entry]:
    q = query.strip().lower()
    out = []
    for e in entries:
        if category == "installed" and not e.installed:
            continue
        if category == "not-installed" and e.installed:
            continue
        if category == "recent" and not e.last_played:
            continue
        if q and q not in " ".join((e.display_title, e.publisher, e.developer, e.genre)).lower():
            continue
        out.append(e)
    return out


class ArtLoader:
    """Resolves artwork for entries on a background thread."""

    def __init__(self, on_update: Callable[[], None]):
        self.on_update = on_update
        self._queue: list[Entry] = []
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = False
        self._thread = threading.Thread(target=self._run, name="vistal-art", daemon=True)
        self._thread.start()

    def request(self, entries: list[Entry]) -> None:
        with self._lock:
            self._queue = [e for e in entries if e.art is None] + self._queue
        self._wake.set()

    def _run(self) -> None:
        while not self._stop:
            self._wake.wait(0.5)
            self._wake.clear()
            while True:
                with self._lock:
                    if not self._queue:
                        break
                    e = self._queue.pop(0)
                if e.art is not None:
                    continue
                try:
                    e.art = art.resolve(e.id, e.exe, e.rom, e.discs)
                except Exception as exc:
                    LOG.debug("art for %s failed: %s", e.id, exc)
                    e.art = art.Art()
                self.on_update()

    def stop(self) -> None:
        self._stop = True
        self._wake.set()

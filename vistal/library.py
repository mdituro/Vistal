"""Installed-game manifests (~/.local/share/vistal/games/<id>/game.json)."""

from __future__ import annotations

import fcntl
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import paths


@dataclass
class Manifest:
    id: str
    title: str
    profile: str = ""
    rom: str = ""
    discs: list[str] = field(default_factory=list)
    exe: str = ""  # Windows path, e.g. C:\Program Files (x86)\...\game.exe
    args: list[str] = field(default_factory=list)
    installed_at: str = ""
    last_played: str = ""
    proton: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def installed(self) -> bool:
        return bool(self.exe)


class GameDir:
    def __init__(self, game_id: str):
        self.id = game_id
        self.root = paths.game_dir(game_id)

    @property
    def compat(self) -> Path:
        return self.root / "compat"

    @property
    def drives(self) -> Path:
        return self.root / "drives"

    @property
    def manifest_file(self) -> Path:
        return self.root / "game.json"

    def disc_root(self, index: int) -> Path:
        return self.drives / f"disc{index + 1}"

    def load(self) -> Manifest | None:
        try:
            data = json.loads(self.manifest_file.read_text())
        except (OSError, ValueError):
            return None
        known = {k: v for k, v in data.items() if k in Manifest.__dataclass_fields__}
        return Manifest(**known)

    def save(self, manifest: Manifest) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.manifest_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(manifest), indent=2))
        os.replace(tmp, self.manifest_file)

    def lock(self):
        """Exclusive lock so a game is never started twice at once."""
        self.root.mkdir(parents=True, exist_ok=True)
        fh = open(self.root / ".lock", "w")
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fh.close()
            return None
        return fh


def all_games() -> list[Manifest]:
    out = []
    root = paths.games_dir()
    if root.is_dir():
        for d in sorted(root.iterdir()):
            m = GameDir(d.name).load()
            if m:
                out.append(m)
    return out


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")

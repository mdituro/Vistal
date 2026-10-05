"""Filesystem locations used by Vistal.

Everything lives under XDG directories by default. Set VISTAL_HOME to keep all
state (prefixes, caches, logs, config) under a single directory instead, e.g.
on an SD card: VISTAL_HOME=/run/media/mmcblk0p1/vistal
"""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PACKAGE_DIR / "data"


def _xdg(var: str, default: str) -> Path:
    val = os.environ.get(var)
    return Path(val) if val else Path.home() / default


def home() -> Path | None:
    val = os.environ.get("VISTAL_HOME")
    return Path(val).expanduser() if val else None


def data_root() -> Path:
    h = home()
    return h / "data" if h else _xdg("XDG_DATA_HOME", ".local/share") / "vistal"


def config_root() -> Path:
    h = home()
    return h / "config" if h else _xdg("XDG_CONFIG_HOME", ".config") / "vistal"


def cache_root() -> Path:
    h = home()
    return h / "cache" if h else _xdg("XDG_CACHE_HOME", ".cache") / "vistal"


def games_dir() -> Path:
    return data_root() / "games"


def game_dir(game_id: str) -> Path:
    return games_dir() / game_id


def logs_dir() -> Path:
    return data_root() / "logs"


def extract_cache() -> Path:
    return cache_root() / "discs"


def mounts_dir() -> Path:
    # Kept under the home directory on purpose: Proton's Steam Linux Runtime
    # container always shares $HOME, but not necessarily $XDG_RUNTIME_DIR.
    return cache_root() / "mnt"


def user_config_file() -> Path:
    return config_root() / "config.toml"


def user_profiles_dir() -> Path:
    return config_root() / "profiles"


def user_layouts_dir() -> Path:
    return config_root() / "controller"


def game_settings_file(game_id: str) -> Path:
    return config_root() / "games" / f"{game_id}.toml"


def slugify(text: str) -> str:
    """Turn a ROM file name into a stable, filesystem-friendly game id."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text or "game"


def ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path

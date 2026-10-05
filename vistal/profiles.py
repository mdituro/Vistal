"""Game profiles: known-game knowledge (executables, Proton tweaks, controller
layouts) plus the layered settings model.

Effective settings for a game are built by deep-merging, in order:
  1. vistal/data/defaults.toml                (built-in defaults)
  2. ~/.config/vistal/config.toml             (your global preferences)
  3. the matched profile                      (built-in or ~/.config/vistal/profiles)
  4. ~/.config/vistal/games/<game-id>.toml    (your per-game overrides)
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import paths, tomlutil
from .media import case_insensitive


@dataclass
class Match:
    profile_id: str
    score: int
    reasons: list[str]


def defaults() -> dict[str, Any]:
    return tomlutil.load(paths.DATA_DIR / "defaults.toml")


def user_config() -> dict[str, Any]:
    return tomlutil.load_if_exists(paths.user_config_file())


def _load_dir(d: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if d.is_dir():
        for f in sorted(d.glob("*.toml")):
            data = tomlutil.load(f)
            pid = str(data.get("id") or f.stem)
            data["id"] = pid
            data["_source"] = str(f)
            out[pid] = data
    return out


def all_profiles() -> dict[str, dict[str, Any]]:
    profiles = _load_dir(paths.DATA_DIR / "games")
    for pid, data in _load_dir(paths.user_profiles_dir()).items():
        profiles[pid] = tomlutil.deep_merge(profiles.get(pid, {}), data)
    return profiles


def get(profile_id: str | None) -> dict[str, Any]:
    if not profile_id:
        return {}
    return all_profiles().get(profile_id, {})


def _globs(patterns, value: str) -> bool:
    v = value.lower().strip()
    return any(fnmatch.fnmatchcase(v, str(p).lower()) for p in patterns or [])


def match(title: str, rom_stem: str = "", label: str = "", content: Path | None = None) -> Match | None:
    """Find the best profile for a game. Name matches count most, then the
    disc's volume label, then files present on the disc."""
    best: Match | None = None
    for pid, prof in all_profiles().items():
        rules = prof.get("match") or {}
        score = 0
        reasons: list[str] = []
        if _globs(rules.get("names"), title) or (rom_stem and _globs(rules.get("names"), rom_stem)):
            score += 3
            reasons.append("name")
        if label and _globs(rules.get("labels"), label):
            score += 2
            reasons.append(f"label {label!r}")
        if content is not None:
            for rel in rules.get("files") or []:
                if case_insensitive(content, rel):
                    score += 2
                    reasons.append(f"file {rel}")
        if score >= 2 and (best is None or score > best.score):
            best = Match(pid, score, reasons)
    return best


def effective(profile_id: str | None, game_id: str | None) -> dict[str, Any]:
    merged = tomlutil.deep_merge(defaults(), user_config())
    prof = get(profile_id)
    if prof:
        merged = tomlutil.deep_merge(merged, {k: v for k, v in prof.items()
                                              if k not in ("match", "_source")})
    if game_id:
        merged = tomlutil.deep_merge(merged, tomlutil.load_if_exists(paths.game_settings_file(game_id)))
    return merged

"""Work out which executable is "the game" after an installer finishes."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import lnk
from .log import LOG
from .proton import to_unix_path

HARD_EXCLUDE = re.compile(
    r"(unins|uninst|uninstall|remove|dxsetup|dxwebsetup|directx|vcredist|vc_redist|redist|"
    r"dotnet|netfx|readme|eula|license|msiexec|isuninst|_isdel|wmfdist|gfwlivesetup|"
    r"crashreport|crashsender|errorreport|qtsetup|physx|oalinst)",
    re.I,
)
SOFT_PENALTY = re.compile(r"(setup|install|config|settings|update|patch|register|regist|help|web|"
                          r"support|manual|server|editor|tool|launcher|autorun|autoplay|demo)", re.I)
#: never scanned (Wine's own files and temporary installer payloads)
SKIP_ALWAYS = {"windows", "users/steamuser/appdata/local/temp", "users/steamuser/temp"}
#: additionally skipped when looking for executables; shortcuts in these
#: places (all-users Start Menu, public desktop) are exactly what we want
SKIP_FOR_EXES = SKIP_ALWAYS | {"programdata/microsoft", "users/public"}


@dataclass
class Snapshot:
    exes: set[str]
    links: set[str]


def _iter_files(root: Path, suffix: str, skip: set[str] | None = None):
    if not root.exists():
        return
    skip = SKIP_FOR_EXES if skip is None else skip
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel = os.path.relpath(dirpath, root).replace("\\", "/").lower()
        if rel != "." and any(rel == s or rel.startswith(s + "/") for s in skip):
            dirnames[:] = []
            continue
        for fn in filenames:
            if fn.lower().endswith(suffix):
                yield Path(dirpath) / fn


def snapshot(prefix: Path) -> Snapshot:
    dc = prefix / "drive_c"
    return Snapshot(
        exes={str(p) for p in _iter_files(dc, ".exe")},
        links={str(p) for p in _iter_files(dc, ".lnk", SKIP_ALWAYS)},
    )


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1 and w not in {"the", "of"}}


def _similarity(title: str, *names: str) -> float:
    tw = _words(title)
    if not tw:
        return 0.0
    best = 0.0
    for name in names:
        nw = _words(name)
        compact = re.sub(r"[^a-z0-9]", "", name.lower())
        hits = sum(1 for w in tw if w in nw or (len(w) > 3 and w in compact))
        best = max(best, hits / len(tw))
    return best


@dataclass
class Candidate:
    path: Path
    score: float
    why: str


def candidates(prefix: Path, title: str, preferred: list[str], before: Snapshot | None = None) -> list[Candidate]:
    """Rank executables in the prefix, best first."""
    after = snapshot(prefix)
    new_exes = after.exes - (before.exes if before else set())
    new_links = after.links - (before.links if before else set())
    scored: dict[str, Candidate] = {}

    def add(p: Path, score: float, why: str) -> None:
        key = str(p).lower()
        if key not in scored or scored[key].score < score:
            scored[key] = Candidate(p, score, why)

    wanted = [w.lower() for w in preferred]
    for exe in after.exes:
        name = Path(exe).name.lower()
        if name in wanted:
            add(Path(exe), 100 - wanted.index(name), "matches the game profile")

    for link_path in sorted(new_links):
        try:
            info = lnk.read(link_path)
        except (OSError, lnk.LnkError, ValueError, IndexError) as exc:
            LOG.debug("unreadable shortcut %s: %s", link_path, exc)
            continue
        if not info.target.lower().endswith(".exe"):
            continue
        target = to_unix_path(info.target, prefix)
        if not target.exists():
            real = _case_fix(target)
            if real is None:
                continue
            target = real
        link_name = Path(link_path).stem
        if HARD_EXCLUDE.search(target.name) or HARD_EXCLUDE.search(link_name):
            continue
        score = 50 + 20 * _similarity(title, link_name, target.stem)
        if SOFT_PENALTY.search(target.stem) or SOFT_PENALTY.search(link_name):
            score -= 25
        add(target, score, f"Start Menu shortcut '{link_name}'")

    for exe in new_exes:
        p = Path(exe)
        if HARD_EXCLUDE.search(p.name):
            continue
        try:
            size_mb = p.stat().st_size / 1e6
        except OSError:
            continue
        score = 10 + 20 * _similarity(title, p.stem, p.parent.name) + min(size_mb, 10)
        if SOFT_PENALTY.search(p.stem):
            score -= 15
        add(p, score, "new executable")
    return sorted(scored.values(), key=lambda c: c.score, reverse=True)


def _case_fix(path: Path) -> Path | None:
    """Wine paths are case-insensitive; find the real file on disk."""
    parts = path.parts
    cur = Path(parts[0])
    for part in parts[1:]:
        nxt = cur / part
        if not nxt.exists():
            try:
                match = next((cur / e for e in os.listdir(cur) if e.lower() == part.lower()), None)
            except OSError:
                return None
            if match is None:
                return None
            nxt = match
        cur = nxt
    return cur


def find_by_name(root: Path, names: list[str]) -> Path | None:
    wanted = [n.lower() for n in names]
    found: dict[str, Path] = {}
    for p in _iter_files(root, ".exe"):
        if p.name.lower() in wanted and p.name.lower() not in found:
            found[p.name.lower()] = p
    for n in wanted:
        if n in found:
            return found[n]
    return None

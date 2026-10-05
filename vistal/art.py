"""Find and cache artwork and Games Explorer metadata for library entries.

Tile artwork, in order of preference:
  1. your own file:  ~/.local/share/vistal/games/<id>/boxart.png|.jpg or icon.png
  2. the game's Games Explorer box art (GDF thumbnail), when it ships one
  3. the game executable's icon (largest size, up to 256x256)
  4. an ES-DE scraped cover (downloaded_media/<system>/covers/<rom>.png|.jpg)
  5. the icon named in the disc's autorun.inf (for games not installed yet)
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import discimage, icons, paths
from .log import LOG

IMAGE_EXTS = (".png", ".jpg", ".jpeg")


@dataclass
class Art:
    icon: Path | None = None      # square application icon (PNG)
    cover: Path | None = None     # box art (PNG or JPEG)
    info: dict[str, str] = field(default_factory=dict)  # GDF metadata
    cover_is_official: bool = False  # GDF thumbnail or user-supplied box art

    def tile(self, prefer: str = "auto") -> Path | None:
        if prefer == "covers":
            return self.cover or self.icon
        if prefer == "icons":
            return self.icon or self.cover
        return self.cover if self.cover and self.cover_is_official else (self.icon or self.cover)


def art_dir() -> Path:
    return paths.ensure(paths.cache_root() / "art")


def _sig(path: Path) -> str:
    try:
        st = path.stat()
    except OSError:
        return "missing"
    return f"{path}|{st.st_size}|{int(st.st_mtime)}"


def _user_override(game_id: str) -> tuple[Path | None, Path | None]:
    gd = paths.game_dir(game_id)
    cover = next((gd / f"boxart{e}" for e in IMAGE_EXTS if (gd / f"boxart{e}").exists()), None)
    icon = gd / "icon.png"
    return (icon if icon.exists() else None), cover


def esde_cover(rom: Path | None, system: str = "gfw") -> Path | None:
    if rom is None:
        return None
    from .frontends import esde_home
    base = esde_home() / "downloaded_media" / system
    for kind in ("covers", "3dboxes", "miximages"):
        for e in IMAGE_EXTS:
            cand = base / kind / f"{rom.stem}{e}"
            if cand.exists():
                return cand
    return None


def _cached(key: str, sig: str) -> dict | None:
    meta = art_dir() / f"{key}.json"
    try:
        data = json.loads(meta.read_text())
    except (OSError, ValueError):
        return None
    if data.get("sig") != sig:
        return None
    return data


def _store(key: str, sig: str, icon_png: bytes | None, cover: bytes | None, cover_ext: str,
           info: dict[str, str]) -> dict:
    d = art_dir()
    data: dict = {"sig": sig, "info": info}
    if icon_png:
        (d / f"{key}-icon.png").write_bytes(icon_png)
        data["icon"] = f"{key}-icon.png"
    if cover:
        name = f"{key}-cover{cover_ext}"
        (d / name).write_bytes(cover)
        data["cover"] = name
    (d / f"{key}.json").write_text(json.dumps(data))
    return data


def _thumb_ext(blob: bytes) -> str:
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if blob[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if blob[:2] == b"BM":
        return ".bmp"
    return ".bin"


def from_executable(exe: Path) -> dict:
    """Icon + GDF metadata of an installed game (cached by exe size/mtime)."""
    key = "exe-" + hashlib.sha1(str(exe).encode()).hexdigest()[:16]
    sig = _sig(exe)
    hit = _cached(key, sig)
    if hit is not None:
        return hit
    icon_png = None
    try:
        icon_png = icons.icon_png(exe)
    except Exception as exc:  # malformed resources are common in old games
        LOG.debug("no icon in %s: %s", exe, exc)
    info, cover, ext = {}, None, ""
    gdf = icons.find_gdf(exe)
    if gdf:
        info = gdf.as_dict()
        if gdf.thumbnail:
            cover, ext = gdf.thumbnail, _thumb_ext(gdf.thumbnail)
            if ext not in (".png", ".jpg"):
                cover = None
    return _store(key, sig, icon_png, cover, ext, info)


def _autorun_icon_spec(text: str) -> tuple[str, int] | None:
    auto = discimage.parse_autorun(text)
    spec = auto.get("icon")
    if not spec:
        return None
    spec = spec.strip().strip('"')
    m = re.match(r"^(.*?)(?:,\s*(-?\d+))?$", spec)
    return (m.group(1).strip().strip('"'), int(m.group(2) or 0)) if m else None


def _icon_from_blob(blob: bytes, index: int) -> bytes:
    if blob[:2] == b"MZ":
        groups = icons.pe_icon_groups(icons.read_pe_resources(blob))
        if not groups:
            raise icons.IconError("no icons")
        grp = groups[index] if 0 <= index < len(groups) else groups[0]
        return icons.image_to_png(icons.best(grp).data)
    return icons.icon_png_from_bytes(blob)


def from_disc(disc: Path) -> dict:
    """Icon from a disc's autorun.inf, read straight out of the image."""
    key = "disc-" + hashlib.sha1(str(disc).encode()).hexdigest()[:16]
    sig = _sig(disc)
    hit = _cached(key, sig)
    if hit is not None:
        return hit
    icon_png = None
    try:
        if disc.is_dir():
            from .media import case_insensitive
            auto = case_insensitive(disc, "autorun.inf")
            spec = _autorun_icon_spec(discimage.decode_text(auto.read_bytes())) if auto else None
            target = case_insensitive(disc, spec[0]) if spec else None
            if target:
                icon_png = _icon_from_blob(target.read_bytes(), spec[1])
        elif disc.suffix.lower() != ".chd":
            with discimage.Disc(str(disc)) as d:
                entry = d.fs.lookup("autorun.inf")
                spec = _autorun_icon_spec(discimage.decode_text(d.fs.read_file(entry))) if entry else None
                target = d.fs.lookup(spec[0]) if spec else None
                if target and not target.is_dir and target.size < 96 * 1024 * 1024:
                    icon_png = _icon_from_blob(d.fs.read_file(target), spec[1])
    except Exception as exc:  # artwork must never break the library
        LOG.debug("no disc icon for %s: %s", disc, exc)
    return _store(key, sig, icon_png, None, "", {})


def resolve(game_id: str, exe: Path | None, rom: Path | None, discs: list[Path]) -> Art:
    art = Art()
    d = art_dir()
    if exe is not None and exe.exists():
        data = from_executable(exe)
        art.info = data.get("info", {})
        if data.get("icon"):
            art.icon = d / data["icon"]
        if data.get("cover"):
            art.cover = d / data["cover"]
            art.cover_is_official = True
    if art.icon is None and discs:
        data = from_disc(discs[0])
        if data.get("icon"):
            art.icon = d / data["icon"]
    if art.cover is None:
        art.cover = esde_cover(rom)
    user_icon, user_cover = _user_override(game_id)
    if user_icon:
        art.icon = user_icon
    if user_cover:
        art.cover = user_cover
        art.cover_is_official = True
    return art

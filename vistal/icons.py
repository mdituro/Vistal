"""Game artwork: icons from Windows executables and .ico files, Games
Explorer metadata (GDF) embedded in game binaries, and a tiny PNG writer.

Everything here is pure Python so it works without any imaging library.

Windows Vista's Games Explorer reads two kinds of data from a game:
  * the executable's icon (RT_GROUP_ICON / RT_ICON resources), and
  * a Game Definition File: resources of type "DATA" named "__GDF_XML"
    (title, publisher, developer, genre, release date...) and
    "__GDF_THUMBNAIL" (box art), stored in the exe or a resource DLL.
"""

from __future__ import annotations

import re
import struct
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass, field
from pathlib import Path

RT_ICON = 3
RT_GROUP_ICON = 14


class IconError(ValueError):
    pass


# --------------------------------------------------------------------------
# PNG
# --------------------------------------------------------------------------


def write_png(width: int, height: int, rgba: bytes) -> bytes:
    """Encode 8-bit RGBA pixels (row-major, top-down) as PNG."""
    if len(rgba) != width * height * 4:
        raise ValueError("pixel buffer has the wrong size")

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    stride = width * 4
    raw = b"".join(b"\0" + rgba[y * stride : (y + 1) * stride] for y in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6))
            + chunk(b"IEND", b""))


def png_size(data: bytes) -> tuple[int, int]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise IconError("not a PNG")
    return struct.unpack(">II", data[16:24])


# --------------------------------------------------------------------------
# DIB (the BMP-style images inside .ico files)
# --------------------------------------------------------------------------


def dib_to_rgba(data: bytes) -> tuple[int, int, bytes]:
    """Decode an icon DIB (BITMAPINFOHEADER + XOR bitmap + AND mask)."""
    if len(data) < 40:
        raise IconError("truncated icon bitmap")
    hdr_size, width, height2, planes, bpp, compression = struct.unpack_from("<IiiHHI", data, 0)
    if compression not in (0, 3):  # BI_RGB / BI_BITFIELDS
        raise IconError(f"unsupported icon compression {compression}")
    height = abs(height2) // 2
    if width <= 0 or height <= 0 or width > 1024 or height > 1024:
        raise IconError("bad icon dimensions")
    clr_used = struct.unpack_from("<I", data, 32)[0]
    off = hdr_size
    if compression == 3:
        off += 12
    palette = []
    if bpp <= 8:
        count = clr_used or (1 << bpp)
        for i in range(count):
            b, g, r, _ = data[off + i * 4 : off + i * 4 + 4]
            palette.append((r, g, b))
        off += count * 4
    xor_stride = ((width * bpp + 31) // 32) * 4
    and_stride = ((width + 31) // 32) * 4
    xor = data[off : off + xor_stride * height]
    mask = data[off + xor_stride * height : off + xor_stride * height + and_stride * height]
    if len(xor) < xor_stride * height:
        raise IconError("truncated icon pixels")
    out = bytearray(width * height * 4)
    any_alpha = False
    for y in range(height):
        row = xor[(height - 1 - y) * xor_stride :]
        mrow = mask[(height - 1 - y) * and_stride :] if mask else b""
        for x in range(width):
            if bpp == 32:
                b, g, r, a = row[x * 4 : x * 4 + 4]
                if a:
                    any_alpha = True
            elif bpp == 24:
                b, g, r = row[x * 3 : x * 3 + 3]
                a = 255
            elif bpp == 16:
                v = row[x * 2] | (row[x * 2 + 1] << 8)
                r, g, b = ((v >> 10) & 31) * 255 // 31, ((v >> 5) & 31) * 255 // 31, (v & 31) * 255 // 31
                a = 255
            elif bpp in (1, 2, 4, 8):
                per = 8 // bpp
                byte = row[x // per]
                shift = (per - 1 - x % per) * bpp
                idx = (byte >> shift) & ((1 << bpp) - 1)
                r, g, b = palette[idx] if idx < len(palette) else (0, 0, 0)
                a = 255
            else:
                raise IconError(f"unsupported bit depth {bpp}")
            if bpp != 32 and mrow and len(mrow) > x // 8 and (mrow[x // 8] >> (7 - x % 8)) & 1:
                a = 0
            o = (y * width + x) * 4
            out[o : o + 4] = bytes((r, g, b, a))
    if bpp == 32 and not any_alpha:
        # old 32-bit icons without alpha: fall back to the AND mask
        for y in range(height):
            mrow = mask[(height - 1 - y) * and_stride :] if mask else b""
            for x in range(width):
                transparent = mrow and len(mrow) > x // 8 and (mrow[x // 8] >> (7 - x % 8)) & 1
                out[(y * width + x) * 4 + 3] = 0 if transparent else 255
    return width, height, bytes(out)


def image_to_png(data: bytes) -> bytes:
    """Icon image (PNG or DIB) -> PNG bytes."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return data
    w, h, rgba = dib_to_rgba(data)
    return write_png(w, h, rgba)


@dataclass
class IconImage:
    width: int
    height: int
    bpp: int
    data: bytes

    @property
    def score(self) -> tuple[int, int]:
        return (self.width * self.height, self.bpp)


def _dim(b: int) -> int:
    return 256 if b == 0 else b


def parse_ico(data: bytes) -> list[IconImage]:
    """Parse a .ico file."""
    if len(data) < 6:
        raise IconError("not an icon file")
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    if reserved != 0 or kind not in (1, 2) or count == 0 or count > 256:
        raise IconError("not an icon file")
    images = []
    for i in range(count):
        w, h, _, _, _, bpp, size, offset = struct.unpack_from("<BBBBHHII", data, 6 + i * 16)
        blob = data[offset : offset + size]
        if blob:
            images.append(_image(w, h, bpp, blob))
    return images


def _image(w: int, h: int, bpp: int, blob: bytes) -> IconImage:
    width, height = _dim(w), _dim(h)
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        try:
            width, height = png_size(blob)
        except IconError:
            pass
        bpp = 32
    elif len(blob) >= 16:
        _, bw, bh2, _, bbpp = struct.unpack_from("<IiiHH", blob, 0)
        width, height, bpp = bw or width, abs(bh2) // 2 or height, bbpp or bpp
    return IconImage(width, height, bpp, blob)


def best(images: list[IconImage]) -> IconImage:
    if not images:
        raise IconError("no icon images")
    return max(images, key=lambda i: i.score)


# --------------------------------------------------------------------------
# PE resources
# --------------------------------------------------------------------------


@dataclass
class PEResources:
    """Resource tree of a PE file: {type: {name: {lang: bytes}}}; types and
    names are ints (IDs) or upper-case strings."""

    entries: dict = field(default_factory=dict)

    def get(self, rtype, name=None) -> bytes | None:
        names = self.entries.get(rtype)
        if not names:
            return None
        if name is None:
            name = next(iter(names))
        langs = names.get(name)
        if not langs:
            return None
        return next(iter(langs.values()))


def read_pe_resources(data: bytes) -> PEResources:
    if data[:2] != b"MZ" or len(data) < 0x40:
        raise IconError("not a Windows executable")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe : pe + 4] != b"PE\0\0":
        raise IconError("not a PE executable (16-bit programs have no PE resources)")
    coff = pe + 4
    nsections = struct.unpack_from("<H", data, coff + 2)[0]
    opt_size = struct.unpack_from("<H", data, coff + 16)[0]
    opt = coff + 20
    magic = struct.unpack_from("<H", data, opt)[0]
    dd = opt + (96 if magic == 0x10B else 112)
    if dd + 24 > len(data):
        raise IconError("truncated PE header")
    rsrc_rva, rsrc_size = struct.unpack_from("<II", data, dd + 16)
    if not rsrc_rva:
        return PEResources()
    sections = []
    sec = opt + opt_size
    for i in range(nsections):
        vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", data, sec + i * 40 + 8)
        sections.append((vaddr, max(vsize, rawsize), rawptr))

    def rva_to_off(rva: int) -> int:
        for vaddr, size, rawptr in sections:
            if vaddr <= rva < vaddr + size:
                return rva - vaddr + rawptr
        raise IconError(f"RVA {rva:#x} outside sections")

    base = rva_to_off(rsrc_rva)

    def name_of(raw: int):
        if raw & 0x80000000:
            off = base + (raw & 0x7FFFFFFF)
            n = struct.unpack_from("<H", data, off)[0]
            return data[off + 2 : off + 2 + n * 2].decode("utf-16-le", "replace").upper()
        return raw

    def directory(off: int, depth: int) -> dict:
        if depth > 3 or off + 16 > len(data):
            return {}
        named, ids = struct.unpack_from("<HH", data, off + 12)
        out = {}
        for i in range(min(named + ids, 4096)):
            raw_name, target = struct.unpack_from("<II", data, off + 16 + i * 8)
            key = name_of(raw_name)
            if target & 0x80000000:
                out[key] = directory(base + (target & 0x7FFFFFFF), depth + 1)
            else:
                entry = base + target
                rva, size = struct.unpack_from("<II", data, entry)
                try:
                    start = rva_to_off(rva)
                except IconError:
                    continue
                out[key] = data[start : start + size]
        return out

    return PEResources(directory(base, 0))


def pe_icon_groups(res: PEResources) -> list[list[IconImage]]:
    groups = []
    icons = res.entries.get(RT_ICON, {})
    for _, langs in res.entries.get(RT_GROUP_ICON, {}).items():
        if not isinstance(langs, dict):
            continue
        grp = next(iter(langs.values()), b"")
        if len(grp) < 6:
            continue
        count = struct.unpack_from("<H", grp, 4)[0]
        images = []
        for i in range(count):
            if 6 + i * 14 + 14 > len(grp):
                break
            w, h, _, _, _, bpp, _, icon_id = struct.unpack_from("<BBBBHHIH", grp, 6 + i * 14)
            blob_langs = icons.get(icon_id)
            if isinstance(blob_langs, dict) and blob_langs:
                images.append(_image(w, h, bpp, next(iter(blob_langs.values()))))
        if images:
            groups.append(images)
    return groups


def icon_png_from_bytes(data: bytes) -> bytes:
    """Best (largest) icon from .ico or .exe/.dll bytes, as PNG."""
    if data[:2] == b"MZ":
        groups = pe_icon_groups(read_pe_resources(data))
        if not groups:
            raise IconError("executable has no icon")
        # the first group is the application icon Explorer shows
        return image_to_png(best(groups[0]).data)
    return image_to_png(best(parse_ico(data)).data)


def icon_png(path: str | Path) -> bytes:
    return icon_png_from_bytes(Path(path).read_bytes())


# --------------------------------------------------------------------------
# Game Definition Files (Vista Games Explorer metadata)
# --------------------------------------------------------------------------


@dataclass
class GameInfo:
    name: str = ""
    description: str = ""
    publisher: str = ""
    developer: str = ""
    genre: str = ""
    release_date: str = ""
    version: str = ""
    thumbnail: bytes = b""  # PNG/JPEG/BMP box art, as stored

    def as_dict(self) -> dict[str, str]:
        return {k: v for k, v in self.__dict__.items() if k != "thumbnail" and v}


def _decode_xml(blob: bytes) -> str:
    if blob[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return blob.decode("utf-16")
    if len(blob) > 1 and blob[1:2] == b"\0":
        return blob.decode("utf-16-le", "replace")
    return blob.decode("utf-8", "replace").lstrip("﻿")


def parse_gdf_xml(text: str) -> GameInfo:
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text.lstrip("﻿"))
    root = ET.fromstring(text)
    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]
    found: dict[str, list[str]] = {}
    for el in root.iter():
        t = (el.text or "").strip()
        if not t and local(el.tag) == "VersionNumber":
            t = el.get("versionNumber", "")
        if t:
            found.setdefault(local(el.tag), []).append(t)
    first = lambda *keys: next((found[k][0] for k in keys if found.get(k)), "")
    release = first("ReleaseDate")
    return GameInfo(
        name=first("Name"),
        description=first("Description"),
        publisher=", ".join(found.get("Publisher", [])),
        developer=", ".join(found.get("Developer", [])),
        genre=", ".join(found.get("Genre", [])),
        release_date=release[:10],
        version=first("VersionNumber", "FileVersion"),
    )


def gdf_from_pe(data: bytes) -> GameInfo | None:
    try:
        res = read_pe_resources(data)
    except (IconError, struct.error):
        return None
    blobs = res.entries.get("DATA") or {}
    xml_res = blobs.get("__GDF_XML")
    if not isinstance(xml_res, dict) or not xml_res:
        return None
    try:
        info = parse_gdf_xml(_decode_xml(next(iter(xml_res.values()))))
    except ET.ParseError:
        info = GameInfo()
    thumb = blobs.get("__GDF_THUMBNAIL")
    if isinstance(thumb, dict) and thumb:
        info.thumbnail = next(iter(thumb.values()))
    return info


def find_gdf(exe: Path, max_bytes: int = 64 * 1024 * 1024) -> GameInfo | None:
    """Look for GDF data in the game executable and DLLs next to it."""
    candidates = [exe]
    try:
        candidates += sorted(p for p in exe.parent.iterdir()
                             if p.suffix.lower() in (".dll", ".exe") and p != exe)
    except OSError:
        pass
    for p in candidates[:40]:
        try:
            if p.stat().st_size > max_bytes:
                continue
            data = p.read_bytes()
        except OSError:
            continue
        if b"_\0_\0G\0D\0F\0_\0X\0M\0L" not in data:
            continue
        info = gdf_from_pe(data)
        if info:
            return info
    return None

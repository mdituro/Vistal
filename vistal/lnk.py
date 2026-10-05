"""Read the target of a Windows shell link (.lnk), per [MS-SHLLINK]."""

from __future__ import annotations

import struct
from dataclasses import dataclass

HAS_IDLIST = 0x01
HAS_LINKINFO = 0x02
HAS_NAME = 0x04
HAS_RELPATH = 0x08
HAS_WORKDIR = 0x10
HAS_ARGS = 0x20
HAS_ICON = 0x40
IS_UNICODE = 0x80

LNK_CLSID = bytes.fromhex("0114020000000000c000000000000046")


class LnkError(ValueError):
    pass


@dataclass
class ShellLink:
    target: str = ""
    arguments: str = ""
    working_dir: str = ""
    relative_path: str = ""
    name: str = ""


def _cstr(data: bytes, off: int, wide: bool = False) -> str:
    if wide:
        end = off
        while end + 1 < len(data) and data[end : end + 2] != b"\0\0":
            end += 2
        return data[off:end].decode("utf-16-le", errors="replace")
    end = data.find(b"\0", off)
    if end < 0:
        end = len(data)
    return data[off:end].decode("cp1252", errors="replace")


def _idlist_path(data: bytes) -> str:
    """Best-effort path from an item ID list (drive item + file system items)."""
    parts: list[str] = []
    i = 0
    while i + 2 <= len(data):
        size = struct.unpack_from("<H", data, i)[0]
        if size == 0:
            break
        item = data[i + 2 : i + size]
        i += size
        if not item:
            continue
        kind = item[0] & 0x70
        if item[0] in (0x2F, 0x23, 0x25, 0x29, 0x2A, 0x2E) and len(item) > 3 and item[2:3] == b":":
            parts = [item[1:3].decode("ascii", "replace")]
        elif kind == 0x30 and len(item) > 12:
            short = _cstr(item, 12)
            long_name = _long_name(item, short)
            parts.append(long_name or short)
    if not parts:
        return ""
    return parts[0] + "\\" + "\\".join(parts[1:]) if len(parts) > 1 else parts[0] + "\\"


def _long_name(item: bytes, short: str) -> str:
    sig = item.find(b"\x04\x00\xef\xbe")
    if sig < 4:
        return ""
    block = item[sig - 4 :]
    for off in (0x12, 0x14, 0x1C, 0x2A, 0x2E):
        if off >= len(block):
            continue
        name = _cstr(block, off, wide=True)
        if name and name.isprintable() and ("." in name) == ("." in short):
            if not short or name.rsplit(".", 1)[-1].lower() == short.rsplit(".", 1)[-1].lower():
                return name
    return ""


def parse(data: bytes) -> ShellLink:
    if len(data) < 0x4C or struct.unpack_from("<I", data, 0)[0] != 0x4C or data[4:20] != LNK_CLSID:
        raise LnkError("not a shell link")
    flags = struct.unpack_from("<I", data, 0x14)[0]
    wide = bool(flags & IS_UNICODE)
    off = 0x4C
    link = ShellLink()
    if flags & HAS_IDLIST:
        size = struct.unpack_from("<H", data, off)[0]
        link.target = _idlist_path(data[off + 2 : off + 2 + size])
        off += 2 + size
    if flags & HAS_LINKINFO:
        info_size, hdr_size, info_flags = struct.unpack_from("<III", data, off)
        info = data[off : off + info_size]
        if info_flags & 0x01:
            base_off, _, suffix_off = struct.unpack_from("<III", info, 16)
            base = _cstr(info, base_off)
            suffix = _cstr(info, suffix_off) if suffix_off else ""
            if hdr_size >= 0x24:
                ubase_off, usuffix_off = struct.unpack_from("<II", info, 28)
                if ubase_off:
                    base = _cstr(info, ubase_off, wide=True)
                if usuffix_off:
                    suffix = _cstr(info, usuffix_off, wide=True)
            if base:
                link.target = base + suffix
        off += info_size

    def string() -> str:
        nonlocal off
        if off + 2 > len(data):
            return ""
        count = struct.unpack_from("<H", data, off)[0]
        off += 2
        nbytes = count * (2 if wide else 1)
        raw = data[off : off + nbytes]
        off += nbytes
        return raw.decode("utf-16-le" if wide else "cp1252", errors="replace")

    if flags & HAS_NAME:
        link.name = string()
    if flags & HAS_RELPATH:
        link.relative_path = string()
    if flags & HAS_WORKDIR:
        link.working_dir = string()
    if flags & HAS_ARGS:
        link.arguments = string()
    return link


def read(path) -> ShellLink:
    with open(path, "rb") as fh:
        return parse(fh.read())


def build(target: str, arguments: str = "", working_dir: str = "") -> bytes:
    """Create a minimal link (LinkInfo + strings). Used for tests and for
    writing shortcuts into prefixes."""
    flags = HAS_LINKINFO | IS_UNICODE
    if working_dir:
        flags |= HAS_WORKDIR
    if arguments:
        flags |= HAS_ARGS
    header = struct.pack("<I16sIIQQQIIIHHII", 0x4C, LNK_CLSID, flags, 0x20, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0)
    base = target.encode("cp1252", errors="replace") + b"\0"
    volume = struct.pack("<IIII", 16, 3, 0, 16) + b"\0"
    hdr = 0x1C
    vol_off = hdr
    base_off = vol_off + len(volume)
    suffix_off = base_off + len(base)
    body = volume + base + b"\0"
    info = struct.pack("<IIIIIII", hdr + len(body), hdr, 1, vol_off, base_off, 0, suffix_off) + body
    strings = b""
    for flag, value in ((HAS_WORKDIR, working_dir), (HAS_ARGS, arguments)):
        if flags & flag:
            strings += struct.pack("<H", len(value)) + value.encode("utf-16-le")
    return header + info + strings

"""Read-only access to CD/DVD images without root, FUSE or external tools.

Supported containers:
  * cooked ISO (.iso, 2048-byte sectors)
  * raw images (.bin/.img/.mdf, 2352/2336/2448-byte sectors, Mode 1 or Mode 2 XA)
  * CUE sheets (.cue) pointing at the above
  * Alcohol (.mds -> .mdf), CloneCD (.ccd -> .img), Nero (.nrg)

Supported filesystems:
  * ISO 9660 with Joliet (what virtually every Windows game disc uses)
  * Rock Ridge alternate names (for images authored on Linux)

UDF-only discs are detected and reported so callers can fall back to an
external extractor (7z / bsdtar).
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import shlex
import struct
from dataclasses import dataclass, field
from typing import Callable, Iterator

SECTOR = 2048

#: (description, sector size, offset of user data inside a sector)
SECTOR_LAYOUTS = [
    ("cooked", 2048, 0),
    ("raw-mode1", 2352, 16),
    ("raw-mode2", 2352, 24),
    ("mode2-2336", 2336, 8),
    ("raw-mode1+sub", 2448, 16),
    ("raw-mode2+sub", 2448, 24),
]

CUE_MODES = {
    "MODE1/2048": (2048, 0),
    "MODE1/2352": (2352, 16),
    "MODE2/2352": (2352, 24),
    "MODE2/2336": (2336, 8),
    "MODE2/2048": (2048, 0),
    "CDI/2352": (2352, 24),
}


class ImageError(Exception):
    """The image could not be opened or understood."""


class UDFOnlyError(ImageError):
    """The image carries a UDF filesystem but no ISO 9660 descriptors."""


# --------------------------------------------------------------------------
# Sector level access
# --------------------------------------------------------------------------


@dataclass
class Track:
    number: int
    mode: str
    file: str
    index1_frames: int = 0  # INDEX 01 position inside `file`, in frames

    @property
    def is_audio(self) -> bool:
        return self.mode.upper() == "AUDIO"


def _msf_to_frames(msf: str) -> int:
    m, s, f = (int(x) for x in msf.split(":"))
    return (m * 60 + s) * 75 + f


def parse_cue(path: str) -> list[Track]:
    """Parse a CUE sheet into tracks with absolute file paths."""
    base = os.path.dirname(os.path.abspath(path))
    tracks: list[Track] = []
    current_file: str | None = None
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                parts = shlex.split(line, posix=True)
            except ValueError:
                parts = line.split()
            if not parts:
                continue
            kw = parts[0].upper()
            if kw == "FILE" and len(parts) >= 2:
                current_file = _resolve_case_insensitive(base, parts[1])
            elif kw == "TRACK" and len(parts) >= 3 and current_file:
                tracks.append(Track(int(parts[1]), parts[2].upper(), current_file))
            elif kw == "INDEX" and len(parts) >= 3 and tracks:
                if int(parts[1]) == 1:
                    tracks[-1].index1_frames = _msf_to_frames(parts[2])
    if not tracks:
        raise ImageError(f"CUE sheet has no tracks: {path}")
    return tracks


def _resolve_case_insensitive(base: str, name: str) -> str:
    """CUE sheets written on Windows often disagree with the real file case."""
    name = name.replace("\\", "/")
    candidate = os.path.join(base, name)
    if os.path.exists(candidate):
        return candidate
    leaf = os.path.basename(name).lower()
    try:
        for entry in os.listdir(base):
            if entry.lower() == leaf:
                return os.path.join(base, entry)
    except OSError:
        pass
    return candidate


def _sibling(path: str, exts: list[str]) -> str | None:
    stem, _ = os.path.splitext(path)
    folder = os.path.dirname(path) or "."
    wanted = {(os.path.basename(stem) + e).lower() for e in exts}
    try:
        for entry in os.listdir(folder):
            if entry.lower() in wanted:
                return os.path.join(folder, entry)
    except OSError:
        pass
    return None


#: Nero images keep a chunk table at the end of the file; the first data
#: track normally starts at 0 or after a 150-sector pregap.
NRG_DATA_OFFSETS = [0, 150 * 2048, 150 * 2352]


class SectorReader:
    """Maps logical 2048-byte sectors onto the bytes of an image file."""

    def __init__(self, path: str, base: int, sector_size: int, data_offset: int, layout: str):
        self.path = path
        self.base = base
        self.sector_size = sector_size
        self.data_offset = data_offset
        self.layout = layout
        self._fh = open(path, "rb")
        self.file_size = os.fstat(self._fh.fileno()).st_size

    def close(self) -> None:
        self._fh.close()

    @property
    def sector_count(self) -> int:
        return max(0, (self.file_size - self.base) // self.sector_size)

    def read(self, lba: int, count: int = 1) -> bytes:
        """Return `count` user-data sectors starting at `lba`."""
        if count <= 0:
            return b""
        self._fh.seek(self.base + lba * self.sector_size)
        raw = self._fh.read(count * self.sector_size)
        if self.sector_size == SECTOR and self.data_offset == 0:
            data = raw
        else:
            out = bytearray()
            mv = memoryview(raw)
            for i in range(0, len(raw) - self.data_offset, self.sector_size):
                out += mv[i + self.data_offset : i + self.data_offset + SECTOR]
            data = bytes(out)
        if len(data) < count * SECTOR:
            data += b"\0" * (count * SECTOR - len(data))
        return data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _probe(path: str, bases: list[int], layouts=SECTOR_LAYOUTS) -> SectorReader:
    found_udf = False
    with open(path, "rb") as fh:
        size = os.fstat(fh.fileno()).st_size
        for base in bases:
            for name, ssize, doff in layouts:
                pos = base + 16 * ssize + doff
                if pos + 6 > size:
                    continue
                fh.seek(pos)
                head = fh.read(6)
                if head[1:6] == b"CD001" and head[0] in (0, 1, 2, 255):
                    # Make sure there really is a primary descriptor in the set.
                    for i in range(16, 32):
                        fh.seek(base + i * ssize + doff)
                        vd = fh.read(7)
                        if vd[1:6] != b"CD001":
                            break
                        if vd[0] == 1:
                            return SectorReader(path, base, ssize, doff, name)
                        if vd[0] == 255:
                            break
                if head[1:6] in (b"BEA01", b"NSR02", b"NSR03"):
                    found_udf = True
    if found_udf:
        raise UDFOnlyError(f"{path}: UDF-only disc (no ISO 9660 filesystem)")
    raise ImageError(f"{path}: no ISO 9660 filesystem found")


def open_image(path: str) -> SectorReader:
    """Open any supported image and return a sector reader for its data track."""
    if not os.path.exists(path):
        raise ImageError(f"No such image: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext == ".cue":
        tracks = parse_cue(path)
        data = next((t for t in tracks if not t.is_audio), None)
        if data is None:
            raise ImageError(f"{path}: audio-only disc, nothing to install")
        if not os.path.exists(data.file):
            raise ImageError(f"{path}: referenced file is missing: {data.file}")
        ssize, doff = CUE_MODES.get(data.mode, (2352, 16))
        base = data.index1_frames * ssize
        # Trust the cue first, fall back to probing in case it lies.
        try:
            return _probe(data.file, [base], [(data.mode.lower(), ssize, doff)])
        except ImageError:
            return _probe(data.file, [base, 0])
    if ext == ".mds":
        mdf = _sibling(path, [".mdf"])
        if not mdf:
            raise ImageError(f"{path}: matching .mdf file not found")
        return _probe(mdf, [0])
    if ext == ".ccd":
        img = _sibling(path, [".img"])
        if not img:
            raise ImageError(f"{path}: matching .img file not found")
        return _probe(img, [0])
    return _probe(path, NRG_DATA_OFFSETS if ext == ".nrg" else [0])


# --------------------------------------------------------------------------
# ISO 9660 / Joliet / Rock Ridge
# --------------------------------------------------------------------------


@dataclass
class Entry:
    name: str
    is_dir: bool
    extents: list[tuple[int, int]]  # (lba, byte length)
    mtime: float = 0.0
    hidden: bool = False
    path: str = ""
    children: list["Entry"] | None = field(default=None, repr=False)

    @property
    def size(self) -> int:
        return sum(length for _, length in self.extents)


def _both_endian32(buf: bytes, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def _record_time(b: bytes) -> float:
    try:
        year, month, day, hour, minute, sec, gmtoff = struct.unpack("6Bb", b[:7])
        if month == 0 or day == 0:
            return 0.0
        tz = _dt.timezone(_dt.timedelta(minutes=15 * gmtoff))
        return _dt.datetime(1900 + year, month, day, hour, minute, sec, tzinfo=tz).timestamp()
    except (ValueError, OverflowError, struct.error):
        return 0.0


class ISO9660:
    """A parsed ISO 9660 filesystem."""

    def __init__(self, reader: SectorReader):
        self.reader = reader
        self.pvd: bytes | None = None
        self.joliet: bytes | None = None
        lba = 16
        while lba < 16 + 64:
            vd = reader.read(lba)
            if vd[1:6] != b"CD001":
                break
            vtype = vd[0]
            if vtype == 1 and self.pvd is None:
                self.pvd = vd
            elif vtype == 2 and self.joliet is None and vd[88:90] == b"%/" and vd[90:91] in (b"@", b"C", b"E"):
                self.joliet = vd
            elif vtype == 255:
                break
            lba += 1
        if self.pvd is None:
            raise ImageError("Primary volume descriptor not found")
        self.use_joliet = self.joliet is not None
        self.susp_skip: int | None = None  # None = Rock Ridge not detected yet
        desc = self.joliet if self.use_joliet else self.pvd
        self.block_size = struct.unpack_from("<H", self.pvd, 128)[0] or SECTOR
        root_rec = desc[156:190]
        self.root = self._parse_record(root_rec, "", is_root=True)
        self.root.path = ""
        if not self.use_joliet:
            self._detect_rock_ridge()

    # -- metadata ---------------------------------------------------------

    @property
    def label(self) -> str:
        """Volume label as Windows reports it (Joliet wins when present)."""
        if self.joliet is not None:
            j = self.joliet[40:72].decode("utf-16-be", errors="replace").rstrip(" \0")
            if j:
                return j
        return self.pvd[40:72].decode("ascii", errors="replace").rstrip(" \0")

    @property
    def iso_label(self) -> str:
        return self.pvd[40:72].decode("ascii", errors="replace").rstrip(" \0")

    @property
    def serial(self) -> int:
        """Volume serial number exactly as Wine/Windows NT derive it for CDFS."""
        desc = self.joliet if self.joliet is not None else self.pvd
        s = [0, 0, 0, 0]
        for i in range(0, 2048, 4):
            s[0] = (s[0] + desc[i]) & 0xFF
            s[1] = (s[1] + desc[i + 1]) & 0xFF
            s[2] = (s[2] + desc[i + 2]) & 0xFF
            s[3] = (s[3] + desc[i + 3]) & 0xFF
        return (s[0] << 24) | (s[1] << 16) | (s[2] << 8) | s[3]

    @property
    def volume_size(self) -> int:
        return _both_endian32(self.pvd, 80) * self.block_size

    # -- directory parsing --------------------------------------------------

    def _detect_rock_ridge(self) -> None:
        data = self.reader.read(self.root.extents[0][0])
        if not data or data[0] < 34:
            return
        rec = data[: data[0]]
        name_len = rec[32]
        su = rec[33 + name_len + (1 - name_len % 2) :]
        if len(su) >= 7 and su[:2] == b"SP" and su[4:6] == b"\xbe\xef":
            self.susp_skip = su[6]

    def _rr_name(self, system_use: bytes) -> str | None:
        if self.susp_skip is None:
            return None
        data = system_use[self.susp_skip :]
        name = b""
        found = False
        i = 0
        while i + 4 <= len(data):
            sig = data[i : i + 2]
            length = data[i + 2]
            if length < 4:
                break
            if sig == b"NM" and length >= 5:
                flags = data[i + 4]
                if flags & 0x06:  # CURRENT / PARENT
                    return None
                name += data[i + 5 : i + length]
                found = True
            elif sig == b"ST":
                break
            i += length
        return name.decode("utf-8", errors="replace") if found else None

    def _parse_record(self, rec: bytes, parent_path: str, is_root: bool = False) -> Entry:
        lba = _both_endian32(rec, 2)
        length = _both_endian32(rec, 10)
        flags = rec[25]
        name_len = rec[32]
        raw_name = rec[33 : 33 + name_len]
        if is_root:
            name = ""
        elif self.use_joliet:
            name = raw_name.decode("utf-16-be", errors="replace")
        else:
            name = raw_name.decode("latin-1")
        if not is_root and not self.use_joliet:
            pad = 1 if name_len % 2 == 0 else 0
            alt = self._rr_name(rec[33 + name_len + pad :])
            if alt:
                name = alt
        is_dir = bool(flags & 0x02)
        if not is_dir:
            name = re.sub(r";\d+$", "", name)
            if name.endswith(".") and len(name) > 1:
                name = name[:-1]
        entry = Entry(
            name=name,
            is_dir=is_dir,
            extents=[(lba, length)],
            mtime=_record_time(rec[18:25]),
            hidden=bool(flags & 0x01),
        )
        entry.path = f"{parent_path}/{name}" if parent_path else name
        return entry

    def listdir(self, entry: Entry) -> list[Entry]:
        if not entry.is_dir:
            raise NotADirectoryError(entry.path)
        if entry.children is not None:
            return entry.children
        lba, length = entry.extents[0]
        sectors = (length + SECTOR - 1) // SECTOR
        data = self.reader.read(lba, sectors)
        children: list[Entry] = []
        pending_multi: Entry | None = None
        for s in range(sectors):
            off = s * SECTOR
            end = off + SECTOR
            while off < end:
                rec_len = data[off]
                if rec_len == 0:
                    break
                rec = data[off : off + rec_len]
                off += rec_len
                if len(rec) < 34:
                    break
                name_len = rec[32]
                if name_len == 1 and rec[33] in (0, 1):
                    continue  # "." and ".."
                child = self._parse_record(rec, entry.path)
                multi = bool(rec[25] & 0x80)
                if pending_multi is not None and pending_multi.name == child.name:
                    pending_multi.extents.extend(child.extents)
                    if not multi:
                        pending_multi = None
                    continue
                children.append(child)
                pending_multi = child if multi else None
        entry.children = children
        return children

    def walk(self, entry: Entry | None = None) -> Iterator[Entry]:
        """Depth-first iteration over every entry below `entry` (exclusive)."""
        stack = [entry or self.root]
        seen: set[int] = set()
        while stack:
            cur = stack.pop()
            for child in self.listdir(cur):
                yield child
                if child.is_dir:
                    key = child.extents[0][0]
                    if key in seen:  # defend against looping images
                        continue
                    seen.add(key)
                    stack.append(child)

    def lookup(self, path: str) -> Entry | None:
        """Case-insensitive path lookup ('/' or '\\' separated)."""
        cur = self.root
        for part in [p for p in re.split(r"[\\/]+", path) if p]:
            if not cur.is_dir:
                return None
            nxt = None
            for child in self.listdir(cur):
                if child.name.lower() == part.lower():
                    nxt = child
                    break
            if nxt is None:
                return None
            cur = nxt
        return cur

    def iter_file(self, entry: Entry, chunk_sectors: int = 512) -> Iterator[bytes]:
        for lba, length in entry.extents:
            remaining = length
            cur = lba
            while remaining > 0:
                n = min(chunk_sectors, (remaining + SECTOR - 1) // SECTOR)
                block = self.reader.read(cur, n)
                take = min(remaining, len(block))
                yield block[:take]
                remaining -= take
                cur += n

    def read_file(self, entry: Entry | str) -> bytes:
        if isinstance(entry, str):
            found = self.lookup(entry)
            if found is None:
                raise FileNotFoundError(entry)
            entry = found
        return b"".join(self.iter_file(entry))

    def total_file_bytes(self) -> int:
        return sum(e.size for e in self.walk() if not e.is_dir)

    def extract(
        self,
        dest: str,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> None:
        """Extract the whole filesystem to `dest`."""
        os.makedirs(dest, exist_ok=True)
        entries = list(self.walk())
        total = sum(e.size for e in entries if not e.is_dir)
        done = 0
        dirs: list[Entry] = []
        for e in entries:
            target = os.path.join(dest, *_safe_parts(e.path))
            if e.is_dir:
                os.makedirs(target, exist_ok=True)
                dirs.append(e)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as out:
                for chunk in self.iter_file(e):
                    out.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total, e.path)
            if e.mtime:
                try:
                    os.utime(target, (e.mtime, e.mtime))
                except OSError:
                    pass
        for d in dirs:
            if d.mtime:
                try:
                    os.utime(os.path.join(dest, *_safe_parts(d.path)), (d.mtime, d.mtime))
                except OSError:
                    pass
        if progress:
            progress(total, total, "")


def _safe_parts(path: str) -> list[str]:
    parts = []
    for p in path.split("/"):
        if p in ("", ".", ".."):
            continue
        parts.append(p.replace("\0", "_"))
    return parts


class Disc:
    """Convenience wrapper: open an image file and its filesystem in one go."""

    def __init__(self, path: str):
        self.path = path
        self.reader = open_image(path)
        try:
            self.fs = ISO9660(self.reader)
        except Exception:
            self.reader.close()
            raise

    def close(self) -> None:
        self.reader.close()

    def __enter__(self) -> "Disc":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def label(self) -> str:
        return self.fs.label

    @property
    def serial(self) -> int:
        return self.fs.serial


def parse_autorun(text: str) -> dict[str, str]:
    """Parse the [autorun] section of an autorun.inf."""
    out: dict[str, str] = {}
    section = None
    for line in text.splitlines():
        line = line.strip().lstrip("﻿")
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and "]" in line:
            section = line[1 : line.index("]")].strip().lower()
            continue
        if section == "autorun" and "=" in line:
            key, val = line.split("=", 1)
            out[key.strip().lower()] = val.strip()
    return out


def decode_text(data: bytes) -> str:
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    for enc in ("utf-8", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")

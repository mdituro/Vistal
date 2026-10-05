"""Turn whatever a frontend hands us (ISO, CUE, M3U, folder, .vistal file...)
into a game source, and turn disc images into directories Wine can expose as
CD-ROM drives.

Disc access strategies (config key `disc.method`):
  extract  - copy files out of the image with the built-in ISO reader (always
             works, costs disk space once; cached across launches)
  fuseiso  - mount via FUSE when `fuseiso` is installed (no copy)
  udisks   - loop-mount through udisksctl (cooked .iso only; no copy)
  auto     - reuse a finished extraction, else fuseiso, else extract

Every disc is presented to Wine through a small "drive root" directory that
holds symlinks to the disc's top-level entries plus `.windows-label` and
`.windows-serial`, which Wine reports as the CD's volume label and serial.
That is what keeps label-based "please insert the disc" checks happy.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import discimage, paths, tomlutil
from .log import LOG
from .ui import Progress

IMAGE_EXTS = {".iso", ".bin", ".img", ".mdf", ".mds", ".nrg", ".ccd", ".cue", ".chd"}
ROM_EXTS = IMAGE_EXTS | {".m3u", ".vistal", ".exe", ".lnk"}

_TAG_RE = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")
_DISC_RE = re.compile(r"[\s_\-]*(disc|disk|cd)[\s_\-]*\d+.*$", re.I)


class MediaError(Exception):
    pass


@dataclass
class GameSource:
    """A launchable thing as selected in a frontend."""

    rom: Path
    id: str
    title: str
    kind: str  # "discs" | "portable" | "exe"
    discs: list[Path] = field(default_factory=list)
    exe: Path | None = None  # for portable folders / direct .exe
    spec: dict[str, Any] = field(default_factory=dict)  # contents of a .vistal file

    @property
    def has_discs(self) -> bool:
        return bool(self.discs)


def clean_title(stem: str) -> str:
    title = _TAG_RE.sub("", stem)
    title = _DISC_RE.sub("", title)
    title = title.replace("_", " ").strip(" -.")
    return title or stem


def read_m3u(path: Path) -> list[Path]:
    discs = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip().lstrip("\ufeff")
        if not line or line.startswith("#"):
            continue
        p = Path(line.replace("\\", "/"))
        if not p.is_absolute():
            p = path.parent / p
        discs.append(p)
    if not discs:
        raise MediaError(f"{path}: playlist is empty")
    return discs


def _disc_dir(path: Path) -> bool:
    """A folder that looks like the contents of an installation disc."""
    names = {n.lower() for n in os.listdir(path)}
    return bool(names & {"autorun.inf", "setup.exe", "install.exe", "autorun.exe", "setup.msi"})


def resolve(rom: str | os.PathLike) -> GameSource:
    """Classify a frontend-supplied path."""
    p = Path(rom).expanduser()
    if not p.exists():
        raise MediaError(f"Not found: {p}")
    p = p.resolve()
    stem = p.stem if p.is_file() else p.name
    title = clean_title(stem)
    gid = paths.slugify(title)
    ext = p.suffix.lower()

    if p.is_dir():
        # ES-DE style "directory as file": Game.m3u/Game.m3u, Game.iso/Game.iso
        if ext in ROM_EXTS:
            inner = next((p / e for e in os.listdir(p) if e.lower() == p.name.lower() and (p / e).is_file()), None)
            if inner is not None:
                return resolve(inner)
        if _disc_dir(p):
            return GameSource(p, gid, title, "discs", discs=[p])
        return GameSource(p, gid, title, "portable")
    if ext == ".m3u":
        discs = read_m3u(p)
        missing = [str(d) for d in discs if not d.exists()]
        if missing:
            raise MediaError("Playlist references missing discs:\n  " + "\n  ".join(missing))
        return GameSource(p, gid, title, "discs", discs=discs)
    if ext == ".vistal":
        return _from_spec(p, gid, title)
    if ext == ".exe":
        return GameSource(p, gid, title, "exe", exe=p)
    if ext in IMAGE_EXTS:
        return GameSource(p, gid, title, "discs", discs=[p])
    raise MediaError(f"Unsupported file type '{ext}': {p}")


def _from_spec(p: Path, gid: str, title: str) -> GameSource:
    """A .vistal file is a small TOML document describing a game, e.g.

        title = "Freelancer"
        id = "freelancer"            # optional, ties it to an existing install
        discs = ["Freelancer.iso"]   # optional, relative to this file
        exe = "C:/Program Files (x86)/Microsoft Games/Freelancer/EXE/Freelancer.exe"
        profile = "freelancer"       # optional built-in profile to apply
    """
    spec = tomlutil.load(p)
    title = spec.get("title", title)
    gid = spec.get("id") or paths.slugify(title)
    discs = []
    for d in spec.get("discs", []):
        dp = Path(d).expanduser()
        discs.append(dp if dp.is_absolute() else (p.parent / dp))
    exe = spec.get("exe")
    kind = "discs" if discs else "portable"
    exe_path = None
    if exe and not re.match(r"^[A-Za-z]:", exe):
        ep = Path(exe).expanduser()
        exe_path = ep if ep.is_absolute() else (p.parent / ep)
        if not discs:
            kind = "exe"
    return GameSource(p, gid, title, kind, discs=discs, exe=exe_path, spec=spec)


# --------------------------------------------------------------------------
# Disc preparation
# --------------------------------------------------------------------------


@dataclass
class PreparedDisc:
    source: Path
    content: Path  # where the files actually are (extract dir or mountpoint)
    label: str
    serial: int
    method: str
    device: str | None = None  # loop device when mounted through udisks
    _cleanup: list = field(default_factory=list, repr=False)

    def release(self) -> None:
        for fn in reversed(self._cleanup):
            try:
                fn()
            except Exception as exc:  # pragma: no cover - best effort
                LOG.debug("cleanup failed: %s", exc)
        self._cleanup.clear()


def _cache_key(path: Path) -> str:
    st = path.stat()
    h = hashlib.sha1(f"{path.resolve()}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:12]
    return f"{paths.slugify(path.stem)[:40]}-{h}"


def _metadata(path: Path) -> tuple[str, int]:
    with discimage.Disc(str(path)) as disc:
        return disc.label, disc.serial


def _label_for_dir(path: Path) -> tuple[str, int]:
    lbl = path / ".windows-label"
    ser = path / ".windows-serial"
    label = lbl.read_text(errors="replace").strip() if lbl.exists() else path.name.upper()[:32]
    serial = 0
    if ser.exists():
        try:
            serial = int(ser.read_text().strip(), 16)
        except ValueError:
            pass
    if not serial:
        serial = int(hashlib.sha1(label.encode()).hexdigest()[:8], 16)
    return label, serial


def _resolve_chd(path: Path, progress: Progress | None) -> Path:
    chdman = shutil.which("chdman")
    if not chdman:
        raise MediaError("CHD images need 'chdman' (from MAME tools) to be installed")
    out_dir = paths.ensure(paths.extract_cache() / (_cache_key(path) + "-chd"))
    cue = out_dir / (path.stem + ".cue")
    if not cue.exists():
        LOG.info("Converting %s with chdman", path.name)
        if progress:
            progress.update(0.0, "Converting CHD image...")
        subprocess.run([chdman, "extractcd", "-i", str(path), "-o", str(cue),
                        "-ob", str(out_dir / (path.stem + ".bin"))], check=True)
    return cue


def _extract(path: Path, progress: Progress | None) -> Path:
    dest = paths.extract_cache() / _cache_key(path)
    marker = dest / ".vistal-complete"
    if marker.exists():
        return dest
    if dest.exists():
        shutil.rmtree(dest)
    tmp = dest.with_name(dest.name + ".partial")
    if tmp.exists():
        shutil.rmtree(tmp)
    LOG.info("Extracting %s -> %s", path.name, dest)
    try:
        with discimage.Disc(str(path)) as disc:
            def cb(done: int, total: int, name: str) -> None:
                if progress and not progress.update(done / total if total else 1.0,
                                                    f"Reading disc: {name}" if name else ""):
                    raise MediaError("Cancelled")
            disc.fs.extract(str(tmp), cb)
    except discimage.UDFOnlyError:
        _external_extract(path, tmp)
    os.replace(tmp, dest)
    marker.write_text(time.strftime("%Y-%m-%d %H:%M:%S\n"))
    return dest


def _external_extract(path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for tool, args in (("7z", ["x", "-y", f"-o{dest}", str(path)]),
                       ("7za", ["x", "-y", f"-o{dest}", str(path)]),
                       ("bsdtar", ["-xf", str(path), "-C", str(dest)])):
        exe = shutil.which(tool)
        if exe:
            LOG.info("UDF image: extracting with %s", tool)
            subprocess.run([exe, *args], check=True, stdout=subprocess.DEVNULL)
            return
    raise MediaError(f"{path.name} is a UDF-only disc; install 7z or bsdtar to read it")


def _mount_fuseiso(path: Path) -> tuple[Path, list] | None:
    exe = shutil.which("fuseiso")
    if not exe:
        return None
    mnt = paths.ensure(paths.mounts_dir() / _cache_key(path))
    if os.path.ismount(mnt):
        return mnt, []
    res = subprocess.run([exe, "-p", str(path), str(mnt)], capture_output=True, text=True)
    if res.returncode != 0 or not os.path.ismount(mnt):
        LOG.debug("fuseiso failed: %s", res.stderr.strip())
        return None
    um = shutil.which("fusermount3") or shutil.which("fusermount") or "fusermount"
    return mnt, [lambda: subprocess.run([um, "-u", str(mnt)], capture_output=True)]


def _mount_udisks(path: Path) -> tuple[Path, str, list] | None:
    exe = shutil.which("udisksctl")
    if not exe or path.suffix.lower() != ".iso":
        return None
    res = subprocess.run([exe, "loop-setup", "-r", "--no-user-interaction", "-f", str(path)],
                         capture_output=True, text=True)
    m = re.search(r"(/dev/loop\d+)", res.stdout)
    if res.returncode != 0 or not m:
        LOG.debug("udisks loop-setup failed: %s", res.stderr.strip())
        return None
    dev = m.group(1)
    cleanup = [lambda: subprocess.run([exe, "loop-delete", "--no-user-interaction", "-b", dev],
                                      capture_output=True)]
    res = subprocess.run([exe, "mount", "--no-user-interaction", "-b", dev], capture_output=True, text=True)
    m = re.search(r" at (/.+?)\.?$", res.stdout.strip())
    if res.returncode != 0 or not m:
        for fn in cleanup:
            fn()
        return None
    mnt = Path(m.group(1))
    cleanup.append(lambda: subprocess.run([exe, "unmount", "--no-user-interaction", "-b", dev],
                                          capture_output=True))
    return mnt, dev, cleanup


def prepare_disc(path: Path, method: str = "auto", progress: Progress | None = None) -> PreparedDisc:
    """Make the contents of one disc available as a directory."""
    path = Path(path)
    if path.is_dir():
        label, serial = _label_for_dir(path)
        return PreparedDisc(path, path, label, serial, "directory")
    if path.suffix.lower() == ".chd":
        path = _resolve_chd(path, progress)
    try:
        label, serial = _metadata(path)
    except discimage.UDFOnlyError:
        label, serial = path.stem.upper()[:32], int(hashlib.sha1(path.name.encode()).hexdigest()[:8], 16)
    except discimage.ImageError as exc:
        raise MediaError(str(exc)) from exc

    cached = paths.extract_cache() / _cache_key(path) / ".vistal-complete"
    order = {
        "auto": ["cached", "fuseiso", "extract"],
        "extract": ["extract"],
        "fuseiso": ["fuseiso", "extract"],
        "udisks": ["udisks", "fuseiso", "extract"],
    }.get(method, ["cached", "fuseiso", "extract"])
    for step in order:
        if step == "cached" and cached.exists():
            return PreparedDisc(path, cached.parent, label, serial, "extract")
        if step == "fuseiso":
            got = _mount_fuseiso(path)
            if got:
                return PreparedDisc(path, got[0], label, serial, "fuseiso", _cleanup=got[1])
        if step == "udisks":
            got = _mount_udisks(path)
            if got:
                return PreparedDisc(path, got[0], label, serial, "udisks", device=got[1], _cleanup=got[2])
        if step == "extract":
            return PreparedDisc(path, _extract(path, progress), label, serial, "extract")
    raise MediaError(f"Could not open {path}")


def build_drive_root(disc: PreparedDisc, root: Path) -> Path:
    """Create the directory a Wine drive letter points at for this disc."""
    if root.is_symlink() or root.is_file():
        root.unlink()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    for entry in os.listdir(disc.content):
        if entry in (".windows-label", ".windows-serial", ".vistal-complete"):
            continue
        os.symlink(disc.content / entry, root / entry)
    (root / ".windows-label").write_text(disc.label + "\n")
    (root / ".windows-serial").write_text(f"{disc.serial:08x}\n")
    return root


def find_installer(content: Path) -> tuple[Path, list[str]] | None:
    """Locate the installer on a disc: autorun.inf first, then common names."""
    entries = {e.lower(): e for e in os.listdir(content)}
    if "autorun.inf" in entries:
        text = discimage.decode_text((content / entries["autorun.inf"]).read_bytes())
        auto = discimage.parse_autorun(text)
        cmd = auto.get("open") or auto.get("shellexecute")
        if cmd:
            target, args = _split_command(cmd)
            found = case_insensitive(content, target)
            if found and found.suffix.lower() in (".exe", ".msi", ".bat", ".com"):
                # Some discs autorun a splash/menu that only offers "Install";
                # that is fine - Proton keeps waiting until every child exits.
                return found, args
    for name in ("setup.exe", "install.exe", "autorun.exe", "setup.msi", "autoplay.exe", "launch.exe"):
        if name in entries:
            return content / entries[name], []
    for sub in ("setup", "install", "disk1", "cd1"):
        if sub in entries and (content / entries[sub]).is_dir():
            got = find_installer(content / entries[sub])
            if got:
                return got
    return None


def _split_command(cmd: str) -> tuple[str, list[str]]:
    cmd = cmd.strip()
    if cmd.startswith('"'):
        end = cmd.find('"', 1)
        if end > 0:
            return cmd[1:end], cmd[end + 1 :].split()
    # unquoted: take the longest prefix ending in a known extension
    m = re.match(r"^(.+?\.(?:exe|msi|bat|com))(\s+.*)?$", cmd, re.I)
    if m:
        return m.group(1), (m.group(2) or "").split()
    parts = cmd.split()
    return parts[0], parts[1:]


def case_insensitive(base: Path, rel: str) -> Path | None:
    cur = base
    for part in [p for p in re.split(r"[\\/]+", rel) if p and p != "."]:
        if not cur.is_dir():
            return None
        match = None
        for e in os.listdir(cur):
            if e.lower() == part.lower():
                match = cur / e
                break
        if match is None:
            return None
        cur = match
    return cur

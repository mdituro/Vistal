"""Find Proton builds installed through Steam and run Windows programs with
them outside of Steam's own game list.

Launch strategies, in order of preference:
  1. umu-run (umu-launcher): the reference way to run Proton outside Steam.
  2. Steam Linux Runtime entry point + `proton waitforexitandrun`: exactly
     what Steam itself executes for a Proton game.
  3. `proton waitforexitandrun` directly on the host (works on SteamOS).
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from . import paths, vdf
from .log import LOG

# Steam Linux Runtime tool app ids -> usual install directory names
RUNTIME_DIRS = {
    "1628350": "SteamLinuxRuntime_sniper",
    "1391110": "SteamLinuxRuntime_soldier",
    "3810310": "SteamLinuxRuntime_4",
}


class ProtonError(Exception):
    pass


@dataclass
class ProtonBuild:
    name: str
    path: Path
    kind: str  # "valve" | "experimental" | "ge" | "other"
    version: tuple[int, ...] = ()
    runtime_appid: str | None = None

    @property
    def script(self) -> Path:
        return self.path / "proton"

    def _bin(self, name: str) -> Path | None:
        for sub in ("files", "dist"):
            cand = self.path / sub / "bin" / name
            if cand.exists():
                return cand
        return None

    @property
    def wine(self) -> Path | None:
        return self._bin("wine")

    @property
    def wineserver(self) -> Path | None:
        return self._bin("wineserver")

    def __str__(self) -> str:
        return f"{self.name} ({self.path})"


def steam_roots() -> list[Path]:
    home = Path.home()
    cands = [
        os.environ.get("VISTAL_STEAM_ROOT"),
        home / ".steam" / "root",
        home / ".steam" / "steam",
        home / ".local" / "share" / "Steam",
        home / ".var" / "app" / "com.valvesoftware.Steam" / "data" / "Steam",
        home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
    ]
    seen: set[Path] = set()
    roots: list[Path] = []
    for c in cands:
        if not c:
            continue
        p = Path(c)
        try:
            real = p.resolve()
        except OSError:
            continue
        if real in seen or not (real / "steamapps").is_dir():
            continue
        seen.add(real)
        roots.append(real)
    return roots


def library_dirs(root: Path) -> list[Path]:
    """All Steam library folders (each containing steamapps/) known to `root`."""
    libs = [root]
    lf = root / "steamapps" / "libraryfolders.vdf"
    if lf.exists():
        try:
            data = vdf.get_ci(vdf.load(lf), "libraryfolders", {})
        except (OSError, vdf.VDFError) as exc:
            LOG.debug("cannot parse %s: %s", lf, exc)
            data = {}
        for key, val in data.items():
            if isinstance(val, dict):
                p = vdf.get_ci(val, "path")
            elif key.isdigit():
                p = val
            else:
                continue
            if p and Path(p) not in libs and (Path(p) / "steamapps").is_dir():
                libs.append(Path(p))
    return libs


def _classify(name: str) -> tuple[str, tuple[int, ...]]:
    if re.search(r"experimental", name, re.I):
        return "experimental", (999,)
    m = re.match(r"^(?:GE-Proton|Proton-GE|Proton-)(\d+)[-.](\d+)", name, re.I)
    if m:
        return "ge", (int(m.group(1)), int(m.group(2)))
    m = re.match(r"^Proton[ _-]?(\d+)\.(\d+)(?:[-.](\d+))?", name, re.I)
    if m:
        return "valve", tuple(int(x) for x in m.groups() if x is not None)
    nums = tuple(int(x) for x in re.findall(r"\d+", name)[:3])
    return "other", nums


def _read_manifest(path: Path) -> str | None:
    tm = path / "toolmanifest.vdf"
    if not tm.exists():
        return None
    try:
        manifest = vdf.get_ci(vdf.load(tm), "manifest", {})
    except (OSError, vdf.VDFError):
        return None
    return vdf.get_ci(manifest, "require_tool_appid")


def find_protons(extra_dirs: Sequence[str | Path] = ()) -> list[ProtonBuild]:
    found: dict[Path, ProtonBuild] = {}
    search: list[Path] = []
    for root in steam_roots():
        for lib in library_dirs(root):
            search.append(lib / "steamapps" / "common")
        search.append(root / "compatibilitytools.d")
    search += [Path("/usr/share/steam/compatibilitytools.d"),
               Path.home() / ".local" / "share" / "umu" / "compatibilitytools",
               Path.home() / ".local" / "share" / "Steam" / "compatibilitytools.d"]
    search += [Path(d).expanduser() for d in extra_dirs]
    for base in search:
        if not base.is_dir():
            continue
        candidates = [base] if (base / "proton").is_file() else sorted(base.iterdir())
        for d in candidates:
            if not (d / "proton").is_file():
                continue
            real = d.resolve()
            if real in found:
                continue
            kind, ver = _classify(d.name)
            found[real] = ProtonBuild(d.name, d, kind, ver, _read_manifest(d))
    return list(found.values())


def select_proton(preference: str = "auto", extra_dirs: Sequence[str | Path] = ()) -> ProtonBuild:
    """Pick a Proton build. `preference` is "auto", a directory, or a name
    (case-insensitive substring match, e.g. "GE-Proton9-20" or "experimental")."""
    pref = (preference or "auto").strip()
    if pref not in ("auto", "") and Path(pref).expanduser().joinpath("proton").is_file():
        p = Path(pref).expanduser()
        kind, ver = _classify(p.name)
        return ProtonBuild(p.name, p, kind, ver, _read_manifest(p))
    builds = find_protons(extra_dirs)
    if not builds:
        raise ProtonError(
            "No Proton installation found. Install one from Steam (Library -> Tools -> "
            "'Proton 9.0' or 'Proton Experimental'), or put GE-Proton in "
            "~/.steam/root/compatibilitytools.d/, or set proton.version to a Proton folder in ~/.config/vistal/config.toml.")
    if pref not in ("auto", ""):
        low = pref.lower()
        exact = [b for b in builds if b.name.lower() == low]
        if exact:
            return exact[0]
        partial = [b for b in builds if low in b.name.lower()]
        if partial:
            return sorted(partial, key=lambda b: b.version, reverse=True)[0]
        LOG.warning("Proton '%s' not found, falling back to automatic choice", pref)
    rank = {"valve": 3, "experimental": 2, "ge": 1, "other": 0}
    return sorted(builds, key=lambda b: (rank[b.kind], b.version), reverse=True)[0]


def find_runtime(appid: str | None) -> Path | None:
    if not appid:
        return None
    for root in steam_roots():
        for lib in library_dirs(root):
            common = lib / "steamapps" / "common"
            names = []
            acf = lib / "steamapps" / f"appmanifest_{appid}.acf"
            if acf.exists():
                try:
                    st = vdf.get_ci(vdf.load(acf), "AppState", {})
                    if vdf.get_ci(st, "installdir"):
                        names.append(vdf.get_ci(st, "installdir"))
                except (OSError, vdf.VDFError):
                    pass
            if appid in RUNTIME_DIRS:
                names.append(RUNTIME_DIRS[appid])
            for n in names:
                ep = common / n / "_v2-entry-point"
                if ep.exists():
                    return ep
    return None


def find_umu() -> str | None:
    return shutil.which("umu-run") or (
        str(p) if (p := Path.home() / ".local" / "bin" / "umu-run").exists() else None)


def _steam_client_dir() -> Path:
    roots = steam_roots()
    if roots:
        return roots[0]
    # Proton insists on this variable; an empty stand-in is enough outside Steam.
    return paths.ensure(paths.cache_root() / "steam-stub")


def proton_env_from_settings(settings: dict[str, Any]) -> dict[str, str]:
    """Translate the [proton] table of a game profile into environment variables."""
    env: dict[str, str] = {}
    renderer = str(settings.get("renderer", "auto")).lower()
    if renderer == "wined3d":
        env["PROTON_USE_WINED3D"] = "1"
    if settings.get("dxvk_d3d8", False):
        env["PROTON_DXVK_D3D8"] = "1"
    if settings.get("esync") is False:
        env["PROTON_NO_ESYNC"] = "1"
    if settings.get("fsync") is False:
        env["PROTON_NO_FSYNC"] = "1"
    for key, var in (("large_address_aware", "PROTON_FORCE_LARGE_ADDRESS_AWARE"),
                     ("heap_delay_free", "PROTON_HEAP_DELAY_FREE"),
                     ("heap_zero_memory", "PROTON_HEAP_ZERO_MEMORY"),
                     ("old_gl_string", "PROTON_OLD_GL_STRING"),
                     ("no_d3d11", "PROTON_NO_D3D11"),
                     ("no_d3d10", "PROTON_NO_D3D10")):
        if settings.get(key):
            env[var] = "1"
    cores = int(settings.get("cpu_cores", 0) or 0)
    if cores > 0:
        env["WINE_CPU_TOPOLOGY"] = f"{cores}:" + ",".join(str(i) for i in range(cores))
    fps = int(settings.get("fps_limit", 0) or 0)
    if fps > 0:
        env["DXVK_FRAME_RATE"] = str(fps)
    overrides = settings.get("dll_overrides") or {}
    if overrides:
        env["WINEDLLOVERRIDES"] = ";".join(f"{k}={v}" for k, v in overrides.items())
    for k, v in (settings.get("env") or {}).items():
        env[str(k)] = str(v)
    return env


@dataclass
class Runner:
    proton: ProtonBuild
    compat_dir: Path
    settings: dict[str, Any] = field(default_factory=dict)
    mode: str = "auto"  # auto | umu | runtime | direct
    umu_gameid: str = "umu-default"
    extra_paths: list[Path] = field(default_factory=list)
    log_file: Path | None = None
    wrapper: list[str] = field(default_factory=list)  # e.g. ["gamescope", "-f", "--"]
    _proc: subprocess.Popen | None = field(default=None, repr=False)

    @property
    def prefix(self) -> Path:
        return self.compat_dir / "pfx"

    def resolved_mode(self) -> str:
        if self.mode in ("umu", "runtime", "direct"):
            return self.mode
        if find_umu():
            return "umu"
        if self.proton.runtime_appid and find_runtime(self.proton.runtime_appid):
            return "runtime"
        return "direct"

    def environment(self, extra: dict[str, str] | None = None, base: dict[str, str] | None = None) -> dict[str, str]:
        env = dict(os.environ if base is None else base)
        # Never inherit another tool's prefix.
        for k in ("STEAM_COMPAT_DATA_PATH", "WINEPREFIX", "PROTONPATH", "WINEDLLOVERRIDES"):
            env.pop(k, None)
        env["STEAM_COMPAT_DATA_PATH"] = str(self.compat_dir)
        env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = str(_steam_client_dir())
        env["WINEPREFIX"] = str(self.prefix)
        env["PROTON_VERB"] = "waitforexitandrun"
        # SteamGameId/SteamAppId are deliberately inherited: in Game Mode they
        # identify the frontend's shortcut so gamescope focuses our window.
        mounts = [str(p) for p in self.extra_paths if p]
        if mounts:
            joined = ":".join(dict.fromkeys(mounts))
            env["STEAM_COMPAT_MOUNTS"] = joined
            env["PRESSURE_VESSEL_FILESYSTEMS_RW"] = joined
        if self.settings.get("log"):
            env["PROTON_LOG"] = "1"
            env["PROTON_LOG_DIR"] = str(paths.ensure(paths.logs_dir()))
        env.update(proton_env_from_settings(self.settings))
        if extra:
            # merge DLL overrides instead of clobbering them
            if "WINEDLLOVERRIDES" in extra and "WINEDLLOVERRIDES" in env:
                extra = dict(extra)
                extra["WINEDLLOVERRIDES"] = env["WINEDLLOVERRIDES"] + ";" + extra["WINEDLLOVERRIDES"]
            env.update(extra)
        return env

    def command(self, program: str, args: Sequence[str] = ()) -> tuple[list[str], dict[str, str]]:
        """Build argv and environment additions for running `program`."""
        mode = self.resolved_mode()
        if mode == "umu":
            umu = find_umu()
            if not umu:
                raise ProtonError("umu-run requested but not installed")
            # umu uses WINEPREFIX as STEAM_COMPAT_DATA_PATH and links pfx -> .
            # (or keeps an existing pfx/ dir), so compat_dir/pfx stays valid.
            return [umu, program, *args], {"PROTONPATH": str(self.proton.path),
                                            "WINEPREFIX": str(self.compat_dir),
                                            "GAMEID": self.umu_gameid, "STORE": "none"}
        cmd = [str(self.proton.script), "waitforexitandrun", program, *args]
        if mode == "runtime":
            ep = find_runtime(self.proton.runtime_appid)
            if ep:
                return [str(ep), "--verb=waitforexitandrun", "--", *cmd], {}
            LOG.warning("Steam Linux Runtime not found; running Proton directly")
        return cmd, {}

    def popen(self, program: str, args: Sequence[str] = (), cwd: Path | None = None,
              env_extra: dict[str, str] | None = None) -> subprocess.Popen:
        self.compat_dir.mkdir(parents=True, exist_ok=True)
        argv, add = self.command(program, args)
        argv = [*self.wrapper, *argv]
        env = self.environment({**add, **(env_extra or {})})
        LOG.debug("exec: %s (cwd=%s)", " ".join(argv), cwd)
        out = None
        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            out = open(self.log_file, "ab")
        try:
            self._proc = subprocess.Popen(argv, cwd=str(cwd) if cwd else None, env=env,
                                          stdout=out, stderr=subprocess.STDOUT if out else None,
                                          start_new_session=True)
        finally:
            if out:
                out.close()
        return self._proc

    def run(self, program: str, args: Sequence[str] = (), cwd: Path | None = None,
            env_extra: dict[str, str] | None = None) -> int:
        proc = self.popen(program, args, cwd, env_extra)
        try:
            return proc.wait()
        except KeyboardInterrupt:
            self.kill()
            raise

    def kill(self) -> None:
        """Terminate everything running in this prefix."""
        ws = self.proton.wineserver
        if ws and self.prefix.exists():
            env = dict(os.environ, WINEPREFIX=str(self.prefix))
            try:
                subprocess.run([str(ws), "-k"], env=env, timeout=10,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (OSError, subprocess.TimeoutExpired):
                pass
        if self._proc and self._proc.poll() is None:
            try:
                os.killpg(self._proc.pid, signal.SIGTERM)
                self._proc.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired, PermissionError):
                try:
                    os.killpg(self._proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass


def to_windows_path(path: Path | str, prefix: Path | None = None) -> str:
    """Convert a Unix path to the Windows path Wine will see."""
    p = Path(path)
    if prefix is not None:
        dc = prefix / "drive_c"
        try:
            rel = p.relative_to(dc)
            return "C:\\" + str(rel).replace("/", "\\") if str(rel) != "." else "C:\\"
        except ValueError:
            pass
    return "Z:" + str(p.absolute()).replace("/", "\\")


def to_unix_path(winpath: str, prefix: Path) -> Path:
    """Resolve a Windows path inside `prefix` (C: and other mapped drives)."""
    m = re.match(r"^([A-Za-z]):[\\/]?(.*)$", winpath)
    if not m:
        return Path(winpath)
    letter, rest = m.group(1).lower(), m.group(2).replace("\\", "/")
    if letter == "c":
        base = prefix / "drive_c"
    else:
        base = prefix / "dosdevices" / f"{letter}:"
        if letter == "z" and not base.exists():
            base = Path("/")
    return base / rest if rest else base

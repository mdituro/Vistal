"""Install-and-play orchestration. This is what `vistal launch <rom>` runs."""

from __future__ import annotations

import os
import re
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import detect, discimage, media, paths, profiles, tomlutil, ui
from .controller.engine import Hotkey
from .library import GameDir, Manifest, now
from .log import LOG, attach_file
from .media import GameSource, MediaError, PreparedDisc
from .prefix import Prefix, cd_letters
from .proton import ProtonError, Runner, select_proton, to_unix_path, to_windows_path


class LaunchError(Exception):
    pass


class Session:
    """Everything needed to install or run one game."""

    def __init__(self, source: GameSource, profile_override: str | None = None):
        self.source = source
        self.ui = ui.get()
        self.game = GameDir(source.id)
        self.manifest = self.game.load() or Manifest(id=source.id, title=source.title,
                                                     rom=str(source.rom),
                                                     discs=[str(d) for d in source.discs])
        self.label = self._first_label()
        self.profile_id = self._pick_profile(profile_override)
        self.settings = profiles.effective(self.profile_id, source.id)
        spec_overrides = {k: v for k, v in source.spec.items() if isinstance(v, dict)}
        if spec_overrides:
            self.settings = tomlutil.deep_merge(self.settings, spec_overrides)
        self.profile = profiles.get(self.profile_id)
        attach_file(paths.logs_dir() / f"{source.id}.log")
        LOG.debug("game %s, profile %s, settings %s", source.id, self.profile_id, self.settings)
        self.discs: list[PreparedDisc] = []
        self.current_disc = 0
        self.letters = cd_letters(self.settings["disc"].get("letter", "d"), max(1, len(source.discs)))
        self.prefix = Prefix(self.game.compat)
        self._runner: Runner | None = None

    # -- setup ------------------------------------------------------------

    def _first_label(self) -> str:
        if not self.source.discs:
            return ""
        first = self.source.discs[0]
        try:
            if first.is_dir():
                return media._label_for_dir(first)[0]
            if first.suffix.lower() == ".chd":
                return ""
            with discimage.Disc(str(first)) as d:
                return d.label
        except (discimage.ImageError, OSError) as exc:
            LOG.debug("cannot read label of %s: %s", first, exc)
            return ""

    def _pick_profile(self, override: str | None) -> str | None:
        if override:
            return override
        if self.source.spec.get("profile"):
            return str(self.source.spec["profile"])
        if self.manifest.profile:
            return self.manifest.profile
        m = profiles.match(self.source.title, self.source.rom.stem, self.label)
        if m:
            LOG.info("Recognised %s (%s)", profiles.get(m.profile_id).get("title", m.profile_id),
                     ", ".join(m.reasons))
            return m.profile_id
        return None

    @property
    def runner(self) -> Runner:
        if self._runner is None:
            p = self.settings["proton"]
            try:
                build = select_proton(p.get("version", "auto"), p.get("extra_dirs", []))
            except ProtonError as exc:
                raise LaunchError(str(exc)) from exc
            LOG.info("Using %s", build)
            proton_log = paths.logs_dir() / f"{self.source.id}-proton.log"
            if proton_log.exists():  # keep the previous session's log as .1
                os.replace(proton_log, proton_log.with_name(proton_log.name + ".1"))
            extra = [self.game.root, paths.extract_cache(), paths.mounts_dir()]
            extra += [d.parent for d in self.source.discs]
            if self.source.rom:
                extra.append(self.source.rom.parent)
            self._runner = Runner(
                proton=build,
                compat_dir=self.game.compat,
                settings=p,
                mode=p.get("launcher", "auto"),
                umu_gameid=p.get("umu_gameid", "umu-default"),
                extra_paths=extra,
                log_file=proton_log,
            )
            self.manifest.proton = build.name
        return self._runner

    # -- discs ------------------------------------------------------------

    def prepare_discs(self) -> None:
        if self.discs or not self.source.discs:
            return
        method = self.settings["disc"].get("method", "auto")
        total = len(self.source.discs)
        with self.ui.progress("Vistal", f"Preparing {self.source.title}...") as prog:
            for i, d in enumerate(self.source.discs):
                class _Scaled(ui.Progress):
                    def update(self_inner, fraction: float, text: str = "") -> bool:
                        return prog.update((i + fraction) / total, text)
                try:
                    disc = media.prepare_disc(d, method, _Scaled())
                except MediaError as exc:
                    self.release_discs()
                    raise LaunchError(str(exc)) from exc
                media.build_drive_root(disc, self.game.disc_root(i))
                self.discs.append(disc)
                LOG.info("Disc %d: %s [%s] via %s", i + 1, d.name, disc.label, disc.method)

    def map_drives(self) -> None:
        mapping = {}
        for i, letter in enumerate(self.letters[: len(self.discs)]):
            idx = self.current_disc if i == 0 else i
            mapping[letter] = self.game.disc_root(idx)
        self.prefix.map_drives(mapping, self.game.drives)
        first = self.discs[self.current_disc] if self.discs else None
        if first is not None and self.letters:
            self.prefix.set_device(self.letters[0], first.device)

    def swap_disc(self, delta: int) -> None:
        if len(self.discs) < 2:
            return
        self.current_disc = (self.current_disc + delta) % len(self.discs)
        self.map_drives()
        LOG.info("Drive %s: now holds disc %d", self.letters[0].upper(), self.current_disc + 1)

    def release_discs(self) -> None:
        for d in self.discs:
            d.release()
        self.discs.clear()

    # -- controller --------------------------------------------------------

    @contextmanager
    def controller(self, installing: bool = False) -> Iterator[None]:
        c = self.settings["controller"]
        mode = str(c.get("mode", "auto")).lower()
        if os.environ.get("VISTAL_NO_MAPPER") or mode == "off":
            yield
            return
        layout_name = self.settings["install"].get("controller_layout", "desktop") if installing \
            else c.get("layout", "desktop")
        if installing or mode in ("auto", "mapped"):
            from .controller.layout import LayoutError, load
            try:
                layout = load(layout_name)
            except LayoutError as exc:
                LOG.warning("%s", exc)
                layout = None
        else:  # native: the game reads the pad; only watch hotkeys
            layout = None
        hold = float(c.get("combo_hold", 1.0))
        hotkeys = []
        try:
            if c.get("exit_combo"):
                hotkeys.append(Hotkey.make(c["exit_combo"], float(c.get("exit_hold", 1.5)), "exit"))
            if len(self.source.discs) > 1:
                if c.get("disc_next_combo"):
                    hotkeys.append(Hotkey.make(c["disc_next_combo"], hold, "disc_next"))
                if c.get("disc_prev_combo"):
                    hotkeys.append(Hotkey.make(c["disc_prev_combo"], hold, "disc_prev"))
        except ValueError as exc:
            LOG.warning("ignoring bad hotkey setting: %s", exc)

        def special(name: str) -> None:
            if name == "exit":
                LOG.info("Exit hotkey pressed; closing the game")
                self.runner.kill()
            elif name == "disc_next":
                self.swap_disc(1)
            elif name == "disc_prev":
                self.swap_disc(-1)

        from .controller.mapper import Mapper
        mapper = Mapper(layout, hotkeys, special, grab=bool(c.get("grab", True)),
                        device_filter=c.get("device") or None,
                        face_layout=c.get("face_layout", "auto"))
        started = False
        try:
            started = mapper.start()
        except Exception as exc:  # controller trouble must never block a game
            LOG.warning("controller mapper unavailable: %s", exc)
        try:
            yield
        finally:
            if started:
                mapper.stop()

    # -- install ----------------------------------------------------------

    def is_installed(self) -> bool:
        if not self.manifest.exe:
            return False
        return self.exe_path() is not None

    def exe_path(self) -> Path | None:
        if not self.manifest.exe:
            return None
        p = to_unix_path(self.manifest.exe, self.prefix.pfx)
        if p.exists():
            return p
        fixed = detect._case_fix(p)
        return fixed

    def _installer(self) -> tuple[str, list[str], Path]:
        """Return (program as Windows path, args, cwd) for the installer."""
        spec_inst = self.source.spec.get("installer")
        if spec_inst:
            p = Path(spec_inst).expanduser()
            if not p.is_absolute():
                p = self.source.rom.parent / p
            if not p.exists():
                raise LaunchError(f"Installer not found: {p}")
            return to_windows_path(p), [], p.parent
        if not self.discs:
            raise LaunchError("Nothing to install from")
        root = self.game.disc_root(self.current_disc)
        found = media.find_installer(self.discs[self.current_disc].content)
        if not found:
            raise LaunchError(f"No installer (setup.exe / autorun.inf) found on {self.source.discs[0].name}")
        exe, args = found
        rel = os.path.relpath(exe, self.discs[self.current_disc].content).replace("/", "\\")
        win = f"{self.letters[0].upper()}:\\{rel}"
        return win, args, root

    def install(self) -> bool:
        if self.source.kind != "discs" and not self.source.spec.get("installer"):
            raise LaunchError(f"{self.source.rom.name} is not an installation disc")
        self.prepare_discs()
        self.prefix.ensure(self.runner, self.settings)
        self.map_drives()
        program, args, cwd = self._installer()
        args = [*args, *self.settings["install"].get("args", [])]
        before = detect.snapshot(self.prefix.pfx)
        LOG.info("Starting installer %s", program)
        if len(self.discs) > 1:
            LOG.info("Multi-disc set: discs are in drives %s; hold Back + D-pad right to swap drive %s:",
                     ", ".join(l.upper() + ":" for l in self.letters[: len(self.discs)]),
                     self.letters[0].upper())
        with self.controller(installing=True):
            if program.lower().endswith(".msi"):
                rc = self.runner.run("msiexec", ["/i", program, *args], cwd=cwd)
            else:
                rc = self.runner.run(program, args, cwd=cwd)
        LOG.info("Installer finished (exit code %s)", rc)
        return self._finish_install(before)

    def _finish_install(self, before: detect.Snapshot | None) -> bool:
        wanted = list(self.settings["launch"].get("exe") or [])
        if self.source.spec.get("exe"):
            wanted.insert(0, re.split(r"[\\/]", str(self.source.spec["exe"]))[-1])
        cands = detect.candidates(self.prefix.pfx, self.source.title, wanted, before)
        if not cands:
            self.ui.error("Vistal", "The installer finished but no game executable was found.\n"
                          "If installation was cancelled, launch the game again to retry.")
            return False
        chosen = cands[0]
        ambiguous = chosen.score < 90 and len(cands) > 1 and cands[1].score > chosen.score - 15
        if ambiguous:
            shown = cands[:10]
            labels = [f"{c.path.name}  —  {self._rel(c.path)}  ({c.why})" for c in shown]
            idx = self.ui.choose("Vistal", f"Which program starts {self.source.title}?", labels, 0)
            if idx is None:
                return False
            chosen = shown[idx]
        self.manifest.exe = to_windows_path(chosen.path, self.prefix.pfx)
        self.manifest.profile = self.profile_id or ""
        self.manifest.installed_at = now()
        self.manifest.discs = [str(d) for d in self.source.discs]
        self.manifest.rom = str(self.source.rom)
        self.game.save(self.manifest)
        LOG.info("Installed. Game executable: %s", self.manifest.exe)
        return True

    def _rel(self, p: Path) -> str:
        try:
            return str(p.relative_to(self.prefix.drive_c))
        except ValueError:
            return str(p)

    def set_exe(self, path: str) -> None:
        p = Path(path).expanduser()
        if p.exists():
            self.manifest.exe = to_windows_path(p.resolve(), self.prefix.pfx)
        else:
            unix = to_unix_path(path, self.prefix.pfx)
            fixed = unix if unix.exists() else detect._case_fix(unix)
            if not fixed:
                raise LaunchError(f"Executable not found: {path}")
            self.manifest.exe = to_windows_path(fixed, self.prefix.pfx)
        if not self.manifest.installed_at:
            self.manifest.installed_at = now()
        self.game.save(self.manifest)

    # -- portable games ------------------------------------------------------

    def _portable_exe(self) -> Path | None:
        if self.source.exe:
            return self.source.exe
        if self.source.kind != "portable":
            return None
        names = list(self.settings["launch"].get("exe") or [])
        if names:
            hit = detect.find_by_name(self.source.rom, names)
            if hit:
                return hit
        exes = [p for p in self.source.rom.rglob("*") if p.suffix.lower() == ".exe"
                and not detect.HARD_EXCLUDE.search(p.name)]
        if not exes:
            return None
        exes.sort(key=lambda p: (detect._similarity(self.source.title, p.stem, p.parent.name),
                                 p.stat().st_size), reverse=True)
        if len(exes) == 1:
            return exes[0]
        idx = self.ui.choose("Vistal", f"Which program starts {self.source.title}?",
                             [str(p.relative_to(self.source.rom)) for p in exes[:15]], 0)
        return exes[idx] if idx is not None else None

    # -- play -------------------------------------------------------------

    def _copy_extras(self, exe: Path) -> None:
        for item in self.settings["prefix"].get("copy_to_game_dir") or []:
            src = Path(str(item)).expanduser()
            if not src.exists():
                LOG.warning("copy_to_game_dir: %s does not exist", src)
                continue
            dst = exe.parent / src.name
            if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
                shutil.copy2(src, dst)
                LOG.info("Copied %s next to the game", src.name)

    def _wrapper(self) -> list[str]:
        d = self.settings.get("display") or {}
        if not d.get("gamescope"):
            return []
        if os.environ.get("XDG_CURRENT_DESKTOP", "").lower() == "gamescope" or os.environ.get("GAMESCOPE_WAYLAND_DISPLAY"):
            return []  # already inside gamescope (Steam Game Mode)
        gs = shutil.which("gamescope")
        if not gs:
            LOG.warning("display.gamescope is set but gamescope is not installed")
            return []
        return [gs, *[str(a) for a in d.get("gamescope_args", [])], "--"]

    def play(self) -> int:
        exe = self.exe_path()
        if exe is None:
            exe = self._portable_exe()
            if exe is None:
                raise LaunchError("No game executable configured. Run 'vistal set-exe' or reinstall.")
            self.manifest.exe = to_windows_path(exe, self.prefix.pfx)
            self.game.save(self.manifest)
        if self.source.discs and self.settings["disc"].get("mount_while_playing", True):
            self.prepare_discs()
        self.prefix.ensure(self.runner, self.settings)
        if self.discs:
            self.map_drives()
        self._copy_extras(exe)
        program = self.manifest.exe
        args = [*self.manifest.args, *[str(a) for a in self.settings["launch"].get("args", [])]]
        vd = self.settings["prefix"].get("virtual_desktop") or ""
        if vd:
            args = [f"/desktop=Vistal,{vd}", program, *args]
            program = "explorer.exe"
        workdir = self.settings["launch"].get("workdir") or ""
        cwd = to_unix_path(workdir, self.prefix.pfx) if workdir else exe.parent
        self.manifest.last_played = now()
        self.manifest.profile = self.profile_id or ""
        self.game.save(self.manifest)
        LOG.info("Starting %s", self.manifest.exe)
        self.runner.wrapper = self._wrapper()
        try:
            with self.controller():
                rc = self.runner.run(program, args, cwd=cwd)
        finally:
            self.runner.wrapper = []
        LOG.info("Game exited with code %s", rc)
        return rc

    def run_program(self, program: str, args: list[str]) -> int:
        """Run an arbitrary Windows program (patch, config tool) in this game's prefix."""
        if self.source.discs:
            self.prepare_discs()
        self.prefix.ensure(self.runner, self.settings)
        if self.discs:
            self.map_drives()
        p = Path(program).expanduser()
        if p.exists():
            program, cwd = to_windows_path(p.resolve()), p.resolve().parent
        else:
            cwd = self.game.compat
        with self.controller(installing=True):
            return self.runner.run(program, args, cwd=cwd)

    # -- top level ----------------------------------------------------------

    def launch(self, reinstall: bool = False) -> int:
        lock = self.game.lock()
        if lock is None:
            raise LaunchError(f"{self.source.title} is already running")
        try:
            spec_exe = self.source.spec.get("exe")
            if spec_exe and not reinstall:
                # An explicit exe in a .vistal file always wins.
                self.manifest.exe = (to_windows_path(self.source.exe, self.prefix.pfx)
                                     if self.source.exe is not None else str(spec_exe).replace("/", "\\"))
            if self.source.kind == "discs" or self.source.spec.get("installer"):
                if reinstall or not self.is_installed():
                    if not self.is_installed() and not reinstall:
                        LOG.info("%s is not installed yet; starting the installer", self.source.title)
                    if not self.install():
                        return 1
                    if not self.settings["install"].get("launch_after_install", True):
                        return 0
            elif self.source.kind == "portable" and not spec_exe and reinstall:
                self.manifest.exe = ""
            return self.play()
        finally:
            self.release_discs()
            lock.close()

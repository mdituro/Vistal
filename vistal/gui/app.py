"""The game library window: state, input handling and game launching."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from .. import paths, profiles, tomlutil
from ..log import LOG
from . import model
from .cairo import Context, Surface
from .images import Cache
from .theme import VIEW_LABELS, VIEW_ORDER, Geometry, Menu, MenuItem, Message
from .theme_aqua import AquaTheme
from .theme_vista import VistaTheme

THEMES = {"vista": VistaTheme, "aqua": AquaTheme}
CATEGORIES = ["all", "installed", "not-installed", "recent"]
CATEGORY_LABELS = {"all": "All Games", "installed": "Installed", "not-installed": "Not Installed",
                   "recent": "Recently Played"}
STATE_KEYS = ("theme", "view", "sort", "artwork")


class Hits:
    def __init__(self):
        self.items: list[tuple[float, float, float, float, tuple]] = []

    def clear(self) -> None:
        self.items.clear()

    def add(self, x, y, w, h, action: tuple) -> None:
        self.items.append((x, y, w, h, action))

    def at(self, x: float, y: float) -> tuple | None:
        for hx, hy, hw, hh, action in reversed(self.items):
            if hx <= x < hx + hw and hy <= y < hy + hh:
                return action
        return None


def state_file() -> Path:
    return paths.config_root() / "frontend-state.toml"


def in_game_mode() -> bool:
    return (os.environ.get("XDG_CURRENT_DESKTOP", "").lower() == "gamescope"
            or bool(os.environ.get("GAMESCOPE_WAYLAND_DISPLAY")))


class App:
    def __init__(self, window=None, theme: str | None = None, view: str | None = None):
        self.window = window
        self.settings = profiles.effective(None, None)
        fe = dict(self.settings.get("frontend") or {})
        fe.update({k: v for k, v in tomlutil.load_if_exists(state_file()).items() if k in STATE_KEYS})
        self.theme_name = theme or fe.get("theme", "vista")
        if self.theme_name not in THEMES:
            self.theme_name = "vista"
        self.view = view or fe.get("view", "large")
        if self.view not in VIEW_ORDER:
            self.view = "large"
        self.sort = fe.get("sort", "name")
        self.artwork = fe.get("artwork", "auto")
        self._themes: dict[str, object] = {}
        self.entries: list[model.Entry] = []
        self.visible: list[model.Entry] = []
        self.sel = 0
        self.scroll = 0.0
        self.hover: int | None = None
        self.hover_hit: tuple | None = None
        self.search = ""
        self.search_focus = False
        self.category = "all"
        self.menu: Menu | None = None
        self.message: Message | None = None
        self.focus = "items"
        self.images = Cache()
        self.hits = Hits()
        self.grid = Geometry()
        self.scale = 1.0
        self.size = (1280.0, 800.0)
        self.busy = ""
        self.caret_on = True
        self.dirty = True
        self.running = True
        self.fullscreen = False
        self._held: dict[str, float] = {}
        self._axes = {"lx": 0.0, "ly": 0.0}
        self._drag: tuple[float, float, float] | None = None
        self._loader: model.ArtLoader | None = None

    # -- data ---------------------------------------------------------------------

    @property
    def theme(self):
        if self.theme_name not in self._themes:
            self._themes[self.theme_name] = THEMES[self.theme_name]()
        return self._themes[self.theme_name]

    @property
    def selected(self) -> model.Entry | None:
        return self.visible[self.sel] if 0 <= self.sel < len(self.visible) else None

    def counts(self) -> dict[str, int]:
        return {c: len(model.filter_entries(self.entries, "", c)) for c in CATEGORIES}

    def empty_help(self) -> list[str]:
        dirs = model.rom_dirs(self.settings)
        where = str(dirs[0]) if dirs else "your ROMs/gfw folder (run: vistal frontend esde)"
        return [f"Put disc images (.iso, .cue, .m3u ...) in {where}",
                "or set frontend.rom_dirs in ~/.config/vistal/config.toml."]

    def reload(self, sync_art: bool = False) -> None:
        # keep resolved artwork unless the install state changed (new exe icon)
        old = {e.id: (e.installed, e.art) for e in self.entries}
        self.entries = model.scan(self.settings)
        for e in self.entries:
            if e.id in old and old[e.id][0] == e.installed:
                e.art = old[e.id][1]
        self.refilter()
        if sync_art:
            from .. import art
            for e in self.entries:
                e.art = art.resolve(e.id, e.exe, e.rom, e.discs)
        else:
            if self._loader is None:
                self._loader = model.ArtLoader(self._art_ready)
            self._loader.request(self.visible + [e for e in self.entries if e not in self.visible])

    def _art_ready(self) -> None:
        self.dirty = True

    def refilter(self) -> None:
        current = self.selected.id if self.selected else None
        self.visible = model.sort_entries(model.filter_entries(self.entries, self.search, self.category), self.sort)
        ids = [e.id for e in self.visible]
        self.sel = ids.index(current) if current in ids else (0 if self.visible else -1)
        self.dirty = True

    def save_state(self) -> None:
        try:
            tomlutil.save(state_file(), {"theme": self.theme_name, "view": self.view, "sort": self.sort,
                                         "artwork": self.artwork},
                          header="# Remembered by 'vistal gui'. Defaults live in config.toml [frontend].")
        except OSError as exc:
            LOG.debug("cannot save frontend state: %s", exc)

    # -- geometry -----------------------------------------------------------------

    def clamp_scroll(self) -> None:
        g = self.grid
        self.scroll = max(0.0, min(self.scroll, max(0.0, g.content_h - g.h)))

    def ensure_visible(self) -> None:
        g = self.grid
        if self.sel < 0 or g.h <= 0:
            return
        row = self.sel // max(1, g.cols)
        top = g.pad + row * g.row_h
        if top - g.pad < self.scroll:
            self.scroll = max(0.0, top - g.pad)
        elif top + g.row_h > self.scroll + g.h:
            self.scroll = top + g.row_h - g.h + g.pad
        self.clamp_scroll()

    # -- rendering ------------------------------------------------------------------

    def render(self, px_w: int, px_h: int, surface: Surface | None = None) -> Surface:
        surface = surface or Surface.create(px_w, px_h)
        self.scale = max(0.6, min(px_w / 1280.0, px_h / 800.0))
        self.size = (px_w / self.scale, px_h / self.scale)
        ctx = Context(surface)
        ctx.scale(self.scale, self.scale)
        self.hits.clear()
        self.theme.draw(ctx, self, *self.size)
        ctx.destroy()
        self.dirty = False
        return surface

    # -- navigation & actions ---------------------------------------------------------

    def move(self, dx: int, dy: int) -> None:
        if self.menu:
            self.menu.move(dy or dx)
            self.dirty = True
            return
        if self.message:
            n = len(self.message.buttons)
            self.message.sel = (self.message.sel + (dx or dy)) % n
            self.dirty = True
            return
        if not self.visible:
            return
        cols = 1 if self.view == "details" else max(1, self.grid.cols)
        idx = self.sel + dx + dy * cols
        if dy and not 0 <= idx < len(self.visible):
            idx = max(0, min(len(self.visible) - 1, idx))
        self.sel = max(0, min(len(self.visible) - 1, idx))
        self.focus = "items"
        self.ensure_visible()
        self.dirty = True

    def page(self, direction: int) -> None:
        rows = max(1, int(self.grid.h // max(1, self.grid.row_h)))
        self.move(0, direction * rows)

    def activate(self) -> None:
        if self.message:
            self.run_action(self.message.actions[self.message.sel])
            return
        if self.menu:
            item = self.menu.items[self.menu.sel]
            if item.enabled and not item.separator:
                self.menu = None
                self.run_action(item.action)
            return
        if self.selected:
            self.run_action(("play",))

    def cancel(self) -> None:
        if self.message:
            self.message = None
        elif self.menu:
            self.menu = None
        elif self.search_focus:
            self.set_search_focus(False)
        elif self.search or self.category != "all":
            self.search, self.category = "", "all"
            self.refilter()
        else:
            self.ask_quit()
        self.dirty = True

    def ask_quit(self) -> None:
        self.message = Message("Vistal", "Close the game library?", ["Close", "Cancel"],
                               [("quit",), ("close-message",)], kind="question")

    def set_search_focus(self, on: bool) -> None:
        self.search_focus = on
        self.focus = "search" if on else "items"
        if self.window:
            self.window.text_input(on)
        self.dirty = True

    def cycle(self, attr: str, options: list[str], step: int = 1) -> None:
        cur = getattr(self, attr)
        i = options.index(cur) if cur in options else 0
        setattr(self, attr, options[(i + step) % len(options)])

    def game_menu_items(self, e: model.Entry | None, with_close: bool = False) -> list[MenuItem]:
        items = []
        if e is not None:
            items.append(MenuItem("Play" if e.installed else "Install and play", ("play",)))
            items.append(MenuItem("Reinstall from disc", ("reinstall",), enabled=bool(e.discs)))
            items.append(MenuItem("Wine configuration", ("winecfg",), enabled=e.rom is not None or e.installed))
            items.append(MenuItem("", separator=True))
        items.append(MenuItem("Refresh library", ("rescan",)))
        if with_close:
            items += [MenuItem("", separator=True), MenuItem("Close", ("ask-quit",))]
        return items

    def menu_items(self, kind: str) -> list[MenuItem]:
        if kind in ("organize", "game"):
            return self.game_menu_items(self.selected, with_close=kind == "organize")
        if kind == "views":
            items = [MenuItem(VIEW_LABELS[v], ("view", v), checked=self.view == v) for v in VIEW_ORDER]
            items += [MenuItem("", separator=True),
                      MenuItem("Sort by Name", ("sort", "name"), checked=self.sort == "name"),
                      MenuItem("Sort by Last Played", ("sort", "last-played"), checked=self.sort == "last-played"),
                      MenuItem("", separator=True),
                      MenuItem("Artwork: Automatic", ("artwork", "auto"), checked=self.artwork == "auto"),
                      MenuItem("Artwork: Program Icons", ("artwork", "icons"), checked=self.artwork == "icons"),
                      MenuItem("Artwork: Box Art", ("artwork", "covers"), checked=self.artwork == "covers")]
            return items
        if kind == "options":
            items = [MenuItem(f"Theme: {cls.label}", ("theme", name), checked=self.theme_name == name)
                     for name, cls in THEMES.items()]
            items += [MenuItem("", separator=True),
                      MenuItem("Full Screen", ("fullscreen",), checked=self.fullscreen, enabled=self.window is not None),
                      MenuItem("", separator=True), MenuItem("Close Vistal", ("ask-quit",))]
            return items
        if kind == "tools":
            e = self.selected
            return [MenuItem("Wine Configuration", ("winecfg",), enabled=e is not None),
                    MenuItem("Reinstall from Disc", ("reinstall",), enabled=bool(e and e.discs)),
                    MenuItem("", separator=True), MenuItem("Refresh Library", ("rescan",))]
        if kind == "category":
            counts = self.counts()
            return [MenuItem(f"{CATEGORY_LABELS[c]} ({counts[c]})", ("category", c), checked=self.category == c)
                    for c in CATEGORIES]
        if kind == "main":
            items = [MenuItem(f"Theme: {cls.label}", ("theme", name), checked=self.theme_name == name)
                     for name, cls in THEMES.items()]
            items.append(MenuItem("", separator=True))
            items += [MenuItem(VIEW_LABELS[v], ("view", v), checked=self.view == v) for v in VIEW_ORDER]
            items += [MenuItem("", separator=True),
                      MenuItem("Sort by Last Played" if self.sort == "name" else "Sort by Name",
                               ("sort", "last-played" if self.sort == "name" else "name")),
                      MenuItem("Refresh Library", ("rescan",)),
                      MenuItem("", separator=True), MenuItem("Close Vistal", ("ask-quit",))]
            return items
        return []

    def open_menu(self, kind: str, x: float, y: float) -> None:
        self.menu = Menu(self.menu_items(kind), x, y, title=kind)
        self.dirty = True

    def tile_anchor(self) -> tuple[float, float]:
        for hx, hy, hw, hh, action in self.hits.items:
            if action == ("tile", self.sel):
                return hx + hw / 2, hy + hh / 2
        return self.size[0] / 2, self.size[1] / 2

    def run_action(self, action: tuple) -> None:
        kind = action[0] if action else ""
        self.dirty = True
        if kind == "play":
            if self.selected:
                self.launch(self.selected, "launch")
        elif kind == "reinstall":
            if self.selected:
                self.launch(self.selected, "reinstall")
        elif kind == "winecfg":
            if self.selected:
                self.launch(self.selected, "winecfg")
        elif kind == "rescan":
            self.reload()
        elif kind == "view":
            self.view = action[1]
            self.scroll = 0
            self.save_state()
        elif kind == "sort":
            self.sort = action[1]
            self.refilter()
            self.save_state()
        elif kind == "artwork":
            self.artwork = action[1]
            self.save_state()
        elif kind == "theme":
            self.theme_name = action[1]
            self.save_state()
        elif kind == "category":
            self.category = action[1]
            self.scroll = 0
            self.refilter()
        elif kind == "fullscreen":
            self.set_fullscreen(not self.fullscreen)
        elif kind == "ask-quit":
            self.ask_quit()
        elif kind == "quit":
            self.message = None
            self.running = False
        elif kind == "close-message":
            self.message = None

    def set_fullscreen(self, on: bool) -> None:
        self.fullscreen = on
        if self.window:
            from .sdl import WINDOW_FULLSCREEN_DESKTOP, lib
            lib().SDL_SetWindowFullscreen(self.window.win, WINDOW_FULLSCREEN_DESKTOP if on else 0)

    # -- launching ----------------------------------------------------------------------

    def launch_command(self, e: model.Entry, mode: str) -> list[str]:
        target = str(e.rom) if e.rom is not None else e.id
        cmd = [sys.executable, "-m", "vistal"]
        if mode == "winecfg":
            return cmd + ["winecfg", target]
        if mode == "reinstall":
            return cmd + ["launch", "--reinstall", target]
        return cmd + ["launch", target]

    def launch(self, e: model.Entry, mode: str) -> int:
        cmd = self.launch_command(e, mode)
        env = dict(os.environ)
        env["PYTHONPATH"] = str(paths.PACKAGE_DIR.parent) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env.setdefault("VISTAL_UI", "auto")
        LOG.info("Starting: %s", " ".join(cmd))
        self.busy = f"Starting {e.display_title}…"
        if self.window:
            self.window.present(self.render(*self.window.size()))
        try:
            proc = subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL)
        except OSError as exc:
            self.busy = ""
            self.error(f"Could not start {e.display_title}", str(exc))
            return 1
        if self.window:
            self.window.show(False)
            while proc.poll() is None:
                self.window.events(200)  # keep the hidden window responsive
            self.window.show(True)
        rc = proc.wait()
        self.busy = ""
        self.reload()
        problems = self._log_errors(e.id)
        if rc != 0 and problems:
            self.error(f"{e.display_title} could not be started", "\n".join(problems))
        return rc

    def _log_errors(self, game_id: str) -> list[str]:
        log = paths.logs_dir() / f"{game_id}.log"
        try:
            lines = log.read_text(errors="replace").splitlines()
        except OSError:
            return []
        return [l.split(" ERROR ", 1)[1] for l in lines if " ERROR " in l][-4:]

    def error(self, title: str, text: str) -> None:
        self.message = Message(title, text, ["OK"], [("close-message",)], kind="error")
        self.dirty = True

    # -- input --------------------------------------------------------------------------

    def to_logical(self, x: float, y: float) -> tuple[float, float]:
        if self.window:
            lw, lh = self.window.logical_size()
            pw, ph = self.window.size()
            x, y = x * pw / max(1, lw), y * ph / max(1, lh)
        return x / self.scale, y / self.scale

    def on_mouse_down(self, x: float, y: float, button: int = 1, clicks: int = 1) -> None:
        x, y = self.to_logical(x, y)
        action = self.hits.at(x, y)
        self.dirty = True
        if action is None:
            return
        kind = action[0]
        if kind == "menuitem":
            item = self.menu.items[action[1]] if self.menu else None
            self.menu = None
            if item and item.enabled:
                self.run_action(item.action)
            return
        if kind == "dismiss":
            self.menu = None
            return
        if kind == "modal":
            return
        if kind == "msgbutton":
            self.run_action(self.message.actions[action[1]])
            return
        if self.search_focus and kind != "search":
            self.set_search_focus(False)
        if kind == "tile":
            self.sel = action[1]
            self.focus = "items"
            self._drag = (y, self.scroll, 0.0)
            if button == 3:
                self.open_menu("game", x, y)
            elif clicks >= 2:
                self.run_action(("play",))
        elif kind == "toolbar":
            key = action[1]
            if key == "play":
                self.run_action(("play",))
            elif self.menu and self.menu.title == key:
                self.menu = None
            else:
                self.open_menu(key, action[2], action[3])
        elif kind == "menu":
            self.open_menu(action[1], action[2], action[3])
        elif kind == "scrollbar":
            self._scroll_to(y, action[1], action[2])
            self._drag = ("bar", action[1], action[2])
        elif kind == "search":
            self.set_search_focus(True)
        elif kind == "caption":
            if action[1] == "close":
                self.running = False
            elif action[1] == "max":
                self.set_fullscreen(not self.fullscreen)
        elif kind == "back":
            self.search, self.category = "", "all"
            self.refilter()
        elif kind in ("sort", "category", "view", "theme", "rescan", "play", "ask-quit", "artwork"):
            self.run_action(action)

    def _scroll_to(self, y: float, top: float, height: float) -> None:
        frac = (y - top) / max(1.0, height)
        self.scroll = frac * self.grid.content_h - self.grid.h / 2
        self.clamp_scroll()

    def on_mouse_up(self) -> None:
        self._drag = None

    def on_motion(self, x: float, y: float) -> None:
        x, y = self.to_logical(x, y)
        action = self.hits.at(x, y)
        hover = action[1] if action and action[0] == "tile" else None
        hover_hit = action if action and action[0] in ("toolbar", "caption", "rescan", "category-item", "sidebar") else None
        if self._drag:
            if self._drag[0] == "bar":
                self._scroll_to(y, self._drag[1], self._drag[2])
            else:
                y0, s0, _ = self._drag
                if abs(y - y0) > 8:  # touch-style drag scrolling
                    self.scroll = s0 - (y - y0)
                    self.clamp_scroll()
            self.dirty = True
        if self.menu and action and action[0] == "menuitem" and self.menu.sel != action[1]:
            self.menu.sel = action[1]
            self.dirty = True
        if hover != self.hover or hover_hit != self.hover_hit:
            self.hover, self.hover_hit = hover, hover_hit
            self.dirty = True

    def on_wheel(self, dy: float) -> None:
        if self.menu:
            self.menu.move(-int(dy))
        else:
            self.scroll -= dy * 60
            self.clamp_scroll()
        self.dirty = True

    def on_text(self, text: str) -> None:
        if self.search_focus:
            self.search += text
            self.scroll = 0
            self.refilter()

    def on_key(self, key: str, mod: int = 0) -> None:
        ctrl = bool(mod & 0x00C0)
        if self.search_focus:
            if key == "backspace":
                self.search = self.search[:-1]
                self.refilter()
                return
            if key in ("enter", "down", "tab"):
                self.set_search_focus(False)
                return
            if key == "escape":
                self.search = ""
                self.set_search_focus(False)
                self.refilter()
                return
            return
        if ctrl and key == "f" or key == "/" or key == "f3":
            self.set_search_focus(True)
        elif key in ("left", "right", "up", "down"):
            self.move(*{"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}[key])
        elif key == "pageup":
            self.page(-1)
        elif key == "pagedown":
            self.page(1)
        elif key == "home":
            self.sel, self.scroll = 0, 0
            self.dirty = True
        elif key == "end":
            self.sel = len(self.visible) - 1
            self.ensure_visible()
            self.dirty = True
        elif key in ("enter", "space"):
            self.activate()
        elif key in ("escape", "backspace"):
            self.cancel()
        elif key in ("menu", "f10"):
            self.open_menu("game", *self.tile_anchor())
        elif key == "f5":
            self.reload()
        elif key == "f11":
            self.set_fullscreen(not self.fullscreen)
        elif key == "q" and ctrl:
            self.running = False

    PAD_NAV = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}

    def on_pad_button(self, b: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if b in self.PAD_NAV:
            self.move(*self.PAD_NAV[b])
            self._held[b] = now + 0.38
            return
        if b == "a":
            self.activate()
        elif b == "b":
            self.cancel()
        elif b == "x" and not self.message:
            if self.menu:
                self.menu = None
            else:
                self.open_menu("game", *self.tile_anchor())
        elif b == "y" and not (self.menu or self.message):
            self.cycle("view", VIEW_ORDER)
            self.save_state()
        elif b == "start":
            self.menu = None if self.menu else Menu(self.menu_items("main"), self.size[0] / 2 - 120, 90, title="main")
        elif b == "back":
            self.set_search_focus(not self.search_focus)
        elif b == "lb":
            self.cycle("theme_name", list(THEMES))
            self.save_state()
        elif b == "rb":
            self.cycle("category", CATEGORIES)
            self.scroll = 0
            self.refilter()
        elif b in ("lt", "rt"):
            self.page(-1 if b == "lt" else 1)
        self.dirty = True

    def on_pad_button_up(self, b: str) -> None:
        self._held.pop(b, None)

    def on_pad_axis(self, axis: str, value: float, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if axis in ("lt", "rt"):
            key = f"trig-{axis}"
            if value > 0.6 and key not in self._held:
                self._held[key] = float("inf")
                self.page(-1 if axis == "lt" else 1)
            elif value < 0.3:
                self._held.pop(key, None)
            return
        if axis not in self._axes:
            return
        self._axes[axis] = value
        for direction, (ax, sign) in {"s-up": ("ly", -1), "s-down": ("ly", 1),
                                      "s-left": ("lx", -1), "s-right": ("lx", 1)}.items():
            v = self._axes[ax] * sign
            if v > 0.6 and direction not in self._held:
                self.move(*self.PAD_NAV[direction[2:]])
                self._held[direction] = now + 0.38
            elif v < 0.4:
                self._held.pop(direction, None)

    def tick(self, now: float | None = None) -> None:
        """Auto-repeat for held d-pad/stick directions; caret blink."""
        now = time.monotonic() if now is None else now
        for key, due in list(self._held.items()):
            name = key[2:] if key.startswith("s-") else key
            if name in self.PAD_NAV and now >= due:
                self.move(*self.PAD_NAV[name])
                self._held[key] = now + 0.09
        if self.search_focus:
            blink = int(now * 2) % 2 == 0
            if blink != self.caret_on:
                self.caret_on = blink
                self.dirty = True

    # -- main loop ---------------------------------------------------------------------

    def run(self) -> int:
        from .sdl import Window
        fs_setting = str((self.settings.get("frontend") or {}).get("fullscreen", "auto")).lower()
        fullscreen = in_game_mode() if fs_setting == "auto" else fs_setting in ("true", "1", "yes")
        self.window = Window("Games - Vistal", 1280, 800, fullscreen=fullscreen)
        self.fullscreen = fullscreen
        self.reload()
        surface = None
        try:
            while self.running:
                for ev in self.window.events(33 if (self._held or self.search_focus) else 120):
                    self.handle(ev)
                self.tick()
                if self.dirty:
                    w, h = self.window.size()
                    if surface is None or (surface.width, surface.height) != (w, h):
                        surface = Surface.create(w, h)
                    self.window.present(self.render(w, h, surface))
        except KeyboardInterrupt:
            pass
        finally:
            if self._loader:
                self._loader.stop()
            self.window.close()
        return 0

    def handle(self, ev) -> None:
        k = ev.kind
        if k == "quit":
            self.running = False
        elif k == "window":
            self.dirty = True
        elif k == "keydown":
            self.on_key(ev.key, ev.mod)
        elif k == "text":
            self.on_text(ev.text)
        elif k == "mousedown":
            self.on_mouse_down(ev.x, ev.y, int(ev.button), ev.clicks)
        elif k == "mouseup":
            self.on_mouse_up()
        elif k == "motion":
            self.on_motion(ev.x, ev.y)
        elif k == "wheel":
            self.on_wheel(ev.value)
        elif k == "padbutton":
            self.on_pad_button(str(ev.button))
        elif k == "padbuttonup":
            self.on_pad_button_up(str(ev.button))
        elif k == "padaxis":
            self.on_pad_axis(str(ev.button), ev.value)


def screenshot(path: str, width: int = 1280, height: int = 800, theme: str | None = None,
               view: str | None = None, select: int | None = None, menu: str | None = None,
               message: bool = False) -> None:
    """Render the library without opening a window (docs, tests, bug reports)."""
    app = App(theme=theme, view=view)
    app.reload(sync_art=True)
    if select is not None and app.visible:
        app.sel = max(0, min(select, len(app.visible) - 1))
    app.render(width, height)  # first pass computes layout
    app.ensure_visible()
    if menu:
        app.open_menu(menu, *app.tile_anchor())
    if message:
        app.error("Freelancer could not be started", "No Proton installation found. Install Proton from "
                  "Steam (Library > Tools) and try again.")
    app.render(width, height).write_png(path)

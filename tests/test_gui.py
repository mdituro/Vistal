"""Game library frontend: rendering, input handling and launching."""
import struct
from pathlib import Path

import pytest

from conftest import make_iso, make_tree, needs_geniso, read_log
from vistal import library, paths, tomlutil
from vistal.gui import cairo as C

pytestmark = pytest.mark.skipif(not C.available(), reason="cairo not installed")
FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def roms(isolated_home, tmp_path):
    rom_dir = tmp_path / "roms" / "gfw"
    rom_dir.mkdir(parents=True)
    tomlutil.save(paths.user_config_file(), {"frontend": {"rom_dirs": [str(rom_dir)]}})
    return rom_dir


def _iso(rom_dir, tmp_path, title, with_icon=True):
    files = {"AUTORUN.INF": "[autorun]\nopen=setup.exe\n" + ("icon=setup.exe\n" if with_icon else ""),
             "setup.exe": (FIX / "gdfgame.exe").read_bytes() if with_icon else "MZ"}
    src = make_tree(tmp_path / ("src-" + title), files)
    return make_iso(rom_dir / f"{title}.iso", src)


def _png_size(path):
    data = Path(path).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


@needs_geniso
@pytest.mark.parametrize("theme", ["vista", "aqua"])
@pytest.mark.parametrize("view", ["extra-large", "large", "medium", "details"])
def test_screenshots_all_views(roms, tmp_path, theme, view):
    from vistal.gui.app import screenshot
    for t in ("Freelancer", "Midtown Madness", "Rise of Legends"):
        _iso(roms, tmp_path, t, with_icon=t != "Midtown Madness")
    out = tmp_path / f"{theme}-{view}.png"
    screenshot(str(out), 1280, 800, theme=theme, view=view, select=1, menu="views")
    assert _png_size(out) == (1280, 800)
    big = tmp_path / "big.png"
    screenshot(str(big), 1920, 1080, theme=theme, view=view)  # scales up for TVs
    assert _png_size(big) == (1920, 1080)


def test_empty_library_and_error_dialog(roms, tmp_path):
    from vistal.gui.app import screenshot
    for theme in ("vista", "aqua"):
        out = tmp_path / f"empty-{theme}.png"
        screenshot(str(out), theme=theme)
        screenshot(str(out), theme=theme, message=True)
        assert _png_size(out) == (1280, 800)


@needs_geniso
def test_model_merges_roms_and_installs(roms, tmp_path):
    from vistal.gui import model
    from vistal import profiles
    _iso(roms, tmp_path, "Freelancer")
    _iso(roms, tmp_path, "Unknown Game", with_icon=False)
    (roms / "systeminfo.txt").write_text("x")
    gd = library.GameDir("freelancer")
    exe = gd.compat / "pfx" / "drive_c" / "Games" / "fl.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    gd.save(library.Manifest(id="freelancer", title="Freelancer", exe="C:\\Games\\fl.exe",
                             rom=str(roms / "Freelancer.iso"), last_played="2026-10-01 10:00:00"))
    library.GameDir("gone").save(library.Manifest(id="gone", title="Removed Game", exe="C:\\x.exe"))
    entries = {e.id: e for e in model.scan(profiles.effective(None, None))}
    assert set(entries) == {"freelancer", "unknown-game", "gone"}
    fl = entries["freelancer"]
    assert fl.installed and fl.profile_id == "freelancer" and fl.exe == exe
    assert not entries["unknown-game"].installed and entries["unknown-game"].status == "Ready to install"
    assert not entries["gone"].installed  # exe missing
    ordered = model.sort_entries(list(entries.values()), "last-played")
    assert ordered[0].id == "freelancer"
    assert [e.id for e in model.filter_entries(list(entries.values()), "", "installed")] == ["freelancer"]
    assert [e.id for e in model.filter_entries(list(entries.values()), "unkn")] == ["unknown-game"]


def _app(roms, tmp_path, n=7, theme="vista"):
    from vistal.gui.app import App
    for i in range(n):
        _iso(roms, tmp_path, f"Game {chr(65 + i)}", with_icon=False)
    app = App(theme=theme, view="large")
    app.reload(sync_art=True)
    app.render(1280, 800)
    return app


@needs_geniso
def test_keyboard_and_gamepad_navigation(roms, tmp_path):
    app = _app(roms, tmp_path, n=9)
    cols = app.grid.cols
    assert cols >= 3 and app.sel == 0
    app.on_key("right")
    assert app.sel == 1
    app.on_key("down")
    assert app.sel == 1 + cols
    app.on_key("end")
    assert app.sel == 8
    app.on_key("home")
    app.on_pad_button("y")              # cycle view
    assert app.view == "medium"
    app.on_pad_button("lb")             # cycle theme
    assert app.theme_name == "aqua"
    assert (paths.config_root() / "frontend-state.toml").exists()
    app.on_pad_button("rb")             # category: installed (none)
    assert app.category == "installed" and app.visible == []
    app.on_pad_button("b")              # back clears the filter
    assert app.category == "all" and len(app.visible) == 9
    app.on_pad_button("b")              # nothing to clear: ask to quit
    assert app.message is not None
    app.on_pad_button("right")
    app.on_pad_button("a")              # "Cancel"
    assert app.message is None and app.running
    # stick auto-repeat
    app.view = "details"
    app.render(1280, 800)
    app.sel = 0
    app.on_pad_axis("ly", 0.9, now=100.0)
    assert app.sel == 1
    app.tick(now=100.1)
    assert app.sel == 1                 # still in the initial delay
    app.tick(now=100.5)
    app.tick(now=100.6)
    assert app.sel == 3
    app.on_pad_axis("ly", 0.0, now=100.7)
    app.tick(now=101.0)
    assert app.sel == 3


@needs_geniso
def test_search_menus_and_mouse(roms, tmp_path):
    from vistal.gui.theme import Menu
    app = _app(roms, tmp_path, n=4, theme="aqua")
    app.on_key("/")
    assert app.search_focus
    for ch in "game c":
        app.on_text(ch)
    assert [e.title for e in app.visible] == ["Game C"]
    app.on_key("escape")
    assert not app.search_focus and len(app.visible) == 4
    app.render(1280, 800)
    # click the third tile
    tile = next(h for h in app.hits.items if h[4] == ("tile", 2))
    app.on_mouse_down(tile[0] + 5, tile[1] + 5)
    assert app.sel == 2
    # right-click opens the game menu; clicking outside dismisses it
    app.on_mouse_down(tile[0] + 5, tile[1] + 5, button=3)
    assert isinstance(app.menu, Menu) and app.menu.items[0].label.startswith("Install")
    app.render(1280, 800)
    app.on_mouse_down(1, 799)
    assert app.menu is None
    # view segment in the Aqua toolbar
    app.render(1280, 800)
    seg = next(h for h in app.hits.items if h[4] == ("view", "details"))
    app.on_mouse_down(seg[0] + 2, seg[1] + 2)
    assert app.view == "details"
    # menu chosen with the gamepad
    app.on_pad_button("start")
    labels = [i.label for i in app.menu.items]
    target = labels.index("Theme: Windows Vista")
    while app.menu.sel != target:
        app.on_pad_button("down")
    app.on_pad_button("a")
    assert app.theme_name == "vista" and app.menu is None


@needs_geniso
def test_double_click_launches_through_vistal(roms, tmp_path, fake_proton):
    src = make_tree(tmp_path / "src", {"AUTORUN.INF": "[autorun]\nopen=Setup.exe\n", "Setup.exe": "MZ"})
    make_iso(roms / "Freelancer.iso", src, label="FREELANCER")
    from vistal.gui.app import App
    app = App()
    app.reload(sync_art=True)
    app.render(1280, 800)
    assert not app.selected.installed
    tile = next(h for h in app.hits.items if h[4] == ("tile", 0))
    app.on_mouse_down(tile[0] + 5, tile[1] + 5, clicks=2)  # fake Proton installs it
    assert [c["program"] for c in read_log(fake_proton["log"])][1] == "D:\\Setup.exe"
    fl = next(e for e in app.entries if e.id == "freelancer")
    assert fl.installed and fl.last_played
    assert app.message is None


def test_launch_failure_is_reported(roms, tmp_path):
    from vistal.gui.app import App
    exe = roms / "Tool.exe"
    exe.write_bytes(b"MZ")
    app = App()
    app.reload(sync_art=True)
    app.render(1280, 800)
    app.activate()  # no Proton installed in the test home
    assert app.message is not None and app.message.kind == "error"
    assert "Proton" in app.message.text


def test_hits_topmost_wins():
    from vistal.gui.app import Hits
    h = Hits()
    h.add(0, 0, 100, 100, ("dismiss",))
    h.add(10, 10, 20, 20, ("menuitem", 0))
    assert h.at(15, 15) == ("menuitem", 0) and h.at(50, 50) == ("dismiss",) and h.at(200, 0) is None


def test_text_helpers():
    s = C.Surface.create(200, 50)
    ctx = C.Context(s)
    ctx.font(12)
    long = "Rise of Nations: Rise of Legends Collector's Edition"
    assert ctx.text_width(ctx.ellipsize(long, 100)) <= 100
    lines = ctx.wrap(long, 120, 2)
    assert len(lines) == 2 and lines[-1].endswith("…")
    assert ctx.wrap("Short", 120, 2) == ["Short"]
    one = ctx.wrap(long, 120, 1)
    assert len(one) == 1 and one[0].endswith("…")


def test_sdl_window_offscreen(monkeypatch):
    from vistal.gui import sdl
    try:
        sdl.lib()
    except sdl.SDLUnavailable:
        pytest.skip("SDL2 not installed")
    monkeypatch.setenv("SDL_VIDEODRIVER", "offscreen")
    win = sdl.Window("test", 320, 200)
    try:
        surf = C.Surface.create(*win.size())
        win.present(surf)
        win.events(1)
    finally:
        win.close()


def test_sdl_event_parsing():
    from vistal.gui import sdl
    w = sdl.Window.__new__(sdl.Window)
    w.controllers = []
    raw = bytearray(64)
    struct.pack_into("<IIIBB", raw, 0, sdl.KEYDOWN, 0, 1, 1, 0)
    struct.pack_into("<iiH", raw, 16, 0, (1 << 30) | 0x52, 0)
    assert w._parse(bytes(raw)).key == "up"
    raw = bytearray(64)
    struct.pack_into("<IIiB", raw, 0, sdl.CONTROLLERBUTTONDOWN, 0, 0, 0)
    assert w._parse(bytes(raw)).button == "a"
    raw = bytearray(64)
    struct.pack_into("<IIiB", raw, 0, sdl.CONTROLLERAXISMOTION, 0, 0, 1)
    struct.pack_into("<h", raw, 16, -32768)
    ev = w._parse(bytes(raw))
    assert ev.button == "ly" and ev.value == -1.0
    raw = bytearray(64)
    struct.pack_into("<IIIIBBB", raw, 0, sdl.MOUSEBUTTONDOWN, 0, 1, 0, 1, 1, 2)
    struct.pack_into("<ii", raw, 20, 40, 50)
    ev = w._parse(bytes(raw))
    assert (ev.kind, ev.x, ev.y, ev.clicks) == ("mousedown", 40, 50, 2)

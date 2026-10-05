import struct
from pathlib import Path

import pytest

from conftest import make_iso, make_tree, needs_geniso
from vistal import art, icons

FIX = Path(__file__).parent / "fixtures"


def _decode_png_alpha(png: bytes):
    import zlib
    w, h = icons.png_size(png)
    pos, idat = 8, b""
    while pos < len(png):
        n = struct.unpack(">I", png[pos:pos + 4])[0]
        kind = png[pos + 4:pos + 8]
        if kind == b"IDAT":
            idat += png[pos + 8:pos + 8 + n]
        pos += 12 + n
    raw = zlib.decompress(idat)
    return w, h, raw


def test_write_png_roundtrip():
    rgba = bytes([255, 0, 0, 255, 0, 255, 0, 128]) * 2
    png = icons.write_png(2, 2, rgba)
    w, h, raw = _decode_png_alpha(png)
    assert (w, h) == (2, 2)
    assert raw == b"\0" + rgba[:8] + b"\0" + rgba[8:]


def test_ico_all_formats():
    images = icons.parse_ico((FIX / "game.ico").read_bytes())
    assert [(i.width, i.height) for i in images] == [(256, 256), (48, 48), (32, 32)]
    assert icons.best(images).width == 256
    # 8-bit palette icon: AND mask makes the left 16 columns transparent
    w, h, rgba = icons.dib_to_rgba(images[2].data)
    assert (w, h) == (32, 32)
    assert rgba[3] == 0 and rgba[16 * 4 + 3] == 255
    # palette entry i is stored as B=i, G=0, R=255-i; column 16 uses index 128
    assert rgba[16 * 4:16 * 4 + 3] == bytes((127, 0, 128))
    w, h, rgba = icons.dib_to_rgba(images[1].data)
    assert rgba[3] == 0 and rgba[(24 * 48 + 24) * 4 + 3] == 255  # round orb, transparent corner


def test_pe_icons_and_gdf():
    data = (FIX / "gdfgame.exe").read_bytes()
    png = icons.icon_png_from_bytes(data)
    assert icons.png_size(png) == (256, 256)
    info = icons.gdf_from_pe(data)
    assert info.name == "Test Legends" and info.publisher == "Example Publishing"
    assert info.developer == "Example Studios" and info.genre == "Strategy"
    assert info.release_date == "2006-05-09" and info.version == "1.0.0.0"
    assert icons.png_size(info.thumbnail) == (64, 80)


def test_not_pe():
    with pytest.raises(icons.IconError):
        icons.read_pe_resources(b"MZ" + b"\0" * 100)
    with pytest.raises(icons.IconError):
        icons.parse_ico(b"junk")


def test_art_from_installed_exe_and_overrides(tmp_path):
    game = tmp_path / "Game"
    game.mkdir()
    exe = game / "game.exe"
    exe.write_bytes((FIX / "gdfgame.exe").read_bytes())
    a = art.resolve("test-legends", exe, None, [])
    assert a.icon and icons.png_size(a.icon.read_bytes()) == (256, 256)
    assert a.cover and a.cover_is_official and a.info["name"] == "Test Legends"
    assert a.tile() == a.cover and a.tile("icons") == a.icon
    # cached second time (same files)
    again = art.resolve("test-legends", exe, None, [])
    assert again.icon == a.icon
    # user override wins
    from vistal import paths
    gd = paths.game_dir("test-legends")
    gd.mkdir(parents=True)
    (gd / "boxart.jpg").write_bytes(b"\xff\xd8\xff")
    assert art.resolve("test-legends", exe, None, []).cover == gd / "boxart.jpg"


@needs_geniso
def test_art_from_disc_autorun(tmp_path):
    src = make_tree(tmp_path / "src", {"AUTORUN.INF": '[autorun]\nopen=setup.exe\nicon="Setup.exe",1\n',
                                       "SETUP.EXE": (FIX / "gdfgame.exe").read_bytes()})
    iso = make_iso(tmp_path / "Disc Game.iso", src)
    a = art.resolve("disc-game", None, iso, [iso])
    assert a.icon is not None and icons.png_size(a.icon.read_bytes()) == (256, 256)
    assert a.cover is None


def test_esde_cover(isolated_home, tmp_path):
    rom = tmp_path / "Freelancer.iso"
    rom.write_bytes(b"")
    covers = isolated_home / "ES-DE" / "downloaded_media" / "gfw" / "covers"
    covers.mkdir(parents=True)
    (covers / "Freelancer.jpg").write_bytes(b"\xff\xd8\xff")
    a = art.resolve("freelancer", None, rom, [])
    assert a.cover == covers / "Freelancer.jpg" and not a.cover_is_official
    assert a.tile() == a.cover  # no icon available, so the cover is used

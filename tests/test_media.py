import os

import pytest

from conftest import make_iso, make_tree, needs_geniso
from vistal import media, paths


def test_clean_title():
    assert media.clean_title("Freelancer (USA) (Disc 1)") == "Freelancer"
    assert media.clean_title("Midtown_Madness_2 [!]") == "Midtown Madness 2"
    assert media.clean_title("Rise of Legends - Disc 2") == "Rise of Legends"
    assert media.clean_title("Age of Empires II CD1") == "Age of Empires II"


def test_resolve_kinds(tmp_path):
    iso = tmp_path / "Freelancer (USA).iso"
    iso.write_bytes(b"x")
    s = media.resolve(iso)
    assert (s.kind, s.id, s.title, s.discs) == ("discs", "freelancer", "Freelancer", [iso.resolve()])

    d1, d2 = tmp_path / "RoL (Disc 1).iso", tmp_path / "sub" / "RoL (Disc 2).cue"
    d1.write_bytes(b"x")
    d2.parent.mkdir()
    d2.write_text("")
    m3u = tmp_path / "Rise of Legends.m3u"
    m3u.write_text("# comment\nRoL (Disc 1).iso\nsub\\RoL (Disc 2).cue\n")
    s = media.resolve(m3u)
    assert s.kind == "discs" and len(s.discs) == 2 and s.id == "rise-of-legends"

    disc_dir = make_tree(tmp_path / "Halo CD", {"AUTORUN.INF": "[autorun]\nopen=setup.exe"})
    assert media.resolve(disc_dir).kind == "discs"
    game_dir = make_tree(tmp_path / "Installed Game", {"game.exe": "MZ"})
    assert media.resolve(game_dir).kind == "portable"
    exe = tmp_path / "tool.exe"
    exe.write_bytes(b"MZ")
    assert media.resolve(exe).kind == "exe"

    with pytest.raises(media.MediaError):
        media.resolve(tmp_path / "missing.iso")
    bad = tmp_path / "x.txt"
    bad.write_text("")
    with pytest.raises(media.MediaError):
        media.resolve(bad)


def test_directory_named_like_a_file(tmp_path):
    folder = tmp_path / "Freelancer.m3u"
    folder.mkdir()
    (folder / "disc1.iso").write_bytes(b"x")
    (folder / "Freelancer.m3u").write_text("disc1.iso\n")
    s = media.resolve(folder)
    assert s.kind == "discs" and s.rom == (folder / "Freelancer.m3u").resolve() and s.id == "freelancer"


def test_m3u_missing_disc(tmp_path):
    m3u = tmp_path / "g.m3u"
    m3u.write_text("nope.iso\n")
    with pytest.raises(media.MediaError, match="missing"):
        media.resolve(m3u)


def test_vistal_spec(tmp_path):
    (tmp_path / "disc.iso").write_bytes(b"x")
    spec = tmp_path / "My Game.vistal"
    spec.write_text('title = "Freelancer"\ndiscs = ["disc.iso"]\nprofile = "freelancer"\n'
                    '[proton]\nfps_limit = 30\n')
    s = media.resolve(spec)
    assert s.id == "freelancer" and s.kind == "discs" and s.discs == [tmp_path.resolve() / "disc.iso"]
    assert s.spec["proton"]["fps_limit"] == 30

    spec2 = tmp_path / "Installed.vistal"
    spec2.write_text('title = "Game"\nexe = "C:/Games/game.exe"\n')
    s2 = media.resolve(spec2)
    assert s2.kind == "portable" and s2.exe is None


def test_find_installer(tmp_path):
    d = make_tree(tmp_path / "d", {"AUTORUN.INF": '[AutoRun]\nopen="Install Me.exe" /silent\n',
                                   "install me.EXE": "MZ"})
    exe, args = media.find_installer(d)
    assert exe.name == "install me.EXE" and args == ["/silent"]

    d2 = make_tree(tmp_path / "d2", {"autorun.inf": "[autorun]\nopen=autorun\\menu.exe -x\n",
                                     "Autorun/Menu.exe": "MZ"})
    exe, args = media.find_installer(d2)
    assert exe.name == "Menu.exe" and args == ["-x"]

    d3 = make_tree(tmp_path / "d3", {"Setup/SETUP.EXE": "MZ", "readme.txt": ""})
    assert media.find_installer(d3)[0].name == "SETUP.EXE"
    assert media.find_installer(make_tree(tmp_path / "d4", {"x.txt": ""})) is None


def test_split_command():
    assert media._split_command("setup.exe") == ("setup.exe", [])
    assert media._split_command("Program Files\\x setup.exe -a b") == ("Program Files\\x setup.exe", ["-a", "b"])
    assert media._split_command('"a b.exe" /q') == ("a b.exe", ["/q"])


@needs_geniso
def test_prepare_disc_extracts_once_and_builds_drive_root(tmp_path):
    src = make_tree(tmp_path / "src", {"setup.exe": "MZ", "Data/a.cab": "cab"})
    iso = make_iso(tmp_path / "game.iso", src, label="GAMEDISC")
    disc = media.prepare_disc(iso, "auto")
    assert disc.method == "extract" and disc.label == "GAMEDISC"
    assert (disc.content / "Data" / "a.cab").read_text() == "cab"
    again = media.prepare_disc(iso, "auto")
    assert again.content == disc.content  # cached
    root = media.build_drive_root(disc, tmp_path / "drive")
    assert (root / ".windows-label").read_text() == "GAMEDISC\n"
    assert int((root / ".windows-serial").read_text(), 16) == disc.serial
    assert (root / "Data" / "a.cab").read_text() == "cab"
    assert os.path.islink(root / "setup.exe")
    # rebuilding replaces the old root cleanly
    media.build_drive_root(disc, root)
    assert sorted(os.listdir(root)) == sorted(["setup.exe", "Data", ".windows-label", ".windows-serial"])


def test_prepare_directory_disc(tmp_path):
    d = make_tree(tmp_path / "CD", {"setup.exe": "MZ", ".windows-label": "MYLABEL\n"})
    disc = media.prepare_disc(d)
    assert disc.method == "directory" and disc.label == "MYLABEL" and disc.content == d


def test_slugify():
    assert paths.slugify("Rise of Nations: Rise of Legends") == "rise-of-nations-rise-of-legends"
    assert paths.slugify("Pokémon!!") == "pokemon"
    assert paths.slugify("???") == "game"

"""End-to-end install/launch flows against a fake `proton` script."""

import os

import pytest

from conftest import make_iso, make_tree, needs_geniso, read_log
from vistal import detect, library, media
from vistal.cli import main
from vistal.launcher import Session


@pytest.fixture
def freelancer_iso(tmp_path):
    src = make_tree(tmp_path / "src", {"AUTORUN.INF": "[autorun]\nopen=Setup.exe\n", "Setup.exe": "MZ",
                                       "Data/game.cab": "cab"})
    roms = tmp_path / "roms" / "gfw"
    roms.mkdir(parents=True)
    return make_iso(roms / "Freelancer (USA).iso", src, label="FREELANCER")


@needs_geniso
def test_first_launch_installs_then_plays(fake_proton, freelancer_iso):
    assert main(["launch", str(freelancer_iso)]) == 0
    calls = read_log(fake_proton["log"])
    assert [c["program"] for c in calls] == ["regedit", "D:\\Setup.exe",
                                             "C:\\Program Files (x86)\\Microsoft Games\\Freelancer\\EXE\\Freelancer.exe"]
    reg, setup, game = calls
    assert '"d:"="cdrom"' in reg["reg"] and "REGEDIT4" in reg["reg"]
    assert all(c["verb"] == "waitforexitandrun" for c in calls)
    assert setup["installer_exists"] and setup["label"] == "FREELANCER"
    assert "d:" in setup["drives"]
    # Freelancer profile: Direct3D 8 through DXVK, 60 fps cap
    assert game["env"]["PROTON_DXVK_D3D8"] == "1" and game["env"]["DXVK_FRAME_RATE"] == "60"
    assert game["cwd"].endswith("Freelancer/EXE")
    m = library.GameDir("freelancer").load()
    assert m.profile == "freelancer" and m.exe.endswith("Freelancer.exe") and m.last_played

    # Second launch: no installer, prefix registry unchanged -> only the game runs
    assert main(["launch", str(freelancer_iso)]) == 0
    calls = read_log(fake_proton["log"])[3:]
    assert [c["program"] for c in calls] == [game["program"]]

    # Launching by game id works too (what 'vistal launch freelancer' does)
    assert main(["launch", "freelancer"]) == 0

    # Reinstall runs the installer again
    assert main(["launch", "--reinstall", str(freelancer_iso)]) == 0
    assert any(c["program"] == "D:\\Setup.exe" for c in read_log(fake_proton["log"])[5:])


@needs_geniso
def test_registry_reapplied_when_settings_change(fake_proton, freelancer_iso, isolated_home):
    assert main(["launch", str(freelancer_iso)]) == 0
    n = len(read_log(fake_proton["log"]))
    cfg = isolated_home / ".config" / "vistal" / "games" / "freelancer.toml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('[prefix]\nwinver = "winxp"\nvirtual_desktop = "1024x768"\n')
    assert main(["launch", str(freelancer_iso)]) == 0
    reg, game = read_log(fake_proton["log"])[n:]
    assert '"Version"="winxp"' in reg["reg"]
    assert game["program"] == "explorer.exe" and game["args"][0] == "/desktop=Vistal,1024x768"


@needs_geniso
def test_multi_disc_playlist(fake_proton, tmp_path):
    discs = []
    for n in (1, 2):
        src = make_tree(tmp_path / f"s{n}", {"setup.exe": "MZ"} if n == 1 else {"data2.cab": "x"})
        discs.append(make_iso(tmp_path / f"Freelancer (Disc {n}).iso", src, label=f"FL_DISC{n}"))
    m3u = tmp_path / "Freelancer.m3u"
    m3u.write_text("\n".join(d.name for d in discs) + "\n")
    s = Session(media.resolve(m3u))
    assert s.profile_id == "freelancer"
    assert s.install()
    setup = [c for c in read_log(fake_proton["log"]) if c["program"].endswith("setup.exe")][0]
    assert {"d:", "e:"} <= set(setup["drives"])
    d = s.prefix.dosdevices
    assert os.path.realpath(d / "e:") == str(s.game.disc_root(1).resolve())
    s.swap_disc(1)
    assert os.path.realpath(d / "d:") == str(s.game.disc_root(1).resolve())
    assert (d / "d:" / ".windows-label").read_text().strip() == "FL_DISC2"
    s.swap_disc(1)
    assert (d / "d:" / ".windows-label").read_text().strip() == "FL_DISC1"
    s.release_discs()


@needs_geniso
def test_install_without_new_executable_fails(fake_proton, tmp_path):
    """An installer that is cancelled leaves nothing to launch."""
    iso = make_iso(tmp_path / "Unknown Game.iso", make_tree(tmp_path / "src", {"setup.exe": "MZ"}))
    s = Session(media.resolve(iso))
    try:
        s.prepare_discs()
        s.prefix.ensure(s.runner, s.settings)
        assert s._finish_install(detect.snapshot(s.prefix.pfx)) is False
        assert not library.GameDir(s.source.id).load()
    finally:
        s.release_discs()


@needs_geniso
def test_no_installer_on_disc(fake_proton, tmp_path):
    iso = make_iso(tmp_path / "Data Disc.iso", make_tree(tmp_path / "src", {"readme.txt": "hi"}))
    assert main(["launch", str(iso)]) == 1


def test_portable_folder(fake_proton, tmp_path):
    game = make_tree(tmp_path / "Midtown Madness", {"Midtown.exe": b"MZ" * 100, "uninst.exe": "MZ"})
    assert main(["launch", str(game)]) == 0
    calls = read_log(fake_proton["log"])
    assert calls[-1]["program"] == "Z:" + str(game / "Midtown.exe").replace("/", "\\")
    assert library.GameDir("midtown-madness").load().profile == "midtown-madness"


def test_direct_exe(fake_proton, tmp_path):
    exe = tmp_path / "Tool.exe"
    exe.write_bytes(b"MZ")
    assert main(["launch", str(exe)]) == 0
    assert read_log(fake_proton["log"])[-1]["program"].endswith("Tool.exe")


@needs_geniso
def test_set_exe_and_info(fake_proton, freelancer_iso, capsys):
    assert main(["install", str(freelancer_iso)]) == 0
    assert main(["set-exe", str(freelancer_iso), "C:\\Program Files (x86)\\Microsoft Games\\Freelancer\\EXE\\FLServer.exe"]) == 0
    assert library.GameDir("freelancer").load().exe.endswith("FLServer.exe")
    assert main(["set-exe", str(freelancer_iso), "C:\\nope.exe"]) == 1
    assert main(["info", str(freelancer_iso)]) == 0
    out = capsys.readouterr().out
    assert "FREELANCER" in out and "Freelancer" in out and "Installed: C:" in out
    assert main(["list"]) == 0
    assert "freelancer" in capsys.readouterr().out


@needs_geniso
def test_cli_image_tools(tmp_path, capsys):
    src = make_tree(tmp_path / "src", {"a/b.txt": "hello"})
    iso = make_iso(tmp_path / "x.iso", src, label="XDISC")
    assert main(["ls", str(iso)]) == 0
    assert "a/b.txt" in capsys.readouterr().out
    assert main(["extract", str(iso), str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "a" / "b.txt").read_text() == "hello"


def test_no_proton_is_a_clean_error(tmp_path):
    exe = tmp_path / "a.exe"
    exe.write_bytes(b"MZ")
    assert main(["launch", str(exe)]) == 1


@needs_geniso
def test_vistal_file_with_exe_and_disc_skips_installer(fake_proton, freelancer_iso, tmp_path):
    assert main(["install", str(freelancer_iso)]) == 0
    spec = tmp_path / "Freelancer.vistal"
    spec.write_text('title = "Freelancer"\nexe = "C:/Program Files (x86)/Microsoft Games/Freelancer/EXE/Freelancer.exe"\n'
                    f'discs = ["{freelancer_iso}"]\n')
    n = len(read_log(fake_proton["log"]))
    assert main(["launch", str(spec)]) == 0
    calls = read_log(fake_proton["log"])[n:]
    assert [c["program"] for c in calls] == ["C:\\Program Files (x86)\\Microsoft Games\\Freelancer\\EXE\\Freelancer.exe"]
    assert "d:" in os.listdir(library.GameDir("freelancer").compat / "pfx" / "dosdevices")

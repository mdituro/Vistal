from pathlib import Path

import pytest

from vistal import proton, vdf
from vistal.proton import Runner, select_proton


def _mk(base: Path, name: str, manifest: str | None = None) -> Path:
    d = base / name
    d.mkdir(parents=True)
    (d / "proton").write_text("#!/bin/sh\n")
    (d / "files" / "bin").mkdir(parents=True)
    (d / "files" / "bin" / "wineserver").write_text("")
    if manifest:
        (d / "toolmanifest.vdf").write_text(manifest)
    return d


SNIPER = '"manifest"\n{\n  "version" "2"\n  "commandline" "/proton %verb%"\n  "require_tool_appid" "1628350"\n}\n'


@pytest.fixture
def steam(isolated_home, tmp_path):
    root = isolated_home / ".local" / "share" / "Steam"
    (root / "steamapps" / "common").mkdir(parents=True)
    (isolated_home / ".steam").mkdir()
    (isolated_home / ".steam" / "root").symlink_to(root)
    lib2 = tmp_path / "sdcard" / "SteamLibrary"
    (lib2 / "steamapps" / "common").mkdir(parents=True)
    (root / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n\t"1"\n\t{\n\t\t"path"\t\t"%s"\n\t\t"apps"\n\t\t{\n\t\t}\n\t}\n}\n'
        % (root, lib2))
    _mk(root / "steamapps" / "common", "Proton 8.0", SNIPER)
    _mk(lib2 / "steamapps" / "common", "Proton 9.0 (Beta)", SNIPER)
    _mk(root / "steamapps" / "common", "Proton - Experimental", SNIPER)
    _mk(root / "compatibilitytools.d", "GE-Proton9-20")
    rt = lib2 / "steamapps" / "common" / "SteamLinuxRuntime_sniper"
    rt.mkdir()
    (rt / "_v2-entry-point").write_text("#!/bin/sh\n")
    return {"root": root, "lib2": lib2, "runtime": rt}


def test_vdf_parser():
    data = vdf.loads('// c\n"a"\n{\n "B" "x\\"y"\n "c" { "d" "1" }\n plain value\n}\n')
    assert data == {"a": {"B": 'x"y', "c": {"d": "1"}, "plain": "value"}}
    assert vdf.get_ci(data["a"], "b") == 'x"y'
    with pytest.raises(vdf.VDFError):
        vdf.loads("}")


def test_discovery_and_selection(steam):
    builds = {b.name: b for b in proton.find_protons()}
    assert set(builds) == {"Proton 8.0", "Proton 9.0 (Beta)", "Proton - Experimental", "GE-Proton9-20"}
    assert builds["GE-Proton9-20"].kind == "ge" and builds["GE-Proton9-20"].version == (9, 20)
    assert builds["Proton 9.0 (Beta)"].runtime_appid == "1628350"
    assert select_proton().name == "Proton 9.0 (Beta)"
    assert select_proton("experimental").name == "Proton - Experimental"
    assert select_proton("ge-proton").name == "GE-Proton9-20"
    assert select_proton(str(steam["root"] / "compatibilitytools.d" / "GE-Proton9-20")).kind == "ge"
    assert select_proton("does-not-exist").name == "Proton 9.0 (Beta)"
    assert proton.find_runtime("1628350") == steam["runtime"] / "_v2-entry-point"


def test_no_proton(isolated_home):
    with pytest.raises(proton.ProtonError):
        select_proton()


def test_runner_modes_and_env(steam, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("SteamGameId", "12345")
    monkeypatch.setenv("WINEDLLOVERRIDES", "inherited=n")
    b = select_proton()
    r = Runner(b, tmp_path / "compat", {"dxvk_d3d8": True, "fps_limit": 60, "cpu_cores": 2,
                                        "dll_overrides": {"ddraw": "n,b"}, "env": {"FOO": "bar"}},
               extra_paths=[tmp_path / "roms", tmp_path / "roms"])
    assert r.resolved_mode() == "runtime"
    argv, add = r.command("D:\\setup.exe", ["/x"])
    assert argv[0].endswith("_v2-entry-point") and argv[1] == "--verb=waitforexitandrun"
    assert argv[3:] == [str(b.script), "waitforexitandrun", "D:\\setup.exe", "/x"]
    env = r.environment({"WINEDLLOVERRIDES": "xlive=n"})
    assert env["STEAM_COMPAT_DATA_PATH"] == str(tmp_path / "compat")
    assert env["WINEPREFIX"] == str(tmp_path / "compat" / "pfx")
    assert env["SteamGameId"] == "12345"  # inherited for gamescope focus
    assert env["PROTON_DXVK_D3D8"] == "1" and env["DXVK_FRAME_RATE"] == "60"
    assert env["WINE_CPU_TOPOLOGY"] == "2:0,1"
    assert env["WINEDLLOVERRIDES"] == "ddraw=n,b;xlive=n"
    assert env["FOO"] == "bar"
    assert env["STEAM_COMPAT_MOUNTS"] == str(tmp_path / "roms")
    assert Path(env["STEAM_COMPAT_CLIENT_INSTALL_PATH"]) == steam["root"]

    r.mode = "direct"
    argv, _ = r.command("game.exe")
    assert argv == [str(b.script), "waitforexitandrun", "game.exe"]


def test_umu_mode(steam, tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "umu-run").write_text("#!/bin/sh\n")
    (bindir / "umu-run").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:/usr/bin:/bin")
    r = Runner(select_proton(), tmp_path / "compat", umu_gameid="umu-12345")
    assert r.resolved_mode() == "umu"
    argv, add = r.command("game.exe", ["-w"])
    assert argv == [str(bindir / "umu-run"), "game.exe", "-w"]
    assert add["GAMEID"] == "umu-12345" and add["WINEPREFIX"] == str(tmp_path / "compat")
    assert add["PROTONPATH"] == str(select_proton().path)


def test_settings_translation():
    env = proton.proton_env_from_settings({"renderer": "wined3d", "esync": False, "fsync": False,
                                            "large_address_aware": True, "heap_delay_free": True,
                                            "old_gl_string": True})
    assert env == {"PROTON_USE_WINED3D": "1", "PROTON_NO_ESYNC": "1", "PROTON_NO_FSYNC": "1",
                   "PROTON_FORCE_LARGE_ADDRESS_AWARE": "1", "PROTON_HEAP_DELAY_FREE": "1",
                   "PROTON_OLD_GL_STRING": "1"}
    assert proton.proton_env_from_settings({}) == {}


def test_path_conversion(tmp_path):
    pfx = tmp_path / "pfx"
    (pfx / "drive_c" / "Games").mkdir(parents=True)
    assert proton.to_windows_path(pfx / "drive_c" / "Games" / "a.exe", pfx) == "C:\\Games\\a.exe"
    assert proton.to_windows_path("/home/deck/x.reg") == "Z:\\home\\deck\\x.reg"
    assert proton.to_unix_path("C:\\Games\\a.exe", pfx) == pfx / "drive_c" / "Games" / "a.exe"
    assert proton.to_unix_path("d:/setup.exe", pfx) == pfx / "dosdevices" / "d:" / "setup.exe"
    assert proton.to_unix_path("Z:\\etc\\hosts", pfx) == Path("/etc/hosts")

import xml.etree.ElementTree as ET
from pathlib import Path

from vistal import frontends, library, paths, profiles, tomlutil


def test_builtin_profiles_load_and_reference_valid_layouts():
    from vistal.controller import layout as L
    profs = profiles.all_profiles()
    for pid in ("freelancer", "rise-of-legends", "midtown-madness", "midtown-madness-2"):
        assert pid in profs
    for pid, p in profs.items():
        lay = (p.get("controller") or {}).get("layout")
        if lay:
            assert L.find(lay), (pid, lay)
        assert p["launch"]["exe"], pid


def test_matching():
    assert profiles.match("Freelancer").profile_id == "freelancer"
    assert profiles.match("Rise of Nations - Rise of Legends").profile_id == "rise-of-legends"
    assert profiles.match("Midtown Madness").profile_id == "midtown-madness"
    assert profiles.match("Midtown Madness 2").profile_id == "midtown-madness-2"
    assert profiles.match("Some Game", label="FREELANCER").profile_id == "freelancer"
    assert profiles.match("Some Unknown Game") is None


def test_effective_settings_layering():
    tomlutil.save(paths.user_config_file(), {"proton": {"version": "GE-Proton9-20", "fps_limit": 144}})
    tomlutil.save(paths.game_settings_file("freelancer"), {"proton": {"fps_limit": 30}, "launch": {"args": ["-w"]}})
    s = profiles.effective("freelancer", "freelancer")
    assert s["proton"]["version"] == "GE-Proton9-20"   # user config
    assert s["proton"]["dxvk_d3d8"] is True             # profile
    assert s["proton"]["fps_limit"] == 30               # per-game override beats profile and config
    assert s["launch"]["args"] == ["-w"]
    assert s["disc"]["letter"] == "d"                   # built-in default
    generic = profiles.effective(None, "other")
    assert generic["proton"]["fps_limit"] == 144 and generic["controller"]["layout"] == "desktop"


def test_user_profile_overrides_builtin():
    tomlutil.save(paths.user_profiles_dir() / "freelancer.toml", {"controller": {"layout": "fps"}})
    tomlutil.save(paths.user_profiles_dir() / "my-game.toml", {"title": "My Game", "match": {"names": ["my game*"]},
                                                                "launch": {"exe": ["mg.exe"]}})
    p = profiles.get("freelancer")
    assert p["controller"]["layout"] == "fps" and p["launch"]["exe"] == ["Freelancer.exe"]
    assert profiles.match("My Game Deluxe").profile_id == "my-game"


def test_toml_roundtrip():
    import tomllib
    d = {"a": 1, "b": "x\"y", "c": [1, "2"], "t": {"x": True, "deep": {"k": "v"}}, "e": {}}
    assert tomllib.loads(tomlutil.dumps(d)) == d


def test_esde_install_merges(isolated_home):
    home = isolated_home / "ES-DE"
    custom = home / "custom_systems"
    custom.mkdir(parents=True)
    (custom / "es_systems.xml").write_text(
        "<?xml version=\"1.0\"?>\n<systemList>\n  <system><name>mysys</name><fullname>Mine</fullname></system>\n"
        "  <system><name>gfw</name><fullname>old</fullname></system>\n</systemList>\n")
    (home / "settings").mkdir()
    roms = isolated_home / "Emulation" / "roms"
    (home / "settings" / "es_settings.xml").write_text(
        f'<?xml version="1.0"?>\n<bool name="x" value="true" />\n<string name="ROMDirectory" value="{roms}" />\n')
    report = frontends.install_esde()
    assert any("gfw" in r for r in report)
    for _ in range(2):  # idempotent
        frontends.install_esde()
    root = ET.parse(custom / "es_systems.xml").getroot()
    systems = {s.findtext("name"): s for s in root.findall("system")}
    assert set(systems) == {"mysys", "gfw"}
    gfw = systems["gfw"]
    assert gfw.findtext("path") == "%ROMPATH%/gfw"
    cmds = gfw.findall("command")
    assert cmds[0].text == "%EMULATOR_VISTAL% launch %ROM%" and cmds[0].get("label")
    exts = gfw.findtext("extension").split()
    assert ".iso" in exts and ".ISO" in exts and ".m3u" in exts and ".vistal" in exts
    assert ".cue" in exts and ".bin" not in exts and ".mdf" not in exts
    rules = ET.parse(custom / "es_find_rules.xml").getroot()
    assert len(rules.findall("emulator")) == 1
    assert rules.find("emulator").get("name") == "VISTAL"
    assert (roms / "gfw" / "systeminfo.txt").exists()


def test_esde_rom_dir_fallback(isolated_home):
    assert frontends.esde_rom_directory() == isolated_home / "ROMs"
    (isolated_home / "Emulation" / "roms").mkdir(parents=True)
    assert frontends.esde_rom_directory() == isolated_home / "Emulation" / "roms"


def test_emulationstation_and_desktop(isolated_home):
    snippet = frontends.emulationstation_system_xml("~/RetroPie/roms/gfw")
    el = ET.fromstring(snippet.strip())
    assert el.findtext("command").endswith("launch %ROM%")
    frontends.install_emulationstation("~/RetroPie/roms/gfw")
    frontends.install_emulationstation("~/RetroPie/roms/gfw")
    cfg = ET.parse(isolated_home / ".emulationstation" / "es_systems.cfg").getroot()
    assert len(cfg.findall("system")) == 1

    gd = library.GameDir("freelancer")
    gd.save(library.Manifest(id="freelancer", title="Freelancer", rom="/roms/gfw/Free 100%.iso", exe="C:\\x.exe"))
    files = frontends.write_desktop_entries(isolated_home / "apps")
    assert "Exec=" in Path(files[0]).read_text() and Path(files[0]).read_text().rstrip().endswith("Terminal=false")
    assert " gui" in Path(files[0]).read_text()
    text = Path(next(f for f in files if f.endswith("vistal-freelancer.desktop"))).read_text()
    assert 'launch "/roms/gfw/Free 100%%.iso"' in text and "Name=Freelancer" in text

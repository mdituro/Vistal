import struct
from pathlib import Path

import pytest

from conftest import make_tree
from vistal import detect, lnk


def test_lnk_roundtrip():
    data = lnk.build("C:\\Games\\Freelancer\\EXE\\Freelancer.exe", arguments="-nointro", working_dir="C:\\Games")
    info = lnk.parse(data)
    assert info.target == "C:\\Games\\Freelancer\\EXE\\Freelancer.exe"
    assert info.arguments == "-nointro" and info.working_dir == "C:\\Games"
    with pytest.raises(lnk.LnkError):
        lnk.parse(b"not a link" * 10)


def _item(data: bytes) -> bytes:
    return struct.pack("<H", len(data) + 2) + data


def test_lnk_idlist_only():
    drive = _item(b"\x2fC:\\" + b"\0" * 19)
    folder = _item(b"\x31\x00" + b"\0" * 10 + b"GAMES\0")
    long_name = "Freelancer.exe".encode("utf-16-le") + b"\0\0"
    ext = struct.pack("<HHI", 0x12 + len(long_name) + 2, 3, 0xBEEF0004) + b"\0" * 10 + long_name + b"\0\0"
    file_item = _item(b"\x32\x00" + b"\0" * 10 + b"FREELA~1.EXE\0\0" + ext)
    idlist = drive + folder + file_item + b"\0\0"
    header = struct.pack("<I16sIIQQQIIIHHII", 0x4C, lnk.LNK_CLSID, lnk.HAS_IDLIST, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0)
    info = lnk.parse(header + struct.pack("<H", len(idlist)) + idlist)
    assert info.target == "C:\\GAMES\\Freelancer.exe"


def _prefix(tmp_path: Path) -> Path:
    pfx = tmp_path / "pfx"
    make_tree(pfx / "drive_c", {"windows/system32/notepad.exe": "MZ", "windows/regedit.exe": "MZ"})
    return pfx


def test_candidates_prefers_start_menu_shortcut(tmp_path):
    pfx = _prefix(tmp_path)
    before = detect.snapshot(pfx)
    game = "Program Files (x86)/Microsoft Games/Rise of Legends"
    make_tree(pfx / "drive_c", {
        f"{game}/RiseOfLegends.exe": b"MZ" + b"\0" * 5000,
        f"{game}/Uninstall.exe": "MZ",
        f"{game}/Tools/Editor.exe": b"MZ" + b"\0" * 50000,
        f"{game}/DirectX/DXSETUP.exe": "MZ",
    })
    sm = pfx / "drive_c" / "users" / "steamuser" / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu"
    sm.mkdir(parents=True)
    win = "C:\\" + game.replace("/", "\\")
    (sm / "Rise of Legends.lnk").write_bytes(lnk.build(win + "\\riseoflegends.EXE"))  # case differs
    (sm / "Uninstall Rise of Legends.lnk").write_bytes(lnk.build(win + "\\Uninstall.exe"))
    (sm / "Readme.lnk").write_bytes(lnk.build(win + "\\readme.txt"))
    cands = detect.candidates(pfx, "Rise of Legends", [], before)
    assert cands[0].path.name == "RiseOfLegends.exe"
    names = [c.path.name for c in cands]
    assert "Uninstall.exe" not in names and "DXSETUP.exe" not in names
    assert "notepad.exe" not in names


def test_candidates_profile_name_wins(tmp_path):
    pfx = _prefix(tmp_path)
    make_tree(pfx / "drive_c", {"Games/AoE/age2_x1/age2_x1.exe": "MZ", "Games/AoE/EMPIRES2.EXE": b"MZ" * 9999})
    cands = detect.candidates(pfx, "Age of Empires II", ["age2_x1.exe", "empires2.exe"], None)
    assert [c.path.name for c in cands[:2]] == ["age2_x1.exe", "EMPIRES2.EXE"]
    assert cands[0].score >= 90
    assert detect.find_by_name(pfx / "drive_c", ["missing.exe", "Empires2.exe"]).name == "EMPIRES2.EXE"


def test_similarity():
    assert detect._similarity("Midtown Madness 2", "mm2", "Midtown Madness 2") == 1.0
    assert detect._similarity("Freelancer", "Freelancer") == 1.0
    assert detect._similarity("Freelancer", "FLServer") == 0.0


@pytest.mark.parametrize("where", ["ProgramData/Microsoft/Windows/Start Menu/Programs/Game",
                                   "users/Public/Desktop",
                                   "users/steamuser/AppData/Roaming/Microsoft/Windows/Start Menu/Programs"])
def test_shortcut_locations_without_profile(tmp_path, where):
    """No profile hint: the installer's shortcut alone must identify the game."""
    pfx = _prefix(tmp_path)
    before = detect.snapshot(pfx)
    make_tree(pfx / "drive_c", {
        "Games/Obscure/bin/xyz_main.exe": b"MZ" + b"\0" * 100,
        "Games/Obscure/bin/huge_other.exe": b"MZ" + b"\0" * 9_000_000,
    })
    folder = pfx / "drive_c" / where
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "Obscure Game.lnk").write_bytes(lnk.build("C:\\Games\\Obscure\\bin\\xyz_main.exe"))
    cands = detect.candidates(pfx, "Obscure Game", [], before)
    assert cands[0].path.name == "xyz_main.exe", [(c.path.name, c.score) for c in cands]

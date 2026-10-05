import filecmp
import os

import pytest

from conftest import make_iso, make_tree, needs_geniso, to_raw
from vistal import discimage
from vistal.discimage import Disc, ImageError, UDFOnlyError

FILES = {
    "autorun.inf": "[autorun]\r\nopen=Setup.exe /auto\r\nicon=setup.exe,0\r\n",
    "Setup.exe": b"MZ" + bytes(range(256)) * 10,
    "EXE/Freelancer Long Name.exe": b"MZ game",
    "DATA/Deep/Nested/Directory/file.ini": "[x]\na=1\n",
    "DATA/big.bin": os.urandom(3 * 1024 * 1024 + 123),
    "lowercase.txt": "hello",
}


@pytest.fixture
def src(tmp_path):
    return make_tree(tmp_path / "src", FILES)


@needs_geniso
def test_joliet_names_label_and_content(tmp_path, src):
    iso = make_iso(tmp_path / "j.iso", src, label="FREELANCER")
    with Disc(str(iso)) as d:
        assert d.label == "FREELANCER"
        assert d.reader.layout == "cooked"
        paths = {e.path for e in d.fs.walk()}
        assert "EXE/Freelancer Long Name.exe" in paths
        assert "DATA/Deep/Nested/Directory/file.ini" in paths
        assert d.fs.read_file("data/BIG.bin") == FILES["DATA/big.bin"]
        assert d.fs.lookup("exe\\freelancer long name.EXE") is not None
        assert d.fs.lookup("missing/file") is None


@needs_geniso
def test_rock_ridge_names(tmp_path, src):
    iso = make_iso(tmp_path / "r.iso", src, joliet=False, rr=True)
    with Disc(str(iso)) as d:
        names = {e.path for e in d.fs.walk()}
        assert "EXE/Freelancer Long Name.exe" in names
        assert "lowercase.txt" in names


@needs_geniso
def test_plain_iso9660_strips_versions(tmp_path, src):
    iso = make_iso(tmp_path / "p.iso", src, joliet=False)
    with Disc(str(iso)) as d:
        names = {e.name for e in d.fs.walk()}
        assert "AUTORUN.INF" in names
        assert not any(";" in n for n in names)


@needs_geniso
@pytest.mark.parametrize("mode,sector", [(1, 2352), (2, 2352), (1, 2448)])
def test_raw_images(tmp_path, src, mode, sector):
    iso = make_iso(tmp_path / "c.iso", src)
    raw = to_raw(iso, tmp_path / "game.bin", mode=mode, sector=sector)
    with Disc(str(raw)) as d:
        assert d.reader.sector_size == sector
        assert d.fs.read_file("DATA/big.bin") == FILES["DATA/big.bin"]


@needs_geniso
def test_cue_sheet_with_wrong_case_and_audio_track(tmp_path, src):
    iso = make_iso(tmp_path / "c.iso", src, label="MIDTOWN")
    to_raw(iso, tmp_path / "Midtown.BIN", mode=1)
    cue = tmp_path / "Midtown.cue"
    cue.write_text('FILE "midtown.bin" BINARY\n  TRACK 01 MODE1/2352\n    INDEX 01 00:00:00\n'
                   '  TRACK 02 AUDIO\n    INDEX 00 10:00:00\n    INDEX 01 10:02:00\n')
    tracks = discimage.parse_cue(str(cue))
    assert [t.mode for t in tracks] == ["MODE1/2352", "AUDIO"]
    assert tracks[1].index1_frames == (10 * 60 + 2) * 75
    with Disc(str(cue)) as d:
        assert d.label == "MIDTOWN"
        assert d.fs.read_file("Setup.exe") == FILES["Setup.exe"]


@needs_geniso
def test_nrg_with_pregap(tmp_path, src):
    iso = make_iso(tmp_path / "c.iso", src)
    nrg = tmp_path / "game.nrg"
    nrg.write_bytes(b"\0" * 150 * 2048 + iso.read_bytes() + b"chunks" + b"NER5" + (0).to_bytes(8, "big"))
    with Disc(str(nrg)) as d:
        assert d.fs.read_file("lowercase.txt") == b"hello"


@needs_geniso
def test_mds_points_to_mdf(tmp_path, src):
    iso = make_iso(tmp_path / "c.iso", src)
    to_raw(iso, tmp_path / "Game.mdf")
    (tmp_path / "Game.mds").write_bytes(b"MEDIA DESCRIPTOR")
    with Disc(str(tmp_path / "Game.mds")) as d:
        assert d.reader.sector_size == 2352


@needs_geniso
def test_extract_matches_source(tmp_path, src):
    iso = make_iso(tmp_path / "x.iso", src)
    out = tmp_path / "out"
    seen = []
    with Disc(str(iso)) as d:
        d.fs.extract(str(out), lambda done, total, name: seen.append((done, total)))
    for rel in FILES:
        assert filecmp.cmp(src / rel, out / rel, shallow=False), rel
    assert seen[-1][0] == seen[-1][1]


@needs_geniso
def test_udf_bridge_is_read_through_iso9660(tmp_path, src):
    iso = make_iso(tmp_path / "u.iso", src, extra=["-udf"])
    with Disc(str(iso)) as d:
        assert d.fs.read_file("lowercase.txt") == b"hello"


def test_udf_only_detected(tmp_path):
    img = tmp_path / "udf.iso"
    data = bytearray(2048 * 20)
    data[16 * 2048 : 16 * 2048 + 6] = b"\x00BEA01"
    data[17 * 2048 : 17 * 2048 + 6] = b"\x00NSR02"
    img.write_bytes(bytes(data))
    with pytest.raises(UDFOnlyError):
        Disc(str(img))


def test_garbage_rejected(tmp_path):
    img = tmp_path / "junk.iso"
    img.write_bytes(os.urandom(100000))
    with pytest.raises(ImageError):
        Disc(str(img))


@needs_geniso
def test_serial_matches_wine_algorithm(tmp_path, src):
    iso = make_iso(tmp_path / "s.iso", src)
    with Disc(str(iso)) as d:
        desc = d.fs.joliet
        sums = [sum(desc[i::4]) & 0xFF for i in range(4)]
        assert d.serial == (sums[0] << 24) | (sums[1] << 16) | (sums[2] << 8) | sums[3]


def test_parse_autorun():
    text = "﻿; comment\n[AutoRun]\nOPEN = setup.exe /x\nicon=a.ico\n[other]\nopen=no.exe\n"
    assert discimage.parse_autorun(text) == {"open": "setup.exe /x", "icon": "a.ico"}
    assert discimage.decode_text("é".encode("cp1252")) == "é"
    assert discimage.decode_text("x".encode("utf-16")) == "x"

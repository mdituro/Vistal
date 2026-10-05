"""The mapper must never get in the way of a game, even without devices or uinput."""
import time

from vistal.controller.layout import load
from vistal.controller.engine import Hotkey
from vistal.controller.mapper import Mapper


def test_mapper_starts_and_stops_without_hardware():
    m = Mapper(load("desktop"), [Hotkey.make(["back", "start"], 1.5, "exit")], grab=True)
    m.start()  # falls back to hotkey-only mode when /dev/uinput is unavailable
    time.sleep(0.05)
    m.stop()


def test_controller_context_in_session(fake_proton, tmp_path, monkeypatch):
    monkeypatch.delenv("VISTAL_NO_MAPPER")
    from vistal.cli import main
    exe = tmp_path / "Freelancer.exe"
    exe.write_bytes(b"MZ")
    assert main(["launch", str(exe)]) == 0

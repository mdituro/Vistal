import struct

import pytest

from vistal.controller import keys as K
from vistal.controller import layout as L
from vistal.controller.engine import Engine, Hotkey
from vistal.controller.evdev import AbsInfo, InputDevice, Translator


class Recorder:
    def __init__(self):
        self.events = []

    def key(self, code, down):
        self.events.append(("key", code, down))

    def rel(self, dx, dy):
        self.events.append(("rel", dx, dy))

    def wheel(self, n):
        self.events.append(("wheel", n))

    def sync(self):
        pass

    def keys(self):
        return [e for e in self.events if e[0] == "key"]


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_parse_action():
    assert K.parse_action("w").keys == (K.KEYS["w"],)
    assert K.parse_action("Ctrl+Shift+S").keys == (29, 42, 31)
    assert K.parse_action("mouse_left").keys == (K.BTN_LEFT,)
    assert K.parse_action("wheel_down").wheel == -1
    assert K.parse_action("layer:alt").layer == "alt"
    assert K.parse_action("exit").special == "exit"
    assert K.parse_action("none").is_none
    assert K.parse_action("kp+").keys == (78,)
    with pytest.raises(K.ActionError):
        K.parse_action("ctrl+nokey")
    assert K.normalize_input("Cross") == "a" and K.normalize_input("L2") == "lt"
    with pytest.raises(K.ActionError):
        K.normalize_input("bogus")


@pytest.mark.parametrize("name", sorted(L.available()))
def test_builtin_layouts_are_valid(name):
    lay = L.load(name)
    assert lay.bindings
    assert "back" not in lay.bindings  # reserved for Vistal hotkeys


def test_layout_validation():
    with pytest.raises(L.LayoutError, match="undefined layer"):
        L.from_dict({"bindings": {"a": "layer:nope"}})
    with pytest.raises(L.LayoutError, match="unknown setting"):
        L.from_dict({"settings": {"speed": 1}})
    with pytest.raises(L.LayoutError, match="stick"):
        L.from_dict({"sticks": {"left": "dance"}})
    with pytest.raises(L.LayoutError, match="unknown controller input"):
        L.from_dict({"bindings": {"zz": "a"}})


def make(bindings, sticks=None, layers=None, settings=None, hotkeys=(), specials=None):
    lay = L.from_dict({"bindings": bindings, "sticks": sticks or {}, "layers": layers or {},
                       "settings": settings or {}})
    rec, clock = Recorder(), Clock()
    eng = Engine(lay, rec, hotkeys, on_special=(specials.append if specials is not None else None), clock=clock)
    return eng, rec, clock


def test_buttons_refcount_and_combos():
    eng, rec, _ = make({"a": "ctrl+s", "b": "ctrl"})
    eng.button("a", True)
    eng.button("b", True)
    eng.button("a", False)  # ctrl must stay down because B still holds it
    assert rec.keys() == [("key", 29, True), ("key", 31, True), ("key", 31, False)]
    eng.button("b", False)
    assert rec.keys()[-1] == ("key", 29, False)
    eng.button("b", False)  # duplicate release is ignored
    assert len(rec.keys()) == 4


def test_layers_release_original_action():
    eng, rec, _ = make({"lt": "layer:alt", "a": "1"}, layers={"alt": {"a": "2"}})
    eng.button("a", True)        # presses 1
    eng.axis("lt", 1.0)          # enter layer while A held
    eng.button("a", False)       # must release 1, not 2
    eng.button("a", True)        # now presses 2
    eng.axis("lt", 0.0)
    eng.button("a", False)
    k1, k2 = K.KEYS["1"], K.KEYS["2"]
    assert rec.keys() == [("key", k1, True), ("key", k1, False), ("key", k2, True), ("key", k2, False)]


def test_stick_keys_with_hysteresis():
    eng, rec, _ = make({"ls_up": "w", "ls_right": "d"}, sticks={"left": "keys"},
                       settings={"stick_threshold": 0.5})
    eng.axis("ly", -0.6)
    eng.axis("ly", -0.45)  # inside hysteresis band: still held
    assert rec.keys() == [("key", K.KEYS["w"], True)]
    eng.axis("ly", -0.2)
    eng.axis("lx", 0.9)
    assert rec.keys()[1:] == [("key", K.KEYS["w"], False), ("key", K.KEYS["d"], True)]


def test_mouse_stick_motion_and_precision():
    eng, rec, _ = make({"rb": "precision"}, sticks={"right": "mouse"},
                       settings={"deadzone": 0.1, "mouse_speed": 1000, "mouse_accel": 1, "precision_factor": 0.5})
    eng.axis("rx", 1.0)
    eng.tick(0.01)
    assert rec.events[-1] == ("rel", 10, 0)
    eng.axis("rx", 0.05)  # within dead zone
    n = len(rec.events)
    eng.tick(0.01)
    assert len(rec.events) == n
    eng.axis("rx", 0.0)
    eng.axis("ry", 1.0)
    eng.button("rb", True)
    eng.tick(0.01)
    assert rec.events[-1] == ("rel", 0, 5)


def test_fractional_motion_accumulates():
    eng, rec, _ = make({}, sticks={"left": "mouse"}, settings={"deadzone": 0.0, "mouse_speed": 50, "mouse_accel": 1})
    eng.axis("lx", 1.0)
    for _ in range(10):
        eng.tick(0.004)  # 0.2 px per tick
    assert sum(e[1] for e in rec.events if e[0] == "rel") == 2


def test_scroll_stick():
    eng, rec, _ = make({}, sticks={"right": "scroll"}, settings={"deadzone": 0.0, "scroll_speed": 10, "mouse_accel": 1})
    eng.axis("ry", -1.0)
    eng.tick(0.25)
    assert ("wheel", 2) in rec.events


def test_triggers_as_buttons():
    eng, rec, _ = make({"rt": "mouse_left"}, settings={"trigger_threshold": 0.5})
    eng.axis("rt", 0.3)
    assert rec.keys() == []
    eng.axis("rt", 0.7)
    eng.axis("rt", 0.45)  # hysteresis
    eng.axis("rt", 0.1)
    assert rec.keys() == [("key", K.BTN_LEFT, True), ("key", K.BTN_LEFT, False)]


def test_hotkey_hold():
    fired = []
    eng, rec, clock = make({"start": "esc"}, hotkeys=[Hotkey.make(["select", "start"], 1.5, "exit")], specials=fired)
    eng.button("back", True)
    eng.button("start", True)
    eng.tick(0.01)
    clock.t = 1.0
    eng.tick(0.01)
    assert fired == []
    clock.t = 1.6
    eng.tick(0.01)
    eng.tick(0.01)
    assert fired == ["exit"]  # fires once per hold
    eng.button("start", False)
    eng.tick(0.01)
    eng.button("start", True)
    clock.t = 5.0
    eng.tick(0.01)
    clock.t = 7.0
    eng.tick(0.01)
    assert fired == ["exit", "exit"]


def test_engine_without_layout_only_watches_hotkeys():
    fired = []
    rec, clock = Recorder(), Clock()
    eng = Engine(None, rec, [Hotkey.make(["back", "start"], 0.0, "exit")], on_special=fired.append, clock=clock)
    eng.button("back", True)
    eng.button("start", True)
    eng.axis("lx", 1.0)
    eng.tick(0.01)
    assert rec.events == [] and fired == ["exit"]


def test_release_all():
    eng, rec, _ = make({"a": "w", "b": "shift+x"})
    eng.button("a", True)
    eng.button("b", True)
    eng.release_all()
    downs = {e[1] for e in rec.keys() if e[2]}
    ups = {e[1] for e in rec.keys() if not e[2]}
    assert downs == ups


def _device(vendor=0x045E, abs_codes=None, keys=None):
    absinfo = {c: AbsInfo(0, lo, hi) for c, (lo, hi) in (abs_codes or {
        K.ABS_X: (-32768, 32767), K.ABS_Y: (-32768, 32767), K.ABS_RX: (-32768, 32767),
        K.ABS_RY: (-32768, 32767), K.ABS_Z: (0, 255), K.ABS_RZ: (0, 255),
        K.ABS_HAT0X: (-1, 1), K.ABS_HAT0Y: (-1, 1)}).items()}
    return InputDevice("/dev/null", -1, "pad", vendor, 0x028E, keys or {K.BTN_SOUTH, K.BTN_START}, absinfo)


class Spy:
    def __init__(self):
        self.calls = []

    def button(self, n, d):
        self.calls.append(("b", n, d))

    def axis(self, n, v):
        self.calls.append(("a", n, round(v, 2)))


def test_translator_xbox_and_sony_layouts():
    spy = Spy()
    t = Translator(_device(), spy)
    t.feed(K.EV_KEY, K.BTN_NORTH, 1)   # xpad reports X as BTN_X == BTN_NORTH
    t.feed(K.EV_ABS, K.ABS_HAT0X, 1)
    t.feed(K.EV_ABS, K.ABS_Y, -32768)
    t.feed(K.EV_ABS, K.ABS_RZ, 255)
    t.feed(K.EV_KEY, K.BTN_TL2, 1)
    assert spy.calls == [("b", "x", True), ("b", "dpad_left", False), ("b", "dpad_right", True),
                         ("a", "ly", -1.0), ("a", "rt", 1.0), ("a", "lt", 1.0)]
    spy2 = Spy()
    Translator(_device(vendor=0x054C), spy2).feed(K.EV_KEY, K.BTN_NORTH, 1)
    assert spy2.calls == [("b", "y", True)]  # triangle is the top button


def test_translator_generic_hid_pad_uses_z_for_right_stick():
    spy = Spy()
    t = Translator(_device(abs_codes={K.ABS_X: (0, 255), K.ABS_Y: (0, 255), K.ABS_Z: (0, 255), K.ABS_RZ: (0, 255)}), spy)
    t.feed(K.EV_ABS, K.ABS_Z, 255)
    t.feed(K.EV_ABS, K.ABS_X, 0)
    assert spy.calls == [("a", "rx", 1.0), ("a", "lx", -1.0)]


def test_struct_sizes():
    from vistal.controller import evdev
    assert evdev.EVENT_SIZE == struct.calcsize("llHHi")
    assert struct.calcsize("80s4HI") + 4 * 64 * 4 == 1116  # sizeof(struct uinput_user_dev)
    assert evdev.EVIOCGRAB == 0x40044590
    assert evdev.UI_DEV_CREATE == 0x5501
    assert evdev.UI_SET_KEYBIT == 0x40045565

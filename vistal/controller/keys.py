"""Linux input event codes and the action names used in controller layouts."""

from __future__ import annotations

from dataclasses import dataclass

# event types
EV_SYN, EV_KEY, EV_REL, EV_ABS = 0x00, 0x01, 0x02, 0x03
SYN_REPORT = 0
REL_X, REL_Y, REL_HWHEEL, REL_WHEEL = 0x00, 0x01, 0x06, 0x08

# mouse buttons
BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE, BTN_EXTRA = 0x110, 0x111, 0x112, 0x113, 0x114

# gamepad buttons
BTN_SOUTH, BTN_EAST, BTN_C, BTN_NORTH, BTN_WEST, BTN_Z = 0x130, 0x131, 0x132, 0x133, 0x134, 0x135
BTN_TL, BTN_TR, BTN_TL2, BTN_TR2 = 0x136, 0x137, 0x138, 0x139
BTN_SELECT, BTN_START, BTN_MODE, BTN_THUMBL, BTN_THUMBR = 0x13A, 0x13B, 0x13C, 0x13D, 0x13E
BTN_DPAD_UP, BTN_DPAD_DOWN, BTN_DPAD_LEFT, BTN_DPAD_RIGHT = 0x220, 0x221, 0x222, 0x223
BTN_TRIGGER_HAPPY1 = 0x2C0

# absolute axes
ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ = 0x00, 0x01, 0x02, 0x03, 0x04, 0x05
ABS_GAS, ABS_BRAKE = 0x09, 0x0A
ABS_HAT0X, ABS_HAT0Y = 0x10, 0x11

_LETTERS = {c: code for c, code in zip("qwertyuiop", range(16, 26))}
_LETTERS.update({c: code for c, code in zip("asdfghjkl", range(30, 39))})
_LETTERS.update({c: code for c, code in zip("zxcvbnm", range(44, 51))})

KEYS: dict[str, int] = {
    "esc": 1, "escape": 1,
    "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10, "0": 11,
    "minus": 12, "-": 12, "equal": 13, "=": 13, "backspace": 14, "tab": 15,
    "leftbrace": 26, "[": 26, "rightbrace": 27, "]": 27, "enter": 28, "return": 28,
    "ctrl": 29, "leftctrl": 29, "lctrl": 29,
    "semicolon": 39, ";": 39, "apostrophe": 40, "'": 40, "grave": 41, "`": 41, "tilde": 41,
    "shift": 42, "leftshift": 42, "lshift": 42, "backslash": 43, "\\": 43,
    "comma": 51, ",": 51, "dot": 52, "period": 52, ".": 52, "slash": 53, "/": 53,
    "rightshift": 54, "rshift": 54, "kpasterisk": 55, "kp*": 55,
    "alt": 56, "leftalt": 56, "lalt": 56, "space": 57, "capslock": 58,
    "f1": 59, "f2": 60, "f3": 61, "f4": 62, "f5": 63, "f6": 64, "f7": 65, "f8": 66,
    "f9": 67, "f10": 68, "numlock": 69, "scrolllock": 70,
    "kp7": 71, "kp8": 72, "kp9": 73, "kpminus": 74, "kp-": 74, "kp4": 75, "kp5": 76, "kp6": 77,
    "kpplus": 78, "kp+": 78, "kp1": 79, "kp2": 80, "kp3": 81, "kp0": 82, "kpdot": 83,
    "f11": 87, "f12": 88, "kpenter": 96, "rightctrl": 97, "rctrl": 97, "kpslash": 98, "kp/": 98,
    "sysrq": 99, "print": 99, "printscreen": 99, "rightalt": 100, "ralt": 100, "altgr": 100,
    "home": 102, "up": 103, "pageup": 104, "pgup": 104, "left": 105, "right": 106, "end": 107,
    "down": 108, "pagedown": 109, "pgdn": 109, "insert": 110, "ins": 110, "delete": 111, "del": 111,
    "pause": 119, "meta": 125, "leftmeta": 125, "win": 125, "super": 125, "menu": 139, "compose": 127,
}
KEYS.update(_LETTERS)

MOUSE_BUTTONS: dict[str, int] = {
    "mouse_left": BTN_LEFT, "mouse1": BTN_LEFT, "lmb": BTN_LEFT,
    "mouse_right": BTN_RIGHT, "mouse2": BTN_RIGHT, "rmb": BTN_RIGHT,
    "mouse_middle": BTN_MIDDLE, "mouse3": BTN_MIDDLE, "mmb": BTN_MIDDLE,
    "mouse_back": BTN_SIDE, "mouse4": BTN_SIDE,
    "mouse_forward": BTN_EXTRA, "mouse5": BTN_EXTRA,
}

WHEEL = {"wheel_up": 1, "wheel_down": -1, "scroll_up": 1, "scroll_down": -1}

#: every key code the virtual device must advertise
ALL_OUTPUT_KEYS = sorted(set(KEYS.values()) | set(MOUSE_BUTTONS.values()))

#: logical gamepad inputs a layout can bind
BUTTON_INPUTS = [
    "a", "b", "x", "y", "lb", "rb", "lt", "rt", "back", "start", "guide", "ls", "rs",
    "dpad_up", "dpad_down", "dpad_left", "dpad_right",
    "ls_up", "ls_down", "ls_left", "ls_right", "rs_up", "rs_down", "rs_left", "rs_right",
    "paddle1", "paddle2", "paddle3", "paddle4",
]
ALIASES = {
    "select": "back", "view": "back", "share": "back", "minus": "back",
    "menu": "start", "options": "start", "plus": "start",
    "home": "guide", "ps": "guide", "mode": "guide",
    "l1": "lb", "r1": "rb", "l2": "lt", "r2": "rt", "l3": "ls", "r3": "rs",
    "up": "dpad_up", "down": "dpad_down", "left": "dpad_left", "right": "dpad_right",
    "cross": "a", "circle": "b", "square": "x", "triangle": "y",
    "l4": "paddle1", "r4": "paddle2", "l5": "paddle3", "r5": "paddle4",
}

SPECIAL = {"none", "precision", "exit", "disc_next", "disc_prev"}


class ActionError(ValueError):
    pass


@dataclass(frozen=True)
class Action:
    """What a bound input does: press keys/buttons, scroll, or a special."""

    keys: tuple[int, ...] = ()
    wheel: int = 0
    layer: str | None = None
    special: str | None = None
    text: str = ""

    @property
    def is_none(self) -> bool:
        return not self.keys and not self.wheel and not self.layer and not self.special


def normalize_input(name: str) -> str:
    n = name.strip().lower()
    n = ALIASES.get(n, n)
    if n not in BUTTON_INPUTS:
        raise ActionError(f"unknown controller input '{name}'")
    return n


def parse_action(spec: str) -> Action:
    """Parse "w", "ctrl+s", "mouse_left", "wheel_up", "layer:alt", "exit"..."""
    text = spec.strip()
    s = text.lower()
    if s in ("", "none"):
        return Action(text=text)
    if s.startswith("layer:"):
        name = s[6:].strip()
        if not name:
            raise ActionError("layer name missing")
        return Action(layer=name, text=text)
    if s in SPECIAL:
        return Action(special=s, text=text)
    if s in WHEEL:
        return Action(wheel=WHEEL[s], text=text)
    parts = [p.strip() for p in (s.split("+") if s not in ("+", "kp+") else [s]) if p.strip()]
    if s.endswith("++"):  # e.g. "shift++" -> shift and plus is meaningless; reject
        raise ActionError(f"cannot parse action '{spec}'")
    codes = []
    for p in parts:
        if p.startswith("key_"):
            p = p[4:]
        if p in KEYS:
            codes.append(KEYS[p])
        elif p in MOUSE_BUTTONS:
            codes.append(MOUSE_BUTTONS[p])
        else:
            raise ActionError(f"unknown key '{p}' in action '{spec}'")
    return Action(keys=tuple(codes), text=text)

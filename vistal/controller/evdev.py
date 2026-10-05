"""Thin ctypes-free bindings to Linux evdev (input) and uinput (output)."""

from __future__ import annotations

import errno
import fcntl
import glob
import os
import struct
from collections import Counter
from dataclasses import dataclass, field

from . import keys as K

_IOC_NONE, _IOC_WRITE, _IOC_READ = 0, 1, 2


def _IOC(direction: int, typ: str, nr: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord(typ) << 8) | nr


EVENT_FORMAT = "llHHi"
EVENT_SIZE = struct.calcsize(EVENT_FORMAT)
ABSINFO_FORMAT = "6i"

EVIOCGID = _IOC(_IOC_READ, "E", 0x02, 8)
EVIOCGRAB = _IOC(_IOC_WRITE, "E", 0x90, 4)


def EVIOCGNAME(length: int) -> int:
    return _IOC(_IOC_READ, "E", 0x06, length)


def EVIOCGBIT(ev: int, length: int) -> int:
    return _IOC(_IOC_READ, "E", 0x20 + ev, length)


def EVIOCGABS(axis: int) -> int:
    return _IOC(_IOC_READ, "E", 0x40 + axis, struct.calcsize(ABSINFO_FORMAT))


UI_DEV_CREATE = _IOC(_IOC_NONE, "U", 1, 0)
UI_DEV_DESTROY = _IOC(_IOC_NONE, "U", 2, 0)
UI_SET_EVBIT = _IOC(_IOC_WRITE, "U", 100, 4)
UI_SET_KEYBIT = _IOC(_IOC_WRITE, "U", 101, 4)
UI_SET_RELBIT = _IOC(_IOC_WRITE, "U", 102, 4)

VIRTUAL_NAME = "Vistal Virtual Input"
SONY_VENDOR = 0x054C


def _bits(fd: int, ev: int, maxcode: int) -> set[int]:
    buf = bytearray((maxcode + 8) // 8)
    try:
        fcntl.ioctl(fd, EVIOCGBIT(ev, len(buf)), buf, True)
    except OSError:
        return set()
    return {i for i in range(maxcode) if buf[i // 8] & (1 << (i % 8))}


@dataclass
class AbsInfo:
    value: int
    minimum: int
    maximum: int
    fuzz: int = 0
    flat: int = 0
    resolution: int = 0

    def stick(self, v: int) -> float:
        span = (self.maximum - self.minimum) / 2.0
        if span <= 0:
            return 0.0
        center = (self.maximum + self.minimum) / 2.0
        return max(-1.0, min(1.0, (v - center) / span))

    def trigger(self, v: int) -> float:
        span = self.maximum - self.minimum
        if span <= 0:
            return 0.0
        return max(0.0, min(1.0, (v - self.minimum) / span))


@dataclass
class InputDevice:
    path: str
    fd: int
    name: str
    vendor: int
    product: int
    key_codes: set[int]
    abs_info: dict[int, AbsInfo] = field(default_factory=dict)
    grabbed: bool = False

    @property
    def is_gamepad(self) -> bool:
        return K.BTN_SOUTH in self.key_codes or K.BTN_TL in self.key_codes and K.BTN_START in self.key_codes

    def grab(self, on: bool = True) -> bool:
        try:
            fcntl.ioctl(self.fd, EVIOCGRAB, 1 if on else 0)
            self.grabbed = on
            return True
        except OSError:
            return False

    def read_events(self) -> list[tuple[int, int, int]]:
        """Non-blocking read of pending (type, code, value) events."""
        out = []
        while True:
            try:
                data = os.read(self.fd, EVENT_SIZE * 64)
            except BlockingIOError:
                break
            except OSError as exc:
                if exc.errno in (errno.ENODEV, errno.EIO):
                    raise
                break
            if not data:
                break
            for i in range(0, len(data) - EVENT_SIZE + 1, EVENT_SIZE):
                _, _, typ, code, val = struct.unpack_from(EVENT_FORMAT, data, i)
                out.append((typ, code, val))
            if len(data) < EVENT_SIZE * 64:
                break
        return out

    def close(self) -> None:
        if self.grabbed:
            self.grab(False)
        try:
            os.close(self.fd)
        except OSError:
            pass


def open_device(path: str) -> InputDevice | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        name_buf = bytearray(256)
        fcntl.ioctl(fd, EVIOCGNAME(len(name_buf)), name_buf, True)
        name = name_buf.split(b"\0", 1)[0].decode("utf-8", "replace")
        id_buf = bytearray(8)
        fcntl.ioctl(fd, EVIOCGID, id_buf, True)
        _, vendor, product, _ = struct.unpack("4H", id_buf)
    except OSError:
        os.close(fd)
        return None
    keys = _bits(fd, K.EV_KEY, 0x300)
    absinfo: dict[int, AbsInfo] = {}
    for axis in _bits(fd, K.EV_ABS, 0x40):
        buf = bytearray(struct.calcsize(ABSINFO_FORMAT))
        try:
            fcntl.ioctl(fd, EVIOCGABS(axis), buf, True)
            absinfo[axis] = AbsInfo(*struct.unpack(ABSINFO_FORMAT, buf))
        except OSError:
            pass
    return InputDevice(path, fd, name, vendor, product, keys, absinfo)


def list_gamepads(name_filter: str | None = None) -> list[InputDevice]:
    found = []
    for path in sorted(glob.glob("/dev/input/event*"), key=lambda p: int(p.rsplit("event", 1)[1] or 0)):
        dev = open_device(path)
        if dev is None:
            continue
        keep = dev.is_gamepad and dev.name != VIRTUAL_NAME
        if keep and name_filter and name_filter.lower() not in dev.name.lower():
            keep = False
        if keep:
            found.append(dev)
        else:
            dev.close()
    return found


class Translator:
    """Turns raw evdev events of one device into logical engine calls."""

    def __init__(self, dev: InputDevice, engine, face_layout: str = "auto"):
        self.dev = dev
        self.engine = engine
        if face_layout == "auto":
            face_layout = "standard" if dev.vendor == SONY_VENDOR else "xbox"
        north_west = {K.BTN_NORTH: "x", K.BTN_WEST: "y"} if face_layout == "xbox" else \
            {K.BTN_NORTH: "y", K.BTN_WEST: "x"}
        self.buttons = {
            K.BTN_SOUTH: "a", K.BTN_EAST: "b", **north_west,
            K.BTN_TL: "lb", K.BTN_TR: "rb", K.BTN_SELECT: "back", K.BTN_START: "start",
            K.BTN_MODE: "guide", K.BTN_THUMBL: "ls", K.BTN_THUMBR: "rs",
            K.BTN_DPAD_UP: "dpad_up", K.BTN_DPAD_DOWN: "dpad_down",
            K.BTN_DPAD_LEFT: "dpad_left", K.BTN_DPAD_RIGHT: "dpad_right",
        }
        has_hat = K.ABS_HAT0X in dev.abs_info
        happy = ["dpad_left", "dpad_right", "dpad_up", "dpad_down"] if not has_hat and \
            K.BTN_DPAD_UP not in dev.key_codes else ["paddle1", "paddle2", "paddle3", "paddle4"]
        for i, name in enumerate(happy):
            self.buttons[K.BTN_TRIGGER_HAPPY1 + i] = name
        has_right = K.ABS_RX in dev.abs_info and K.ABS_RY in dev.abs_info
        if has_right:
            self.axes = {K.ABS_X: "lx", K.ABS_Y: "ly", K.ABS_RX: "rx", K.ABS_RY: "ry",
                         K.ABS_Z: "lt", K.ABS_RZ: "rt", K.ABS_BRAKE: "lt", K.ABS_GAS: "rt"}
        else:  # generic HID pads put the right stick on Z/RZ
            self.axes = {K.ABS_X: "lx", K.ABS_Y: "ly", K.ABS_Z: "rx", K.ABS_RZ: "ry",
                         K.ABS_BRAKE: "lt", K.ABS_GAS: "rt"}
        self._hat = {"x": 0, "y": 0}

    def feed(self, typ: int, code: int, value: int) -> None:
        eng = self.engine
        if typ == K.EV_KEY:
            if code == K.BTN_TL2:
                eng.axis("lt", 1.0 if value else 0.0)
            elif code == K.BTN_TR2:
                eng.axis("rt", 1.0 if value else 0.0)
            elif code in self.buttons:
                eng.button(self.buttons[code], value != 0)
        elif typ == K.EV_ABS:
            if code in (K.ABS_HAT0X, K.ABS_HAT0Y):
                axis = "x" if code == K.ABS_HAT0X else "y"
                neg, pos = ("dpad_left", "dpad_right") if axis == "x" else ("dpad_up", "dpad_down")
                self._hat[axis] = value
                eng.button(neg, value < 0)
                eng.button(pos, value > 0)
                return
            name = self.axes.get(code)
            info = self.dev.abs_info.get(code)
            if not name or not info:
                return
            if name in ("lt", "rt"):
                eng.axis(name, info.trigger(value))
            else:
                eng.axis(name, info.stick(value))


class UInputSink:
    """A virtual keyboard+mouse. Key presses are reference counted so several
    controllers (or two inputs bound to the same key) never cut each other off."""

    def __init__(self, name: str = VIRTUAL_NAME):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        self._refs: Counter[int] = Counter()
        try:
            for ev in (K.EV_KEY, K.EV_REL, K.EV_SYN):
                fcntl.ioctl(self.fd, UI_SET_EVBIT, ev)
            for code in K.ALL_OUTPUT_KEYS:
                fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)
            for rel in (K.REL_X, K.REL_Y, K.REL_WHEEL, K.REL_HWHEEL):
                fcntl.ioctl(self.fd, UI_SET_RELBIT, rel)
            # legacy struct uinput_user_dev: works on every kernel
            dev = struct.pack("80s4HI", name.encode()[:79], 0x06, 0x1209, 0x5653, 1, 0)
            dev += b"\0" * (4 * 64 * 4)
            os.write(self.fd, dev)
            fcntl.ioctl(self.fd, UI_DEV_CREATE)
        except OSError:
            os.close(self.fd)
            raise

    def _emit(self, typ: int, code: int, value: int) -> None:
        try:
            os.write(self.fd, struct.pack(EVENT_FORMAT, 0, 0, typ, code, value))
        except BlockingIOError:
            pass

    def key(self, code: int, down: bool) -> None:
        if down:
            self._refs[code] += 1
            if self._refs[code] == 1:
                self._emit(K.EV_KEY, code, 1)
        elif self._refs[code] > 0:
            self._refs[code] -= 1
            if self._refs[code] == 0:
                del self._refs[code]
                self._emit(K.EV_KEY, code, 0)

    def rel(self, dx: int, dy: int) -> None:
        if dx:
            self._emit(K.EV_REL, K.REL_X, dx)
        if dy:
            self._emit(K.EV_REL, K.REL_Y, dy)

    def wheel(self, notches: int) -> None:
        self._emit(K.EV_REL, K.REL_WHEEL, notches)

    def sync(self) -> None:
        self._emit(K.EV_SYN, K.SYN_REPORT, 0)

    def close(self) -> None:
        for code in list(self._refs):
            self._emit(K.EV_KEY, code, 0)
        self._refs.clear()
        self.sync()
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        except OSError:
            pass
        os.close(self.fd)


class NullSink:
    def key(self, code: int, down: bool) -> None: ...
    def rel(self, dx: int, dy: int) -> None: ...
    def wheel(self, notches: int) -> None: ...
    def sync(self) -> None: ...
    def close(self) -> None: ...


def uinput_status() -> tuple[bool, str]:
    if not os.path.exists("/dev/uinput"):
        return False, "/dev/uinput does not exist (load the 'uinput' kernel module)"
    if not os.access("/dev/uinput", os.W_OK):
        return False, ("/dev/uinput is not writable; install Steam's udev rules "
                       "(package 'steam-devices') or add a uaccess rule")
    return True, "writable"

"""Background thread that maps every connected gamepad while a game runs.

Modes:
  mapped  - translate the pad into keyboard/mouse with a layout (and grab the
            pad so the game does not also see it)
  native  - let the game read the pad itself; only watch for hotkeys
"""

from __future__ import annotations

import errno
import glob
import select
import threading
import time
from typing import Callable, Sequence

from ..log import LOG
from .engine import Engine, Hotkey
from .evdev import NullSink, Translator, UInputSink, list_gamepads, open_device, VIRTUAL_NAME
from .layout import Layout


class Mapper:
    def __init__(self, layout: Layout | None, hotkeys: Sequence[Hotkey] = (),
                 on_special: Callable[[str], None] | None = None, grab: bool = True,
                 device_filter: str | None = None, face_layout: str = "auto", rate: float = 250.0,
                 engine_factory: Callable[..., Engine] | None = None):
        self.layout = layout
        self.hotkeys = list(hotkeys)
        self.on_special = on_special or (lambda name: None)
        self.grab = grab and layout is not None
        self.device_filter = device_filter
        self.face_layout = face_layout
        self.interval = 1.0 / rate
        self.engine_factory = engine_factory or Engine
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._devices: dict[int, tuple] = {}  # fd -> (device, translator, engine)
        self._known_paths: set[str] = set()
        self.sink = None

    # -- lifecycle --------------------------------------------------------

    def start(self) -> bool:
        if self.layout is not None:
            try:
                self.sink = UInputSink()
            except OSError as exc:
                LOG.warning("Controller mapping disabled: cannot open /dev/uinput (%s). "
                            "Use Steam Input instead, or run 'vistal doctor'.", exc)
                self.layout = None
                self.grab = False
        if self.sink is None:
            self.sink = NullSink()
        if self.layout is None and not self.hotkeys and self.engine_factory is Engine:
            return False
        self._scan()
        self._thread = threading.Thread(target=self._loop, name="vistal-mapper", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        for dev, _, eng in list(self._devices.values()):
            eng.release_all()
            dev.close()
        self._devices.clear()
        if self.sink:
            self.sink.close()

    # -- internals ----------------------------------------------------------

    def _special(self, name: str) -> None:
        LOG.info("Controller hotkey: %s", name)
        try:
            self.on_special(name)
        except Exception as exc:  # never let a callback kill the mapper
            LOG.error("hotkey action failed: %s", exc)

    def _add(self, dev) -> None:
        eng = self.engine_factory(self.layout, self.sink, [Hotkey(h.inputs, h.hold, h.action) for h in self.hotkeys],
                     on_special=self._special)
        tr = Translator(dev, eng, self.face_layout)
        if self.grab and not dev.grab(True):
            LOG.debug("could not grab %s", dev.name)
        self._devices[dev.fd] = (dev, tr, eng)
        self._known_paths.add(dev.path)
        LOG.info("Controller connected: %s%s", dev.name, " (mapped)" if self.layout else "")

    def _scan(self) -> None:
        if not self._devices and not self._known_paths:
            for dev in list_gamepads(self.device_filter):
                self._add(dev)
            return
        for path in glob.glob("/dev/input/event*"):
            if path in self._known_paths:
                continue
            self._known_paths.add(path)
            dev = open_device(path)
            if dev is None:
                self._known_paths.discard(path)  # maybe permissions not ready yet
                continue
            wanted = dev.is_gamepad and dev.name != VIRTUAL_NAME and (
                not self.device_filter or self.device_filter.lower() in dev.name.lower())
            if wanted:
                self._add(dev)
            else:
                dev.close()

    def _drop(self, fd: int) -> None:
        dev, _, eng = self._devices.pop(fd)
        eng.release_all()
        self._known_paths.discard(dev.path)
        dev.close()
        LOG.info("Controller disconnected: %s", dev.name)

    def _loop(self) -> None:
        last = time.monotonic()
        next_scan = last + 2.0
        while not self._stop.is_set():
            fds = list(self._devices)
            try:
                readable = select.select(fds, [], [], self.interval)[0] if fds else []
                if not fds:
                    self._stop.wait(self.interval)
            except (OSError, ValueError):
                readable = []
            for fd in readable:
                entry = self._devices.get(fd)
                if not entry:
                    continue
                try:
                    events = entry[0].read_events()
                except OSError as exc:
                    if exc.errno in (errno.ENODEV, errno.EIO):
                        self._drop(fd)
                    continue
                for typ, code, val in events:
                    entry[1].feed(typ, code, val)
            now = time.monotonic()
            dt = now - last
            last = now
            for _, _, eng in list(self._devices.values()):
                eng.tick(dt)
            if now >= next_scan:
                next_scan = now + 2.0
                self._scan()

"""Device-independent mapping engine: logical gamepad state in, keyboard and
mouse events out. Kept free of any I/O so it can be unit tested."""

from __future__ import annotations

import math
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Protocol, Sequence

from .keys import Action, normalize_input
from .layout import Layout

NONE = Action()


class Sink(Protocol):
    def key(self, code: int, down: bool) -> None: ...
    def rel(self, dx: int, dy: int) -> None: ...
    def wheel(self, notches: int) -> None: ...
    def sync(self) -> None: ...


@dataclass
class Hotkey:
    inputs: tuple[str, ...]
    hold: float
    action: str  # special action name, e.g. "exit"
    _since: float | None = field(default=None, repr=False)
    _fired: bool = field(default=False, repr=False)

    @classmethod
    def make(cls, inputs: Sequence[str], hold: float, action: str) -> "Hotkey":
        return cls(tuple(normalize_input(i) for i in inputs), float(hold), action)


class Engine:
    def __init__(self, layout: Layout | None, sink: Sink, hotkeys: Sequence[Hotkey] = (),
                 on_special: Callable[[str], None] | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.layout = layout
        self.sink = sink
        self.hotkeys = list(hotkeys)
        self.on_special = on_special or (lambda name: None)
        self.clock = clock
        self.axes = {"lx": 0.0, "ly": 0.0, "rx": 0.0, "ry": 0.0, "lt": 0.0, "rt": 0.0}
        self.held: set[str] = set()
        self._active: dict[str, Action] = {}
        self._refs: Counter[int] = Counter()
        self._layers: list[str] = []
        self._precision = 0
        self._mouse_frac = [0.0, 0.0]
        self._wheel_frac = 0.0
        self._dirty = False

    # -- configuration --------------------------------------------------

    def _setting(self, key: str) -> float:
        return self.layout.settings[key] if self.layout else 0.0

    def _lookup(self, name: str) -> Action:
        if not self.layout:
            return NONE
        for layer in reversed(self._layers):
            binds = self.layout.layers.get(layer, {})
            if name in binds:
                return binds[name]
        return self.layout.bindings.get(name, NONE)

    # -- inputs ---------------------------------------------------------

    def button(self, name: str, down: bool) -> None:
        if down:
            if name in self.held:
                return
            self.held.add(name)
            action = self._lookup(name)
            self._active[name] = action
            self._activate(action)
        else:
            if name not in self.held:
                return
            self.held.discard(name)
            action = self._active.pop(name, NONE)
            self._deactivate(action)
        self._flush()

    def axis(self, name: str, value: float) -> None:
        self.axes[name] = value
        if name in ("lt", "rt"):
            thr = self._setting("trigger_threshold") or 0.35
            on = name in self.held
            if not on and value >= thr:
                self.button(name, True)
            elif on and value < thr * 0.8:
                self.button(name, False)
            return
        side = "left" if name in ("lx", "ly") else "right"
        # Only sticks in "keys" mode produce the digital ls_*/rs_* inputs;
        # mouse/scroll sticks are consumed continuously by tick().
        if self.layout and self.layout.sticks.get(side) == "keys":
            self._stick_keys(side)

    def _stick_keys(self, side: str) -> None:
        pre = "ls" if side == "left" else "rs"
        x = self.axes["lx" if side == "left" else "rx"]
        y = self.axes["ly" if side == "left" else "ry"]
        thr = self._setting("stick_threshold") or 0.5
        for direction, val in (("up", -y), ("down", y), ("left", -x), ("right", x)):
            name = f"{pre}_{direction}"
            on = name in self.held
            if not on and val >= thr:
                self.button(name, True)
            elif on and val < thr * 0.8:
                self.button(name, False)

    # -- actions --------------------------------------------------------

    def _activate(self, a: Action) -> None:
        for code in a.keys:
            self._refs[code] += 1
            if self._refs[code] == 1:
                self.sink.key(code, True)
                self._dirty = True
        if a.wheel:
            self.sink.wheel(a.wheel)
            self._dirty = True
        if a.layer:
            self._layers.append(a.layer)
        if a.special == "precision":
            self._precision += 1
        elif a.special:
            self.on_special(a.special)

    def _deactivate(self, a: Action) -> None:
        for code in reversed(a.keys):
            if self._refs[code] <= 0:
                continue
            self._refs[code] -= 1
            if self._refs[code] == 0:
                del self._refs[code]
                self.sink.key(code, False)
                self._dirty = True
        if a.layer and a.layer in self._layers:
            idx = len(self._layers) - 1 - self._layers[::-1].index(a.layer)
            self._layers.pop(idx)
        if a.special == "precision":
            self._precision = max(0, self._precision - 1)

    def release_all(self) -> None:
        for name in list(self.held):
            self.button(name, False)
        for code in list(self._refs):
            self.sink.key(code, False)
        self._refs.clear()
        self._layers.clear()
        self._flush()

    def _flush(self) -> None:
        if self._dirty:
            self.sink.sync()
            self._dirty = False

    # -- time based output ------------------------------------------------

    def _curve(self, x: float, y: float) -> tuple[float, float]:
        mag = math.hypot(x, y)
        dz = self._setting("deadzone")
        if mag <= dz or mag == 0.0:
            return 0.0, 0.0
        scaled = min(1.0, (mag - dz) / (1.0 - dz))
        shaped = scaled ** max(0.1, self._setting("mouse_accel"))
        return x / mag * shaped, y / mag * shaped

    def tick(self, dt: float) -> None:
        now = self.clock()
        for hk in self.hotkeys:
            if all(i in self.held for i in hk.inputs):
                if hk._since is None:
                    hk._since = now
                if not hk._fired and now - hk._since >= hk.hold:
                    hk._fired = True
                    self.on_special(hk.action)
            else:
                hk._since = None
                hk._fired = False
        if not self.layout or dt <= 0:
            return
        factor = self._setting("precision_factor") if self._precision else 1.0
        mx = my = 0.0
        scroll = 0.0
        for side, ax, ay in (("left", "lx", "ly"), ("right", "rx", "ry")):
            mode = self.layout.sticks.get(side)
            if mode == "mouse":
                cx, cy = self._curve(self.axes[ax], self.axes[ay])
                speed = self._setting("mouse_speed") * factor
                mx += cx * speed * dt
                my += cy * speed * dt
            elif mode == "scroll":
                _, cy = self._curve(0.0, self.axes[ay])
                scroll += -cy * self._setting("scroll_speed") * dt
        if mx or my:
            self._mouse_frac[0] += mx
            self._mouse_frac[1] += my
            ix, iy = int(self._mouse_frac[0]), int(self._mouse_frac[1])
            if ix or iy:
                self._mouse_frac[0] -= ix
                self._mouse_frac[1] -= iy
                self.sink.rel(ix, iy)
                self._dirty = True
        else:
            self._mouse_frac = [0.0, 0.0]
        if scroll:
            self._wheel_frac += scroll
            n = int(self._wheel_frac)
            if n:
                self._wheel_frac -= n
                self.sink.wheel(n)
                self._dirty = True
        else:
            self._wheel_frac = 0.0
        self._flush()

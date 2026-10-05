"""Controller layouts: TOML files that bind gamepad inputs to keys and mouse.

Example (see vistal/data/controller/*.toml for complete ones):

    name = "My layout"

    [settings]
    deadzone = 0.15        # stick dead zone (0..1)
    mouse_speed = 1000     # cursor pixels per second at full deflection
    mouse_accel = 1.8      # response curve exponent (1 = linear)

    [sticks]
    left = "keys"          # keys | mouse | scroll | none
    right = "mouse"

    [bindings]
    a = "mouse_left"
    b = "mouse_right"
    ls_up = "w"
    lb = "layer:alt"       # hold LB to use [layers.alt] bindings

    [layers.alt]
    a = "ctrl+1"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import paths, tomlutil
from .keys import Action, ActionError, normalize_input, parse_action

STICK_MODES = {"keys", "mouse", "scroll", "none"}

DEFAULT_SETTINGS = {
    "deadzone": 0.15,
    "trigger_threshold": 0.35,
    "stick_threshold": 0.5,
    "mouse_speed": 1000.0,
    "mouse_accel": 1.8,
    "scroll_speed": 12.0,
    "precision_factor": 0.35,
}


class LayoutError(Exception):
    pass


@dataclass
class Layout:
    name: str
    description: str = ""
    settings: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_SETTINGS))
    sticks: dict[str, str] = field(default_factory=lambda: {"left": "none", "right": "none"})
    bindings: dict[str, Action] = field(default_factory=dict)
    layers: dict[str, dict[str, Action]] = field(default_factory=dict)
    source: str = ""

    def describe(self) -> list[str]:
        lines = [f"{self.name}: {self.description}".rstrip(": ")]
        lines.append(f"  left stick: {self.sticks['left']}, right stick: {self.sticks['right']}")
        for k, a in self.bindings.items():
            lines.append(f"  {k:<11} -> {a.text}")
        for lname, binds in self.layers.items():
            lines.append(f"  [layer {lname}]")
            for k, a in binds.items():
                lines.append(f"    {k:<9} -> {a.text}")
        return lines


def _bindings(table: dict[str, Any], where: str) -> dict[str, Action]:
    out: dict[str, Action] = {}
    for key, val in table.items():
        if isinstance(val, dict):
            continue
        try:
            out[normalize_input(key)] = parse_action(str(val))
        except ActionError as exc:
            raise LayoutError(f"{where}: {exc}") from exc
    return out


def from_dict(data: dict[str, Any], source: str = "<layout>") -> Layout:
    settings = dict(DEFAULT_SETTINGS)
    for k, v in (data.get("settings") or {}).items():
        if k not in DEFAULT_SETTINGS:
            raise LayoutError(f"{source}: unknown setting '{k}'")
        try:
            settings[k] = float(v)
        except (TypeError, ValueError) as exc:
            raise LayoutError(f"{source}: setting '{k}' must be a number") from exc
    sticks = {"left": "none", "right": "none"}
    for side, mode in (data.get("sticks") or {}).items():
        if side not in sticks or str(mode) not in STICK_MODES:
            raise LayoutError(f"{source}: bad stick entry {side} = {mode!r}")
        sticks[side] = str(mode)
    bindings = _bindings(data.get("bindings") or {}, source)
    layers = {}
    for lname, table in (data.get("layers") or {}).items():
        if not isinstance(table, dict):
            raise LayoutError(f"{source}: [layers.{lname}] must be a table")
        layers[lname] = _bindings(table, f"{source} [layers.{lname}]")
    for act in list(bindings.values()) + [a for t in layers.values() for a in t.values()]:
        if act.layer and act.layer not in layers:
            raise LayoutError(f"{source}: binding refers to undefined layer '{act.layer}'")
    return Layout(
        name=str(data.get("name", Path(source).stem)),
        description=str(data.get("description", "")),
        settings=settings,
        sticks=sticks,
        bindings=bindings,
        layers=layers,
        source=source,
    )


def layout_dirs() -> list[Path]:
    return [paths.user_layouts_dir(), paths.DATA_DIR / "controller"]


def find(name: str) -> Path | None:
    p = Path(name).expanduser()
    if p.suffix == ".toml" and p.exists():
        return p
    for d in layout_dirs():
        cand = d / f"{name}.toml"
        if cand.exists():
            return cand
    return None


def load(name: str) -> Layout:
    path = find(name)
    if path is None:
        raise LayoutError(f"controller layout '{name}' not found (looked in "
                          + ", ".join(str(d) for d in layout_dirs()) + ")")
    try:
        data = tomlutil.load(path)
    except tomlutil.ConfigError as exc:
        raise LayoutError(str(exc)) from exc
    return from_dict(data, str(path))


def available() -> dict[str, Path]:
    out: dict[str, Path] = {}
    for d in reversed(layout_dirs()):
        if d.is_dir():
            for f in sorted(d.glob("*.toml")):
                out[f.stem] = f
    return out

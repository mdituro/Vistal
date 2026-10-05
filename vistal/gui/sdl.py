"""Minimal ctypes binding to SDL2: a window showing a cairo-drawn frame,
plus keyboard, mouse/touch and game controller events."""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import struct
from ctypes import c_char_p, c_int, c_uint32, c_void_p
from dataclasses import dataclass

INIT_VIDEO = 0x20
INIT_GAMECONTROLLER = 0x2000
INIT_EVENTS = 0x4000
WINDOWPOS_CENTERED = 0x2FFF0000
WINDOW_FULLSCREEN_DESKTOP = 0x1001
WINDOW_RESIZABLE = 0x20
WINDOW_ALLOW_HIGHDPI = 0x2000
WINDOW_HIDDEN = 0x08
RENDERER_ACCELERATED = 0x02
RENDERER_PRESENTVSYNC = 0x04
PIXELFORMAT_ARGB8888 = 0x16362004
TEXTUREACCESS_STREAMING = 1

QUIT = 0x100
WINDOWEVENT = 0x200
KEYDOWN, KEYUP, TEXTINPUT = 0x300, 0x301, 0x303
MOUSEMOTION, MOUSEBUTTONDOWN, MOUSEBUTTONUP, MOUSEWHEEL = 0x400, 0x401, 0x402, 0x403
CONTROLLERAXISMOTION, CONTROLLERBUTTONDOWN, CONTROLLERBUTTONUP = 0x650, 0x651, 0x652
CONTROLLERDEVICEADDED, CONTROLLERDEVICEREMOVED = 0x653, 0x654

# SDL_GameControllerButton
BUTTONS = {0: "a", 1: "b", 2: "x", 3: "y", 4: "back", 5: "guide", 6: "start", 7: "ls", 8: "rs",
           9: "lb", 10: "rb", 11: "up", 12: "down", 13: "left", 14: "right"}
AXES = {0: "lx", 1: "ly", 2: "rx", 3: "ry", 4: "lt", 5: "rt"}

_K = 1 << 30
KEYS = {13: "enter", 27: "escape", 8: "backspace", 9: "tab", 32: "space", 127: "delete",
        _K | 0x4F: "right", _K | 0x50: "left", _K | 0x51: "down", _K | 0x52: "up",
        _K | 0x4A: "home", _K | 0x4D: "end", _K | 0x4B: "pageup", _K | 0x4E: "pagedown",
        _K | 0x3A: "f1", _K | 0x3B: "f2", _K | 0x3E: "f5", _K | 0x44: "f11", _K | 0x58: "enter",
        _K | 0x65: "menu"}


class SDLUnavailable(RuntimeError):
    pass


@dataclass
class Event:
    kind: str
    key: str = ""
    text: str = ""
    x: int = 0
    y: int = 0
    button: int | str = 0
    value: float = 0.0
    clicks: int = 0
    mod: int = 0


_lib = None


def lib():
    global _lib
    if _lib is not None:
        return _lib
    name = os.environ.get("VISTAL_LIBSDL2") or ctypes.util.find_library("SDL2-2.0") or "libSDL2-2.0.so.0"
    try:
        L = ctypes.CDLL(name)
    except OSError as exc:
        raise SDLUnavailable(f"SDL2 library not found ({exc})") from exc
    I, P, S, U = c_int, c_void_p, c_char_p, c_uint32
    sig = {
        "SDL_Init": (I, [U]), "SDL_Quit": (None, []), "SDL_GetError": (S, []),
        "SDL_SetHint": (I, [S, S]),
        "SDL_CreateWindow": (P, [S, I, I, I, I, U]), "SDL_DestroyWindow": (None, [P]),
        "SDL_ShowWindow": (None, [P]), "SDL_HideWindow": (None, [P]), "SDL_RaiseWindow": (None, [P]),
        "SDL_SetWindowFullscreen": (I, [P, U]),
        "SDL_GetWindowSize": (None, [P, ctypes.POINTER(I), ctypes.POINTER(I)]),
        "SDL_CreateRenderer": (P, [P, I, U]), "SDL_DestroyRenderer": (None, [P]),
        "SDL_GetRendererOutputSize": (I, [P, ctypes.POINTER(I), ctypes.POINTER(I)]),
        "SDL_CreateTexture": (P, [P, U, I, I, I]), "SDL_DestroyTexture": (None, [P]),
        "SDL_UpdateTexture": (I, [P, P, P, I]),
        "SDL_RenderClear": (I, [P]), "SDL_RenderCopy": (I, [P, P, P, P]), "SDL_RenderPresent": (None, [P]),
        "SDL_PollEvent": (I, [P]), "SDL_WaitEventTimeout": (I, [P, I]),
        "SDL_IsGameController": (I, [I]), "SDL_GameControllerOpen": (P, [I]),
        "SDL_NumJoysticks": (I, []),
        "SDL_StartTextInput": (None, []), "SDL_StopTextInput": (None, []),
        "SDL_GetTicks": (U, []),
    }
    for fname, (res, args) in sig.items():
        fn = getattr(L, fname)
        fn.restype = res
        fn.argtypes = args
    _lib = L
    return L


class Window:
    def __init__(self, title: str, width: int, height: int, fullscreen: bool = False):
        L = lib()
        L.SDL_SetHint(b"SDL_VIDEO_X11_NET_WM_BYPASS_COMPOSITOR", b"0")
        if L.SDL_Init(INIT_VIDEO | INIT_GAMECONTROLLER | INIT_EVENTS) != 0:
            raise SDLUnavailable(L.SDL_GetError().decode(errors="replace"))
        flags = WINDOW_RESIZABLE | WINDOW_ALLOW_HIGHDPI | (WINDOW_FULLSCREEN_DESKTOP if fullscreen else 0)
        self.win = L.SDL_CreateWindow(title.encode(), WINDOWPOS_CENTERED, WINDOWPOS_CENTERED, width, height, flags)
        if not self.win:
            raise SDLUnavailable(L.SDL_GetError().decode(errors="replace"))
        self.ren = L.SDL_CreateRenderer(self.win, -1, RENDERER_ACCELERATED | RENDERER_PRESENTVSYNC) or \
            L.SDL_CreateRenderer(self.win, -1, 0)
        if not self.ren:
            raise SDLUnavailable(L.SDL_GetError().decode(errors="replace"))
        self.tex = None
        self.tex_size = (0, 0)
        self._ev = ctypes.create_string_buffer(64)
        self.controllers = []
        for i in range(L.SDL_NumJoysticks()):
            self._open_controller(i)

    def _open_controller(self, index: int) -> None:
        L = lib()
        if L.SDL_IsGameController(index):
            c = L.SDL_GameControllerOpen(index)
            if c:
                self.controllers.append(c)

    def size(self) -> tuple[int, int]:
        w, h = c_int(), c_int()
        if lib().SDL_GetRendererOutputSize(self.ren, ctypes.byref(w), ctypes.byref(h)) != 0:
            lib().SDL_GetWindowSize(self.win, ctypes.byref(w), ctypes.byref(h))
        return w.value, h.value

    def logical_size(self) -> tuple[int, int]:
        w, h = c_int(), c_int()
        lib().SDL_GetWindowSize(self.win, ctypes.byref(w), ctypes.byref(h))
        return w.value, h.value

    def present(self, surface) -> None:
        L = lib()
        w, h = surface.width, surface.height
        if self.tex is None or self.tex_size != (w, h):
            if self.tex:
                L.SDL_DestroyTexture(self.tex)
            self.tex = L.SDL_CreateTexture(self.ren, PIXELFORMAT_ARGB8888, TEXTUREACCESS_STREAMING, w, h)
            self.tex_size = (w, h)
        L.SDL_UpdateTexture(self.tex, None, surface.data(), surface.stride)
        L.SDL_RenderClear(self.ren)
        L.SDL_RenderCopy(self.ren, self.tex, None, None)
        L.SDL_RenderPresent(self.ren)

    def show(self, visible: bool) -> None:
        if visible:
            lib().SDL_ShowWindow(self.win)
            lib().SDL_RaiseWindow(self.win)
        else:
            lib().SDL_HideWindow(self.win)

    def text_input(self, on: bool) -> None:
        (lib().SDL_StartTextInput if on else lib().SDL_StopTextInput)()

    def events(self, timeout_ms: int) -> list[Event]:
        """Wait up to timeout_ms for events and return all pending ones."""
        L = lib()
        out = []
        got = L.SDL_WaitEventTimeout(self._ev, max(0, timeout_ms)) if timeout_ms > 0 else L.SDL_PollEvent(self._ev)
        while got:
            ev = self._parse(self._ev.raw)
            if ev:
                out.append(ev)
            got = L.SDL_PollEvent(self._ev)
        return out

    def _parse(self, raw: bytes) -> Event | None:
        kind = struct.unpack_from("<I", raw, 0)[0]
        if kind == QUIT:
            return Event("quit")
        if kind == WINDOWEVENT:
            return Event("window", value=raw[12])
        if kind in (KEYDOWN, KEYUP):
            sym, mod = struct.unpack_from("<iH", raw, 20)
            name = KEYS.get(sym) or (chr(sym) if 32 < sym < 127 else "")
            return Event("keydown" if kind == KEYDOWN else "keyup", key=name, mod=mod, value=raw[13])
        if kind == TEXTINPUT:
            return Event("text", text=raw[12:44].split(b"\0", 1)[0].decode("utf-8", "replace"))
        if kind == MOUSEMOTION:
            x, y = struct.unpack_from("<ii", raw, 20)
            return Event("motion", x=x, y=y)
        if kind in (MOUSEBUTTONDOWN, MOUSEBUTTONUP):
            button, _, clicks = raw[16], raw[17], raw[18]
            x, y = struct.unpack_from("<ii", raw, 20)
            return Event("mousedown" if kind == MOUSEBUTTONDOWN else "mouseup", x=x, y=y, button=button, clicks=clicks)
        if kind == MOUSEWHEEL:
            _, dy = struct.unpack_from("<ii", raw, 16)
            return Event("wheel", value=dy)
        if kind in (CONTROLLERBUTTONDOWN, CONTROLLERBUTTONUP):
            return Event("padbutton" if kind == CONTROLLERBUTTONDOWN else "padbuttonup", button=BUTTONS.get(raw[12], ""))
        if kind == CONTROLLERAXISMOTION:
            value = struct.unpack_from("<h", raw, 16)[0] / 32767.0
            return Event("padaxis", button=AXES.get(raw[12], ""), value=max(-1.0, min(1.0, value)))
        if kind == CONTROLLERDEVICEADDED:
            self._open_controller(struct.unpack_from("<i", raw, 8)[0])
        return None

    def close(self) -> None:
        L = lib()
        if self.tex:
            L.SDL_DestroyTexture(self.tex)
        if self.ren:
            L.SDL_DestroyRenderer(self.ren)
        if self.win:
            L.SDL_DestroyWindow(self.win)
        L.SDL_Quit()

"""Load artwork into cairo surfaces (PNG natively, JPEG/BMP via gdk-pixbuf
when it is installed, which it is on SteamOS) with a cache of scaled copies."""

from __future__ import annotations

import ctypes
import ctypes.util
from ctypes import POINTER, c_char_p, c_double, c_int, c_void_p
from pathlib import Path

from . import cairo as C

_gdk = None
_gdk_failed = False


def _gdk_lib():
    global _gdk, _gdk_failed
    if _gdk is not None or _gdk_failed:
        return _gdk
    try:
        pix = ctypes.CDLL(ctypes.util.find_library("gdk_pixbuf-2.0") or "libgdk_pixbuf-2.0.so.0")
        gdk = ctypes.CDLL(ctypes.util.find_library("gdk-3") or "libgdk-3.so.0")
        gobj = ctypes.CDLL(ctypes.util.find_library("gobject-2.0") or "libgobject-2.0.so.0")
    except OSError:
        _gdk_failed = True
        return None
    pix.gdk_pixbuf_new_from_file.restype = c_void_p
    pix.gdk_pixbuf_new_from_file.argtypes = [c_char_p, POINTER(c_void_p)]
    pix.gdk_pixbuf_get_width.restype = c_int
    pix.gdk_pixbuf_get_width.argtypes = [c_void_p]
    pix.gdk_pixbuf_get_height.restype = c_int
    pix.gdk_pixbuf_get_height.argtypes = [c_void_p]
    gdk.gdk_cairo_set_source_pixbuf.restype = None
    gdk.gdk_cairo_set_source_pixbuf.argtypes = [c_void_p, c_void_p, c_double, c_double]
    gobj.g_object_unref.restype = None
    gobj.g_object_unref.argtypes = [c_void_p]
    _gdk = (pix, gdk, gobj)
    return _gdk


def load(path: str | Path) -> C.Surface | None:
    path = Path(path)
    if not path.exists():
        return None
    with open(path, "rb") as fh:
        head = fh.read(8)
    if head == b"\x89PNG\r\n\x1a\n":
        surf = C.Surface.from_png(str(path))
        if surf is not None:
            return surf
    libs = _gdk_lib()
    if not libs:
        return None
    pix, gdk, gobj = libs
    err = c_void_p()
    pb = pix.gdk_pixbuf_new_from_file(str(path).encode(), ctypes.byref(err))
    if not pb:
        return None
    try:
        w, h = pix.gdk_pixbuf_get_width(pb), pix.gdk_pixbuf_get_height(pb)
        surf = C.Surface.create(w, h)
        ctx = C.Context(surf)
        gdk.gdk_cairo_set_source_pixbuf(ctx.cr, pb, 0.0, 0.0)
        ctx.paint()
        ctx.destroy()
        return surf
    finally:
        gobj.g_object_unref(pb)


class Cache:
    """Keeps decoded originals and pre-scaled copies (cheap to draw)."""

    def __init__(self):
        self._orig: dict[str, C.Surface | None] = {}
        self._scaled: dict[tuple[str, int, int], C.Surface | None] = {}

    def original(self, path: Path | None) -> C.Surface | None:
        if path is None:
            return None
        key = str(path)
        if key not in self._orig:
            try:
                self._orig[key] = load(path)
            except Exception:
                self._orig[key] = None
        return self._orig[key]

    def fit(self, path: Path | None, box_w: int, box_h: int, upscale_limit: float = 4.0) -> C.Surface | None:
        """Copy of the image scaled to fit (box_w x box_h), aspect preserved.
        Small icons are only enlarged up to `upscale_limit` times."""
        if path is None:
            return None
        key = (str(path), int(box_w), int(box_h))
        if key in self._scaled:
            return self._scaled[key]
        src = self.original(path)
        out = None
        if src is not None and src.width > 0 and src.height > 0:
            s = min(box_w / src.width, box_h / src.height, upscale_limit)
            w, h = max(1, round(src.width * s)), max(1, round(src.height * s))
            out = C.Surface.create(w, h)
            ctx = C.Context(out)
            ctx.image(src, 0, 0, w, h, filter_=C.FILTER_BEST)
            ctx.destroy()
        self._scaled[key] = out
        return out

    def forget(self, path: Path | None) -> None:
        if path is None:
            return
        key = str(path)
        self._orig.pop(key, None)
        for k in [k for k in self._scaled if k[0] == key]:
            del self._scaled[k]

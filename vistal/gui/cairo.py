"""Minimal ctypes binding to cairo with a small Pythonic wrapper."""

from __future__ import annotations

import ctypes
import ctypes.util
import math
import os
from ctypes import POINTER, c_char_p, c_double, c_int, c_void_p

FORMAT_ARGB32 = 0
OPERATOR_CLEAR, OPERATOR_SOURCE, OPERATOR_OVER = 0, 1, 2
EXTEND_NONE, EXTEND_REPEAT, EXTEND_REFLECT, EXTEND_PAD = 0, 1, 2, 3
FILTER_FAST, FILTER_GOOD, FILTER_BEST, FILTER_NEAREST, FILTER_BILINEAR = 0, 1, 2, 3, 4
SLANT_NORMAL, WEIGHT_NORMAL, WEIGHT_BOLD = 0, 0, 1


class CairoUnavailable(RuntimeError):
    pass


class _TextExtents(ctypes.Structure):
    _fields_ = [(n, c_double) for n in ("x_bearing", "y_bearing", "width", "height", "x_advance", "y_advance")]


class _FontExtents(ctypes.Structure):
    _fields_ = [(n, c_double) for n in ("ascent", "descent", "height", "max_x_advance", "max_y_advance")]


_lib = None


def lib():
    global _lib
    if _lib is not None:
        return _lib
    name = os.environ.get("VISTAL_LIBCAIRO") or ctypes.util.find_library("cairo") or "libcairo.so.2"
    try:
        L = ctypes.CDLL(name)
    except OSError as exc:
        raise CairoUnavailable(f"cairo library not found ({exc})") from exc
    D, I, P, S = c_double, c_int, c_void_p, c_char_p
    sig = {
        "cairo_image_surface_create": (P, [I, I, I]),
        "cairo_image_surface_create_from_png": (P, [S]),
        "cairo_image_surface_get_width": (I, [P]),
        "cairo_image_surface_get_height": (I, [P]),
        "cairo_image_surface_get_stride": (I, [P]),
        "cairo_image_surface_get_data": (P, [P]),
        "cairo_surface_flush": (None, [P]),
        "cairo_surface_mark_dirty": (None, [P]),
        "cairo_surface_destroy": (None, [P]),
        "cairo_surface_status": (I, [P]),
        "cairo_surface_write_to_png": (I, [P, S]),
        "cairo_create": (P, [P]),
        "cairo_destroy": (None, [P]),
        "cairo_save": (None, [P]),
        "cairo_restore": (None, [P]),
        "cairo_translate": (None, [P, D, D]),
        "cairo_scale": (None, [P, D, D]),
        "cairo_rectangle": (None, [P, D, D, D, D]),
        "cairo_arc": (None, [P, D, D, D, D, D]),
        "cairo_move_to": (None, [P, D, D]),
        "cairo_line_to": (None, [P, D, D]),
        "cairo_rel_line_to": (None, [P, D, D]),
        "cairo_curve_to": (None, [P, D, D, D, D, D, D]),
        "cairo_close_path": (None, [P]),
        "cairo_new_path": (None, [P]),
        "cairo_new_sub_path": (None, [P]),
        "cairo_fill": (None, [P]),
        "cairo_fill_preserve": (None, [P]),
        "cairo_stroke": (None, [P]),
        "cairo_stroke_preserve": (None, [P]),
        "cairo_clip": (None, [P]),
        "cairo_reset_clip": (None, [P]),
        "cairo_paint": (None, [P]),
        "cairo_paint_with_alpha": (None, [P, D]),
        "cairo_mask_surface": (None, [P, P, D, D]),
        "cairo_set_source_rgba": (None, [P, D, D, D, D]),
        "cairo_set_source_surface": (None, [P, P, D, D]),
        "cairo_set_source": (None, [P, P]),
        "cairo_get_source": (P, [P]),
        "cairo_set_line_width": (None, [P, D]),
        "cairo_set_operator": (None, [P, I]),
        "cairo_set_antialias": (None, [P, I]),
        "cairo_push_group": (None, [P]),
        "cairo_pop_group_to_source": (None, [P]),
        "cairo_pattern_create_linear": (P, [D, D, D, D]),
        "cairo_pattern_create_radial": (P, [D, D, D, D, D, D]),
        "cairo_pattern_create_for_surface": (P, [P]),
        "cairo_pattern_add_color_stop_rgba": (None, [P, D, D, D, D, D]),
        "cairo_pattern_set_filter": (None, [P, I]),
        "cairo_pattern_set_extend": (None, [P, I]),
        "cairo_pattern_destroy": (None, [P]),
        "cairo_select_font_face": (None, [P, S, I, I]),
        "cairo_set_font_size": (None, [P, D]),
        "cairo_show_text": (None, [P, S]),
        "cairo_text_path": (None, [P, S]),
        "cairo_text_extents": (None, [P, S, POINTER(_TextExtents)]),
        "cairo_font_extents": (None, [P, POINTER(_FontExtents)]),
    }
    for fname, (res, args) in sig.items():
        fn = getattr(L, fname)
        fn.restype = res
        fn.argtypes = args
    _lib = L
    return L


def available() -> bool:
    try:
        lib()
        return True
    except CairoUnavailable:
        return False


def rgb(hexstr: str, a: float = 1.0) -> tuple[float, float, float, float]:
    h = hexstr.lstrip("#")
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, a)


class Surface:
    def __init__(self, ptr: int, owned: bool = True):
        if not ptr:
            raise CairoUnavailable("could not create surface")
        self.ptr = ptr
        self.owned = owned

    @classmethod
    def create(cls, width: int, height: int) -> "Surface":
        return cls(lib().cairo_image_surface_create(FORMAT_ARGB32, max(1, int(width)), max(1, int(height))))

    @classmethod
    def from_png(cls, path: str) -> "Surface | None":
        ptr = lib().cairo_image_surface_create_from_png(str(path).encode())
        if not ptr or lib().cairo_surface_status(ptr) != 0:
            if ptr:
                lib().cairo_surface_destroy(ptr)
            return None
        return cls(ptr)

    @property
    def width(self) -> int:
        return lib().cairo_image_surface_get_width(self.ptr)

    @property
    def height(self) -> int:
        return lib().cairo_image_surface_get_height(self.ptr)

    @property
    def stride(self) -> int:
        return lib().cairo_image_surface_get_stride(self.ptr)

    def data(self) -> int:
        lib().cairo_surface_flush(self.ptr)
        return lib().cairo_image_surface_get_data(self.ptr)

    def write_png(self, path: str) -> None:
        lib().cairo_surface_flush(self.ptr)
        if lib().cairo_surface_write_to_png(self.ptr, str(path).encode()) != 0:
            raise OSError(f"could not write {path}")

    def destroy(self) -> None:
        if self.ptr and self.owned:
            lib().cairo_surface_destroy(self.ptr)
        self.ptr = 0

    def __del__(self):
        try:
            self.destroy()
        except Exception:
            pass


class Pattern:
    def __init__(self, ptr: int):
        self.ptr = ptr

    @classmethod
    def linear(cls, x0, y0, x1, y1, stops) -> "Pattern":
        p = cls(lib().cairo_pattern_create_linear(x0, y0, x1, y1))
        for off, color in stops:
            lib().cairo_pattern_add_color_stop_rgba(p.ptr, off, *color)
        return p

    @classmethod
    def radial(cls, cx0, cy0, r0, cx1, cy1, r1, stops) -> "Pattern":
        p = cls(lib().cairo_pattern_create_radial(cx0, cy0, r0, cx1, cy1, r1))
        for off, color in stops:
            lib().cairo_pattern_add_color_stop_rgba(p.ptr, off, *color)
        return p

    @classmethod
    def repeating(cls, surface: "Surface") -> "Pattern":
        p = cls(lib().cairo_pattern_create_for_surface(surface.ptr))
        p._keep = surface  # the pattern references the surface
        lib().cairo_pattern_set_extend(p.ptr, EXTEND_REPEAT)
        lib().cairo_pattern_set_filter(p.ptr, FILTER_NEAREST)
        return p

    def __del__(self):
        try:
            if self.ptr:
                lib().cairo_pattern_destroy(self.ptr)
        except Exception:
            pass


class Context:
    """Drawing context with helpers for the shapes both themes need."""

    def __init__(self, surface: Surface):
        self.surface = surface
        self.L = lib()
        self.cr = self.L.cairo_create(surface.ptr)
        self.font_family = "Sans"

    def destroy(self) -> None:
        if self.cr:
            self.L.cairo_destroy(self.cr)
            self.cr = 0

    def __del__(self):
        try:
            self.destroy()
        except Exception:
            pass

    # state
    def save(self): self.L.cairo_save(self.cr)
    def restore(self): self.L.cairo_restore(self.cr)
    def translate(self, x, y): self.L.cairo_translate(self.cr, x, y)
    def scale(self, sx, sy): self.L.cairo_scale(self.cr, sx, sy)
    def clip(self): self.L.cairo_clip(self.cr)
    def reset_clip(self): self.L.cairo_reset_clip(self.cr)
    def set_operator(self, op): self.L.cairo_set_operator(self.cr, op)
    def line_width(self, w): self.L.cairo_set_line_width(self.cr, w)

    # paths
    def new_path(self): self.L.cairo_new_path(self.cr)
    def move_to(self, x, y): self.L.cairo_move_to(self.cr, x, y)
    def line_to(self, x, y): self.L.cairo_line_to(self.cr, x, y)
    def curve_to(self, *a): self.L.cairo_curve_to(self.cr, *a)
    def close_path(self): self.L.cairo_close_path(self.cr)
    def rect(self, x, y, w, h): self.L.cairo_rectangle(self.cr, x, y, w, h)
    def arc(self, cx, cy, r, a0=0.0, a1=2 * math.pi): self.L.cairo_arc(self.cr, cx, cy, r, a0, a1)
    def circle(self, cx, cy, r):
        self.L.cairo_new_sub_path(self.cr)
        self.arc(cx, cy, r)

    def rounded(self, x, y, w, h, r, tl=True, tr=True, br=True, bl=True):
        r = max(0.0, min(r, w / 2, h / 2))
        L, cr = self.L, self.cr
        L.cairo_new_sub_path(cr)
        if tl:
            L.cairo_arc(cr, x + r, y + r, r, math.pi, 1.5 * math.pi)
        else:
            L.cairo_move_to(cr, x, y)
        if tr:
            L.cairo_arc(cr, x + w - r, y + r, r, 1.5 * math.pi, 2 * math.pi)
        else:
            L.cairo_line_to(cr, x + w, y)
        if br:
            L.cairo_arc(cr, x + w - r, y + h - r, r, 0, 0.5 * math.pi)
        else:
            L.cairo_line_to(cr, x + w, y + h)
        if bl:
            L.cairo_arc(cr, x + r, y + h - r, r, 0.5 * math.pi, math.pi)
        else:
            L.cairo_line_to(cr, x, y + h)
        L.cairo_close_path(cr)

    # painting
    def color(self, c):
        if isinstance(c, str):
            c = rgb(c)
        if len(c) == 3:
            c = (*c, 1.0)
        self.L.cairo_set_source_rgba(self.cr, *c)

    def source(self, pattern: Pattern):
        self.L.cairo_set_source(self.cr, pattern.ptr)

    def fill(self, c=None, preserve=False):
        if c is not None:
            self.color(c) if not isinstance(c, Pattern) else self.source(c)
        (self.L.cairo_fill_preserve if preserve else self.L.cairo_fill)(self.cr)

    def stroke(self, c=None, width=None, preserve=False):
        if c is not None:
            self.color(c) if not isinstance(c, Pattern) else self.source(c)
        if width is not None:
            self.line_width(width)
        (self.L.cairo_stroke_preserve if preserve else self.L.cairo_stroke)(self.cr)

    def paint(self, alpha: float = 1.0):
        if alpha >= 1.0:
            self.L.cairo_paint(self.cr)
        else:
            self.L.cairo_paint_with_alpha(self.cr, alpha)

    def vgradient(self, y0, y1, stops) -> Pattern:
        return Pattern.linear(0, y0, 0, y1, [(o, rgb(c) if isinstance(c, str) else c) for o, c in stops])

    def hgradient(self, x0, x1, stops) -> Pattern:
        return Pattern.linear(x0, 0, x1, 0, [(o, rgb(c) if isinstance(c, str) else c) for o, c in stops])

    def image(self, surf: Surface, x, y, w=None, h=None, alpha=1.0, filter_=FILTER_GOOD):
        """Draw `surf` at (x, y), scaled to w x h if given."""
        sw, sh = surf.width, surf.height
        w = w or sw
        h = h or sh
        self.save()
        self.translate(x, y)
        if (w, h) != (sw, sh):
            self.scale(w / sw, h / sh)
        self.L.cairo_set_source_surface(self.cr, surf.ptr, 0, 0)
        self.L.cairo_pattern_set_filter(self.L.cairo_get_source(self.cr), filter_)
        self.rect(0, 0, sw, sh)
        self.clip()
        self.paint(alpha)
        self.restore()

    def push_group(self): self.L.cairo_push_group(self.cr)
    def pop_group_to_source(self): self.L.cairo_pop_group_to_source(self.cr)

    # text
    def font(self, size: float, bold: bool = False, family: str | None = None):
        self.L.cairo_select_font_face(self.cr, (family or self.font_family).encode(), SLANT_NORMAL,
                                      WEIGHT_BOLD if bold else WEIGHT_NORMAL)
        self.L.cairo_set_font_size(self.cr, size)

    def text_width(self, text: str) -> float:
        ext = _TextExtents()
        self.L.cairo_text_extents(self.cr, text.encode("utf-8"), ctypes.byref(ext))
        return ext.x_advance

    def font_metrics(self) -> tuple[float, float]:
        ext = _FontExtents()
        self.L.cairo_font_extents(self.cr, ctypes.byref(ext))
        return ext.ascent, ext.descent

    def text(self, x, y, text: str, c=None, align: str = "left", max_width: float | None = None):
        """Draw text with its baseline at y. Returns the drawn width."""
        if max_width is not None:
            text = self.ellipsize(text, max_width)
        w = self.text_width(text)
        if align == "center":
            x -= w / 2
        elif align == "right":
            x -= w
        if c is not None:
            self.color(c)
        self.L.cairo_move_to(self.cr, x, y)
        self.L.cairo_show_text(self.cr, text.encode("utf-8"))
        return w

    def ellipsize(self, text: str, max_width: float) -> str:
        if self.text_width(text) <= max_width:
            return text
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.text_width(text[:mid].rstrip() + "…") <= max_width:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo].rstrip() + "…"

    def wrap(self, text: str, max_width: float, max_lines: int = 2) -> list[str]:
        if max_lines <= 1:
            return [self.ellipsize(" ".join(text.split()), max_width)]
        words = text.split()
        lines: list[str] = []
        cur = ""
        for i, word in enumerate(words):
            trial = f"{cur} {word}".strip()
            if self.text_width(trial) <= max_width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
                if len(lines) == max_lines - 1:
                    cur = " ".join(words[i:])
                    break
        if cur:
            lines.append(cur)
        lines = lines[:max_lines]
        return [self.ellipsize(l, max_width) for l in lines]

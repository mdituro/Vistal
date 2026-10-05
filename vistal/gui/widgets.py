"""Drawing primitives shared by the themes: glossy orbs and gel buttons,
vector glyphs, gamepad button hints, placeholder artwork, font selection."""

from __future__ import annotations

import math
import shutil
import subprocess
from functools import lru_cache

from .cairo import Context, Pattern, rgb


@lru_cache(maxsize=1)
def installed_families() -> frozenset[str]:
    if not shutil.which("fc-list"):
        return frozenset()
    try:
        out = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return frozenset()
    fams = set()
    for line in out.splitlines():
        for name in line.split(","):
            fams.add(name.strip().lower())
    return frozenset(fams)


def pick_font(preferences: list[str]) -> str:
    fams = installed_families()
    for p in preferences:
        if p.lower() in fams:
            return p
    return preferences[-1] if preferences else "Sans"


def mix(c1, c2, t: float):
    a, b = rgb(c1) if isinstance(c1, str) else c1, rgb(c2) if isinstance(c2, str) else c2
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(4))


# --------------------------------------------------------------------------
# glossy shapes
# --------------------------------------------------------------------------


def orb(ctx: Context, cx, cy, r, base: str, dark: str, enabled: bool = True):
    """Vista-style round glass button (the back/forward orbs)."""
    if not enabled:
        base, dark = "#9fb2c6", "#6f8399"
    ctx.circle(cx, cy + 0.5, r + 1)
    ctx.fill((0, 0, 0, 0.35))
    ctx.circle(cx, cy, r)
    ctx.fill(Pattern.radial(cx, cy + r * 0.6, r * 0.1, cx, cy + r * 0.2, r * 1.2,
                            [(0, rgb(base)), (1, rgb(dark))]))
    ctx.circle(cx, cy, r)
    ctx.stroke((0.05, 0.15, 0.3, 0.8), 1)
    ctx.save()
    ctx.translate(cx, cy - r * 0.45)
    ctx.scale(1.0, 0.55)
    ctx.circle(0, 0, r * 0.75)
    ctx.restore()
    ctx.fill(ctx.vgradient(cy - r, cy, [(0, (1, 1, 1, 0.75)), (1, (1, 1, 1, 0.08))]))


def gel_circle(ctx: Context, cx, cy, r, top: str, bottom: str, rim: str):
    """Aqua 'gel' candy circle (traffic lights, round buttons)."""
    ctx.circle(cx, cy + 0.6, r + 0.6)
    ctx.fill((0, 0, 0, 0.25))
    ctx.circle(cx, cy, r)
    ctx.fill(Pattern.radial(cx, cy + r * 0.7, r * 0.1, cx, cy + r * 0.3, r * 1.3,
                            [(0, rgb(top)), (1, rgb(bottom))]))
    ctx.circle(cx, cy, r)
    ctx.stroke(rim, 0.8)
    ctx.save()
    ctx.translate(cx, cy - r * 0.42)
    ctx.scale(1.0, 0.6)
    ctx.circle(0, 0, r * 0.68)
    ctx.restore()
    ctx.fill(ctx.vgradient(cy - r, cy, [(0, (1, 1, 1, 0.9)), (1, (1, 1, 1, 0.1))]))


def gel_pill(ctx: Context, x, y, w, h, colors: tuple[str, str, str], rim: str, radius=None):
    """Aqua gel capsule: colors = (top, middle-dark, bottom-glow)."""
    r = radius if radius is not None else h / 2
    ctx.rounded(x, y + 1, w, h, r)
    ctx.fill((0, 0, 0, 0.18))
    ctx.rounded(x, y, w, h, r)
    ctx.fill(ctx.vgradient(y, y + h, [(0, colors[0]), (0.5, colors[1]), (1, colors[2])]))
    ctx.rounded(x + 0.5, y + 0.5, w - 1, h - 1, r)
    ctx.stroke(rim, 1)
    ctx.rounded(x + h * 0.2, y + 1.5, w - h * 0.4, h * 0.45, min(r, h * 0.22))
    ctx.fill(ctx.vgradient(y, y + h * 0.5, [(0, (1, 1, 1, 0.85)), (1, (1, 1, 1, 0.15))]))


def glass_highlight(ctx: Context, x, y, w, h, radius=3, strength=1.0):
    """Vista hover/pressed glass bevel used on command bar buttons."""
    ctx.rounded(x + 0.5, y + 0.5, w - 1, h - 1, radius)
    ctx.fill(ctx.vgradient(y, y + h, [(0, (1, 1, 1, 0.35 * strength)), (0.5, (1, 1, 1, 0.15 * strength)),
                                       (0.5, (1, 1, 1, 0.02)), (1, (1, 1, 1, 0.2 * strength))]))
    ctx.rounded(x + 0.5, y + 0.5, w - 1, h - 1, radius)
    ctx.stroke((1, 1, 1, 0.55 * strength), 1)
    ctx.rounded(x + 1.5, y + 1.5, w - 3, h - 3, radius - 1)
    ctx.stroke((0, 0, 0, 0.25 * strength), 1)


def drop_shadow(ctx: Context, x, y, w, h, radius=4, spread=8, alpha=0.35, dy=3):
    for i in range(spread, 0, -1):
        a = alpha * (1 - i / (spread + 1)) ** 2 / 3
        ctx.rounded(x - i, y - i + dy, w + 2 * i, h + 2 * i, radius + i)
        ctx.fill((0, 0, 0, a))


# --------------------------------------------------------------------------
# glyphs (drawn as paths so no font needs to contain them)
# --------------------------------------------------------------------------


def chevron(ctx: Context, x, y, size, direction: str, color, width=1.6):
    s = size / 2
    pts = {
        "down": [(x - s, y - s / 2), (x, y + s / 2), (x + s, y - s / 2)],
        "up": [(x - s, y + s / 2), (x, y - s / 2), (x + s, y + s / 2)],
        "right": [(x - s / 2, y - s), (x + s / 2, y), (x - s / 2, y + s)],
        "left": [(x + s / 2, y - s), (x - s / 2, y), (x + s / 2, y + s)],
    }[direction]
    ctx.move_to(*pts[0])
    for p in pts[1:]:
        ctx.line_to(*p)
    ctx.stroke(color, width)


def triangle(ctx: Context, x, y, size, direction: str, color):
    s = size / 2
    pts = {
        "down": [(x - s, y - s / 2), (x + s, y - s / 2), (x, y + s / 2)],
        "right": [(x - s / 2, y - s), (x + s / 2, y), (x - s / 2, y + s)],
        "up": [(x - s, y + s / 2), (x + s, y + s / 2), (x, y - s / 2)],
    }[direction]
    ctx.move_to(*pts[0])
    for p in pts[1:]:
        ctx.line_to(*p)
    ctx.close_path()
    ctx.fill(color)


def arrow(ctx: Context, cx, cy, size, direction: str, color, width=2.2):
    s = size / 2
    sign = -1 if direction == "left" else 1
    ctx.move_to(cx - sign * s, cy)
    ctx.line_to(cx + sign * s, cy)
    ctx.stroke(color, width)
    ctx.move_to(cx + sign * (s - s * 0.8), cy - s * 0.75)
    ctx.line_to(cx + sign * s, cy)
    ctx.line_to(cx + sign * (s - s * 0.8), cy + s * 0.75)
    ctx.stroke(color, width)


def magnifier(ctx: Context, cx, cy, r, color, width=1.6):
    ctx.circle(cx - r * 0.2, cy - r * 0.2, r * 0.7)
    ctx.stroke(color, width)
    ctx.move_to(cx + r * 0.3, cy + r * 0.3)
    ctx.line_to(cx + r, cy + r)
    ctx.stroke(color, width + 0.8)


def play_glyph(ctx: Context, cx, cy, size, color):
    s = size / 2
    ctx.move_to(cx - s * 0.6, cy - s)
    ctx.line_to(cx + s, cy)
    ctx.line_to(cx - s * 0.6, cy + s)
    ctx.close_path()
    ctx.fill(color)


def gear(ctx: Context, cx, cy, r, color):
    teeth = 8
    ctx.new_path()
    for i in range(teeth * 2):
        a = i * math.pi / teeth
        rr = r if i % 2 == 0 else r * 0.75
        for da in (-0.18, 0.18):
            x, y = cx + rr * math.cos(a + da), cy + rr * math.sin(a + da)
            ctx.line_to(x, y)
    ctx.close_path()
    ctx.fill(color)
    ctx.circle(cx, cy, r * 0.32)
    ctx.fill((1, 1, 1, 0.9))


def info_glyph(ctx: Context, cx, cy, r, fg, bg):
    ctx.circle(cx, cy, r)
    ctx.fill(bg)
    ctx.circle(cx, cy - r * 0.45, r * 0.13)
    ctx.fill(fg)
    ctx.rect(cx - r * 0.11, cy - r * 0.2, r * 0.22, r * 0.75)
    ctx.fill(fg)


def grid_glyph(ctx: Context, x, y, size, cells: int, color):
    gap = size * 0.12
    cs = (size - gap * (cells - 1)) / cells
    for i in range(cells):
        for j in range(cells):
            ctx.rect(x + i * (cs + gap), y + j * (cs + gap), cs, cs)
    ctx.fill(color)


def list_glyph(ctx: Context, x, y, size, color):
    for i in range(4):
        yy = y + i * size / 4 + size / 10
        ctx.rect(x, yy, size * 0.18, size * 0.14)
        ctx.rect(x + size * 0.28, yy, size * 0.72, size * 0.14)
    ctx.fill(color)


PAD_COLORS = {"A": "#3fae3a", "B": "#d8382d", "X": "#2f6fd8", "Y": "#e8b10f"}


def pad_hint(ctx: Context, x, y, button: str, label: str, text_color, size=18, font_size=12,
             shadow=None) -> float:
    """Draw a gamepad button glyph followed by a label; returns the width used."""
    r = size / 2
    if button in PAD_COLORS:
        ctx.circle(x + r, y, r)
        ctx.fill(Pattern.radial(x + r, y + r * 0.5, 1, x + r, y, r * 1.3,
                                [(0, mix(PAD_COLORS[button], "#ffffff", 0.25)), (1, rgb(PAD_COLORS[button]))]))
        ctx.circle(x + r, y, r)
        ctx.stroke((0, 0, 0, 0.45), 1)
        ctx.font(font_size * 0.85, bold=True)
        ctx.text(x + r, y + font_size * 0.3, button, "#ffffff", align="center")
        bw = size
    else:
        ctx.font(font_size * 0.75, bold=True)
        tw = ctx.text_width(button) + 10
        ctx.rounded(x, y - r * 0.8, tw, r * 1.6, r * 0.5)
        ctx.fill((0.2, 0.22, 0.25, 0.9))
        ctx.rounded(x, y - r * 0.8, tw, r * 1.6, r * 0.5)
        ctx.stroke((1, 1, 1, 0.35), 1)
        ctx.text(x + tw / 2, y + font_size * 0.27, button, "#ffffff", align="center")
        bw = tw
    ctx.font(font_size)
    if shadow:
        ctx.text(x + bw + 6, y + font_size * 0.35 + 1, label, shadow)
    w = ctx.text(x + bw + 6, y + font_size * 0.35, label, text_color)
    return bw + 6 + w


# --------------------------------------------------------------------------
# placeholder artwork
# --------------------------------------------------------------------------


def disc_icon(ctx: Context, cx, cy, r):
    """A shiny CD-ROM, used when a game has no artwork."""
    ctx.circle(cx, cy + r * 0.04, r)
    ctx.fill((0, 0, 0, 0.18))
    ctx.circle(cx, cy, r)
    ctx.fill(Pattern.radial(cx - r * 0.3, cy - r * 0.3, r * 0.1, cx, cy, r,
                            [(0, rgb("#ffffff")), (0.6, rgb("#d9dee6")), (1, rgb("#aeb7c4"))]))
    # iridescent sheen
    for i, col in enumerate(("#ff9db0", "#ffe08a", "#9ef0b0", "#9ec8ff", "#d9a8ff")):
        a0 = -0.9 + i * 0.22
        ctx.new_path()
        ctx.move_to(cx, cy)
        ctx.arc(cx, cy, r * 0.97, a0, a0 + 0.22)
        ctx.close_path()
        ctx.fill(rgb(col, 0.35))
        ctx.new_path()
        ctx.move_to(cx, cy)
        ctx.arc(cx, cy, r * 0.97, a0 + math.pi, a0 + math.pi + 0.22)
        ctx.close_path()
        ctx.fill(rgb(col, 0.3))
    ctx.circle(cx, cy, r)
    ctx.stroke((0.35, 0.4, 0.48, 0.8), max(1, r * 0.02))
    ctx.circle(cx, cy, r * 0.33)
    ctx.fill(Pattern.radial(cx, cy, 1, cx, cy, r * 0.33, [(0, rgb("#f4f6f9")), (1, rgb("#c3cad4"))]))
    ctx.circle(cx, cy, r * 0.33)
    ctx.stroke((0.4, 0.45, 0.52, 0.6), 1)
    ctx.circle(cx, cy, r * 0.12)
    ctx.fill((0.3, 0.33, 0.38, 0.9))


def install_badge(ctx: Context, cx, cy, r):
    """Small blue orb with a down arrow: 'not installed yet'."""
    orb(ctx, cx, cy, r, "#58a6f0", "#1b56b3")
    ctx.move_to(cx, cy - r * 0.5)
    ctx.line_to(cx, cy + r * 0.35)
    ctx.stroke("#ffffff", max(1.5, r * 0.22))
    ctx.move_to(cx - r * 0.42, cy)
    ctx.line_to(cx, cy + r * 0.45)
    ctx.line_to(cx + r * 0.42, cy)
    ctx.stroke("#ffffff", max(1.5, r * 0.22))


_stripe_cache: dict = {}


def pinstripes(ctx: Context, x, y, w, h, light="#f6f6f6", dark="#e9e9e9", period=2):
    """Aqua pinstripes, painted from a tiny repeating pattern."""
    from .cairo import Surface
    key = (str(light), str(dark), period)
    pat = _stripe_cache.get(key)
    if pat is None:
        tile = Surface.create(1, period)
        tctx = Context(tile)
        tctx.rect(0, 0, 1, period)
        tctx.fill(light)
        tctx.rect(0, 0, 1, period / 2)
        tctx.fill(dark)
        tctx.destroy()
        pat = _stripe_cache[key] = Pattern.repeating(tile)
    ctx.rect(x, y, w, h)
    ctx.fill(pat)

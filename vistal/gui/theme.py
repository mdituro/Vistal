"""Theme base class: layout and drawing shared by the Vista and Aqua looks.
Themes draw the whole frame in logical units (designed for 1280x800, the
Steam Deck screen) and register clickable regions as they go."""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import widgets as W
from .cairo import Context

#: view -> (icon size, tile width, tile height)
VIEWS = {
    "extra-large": (256, 288, 318),
    "large": (128, 158, 192),
    "medium": (64, 108, 118),
}
VIEW_ORDER = ["extra-large", "large", "medium", "details"]
VIEW_LABELS = {"extra-large": "Extra Large Icons", "large": "Large Icons", "medium": "Medium Icons",
               "details": "Details"}
DETAIL_ROW = 40


@dataclass
class Geometry:
    x: float = 0
    y: float = 0
    w: float = 0
    h: float = 0
    cols: int = 1
    row_h: float = 1
    content_h: float = 0
    pad: float = 0


@dataclass
class MenuItem:
    label: str
    action: tuple = ()
    checked: bool = False
    enabled: bool = True
    separator: bool = False


@dataclass
class Menu:
    items: list[MenuItem]
    x: float
    y: float
    sel: int = 0
    title: str = ""

    def __post_init__(self):
        self.sel = next((i for i, it in enumerate(self.items) if it.enabled and not it.separator), 0)

    def move(self, delta: int) -> None:
        n = len(self.items)
        i = self.sel
        for _ in range(n):
            i = (i + delta) % n
            if self.items[i].enabled and not self.items[i].separator:
                self.sel = i
                return


@dataclass
class Message:
    title: str
    text: str
    buttons: list[str]
    actions: list[tuple]
    sel: int = 0
    kind: str = "info"  # info | error | question


class Theme:
    name = "base"
    label = "Base"
    fonts = ["Sans"]
    scrollbar_w = 16
    text = "#000000"
    subtle = "#5a6779"

    def __init__(self):
        self.family = W.pick_font(self.fonts)
        self._layers: dict[tuple, object] = {}

    def cached_layer(self, ctx: Context, app, name: str, w: float, h: float, draw) -> None:
        """Paint a static full-window layer, rendering it only once per size.
        Full-screen gradients are by far the most expensive thing we draw."""
        from .cairo import Surface
        key = (name, round(w), round(h), round(app.scale, 3))
        surf = self._layers.get(key)
        if surf is None:
            if len(self._layers) > 6:
                self._layers.clear()
            surf = Surface.create(round(w * app.scale), round(h * app.scale))
            lctx = Context(surf)
            lctx.scale(app.scale, app.scale)
            lctx.font_family = self.family
            draw(lctx, w, h)
            lctx.destroy()
            self._layers[key] = surf
        ctx.image(surf, 0, 0, w, h)

    # -- entry point ----------------------------------------------------------

    def draw(self, ctx: Context, app, width: float, height: float) -> None:
        raise NotImplementedError

    def prepare(self, ctx: Context) -> None:
        ctx.font_family = self.family

    # -- items area -----------------------------------------------------------

    def draw_items(self, ctx: Context, app, x, y, w, h) -> None:
        ctx.save()
        ctx.rect(x, y, w, h)
        ctx.clip()
        if not app.visible:
            self.draw_empty(ctx, app, x, y, w, h)
        elif app.view == "details":
            self.draw_details(ctx, app, x, y, w, h)
        else:
            self.draw_icons(ctx, app, x, y, w, h)
        ctx.restore()
        g = app.grid
        if g.content_h > h:
            self.draw_scrollbar(ctx, app, x + w - self.scrollbar_w, y, self.scrollbar_w, h,
                                app.scroll / g.content_h, h / g.content_h)
            app.hits.add(x + w - self.scrollbar_w, y, self.scrollbar_w, h, ("scrollbar", y, h))

    def draw_empty(self, ctx, app, x, y, w, h) -> None:
        app.grid = Geometry(x, y, w, h, 1, 1, 0)
        ctx.font(14)
        msg = "No games match your search." if app.search else "No games yet."
        ctx.text(x + w / 2, y + 60, msg, self.subtle, align="center")
        if not app.search:
            ctx.font(12)
            for i, line in enumerate(app.empty_help()):
                ctx.text(x + w / 2, y + 90 + i * 20, line, self.subtle, align="center")

    def draw_icons(self, ctx: Context, app, x, y, w, h) -> None:
        icon, tw, th = VIEWS.get(app.view, VIEWS["large"])
        pad = 14
        usable = w - 2 * pad - self.scrollbar_w
        cols = max(1, int(usable // tw))
        tw = max(tw, usable / cols) if cols > 1 else tw  # spread tiles evenly
        rows = math.ceil(len(app.visible) / cols)
        app.grid = Geometry(x, y, w, h, cols, th, rows * th + 2 * pad, pad)
        app.clamp_scroll()
        first = max(0, int((app.scroll - pad) // th))
        last = int((app.scroll + h) // th) + 1
        for i in range(first * cols, min(len(app.visible), (last + 1) * cols)):
            tx = x + pad + (i % cols) * tw
            ty = y + pad + (i // cols) * th - app.scroll
            self.draw_tile(ctx, app, app.visible[i], tx, ty, tw, th, icon, i == app.sel, i == app.hover)
            vy0, vy1 = max(ty, y), min(ty + th, y + h)
            if vy1 > vy0:
                app.hits.add(tx, vy0, tw, vy1 - vy0, ("tile", i))

    def draw_tile(self, ctx, app, entry, x, y, w, h, icon, selected, hover) -> None:
        raise NotImplementedError

    def art(self, ctx: Context, app, entry, cx, top, size, shadow=True) -> tuple[float, float, float, float]:
        """Draw the entry's artwork bottom-centred in a size x size box.
        Returns the rectangle actually covered."""
        path = entry.art.tile(app.artwork) if entry.art else None
        px = max(1, int(size * app.scale))
        surf = app.images.fit(path, px, px, upscale_limit=3.0) if path else None
        if surf is not None:
            sw, sh = surf.width / app.scale, surf.height / app.scale
            ax, ay = cx - sw / 2, top + size - sh
            square = abs(sw - sh) < 2
            if not square and shadow:  # box art: give it a frame like Explorer thumbnails
                W.drop_shadow(ctx, ax, ay, sw, sh, radius=1, spread=4, alpha=0.5, dy=2)
            ctx.image(surf, ax, ay, sw, sh)
            if not square:
                ctx.rect(ax + 0.5, ay + 0.5, sw - 1, sh - 1)
                ctx.stroke((0, 0, 0, 0.25), 1)
            rect = (ax, ay, sw, sh)
        else:
            r = size * 0.42
            W.disc_icon(ctx, cx, top + size - r - size * 0.06, r)
            rect = (cx - r, top + size - 2 * r - size * 0.06, 2 * r, 2 * r)
        if not entry.installed:
            br = max(7.0, min(16.0, size * 0.11))
            W.install_badge(ctx, rect[0] + rect[2] - br * 0.6, rect[1] + rect[3] - br * 0.6, br)
        return rect

    # -- details (list) view ----------------------------------------------------

    columns = [("Name", 0.36), ("Publisher", 0.2), ("Last Played", 0.2), ("Status", 0.24)]

    def column_values(self, e) -> list[str]:
        return [e.display_title, e.publisher or e.developer or "—", _date(e.last_played) or "Never", e.status]

    def draw_details(self, ctx: Context, app, x, y, w, h) -> None:
        rows = len(app.visible)
        app.grid = Geometry(x, y, w, h, 1, DETAIL_ROW, rows * DETAIL_ROW + 8, 4)
        app.clamp_scroll()
        first = max(0, int(app.scroll // DETAIL_ROW))
        last = min(rows, int((app.scroll + h) // DETAIL_ROW) + 2)
        usable = w - self.scrollbar_w
        for i in range(first, last):
            ry = y + 4 + i * DETAIL_ROW - app.scroll
            self.draw_row(ctx, app, app.visible[i], x, ry, usable, DETAIL_ROW, i, i == app.sel, i == app.hover)
            vy0, vy1 = max(ry, y), min(ry + DETAIL_ROW, y + h)
            if vy1 > vy0:
                app.hits.add(x, vy0, usable, vy1 - vy0, ("tile", i))

    def draw_row_cells(self, ctx: Context, app, e, x, y, w, h, color, sub_color) -> None:
        self.art(ctx, app, e, x + 24, y + 4, h - 8, shadow=False)
        cx = x + 46
        ctx.font(12.5)
        for idx, ((_, frac), value) in enumerate(zip(self.columns, self.column_values(e))):
            cw = w * frac - (46 if idx == 0 else 0)
            ctx.text(cx + 4, y + h / 2 + 4.5, value, color if idx == 0 else sub_color, max_width=cw - 12)
            cx += cw

    def draw_row(self, ctx, app, e, x, y, w, h, index, selected, hover) -> None:
        raise NotImplementedError

    def column_header_labels(self, ctx: Context, app, x, y, w, h, color, line):
        cx = x
        ctx.font(12)
        for i, (name, frac) in enumerate(self.columns):
            cw = (w - self.scrollbar_w) * frac
            ctx.text(cx + 10, y + h / 2 + 4, name, color)
            if (name == "Name" and app.sort == "name") or (name == "Last Played" and app.sort == "last-played"):
                W.chevron(ctx, cx + cw / 2, y + 5, 7, "up" if name == "Name" else "down", line, 1.2)
            if i:
                ctx.rect(cx, y + 4, 1, h - 8)
                ctx.fill(line)
            app.hits.add(cx, y, cw, h, ("sort", "name" if name == "Name" else "last-played"))
            cx += cw

    # -- overlays ---------------------------------------------------------------

    def draw_scrollbar(self, ctx, app, x, y, w, h, start, length) -> None:
        raise NotImplementedError

    def menu_size(self, ctx: Context, menu: Menu) -> tuple[float, float]:
        ctx.font(13)
        width = max((ctx.text_width(i.label) for i in menu.items if not i.separator), default=100)
        height = sum(9 if i.separator else 26 for i in menu.items) + 8
        return width + 70, height

    def place_menu(self, ctx, app, menu: Menu, width, height) -> tuple[float, float, float, float]:
        mw, mh = self.menu_size(ctx, menu)
        x = min(menu.x, width - mw - 4)
        y = menu.y if menu.y + mh < height - 4 else max(4, menu.y - mh)
        return x, y, mw, mh

    def draw_menu(self, ctx, app, menu: Menu, width, height) -> None:
        raise NotImplementedError

    def draw_message(self, ctx, app, msg: Message, width, height) -> None:
        raise NotImplementedError

    def hints(self, app) -> list[tuple[str, str]]:
        e = app.selected
        out = []
        if app.message:
            return [("A", "OK"), ("B", "Close")]
        if app.menu:
            return [("A", "Select"), ("B", "Close")]
        if e is not None:
            out.append(("A", "Play" if e.installed else "Install"))
            out.append(("X", "Game options"))
        out += [("Y", "Change view"), ("Start", "Menu"), ("LB", "Theme")]
        return out


def _date(ts: str) -> str:
    if not ts:
        return ""
    try:
        y, m, d = ts[:10].split("-")
        hh, mm = ts[11:16].split(":")
        hour = int(hh)
        ampm = "AM" if hour < 12 else "PM"
        return f"{int(m)}/{int(d)}/{y} {hour % 12 or 12}:{mm} {ampm}"
    except ValueError:
        return ts

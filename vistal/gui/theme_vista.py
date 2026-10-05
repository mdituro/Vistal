"""Windows Vista "Games Explorer" look: Aero glass frame, orb navigation
buttons, breadcrumb address bar, dark command bar, white icon view with the
soft blue Explorer selection, preview pane and details pane."""

from __future__ import annotations

from . import widgets as W
from .cairo import Context, Pattern
from .theme import Message, Menu, Theme, _date

GLASS_TOP = (0.47, 0.64, 0.84, 0.58)
GLASS_BOTTOM = (0.26, 0.42, 0.62, 0.55)
SEL_BORDER = "#7da2ce"
SEL_TOP, SEL_BOTTOM = "#e8f2fd", "#c4dcf8"
HOVER_BORDER = "#b8d6fb"
HOVER_TOP, HOVER_BOTTOM = "#fafcfe", "#e6f0fc"
TITLE_BLUE = "#1e3287"


def glow_text(ctx: Context, x, y, text, color="#000000", align="left", max_width=None, size=None):
    """Text on glass: dark text over a soft white cloud, like Vista captions."""
    if max_width is not None:
        text = ctx.ellipsize(text, max_width)
    w = ctx.text_width(text)
    left = x - w / 2 if align == "center" else (x - w if align == "right" else x)
    asc, _ = ctx.font_metrics()
    for i in range(6, 0, -1):
        ctx.rounded(left - 4 - i * 1.6, y - asc - i * 1.2, w + 8 + i * 3.2, asc + 6 + i * 2.4, 6 + i * 1.5)
        ctx.fill((1, 1, 1, 0.07))
    return ctx.text(x, y, text, color, align=align)


def selection(ctx: Context, x, y, w, h, selected: bool, hover: bool, focused: bool = True):
    if not (selected or hover):
        return
    if selected:
        top, bottom, border = (SEL_TOP, SEL_BOTTOM, SEL_BORDER) if focused else ("#f8f8f8", "#e5e5e5", "#d9d9d9")
    else:
        top, bottom, border = HOVER_TOP, HOVER_BOTTOM, HOVER_BORDER
    ctx.rounded(x + 0.5, y + 0.5, w - 1, h - 1, 3)
    ctx.fill(ctx.vgradient(y, y + h, [(0, top), (1, bottom)]))
    ctx.rounded(x + 0.5, y + 0.5, w - 1, h - 1, 3)
    ctx.stroke(border, 1)
    ctx.rounded(x + 1.5, y + 1.5, w - 3, h - 3, 2)
    ctx.stroke((1, 1, 1, 0.6), 1)


def button(ctx: Context, x, y, w, h, label, default=False, hover=False):
    ctx.rounded(x + 0.5, y + 0.5, w - 1, h - 1, 3)
    if default or hover:
        ctx.fill(ctx.vgradient(y, y + h, [(0, "#eaf6fd"), (0.5, "#d9f0fc"), (0.5, "#bee6fd"), (1, "#a7d9f5")]))
    else:
        ctx.fill(ctx.vgradient(y, y + h, [(0, "#f2f2f2"), (0.5, "#ebebeb"), (0.5, "#dddddd"), (1, "#cfcfcf")]))
    ctx.rounded(x + 0.5, y + 0.5, w - 1, h - 1, 3)
    ctx.stroke("#3c7fb1" if default or hover else "#707070", 1)
    ctx.rounded(x + 1.5, y + 1.5, w - 3, h - 3, 2)
    ctx.stroke((1, 1, 1, 0.7), 1)
    ctx.font(12.5)
    ctx.text(x + w / 2, y + h / 2 + 4.5, label, "#000000", align="center")


class VistaTheme(Theme):
    name = "vista"
    label = "Windows Vista"
    fonts = ["Segoe UI", "Noto Sans", "Open Sans", "Cantarell", "DejaVu Sans", "Liberation Sans", "Sans"]
    subtle = "#5a6779"

    # -- frame ------------------------------------------------------------------

    def wallpaper(self, ctx: Context, w, h):
        ctx.rect(0, 0, w, h)
        ctx.fill(ctx.vgradient(0, h, [(0, "#0d3357"), (0.6, "#071c33"), (1, "#03101e")]))
        for cx, cy, r, col in ((w * 0.22, h * 0.95, w * 0.55, (0.25, 0.78, 0.45, 0.55)),
                               (w * 0.78, h * 0.05, w * 0.5, (0.25, 0.55, 0.98, 0.55)),
                               (w * 0.55, h * 0.55, w * 0.35, (0.2, 0.75, 0.75, 0.25))):
            ctx.rect(0, 0, w, h)
            ctx.fill(Pattern.radial(cx, cy, 0, cx, cy, r, [(0, col), (1, (*col[:3], 0))]))
        # aurora ribbon
        ctx.move_to(-50, h * 0.42)
        ctx.curve_to(w * 0.3, h * 0.05, w * 0.6, h * 0.75, w + 50, h * 0.18)
        ctx.line_to(w + 50, h * 0.3)
        ctx.curve_to(w * 0.6, h * 0.85, w * 0.3, h * 0.18, -50, h * 0.55)
        ctx.close_path()
        ctx.fill(ctx.hgradient(0, w, [(0, (0.6, 1, 0.75, 0.0)), (0.35, (0.6, 1, 0.8, 0.35)),
                                      (0.7, (0.6, 0.85, 1, 0.3)), (1, (0.6, 0.85, 1, 0.0))]))

    def glass(self, ctx: Context, w, h):
        ctx.rect(0, 0, w, h)
        ctx.fill(ctx.vgradient(0, h, [(0, GLASS_TOP), (1, GLASS_BOTTOM)]))
        # diagonal reflections
        for x0, width, alpha in ((w * 0.08, 70, 0.07), (w * 0.15, 25, 0.06), (w * 0.62, 110, 0.05), (w * 0.74, 30, 0.06)):
            ctx.move_to(x0, 0)
            ctx.line_to(x0 + width, 0)
            ctx.line_to(x0 + width - h * 0.6, h)
            ctx.line_to(x0 - h * 0.6, h)
            ctx.close_path()
            ctx.fill((1, 1, 1, alpha))
        ctx.rect(0, 0, w, 60)
        ctx.fill(ctx.vgradient(0, 60, [(0, (1, 1, 1, 0.22)), (1, (1, 1, 1, 0.0))]))
        ctx.rect(0.5, 0.5, w - 1, h - 1)
        ctx.stroke((0, 0, 0, 0.8), 1)
        ctx.rect(1.5, 1.5, w - 3, h - 3)
        ctx.stroke((1, 1, 1, 0.45), 1)

    def caption_buttons(self, ctx: Context, app, w):
        specs = [("min", 27), ("max", 27), ("close", 45)]
        total = sum(s[1] for s in specs)
        x = w - 8 - total
        y, h = 1, 19
        for name, bw in specs:
            first, last = name == "min", name == "close"
            hover = app.hover_hit == ("caption", name)
            ctx.rounded(x, y, bw, h, 4, tl=False, tr=False, bl=first, br=last)
            if name == "close":
                ctx.fill(ctx.vgradient(y, y + h, [(0, "#eaa99b"), (0.45, "#d9634a"), (0.5, "#c8401f"),
                                                  (1, "#e2774f" if hover else "#cf5730")]))
            else:
                ctx.fill(ctx.vgradient(y, y + h, [(0, (1, 1, 1, 0.55 if hover else 0.4)), (0.5, (1, 1, 1, 0.2)),
                                                  (0.5, (1, 1, 1, 0.05)), (1, (1, 1, 1, 0.25 if hover else 0.15))]))
            ctx.rounded(x + 0.5, y + 0.5, bw - 1, h - 1, 4, tl=False, tr=False, bl=first, br=last)
            ctx.stroke((0.05, 0.1, 0.2, 0.75), 1)
            cx, cy = x + bw / 2, y + h / 2
            if name == "close":
                for col, wd in (((0.3, 0.05, 0, 0.6), 3.6), ("#ffffff", 2.0)):
                    ctx.move_to(cx - 4.5, cy - 4)
                    ctx.line_to(cx + 4.5, cy + 4)
                    ctx.move_to(cx + 4.5, cy - 4)
                    ctx.line_to(cx - 4.5, cy + 4)
                    ctx.stroke(col, wd)
            elif name == "min":
                ctx.rect(cx - 5, cy + 2, 10, 3)
                ctx.fill("#ffffff")
                ctx.rect(cx - 5.5, cy + 1.5, 11, 4)
                ctx.stroke((0, 0, 0, 0.5), 1)
            else:
                ctx.rect(cx - 5, cy - 4, 10, 8)
                ctx.stroke((0, 0, 0, 0.5), 3)
                ctx.rect(cx - 5, cy - 4, 10, 8)
                ctx.stroke("#ffffff", 1.6)
            app.hits.add(x, y, bw, h, ("caption", name))
            x += bw

    def address_bar(self, ctx: Context, app, w):
        cy = 41
        back_on = bool(app.search or app.category != "all")
        W.orb(ctx, 25, cy, 13, "#5aa4ec", "#1a54a6", enabled=back_on)
        W.arrow(ctx, 25, cy, 12, "left", "#ffffff", 2.4)
        app.hits.add(11, cy - 14, 28, 28, ("back",))
        W.orb(ctx, 54, cy, 12, "#5aa4ec", "#1a54a6", enabled=False)
        W.arrow(ctx, 54, cy, 11, "right", (1, 1, 1, 0.8), 2.2)
        W.chevron(ctx, 74, cy + 1, 6, "down", (0, 0, 0, 0.6), 1.3)
        # address box
        x, y, bw, bh = 86, cy - 12, w - 86 - 262, 24
        ctx.rounded(x, y, bw, bh, 2)
        ctx.fill(ctx.vgradient(y, y + bh, [(0, (1, 1, 1, 0.9)), (1, (0.94, 0.96, 0.99, 0.88))]))
        ctx.rounded(x + 0.5, y + 0.5, bw - 1, bh - 1, 2)
        ctx.stroke((0.1, 0.18, 0.3, 0.55), 1)
        W.disc_icon(ctx, x + 14, cy, 7.5)
        ctx.font(12.5)
        tx = x + 28
        W.chevron(ctx, tx + 3, cy, 6, "right", "#3d3d3d", 1.3)
        tx += 12
        tx += ctx.text(tx, cy + 4.5, "Games", "#000000") + 8
        app.hits.add(x + 22, y, tx - x - 22, bh, ("category", "all"))
        W.chevron(ctx, tx + 3, cy, 6, "right", "#3d3d3d", 1.3)
        tx += 12
        label = {"all": "All Games", "installed": "Installed", "not-installed": "Not Installed",
                 "recent": "Recently Played"}[app.category]
        if app.search:
            label = f"Search Results for \"{app.search}\""
        lw = ctx.text(tx, cy + 4.5, label, "#000000")
        app.hits.add(tx - 4, y, lw + 20, bh, ("menu", "category", tx - 4, y + bh))
        W.chevron(ctx, tx + lw + 9, cy + 1, 6, "down", "#3d3d3d", 1.2)
        # refresh button on the right end of the address box
        rx = x + bw - 14
        ctx.rect(rx - 13, y + 2, 1, bh - 4)
        ctx.fill((0, 0, 0, 0.15))
        ctx.arc(rx, cy, 5.5, -2.6, 2.0)
        ctx.stroke("#2a6a2a" if app.hover_hit == ("rescan",) else "#3c7a3c", 1.8)
        W.triangle(ctx, rx + 4.5, cy - 4.5, 6, "up", "#3c7a3c")
        app.hits.add(rx - 12, y, 26, bh, ("rescan",))
        # search box
        sx, sw = w - 254, 244
        ctx.rounded(sx, y, sw, bh, 2)
        ctx.fill(ctx.vgradient(y, y + bh, [(0, (1, 1, 1, 0.92 if app.search_focus else 0.8)),
                                           (1, (0.95, 0.97, 1, 0.85))]))
        ctx.rounded(sx + 0.5, y + 0.5, sw - 1, bh - 1, 2)
        ctx.stroke("#3c7fb1" if app.search_focus else (0.1, 0.18, 0.3, 0.55), 1)
        ctx.font(12.5)
        if app.search or app.search_focus:
            tw = ctx.text(sx + 8, cy + 4.5, app.search, "#000000", max_width=sw - 40)
            if app.search_focus and app.caret_on:
                ctx.rect(sx + 9 + tw, y + 5, 1, bh - 10)
                ctx.fill("#000000")
        else:
            ctx.text(sx + 8, cy + 4.5, "Search", "#6d6d6d")
        W.magnifier(ctx, sx + sw - 15, cy, 6, "#3c5a7a", 1.6)
        app.hits.add(sx, y, sw, bh, ("search",))

    def command_bar(self, ctx: Context, app, x, y, w, h):
        ctx.rect(x, y, w, h)
        ctx.fill(ctx.vgradient(y, y + h, [(0, "#4c6c8f"), (0.48, "#2f5276"), (0.5, "#1f3f63"), (1, "#16345a")]))
        ctx.rect(x, y, w, 1)
        ctx.fill((1, 1, 1, 0.35))
        ctx.rect(x, y + h - 1, w, 1)
        ctx.fill("#0a1d33")
        e = app.selected
        items = [("Organize", True, "organize"), ("Views", True, "views")]
        if e is not None:
            items.append(("Play" if e.installed else "Install", False, "play"))
        items += [("Options", False, "options"), ("Tools", True, "tools")]
        ctx.font(12.5)
        cx = x + 6
        for label, drop, key in items:
            tw = ctx.text_width(label)
            bw = tw + (34 if drop else 20) + (18 if key == "play" else 0)
            hover = app.hover_hit and app.hover_hit[:2] == ("toolbar", key)
            if hover or (app.menu and app.menu.title == key):
                W.glass_highlight(ctx, cx, y + 3, bw, h - 6, 3, 1.0)
            tx = cx + 10
            if key == "play":
                W.play_glyph(ctx, tx + 6, y + h / 2, 11, "#8fe388" if e.installed else "#9cc8ff")
                tx += 18
            ctx.text(tx, y + h / 2 + 5, label, (0, 0, 0, 0.5))
            ctx.text(tx, y + h / 2 + 4, label, "#ffffff")
            if drop:
                W.chevron(ctx, tx + tw + 10, y + h / 2 + 1, 6, "down", "#ffffff", 1.3)
            app.hits.add(cx, y, bw, h, ("toolbar", key, cx, y + h))
            cx += bw + 2
        # help orb on the right
        W.info_glyph(ctx, x + w - 22, y + h / 2, 8, "#ffffff", (1, 1, 1, 0.2))

    def column_header(self, ctx: Context, app, x, y, w, h):
        ctx.rect(x, y, w, h)
        ctx.fill(ctx.vgradient(y, y + h, [(0, "#ffffff"), (1, "#f1f5fa")]))
        ctx.rect(x, y + h - 1, w, 1)
        ctx.fill("#d5dfe8")
        self.column_header_labels(ctx, app, x, y, w, h, "#4c607a", "#dde4ec")

    # -- tiles ----------------------------------------------------------------------

    def draw_tile(self, ctx, app, e, x, y, w, h, icon, selected, hover):
        selection(ctx, x + 3, y + 3, w - 6, h - 6, selected, hover, app.focus == "items")
        self.art(ctx, app, e, x + w / 2, y + 8, icon)
        size = 12.5 if icon >= 96 else 12
        ctx.font(size)
        lines = ctx.wrap(e.display_title, w - 16, 3 if selected else 2)
        ty = y + 8 + icon + 18
        for line in lines:
            ctx.text(x + w / 2, ty, line, "#000000", align="center")
            ty += size + 3

    def draw_row(self, ctx, app, e, x, y, w, h, index, selected, hover):
        selection(ctx, x + 2, y + 1, w - 4, h - 2, selected, hover, app.focus == "items")
        self.draw_row_cells(ctx, app, e, x, y, w, h, "#000000", "#4d4d4d")

    def draw_scrollbar(self, ctx, app, x, y, w, h, start, length):
        ctx.rect(x, y, w, h)
        ctx.fill(ctx.hgradient(x, x + w, [(0, "#e9e9e9"), (0.5, "#f5f5f5"), (1, "#e9e9e9")]))
        for ay, d in ((y, "up"), (y + h - w, "down")):
            W.triangle(ctx, x + w / 2, ay + w / 2, 7, d, "#606060")
        track = h - 2 * w
        ty = y + w + track * start
        th = max(24, track * length)
        ctx.rounded(x + 1.5, ty, w - 3, th, 2.5)
        ctx.fill(ctx.hgradient(x, x + w, [(0, "#f4f4f4"), (0.5, "#e2e2e2"), (0.5, "#d6d6d6"), (1, "#cfcfcf")]))
        ctx.rounded(x + 1.5, ty, w - 3, th, 2.5)
        ctx.stroke("#9b9b9b", 1)
        for i in (-3, 0, 3):
            ctx.rect(x + 5, ty + th / 2 + i, w - 10, 1)
        ctx.fill("#8a8a8a")

    # -- panes ------------------------------------------------------------------------

    def preview_pane(self, ctx: Context, app, x, y, w, h):
        ctx.rect(x, y, w, h)
        ctx.fill(ctx.vgradient(y, y + h, [(0, "#ffffff"), (1, "#eaf1fa")]))
        ctx.rect(x, y, 1, h)
        ctx.fill("#d6e0ea")
        e = app.selected
        if e is None:
            ctx.font(12.5)
            ctx.text(x + w / 2, y + 60, "Select a game to see its details.", self.subtle, align="center")
            return
        art_size = min(220, w - 60)
        self.art(ctx, app, e, x + w / 2, y + 18, art_size)
        ty = y + 18 + art_size + 30
        ctx.font(16, bold=True)
        for line in ctx.wrap(e.display_title, w - 36, 2):
            ctx.text(x + 18, ty, line, "#1e1e1e")
            ty += 21
        ctx.circle(x + 23, ty - 4, 4)
        ctx.fill("#3fae3a" if e.installed else "#2f6fd8")
        ctx.font(12.5)
        ctx.text(x + 33, ty, e.status, "#3d3d3d")
        ty += 22
        ctx.font(12.5, bold=True)
        ctx.text(x + 18, ty, "Game Information", TITLE_BLUE)
        ctx.rect(x + 18, ty + 6, w - 36, 1)
        ctx.fill(ctx.hgradient(x + 18, x + w - 18, [(0, "#a8bcd8"), (1, (0.66, 0.74, 0.85, 0))]))
        ty += 24
        rows = [("Publisher", e.publisher), ("Developer", e.developer), ("Genre", e.genre), ("Released", e.year),
                ("Profile", e.profile.get("title", "") if e.profile else "Generic settings")]
        ctx.font(12)
        for label, value in rows:
            if not value:
                continue
            ctx.text(x + 18, ty, label + ":", self.subtle)
            ctx.text(x + 100, ty, value, "#1e1e1e", max_width=w - 118)
            ty += 19
        notes = str(e.profile.get("notes", "")).strip() if e.profile else ""
        if notes and ty < y + h - 50:
            ty += 8
            ctx.font(11.5)
            for line in ctx.wrap(" ".join(notes.split()), w - 36, max(1, int((y + h - ty - 8) // 16))):
                ctx.text(x + 18, ty, line, "#4d4d4d")
                ty += 16

    def details_pane(self, ctx: Context, app, x, y, w, h):
        ctx.rect(x, y, w, h)
        ctx.fill(ctx.vgradient(y, y + h, [(0, "#fbfdff"), (1, "#dce8f5")]))
        ctx.rect(x, y, w, 1)
        ctx.fill("#c3d2e3")
        e = app.selected
        if e is None:
            ctx.font(12.5)
            ctx.text(x + 20, y + h / 2 + 5, f"{len(app.visible)} items", "#1e1e1e")
            return
        self.art(ctx, app, e, x + 48, y + 10, h - 20, shadow=False)
        ctx.font(15)
        ctx.text(x + 92, y + 32, e.display_title, "#1e1e1e", max_width=270)
        ctx.font(12)
        ctx.text(x + 92, y + 52, e.kind, self.subtle, max_width=270)
        cols = [[("Status", e.status), ("Last played", _date(e.last_played) or "Never")],
                [("Publisher", e.publisher or "Unknown"), ("Developer", e.developer or "Unknown")]]
        cx = x + 380
        for col in cols:
            for i, (label, value) in enumerate(col):
                yy = y + 30 + i * 22
                ctx.text(cx + 80, yy, label + ":", self.subtle, align="right")
                ctx.text(cx + 88, yy, value, "#1e1e1e", max_width=190)
            cx += 290

    def bottom_strip(self, ctx: Context, app, w, h):
        y = h - 18
        ctx.font(12.5)
        n_inst = sum(1 for e in app.visible if e.installed)
        glow_text(ctx, 16, y + 4, f"{len(app.visible)} games, {n_inst} installed")
        if app.busy:
            glow_text(ctx, w / 2, y + 4, app.busy, align="center")
        x = w - 12
        hints = self.hints(app)
        widths = []
        for b, label in hints:
            ctx.font(12)
            widths.append(ctx.text_width(label) + (18 if len(b) == 1 else ctx.text_width(b) + 10) + 22)
        x -= sum(widths)
        total = sum(widths)
        for i in range(6, 0, -1):
            ctx.rounded(x - 6 - i * 1.6, y - 11 - i * 1.2, total + 4 + i * 3.2, 22 + i * 2.4, 8 + i * 1.5)
            ctx.fill((1, 1, 1, 0.07))
        for (b, label), wd in zip(hints, widths):
            W.pad_hint(ctx, x, y, b, label, "#000000", size=17, font_size=12)
            x += wd

    # -- frame --------------------------------------------------------------------------

    def draw(self, ctx: Context, app, w, h):
        self.prepare(ctx)
        self.cached_layer(ctx, app, "frame", w, h, lambda c, lw, lh: (self.wallpaper(c, lw, lh), self.glass(c, lw, lh)))
        self.caption_buttons(ctx, app, w)
        self.address_bar(ctx, app, w)
        x0, y0, w0, h0 = 8, 62, w - 16, h - 62 - 36
        ctx.rect(x0 - 0.5, y0 - 0.5, w0 + 1, h0 + 1)
        ctx.stroke((0.05, 0.1, 0.2, 0.7), 1)
        ctx.rect(x0, y0, w0, h0)
        ctx.fill("#ffffff")
        self.command_bar(ctx, app, x0, y0, w0, 33)
        details_h = 82
        preview_w = 300 if w0 >= 980 else 0
        main_y = y0 + 33
        main_h = h0 - 33 - details_h
        list_w = w0 - preview_w
        self.column_header(ctx, app, x0, main_y, list_w, 25)
        self.draw_items(ctx, app, x0, main_y + 25, list_w, main_h - 25)
        if preview_w:
            self.preview_pane(ctx, app, x0 + list_w, main_y, preview_w, main_h)
        self.details_pane(ctx, app, x0, main_y + main_h, w0, details_h)
        self.bottom_strip(ctx, app, w, h)
        if app.menu:
            self.draw_menu(ctx, app, app.menu, w, h)
        if app.message:
            self.draw_message(ctx, app, app.message, w, h)

    # -- overlays --------------------------------------------------------------------------

    def draw_menu(self, ctx, app, menu: Menu, width, height):
        app.hits.add(0, 0, width, height, ("dismiss",))
        x, y, mw, mh = self.place_menu(ctx, app, menu, width, height)
        W.drop_shadow(ctx, x, y, mw, mh, radius=0, spread=5, alpha=0.45, dy=3)
        ctx.rect(x, y, mw, mh)
        ctx.fill("#f0f0f0")
        ctx.rect(x + 0.5, y + 0.5, mw - 1, mh - 1)
        ctx.stroke("#979797", 1)
        ctx.rect(x + 28, y + 2, 1, mh - 4)
        ctx.fill("#e2e3e3")
        ctx.rect(x + 29, y + 2, 1, mh - 4)
        ctx.fill("#ffffff")
        yy = y + 4
        ctx.font(13)
        for i, item in enumerate(menu.items):
            if item.separator:
                ctx.rect(x + 32, yy + 4, mw - 36, 1)
                ctx.fill("#e0e0e0")
                ctx.rect(x + 32, yy + 5, mw - 36, 1)
                ctx.fill("#ffffff")
                yy += 9
                continue
            if i == menu.sel and item.enabled:
                ctx.rounded(x + 3.5, yy + 0.5, mw - 7, 25, 3)
                ctx.fill(ctx.vgradient(yy, yy + 26, [(0, "#f1f7fe"), (1, "#d7e8fc")]))
                ctx.rounded(x + 3.5, yy + 0.5, mw - 7, 25, 3)
                ctx.stroke("#9dc5f3", 1)
            if item.checked:
                ctx.rounded(x + 5.5, yy + 3.5, 20, 19, 2)
                ctx.fill("#e6f0fa")
                ctx.rounded(x + 5.5, yy + 3.5, 20, 19, 2)
                ctx.stroke("#a6c4e4", 1)
                ctx.move_to(x + 10, yy + 13)
                ctx.line_to(x + 14, yy + 17)
                ctx.line_to(x + 21, yy + 8)
                ctx.stroke("#1f3f63", 1.8)
            ctx.text(x + 38, yy + 17.5, item.label, "#000000" if item.enabled else "#8d8d8d")
            if item.enabled:
                app.hits.add(x, yy, mw, 26, ("menuitem", i))
            yy += 26

    def draw_message(self, ctx, app, msg: Message, width, height):
        app.hits.add(0, 0, width, height, ("modal",))
        ctx.rect(0, 0, width, height)
        ctx.fill((0, 0, 0, 0.25))
        mw = 500
        ctx.font(12.5)
        lines = []
        for para in msg.text.split("\n"):
            lines += ctx.wrap(para, mw - 110, 6) if para.strip() else [""]
        lines = lines[:12]
        body_h = 70 + len(lines) * 18
        mh = 34 + body_h + 48 + 8
        x, y = (width - mw) / 2, (height - mh) / 2
        W.drop_shadow(ctx, x, y, mw, mh, radius=6, spread=10, alpha=0.6, dy=4)
        ctx.save()
        ctx.rounded(x, y, mw, mh, 6)
        ctx.clip()
        self.cached_layer(ctx, app, "wallpaper", width, height, self.wallpaper)
        ctx.rect(x, y, mw, mh)
        ctx.fill(ctx.vgradient(y, y + mh, [(0, GLASS_TOP), (1, GLASS_BOTTOM)]))
        ctx.restore()
        ctx.rounded(x + 0.5, y + 0.5, mw - 1, mh - 1, 6)
        ctx.stroke((0, 0, 0, 0.8), 1)
        ctx.font(12.5)
        glow_text(ctx, x + 12, y + 21, msg.title)
        bx, by, bw, bh = x + 8, y + 32, mw - 16, mh - 40
        ctx.rect(bx, by, bw, bh)
        ctx.fill("#ffffff")
        ctx.rect(bx, by + bh - 48, bw, 48)
        ctx.fill("#f0f0f0")
        ctx.rect(bx, by + bh - 48, bw, 1)
        ctx.fill("#dfdfdf")
        icx, icy = bx + 36, by + 38
        if msg.kind == "error":
            W.orb(ctx, icx, icy, 17, "#f0745c", "#b3200e")
            ctx.move_to(icx - 6, icy - 6)
            ctx.line_to(icx + 6, icy + 6)
            ctx.move_to(icx + 6, icy - 6)
            ctx.line_to(icx - 6, icy + 6)
            ctx.stroke("#ffffff", 3)
        else:
            W.orb(ctx, icx, icy, 17, "#69b4f5", "#1650b0")
            ctx.font(20, bold=True)
            ctx.text(icx, icy + 7, "?" if msg.kind == "question" else "i", "#ffffff", align="center")
        ctx.font(12.5)
        ty = by + 36
        for line in lines:
            ctx.text(bx + 70, ty, line, TITLE_BLUE if ty == by + 36 else "#1e1e1e")
            ty += 18
        btn_w = 92
        bxx = bx + bw - 14 - len(msg.buttons) * (btn_w + 8) + 8
        for i, label in enumerate(msg.buttons):
            button(ctx, bxx, by + bh - 36, btn_w, 25, label, default=i == msg.sel)
            app.hits.add(bxx, by + bh - 36, btn_w, 25, ("msgbutton", i))
            bxx += btn_w + 8

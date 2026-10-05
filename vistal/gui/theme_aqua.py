"""Mac OS X "Aqua" look: blue desktop, pinstriped window with traffic
lights, gel segmented controls, Finder-style sidebar and icon view with blue
label pills, a Get Info style inspector drawer, and a Dock."""

from __future__ import annotations

from . import widgets as W
from .cairo import Context, Pattern
from .theme import VIEW_ORDER, Message, Menu, Theme, _date

AQUA_BLUE = "#3875d7"
SEL_GRAD = ("#6c9be8", "#3b72d6")


def blue_bar(ctx: Context, x, y, w, h):
    ctx.rect(x, y, w, h)
    ctx.fill(ctx.vgradient(y, y + h, [(0, SEL_GRAD[0]), (1, SEL_GRAD[1])]))
    ctx.rect(x, y, w, 1)
    ctx.fill((1, 1, 1, 0.3))


def gray_gel(ctx: Context, x, y, w, h, r, pressed=False, tl=True, tr=True, br=True, bl=True):
    ctx.rounded(x, y, w, h, r, tl, tr, br, bl)
    if pressed:
        ctx.fill(ctx.vgradient(y, y + h, [(0, "#a9c6ef"), (0.5, "#6f9de0"), (0.5, "#5b8bd8"), (1, "#9cc3f2")]))
    else:
        ctx.fill(ctx.vgradient(y, y + h, [(0, "#ffffff"), (0.5, "#ececec"), (0.5, "#dcdcdc"), (1, "#f3f3f3")]))
    ctx.rounded(x + 0.5, y + 0.5, w - 1, h - 1, r, tl, tr, br, bl)
    ctx.stroke("#7f7f7f" if not pressed else "#3d5f99", 1)


def gel_button(ctx: Context, x, y, w, h, label, default=False):
    if default:
        W.gel_pill(ctx, x, y, w, h, ("#a9cdfa", "#3a7ee8", "#93c6ff"), "#2a4f8f")
    else:
        W.gel_pill(ctx, x, y, w, h, ("#ffffff", "#e3e3e3", "#fafafa"), "#7a7a7a")
    ctx.font(13)
    ctx.text(x + w / 2, y + h / 2 + 4.5, label, "#000000", align="center")


class AquaTheme(Theme):
    name = "aqua"
    label = "Aqua"
    fonts = ["Lucida Grande", "Noto Sans", "Open Sans", "Cantarell", "DejaVu Sans", "Liberation Sans", "Sans"]
    subtle = "#5f5f5f"
    scrollbar_w = 15
    columns = [("Name", 0.36), ("Publisher", 0.2), ("Last Played", 0.2), ("Status", 0.24)]

    # -- desktop -----------------------------------------------------------------

    def desktop(self, ctx: Context, w, h):
        ctx.rect(0, 0, w, h)
        ctx.fill(ctx.vgradient(0, h, [(0, "#6fa5ea"), (0.45, "#3b77cf"), (1, "#123d8c")]))
        ctx.rect(0, 0, w, h)
        ctx.fill(Pattern.radial(w * 0.3, h * 0.25, 0, w * 0.3, h * 0.25, w * 0.6,
                                [(0, (1, 1, 1, 0.28)), (1, (1, 1, 1, 0))]))
        for k, alpha in ((0, 0.22), (1, 0.14), (2, 0.1)):
            off = k * 40
            ctx.move_to(-20, h * 0.75 + off)
            ctx.curve_to(w * 0.25, h * 0.35 + off, w * 0.65, h * 1.05 + off, w + 20, h * 0.45 + off)
            ctx.line_to(w + 20, h * 0.52 + off)
            ctx.curve_to(w * 0.65, h * 1.12 + off, w * 0.25, h * 0.42 + off, -20, h * 0.82 + off)
            ctx.close_path()
            ctx.fill((1, 1, 1, alpha))

    # -- window chrome --------------------------------------------------------------

    def title_and_toolbar(self, ctx: Context, app, x, y, w, h):
        ctx.save()
        ctx.rounded(x, y, w, h + 8, 7, br=False, bl=False)
        ctx.clip()
        W.pinstripes(ctx, x, y, w, h, "#f4f4f4", "#e7e7e7")
        ctx.rect(x, y, w, h)
        ctx.fill(ctx.vgradient(y, y + h, [(0, (1, 1, 1, 0.55)), (0.3, (1, 1, 1, 0.0)), (1, (0, 0, 0, 0.06))]))
        ctx.restore()
        ctx.rect(x, y + h - 1, w, 1)
        ctx.fill("#8f8f8f")
        # traffic lights
        for i, (top, bottom, rim, key) in enumerate((("#ff9a8a", "#d42d1c", "#8f1c11", "close"),
                                                     ("#ffe08a", "#e0a313", "#97690b", "min"),
                                                     ("#b3f08f", "#46a923", "#2c6e14", "zoom"))):
            cx = x + 16 + i * 21
            W.gel_circle(ctx, cx, y + 12, 6.5, top, bottom, rim)
            if app.hover_hit and app.hover_hit[0] == "caption":
                glyph = (0.3, 0.05, 0.0, 0.7)
                if key == "close":
                    ctx.move_to(cx - 2.5, y + 9.5)
                    ctx.line_to(cx + 2.5, y + 14.5)
                    ctx.move_to(cx + 2.5, y + 9.5)
                    ctx.line_to(cx - 2.5, y + 14.5)
                    ctx.stroke(glyph, 1.4)
                elif key == "min":
                    ctx.rect(cx - 3, y + 11.3, 6, 1.4)
                    ctx.fill(glyph)
                else:
                    ctx.rect(cx - 3, y + 11.3, 6, 1.4)
                    ctx.rect(cx - 0.7, y + 9, 1.4, 6)
                    ctx.fill(glyph)
            app.hits.add(cx - 8, y + 4, 16, 16, ("caption", {"close": "close", "min": "min", "zoom": "max"}[key]))
        ctx.font(13, bold=True)
        title = "Games"
        tw = ctx.text_width(title)
        W.disc_icon(ctx, x + w / 2 - tw / 2 - 12, y + 12, 7)
        ctx.text(x + w / 2 + 6, y + 17, title, (0, 0, 0, 0.82), align="center")
        # toolbar
        ty = y + 26
        self.nav_segments(ctx, app, x + 14, ty + 6)
        self.view_segments(ctx, app, x + 92, ty + 6)
        bx = x + 250
        e = app.selected
        buttons = []
        if e is not None:
            buttons.append(("play", "Play" if e.installed else "Install"))
            buttons.append(("info", "Options"))
        buttons += [("refresh", "Refresh"), ("theme", "Vista")]
        for key, label in buttons:
            self.toolbar_button(ctx, app, bx, ty + 2, key, label)
            bx += 72
        # search field
        sw = 210
        sx, sy = x + w - sw - 16, ty + 10
        ctx.rounded(sx, sy, sw, 22, 11)
        ctx.fill("#ffffff")
        ctx.rounded(sx + 0.5, sy + 0.5, sw - 1, 21, 10.5)
        ctx.stroke("#3875d7" if app.search_focus else "#8c8c8c", 2 if app.search_focus else 1)
        ctx.rounded(sx + 1.5, sy + 1.5, sw - 3, 6, 3)
        ctx.fill(ctx.vgradient(sy, sy + 8, [(0, (0, 0, 0, 0.12)), (1, (0, 0, 0, 0))]))
        W.magnifier(ctx, sx + 14, sy + 11, 5.5, "#6b6b6b", 1.5)
        ctx.font(12)
        if app.search or app.search_focus:
            tw = ctx.text(sx + 26, sy + 15.5, app.search, "#000000", max_width=sw - 36)
            if app.search_focus and app.caret_on:
                ctx.rect(sx + 27 + tw, sy + 5, 1, 12)
                ctx.fill("#000000")
        else:
            ctx.text(sx + 26, sy + 15.5, "Search", "#9a9a9a")
        app.hits.add(sx, sy, sw, 22, ("search",))
        ctx.font(10.5)
        ctx.text(sx + sw / 2, sy + 34, "Search", "#3d3d3d", align="center")

    def nav_segments(self, ctx: Context, app, x, y):
        back_on = bool(app.search or app.category != "all")
        gray_gel(ctx, x, y, 34, 22, 5, tr=False, br=False)
        gray_gel(ctx, x + 34, y, 34, 22, 5, tl=False, bl=False)
        ctx.move_to(x + 20, y + 6)
        ctx.line_to(x + 13, y + 11)
        ctx.line_to(x + 20, y + 16)
        ctx.close_path()
        ctx.fill((0, 0, 0, 0.75 if back_on else 0.28))
        ctx.move_to(x + 48, y + 6)
        ctx.line_to(x + 55, y + 11)
        ctx.line_to(x + 48, y + 16)
        ctx.close_path()
        ctx.fill((0, 0, 0, 0.28))
        app.hits.add(x, y, 34, 22, ("back",))
        ctx.font(10.5)
        ctx.text(x + 34, y + 34, "Back", "#3d3d3d", align="center")

    def view_segments(self, ctx: Context, app, x, y):
        seg = 33
        for i, view in enumerate(VIEW_ORDER):
            first, last = i == 0, i == len(VIEW_ORDER) - 1
            on = app.view == view
            gray_gel(ctx, x + i * seg, y, seg, 22, 5, tl=first, bl=first, tr=last, br=last, pressed=on)
            col = (1, 1, 1, 0.95) if on else (0.15, 0.15, 0.15, 0.85)
            cx = x + i * seg + seg / 2
            if view == "extra-large":
                W.grid_glyph(ctx, cx - 6, y + 5, 12, 1, col)
            elif view == "large":
                W.grid_glyph(ctx, cx - 6, y + 5, 12, 2, col)
            elif view == "medium":
                W.grid_glyph(ctx, cx - 6, y + 5, 12, 3, col)
            else:
                W.list_glyph(ctx, cx - 6, y + 5, 12, col)
            app.hits.add(x + i * seg, y, seg, 22, ("view", view))
        ctx.font(10.5)
        ctx.text(x + seg * 2, y + 34, "View", "#3d3d3d", align="center")

    def toolbar_button(self, ctx: Context, app, x, y, key, label):
        cx, cy = x + 30, y + 15
        pressed = app.hover_hit and app.hover_hit[:2] == ("toolbar", key)
        if key == "play":
            W.gel_circle(ctx, cx, cy, 13, "#a8d4ff", "#1f63d6", "#17418a")
            W.play_glyph(ctx, cx + 1.5, cy, 11, (1, 1, 1, 0.95))
        elif key == "info":
            W.gel_circle(ctx, cx, cy, 13, "#d8e7fb", "#6f8fbf", "#405a80")
            W.info_glyph(ctx, cx, cy, 8, "#ffffff", (0, 0, 0, 0))
        elif key == "refresh":
            W.gel_circle(ctx, cx, cy, 13, "#c9f2b5", "#3c9a28", "#2b6a1c")
            ctx.arc(cx, cy, 6, -2.4, 2.2)
            ctx.stroke("#ffffff", 2)
            W.triangle(ctx, cx + 5, cy - 5.5, 6, "up", "#ffffff")
        else:  # theme switch: a tiny Vista-blue window
            W.gel_circle(ctx, cx, cy, 13, "#e9eef6", "#9aa7b8", "#5b6676")
            ctx.rect(cx - 7, cy - 6, 14, 12)
            ctx.fill("#2f6fb5")
            ctx.rect(cx - 5, cy - 2, 10, 6)
            ctx.fill("#ffffff")
        if pressed:
            ctx.circle(cx, cy, 13)
            ctx.fill((0, 0, 0, 0.15))
        ctx.font(10.5)
        ctx.text(cx, y + 38, label, "#1e1e1e", align="center")
        action = {"play": ("toolbar", "play", x, y + 44), "info": ("toolbar", "game", x, y + 44),
                  "refresh": ("rescan",), "theme": ("theme", "vista")}[key]
        app.hits.add(x, y, 60, 44, action)

    # -- sidebar -------------------------------------------------------------------------

    def sidebar(self, ctx: Context, app, x, y, w, h):
        ctx.rect(x, y, w, h)
        ctx.fill(ctx.vgradient(y, y + h, [(0, "#e8edf4"), (1, "#dce3ec")]))
        ctx.rect(x + w - 1, y, 1, h)
        ctx.fill("#a3a3a3")
        counts = app.counts()
        yy = y + 22
        ctx.font(11, bold=True)
        ctx.text(x + 12, yy, "LIBRARY", "#6d7a8a")
        yy += 10
        for cat, label in (("all", "All Games"), ("installed", "Installed"),
                           ("not-installed", "Not Installed"), ("recent", "Recently Played")):
            on = app.category == cat
            if on:
                blue_bar(ctx, x, yy, w - 1, 22)
            icon_x = x + 22
            if cat == "all":
                W.disc_icon(ctx, icon_x, yy + 11, 7)
            elif cat == "installed":
                W.gel_circle(ctx, icon_x, yy + 11, 6.5, "#b3f08f", "#46a923", "#2c6e14")
            elif cat == "not-installed":
                W.install_badge(ctx, icon_x, yy + 11, 6.5)
            else:
                ctx.circle(icon_x, yy + 11, 6.5)
                ctx.fill("#ffffff" if on else "#f6f6f6")
                ctx.circle(icon_x, yy + 11, 6.5)
                ctx.stroke("#555555", 1)
                ctx.move_to(icon_x, yy + 6.5)
                ctx.line_to(icon_x, yy + 11)
                ctx.line_to(icon_x + 3.5, yy + 12.5)
                ctx.stroke("#333333", 1.2)
            ctx.font(12.5, bold=on)
            ctx.text(x + 36, yy + 15.5, label, "#ffffff" if on else "#111111", max_width=w - 80)
            n = str(counts.get(cat, 0))
            ctx.font(10.5, bold=True)
            bw = ctx.text_width(n) + 12
            ctx.rounded(x + w - bw - 10, yy + 4, bw, 14, 7)
            ctx.fill((1, 1, 1, 0.95) if on else "#8d9db3")
            ctx.text(x + w - 10 - bw / 2, yy + 15, n, AQUA_BLUE if on else "#ffffff", align="center")
            app.hits.add(x, yy, w, 22, ("category", cat))
            yy += 24
        yy += 18
        ctx.font(11, bold=True)
        ctx.text(x + 12, yy, "APPEARANCE", "#6d7a8a")
        yy += 10
        for name, label in (("aqua", "Aqua"), ("vista", "Windows Vista")):
            on = app.theme_name == name
            if on:
                blue_bar(ctx, x, yy, w - 1, 22)
            ctx.circle(x + 22, yy + 11, 6.5)
            ctx.fill("#5d8fe0" if name == "aqua" else "#2f5c8f")
            ctx.circle(x + 22, yy + 11, 6.5)
            ctx.stroke("#ffffff", 1.5)
            ctx.font(12.5, bold=on)
            ctx.text(x + 36, yy + 15.5, label, "#ffffff" if on else "#111111")
            app.hits.add(x, yy, w, 22, ("theme", name))
            yy += 24

    # -- items -------------------------------------------------------------------------------

    def draw_tile(self, ctx, app, e, x, y, w, h, icon, selected, hover):
        top = y + 10
        if selected:
            pad = 6
            ctx.rounded(x + w / 2 - icon / 2 - pad, top - pad, icon + 2 * pad, icon + 2 * pad, 8)
            ctx.fill((0, 0, 0, 0.13))
        self.art(ctx, app, e, x + w / 2, top, icon)
        size = 12.5 if icon >= 96 else 11.5
        ctx.font(size, bold=False)
        lines = ctx.wrap(e.display_title, w - 20, 3 if selected else 2)
        ty = top + icon + 20
        for line in lines:
            if selected:
                lw = ctx.text_width(line)
                ctx.rounded(x + w / 2 - lw / 2 - 7, ty - size - 1, lw + 14, size + 6, (size + 6) / 2)
                ctx.fill(AQUA_BLUE if app.focus == "items" else "#8e8e8e")
                ctx.text(x + w / 2, ty, line, "#ffffff", align="center")
            else:
                ctx.text(x + w / 2, ty, line, "#000000", align="center")
            ty += size + 5

    def draw_row(self, ctx, app, e, x, y, w, h, index, selected, hover):
        if selected:
            ctx.rect(x, y, w, h)
            ctx.fill(AQUA_BLUE)
        elif index % 2 == 1:
            ctx.rect(x, y, w, h)
            ctx.fill("#edf3fe")
        color = "#ffffff" if selected else "#000000"
        self.draw_row_cells(ctx, app, e, x, y, w, h, color, "#ffffff" if selected else "#333333")

    def list_header(self, ctx: Context, app, x, y, w, h):
        ctx.rect(x, y, w, h)
        ctx.fill(ctx.vgradient(y, y + h, [(0, "#fbfbfb"), (0.5, "#ececec"), (0.5, "#e2e2e2"), (1, "#f0f0f0")]))
        cx = x
        for name, frac in self.columns:
            cw = (w - self.scrollbar_w) * frac
            active = (name == "Name" and app.sort == "name") or (name == "Last Played" and app.sort == "last-played")
            if active:
                ctx.rect(cx, y, cw, h)
                ctx.fill(ctx.vgradient(y, y + h, [(0, "#c9ddf8"), (0.5, "#8db6ee"), (0.5, "#76a6ea"), (1, "#a9ccf6")]))
                W.triangle(ctx, cx + cw - 12, y + h / 2, 7, "up" if name == "Name" else "down", "#1d3f75")
            cx += cw
        ctx.rect(x, y + h - 1, w, 1)
        ctx.fill("#9a9a9a")
        cx = x
        ctx.font(11.5)
        for i, (name, frac) in enumerate(self.columns):
            cw = (w - self.scrollbar_w) * frac
            ctx.text(cx + 8, y + h / 2 + 4, name, "#111111")
            if i:
                ctx.rect(cx, y + 3, 1, h - 6)
                ctx.fill("#b5b5b5")
            app.hits.add(cx, y, cw, h, ("sort", "name" if name == "Name" else "last-played"))
            cx += cw

    def draw_scrollbar(self, ctx, app, x, y, w, h, start, length):
        W.pinstripes(ctx, x, y, w, h, "#f6f6f6", "#ededed")
        ctx.rect(x, y, 1, h)
        ctx.fill("#b9b9b9")
        track_h = h - 2 * w
        ctx.rounded(x + 2, y + 2, w - 4, track_h - 4, (w - 4) / 2)
        ctx.fill(ctx.hgradient(x, x + w, [(0, "#c8c8c8"), (0.3, "#e8e8e8"), (1, "#f7f7f7")]))
        th = max(30, (track_h - 4) * length)
        ty = y + 2 + (track_h - 4 - th) * min(1.0, start / max(1e-6, 1 - length)) if length < 1 else y + 2
        ctx.rounded(x + 2, ty, w - 4, th, (w - 4) / 2)
        ctx.fill(ctx.hgradient(x, x + w, [(0, "#2d68d0"), (0.35, "#80b2f2"), (0.6, "#5b93e6"), (1, "#2c63c6")]))
        ctx.rounded(x + 2.5, ty + 0.5, w - 5, th - 1, (w - 5) / 2)
        ctx.stroke("#22508f", 1)
        ctx.rounded(x + 4, ty + 3, 3, th - 6, 1.5)
        ctx.fill((1, 1, 1, 0.55))
        for i, d in enumerate(("up", "down")):
            ay = y + h - 2 * w + i * w
            ctx.rect(x, ay, w, w)
            ctx.fill(ctx.hgradient(x, x + w, [(0, "#fafafa"), (1, "#dddddd")]))
            ctx.rect(x, ay, w, 1)
            ctx.fill("#a8a8a8")
            W.triangle(ctx, x + w / 2, ay + w / 2, 7, d, "#3a3a3a")

    # -- inspector drawer -------------------------------------------------------------------

    def inspector(self, ctx: Context, app, x, y, w, h):
        W.pinstripes(ctx, x, y, w, h, "#ededed", "#e4e4e4")
        ctx.rect(x, y, 1, h)
        ctx.fill("#8c8c8c")
        ctx.rect(x + 1, y, 1, h)
        ctx.fill((1, 1, 1, 0.8))
        e = app.selected
        if e is None:
            ctx.font(12)
            ctx.text(x + w / 2, y + 50, "No selection", self.subtle, align="center")
            return
        inner_x, inner_w = x + 12, w - 24
        ctx.rounded(inner_x, y + 12, inner_w, 200, 6)
        ctx.fill((1, 1, 1, 0.7))
        ctx.rounded(inner_x + 0.5, y + 12.5, inner_w - 1, 199, 6)
        ctx.stroke("#b8b8b8", 1)
        self.art(ctx, app, e, x + w / 2, y + 24, 150)
        ctx.font(13, bold=True)
        title = ctx.wrap(e.display_title, inner_w - 10, 2)
        ty = y + 196 - (8 if len(title) > 1 else 0)
        for line in title:
            ctx.text(x + w / 2, ty, line, "#000000", align="center")
            ty += 16
        ty = y + 236
        sections = [
            ("General:", [("Kind", e.kind), ("Status", e.status), ("Last played", _date(e.last_played) or "Never")]),
            ("More Info:", [("Publisher", e.publisher), ("Developer", e.developer), ("Genre", e.genre),
                            ("Released", e.year)]),
            ("Vistal:", [("Profile", e.profile.get("title", "") if e.profile else "Generic"),
                         ("Controller", str((e.profile.get("controller") or {}).get("layout", "desktop"))
                          if e.profile else "desktop")]),
        ]
        for title, rows in sections:
            rows = [(k, v) for k, v in rows if v]
            if not rows or ty > y + h - 40:
                continue
            W.triangle(ctx, x + 18, ty - 4, 8, "down", "#4a4a4a")
            ctx.font(12, bold=True)
            ctx.text(x + 28, ty, title, "#000000")
            ty += 20
            ctx.font(11.5)
            for k, v in rows:
                if ty > y + h - 14:
                    break
                ctx.text(x + 100, ty, k + ":", "#4f4f4f", align="right")
                ctx.text(x + 106, ty, v, "#000000", max_width=w - 118)
                ty += 17
            ty += 10

    # -- status bar & dock ------------------------------------------------------------------

    def status_bar(self, ctx: Context, app, x, y, w, h):
        W.pinstripes(ctx, x, y, w, h, "#f0f0f0", "#e5e5e5")
        ctx.rect(x, y, w, 1)
        ctx.fill("#9b9b9b")
        ctx.font(11.5)
        n_inst = sum(1 for e in app.visible if e.installed)
        status = app.busy or f"{len(app.visible)} items, {n_inst} installed"
        ctx.text(x + 14, y + h / 2 + 4, status, "#333333")
        hints = self.hints(app)
        widths = []
        for b, label in hints:
            ctx.font(11)
            widths.append(ctx.text_width(label) + (16 if len(b) == 1 else ctx.text_width(b) + 10) + 20)
        hx = x + w - 12 - sum(widths)
        for (b, label), wd in zip(hints, widths):
            W.pad_hint(ctx, hx, y + h / 2, b, label, "#222222", size=15, font_size=11)
            hx += wd

    def dock(self, ctx: Context, app, w, h):
        games = sorted([e for e in app.entries if e.installed], key=lambda e: e.last_played, reverse=True)[:9]
        if not games:
            return
        size, gap = 44, 10
        dw = len(games) * (size + gap) + gap + 20
        dx, dy = (w - dw) / 2, h - size - 16
        ctx.rounded(dx, dy, dw, size + 14, 8)
        ctx.fill(ctx.vgradient(dy, dy + size + 14, [(0, (1, 1, 1, 0.55)), (1, (1, 1, 1, 0.35))]))
        ctx.rounded(dx + 0.5, dy + 0.5, dw - 1, size + 13, 8)
        ctx.stroke((1, 1, 1, 0.75), 1)
        ix = dx + 10 + gap
        for e in games:
            self.art(ctx, app, e, ix + size / 2, dy + 5, size, shadow=False)
            idx = app.visible.index(e) if e in app.visible else None
            if idx is not None:
                app.hits.add(ix, dy, size, size + 10, ("tile", idx))
            if app.selected is e:
                W.triangle(ctx, ix + size / 2, dy + size + 10, 6, "up", (0, 0, 0, 0.75))
            ix += size + gap

    # -- frame ------------------------------------------------------------------------------

    def draw(self, ctx: Context, app, w, h):
        self.prepare(ctx)
        wx, wy, ww, wh = 10, 8, w - 20, h - 8 - 72

        def backdrop(c, lw, lh):
            self.desktop(c, lw, lh)
            W.drop_shadow(c, wx, wy, ww, wh, radius=7, spread=12, alpha=0.75, dy=6)

        self.cached_layer(ctx, app, "desktop", w, h, backdrop)
        ctx.rounded(wx, wy, ww, wh, 7, br=False, bl=False)
        ctx.fill("#ffffff")
        toolbar_h = 74
        self.title_and_toolbar(ctx, app, wx, wy, ww, toolbar_h)
        body_y = wy + toolbar_h
        status_h = 24
        body_h = wh - toolbar_h - status_h
        side_w = 196
        drawer_w = 270 if ww >= 1000 else 0
        self.sidebar(ctx, app, wx, body_y, side_w, body_h)
        cx, cw = wx + side_w, ww - side_w - drawer_w
        if app.view == "details":
            self.list_header(ctx, app, cx, body_y, cw, 20)
            self.draw_items(ctx, app, cx, body_y + 20, cw, body_h - 20)
        else:
            self.draw_items(ctx, app, cx, body_y, cw, body_h)
        if drawer_w:
            self.inspector(ctx, app, wx + ww - drawer_w, body_y, drawer_w, body_h)
        self.status_bar(ctx, app, wx, body_y + body_h, ww, status_h)
        ctx.rounded(wx + 0.5, wy + 0.5, ww - 1, wh - 1, 7, br=False, bl=False)
        ctx.stroke((0, 0, 0, 0.45), 1)
        self.dock(ctx, app, w, h)
        if app.menu:
            self.draw_menu(ctx, app, app.menu, w, h)
        if app.message:
            self.draw_message(ctx, app, app.message, w, h)

    # -- overlays ----------------------------------------------------------------------------

    def menu_size(self, ctx, menu: Menu):
        ctx.font(13)
        width = max((ctx.text_width(i.label) for i in menu.items if not i.separator), default=100)
        return width + 56, sum(10 if i.separator else 21 for i in menu.items) + 10

    def draw_menu(self, ctx, app, menu: Menu, width, height):
        app.hits.add(0, 0, width, height, ("dismiss",))
        x, y, mw, mh = self.place_menu(ctx, app, menu, width, height)
        W.drop_shadow(ctx, x, y, mw, mh, radius=5, spread=8, alpha=0.5, dy=4)
        ctx.rounded(x, y, mw, mh, 5)
        ctx.fill((1, 1, 1, 0.96))
        ctx.rounded(x + 0.5, y + 0.5, mw - 1, mh - 1, 5)
        ctx.stroke((0, 0, 0, 0.25), 1)
        yy = y + 5
        ctx.font(13)
        for i, item in enumerate(menu.items):
            if item.separator:
                ctx.rect(x + 1, yy + 4.5, mw - 2, 1)
                ctx.fill("#dddddd")
                yy += 10
                continue
            hl = i == menu.sel and item.enabled
            if hl:
                ctx.rect(x, yy, mw, 21)
                ctx.fill(ctx.vgradient(yy, yy + 21, [(0, "#6896e6"), (1, "#2d62cd")]))
            fg = "#ffffff" if hl else ("#000000" if item.enabled else "#9a9a9a")
            if item.checked:
                ctx.move_to(x + 9, yy + 11)
                ctx.line_to(x + 12.5, yy + 15)
                ctx.line_to(x + 18, yy + 6)
                ctx.stroke(fg, 1.8)
            ctx.text(x + 26, yy + 15, item.label, fg)
            if item.enabled:
                app.hits.add(x, yy, mw, 21, ("menuitem", i))
            yy += 21

    def draw_message(self, ctx, app, msg: Message, width, height):
        app.hits.add(0, 0, width, height, ("modal",))
        mw = 470
        ctx.font(12)
        lines = []
        for para in msg.text.split("\n"):
            lines += ctx.wrap(para, mw - 120, 6) if para.strip() else [""]
        lines = lines[:12]
        mh = 92 + len(lines) * 17 + 46
        x, y = (width - mw) / 2, 8 + 74  # sheets drop from under the toolbar
        W.drop_shadow(ctx, x, y, mw, mh, radius=4, spread=10, alpha=0.6, dy=6)
        ctx.rounded(x, y, mw, mh, 4, tl=False, tr=False)
        ctx.fill("#ececec")
        W.pinstripes(ctx, x, y, mw, mh, (0.95, 0.95, 0.95, 0.97), (0.91, 0.91, 0.91, 0.97))
        ctx.rect(x + 0.5, y, mw - 1, mh - 0.5)
        ctx.stroke("#8a8a8a", 1)
        ix, iy = x + 52, y + 50
        if msg.kind == "error":
            ctx.move_to(ix, iy - 28)
            ctx.line_to(ix + 30, iy + 24)
            ctx.line_to(ix - 30, iy + 24)
            ctx.close_path()
            ctx.fill(ctx.vgradient(iy - 28, iy + 24, [(0, "#ffe680"), (1, "#f0a800")]))
            ctx.move_to(ix, iy - 28)
            ctx.line_to(ix + 30, iy + 24)
            ctx.line_to(ix - 30, iy + 24)
            ctx.close_path()
            ctx.stroke("#8a6400", 1.5)
            ctx.font(30, bold=True)
            ctx.text(ix, iy + 18, "!", "#000000", align="center")
        else:
            W.disc_icon(ctx, ix, iy, 28)
        ctx.font(13, bold=True)
        ctx.text(x + 100, y + 32, msg.title, "#000000", max_width=mw - 120)
        ctx.font(12)
        ty = y + 54
        for line in lines:
            ctx.text(x + 100, ty, line, "#1e1e1e")
            ty += 17
        bw = 90
        bx = x + mw - 18 - len(msg.buttons) * (bw + 10) + 10
        for i, label in enumerate(msg.buttons):
            gel_button(ctx, bx, y + mh - 40, bw, 24, label, default=i == msg.sel)
            app.hits.add(bx, y + mh - 40, bw, 24, ("msgbutton", i))
            bx += bw + 10

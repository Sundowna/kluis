"""Home (HANDOVER §3.1): VPN chip, status title, offline world dot map with cloud and "You" pins."""
from __future__ import annotations

import json
import math
import os

from gi.repository import GLib, Gtk

from .. import geo
from ..i18n import _
from .common import a11y, button, hbox, label, set_class, styled, vbox
from .theme import animations_enabled

MAP = json.load(open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "worldmap.json"), encoding="utf-8"))


class WorldMap(Gtk.DrawingArea):
    def __init__(self, app):
        super().__init__(hexpand=True, vexpand=True)
        self.app = app
        self.you = None            # (city, lat, lon)
        self.vpn = False
        self.show_you = True
        self.syncing = False
        self._phase = 0.0
        self._anim = 0
        self.connect("draw", self._draw)
        a11y(self, _("World map"))

    def set_state(self, you, vpn, syncing, show_you=True):
        self.you, self.vpn, self.syncing, self.show_you = you, vpn, syncing, show_you
        if syncing and animations_enabled() and not self._anim:
            self._anim = GLib.timeout_add(50, self._tick)
        self.queue_draw()

    def caption(self) -> str:
        if not self.show_you or not self.you:
            return _("Proton Drive · Zürich")
        return _("You · {c} (VPN)").format(c=self.you[0]) if self.vpn else _("You · {c}").format(c=self.you[0])

    def _tick(self):
        if not self.syncing or not animations_enabled():
            self._anim = 0
            self.queue_draw()
            return False
        self._phase = (self._phase + 0.05) % 1.0
        self.queue_draw()
        return True

    def _proj(self, w, h, lat, lon):
        rows, cols, step = MAP["rows"], MAP["cols"], MAP["step"]
        cell = min(w / cols, h / rows)
        ox, oy = (w - cell * cols) / 2, (h - cell * rows) / 2
        x = ox + (lon - MAP["lon_left"]) / step * cell
        y = oy + (MAP["lat_top"] - lat) / step * cell + cell / 2
        return x, y, cell, ox, oy

    def _draw(self, _w, cr):
        th = self.app.theme
        w, h = self.get_allocated_width(), self.get_allocated_height()
        _x, _y, cell, ox, oy = self._proj(w, h, 0, 0)
        cr.set_source_rgb(*th.color("mapdot"))
        r = max(1.0, cell * 0.28)
        for row, spans in enumerate(MAP["runs"]):
            y = oy + row * cell + cell / 2
            for a, b in spans:
                for c in range(a, b + 1):
                    cr.arc(ox + c * cell + cell / 2, y, r, 0, 2 * math.pi)
                    cr.new_sub_path()
        cr.fill()
        cx, cy, *_rest = self._proj(w, h, geo.CLOUD[1], geo.CLOUD[2])
        accent = th.color("accent")
        if self.show_you and self.you:
            yx, yy, *_rest = self._proj(w, h, self.you[1], self.you[2])
            # arc
            mx, my = (yx + cx) / 2, min(yy, cy) - max(40, abs(yx - cx) * 0.25)
            cr.set_source_rgba(*accent, 0.9)
            cr.set_line_width(2)
            cr.set_dash([6, 6], -self._phase * 12 if self.syncing else 0)
            cr.move_to(yx, yy)
            cr.curve_to(mx, my, mx, my, cx, cy)
            cr.stroke()
            cr.set_dash([])
            # pulse
            if self.syncing and animations_enabled():
                pr = 6 + 14 * self._phase
                cr.set_source_rgba(*accent, 0.5 * (1 - self._phase))
                cr.arc(yx, yy, pr, 0, 2 * math.pi)
                cr.fill()
            cr.set_source_rgb(*accent)
            cr.arc(yx, yy, 6, 0, 2 * math.pi)
            cr.fill()
            self._label(cr, yx, yy, self.caption(), w)
        # cloud pin
        cr.set_source_rgb(*th.color("text"))
        cr.arc(cx, cy, 5, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgb(*accent)
        cr.set_line_width(2)
        cr.arc(cx, cy, 9, 0, 2 * math.pi)
        cr.stroke()
        self._label(cr, cx, cy - 2, _("Proton Drive · Zürich"), w, above=True)

    def _label(self, cr, x, y, text, w, above=False):
        th = self.app.theme
        cr.select_font_face("sans-serif", 0, 1)
        cr.set_font_size(13)
        ext = cr.text_extents(text)
        tx = min(max(8, x + 12), w - ext.width - 16)
        ty = y - 14 if above else y + 22
        cr.set_source_rgba(*th.color("panel"), 0.85)
        _rounded(cr, tx - 6, ty - ext.height - 5, ext.width + 12, ext.height + 10, 6)
        cr.fill()
        cr.set_source_rgb(*th.color("text"))
        cr.move_to(tx, ty)
        cr.show_text(text)


def _rounded(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


class HomePage(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.app = app
        top = Gtk.Box(spacing=12)
        self.chip = button(_("VPN off"), self._open_vpn, "k-chip")
        a11y(self.chip, _("VPN state"))
        self.loc = label("", "k-muted", "k-s13")
        top.pack_start(self.chip, False, False, 0)
        top.pack_start(self.loc, False, False, 0)
        self.top = top
        self.pack_start(top, False, False, 0)
        self.banner = Gtk.Box(spacing=12, no_show_all=True)
        styled(self.banner, "k-banner")
        self.banner_lbl = label("", wrap=True)
        self.banner.pack_start(self.banner_lbl, True, True, 0)
        self.banner_btn = button(_("Sign in again"), lambda: app.sign_in_again(), "suggested-action")
        self.banner.pack_end(self.banner_btn, False, False, 0)
        self.pack_start(self.banner, False, False, 0)
        self.title = label("", "k-h0", wrap=True)
        self.sub = label("", "k-muted", wrap=True)
        a11y(self.title, _("Status"))
        self.pack_start(vbox(self.title, self.sub, spacing=4), False, False, 0)
        self.map = WorldMap(app)
        self.pack_start(self.map, True, True, 0)

    def _open_vpn(self):
        import shutil
        for exe in ("protonvpn-app", "protonvpn"):
            if shutil.which(exe):
                if os.environ.get("KLUIS_TEST") == "1":
                    from .common import OPENED
                    OPENED.append(exe)
                    return
                GLib.spawn_async([shutil.which(exe)], flags=GLib.SpawnFlags.DEFAULT)
                return

    def refresh(self, status, loc):
        """status: status.Status; loc: app.location() -> (place, vpn_on, vpn_country_known)."""
        show = self.app.settings.vpn_view
        place, vpn_on, known = loc
        self.top.set_visible(show)
        if show:
            self.chip.set_label(_("VPN on") if vpn_on else _("VPN off"))
            set_class(self.chip, "k-on", vpn_on)
            if vpn_on and not known:
                self.loc.set_text(_("Location unknown"))
            elif vpn_on:
                self.loc.set_text(_("Showing as {c}").format(c=place[0]))
            else:
                self.loc.set_text(_("Your location {c}").format(c=place[0]) if place else "")
        self.title.set_text(status.title)
        self.sub.set_text(status.subtitle)
        for c in ("k-warn", "k-error"):
            self.sub.get_style_context().remove_class(c)
        if status.tone in ("warn", "error"):
            self.sub.get_style_context().add_class("k-warn" if status.tone == "warn" else "k-error")
        signed_out = self.app.manager.logged_in is False and self.app.settings.onboarded
        self.banner.set_visible(signed_out)
        if signed_out:
            self.banner_lbl.set_text(_("Your Proton Drive session ended. Sign in again to keep syncing."))
            self.banner.show_all()
        self.map.set_state(place, vpn_on and known, status.kind == "syncing", show_you=show)


"""Photos (HANDOVER §3.5): Download/Upload cards (collapsible), virtualised month gallery, month scrubber.

The gallery draws only the visible rows into one viewport-sized area with its own scrollbar, so
50'000 photos stay smooth (a widget as tall as the whole library would exceed X11's 32'767 px limit).
"""
from __future__ import annotations

import collections
import math
import os
import time

from gi.repository import Gdk, GLib, Gtk

from .. import scrubber
from ..cli import PhotoItem
from ..config import PHOTOS_ID
from ..listcache import fetch, shared_lists
from ..i18n import _, ngettext
from ..photos import captured_dt
from ..thumbs import Thumbnailer
from .common import (a11y, button, combo, hbox, label, open_path, open_uri, run_bg, short_path, styled,
                     switch, vbox, wrap_check, wrapbar)
from .dialogs import choose_local_folder
from .theme import animations_enabled

WEB_PHOTOS = "https://drive.proton.me/photos"
TILE, GAP = 132, 8
YEAR_H, MONTH_H = 40, 34
LRU = 1200                      # decoded previews kept in memory (~80 MB)


class CollapsibleCard(Gtk.Box):
    """Header row toggles open/closed (chevron down = closed, up = open); the switch sits outside it."""

    def __init__(self, glyph, title, with_switch=True):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        styled(self, "k-card")
        head = Gtk.Box(spacing=10)
        self.toggle_area = Gtk.EventBox(visible_window=False, can_focus=True)
        a11y(self.toggle_area, _("Expand {t}").format(t=title))
        inner = Gtk.Box(spacing=10)
        inner.pack_start(label(glyph, "k-h3", "k-ok"), False, False, 0)
        inner.pack_start(label(title, "k-h3"), False, False, 0)
        self.status = label("", "k-muted", "k-s13", ellipsize="end")
        inner.pack_start(self.status, True, True, 0)
        self.chev = Gtk.Image.new_from_icon_name("kluis-chevron-down-symbolic", Gtk.IconSize.BUTTON)
        inner.pack_end(self.chev, False, False, 0)
        self.toggle_area.add(inner)
        self.toggle_area.connect("button-release-event", lambda *_: (self.toggle(), True)[1])
        self.toggle_area.connect("key-press-event", self._key)
        head.pack_start(self.toggle_area, True, True, 0)
        self.switch = switch(False, None, title) if with_switch else None
        if self.switch:
            head.pack_end(self.switch, False, False, 0)
        self.pack_start(head, False, False, 0)
        self.rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN,
                                transition_duration=220 if animations_enabled() else 0)
        self.body = vbox(spacing=10, margin_top=12)
        # the settings scroll only when the window is too short to show them (1024×640); at 1440×900
        # everything shows and only the gallery scrolls
        sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True)
        sc.set_min_content_height(72)
        sc.add(self.body)
        self.rev.add(sc)
        self.pack_start(self.rev, False, False, 0)
        self.title = title
        self.on_toggle = None

    def _key(self, _w, ev):
        if ev.keyval in (Gdk.KEY_Return, Gdk.KEY_space, Gdk.KEY_KP_Enter):
            self.toggle()
            return True
        return False

    @property
    def is_open(self):
        return self.rev.get_reveal_child()

    def toggle(self, open_=None):
        o = (not self.is_open) if open_ is None else open_
        self.rev.set_reveal_child(o)
        self.chev.set_from_icon_name("kluis-chevron-up-symbolic" if o else "kluis-chevron-down-symbolic", Gtk.IconSize.BUTTON)
        a11y(self.toggle_area, (_("Collapse {t}") if o else _("Expand {t}")).format(t=self.title))
        if self.on_toggle:
            self.on_toggle(o)


class Layout:
    """Rows of a month-grouped gallery for a given width (pure, cheap to rebuild)."""

    def __init__(self, months, width, view_h=0):
        self.cols = max(1, int((width + GAP) // (TILE + GAP)))
        self.rows = []          # (y, kind, payload) kind: year | month | tiles
        self.offsets = []       # month block tops (heading included), for the scrubber
        y, last_year = 8, None
        for m in months:
            top = y
            if m["year"] != last_year:
                self.rows.append((y, "year", m["year"]))
                y += YEAR_H
                last_year = m["year"]
            self.offsets.append(top)
            self.rows.append((y, "month", m))
            y += MONTH_H
            items = m["items"]
            for i in range(0, len(items), self.cols):
                self.rows.append((y, "tiles", (m, items[i:i + self.cols], i)))
                y += TILE + GAP
            y += 8
        # room after the last month so every month's heading can scroll to the top (F9 step 8)
        self.height = max(y + 8, (self.offsets[-1] if self.offsets else 0) + view_h)
        self._ys = [r[0] for r in self.rows]

    def visible(self, top, bottom):
        import bisect
        i = max(0, bisect.bisect_right(self._ys, top) - 1)
        out = []
        while i < len(self.rows) and self.rows[i][0] < bottom:
            out.append(self.rows[i])
            i += 1
        return out


class Gallery(Gtk.Box):
    def __init__(self, page):
        super().__init__(spacing=6)
        self.page = page
        self.months = []
        self.layout = None
        self.sel: set[str] = set()
        self.focus_idx = 0
        self.flat = []
        self.pix = collections.OrderedDict()
        self.adj = Gtk.Adjustment(value=0, lower=0, upper=1, step_increment=60, page_increment=400, page_size=1)
        self.area = Gtk.DrawingArea(hexpand=True, vexpand=True, can_focus=True)
        self.area.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK |
                             Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        a11y(self.area, _("Gallery"))
        self.area.connect("draw", self._draw)
        self.area.connect("size-allocate", lambda *_: self.relayout())
        self.area.connect("scroll-event", self._scroll)
        self.area.connect("button-press-event", self._press)
        self.area.connect("key-press-event", self._keys)
        self.adj.connect("value-changed", lambda *_: (self.area.queue_draw(), self.scrub.queue_draw(),
                                                     self._request_visible()))
        self.sb = Gtk.Scrollbar(orientation=Gtk.Orientation.VERTICAL, adjustment=self.adj)
        a11y(self.sb, _("Gallery scrollbar"))
        self.scrub = Gtk.DrawingArea(width_request=118)
        self.scrub.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        a11y(self.scrub, _("Month scrubber"))
        self.scrub.connect("draw", self._draw_scrub)
        self.scrub.connect("button-press-event", self._scrub_press)
        self.pack_start(self.area, True, True, 0)
        self.pack_start(self.sb, False, False, 0)
        self.pack_start(self.scrub, False, False, 0)
        self._anim = 0

    # ---------- data ----------
    def set_photos(self, items, keep_scroll=False):
        groups = collections.OrderedDict()
        for p in items:
            dt = captured_dt(p)
            key = (dt.year, dt.month) if dt else (0, 0)
            groups.setdefault(key, []).append(p)
        months = []
        for (y, mo), ps in sorted(groups.items(), reverse=True):
            name = time.strftime("%B", time.strptime(str(mo), "%m")) if mo else _("Unknown date")
            months.append({"year": str(y) if y else "", "label": f"{name} {y}" if y else name,
                           "short": f"{name[:3]} {y}" if y else "?", "items": ps})
        self.months = months
        self.flat = [p for m in months for p in m["items"]]
        self.sel = {u for u in self.sel if any(p.uid == u for p in self.flat)}
        top = self.adj.get_value()
        self.relayout()
        self.adj.set_value(min(top, self.adj.get_upper()) if keep_scroll else 0)
        self.page.sel_changed()

    def relayout(self):
        w = self.area.get_allocated_width()
        if w <= 1:
            return
        h = self.area.get_allocated_height()
        self.layout = Layout(self.months, w, h)
        self.adj.configure(min(self.adj.get_value(), max(0, self.layout.height - h)), 0, self.layout.height, 60,
                           max(h - 60, 60), h)
        self.area.queue_draw()
        self.scrub.queue_draw()
        self._request_visible()

    def month_count(self):
        return len(self.months)

    # ---------- scrolling ----------
    def _scroll(self, _w, ev):
        ok, dx, dy = ev.get_scroll_deltas()
        if not ok:
            dy = {Gdk.ScrollDirection.UP: -1, Gdk.ScrollDirection.DOWN: 1}.get(ev.direction, 0)
        self.scroll_by(dy * 60)
        return True

    def scroll_by(self, d):
        v = self.adj.get_value() + d
        self.adj.set_value(max(0, min(v, self.adj.get_upper() - self.adj.get_page_size())))

    def ring(self):
        if not self.layout or len(self.months) < 2:
            return 0.0
        return scrubber.ring_position(self.adj.get_value(), self.adj.get_page_size(), self.layout.height,
                                      self.layout.offsets)

    def jump(self, i):
        if not self.layout:
            return
        target = scrubber.scroll_for_dot(i, self.adj.get_page_size(), self.layout.height, self.layout.offsets)
        if not animations_enabled():
            self.adj.set_value(target)
            return
        start, t0 = self.adj.get_value(), time.monotonic()
        if self._anim:
            GLib.source_remove(self._anim)

        def step():
            t = min(1.0, (time.monotonic() - t0) / 0.25)
            e = 1 - (1 - t) ** 3
            self.adj.set_value(start + (target - start) * e)
            if t >= 1:
                self._anim = 0
                return False
            return True
        self._anim = GLib.timeout_add(16, step)

    def top_month(self):
        """Index of the month whose heading is at (or just above) the top of the viewport."""
        import bisect
        if not self.layout:
            return 0
        return max(0, bisect.bisect_right(self.layout.offsets, self.adj.get_value() + 1) - 1)

    # ---------- hit testing ----------
    def _tile_at(self, x, y):
        if not self.layout:
            return None
        yy = y + self.adj.get_value()
        for ry, kind, payload in self.layout.visible(yy - TILE, yy + 1):
            if kind == "tiles" and ry <= yy < ry + TILE:
                col = int((x - 8) // (TILE + GAP))
                m, items, _start = payload
                if 0 <= col < len(items) and (x - 8) - col * (TILE + GAP) < TILE:
                    return items[col]
        return None

    def _press(self, _w, ev):
        self.area.grab_focus()
        p = self._tile_at(ev.x, ev.y)
        if not p:
            return False
        if ev.type == Gdk.EventType._2BUTTON_PRESS:
            self.page.open_photo(p)
        elif ev.type == Gdk.EventType.BUTTON_PRESS and ev.button == 1:
            self.toggle(p.uid)
            self.focus_idx = self.flat.index(p)
        return True

    def toggle(self, uid):
        (self.sel.discard if uid in self.sel else self.sel.add)(uid)
        self.area.queue_draw()
        self.page.sel_changed()

    def _keys(self, _w, ev):
        k = ev.keyval
        if not self.flat:
            return False
        cols = self.layout.cols if self.layout else 1
        moves = {Gdk.KEY_Right: 1, Gdk.KEY_Left: -1, Gdk.KEY_Down: cols, Gdk.KEY_Up: -cols}
        if k in moves:
            self.focus_idx = max(0, min(len(self.flat) - 1, self.focus_idx + moves[k]))
            self._reveal(self.focus_idx)
            self.area.queue_draw()
            return True
        if k == Gdk.KEY_space:
            self.toggle(self.flat[self.focus_idx].uid)
            return True
        if k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.page.open_photo(self.flat[self.focus_idx])
            return True
        if k in (Gdk.KEY_Page_Down, Gdk.KEY_Page_Up):
            self.scroll_by(self.adj.get_page_increment() * (1 if k == Gdk.KEY_Page_Down else -1))
            return True
        return False

    def _reveal(self, idx):
        p = self.flat[idx]
        for ry, kind, payload in self.layout.rows:
            if kind == "tiles" and p in payload[1]:
                v, h = self.adj.get_value(), self.adj.get_page_size()
                if ry < v:
                    self.adj.set_value(ry - MONTH_H)
                elif ry + TILE > v + h:
                    self.adj.set_value(ry + TILE - h + GAP)
                return

    # ---------- previews ----------
    def _request_visible(self):
        if not self.layout:
            return
        v, h = self.adj.get_value(), self.adj.get_page_size()
        local = self.page.local_paths()
        for _y, kind, payload in self.layout.visible(v - TILE * 2, v + h + TILE * 2):
            if kind == "tiles":
                for p in payload[1]:
                    if p.uid not in self.pix:
                        lp = local.get(p.uid)
                        self.page.thumbs.request(p, lp if lp and os.path.exists(lp) else None)

    def preview_ready(self, uid, pb):
        self.pix[uid] = pb
        self.pix.move_to_end(uid)
        while len(self.pix) > LRU:
            self.pix.popitem(last=False)
        self.area.queue_draw()

    # ---------- drawing ----------
    def _draw(self, _w, cr):
        th = self.page.app.theme
        if not self.layout:
            return
        v = self.adj.get_value()
        h = self.area.get_allocated_height()
        cr.select_font_face("sans-serif", 0, 1)
        focused = self.flat[self.focus_idx] if self.flat and self.area.has_focus() else None
        for ry, kind, payload in self.layout.visible(v - TILE, v + h):
            y = ry - v
            if kind == "year":
                cr.set_source_rgb(*th.color("text"))
                cr.set_font_size(20)
                cr.move_to(8, y + 28)
                cr.show_text(payload)
            elif kind == "month":
                cr.set_source_rgb(*th.color("muted"))
                cr.set_font_size(13)
                cr.move_to(8, y + 22)
                n = len(payload["items"])
                cr.show_text(ngettext("{m} · {n} item", "{m} · {n} items", n).format(m=payload["label"], n=n))
            else:
                _m, items, _start = payload
                for col, p in enumerate(items):
                    x = 8 + col * (TILE + GAP)
                    self._tile(cr, th, x, y, p, p.uid in self.sel, p is focused)

    def _tile(self, cr, th, x, y, p, selected, focused):
        _rr(cr, x, y, TILE, TILE, 8)
        cr.set_source_rgb(*th.color("surface"))
        cr.fill_preserve()
        cr.save()
        cr.clip()
        pb = self.pix.get(p.uid)
        if pb is not None:
            Gdk.cairo_set_source_pixbuf(cr, pb, x + (TILE - pb.get_width()) / 2, y + (TILE - pb.get_height()) / 2)
            cr.paint()
        else:
            cr.set_source_rgb(*th.color("muted"))
            cr.set_font_size(11)
            name = p.name if len(p.name) < 18 else p.name[:16] + "…"
            ext = cr.text_extents(name)
            cr.move_to(x + (TILE - ext.width) / 2, y + TILE / 2 + 4)
            cr.show_text(name)
        cr.restore()
        if p.is_video:
            cr.set_source_rgba(0, 0, 0, 0.6)
            _rr(cr, x + TILE - 30, y + TILE - 24, 24, 18, 5)
            cr.fill()
            cr.set_source_rgb(1, 1, 1)          # ▶ drawn as a path: no font glyph needed
            cr.move_to(x + TILE - 22, y + TILE - 20)
            cr.line_to(x + TILE - 13, y + TILE - 15)
            cr.line_to(x + TILE - 22, y + TILE - 10)
            cr.close_path()
            cr.fill()
        if selected or focused:
            _rr(cr, x + 1, y + 1, TILE - 2, TILE - 2, 8)
            cr.set_source_rgb(*th.color("accent"))
            cr.set_line_width(3 if selected else 2)
            cr.stroke()
        if selected:
            cr.set_source_rgb(*th.color("accent"))
            cr.arc(x + TILE - 14, y + 14, 10, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgb(*th.color("on_accent"))   # ✓ drawn as a path
            cr.set_line_width(2.2)
            cr.move_to(x + TILE - 19, y + 14)
            cr.line_to(x + TILE - 15, y + 18)
            cr.line_to(x + TILE - 9, y + 10)
            cr.stroke()

    def _scrub_geom(self):
        h = self.scrub.get_allocated_height()
        top, bottom = 22, h - 22
        n = len(self.months)
        return top, bottom, n, (bottom - top) / (n - 1) if n > 1 else 0

    def _draw_scrub(self, _w, cr):
        th = self.page.app.theme
        if len(self.months) < 2:
            return
        top, bottom, n, gap = self._scrub_geom()
        x = 70
        cr.select_font_face("sans-serif", 0, 1)
        pos = self.ring()
        ry = top + pos * gap
        cr.set_line_width(2)
        cr.set_source_rgb(*th.color("line"))
        cr.move_to(x, top)
        cr.line_to(x, bottom)
        cr.stroke()
        cr.set_source_rgb(*th.color("accent"))
        cr.move_to(x, top)
        cr.line_to(x, ry)
        cr.stroke()
        cr.select_font_face("sans-serif", 0, 1)
        cr.set_font_size(11)
        last_year = None
        for i, m in enumerate(self.months):
            y = top + i * gap
            cr.set_source_rgb(*(th.color("accent") if i <= pos else th.color("mapdot")))
            cr.arc(x, y, 3, 0, 2 * math.pi)
            cr.fill()
            if m["year"] != last_year:
                last_year = m["year"]
                cr.set_source_rgb(*th.color("muted"))
                cr.move_to(x + 8, y + 4)
                cr.show_text(m["year"])
        cr.set_source_rgb(*th.color("accent"))
        cr.set_line_width(2)
        cr.arc(x, ry, 7, 0, 2 * math.pi)
        cr.stroke()
        lab = self.months[min(int(pos + 0.5), n - 1)]["short"]
        ext = cr.text_extents(lab)
        cr.set_source_rgb(*th.color("text"))
        cr.move_to(x - 12 - ext.width, ry + 4)
        cr.show_text(lab)

    def _scrub_press(self, _w, ev):
        if len(self.months) < 2:
            return False
        top, _bottom, n, gap = self._scrub_geom()
        i = int(round((ev.y - top) / gap)) if gap else 0
        self.jump(max(0, min(n - 1, i)))
        return True


def _rr(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


class PhotosPage(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.app = app
        ps = app.settings.photos
        self.thumbs = Thumbnailer(app.cli, self._preview_ready)
        self.thumbs.remote_enabled = ps.remote_previews
        self.loaded = False
        self.album = ""
        self._local = None

        # --- Download card
        self.down = CollapsibleCard("↓", _("Download"))
        a11y(self.down.switch, _("Download my photos to this computer"))
        self.down.switch.set_active(ps.download)
        self.down.switch.connect("notify::active", lambda s, _p: self._toggle("download", s.get_active()))
        self.down_path = self._path_button(lambda: self._open_dir(ps.download_dir), _("Open download folder"))
        self.down.body.pack_start(label(_("New photos from your phone appear here automatically, sorted into folders."),
                                        "k-muted", "k-s13", wrap=True, max_chars=20), False, False, 0)
        self.down.body.pack_start(hbox(self.down_path, button(_("Change…"), self._pick_download, "k-small",
                                                              name=_("Change download folder"))), False, False, 0)
        self.layout_combo = combo([("month", _("Folders by month (2026 / 2026-11)")),
                                   ("year", _("Folders by year (2026)")), ("flat", _("All in one folder"))],
                                  ps.layout, lambda v: self._set("layout", v), _("Folder layout"), max_chars=14)
        self.down.body.pack_start(self.layout_combo, False, False, 0)
        self.albums_chk = Gtk.CheckButton(label=_("Also save albums as folders (Albums/…)"), active=ps.albums)
        a11y(self.albums_chk, _("Also save albums as folders"))
        self.albums_chk.connect("toggled", lambda c: self._set("albums", c.get_active()))
        self.trash_chk = Gtk.CheckButton(label=_("If a photo is deleted in Proton, move my copy to the Trash"),
                                         active=ps.remove_deleted)
        a11y(self.trash_chk, _("If a photo is deleted in Proton, move my copy to the Trash"))
        self.trash_chk.connect("toggled", lambda c: self._set("remove_deleted", c.get_active()))
        self.down.body.pack_start(wrap_check(self.albums_chk, 20), False, False, 0)
        self.down.body.pack_start(wrap_check(self.trash_chk, 20), False, False, 0)

        # --- Upload card
        self.up = CollapsibleCard("↑", _("Upload"))
        a11y(self.up.switch, _("Add photos from this computer"))
        self.up.switch.set_active(ps.upload)
        self.up.switch.connect("notify::active", lambda s, _p: self._toggle("upload", s.get_active()))
        self.up_path = self._path_button(lambda: self._open_dir(ps.upload_dir) if ps.upload_dir else self._pick_upload(),
                                         _("Open upload folder"))
        self.up.body.pack_start(label(_("New photos and videos in a folder (e.g. a camera import folder) are added to "
                                        "Proton Photos. Ones already there are skipped."), "k-muted", "k-s13",
                                      wrap=True), False, False, 0)
        self.up.body.pack_start(hbox(self.up_path, button(_("Change…"), self._pick_upload, "k-small",
                                                          name=_("Change upload folder"))), False, False, 0)
        self.up.body.pack_start(label(_("Photos you downloaded above are never uploaded again."), "k-muted",
                                      "k-s12", wrap=True, max_chars=20), False, False, 0)
        cards = Gtk.Box(spacing=12, homogeneous=True)
        for c in (self.down, self.up):
            c.set_valign(Gtk.Align.START)          # an open card doesn't stretch the closed one
        cards.pack_start(self.down, True, True, 0)
        cards.pack_start(self.up, True, True, 0)
        self.pack_start(cards, False, False, 0)

        # --- toolbar (wraps onto two rows when narrow)
        self.album_combo = combo([("", _("All photos"))], "", self._album_changed, _("Album"), max_chars=14)
        self.sel_lbl = label("", "k-muted", "k-s13")
        self.open_btn = button(_("Open"), self._open_selected)
        self.dl_btn = button(_("↓ Download selected"), self._download_selected, "suggested-action")
        self.prev_sw = switch(ps.remote_previews, self._toggle_previews, _("Previews for all photos"),
                              tooltip=_("Photos not saved on this computer are fetched once; a small preview is kept "
                                        "and the original deleted. Videos over 60 MB are skipped."))
        # the timeline on screen may be the kept one: say quietly that Kluis is checking, or since when it's offline
        self.fresh_lbl = label("", "k-muted", "k-s12", ellipsize="end")
        a11y(self.fresh_lbl, _("Timeline freshness"))
        bar = wrapbar(label(_("Gallery"), "k-h3"), self.album_combo, self.sel_lbl, self.open_btn, self.dl_btn,
                      self.fresh_lbl)
        self.pack_start(bar, False, False, 0)

        # --- gallery
        self.gallery = Gallery(self)
        self.gstack = Gtk.Stack()
        self.gstack.add_named(self.gallery, "gallery")
        self.wait = label(_("Reading your timeline…"), "k-muted", xalign=0.5)
        self.gstack.add_named(vbox(Gtk.Spinner(active=True), self.wait, valign=Gtk.Align.CENTER), "loading")
        self.gmsg = label("", "k-muted", xalign=0.5, wrap=True)
        empty = vbox(label(_("See your photo timeline"), "k-h2", xalign=0.5),
                     self.gmsg, hbox(button(_("Show my photos"), self.load, "suggested-action"),
                                     button(_("See your photo timeline"), lambda: open_uri(WEB_PHOTOS)),
                                     halign=Gtk.Align.CENTER), spacing=6, valign=Gtk.Align.CENTER)
        self.gstack.add_named(empty, "msg")
        self.pack_start(self.gstack, True, True, 0)
        foot = Gtk.Box(spacing=12)
        foot.pack_start(label(_("Click to select (several at once is fine) · double-click opens a photo · previews "
                                "are made on this computer"), "k-muted", "k-s12", wrap=True), True, True, 0)
        foot.pack_end(button(_("Open on the web"), lambda: open_uri(WEB_PHOTOS), "k-link"), False, False, 0)
        foot.pack_end(hbox(label(_("Previews for all photos"), "k-muted", "k-s12"), self.prev_sw, spacing=6),
                      False, False, 0)
        self.pack_start(foot, False, False, 0)
        self._labels()
        self.refresh_status()
        self.sel_changed()

    @staticmethod
    def _path_button(cb, name):
        """A link-style button whose own label ellipsizes long paths (it never widens the window)."""
        from gi.repository import Pango
        b = Gtk.Button()
        lb = Gtk.Label(ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=48, xalign=0)
        b.add(lb)
        b.kluis_label = lb
        styled(b, "k-link")
        b.set_tooltip_text(_("Open in file manager"))
        b.connect("clicked", lambda *_a: cb())
        return a11y(b, name)

    # ---------- settings ----------
    def _set(self, key, value):
        ps = self.app.settings.photos
        if getattr(ps, key) == value:
            return
        setattr(ps, key, value)
        self.app.settings.save()
        self.app.manager.photos_changed()
        self.refresh_status()

    def _labels(self):
        ps = self.app.settings.photos
        self.down_path.kluis_label.set_text(short_path(ps.download_dir or self._default_download_dir()))
        self.up_path.kluis_label.set_text(short_path(ps.upload_dir) if ps.upload_dir else _("No folder chosen yet"))

    def _default_download_dir(self):
        pics = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) or os.path.expanduser("~/Pictures")
        return os.path.join(pics, "Proton Photos")

    def _open_dir(self, path):
        path = path or self._default_download_dir()
        os.makedirs(path, exist_ok=True)
        open_path(path)

    def _toggle(self, which, on):
        ps = self.app.settings.photos
        if which == "download":
            if on and not ps.download_dir:
                ps.download_dir = self._default_download_dir()
                os.makedirs(ps.download_dir, exist_ok=True)
            ps.download = on
        else:
            if on and not ps.upload_dir:
                p = choose_local_folder(self.get_toplevel(), _("Add photos from which folder?"),
                                        GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES))
                if not p:
                    self.up.switch.set_active(False)
                    return
                ps.upload_dir = p
            ps.upload = on
        self.app.settings.save()
        self._labels()
        self.app.manager.photos_changed()
        self.refresh_status()

    def _pick_download(self):
        ps = self.app.settings.photos
        p = choose_local_folder(self.get_toplevel(), _("Save photos to…"), ps.download_dir or self._default_download_dir())
        if p:
            ps.download_dir = p
            self.app.settings.save()
            self._labels()
            self.app.manager.photos_changed(reset=True)

    def _pick_upload(self):
        ps = self.app.settings.photos
        p = choose_local_folder(self.get_toplevel(), _("Add photos from…"), ps.upload_dir)
        if p:
            if p != ps.upload_dir:
                ps.added = ps.skipped = 0       # the counters belong to one upload folder
            ps.upload_dir = p
            if not ps.upload:
                ps.upload = True
                self.up.switch.set_active(True)
            self.app.settings.save()
            self._labels()
            self.app.manager.photos_changed()

    def refresh_status(self, reload=False):
        ps = self.app.settings.photos
        st = self.app.manager.status.get(PHOTOS_ID)
        busy = st and st.state in ("syncing", "queued")
        if not ps.download:
            d = _("Off")
        elif busy:
            d = st.text or _("Syncing…")
        elif ps.last_sync:
            n = len(self.app.manager.store.photos_downloaded())
            d = _("{n} photos saved · last {t}").format(n=n, t=time.strftime("%H:%M", time.localtime(ps.last_sync)))
        else:
            d = _("Waiting for first sync")
        if not ps.upload:
            u = _("Off") if ps.upload_dir else _("No folder chosen yet")
        elif busy:
            u = st.text or _("Syncing…")
        elif ps.last_sync:
            u = _("{a} new added · {s} skipped (already in Proton Photos)").format(a=ps.added, s=ps.skipped)
        else:
            u = _("Waiting for first sync")
        if st and st.state == "error":
            d = u = st.text
        self.down.status.set_text(d)
        self.up.status.set_text(u)
        self._local = None
        if reload and self.loaded:
            self.load()

    # ---------- gallery ----------
    def local_paths(self):
        if self._local is None:
            ps = self.app.settings.photos
            root = ps.download_dir
            self._local = {k: os.path.join(root, rel) for k, rel in
                           self.app.manager.store.photos_downloaded().items()} if root else {}
        return self._local

    def on_shown(self):
        if not self.loaded:
            self.load()

    def load(self):
        """The kept timeline (or album) at once, then Proton's answer in the background (kluis/listcache.py)."""
        self.loaded = True
        album = self.album
        key = f"album:{album}" if album else "timeline"
        lc = shared_lists(self.app)
        if lc.get(key, PhotoItem) is None:
            self.wait.set_text(_("Reading your timeline…"))
            self.gstack.set_visible_child_name("loading")
        shown = {"any": False}

        def show(items, kept):
            if album != self.album:
                return
            self.fresh_lbl.set_text(_("Checking Proton Drive…") if kept else "")
            if items is None:
                return
            first = not shown["any"]
            shown["any"] = True
            if first:
                self.thumbs.reset()
                self.gallery.pix.clear()
            photos = [p for p in items if p.type == "photo"]
            if not photos:
                self.gmsg.set_text(_("No photos here yet."))
                self.gstack.set_visible_child_name("msg")
                return
            self.gstack.set_visible_child_name("gallery")
            self.gallery.set_photos(photos, keep_scroll=not first)

        def fail(e, kept_shown):
            if album != self.album:
                return
            if kept_shown:
                self.fresh_lbl.set_text(_("Couldn't check Proton Drive · timeline from {t}").format(
                    t=time.strftime("%d.%m. %H:%M", time.localtime(when))))
                return
            self.fresh_lbl.set_text("")
            self.gmsg.set_text(_("Couldn't read your photos: {e}").format(e=e))
            self.gstack.set_visible_child_name("msg")

        def show_albums(albums, _kept):
            if albums is None or album != self.album:
                return
            cur = self.album_combo.get_active_id() or ""
            self._suspend = True
            self.album_combo.remove_all()
            self.album_combo.append("", _("All photos"))
            for a in albums:
                if a.type == "album":
                    self.album_combo.append(a.uid, a.name)
            self.album_combo.set_active_id(cur)
            self._suspend = False

        when = fetch(self.app, key, PhotoItem,
                     (lambda: self.app.cli.album_photos(album)) if album else self.app.cli.photo_timeline, show, fail)
        if not album:
            fetch(self.app, "albums", PhotoItem, self.app.cli.albums, show_albums, lambda _e, _k: None)

    def _album_changed(self, aid):
        if getattr(self, "_suspend", False):
            return
        aid = aid or ""
        if aid != self.album and self.loaded:
            self.album = aid
            self.load()

    def _preview_ready(self, uid, pixbuf):
        self.gallery.preview_ready(uid, pixbuf)

    def _toggle_previews(self, on):
        ps = self.app.settings.photos
        ps.remote_previews = on
        self.app.settings.save()
        self.thumbs.remote_enabled = on
        self.gallery._request_visible()

    def selected(self):
        return [p for p in self.gallery.flat if p.uid in self.gallery.sel]

    def sel_changed(self):
        n = len(self.gallery.sel)
        self.sel_lbl.set_text(ngettext("{n} selected", "{n} selected", n).format(n=n) if n else "")
        self.open_btn.set_sensitive(n == 1)
        self.dl_btn.set_sensitive(n > 0)

    def _open_selected(self):
        s = self.selected()
        if len(s) == 1:
            self.open_photo(s[0])

    def open_photo(self, p):
        lp = self.local_paths().get(p.uid)
        if lp and os.path.exists(lp):
            open_path(lp)
            return
        cache = os.path.join(GLib.get_user_cache_dir(), "kluis", "photos", p.uid.replace("~", "_"))
        os.makedirs(cache, exist_ok=True)
        self.app.toast(_("Opening {n}…").format(n=p.name))

        def done(_s):
            files = sorted(os.listdir(cache))
            if files:
                open_path(os.path.join(cache, files[0]))
        run_bg(lambda: self.app.cli.photo_download([p.uid], cache, "remove"), done,
               lambda e: self.app.toast(_("Couldn't open the photo: {e}").format(e=e)))

    def _download_selected(self):
        photos = self.selected()
        if not photos:
            return
        ps = self.app.settings.photos
        dest = ps.download_dir or self._default_download_dir()
        os.makedirs(dest, exist_ok=True)
        self.app.toast(ngettext("Downloading {n} photo…", "Downloading {n} photos…", len(photos)).format(n=len(photos)))

        def done(s):
            self.app.manager.log("ok", PHOTOS_ID, ngettext("Downloaded {n} photo", "Downloaded {n} photos",
                                                           s.transferred).format(n=s.transferred),
                                 _("to {d}").format(d=short_path(dest)))
            self.app.toast(ngettext("Downloaded {n} photo", "Downloaded {n} photos", s.transferred).format(
                n=s.transferred), (_("Show in folder"), lambda: open_path(dest)))
            self.gallery.sel.clear()
            self.gallery.area.queue_draw()
            self.sel_changed()
        run_bg(lambda: self.app.cli.photo_download([p.uid for p in photos], dest, "rename"), done,
               lambda e: self.app.toast(_("Download failed: {e}").format(e=e)))


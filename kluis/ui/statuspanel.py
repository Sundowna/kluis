"""Status panel (HANDOVER §4.3): Proton-VPN-style, bottom of Main on every tab.

On Browse and Photos it is one compact line (same contents side by side, slim graph) so the file lists get the
room; the chevron at its right end switches between the line and the full card (Walter, 2026-11-26)."""
from __future__ import annotations

import time

from gi.repository import Gtk, Pango

from ..i18n import _
from ..status import axis_max, duration_text, eta_text, human_bytes
from .common import a11y, label, set_class, styled, vbox

COMPACT_TABS = ("browse", "photos")


class Graph(Gtk.DrawingArea):
    def __init__(self, app):
        super().__init__(height_request=72, hexpand=True)
        self.app = app
        self.connect("draw", self._draw)
        a11y(self, _("Current transfer graph"))

    def _draw(self, _w, cr):
        th = self.app.theme
        w, h = self.get_allocated_width(), self.get_allocated_height()
        samples = list(self.app.manager.samples)
        ups = [u / 1000 for u, _d in samples]
        downs = [d / 1000 for _u, d in samples]
        top = axis_max(ups + downs)
        slim = h < 40                     # compact panel: lines only, the numbers are next to it
        left, pad = (0, 3) if slim else (26, 6)
        cr.select_font_face("sans-serif", 0, 0)
        cr.set_font_size(10)
        for frac, txt in ((0, "0"), (0.5, f"{top / 2:.0f}"), (1, f"{top:.0f}")):
            y = h - pad - frac * (h - 2 * pad)
            if not slim:
                cr.set_source_rgb(*th.color("muted"))
                cr.move_to(0, y + 3)
                cr.show_text(txt)
            cr.set_source_rgba(*th.color("line"), 0.8)
            cr.set_line_width(1)
            cr.set_dash([3, 4])
            cr.move_to(left, y)
            cr.line_to(w, y)
            cr.stroke()
        cr.set_dash([])

        def line(vals, color, dashed):
            if not vals:
                return
            n = len(vals)
            cr.set_source_rgb(*color)
            cr.set_line_width(2)
            cr.set_dash([5, 4] if dashed else [])
            for i, v in enumerate(vals):
                x = left + (w - left) * i / max(n - 1, 1)
                y = h - pad - min(v / top, 1) * (h - 2 * pad)
                (cr.line_to if i else cr.move_to)(x, y)
            cr.stroke()
            cr.set_dash([])
        line(downs, th.color("accent"), False)
        line(ups, th.color("upload"), True)


class StatusPanel(Gtk.Box):
    def __init__(self, app):
        super().__init__(spacing=16)
        self.app = app
        self.compact = False
        self.tab = ""
        self.user_full: set[str] = set()      # compact tabs the user opened to the full card (this session)
        left = vbox(spacing=6)
        self.left = left
        self.head = label("", "k-h3", ellipsize="end", max_chars=34)
        a11y(self.head, _("Sync state"))
        left.pack_start(self.head, False, False, 0)
        grid = Gtk.Grid(column_spacing=16, row_spacing=6, column_homogeneous=True)
        self.cells = {}
        self.grid = grid

        def cell(key, title, col, row, bar=False):
            t = label(title, "k-muted", "k-s12")
            v = label("", "k-bold", "k-num", ellipsize="end")
            a11y(v, title)
            box = vbox(t, v, spacing=2)
            pb = None
            if bar:
                pb = Gtk.ProgressBar()
                pb.set_size_request(72, -1)
                box.pack_start(pb, False, False, 2)
            grid.attach(box, col, row, 1, 1)
            self.cells[key] = (box, t, v, pb)
        cell("enc", _("Encryption"), 0, 0)
        cell("space", _("Space used"), 1, 0, bar=True)
        cell("prog", _("Last run"), 0, 1, bar=True)
        cell("today", _("Total today"), 1, 1)
        self.cells["enc"][2].set_text(_("End to end"))
        left.pack_start(grid, False, False, 0)
        self.pack_start(left, False, False, 0)
        right = vbox(spacing=4)
        top = Gtk.Box(spacing=12)
        self.graph_title = label(_("Current transfer (KB/s)"), "k-muted", "k-s12", ellipsize="end")
        top.pack_start(self.graph_title, True, True, 0)
        self.rates = label("", "k-num", "k-s12", ellipsize="end")
        top.pack_end(self.rates, False, False, 0)
        right.pack_start(top, False, False, 0)
        self.graph = Graph(app)
        right.pack_start(self.graph, True, True, 0)
        self.right, self.top = right, top
        self.pack_start(right, True, True, 0)
        self.toggle = Gtk.Button()
        self.toggle_img = Gtk.Image()
        self.toggle.add(self.toggle_img)
        styled(self.toggle, "k-flat")
        self.toggle.set_valign(Gtk.Align.CENTER)
        self.toggle.connect("clicked", lambda *_: self._flip())
        self.toggle.set_no_show_all(True)
        self.pack_end(self.toggle, False, False, 0)
        # §6: the CLI has no quota command, so "Space used" is hidden (never faked)
        self.cells["space"][0].set_no_show_all(True)
        self.cells["space"][0].hide()

    # ---------- compact line ----------
    def set_tab(self, key):
        self.tab = key
        self.toggle.set_visible(key in COMPACT_TABS)
        self.toggle_img.show()
        self.set_compact(key in COMPACT_TABS and key not in self.user_full)

    def _flip(self):
        if self.compact:
            self.user_full.add(self.tab)
        else:
            self.user_full.discard(self.tab)
        self.set_compact(not self.compact)

    def set_compact(self, on):
        self.compact = on
        H, V = Gtk.Orientation.HORIZONTAL, Gtk.Orientation.VERTICAL
        self.left.set_orientation(H if on else V)
        self.left.set_spacing(12 if on else 6)
        self.head.set_max_width_chars(26 if on else 34)
        # one line: the hidden "Space used" cell goes last, so it leaves no gap (it must fit 1024 px wide)
        places = ({"enc": (0, 0), "prog": (1, 0), "today": (2, 0), "space": (3, 0)} if on else
                  {"enc": (0, 0), "space": (1, 0), "prog": (0, 1), "today": (1, 1)})
        for key, (col, row) in places.items():
            box = self.cells[key][0]
            self.grid.child_set_property(box, "left-attach", col)
            self.grid.child_set_property(box, "top-attach", row)
            box.set_orientation(H if on else V)
            box.set_spacing(4 if on else 2)
            # one line on a narrow window: labels may shorten with "…" instead of widening the window
            for lb in self.cells[key][1:3]:
                lb.set_ellipsize(Pango.EllipsizeMode.END)
                lb.set_width_chars(4 if on else -1)
            pb = self.cells[key][3]
            if pb is not None:
                pb.set_valign(Gtk.Align.CENTER)
                pb.set_size_request(36 if on else 72, -1)
        self.grid.set_column_homogeneous(not on)
        self.grid.set_column_spacing(10 if on else 16)
        self.graph_title.set_visible(not on)
        self.set_spacing(10 if on else 16)
        self.right.set_spacing(8 if on else 4)
        self.right.set_orientation(H if on else V)
        self.right.reorder_child(self.graph, 0 if on else 1)
        self.graph.set_size_request(-1, 24 if on else 72)
        self.graph.set_valign(Gtk.Align.CENTER if on else Gtk.Align.FILL)
        self.toggle_img.set_from_icon_name("kluis-chevron-up-symbolic" if on else "kluis-chevron-down-symbolic",
                                           Gtk.IconSize.BUTTON)
        name = _("Show the full status panel") if on else _("Make the status panel one line")
        self.toggle.set_tooltip_text(name)
        a11y(self.toggle, name)
        parent = self.get_parent()
        if parent is not None:
            set_class(parent, "k-panel-compact", on)
        self.graph.queue_draw()

    def refresh(self, st):
        m = self.app.manager
        now = time.time()
        if st.kind == "paused":
            head = _("🔒 Paused • paused {t}").format(t=time.strftime("%H:%M", time.localtime(m.state_since)))
        elif st.kind == "syncing":
            head = _("🔒 Syncing • started {t}").format(t=time.strftime("%H:%M", time.localtime(m.run_started or now)))
        elif st.kind == "problems":
            head = _("🔒 Needs attention • {t}").format(t=st.title)
        else:
            head = _("🔒 In sync • for {d}").format(d=duration_text(now - m.state_since))
        self.head.set_text(head)
        self.head.set_tooltip_text(head)
        _box, t, v, pb = self.cells["prog"]
        if st.kind == "syncing":
            t.set_text(_("Uploading") if m.today.get("up", 0) >= m.today.get("down", 0) else _("Downloading"))
            eta = eta_text(self.app.eta())
            v.set_text(_("{d} of {n} files").format(d=m.run_done, n=m.run_total) + (f" · {eta}" if eta else ""))
            pb.set_fraction(m.run_done / m.run_total if m.run_total else 0)
        else:
            t.set_text(_("Last run"))
            if m.run_total:
                v.set_text(_("{d} of {n} files · done ✓").format(d=m.run_done, n=m.run_total)
                           if m.run_done >= m.run_total else _("{d} of {n} files").format(d=m.run_done, n=m.run_total))
                pb.set_fraction(m.run_done / m.run_total)
            else:
                v.set_text(_("Nothing to transfer"))
                pb.set_fraction(0)
        self.cells["today"][2].set_text(f"↑ {human_bytes(m.today.get('up', 0))} · ↓ {human_bytes(m.today.get('down', 0))}")
        self.refresh_rate()

    def refresh_rate(self):
        up, down = self.app.manager.samples[-1] if self.app.manager.samples else (0, 0)
        self.rates.set_text(f"↓ {down / 1000:.0f}  ↑ {up / 1000:.0f}")
        self.graph.queue_draw()


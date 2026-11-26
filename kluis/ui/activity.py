"""Activity (HANDOVER §3.7): filter, open log folder, clear with Undo, coloured icons, empty state."""
from __future__ import annotations

import time

from gi.repository import Gtk

from ..i18n import _
from .common import a11y, button, clear, combo, label, styled, vbox

ICONS = {"ok": ("✓", "k-ok"), "info": ("i", "k-muted"), "warning": ("!", "k-warn"), "error": ("✕", "k-error")}


class ActivityPage(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.app = app
        self.filter = combo([("all", _("Everything")), ("problems", _("Problems only"))], "all",
                            lambda _v: self.rebuild(), _("Show"))
        from .common import wrapbar
        bar = Gtk.Box(spacing=8)
        bar.pack_start(label(_("Recent activity"), "k-h3", ellipsize="end"), True, True, 0)
        bar.pack_end(wrapbar(self.filter, button(_("Open log folder"), app.open_logs), button(_("Clear"), self._clear),
                             per_line=1), False, False, 0)
        self.pack_start(bar, False, False, 0)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        a11y(self.list, _("Activity"))
        ph = label(_("Nothing yet. Sync activity shows up here."), "k-muted", xalign=0.5)
        ph.set_margin_top(30)
        ph.show()
        self.list.set_placeholder(ph)
        sw = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        styled(sw, "k-card")
        sw.add(self.list)
        self.pack_start(sw, True, True, 0)

    def _row(self, a):
        row = Gtk.ListBoxRow()
        box = Gtk.Box(spacing=12, margin=6)
        glyph, cls = ICONS.get(a.level, ICONS["info"])
        ic = label(glyph, "k-iconbox", cls, xalign=0.5)
        ic.set_size_request(32, 32)
        ic.set_valign(Gtk.Align.START)
        box.pack_start(ic, False, False, 0)
        text = f"{a.folder} · {a.text}" if a.folder else a.text
        v = vbox(label(text, wrap=True, selectable=True), spacing=2)
        if a.detail:
            v.pack_start(label(a.detail, "k-muted", "k-s12", wrap=True), False, False, 0)
        box.pack_start(v, True, True, 0)
        t = time.localtime(a.ts)
        when = time.strftime("%H:%M", t) if time.strftime("%Y%m%d", t) == time.strftime("%Y%m%d") \
            else time.strftime("%Y-%m-%d %H:%M", t)
        box.pack_end(label(when, "k-muted", "k-s12", "k-num"), False, False, 0)
        row.add(box)
        row.kluis_level = a.level
        a11y(row, f"{a.level}: {text}")
        return row

    def rebuild(self):
        clear(self.list)
        only = self.filter.get_active_id() == "problems"
        for a in list(self.app.manager.activity)[:300]:
            if only and a.level not in ("error", "warning"):
                continue
            self.list.add(self._row(a))
        self.list.show_all()

    def prepend(self, a):
        if self.filter.get_active_id() == "problems" and a.level not in ("error", "warning"):
            return
        row = self._row(a)
        row.show_all()
        self.list.prepend(row)

    def rows(self):
        return [r for r in self.list.get_children() if isinstance(r, Gtk.ListBoxRow)]

    def _clear(self):
        old = self.app.manager.clear_activity()
        self.app.toast(_("Activity cleared"), (_("Undo"), lambda: self.app.manager.restore_activity(old)))

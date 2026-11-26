"""Activity (HANDOVER §3.7): filter, open log folder, clear with Undo, coloured icons, empty state.
Above the log: the big-items lane (kluis/lane.py), each item with Pause / Resume / Send first."""
from __future__ import annotations

import time

from gi.repository import Gtk

from ..i18n import _
from ..status import big_lane_text, duration_text, files_lane_text, human_bytes
from .common import a11y, button, clear, combo, label, set_button_text, styled, vbox

ICONS = {"ok": ("✓", "k-ok"), "info": ("i", "k-muted"), "warning": ("!", "k-warn"), "error": ("✕", "k-error")}


class ActivityPage(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.app = app
        self.filter = combo([("all", _("Everything")), ("problems", _("Problems only"))], "all",
                            lambda _v: self.rebuild(), _("Show"))
        bar = Gtk.Box(spacing=8)
        bar.pack_start(label(_("Recent activity"), "k-h3", ellipsize="end"), True, True, 0)
        for wdg in (button(_("Clear"), self._clear), button(_("Open log folder"), app.open_logs), self.filter):
            wdg.set_valign(Gtk.Align.CENTER)                # side by side (Walter, 2026-11-26)
            bar.pack_end(wdg, False, False, 0)
        self.pack_start(self._big_card(), False, False, 0)
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

    # ---------- the two lanes ----------
    def _big_card(self):
        """Transfers: lane 1 (files) and lane 2 (big items) with what each is doing; big items listed under
        lane 2 with Pause / Resume / Send first."""
        self.big = vbox(spacing=8)
        styled(self.big, "k-card")
        a11y(self.big, _("Transfers"))
        self.big.pack_start(label(_("Transfers"), "k-h3"), False, False, 0)

        def lane(title, glyph):
            ic = label(glyph, "k-iconbox", "k-muted", xalign=0.5)
            ic.set_size_request(32, 32)
            name = label(title, "k-bold", ellipsize="end")
            state = label("", "k-muted", "k-s12", ellipsize="end")
            row = Gtk.Box(spacing=10)
            row.pack_start(ic, False, False, 0)
            row.pack_start(vbox(name, state, spacing=2), True, True, 0)
            self.big.pack_start(row, False, False, 0)
            return row, state
        row1, self.files_state = lane(_("Lane 1 · Files"), "⇅")
        a11y(self.files_state, _("Files lane"))
        self.files_btn = button(_("Pause"), self._toggle_files, name=_("Pause the files lane"),
                                tooltip=_("Big items keep syncing; other changes wait until you resume."))
        self.files_btn.set_valign(Gtk.Align.CENTER)
        row1.pack_end(self.files_btn, False, False, 0)
        _row2, self.big_state = lane(_("Lane 2 · Big items (1 GB or more)"), "⇅")
        a11y(self.big_state, _("Big items lane"))
        self.big_list = vbox(spacing=4)
        self.big_list.set_margin_start(42)
        # a long list scrolls inside the card: the window must still fit a 640 px high screen (F23/F25)
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                max_content_height=132)
        sw.add(self.big_list)
        self.big.pack_start(sw, False, False, 0)
        self.big_hint = label("", "k-muted", "k-s12", wrap=True)
        self.big.pack_start(self.big_hint, False, False, 0)
        self._big_sig = None
        self._big_rows = []
        return self.big

    def _toggle_files(self):
        m = self.app.manager
        m.set_files_paused(not self.app.settings.files_paused)
        self.refresh_big()

    def refresh_big(self):
        """Updates both lanes; rebuilds the big-items list only when its items or their states changed."""
        m, s = self.app.manager, self.app.settings
        lane = m.lane
        running = lane.current
        self.files_state.set_text(files_lane_text(s.paused, s.files_paused, m.busy, m.name_of(m.current),
                                                  m.run_done, m.run_total))
        paused = s.files_paused
        set_button_text(self.files_btn, _("Resume") if paused else _("Pause"),
                        _("Resume the files lane") if paused else _("Pause the files lane"))
        self.files_btn.set_sensitive(not s.paused)
        self.big_state.set_text(big_lane_text(
            s.paused, running.name if running else "", bool(running and running.direction == "up"),
            running.bytes if running else 0, time.time() - running.started if running else 0,
            len(lane.waiting()), sum(len(f.held) for f in s.folders)))
        rows = [(it, "running" if it is running else "waiting", None) for it in list(lane.items)]
        rows += [(it, "paused", (f, path)) for f, path, it in lane.paused_list()]
        sig = tuple((r[0].key if r[0] else r[2], r[1]) for r in rows)
        if sig != self._big_sig:
            self._big_sig = sig
            clear(self.big_list)
            self._big_rows = []
            for it, state, where in rows:
                row, detail = self._big_row(it, state, where)
                self.big_list.pack_start(row, False, False, 0)
                self._big_rows.append((it, state, where, detail))
            self.big_list.show_all()
        for it, state, where, detail in self._big_rows:
            detail.set_text(self._big_detail(it, state, where))
        mins = s.resume_paused_after
        self.big_hint.set_text(_("Big files and folders sync in lane 2, one at a time, next to everything else.")
                               + " " + (_("Paused big items continue by themselves after {n} min without other "
                                          "syncing.").format(n=mins) if mins
                                        else _("Paused big items wait until you resume them.")))

    def _big_row(self, it, state, where):
        row = Gtk.Box(spacing=10)
        up = (it.direction if it else "up") == "up"
        ic = label("↑" if up else "↓", "k-iconbox", "k-muted", xalign=0.5)
        ic.set_size_request(28, 28)
        row.pack_start(ic, False, False, 0)
        name = (it.rel if it else where[1].rstrip("/"))
        folder = self.app.manager.name_of(it.fid if it else where[0].id)
        title = label(f"{folder} · {name}", ellipsize="middle")
        title.set_tooltip_text(name)
        detail = label("", "k-muted", "k-s12", ellipsize="end")
        row.pack_start(vbox(title, detail, spacing=2), True, True, 0)
        m = self.app.manager
        if state == "paused":
            fid, path = where[0].id, where[1]
            b = button(_("Resume"), lambda: m.resume_item(fid, path), name=_("Resume {n}").format(n=name))
            b.set_valign(Gtk.Align.CENTER)
            row.pack_end(b, False, False, 0)
        else:
            key = it.key
            b = button(_("Pause"), lambda: self._pause(key), name=_("Pause {n}").format(n=name))
            b.set_valign(Gtk.Align.CENTER)
            row.pack_end(b, False, False, 0)
            if state == "waiting":
                b2 = button(_("Send first"), lambda: m.send_first(key), name=_("Send {n} first").format(n=name),
                            tooltip=_("Next in line. The item being transferred now keeps going."))
                b2.set_valign(Gtk.Align.CENTER)
                row.pack_end(b2, False, False, 0)
        a11y(row, f"{state}: {folder} · {name}")
        row.kluis_state = state
        return row, detail

    def _big_detail(self, it, state, where) -> str:
        if it is None:
            return _("Paused")
        size = human_bytes(it.bytes)
        files = _(" · {n} files").format(n=len(it.files)) if it.is_folder else ""
        if state == "running":
            verb = _("Uploading") if it.direction == "up" else _("Downloading")
            done = _(" · {d} of {n} done").format(d=it.done_files, n=len(it.files)) if it.is_folder else ""
            return f"{verb} · {size}{done} · {duration_text(time.time() - it.started)}"
        if state == "waiting":
            return f"{_('Waiting')} · {size}{files}"
        return f"{_('Paused')} · {size}{files}"

    def _pause(self, key):
        if self.app.manager.pause_item(key):
            self.app.toast(_("Paused. A paused file starts again from the beginning when it continues."))

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
        self.refresh_big()          # paused big items from before a restart show at once

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

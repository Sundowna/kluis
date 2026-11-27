"""Shared with me (HANDOVER §3.6). Shown because the CLI lists /shared-with-me (docs/cli-capabilities.md).

Editor items sync two-way, Viewer items mirror down only (invariant 4). Turning Sync off keeps the local copy.
"""
from __future__ import annotations

import os

from gi.repository import Gdk, GObject, Gtk, Pango

from ..cli import RemoteNode
from ..config import FolderPair, validate_local
from ..listcache import fetch, shared_lists
from ..i18n import _, ngettext
from .common import a11y, button, iso_date, label, open_path, run_bg, short_path, styled, vbox
from .dialogs import choose_local_folder

# defaults fit a 1440×900 window with Quick settings open; Name and Local folder take any extra room
COLS = [("perm", _("Permissions"), 96), ("name", _("Name"), 170), ("by", _("Shared by"), 150),
        ("target", _("Local folder"), 200), ("date", _("Shared on"), 104), ("sync", _("Sync"), 64)]


def perm_text(role):
    return _("Can edit") if role in ("editor", "admin") else _("Viewer")


class SharedPage(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.app = app
        self.items = []
        self.desc = True
        self.loaded = False
        self.count = label("", "k-h3")
        a11y(self.count, _("Shared items synced"))
        self.pack_start(self.count, False, False, 0)
        # node, perm, icon, name, by, target, date, sync, dim
        self.store = Gtk.ListStore(GObject.TYPE_PYOBJECT, str, str, str, str, str, str, bool, bool)
        self.view = Gtk.TreeView(model=self.store)
        self.view.get_selection().set_mode(Gtk.SelectionMode.SINGLE)
        a11y(self.view, _("Shared with me"))
        self.view.connect("button-press-event", self._press)
        widths = app.settings.columns.get("shared", {})
        self.columns = {}
        for key, title, w in COLS:
            if key == "sync":
                r = Gtk.CellRendererToggle()
                r.connect("toggled", self._toggle_sync)
                col = Gtk.TreeViewColumn(title, r, active=7)
            elif key == "name":
                col = Gtk.TreeViewColumn(title)
                ic = Gtk.CellRendererPixbuf()
                tx = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
                col.pack_start(ic, False)
                col.pack_start(tx, True)
                col.add_attribute(ic, "icon-name", 2)
                col.add_attribute(tx, "text", 3)
            elif key == "target":
                tx = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.MIDDLE)
                ic = Gtk.CellRendererPixbuf(icon_name="folder-open-symbolic")
                col = Gtk.TreeViewColumn(title)
                col.pack_start(tx, True)
                col.pack_start(ic, False)
                col.add_attribute(tx, "text", 5)
                col.set_cell_data_func(tx, self._dim)
            else:
                idx = {"perm": 1, "by": 4, "date": 6}[key]
                tx = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
                col = Gtk.TreeViewColumn(title, tx, text=idx)
            col.set_resizable(True)
            col.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
            col.set_fixed_width(int(widths.get(key, w)))
            col.set_min_width(56)
            col.set_expand(key in ("name", "target") and key not in widths)
            col.connect("notify::width", self._col_width, key)
            if key == "date":
                col.set_clickable(True)
                col.set_sort_indicator(True)
                col.set_sort_order(Gtk.SortType.DESCENDING)
                col.connect("clicked", lambda *_: self.sort_by_date())
            self.view.append_column(col)
            self.columns[key] = col
        self.view.connect("realize", lambda *_: self._header_keys())
        sw = Gtk.ScrolledWindow(vexpand=True)
        sw.add(self.view)
        styled(sw, "k-card")
        self.stack = Gtk.Stack()
        self.stack.add_named(sw, "list")
        self.msg = label("", "k-muted", xalign=0.5, wrap=True)
        self.stack.add_named(vbox(self.msg, button(_("Retry"), self.load), valign=Gtk.Align.CENTER), "msg")
        self.stack.add_named(Gtk.Spinner(active=True), "loading")
        self.pack_start(self.stack, True, True, 0)
        self.pack_start(label(_("Items others shared with you · choose a local folder per item, then switch on Sync to "
                                "keep a copy there · Viewer items sync down only"), "k-muted", "k-s12", wrap=True),
                        False, False, 0)

    # ---------- columns ----------
    def _header_keys(self):
        for key, col in self.columns.items():
            b = col.get_button()
            if b is None:
                continue
            a11y(b, col.get_title(), _("Resize column (arrow keys)"))
            b.connect("key-press-event", self._header_key, key)
        self.columns["sync"].get_button().set_tooltip_text(
            _("Editor items sync both ways. Viewer items sync down only, because you can't change them."))

    def _header_key(self, _b, ev, key):
        if ev.keyval not in (Gdk.KEY_Left, Gdk.KEY_Right):
            return False
        self.resize_column(key, 16 if ev.keyval == Gdk.KEY_Right else -16)
        return True

    def resize_column(self, key, delta):
        col = self.columns[key]
        cur = col.get_fixed_width() if col.get_fixed_width() > 0 else col.get_width()
        w = max(56, min(600, cur + delta))
        col.set_fixed_width(w)
        self.app.settings.columns.setdefault("shared", {})[key] = w
        self.app.save_soon()

    def _col_width(self, col, _p, key):
        w = col.get_width()
        if w > 0 and self.app.settings.columns.setdefault("shared", {}).get(key) != w:
            self.app.settings.columns["shared"][key] = w
            self.app.save_soon()

    # ---------- data ----------
    def on_shown(self):
        if not self.loaded:
            self.load()

    def load(self):
        """The kept list at once, then Proton's answer in the background (kluis/listcache.py)."""
        self.loaded = True
        if shared_lists(self.app).get("shared", RemoteNode) is None:
            self.stack.set_visible_child_name("loading")

        def show(items, kept):
            if items is not None:
                self.items = items
                self.app.shared_cache = items
                self._fill()
                self.stack.set_visible_child_name("list")
            elif not kept:
                self._fill()                # unchanged: only the "checking" note goes
            if kept:
                self.count.set_text(self.count.get_text() + " · " + _("checking Proton Drive…"))

        def fail(e, kept_shown):
            if kept_shown:
                self._fill()
                self.count.set_text(self.count.get_text() + " · " + _("couldn't check Proton Drive"))
                return
            self.msg.set_text(_("Couldn't load the items shared with you: {e}").format(e=e))
            self.stack.set_visible_child_name("msg")
        fetch(self.app, "shared", RemoteNode, self.app.cli.shared_with_me, show, fail)

    def target_for(self, n) -> str:
        fid = self.app.settings.shares.get(n.uid)
        f = self.app.settings.folder(fid) if fid else None
        if f:
            return f.local
        pending = getattr(self, "_targets", {}).get(n.uid)
        return pending or os.path.join(self.app.settings.root_dir, _("Shared with me"), n.name)

    def _fill(self):
        items = sorted(self.items, key=lambda n: n.shared_on or "", reverse=self.desc)
        self.store.clear()
        for n in items:
            fid = self.app.settings.shares.get(n.uid)
            synced = bool(fid and self.app.settings.folder(fid))
            icon = "folder" if n.is_folder else ("x-office-spreadsheet" if "sheet" in (n.media_type or "")
                                                 else "x-office-document")
            self.store.append([n, perm_text(n.role), icon, n.name, n.shared_by or "—",
                               short_path(self.target_for(n)), iso_date(n.shared_on), synced, not synced])
        done = sum(1 for r in self.store if r[7])
        self.count.set_text(ngettext("{d} of {n} item synced", "{d} of {n} items synced", len(self.items)).format(
            d=done, n=len(self.items)))

    def _dim(self, _col, cell, model, it, _data):
        cell.set_property("foreground-rgba", None)
        cell.set_property("sensitive", not model.get_value(it, 8))

    def sort_by_date(self):
        self.desc = not self.desc
        self.columns["date"].set_sort_order(Gtk.SortType.DESCENDING if self.desc else Gtk.SortType.ASCENDING)
        self.columns["date"].set_title(_("Shared on") + (" ▼" if self.desc else " ▲"))
        self._fill()

    def _press(self, view, ev):
        if ev.type != Gdk.EventType.BUTTON_PRESS or ev.button != 1:
            return False
        hit = view.get_path_at_pos(int(ev.x), int(ev.y))
        if not hit or hit[1] is not self.columns["target"]:
            return False
        n = self.store[hit[0]][0]
        cell_x = hit[2]
        if cell_x > self.columns["target"].get_width() - 28:
            self.pick_target(n)
        else:
            t = self.target_for(n)
            if os.path.isdir(t):
                open_path(t)
            else:
                self.app.toast(_("Switch on Sync first to create the local copy"))
        return True

    def pick_target(self, n):
        p = choose_local_folder(self.get_toplevel(), _("Choose a local folder for {n}").format(n=n.name),
                                os.path.expanduser("~"))
        if not p:
            return
        fid = self.app.settings.shares.get(n.uid)
        err = validate_local(self.app.settings, p, fid or "") if os.path.isdir(p) else None
        if err and err != "That folder doesn't exist":
            self.app.toast(err)
            return
        self._targets = getattr(self, "_targets", {})
        self._targets[n.uid] = p
        f = self.app.settings.folder(fid) if fid else None
        if f:
            f.local = os.path.realpath(p)
            self.app.settings.save()
            self.app.manager.folder_changed(f, reset_state=True)
        self.app.toast(_("{n} will sync to {p}").format(n=n.name, p=short_path(p)))
        self._fill()

    def _toggle_sync(self, _r, tpath):
        n = self.store[tpath][0]
        self.set_sync(n, not self.store[tpath][7])

    def set_sync(self, n, on):
        s = self.app.settings
        fid = s.shares.get(n.uid)
        if on and not (fid and s.folder(fid)):
            target = self.target_for(n)
            os.makedirs(target, exist_ok=True)
            err = validate_local(s, target)
            if err:
                self.app.toast(err)
                return
            viewer = n.role not in ("editor", "admin")
            f = FolderPair(local=os.path.realpath(target), remote=f"/shared-with-me/{n.uid}",
                           mode="mirror" if viewer else "two-way")
            s.shares[n.uid] = f.id
            self.app.add_folder(f, quiet=True)
            self.app.toast(_("Syncing {n} to {p}").format(n=n.name, p=short_path(target)) +
                           (" · " + _("down only (Viewer)") if viewer else ""))
        elif not on and fid:
            f = s.folder(fid)
            s.shares.pop(n.uid, None)
            if f:
                s.folders.remove(f)
                s.save()
                self.app.manager.folder_removed(f.id)
                self.app.window.folders.rebuild()
            self.app.toast(_("Stopped syncing {n} · local copy kept").format(n=n.name))
        self._fill()


"""Browse Proton Drive (HANDOVER §3.4): breadcrumbs, toolbar, resizable columns, trash with Undo."""
from __future__ import annotations

import collections
import os
import threading
from urllib.parse import unquote, urlparse

from gi.repository import Gdk, GLib, GObject, Gtk, Pango

from ..cli import CliError, rjoin
from ..errors import OFFLINE, classify
from ..i18n import _, ngettext
from .common import a11y, button, clear, human_size, iso_date, label, open_path, run_bg, styled, vbox
from .dialogs import ask_text, choose_files, confirm

ROOT_NAMES = {"/my-files": _("My files"), "/devices": _("Computers"), "/shared-with-me": _("Shared with me"),
              "/trash": _("Trash")}
COLS = [("files", _("Files"), 80), ("size", _("Size"), 90), ("date", _("Modified"), 110)]
COL_MIN, COL_MAX, COL_STEP = 56, 600, 16


def file_icon(n) -> str:
    if n.is_folder:
        return "folder"
    mt = n.media_type or ""
    for prefix, icon in (("image/", "image-x-generic"), ("video/", "video-x-generic"),
                         ("audio/", "audio-x-generic"), ("text/", "text-x-generic"),
                         ("application/pdf", "application-pdf"), ("application/zip", "package-x-generic"),
                         ("application/vnd.proton", "x-office-document")):
        if mt.startswith(prefix):
            return icon
    return "text-x-generic"


class FolderStats:
    """Files/Size of Proton Drive folders, from a recursive listing of active items (decisions D4).
    Computed lazily for visible folders, one at a time in the background, cached."""

    def __init__(self, cli, on_ready):
        self.cli = cli
        self.on_ready = on_ready
        self.cache: dict[str, tuple[int, int]] = {}
        self._q: collections.deque[str] = collections.deque()
        self._busy = False
        self._lock = threading.Lock()

    def get(self, path):
        return self.cache.get(path)

    def want(self, paths):
        with self._lock:
            for p in paths:
                if p not in self.cache and p not in self._q:
                    self._q.append(p)
            if self._busy:
                return
            self._busy = True
        threading.Thread(target=self._work, daemon=True).start()

    def forget(self, path):
        for k in list(self.cache):
            if k == path or k.startswith(path + "/") or path.startswith(k + "/"):
                self.cache.pop(k, None)

    def _work(self):
        while True:
            with self._lock:
                if not self._q:
                    self._busy = False
                    return
                path = self._q.popleft()
            try:
                files, size, stack = 0, 0, [path]
                while stack:
                    p = stack.pop()
                    for n in self.cli.list(p):
                        if n.is_folder:
                            stack.append(rjoin(p, n.name))
                        elif n.type == "file":
                            files += 1
                            size += n.size or 0
                self.cache[path] = (files, size)
                GLib.idle_add(lambda p=path: (self.on_ready(p), False)[1])
            except CliError:
                continue


class BrowserPage(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.app = app
        self.path = "/my-files"
        self.loaded_once = False
        self.nodes = []
        self.stats = FolderStats(app.cli, self._stats_ready)
        self.crumbs = Gtk.Box(spacing=2)
        a11y(self.crumbs, _("Breadcrumbs"))
        self.pack_start(self.crumbs, False, False, 0)

        bar = Gtk.Box(spacing=8)
        self.up_btn = button(_("↑ Upload…"), self._upload_dialog, "suggested-action")
        self.new_btn = button(_("+ New folder"), self._new_folder)
        self.dl_btn = button(_("↓ Download"), self._download_selected)
        self.rn_btn = button(_("Rename"), self._rename_selected)
        self.tr_btn = button(_("Move to trash"), self._trash_selected, "k-danger")
        for b in (self.up_btn, self.new_btn, self.dl_btn, self.rn_btn, self.tr_btn):
            bar.pack_start(b, False, False, 0)
        self.refresh_btn = button("↻", self.load, "k-flat", tooltip=_("Reload this folder"), name=_("Reload"))
        bar.pack_end(self.refresh_btn, False, False, 0)
        self.pack_start(bar, False, False, 0)

        # list
        self.store = Gtk.ListStore(GObject.TYPE_PYOBJECT, bool, str, str, str, str, str)
        self.view = Gtk.TreeView(model=self.store, headers_visible=True, enable_search=True, search_column=3)
        self.view.get_selection().set_mode(Gtk.SelectionMode.NONE)
        a11y(self.view, _("Files in this folder"))
        self.view.connect("row-activated", self._activated)
        self.view.connect("button-press-event", self._button)
        self.view.connect("key-press-event", self._key)
        tog = Gtk.CellRendererToggle()
        tog.connect("toggled", self._toggled)
        c0 = Gtk.TreeViewColumn("", tog, active=1)
        c0.set_min_width(36)
        self.view.append_column(c0)
        widths = self.app.settings.columns.get("browse", {})
        name_col = Gtk.TreeViewColumn(_("Name"))
        ic = Gtk.CellRendererPixbuf()
        tx = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
        name_col.pack_start(ic, False)
        name_col.pack_start(tx, True)
        name_col.add_attribute(ic, "icon-name", 2)
        name_col.add_attribute(tx, "text", 3)
        name_col.set_expand(True)
        name_col.set_resizable(True)
        name_col.set_min_width(160)
        self.view.append_column(name_col)
        self.columns = {"name": name_col}
        for i, (key, title, w) in enumerate(COLS):
            r = Gtk.CellRendererText(xalign=1.0 if key != "date" else 0.0)
            col = Gtk.TreeViewColumn(title, r, text=4 + i)
            col.set_resizable(True)
            col.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
            col.set_fixed_width(int(widths.get(key, w)))
            col.set_min_width(COL_MIN)
            col.set_max_width(COL_MAX)
            col.connect("notify::width", self._col_width, key)
            self.view.append_column(col)
            self.columns[key] = col
        self.view.connect("realize", lambda *_: self._header_keys())
        sw = Gtk.ScrolledWindow(vexpand=True)
        sw.add(self.view)
        styled(sw, "k-card")
        sw.get_style_context().add_class("k-tight")
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE)
        self.stack.add_named(sw, "list")
        skel = vbox(spacing=12, margin=16)
        for _i in range(7):
            row = Gtk.Box(spacing=16)
            for wdt in (260, 60, 70, 90):
                b = Gtk.Box()
                b.set_size_request(wdt, 14)
                styled(b, "k-skeleton")
                row.pack_start(b, wdt == 260, wdt == 260, 0)
            skel.pack_start(row, False, False, 0)
        a11y(skel, _("Loading"))
        self.stack.add_named(skel, "skeleton")
        self.stack.add_named(Gtk.Box(), "blank")
        self.msg = label("", "k-muted", xalign=0.5, wrap=True)
        self.retry = button(_("Retry"), self.load)
        self.retry.set_halign(Gtk.Align.CENTER)
        msgbox = vbox(self.msg, self.retry, spacing=12, valign=Gtk.Align.CENTER)
        self.stack.add_named(msgbox, "msg")
        self.pack_start(self.stack, True, True, 0)
        self.pack_start(label(_("Drag files onto this list to upload · click a folder to open it · trashed items can "
                                "be restored from the Proton Drive trash"), "k-muted", "k-s12", wrap=True),
                        False, False, 0)
        self.drag_dest_set(Gtk.DestDefaults.ALL, [Gtk.TargetEntry.new("text/uri-list", 0, 0)], Gdk.DragAction.COPY)
        self.connect("drag-data-received", self._on_drop)
        self._sel_changed()

    # ---------- columns ----------
    def _header_keys(self):
        for key, col in self.columns.items():
            btn = col.get_button()
            if btn is None:
                continue
            a11y(btn, col.get_title() or _("Select"), _("Resize column (arrow keys)"))
            btn.set_tooltip_text(_("Drag the edge to resize · ←/→ resize"))
            btn.connect("key-press-event", self._header_key, key)

    def _header_key(self, _btn, ev, key):
        if ev.keyval not in (Gdk.KEY_Left, Gdk.KEY_Right):
            return False
        self.resize_column(key, COL_STEP if ev.keyval == Gdk.KEY_Right else -COL_STEP)
        return True

    def resize_column(self, key, delta):
        col = self.columns[key]
        cur = col.get_fixed_width() if key != "name" and col.get_fixed_width() > 0 else col.get_width()
        w = max(COL_MIN, min(COL_MAX, cur + delta))
        if key == "name":
            col.set_min_width(w)
            return
        col.set_fixed_width(w)
        self._save_width(key, w)

    def _col_width(self, col, _p, key):
        w = col.get_width()
        if w > 0:
            self._save_width(key, w)

    def _save_width(self, key, w):
        cols = self.app.settings.columns.setdefault("browse", {})
        if cols.get(key) != w:
            cols[key] = w
            self.app.save_soon()

    # ---------- navigation ----------
    def on_shown(self):
        if not self.loaded_once:
            self.load()

    def go(self, path):
        self.path = path
        self.load()

    def _crumbs(self):
        clear(self.crumbs)
        parts = [p for p in self.path.strip("/").split("/") if p]
        for i, p in enumerate(parts):
            if i:
                self.crumbs.pack_start(label("›", "k-muted"), False, False, 0)
            target = "/" + "/".join(parts[:i + 1])
            b = button(ROOT_NAMES.get(target, p), lambda t=target: self.go(t), "k-flat",
                       "k-bold" if i == len(parts) - 1 else "")
            self.crumbs.pack_start(b, False, False, 0)
        roots = Gtk.MenuButton(image=Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.BUTTON))
        styled(roots, "k-flat")
        a11y(roots, _("Sections"))
        from .common import popover_menu
        roots.set_popover(popover_menu(roots, [(name, lambda p=p: self.go(p)) for p, name in ROOT_NAMES.items()
                                               if p != "/trash"]))
        self.crumbs.pack_start(roots, False, False, 0)
        self.crumbs.show_all()

    def crumb_text(self) -> str:
        parts = [p for p in self.path.strip("/").split("/") if p]
        out = []
        for i, p in enumerate(parts):
            t = "/" + "/".join(parts[:i + 1])
            out.append(ROOT_NAMES.get(t, p))
        return " › ".join(out)

    def load(self):
        self.loaded_once = True
        self._crumbs()
        path = self.path
        self._loading = path
        self.stack.set_visible_child_name("blank")
        GLib.timeout_add(300, lambda: (self.stack.set_visible_child_name("skeleton")
                                       if getattr(self, "_loading", None) == path else None, False)[1])

        def done(nodes):
            if path != self.path:
                return
            self._loading = None
            self.nodes = sorted(nodes, key=lambda n: (not n.is_folder, n.name.lower()))
            self._fill()
            if not self.nodes:
                self.msg.set_text(_("This folder is empty. Drag files here to upload them."))
                self.retry.hide()
                self.stack.set_visible_child_name("msg")
                return
            self.stack.set_visible_child_name("list")

        def fail(e):
            if path != self.path:
                return
            self._loading = None
            reason = _("offline") if classify(e) == OFFLINE else str(e)
            self.msg.set_text(_("Couldn't load this folder: {r}").format(r=reason))
            self.retry.show()
            self.stack.set_visible_child_name("msg")
        run_bg(lambda: self.app.cli.list(path), done, fail)

    def _fill(self, keep_sel=False):
        sel = {r[0].name for r in self.store if r[1]} if keep_sel else set()
        self.store.clear()
        want = []
        for n in self.nodes:
            p = rjoin(self.path, n.name)
            if n.is_folder:
                st = self.stats.get(p)
                files, size = (str(st[0]), human_size(st[1])) if st else ("…", "…")
                if not st:
                    want.append(p)
            else:
                files, size = "—", human_size(n.size)
            self.store.append([n, n.name in sel, file_icon(n), n.name, files, size, iso_date(n.modified)])
        if want:
            self.stats.want(want)
        self._sel_changed()

    def _stats_ready(self, path):
        if os.path.dirname(path.rstrip("/")) == self.path.rstrip("/"):
            self._fill(keep_sel=True)

    # ---------- selection ----------
    def _toggled(self, _r, tpath):
        it = self.store.get_iter(tpath)
        self.store.set_value(it, 1, not self.store.get_value(it, 1))
        self._sel_changed()

    def select(self, names):
        for r in self.store:
            r[1] = r[0].name in names
        self._sel_changed()

    def selected(self):
        return [r[0] for r in self.store if r[1]]

    def _sel_changed(self):
        n = len(self.selected())
        self.dl_btn.set_sensitive(n > 0)
        self.rn_btn.set_sensitive(n == 1)
        self.tr_btn.set_sensitive(n > 0)

    def _button(self, view, ev):
        if ev.type == Gdk.EventType.BUTTON_PRESS and ev.button == 1:
            hit = view.get_path_at_pos(int(ev.x), int(ev.y))
            if hit and hit[1] is not self.view.get_column(0):
                node = self.store[hit[0]][0]
                if node.is_folder:
                    self.go(rjoin(self.path, node.name))
                    return True
        return False

    def _key(self, _v, ev):
        if ev.keyval == Gdk.KEY_space:
            path, _c = self.view.get_cursor()
            if path:
                self._toggled(None, path)
                return True
        if ev.keyval == Gdk.KEY_Delete and self.selected():
            self._trash_selected()
            return True
        return False

    def _activated(self, _v, tpath, _col):
        n = self.store[tpath][0]
        if n.is_folder:
            self.go(rjoin(self.path, n.name))
        else:
            self.open_file(n)

    # ---------- actions ----------
    def open_file(self, n):
        cache = os.path.join(GLib.get_user_cache_dir(), "kluis", "open", n.uid.replace("/", "_") or "x")
        os.makedirs(cache, exist_ok=True)
        self.app.toast(_("Opening {n}…").format(n=n.name))
        run_bg(lambda: self.app.cli.download([rjoin(self.path, n.name)], cache, file_strategy="remove"),
               lambda _s: open_path(os.path.join(cache, n.name)),
               lambda e: self.app.toast(_("Couldn't open {n}: {e}").format(n=n.name, e=e)))

    def _download_selected(self):
        nodes = self.selected()
        if not nodes:
            return
        dest = os.path.expanduser("~/Downloads")
        os.makedirs(dest, exist_ok=True)
        paths = [rjoin(self.path, n.name) for n in nodes]
        self.app.toast(ngettext("Downloading {n} item to ~/Downloads…", "Downloading {n} items to ~/Downloads…",
                                len(nodes)).format(n=len(nodes)))

        def done(summary):
            self.app.manager.log("ok", "", ngettext("Downloaded {n} file", "Downloaded {n} files",
                                                    summary.transferred).format(n=summary.transferred),
                                 _("to ~/Downloads"))
            self.app.toast(ngettext("Downloaded {n} file to ~/Downloads", "Downloaded {n} files to ~/Downloads",
                                    summary.transferred).format(n=summary.transferred),
                           (_("Show in folder"), lambda: open_path(dest)))
            self.select([])
        run_bg(lambda: self.app.cli.download(paths, dest, file_strategy="rename", folder_strategy="rename"),
               done, lambda e: self.app.toast(_("Download failed: {e}").format(e=e)))

    def upload(self, local_paths):
        if not local_paths:
            return
        target = self.path
        self.app.toast(ngettext("Uploading {n} item…", "Uploading {n} items…", len(local_paths)).format(
            n=len(local_paths)))

        def done(summary):
            self.stats.forget(target)
            msg = ngettext("Uploaded {n} file ✓", "Uploaded {n} files ✓", summary.transferred).format(
                n=summary.transferred)
            if summary.failed:
                msg = _("Uploaded {n}, {f} failed").format(n=summary.transferred, f=summary.failed)
            self.app.manager.log("error" if summary.failed else "ok", "", msg, _("into {t}").format(t=target))
            self.app.toast(msg)
            if target == self.path:
                self.load()
        run_bg(lambda: self.app.cli.upload(local_paths, target, file_strategy="rename"), done,
               lambda e: self.app.toast(_("Upload failed: {e}").format(e=e)))

    def _upload_dialog(self):
        self.upload(choose_files(self.get_toplevel(), _("Upload to Proton Drive")))

    def _on_drop(self, _w, _ctx, _x, _y, data, _info, _time):
        paths = [unquote(urlparse(u).path) for u in data.get_uris() if u.startswith("file://")]
        self.upload([p for p in paths if os.path.exists(p)])

    def _new_folder(self):
        name = ask_text(self.get_toplevel(), _("New folder"), _("Folder name"), ok=_("Create"))
        if name:
            path = self.path
            run_bg(lambda: self.app.cli.create_folder(path, name, exist_ok=False),
                   lambda _r: (self.app.toast(_("Created “{n}”").format(n=name)), self.load()),
                   lambda e: self.app.toast(_("Couldn't create the folder: {e}").format(e=e)))

    def _rename_selected(self):
        sel = self.selected()
        if len(sel) != 1:
            return
        n = sel[0]
        name = ask_text(self.get_toplevel(), _("Rename “{n}”").format(n=n.name), initial=n.name, ok=_("Rename"))
        if name and name != n.name:
            run_bg(lambda: self.app.cli.rename(rjoin(self.path, n.name), name),
                   lambda _r: (self.app.toast(_("Renamed to “{n}”").format(n=name)), self.load()),
                   lambda e: self.app.toast(_("Rename failed: {e}").format(e=e)))

    def _trash_selected(self):
        nodes = self.selected()
        if not nodes:
            return
        n = len(nodes)
        if not confirm(self.get_toplevel(),
                       ngettext("Move {n} item to the trash?", "Move {n} items to the trash?", n).format(n=n),
                       _("You can restore them from the Proton Drive trash."),
                       _("Move to trash"), _("Keep files"), destructive=True, default="none"):
            return
        paths = [rjoin(self.path, x.name) for x in nodes]
        uids = [x.uid for x in nodes]
        here = self.path

        def done(_r):
            self.stats.forget(here)
            msg = ngettext("Moved {n} item to the Proton Drive trash", "Moved {n} items to the Proton Drive trash",
                           n).format(n=n)
            self.app.manager.log("info", "", msg)
            self.app.toast(msg, (_("Undo"), lambda: self._restore(uids, here)))
            self.load()
        run_bg(lambda: self.app.cli.trash(paths), done,
               lambda e: self.app.toast(_("Couldn't move to the trash: {e}").format(e=e)))

    def _restore(self, uids, here):
        def done(_r):
            self.stats.forget(here)
            self.app.toast(_("Restored from the Proton Drive trash"))
            if self.path == here:
                self.load()
        run_bg(lambda: self.app.cli.restore(uids), done,
               lambda e: self.app.toast(_("Couldn't restore: {e}").format(e=e)))


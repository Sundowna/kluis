"""Browse Proton Drive (HANDOVER §3.4): breadcrumbs, toolbar, resizable columns, trash with Undo."""
from __future__ import annotations

import collections
import hashlib
import json
import os
import threading
import time
from urllib.parse import unquote, urlparse

from gi.repository import Gdk, GLib, GObject, Gtk, Pango

from ..cli import CliError, RemoteNode, rjoin
from ..errors import OFFLINE, classify
from ..i18n import _, ngettext
from ..listcache import fetch, shared_lists
from .common import a11y, button, clear, human_size, iso_date, label, open_path, run_bg, set_class, styled, vbox
from .dialogs import ask_text, choose_files, confirm

SECTION_ICONS = {"/my-files": "kluis-folder-symbolic", "/devices": "kluis-computer-symbolic",
                 "/shared-with-me": "kluis-shared-symbolic"}      # Trash: on the web (Browse's actions don't apply)
ROOT_NAMES = {"/my-files": _("My files"), "/devices": _("Computers"), "/shared-with-me": _("Shared with me"),
              "/trash": _("Trash")}
COLS = [("files", _("Files"), 80), ("size", _("Size"), 90), ("date", _("Modified"), 110)]
COL_MIN, COL_MAX, COL_STEP = 56, 600, 16
READ_AHEAD = 12                  # subfolders listed ahead of a click


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

    Counted lazily for visible folders, one at a time in the background. The counts are kept on disk per Proton
    account (~/.cache/kluis/folder-counts-<id>.json, only this user can read it), so Browse and Sync Center show
    them at once on the next start; a count older than a day is shown and quietly counted again. ↻ counts again
    now. The names found while counting (for search in subfolders) stay in memory only; a search asks for them.
    One instance per app (shared_stats), so Browse and Sync Center never write the file over each other."""

    MAX_AGE = 24 * 3600
    VERSION = 1

    def __init__(self, cli, on_ready=None, store=None):
        self.cli = cli
        self.listeners = [on_ready] if on_ready else []
        self.store = store                  # () -> path of this account's cache file, or None (memory only)
        self.cache: dict[str, tuple[int, int]] = {}
        self.when: dict[str, float] = {}
        # every name found while counting, for search in subfolders: folder -> [(remote path, name)]
        self.names: dict[str, list[tuple[str, str]]] = {}
        self._q: collections.deque[str] = collections.deque()
        self._busy = False
        self._lock = threading.Lock()
        self._loaded_from = None
        self._save_src = 0

    # ---------- disk ----------
    def _file(self):
        return self.store() if self.store else None

    def _load(self):
        path = self._file()
        if path == self._loaded_from:
            return
        self._loaded_from = path
        self.cache, self.when, self.names = {}, {}, {}
        if not path:
            return
        try:
            with open(path) as fh:
                raw = json.load(fh)
            if raw.get("v") != self.VERSION:
                return
            for k, (files, size, ts) in raw.get("counts", {}).items():
                self.cache[k] = (int(files), int(size))
                self.when[k] = float(ts)
        except (OSError, ValueError, TypeError, AttributeError):
            pass                            # no cache yet, or an unreadable one: count again

    def _save_soon(self):
        if not self._save_src:
            self._save_src = GLib.timeout_add(1500, self._save)

    def _save(self):
        self._save_src = 0
        path = self._loaded_from
        if not path:
            return False
        data = {"v": self.VERSION, "counts": {k: [v[0], v[1], self.when.get(k, 0)] for k, v in self.cache.items()}}
        try:
            os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
            tmp = path + ".tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as fh:
                json.dump(data, fh)
            os.replace(tmp, path)
        except OSError:
            pass                            # a cache: never worth an error
        return False

    # ---------- counts ----------
    def get(self, path):
        self._load()
        return self.cache.get(path)

    def fresh(self, path) -> bool:
        return path in self.cache and time.time() - self.when.get(path, 0) < self.MAX_AGE

    def want(self, paths, names=False):
        """Count these folders in the background: missing or older than a day, or (names=True, for search)
        every one whose names aren't read yet this session."""
        self._load()
        with self._lock:
            for p in paths:
                need = p not in self.names if names else not self.fresh(p)
                if need and p not in self._q:
                    self._q.append(p)
            if self._busy or not self._q:
                return
            self._busy = True
        threading.Thread(target=self._work, daemon=True).start()

    def forget(self, path):
        self._load()
        for k in list(self.cache) + list(self.names):
            if k == path or k.startswith(path + "/") or path.startswith(k + "/"):
                self.cache.pop(k, None)
                self.when.pop(k, None)
                self.names.pop(k, None)
        self._save_soon()

    def clear(self):
        """↻: count everything again (this account's file too)."""
        self._load()
        self.cache.clear()
        self.when.clear()
        self.names.clear()
        self._save_soon()

    def unload(self):
        """Another Proton account is active: the next get() reads that account's file."""
        with self._lock:
            self._q.clear()
        self._loaded_from = None
        self.cache, self.when, self.names = {}, {}, {}

    @property
    def busy(self) -> bool:
        return self._busy or bool(self._q)

    def _work(self):
        source = self._loaded_from
        while True:
            with self._lock:
                if not self._q:
                    self._busy = False
                    return
                path = self._q.popleft()
            try:
                files, size, stack, found = 0, 0, [path], []
                while stack:
                    p = stack.pop()
                    for n in self.cli.list(p):
                        found.append((rjoin(p, n.name), n.name))
                        if n.is_folder:
                            stack.append(rjoin(p, n.name))
                        elif n.type == "file":
                            files += 1
                            size += n.size or 0
                GLib.idle_add(self._done, path, files, size, found, source)
            except CliError:
                continue

    def _done(self, path, files, size, found, source):
        if source != self._loaded_from:         # counted for the previous account
            return False
        self.cache[path] = (files, size)
        self.when[path] = time.time()
        self.names[path] = found
        self._save_soon()
        for cb in list(self.listeners):
            cb(path)
        return False


def shared_stats(app) -> FolderStats:
    """The one FolderStats of this app, its counts kept per Proton account."""
    st = getattr(app, "folder_stats", None)
    if st is None:
        def store():
            acct = (app.settings.account or "").strip().lower()
            key = hashlib.sha1(acct.encode()).hexdigest()[:12] if acct else "default"
            return os.path.join(GLib.get_user_cache_dir(), "kluis", f"folder-counts-{key}.json")
        st = FolderStats(app.cli, store=store)
        app.folder_stats = st
    return st


class BrowserPage(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.app = app
        self.path = "/my-files"
        self.loaded_once = False
        self.nodes = []
        self.stats = shared_stats(app)
        self.stats.listeners.append(self._stats_ready)
        # Proton Drive's sections, always visible (Walter, 2026-11-26: "Computers" was easy to miss in a ▾ menu)
        self.sections = {}
        row = Gtk.Box(spacing=6)
        a11y(row, _("Sections"))
        for root, icon in SECTION_ICONS.items():
            b = button(ROOT_NAMES[root], lambda r=root: self.go(r), icon=icon,
                       name=_("Section: {s}").format(s=ROOT_NAMES[root]))
            row.pack_start(b, False, False, 0)
            self.sections[root] = b
        # the list on screen may be the kept one: say quietly that Kluis is checking, or since when it's offline
        self.fresh_lbl = label("", "k-muted", "k-s12", ellipsize="end")
        a11y(self.fresh_lbl, _("List freshness"))
        row.pack_end(self.fresh_lbl, False, False, 0)
        self.pack_start(row, False, False, 0)
        self.crumbs = Gtk.Box(spacing=2)
        a11y(self.crumbs, _("Breadcrumbs"))
        self.pack_start(self.crumbs, False, False, 0)

        self.up_btn = button(_("↑ Upload…"), self._upload_dialog, "suggested-action")
        self.new_btn = button(_("+ New folder"), self._new_folder)
        self.dl_btn = button(_("↓ Download"), self._download_selected,
                             tooltip=_("A one-off copy in ~/Downloads. To keep it in step, use Sync to this computer"))
        self.sync_btn = button(_("⇄ Sync to this computer…"), self._sync_here,
                               tooltip=_("Open this folder in Sync Center, ticked, to choose where it goes"))
        self.rn_btn = button(_("Rename"), self._rename_selected)
        self.tr_btn = button(_("Move to trash"), self._trash_selected, "k-danger")
        self.refresh_btn = button("↻", self.load, tooltip=_("Reload this folder"), name=_("Reload"))
        from .common import wrapbar
        # two per row at the least: seven buttons must still fit a 960 px window with wide fonts (F-020)
        self.pack_start(wrapbar(self.up_btn, self.new_btn, self.dl_btn, self.sync_btn, self.rn_btn, self.tr_btn,
                                self.refresh_btn, per_line=2), False, False, 0)

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
        for _i in range(4):
            row = Gtk.Box(spacing=16)
            for wdt in (160, 50, 60, 80):
                b = Gtk.Box()
                b.set_size_request(wdt, 14)
                styled(b, "k-skeleton")
                row.pack_start(b, wdt == 160, wdt == 160, 0)
            skel.pack_start(row, False, False, 0)
        a11y(skel, _("Loading"))
        self.stack.add_named(skel, "skeleton")
        self.stack.add_named(Gtk.Box(), "blank")
        self.msg = label("", "k-muted", xalign=0.5, wrap=True)
        self.retry = button(_("Retry"), self.load)
        self.retry.set_halign(Gtk.Align.CENTER)
        self.to_devices = button(_("Open Computers"), lambda: self.go("/devices"), "suggested-action")
        self.to_devices.set_halign(Gtk.Align.CENTER)
        self.to_devices.set_no_show_all(True)
        msgbox = vbox(self.msg, self.retry, self.to_devices, spacing=12, valign=Gtk.Align.CENTER)
        self.stack.add_named(msgbox, "msg")
        self.pack_start(self.stack, True, True, 0)
        self.pack_start(label(_("Drag files onto this list to upload · click a folder to open it · trashed items can "
                                "be restored from the Proton Drive trash"), "k-muted", "k-s12", wrap=True, max_chars=60),
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
        here = "/" + parts[0] if parts else ""
        for root, b in self.sections.items():
            set_class(b, "k-pressed", root == here)
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
        self._gen = getattr(self, "_gen", 0) + 1      # answers of an earlier load must not change this one
        self.to_devices.hide()           # only for an empty My files (_check_devices); never left over
        self._crumbs()
        path = self.path
        self._loading = path
        gen = self._gen

        def show(nodes, kept):
            if path != self.path or gen != self._gen:
                return
            self.fresh_lbl.set_text(_("Checking Proton Drive…") if kept else "")
            if nodes is not None:           # None: Proton's answer is the list already on screen
                done(nodes, keep=self._loading is None)
            if not kept:
                self._read_ahead(path)

        def done(nodes, keep=False):
            self._loading = None
            self.nodes = sorted(nodes, key=lambda n: (not n.is_folder, n.name.lower()))
            self._fill(keep_sel=keep)
            if self.nodes:
                self.to_devices.hide()      # a kept empty list may have offered it a moment ago
            if not self.nodes:
                self.msg.set_text(_("This folder is empty. Drag files here to upload them."))
                self.retry.hide()
                self.to_devices.hide()
                if path == "/my-files":
                    self._check_devices()
                self.stack.set_visible_child_name("msg")
                return
            self.stack.set_visible_child_name("list")

        def fail(e, kept_shown):
            if path != self.path or gen != self._gen:
                return
            reason = _("offline") if classify(e) == OFFLINE else str(e)
            if kept_shown:                  # keep showing the kept list, and say how old it is
                self.fresh_lbl.set_text(_("Couldn't check Proton Drive ({r}) · list from {t}").format(
                    r=reason, t=time.strftime("%d.%m. %H:%M", time.localtime(when))))
                return
            self._loading = None
            self.fresh_lbl.set_text("")
            self.msg.set_text(_("Couldn't load this folder: {r}").format(r=reason))
            self.retry.show()
            self.to_devices.hide()
            self.stack.set_visible_child_name("msg")
        if shared_lists(self.app).get("list:" + path, RemoteNode) is None:
            self.stack.set_visible_child_name("blank")
            GLib.timeout_add(300, lambda: (self.stack.set_visible_child_name("skeleton")
                                           if getattr(self, "_loading", None) == path else None, False)[1])
        when = fetch(self.app, "list:" + path, RemoteNode, lambda: self.app.cli.list(path), show, fail)

    def _read_ahead(self, path):
        """List the subfolders of the open folder in the background, one at a time, so opening one is
        instant. Stops when another folder is opened; skips lists checked in the last 10 minutes."""
        lc = shared_lists(self.app)
        todo = [rjoin(path, n.name) for n in self.nodes if n.is_folder]
        todo = [p for p in todo if (lc.age("list:" + p) or 1e9) > 600][:READ_AHEAD]
        gen = self._gen

        def step():
            if not todo or gen != self._gen:
                return
            p = todo.pop(0)

            def got(nodes):
                lc.put("list:" + p, nodes)
                step()
            run_bg(lambda: self.app.cli.list(p), got, lambda _e: step())
        step()

    def changed(self, path):
        """Kluis changed this folder in Proton Drive: forget its kept list and counts, then show it fresh."""
        self.stats.forget(path)
        shared_lists(self.app).forget("list:" + path)
        if path == self.path:
            self.load()

    def _check_devices(self):
        """My files is empty: folders synced from a computer by Proton's desktop app are under Computers
        (/devices). Say so, instead of looking like an empty Drive."""
        gen = self._gen

        def done(devices):
            if gen != self._gen or self.path != "/my-files" or self.nodes or not devices:
                return
            names = ", ".join(d.name for d in devices[:3]) + ("…" if len(devices) > 3 else "")
            self.msg.set_text(_("My files is empty. Folders synced from your computers are under Computers: "
                                "{names}.").format(names=names))
            self.to_devices.show()
        run_bg(lambda: self.app.cli.list("/devices"), done, lambda _e: None)

    def _fill(self, keep_sel=False):
        sel = {r[0].name for r in self.store if r[1]} if keep_sel else set()
        self.store.clear()
        want = []
        for n in self.nodes:
            p = rjoin(self.path, n.name)
            if n.is_folder:
                st = self.stats.get(p)
                files, size = (str(st[0]), human_size(st[1])) if st else ("…", "…")
                want.append(p)                   # counted only when missing or older than a day
            else:
                files, size = "—", human_size(n.size)
            self.store.append([n, n.name in sel, file_icon(n), n.name, files, size, iso_date(n.modified)])
        if want:
            self.stats.want(want)
        self._sel_changed()

    def _stats_ready(self, path):
        if os.path.dirname(path.rstrip("/")) == self.path.rstrip("/"):
            self._fill(keep_sel=True)
        self.app.window.refresh_search()          # a search may now find more in subfolders

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
        self.sync_btn.set_sensitive(bool(self.sync_target()))
        self.rn_btn.set_sensitive(n == 1)
        self.tr_btn.set_sensitive(n > 0)

    def sync_target(self) -> str:
        """The folder "Sync to this computer…" means: the one ticked folder, else the folder open here."""
        sel = self.selected()
        if len(sel) == 1 and sel[0].is_folder:
            path = rjoin(self.path, sel[0].name)
        elif not sel:
            path = self.path
        else:
            return ""
        top = next((r for r in ("/my-files", "/devices") if path.startswith(r + "/")), "")
        if not top or (top == "/devices" and path.count("/") < 3):
            return ""                       # a whole section or a whole computer: pick a folder in it
        return path

    def _sync_here(self):
        path = self.sync_target()
        if path:
            self.app.window.folders.jump_to(path)

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
        elif n.type == "file":
            self.open_file(n)
        else:       # never "open" (= download) something that isn't one file: it can be a whole computer
            self.app.toast(_("Kluis can't open “{n}” here").format(n=n.name))

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
            msg = ngettext("Uploaded {n} file ✓", "Uploaded {n} files ✓", summary.transferred).format(
                n=summary.transferred)
            if summary.failed:
                msg = _("Uploaded {n}, {f} failed").format(n=summary.transferred, f=summary.failed)
            self.app.manager.log("error" if summary.failed else "ok", "", msg, _("into {t}").format(t=target))
            self.app.toast(msg)
            self.changed(target)
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
                   lambda _r: (self.app.toast(_("Created “{n}”").format(n=name)), self.changed(path)),
                   lambda e: self.app.toast(_("Couldn't create the folder: {e}").format(e=e)))

    def _rename_selected(self):
        sel = self.selected()
        if len(sel) != 1:
            return
        n = sel[0]
        name = ask_text(self.get_toplevel(), _("Rename “{n}”").format(n=n.name), initial=n.name, ok=_("Rename"))
        if name and name != n.name:
            here, old = self.path, rjoin(self.path, n.name)
            run_bg(lambda: self.app.cli.rename(old, name),
                   lambda _r: (self.app.toast(_("Renamed to “{n}”").format(n=name)),
                               shared_lists(self.app).forget("list:" + old), self.changed(here)),
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

        def done(found):
            for p in paths:
                shared_lists(self.app).forget("list:" + p)
            msg = ngettext("Moved {n} item to the Proton Drive trash", "Moved {n} items to the Proton Drive trash",
                           n).format(n=n)
            self.app.manager.log("info", "", msg)
            if found:
                self.app.toast(msg, (_("Undo"), lambda: self._restore(found, here)))
            else:
                # another item in the trash has the same name: restoring by name could hit it, so no Undo
                self.app.toast(msg + " · " + _("restore it on drive.proton.me"))
            self.changed(here)

        def work():
            self.app.cli.trash(paths)
            return self.app.cli.trashed(uids)
        run_bg(work, done, lambda e: self.app.toast(_("Couldn't move to the trash: {e}").format(e=e)))

    def _restore(self, nodes, here):
        def done(_r):
            self.app.toast(_("Restored from the Proton Drive trash"))
            self.changed(here)
        run_bg(lambda: self.app.cli.restore(nodes), done,
               lambda e: self.app.toast(_("Couldn't restore: {e}").format(e=e)))


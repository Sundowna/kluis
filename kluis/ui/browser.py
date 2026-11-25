"""Browse Proton Drive: open folders, download, upload (button or drag & drop), new folder, rename, trash."""
from __future__ import annotations

import os
from urllib.parse import unquote, urlparse

from gi.repository import Gdk, Gtk

from ..cli import rjoin
from .common import human_size, icon_button, iso_short, label, popover_menu, run_bg, styled, text_button
from .dialogs import ask_text, choose_local_folder, confirm, error_dialog

ROOT_NAMES = {"/my-files": "My files", "/devices": "Computers", "/shared-with-me": "Shared with me",
              "/trash": "Trash"}


def file_icon(n) -> str:
    if n.is_folder:
        return "folder"
    mt = n.media_type or ""
    for prefix, icon in (("image/", "image-x-generic"), ("video/", "video-x-generic"),
                         ("audio/", "audio-x-generic"), ("text/", "text-x-generic"),
                         ("application/pdf", "application-pdf"), ("application/zip", "package-x-generic")):
        if mt.startswith(prefix):
            return icon
    return "text-x-generic" if "." not in n.name else "application-x-generic"


class BrowserPage(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        styled(self, "k-page")
        self.app = app
        self.path = "/my-files"
        self.loaded_once = False

        bar = Gtk.Box(spacing=6)
        self.up_btn = icon_button("go-up-symbolic", "Up one folder", self._up)
        bar.pack_start(self.up_btn, False, False, 0)
        self.crumbs = Gtk.Box(spacing=2)
        bar.pack_start(self.crumbs, True, True, 0)
        bar.pack_start(icon_button("view-refresh-symbolic", "Refresh", self.load), False, False, 0)
        bar.pack_start(icon_button("folder-new-symbolic", "New folder", self._new_folder), False, False, 0)
        self.dl_btn = text_button("Download", self._download_selected, "k-pill", icon="folder-download-symbolic")
        bar.pack_start(self.dl_btn, False, False, 0)
        bar.pack_start(text_button("Upload…", self._upload_dialog, "k-pill", "k-accent",
                                   icon="document-send-symbolic"), False, False, 0)
        self.pack_start(bar, False, False, 0)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.MULTIPLE, activate_on_single_click=False)
        styled(self.list, "k-files")
        self.list.connect("row-activated", self._activate)
        self.list.connect("selected-rows-changed", lambda *_: self._sel_changed())
        self.list.connect("button-press-event", self._on_button)
        sw = Gtk.ScrolledWindow(vexpand=True)
        styled(sw, "frame")
        sw.add(self.list)
        self.stack.add_named(sw, "list")
        sp = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, valign=Gtk.Align.CENTER)
        sp.pack_start(Gtk.Spinner(active=True, width_request=32, height_request=32), False, False, 0)
        self.wait_lbl = label("Loading…", "k-dim", xalign=0.5)
        sp.pack_start(self.wait_lbl, False, False, 0)
        self.stack.add_named(sp, "loading")
        self.msg = label("", "k-dim", xalign=0.5, wrap=True)
        self.msg.set_valign(Gtk.Align.CENTER)
        self.stack.add_named(self.msg, "msg")
        self.pack_start(self.stack, True, True, 0)
        self.hint = label("Tip: drag files from the file manager here to upload them into this folder. "
                          "Double-click a folder to open it.", "k-dim", "k-small")
        self.pack_start(self.hint, False, False, 0)

        self.drag_dest_set(Gtk.DestDefaults.ALL, [Gtk.TargetEntry.new("text/uri-list", 0, 0)],
                           Gdk.DragAction.COPY)
        self.connect("drag-data-received", self._on_drop)
        self._sel_changed()

    # ---------- navigation ----------
    def on_shown(self):
        if not self.loaded_once:
            self.load()

    def _go(self, path):
        self.path = path
        self.load()

    def _up(self):
        parent = os.path.dirname(self.path.rstrip("/"))
        if parent and parent != "/":
            self._go(parent)

    def _crumbs(self):
        for c in self.crumbs.get_children():
            c.destroy()
        parts = [p for p in self.path.strip("/").split("/") if p]
        for i, p in enumerate(parts):
            if i:
                self.crumbs.pack_start(label("›", "k-dim"), False, False, 0)
            target = "/" + "/".join(parts[:i + 1])
            b = Gtk.Button(label=ROOT_NAMES.get(target, p))
            styled(b, "flat", "k-crumb")
            b.connect("clicked", lambda _b, t=target: self._go(t))
            self.crumbs.pack_start(b, False, False, 0)
        roots = Gtk.MenuButton(image=Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.BUTTON))
        styled(roots, "flat")
        roots.set_popover(popover_menu(roots, [(name, lambda p=p: self._go(p)) for p, name in ROOT_NAMES.items()
                                               if p != "/trash"]))
        self.crumbs.pack_start(roots, False, False, 0)
        self.crumbs.show_all()
        self.up_btn.set_sensitive(len(parts) > 1)

    def load(self):
        self.loaded_once = True
        self._crumbs()
        self.wait_lbl.set_text("Waiting for the current sync to finish…" if self.app.manager.busy
                               else "Loading…")
        self.stack.set_visible_child_name("loading")
        path = self.path

        def done(nodes):
            if path != self.path:
                return
            for r in self.list.get_children():
                r.destroy()
            nodes = sorted(nodes, key=lambda n: (not n.is_folder, n.name.lower()))
            if not nodes:
                self.msg.set_text("This folder is empty.\nDrop files here to upload them.")
                self.stack.set_visible_child_name("msg")
                return
            for n in nodes:
                self.list.add(self._row(n))
            self.list.show_all()
            self.stack.set_visible_child_name("list")

        def fail(e):
            self.msg.set_text(f"Could not open this folder.\n{e}")
            self.stack.set_visible_child_name("msg")
        run_bg(lambda: self.app.cli.list(path), done, fail)

    def _row(self, n):
        row = Gtk.ListBoxRow()
        row.node = n
        box = Gtk.Box(spacing=12)
        box.pack_start(Gtk.Image.new_from_icon_name(file_icon(n), Gtk.IconSize.LARGE_TOOLBAR), False, False, 0)
        name = label(n.name, ellipsize=True)
        box.pack_start(name, True, True, 0)
        if n.shared:
            box.pack_start(Gtk.Image.new_from_icon_name("emblem-shared-symbolic", Gtk.IconSize.BUTTON),
                           False, False, 0)
        box.pack_start(label("" if n.is_folder else human_size(n.size), "k-dim", "k-small", xalign=1),
                       False, False, 0)
        mod = label(iso_short(n.modified), "k-dim", "k-small", xalign=1)
        mod.set_width_chars(16)
        box.pack_start(mod, False, False, 0)
        more = Gtk.MenuButton(image=Gtk.Image.new_from_icon_name("view-more-symbolic", Gtk.IconSize.BUTTON))
        styled(more, "flat")
        more.set_popover(popover_menu(more, [
            ("Open" if n.is_folder else "Download…", lambda: self._activate(None, row) if n.is_folder
             else self._download([n])),
            ("Download…", lambda: self._download([n])) if n.is_folder else None,
            ("Rename…", lambda: self._rename(n)),
            None,
            ("Move to trash", lambda: self._trash([n]), True),
        ] if n.is_folder else [
            ("Download…", lambda: self._download([n])),
            ("Rename…", lambda: self._rename(n)),
            None,
            ("Move to trash", lambda: self._trash([n]), True),
        ]))
        box.pack_start(more, False, False, 0)
        row.add(box)
        return row

    def _activate(self, _lb, row):
        if row.node.is_folder:
            self._go(rjoin(self.path, row.node.name))
        else:
            self._download([row.node])

    def _on_button(self, _w, ev):
        if ev.type == Gdk.EventType.BUTTON_PRESS and ev.button == 3:
            row = self.list.get_row_at_y(int(ev.y))
            if row:
                if not row.is_selected():
                    self.list.unselect_all()
                    self.list.select_row(row)
                nodes = self._selected()
                pop = popover_menu(row, [
                    (f"Download {len(nodes)} item(s)…", lambda: self._download(nodes)),
                    None,
                    ("Move to trash", lambda: self._trash(nodes), True),
                ])
                pop.popup()
                return True
        return False

    def _selected(self):
        return [r.node for r in self.list.get_selected_rows()]

    def _sel_changed(self):
        n = len(self._selected())
        self.dl_btn.set_sensitive(n > 0)
        self.dl_btn.set_tooltip_text(f"Download {n} selected item(s)" if n else "Select files to download")

    # ---------- actions ----------
    def _busy(self, text):
        self.wait_lbl.set_text(text)
        self.stack.set_visible_child_name("loading")

    def _download_selected(self):
        self._download(self._selected())

    def _download(self, nodes):
        if not nodes:
            return
        dest = choose_local_folder(self.get_toplevel(), "Download to…", os.path.expanduser("~/Downloads"))
        if not dest:
            return
        self._busy(f"Downloading {len(nodes)} item(s)…")
        paths = [rjoin(self.path, n.name) for n in nodes]

        def done(summary):
            self.app.manager.log("ok", "", f"Downloaded {summary.transferred} file(s) to {dest}")
            self.app.toast(f"Downloaded {summary.transferred} file(s)", ("Open folder", lambda: self._open(dest)))
            self.load()
        run_bg(lambda: self.app.cli.download(paths, dest, file_strategy="rename", folder_strategy="merge"),
               done, lambda e: (error_dialog(self.get_toplevel(), "Download failed", str(e)), self.load()))

    @staticmethod
    def _open(path):
        from .common import open_path
        open_path(path)

    def _upload(self, local_paths):
        if not local_paths:
            return
        self._busy(f"Uploading {len(local_paths)} item(s)…")
        target = self.path

        def done(summary):
            msg = f"Uploaded {summary.transferred} file(s) to {target}"
            if summary.failed:
                msg += f", {summary.failed} failed"
            self.app.manager.log("error" if summary.failed else "ok", "", msg)
            self.app.toast(msg)
            self.load()
        run_bg(lambda: self.app.cli.upload(local_paths, target, file_strategy="rename"), done,
               lambda e: (error_dialog(self.get_toplevel(), "Upload failed", str(e)), self.load()))

    def _upload_dialog(self):
        fc = Gtk.FileChooserNative.new("Upload to Proton Drive", self.get_toplevel(), Gtk.FileChooserAction.OPEN,
                                       "Upload", "Cancel")
        fc.set_select_multiple(True)
        if fc.run() == Gtk.ResponseType.ACCEPT:
            self._upload(fc.get_filenames())
        fc.destroy()

    def _on_drop(self, _w, _ctx, _x, _y, data, _info, _time):
        paths = [unquote(urlparse(u).path) for u in data.get_uris() if u.startswith("file://")]
        self._upload([p for p in paths if os.path.exists(p)])

    def _new_folder(self):
        name = ask_text(self.get_toplevel(), "New folder", "Folder name")
        if name:
            run_bg(lambda: self.app.cli.create_folder(self.path, name, exist_ok=False), lambda _r: self.load(),
                   lambda e: error_dialog(self.get_toplevel(), "Could not create the folder", str(e)))

    def _rename(self, n):
        name = ask_text(self.get_toplevel(), f"Rename “{n.name}”", initial=n.name)
        if name and name != n.name:
            run_bg(lambda: self.app.cli.rename(rjoin(self.path, n.name), name), lambda _r: self.load(),
                   lambda e: error_dialog(self.get_toplevel(), "Rename failed", str(e)))

    def _trash(self, nodes):
        if not nodes:
            return
        names = ", ".join(n.name for n in nodes[:3]) + ("…" if len(nodes) > 3 else "")
        if not confirm(self.get_toplevel(), f"Move {len(nodes)} item(s) to the trash?",
                       f"{names}\nYou can restore them from the Proton Drive trash.", ok="Move to trash"):
            return
        paths = [rjoin(self.path, n.name) for n in nodes]
        run_bg(lambda: self.app.cli.trash(paths), lambda _r: self.load(),
               lambda e: error_dialog(self.get_toplevel(), "Could not move to trash", str(e)))

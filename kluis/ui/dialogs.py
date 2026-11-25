"""Folder editor, Proton Drive folder picker and settings."""
from __future__ import annotations

import os

from gi.repository import Gtk

from ..cli import CliError, rjoin
from ..config import DEFAULT_IGNORES, MODES, FolderPair
from .common import label, run_bg, short_path, styled, text_button

REMOTE_ROOTS = ("/my-files", "/devices", "/shared-with-me")


def _dialog(parent, title, ok_text=None, width=560):
    d = Gtk.Dialog(transient_for=parent, modal=True, use_header_bar=True)
    d.set_title(title)
    d.set_default_size(width, -1)
    d.add_button("Cancel", Gtk.ResponseType.CANCEL)
    if ok_text:
        ok = d.add_button(ok_text, Gtk.ResponseType.OK)
        styled(ok, "k-accent", "k-pill")
        d.set_default_response(Gtk.ResponseType.OK)
    area = d.get_content_area()
    area.set_spacing(12)
    area.set_border_width(18)
    return d, area


def error_dialog(parent, title, text):
    m = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.ERROR,
                          buttons=Gtk.ButtonsType.CLOSE, text=title)
    m.format_secondary_text(text)
    m.run()
    m.destroy()


def confirm(parent, title, text, ok="Remove", destructive=True) -> bool:
    m = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.QUESTION,
                          buttons=Gtk.ButtonsType.NONE, text=title)
    m.format_secondary_text(text)
    m.add_button("Cancel", Gtk.ResponseType.CANCEL)
    b = m.add_button(ok, Gtk.ResponseType.OK)
    styled(b, "destructive-action" if destructive else "suggested-action")
    r = m.run() == Gtk.ResponseType.OK
    m.destroy()
    return r


def ask_text(parent, title, placeholder="", initial="") -> str | None:
    d, area = _dialog(parent, title, "OK", 380)
    e = Gtk.Entry(text=initial, placeholder_text=placeholder, activates_default=True)
    area.pack_start(e, False, False, 0)
    d.show_all()
    r = d.run()
    text = e.get_text().strip()
    d.destroy()
    return text if r == Gtk.ResponseType.OK and text else None


def choose_local_folder(parent, title="Choose a folder", start=None) -> str | None:
    fc = Gtk.FileChooserNative.new(title, parent, Gtk.FileChooserAction.SELECT_FOLDER, "Select", "Cancel")
    if start and os.path.isdir(start):
        fc.set_current_folder(start)
    r = fc.run()
    path = fc.get_filename() if r == Gtk.ResponseType.ACCEPT else None
    fc.destroy()
    return path


class RemotePicker:
    """Browse Proton Drive folders and pick one."""

    def __init__(self, parent, cli, start="/my-files"):
        self.cli = cli
        self.path = start if any(start.startswith(r) for r in REMOTE_ROOTS) else "/my-files"
        self.dialog, area = _dialog(parent, "Choose a Proton Drive folder", "Select this folder", 520)
        self.dialog.set_default_size(520, 480)
        self.crumbs = Gtk.Box(spacing=2)
        area.pack_start(self.crumbs, False, False, 0)
        self.stack = Gtk.Stack()
        self.list = Gtk.ListBox()
        self.list.connect("row-activated", self._enter)
        sw = Gtk.ScrolledWindow(vexpand=True)
        sw.add(self.list)
        styled(sw, "frame")
        self.stack.add_named(sw, "list")
        spin = Gtk.Spinner(active=True, width_request=32, height_request=32)
        self.stack.add_named(spin, "loading")
        self.msg = label("", "k-dim", xalign=0.5, wrap=True)
        self.stack.add_named(self.msg, "msg")
        area.pack_start(self.stack, True, True, 0)
        bar = Gtk.Box(spacing=8)
        bar.pack_start(text_button("New folder", self._new_folder, icon="folder-new-symbolic"), False, False, 0)
        self.sel = label("", "k-dim", "k-small", ellipsize=True)
        bar.pack_start(self.sel, True, True, 0)
        area.pack_start(bar, False, False, 0)
        self._load()

    def run(self) -> str | None:
        self.dialog.show_all()
        self._load()
        r = self.dialog.run()
        path = self.path
        self.dialog.destroy()
        return path if r == Gtk.ResponseType.OK else None

    def _crumbs(self):
        for c in self.crumbs.get_children():
            c.destroy()
        parts = [p for p in self.path.strip("/").split("/") if p]
        for i, p in enumerate(parts):
            if i:
                self.crumbs.pack_start(label("›", "k-dim"), False, False, 0)
            target = "/" + "/".join(parts[:i + 1])
            b = Gtk.Button(label="My files" if target == "/my-files" else p)
            styled(b, "flat", "k-crumb")
            b.connect("clicked", lambda _b, t=target: self._go(t))
            self.crumbs.pack_start(b, False, False, 0)
        self.crumbs.show_all()
        self.sel.set_text(f"Selected: {self.path}")

    def _go(self, path):
        self.path = path
        self._load()

    def _load(self):
        self._crumbs()
        self.stack.set_visible_child_name("loading")

        def done(nodes):
            for r in self.list.get_children():
                r.destroy()
            folders = [n for n in nodes if n.is_folder]
            if not folders:
                self.msg.set_text("No folders here. You can select this folder or create a new one.")
                self.stack.set_visible_child_name("msg")
                return
            for n in sorted(folders, key=lambda n: n.name.lower()):
                row = Gtk.ListBoxRow()
                row.node_name = n.name
                box = Gtk.Box(spacing=10, margin=8)
                box.pack_start(Gtk.Image.new_from_icon_name("folder", Gtk.IconSize.LARGE_TOOLBAR), False, False, 0)
                box.pack_start(label(n.name, ellipsize=True), True, True, 0)
                box.pack_start(Gtk.Image.new_from_icon_name("go-next-symbolic", Gtk.IconSize.BUTTON), False, False, 0)
                row.add(box)
                self.list.add(row)
            self.list.show_all()
            self.stack.set_visible_child_name("list")

        def fail(e):
            self.msg.set_text(f"This folder does not exist yet. It will be created when you sync.\n\n{e}"
                              if isinstance(e, CliError) and e.not_found else str(e))
            self.stack.set_visible_child_name("msg")
        run_bg(lambda: self.cli.list(self.path), done, fail)

    def _enter(self, _lb, row):
        self._go(rjoin(self.path, row.node_name))

    def _new_folder(self):
        name = ask_text(self.dialog, "New folder", "Folder name")
        if not name:
            return
        run_bg(lambda: self.cli.create_folder(self.path, name), lambda _r: self._go(rjoin(self.path, name)),
               lambda e: error_dialog(self.dialog, "Could not create the folder", str(e)))


class FolderDialog:
    def __init__(self, parent, app, folder: FolderPair | None = None, local: str | None = None):
        self.app = app
        self.folder = folder
        editing = folder is not None
        self.dialog, area = _dialog(parent, "Edit synced folder" if editing else "Add a folder to sync",
                                    "Save" if editing else "Start syncing", 620)
        self.local = folder.local if folder else (local or "")
        self.remote_touched = editing

        # --- local + remote ---
        grid = Gtk.Grid(column_spacing=12, row_spacing=10)
        grid.attach(label("On this computer", "k-dim"), 0, 0, 1, 1)
        self.local_btn = Gtk.Button(hexpand=True)
        self.local_lbl = label("", ellipsize=True)
        lb = Gtk.Box(spacing=8)
        lb.pack_start(Gtk.Image.new_from_icon_name("folder-symbolic", Gtk.IconSize.BUTTON), False, False, 0)
        lb.pack_start(self.local_lbl, True, True, 0)
        self.local_btn.add(lb)
        self.local_btn.connect("clicked", lambda *_: self._pick_local())
        grid.attach(self.local_btn, 1, 0, 1, 1)

        grid.attach(label("In Proton Drive", "k-dim"), 0, 1, 1, 1)
        rb = Gtk.Box(spacing=6)
        self.remote = Gtk.Entry(hexpand=True, text=folder.remote if folder else "")
        self.remote.connect("changed", self._remote_edited)
        rb.pack_start(self.remote, True, True, 0)
        rb.pack_start(text_button("Browse…", self._pick_remote), False, False, 0)
        grid.attach(rb, 1, 1, 1, 1)
        area.pack_start(grid, False, False, 0)

        # --- mode cards ---
        area.pack_start(label("How should it sync?", "k-section"), False, False, 0)
        modes = Gtk.Box(spacing=10, homogeneous=True)
        self.mode_buttons = {}
        group = None
        for key, (glyph, title, desc) in MODES.items():
            b = Gtk.RadioButton.new_from_widget(group)
            group = group or b
            b.set_mode(False)
            styled(b, "k-mode")
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            top = Gtk.Box(spacing=8)
            g = label(glyph, "k-mode-glyph")
            top.pack_start(g, False, False, 0)
            top.pack_start(label(title, "k-card-title"), False, False, 0)
            v.pack_start(top, False, False, 0)
            d = label(desc, "k-dim", "k-small", wrap=True)
            d.set_max_width_chars(22)
            v.pack_start(d, False, False, 0)
            b.add(v)
            b.connect("toggled", lambda *_: self._update_preview())
            modes.pack_start(b, True, True, 0)
            self.mode_buttons[key] = b
        self.mode_buttons[folder.mode if folder else "two-way"].set_active(True)
        area.pack_start(modes, False, False, 0)

        self.preview = label("", "k-dim", wrap=True)
        area.pack_start(self.preview, False, False, 0)

        # --- advanced ---
        exp = Gtk.Expander(label="More options")
        adv = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=8)
        self.watch = Gtk.Switch(active=folder.watch if folder else True, valign=Gtk.Align.CENTER)
        adv.pack_start(self._switch_row("Sync soon after I change files",
                                        "Watches this folder and syncs about 10 seconds after a change.",
                                        self.watch), False, False, 0)
        self.deletions = Gtk.Switch(active=folder.mirror_deletions if folder else True, valign=Gtk.Align.CENTER)
        adv.pack_start(self._switch_row("Copy deletions to the other side",
                                        "Deleted files go to the Trash on the other side, never deleted for good. "
                                        "Off: deleted files come back.", self.deletions), False, False, 0)
        adv.pack_start(label("Skip files that match (one pattern per line)", "k-dim"), False, False, 0)
        self.ignore = Gtk.TextView(monospace=True, wrap_mode=Gtk.WrapMode.NONE, top_margin=6, left_margin=6)
        self.ignore.get_buffer().set_text("\n".join(folder.ignore if folder else DEFAULT_IGNORES))
        sw = Gtk.ScrolledWindow(min_content_height=90)
        styled(sw, "frame")
        sw.add(self.ignore)
        adv.pack_start(sw, False, False, 0)
        if editing:
            self.reset = Gtk.CheckButton(label="Check every file again on the next sync (slower, fixes odd states)")
            adv.pack_start(self.reset, False, False, 0)
        exp.add(adv)
        area.pack_start(exp, False, False, 0)
        self._set_local(self.local)

    @staticmethod
    def _switch_row(title, sub, switch):
        row = Gtk.Box(spacing=12)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        v.pack_start(label(title), False, False, 0)
        s = label(sub, "k-dim", "k-small", wrap=True)
        s.set_max_width_chars(60)
        v.pack_start(s, False, False, 0)
        row.pack_start(v, True, True, 0)
        row.pack_start(switch, False, False, 0)
        return row

    def mode(self) -> str:
        return next(k for k, b in self.mode_buttons.items() if b.get_active())

    def _set_local(self, path):
        self.local = path
        self.local_lbl.set_text(short_path(path) if path else "Choose a folder…")
        if path and not self.remote_touched:
            self.remote.handler_block_by_func(self._remote_edited)
            self.remote.set_text(rjoin("/my-files", os.path.basename(path.rstrip("/"))))
            self.remote.handler_unblock_by_func(self._remote_edited)
        self._update_preview()

    def _remote_edited(self, *_):
        self.remote_touched = True
        self._update_preview()

    def _pick_local(self):
        p = choose_local_folder(self.dialog, start=self.local or os.path.expanduser("~"))
        if p:
            self._set_local(p)

    def _pick_remote(self):
        p = RemotePicker(self.dialog, self.app.cli, self.remote.get_text() or "/my-files").run()
        if p:
            self.remote.set_text(p)

    def _update_preview(self):
        if not self.local:
            self.preview.set_text("")
            return
        loc, rem = short_path(self.local), self.remote.get_text().strip() or "…"
        text = {
            "two-way": f"{loc}  ⇄  {rem}\nEdits, new files and deletions travel both ways.",
            "backup": f"{loc}  →  {rem}\nNew and changed files are uploaded. Nothing is deleted in Proton Drive.",
            "mirror": f"{rem}  →  {loc}\nProton Drive is the source. Local edits are kept as conflict copies.",
        }[self.mode()]
        self.preview.set_text(text)

    def _validate(self) -> str | None:
        if not self.local or not os.path.isdir(self.local):
            return "Choose a folder on this computer."
        rem = self.remote.get_text().strip()
        if not any(rem == r or rem.startswith(r + "/") for r in REMOTE_ROOTS):
            return "The Proton Drive folder must start with /my-files (or /devices, /shared-with-me)."
        if rem in REMOTE_ROOTS and self.mode() != "mirror":
            return "Pick or type a folder inside /my-files rather than the root itself."
        other = self.app.settings.overlaps(self.local, self.folder.id if self.folder else "")
        if other:
            return f"This overlaps with a folder you already sync: {short_path(other.local)}"
        if os.path.realpath(self.local) == os.path.expanduser("~"):
            return "Syncing your whole home folder is not supported. Pick a folder inside it."
        return None

    def run(self) -> tuple[FolderPair, bool] | None:
        self.dialog.show_all()
        while True:
            r = self.dialog.run()
            if r != Gtk.ResponseType.OK:
                self.dialog.destroy()
                return None
            problem = self._validate()
            if problem:
                error_dialog(self.dialog, "Almost there", problem)
                continue
            break
        buf = self.ignore.get_buffer()
        ignores = [x.strip() for x in buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).splitlines()
                   if x.strip()]
        f = self.folder or FolderPair(local="", remote="")
        changed_target = self.folder is not None and (
            f.local != self.local or f.remote != self.remote.get_text().strip() or f.mode != self.mode())
        f.local = os.path.realpath(self.local)
        f.remote = rjoin(self.remote.get_text().strip())
        f.mode = self.mode()
        f.watch = self.watch.get_active()
        f.mirror_deletions = self.deletions.get_active()
        f.ignore = ignores
        reset = changed_target or (hasattr(self, "reset") and self.reset.get_active())
        self.dialog.destroy()
        return f, reset


class SettingsDialog:
    def __init__(self, parent, app):
        self.app = app
        s = app.settings
        self.dialog = Gtk.Dialog(transient_for=parent, modal=True, use_header_bar=True, title="Settings")
        self.dialog.set_default_size(560, 600)
        area = self.dialog.get_content_area()
        sw = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin=18)
        sw.add(body)
        area.pack_start(sw, True, True, 0)

        def group(title, rows):
            body.pack_start(label(title, "k-settings-head"), False, False, 0)
            g = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            styled(g, "k-settings-group")
            for title_, sub, widget in rows:
                r = Gtk.Box(spacing=12)
                v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
                v.pack_start(label(title_), False, False, 0)
                if sub:
                    sl = label(sub, "k-dim", "k-small", wrap=True)
                    sl.set_max_width_chars(48)
                    v.pack_start(sl, False, False, 0)
                r.pack_start(v, True, True, 0)
                widget.set_valign(Gtk.Align.CENTER)
                r.pack_start(widget, False, False, 0)
                g.pack_start(r, False, False, 0)
            body.pack_start(g, False, False, 0)

        self.autostart = Gtk.Switch(active=s.autostart)
        self.minimized = Gtk.Switch(active=s.start_minimized)
        self.interval = Gtk.SpinButton.new_with_range(5, 720, 5)
        self.interval.set_value(s.interval_minutes)
        self.notify = Gtk.ComboBoxText()
        for k, t in (("all", "Everything"), ("important", "Only problems and conflicts"), ("off", "Off")):
            self.notify.append(k, t)
        self.notify.set_active_id(s.notifications)
        self.theme = Gtk.ComboBoxText()
        for k, t in (("system", "Follow system"), ("light", "Light"), ("dark", "Dark")):
            self.theme.append(k, t)
        self.theme.set_active_id(s.theme)
        group("General", [
            ("Start Kluis when I log in", None, self.autostart),
            ("Start hidden in the panel", "Only the tray icon shows at login.", self.minimized),
            ("Check Proton Drive every … minutes", "Local changes sync within seconds anyway.", self.interval),
            ("Notifications", None, self.notify),
            ("Appearance", None, self.theme),
        ])

        self.cli_lbl = label(short_path(app.cli.path or "not found"), "k-mono", ellipsize=True)
        self.cli_lbl.set_max_width_chars(28)
        change = text_button("Change…", self._change_cli)
        self.update_btn = text_button("Check for update", self._check_update)
        self.thumbs = Gtk.Switch(active=s.skip_thumbnails)
        self.version_lbl = label("…", "k-dim")
        group("Proton Drive CLI", [
            ("Location", None, self.cli_lbl),
            ("Use another copy", None, change),
            ("Version", None, self.version_lbl),
            ("Updates", "Downloads the newest official build from proton.me and checks its SHA-512.",
             self.update_btn),
            ("Skip image previews when uploading", "Faster uploads; Proton Drive shows no thumbnails.",
             self.thumbs),
        ])
        out = text_button("Sign out", self._sign_out, "destructive-action")
        group("Account", [("Sign out of Proton Drive", "Syncing stops until you sign in again.", out)])
        logs = text_button("Open log folder", self._open_logs)
        group("Troubleshooting", [("Logs", "Kluis and the Proton Drive CLI write logs here.", logs)])

        run_bg(app.cli.version, lambda v: self.version_lbl.set_text(v), lambda e: self.version_lbl.set_text("?"))

    def _change_cli(self):
        fc = Gtk.FileChooserNative.new("Choose the proton-drive program", self.dialog, Gtk.FileChooserAction.OPEN,
                                       "Select", "Cancel")
        if fc.run() == Gtk.ResponseType.ACCEPT:
            self.app.set_cli_path(fc.get_filename())
            self.cli_lbl.set_text(short_path(self.app.cli.path))
            run_bg(self.app.cli.version, lambda v: self.version_lbl.set_text(v))
        fc.destroy()

    def _check_update(self):
        self.update_btn.set_sensitive(False)
        self.app.update_cli(self.dialog, lambda: (self.update_btn.set_sensitive(True),
                                                  run_bg(self.app.cli.version,
                                                         lambda v: self.version_lbl.set_text(v))))

    def _sign_out(self):
        if confirm(self.dialog, "Sign out of Proton Drive?", "Syncing stops until you sign in again. "
                   "Your files stay where they are.", ok="Sign out"):
            self.dialog.response(Gtk.ResponseType.CLOSE)
            self.app.sign_out()

    def _open_logs(self):
        from ..paths import STATE_DIR
        from .common import open_path
        open_path(str(STATE_DIR))

    def run(self):
        self.dialog.show_all()
        self.dialog.run()
        s = self.app.settings
        s.autostart = self.autostart.get_active()
        s.start_minimized = self.minimized.get_active()
        s.interval_minutes = int(self.interval.get_value())
        s.notifications = self.notify.get_active_id()
        s.theme = self.theme.get_active_id()
        s.skip_thumbnails = self.thumbs.get_active()
        self.app.cli.skip_thumbnails = s.skip_thumbnails
        s.save()
        self.app.apply_settings()
        self.dialog.destroy()

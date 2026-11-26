"""Dialogs: confirm, text input, folder pickers, Add/Edit folder, Settings."""
from __future__ import annotations

import os
import time

from gi.repository import Gdk, GLib, Gtk

from .. import VERSION
from ..cli import CliError, rjoin
from ..config import DEFAULT_IGNORES, INTERVALS, MODES, FolderPair, validate_local
from ..i18n import _, complete_languages
from .common import (a11y, button, clear, combo, hbox, label, run_bg, short_path, styled, switch, vbox)

REMOTE_ROOTS = ("/my-files", "/devices", "/shared-with-me")

# Tests answer native file choosers through this queue (KLUIS_TEST=1 only); a real run uses the portal.
TEST_ANSWERS: list = []


def _testing() -> bool:
    return os.environ.get("KLUIS_TEST") == "1"


def _dialog(parent, title, width=560):
    d = Gtk.Dialog(transient_for=parent, modal=True, use_header_bar=True, title=title)
    d.set_default_size(width, -1)
    styled(d, "kluis", "k-dialog")
    area = d.get_content_area()
    area.set_spacing(14)
    area.set_border_width(22)
    a11y(d, title)
    return d, area


def _footer(d, *buttons):
    """Our own button row (44 px dialog buttons, §5), so wording and defaults are exact."""
    row = Gtk.Box(spacing=10, halign=Gtk.Align.END, margin_top=10)
    for b in buttons:
        styled(b, "k-big")
        row.pack_start(b, False, False, 0)
    d.get_content_area().pack_end(row, False, False, 0)
    return row


def confirm(parent, title, text, ok, cancel, destructive=False, default="cancel") -> bool:
    """default: 'cancel' (Enter and Esc keep), 'ok', or 'none' (no default; Esc keeps)."""
    d, area = _dialog(parent, title, 480)
    d.set_title("Kluis")              # the question is the dialog's body (and its accessible name)
    area.pack_start(label(title, "k-h2", wrap=True, max_chars=50), False, False, 0)
    if text:
        area.pack_start(label(text, "k-muted", wrap=True, max_chars=60), False, False, 0)
    res = {"ok": False}
    no = button(cancel, lambda: d.response(Gtk.ResponseType.CANCEL))
    yes = button(ok, lambda: (res.update(ok=True), d.response(Gtk.ResponseType.OK)),
                 "destructive-action" if destructive else "suggested-action")
    _footer(d, no, yes)
    d.show_all()
    if default == "ok":
        yes.grab_focus()
    elif default == "cancel":
        no.grab_focus()
    else:
        d.set_focus(None)          # no default: Enter does nothing, Esc keeps
    d.kluis_buttons = (no, yes)
    d.run()
    d.destroy()
    return res["ok"]


def ask_text(parent, title, placeholder="", initial="", ok=_("Save")) -> str | None:
    d, area = _dialog(parent, title, 420)
    e = Gtk.Entry(text=initial, placeholder_text=placeholder, activates_default=True)
    a11y(e, title)
    area.pack_start(label(title, "k-h3"), False, False, 0)
    area.pack_start(e, False, False, 0)
    res = {"v": None}

    def done():
        t = e.get_text().strip()
        if t:
            res["v"] = t
            d.response(Gtk.ResponseType.OK)
    okb = button(ok, done, "suggested-action")
    e.connect("activate", lambda *_: done())
    _footer(d, button(_("Cancel"), lambda: d.response(Gtk.ResponseType.CANCEL)), okb)
    d.show_all()
    e.grab_focus()
    d.run()
    d.destroy()
    return res["v"]


def choose_local_folder(parent, title=_("Choose a folder"), start=None) -> str | None:
    if _testing():
        return TEST_ANSWERS.pop(0) if TEST_ANSWERS else None
    fc = Gtk.FileChooserNative.new(title, parent, Gtk.FileChooserAction.SELECT_FOLDER, _("Select"), _("Cancel"))
    if start and os.path.isdir(start):
        fc.set_current_folder(start)
    r = fc.run()
    path = fc.get_filename() if r == Gtk.ResponseType.ACCEPT else None
    fc.destroy()
    return path


def choose_files(parent, title=_("Choose files")) -> list[str]:
    if _testing():
        return TEST_ANSWERS.pop(0) if TEST_ANSWERS else []
    fc = Gtk.FileChooserNative.new(title, parent, Gtk.FileChooserAction.OPEN, _("Upload"), _("Cancel"))
    fc.set_select_multiple(True)
    r = fc.run()
    paths = fc.get_filenames() if r == Gtk.ResponseType.ACCEPT else []
    fc.destroy()
    return paths


def choose_file(parent, title, start=None) -> str | None:
    if _testing():
        return TEST_ANSWERS.pop(0) if TEST_ANSWERS else None
    fc = Gtk.FileChooserNative.new(title, parent, Gtk.FileChooserAction.OPEN, _("Select"), _("Cancel"))
    if start and os.path.isdir(start):
        fc.set_current_folder(start)
    r = fc.run()
    p = fc.get_filename() if r == Gtk.ResponseType.ACCEPT else None
    fc.destroy()
    return p


class RemotePicker:
    """Browse Proton Drive folders and pick one (with New folder)."""

    def __init__(self, parent, cli, start="/my-files"):
        self.cli = cli
        self.path = start if any(start == r or start.startswith(r + "/") for r in REMOTE_ROOTS) else "/my-files"
        self.dialog, area = _dialog(parent, _("Choose a Proton Drive folder"), 540)
        self.dialog.set_default_size(540, 500)
        self.crumbs = Gtk.Box(spacing=2)
        area.pack_start(self.crumbs, False, False, 0)
        self.stack = Gtk.Stack()
        self.list = Gtk.ListBox()
        self.list.connect("row-activated", self._enter)
        sw = Gtk.ScrolledWindow(vexpand=True)
        sw.add(self.list)
        styled(sw, "k-card")
        self.stack.add_named(sw, "list")
        self.stack.add_named(Gtk.Spinner(active=True, width_request=32, height_request=32), "loading")
        self.msg = label("", "k-muted", xalign=0.5, wrap=True)
        self.stack.add_named(self.msg, "msg")
        area.pack_start(self.stack, True, True, 0)
        self.sel = label("", "k-muted", "k-s12", ellipsize=True)
        area.pack_start(self.sel, False, False, 0)
        self.ok = button(_("Select this folder"), lambda: self.dialog.response(Gtk.ResponseType.OK), "suggested-action")
        _footer(self.dialog, button(_("+ New folder"), self._new_folder),
                button(_("Cancel"), lambda: self.dialog.response(Gtk.ResponseType.CANCEL)), self.ok)

    def run(self) -> str | None:
        self.dialog.show_all()
        self._load()
        r = self.dialog.run()
        path = self.path
        self.dialog.destroy()
        return path if r == Gtk.ResponseType.OK else None

    def _crumbs(self):
        clear(self.crumbs)
        parts = [p for p in self.path.strip("/").split("/") if p]
        for i, p in enumerate(parts):
            if i:
                self.crumbs.pack_start(label("›", "k-muted"), False, False, 0)
            target = "/" + "/".join(parts[:i + 1])
            name = {"/my-files": _("My files"), "/devices": _("Computers"),
                    "/shared-with-me": _("Shared with me")}.get(target, p)
            self.crumbs.pack_start(button(name, lambda t=target: self._go(t), "k-flat", "k-small"), False, False, 0)
        self.crumbs.show_all()
        self.sel.set_text(_("Selected: {p}").format(p=self.path))

    def _go(self, path):
        self.path = path
        self._load()

    def _load(self):
        self._crumbs()
        self.stack.set_visible_child_name("loading")
        path = self.path

        def done(nodes):
            if path != self.path:
                return
            clear(self.list)
            folders = [n for n in nodes if n.is_folder]
            if not folders:
                self.msg.set_text(_("No folders here. You can select this folder or create a new one."))
                self.stack.set_visible_child_name("msg")
                return
            for n in sorted(folders, key=lambda n: n.name.lower()):
                row = Gtk.ListBoxRow()
                row.node_name = n.name
                box = hbox(Gtk.Image.new_from_icon_name("folder", Gtk.IconSize.LARGE_TOOLBAR),
                           label(n.name, ellipsize=True), spacing=10, margin=8)
                row.add(box)
                a11y(row, n.name)
                self.list.add(row)
            self.list.show_all()
            self.stack.set_visible_child_name("list")

        def fail(e):
            self.msg.set_text(_("This folder doesn't exist yet. It will be created when you sync.")
                              if isinstance(e, CliError) and e.not_found else str(e))
            self.stack.set_visible_child_name("msg")
        run_bg(lambda: self.cli.list(path), done, fail)

    def _enter(self, _lb, row):
        self._go(rjoin(self.path, row.node_name))

    def _new_folder(self):
        name = ask_text(self.dialog, _("New folder"), _("Folder name"), ok=_("Create"))
        if not name:
            return
        run_bg(lambda: self.cli.create_folder(self.path, name), lambda _r: self._go(rjoin(self.path, name)),
               lambda e: confirm(self.dialog, _("Couldn't create the folder"), str(e), _("OK"), _("Close")))


class FolderDialog:
    """Add a folder (§3.3) or Edit synced folder (§9b)."""

    def __init__(self, parent, app, folder: FolderPair | None = None, local: str | None = None,
                 remote: str | None = None, mode: str | None = None):
        self.app = app
        self.folder = folder
        editing = folder is not None
        title = _("Edit synced folder") if editing else _("Add a folder")
        self.dialog, area = _dialog(parent, title, 640)
        self.local = folder.local if folder else (local or "")
        self.remote = folder.remote if folder else (remote or "")
        self.remote_touched = editing or bool(remote)
        area.pack_start(label(title, "k-h1"), False, False, 0)

        area.pack_start(label(_("Folder on this computer"), "k-section-head"), False, False, 0)
        self.local_btn = button(_("Choose a folder…"), self._pick_local, "k-big", icon="folder-symbolic",
                                name=_("Folder on this computer"))
        self.local_err = label("", "k-inline-error", wrap=True)
        area.pack_start(hbox(self.local_btn, self.local_err, spacing=12), False, False, 0)

        area.pack_start(label(_("Folder in Proton Drive"), "k-section-head"), False, False, 0)
        self.remote_btn = button("…", self._pick_remote, "k-big", icon="folder-remote-symbolic",
                                 name=_("Folder in Proton Drive"))
        self.remote_err = label("", "k-inline-error", wrap=True)
        area.pack_start(hbox(self.remote_btn, self.remote_err, spacing=12), False, False, 0)

        area.pack_start(label(_("How should it sync?"), "k-section-head"), False, False, 0)
        modes = Gtk.Box(spacing=10, homogeneous=True)
        self.mode_buttons = {}
        group = None
        for key, (glyph, mtitle, desc) in MODES.items():
            b = Gtk.RadioButton.new_from_widget(group)
            group = group or b
            b.set_mode(False)
            styled(b, "k-modecard")
            v = vbox(label(f"{glyph} {mtitle}", "k-h3"), label(desc, "k-muted", "k-s12", wrap=True, max_chars=24),
                     spacing=4)
            b.add(v)
            b.connect("toggled", lambda *_: self._validate())
            a11y(b, f"{glyph} {mtitle}")
            modes.pack_start(b, True, True, 0)
            self.mode_buttons[key] = b
        area.pack_start(modes, False, False, 0)
        self.share_note = label("", "k-muted", "k-s12", wrap=True)
        area.pack_start(self.share_note, False, False, 0)

        exp = Gtk.Expander(label=_("More options"))
        a11y(exp, _("More options"))
        adv = vbox(spacing=10, margin_top=8)
        self.watch = switch(folder.watch if folder else True, name=_("Sync soon after I change files"))
        adv.pack_start(self._switch_row(_("Sync soon after I change files"),
                                        _("Watches this folder and syncs about 10 seconds after a change."),
                                        self.watch), False, False, 0)
        self.deletions = switch(folder.mirror_deletions if folder else True, name=_("Copy deletions to the other side"))
        adv.pack_start(self._switch_row(_("Copy deletions to the other side"),
                                        _("Deleted files go to the trash on the other side, never deleted for good. "
                                          "Off: deleted files come back."), self.deletions), False, False, 0)
        adv.pack_start(label(_("Skip files that match (one pattern per line)"), "k-muted"), False, False, 0)
        self.ignore = Gtk.TextView(monospace=True, wrap_mode=Gtk.WrapMode.NONE, top_margin=6, left_margin=6)
        a11y(self.ignore, _("Skip files that match"))
        self.ignore.get_buffer().set_text("\n".join(folder.ignore if folder else DEFAULT_IGNORES))
        sw = Gtk.ScrolledWindow(min_content_height=90)
        styled(sw, "k-card")
        sw.add(self.ignore)
        adv.pack_start(sw, False, False, 0)
        self.reset = Gtk.CheckButton(label=_("Check every file again on the next sync"))
        a11y(self.reset, _("Check every file again on the next sync"))
        adv.pack_start(self.reset, False, False, 0)
        exp.add(adv)
        area.pack_start(exp, False, False, 0)
        self.expander = exp

        self.start = button(_("Save") if editing else _("Start syncing"),
                            lambda: self.dialog.response(Gtk.ResponseType.OK), "suggested-action")
        _footer(self.dialog, button(_("Cancel"), lambda: self.dialog.response(Gtk.ResponseType.CANCEL)), self.start)
        self.mode_buttons[(folder.mode if folder else mode) or "two-way"].set_active(True)
        self._set_local(self.local)

    @staticmethod
    def _switch_row(title, sub, sw):
        v = vbox(label(title), label(sub, "k-muted", "k-s12", wrap=True, max_chars=60), spacing=2)
        row = Gtk.Box(spacing=12)
        row.pack_start(v, True, True, 0)
        row.pack_start(sw, False, False, 0)
        return row

    def mode(self) -> str:
        return next(k for k, b in self.mode_buttons.items() if b.get_active())

    def _set_local(self, path):
        self.local = path
        if path and not self.remote_touched:
            self.remote = rjoin("/my-files", os.path.basename(path.rstrip("/")))
        self._validate()

    def set_local(self, path):          # used by drag & drop and tests
        self._set_local(path)

    def _pick_local(self):
        p = choose_local_folder(self.dialog, start=self.local or os.path.expanduser("~"))
        if p:
            self._set_local(p)

    def _pick_remote(self):
        p = RemotePicker(self.dialog, self.app.cli, self.remote or "/my-files").run()
        if p:
            self.remote = p
            self.remote_touched = True
            self._validate()

    def _validate(self) -> bool:
        from .common import set_button_text
        set_button_text(self.local_btn, short_path(self.local) if self.local else _("Choose a folder…"),
                        _("Folder on this computer"))
        set_button_text(self.remote_btn, (_("Proton Drive") + self.remote.replace("/my-files", "", 1))
                        if self.remote else "…", _("Folder in Proton Drive"))
        lerr = validate_local(self.app.settings, self.local, self.folder.id if self.folder else "") \
            if self.local else ""
        rem = self.remote.strip()
        rerr = ""
        if rem and not any(rem == r or rem.startswith(r + "/") for r in REMOTE_ROOTS):
            rerr = _("The Proton Drive folder must be inside My files, Computers or Shared with me")
        elif rem in REMOTE_ROOTS and self.mode() != "mirror":
            rerr = _("Pick a folder inside My files rather than the top level")
        viewer = rem.startswith("/shared-with-me/") and self._share_role(rem) == "viewer"
        self.mode_buttons["two-way"].set_sensitive(not viewer)
        self.mode_buttons["backup"].set_sensitive(not viewer)
        if viewer and self.mode() != "mirror":
            self.mode_buttons["mirror"].set_active(True)
        self.share_note.set_text(_("You can only view this shared item, so it syncs down only.") if viewer else "")
        self.local_err.set_text(lerr or "")
        self.remote_err.set_text(rerr)
        ok = bool(self.local) and not lerr and bool(rem) and not rerr
        self.start.set_sensitive(ok)
        return ok

    def _share_role(self, rem):
        top = rem[len("/shared-with-me/"):].split("/")[0]
        for n in getattr(self.app, "shared_cache", []) or []:
            if top in (n.uid, n.name):
                return n.role or "viewer"
        return "viewer"

    def run(self) -> tuple[FolderPair, bool] | None:
        self.dialog.show_all()
        self.local_btn.grab_focus()
        while True:
            r = self.dialog.run()
            if r != Gtk.ResponseType.OK:
                self.dialog.destroy()
                return None
            if self._validate():
                break
        buf = self.ignore.get_buffer()
        ignores = [x.strip() for x in buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).splitlines()
                   if x.strip()]
        f = self.folder or FolderPair(local="", remote="")
        changed_target = self.folder is not None and (
            f.local != os.path.realpath(self.local) or f.remote != rjoin(self.remote) or f.mode != self.mode())
        f.local = os.path.realpath(self.local)
        f.remote = rjoin(self.remote.strip())
        f.mode = self.mode()
        f.watch = self.watch.get_active()
        f.mirror_deletions = self.deletions.get_active()
        f.ignore = ignores
        reset = changed_target or self.reset.get_active()
        self.dialog.destroy()
        return f, reset


# ---------------------------------------------------------------- Settings (§3.8)
class SettingsDialog:
    def __init__(self, parent, app):
        self.app = app
        s = app.settings
        self.dialog = Gtk.Dialog(transient_for=parent, modal=True, use_header_bar=True, title=_("Settings"))
        styled(self.dialog, "kluis", "k-dialog")
        a11y(self.dialog, _("Settings"))
        self.dialog.set_default_size(640, 720)
        area = self.dialog.get_content_area()
        sw = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        body = vbox(spacing=6, margin=22)
        sw.add(body)
        area.pack_start(sw, True, True, 0)
        self.body = body

        def group(title, rows):
            body.pack_start(label(title, "k-h3"), False, False, 6)
            g = vbox(spacing=12)
            styled(g, "k-card")
            for title_, sub, widget in rows:
                r = Gtk.Box(spacing=12)
                v = vbox(label(title_), spacing=2, valign=Gtk.Align.CENTER)
                if sub:
                    v.pack_start(sub if isinstance(sub, Gtk.Widget) else
                                 label(sub, "k-muted", "k-s12", wrap=True, max_chars=50), False, False, 0)
                r.pack_start(v, True, True, 0)
                if widget is not None:
                    widget.set_valign(Gtk.Align.CENTER)
                    r.pack_start(widget, False, False, 0)
                g.pack_start(r, False, False, 0)
            body.pack_start(g, False, False, 0)

        # 1. Your Proton Drive folder
        self.root_lbl = label("", "k-mono", ellipsize=True, max_chars=34)
        self.root_ok = label("", "k-ok")
        self.root_change = button(_("Change…"), self._change_root, name=_("Change Proton Drive folder"))
        group(_("Your Proton Drive folder"), [(_("Location"), hbox(self.root_lbl, self.root_ok), self.root_change)])
        self._refresh_root()

        # 2. General
        self.autostart = switch(s.autostart, lambda v: app.set_setting("autostart", v), _("Start at login"))
        self.hidden = switch(s.start_minimized, lambda v: app.set_setting("start_minimized", v), _("Start hidden"))
        self.interval = combo([(str(i), _("Every {n} min").format(n=i)) for i in INTERVALS], str(s.interval_minutes),
                              lambda v: app.set_setting("interval_minutes", int(v)), _("Check Proton Drive"))
        self.theme = combo([("system", _("System")), ("light", _("Light")), ("dark", _("Dark"))], s.theme,
                           lambda v: app.set_setting("theme", v), _("Theme"))
        self.notify = combo([("all", _("All")), ("problems", _("Problems only")), ("off", _("Off"))], s.notifications,
                            lambda v: app.set_setting("notifications", v), _("Notifications"))
        self.beta = switch(s.beta, lambda v: app.set_setting("beta", v), _("Beta access"))
        self.updates = switch(s.app_updates, lambda v: app.set_setting("app_updates", v),
                              _("Tell me about Kluis updates"))
        self.home = self._home_combo()
        rows = [
            (_("Start at login"), None, self.autostart),
            (_("Start hidden"), _("Only the panel icon shows at login."), self.hidden),
            (_("Check Proton Drive"), _("Local changes are watched instantly."), self.interval),
            (_("Theme"), None, self.theme),
            (_("Notifications"), None, self.notify),
        ]
        if len(complete_languages()) > 1:
            rows.append((_("Language"), None, combo([(c, c) for c in complete_languages()], s.language or "en",
                                                    lambda v: app.set_setting("language", v), _("Language"))))
        rows += [
            (_("Tell me about Kluis updates"), _("Only a notice with a link. Nothing installs by itself."), self.updates),
            (_("Beta access"), _("Also tell me about Kluis pre-release updates."), self.beta),
            (_("Home location"), _("Shown on the map when no VPN is connected."), self.home),
        ]
        group(_("General"), rows)

        # 3. Proton Drive CLI
        self.cli_ver = label("…", "k-num")
        self.cli_checked = label("", "k-muted", "k-s12")
        self.cli_btn = button(_("Check now"), self._check_cli, name=_("Check now"))
        self.cli_loc = label(short_path(app.cli.path or _("not found")), "k-mono", ellipsize=True, max_chars=30)
        cli_note = _("You chose your own copy, so Kluis doesn't update it.") if s.cli_custom else \
            _("Always uses the latest official version")
        group(_("Proton Drive CLI"), [
            (_("Version"), vbox(label(cli_note, "k-muted", "k-s12"), self.cli_checked, spacing=2),
             hbox(self.cli_ver, self.cli_btn, spacing=12)),
            (_("Location"), None, hbox(self.cli_loc, button(_("Use another copy"), self._other_cli), spacing=8)),
            (_("Skip image previews when uploading"), _("Faster uploads; Proton Drive shows no thumbnails."),
             switch(s.skip_thumbnails, lambda v: app.set_setting("skip_thumbnails", v),
                    _("Skip image previews when uploading"))),
        ])
        self._refresh_cli_checked()
        run_bg(app.cli.version, lambda v: self.cli_ver.set_text(v), lambda e: self.cli_ver.set_text("?"))

        # 4. Account
        email = app.manager.email or _("Signed in")
        group(_("Account"), [(email if app.manager.logged_in else _("Not signed in"),
                              _("Session kept in your keyring"),
                              button(_("Sign out…"), self._sign_out, "k-danger"))])

        # Troubleshooting
        group(_("Troubleshooting"), [
            (_("Logs"), _("Kluis and the Proton Drive CLI write logs here."),
             button(_("Open log folder"), app.open_logs)),
            (_("Copy diagnostics"), _("Versions and recent log lines, without your email, tokens or private paths."),
             button(_("Copy diagnostics"), self._diagnostics)),
        ])

        body.pack_start(label(_("Shortcuts: Ctrl+1…6 tabs · Ctrl+R sync · Ctrl+N add folder · Ctrl+F search · "
                                "Ctrl+, settings · Ctrl+Q quit"), "k-muted", "k-s12", wrap=True), False, False, 12)
        body.pack_start(label(_("Kluis {v} · not affiliated with Proton AG").format(v=VERSION), "k-muted", "k-s12"),
                        False, False, 0)
        self.dialog.connect("key-press-event", self._key)

    def _key(self, _w, ev):
        if ev.keyval == Gdk.KEY_Escape:
            self.dialog.response(Gtk.ResponseType.CLOSE)
            return True
        return False

    def _home_combo(self):
        from ..geo import system_timezone, zone_cities
        cities = zone_cities()
        tz = system_timezone()
        auto = _("From time zone ({c})").format(c=cities.get(tz, ("?",))[0])
        opts = [("", auto)] + sorted(((k, f"{v[0]} · {k.split('/')[0]}") for k, v in cities.items()),
                                     key=lambda kv: kv[1])
        return combo(opts, self.app.settings.home_city, lambda v: self.app.set_setting("home_city", v or ""),
                     _("Home location"))

    def _refresh_root(self):
        r = self.app.settings.root_dir
        self.root_lbl.set_text(short_path(r))
        ok = os.path.isdir(r) and os.access(r, os.W_OK)
        self.root_ok.set_text("✓" if ok else "⚠")
        self.root_ok.get_style_context().remove_class("k-ok" if not ok else "k-warn")
        self.root_ok.get_style_context().add_class("k-ok" if ok else "k-warn")
        self.root_ok.set_tooltip_text(_("Exists and Kluis can write to it") if ok else
                                      _("Missing or not writable; Kluis creates it when needed"))

    def _change_root(self):
        p = choose_local_folder(self.dialog, _("Choose your Proton Drive folder"),
                                os.path.dirname(self.app.settings.root_dir))
        if p:
            self.app.move_root(p, self.dialog, done=self._refresh_root)

    def _refresh_cli_checked(self):
        t = self.app.settings.cli_last_check
        self.cli_checked.set_text(_("Last checked {t}").format(t=time.strftime("%H:%M", time.localtime(t))) if t else "")

    def _check_cli(self):
        from .common import set_button_text
        set_button_text(self.cli_btn, _("Checking…"), _("Check now"))
        self.cli_btn.set_sensitive(False)

        def done(res):
            self.cli_btn.set_sensitive(True)
            set_button_text(self.cli_btn, _("✓ Up to date") if res.status in ("up-to-date", "updated") else
                            _("Check now"), _("Check now"))
            self._refresh_cli_checked()
            run_bg(self.app.cli.version, lambda v: self.cli_ver.set_text(v))
        self.app.check_cli(force=True, done=done)

    def _other_cli(self):
        p = choose_file(self.dialog, _("Choose the proton-drive program"), os.path.expanduser("~"))
        if p:
            self.app.set_cli_path(p, custom=True)
            self.cli_loc.set_text(short_path(p))
            run_bg(self.app.cli.version, lambda v: self.cli_ver.set_text(v))

    def _sign_out(self):
        if confirm(self.dialog, _("Sign out?"), _("Syncing stops until you sign in again. Your files stay on this "
                                                  "computer and in Proton Drive."), _("Sign out"), _("Stay signed in"),
                   destructive=True):
            self.dialog.response(Gtk.ResponseType.CLOSE)
            GLib.idle_add(lambda: (self.app.sign_out(), False)[1])

    def _diagnostics(self):
        self.app.copy_diagnostics()

    def run(self):
        self.dialog.show_all()
        self.dialog.run()
        self.dialog.destroy()

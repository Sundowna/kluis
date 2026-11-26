"""Folders (HANDOVER §3.2): status card, one card per synced folder, drop zone, mode legend."""
from __future__ import annotations

import os
import threading

from gi.repository import GLib, Gtk

from ..config import MODES, PART_DIR
from ..i18n import _
from .common import (WEB_URL, a11y, ago, button, clear, combo, hbox, human_size, label, open_path, open_uri,
                     popover_menu, set_class, short_path, styled, switch, vbox)

SIZES: dict[str, int | None] = {}        # local path -> bytes (computed in the background)
_measuring: set = set()


def measure(path: str, done):
    """du of a local folder in a thread; never blocks the UI."""
    if path in _measuring:
        return
    _measuring.add(path)

    def work():
        total = 0
        for dp, dns, fns in os.walk(path):
            dns[:] = [d for d in dns if d != PART_DIR]
            for fn in fns:
                try:
                    total += os.lstat(os.path.join(dp, fn)).st_size
                except OSError:
                    pass
        SIZES[path] = total
        _measuring.discard(path)
        GLib.idle_add(lambda: (done(), False)[1])
    threading.Thread(target=work, daemon=True).start()


class StatusCard(Gtk.Box):
    def __init__(self, app, with_add=True):
        super().__init__(spacing=16)
        styled(self, "k-card")
        self.icon = label("✓", "k-iconbox", xalign=0.5)
        self.icon.set_valign(Gtk.Align.CENTER)
        self.pack_start(self.icon, False, False, 0)
        self.title = label("", "k-h1", ellipsize="end")
        self.sub = label("", "k-muted", ellipsize="end")
        a11y(self.title, _("Folders status"))
        self.pack_start(vbox(self.title, self.sub, spacing=4, valign=Gtk.Align.CENTER), True, True, 0)
        if with_add:
            add = button(_("+ Add folder"), app.add_folder_dialog, "suggested-action", tooltip=_("Add folder (Ctrl+N)"))
            add.set_valign(Gtk.Align.CENTER)
            self.pack_end(add, False, False, 0)

    def refresh(self, st):
        icons = {"paused": "⏸", "syncing": "↻", "problems": "!", "empty": "☁", "ok": "✓"}
        self.icon.set_text(icons.get(st.kind, "✓"))
        for c in ("k-ok", "k-warn", "k-error"):
            self.icon.get_style_context().remove_class(c)
            self.sub.get_style_context().remove_class(c)
        self.icon.get_style_context().add_class({"warn": "k-warn", "error": "k-error"}.get(st.tone, "k-ok"))
        if st.tone in ("warn", "error"):
            self.sub.get_style_context().add_class("k-warn" if st.tone == "warn" else "k-error")
        self.title.set_text(st.title)
        self.sub.set_text(st.subtitle)
        self.sub.set_tooltip_text(st.subtitle)


class FolderCard(Gtk.Box):
    def __init__(self, app, folder):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        styled(self, "k-card")
        self.app = app
        self.fid = folder.id
        self.dead = False
        self.connect("destroy", lambda *_a: setattr(self, "dead", True))   # late callbacks (size) are ignored
        a11y(self, folder.name)
        top = Gtk.Box(spacing=12)
        self.switch = switch(folder.enabled, self._toggled, _("Sync {n}").format(n=folder.name))
        top.pack_start(self.switch, False, False, 0)
        self.name = label(folder.name, "k-h3", ellipsize="end")
        self.size = label(_("Measuring…"), "k-sizechip")
        a11y(self.size, _("Size of {n}").format(n=folder.name))
        top.pack_start(self.name, False, False, 0)
        top.pack_start(self.size, False, False, 0)
        more = Gtk.MenuButton(image=Gtk.Image.new_from_icon_name("kluis-more-symbolic", Gtk.IconSize.BUTTON),
                              tooltip_text=_("More"))
        styled(more, "k-flat")
        a11y(more, _("More for {n}").format(n=folder.name))
        more.set_popover(popover_menu(more, [
            (_("Edit…"), lambda: app.edit_folder(self.fid)),
            (_("Show in Kluis browser"), lambda: app.window.show_remote(app.settings.folder(self.fid).remote)),
            (_("Open Proton Drive on the web"), lambda: open_uri(WEB_URL)),
            (_("Check every file again"), lambda: app.recheck_folder(self.fid)),
            None,
            (_("Stop syncing this folder…"), lambda: app.remove_folder(self.fid), True),
        ]))
        self.more = more
        top.pack_end(more, False, False, 0)
        self.pack_start(top, False, False, 0)
        self.route = label("", "k-muted", "k-s13", ellipsize=True)
        self.pack_start(self.route, False, False, 0)
        self.status = label("", "k-s13", ellipsize="end")
        a11y(self.status, _("Status of {n}").format(n=folder.name))
        self.bar = Gtk.ProgressBar(no_show_all=True)
        self.pack_start(self.status, False, False, 0)
        self.pack_start(self.bar, False, False, 0)
        actions = Gtk.Box(spacing=8)
        actions.pack_start(label(_("Mode"), "k-muted", "k-s13"), False, False, 0)
        self.mode = combo([(k, f"{g} {t}") for k, (g, t, _d) in MODES.items()], folder.mode, self._mode_changed,
                          _("Mode of {n}").format(n=folder.name))
        actions.pack_start(self.mode, False, False, 0)
        self.sync_btn = button(_("↻ Sync"), lambda: app.manager.request(self.fid), tooltip=_("Sync this folder now"),
                               name=_("Sync {n} now").format(n=folder.name))
        self.open_btn = button(_("Open"), lambda: open_path(app.settings.folder(self.fid).local),
                               name=_("Open {n}").format(n=folder.name))
        self.remove_btn = button(_("Remove"), lambda: app.remove_folder(self.fid), "k-danger",
                                 tooltip=_("Stop syncing {n}").format(n=folder.name),
                                 name=_("Remove {n}").format(n=folder.name))
        self.review_btn = button(_("Review…"), lambda: app.ask_guard(self.fid),
                                 name=_("Review {n}").format(n=folder.name))
        self.review_btn.set_no_show_all(True)
        for b in (self.sync_btn, self.open_btn, self.review_btn):
            actions.pack_start(b, False, False, 0)
        actions.pack_end(self.remove_btn, False, False, 0)
        self.pack_start(actions, False, False, 0)
        self.refresh()

    def _toggled(self, on):
        f = self.app.settings.folder(self.fid)
        if f and f.enabled != on:
            f.enabled = on
            if on and f.hold == "guard":
                f.hold = ""
            self.app.settings.save()
            self.app.manager.folder_changed(f)
            self.refresh()

    def _mode_changed(self, mode):
        f = self.app.settings.folder(self.fid)
        if f and mode and f.mode != mode:
            if not self.app.change_mode(self.fid, mode):
                GLib.idle_add(lambda: (self.mode.set_active_id(self.app.settings.folder(self.fid).mode), False)[1])

    def refresh(self):
        f = self.app.settings.folder(self.fid)
        if not f or self.dead:
            return
        st = self.app.manager.status.get(self.fid)
        set_class(self, "k-off", not f.enabled)
        if self.switch.get_active() != f.enabled:
            self.switch.set_active(f.enabled)
        if self.mode.get_active_id() != f.mode:
            self.mode.set_active_id(f.mode)
        size = SIZES.get(f.local)
        if size is None:
            self.size.set_text(_("Measuring…"))
            if os.path.isdir(f.local):
                measure(f.local, self.refresh)
        else:
            self.size.set_text(human_size(size))
        remote = f.remote.replace("/my-files", "", 1) if f.remote.startswith("/my-files") else f.remote
        self.route.set_text(f"{short_path(f.local)} ⇢ Proton Drive{remote}")
        state = st.state if st else "idle"
        ctx = self.status.get_style_context()
        for c in ("k-warn", "k-error"):
            ctx.remove_class(c)
        if not f.enabled:
            text = _("Off · not syncing")
        elif state == "syncing":
            text = st.text or _("Syncing…")
        elif state == "queued":
            text = _("Waiting for its turn…")
        elif state in ("guard", "missing", "hold"):
            text = st.text
            ctx.add_class("k-error" if state != "guard" else "k-warn")
        elif state in ("ok", "conflict", "error"):
            text = self._result_text(f, st)
            if state == "conflict":
                ctx.add_class("k-warn")
            elif state == "error":
                ctx.add_class("k-error")
        elif not f.last_sync:
            text = _("First sync started…") if self.app.manager.busy else (st.text if st else "")
        else:
            text = st.text if st else ""
        if not f.watch and f.enabled and state not in ("syncing", "queued", "error", "missing", "guard"):
            text += " · " + _("changes wait for the next check")
        self.status.set_text(text)
        self.status.set_tooltip_text(text)
        if state == "syncing" and st.total:
            self.bar.set_fraction(st.done / max(st.total, 1))
            self.bar.show()
        else:
            self.bar.hide()
        busy = state in ("syncing", "queued")
        self.sync_btn.set_sensitive(f.enabled and not busy and not self.app.settings.paused)
        self.review_btn.set_visible(state == "guard")

    @staticmethod
    def _result_text(f, st):
        if st.state == "conflict":
            return _("{msg} · {t}").format(msg=st.text, t=ago(f.last_sync))
        if st.state == "error":
            return st.text
        when = ago(f.last_sync)
        if f.mode == "backup":
            return _("Backed up {t} · {n} files").format(t=when, n=f.last_files)
        if when == "just now":
            return _("Synced just now")
        return _("Synced {t} · {n} files").format(t=when, n=f.last_files)


class FoldersPage(Gtk.ScrolledWindow):
    def __init__(self, app):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.app = app
        body = vbox(spacing=12)
        self.add(body)
        self.status = StatusCard(app)
        body.pack_start(self.status, False, False, 0)
        self.list = vbox(spacing=10)
        body.pack_start(self.list, False, False, 0)
        self.empty = vbox(label("☁", "k-h0", xalign=0.5), label(_("Ready when you are"), "k-h2", xalign=0.5),
                          label(_("Add a folder to start syncing with Proton Drive."), "k-muted", xalign=0.5),
                          hbox(button(_("+ Add folder"), app.add_folder_dialog, "suggested-action"),
                               halign=Gtk.Align.CENTER), spacing=8)
        styled(self.empty, "k-card")
        body.pack_start(self.empty, False, False, 0)
        self.drop = vbox(label(_("Drag a folder onto this window to start syncing it"), "k-muted", xalign=0.5))
        styled(self.drop, "k-card", "k-drop")
        a11y(self.drop, _("Drop zone"))
        body.pack_start(self.drop, False, False, 0)
        legend = vbox(*[label(t, "k-muted", "k-s12") for t in (
            _("⇄ Two-way: edits, new files and deletions travel both ways"),
            _("↑ Back up: uploads only, never deletes in Proton Drive"),
            _("↓ Mirror down: local copy, never changes Proton Drive"))], spacing=2)
        body.pack_start(legend, False, False, 0)
        self.cards: dict[str, FolderCard] = {}

    def rebuild(self):
        clear(self.list)
        self.cards.clear()
        for f in self.app.settings.folders:
            c = FolderCard(self.app, f)
            self.cards[f.id] = c
            self.list.pack_start(c, False, False, 0)
        self.list.show_all()
        for c in self.cards.values():
            c.refresh()
        n = len(self.cards)
        self.empty.set_visible(n == 0)

    def refresh_folder(self, fid):
        c = self.cards.get(fid)
        if c:
            c.refresh()

    def refresh_all(self):
        for c in self.cards.values():
            c.refresh()

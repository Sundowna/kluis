"""First-run flow: 1 get the official CLI, 2 sign in, 3 pick folders. Each step is one click."""
from __future__ import annotations

import os

from gi.repository import GLib, Gtk

from ..cli import download_cli, rjoin
from ..config import FolderPair
from .common import label, open_uri, run_bg, short_path, styled, text_button, user_dir
from ..cli import DOWNLOAD_PAGE_URL


class Step(Gtk.Box):
    def __init__(self, num, title, sub):
        super().__init__(spacing=14)
        styled(self, "k-step")
        self.num = label(str(num), "k-step-num", xalign=0.5)
        self.num.set_valign(Gtk.Align.START)
        self.pack_start(self.num, False, False, 0)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        v.pack_start(label(title, "k-step-title"), False, False, 0)
        self.sub = label(sub, "k-dim", wrap=True)
        self.sub.set_max_width_chars(60)
        v.pack_start(self.sub, False, False, 0)
        self.actions = Gtk.Box(spacing=8, margin_top=4)
        v.pack_start(self.actions, False, False, 0)
        self.pack_start(v, True, True, 0)
        self._n = num

    def set_state(self, state):  # pending | active | done
        ctx = self.get_style_context()
        for c in ("k-active", "k-done"):
            ctx.remove_class(c)
        if state == "active":
            ctx.add_class("k-active")
        if state == "done":
            ctx.add_class("k-done")
            self.num.set_text("✓")
        else:
            self.num.set_text(str(self._n))
        self.actions.set_visible(state != "pending")
        self.set_sensitive(state != "pending")

    def set_actions(self, *widgets):
        for c in self.actions.get_children():
            c.destroy()
        for w in widgets:
            self.actions.pack_start(w, False, False, 0)
        self.actions.show_all()


class Onboarding(Gtk.ScrolledWindow):
    def __init__(self, app, on_finished):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.app = app
        self.on_finished = on_finished
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, halign=Gtk.Align.CENTER)
        styled(outer, "k-welcome")
        outer.set_size_request(560, -1)
        head = Gtk.Box(spacing=14)
        head.pack_start(Gtk.Image.new_from_icon_name("dev.kluis.Kluis", Gtk.IconSize.DIALOG), False, False, 0)
        hv = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        hv.pack_start(label("Welcome to Kluis", "k-logo-title"), False, False, 0)
        hv.pack_start(label("Your Proton Drive folders, synced on Linux Mint. End-to-end encrypted, "
                            "powered by Proton's official CLI.", "k-dim", wrap=True), False, False, 0)
        head.pack_start(hv, True, True, 0)
        outer.pack_start(head, False, False, 6)

        self.s1 = Step(1, "Get the official Proton Drive CLI",
                       "Kluis talks to Proton Drive through Proton's own command-line tool. "
                       "It is downloaded from proton.me and checked against Proton's SHA-512 checksum.")
        self.s2 = Step(2, "Sign in", "Your browser opens Proton's sign-in page. Your password never "
                                     "passes through Kluis; the session is kept in your keyring.")
        self.s3 = Step(3, "Choose what to sync", "Pick folders now or later. Each one syncs both ways "
                                                  "with a folder of the same name in Proton Drive.")
        for s in (self.s1, self.s2, self.s3):
            outer.pack_start(s, False, False, 0)
        self.add(outer)
        self.suggestions = {}

    # ---------- state ----------
    def refresh(self, account_state: str):
        """account_state: checking | no-cli | signed-out | ok | offline"""
        if account_state == "checking":
            for s in (self.s1, self.s2, self.s3):
                s.set_state("pending")
            self.s1.set_actions(Gtk.Spinner(active=True), label("Looking for the Proton Drive CLI…", "k-dim"))
            self.s1.actions.set_visible(True)
            self.show_all()
            return
        if account_state == "no-cli":
            self._step1()
            self.s2.set_state("pending")
            self.s3.set_state("pending")
        elif account_state == "signed-out":
            self._cli_done()
            self._step2()
            self.s3.set_state("pending")
        else:
            self._cli_done()
            self.s2.set_state("done")
            self.s2.set_actions()
            self.s2.sub.set_text("You are signed in.")
            self._step3()
        self.show_all()
        for s in (self.s1, self.s2, self.s3):
            s.actions.set_visible(s.get_sensitive())

    def _cli_done(self):
        self.s1.set_state("done")
        self.s1.sub.set_text(f"Found at {short_path(self.app.cli.path or '')}")
        self.s1.set_actions()

    def _step1(self):
        self.s1.set_state("active")
        self.bar = Gtk.ProgressBar(valign=Gtk.Align.CENTER, width_request=160)
        self.bar.set_no_show_all(True)
        dl = text_button("Download from proton.me", self._download, "k-accent", "k-pill",
                         icon="folder-download-symbolic")
        have = text_button("I already have it…", self._locate, "k-pill")
        page = text_button("Download page", lambda: open_uri(DOWNLOAD_PAGE_URL), "flat")
        self.s1.set_actions(dl, have, page, self.bar)

    def _download(self):
        self.s1.actions.set_sensitive(False)
        self.bar.show()

        def progress(frac):
            GLib.idle_add(self.bar.set_fraction, frac)

        def done(path):
            self.app.set_cli_path(path)
            self.app.recheck()

        def fail(e):
            self.s1.actions.set_sensitive(True)
            self.bar.hide()
            self.s1.sub.set_markup(f"<span foreground='#e5484d'>Download failed: {GLib.markup_escape_text(str(e))}"
                                   "</span>\nYou can download it from the download page, then choose "
                                   "“I already have it…”.")
        run_bg(lambda: download_cli(progress), done, fail)

    def _locate(self):
        fc = Gtk.FileChooserNative.new("Choose the proton-drive program", self.get_toplevel(),
                                       Gtk.FileChooserAction.OPEN, "Select", "Cancel")
        fc.set_current_folder(os.path.expanduser("~/Downloads"))
        if fc.run() == Gtk.ResponseType.ACCEPT:
            path = fc.get_filename()
            try:
                os.chmod(path, os.stat(path).st_mode | 0o111)  # same as `chmod +x proton-drive`
            except OSError:
                pass
            self.app.set_cli_path(path)
            self.app.recheck()
        fc.destroy()

    def _step2(self):
        self.s2.set_state("active")
        self.s2.sub.set_text("Your browser opens Proton's sign-in page. Your password never passes through "
                             "Kluis; the session is kept in your keyring.")
        go = text_button("Sign in with your browser", self._sign_in, "k-accent", "k-pill",
                         icon="dialog-password-symbolic")
        self.s2.set_actions(go)

    def _sign_in(self):
        spin = Gtk.Spinner(active=True)
        wait = label("Waiting for you to finish in the browser…", "k-dim")
        self.s2.set_actions(spin, wait)

        def on_url(url):
            def show():
                again = Gtk.LinkButton(uri=url, label="Open the sign-in page again")
                self.s2.set_actions(spin, wait, again)
                return False
            GLib.idle_add(show)

        def fail(e):
            self._step2()
            self.s2.sub.set_markup(f"<span foreground='#e5484d'>{GLib.markup_escape_text(str(e))}</span>")
        run_bg(lambda: self.app.cli.login(on_url), lambda _r: self.app.recheck(), fail)

    def _step3(self):
        self.s3.set_state("active")
        chips = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4, column_spacing=6,
                            row_spacing=6)
        self.suggestions = {}
        for kind in (GLib.UserDirectory.DIRECTORY_DOCUMENTS, GLib.UserDirectory.DIRECTORY_PICTURES,
                     GLib.UserDirectory.DIRECTORY_DESKTOP, GLib.UserDirectory.DIRECTORY_MUSIC):
            p = user_dir(kind)
            if not p or self.app.settings.overlaps(p):
                continue
            t = Gtk.ToggleButton(label=f"  {os.path.basename(p)}")
            styled(t, "k-suggest")
            t.set_active(kind == GLib.UserDirectory.DIRECTORY_DOCUMENTS)
            self.suggestions[p] = t
            chips.add(t)
        other = text_button("Another folder…", self._other, "k-suggest", icon="list-add-symbolic")
        chips.add(other)
        start = text_button("Start syncing", self._finish, "k-accent", "k-pill")
        later = text_button("Skip for now", lambda: self._finish(skip=True), "flat")
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        v.pack_start(chips, False, False, 0)
        hb = Gtk.Box(spacing=8)
        hb.pack_start(start, False, False, 0)
        hb.pack_start(later, False, False, 0)
        v.pack_start(hb, False, False, 0)
        self.s3.set_actions(v)

    def _other(self):
        from .dialogs import FolderDialog
        r = FolderDialog(self.get_toplevel(), self.app).run()
        if r:
            self.app.add_folder(r[0])
            self._finish(skip=True)

    def _finish(self, skip=False):
        if not skip:
            for path, t in self.suggestions.items():
                if t.get_active() and not self.app.settings.overlaps(path):
                    self.app.add_folder(FolderPair(local=path, remote=rjoin("/my-files", os.path.basename(path))))
        self.app.settings.onboarded = True
        self.app.settings.save()
        self.on_finished()

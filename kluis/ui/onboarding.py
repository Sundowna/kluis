"""First run (HANDOVER §3.0): Step 1 get the CLI, 2 sign in, 3 pick folders. Back/Next on every step;
the current step is saved, so closing mid-setup resumes there."""
from __future__ import annotations

import os
import time

from gi.repository import GLib, Gtk

from ..cli import DOWNLOAD_PAGE_URL, ChecksumMismatch, download_cli, find_cli, rjoin
from ..config import FolderPair
from ..i18n import _
from .common import a11y, button, clear, hbox, label, open_uri, run_bg, set_button_text, short_path, styled, \
    user_dir, vbox

SIGNIN_TIMEOUT = float(os.environ.get("KLUIS_SIGNIN_TIMEOUT", "300"))   # 5 min; tests shorten it (mock clock)
STEPS = (_("Get the CLI"), _("Sign in"), _("Pick folders"))


def is_kde() -> bool:
    return "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()


class Onboarding(Gtk.Box):
    def __init__(self, app, on_finished):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.app = app
        self.on_finished = on_finished
        self.cli_state = "idle"         # idle | busy | done | error
        self.sign_state = "idle"        # idle | busy | done | timeout | error
        self.expect_email = ""          # switching to this account (decisions D30)
        self.picks: dict[str, bool] = {}
        self._signin_src = 0
        card = vbox(spacing=22)
        styled(card, "k-panel")
        card.set_size_request(640, -1)
        card.set_margin_top(24)
        card.set_margin_bottom(24)
        from .window import logo_image
        head = hbox(logo_image(48),
                    vbox(label(_("Welcome to Kluis"), "k-h0"),
                         label(_("Proton Drive on Linux, through Proton’s official CLI"), "k-muted"), spacing=2),
                    spacing=14)
        card.pack_start(head, False, False, 0)
        self.bars = Gtk.Box(spacing=8, homogeneous=True)
        a11y(self.bars, _("Progress"))
        card.pack_start(self.bars, False, False, 0)
        self.step_lbl = label("", "k-muted", "k-s13", "k-bold")
        card.pack_start(self.step_lbl, False, False, 0)
        self.body = vbox(spacing=12)
        card.pack_start(self.body, False, False, 0)
        nav = Gtk.Box(spacing=12)
        nav.set_margin_top(8)
        self.back = button(_("Back"), self._back, "k-big")
        self.next = button(_("Next"), self._next, "suggested-action", "k-big")
        self.next.set_size_request(160, -1)
        nav.pack_start(self.back, False, False, 0)
        nav.pack_end(self.next, False, False, 0)
        card.pack_start(Gtk.Separator(), False, False, 0)
        card.pack_start(nav, False, False, 0)
        self.pack_start(card, False, False, 0)
        self.step = 1

    # ---------- state ----------
    def refresh(self, account_state: str):
        """account_state: checking | no-cli | signed-out | ok | offline. Resumes at the saved step."""
        saved = max(1, min(3, self.app.settings.onboarding_step or 1))
        if account_state == "checking":
            self.cli_state = "busy"
            self.show_step(1, persist=False)   # only a placeholder: never overwrite the step to resume at
            return
        if account_state == "no-cli":
            if self.cli_state != "error":
                self.cli_state = "idle"
            self.show_step(1)
            return
        self.cli_state = "done"
        if account_state == "signed-out":
            if self.sign_state not in ("busy", "timeout", "error"):
                self.sign_state = "idle"
            self.show_step(min(saved, 2))
        else:
            self.sign_state = "done"
            self.show_step(saved)

    def show_step(self, n: int, persist=True):
        self.step = n
        if persist:
            self.app.settings.onboarding_step = n
            self.app.settings.save()
        clear(self.bars)
        for i, name in enumerate(STEPS, 1):
            bar = Gtk.Box()
            styled(bar, "k-step-bar", "k-on" if i <= n else "")
            lb = label(name, "k-s12", "k-bold", "k-ok" if i <= n else "k-muted")
            self.bars.pack_start(vbox(bar, lb, spacing=6), True, True, 0)
        self.bars.show_all()
        self.step_lbl.set_text(_("Step {n} of 3").format(n=n))
        clear(self.body)
        getattr(self, f"_step{n}")()
        self.body.show_all()
        self.back.set_sensitive(n > 1)
        set_button_text(self.next, _("Start syncing") if n == 3 else _("Next"))
        self._update_next()

    def _update_next(self):
        ok = {1: self.cli_state == "done", 2: self.sign_state == "done", 3: True}[self.step]
        self.next.set_sensitive(ok)

    def _back(self):
        if self.step > 1:
            self.show_step(self.step - 1)

    def _next(self):
        if self.step < 3:
            self.show_step(self.step + 1)
        else:
            self._finish()

    # ---------- step 1 ----------
    def _step1(self):
        self.body.pack_start(label(_("Get the official Proton Drive CLI"), "k-h1"), False, False, 0)
        self.body.pack_start(label(_("One click downloads it from proton.me and checks Proton’s SHA-512 checksum. "
                                     "Kluis never touches your files any other way."), "k-muted", wrap=True,
                                   max_chars=70), False, False, 0)
        self.dl_btn = button(_("Download from proton.me"), self._download, "suggested-action", "k-big")
        self.dl_btn.set_size_request(240, -1)
        self.cli_note = label("", "k-num", wrap=True, max_chars=50)
        self.body.pack_start(hbox(self.dl_btn, self.cli_note, spacing=12), False, False, 0)
        self.body.pack_start(hbox(button(_("I already have it…"), self._locate, "k-flat"),
                                  button(_("Download page"), lambda: open_uri(DOWNLOAD_PAGE_URL), "k-link"),
                                  spacing=8), False, False, 0)
        self._paint_cli()

    def _paint_cli(self, text=None, tone=None):
        st = self.cli_state
        for c in ("k-ok", "k-error", "k-muted"):
            self.cli_note.get_style_context().remove_class(c)
        if st == "busy" and text is None:
            text = _("Looking for the Proton Drive CLI…")
        if st == "done":
            ver = getattr(self, "_cli_version", "")
            text = text or (_("✓ Downloaded · proton-drive {v} · SHA-512 checksum matches").format(v=ver)
                            if getattr(self, "_downloaded", False) else
                            _("✓ Found at {p}").format(p=short_path(self.app.cli.path or "")))
            tone = "k-ok"
            set_button_text(self.dl_btn, _("✓ Downloaded") if getattr(self, "_downloaded", False)
                            else _("Download from proton.me"), _("Download from proton.me"))
            self.dl_btn.set_sensitive(not getattr(self, "_downloaded", False))
        elif st == "busy":
            self.dl_btn.set_sensitive(False)
        else:
            self.dl_btn.set_sensitive(True)
        self.cli_note.set_text(text or _("about 38 MB"))
        self.cli_note.get_style_context().add_class(tone or "k-muted")
        self._update_next()

    def _download(self):
        self.cli_state = "busy"
        set_button_text(self.dl_btn, _("Downloading…"), _("Download from proton.me"))
        self._paint_cli(_("Starting…"))
        t0 = time.monotonic()

        def progress(done, total):
            def show():
                if self.cli_state == "busy" and hasattr(self, "cli_note"):
                    self.cli_note.set_text(_("{a} of {b} MB").format(a=f"{done / 1e6:.1f}",
                                                                     b=f"{total / 1e6:.1f}" if total else "?"))
                return False
            if time.monotonic() - t0 >= 0 or done == total:
                GLib.idle_add(show)

        def done(path):
            from ..capabilities import self_test  # noqa: F401  (self-test runs at sign-in time)
            self._downloaded = True
            self.app.set_cli_path(path)
            run_bg(lambda: self.app.cli.version(), lambda v: (setattr(self, "_cli_version", v.split("+")[0]
                                                                       .replace("cli-drive@", "")),
                                                               self._done_cli()), lambda e: self._done_cli())

        def fail(e):
            self.cli_state = "error"
            set_button_text(self.dl_btn, _("Download from proton.me"))
            msg = str(e) if isinstance(e, ChecksumMismatch) else \
                _("Download failed: {e}").format(e=e)
            self._paint_cli(msg, "k-error")
        run_bg(lambda: download_cli(progress), done, fail)

    def _done_cli(self):
        self.cli_state = "done"
        if self.step == 1:
            self._paint_cli()

    def _locate(self):
        from .dialogs import choose_file
        path = choose_file(self.get_toplevel(), _("Choose the proton-drive program"), os.path.expanduser("~/Downloads"))
        if not path:
            return
        try:
            os.chmod(path, os.stat(path).st_mode | 0o111)  # same as `chmod +x proton-drive`
        except OSError:
            pass
        self.app.set_cli_path(path, custom=path != find_cli(None))
        self.cli_state = "done"
        self._paint_cli()

    # ---------- step 2 ----------
    def _step2(self):
        from .. import accounts
        back = (self.app.switch_back or "").lower()
        others = [r for r in accounts.records(self.app.settings) if not r.get("signed_out") and
                  (r["email"].lower() != (self.app.settings.account or "").lower() or r["email"].lower() == back)]
        if self.expect_email:
            title = _("Sign in as {e}").format(e=self.expect_email)
        elif self.app.switch_back:
            title = _("Sign in to another Proton account")
        else:
            title = _("Sign in to Proton")
        self.body.pack_start(label(title, "k-h1", wrap=True, max_chars=50), False, False, 0)
        self.body.pack_start(label(_("Your browser opens Proton’s own sign-in page. Kluis never sees your password; "
                                     "the session is kept in your system keyring."), "k-muted", wrap=True,
                                   max_chars=70), False, False, 0)
        self.sign_btn = button(_("Open Proton sign-in"), self._sign_in, "suggested-action", "k-big")
        self.sign_note = label("", wrap=True, max_chars=50)
        self.body.pack_start(hbox(self.sign_btn, self.sign_note, spacing=12), False, False, 0)
        self.again = Gtk.Box()
        self.body.pack_start(self.again, False, False, 0)
        if is_kde():
            self.kde_note = label(_("On KDE Plasma, if sign-in isn’t remembered, install gnome-keyring and log in "
                                    "again."), "k-muted", "k-s13", wrap=True, max_chars=70)
            a11y(self.kde_note, "KDE keyring note")
            self.body.pack_start(self.kde_note, False, False, 0)
        for r in others:                # accounts Kluis keeps: one click back, no sign-in
            if r["email"].lower() == (self.expect_email or "").lower():
                continue
            b = button(_("Use {e} instead").format(e=r["email"]),
                       lambda e=r["email"]: self.app.cancel_switch() if e == self.app.switch_back
                       else (self.cancel_sign_in(), self.app.switch_account(e, force=True)), "k-link")
            b.set_halign(Gtk.Align.START)
            self.body.pack_start(b, False, False, 0)
        self._paint_sign()

    def _paint_sign(self, text=None):
        st = self.sign_state
        ctx = self.sign_note.get_style_context()
        for c in ("k-ok", "k-error", "k-muted"):
            ctx.remove_class(c)
        if st == "done":
            email = self.app.manager.email
            text = _("✓ Signed in as {e}").format(e=email) if email else _("✓ Signed in")
            ctx.add_class("k-ok")
            self.sign_btn.set_sensitive(False)
        elif st == "busy":
            text = _("Waiting for your browser…")
            ctx.add_class("k-muted")
            self.sign_btn.set_sensitive(False)
        elif st == "timeout":
            text = _("Sign-in didn't finish. Try again.")
            ctx.add_class("k-error")
            self.sign_btn.set_sensitive(True)
        else:
            ctx.add_class("k-error" if st == "error" else "k-muted")
            self.sign_btn.set_sensitive(True)
        self.sign_note.set_text(text or "")
        self._update_next()

    def _sign_in(self):
        self.sign_state = "busy"
        self._paint_sign()
        attempt = object()
        self._attempt = attempt

        def on_url(url):
            def show():
                if self.step == 2 and self._attempt is attempt:
                    clear(self.again)
                    self.again.pack_start(button(_("Open the sign-in page again"), lambda: open_uri(url), "k-link"),
                                          False, False, 0)
                    self.again.show_all()
                return False
            GLib.idle_add(show)

        def timeout():
            self._signin_src = 0
            if self._attempt is attempt and self.sign_state == "busy":
                self._attempt = None
                self.app.cli.cancel()
                self.sign_state = "timeout"
                if self.step == 2:
                    self._paint_sign()
            return False
        if self._signin_src:
            GLib.source_remove(self._signin_src)
        self._signin_src = GLib.timeout_add(int(SIGNIN_TIMEOUT * 1000), timeout)

        def done(_r):
            if self._attempt is not attempt:
                return
            if self._signin_src:
                GLib.source_remove(self._signin_src)
                self._signin_src = 0

            def checked(state):
                self.sign_state = "done" if state == "ok" else "error"
                if self.step == 2:
                    self._paint_sign()
                return False
            self.app.manager.check_account(checked)

        def fail(e):
            if self._attempt is not attempt:
                return
            self.sign_state = "error"
            if self.step == 2:
                self._paint_sign(str(e))
        run_bg(lambda: self.app.cli.login(on_url), done, fail)

    def cancel_sign_in(self):
        """Leaving the sign-in page for another account: stop waiting for the browser."""
        if self.sign_state == "busy":
            self._attempt = None
            if self._signin_src:
                GLib.source_remove(self._signin_src)
                self._signin_src = 0
            self.app.cli.cancel()
        self.sign_state = "idle"
        self.expect_email = ""

    # ---------- step 3 ----------
    def _step3(self):
        self.body.pack_start(label(_("Pick folders to sync"), "k-h1"), False, False, 0)
        self.body.pack_start(label(_("Each starts as two-way sync. You can change that per folder later."), "k-muted",
                                   wrap=True), False, False, 0)
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=5, column_spacing=8,
                           row_spacing=8, homogeneous=False)
        kinds = [(GLib.UserDirectory.DIRECTORY_DOCUMENTS, True), (GLib.UserDirectory.DIRECTORY_PICTURES, True),
                 (GLib.UserDirectory.DIRECTORY_DESKTOP, False), (GLib.UserDirectory.DIRECTORY_MUSIC, False)]
        if not self.picks:
            for kind, default in kinds:
                p = user_dir(kind)
                if p and not self.app.settings.overlaps(p):
                    self.picks[p] = default
        for p, on in list(self.picks.items()):
            t = Gtk.ToggleButton(label=("✓ " if on else "") + os.path.basename(p))
            styled(t, "k-chipbtn", "k-big")
            t.set_active(on)
            a11y(t, os.path.basename(p))
            t.connect("toggled", self._flip, p)
            flow.add(t)
        other = button(_("+ Other folder…"), self._other, "k-big")
        flow.add(other)
        self.body.pack_start(flow, False, False, 0)
        self.body.pack_start(button(_("Skip for now"), lambda: self._finish(skip=True), "k-link"), False, False, 0)

    def _flip(self, t, path):
        self.picks[path] = t.get_active()
        t.set_label(("✓ " if t.get_active() else "") + os.path.basename(path))

    def _other(self):
        from .dialogs import choose_local_folder
        p = choose_local_folder(self.get_toplevel(), _("Choose a folder to sync"), os.path.expanduser("~"))
        if p:
            from ..config import validate_local
            err = validate_local(self.app.settings, p)
            if err:
                self.app.toast(err)
                return
            self.picks[os.path.realpath(p)] = True
            self.show_step(3)

    def _finish(self, skip=False):
        if not skip:
            for path, on in self.picks.items():
                if on and not self.app.settings.overlaps(path):
                    self.app.add_folder(FolderPair(local=path, remote=rjoin("/my-files", os.path.basename(path))),
                                        quiet=True)
        self.app.settings.onboarded = True
        self.app.settings.onboarding_step = 1
        self.app.settings.save()
        self.on_finished()

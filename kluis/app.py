"""Application: wires settings, CLI, sync manager, window, panel icon, VPN, updates and notifications."""
from __future__ import annotations

import logging
import logging.handlers
import os
import shutil
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_foreign("cairo")      # map, gallery and graph draw with Cairo: fail clearly if the bridge is missing
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, APP_NAME, VERSION, accounts, geo  # noqa: E402
from .cli import ProtonDriveCli, find_cli  # noqa: E402
from .config import MODES, PHOTOS_ID, FolderPair, Settings  # noqa: E402
from .errors import DISK_FULL, SIGNED_OUT  # noqa: E402
from .i18n import _, ngettext  # noqa: E402
from .manager import SyncManager  # noqa: E402
from .state import StateStore  # noqa: E402
from .paths import AUTOSTART_DIR, LOG_FILE, STATE_DIR, ensure_dirs  # noqa: E402
from .status import Snapshot, compute, estimate_eta  # noqa: E402

DATA = os.path.join(os.path.dirname(__file__), "data")
log = logging.getLogger("kluis")
NOTIFY_GAP = 30          # §3.12: never more than one notification per 30 s (batched)
UNDO_S = 8


def setup_logging():
    ensure_dirs()
    root = logging.getLogger("kluis")
    if any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        return
    h = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.setLevel(logging.INFO)
    root.addHandler(h)
    if os.environ.get("KLUIS_DEBUG"):
        root.setLevel(logging.DEBUG)
        root.addHandler(logging.StreamHandler())


class KluisApp(Gtk.Application):
    def __init__(self, hidden=False):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.start_hidden = hidden
        self.window = None
        self.tray = None
        self.account_state = None
        self.shared_cache = []
        self.vpn_state = None
        self._save_src = 0
        self._notes: list[tuple[str, str]] = []
        self._last_note = 0.0
        self._note_src = 0
        self._removed: dict[str, tuple] = {}
        self.switch_back = ""            # account to go back to when a switch/add ends on the sign-in page
        self._pending_cache = None       # CLI cache folder for an account being added

    # ---------- startup ----------
    def do_startup(self):
        Gtk.Application.do_startup(self)
        setup_logging()
        log.info("Kluis %s starting", VERSION)
        self.settings = Settings.load()
        self.cli = ProtonDriveCli(find_cli(self.settings.cli_path), self.settings.skip_thumbnails)
        rec = accounts.record(self.settings, self.settings.account)
        self.cli.cache_dir = (rec or {}).get("cache", "")
        self.vault = accounts.open_vault()
        self.manager = SyncManager(self.settings, self.cli, StateStore(accounts.state_path(rec)))
        self.manager.listeners.append(self._on_manager)
        icons = Gtk.IconTheme.get_default()
        icons.append_search_path(os.path.join(DATA, "icons"))
        from .ui.theme import Theme
        self.theme = Theme()
        self.theme.listeners.append(lambda _d: self.window and self.window.queue_draw())
        self.theme.apply(self.settings.theme, self.settings.accent)
        self._write_autostart()

        for name, cb, accel in (("sync", lambda *_: self.manager.request(), "<Ctrl>r"),
                                ("add", lambda *_: self.add_folder_dialog(), "<Ctrl>n"),
                                ("settings", lambda *_: self.open_settings(), "<Ctrl>comma"),
                                ("quit", lambda *_: self.quit_app(), "<Ctrl>q"),
                                ("show", lambda *_: self.present_window(), None)):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", cb)
            self.add_action(a)
            if accel:
                self.set_accels_for_action(f"app.{name}", [accel])
        from .vpn import VpnWatcher
        self.vpn = VpnWatcher(self._vpn_changed)
        from .tray import Tray
        self.tray = Tray(self)
        self.hold()  # keep running in the panel when the window is closed
        self._resume_root_move()
        GLib.timeout_add_seconds(3600, self._hourly)
        GLib.timeout_add_seconds(20, lambda: (self._hourly(), False)[1])

    def do_activate(self):
        if self.window is None:
            from .ui.window import MainWindow
            self.window = MainWindow(self)
            self.window.connect("delete-event", self._on_close)
            if self.settings.onboarded:
                self.window.show_main()
            else:
                self.window.show_onboarding("checking")
            if self.start_hidden and self.tray.available and self.settings.onboarded:
                self.window.hide()
            self.recheck()
            GLib.timeout_add_seconds(1, self._refresh_tick)
        else:
            self.present_window()

    def recheck(self):
        self.manager.check_account(self._account_checked)

    def _account_checked(self, state):
        self.account_state = state
        if state == "ok" and self.settings.onboarded:
            if self.window.root.get_visible_child_name() != "main":
                self.window.show_main()
            self.manager.rewatch()
            self.manager.request(reason="start")
            GLib.timeout_add_seconds(30, lambda: (self.auto_selftest(), False)[1])
        elif state == "offline" and self.settings.onboarded:
            self.window.show_main()
            self.manager.set_hold("offline")
        elif not self.settings.onboarded:
            self.window.show_onboarding(state if state != "offline" else "ok")
        elif state in ("no-cli", "signed-out"):
            self.window.show_main()
            if state == "signed-out":
                self.manager.set_hold(SIGNED_OUT)
        self.refresh_all()
        return False

    # ---------- window ----------
    def _on_close(self, win, _ev):
        if self.tray and self.tray.available:
            win.hide()
            if not self.settings.told_background:
                self.settings.told_background = True
                self.settings.save()
                self.notify(_("Kluis keeps syncing in the background"),
                            _("Click the panel icon to open it again, or choose Quit from its menu."), force=True)
            return True
        self.quit_app()
        return True

    def present_window(self):
        if self.window:
            self.window.show()
            self.window.present()

    def toggle_window(self):
        if self.window and self.window.is_visible() and self.window.is_active():
            self.window.hide()
        else:
            self.present_window()

    def quit_app(self):
        self.manager.shutdown()
        self.cli.cancel()                # also a Browse download or preview fetch that is still running
        self.settings.save()
        if self.tray:
            self.tray.close()
        self.release()
        self.quit()

    def toast(self, text, action=None):
        if self.window:
            self.window.toast(text, action)

    def save_soon(self):
        if not self._save_src:
            self._save_src = GLib.timeout_add(800, self._save_now)

    def _save_now(self):
        self._save_src = 0
        self.settings.save()
        return False

    # ---------- status ----------
    def location(self):
        """(place, vpn_on, country_known) for Home and the status text. Never a network lookup."""
        st = self.vpn.state if getattr(self, "vpn", None) else None
        home = geo.home_location(self.settings.home_city)
        if st and st.on:
            cap = geo.capital(st.country) if st.country else None
            if cap:
                return (cap, True, True)
            return (home, True, False)
        return (home, False, False)

    def eta(self):
        m = self.manager
        return estimate_eta(m.run_file_times, m.run_done, m.run_total, m.run_started)

    def status(self):
        m, s = self.manager, self.settings
        enabled = [f for f in s.folders if f.enabled]
        problems = [m.status[f.id].text for f in enabled
                    if m.status.get(f.id) and m.status[f.id].state in ("error", "missing", "guard")]
        conflicts = sum(1 for f in enabled if m.status.get(f.id) and m.status[f.id].state == "conflict")
        place, vpn_on, known = self.location()
        hold = m.hold
        snap = Snapshot(paused=s.paused, syncing=m.busy and not s.paused, done=m.run_done, total=m.run_total,
                        eta_s=self.eta(), city=place[0] if place else "", via_vpn=vpn_on and known,
                        problems=problems, folders=len(s.folders), enabled=len(enabled), watching=m.watching(),
                        conflicts=conflicts, remote_checked=m.last_remote_check,
                        signed_out=m.logged_in is False and s.onboarded,
                        hold_text=hold["text"] if hold and hold["kind"] != SIGNED_OUT else "")
        st = compute(snap)
        if st.kind != getattr(self, "_last_kind", None):
            self._last_kind = st.kind
            m.state_since = time.time()
        return st

    def refresh_all(self):
        w = self.window
        if not w or w.root.get_visible_child_name() != "main":
            self._update_tray()
            return
        st = self.status()
        w.home.refresh(st, self.location())
        w.folders.status.refresh(st)
        w.status_panel.refresh(st)
        w.refresh_header()
        w.refresh_quick()
        w.refresh_timeline()
        self._update_tray(st)

    def _refresh_tick(self):
        if self.window and self.window.get_visible():
            self.refresh_all()
        return True

    def _vpn_changed(self, st):
        self.vpn_state = st
        log.info("VPN %s %s", "on" if st.on else "off", st.country or "")
        self.refresh_all()

    # ---------- folders ----------
    def add_folder_dialog(self, local=None):
        from .ui.dialogs import FolderDialog
        if not self.window or self.window.root.get_visible_child_name() != "main":
            return
        self.present_window()
        r = FolderDialog(self.window, self, local=local).run()
        if r:
            self.add_folder(r[0])
            self.window.show_tab("folders")

    def add_folder(self, f: FolderPair, quiet=False):
        self.settings.folders.append(f)
        self.settings.save()
        self.manager.folder_added(f)
        self.manager.log("info", f.id, _("Added: {l} ⇄ {r}").format(l=f.local, r=f.remote))
        if self.window:
            self.window.folders.rebuild()
        if not quiet:
            self.toast(_("Syncing “{n}” · first sync started").format(n=f.name))

    def edit_folder(self, fid):
        from .ui.dialogs import FolderDialog
        f = self.settings.folder(fid)
        if not f:
            return
        r = FolderDialog(self.window, self, folder=f).run()
        if r:
            self.settings.save()
            self.manager.folder_changed(r[0], reset_state=r[1])
            self.window.folders.rebuild()
            self.toast(_("Saved “{n}”").format(n=f.name))

    def recheck_folder(self, fid):
        f = self.settings.folder(fid)
        if f:
            self.manager.folder_changed(f, reset_state=True)
            self.toast(_("{n}: every file is checked again on the next sync").format(n=f.name))

    def remove_folder(self, fid):
        """Stops syncing; files stay on both sides (invariant 5). Undo for 8 s."""
        f = self.settings.folder(fid)
        if not f:
            return
        idx = self.settings.folders.index(f)
        self.settings.folders.remove(f)
        share = next((k for k, v in self.settings.shares.items() if v == fid), None)
        if share:
            self.settings.shares.pop(share)
        self.settings.save()
        self.manager.folder_removed(fid)
        self.window.folders.rebuild()
        token = object()
        self._removed[fid] = (f, idx, share, token)

        def undo():
            if fid not in self._removed:
                return
            f2, i2, sh, _t = self._removed.pop(fid)
            self.settings.folders.insert(min(i2, len(self.settings.folders)), f2)
            if sh:
                self.settings.shares[sh] = fid
            self.settings.save()
            self.manager.folder_restored(f2)
            self.window.folders.rebuild()
            self.toast(_("{n} is back").format(n=f2.name))

        def expire():
            entry = self._removed.get(fid)
            if entry and entry[3] is token:
                self._removed.pop(fid)
                self.manager.forget_folder_state(fid)
            return False
        GLib.timeout_add_seconds(UNDO_S + 1, expire)
        self.manager.log("info", fid, _("Stopped syncing {n} · files kept on both sides").format(n=f.name))
        self.toast(_("Stopped syncing {n} · files kept on both sides").format(n=f.name), (_("Undo"), undo))

    def change_mode(self, fid, mode) -> bool:
        """Confirm only when it gets riskier (to two-way). Returns False when the user kept the old mode."""
        f = self.settings.folder(fid)
        if not f or f.mode == mode:
            return True
        if f.is_share and mode != "mirror" and self._share_role(f) == "viewer":
            self.toast(_("You can only view this shared item, so it stays ↓ Mirror down"))
            return False
        old = f.mode
        if mode == "two-way":
            from .ui.dialogs import confirm
            cur = f"{MODES[old][0]} {MODES[old][1]}"
            if not confirm(self.window, _("Two-way sync also sends deletions. Switch {n} to two-way?").format(n=f.name),
                           "", _("Switch to two-way"), _("Keep {m}").format(m=cur)):
                return False
        f.mode = mode
        self.settings.save()
        self.manager.folder_changed(f)
        self.window.folders.refresh_folder(fid)
        label = f"{MODES[mode][0]} {MODES[mode][1]}"

        def undo():
            g = self.settings.folder(fid)
            if g:
                g.mode = old
                self.settings.save()
                self.manager.folder_changed(g)
                self.window.folders.refresh_folder(fid)
        self.toast(f"{f.name}: {label}", (_("Undo"), undo) if mode != "two-way" else None)
        return True

    def _share_role(self, f):
        top = f.remote[len("/shared-with-me/"):].split("/")[0]
        n = next((x for x in self.shared_cache if top in (x.uid, x.name)), None)
        return (n.role if n else "") or "viewer"

    def ask_guard(self, fid):
        from .ui.dialogs import confirm
        f = self.settings.folder(fid)
        n = self.manager.guard_counts.get(fid)
        if not f:
            return
        if n is None:
            self.manager.request(fid)       # re-run: the guard asks again with a fresh count
            return
        self.present_window()
        if confirm(self.window, _("Kluis is about to move {n} files from {f} to the trash.").format(n=n, f=f.name),
                   _("This usually means a folder was moved or a drive is missing."),
                   _("Move them to the trash"), _("Keep everything and pause"), destructive=True, default="cancel"):
            self.manager.approve_trash(fid)
        else:
            self.manager.keep_paused(fid)
        self.refresh_all()

    # ---------- sync controls (header, Quick settings and panel icon stay consistent) ----------
    def set_paused(self, paused):
        self.manager.set_paused(paused)
        self.toast(_("Sync paused · nothing is lost") if paused else _("Syncing resumed"))
        self.refresh_all()

    def stop_sync(self):
        done, total = self.manager.cancel()
        self.toast(_("Stopped at {d} of {n} · nothing lost").format(d=done, n=total))
        self.refresh_all()

    def quick_toggle(self, key):
        s = self.settings
        if key == "pause":
            self.set_paused(not s.paused)
        elif key == "notify":
            order = ["all", "problems", "off"]
            self.set_setting("notifications", order[(order.index(s.notifications) + 1) % 3])
        elif key == "dark":
            self.set_setting("theme", "light" if self.theme.dark else "dark")
        elif key == "login":
            self.set_setting("autostart", not s.autostart)
        elif key == "vpn":
            self.set_setting("vpn_view", not s.vpn_view)
        self.refresh_all()

    def set_setting(self, key, value):
        s = self.settings
        if getattr(s, key) == value:
            return
        setattr(s, key, value)
        s.save()
        if key == "theme":
            self.theme.apply(value)
        elif key == "accent":
            self.theme.apply(s.theme, value)
        elif key == "autostart":
            self._write_autostart()
        elif key == "skip_thumbnails":
            self.cli.skip_thumbnails = value
        elif key in ("beta", "app_updates") and value:
            s.app_last_check = 0
            GLib.idle_add(lambda: (self._hourly(), False)[1])
        self.refresh_all()

    # ---------- account / CLI ----------
    def set_cli_path(self, path, custom=False):
        self.settings.cli_path = path
        self.settings.cli_custom = custom
        self.settings.save()
        self.cli.path = path

    def sign_in_again(self):
        if self.manager.logged_in:
            self.toast(_("You're already signed in."))
            return
        self.present_window()
        self.settings.onboarding_step = 2
        self.window.onboarding.sign_state = "idle"
        self.window.show_onboarding("signed-out")
        self.settings.onboarded = False
        self.settings.save()

    def sign_out(self, switch=True):
        """Signs out of the active Proton account. With other accounts kept in Kluis, the next one takes over
        (like Proton's own account menu); otherwise Kluis shows the sign-in page."""
        from .ui.common import run_bg
        self.manager.cancel()
        me = self.settings.account
        rec = accounts.record(self.settings, me)
        nxt = next((r["email"] for r in accounts.others(self.settings) if not r.get("signed_out")), "") \
            if switch else ""

        def done(_r):
            if rec is not None:
                rec["signed_out"] = True
            if nxt:
                self.manager.log("info", "", _("Signed out of {e}").format(e=me))
                self.switch_account(nxt, force=True)
                return
            self.manager.logged_in = False
            self.manager.email = ""
            self.settings.onboarded = False
            self.settings.onboarding_step = 2
            self.settings.save()
            self.window.onboarding.sign_state = "idle"
            self.window.show_onboarding("signed-out")
            self.manager.log("info", "", _("Signed out"), _("Your files stay on this computer and in Proton Drive."))
            self._update_tray()
            self.refresh_accounts()

        def work():
            self.cli.logout()
            if me and self.vault.available:          # in the same step: gone before anything else happens
                try:
                    self.vault.forget(me)
                except Exception as e:  # noqa: BLE001
                    log.warning("keyring: %s", e)
        run_bg(work, done, lambda e: self.toast(_("Sign-out failed: {e}").format(e=e)))

    # ---------- more than one Proton account (kluis/accounts.py, decisions D30) ----------
    def _stop_for_switch(self):
        self.manager.switching = True
        if self.manager.busy:
            self.manager.cancel()

    def _wait_idle(self, limit=60.0):
        """Worker thread only: the current folder run stops at its next file."""
        end = time.time() + limit
        while self.manager.current is not None and time.time() < end:
            time.sleep(0.1)

    def _keep_live_session(self, email):
        """Worker thread: copy the CLI's current session to the account it belongs to."""
        if not email or not self.vault.available:
            return
        try:
            live = self.vault.read_live()
            if live:
                self.vault.save(email, live)
        except Exception as e:  # noqa: BLE001
            log.warning("could not keep the session of %s: %s", email, e)

    def switch_account(self, email, force=False):
        """One click when the account's session is kept in the keyring; otherwise Proton's browser sign-in."""
        if not email or (self.manager.switching and not force):
            return
        if not force and email.lower() == (self.settings.account or "").lower() and self.manager.logged_in:
            return
        self._stop_for_switch()
        prev = self.settings.account
        rec = accounts.record(self.settings, email) or {}
        self.toast(_("Switching to {e}…").format(e=email))

        def work():
            self._wait_idle()
            if prev and prev.lower() != email.lower():
                self._keep_live_session(prev)
            saved = None
            try:
                saved = self.vault.load(email) if self.vault.available else None
            except Exception as e:  # noqa: BLE001
                log.warning("keyring: %s", e)
            self.cli.cache_dir = rec.get("cache", "")
            if saved:
                try:
                    self.vault.write_live(saved)
                    if self.cli.is_logged_in():
                        info = self.cli.info("/my-files")
                        owner = info.get("ownedBy") or {}
                        return "ok", (owner.get("email") if isinstance(owner, dict) else "") or email
                except Exception as e:  # noqa: BLE001
                    log.info("kept session of %s didn't work (%s); asking for a sign-in", email, e)
            try:
                self.vault.clear_live()           # local only: never ends the other account's session at Proton
            except Exception as e:  # noqa: BLE001
                log.warning("keyring: %s", e)
            return "sign-in", email

        def done(res):
            kind, who = res
            accounts.swap_profile(self.settings, who)
            r = accounts.record(self.settings, who)
            self.manager.email = who
            self.manager.use_account(accounts.state_path(r))
            self.window.account_changed()
            self._pending_cache = None
            if kind == "ok":
                self.switch_back = ""
                self.manager.logged_in = True
                self.manager.switching = False
                self.settings.onboarded = True
                self.settings.onboarding_step = 1
                self.settings.save()
                self.window.show_main()
                self.toast(_("Switched to {e}").format(e=who))
                self.manager.log("info", "", _("Switched to {e}").format(e=who))
                self.manager.request(reason="start")
            else:
                self.manager.logged_in = False
                self._ask_sign_in(prev, who)
            self.refresh_accounts()

        def fail(e):
            self.manager.switching = False
            self.toast(_("Couldn't switch accounts: {e}").format(e=e))
            self.refresh_accounts()
        from .ui.common import run_bg
        run_bg(work, done, fail)

    def _ask_sign_in(self, back_to, expect=""):
        """Proton's browser sign-in for another account, with a way back to the one before."""
        self.switch_back = back_to if back_to and back_to.lower() != (expect or "").lower() else ""
        self.settings.onboarded = False
        self.settings.onboarding_step = 2
        self.settings.save()
        ob = self.window.onboarding
        ob.sign_state = "idle"
        ob.expect_email = expect
        ob.picks = {}
        self.present_window()
        self.window.show_onboarding("signed-out")

    def add_account(self):
        """Sign in to one more Proton account; the current one stays in the account list."""
        if self.manager.switching:
            return
        self._stop_for_switch()
        prev = self.settings.account
        import uuid
        pending = os.path.join(str(accounts.DATA_DIR), "accounts", "new-" + uuid.uuid4().hex[:8], "cli")

        def work():
            self._wait_idle()
            self._keep_live_session(prev)
            try:
                self.vault.clear_live()
            except Exception as e:  # noqa: BLE001
                log.warning("keyring: %s", e)
            self.cli.cache_dir = pending

        def done(_r):
            self._pending_cache = pending
            self.manager.logged_in = False
            self._ask_sign_in(prev)

        def fail(e):
            self.manager.switching = False
            self.toast(_("Couldn't add an account: {e}").format(e=e))
        from .ui.common import run_bg
        run_bg(work, done, fail)

    def cancel_switch(self):
        """"Stay with …" on the sign-in page: back to the account before."""
        back = self.switch_back
        self.window.onboarding.cancel_sign_in()
        if back:
            self.switch_account(back, force=True)

    def _adopt_account(self):
        """The CLI is signed in as manager.email: make sure Kluis shows and syncs that account's folders."""
        email = self.manager.email
        if not email:
            self.manager.switching = False
            return
        changed = accounts.adopt(self.settings, email)
        rec = accounts.record(self.settings, email)
        if self._pending_cache is not None:
            rec["cache"] = self._pending_cache        # the folder this account's sign-in used
            self._pending_cache = None
        elif changed:
            self.cli.cache_dir = rec.get("cache", "")
        if changed:
            self.manager.use_account(accounts.state_path(rec))
            if self.window:
                self.window.account_changed()
            self.manager.log("info", "", _("Signed in as {e}").format(e=email))
        self.switch_back = ""
        self.manager.switching = False
        self.settings.save()
        if accounts.others(self.settings):      # one account: nothing to switch to, keep no extra copy
            from .ui.common import run_bg
            run_bg(lambda: self._keep_live_session(email))
        self.refresh_accounts()

    def forget_account(self, email):
        """Remove another account from Kluis. Its folders on this computer stay as they are."""
        if email.lower() == (self.settings.account or "").lower():
            return
        accounts.forget(self.settings, email)
        self.settings.save()
        from .ui.common import run_bg
        run_bg(lambda: self.vault.forget(email))
        self.toast(_("Removed {e} from Kluis").format(e=email))
        self.refresh_accounts()

    def sign_out_all(self):
        from .ui.common import run_bg
        others = [r["email"] for r in accounts.others(self.settings)]

        def forget_all():
            for e in others:
                try:
                    self.vault.forget(e)
                except Exception:  # noqa: BLE001
                    pass
        run_bg(forget_all)
        for r in accounts.others(self.settings):
            r["signed_out"] = True
        self.sign_out(switch=False)

    def refresh_accounts(self):
        if self.window and hasattr(self.window, "account_btn"):
            self.window.account_btn.refresh()
        self.refresh_all()

    def run_setup_again(self):
        self.settings.onboarding_step = 1
        self.settings.save()
        self.window.onboarding.cli_state = "done" if self.cli.path else "idle"
        self.window.show_onboarding("ok" if self.manager.logged_in else
                                    ("signed-out" if self.cli.path else "no-cli"))
        self.window.onboarding.show_step(1)
        self.settings.onboarded = False
        self.settings.save()

    def check_cli(self, force=False, done=None):
        from .cliupdate import check_and_update
        from .ui.common import run_bg

        def work():
            return check_and_update(self.settings, self.cli, bool(self.manager.logged_in), force=force)

        def finished(res):
            self.settings.save()
            if res.status == "updated":
                self.manager.log("ok", "", _("Proton Drive CLI {v} installed").format(v=res.version),
                                 _("Checksum verified (SHA-512) and capability self-test passed"))
                self.toast(_("Proton Drive CLI updated to {v}").format(v=res.version))
            elif res.status == "incompatible" and res.message:
                self.manager.log("error", "", res.message, _("Kluis keeps the previous version and checks again daily."))
                self.notify(_("Proton changed its Drive tool"), _("Kluis needs an update for it."), problem=True)
            elif res.status == "error" and force:
                self.toast(res.message)
            if done:
                done(res)
        run_bg(work, finished, lambda e: done and done(None))

    def _hourly(self):
        s = self.settings
        if self.cli.path and time.time() - s.cli_last_check >= 24 * 3600:
            self.check_cli()
        if s.app_updates and time.time() - s.app_last_check >= 24 * 3600:
            s.app_last_check = time.time()
            from . import appupdate
            from .ui.common import run_bg

            def got(rel):
                if rel and rel["version"] != s.app_notified_version:
                    s.app_notified_version = rel["version"]
                    s.save()
                    self.notify(_("Kluis {v} is available").format(v=rel["version"]), rel["url"], problem=True)
                    self.manager.log("info", "", _("Kluis {v} is available").format(v=rel["version"]), rel["url"])
            run_bg(lambda: appupdate.check(s.beta), got, lambda e: log.info("update check failed: %s", e))
        return True

    def auto_selftest(self):
        """§8 D / decisions D18: after an install, an upgrade or a CLI update, run --selftest once in the
        background (a package script runs as root and can't reach her keyring, so the app does it)."""
        if os.environ.get("KLUIS_TEST") == "1" or not self.manager.logged_in:
            return
        from .ui.common import run_bg
        try:
            cli_v = self.cli.version().split("+")[0]
        except Exception:  # noqa: BLE001
            return
        key = f"{VERSION}/{cli_v}"
        if self.settings.selftest_for == key:
            return
        self.settings.selftest_for = key
        self.settings.save()
        self.manager.log("info", "", _("Self-test started"), _("Checks Kluis and the Proton Drive CLI in its own "
                                                              "test folder; nothing else is touched."))

        def work():
            from .selftest import SelfTest
            t = SelfTest(self.cli, out=lambda line: log.info("selftest %s", line))
            try:
                t.run()
                return True, f"{t.steps} checks"
            except Exception as e:  # noqa: BLE001
                return False, str(e)
            finally:
                t.cleanup()

        def done(r):
            ok, detail = r
            if ok:
                self.manager.log("ok", "", _("Self-test passed"), detail)
            else:
                self.manager.set_paused(True)
                self.manager.log("error", "", _("Self-test failed — syncing stays paused"), detail)
                self.notify(_("Kluis self-test failed"), _("Syncing stays paused. Open Kluis → Activity."),
                            problem=True)
            self.refresh_all()
        run_bg(work, done)

    # ---------- root folder (§3.8.1, invariant 6) ----------
    def move_root(self, dest, parent, done=None):
        from . import rootmove
        from .ui.common import run_bg
        from .ui.dialogs import confirm
        src = self.settings.root_dir
        if not os.path.isdir(src):
            self.settings.root_dir = dest
            self.settings.save()
            done and done()
            return
        dest = os.path.join(dest, os.path.basename(src)) if os.path.isdir(dest) and os.listdir(dest) else dest
        problem = rootmove.check_target(src, dest)
        if problem:
            confirm(parent, _("Can't move there"), problem, _("OK"), _("Close"))
            return
        was_paused = self.settings.paused
        self.manager.set_paused(True)
        j = rootmove.start(src, dest)
        dlg = Gtk.MessageDialog(transient_for=parent, modal=True, text=_("Moving your Proton Drive folder…"))
        dlg.get_style_context().add_class("kluis")
        bar = Gtk.ProgressBar(show_text=True)
        dlg.get_message_area().pack_start(bar, False, False, 0)
        cancel = {"v": False}
        dlg.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        dlg.connect("response", lambda *_: cancel.update(v=True))
        dlg.show_all()

        def progress(i, n, _name):
            GLib.idle_add(lambda: (bar.set_fraction(i / n if n else 1),
                                   bar.set_text(_("Moving {i} of {n} files").format(i=i, n=n)), False)[2])

        def finished(ok):
            dlg.destroy()
            if ok:
                self._finish_root_move(src, dest)
                self.toast(_("Moved your Proton Drive folder to {p}").format(p=dest),
                           (_("Undo"), lambda: self.move_root(os.path.dirname(src) if os.path.basename(src) ==
                                                              os.path.basename(dest) else src, parent, done)))
            else:
                self.toast(_("Move paused · Kluis finishes it the next time you start it"))
            if not was_paused:
                self.manager.set_paused(False)
            done and done()
        run_bg(lambda: rootmove.run(j, progress, lambda: cancel["v"]), finished,
               lambda e: (dlg.destroy(), self.toast(_("Move stopped: {e}").format(e=e)),
                          not was_paused and self.manager.set_paused(False)))

    def _finish_root_move(self, src, dest):
        from . import rootmove
        self.settings.root_dir = dest
        for f in self.settings.folders:
            f.local = rootmove.remap(f.local, src, dest)
        self.settings.save()
        self.manager.rewatch()
        self.manager.log("ok", "", _("Moved your Proton Drive folder"), f"{src} → {dest}")
        if self.window:
            self.window.folders.rebuild()

    def _resume_root_move(self):
        from . import rootmove
        j = rootmove.pending()
        if not j:
            return
        log.warning("finishing an interrupted folder move %s -> %s", j["src"], j["dest"])
        try:
            if rootmove.run(j):
                self._finish_root_move(j["src"], j["dest"])
        except (OSError, rootmove.MoveError) as e:
            log.error("could not finish the folder move: %s", e)

    # ---------- misc ----------
    def open_settings(self):
        from .ui.dialogs import SettingsDialog
        if not self.window:
            return
        self.present_window()
        SettingsDialog(self.window, self).run()
        self.refresh_all()

    def open_logs(self):
        from .ui.common import open_path
        open_path(str(STATE_DIR))

    def copy_diagnostics(self):
        from . import diagnostics
        from .ui.common import run_bg

        def got(ver):
            text = diagnostics.collect(self.settings, ver)
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
            self.toast(_("Copied"))
        run_bg(self.cli.version, got, lambda e: got("?"))

    def search(self, q):
        """Names Kluis already knows: synced folders (from the sync state), the folder open in Browse and all
        its subfolders (read while counting Files/Size; D17, Walter 2026-11-26)."""
        hits = []
        seen = set()
        for f in self.settings.folders:
            for rel in self.manager.store.load(f.id):
                if q in rel.rsplit("/", 1)[-1].lower():
                    hits.append((f"{f.remote}/{rel}", rel.rsplit("/", 1)[-1]))
                    if len(hits) > 50:
                        return hits
        if self.window:
            b = self.window.browser
            for n in b.nodes:
                if q in n.name.lower():
                    hits.append((f"{b.path}/{n.name}", n.name))
            seen.update(h[0] for h in hits)
            here = b.path.rstrip("/") + "/"
            for root, found in list(b.stats.names.items()):
                if not (root + "/").startswith(here):
                    continue
                for path, name in found:
                    if q in name.lower() and path not in seen:
                        seen.add(path)
                        hits.append((path, name))
                        if len(hits) > 200:
                            return hits
        return hits

    def _write_autostart(self):
        path = AUTOSTART_DIR / "kluis.desktop"
        if self.settings.autostart:
            AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
            exe = shutil.which("kluis") or os.path.expanduser("~/.local/bin/kluis")
            exe = exe if os.path.exists(exe) else f"{sys.executable} -m kluis"
            hidden = " --hidden" if self.settings.start_minimized else ""
            tmp = path.with_suffix(".tmp")
            tmp.write_text("[Desktop Entry]\nType=Application\nName=Kluis\n"
                           "Comment=Proton Drive sync (unofficial)\n"
                           f"Exec={exe}{hidden}\nIcon={APP_ID}\nX-GNOME-Autostart-enabled=true\n"
                           "X-GNOME-Autostart-Delay=10\nX-KDE-autostart-after=panel\n")
            os.replace(tmp, path)
        elif path.exists():
            path.unlink()

    def about(self):
        d = Gtk.AboutDialog(transient_for=self.window, modal=True, program_name=APP_NAME, version=VERSION,
                            logo_icon_name=APP_ID,
                            comments=_("Unofficial Proton Drive client for Linux Mint and EndeavourOS. Every transfer "
                                       "goes through Proton’s official CLI, so files stay end-to-end encrypted. "
                                       "Not affiliated with Proton AG.\n\n“Kluis” is Afrikaans for a safe."),
                            license_type=Gtk.License.GPL_3_0,
                            website="https://github.com/Sundowna/kluis/releases", website_label="Kluis releases")
        d.get_style_context().add_class("kluis")
        d.run()
        d.destroy()

    # ---------- events from the sync manager ----------
    def _on_manager(self, kind, fid, payload):
        w = self.window
        if kind == "rate":
            if w and w.get_visible() and w.root.get_visible_child_name() == "main":
                w.status_panel.refresh_rate()
            return
        if kind == "account" and payload == "ok":
            self._adopt_account()        # before anything syncs: the folders must be this account's
            return
        if not w:
            return
        if kind == "folder":
            if fid == PHOTOS_ID:
                w.photos.refresh_status()
            else:
                w.folders.refresh_folder(fid)
        elif kind in ("global", "tick"):
            if kind == "tick":
                w.folders.refresh_all()
            self.refresh_all()
        elif kind == "activity":
            if payload is None:
                w.activity.rebuild()
            else:
                w.activity.prepend(payload)
            w.refresh_timeline()
            w.refresh_header()
        elif kind == "account" and payload == "signed-out" and self.settings.onboarded:
            self.notify(_("Sign in to keep syncing"), _("Your Proton Drive session ended."), problem=True)
            self.refresh_all()
        elif kind == "guard":
            self.notify(_("Kluis paused {n}").format(n=self.manager.name_of(fid)),
                        _("{c} files would go to the trash. Open Kluis to check.").format(c=payload), problem=True)
            GLib.idle_add(lambda: (self.ask_guard(fid), False)[1])
        elif kind == "problem":
            if payload == DISK_FULL:
                self.notify(_("Disk full on this computer"), _("Kluis paused syncing and continues when there is "
                                                                "space again."), problem=True)
            elif payload == "missing":
                self.notify(_("Folder not found"), self.manager.status[fid].text if fid in self.manager.status
                            else "", problem=True)
        elif kind == "result":
            name = self.manager.name_of(fid)
            if name and payload.status == "error":
                fails = [e for e in payload.errors if "upload failed" in e.lower()]
                if fails:
                    self.notify_batched("upload", name, len(fails))
                else:
                    self.notify(_("Problem syncing {n}").format(n=name), payload.message, problem=True)
            elif name and payload.status == "conflict":
                self.notify(_("Conflict in {n}").format(n=name), payload.message, problem=True)
            elif name and payload.status == "ok" and self.settings.notifications == "all" \
                    and payload.message not in ("Up to date", "Stopped"):
                self.notify(_("{n} synced").format(n=name), payload.message)
            if not self.manager.busy and payload.status == "ok" and self.manager.run_total:
                self.toast(_("Everything is up to date ✓"))
        if kind in ("folder", "photos-done") and fid == PHOTOS_ID:
            w.photos.refresh_status(reload=kind == "photos-done")

    def _update_tray(self, st=None):
        if not self.tray:
            return
        st = st or (self.status() if self.settings.onboarded else None)
        m = self.manager
        if not st:
            self.tray.update("idle", _("Setting up"))
        elif m.logged_in is False:
            self.tray.update("error", _("Sign in to keep syncing"))
        elif st.kind == "paused":
            self.tray.update("paused", st.title)
        elif st.kind == "syncing":
            self.tray.update("sync", st.title)
        elif st.kind == "problems":
            self.tray.update("error", st.title)
        else:
            self.tray.update("idle", st.title)

    # ---------- notifications (§3.12) ----------
    def notify_batched(self, kind, name, n):
        """Failed uploads add up: one "3 files couldn't upload" instead of one per folder."""
        self._queue_note(("upload", ngettext("{n} file couldn't upload", "{n} files couldn't upload", n).format(n=n),
                          _("Kluis will try again. See Activity for details."), n))

    def notify(self, title, body, force=False, problem=False):
        level = self.settings.notifications
        if not force and (level == "off" or (level == "problems" and not problem)):
            return
        if force:
            self._send(title, body)
            return
        self._queue_note(("note", title, body, 1))

    def _queue_note(self, note):
        if self.settings.notifications == "off":
            return
        self._notes.append(note)
        if self._note_src:
            return
        wait = self._last_note + NOTIFY_GAP - time.time()
        if wait <= 0:
            self._flush_notes()
        else:
            self._note_src = GLib.timeout_add(int(wait * 1000) + 50, self._flush_notes)

    def _flush_notes(self):
        self._note_src = 0
        notes, self._notes = self._notes, []
        if not notes:
            return False
        uploads = sum(n[3] for n in notes if n[0] == "upload")
        others = [n for n in notes if n[0] != "upload"]
        if uploads and not others:
            self._send(ngettext("{n} file couldn't upload", "{n} files couldn't upload", uploads).format(n=uploads),
                       _("Kluis will try again. See Activity for details."))
        elif len(notes) == 1:
            self._send(notes[0][1], notes[0][2])
        else:
            self._send(ngettext("{n} thing needs your attention", "{n} things need your attention",
                                len(notes)).format(n=len(notes)),
                       "; ".join(n[1] for n in notes[:3]) + ("…" if len(notes) > 3 else ""))
        return False

    def _send(self, title, body):
        self._last_note = time.time()
        n = Gio.Notification.new(title)
        n.set_body(body)
        n.set_icon(Gio.ThemedIcon.new(APP_ID))
        n.set_default_action("app.show")
        self.sent_notifications.append((title, body))
        self.send_notification(None, n)

    sent_notifications: list = []


def run(argv):
    if "--selftest" in argv:
        from .selftest import main as selftest_main
        return selftest_main(argv)
    if "--version" in argv:
        print(f"Kluis {VERSION}")
        return 0
    hidden = "--hidden" in argv
    argv = [a for a in argv if a != "--hidden"]
    app = KluisApp(hidden=hidden)
    return app.run(argv)


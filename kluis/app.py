"""Application: wires settings, CLI, sync manager, window, panel icon and notifications."""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, APP_NAME, VERSION  # noqa: E402
from .cli import ProtonDriveCli, download_cli, fetch_latest_release, find_cli  # noqa: E402
from .config import FolderPair, Settings  # noqa: E402
from .manager import SyncManager  # noqa: E402
from .paths import AUTOSTART_DIR, LOG_FILE, ensure_dirs  # noqa: E402

DATA = os.path.join(os.path.dirname(__file__), "data")
log = logging.getLogger("kluis")


def setup_logging():
    ensure_dirs()
    h = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("kluis")
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

    # ---------- startup ----------
    def do_startup(self):
        Gtk.Application.do_startup(self)
        setup_logging()
        self.settings = Settings.load()
        self.cli = ProtonDriveCli(find_cli(self.settings.cli_path), self.settings.skip_thumbnails)
        self.manager = SyncManager(self.settings, self.cli)
        self.manager.listeners.append(self._on_manager)

        icons = Gtk.IconTheme.get_default()
        icons.append_search_path(os.path.join(DATA, "icons"))
        css = Gtk.CssProvider()
        css.load_from_path(os.path.join(DATA, "style.css"))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.apply_settings()

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

        from .tray import Tray
        self.tray = Tray(self)
        self.hold()  # keep running in the panel when the window is closed

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
        else:
            self.present_window()

    def recheck(self):
        self.manager.check_account(self._account_checked)

    def _account_checked(self, state):
        self.account_state = state
        if state == "ok" and self.settings.onboarded:
            self.window.show_main()
            self.manager.rewatch()
            self.manager.request(reason="start")
        elif state == "offline" and self.settings.onboarded:
            self.window.show_main()
            self.window.toast("Can't reach Proton Drive right now. Kluis will keep trying.")
            GLib.timeout_add_seconds(120, lambda: (self.recheck(), False)[1])
        else:
            self.window.show_onboarding(state if state != "offline" else "ok")
            if state in ("no-cli", "signed-out") and self.settings.onboarded:
                self.present_window()
        self._update_tray()
        return False

    # ---------- window ----------
    def _on_close(self, win, _ev):
        if self.tray and self.tray.available:
            win.hide()
            if not getattr(self, "_told_tray", False):
                self._told_tray = True
                self.notify("Kluis keeps syncing in the background",
                            "Click the panel icon to open it again, or choose Quit from its menu.", force=True)
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
        self.settings.save()
        self.release()
        self.quit()

    def toast(self, text, action=None):
        if self.window:
            self.window.toast(text, action)

    # ---------- folders ----------
    def add_folder_dialog(self, local=None):
        from .ui.dialogs import FolderDialog
        self.present_window()
        r = FolderDialog(self.window, self, local=local).run()
        if r:
            self.add_folder(r[0])
            if self.window.root.get_visible_child_name() == "welcome":
                return
            self.window.show_main()
            self.toast(f"Syncing “{r[0].name}”")

    def add_folder(self, f: FolderPair):
        self.settings.folders.append(f)
        self.settings.save()
        self.manager.folder_added(f)
        self.manager.log("info", f.id, f"Added: {f.local} ⇄ {f.remote}")

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

    def remove_folder(self, fid):
        from .ui.dialogs import confirm
        f = self.settings.folder(fid)
        if not f:
            return
        if confirm(self.window, f"Stop syncing “{f.name}”?",
                   "Nothing is deleted. The files stay on this computer and in Proton Drive."):
            self.settings.folders.remove(f)
            self.settings.save()
            self.manager.folder_removed(fid)
            self.window.folders.rebuild()
            self.toast(f"Stopped syncing “{f.name}”")

    # ---------- account / CLI ----------
    def set_cli_path(self, path):
        self.settings.cli_path = path
        self.settings.save()
        self.cli.path = path

    def sign_in_again(self):
        if self.manager.logged_in:
            self.toast("You are already signed in.")
            return
        self.present_window()
        self.window.show_onboarding("signed-out")

    def sign_out(self):
        self.manager.cancel()

        def done(_r):
            self.manager.logged_in = False
            self.window.show_onboarding("signed-out")
            self._update_tray()
        from .ui.common import run_bg
        run_bg(self.cli.logout, done, lambda e: self.toast(f"Sign-out failed: {e}"))

    def update_cli(self, parent, finished):
        from .ui.common import run_bg
        from .ui.dialogs import confirm, error_dialog

        def check():
            rel = fetch_latest_release()
            return rel, (self.cli.version() if self.cli.path else "")

        def got(result):
            rel, current = result
            if not rel:
                error_dialog(parent, "No update information", "Could not read Proton's version list.")
                finished()
                return
            if rel["version"] and rel["version"] in current:
                self.toast(f"The Proton Drive CLI is up to date ({rel['version']}).")
                finished()
                return
            if confirm(parent, f"Update the Proton Drive CLI to {rel['version']}?",
                       "Kluis downloads it from proton.me, checks the SHA-512 checksum and replaces "
                       "~/.local/bin/proton-drive.", ok="Update", destructive=False):
                self.manager.cancel()
                run_bg(download_cli, lambda p: (self.set_cli_path(p), self.toast("CLI updated"), finished()),
                       lambda e: (error_dialog(parent, "Update failed", str(e)), finished()))
            else:
                finished()
        run_bg(check, got, lambda e: (error_dialog(parent, "Update check failed", str(e)), finished()))

    # ---------- settings ----------
    def open_settings(self):
        from .ui.dialogs import SettingsDialog
        self.present_window()
        SettingsDialog(self.window, self).run()

    def apply_settings(self):
        gs = Gtk.Settings.get_default()
        if self.settings.theme == "dark":
            gs.set_property("gtk-application-prefer-dark-theme", True)
        elif self.settings.theme == "light":
            gs.set_property("gtk-application-prefer-dark-theme", False)
        self._write_autostart()
        if self.window:
            self.window.folders.refresh_hero()

    def _write_autostart(self):
        path = AUTOSTART_DIR / "kluis.desktop"
        if self.settings.autostart:
            AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
            import shutil
            exe = shutil.which("kluis") or os.path.expanduser("~/.local/bin/kluis")
            exe = exe if os.path.exists(exe) else f"{sys.executable} -m kluis"
            path.write_text("[Desktop Entry]\nType=Application\nName=Kluis\n"
                            "Comment=Proton Drive sync (unofficial)\n"
                            f"Exec={exe} --hidden\nIcon={APP_ID}\nX-GNOME-Autostart-enabled=true\n"
                            "X-GNOME-Autostart-Delay=10\n")
        elif path.exists():
            path.unlink()

    def about(self):
        d = Gtk.AboutDialog(transient_for=self.window, modal=True, program_name=APP_NAME, version=VERSION,
                            logo_icon_name=APP_ID,
                            comments="Unofficial desktop client for Proton Drive on Linux, built on the "
                                     "official Proton Drive CLI. Not affiliated with Proton AG.\n\n"
                                     "“Kluis” is Afrikaans for a safe or vault.",
                            license_type=Gtk.License.GPL_3_0,
                            website="https://proton.me/download/drive/cli/index.html",
                            website_label="Official Proton Drive CLI")
        d.run()
        d.destroy()

    # ---------- events from the sync manager ----------
    def _on_manager(self, kind, fid, payload):
        w = self.window
        if not w:
            return
        if kind == "folder":
            w.folders.refresh_folder(fid)
        elif kind in ("global", "tick"):
            w.folders.refresh_hero()
            w.refresh_toolbar()
            if kind == "tick":
                for r in w.folders.rows.values():
                    r.refresh()
            self._update_tray()
        elif kind == "activity":
            if payload is None:
                w.activity.rebuild()
            else:
                w.activity.prepend(payload)
        elif kind == "account" and payload == "signed-out" and self.settings.onboarded:
            w.folders.refresh_hero()
            self.notify("Sign in to keep syncing", "Your Proton Drive session ended.", force=True)
        elif kind == "result":
            name = self.manager.name_of(fid)
            if name and payload.status == "error":
                self.notify(f"Problem syncing {name}", payload.message)
            elif name and payload.status == "conflict":
                self.notify(f"Conflict in {name}", payload.message)
            elif name and self.settings.notifications == "all" and payload.message not in ("Up to date", "Stopped"):
                self.notify(f"{name} synced", payload.message)
        if kind in ("folder", "photos-done") and fid == "photos" and hasattr(w, "photos"):
            w.photos.refresh_status(reload=kind == "photos-done")

    def _update_tray(self):
        if not self.tray:
            return
        m, s = self.manager, self.settings
        if m.logged_in is False:
            self.tray.update("error", "Signed out")
        elif s.paused:
            self.tray.update("paused", "Paused")
        elif m.current:
            self.tray.update("sync", f"Syncing {m.name_of(m.current)}…")
        elif any(m.status.get(f.id) and m.status[f.id].state == "error" for f in s.folders if f.enabled):
            self.tray.update("error", "A folder needs attention")
        else:
            self.tray.update("idle", "Up to date")

    def notify(self, title, body, force=False):
        if self.settings.notifications == "off" and not force:
            return
        n = Gio.Notification.new(title)
        n.set_body(body)
        n.set_icon(Gio.ThemedIcon.new(APP_ID))
        n.set_default_action("app.show")
        self.send_notification(None, n)


def run(argv):
    hidden = "--hidden" in argv
    argv = [a for a in argv if a != "--hidden"]
    app = KluisApp(hidden=hidden)
    return app.run(argv)

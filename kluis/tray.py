"""Panel icon. Linux Mint (Cinnamon/MATE/Xfce) uses XApp.StatusIcon; elsewhere Ayatana AppIndicator;
Windows the notification area (kluis/wintray.py), with the same menu."""
from __future__ import annotations

import logging
import os

import gi
from gi.repository import Gtk

log = logging.getLogger("kluis.tray")
ICON_DIR = os.path.join(os.path.dirname(__file__), "data", "icons")


def _icon(name):
    return os.path.join(ICON_DIR, f"kluis-tray-{name}.svg")


class Tray:
    def __init__(self, app):
        self.app = app
        self.kind = None
        self.menu = Gtk.Menu()
        self.status_item = Gtk.MenuItem(label="Kluis", sensitive=False)
        self.menu.append(self.status_item)
        self.menu.append(Gtk.SeparatorMenuItem())
        self.sync_item = Gtk.MenuItem(label="Sync now")
        self.sync_item.connect("activate", lambda *_: app.manager.request())
        self.menu.append(self.sync_item)
        self.pause_item = Gtk.MenuItem(label="Pause syncing")
        self.pause_item_cb = lambda: app.set_paused(not app.settings.paused)
        self.pause_item.connect("activate", lambda *_: self.pause_item_cb())
        self.menu.append(self.pause_item)
        self.menu.append(Gtk.SeparatorMenuItem())
        open_item = Gtk.MenuItem(label="Open Kluis")
        self.open_item = open_item
        open_item.connect("activate", lambda *_: app.present_window())
        self.menu.append(open_item)
        web = Gtk.MenuItem(label="Proton Drive on the web")
        web.connect("activate", lambda *_: __import__("kluis.ui.common", fromlist=["open_uri"]).open_uri(
            "https://drive.proton.me/"))
        self.menu.append(web)
        self.menu.append(Gtk.SeparatorMenuItem())
        quit_item = Gtk.MenuItem(label="Quit Kluis")
        quit_item.connect("activate", lambda *_: app.quit_app())
        self.menu.append(quit_item)
        self.menu.show_all()
        self._setup()

    def _setup(self):
        if os.name == "nt":
            if self._try_windows():
                log.info("panel icon: Windows notification area")
                return
            self.icon = None
            return
        # Cinnamon, MATE and Xfce (Linux Mint) have XApp's own panel applet. KDE Plasma (EndeavourOS
        # default), GNOME with the AppIndicator extension, Budgie etc. use StatusNotifier via Ayatana.
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
        xapp_first = any(d in desktop for d in ("CINNAMON", "MATE", "XFCE"))
        order = [self._try_xapp, self._try_indicator] if xapp_first else [self._try_indicator, self._try_xapp]
        for attempt in order:
            if attempt():
                log.info("panel icon: %s (desktop %s)", self.kind, desktop or "?")
                return
        log.warning("No panel icon library found; closing the window will quit Kluis")
        self.icon = None

    def _try_windows(self) -> bool:
        try:
            from .wintray import WinTrayIcon
            self.icon = WinTrayIcon(self.app.toggle_window, self._windows_menu, self.app.present_window)
        except Exception as e:  # noqa: BLE001
            log.warning("Windows notification area icon not available: %s", e)
            return False
        self.kind = "windows"
        self._set_windows_icon("idle", "Kluis")
        return True

    def _windows_menu(self):
        """The same entries as the GTK menu, read from it, so labels and greyed-out items always match."""
        out = []
        for item in self.menu.get_children():
            if isinstance(item, Gtk.SeparatorMenuItem):
                out.append(None)
            else:
                out.append((item.get_label(), (lambda it=item: it.activate()) if item.get_sensitive() else None))
        return out

    def _set_windows_icon(self, state, text):
        from .wintray import icon_from_svg
        import ctypes
        size = ctypes.windll.user32.GetSystemMetrics(49) or 16          # SM_CXSMICON, follows display scaling
        try:
            hicon = icon_from_svg(_icon(state), size)
        except Exception as e:  # noqa: BLE001
            log.warning("tray icon %s: %s", state, e)
            hicon = 0
        self.icon.set_icon(hicon, text)

    def balloon(self, title: str, body: str, problem: bool = False) -> bool:
        """Windows: a notification from the tray icon. False where Kluis uses Gio notifications instead."""
        if self.kind != "windows" or not self.icon:
            return False
        return self.icon.balloon(title, body, warning=problem)

    def _try_xapp(self) -> bool:
        try:
            gi.require_version("XApp", "1.0")
            from gi.repository import XApp
        except (ValueError, ImportError) as e:
            log.info("XApp status icon not available: %s", e)
            return False
        self.icon = XApp.StatusIcon()
        self.icon.set_name("kluis")
        self.icon.set_icon_name(_icon("idle"))
        self.icon.set_tooltip_text("Kluis")
        self.icon.set_secondary_menu(self.menu)
        self.icon.connect("activate", self._xapp_activate)
        self.icon.set_visible(True)
        self.kind = "xapp"
        return True

    def _try_indicator(self) -> bool:
        for ns in ("AyatanaAppIndicator3", "AppIndicator3"):
            try:
                gi.require_version(ns, "0.1")
                mod = __import__("gi.repository." + ns, fromlist=[ns])
            except (ValueError, ImportError) as e:
                log.info("%s not available: %s", ns, e)
                continue
            ind = mod.Indicator.new("kluis", _icon("idle"), mod.IndicatorCategory.APPLICATION_STATUS)
            ind.set_status(mod.IndicatorStatus.ACTIVE)
            ind.set_menu(self.menu)
            ind.set_title("Kluis")
            self.icon, self.kind, self._mod = ind, "indicator", mod
            return True
        return False

    def close(self):
        if not self.icon:
            return
        try:
            if self.kind == "xapp":
                self.icon.set_visible(False)
            elif self.kind == "windows":
                self.icon.close()
            else:
                self.icon.set_status(self._mod.IndicatorStatus.PASSIVE)
        except Exception:  # noqa: BLE001 - quitting anyway
            pass

    @property
    def available(self) -> bool:
        return self.icon is not None

    def _xapp_activate(self, _icon, button, _time):
        if button == 1:
            self.app.toggle_window()

    def update(self, state: str, text: str):
        """state: idle | sync | error | paused"""
        self.state = state
        self.status_item.set_label(text)
        self.sync_item.set_sensitive(not self.app.settings.paused)
        self.pause_item.set_label("Resume syncing" if self.app.settings.paused else "Pause syncing")
        if not self.icon:
            return
        if self.kind == "xapp":
            self.icon.set_icon_name(_icon(state))
            self.icon.set_tooltip_text(f"Kluis: {text}")
        elif self.kind == "windows":
            if (state, text) != getattr(self, "_win_shown", None):
                self._win_shown = (state, text)
                self._set_windows_icon(state, f"Kluis: {text}")
        else:
            self.icon.set_icon_full(_icon(state), text)

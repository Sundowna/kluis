"""Panel icon. Linux Mint (Cinnamon/MATE/Xfce) uses XApp.StatusIcon; elsewhere Ayatana AppIndicator."""
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
        self.pause_item.connect("activate", lambda *_: app.manager.set_paused(not app.settings.paused))
        self.menu.append(self.pause_item)
        self.menu.append(Gtk.SeparatorMenuItem())
        open_item = Gtk.MenuItem(label="Open Kluis")
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
        try:
            gi.require_version("XApp", "1.0")
            from gi.repository import XApp
            self.icon = XApp.StatusIcon()
            self.icon.set_name("kluis")
            self.icon.set_icon_name(_icon("idle"))
            self.icon.set_tooltip_text("Kluis")
            self.icon.set_secondary_menu(self.menu)
            self.icon.connect("activate", self._xapp_activate)
            self.icon.set_visible(True)
            self.kind = "xapp"
            return
        except (ValueError, ImportError) as e:
            log.info("XApp status icon not available: %s", e)
        for ns in ("AyatanaAppIndicator3", "AppIndicator3"):
            try:
                gi.require_version(ns, "0.1")
                mod = __import__("gi.repository." + ns, fromlist=[ns])
                ind = mod.Indicator.new("kluis", _icon("idle"), mod.IndicatorCategory.APPLICATION_STATUS)
                ind.set_status(mod.IndicatorStatus.ACTIVE)
                ind.set_menu(self.menu)
                ind.set_title("Kluis")
                self.icon, self.kind = ind, "indicator"
                return
            except (ValueError, ImportError) as e:
                log.info("%s not available: %s", ns, e)
        self.icon = None

    @property
    def available(self) -> bool:
        return self.icon is not None

    def _xapp_activate(self, _icon, button, _time):
        if button == 1:
            self.app.toggle_window()

    def update(self, state: str, text: str):
        """state: idle | sync | error | paused"""
        self.status_item.set_label(text)
        self.pause_item.set_label("Resume syncing" if self.app.settings.paused else "Pause syncing")
        if not self.icon:
            return
        if self.kind == "xapp":
            self.icon.set_icon_name(_icon(state))
            self.icon.set_tooltip_text(f"Kluis: {text}")
        else:
            self.icon.set_icon_full(_icon(state), text)

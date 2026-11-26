"""Theme: kit CSS (dark/light) + app layout CSS, System/Light/Dark (HANDOVER §2, §5).

"System" follows the desktop's preference: the freedesktop portal setting
org.freedesktop.appearance color-scheme (KDE Plasma, GNOME, Cinnamon), else the GTK theme name.
"""
from __future__ import annotations

import logging
import os
import re

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
log = logging.getLogger("kluis.theme")


class Theme:
    def __init__(self):
        self.provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self.provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.choice = "system"
        self.accent = "green"
        self.dark = True
        self.listeners = []
        self._portal_dark = None
        try:
            self._portal = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, None, "org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop", "org.freedesktop.portal.Settings", None)
            v = self._portal.call_sync("Read", GLib.Variant("(ss)", ("org.freedesktop.appearance", "color-scheme")),
                                       Gio.DBusCallFlags.NONE, 1500, None)
            val = v.unpack()[0]
            while isinstance(val, GLib.Variant):
                val = val.unpack()
            self._portal_dark = {1: True, 2: False}.get(val)
            self._portal.connect("g-signal", self._portal_signal)
        except (GLib.Error, TypeError):
            self._portal = None

    def _portal_signal(self, _p, _sender, signal, params):
        if signal != "SettingChanged":
            return
        ns, key, val = params.unpack()
        if ns == "org.freedesktop.appearance" and key == "color-scheme":
            self._portal_dark = {1: True, 2: False}.get(val)
            if self.choice == "system":
                self.apply(self.choice)

    def system_dark(self) -> bool:
        if os.environ.get("KLUIS_TEST_THEME") in ("dark", "light"):
            return os.environ["KLUIS_TEST_THEME"] == "dark"
        if self._portal_dark is not None:
            return self._portal_dark
        name = (Gtk.Settings.get_default().get_property("gtk-theme-name") or "").lower()
        return "dark" in name

    def apply(self, choice: str, accent: str | None = None):
        self.choice = choice
        if accent:
            self.accent = accent
        dark = self.system_dark() if choice == "system" else choice == "dark"
        self.dark = dark
        mode = "dark" if dark else "light"
        css = open(os.path.join(DATA, f"kluis-{mode}.css"), encoding="utf-8").read()
        for name, value in ACCENTS.get(self.accent, {}).get(mode, {}).items():
            css = re.sub(rf"@define-color k_{name} #[0-9a-fA-F]{{6}};", f"@define-color k_{name} {value};", css)
        css += "\n" + open(os.path.join(DATA, "app.css"), encoding="utf-8").read()
        self.provider.load_from_data(css.encode())
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", dark)
        for cb in list(self.listeners):
            cb(dark)

    def color(self, name: str) -> tuple[float, float, float]:
        """Token colour as RGB floats for Cairo drawing (§5 table)."""
        mode = "dark" if self.dark else "light"
        hexv = ACCENTS.get(self.accent, {}).get(mode, {}).get(name) or TOKENS[mode][name]
        return tuple(int(hexv[i:i + 2], 16) / 255 for i in (1, 3, 5))


TOKENS = {
    "dark": {"bg": "#262530", "panel": "#1f1e28", "surface": "#32313e", "line": "#4d4b59", "text": "#eeedf5",
             "muted": "#bdbcca", "mapdot": "#575665", "accent": "#5ed8a9", "accent_soft": "#1a533e",
             "on_accent": "#0c1f17", "upload": "#f49191", "warn": "#f0ba59", "error": "#f7857d"},
    "light": {"bg": "#f0eff7", "panel": "#faf9fe", "surface": "#ebeaf3", "line": "#d4d3de", "text": "#24222d",
              "muted": "#555460", "mapdot": "#bdbcca", "accent": "#00704e", "accent_soft": "#c3ecd9",
              "on_accent": "#fcfcfc", "upload": "#af3b43", "warn": "#a16100", "error": "#b63132"},
}


# Accent colours other than the kit's green. Purple: Proton's own #6d4aff (light) and a lighter shade
# that stays readable on the dark background. Contrast is unit-tested like the green.
ACCENTS = {
    "purple": {
        "dark": {"accent": "#9b7dff", "accent_soft": "#3a2d70", "on_accent": "#160b38"},
        "light": {"accent": "#6d4aff", "accent_soft": "#e2dcff", "on_accent": "#ffffff"},
    },
}


def animations_enabled() -> bool:
    """§4.6: all motion off when the desktop turns animations off."""
    try:
        return bool(Gtk.Settings.get_default().get_property("gtk-enable-animations"))
    except TypeError:
        return True

"""Read-only VPN state from NetworkManager over D-Bus (HANDOVER §2). No network calls.

Watches active connections; any active connection of type vpn or wireguard counts as "VPN on".
The country comes from the connection name (e.g. "ProtonVPN CH#23"); see geo.country_from_connection.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from gi.repository import Gio, GLib

from . import geo

log = logging.getLogger("kluis.vpn")
NM = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"
VPN_TYPES = ("vpn", "wireguard")


@dataclass
class VpnState:
    on: bool = False
    name: str = ""
    country: str = ""


def _prop(bus, path, iface, name):
    try:
        v = bus.call_sync(NM, path, "org.freedesktop.DBus.Properties", "Get",
                          GLib.Variant("(ss)", (iface, name)), GLib.VariantType("(v)"),
                          Gio.DBusCallFlags.NONE, 2000, None)
        return v.unpack()[0]
    except GLib.Error:
        return None


def read_state(bus=None) -> VpnState:
    if os.environ.get("KLUIS_TEST_VPN") is not None:          # tests: "" = off, "ProtonVPN CH#23" = on
        name = os.environ["KLUIS_TEST_VPN"]
        return VpnState(bool(name), name, geo.country_from_connection(name) or "")
    try:
        bus = bus or Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    except GLib.Error:
        return VpnState()
    active = _prop(bus, NM_PATH, NM, "ActiveConnections") or []
    for path in active:
        ctype = _prop(bus, path, NM + ".Connection.Active", "Type") or ""
        if ctype in VPN_TYPES:
            name = _prop(bus, path, NM + ".Connection.Active", "Id") or ""
            return VpnState(True, name, geo.country_from_connection(name) or "")
    return VpnState()


class VpnWatcher:
    """Calls on_change(VpnState) on the GTK thread when NetworkManager's active connections change."""

    def __init__(self, on_change):
        self.on_change = on_change
        self.state = VpnState()
        self._bus = None
        self._sub = 0
        try:
            if os.environ.get("KLUIS_TEST_VPN") is None:
                self._bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
                self._sub = self._bus.signal_subscribe(NM, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                                       None, None, Gio.DBusSignalFlags.NONE, self._changed)
        except GLib.Error as e:
            log.info("NetworkManager not reachable: %s", e)
        self.refresh()
        GLib.timeout_add_seconds(2, self._poll)    # belt and braces: catch missed signals within 2 s

    def _changed(self, *_a):
        GLib.idle_add(lambda: (self.refresh(), False)[1])

    def _poll(self):
        self.refresh()
        return True

    def refresh(self):
        st = read_state(self._bus)
        if st != self.state:
            self.state = st
            self.on_change(st)

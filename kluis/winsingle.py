"""One Kluis per Windows user (on Linux, GApplication does this over D-Bus).

The first Kluis owns a named mutex and waits on a named event. A second start finds the mutex, sets the
event (the first Kluis then shows its window) and ends. Names are per sign-in session ("Local\\").
Tests use their own names (KLUIS_TEST_INSTANCE), so a test run never meets a real Kluis.
"""
from __future__ import annotations

import ctypes
import logging
import os
import threading
from ctypes import wintypes

log = logging.getLogger("kluis.winsingle")
ERROR_ALREADY_EXISTS = 183
EVENT_MODIFY_STATE = 0x0002
WAIT_OBJECT_0 = 0

_k32 = None
_mutex = None


def _names():
    tag = os.environ.get("KLUIS_TEST_INSTANCE", "") if os.environ.get("KLUIS_TEST") == "1" else ""
    base = "Local\\dev.kluis.Kluis" + (f".test.{tag}" if tag else "")
    return base + ".instance", base + ".show"


def _api():
    global _k32
    if _k32 is None:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateMutexW.restype = wintypes.HANDLE
        k.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        k.CreateEventW.restype = wintypes.HANDLE
        k.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        k.OpenEventW.restype = wintypes.HANDLE
        k.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        k.SetEvent.argtypes = [wintypes.HANDLE]
        k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        _k32 = k
    return _k32


def already_running() -> bool:
    """True (after asking the running Kluis to show itself) when another Kluis runs for this user."""
    global _mutex
    k = _api()
    mutex_name, event_name = _names()
    h = k.CreateMutexW(None, False, mutex_name)
    if not h:
        log.warning("single instance check failed: %s", ctypes.get_last_error())
        return False
    if ctypes.get_last_error() != ERROR_ALREADY_EXISTS:
        _mutex = h                       # kept open until Kluis ends; Windows releases it even after a crash
        return False
    k.CloseHandle(h)
    ev = k.OpenEventW(EVENT_MODIFY_STATE, False, event_name)
    if ev:
        k.SetEvent(ev)
        k.CloseHandle(ev)
    return True


def listen(on_show):
    """Calls on_show() (from a background thread) each time another start asks Kluis to show itself."""
    k = _api()
    _, event_name = _names()
    ev = k.CreateEventW(None, False, False, event_name)       # auto-reset
    if not ev:
        log.warning("could not listen for a second start: %s", ctypes.get_last_error())
        return

    def wait():
        while True:
            if k.WaitForSingleObject(ev, 0xFFFFFFFF) == WAIT_OBJECT_0:
                try:
                    on_show()
                except Exception:  # noqa: BLE001
                    log.exception("showing Kluis for a second start failed")
            else:
                return
    threading.Thread(target=wait, daemon=True, name="kluis-second-start").start()

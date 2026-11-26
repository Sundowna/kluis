"""Windows: paint the title bar (the strip with minimise, maximise and close) in Kluis's own colours.

Windows draws that bar itself, white by default, above GTK's content. The Desktop Window Manager lets an
app choose its colour: Windows 11 takes any colour (the bar then flows into the green glow at the top of
Kluis's window), Windows 10 only light or dark.
"""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

log = logging.getLogger("kluis.wintitle")

DWMWA_USE_IMMERSIVE_DARK_MODE = 20      # Windows 10 2004 and later (19 before that)
DWMWA_BORDER_COLOR = 34                 # Windows 11
DWMWA_CAPTION_COLOR = 35
DWMWA_TEXT_COLOR = 36

_dwm = ctypes.WinDLL("dwmapi")
_dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
_dwm.DwmSetWindowAttribute.restype = ctypes.c_long
_capsule = ctypes.pythonapi.PyCapsule_GetPointer
_capsule.restype = ctypes.c_void_p
_capsule.argtypes = [ctypes.py_object, ctypes.c_char_p]
try:
    _gdk = ctypes.CDLL("libgdk-3-0.dll")
    _gdk.gdk_win32_window_get_handle.restype = ctypes.c_void_p
    _gdk.gdk_win32_window_get_handle.argtypes = [ctypes.c_void_p]
except (OSError, AttributeError):
    _gdk = None


def hwnd_of(gtk_window) -> int | None:
    """The Windows handle (HWND) behind a realized Gtk.Window."""
    gdk_window = gtk_window.get_window()
    if gdk_window is None or _gdk is None:
        return None
    return _gdk.gdk_win32_window_get_handle(_capsule(gdk_window.__gpointer__, None)) or None


def _colorref(hexv: str) -> wintypes.DWORD:
    r, g, b = (int(hexv[i:i + 2], 16) for i in (1, 3, 5))
    return wintypes.DWORD(r | g << 8 | b << 16)


def _set(hwnd, attr, value) -> bool:
    return _dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0


def style(gtk_window, caption: str, text: str, dark: bool) -> bool:
    """Colours the title bar of gtk_window. Returns True when Windows took the exact colour (Windows 11)."""
    hwnd = hwnd_of(gtk_window)
    if not hwnd:
        return False
    flag = wintypes.BOOL(dark)
    if not _set(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, flag):
        _set(hwnd, 19, flag)
    exact = _set(hwnd, DWMWA_CAPTION_COLOR, _colorref(caption))
    if exact:
        _set(hwnd, DWMWA_TEXT_COLOR, _colorref(text))
        _set(hwnd, DWMWA_BORDER_COLOR, _colorref(caption))
    return exact

"""Windows notification-area icon (the "tray"), with Kluis's menu and Windows notifications.

The same icon, menu and states as on Linux. Built on Shell_NotifyIconW with a hidden window of its own;
GTK's main loop already dispatches every Windows message of this thread, so no extra loop is needed.
Notifications are the icon's balloons, which Windows 10/11 shows as normal notifications; a click on one
opens Kluis, like the Linux notification's default action.
"""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

log = logging.getLogger("kluis.wintray")

WM_USER = 0x0400
WM_TRAY = WM_USER + 20
WM_COMMAND = 0x0111
WM_DESTROY = 0x0002
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B
NIN_SELECT = WM_USER
NIN_KEYSELECT = WM_USER + 1
NIN_BALLOONUSERCLICK = WM_USER + 5
NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETVERSION = 0, 1, 2, 4
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO, NIF_SHOWTIP = 0x1, 0x2, 0x4, 0x10, 0x80
NIIF_INFO, NIIF_WARNING, NIIF_NOSOUND = 0x1, 0x2, 0x10
MF_STRING, MF_GRAYED, MF_SEPARATOR = 0x0, 0x1, 0x800
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD), ("guidItem", GUID), ("hBalloonIcon", wintypes.HICON)]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR)]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


def _api():
    u, s, k = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("shell32"), ctypes.WinDLL("kernel32")
    u.DefWindowProcW.restype = LRESULT
    u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    u.CreateWindowExW.restype = wintypes.HWND
    u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                  wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    u.RegisterWindowMessageW.restype = wintypes.UINT
    u.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
    u.CreatePopupMenu.restype = wintypes.HMENU
    u.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
    u.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                 wintypes.HWND, ctypes.c_void_p]
    u.DestroyMenu.argtypes = [wintypes.HMENU]
    u.SetForegroundWindow.argtypes = [wintypes.HWND]
    u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.SendMessageW.restype = LRESULT
    u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u.DestroyWindow.argtypes = [wintypes.HWND]
    u.DestroyIcon.argtypes = [wintypes.HICON]
    u.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    u.CreateIconFromResourceEx.restype = wintypes.HICON
    u.CreateIconFromResourceEx.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD,
                                           ctypes.c_int, ctypes.c_int, wintypes.UINT]
    s.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    k.GetModuleHandleW.restype = wintypes.HMODULE
    k.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    return u, s, k


def icon_from_svg(path: str, size: int) -> int:
    """An HICON from one of Kluis's SVG tray icons (rendered by GdkPixbuf, handed to Windows as PNG)."""
    from gi.repository import GdkPixbuf
    pb = GdkPixbuf.Pixbuf.new_from_file_at_size(path, size, size)
    ok, data = pb.save_to_bufferv("png", [], [])
    if not ok:
        return 0
    u, _s, _k = _api()
    buf = ctypes.create_string_buffer(bytes(data), len(data))
    return u.CreateIconFromResourceEx(buf, len(data), True, 0x00030000, size, size, 0) or 0


_ICONS: dict = {}          # hwnd -> WinTrayIcon


def _dispatch(hwnd, msg, wparam, lparam):
    icon = _ICONS.get(hwnd)
    if icon is not None:
        return icon._wndproc(hwnd, msg, wparam, lparam)
    u = ctypes.WinDLL("user32")
    u.DefWindowProcW.restype = LRESULT
    u.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    return u.DefWindowProcW(hwnd, msg, wparam, lparam)


_PROC = WNDPROC(_dispatch)  # one window procedure for the process lifetime (Windows keeps calling it)


class WinTrayIcon:
    """Low-level icon: add/update/remove, menu, balloons. Kluis's Tray (kluis/tray.py) drives it."""
    _class_registered = False

    def __init__(self, on_left_click, build_menu, on_balloon_click, tooltip="Kluis"):
        self.u, self.s, self.k = _api()
        self.on_left_click, self.build_menu, self.on_balloon_click = on_left_click, build_menu, on_balloon_click
        self.hinst = self.k.GetModuleHandleW(None)
        self.class_name = "KluisTrayWindow"
        wc = WNDCLASSW()
        wc.lpfnWndProc = _PROC
        wc.hInstance = self.hinst
        wc.lpszClassName = self.class_name
        if not WinTrayIcon._class_registered:
            if not self.u.RegisterClassW(ctypes.byref(wc)) and ctypes.get_last_error() != 1410:  # already exists
                raise OSError(ctypes.get_last_error(), "RegisterClassW")
            WinTrayIcon._class_registered = True
        self.hwnd = self.u.CreateWindowExW(0, self.class_name, "Kluis", 0, 0, 0, 0, 0, None, None, self.hinst, None)
        if not self.hwnd:
            raise OSError(ctypes.get_last_error(), "CreateWindowExW")
        _ICONS[self.hwnd] = self
        self.taskbar_created = self.u.RegisterWindowMessageW("TaskbarCreated")
        self.hicon = 0
        self.tooltip = tooltip
        self.menu_actions: dict[int, object] = {}
        self.added = False
        self._add()

    def _data(self, flags=0):
        d = NOTIFYICONDATAW()
        d.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        d.hWnd, d.uID = self.hwnd, 1
        d.uFlags = flags
        return d

    def _add(self):
        d = self._data(NIF_MESSAGE | NIF_TIP | NIF_SHOWTIP | (NIF_ICON if self.hicon else 0))
        d.uCallbackMessage = WM_TRAY
        d.hIcon = self.hicon
        d.szTip = self.tooltip[:127]
        self.added = bool(self.s.Shell_NotifyIconW(NIM_ADD, ctypes.byref(d)))
        d.uVersion = 4                                     # NOTIFYICON_VERSION_4
        self.s.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(d))
        return self.added

    def set_icon(self, hicon: int, tooltip: str | None = None):
        old, self.hicon = self.hicon, hicon
        if tooltip is not None:
            self.tooltip = tooltip
        d = self._data(NIF_ICON | NIF_TIP | NIF_SHOWTIP)
        d.hIcon = hicon
        d.szTip = self.tooltip[:127]
        if not self.s.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(d)) and not self.added:
            self._add()
        if old and old != hicon:
            self.u.DestroyIcon(old)

    def balloon(self, title: str, body: str, warning: bool = False) -> bool:
        d = self._data(NIF_INFO)
        d.szInfoTitle = (title or "")[:63]
        d.szInfo = (body or " ")[:255]
        d.dwInfoFlags = (NIIF_WARNING if warning else NIIF_INFO)
        return bool(self.s.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(d)))

    def popup_menu(self):
        items = self.build_menu()            # [(label, callback or None = disabled)] or None = separator
        menu = self.u.CreatePopupMenu()
        self.menu_actions = {}
        for i, it in enumerate(items, start=1):
            if it is None:
                self.u.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                continue
            text, cb = it
            self.u.AppendMenuW(menu, MF_STRING | (0 if cb else MF_GRAYED), i, text)
            self.menu_actions[i] = cb
        pt = POINT()
        self.u.GetCursorPos(ctypes.byref(pt))
        self.u.SetForegroundWindow(self.hwnd)               # so the menu closes when clicking elsewhere
        cmd = self.u.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY, pt.x, pt.y, 0,
                                    self.hwnd, None)
        self.u.PostMessageW(self.hwnd, 0, 0, 0)            # WM_NULL: Windows' documented menu fix
        self.u.DestroyMenu(menu)
        self.run_menu_item(cmd)

    def run_menu_item(self, cmd):
        cb = self.menu_actions.get(cmd)
        if cb:
            from gi.repository import GLib
            GLib.idle_add(lambda: (cb(), False)[1])

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAY:
                event = lparam & 0xFFFF                     # NOTIFYICON_VERSION_4: event in LOWORD
                if event in (NIN_SELECT, NIN_KEYSELECT, WM_LBUTTONUP):
                    self.on_left_click()
                elif event in (WM_CONTEXTMENU, WM_RBUTTONUP):
                    self.popup_menu()
                elif event == NIN_BALLOONUSERCLICK:
                    self.on_balloon_click()
                return 0
            if msg == self.taskbar_created and msg:          # Explorer restarted: the icon must be added again
                self._add()
                return 0
        except Exception:  # noqa: BLE001 - an exception must never cross into Windows
            log.exception("tray message %s failed", msg)
            return 0
        return self.u.DefWindowProcW(hwnd, msg, wparam, lparam)

    def close(self):
        if self.added:
            d = self._data()
            self.s.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(d))
            self.added = False
        if self.hicon:
            self.u.DestroyIcon(self.hicon)
            self.hicon = 0
        if self.hwnd:
            self.u.DestroyWindow(self.hwnd)
            _ICONS.pop(self.hwnd, None)
            self.hwnd = None

"""Windows: notices changes in a whole synced folder with one handle (ReadDirectoryChangesW, subtree on).

On Linux Kluis watches each subfolder with Gio (inotify). On Windows that would keep a handle open in every
subfolder, and Windows refuses to rename or move a folder while a handle inside it is open ("The action can't
be completed because the folder is open in another program"). One handle on the synced folder itself, opened
with delete sharing, leaves the user free to rename and move everything inside it, like with OneDrive.
"""
from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes

log = logging.getLogger("kluis.winwatch")

FILE_LIST_DIRECTORY = 0x0001
SHARE_ALL = 0x1 | 0x2 | 0x4
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
INVALID_HANDLE = ctypes.c_void_p(-1).value
NOTIFY = 0x1 | 0x2 | 0x8 | 0x10 | 0x40     # file name, dir name, size, last write, creation
THREAD_TERMINATE = 0x0001
ACTIONS = {1: "created", 2: "deleted", 3: "changed", 4: "moved-from", 5: "moved-to"}

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.restype = wintypes.HANDLE
_k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                             wintypes.DWORD, wintypes.HANDLE]
_k32.ReadDirectoryChangesW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, wintypes.BOOL,
                                       wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
                                       ctypes.c_void_p]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.OpenThread.restype = wintypes.HANDLE
_k32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k32.CancelSynchronousIo.argtypes = [wintypes.HANDLE]


class TreeWatcher:
    """Calls on_change(rel_path, action) from a background thread for every change below `root`
    (rel_path uses "/"; "" when Windows lost track and the whole folder should be looked at)."""

    def __init__(self, root: str, on_change):
        self.root, self.on_change = root, on_change
        self._stop = False
        self._tid = 0
        self.handle = _k32.CreateFileW(root, FILE_LIST_DIRECTORY, SHARE_ALL, None, OPEN_EXISTING,
                                       FILE_FLAG_BACKUP_SEMANTICS, None)
        if not self.handle or self.handle == INVALID_HANDLE:
            raise OSError(ctypes.get_last_error(), f"can't watch {root}")
        self._ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name="kluis-watch")
        self.thread.start()
        self._ready.wait(2)

    def _run(self):
        self._tid = threading.get_native_id()
        self._ready.set()
        buf = ctypes.create_string_buffer(64 * 1024)
        got = wintypes.DWORD()
        while not self._stop:
            ok = _k32.ReadDirectoryChangesW(self.handle, buf, len(buf), True, NOTIFY, ctypes.byref(got), None, None)
            if self._stop:
                return
            if not ok:
                err = ctypes.get_last_error()
                if err in (995, 6):              # cancelled / handle closed: stopping
                    return
                log.warning("watching %s stopped: %s", self.root, err)
                return
            if got.value == 0:                    # more changes than the buffer holds: look at everything
                self._emit("", "overflow")
                continue
            off = 0
            raw = buf.raw[:got.value]
            while True:
                nxt, action, length = int.from_bytes(raw[off:off + 4], "little"), \
                    int.from_bytes(raw[off + 4:off + 8], "little"), int.from_bytes(raw[off + 8:off + 12], "little")
                name = raw[off + 12:off + 12 + length].decode("utf-16-le", "replace").replace("\\", "/")
                self._emit(name, ACTIONS.get(action, "changed"))
                if not nxt:
                    break
                off += nxt

    def _emit(self, rel, action):
        try:
            self.on_change(rel, action)
        except Exception:  # noqa: BLE001
            log.exception("change handler failed")

    def cancel(self):
        if self._stop:
            return
        self._stop = True
        th = _k32.OpenThread(THREAD_TERMINATE, False, self._tid) if self._tid else None
        try:
            for _i in range(40):                  # the thread may be between two reads: try until it ends
                if th:
                    _k32.CancelSynchronousIo(th)
                self.thread.join(0.05)
                if not self.thread.is_alive():
                    break
        finally:
            if th:
                _k32.CloseHandle(th)
        _k32.CloseHandle(self.handle)

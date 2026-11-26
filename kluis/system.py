"""What differs between Linux and Windows, in one place (the Windows port, Kluis 1.2).

Everything else in Kluis is the same code on both systems. Linux behaviour here is exactly what Kluis
did before; the Windows branches are new.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys

log = logging.getLogger("kluis.system")

IS_WINDOWS = os.name == "nt"


# ---------------------------------------------------------------- paths on this computer
def path_key(path: str) -> str:
    """A form of a local path for comparing: real path, the system's separator, and on Windows
    case-insensitive (C:\\Users\\Walter\\Docs and c:/users/walter/docs are the same folder)."""
    p = os.path.realpath(path)
    # MSYS2's Python writes "/" where Windows writes "\\": compare in one spelling
    return os.path.normcase(p).replace("/", "\\") if IS_WINDOWS else p


def is_inside(child: str, parent: str) -> bool:
    """True when `child` is `parent` itself or anywhere under it (both compared with path_key)."""
    c, p = path_key(child), path_key(parent)
    if c == p:
        return True
    sep = "\\" if IS_WINDOWS else "/"
    return c.startswith(p.rstrip(sep) + sep)


def is_strictly_inside(child: str, parent: str) -> bool:
    return is_inside(child, parent) and path_key(child) != path_key(parent)


def is_system_root(path: str) -> bool:
    """"/" on Linux; a drive root (C:\\, D:\\) or a share root (\\\\server\\share) on Windows."""
    real = os.path.realpath(path)
    if not IS_WINDOWS:
        return real == "/"
    drive, rest = os.path.splitdrive(real)
    return bool(drive) and rest.strip("\\/") == ""


# ---------------------------------------------------------------- names Windows can't store
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10)),
             "COM¹", "COM²", "COM³", "LPT¹", "LPT²", "LPT³", "CONIN$", "CONOUT$"}
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def windows_name_problem(name: str) -> str | None:
    """Why a file or folder name from Proton Drive can't exist on Windows, or None.

    Linux and macOS allow names Windows refuses (a:b.txt, "notes.", CON.txt). Such an item is left alone:
    it is never downloaded under another name and never deleted anywhere."""
    if not name:
        return "it has no name"
    bad = sorted(set(_ILLEGAL.findall(name)))
    if bad:
        shown = " ".join("control characters" if ord(c) < 32 else c for c in bad)
        return f"Windows doesn't allow {shown} in names"
    if name[-1] in ". ":
        return "Windows doesn't allow names that end with a dot or a space"
    if name.split(".")[0].rstrip(" ").upper() in _RESERVED:
        return f"{name.split('.')[0]} is a name Windows reserves"
    return None


# ---------------------------------------------------------------- child processes (the Proton CLI)
def _die_with_kluis():
    """Linux, child side: if Kluis ends for any reason (Quit, crash, force quit), the kernel stops the CLI
    too. Found on a test laptop: a force-quit Kluis left a CLI download of 4 GB running."""
    try:
        import ctypes
        import signal
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)    # PR_SET_PDEATHSIG
    except Exception:  # noqa: BLE001  (not Linux/glibc: nothing to do)
        pass


_JOB = None


def _kill_on_close_job():
    """Windows: one Job Object for all CLI processes, closed by Windows when Kluis ends in any way; then
    Windows ends every process in it. Processes the CLI starts itself (a browser for sign-in) may leave it."""
    global _JOB
    if _JOB is not None:
        return _JOB or None
    _JOB = 0
    try:
        import ctypes
        from ctypes import wintypes

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount",
                                                          "OtherOperationCount", "ReadTransferCount",
                                                          "WriteTransferCount", "OtherTransferCount")]

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class EXTENDED(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        job = k32.CreateJobObjectW(None, None)
        if not job:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW")
        info = EXTENDED()
        # KILL_ON_JOB_CLOSE | SILENT_BREAKAWAY_OK (the CLI's own children, like a browser, are not ended)
        info.BasicLimitInformation.LimitFlags = 0x2000 | 0x1000
        if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError(ctypes.get_last_error(), "SetInformationJobObject")
        _JOB = job
    except Exception as e:  # noqa: BLE001
        log.warning("could not set up ending CLI processes with Kluis: %s", e)
    return _JOB or None


def popen_kwargs() -> dict:
    """Extra arguments for every subprocess Kluis starts: no console window flashing up on Windows."""
    if IS_WINDOWS:
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


def cli_popen_kwargs() -> dict:
    """popen_kwargs() plus, on Linux, ending the CLI with Kluis (Windows: see bind_to_kluis)."""
    if IS_WINDOWS:
        return popen_kwargs()
    return {"preexec_fn": _die_with_kluis}


def bind_to_kluis(proc: subprocess.Popen):
    """Windows: put a CLI process into the kill-on-close job right after it started."""
    if not IS_WINDOWS:
        return
    job = _kill_on_close_job()
    if not job:
        return
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        if not k32.AssignProcessToJobObject(job, int(proc._handle)):
            log.warning("could not tie CLI process %s to Kluis: %s", proc.pid, ctypes.get_last_error())
    except Exception as e:  # noqa: BLE001
        log.warning("could not tie CLI process %s to Kluis: %s", proc.pid, e)


def command_for(binary: str) -> list[str]:
    """How to start a program file. On Windows a script (the test suites' mock CLI) can't run by itself:
    it runs with this Python. Real programs (proton-drive.exe) start directly."""
    if IS_WINDOWS and not getattr(sys, "frozen", False):
        try:
            with open(binary, "rb") as fh:
                head = fh.read(64)
        except OSError:
            head = b""
        if head.startswith(b"#!") and b"python" in head.split(b"\n")[0]:
            return [sys.executable, binary]
    return [binary]


def pid_alive(pid: int) -> bool:
    if IS_WINDOWS:
        import ctypes
        k32 = ctypes.WinDLL("kernel32")
        h = k32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            k32.GetExitCodeProcess(h, ctypes.byref(code))
            return code.value == 259                    # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        return "Z" not in open(f"/proc/{pid}/status").read().split("State:")[1].split()[0]
    except OSError:
        return False


# ---------------------------------------------------------------- the trash / Recycle Bin
class TrashUnavailable(OSError):
    pass


def move_to_trash(path: str):
    """Linux: the freedesktop Trash via Gio (what Nemo and Dolphin use). Windows: the Recycle Bin.

    Never deletes: on Windows a drive without a Recycle Bin (USB stick, network share) is refused, because
    Windows would delete the file there for good."""
    if IS_WINDOWS:
        return _recycle(path)
    try:
        from gi.repository import Gio
        Gio.File.new_for_path(path).trash(None)
    except ImportError:
        subprocess.run(["gio", "trash", path], check=True)


def _recycle(path: str):
    import ctypes
    from ctypes import wintypes
    full = os.path.abspath(path).replace("/", "\\")
    if not os.path.lexists(full):
        raise FileNotFoundError(2, "No such file or folder", full)
    root = os.path.splitdrive(full)[0] + "\\"
    k32 = ctypes.WinDLL("kernel32")
    k32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    if k32.GetDriveTypeW(root) != 3:                       # DRIVE_FIXED: the only kind with a Recycle Bin
        raise TrashUnavailable(f"{root} has no Recycle Bin, so Kluis left {os.path.basename(full)} in place")

    class SHQUERYRBINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("i64Size", ctypes.c_longlong), ("i64NumItems", ctypes.c_longlong)]
    shell32 = ctypes.WinDLL("shell32")
    q = SHQUERYRBINFO(ctypes.sizeof(SHQUERYRBINFO))
    shell32.SHQueryRecycleBinW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p]
    if shell32.SHQueryRecycleBinW(root, ctypes.byref(q)) != 0:
        raise TrashUnavailable(f"The Recycle Bin on {root} is turned off, so Kluis left "
                               f"{os.path.basename(full)} in place")

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
    FO_DELETE = 3
    # ALLOWUNDO = Recycle Bin; NOCONFIRMATION | NOERRORUI | SILENT = no dialogs during a background sync;
    # WANTNUKEWARNING = if Windows would delete for good after all, it asks instead of deleting silently.
    flags = 0x0040 | 0x0010 | 0x0400 | 0x0004 | 0x4000
    op = SHFILEOPSTRUCTW(None, FO_DELETE, full + "\0", None, flags, False, None, None)
    shell32.SHFileOperationW.argtypes = [ctypes.c_void_p]
    rc = shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0 or op.fAnyOperationsAborted:
        raise OSError(f"Windows could not move {os.path.basename(full)} to the Recycle Bin (code {rc})")
    if os.path.lexists(full):
        raise OSError(f"{os.path.basename(full)} is still in place after moving it to the Recycle Bin")


# ---------------------------------------------------------------- opening files and web pages
def open_with_system(target: str) -> bool:
    """Windows: the default program for a file, folder or URL (like a double-click). False elsewhere."""
    if not IS_WINDOWS:
        return False
    os.startfile(target)        # noqa: S606 - the user's own file or a Proton URL
    return True


# ---------------------------------------------------------------- start at sign-in
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "Kluis"


def kluis_command() -> str:
    """The command line that starts this Kluis on Windows (the installed Kluis.exe, or Python + module)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pyw):
        exe = pyw
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return f'"{exe}" -c "import sys; sys.path.insert(0, r\'{root}\'); from kluis.__main__ import main; main()"'


def set_autostart_windows(enabled: bool, hidden: bool):
    """HKCU\\…\\Run\\Kluis, the same place Windows' Settings → Apps → Startup lists and switches off.
    Tests point it at their own registry key (KLUIS_TEST_RUN_KEY)."""
    import winreg
    key = os.environ.get("KLUIS_TEST_RUN_KEY") if os.environ.get("KLUIS_TEST") == "1" else None
    key = key or RUN_KEY
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, kluis_command() + (" --hidden" if hidden else ""))
        else:
            try:
                winreg.DeleteValue(k, RUN_VALUE)
            except FileNotFoundError:
                pass


def autostart_windows() -> str | None:
    import winreg
    key = os.environ.get("KLUIS_TEST_RUN_KEY") if os.environ.get("KLUIS_TEST") == "1" else None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key or RUN_KEY) as k:
            return winreg.QueryValueEx(k, RUN_VALUE)[0]
    except OSError:
        return None


# ---------------------------------------------------------------- the time zone
def windows_timezone() -> str:
    """The IANA name ("Europe/Zurich") of Windows' time zone, from the ICU that ships with Windows 10/11."""
    if not IS_WINDOWS:
        return ""
    try:
        import ctypes
        icu = ctypes.WinDLL("icu")
        buf = ctypes.create_unicode_buffer(128)
        status = ctypes.c_int(0)
        n = icu.ucal_getDefaultTimeZone(buf, 128, ctypes.byref(status))
        return buf.value[:n] if status.value <= 0 and n > 0 else ""
    except (OSError, AttributeError):
        return ""


def os_name() -> str:
    """"Windows 11 Pro (26200)" and the like; "" when not on Windows."""
    if not IS_WINDOWS:
        return ""
    import platform
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as k:
            name = winreg.QueryValueEx(k, "ProductName")[0]
            build = winreg.QueryValueEx(k, "CurrentBuildNumber")[0]
        if int(build) >= 22000:                      # Windows 11 still calls itself "Windows 10" here
            name = name.replace("Windows 10", "Windows 11")
        return f"{name} ({build})"
    except (OSError, ValueError):
        return f"Windows {platform.release()} ({platform.version()})"

"""Shared setup for the script-style test suites: isolated XDG dirs and mock cloud inside ~/.cache
(same drive as the home Trash, like real synced folders)."""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
MOCK = os.path.join(HERE, "mock_cli", "proton-drive")


def setup(prefix="kluis-test-"):
    base = os.path.join(os.path.expanduser("~"), ".cache")
    os.makedirs(base, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=prefix, dir=base)
    os.environ["XDG_CONFIG_HOME"] = os.path.join(tmp, "config")
    os.environ["XDG_DATA_HOME"] = os.path.join(tmp, "data")
    os.environ["XDG_STATE_HOME"] = os.path.join(tmp, "state")
    os.environ["XDG_CACHE_HOME"] = os.path.join(tmp, "cache")
    os.environ["MOCK_ROOT"] = os.path.join(tmp, "cloud")
    os.environ["KLUIS_TEST"] = "1"
    # Proton accounts (kluis/accounts.py): kept sessions in files; the mock CLI's session file is its keyring slot
    os.environ["KLUIS_TEST_VAULT"] = os.path.join(tmp, "vault")
    os.environ["KLUIS_TEST_VAULT_SLOT"] = os.path.join(tmp, "cloud", ".logged_in")
    os.environ.pop("PROTON_DRIVE_CACHE_DIR", None)
    for k in ("MOCK_DELAY", "MOCK_BAD_SHA1", "MOCK_DOWNLOAD_DELAY", "MOCK_UPLOAD_DELAY", "MOCK_INCOMPATIBLE",
              "MOCK_SLOW_DELAY"):
        os.environ.pop(k, None)
    os.makedirs(os.path.join(tmp, "cloud", "my-files"), exist_ok=True)
    open(os.path.join(tmp, "cloud", ".logged_in"), "w").close()
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    return tmp


def file_uri(path):
    """file:///… for a local path (also C:\… on Windows)."""
    import pathlib
    return pathlib.Path(os.path.abspath(path)).as_uri()


def in_trash(path):
    """Is the file that was at `path` now in the system trash? Linux: the freedesktop Trash under
    XDG_DATA_HOME (the tests' own); Windows: the Recycle Bin of that drive ($I files name the original path)."""
    if os.name != "nt":
        return os.path.exists(os.path.join(os.environ["XDG_DATA_HOME"], "Trash", "files", os.path.basename(path)))
    import glob
    import struct
    want = os.path.normcase(os.path.abspath(path))
    drive = os.path.splitdrive(want)[0] or "C:"
    for info in glob.glob(os.path.join(drive + "\\", "$Recycle.Bin", "*", "$I*")):
        try:
            data = open(info, "rb").read()
        except OSError:
            continue
        version = struct.unpack_from("<q", data, 0)[0]
        if version == 2:
            n = struct.unpack_from("<i", data, 24)[0]
            orig = data[28:28 + 2 * n].decode("utf-16-le").rstrip(chr(0))
        else:
            orig = data[24:24 + 520].decode("utf-16-le").split(chr(0))[0]
        if os.path.normcase(orig) == want:
            return True
    return False


def pid_alive(pid):
    from kluis.system import pid_alive as alive
    return alive(pid)


def flag(tmp, name, on=True):
    p = os.path.join(tmp, "cloud", "." + name)
    if on:
        open(p, "w").close()
    elif os.path.exists(p):
        os.remove(p)


def calls(tmp):
    try:
        return open(os.path.join(tmp, "cloud", ".calls")).read().splitlines()
    except OSError:
        return []


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    time.sleep(0.01)


def read(path):
    with open(path) as f:
        return f.read()


class Checker:
    def __init__(self):
        self.passed = 0

    def __call__(self, cond, msg):
        if not cond:
            print("FAIL:", msg)
            sys.exit(1)
        self.passed += 1
        print("  ok -", msg)


def cleanup(tmp):
    shutil.rmtree(tmp, ignore_errors=True)

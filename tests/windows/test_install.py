"""F-030 / F-028 / F-023 on a real install: the built installer, the installed Kluis.exe, the uninstaller.

CI (job windows) runs it after packaging/windows/build.sh, from the repository root:
    python tests/windows/test_install.py
It installs dist/Kluis-Setup-*.exe silently for this user, starts Kluis, starts it a second time (it must hand
over, not run twice), takes a screenshot, uninstalls, and checks nothing is left behind except settings.
"""
import glob
import os
import subprocess
import sys
import time
import winreg

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIST = os.path.join(REPO, "dist")
LOCAL = os.environ["LOCALAPPDATA"]
APP = os.path.join(LOCAL, "Programs", "Kluis")
EXE = os.path.join(APP, "Kluis.exe")
LNK = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs", "Kluis.lnk")
passed = 0


def check(cond, msg):
    global passed
    if not cond:
        print("FAIL:", msg)
        sys.exit(1)
    passed += 1
    print("  ok -", msg)


def kluis_pids():
    out = subprocess.run(["tasklist", "/fi", "imagename eq Kluis.exe", "/fo", "csv", "/nh"],
                         capture_output=True, text=True).stdout
    return [int(line.split('","')[1]) for line in out.splitlines() if line.startswith('"Kluis.exe"')]


def run_key():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
            return winreg.QueryValueEx(k, "Kluis")[0]
    except OSError:
        return None


def screenshot(path):
    ps = ("Add-Type -AssemblyName System.Windows.Forms, System.Drawing;"
          "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
          "$m=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
          "[System.Drawing.Graphics]::FromImage($m).CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size);"
          f"$m.Save('{path}')")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=60)


setup = sorted(glob.glob(os.path.join(DIST, "Kluis-Setup-*.exe")))
check(setup, "F-030 the installer was built")
subprocess.run([setup[-1], "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=" + os.path.join(DIST, "install.log")],
               check=True, timeout=600)
check(os.path.isfile(EXE), f"F-030 Kluis.exe is installed for this user ({APP})")
check(os.path.isfile(LNK), "F-030 Kluis is in the Start menu")

env = dict(os.environ, KLUIS_DEBUG="1")
first = subprocess.Popen([EXE], env=env)
time.sleep(25)
check(first.poll() is None and len(kluis_pids()) == 1, f"Kluis.exe starts and keeps running ({kluis_pids()})")
screenshot(os.path.join(DIST, "windows-installed.png"))
second = subprocess.Popen([EXE], env=env)
try:
    second.wait(timeout=30)
    handed_over = True
except subprocess.TimeoutExpired:
    handed_over = False
time.sleep(2)
check(handed_over and len(kluis_pids()) == 1, f"F-028 a second start hands over and ends ({kluis_pids()})")
log = os.path.join(LOCAL, "Kluis", "state", "kluis.log")
text = open(log, encoding="utf-8", errors="replace").read() if os.path.exists(log) else ""
open(os.path.join(DIST, "kluis-installed.log"), "w", encoding="utf-8").write(text)
check("Traceback" not in text, "Kluis logged no exception")
check("panel icon: Windows notification area" in text, "F-023 Kluis's icon is in the notification area")
check(run_key() and "Kluis.exe" in run_key(), f"F-025 Start at sign-in (on by default) points at Kluis.exe ({run_key()})")

subprocess.run([os.path.join(APP, "unins000.exe"), "/VERYSILENT", "/SUPPRESSMSGBOXES"], check=True, timeout=300)
time.sleep(5)
check(not os.path.exists(EXE), "F-030 uninstalling removes Kluis.exe")
check(not kluis_pids(), "F-030 uninstalling ends a running Kluis")
check(run_key() is None, "F-030 uninstalling removes the Start at sign-in entry")
check(not os.path.exists(LNK), "F-030 uninstalling removes the Start menu entry")
check(os.path.exists(os.path.join(LOCAL, "Kluis", "config")), "F-030 settings are kept")
print(f"\n{passed} checks passed")

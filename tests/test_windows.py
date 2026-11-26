"""Windows port checks that need no GTK (added by the fresh-eyes audit of 2026-11-26).

Run: python tests/test_windows.py   (Windows: everything; Linux: the name rules and the Credential Manager name)
The checks that need Windows itself (Recycle Bin, open files, junctions, the folder watcher, replacing a running
proton-drive.exe) are skipped on Linux with a line saying so.
"""
import hashlib
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

TMP = harness.setup("kluis-windows-")
check = harness.Checker()
WIN = os.name == "nt"
write, read = harness.write, harness.read

from kluis.cli import ProtonDriveCli  # noqa: E402
from kluis.config import FolderPair  # noqa: E402
from kluis.engine import SyncEngine  # noqa: E402
from kluis.state import StateStore  # noqa: E402

CLOUD = os.path.join(TMP, "cloud", "my-files")
HOME = os.path.join(TMP, "home")
cli = ProtonDriveCli(harness.MOCK)
eng = SyncEngine(cli, StateStore(os.path.join(TMP, "state.sqlite")))
logged = []
eng.on_event = lambda fid, kind, **d: logged.append(d.get("text", "")) if kind == "log" else None


def pair(name, local=None, mode="two-way"):
    local = local or os.path.join(HOME, name)
    os.makedirs(local, exist_ok=True)
    os.makedirs(os.path.join(CLOUD, name), exist_ok=True)
    return FolderPair(local=local, remote="/my-files/" + name, mode=mode)


def skip(msg):
    print("  skip -", msg)


print("Credential Manager item of Proton's CLI (F-024)")
from kluis.accounts import CLI_WIN_TARGET  # noqa: E402
# Bun.secrets on Windows (oven-sh/bun src/jsc/bindings/SecretsWindows.cpp): TargetName = service + "/" + name
check(CLI_WIN_TARGET == "ch.proton.drive/drive-sdk-cli/auth-session",
      f"F-024 Kluis copies the CLI's own credential ch.proton.drive/drive-sdk-cli/auth-session ({CLI_WIN_TARGET})")

print("a file open in another program (F-033)")
if WIN:
    f = pair("InUse")
    write(f"{CLOUD}/InUse/open.txt", "v1")
    write(f"{CLOUD}/InUse/other.txt", "o1")
    check(eng.sync(f).status == "ok" and read(f"{f.local}/open.txt") == "v1", "F-033 synced once")
    write(f"{CLOUD}/InUse/open.txt", "v2 from Proton Drive")
    write(f"{CLOUD}/InUse/other.txt", "o2")
    held = open(f"{f.local}/open.txt", "rb")           # like Word: open without delete sharing
    try:
        r = eng.sync(f)
    finally:
        held.close()
    check(any("open.txt is in use by another program" in e for e in r.errors),
          f"F-033 a file another program has open is reported, not crashed on ({r.errors})")
    check(read(f"{f.local}/open.txt") == "v1" and read(f"{f.local}/other.txt") == "o2",
          "F-033 the open file stays as it was; the rest of the folder syncs")
    part = os.path.join(f.local, ".kluis-part")
    check(not os.path.isdir(part) or not any(files for _d, _s, files in os.walk(part)),
          "F-033 no half-finished download is left behind")
    r = eng.sync(f)
    check(r.status == "ok" and read(f"{f.local}/open.txt") == "v2 from Proton Drive",
          f"F-033 once the program closes it, the next sync brings the new version ({r.message})")
else:
    skip("F-033 needs Windows' file locking")

print("junctions are not followed (F-035)")
if WIN:
    import _winapi
    f = pair("Junction")
    outside = os.path.join(TMP, "outside")
    write(f"{outside}/private.txt", "not for the cloud")
    write(f"{f.local}/mine.txt", "mine")
    _winapi.CreateJunction(outside, os.path.join(f.local, "link"))
    r = eng.sync(f)
    check(r.status == "ok" and os.path.exists(f"{CLOUD}/Junction/mine.txt"), f"F-035 the folder syncs ({r.message})")
    check(not os.path.exists(f"{CLOUD}/Junction/link"),
          "F-035 a junction (a link to another folder) is not followed: nothing behind it is uploaded")
    os.rmdir(os.path.join(f.local, "link"))             # removes the junction only
else:
    skip("F-035 junctions exist only on Windows")

print("a drive without a Recycle Bin (F-027)")
if WIN:
    base = os.path.join(TMP, "share")
    drive, rest = os.path.splitdrive(base)
    unc = "\\\\localhost\\" + drive[0] + "$" + rest     # the same folder seen as a network share
    os.makedirs(base, exist_ok=True)
    if os.path.isdir(unc):
        f = pair("Share", local=os.path.join(unc, "Share"))
        write(f"{CLOUD}/Share/gone.txt", "g")
        for i in range(9):
            write(f"{CLOUD}/Share/keep{i}.txt", "k")
        check(eng.sync(f).status == "ok" and os.path.exists(os.path.join(base, "Share", "gone.txt")),
              "F-027 a folder on a network share syncs")
        os.remove(f"{CLOUD}/Share/gone.txt")
        r = eng.sync(f, allow_trash=1)
        check(os.path.exists(os.path.join(base, "Share", "gone.txt")),
              "F-027 deleted in Proton Drive, but the share has no Recycle Bin: the file stays in place")
        check(any("no Recycle Bin" in e and "gone.txt" in e for e in r.errors),
              f"F-027 … and Kluis says so ({r.errors})")
    else:
        skip(f"F-027 the administrative share {unc[:20]}… is not reachable here")
else:
    skip("F-027 the Recycle Bin is Windows only (Linux: tests/test_safety.py)")

print("changes on this computer are noticed (F-032)")
if WIN:
    from kluis.winwatch import TreeWatcher
    root = os.path.join(HOME, "Watched")
    os.makedirs(os.path.join(root, "sub"), exist_ok=True)
    seen = []
    w = TreeWatcher(root, lambda rel, action: seen.append((rel, action)))
    try:
        write(os.path.join(root, "sub", "new.txt"), "x")
        deadline = time.time() + 10
        while time.time() < deadline and not any(rel == "sub/new.txt" for rel, _a in seen):
            time.sleep(0.1)
        check(any(rel == "sub/new.txt" for rel, _a in seen),
              f"F-032 a new file in a subfolder is noticed, with its path inside the synced folder ({seen[:4]})")
        os.rename(os.path.join(root, "sub"), os.path.join(root, "renamed"))
        check(os.path.isdir(os.path.join(root, "renamed")),
              "F-032 while Kluis watches, a subfolder can still be renamed (one handle, on the synced folder)")
        moved = root + "-moved"
        try:
            os.rename(root, moved)
        except OSError as e:
            print("   ", e)
        check(os.path.isdir(moved), "F-032 … and the synced folder itself can be moved (the handle shares delete)")
    finally:
        w.cancel()
else:
    skip("F-032 kluis/winwatch.py is Windows only (Linux: Gio file monitors)")

print("updating proton-drive.exe while it runs (F-034)")
if WIN:
    from kluis.cli import download_cli
    from kluis.paths import CLI_NAME
    bindir = os.path.join(TMP, "bin")
    os.makedirs(bindir)
    exe = os.path.join(bindir, CLI_NAME)
    shutil.copy(os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "PING.EXE"), exe)
    running = subprocess.Popen([exe, "-n", "30", "127.0.0.1"], stdout=subprocess.DEVNULL)
    try:
        time.sleep(0.5)
        new = open(harness.MOCK, "rb").read()
        path = download_cli(dest_dir=bindir, rel={"version": "9.9.9", "url": harness.file_uri(harness.MOCK),
                                                  "sha512": hashlib.sha512(new).hexdigest()})
        check(open(path, "rb").read() == new and os.path.basename(path) == CLI_NAME,
              "F-034 the new proton-drive.exe is in place although the old one was still running")
        check(any(n.endswith(".old") for n in os.listdir(bindir)) and running.poll() is None,
              "F-034 the running one was moved aside, not stopped")
    finally:
        running.kill()
        running.wait()
else:
    skip("F-034 Linux replaces a running program file without help")

print("names Windows tells apart (F-021, F-022; broken in 2ec033e, fixed by audit 2026-11-26)")
eng.windows = True
f = pair("Strasse")
write(f"{CLOUD}/Strasse/straße.txt", "with ß")
write(f"{CLOUD}/Strasse/strasse.txt", "with ss")
write(f"{CLOUD}/Strasse/straße.md", "Proton's")
write(f"{f.local}/STRASSE.md", "mine")
logged.clear()
r = eng.sync(f)
check(r.status == "ok",
      f"F-022 straße.md in Proton Drive and STRASSE.md here are different names on Windows: the folder syncs "
      f"({r.status}: {r.message})")
check(read(f"{f.local}/straße.txt") == "with ß" and read(f"{f.local}/strasse.txt") == "with ss"
      and not any("Left out" in t for t in logged),
      f"F-021 straße.txt and strasse.txt can both exist on Windows: neither is left out ({logged})")
check(read(f"{CLOUD}/Strasse/STRASSE.md") == "mine" and read(f"{CLOUD}/Strasse/straße.md") == "Proton's",
      "F-022 both .md files end up on both sides")
eng.windows = WIN

print(f"\n{check.passed} checks passed")
harness.cleanup(TMP)

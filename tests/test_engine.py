"""End-to-end engine scenarios against the mock CLI. Run: python3 tests/test_engine.py"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# inside the home folder, like real synced folders, so the home Trash is on the same drive
_base = os.path.join(os.path.expanduser("~"), ".cache")
os.makedirs(_base, exist_ok=True)
TMP = tempfile.mkdtemp(prefix="kluis-test-", dir=_base)
os.environ["XDG_CONFIG_HOME"] = os.path.join(TMP, "config")
os.environ["XDG_DATA_HOME"] = os.path.join(TMP, "data")
os.environ["XDG_STATE_HOME"] = os.path.join(TMP, "state")
os.environ["MOCK_ROOT"] = os.path.join(TMP, "cloud")
sys.path.insert(0, os.path.dirname(HERE))

from kluis.cli import ProtonDriveCli  # noqa: E402
from kluis.config import FolderPair  # noqa: E402
from kluis.engine import SyncEngine  # noqa: E402
from kluis.state import StateStore  # noqa: E402

CLI = os.path.join(HERE, "mock_cli", "proton-drive")
CLOUD = os.path.join(TMP, "cloud", "my-files")
cli = ProtonDriveCli(CLI)
store = StateStore(os.path.join(TMP, "state.sqlite"))
eng = SyncEngine(cli, store)
passed = 0


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    time.sleep(0.01)


def read(path):
    with open(path) as f:
        return f.read()


def check(cond, msg):
    global passed
    if not cond:
        print("FAIL:", msg)
        sys.exit(1)
    passed += 1
    print("  ok -", msg)


print("auth")
check(not cli.is_logged_in(), "reports logged out before sign-in")
urls = []
cli.login(urls.append)
check(urls and urls[0].startswith("https://"), "sign-in URL is surfaced")
check(cli.is_logged_in(), "logged in afterwards")
check(cli.version().startswith("cli-drive@0.9.0"), "version parsed")

print("two-way")
L = os.path.join(TMP, "home", "Notes")
write(f"{L}/a.md", "alpha")
write(f"{L}/sub/b.md", "beta")
write(f"{L}/skip.tmp", "ignored")
write(f"{CLOUD}/Notes/r.md", "remote")
f = FolderPair(local=L, remote="/my-files/Notes", mode="two-way")
r = eng.sync(f)
check(r.status == "ok", f"first sync ok ({r.message})")
check(read(f"{CLOUD}/Notes/a.md") == "alpha" and read(f"{CLOUD}/Notes/sub/b.md") == "beta", "local files uploaded")
check(read(f"{L}/r.md") == "remote", "remote file downloaded")
check(not os.path.exists(f"{CLOUD}/Notes/skip.tmp"), "ignore patterns respected")
r = eng.sync(f)
check(r.message == "Up to date" and r.uploaded == r.downloaded == 0, "second sync is a no-op")

write(f"{L}/a.md", "alpha v2")
write(f"{CLOUD}/Notes/r.md", "remote v2")
r = eng.sync(f)
check(read(f"{CLOUD}/Notes/a.md") == "alpha v2", "local edit uploaded")
check(read(f"{L}/r.md") == "remote v2", "remote edit downloaded")
check(eng.sync(f).message == "Up to date", "stable after edits")

write(f"{L}/a.md", "local side")
write(f"{CLOUD}/Notes/a.md", "remote side")
r = eng.sync(f)
check(r.status == "conflict", "edit on both sides is a conflict")
conf = [n for n in os.listdir(L) if "conflict" in n]
check(len(conf) == 1 and read(f"{L}/a.md") == "remote side" and read(f"{L}/{conf[0]}") == "local side",
      "both copies kept locally")
check(os.path.exists(f"{CLOUD}/Notes/{conf[0]}"), "conflict copy uploaded")
check(eng.sync(f).message == "Up to date", "stable after conflict")

os.remove(f"{L}/sub/b.md")
os.remove(f"{CLOUD}/Notes/r.md")
r = eng.sync(f)
check(r.status == "guard" and r.pending_trash == 2 and os.path.exists(f"{CLOUD}/Notes/sub/b.md"),
      "mass-deletion guard asks first (2 of 6 files > 10 %) and changes nothing")
r = eng.sync(f, allow_trash=r.pending_trash)   # the user clicked "Move them to the trash"
check(not os.path.exists(f"{CLOUD}/Notes/sub/b.md"), "local delete -> Proton Drive trash")
check(any("b.md" in n for n in os.listdir(os.path.join(TMP, "cloud", ".trash"))), "remote copy is in the trash")
check(not os.path.exists(f"{L}/r.md"), "remote delete -> local Trash")
check(eng.sync(f).message == "Up to date", "stable after deletes")

shutil.rmtree(f"{L}/sub")
eng.sync(f, allow_trash=10)
check(not os.path.exists(f"{CLOUD}/Notes/sub"), "deleted folder trashed remotely")

write(f"{L}/new/deep/x.md", "x")
r = eng.sync(f)
check(read(f"{CLOUD}/Notes/new/deep/x.md") == "x", "new nested folders created and uploaded")

print("failures")
write(f"{L}/FAILME.md", "boom")
r = eng.sync(f)
check(r.status == "error" and "FAILME" in r.message, f"upload failure reported ({r.message})")
r = eng.sync(f)
check(r.status == "error", "failed file is retried next time")
os.remove(f"{L}/FAILME.md")
check(eng.sync(f).status == "ok", "recovers once the problem is gone")

print("backup")
B = os.path.join(TMP, "home", "Photos")
write(f"{B}/1.jpg", "one")
fb = FolderPair(local=B, remote="/my-files/Backups/Photos", mode="backup")
r = eng.sync(fb)
check(r.status == "ok" and read(f"{CLOUD}/Backups/Photos/1.jpg") == "one", f"backup creates path & uploads ({r.message})")
os.remove(f"{B}/1.jpg")
write(f"{B}/2.jpg", "two")
eng.sync(fb)
check(os.path.exists(f"{CLOUD}/Backups/Photos/1.jpg"), "backup never deletes in Proton Drive")
write(f"{CLOUD}/Backups/Photos/cloud-only.jpg", "c")
eng.sync(fb)
check(not os.path.exists(f"{B}/cloud-only.jpg"), "backup never changes this computer")

print("mirror")
M = os.path.join(TMP, "home", "Shared")
write(f"{CLOUD}/Team/plan.md", "p1")
write(f"{CLOUD}/Team/docs/spec.md", "s1")
fm = FolderPair(local=M, remote="/my-files/Team", mode="mirror")
r = eng.sync(fm)
check(read(f"{M}/plan.md") == "p1" and read(f"{M}/docs/spec.md") == "s1", f"mirror downloads tree ({r.message})")
write(f"{M}/local-extra.md", "mine")
write(f"{CLOUD}/Team/plan.md", "p2")
eng.sync(fm)
check(read(f"{M}/plan.md") == "p2", "mirror picks up remote edits")
check(not os.path.exists(f"{CLOUD}/Team/local-extra.md"), "mirror never uploads")
check(eng.sync(fm).message == "Up to date", "mirror stable")

print("an unfinished run continues with the listings it has (RESUME_MAX)")
from kluis.engine import RESUME_MAX  # noqa: E402

RB = os.path.join(TMP, "home", "Brain")
for d in ("a", "b", "c", "d"):
    write(f"{CLOUD}/Brain/{d}/x.md", d)
    write(f"{CLOUD}/Brain/{d}/sub/y.md", d)
for i in range(20):                     # enough files that one deletion stays under the §7.8 guard
    write(f"{CLOUD}/Brain/n{i:02}.md", str(i))
fr = FolderPair(local=RB, remote="/my-files/Brain", mode="mirror", id="brain")
_orig_list = cli.list
listed, stop = [], {"list": 0}


def _list(p):
    listed.append(p)
    out = _orig_list(p)
    if stop["list"] and len(listed) >= stop["list"]:
        eng.cancel()                    # like quitting Kluis halfway through the scan
    return out


cli.list = _list
stop["list"] = 3
r = eng.sync(fr)
kept = len(store.scan_get("brain", fr.remote, RESUME_MAX))
check(r.status == "cancelled" and kept == len(listed) and 0 < kept < 9,
      f"a scan stopped halfway keeps the {kept} of 9 folders it listed")
listed.clear()
stop["list"] = 0
r = eng.sync(fr)
check(r.status == "ok" and len(listed) == 9 - kept and read(f"{RB}/d/sub/y.md") == "d" and r.downloaded == 28,
      f"the next run lists only the {9 - kept} folders it didn't have, and finishes ({r.message})")
check(store.scan_get("brain", fr.remote, RESUME_MAX) == {}, "a completed run throws the listings away")
listed.clear()
check(eng.sync(fr).message == "Up to date" and len(listed) == 9, "so the next ordinary sync lists every folder")

listed.clear()
stop["list"] = 2
eng.sync(fr)
with store._lock, store._db:
    store._db.execute("UPDATE scan_cache SET ts = ts - ?", (RESUME_MAX + 1,))
listed.clear()
stop["list"] = 0
eng.sync(fr)
check(len(listed) == 9, "listings older than RESUME_MAX are never used")

listed.clear()
stop["list"] = 1                        # only the top folder listed, then stopped
eng.sync(fr)
write(f"{CLOUD}/Brain/new.md", "added meanwhile")
stop["list"] = 0
r = eng.sync(fr)
check(r.status == "ok" and not os.path.exists(f"{RB}/new.md"), "a file added after the kept listing waits …")
r = eng.sync(fr)
check(read(f"{RB}/new.md") == "added meanwhile", "… for the next run, which lists fresh (never lost)")

listed.clear()
stop["list"] = 2                        # the top folder and "a" (with x.md) listed, then stopped
eng.sync(fr)
check("a" in store.scan_get("brain", fr.remote, RESUME_MAX), "(folder a's listing is kept)")
os.remove(f"{CLOUD}/Brain/a/x.md")
stop["list"] = 0
r = eng.sync(fr)
check(r.status == "ok" and os.path.exists(f"{RB}/a/x.md"),
      f"a file deleted after its folder's kept listing stays on this computer for now ({r.message})")
r = eng.sync(fr)
check(r.status == "ok" and not os.path.exists(f"{RB}/a/x.md"),
      f"the fresh listing after it mirrors the deletion as usual ({r.message})")

TW = os.path.join(TMP, "home", "Work2")
write(f"{TW}/Plan.md", "v1")
write(f"{TW}/sub/s.md", "s")
fw = FolderPair(local=TW, remote="/my-files/Work2", mode="two-way", id="work2")
check(eng.sync(fw).status == "ok", "two-way folder synced")
listed.clear()
stop["list"] = 1
eng.sync(fw)
check(store.scan_get("work2", fw.remote, RESUME_MAX) == {}, "two-way runs keep no listings")
write(f"{TW}/Plan.md", "local edit")
write(f"{CLOUD}/Work2/Plan.md", "edit in Proton Drive meanwhile")
stop["list"] = 0
r = eng.sync(fw)
conf = [n for n in os.listdir(TW) if n.startswith("Plan (conflict ")]
check(len(conf) == 1 and read(f"{TW}/Plan.md") == "edit in Proton Drive meanwhile",
      f"so an edit made in Drive during the stop is seen: both copies kept ({r.message})")
cli.list = _orig_list

print("cancel / logged out")
cli.logout()
r = eng.sync(f)
check(r.status == "hold" and r.hold_kind == "signed-out", "logged-out state pauses syncing clearly (§7.10)")

print(f"\n{passed} checks passed")
shutil.rmtree(TMP, ignore_errors=True)

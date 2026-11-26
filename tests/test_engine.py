"""End-to-end engine scenarios against the mock CLI. Run: python3 tests/test_engine.py"""
import json
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
sys.path.insert(0, HERE)

from kluis.cli import ProtonDriveCli  # noqa: E402
from kluis.config import FolderPair  # noqa: E402
from kluis.engine import SyncEngine  # noqa: E402
from kluis.state import StateStore  # noqa: E402
from harness import in_trash as harness_in_trash  # noqa: E402

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

print("names Windows can't store (F-021, F-022)")
# On Linux the mock cloud can hold every name Proton Drive allows, so the whole Windows rule runs end to end
# (eng.windows = True is what a Windows Kluis does). On Windows the mock cloud is an NTFS folder: the
# case-insensitive part runs there for real.
eng.windows = True
W = os.path.join(TMP, "home", "Mixed")
os.makedirs(W, exist_ok=True)
odd = ["a:b.txt", "ends with dot.", "CON.txt", "what?.md", "bad|dir/inner.txt"]
if os.name != "nt":
    for n in odd:
        write(f"{CLOUD}/Mixed/{n}", "odd")
    write(f"{CLOUD}/Mixed/Plan.md", "upper")
    write(f"{CLOUD}/Mixed/plan.md", "lower")
write(f"{CLOUD}/Mixed/ok.txt", "fine")
fw = FolderPair(local=W, remote="/my-files/Mixed", mode="two-way")
logged = []
eng.on_event = lambda fid, kind, **d: logged.append(d.get("text", "")) if kind == "log" else None
r = eng.sync(fw)
check(r.status == "ok" and read(f"{W}/ok.txt") == "fine", f"F-021 a folder with odd names still syncs ({r.message})")
if os.name != "nt":
    check(sorted(os.listdir(W)) == ["Plan.md", "ok.txt"],
          f"F-021 names Windows can't store are left out; of Plan.md/plan.md one is synced ({sorted(os.listdir(W))})")
    check(all(os.path.exists(f"{CLOUD}/Mixed/{n}") for n in odd + ["plan.md", "Plan.md"]),
          "F-021 left-out items stay untouched in Proton Drive")
    check(sum("Left out" in t for t in logged) == len(odd) + 1 and any("upper and lower case" in t for t in logged),
          "F-021 Activity says which items were left out and why")
    logged.clear()
    r = eng.sync(fw)
    check(r.message == "Up to date" and not logged, "F-021 the next sync is quiet: nothing to do, said once")
    trashed = json.load(open(os.path.join(TMP, "cloud", ".trash", "index.json"))) \
        if os.path.exists(os.path.join(TMP, "cloud", ".trash", "index.json")) else {}
    check(not any("Mixed" in e.get("orig", "") for e in trashed.values()), "F-021 nothing of it went to a trash")
else:
    write(f"{W}/notes.txt", "same text")
    write(f"{CLOUD}/Mixed/Notes.txt", "same text")
    write(f"{W}/sub/Deep.txt", "deep")
    write(f"{CLOUD}/Mixed/SUB/Deep.txt", "deep")
    r = eng.sync(fw)
    names = sorted(os.listdir(f"{CLOUD}/Mixed"))
    check(r.conflicts == 0 and names == ["Notes.txt", "SUB", "ok.txt"],
          f"F-022 notes.txt here and Notes.txt in Proton Drive are one file, not two ({names}, {r.message})")
    check(eng.sync(fw).message == "Up to date", "F-022 stable afterwards")
    os.remove(f"{CLOUD}/Mixed/Notes.txt")
    r = eng.sync(fw, allow_trash=1)          # 1 of 3 files is more than the guard's 10 %
    check(not os.path.exists(f"{W}/notes.txt") and harness_in_trash(f"{W}/notes.txt"),
          "F-022 deleting it in Proton Drive moves the local copy (other spelling) to the Recycle Bin")
eng.windows = os.name == "nt"
eng.on_event = lambda *a, **k: None

print("cancel / logged out")
cli.logout()
r = eng.sync(f)
check(r.status == "hold" and r.hold_kind == "signed-out", "logged-out state pauses syncing clearly (§7.10)")

print(f"\n{passed} checks passed")
shutil.rmtree(TMP, ignore_errors=True)

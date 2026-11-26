"""One test per safety invariant (HANDOVER §7). Run: python3 tests/test_safety.py"""
import glob
import hashlib
import json
import os
import re
import shutil
import socket
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
from harness import read, write  # noqa: E402

TMP = harness.setup("kluis-safety-")
check = harness.Checker()

from kluis.cli import ProtonDriveCli  # noqa: E402
from kluis.config import FolderPair, Settings  # noqa: E402
from kluis.engine import SyncEngine  # noqa: E402
from kluis.state import StateStore  # noqa: E402

CLOUD = os.path.join(TMP, "cloud", "my-files")
HOME = os.path.join(TMP, "home")
TRASH_FILES = os.path.join(os.environ["XDG_DATA_HOME"], "Trash", "files")
cli = ProtonDriveCli(harness.MOCK)
store = StateStore(os.path.join(TMP, "state.sqlite"))
eng = SyncEngine(cli, store)


def folder(name, mode="two-way", remote=None, **kw):
    return FolderPair(local=os.path.join(HOME, name), remote=remote or f"/my-files/{name}", mode=mode, **kw)


def mock_trash():
    idx = os.path.join(TMP, "cloud", ".trash", "index.json")
    return json.load(open(idx)) if os.path.exists(idx) else {}


# ---------------------------------------------------------------- 1
print("1 · nothing is ever deleted permanently")
f1 = folder("One")
for i in range(30):
    write(f"{f1.local}/f{i}.txt", f"v{i}")
eng.sync(f1)
os.remove(f"{f1.local}/f0.txt")
os.remove(f"{CLOUD}/One/f1.txt")
eng.sync(f1)
check(any(os.path.basename(e["orig"]) == "f0.txt" for e in mock_trash().values()),
      "local delete → item is in the Proton Drive trash (restorable)")
check(os.path.exists(os.path.join(TRASH_FILES, "f1.txt")), "remote delete → file is in the freedesktop Trash")
uid = next(u for u, e in mock_trash().items() if e["orig"].endswith("f0.txt"))
found = cli.trashed([uid])
check(found is not None and found[0].name == "f0.txt", "trashed item is found by uid, addressed by its unique name")
cli.restore(found)
check(os.path.exists(f"{CLOUD}/One/f0.txt"), "trashed item restores from the Proton Drive trash (Undo)")
src = open(os.path.join(harness.REPO, "kluis", "cli.py")).read()
check("delete_trashed" in src and not any("delete_trashed" in open(p).read() for p in
                                           glob.glob(os.path.join(harness.REPO, "kluis", "*.py"))
                                           if not p.endswith(("cli.py", "selftest.py"))),
      "permanent delete is only reachable from --selftest")

# ---------------------------------------------------------------- 2
print("2 · changed on both sides keeps both copies")
write(f"{f1.local}/f2.txt", "mine")
write(f"{CLOUD}/One/f2.txt", "theirs")
r = eng.sync(f1)
host = socket.gethostname()
pat = re.compile(r"^f2 \(conflict \d{4}-\d{2}-\d{2} \d{4} " + re.escape(host) + r"\)\.txt$")
conf = [n for n in os.listdir(f1.local) if pat.match(n)]
check(r.status == "conflict" and len(conf) == 1, f"conflict copy named like 'f2 (conflict YYYY-MM-DD HHMM {host}).txt'")
check(read(f"{f1.local}/f2.txt") == "theirs" and read(f"{f1.local}/{conf[0]}") == "mine", "both contents kept")

# ---------------------------------------------------------------- 3
print("3 · synced only after the SHA-1 matches")
f3 = folder("Three")
write(f"{f3.local}/good.txt", "g")
write(f"{f3.local}/BADHASH.txt", "b")
os.environ["MOCK_BAD_SHA1"] = "BADHASH"
eng.sync(f3)
st = store.load(f3.id)
check("good.txt" in st and "BADHASH.txt" not in st, "upload whose remote SHA-1 differs is not marked synced")
write(f"{CLOUD}/Three/BADHASH-down.txt", "d")
r = eng.sync(f3)
check(not os.path.exists(f"{f3.local}/BADHASH-down.txt") and "checksum" in r.message,
      "download whose SHA-1 differs is not placed")
os.environ.pop("MOCK_BAD_SHA1")
eng.sync(f3)
check("BADHASH.txt" in store.load(f3.id) and read(f"{f3.local}/BADHASH-down.txt") == "d",
      "both are retried and recorded once the hashes match")

# ---------------------------------------------------------------- 4
print("4 · mode rules")
fb = folder("Back", mode="backup")
write(f"{fb.local}/a.txt", "a")
eng.sync(fb)
os.remove(f"{fb.local}/a.txt")
write(f"{CLOUD}/Back/remote-only.txt", "r")
write(f"{CLOUD}/Back/a2.txt", "x")
before = sorted(os.listdir(fb.local))
eng.sync(fb, allow_trash=99)
check(os.path.exists(f"{CLOUD}/Back/a.txt"), "back up never deletes remotely")
check(sorted(os.listdir(fb.local)) == before, "back up never changes local files")
fm = folder("Mirror", mode="mirror")
write(f"{CLOUD}/Mirror/m.txt", "m1")
eng.sync(fm)
remote_before = {n: read(f"{CLOUD}/Mirror/{n}") for n in os.listdir(f"{CLOUD}/Mirror")}
write(f"{fm.local}/m.txt", "local edit")
write(f"{fm.local}/new-local.txt", "n")
os.makedirs(f"{fm.local}/newdir", exist_ok=True)
eng.sync(fm)
check({n: read(f"{CLOUD}/Mirror/{n}") for n in os.listdir(f"{CLOUD}/Mirror")} == remote_before,
      "mirror down never changes Proton Drive")
os.makedirs(os.path.join(TMP, "cloud", "shared-with-me", "Papies"), exist_ok=True)
write(os.path.join(TMP, "cloud", "shared-with-me", "Papies", "p.txt"), "p")
json.dump({"Papies": {"role": "viewer", "by": "a@b.c"}}, open(os.path.join(TMP, "cloud", "shared.json"), "w"))
fv = FolderPair(local=os.path.join(HOME, "Papies"), remote="/shared-with-me/Papies", mode="two-way")
eng.sync(fv)
write(f"{fv.local}/mine.txt", "m")
eng.sync(fv)
check(read(f"{fv.local}/p.txt") == "p" and not os.path.exists(
    os.path.join(TMP, "cloud", "shared-with-me", "Papies", "mine.txt")), "viewer share is always mirror down")

# ---------------------------------------------------------------- 5
print("5 · removing a folder never deletes files")
from kluis.manager import SyncManager  # noqa: E402
s = Settings()
s.folders = [f1]
m = SyncManager(s, cli, store=store, start_thread=False)
local_before = sorted(os.listdir(f1.local))
remote_before = sorted(os.listdir(f"{CLOUD}/One"))
s.folders.remove(f1)
m.folder_removed(f1.id)
check(sorted(os.listdir(f1.local)) == local_before and sorted(os.listdir(f"{CLOUD}/One")) == remote_before,
      "both sides untouched after Remove")

# ---------------------------------------------------------------- 6
print("6 · moving the Proton Drive folder is atomic per item and resumable")
from kluis import rootmove  # noqa: E402
R1, R2 = os.path.join(HOME, "PD"), os.path.join(HOME, "PD2")
for i in range(6):
    write(f"{R1}/item{i}/doc.txt", f"d{i}")
write(f"{R1}/top.txt", "t")
files = {f"item{i}/doc.txt": f"d{i}" for i in range(6)}
files["top.txt"] = "t"
journal = os.path.join(TMP, "journal.json")
orig_same = rootmove._same_device
rootmove._same_device = lambda a, b: False                        # force the copy path (other drive)
j = rootmove.start(R1, R2, journal=journal)
try:
    rootmove.run(j, journal=journal, _crash_after=2)
except KeyboardInterrupt:
    pass
every = all(os.path.exists(os.path.join(R1, rel)) or os.path.exists(os.path.join(R2, rel)) for rel in files)
check(every, "after a crash mid-move every file exists in at least one place")
j2 = rootmove.pending(journal)
check(j2 is not None, "the journal survives the crash")
check(rootmove.run(j2, journal=journal), "the move resumes from the journal")
check(all(read(os.path.join(R2, rel)) == txt for rel, txt in files.items()) and not os.path.exists(R1)
      and rootmove.pending(journal) is None, "all files moved, nothing lost, journal removed")
rootmove._same_device = orig_same

# ---------------------------------------------------------------- 7
print("7 · Pause/Stop leaves no half-written files")
f7 = folder("Seven")
os.makedirs(f7.local, exist_ok=True)
for i in range(3):
    write(f"{CLOUD}/Seven/big{i}.bin", "x" * 200000)
os.environ["MOCK_DOWNLOAD_DELAY"] = "3"
res = {}
t = threading.Thread(target=lambda: res.setdefault("r", eng.sync(f7)))
t.start()
time.sleep(1.5)
eng.cancel()
t.join(20)
os.environ.pop("MOCK_DOWNLOAD_DELAY")
leftovers = [p for p in glob.glob(f"{f7.local}/**", recursive=True) if ".kluis-part" in p]
check(res["r"].status == "cancelled" and not leftovers, "Stop mid-download: no .kluis-part leftovers")
check(all(os.path.getsize(p) == 200000 for p in glob.glob(f"{f7.local}/*.bin")),
      "no half-written file in the folder")
os.makedirs(f"{f7.local}/.kluis-part/123", exist_ok=True)
write(f"{f7.local}/.kluis-part/123/big0.bin", "half")
eng.sync(f7)
check(not os.path.exists(f"{f7.local}/.kluis-part") and not os.path.exists(f"{CLOUD}/Seven/.kluis-part"),
      "a crash leftover is cleared on the next run and never uploaded")

# ---------------------------------------------------------------- 8
print("8 · mass-deletion guard")
f8 = folder("Agriland")
os.makedirs(f8.local, exist_ok=True)
for i in range(400):
    with open(f"{f8.local}/doc{i:03}.txt", "w") as fh:
        fh.write(str(i))
eng.sync(f8)
for i in range(312):
    os.remove(f"{f8.local}/doc{i:03}.txt")
r = eng.sync(f8)
check(r.status == "guard" and r.pending_trash == 312 and len(os.listdir(f"{CLOUD}/Agriland")) == 400,
      "312 deletions pause the folder and move nothing")
check("Kluis is about to move 312 files from Agriland to the trash" in r.message, "the dialog text names count and folder")
r = eng.sync(f8, allow_trash=312)
check(r.status == "ok" and len(os.listdir(f"{CLOUD}/Agriland")) == 88, "after “Move them to the trash” it goes ahead")

# ---------------------------------------------------------------- 9
print("9 · missing-folder guard")
f9 = folder("Drive")
for i in range(5):
    write(f"{f9.local}/x{i}.txt", "x")
eng.sync(f9)
shutil.move(f9.local, f9.local + "-unplugged")
r = eng.sync(f9)
check(r.status == "missing" and r.message.startswith("Folder not found:") and len(os.listdir(f"{CLOUD}/Drive")) == 5,
      "vanished folder pauses with “Folder not found…”; nothing trashed remotely")
os.makedirs(f9.local)                       # empty mount point left behind by an unplugged drive
r = eng.sync(f9)
check(r.status == "missing" and len(os.listdir(f"{CLOUD}/Drive")) == 5, "empty mount point is not “everything deleted”")
os.rmdir(f9.local)
shutil.move(f9.local + "-unplugged", f9.local)
check(eng.sync(f9).status == "ok", "syncs normally once the drive is back")

# ---------------------------------------------------------------- 10
print("10 · offline, disk full, signed out: pause and back off, no retry storm")
from kluis.errors import backoff_delay  # noqa: E402
f10 = folder("Ten")
for i in range(80):
    os.makedirs(f"{f10.local}/sub{i % 4}", exist_ok=True)
    with open(f"{f10.local}/sub{i % 4}/n{i}.txt", "w") as fh:
        fh.write("n")
harness.flag(TMP, "offline")
n0 = len(harness.calls(TMP))
r = eng.sync(f10)
n_calls = len(harness.calls(TMP)) - n0
check(r.status == "hold" and r.hold_kind == "offline", "offline → hold “offline”")
check(n_calls <= 2, f"the run stops at the first network failure ({n_calls} CLI call(s), no storm)")
harness.flag(TMP, "offline", False)
r = eng.sync(f10)
check(r.status == "ok" and len(store.load(f10.id)) >= 80, "resumes when back online")
dups = [n for n in glob.glob(f"{CLOUD}/Ten/**", recursive=True) if re.search(r" \(\d+\)\.txt$", n)]
check(not dups, "no duplicate files after the outage")
delays = [backoff_delay(i) for i in range(8)]
check(delays[:3] == [30, 60, 120] and max(delays) == 900 and delays == sorted(delays), "backoff 30 s → … → max 15 min")
write(f"{CLOUD}/Ten/fresh.txt", "f")
harness.flag(TMP, "diskfull")
r = eng.sync(f10)
harness.flag(TMP, "diskfull", False)
check(r.status == "hold" and r.hold_kind == "disk-full", "disk full → hold “disk-full”")
check(not os.path.exists(f"{f10.local}/fresh.txt"), "nothing half-written while the disk is full")
os.remove(os.path.join(TMP, "cloud", ".logged_in"))
r = eng.sync(f10)
check(r.status == "hold" and r.hold_kind == "signed-out", "expired sign-in → hold “signed-out”")
open(os.path.join(TMP, "cloud", ".logged_in"), "w").close()
from gi.repository import GLib  # noqa: E402,F401
s10 = Settings()
s10.save = lambda *a, **k: None
m10 = SyncManager(s10, cli, store=store, start_thread=False)
m10.set_hold("offline")
d1 = m10.hold["until"] - time.time()
m10.set_hold("offline")
d2 = m10.hold["until"] - time.time()
check(d2 > d1 * 1.5 and m10.hold["attempt"] == 1, "repeated failures double the wait")

# ---------------------------------------------------------------- 11
print("11 · config writes are atomic with a backup")
cfg = os.path.join(TMP, "cfg.json")
a = Settings()
a.interval_minutes = 30
a.save(cfg)
a.interval_minutes = 60
a.save(cfg)
check(os.path.exists(cfg + ".bak") and json.load(open(cfg + ".bak"))["interval_minutes"] == 30, ".bak keeps the previous file")
open(cfg, "w").write("{ broken")
b = Settings.load(cfg)
check(b.interval_minutes == 30, "corrupt config → starts from the backup")
check(not glob.glob(cfg + ".tmp"), "no temp file left behind")

# ---------------------------------------------------------------- 12
print("12 · capability self-test gates every CLI binary")
from kluis import capabilities  # noqa: E402
ok, probs = capabilities.self_test(harness.MOCK)
check(ok, f"current mock CLI passes ({probs})")
os.environ["MOCK_INCOMPATIBLE"] = "1"
ok, probs = capabilities.self_test(harness.MOCK)
os.environ.pop("MOCK_INCOMPATIBLE")
check(not ok and any("restore" in p for p in probs), "a CLI without a needed command fails")
from kluis import cliupdate  # noqa: E402
from kluis.cli import ChecksumMismatch, download_cli, platform_key  # noqa: E402
bindir = os.path.join(TMP, "bin")
os.makedirs(bindir)
shutil.copy(harness.MOCK, os.path.join(bindir, "proton-drive"))
old_sha = hashlib.sha1(open(os.path.join(bindir, "proton-drive"), "rb").read()).hexdigest()
newbin = os.path.join(TMP, "new-proton-drive")
shutil.copy(harness.MOCK, newbin)


def manifest(path, sha=None, version="0.9.1"):
    sha = sha or hashlib.sha512(open(path, "rb").read()).hexdigest()
    mf = os.path.join(TMP, "version.json")
    json.dump({"Releases": [{"Version": version, "CategoryName": "Stable",
                             "Files": [{"Platform": platform_key(), "Url": "file://" + path, "Sha512CheckSum": sha}]}]},
              open(mf, "w"))
    os.environ["KLUIS_TEST_MANIFEST"] = "file://" + mf


manifest(newbin, sha="ab" * 64)
try:
    download_cli(dest_dir=bindir)
    raised = False
except ChecksumMismatch:
    raised = True
check(raised and not os.path.exists(os.path.join(bindir, ".proton-drive.download")),
      "checksum mismatch: download deleted, nothing switched")
open(newbin, "w").write(open(harness.MOCK).read().replace(
    'print(text)\n        return', 'print(text.replace("filesystem restore path...", ""))\n        return'))
manifest(newbin)
st = Settings()
c2 = ProtonDriveCli(os.path.join(bindir, "proton-drive"))
r = cliupdate.check_and_update(st, c2, signed_in=True, force=True, dest_dir=bindir)
now_sha = hashlib.sha1(open(os.path.join(bindir, "proton-drive"), "rb").read()).hexdigest()
check(r.status == "incompatible" and now_sha == old_sha and "Proton changed its Drive tool" in r.message,
      "incompatible new CLI: previous binary kept, one notice")
r = cliupdate.check_and_update(st, c2, signed_in=True, force=False, dest_dir=bindir)
check(r.status in ("incompatible", "skipped") and not r.message, "no second notice for the same version")
open(newbin, "w").write(open(harness.MOCK).read().replace('or "0.9.0"', 'or "0.9.1"'))
os.chmod(newbin, 0o755)
manifest(newbin)
r = cliupdate.check_and_update(st, c2, signed_in=True, force=True, dest_dir=bindir)
check(r.status == "updated" and "0.9.1" in c2.version(), "compatible new CLI is switched to atomically")
os.environ.pop("KLUIS_TEST_MANIFEST")

# ---------------------------------------------------------------- 13
print("13 · no network calls except the CLI, proton.me and GitHub releases")
allowed = {"https://proton.me/download/drive/cli/version.json", "https://proton.me/download/drive/cli/index.html",
           "https://api.github.com/repos/Sundowna/kluis/releases", "https://github.com/Sundowna/kluis/releases",
           "https://drive.proton.me/", "https://drive.proton.me/photos", "https://proton.me/", "https://proton.me"}
found = set()
for p in glob.glob(os.path.join(harness.REPO, "kluis", "**", "*.py"), recursive=True):
    for u in re.findall(r"https?://[^\s\"')]+", open(p).read()):
        found.add(u.rstrip(".,"))
net_code = [u for u in found if u not in allowed and not u.startswith(("http://127.0.0.1", "https://proton.me/download"))]
check(not net_code, f"only allowed URLs in the code ({net_code})")
connects = []
real_connect = socket.socket.connect


def spy(self, addr):
    if self.family != socket.AF_UNIX:
        connects.append(addr)
    return real_connect(self, addr)


socket.socket.connect = spy
write(f"{f1.local}/net.txt", "n")
eng.sync(f1)
from kluis import diagnostics, status  # noqa: E402,F401
diagnostics.collect(Settings(), "0.9.0")
socket.socket.connect = real_connect
check(not connects, "a full sync run and diagnostics open no network sockets in Kluis itself")

print(f"\n{check.passed} checks passed")
harness.cleanup(TMP)

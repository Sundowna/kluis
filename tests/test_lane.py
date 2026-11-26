"""The big-items lane (kluis/lane.py) against the mock CLI: big files and big folders sync next to the rest,
can be paused, resumed and sent first. Run: python3 tests/test_lane.py"""
import os
import shutil
import sys
import time
from dataclasses import asdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness  # noqa: E402

TMP = harness.setup("kluis-lane-")
os.environ["KLUIS_BIG_BYTES"] = "1000"          # "big" = 1000 bytes here, 1 GB in real use
os.environ["MOCK_SLOW_DELAY"] = "3"

from kluis.cli import ProtonDriveCli  # noqa: E402
from kluis.config import PART_DIR, FolderPair, Settings  # noqa: E402
from kluis.engine import SyncEngine, is_held, split_big  # noqa: E402
from kluis.lane import BigLane  # noqa: E402
from kluis.state import StateStore  # noqa: E402

CLOUD = os.path.join(TMP, "cloud", "my-files")
cli = ProtonDriveCli(harness.MOCK)
store = StateStore(os.path.join(TMP, "state.sqlite"))
settings = Settings()
logs = []
done_for = []
lane = BigLane(settings, cli.sibling, lambda: store, on_log=lambda *a: logs.append(a),
               on_done=done_for.append, start_thread=False)
eng = SyncEngine(cli, store)
eng.defer, eng.held = lane.add, lane.held
passed = 0


def write(path, size_or_text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = size_or_text if isinstance(size_or_text, str) else "x" * size_or_text
    with open(path, "w") as f:
        f.write(data)


def check(cond, msg):
    global passed
    if not cond:
        print("FAIL:", msg)
        sys.exit(1)
    passed += 1
    print("  ok -", msg)


def run_next():
    """What the lane's thread does for one item."""
    it = lane.items[0]
    lane.current = it
    try:
        return lane.run_item(it)
    finally:
        lane.items.remove(it)
        lane.current = None


print("which items are big")
sizes = {"a.zip": 5000, "notes.txt": 10, "top.jpg": 600, "top2.jpg": 600,
         "photos/2023/a.jpg": 400, "photos/2023/b.jpg": 400, "photos/2023/c.jpg": 400,
         "photos/2024/x.jpg": 300, "photos/2024/y.jpg": 300, "photos/2025/z.jpg": 500,
         "docs/cv.pdf": 50}
small, items = split_big(sorted(sizes), sizes.get, 1000)
names = sorted((it[0], it[1]) for it in items)
check(("a.zip", False) in names, "F-036 a file of the big size is a big item on its own")
check(("photos/2023", True) in names, "F-036 a folder with that much to transfer is one big item")
check(("photos", True) in names and sorted(dict((i[0], i[2]) for i in items)["photos"]) ==
      ["photos/2024/x.jpg", "photos/2024/y.jpg", "photos/2025/z.jpg"],
      "F-036 small subfolders that add up count towards their parent folder (deepest folder first)")
check(sorted(small) == ["docs/cv.pdf", "notes.txt", "top.jpg", "top2.jpg"],
      f"F-036 small files, and files directly in the synced folder, stay in the normal sync ({small})")
check(is_held("photos/2023/a.jpg", ["photos/"]) and not is_held("photos2/a.jpg", ["photos/"])
      and is_held("a.zip", ["a.zip"]) and not is_held("a.zip.bak", ["a.zip"]), "held paths match exactly")

print("uploads")
L = os.path.join(TMP, "home", "Backups")
write(f"{L}/notes.txt", "hello")
write(f"{L}/backup.zip", 3000)
write(f"{L}/fotos/2023/a.jpg", 400)
write(f"{L}/fotos/2023/b.jpg", 400)
write(f"{L}/fotos/2023/c.jpg", 400)
write(f"{L}/fotos/klein.jpg", 50)
f = FolderPair(local=L, remote="/my-files/Backups", mode="two-way")
settings.folders.append(f)
r = eng.sync(f)
check(r.status == "ok" and r.deferred == 2, f"F-036 the run hands 2 big items to the lane ({r.message})")
check("big-items lane" in r.message, "F-036 the run says so")
check(os.path.exists(f"{CLOUD}/Backups/notes.txt") and os.path.exists(f"{CLOUD}/Backups/fotos/klein.jpg"),
      "F-036 small files are uploaded by the normal sync straight away")
check(not os.path.exists(f"{CLOUD}/Backups/backup.zip") and not os.path.exists(f"{CLOUD}/Backups/fotos/2023/a.jpg"),
      "F-036 big items are not uploaded by the normal sync")
check(sorted(it.rel for it in lane.items) == ["backup.zip", "fotos/2023"], "both are waiting in the lane")
r = eng.sync(f)
check(r.message == "Up to date" and len(lane.items) == 2 and r.held == 4,
      f"F-036 the next sync leaves items in the lane alone, no doubles ({r.message}, held {r.held})")
r1 = run_next()
check(r1.uploaded == 1 and os.path.getsize(f"{CLOUD}/Backups/backup.zip") == 3000, "F-036 the lane uploads the big file")
check(any(a[0] == "ok" and "backup.zip" in a[2] for a in logs), "F-036 Activity says it was uploaded")
check(done_for == [f.id], "a finished item asks for a fresh look at its folder")
run_next()
check(all(os.path.exists(f"{CLOUD}/Backups/fotos/2023/{n}.jpg") for n in "abc"), "F-036 the lane uploads the big folder")
check(eng.sync(f).message == "Up to date" and not lane.items, "F-036 afterwards everything is recorded: up to date")

print("pause, resume, send first")
write(f"{L}/backup2.zip", 2000)
write(f"{L}/backup3.zip", 2000)
write(f"{L}/backup4.zip", 2000)
r = eng.sync(f)
check([it.rel for it in lane.items] == ["backup2.zip", "backup3.zip", "backup4.zip"], "three big items wait in order")
key = lambda rel: (f.id, "up", rel)  # noqa: E731
check(lane.send_first(key("backup4.zip")) and lane.items[0].rel == "backup4.zip", "F-038 Send first puts it at the front")
check(not lane.pause(key("nope")), "pausing something that isn't there does nothing")
lane.pause(key("backup3.zip"))
check("backup3.zip" in f.held and [it.rel for it in lane.items] == ["backup4.zip", "backup2.zip"],
      "F-037 a paused item leaves the lane and is remembered on the folder (kept over a restart)")
check(Settings.from_dict(asdict(settings)).folders[0].held == ["backup3.zip"],
      "F-037 the paused list survives saving and loading the settings")
run_next()
run_next()
r = eng.sync(f)
check(not os.path.exists(f"{CLOUD}/Backups/backup3.zip") and r.message == "Up to date" and not lane.items,
      f"F-037 a paused item stays out of every sync ({r.message})")
os.remove(f"{L}/backup2.zip")
r = eng.sync(f, allow_trash=1)               # 1 of a few files trips the 10 % guard: confirmed
check(not os.path.exists(f"{CLOUD}/Backups/backup2.zip"), "deleting a synced big file still reaches Proton Drive")
check(lane.paused_list()[0][1] == "backup3.zip" and lane.paused_list()[0][2].bytes == 2000,
      "F-037 the paused list knows the item's size")
check(lane.resume(f.id, "backup3.zip") and not f.held, "F-037 Resume takes it back")
r = eng.sync(f)
check(r.deferred == 1 and lane.items[0].rel == "backup3.zip", "F-037 the next sync sends it to the lane again")
run_next()
check(os.path.exists(f"{CLOUD}/Backups/backup3.zip"), "F-037 and it's uploaded")

print("a paused item is never trashed")
lane.items.clear()
write(f"{L}/old.zip", 1500)
eng.sync(f)
run_next()
lane.paused[(f.id, "old.zip")] = None
f.held.append("old.zip")
os.remove(f"{CLOUD}/Backups/old.zip")
r = eng.sync(f)
check(os.path.exists(f"{L}/old.zip"), "F-037 deleted in Proton Drive while paused: the local copy is left alone")
f.held.append("fotos/")
os.remove(f"{CLOUD}/Backups/fotos/klein.jpg")
shutil.rmtree(f"{CLOUD}/Backups/fotos")
r = eng.sync(f)
check(os.path.exists(f"{L}/fotos/2023/a.jpg"), "F-037 a paused folder isn't trashed either")
f.held.clear()
lane.paused.clear()
shutil.rmtree(f"{L}/fotos")
os.remove(f"{L}/old.zip")
eng.sync(f)                                  # gone on both sides now: forgotten

print("downloads")
D = os.path.join(TMP, "home", "Sister")
write(f"{CLOUD}/Sister/readme.txt", "hi")
for n in range(5):
    write(f"{CLOUD}/Sister/Vakantie/IMG_{n}.jpg", 300)
write(f"{CLOUD}/Sister/film.mp4", 1200)
fd = FolderPair(local=D, remote="/my-files/Sister", mode="mirror")
settings.folders.append(fd)
r = eng.sync(fd)
check(r.deferred == 2 and os.path.exists(f"{D}/readme.txt") and not os.path.exists(f"{D}/film.mp4"),
      f"F-036 downloads: a big folder of photos and a big file go to the lane ({r.message})")
while lane.items:
    run_next()
check(all(os.path.getsize(f"{D}/Vakantie/IMG_{n}.jpg") == 300 for n in range(5)) and
      os.path.getsize(f"{D}/film.mp4") == 1200, "F-036 the lane downloads them, complete")
check(not os.path.exists(os.path.join(D, PART_DIR)), "no staging folder is left behind")
check(eng.sync(fd).message == "Up to date", "and the folder is up to date")

print("side by side (threads, slow mock transfers)")
lane2 = BigLane(settings, cli.sibling, lambda: store, on_log=lambda *a: logs.append(a))
eng.defer, eng.held = lane2.add, lane2.held
write(f"{L}/SLOW-image.iso", 2000)
t0 = time.time()
eng.sync(f)                                  # hands it over, returns at once
check(time.time() - t0 < 2.5, "F-036 the normal run doesn't wait for the big file")
for _ in range(50):
    if lane2.current is not None:
        break
    time.sleep(0.1)
check(lane2.current is not None and lane2.current.state == "running", "the lane is transferring it")
write(f"{L}/small-while-big.txt", "quick")
t1 = time.time()
r = eng.sync(f)
check(os.path.exists(f"{CLOUD}/Backups/small-while-big.txt") and lane2.current is not None,
      f"F-036 a small file goes through while the big one is still uploading ({time.time() - t1:.1f} s)")
for _ in range(100):
    if not lane2.busy:
        break
    time.sleep(0.1)
check(os.path.exists(f"{CLOUD}/Backups/SLOW-image.iso"), "the big one arrives afterwards")

print("pausing a running item")
write(f"{L}/SLOW-second.iso", 2000)
os.environ["MOCK_SLOW_DELAY"] = "20"
eng.sync(f)
for _ in range(50):
    if lane2.current is not None:
        break
    time.sleep(0.1)
time.sleep(0.5)
t0 = time.time()
logs.clear()
check(lane2.pause((f.id, "up", "SLOW-second.iso")), "F-037 pausing the item being uploaded says it restarts later")
for _ in range(100):
    if lane2.current is None:
        break
    time.sleep(0.1)
check(lane2.current is None and time.time() - t0 < 8, f"F-037 its transfer stops at once ({time.time() - t0:.1f} s)")
check(not os.path.exists(f"{CLOUD}/Backups/SLOW-second.iso") and "SLOW-second.iso" in f.held,
      "F-037 nothing half-uploaded, and it is paused")
check(not any(a[0] == "ok" for a in logs) and any("Paused" in a[2] for a in logs),
      "F-037 Activity says paused, not uploaded")
lane2.shutdown()

print(f"\n{passed} checks passed")
shutil.rmtree(TMP, ignore_errors=True)

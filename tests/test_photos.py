"""Proton Photos scenarios against the mock CLI. Run: python3 tests/test_photos.py"""
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
# inside the home folder, like real synced folders, so the home Trash is on the same drive
_base = os.path.join(os.path.expanduser("~"), ".cache")
os.makedirs(_base, exist_ok=True)
TMP = tempfile.mkdtemp(prefix="kluis-photos-", dir=_base)
for k, v in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state")):
    os.environ[k] = os.path.join(TMP, v)
os.environ["MOCK_ROOT"] = os.path.join(TMP, "cloud")
os.makedirs(os.environ["MOCK_ROOT"])
open(os.path.join(TMP, "cloud", ".logged_in"), "w").close()
sys.path.insert(0, os.path.dirname(HERE))

from kluis.cli import ProtonDriveCli  # noqa: E402
from kluis.config import PhotoSettings  # noqa: E402
from kluis.photos import PhotoSync  # noqa: E402
from kluis.state import StateStore  # noqa: E402

cli = ProtonDriveCli(os.path.join(HERE, "mock_cli", "proton-drive"))
store = StateStore(os.path.join(TMP, "s.sqlite"))
ps_sync = PhotoSync(cli, store)
n = 0


def check(c, m):
    global n
    if not c:
        print("FAIL:", m)
        sys.exit(1)
    n += 1
    print("  ok -", m)


def make(path, content, when):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(content)
    os.utime(path, (when, when))


# "phone" uploads: two different IMG_0001.jpg from two phones, a video, different months
PHONE = os.path.join(TMP, "phone")
make(f"{PHONE}/a/IMG_0001.jpg", "phone A beach", 1761955200)    # 2025-11-01
make(f"{PHONE}/b/IMG_0001.jpg", "phone B dinner", 1762041600)   # 2025-11-02
make(f"{PHONE}/a/VID_0002.mp4", "video", 1763251200)            # 2025-11-16
make(f"{PHONE}/a/IMG_0100.jpg", "summer", 1751328000)           # 2025-07-01
cli.photo_upload([f"{PHONE}/a/IMG_0001.jpg", f"{PHONE}/b/IMG_0001.jpg", f"{PHONE}/a/VID_0002.mp4",
                  f"{PHONE}/a/IMG_0100.jpg"])
tl = cli.photo_timeline()
check(len(tl) == 4 and tl[0].name == "VID_0002.mp4" and tl[0].is_video, "timeline read, newest first")
summer = next(p for p in tl if p.name == "IMG_0100.jpg")
json.dump({"alb1": {"name": "Holiday", "photos": [summer.uid]}},
          open(os.path.join(TMP, "cloud", "albums.json"), "w"))

print("download")
LOCAL = os.path.join(TMP, "Pictures", "Proton Photos")
ps = PhotoSettings(download=True, download_dir=LOCAL, albums=True)
r = ps_sync.sync(ps)
check(r.status == "ok" and r.downloaded == 5, f"timeline + album saved ({r.message})")
nov = sorted(os.listdir(f"{LOCAL}/2025/2025-11"))
check(nov == ["IMG_0001 (1).jpg", "IMG_0001.jpg", "VID_0002.mp4"], f"month folders, same names kept apart {nov}")
check(os.path.exists(f"{LOCAL}/2025/2025-07/IMG_0100.jpg"), "July photo in its own month")
check(os.path.exists(f"{LOCAL}/Albums/Holiday/IMG_0100.jpg"), "album saved as a folder")
check(ps.count == 4, "photo count recorded")
r = ps_sync.sync(ps)
check(r.message == "Up to date" and r.downloaded == 0, "second run downloads nothing")

os.remove(f"{LOCAL}/2025/2025-11/VID_0002.mp4")
r = ps_sync.sync(ps)
check(not os.path.exists(f"{LOCAL}/2025/2025-11/VID_0002.mp4"), "deleting a local copy is respected")

store.photos_reset()
r = ps_sync.sync(ps)
check(sorted(os.listdir(f"{LOCAL}/2025/2025-11")).count("IMG_0001.jpg") == 1
      and not any("(2)" in f for f in os.listdir(f"{LOCAL}/2025/2025-11")),
      f"after a reset, existing identical files are recognised, not duplicated ({r.message})")

print("upload")
CAM = os.path.join(TMP, "Pictures")
make(f"{CAM}/Camera/new1.jpg", "new photo", 1763337600)
make(f"{CAM}/Camera/notes.txt", "not media", 1763337600)
make(f"{CAM}/Camera/IMG_0001.jpg", "phone A beach", 1761955200)   # already in Proton Photos
ps2 = PhotoSettings(download=True, download_dir=LOCAL, upload=True, upload_dir=CAM)
r = ps_sync.sync(ps2)
check(r.status == "ok" and r.uploaded == 1, f"only the new photo is added ({r.message})")
check(len(cli.photo_timeline()) == 5, "timeline grew by one, no duplicate, downloaded copies not re-uploaded")
r = ps_sync.sync(ps2)
check(r.uploaded == 0, "uploads are remembered")

print(f"\n{n} checks passed")
shutil.rmtree(TMP, ignore_errors=True)

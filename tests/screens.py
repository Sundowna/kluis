"""Drive the real UI under Xvfb with the mock CLI and save screenshots. Dev-only."""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kluis-shots"
SCENARIO = sys.argv[2] if len(sys.argv) > 2 else "main"
os.environ.setdefault("XDG_CACHE_HOME", os.path.join(tempfile.gettempdir(), "kluis-cache-test"))
os.makedirs(OUT, exist_ok=True)
TMP = tempfile.mkdtemp(prefix="kluis-ui-")
HOME = os.path.join(TMP, "home")
for k, v in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"), ("XDG_STATE_HOME", "state")):
    os.environ[k] = os.path.join(TMP, v)
os.environ["MOCK_ROOT"] = os.path.join(TMP, "cloud")
os.environ["MOCK_DELAY"] = "0.6"
sys.path.insert(0, os.path.dirname(HERE))
CLI = os.path.join(HERE, "mock_cli", "proton-drive")


def w(p, t="x" * 2000):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(t)


for n in ("Q3 report.pdf", "budget.ods", "notes/ideas.md", "notes/2026-11-17.md"):
    w(f"{HOME}/Documents/{n}")
for n in ("trip/IMG_0001.jpg", "trip/IMG_0002.jpg"):
    w(f"{HOME}/Pictures/{n}")
w(f"{HOME}/Vault/index.md")
for n in ("Invoices/2026-10.pdf", "Invoices/2026-11.pdf", "Contracts/lease.pdf", "photo.jpg", "readme.txt"):
    w(f"{TMP}/cloud/my-files/{n}")
w(f"{TMP}/cloud/my-files/Team/plan.md")

from kluis.config import FolderPair, PhotoSettings, Settings  # noqa: E402
from kluis.paths import ensure_dirs  # noqa: E402

ensure_dirs()
s = Settings(cli_path=CLI, autostart=False, onboarded=SCENARIO != "welcome")
if SCENARIO != "welcome":
    s.folders = [FolderPair(local=f"{HOME}/Documents", remote="/my-files/Documents"),
                 FolderPair(local=f"{HOME}/Pictures", remote="/my-files/Backups/Pictures", mode="backup"),
                 FolderPair(local=f"{HOME}/Team", remote="/my-files/Team", mode="mirror"),
                 FolderPair(local=f"{HOME}/Vault", remote="/my-files/Vault", enabled=False)]
    os.makedirs(os.path.join(TMP, "cloud"), exist_ok=True)
    open(os.path.join(TMP, "cloud", ".logged_in"), "w").close()
if SCENARIO == "photos":
    s.folders = s.folders[:1]
    seed = os.path.join(TMP, "seed")
    os.makedirs(seed)
    colors = ["#e76f51", "#2a9d8f", "#e9c46a", "#264653", "#f4a261", "#8ab17d", "#6d597a", "#b56576",
              "#355070", "#eaac8b", "#457b9d", "#a8dadc", "#f28482", "#84a59d"]
    for i, c in enumerate(colors):
        f = os.path.join(seed, f"IMG_{2000 + i}.jpg")
        subprocess.run(["convert", "-size", "320x240", f"gradient:{c}-white", "-fill", "white", "-draw",
                        f"circle {80 + i * 12},{90 + (i % 3) * 30} {110 + i * 12},{100 + (i % 3) * 30}", f], check=True)
        t = 1763337600 - i * 86400 * 4
        os.utime(f, (t, t))
    for j, (src, t) in enumerate((("testsrc2", 3600), ("mandelbrot", 86400 * 9))):
        v = os.path.join(seed, f"VID_{2100 + j}.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"{src}=size=320x240:rate=10",
                        "-t", "2", "-pix_fmt", "yuv420p", v], check=True)
        os.utime(v, (1763337600 - t, 1763337600 - t))
    subprocess.run([CLI, "photo", "upload", seed, "--json"], check=True, capture_output=True)
    s.photos = PhotoSettings(download=os.environ.get("PHOTO_LOCAL") == "1",
                             download_dir=f"{HOME}/Pictures/Proton Photos")
s.save()

from gi.repository import GLib  # noqa: E402

from kluis.app import KluisApp  # noqa: E402

app = KluisApp()
steps = []


def shot(name):
    def go():
        subprocess.run(["import", "-window", "root", os.path.join(OUT, f"{name}.png")], check=False)
        return False
    return go


def page(name):
    def go():
        app.window.stack.set_visible_child_name(name)
        return False
    return go


if SCENARIO == "welcome":
    steps = [(2500, shot("01-welcome")),
             (2600, lambda: (app.window.onboarding.refresh("signed-out"), False)[1]),
             (3200, shot("02-signin")),
             (3300, lambda: (open(os.path.join(TMP, "cloud", ".logged_in"), "w").close(), app.recheck(), False)[2]),
             (6000, shot("03-choose"))]
elif SCENARIO == "photos":
    steps = [(12000, page("photos")),
             (12200, lambda: (app.window.photos.load(), False)[1]),
             (16000, shot("20-photos")),
             (16100, lambda: (app.window.photos.get_vadjustment().set_value(400), False)[1]),
             (17000, shot("21-photos-gallery"))]
else:
    steps = [(2200, shot("10-syncing")),
             (16000, shot("11-folders")),
             (16100, page("browse")),
             (19000, shot("12-browse")),
             (19100, page("activity")),
             (19600, shot("13-activity")),
             (19700, page("folders")),
             (19800, lambda: (GLib.idle_add(app.add_folder_dialog, f"{HOME}/Vault2"), False)[1]),
             ]
    os.makedirs(f"{HOME}/Vault2", exist_ok=True)


def dialog_shot():
    subprocess.run(["import", "-window", "root", os.path.join(OUT, "14-add-folder.png")])
    for wdw in __import__("gi.repository.Gtk", fromlist=["Gtk"]).Window.list_toplevels():
        if wdw.get_title() == "Add a folder to sync":
            wdw.response(-6)
    return False


def finish():
    app.quit_app()
    return False


def start(_a):
    for ms, fn in steps:
        GLib.timeout_add(ms, fn)
    if SCENARIO == "main":
        GLib.timeout_add(21500, dialog_shot)
    GLib.timeout_add({"welcome": 7000, "photos": 18000}.get(SCENARIO, 23000), finish)


app.connect("activate", start)
app.run([])
shutil.rmtree(TMP, ignore_errors=True)

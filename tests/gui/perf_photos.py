"""Photos gallery with 50'000 photos (HANDOVER §8 B.5): smooth scrolling and memory < 400 MB.

Run: xvfb-run -a -s "-screen 0 1440x900x24" dbus-run-session -- python3 tests/gui/perf_photos.py
Measures the time to scroll one wheel step *and draw the frame*, top to bottom, with previews arriving.
"""
import os
import resource
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from driver import Env  # noqa: E402

env = Env(theme="dark", size=(1440, 900))
import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import GdkPixbuf, Gtk  # noqa: E402

from kluis.cli import PhotoItem  # noqa: E402
from kluis.ui.photos import Gallery  # noqa: E402
from kluis.ui.theme import Theme  # noqa: E402

N = 50_000
items = []
for k in range(N):
    y, m, d = 2014 + (k // 4200), (k // 350) % 12 + 1, k % 28 + 1
    items.append(PhotoItem(uid=f"u{k}", name=f"IMG_{k:05d}.jpg", captured=f"{y}-{m:02d}-{d:02d}T10:00:00Z",
                           media_type="video/mp4" if k % 17 == 0 else "image/jpeg"))


class FakeApp:
    def __init__(self):
        self.theme = Theme()
        self.theme.apply("dark")


class FakePage:
    def __init__(self):
        self.app = FakeApp()
        self.requested = 0

        class T:
            def request(_s, p, lp):
                self.requested += 1
                pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 128, 128)
                pb.fill(0x55AA88FF)
                gal.preview_ready(p.uid, pb)            # previews arrive immediately (worst case for memory)
        self.thumbs = T()

    def local_paths(self):
        return {}

    def sel_changed(self):
        pass

    def open_photo(self, p):
        pass


page = FakePage()
win = Gtk.Window()
win.set_default_size(1100, 700)
gal = Gallery(page)
win.add(gal)
win.show_all()
for _ in range(50):
    while Gtk.events_pending():
        Gtk.main_iteration()
    time.sleep(0.01)
t0 = time.monotonic()
gal.set_photos(items)
for _ in range(10):
    while Gtk.events_pending():
        Gtk.main_iteration()
load_s = time.monotonic() - t0
months = gal.month_count()
frames = []
steps = 0
while gal.adj.get_value() < gal.adj.get_upper() - gal.adj.get_page_size() - 1 and steps < 4000:
    t = time.monotonic()
    gal.scroll_by(120 * 8)       # a fast wheel flick: 8 notches per frame
    win.get_window().process_updates(True)
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)
    frames.append(time.monotonic() - t)
    steps += 1
rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
frames.sort()
avg = sum(frames) / len(frames) * 1000
p95 = frames[int(len(frames) * 0.95)] * 1000
print(f"{N} photos, {months} months, layout {load_s * 1000:.0f} ms, {steps} frames: avg {avg:.1f} ms, "
      f"p95 {p95:.1f} ms, peak RSS {rss_mb:.0f} MB, previews requested {page.requested}")
ok = avg < 16.7 and p95 < 33 and rss_mb < 400 and abs(gal.ring() - (months - 1)) < 1e-6
print("PASS" if ok else "FAIL")
env.cleanup()
sys.exit(0 if ok else 1)

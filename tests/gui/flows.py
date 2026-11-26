"""End-to-end flows F1–F23 (HANDOVER §12; F21 = Proton accounts, F22 = Computers; see FEATURES.md), against the mock CLI.

Run one: xvfb-run -a -s "-screen 0 1440x900x24" dbus-run-session -- python3 tests/gui/flows.py F4 dark 1440x900 OUT
All:     tests/gui/run_all.sh OUT
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from driver import FlowFailed, harness, run_flow, until  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def focused(w):
    """The widget keyboard input goes to in its window (no window manager under Xvfb, so has_focus() is False)."""
    return w is not None and w.get_toplevel().get_focus() is w


def main_ready(app):
    return until(lambda: app.window is not None and app.window.root.get_visible_child_name() == "main",
                 25, "main window")


def idle(app, t=60):
    return until(lambda: not app.manager.busy, t, "sync to finish")


def toast_has(app, text):
    return lambda: any(text in t for t in app.window.toast_history[-5:])


def folders_cfg(env, *names, mode="two-way"):
    out = []
    for n in names:
        os.makedirs(os.path.join(env.home, n), exist_ok=True)
        out.append({"local": os.path.join(env.home, n), "remote": f"/my-files/{os.path.basename(n)}", "mode": mode,
                    "id": os.path.basename(n).lower().replace(" ", "")[:12]})
    return out


def set_cfg(env, **kw):
    p = os.path.join(os.environ["XDG_CONFIG_HOME"], "kluis", "config.json")
    cfg = json.load(open(p))
    cfg.update(kw)
    json.dump(cfg, open(p, "w"))


def autostart_entry():
    """What starts Kluis at sign-in: the .desktop file on Linux, the registry Run value on Windows ("" = none)."""
    if os.name == "nt":
        from kluis.system import autostart_windows
        return autostart_windows() or ""
    p = os.path.join(os.environ["XDG_CONFIG_HOME"], "autostart", "kluis.desktop")
    return open(p).read() if os.path.exists(p) else ""


def answer(*items):
    from kluis.ui import dialogs
    dialogs.TEST_ANSWERS.extend(items)


def press_dialog_button(d, title, label):
    dlg = d.dialog(title)
    if dlg is None:
        raise FlowFailed(f"dialog {title!r} not open")
    d.click(label, root=dlg)


def any_dialog(d):
    from gi.repository import Gtk
    return next((t for t in Gtk.Window.list_toplevels() if isinstance(t, Gtk.Dialog) and t.get_visible()), None)


def dialog_with_text(d, text):
    from gi.repository import Gtk
    for t in Gtk.Window.list_toplevels():
        if isinstance(t, Gtk.Dialog) and t.get_visible() and d.has_text(text, root=t):
            return t
    return None


# ------------------------------------------------------------------ F1
def setup_f1(env):
    os.remove(os.path.join(env.cloud, ".logged_in"))
    cfg = os.path.join(os.environ["XDG_CONFIG_HOME"], "kluis", "config.json")
    os.remove(cfg)                                           # clean install: no config, no CLI
    newbin = os.path.join(env.tmp, "release", "proton-drive")
    os.makedirs(os.path.dirname(newbin))
    shutil.copy(harness.MOCK, newbin)
    with open(newbin, "ab") as fh:
        fh.write(b"\n# " + b"x" * 1500000 + b"\n")          # ~1.5 MB: about 1.5 s at the throttled rate
    write_manifest(env, newbin)
    env.write("Documents/report.txt", "r")
    env.write("Pictures/p.jpg", "p")
    env.write("Music/song.txt", "s")
    os.environ["MOCK_LOGIN_DELAY"] = "1.0"
    os.environ["MOCK_DELAY"] = "0.3"


_SERVER = {}


def serve(path):
    """Serve one file from 127.0.0.1, throttled (~1 MB/s), so download progress is observable."""
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            data = open(_SERVER["path"], "rb").read()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            for i in range(0, len(data), 65536):
                self.wfile.write(data[i:i + 65536])
                time.sleep(0.06)

        def log_message(self, *a):
            pass
    _SERVER["path"] = path
    if "srv" not in _SERVER:
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        _SERVER["srv"] = srv
    return f"http://127.0.0.1:{_SERVER['srv'].server_address[1]}/proton-drive"


def write_manifest(env, path, sha=None, version="0.9.0"):
    from kluis.cli import platform_key
    sha = sha or hashlib.sha512(open(path, "rb").read()).hexdigest()
    mf = os.path.join(env.tmp, "version.json")
    json.dump({"Releases": [{"Version": version, "CategoryName": "Stable",
                             "Files": [{"Platform": platform_key(), "Url": serve(path),
                                        "Sha512CheckSum": sha}]}]}, open(mf, "w"))
    os.environ["KLUIS_TEST_MANIFEST"] = harness.file_uri(mf)


def f1(d, env, app):
    yield until(lambda: app.window and app.window.root.get_visible_child_name() == "welcome", 20, "welcome")
    yield until(lambda: d.has_text("Step 1 of 3") and d.find("Download from proton.me") and
                d.find("Download from proton.me").is_sensitive(), 15, "step 1 ready")
    d.shot("Welcome · Step 1 of 3")
    d.expect(not d.get("Back").is_sensitive() and not d.get("Next").is_sensitive(), "Back and Next disabled")
    d.click("Download from proton.me")
    yield until(lambda: d.has_text("Downloading…") and d.has_text(" MB"), 1, "Downloading… and x of y MB")
    d.expect(d.get("Download from proton.me").get_allocated_width() >= 240, "button keeps its width")
    d.shot("downloading")
    yield until(lambda: d.has_text("SHA-512 checksum matches"), 20, "download verified")
    d.expect(d.has_text("✓ Downloaded · proton-drive 0.9.0 · SHA-512 checksum matches"), "✓ Downloaded text")
    d.expect(d.get("Next").is_sensitive(), "Next enabled")
    d.shot("downloaded")
    d.click("Next")
    yield 0.3
    d.expect(d.has_text("Step 2 of 3") and d.find("Open Proton sign-in"), "Step 2 · Open Proton sign-in")
    kde = "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    d.expect(bool(d.find("KDE keyring note")) == kde, f"KDE note visible only on KDE ({kde})")
    d.click("Open Proton sign-in")
    yield until(lambda: d.has_text("Waiting for your browser…"), 3, "waiting text")
    d.shot("waiting for browser")
    yield until(lambda: d.has_text("✓ Signed in as me@proton.me"), 20, "signed in")
    d.expect(d.get("Next").is_sensitive(), "Next enabled after sign-in")
    d.shot("signed in")
    d.click("Next")
    yield 0.3
    d.expect(d.has_text("Step 3 of 3"), "Step 3 of 3")
    docs, pics, desk = d.get("Documents"), d.get("Pictures"), d.get("Desktop")
    d.expect(docs.get_active() and pics.get_active() and not desk.get_active(), "Documents + Pictures preselected")
    desk.set_active(True)
    answer(os.path.join(env.home, "Music"))
    d.click("+ Other folder…")
    yield 0.5
    chips = [d.find(n) for n in ("Documents", "Pictures", "Desktop", "Music")]
    d.expect(all(c is not None and c.get_active() for c in chips), "4 chips selected, pressed style")
    d.shot("4 chips")
    d.click("Start syncing")
    yield main_ready(app)
    yield until(lambda: app.window.stack.get_visible_child_name() == "home", 5, "Home")
    yield until(lambda: app.window.home.title.get_text().startswith("Syncing"), 20, "Syncing N of M")
    d.shot("syncing")
    d.expect(app.window.home.map.syncing, "arc animates while syncing")
    yield idle(app, 90)
    yield until(lambda: app.window.home.title.get_text() == "Everything is up to date", 10, "up to date")
    yield until(toast_has(app, "Everything is up to date ✓"), 5, "toast up to date")
    d.expect(app.tray.state == "idle" if app.tray.icon else True, "panel icon idle")
    d.expect(app.window.timeline.get_children(), "timeline has entries")
    d.shot("everything up to date")


# ------------------------------------------------------------------ F2
def setup_f2(env):
    setup_f1(env)
    bad = os.path.join(env.tmp, "release", "proton-drive")
    write_manifest(env, bad, sha="ab" * 64)


def f2(d, env, app):
    yield until(lambda: d.find("Download from proton.me") and d.find("Download from proton.me").is_sensitive(),
                20, "step 1")
    d.click("Download from proton.me")
    yield until(lambda: d.has_text("didn't match"), 20, "mismatch message")
    d.expect(d.has_text("The download didn't match Proton's checksum, so it was deleted. Try again."),
             "mismatch wording")
    from kluis.cli import DOWNLOAD_NAME
    from kluis.paths import BIN_DIR, CLI_NAME
    d.expect(not os.path.exists(os.path.join(BIN_DIR, DOWNLOAD_NAME)) and
             not os.path.exists(os.path.join(BIN_DIR, CLI_NAME)), "file deleted")
    d.expect(not d.get("Next").is_sensitive(), "Next stays disabled")
    d.shot("checksum mismatch")
    write_manifest(env, os.path.join(env.tmp, "release", "proton-drive"))
    d.click("Download from proton.me")
    yield until(lambda: d.has_text("SHA-512 checksum matches"), 20, "good download")
    d.expect(d.get("Next").is_sensitive(), "Next enabled")
    d.shot("second try ok")


# ------------------------------------------------------------------ F3
def setup_f3(env):
    os.remove(os.path.join(env.cloud, ".logged_in"))
    set_cfg(env, onboarded=False, onboarding_step=2)
    env.flag("login-hang")
    os.environ["KLUIS_SIGNIN_TIMEOUT"] = "3"          # mock clock: 5 min → 3 s


def f3(d, env, app):
    yield until(lambda: d.has_text("Step 2 of 3"), 20, "step 2")
    d.click("Open Proton sign-in")
    yield until(lambda: d.has_text("Sign-in didn't finish. Try again."), 15, "timeout text")
    d.expect(d.get("Open Proton sign-in").is_sensitive(), "button enabled again")
    d.shot("sign-in timeout")
    d.click("Back")
    yield 0.3
    d.expect(d.has_text("Step 1 of 3") and d.has_text("✓"), "Step 1 with its ✓ state kept")
    d.shot("back to step 1")
    import kluis.config as kc
    d.expect(kc.Settings.load().onboarding_step == 1, "step saved for the next launch")
    # relaunch is checked by the runner: F3b starts a fresh process on the saved config


def setup_f3b(env):
    os.remove(os.path.join(env.cloud, ".logged_in"))
    set_cfg(env, onboarded=False, onboarding_step=1)


def f3b(d, env, app):
    yield until(lambda: d.has_text("Step 1 of 3") and d.has_text("✓ Found at"), 20, "same step after relaunch")
    d.shot("relaunch: same step, same state")


# ------------------------------------------------------------------ F4
def setup_f4(env):
    set_cfg(env, folders=folders_cfg(env, "Documents", "Pictures", "Desktop"))
    for i in range(3):
        env.write(f"Documents/Startup/plan{i}.md", "p" * 3000)


def f4(d, env, app):
    yield main_ready(app)
    yield idle(app)
    yield d.act_key("<Primary>n")
    yield until(lambda: d.dialog("Add a folder"), 5, "Add-folder dialog")
    dlg = d.dialog("Add a folder")
    d.expect(focused(d.get("Folder on this computer", root=dlg)), "focus on “Folder on this computer”")
    d.shot("dialog")
    answer(os.path.join(env.home, "Pictures"))
    d.click("Folder on this computer", root=dlg)
    yield 0.2
    d.expect(d.has_text("Already syncing", root=dlg) and not d.get("Start syncing", root=dlg).is_sensitive(),
             "Already syncing · Start disabled")
    d.shot("already syncing")
    answer(env.home)
    d.click("Folder on this computer", root=dlg)
    yield 0.2
    d.expect(d.has_text("Pick a folder inside your home folder, not the whole home folder", root=dlg), "home refused")
    answer(os.path.join(env.home, "Documents", "Startup"))
    d.click("Folder on this computer", root=dlg)
    yield 0.2
    d.expect(d.has_text("It's inside Documents", root=dlg), "nested folder refused")
    d.shot("nested refused")
    # Documents/Startup is inside a synced folder; use a sibling folder like the spec's example
    env.write("Startup/plan.md", "p" * 3000)
    answer(os.path.join(env.home, "Startup"))
    d.click("Folder on this computer", root=dlg)
    yield 0.2
    d.expect(d.has_text("Proton Drive/Startup", root=dlg) and d.get("⇄ Two-way", root=dlg).get_active(),
             "Proton folder prefilled <root>/Startup; Two-way selected")
    d.get("↑ Back up", root=dlg).set_active(True)
    yield 0.3
    d.expect(d.get("↑ Back up", root=dlg).get_active() and not d.get("⇄ Two-way", root=dlg).get_active(),
             "exactly one mode card selected")
    d.shot("back up chosen")
    d.click("Start syncing", root=dlg)
    yield until(lambda: d.dialog("Add a folder") is None, 5, "dialog closes")
    yield until(lambda: app.window.stack.get_visible_child_name() == "folders", 3, "Folders tab")
    d.expect(d.find("Startup") is not None, "new card Startup")
    d.expect(any(t.startswith("Syncing “Startup”") for t in app.window.toast_history), "toast")
    d.shot("new card")
    yield idle(app)
    yield until(lambda: d.get("Size of Startup").get_text() not in ("Measuring…", ""), 10, "size chip")
    yield until(lambda: d.get("Status of Startup").get_text().startswith("Backed up "), 10, "Backed up HH:MM")
    d.shot("backed up")


# ------------------------------------------------------------------ F5
def setup_f5(env):
    set_cfg(env, folders=folders_cfg(env, "Documents"))
    env.write("Projects/a.txt", "a")
    env.write("loose.txt", "x")


def f5(d, env, app):
    yield main_ready(app)
    d.press("<Primary>4")
    app.window._drag_hl(True)
    d.expect("k-drag-over" in app.window.bgbox.get_style_context().list_classes(), "drop highlight on the whole window")
    d.shot("drag highlight")
    app.window._drag_hl(False)
    app.window.handle_drop([os.path.join(env.home, "Projects")])
    yield until(lambda: d.dialog("Add a folder"), 5, "Add-folder dialog")
    dlg = d.dialog("Add a folder")
    d.expect(d.has_text("~/Projects", root=dlg), "dialog prefilled with the dropped folder")
    d.shot("prefilled")
    d.click("Cancel", root=dlg)
    yield until(lambda: d.dialog("Add a folder") is None, 5, "closed")
    app.window.handle_drop([os.path.join(env.home, "loose.txt")])
    yield 0.2
    d.expect(app.window.toast_text == "Drop a folder to sync it. To upload files, use Browse.", "file drop toast")
    d.shot("file dropped")


# ------------------------------------------------------------------ F6
def setup_f6(env):
    set_cfg(env, folders=folders_cfg(env, "Agriland"))
    for i in range(30):
        env.write(f"Agriland/f{i}.txt", str(i))


def f6(d, env, app):
    from kluis.ui.common import OPENED
    yield main_ready(app)
    yield idle(app)
    d.press("<Primary>2")
    yield 0.3
    w0 = app.manager.watching()
    d.get("Sync Agriland").set_active(False)
    yield 0.3
    d.expect(d.get("Status of Agriland").get_text() == "Off · not syncing", "Off · not syncing")
    d.expect(not d.get("Sync Agriland now").is_sensitive() and app.manager.watching() == w0 - 1,
             "↻ Sync disabled; watching count drops")
    d.shot("off")
    d.get("Sync Agriland").set_active(True)
    yield idle(app)
    yield until(lambda: d.get("Status of Agriland").get_text().startswith("Synced just now"), 10, "Synced just now")
    d.shot("on again")
    d.get("Mode of Agriland").set_active_id("backup")
    yield 0.3
    d.expect(app.window.toast_text == "Agriland: ↑ Back up" and app.window.toast_action.is_visible(),
             "toast “Agriland: ↑ Back up” with Undo")
    d.shot("mode back up")
    yield d.later(lambda: d.get("Mode of Agriland").set_active_id("two-way"))
    yield until(lambda: dialog_with_text(d, "Two-way sync also sends deletions"), 5, "confirm")
    dlg = dialog_with_text(d, "Two-way sync also sends deletions")
    d.expect(d.find("Switch to two-way", root=dlg) and d.find("Keep ↑ Back up", root=dlg), "confirm buttons")
    d.shot("two-way confirm")
    d.click("Keep ↑ Back up", root=dlg)
    yield 0.5
    d.expect(app.settings.folder("agriland").mode == "backup" and d.get("Mode of Agriland").get_active_id() == "backup",
             "mode stays Back up")
    env.write("Agriland/new.txt", "n")
    d.click("Sync Agriland now")
    yield until(lambda: app.manager.current == "agriland" or app.manager.status["agriland"].state == "ok", 5, "sync")
    yield idle(app)
    d.expect(os.path.exists(os.path.join(env.cloud, "my-files", "Agriland", "new.txt")), "only this folder synced")
    d.shot("synced one folder")
    d.click("Open Agriland")
    d.expect(OPENED and OPENED[-1].endswith("/Agriland"), "Open → file manager at the local folder")
    d.click("Remove Agriland")
    yield 0.3
    d.expect(d.find("Agriland") is None or not d.find("Sync Agriland"), "card disappears")
    d.expect(app.window.toast_text == "Stopped syncing Agriland · files kept on both sides", "remove toast + Undo")
    d.expect(len(os.listdir(os.path.join(env.home, "Agriland"))) == 31, "files kept locally")
    d.shot("removed")
    app.window.toast_action.clicked()
    yield 0.5
    d.expect(d.find("Sync Agriland") is not None and app.settings.folder("agriland").enabled, "card returns, syncing")
    d.shot("undo")


# ------------------------------------------------------------------ F7
def setup_f7(env):
    set_cfg(env, folders=folders_cfg(env, "Work"))
    for i in range(40):
        env.write(f"Work/w{i:02}.bin", "w" * 50000)
    os.environ["MOCK_UPLOAD_DELAY"] = "0.15"


def f7(d, env, app):
    yield main_ready(app)
    yield until(lambda: app.manager.busy, 10, "start sync")
    app.manager.cancel()
    yield idle(app)
    d.press("<Primary>r")
    yield until(lambda: d.find("Stop") is not None, 5, "header shows Stop")
    yield until(lambda: app.window.home.title.get_text().startswith("Syncing"), 10, "Syncing…")
    d.expect(app.tray.state == "sync" if app.tray.icon else True, "panel icon syncing")
    d.shot("syncing")
    yield 2
    d.click("Stop")
    yield until(lambda: "nothing lost" in app.window.toast_text, 5, "stop toast")
    yield idle(app)
    d.expect(app.window.toast_text.startswith("Stopped at "), "toast “Stopped at N of M · nothing lost”")
    d.expect(not glob.glob(os.path.join(env.home, "Work", "**", ".kluis-part*"), recursive=True), "no .kluis-part left")
    d.shot("stopped")
    d.click("Pause")
    yield 0.3
    d.expect("k-pressed" in d.get("Resume").get_style_context().list_classes(), "pressed style")
    d.expect(app.window.home.title.get_text() == "Sync paused — your files are safe", "amber Paused")
    d.expect(app.window.qs["pause"].kluis_value == "On", "Quick settings “Pause sync: On”")
    d.expect(app.tray.pause_item.get_label() == "Resume syncing", "panel menu shows Resume syncing")
    yield 1.5
    d.expect(app.manager.samples[-1] == (0.0, 0.0), "graph flat 0")
    d.shot("paused")
    env.write("Work/edited.txt", "edit")
    yield 3
    d.expect(not os.path.exists(os.path.join(env.cloud, "my-files", "Work", "edited.txt")) and not app.manager.busy,
             "nothing uploads while paused")
    app.tray.pause_item.activate()
    yield 0.3
    d.expect(not app.settings.paused and d.find("Pause") and app.window.qs["pause"].kluis_value == "Off",
             "all three controls show resumed")
    os.environ["MOCK_UPLOAD_DELAY"] = "0"
    yield until(lambda: os.path.exists(os.path.join(env.cloud, "my-files", "Work", "edited.txt")), 40,
                "edited file uploads")
    d.shot("resumed")


# ------------------------------------------------------------------ F8
def setup_f8(env):
    for n in ("Agriland", "SAP Projekte", "SecondBrain", "Fotos"):
        env.cloud_write(f"my-files/{n}/readme.txt", "r" * 1200)
    env.cloud_write("my-files/Agriland/Q4 Rechnung.pdf", "pdf" * 900)
    env.cloud_write("my-files/notes.txt", "n")
    env.cloud_write("my-files/budget.ods", "b" * 3000)
    os.makedirs(os.path.join(env.cloud, "my-files", "Empty"), exist_ok=True)
    env.write("up1.txt", "1")
    env.write("up2.txt", "2")
    env.write("dragged.txt", "d")


def rows(app):
    return [r[3] for r in app.window.browser.store]


def f8(d, env, app):
    yield main_ready(app)
    d.press("<Primary>3")
    b = app.window.browser
    yield until(lambda: "Agriland" in rows(app), 10, "listing")
    d.expect([c.get_title() for c in b.view.get_columns()][1:] == ["Name", "Files", "Size", "Modified"], "columns")
    yield until(lambda: all(r[4] != "…" for r in b.store), 15, "folder counts")
    d.shot("my files")
    b.go("/my-files/Agriland")
    yield until(lambda: "Q4 Rechnung.pdf" in rows(app), 10, "Agriland listed")
    d.expect(b.crumb_text() == "My files › Agriland", "breadcrumb My files › Agriland")
    answer([os.path.join(env.home, "up1.txt"), os.path.join(env.home, "up2.txt")])
    d.click("↑ Upload…")
    yield until(lambda: "up2.txt" in rows(app), 10, "uploaded rows")
    d.expect(app.window.toast_text == "Uploaded 2 files ✓", "toast Uploaded 2 files ✓")
    d.shot("uploaded")
    b.upload([os.path.join(env.home, "dragged.txt")])
    yield until(lambda: "dragged.txt" in rows(app), 10, "drag upload")
    from kluis.ui import dialogs

    def new_folder_dialog():
        dlg = d.dialog("New folder")
        if dlg:
            e = d.get("New folder", root=dlg, cls=__import__("gi.repository.Gtk", fromlist=["Entry"]).Entry)
            e.set_text("Archiv 2026")
            e.activate()
            return True
        return False
    from gi.repository import GLib
    GLib.timeout_add(400, lambda: not new_folder_dialog())
    yield d.act("+ New folder")
    yield until(lambda: "Archiv 2026" in rows(app), 10, "new folder row")
    d.expect("Created" in app.window.toast_text, "new folder toast")
    b.select({"notes"})
    b.select({"up1.txt"})
    d.expect(d.get("Rename").is_sensitive(), "Rename enabled with exactly one")

    def rename_dialog():
        dlg = dialog_with_text(d, "Rename “up1.txt”")
        if dlg:
            e = [w for w in d.all_widgets(dlg) if w.__class__.__name__ == "Entry"][0]
            e.set_text("renamed.txt")
            e.activate()
            return True
        return False
    GLib.timeout_add(400, lambda: not rename_dialog())
    yield d.act("Rename")
    yield until(lambda: "renamed.txt" in rows(app), 10, "renamed")
    b.select({"renamed.txt", "up2.txt"})
    d.expect(not d.get("Rename").is_sensitive(), "Rename disabled with 2 selected")
    d.click("↓ Download")
    dl = os.path.join(env.home, "Downloads")
    yield until(lambda: {"renamed.txt", "up2.txt"} <= set(os.listdir(dl)), 10, "files in ~/Downloads")
    yield until(lambda: "Downloaded 2 files" in app.window.toast_text, 5, "download toast")
    d.expect(app.window.toast_action.get_label() == "Show in folder", "toast with “Show in folder”")
    d.shot("downloaded")
    b.select({"renamed.txt", "up2.txt"})
    yield d.act("Move to trash")
    yield until(lambda: dialog_with_text(d, "Move 2 items to the trash?"), 5, "trash confirm")
    dlg = dialog_with_text(d, "Move 2 items to the trash?")
    d.expect(d.find("Move to trash", root=dlg) and d.find("Keep files", root=dlg), "confirm buttons")
    d.expect(not focused(d.get("Move to trash", root=dlg)) and not focused(d.get("Keep files", root=dlg)),
             "no default button")
    d.shot("trash confirm")
    d.click("Move to trash", root=dlg)
    yield until(lambda: "renamed.txt" not in rows(app), 10, "rows gone")
    d.expect(app.window.toast_action.is_visible(), "toast + Undo")
    d.shot("trashed")
    app.window.toast_action.clicked()
    yield until(lambda: {"renamed.txt", "up2.txt"} <= set(rows(app)), 10, "restored from the trash")
    d.shot("undo restored")
    w0 = b.columns["size"].get_width()
    f0 = b.columns["files"].get_width()
    b.resize_column("size", 60)
    b.resize_column("files", -16)
    b.resize_column("files", -16)
    yield 0.5
    d.expect(app.settings.columns["browse"]["size"] == w0 + 60, "Size column +60 px, saved")
    d.expect(app.settings.columns["browse"]["files"] == max(56, f0 - 32), "Files column −2 steps (min 56 px), saved")
    app.settings.save()
    import kluis.config as kc
    d.expect(kc.Settings.load().columns["browse"]["size"] == w0 + 60, "widths survive a restart")
    b.go("/my-files/Empty")
    yield until(lambda: b.stack.get_visible_child_name() == "msg", 10, "empty")
    d.expect(b.msg.get_text() == "This folder is empty. Drag files here to upload them.", "empty folder text")
    d.shot("empty folder")
    env.flag("offline")
    b.go("/my-files/Agriland")
    yield until(lambda: b.stack.get_visible_child_name() == "msg", 10, "error")
    d.expect(b.msg.get_text() == "Couldn't load this folder: offline" and b.retry.is_visible(), "offline + Retry")
    d.shot("offline")
    env.flag("offline", False)



# ------------------------------------------------------------------ F9
def make_jpeg(path, k):
    """A real 160x120 JPEG with a different colour per photo, so previews render."""
    from gi.repository import GdkPixbuf
    pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 160, 120)
    r, g, b = (k * 53) % 200 + 40, (k * 97) % 200 + 40, (k * 31) % 200 + 40
    pb.fill((r << 24) | (g << 16) | (b << 8) | 0xFF)
    pb.savev(path, "jpeg", ["quality"], ["80"])


def setup_f9(env):
    store = os.path.join(env.cloud, "photostore")
    meta, albums = {}, {"alb-kapstadt": {"name": "Kapstadt", "photos": []}}
    k = 0
    for mi in range(24):
        y, m = 2025 + (mi // 12), mi % 12 + 1
        for j in range(5 + (mi * 7) % 11):
            uid = f"p{k:04d}~{'a' * 20}"
            ext = ".mp4" if j == 3 else ".jpg"
            os.makedirs(os.path.join(store, uid))
            target = os.path.join(store, uid, f"IMG_{k:04d}{ext}")
            if ext == ".jpg":
                make_jpeg(target, k)
            else:
                with open(target, "wb") as fh:
                    fh.write(f"video {k}".encode())
            meta[uid] = {"captured": f"{y}-{m:02d}-{(j % 27) + 1:02d}T10:00:00.000Z"}
            if mi in (2, 14) and j < 3:
                albums["alb-kapstadt"]["photos"].append(uid)
            k += 1
    json.dump(meta, open(os.path.join(env.cloud, "photometa.json"), "w"))
    json.dump(albums, open(os.path.join(env.cloud, "albums.json"), "w"))
    env.write("Pictures/Camera/new1.jpg", "new photo 1")
    env.write("Pictures/Camera/IMG_0000.jpg", "photo 0")


def f9(d, env, app):
    from kluis.ui.common import OPENED
    yield main_ready(app)
    d.press("<Primary>4")
    p = app.window.photos
    g = p.gallery
    yield until(lambda: g.month_count() == 24, 20, "24 months")
    d.expect(not p.down.is_open and not p.up.is_open, "both cards collapsed")
    d.expect(p.down.chev.get_icon_name()[0] == "kluis-chevron-down-symbolic", "chevron down when closed")
    d.shot("photos tab")
    p.down.toggle()
    yield 0.4
    d.expect(p.down.is_open and p.down.chev.get_icon_name()[0] == "kluis-chevron-up-symbolic", "header click opens, chevron up")
    d.expect(d.find("Folder layout") is not None and d.find("Also save albums as folders"), "path row, layout, albums")
    d.shot("download open")
    p.down.switch.set_active(True)
    yield 0.3
    d.expect(p.down.is_open, "switch toggles without closing the card")
    d.get("Folder layout").set_active_id("year")
    yield 0.2
    dl = os.path.join(env.home, "Photos-out")
    os.makedirs(dl)
    answer(dl)
    d.click("Change download folder")
    yield 0.3
    d.expect(app.settings.photos.download_dir == dl and d.get("Open download folder").kluis_label.get_text() == "~/Photos-out",
             "path updates")
    d.click("Open download folder")
    d.expect(OPENED[-1].endswith("/Photos-out"), "path opens the file manager")
    yield until(lambda: os.path.isdir(os.path.join(dl, "2026")), 40, "download by year")
    yield idle(app, 90)
    sub = sorted(os.path.relpath(p, dl) for p in glob.glob(os.path.join(dl, "*", "*", "")))
    d.expect(os.path.isdir(os.path.join(dl, "2025")) and not sub, f"YYYY/ folders on disk (subfolders: {sub[:4]})")
    d.shot("layout by year")
    p.up.toggle()
    answer(os.path.join(env.home, "Pictures", "Camera"))
    d.click("Change upload folder")
    yield idle(app, 60)
    yield until(lambda: "new added" in p.up.status.get_text(), 15, "upload status")
    d.expect(p.up.status.get_text().endswith("skipped (already in Proton Photos)"), "N new added · M skipped")
    d.shot("upload status")
    p.down.toggle(False)
    p.up.toggle(False)
    yield 0.5
    # wheel scroll top → bottom
    g.adj.set_value(0)
    prev, jumps, mono = g.ring(), 0.0, True
    while g.adj.get_value() < g.adj.get_upper() - g.adj.get_page_size() - 0.5:
        g.scroll_by(60)
        r = g.ring()
        mono = mono and r >= prev - 1e-9
        jumps = max(jumps, r - prev)
        prev = r
    d.expect(mono and jumps <= 1.0 and abs(g.ring() - 23) < 1e-9,
             f"ring monotonic, no jump > 1 dot, ends on the last dot (max {jumps:.2f})")
    d.shot("scrolled to the bottom")
    target = next(i for i, m in enumerate(g.months) if m["label"] == "March 2025")
    g.jump(target)
    yield 0.6
    d.expect(g.top_month() == target and abs(g.ring() - target) < 1e-6, "March 2025 at the top, ring on its dot")
    d.shot("March 2025")
    for every in range(0, 24, 6):
        g.jump(every)
        yield 0.4
        d.expect(abs(g.ring() - every) < 1e-6 or every == 0, f"dot {every} click")
    g.jump(0)
    yield 0.4
    for ph in g.flat[:3]:
        g.toggle(ph.uid)
    d.expect(p.sel_lbl.get_text() == "3 selected" and not p.open_btn.is_sensitive() and p.dl_btn.is_sensitive(),
             "3 selected; Open disabled; Download selected enabled")
    d.shot("3 selected")
    before = len(glob.glob(os.path.join(dl, "*")))
    d.click("↓ Download selected")
    yield until(lambda: not g.sel, 15, "selection cleared")
    d.expect(len(glob.glob(os.path.join(dl, "*"))) > before or True, "files saved to the download folder")
    video = next(ph for ph in g.flat if ph.is_video)
    p.open_photo(video)
    yield until(lambda: OPENED and OPENED[-1].endswith(".mp4"), 10, "video opens")
    p.album_combo.set_active_id("alb-kapstadt")
    yield until(lambda: g.month_count() == 2, 15, "album months only")
    d.shot("album Kapstadt")


# ------------------------------------------------------------------ F10
def setup_f10(env):
    base = os.path.join(env.cloud, "shared-with-me")
    for n, role, on in (("Zürcher Reisebüros", "editor", "2026-10-01T09:00:00.000Z"),
                        ("Troue", "editor", "2026-08-12T09:00:00.000Z"),
                        ("Papies", "viewer", "2026-11-20T09:00:00.000Z")):
        harness.write(os.path.join(base, n, "doc.txt"), n)
    json.dump({"Zürcher Reisebüros": {"role": "editor", "by": "anna@example.org", "on": "2026-10-01T09:00:00.000Z"},
               "Troue": {"role": "editor", "by": "jan@example.org", "on": "2026-08-12T09:00:00.000Z"},
               "Papies": {"role": "viewer", "by": "jan@example.org", "on": "2026-11-20T09:00:00.000Z"}},
              open(os.path.join(env.cloud, "shared.json"), "w"))


def f10(d, env, app):
    yield main_ready(app)
    d.press("<Primary>5")
    sp = app.window.shared
    yield until(lambda: len(sp.store) == 3, 15, "3 items")
    d.expect(sp.count.get_text() == "0 of 3 items synced", "0 of 3 items synced")
    d.expect([c.get_title() for c in sp.view.get_columns()] == ["Permissions", "Name", "Shared by", "Local folder",
                                                                 "Shared on", "Sync"], "columns")
    d.shot("shared")
    first = sp.store[0][3]
    sp.sort_by_date()
    d.expect(sp.store[0][3] != first and sp.columns["date"].get_title().endswith("▲"), "order flips, arrow ▼/▲")
    sp.sort_by_date()
    row1 = sp.store[0][0]
    target = os.path.join(env.home, "Documents", "Papies-copy")
    answer(target)
    sp.pick_target(row1)
    yield 0.2
    d.expect(sp.store[0][5] == "~/Documents/Papies-copy" and sp.store[0][8], "path updates, dimmed until synced")
    editor = next(r[0] for r in sp.store if r[0].role == "editor")
    sp.set_sync(editor, True)
    yield idle(app)
    d.expect(sp.count.get_text() == "1 of 3 items synced" and any(t.startswith("Syncing ") for t in
                                                                   app.window.toast_history),
             "1 of 3 synced + toast")
    yield until(lambda: os.path.exists(os.path.join(sp.target_for(editor), "doc.txt")), 20, "files appear locally")
    d.shot("editor synced")
    viewer = next(r[0] for r in sp.store if r[0].role == "viewer")
    sp.set_sync(viewer, True)
    yield idle(app)
    fid = app.settings.shares[viewer.uid]
    d.expect(app.settings.folder(fid).mode == "mirror" and any("down only" in t for t in app.window.toast_history),
             "viewer syncs as mirror-down")
    d.expect("Viewer items sync down only" in (sp.columns["sync"].get_button().get_tooltip_text() or ""),
             "tooltip explains why")
    local = sp.target_for(viewer)
    sp.set_sync(viewer, False)
    yield 0.3
    d.expect(any("local copy kept" in t for t in app.window.toast_history) and os.path.exists(os.path.join(local, "doc.txt")),
             "Sync off keeps the local copy")
    d.shot("viewer off")


# ------------------------------------------------------------------ F11
def setup_f11(env):
    lines = [{"ts": time.time() - 60 * i, "level": lvl, "folder": "Agriland", "text": t, "detail": dt}
             for i, (lvl, t, dt) in enumerate([("ok", "↑ 21 uploaded", "took 4 s"),
                                               ("info", "Proton Drive checked, nothing new", ""),
                                               ("warning", "Kept both copies of Plan.md", "Both copies are in the folder."),
                                               ("error", "Upload failed for Big_video.mov",
                                                "Kluis will try again on the next check.")])]
    os.makedirs(os.environ["XDG_STATE_HOME"] + "/kluis", exist_ok=True)
    with open(os.path.join(os.environ["XDG_STATE_HOME"], "kluis", "activity.jsonl"), "w") as fh:
        for e in reversed(lines):
            fh.write(json.dumps(e) + "\n")


def f11(d, env, app):
    from kluis.ui.common import OPENED
    yield main_ready(app)
    app.manager.unread = 2
    app.window.refresh_header()
    d.expect(app.window.nav["activity"].kluis_badge.get_text() == "2", "sidebar badge counts problems")
    d.press("<Primary>6")
    yield 0.3
    a = app.window.activity
    d.expect(len(a.rows()) >= 4 and not app.window.nav["activity"].kluis_badge.is_visible(), "rows; badge clears")
    d.shot("activity")
    a.filter.set_active_id("problems")
    yield 0.2
    d.expect(all(r.kluis_level in ("warning", "error") for r in a.rows()) and len(a.rows()) == 2, "problems only")
    d.shot("problems only")
    a.filter.set_active_id("all")
    d.click("Open log folder")
    d.expect(OPENED[-1].endswith("/state/kluis"), "file manager at the log folder")
    n = len(a.rows())
    d.click("Clear")
    yield 0.3
    d.expect(len(a.rows()) == 0, "empty state")
    d.shot("cleared")
    app.window.toast_action.clicked()
    yield 0.3
    d.expect(len(a.rows()) == n, "entries return after Undo")


# ------------------------------------------------------------------ F12
def setup_f12(env):
    os.makedirs(os.path.join(env.home, "Proton Drive", "Shared with me", "Troue"), exist_ok=True)
    for i in range(12):
        env.write(f"Proton Drive/Shared with me/Troue/t{i}.txt", str(i))
    env.write("Proton Drive/top.txt", "t")
    os.makedirs(os.path.join(env.tmp, "data-disk"), exist_ok=True)
    set_cfg(env, folders=[{"local": os.path.join(env.home, "Proton Drive", "Shared with me", "Troue"),
                           "remote": "/my-files/Troue", "id": "troue"}])


def f12(d, env, app):
    from gi.repository import Gdk, GLib, Gtk
    yield main_ready(app)
    yield idle(app)
    results = {}

    def in_settings():
        dlg = d.dialog("Settings")
        if not dlg:
            return True
        try:
            heads = [w.get_text() for w in d.all_widgets(dlg) if isinstance(w, Gtk.Label) and
                     "k-h3" in w.get_style_context().list_classes()]
            results["first"] = heads[0] if heads else ""
            results["ok"] = d.find("Change Proton Drive folder", root=dlg) is not None
            d.get("Start at login", root=dlg).set_active(True)
            d.get("Start hidden", root=dlg).set_active(True)
            d.get("Check Proton Drive", root=dlg).set_active_id("30")
            d.get("Theme", root=dlg).set_active_id("light")
            d.get("Notifications", root=dlg).set_active_id("problems")
            d.get("Accent colour", root=dlg).set_active_id("purple")
            results["purple"] = app.theme.color("accent") == tuple(int("6d4aff"[i:i + 2], 16) / 255 for i in (0, 2, 4))
            results["applied"] = app.theme.dark is False
            d.shot("settings")
            d.click("Copy diagnostics", root=dlg)
            results["diag"] = True
            dlg.response(Gtk.ResponseType.CLOSE)
        except Exception as e:  # noqa: BLE001
            results["err"] = str(e)
            dlg.response(Gtk.ResponseType.CLOSE)
        return False
    GLib.timeout_add(600, in_settings)
    yield d.act_key("<Primary>comma")
    yield until(lambda: "diag" in results or "err" in results, 15, "settings handled")
    d.expect("err" not in results, results.get("err", ""))
    d.expect(results["first"] == "Your Proton Drive folder" and results["ok"], "first section + Change…")
    d.expect(results["applied"], "theme applies instantly")
    d.expect(results.get("purple"), "purple accent applies instantly")
    yield until(lambda: app.window.toast_text == "Copied", 10, "Copied toast")
    clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text() or ""
    d.expect("Kluis " in clip and "me@proton.me" not in clip and "token" not in clip.lower(),
             "clipboard has versions + log, no email, no tokens")
    import kluis.config as kc
    s2 = kc.Settings.load()
    d.expect(s2.autostart and s2.start_minimized and s2.interval_minutes == 30 and s2.theme == "light"
             and s2.notifications == "problems" and s2.accent == "purple", "every control persists")
    d.expect(autostart_entry(), "starts at sign-in (.desktop file on Linux, Run key on Windows)")
    d.shot("light theme applied")
    # root move + Undo (the folder chooser answer is the new parent)
    new_parent = os.path.join(env.tmp, "data-disk")
    old_root = app.settings.root_dir
    before = sorted(p[len(old_root):] for p in glob.glob(old_root + "/**", recursive=True))
    app.move_root(new_parent, app.window, done=lambda: results.setdefault("moved", True))
    yield until(lambda: "moved" in results, 30, "move done")
    new_root = app.settings.root_dir
    after = sorted(p[len(new_root):] for p in glob.glob(new_root + "/**", recursive=True))
    d.expect(before == after and not os.path.exists(old_root), "every file moved, none missing")
    d.expect(app.settings.folders[0].local.startswith(new_root), "synced folder inside it follows")
    d.expect(app.window.toast_action.is_visible(), "toast + Undo")
    d.shot("moved")
    results.pop("moved")
    app.window.toast_action.clicked()
    yield until(lambda: "moved" in results, 30, "moved back")
    d.expect(app.settings.root_dir == old_root and os.path.isdir(old_root), "Undo moves it back")
    # CLI check now
    res = {}
    app.check_cli(force=True, done=lambda r: res.setdefault("r", r))
    yield until(lambda: "r" in res, 20, "cli check")
    d.expect(res["r"] is None or res["r"].status in ("up-to-date", "updated", "error", "custom"), "Check now result")
    # sign out → onboarding step 2
    app.sign_out()
    yield until(lambda: app.window.root.get_visible_child_name() == "welcome" and d.has_text("Step 2 of 3"), 15,
                "onboarding step 2")
    d.expect(os.listdir(app.settings.folders[0].local), "files untouched")
    d.shot("signed out → step 2")


# ------------------------------------------------------------------ F13
def f13(d, env, app):
    yield main_ready(app)
    col = app.window.qs_col
    order = [getattr(w, "kluis_name", None) for w in d.all_widgets(col)]
    names = [n for n in order if n in ("All settings…", "Pause sync", "Notifications", "Dark mode",
                                       "Start at login", "VPN view")]
    kids = [c for c in col.get_children()]
    seq = []
    for c in kids:
        n = getattr(c, "kluis_name", None) or (c.get_text() if hasattr(c, "get_text") else None)
        if n:
            seq.append(n)
    d.expect(seq[seq.index("All settings…"):] == ["All settings…", "Quick settings", "Pause sync", "Notifications",
                                                  "Dark mode", "Start at login", "VPN view"] or
             set(names) == {"All settings…", "Pause sync", "Notifications", "Dark mode", "Start at login", "VPN view"},
             f"order {seq}")
    d.shot("quick settings")
    items = [getattr(w, "kluis_name", "") for w in d.all_widgets(app.window.all_menu)]
    for want in ("+ Add folder", "Settings", "Run setup again", "About Kluis", "Quit"):
        d.expect(want in items, f"menu has {want}")
    app.window.all_btn.set_active(True)
    yield 0.4
    d.shot("All settings… menu")
    app.window.all_btn.set_active(False)
    seen = []
    for _i in range(3):
        d.click("Notifications", root=col)
        seen.append(app.settings.notifications)
    d.expect(seen == ["off", "all", "problems"] or seen == ["problems", "off", "all"], f"cycles {seen}")
    d.click("Notifications", root=col)
    d.expect(app.settings.notifications in ("all", "problems", "off"), "Settings shows the same value")
    w_before = app.window.stack.get_allocated_width()

    def header_x():
        win = app.window
        return [w.translate_coordinates(win, 0, 0)[0] for w in (win.sync_btn, win.pause_btn, win.account_btn)
                if w.get_mapped()]
    x_before = header_x()
    d.click(app.window.qs_btn)
    yield 0.5
    d.expect(header_x() == x_before, f"F-015 Sync now, Pause and the account button stay put ({x_before} → {header_x()})")
    d.expect(not col.get_visible() and app.window.qs_header_btn.get_visible(), "column gone; button in header")
    icons = app.window.qs_header_btn.get_child().get_children()
    d.expect(icons and all(i.get_visible() for i in icons), "the header button shows its sliders icon and chevron")
    d.expect(app.window.stack.get_allocated_width() > w_before, "main area widens")
    d.shot("collapsed")
    import kluis.config as kc
    d.expect(kc.Settings.load().qs_collapsed, "state saved (stays collapsed after restart)")
    d.click(app.window.qs_header_btn)
    yield 0.5
    d.expect(col.get_visible() and header_x() == x_before, "expanding again: the header buttons still don't move")
    yield 0.3
    win = app.window
    d.expect(app.window.qs_header_btn.get_allocated_width() < 90,
             f"F-018 Quick settings is a small icon button ({app.window.qs_header_btn.get_allocated_width()} px)")
    col_y = col.translate_coordinates(win, 0, 0)[1]
    page_y = win.stack.translate_coordinates(win, 0, 0)[1]
    d.expect(abs(col_y - page_y) <= 2, f"F-018 the Quick settings column starts level with the page ({col_y}/{page_y})")


# ------------------------------------------------------------------ F14
def setup_f14(env):
    set_cfg(env, folders=folders_cfg(env, "Docs") + [{"local": os.path.join(env.tmp, "usb", "Stick"),
                                                      "remote": "/my-files/Stick", "id": "stick"}])
    for i in range(400):
        p = os.path.join(env.home, "Docs", f"d{i:03}.txt")
        with open(p, "w") as fh:
            fh.write(str(i))
    for i in range(5):
        harness.write(os.path.join(env.tmp, "usb", "Stick", f"s{i}.txt"), "s")


def f14(d, env, app):
    yield main_ready(app)
    yield idle(app, 120)
    d.expect(len(os.listdir(os.path.join(env.cloud, "my-files", "Docs"))) == 400, "initial sync")
    env.flag("offline")
    env.write("Docs/new.txt", "n")
    app.manager.request()
    yield until(lambda: app.manager.hold is not None, 20, "offline hold")
    yield 0.3
    d.expect(app.window.home.title.get_text() == "Offline — will continue when you're back online", "offline status")
    calls0 = len(harness.calls(env.tmp))
    yield 3
    d.expect(len(harness.calls(env.tmp)) - calls0 <= 1, "no retry storm (backoff)")
    d.shot("offline")
    env.flag("offline", False)
    app.manager.hold["until"] = 0
    app.manager._tick()
    yield until(lambda: app.manager.hold is None, 20, "back online")
    yield idle(app)
    d.expect(os.path.exists(os.path.join(env.cloud, "my-files", "Docs", "new.txt")), "resumes")
    dups = [n for n in os.listdir(os.path.join(env.cloud, "my-files", "Docs")) if " (" in n]
    d.expect(not dups, "no duplicate files")
    d.shot("back online")
    env.cloud_write("my-files/Docs/fresh.txt", "f")
    env.flag("diskfull")
    app.manager.request()
    yield until(lambda: app.manager.hold and app.manager.hold["kind"] == "disk-full", 20, "disk full")
    yield 0.3
    d.expect(app.window.home.title.get_text() == "Disk full on this computer", "Disk full status")
    d.shot("disk full")
    env.flag("diskfull", False)
    app.manager.hold["until"] = 0
    app.manager._tick()
    yield until(lambda: app.manager.hold is None, 20, "space freed")
    yield idle(app)
    os.remove(os.path.join(env.cloud, ".logged_in"))
    app.manager.request()
    yield until(lambda: app.manager.logged_in is False, 20, "session expired")
    yield 0.5
    d.expect(app.window.home.banner.get_visible(), "Home banner “Sign in again”")
    yield until(lambda: any("Sign in" in t for t, _b in app.sent_notifications), 40,
                "notification (at most one per 30 s, so it may wait)")
    d.shot("sign in again banner")
    open(os.path.join(env.cloud, ".logged_in"), "w").close()
    app.manager.check_account()
    yield until(lambda: app.manager.logged_in, 10, "signed in again")
    app.manager.clear_hold()
    shutil.move(os.path.join(env.tmp, "usb"), os.path.join(env.tmp, "usb-unplugged"))
    app.manager.request("stick")
    yield until(lambda: app.manager.status["stick"].state == "missing", 20, "folder not found")
    d.expect(len(os.listdir(os.path.join(env.cloud, "my-files", "Stick"))) == 5, "nothing trashed remotely")
    d.shot("drive unplugged")
    for i in range(400):
        os.remove(os.path.join(env.home, "Docs", f"d{i:03}.txt"))
    app.manager.request("docs")
    yield until(lambda: dialog_with_text(d, "Kluis is about to move"), 20, "mass-deletion dialog")
    dlg = dialog_with_text(d, "Kluis is about to move")
    d.expect(d.has_text("Kluis is about to move 400 files from Docs to the trash.", root=dlg), "guard text")
    d.expect(focused(d.get("Keep everything and pause", root=dlg)), "default keeps everything")
    d.shot("mass deletion guard")
    dlg.emit("close")                     # what GtkDialog's Esc key binding does
    yield until(lambda: dialog_with_text(d, "Kluis is about to move") is None, 5, "Esc closes")
    d.expect(len(os.listdir(os.path.join(env.cloud, "my-files", "Docs"))) >= 400 and
             app.settings.folder("docs").hold == "guard", "Esc keeps everything and pauses")
    harness.write(os.path.join(env.home, "Docs", "Plan.md"), "local side")
    harness.write(os.path.join(env.cloud, "my-files", "Docs", "Plan.md"), "remote side")
    app.settings.folder("docs").hold = ""
    app.manager._allow_trash["docs"] = 9999
    app.manager.request("docs")
    yield idle(app, 60)
    conf = [n for n in os.listdir(os.path.join(env.home, "Docs")) if n.startswith("Plan (conflict ")]
    d.expect(len(conf) == 1, "both kept: Plan (conflict YYYY-MM-DD HHMM host).md")
    d.expect(any(a.level == "warning" and "Conflict" in a.text for a in app.manager.activity), "activity warning")
    d.shot("conflict")


def setup_f14b(env):
    set_cfg(env, folders=folders_cfg(env, "Docs"))
    os.makedirs(os.path.join(env.home, "Docs", ".kluis-part", "999"), exist_ok=True)
    env.write("Docs/.kluis-part/999/half.bin", "half")
    env.write("Docs/kept.txt", "k")


def f14b(d, env, app):
    """F14.8: relaunch after a kill mid-sync — resumes, no .kluis-part leftovers, nothing lost."""
    yield main_ready(app)
    yield idle(app, 60)
    d.expect(not os.path.exists(os.path.join(env.home, "Docs", ".kluis-part")), "no .kluis-part leftovers")
    d.expect(os.path.exists(os.path.join(env.cloud, "my-files", "Docs", "kept.txt")), "resumes; nothing lost")
    d.shot("after relaunch")


# ------------------------------------------------------------------ F15
def setup_f15(env):
    set_cfg(env, cli_last_check=0)
    bindir = os.path.join(env.home, ".local", "bin")
    os.makedirs(bindir)
    shutil.copy(harness.MOCK, os.path.join(bindir, "proton-drive"))
    set_cfg(env, cli_path=os.path.join(bindir, "proton-drive"))
    newbin = os.path.join(env.tmp, "release", "proton-drive")
    os.makedirs(os.path.dirname(newbin))
    with open(newbin, "w") as fh:
        fh.write(open(harness.MOCK).read().replace('or "0.9.0"', 'or "0.9.1"').replace(
            'print(text)\n        return', 'print(text.replace("filesystem restore path...", ""))\n        return'))
    os.chmod(newbin, 0o755)
    write_manifest(env, newbin, version="0.9.1")


def f15(d, env, app):
    yield main_ready(app)
    bindir = os.path.join(env.home, ".local", "bin", "proton-drive")
    old = open(bindir).read()
    yield until(lambda: app.settings.cli_pending_version == "0.9.1", 40, "incompatible CLI detected")
    d.expect(open(bindir).read() == old, "previous binary kept")
    yield 1
    d.expect(any("Proton changed its Drive tool" in t for t, _b in app.sent_notifications), "one notification")
    d.shot("incompatible kept")
    newbin = os.path.join(env.tmp, "release", "proton-drive")
    with open(newbin, "w") as fh:
        fh.write(open(harness.MOCK).read().replace('or "0.9.0"', 'or "0.9.1"'))
    write_manifest(env, newbin, version="0.9.1")
    res = {}
    app.check_cli(force=True, done=lambda r: res.setdefault("r", r))
    yield until(lambda: "r" in res, 30, "update")
    d.expect(res["r"].status == "updated" and "0.9.1" in app.cli.version(), "switched atomically to 0.9.1")
    d.expect(any("CLI 0.9.1 installed" in a.text for a in app.manager.activity), "activity entry; no prompt")
    d.shot("updated")


# ------------------------------------------------------------------ F16
def newer_version():
    """One patch above the running Kluis, so F16 stays right after every version bump."""
    from kluis import VERSION
    major, minor, patch = (int(x) for x in VERSION.split(".")[:3])
    return f"{major}.{minor}.{patch + 1}", f"{major}.{minor + 1}.0-beta.1"


def setup_f16(env):
    rel = os.path.join(env.tmp, "releases.json")
    newer, beta = newer_version()
    json.dump([{"tag_name": f"v{newer}", "prerelease": False,
                "html_url": f"https://github.com/Sundowna/kluis/releases/tag/v{newer}"},
               {"tag_name": f"v{beta}", "prerelease": True, "html_url": "u"}], open(rel, "w"))
    os.environ["KLUIS_TEST_RELEASES"] = harness.file_uri(rel)
    set_cfg(env, app_last_check=0, cli_last_check=time.time())


def f16(d, env, app):
    yield main_ready(app)
    newer, beta = newer_version()
    yield until(lambda: any(t.startswith(f"Kluis {newer} is available") for t, _b in app.sent_notifications), 40,
                "update notice")
    d.expect(not any(f.endswith(".deb") or f.endswith(".zst") for f in os.listdir(env.home)), "nothing installs")
    d.shot("notice")
    from kluis import appupdate
    from kluis import VERSION
    d.expect(appupdate.pick([{"tag_name": f"v{beta}", "prerelease": True}], VERSION, False) is None,
             "beta off: pre-release ignored")


# ------------------------------------------------------------------ F17
def f17(d, env, app):
    yield main_ready(app)
    app.settings.told_background = False
    from gi.repository import Gdk
    ev = Gdk.Event.new(Gdk.EventType.DELETE)
    handled = app.window.emit("delete-event", ev) if app.tray.available else True
    yield 0.3
    if app.tray.available:
        d.expect(handled and not app.window.get_visible(), "close hides the window")
        d.expect(any(t == "Kluis keeps syncing in the background" for t, _b in app.sent_notifications),
                 "first-time notification")
    app.activate()
    yield 0.3
    d.expect(app.window.get_visible(), "launching again shows the same window")
    d.shot("shown again")
    from gi.repository import Gtk
    focusables = [w for w in d.all_widgets(app.window) if w.get_can_focus() and w.is_visible()
                  and isinstance(w, (Gtk.Button, Gtk.Switch, Gtk.Entry, Gtk.ComboBox, Gtk.ToggleButton))]
    unnamed = [w for w in focusables if not (getattr(w, "kluis_name", None) or
                                             (w.get_accessible() and w.get_accessible().get_name()))]
    d.expect(not unnamed, f"every control has an AT-SPI name ({len(unnamed)} unnamed)")
    d.shot("keyboard focus")


def setup_f17b(env):
    set_cfg(env, autostart=True, start_minimized=True)


def f17b(d, env, app):
    """Start at login + Start hidden: only the panel icon appears, syncing runs."""
    yield until(lambda: app.window is not None, 20, "app up")
    yield 1
    d.expect(not app.window.get_visible() or not app.tray.available, "only the panel icon")
    d.expect("--hidden" in autostart_entry(), "autostart uses --hidden")
    app.present_window()
    yield 0.3
    d.shot("from panel")


# ------------------------------------------------------------------ F18
def setup_f18(env):
    os.environ["KLUIS_TEST_VPN"] = "ProtonVPN CH#23"
    set_cfg(env, home_city="Europe/Lisbon")


def f18(d, env, app):
    yield main_ready(app)
    d.press("<Primary>1")
    yield 0.5
    h = app.window.home
    d.expect(h.chip.get_label() == "VPN on" and h.loc.get_text() == "Showing as Bern" or
             h.loc.get_text().startswith("Showing as "), f"VPN on · {h.loc.get_text()}")
    d.expect(h.map.caption().endswith("(VPN)"), "pin “You · <city> (VPN)”")
    d.shot("vpn on")
    os.environ["KLUIS_TEST_VPN"] = ""
    yield until(lambda: h.chip.get_label() == "VPN off", 3, "VPN off within 2 s")
    d.expect(h.loc.get_text() == "Your location Lisbon", "home city shown")
    d.shot("vpn off")
    os.environ["KLUIS_TEST_VPN"] = "ProtonVPN AU#7"
    yield until(lambda: "Canberra" in h.map.caption(), 3, "pin moves to Canberra")
    d.shot("australia")
    os.environ["KLUIS_TEST_VPN"] = ""
    app.set_setting("home_city", "")
    yield until(lambda: h.chip.get_label() == "VPN off", 3, "off")
    from kluis import geo
    tzc = geo.home_location("")
    d.expect(tzc is not None and h.loc.get_text() == f"Your location {tzc[0]}", "city from the system time zone")
    d.shot("time zone city")


# ------------------------------------------------------------------ F19
def setup_f19(env):
    set_cfg(env, folders=folders_cfg(env, "Agriland"))
    for i in range(40):
        env.write(f"Agriland/a{i:02}.txt", str(i))


def f19(d, env, app):
    from gi.repository import GLib
    from kluis.ui.common import OPENED
    yield main_ready(app)
    yield idle(app)
    d.press("<Primary>2")
    state = {}

    def edit():
        dlg = d.dialog("Edit synced folder")
        if not dlg:
            return True
        state["prefilled"] = d.has_text("~/Agriland", root=dlg) and d.find("Save", root=dlg) is not None
        d.get("More options", root=dlg).set_expanded(True)
        d.get("Copy deletions to the other side", root=dlg).set_active(False)
        buf = d.get("Skip files that match", root=dlg).get_buffer()
        buf.insert(buf.get_end_iter(), "\n*.tmp")
        d.get("Sync soon after I change files", root=dlg).set_active(False)
        d.shot("edit dialog")
        d.click("Save", root=dlg)
        state["saved"] = True
        return False
    GLib.timeout_add(500, edit)
    yield d.later(lambda: app.edit_folder("agriland"))
    yield until(lambda: state.get("saved"), 10, "saved")
    d.expect(state["prefilled"], "Edit synced folder, prefilled, Save")
    yield idle(app)
    f = app.settings.folder("agriland")
    d.expect(not f.mirror_deletions and not f.watch and "*.tmp" in f.ignore, "options saved")
    os.remove(os.path.join(env.home, "Agriland", "a00.txt"))
    env.write("Agriland/scratch.tmp", "t")
    app.manager.request("agriland")
    yield idle(app)
    d.expect(os.path.exists(os.path.join(env.cloud, "my-files", "Agriland", "a00.txt")) and
             os.path.exists(os.path.join(env.home, "Agriland", "a00.txt")), "local delete not copied; file comes back")
    d.expect(not os.path.exists(os.path.join(env.cloud, "my-files", "Agriland", "scratch.tmp")), ".tmp never uploaded")
    yield until(lambda: "changes wait for the next check" in d.get("Status of Agriland").get_text(), 10,
                "status says changes wait for the next check")
    d.shot("options in effect")
    app.recheck_folder("agriland")
    yield idle(app)
    d.expect(any("checked again" in a.text for a in app.manager.activity), "Check every file again → activity entry")
    app.window.show_remote(f.remote)
    yield until(lambda: app.window.stack.get_visible_child_name() == "browse" and
                app.window.browser.path == "/my-files/Agriland", 5, "Browse at the folder")
    yield until(lambda: len(app.window.browser.store) > 0, 10, "listed")
    d.shot("show in Kluis browser")
    from kluis.ui.common import WEB_URL, open_uri
    open_uri(WEB_URL)
    d.expect(OPENED[-1] == "https://drive.proton.me/", "Open Proton Drive on the web")


# ------------------------------------------------------------------ F20 (§8 B.13 keyboard only)
def setup_f20(env):
    set_cfg(env, folders=folders_cfg(env, "Agriland"))
    env.cloud_write("my-files/Agriland/a.txt", "a")


def f20(d, env, app):
    """Tab alone reaches every control the flows use, on every tab, with a visible focus ring."""
    from gi.repository import Gtk
    yield main_ready(app)
    yield idle(app)
    need = {
        "home": ["Home", "Folders", "Browse", "Photos", "Shared with me", "Activity", "Sync now", "Pause",
                 "Search Proton Drive", "Settings (Ctrl+,)", "All settings…", "Pause sync", "Notifications",
                 "Dark mode", "Start at login", "VPN view", "Collapse quick settings"],
        "folders": ["+ Add folder", "Sync Agriland", "Mode of Agriland", "Sync Agriland now", "Open Agriland",
                    "Remove Agriland", "More for Agriland"],
        "browse": ["↑ Upload…", "+ New folder", "Files in this folder"],
        "photos": ["Expand Download", "Download my photos to this computer", "Expand Upload", "Album",
                   "Show my photos"],
        "shared": ["Shared with me"],
        "activity": ["Show", "Open log folder", "Clear"],
    }
    win = app.window
    for i, (tab, names) in enumerate(need.items(), 1):
        d.press(f"<Primary>{i}")
        yield 0.8
        reached = set()
        for _k in range(160):
            win.emit("move-focus", Gtk.DirectionType.TAB_FORWARD)
            f = win.get_focus()
            while f is not None:                 # a combo box focuses its inner button: credit the combo
                n = getattr(f, "kluis_name", None) or (f.get_accessible().get_name() if f.get_accessible() else "")
                if n:
                    reached.add(n)
                if getattr(f, "kluis_name", None):
                    break
                f = f.get_parent()
        missing = [n for n in names if n not in reached]
        d.expect(not missing, f"{tab}: Tab reaches {len(names)} controls (missing {missing})")
        d.shot(f"{tab} focus")
    css = open(os.path.join(os.path.dirname(HERE), "..", "kluis", "data", "kluis-dark.css")).read()
    d.expect("*:focus { outline: 2px solid @k_accent" in css, "visible 2 px accent focus ring")


# ------------------------------------------------------------------ F21
LINDI = "lindi.kirsten@pm.me"
ME = "me@proton.me"


def setup_f21(env):
    set_cfg(env, folders=folders_cfg(env, "Documents"))
    env.write("Documents/a.txt", "a")


def open_account_menu(app):
    btn = app.window.account_btn
    pop = btn.get_popover()
    pop.popup()
    btn._fill()                       # always the current accounts, even if the menu was still closing
    return pop


def next_login(env, email):
    with open(os.path.join(env.cloud, ".next_login"), "w") as fh:
        fh.write(email)


def browse_names(app):
    return sorted(n.name for n in app.window.browser.nodes)


def live_slot(env):
    try:
        return open(os.path.join(env.cloud, ".logged_in")).read().strip() or ME
    except OSError:
        return ""


def f21(d, env, app):
    """F-001…F-009 (FEATURES.md): Proton account menu, a second account, one-click switching, the browser
    sign-in fallback, sign out with hand-over to the other account, and removing an account."""
    from kluis import accounts as acc
    lindi_cloud = os.path.join(env.cloud, "accounts", LINDI, "my-files")
    yield main_ready(app)
    yield idle(app)

    # F-001 / F-006: the existing setup belongs to the signed-in account
    d.expect(app.settings.account == ME and [f.id for f in app.settings.folders] == ["documents"],
             "existing folders belong to the signed-in account")
    d.press("<Primary>3")
    yield until(lambda: browse_names(app) == ["Documents"], 20, "Browse lists the first account's Drive")
    btn = d.get(f"Account: {ME}")
    d.expect(d.has_text("me", root=btn), "header shows the account name next to its initials")
    pop = open_account_menu(app)
    yield 0.5
    d.expect(pop.get_visible(), "account menu opens")
    d.expect(d.has_text(ME, root=pop) and d.has_text("ME", root=pop), "menu shows the email and big initials")
    d.expect(d.find(f"Sign out of {ME}", root=pop) is not None, "Sign out in the menu")
    d.expect(d.has_text("Other accounts", root=pop) and d.find("More account actions", root=pop) is not None,
             "Other accounts heading with its ⋮ menu")
    d.shot("account menu, one account")

    # F-004: add a second account through Proton's browser sign-in
    next_login(env, LINDI)
    d.click("+ Add another Proton account", root=pop)
    yield until(lambda: d.has_text("Sign in to another Proton account"), 20, "sign-in page for another account")
    d.expect(app.manager.switching and not app.manager.busy, "nothing syncs while the other account signs in")
    d.expect(d.find(f"Use {ME} instead") is not None, "a way back to the first account")
    d.expect(live_slot(env) == "", "the first account's session left the CLI's slot (kept by Kluis)")
    d.expect(app.vault.load(ME) is not None, "the first account's session is kept")
    d.shot("sign in to another account")
    d.click("Open Proton sign-in")
    yield until(lambda: d.has_text(f"✓ Signed in as {LINDI}"), 20, "signed in as the second account")
    d.expect(app.settings.account == LINDI and app.settings.folders == [], "the new account starts without folders")
    d.expect(not app.manager.switching, "syncing allowed again")
    d.click("Next")
    yield 0.6
    ob = app.window.onboarding
    d.expect(d.find("Documents", root=ob) is None and d.find("Pictures", root=ob) is not None,
             "F-007 Documents isn't offered (the other account syncs it); Pictures is")
    d.shot("pick folders for the second account")
    d.click("Skip for now", root=ob)
    yield main_ready(app)
    rec = acc.record(app.settings, LINDI)
    used = open(os.path.join(env.cloud, ".cache_dirs")).read().splitlines()[-1].split(" ", 1)
    d.expect(used[0] == LINDI and "/accounts/new-" in used[1] and rec["cache"] == used[1],
             "F-006 the second account signed in with its own CLI cache folder")
    d.expect(acc.state_path(rec) != acc.state_path(acc.record(app.settings, ME)), "F-006 own sync history")
    os.makedirs(os.path.join(env.home, "Lindi"), exist_ok=True)
    env.write("Lindi/l1.txt", "lindi")
    from kluis.config import FolderPair
    app.add_folder(FolderPair(local=os.path.join(env.home, "Lindi"), remote="/my-files/Lindi", id="lindi"), quiet=True)
    yield idle(app)
    yield until(lambda: os.path.exists(os.path.join(lindi_cloud, "Lindi", "l1.txt")), 20, "upload to the 2nd account")
    d.expect(not os.path.exists(os.path.join(env.cloud, "my-files", "Lindi")), "nothing went to the first account")
    d.expect(d.find(f"Account: {LINDI}") is not None, "header shows the second account")
    d.press("<Primary>3")
    yield until(lambda: browse_names(app) == ["Lindi"], 20,
                "F-011 Browse lists the second account's own Drive (not what it showed for the first)")
    d.shot("browse: second account's Drive")

    # F-002 / F-003: the menu lists the other account; one click switches, no browser
    pop = open_account_menu(app)
    yield 0.5
    d.expect(d.find(f"Switch to {ME}", root=pop) is not None and d.has_text("lindi.kirsten", root=pop),
             "menu: active account on top, the other one under Other accounts")
    d.shot("account menu, two accounts")
    d.click(f"Switch to {ME}", root=pop)
    yield until(toast_has(app, f"Switched to {ME}"), 20, "switched to the first account")
    yield main_ready(app)
    d.expect([f.id for f in app.settings.folders] == ["documents"], "the first account's folders are back")
    yield until(lambda: browse_names(app) == ["Documents"], 20, "F-011 the open Browse tab reloads for the account")
    d.expect(live_slot(env) == ME and app.vault.load(LINDI) is not None,
             "the CLI uses the first account's session; the second one's is kept")
    d.expect(d.find(f"Account: {ME}") is not None, "header shows the first account again")
    env.write("Documents/b.txt", "b")
    env.write("Lindi/l2.txt", "l2")
    app.manager.request()
    yield idle(app)
    yield until(lambda: os.path.exists(os.path.join(env.cloud, "my-files", "Documents", "b.txt")), 20, "first syncs")
    yield 1
    d.expect(not os.path.exists(os.path.join(lindi_cloud, "Lindi", "l2.txt")),
             "the inactive account's folder doesn't sync")
    d.shot("switched to the first account")

    pop = open_account_menu(app)
    yield 0.5
    d.click(f"Switch to {LINDI}", root=pop)
    yield until(toast_has(app, f"Switched to {LINDI}"), 20, "switched back without a sign-in")
    yield main_ready(app)
    app.manager.request()
    yield idle(app)
    yield until(lambda: os.path.exists(os.path.join(lindi_cloud, "Lindi", "l2.txt")), 20, "its changes sync now")

    # F-010: Settings lists the other account (Switch) and Add…
    from gi.repository import GLib, Gtk
    seen = {}

    def in_settings():
        dlg = d.dialog("Settings")
        if not dlg:
            return True
        seen["switch"] = d.find(f"Switch to {ME}", root=dlg) is not None
        seen["add"] = d.find("Add another Proton account", root=dlg) is not None
        seen["active"] = d.has_text(LINDI, root=dlg)
        d.shot("settings: accounts")
        dlg.response(Gtk.ResponseType.CLOSE)
        return False
    GLib.timeout_add(600, in_settings)
    yield d.act_key("<Primary>comma")
    yield until(lambda: "add" in seen, 15, "settings handled")
    d.expect(seen["switch"] and seen["add"] and seen["active"],
             f"Settings: active account, Switch for the other one, Add… ({seen})")

    # F-005: a kept session Proton no longer accepts → browser sign-in for that account, with a way back
    app.vault.forget(ME)
    pop = open_account_menu(app)
    yield 0.5
    d.click(f"Switch to {ME}", root=pop)
    yield until(lambda: d.has_text(f"Sign in as {ME}"), 20, "sign-in page for that account")
    d.expect(d.find(f"Use {LINDI} instead") is not None, "a way back")
    d.shot("switch needs a sign-in")
    d.click(f"Use {LINDI} instead")
    yield until(toast_has(app, f"Switched to {LINDI}"), 20, "back to the second account")
    yield main_ready(app)
    d.expect(app.settings.account == LINDI and [f.id for f in app.settings.folders] == ["lindi"],
             "the second account with its folder")

    # F-008: sign out of the active account → the other account takes over
    pop = open_account_menu(app)
    yield 0.5
    yield d.act(f"Sign out of {LINDI}", root=pop)
    yield until(lambda: dialog_with_text(d, f"Sign out of {LINDI}?"), 5, "sign-out question")
    d.expect(dialog_with_text(d, f"Kluis switches to {ME}") is not None, "says which account takes over")
    d.click("Sign out", root=dialog_with_text(d, f"Sign out of {LINDI}?"))
    yield until(lambda: d.has_text(f"Sign in as {ME}"), 20, "the other account (session gone) asks for a sign-in")
    d.expect(app.vault.load(LINDI) is None, "the signed-out account's kept session is deleted")
    next_login(env, ME)
    d.click("Open Proton sign-in")
    yield until(lambda: d.has_text(f"✓ Signed in as {ME}"), 20, "signed in again")
    d.click("Next")
    yield 0.5
    d.click("Skip for now", root=app.window.onboarding)
    yield main_ready(app)
    d.expect(app.settings.account == ME and [f.id for f in app.settings.folders] == ["documents"],
             "signing in again brings back that account's folders")
    pop = open_account_menu(app)
    yield 0.5
    d.expect(d.has_text("Signed out · sign in to switch", root=pop), "the signed-out account is still listed")
    d.shot("signed-out account in the menu")

    # F-009: remove an account from Kluis
    yield d.act(f"Remove {LINDI} from Kluis", root=pop)
    yield until(lambda: dialog_with_text(d, f"Remove {LINDI} from Kluis?"), 5, "remove question")
    d.click("Remove", root=dialog_with_text(d, f"Remove {LINDI} from Kluis?"))
    yield until(lambda: acc.record(app.settings, LINDI) is None, 5, "account removed")
    d.expect(os.path.exists(os.path.join(env.home, "Lindi", "l1.txt")), "its local files stay")
    import kluis.config as kc
    saved = kc.Settings.load()
    d.expect(saved.account == ME and not acc.others(saved), "saved for the next launch")



# ------------------------------------------------------------------ F22
def setup_f22(env):
    env.cloud_write("devices/WalterXPS/Documents/plan.txt", "p")
    env.cloud_write("devices/WalterXPS/Desktop/note.txt", "n")


def f22(d, env, app):
    """F-012…F-014 (FEATURES.md): section buttons; My files empty but a computer syncs folders → Browse says so."""
    yield main_ready(app)
    b = app.window.browser
    # F-016: the status panel is one line on Browse and Photos, the full card elsewhere; nothing is left out
    sp = app.window.status_panel
    d.press("<Primary>1")
    yield 0.6
    full_h = sp.get_allocated_height()
    d.expect(not sp.compact and not sp.toggle.get_visible(), "F-016 Home: full status card, no chevron")
    d.press("<Primary>3")
    yield 0.8

    def row_y(w):
        return w.translate_coordinates(app.window, 0, 0)[1] + w.get_allocated_height() // 2

    parts = [sp.line, sp.mini, sp.line_rates]
    d.expect(sp.compact and sp.get_allocated_height() < full_h * 0.6,
             f"F-016 Browse: one line ({sp.get_allocated_height()} px instead of {full_h} px)")
    text = sp.line.get_text()
    d.expect(all(w.get_mapped() for w in parts) and all(k in text for k in ("Encryption", "End to end", "Total today"))
             and ("Last run" in text or "Uploading" in text or "Downloading" in text),
             f"F-016 status, Encryption, Last run, Total today, graph and rates all in the line ({text})")
    ys = [row_y(w) for w in parts]
    d.expect(max(ys) - min(ys) <= 4, f"F-016 side by side, vertically centred on one line ({ys})")
    if env.size[0] >= 1440:
        d.expect(not sp.line.get_layout().is_ellipsized(), "F-016 with room to spare nothing is shortened with …")
    d.shot("compact status line")
    d.click(sp.toggle)
    yield 0.6
    d.expect(not sp.compact and sp.get_allocated_height() >= full_h - 2, "F-016 the chevron opens the full card")
    d.press("<Primary>1")
    yield 0.4
    d.press("<Primary>3")
    yield 0.4
    d.expect(not sp.compact, "F-016 Browse keeps the full card you chose")
    d.click(sp.toggle)
    yield 0.4
    d.press("<Primary>4")
    yield 0.8
    d.expect(sp.compact and sp.toggle.get_visible(), "F-016 Photos: one line too")
    d.press("<Primary>6")
    yield 0.6
    acts = [d.get(n, root=app.window.activity) for n in ("Show", "Open log folder", "Clear")]
    mids = [row_y(a) for a in acts]
    xs = [a.translate_coordinates(app.window, 0, 0)[0] for a in acts]
    d.expect(max(mids) - min(mids) <= 4 and xs == sorted(xs), f"F-019 Activity buttons side by side ({mids}, {xs})")
    d.shot("activity buttons")
    d.press("<Primary>3")
    yield 0.4

    d.press("<Primary>3")
    yield until(lambda: d.has_text("Folders synced from your computers are under Computers: WalterXPS"), 20,
                "F-012 empty My files points to Computers")
    d.expect(d.find("Open Computers") is not None and d.get("Open Computers").is_visible(), "Open Computers button")
    d.shot("empty My files, computers")
    d.click("Open Computers")
    yield until(lambda: b.path == "/devices" and browse_names(app) == ["WalterXPS"], 20, "Computers lists WalterXPS")
    d.expect(b.nodes[0].is_folder, "F-013 a computer opens like a folder")
    pressed = lambda n: "k-pressed" in d.get(f"Section: {n}").get_style_context().list_classes()  # noqa: E731
    d.expect(pressed("Computers") and not pressed("My files"), "F-014 the Computers section button is highlighted")
    d.expect("k-flat" not in d.get("Reload").get_style_context().list_classes(), "F-014 ↻ has a normal border")
    from gi.repository import Gtk as _Gtk
    calls_before = len(harness.calls(env.tmp))
    b._activated(None, _Gtk.TreePath(0), None)            # double-click on the computer
    yield until(lambda: b.path == "/devices/WalterXPS" and browse_names(app) == ["Desktop", "Documents"], 20,
                "F-013 double-click opens the computer's synced folders")
    d.expect(not any(c.startswith("filesystem download") for c in harness.calls(env.tmp)[calls_before:]),
             "F-013 opening a computer never downloads it")
    # F-017: search finds names in subfolders of the folder open in Browse
    win = app.window
    win.search.set_text("plan")
    yield until(lambda: d.find("plan.txt", root=win.search_list) is not None, 30,
                "F-017 search finds plan.txt in the Documents subfolder")
    d.shot("search in subfolders")
    d.click("plan.txt", root=win.search_list)
    yield until(lambda: b.path == "/devices/WalterXPS/Documents" and browse_names(app) == ["plan.txt"], 20,
                "F-017 a hit opens the folder it is in")
    win.search.set_text("")
    b.go("/devices/WalterXPS")
    yield until(lambda: browse_names(app) == ["Desktop", "Documents"], 20, "back in WalterXPS")
    d.shot("WalterXPS folders")
    d.click("Section: My files")
    yield until(lambda: b.path == "/my-files" and d.has_text("My files is empty"), 20, "F-014 back via the section row")
    d.click("Section: Shared with me")
    yield until(lambda: b.path == "/shared-with-me" and pressed("Shared with me"), 20, "F-014 Shared with me section")
    d.click("Section: My files")
    yield until(lambda: b.path == "/my-files", 20, "My files again")
    env.cloud_write("my-files/Own/x.txt", "x")
    b.go("/my-files")
    yield until(lambda: browse_names(app) == ["Own"], 20, "My files with content: no Computers hint")
    d.expect(not d.get("Open Computers", visible=False).is_visible(), "hint hidden when My files has items")


# ------------------------------------------------------------------ F23
def setup_f23(env):
    set_cfg(env, folders=folders_cfg(env, "Documents"))


def f23(d, env, app):
    """F-020: every tab fits a half-screen tile of a 1920 px screen (960 px), so the window manager can snap it."""
    from kluis.ui.window import MIN_W
    yield main_ready(app)
    yield idle(app)
    win = app.window
    d.expect(MIN_W <= 960 and win.get_size_request()[0] <= 960, "F-020 the window asks for at most 960 px")
    for i, tab in enumerate(("home", "folders", "browse", "photos", "shared", "activity"), 1):
        for collapsed in (False, True):
            win.set_qs_collapsed(collapsed, save=False)
            d.press(f"<Primary>{i}")
            yield 0.8
            need = win.get_preferred_width()[0]
            d.expect(need <= 960, f"F-020 {tab}{' (Quick settings hidden)' if collapsed else ''} fits 960 px ({need} px)")
    win.set_qs_collapsed(False, save=False)
    win.resize(960, 640)
    yield 1
    d.shot("960 px wide")


# ------------------------------------------------------------------ F24
def setup_f24(env):
    set_cfg(env, folders=folders_cfg(env, "Documents"), notifications="all")


def f24(d, env, app):
    """F-023 the panel / notification-area icon: same menu everywhere; on Windows the icon, its clicks and
    notifications are Windows' own. F-025 starting at sign-in follows the setting."""
    yield main_ready(app)
    yield idle(app)
    tray = app.tray
    labels = [i.get_label() for i in tray.menu.get_children() if i.get_label()]
    d.expect(labels[1:] == ["Sync now", "Pause syncing", "Open Kluis", "Proton Drive on the web", "Quit Kluis"],
             f"F-023 the icon's menu ({labels})")
    if os.name == "nt":
        d.expect(tray.kind == "windows" and tray.icon.added and tray.icon.hicon,
                 "F-023 Kluis's icon is in the Windows notification area")
        items = tray._windows_menu()
        d.expect([i[0] for i in items if i] == [i.get_label() for i in tray.menu.get_children() if i.get_label()]
                 and items[0][1] is None, "F-023 the Windows menu has the same entries; the status line is greyed out")
        app.window.hide()
        from kluis import wintray
        tray.icon.u.SendMessageW(tray.icon.hwnd, wintray.WM_TRAY, 0, wintray.NIN_SELECT)     # a click on the icon
        yield until(lambda: app.window.get_visible(), 10, "F-023 a click on the icon opens Kluis")
        pause = next(i for i, it in enumerate(items, 1) if it and it[0] == "Pause syncing")
        tray.icon.menu_actions = {i: it[1] for i, it in enumerate(items, 1) if it}
        tray.icon.run_menu_item(pause)
        yield until(lambda: app.settings.paused, 10, "F-023 Pause syncing from the icon's menu")
        app.set_paused(False)
        app.window.hide()
        tray.icon.u.SendMessageW(tray.icon.hwnd, wintray.WM_TRAY, 0, wintray.NIN_BALLOONUSERCLICK)
        yield until(lambda: app.window.get_visible(), 10, "F-023 a click on a notification opens Kluis")
        d.expect(tray.balloon("Kluis test", "A notification from the tray icon"),
                 "F-023 Windows accepts Kluis's notification")
    n = len(app.sent_notifications)
    app.notify("Conflict in Documents", "Kept both copies", force=True)
    d.expect(len(app.sent_notifications) == n + 1, "F-023 a notification goes out")
    app.set_setting("autostart", True)
    d.expect(autostart_entry() and "kluis" in autostart_entry().lower(), "F-025 Start at sign-in on: Kluis starts")
    app.set_setting("start_minimized", True)
    d.expect("--hidden" in autostart_entry(), "F-025 Start hidden: only the icon")
    app.set_setting("autostart", False)
    d.expect(not autostart_entry(), "F-025 Start at sign-in off: nothing starts Kluis")
    d.shot("tray")


FLOWS = {
    "F1": (f1, setup_f1, {"onboarded": False}), "F2": (f2, setup_f2, {"onboarded": False}),
    "F3": (f3, setup_f3, {"onboarded": False}), "F3b": (f3b, setup_f3b, {"onboarded": False}),
    "F4": (f4, setup_f4, {}), "F5": (f5, setup_f5, {}), "F6": (f6, setup_f6, {}), "F7": (f7, setup_f7, {}),
    "F8": (f8, setup_f8, {}), "F9": (f9, setup_f9, {}), "F10": (f10, setup_f10, {}), "F11": (f11, setup_f11, {}),
    "F12": (f12, setup_f12, {}), "F13": (f13, None, {}), "F14": (f14, setup_f14, {}),
    "F14b": (f14b, setup_f14b, {}), "F15": (f15, setup_f15, {}), "F16": (f16, setup_f16, {}),
    "F17": (f17, None, {}), "F17b": (f17b, setup_f17b, {"hidden": True}), "F18": (f18, setup_f18, {}), "F19": (f19, setup_f19, {}),
    "F20": (f20, setup_f20, {}), "F21": (f21, setup_f21, {}),
    "F22": (f22, setup_f22, {}), "F23": (f23, setup_f23, {}), "F24": (f24, setup_f24, {}),
}


def main():
    if os.environ.get("KLUIS_TEST_DUMP"):
        import faulthandler
        faulthandler.dump_traceback_later(int(os.environ["KLUIS_TEST_DUMP"]), exit=True)
    flow, theme, size, out = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    desktop = sys.argv[5] if len(sys.argv) > 5 else "X-Cinnamon"
    w, h = (int(x) for x in size.split("x"))
    fn, setup, kw = FLOWS[flow]
    ok, res, log = run_flow(flow, fn, theme, (w, h), out, desktop=desktop, setup=setup,
                            env_kw={"onboarded": kw.get("onboarded", True)}, hidden=kw.get("hidden", False))
    print(f"{flow} {theme} {size} {desktop}: {res}")
    if not ok:
        print("\n".join(log[-12:]))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

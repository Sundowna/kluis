"""In-process GUI test driver (decisions D1).

Runs Kluis under Xvfb with the mock CLI. A flow is a generator: it acts on widgets found by their
accessible name (the same name AT-SPI exposes) and yields waits. Steps run from GLib timeouts, so they
keep running inside modal dialogs' nested main loops. Every step is screenshotted.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tests"))
import harness  # noqa: E402


class FlowFailed(Exception):
    pass


class Env:
    """Isolated HOME, XDG dirs and mock cloud, created before GTK is imported."""

    def __init__(self, theme="dark", size=(1440, 900), desktop="X-Cinnamon", vpn="", onboarded=True,
                 config=None):
        self.tmp = harness.setup("kluis-gui-")
        real_home = os.path.expanduser("~")
        # never let a test find (and use) the real, signed-in proton-drive of this machine
        os.environ["PATH"] = os.pathsep.join(p for p in os.environ.get("PATH", "").split(os.pathsep)
                                             if not p.startswith(real_home) and p != "/usr/local/bin")
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home, exist_ok=True)
        os.environ["HOME"] = self.home
        os.environ["KLUIS_TEST_THEME"] = theme
        os.environ["KLUIS_TEST_VPN"] = vpn
        os.environ["XDG_CURRENT_DESKTOP"] = desktop
        os.environ.setdefault("TZ", "Europe/Zurich")
        for d in ("Documents", "Pictures", "Desktop", "Music", "Downloads"):
            os.makedirs(os.path.join(self.home, d), exist_ok=True)
        os.makedirs(os.environ["XDG_CONFIG_HOME"], exist_ok=True)
        with open(os.path.join(os.environ["XDG_CONFIG_HOME"], "user-dirs.dirs"), "w") as fh:
            for k, d in (("DOCUMENTS", "Documents"), ("PICTURES", "Pictures"), ("DESKTOP", "Desktop"),
                         ("MUSIC", "Music"), ("DOWNLOAD", "Downloads")):
                fh.write(f'XDG_{k}_DIR="$HOME/{d}"\n')
        self.cloud = os.path.join(self.tmp, "cloud")
        self.size = size
        cfg = {"cli_path": harness.MOCK, "onboarded": onboarded, "theme": theme, "autostart": False,
               "window": {"w": size[0], "h": size[1], "x": 0, "y": 0, "max": False}, "told_background": True,
               "root_dir": os.path.join(self.home, "Proton Drive")}
        cfg.update(config or {})
        os.makedirs(os.path.join(os.environ["XDG_CONFIG_HOME"], "kluis"), exist_ok=True)
        with open(os.path.join(os.environ["XDG_CONFIG_HOME"], "kluis", "config.json"), "w") as fh:
            json.dump(cfg, fh)

    def write(self, rel, text="x"):
        harness.write(os.path.join(self.home, rel), text)

    def cloud_write(self, rel, text="x"):
        harness.write(os.path.join(self.cloud, rel), text)

    def flag(self, name, on=True):
        harness.flag(self.tmp, name, on)

    def cleanup(self):
        harness.cleanup(self.tmp)


class Driver:
    def __init__(self, env: Env, flow_id: str, shots_dir: str, label: str):
        from gi.repository import GLib, Gtk  # noqa: F401
        self.env = env
        self.flow = flow_id
        self.shots = os.path.join(shots_dir, flow_id)
        os.makedirs(self.shots, exist_ok=True)
        self.label = label
        self.step = 0
        self.result = None
        self.log: list[str] = []

    # ---------- widget lookup ----------
    @staticmethod
    def _children(w):
        from gi.repository import Gtk
        out = []
        if isinstance(w, Gtk.Container):
            out = list(w.get_children())
            if isinstance(w, Gtk.MenuButton) and w.get_popover():
                out.append(w.get_popover())
        if hasattr(w, "get_popover") and not isinstance(w, Gtk.MenuButton):
            try:
                p = w.get_popover()
                if p:
                    out.append(p)
            except TypeError:
                pass
        return out

    def all_widgets(self, root=None):
        from gi.repository import Gtk
        roots = [root] if root else [t for t in Gtk.Window.list_toplevels() if t.get_visible()]
        seen, stack, out = set(), list(reversed(roots)), []
        while stack:
            w = stack.pop()
            if id(w) in seen:
                continue
            seen.add(id(w))
            out.append(w)
            stack.extend(reversed(self._children(w)))      # pre-order: document order
        return out

    def find(self, name, root=None, visible=True, cls=None, exact=True):
        """Controls named with a11y() first; plain ATK names (e.g. a label's text) only as a fallback."""
        widgets = self.all_widgets(root)
        for pass_ in (0, 1):
            for w in widgets:
                n = getattr(w, "kluis_name", None)
                if n is None and pass_ == 1:
                    acc = w.get_accessible()
                    n = acc.get_name() if acc else None
                if not n:
                    continue
                if (n == name if exact else name in n) and (not visible or w.is_visible()) and \
                        (cls is None or isinstance(w, cls)):
                    return w
        return None

    def get(self, name, **kw):
        w = self.find(name, **kw)
        if w is None:
            raise FlowFailed(f"widget not found: {name!r}")
        return w

    def dialog(self, title):
        from gi.repository import Gtk
        for t in Gtk.Window.list_toplevels():
            if isinstance(t, Gtk.Dialog) and t.get_visible() and (getattr(t, "kluis_name", "") == title or
                                                                 t.get_title() == title):
                return t
        return None

    def texts(self, root=None):
        from gi.repository import Gtk
        out = []
        for w in self.all_widgets(root):
            if isinstance(w, Gtk.Label) and w.is_visible():
                out.append(w.get_text())
            elif isinstance(w, Gtk.Button) and w.is_visible() and w.get_label():
                out.append(w.get_label())
        return out

    def has_text(self, text, root=None):
        return any(text in t for t in self.texts(root))

    # ---------- actions ----------
    def click(self, name, **kw):
        w = self.get(name, **kw) if isinstance(name, str) else name
        if not w.is_sensitive():
            raise FlowFailed(f"{getattr(w, 'kluis_name', w)} is disabled")
        w.clicked()

    def later(self, fn, settle=0.4):
        """Run fn from its own main-loop callback and wait until it has started (+ settle time).

        Needed for anything that opens a modal dialog: dialog.run() spins a nested main loop, and the
        flow's own tick can only continue inside it when the dialog wasn't opened from within the tick."""
        from gi.repository import GLib
        started = {}

        def go():
            started["t"] = time.monotonic()
            fn()
            return False
        GLib.idle_add(go)
        return until(lambda: "t" in started and time.monotonic() - started["t"] >= settle, 15, "action to start")

    def act(self, name, **kw):
        """Deferred click (for buttons that open dialogs): `yield d.act("Rename")`."""
        w = self.get(name, **kw) if isinstance(name, str) else name
        if not w.is_sensitive():
            raise FlowFailed(f"{getattr(w, 'kluis_name', w)} is disabled")
        return self.later(w.clicked)

    def act_key(self, accel):
        return self.later(lambda: self.press(accel))

    def press(self, accel):
        """Activate an application/window shortcut, e.g. '<Ctrl>3'."""
        app = self.app
        for action in app.get_actions_for_accel(accel):
            group, name = action.split(".", 1)
            target = app if group == "app" else app.window
            target.activate_action(name, None)
            return
        raise FlowFailed(f"no action for {accel}")

    # ---------- screenshots ----------
    def shot(self, note=""):
        from gi.repository import Gdk, Gtk
        for _i in range(200):           # let GTK draw what the last action changed
            if not Gtk.events_pending():
                break
            Gtk.main_iteration_do(False)
        self.step += 1
        root = Gdk.get_default_root_window()
        w, h = self.env.size
        pb = Gdk.pixbuf_get_from_window(root, 0, 0, w, h)
        name = f"{self.step:02d}-{self.label}.png"
        if pb:
            pb.savev(os.path.join(self.shots, name), "png", [], [])
        self.log.append(f"{self.step:02d} {note}")

    def expect(self, cond, what):
        if not cond:
            self.shot("FAILED: " + what)
            raise FlowFailed(what)
        self.log.append(f"   ok - {what}")

    # ---------- running ----------
    def run(self, flow_fn, app):
        from gi.repository import GLib
        self.app = app
        gen = flow_fn(self, self.env, app)
        state = {"until": None, "deadline": 0, "what": ""}

        def tick():
            try:
                if state["until"] is not None:
                    if state["until"]():
                        state["until"] = None
                    elif time.monotonic() > state["deadline"]:
                        self.shot("TIMEOUT: " + state["what"])
                        raise FlowFailed("timed out waiting for " + state["what"])
                    else:
                        return True
                item = next(gen)
                if isinstance(item, (int, float)):
                    end = time.monotonic() + item
                    state["until"], state["deadline"], state["what"] = (lambda: time.monotonic() >= end), end + 1, \
                        "sleep"
                elif isinstance(item, tuple):
                    cond, timeout, what = item
                    state["until"], state["deadline"], state["what"] = cond, time.monotonic() + timeout, what
                return True
            except StopIteration:
                self.result = "PASS"
            except FlowFailed as e:
                self.result = f"FAIL: {e}"
            except Exception as e:  # noqa: BLE001
                self.result = f"ERROR: {type(e).__name__}: {e}\n{traceback.format_exc()}"
            GLib.idle_add(self._finish)
            return False
        GLib.timeout_add(120, tick)

    def _finish(self):
        from gi.repository import Gtk
        for t in Gtk.Window.list_toplevels():
            if isinstance(t, Gtk.Dialog) and t.get_visible():
                t.response(-6)
        self.app.manager.shutdown()
        self.app.release()
        self.app.quit()
        return False


def until(cond, timeout=15, what="condition"):
    return (cond, timeout, what)


def run_flow(flow_id, fn, theme, size, shots_dir, desktop="X-Cinnamon", setup=None, env_kw=None):
    env = Env(theme=theme, size=size, desktop=desktop, **(env_kw or {}))
    if setup:
        setup(env)
    label = f"{theme}-{size[0]}x{size[1]}"
    from gi.repository import GLib  # noqa: F401
    from kluis.app import KluisApp
    import kluis.app as kapp
    kapp.KluisApp.sent_notifications = []
    app = KluisApp()
    d = Driver(env, flow_id, shots_dir, label)
    app.connect("activate", lambda *_: GLib.idle_add(lambda: (d.run(fn, app), False)[1]))
    app.run([])
    ok = d.result == "PASS"
    with open(os.path.join(d.shots, f"log-{label}.txt"), "w") as fh:
        fh.write("\n".join(d.log + [d.result or "no result"]) + "\n")
    env.cleanup()
    return ok, d.result, d.log


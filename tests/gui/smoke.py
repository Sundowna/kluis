"""Smoke: start the app on each tab and screenshot. Run under xvfb-run + dbus-run-session."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from driver import run_flow, until

def flow(d, env, app):
    yield until(lambda: app.window and app.window.root.get_visible_child_name() == "main", 20, "main window")
    yield 1.5
    for i in range(1, 7):
        d.press(f"<Primary>{i}")
        yield 1.2
        d.shot(f"tab {i}")

def setup(env):
    env.write("Documents/a.txt", "hello")
    env.cloud_write("my-files/Remote/r.txt", "remote")

theme = sys.argv[1] if len(sys.argv) > 1 else "dark"
ok, res, log = run_flow("smoke", flow, theme, (1440, 900), sys.argv[2] if len(sys.argv) > 2 else "/tmp/kluis-shots",
                        setup=setup, env_kw={"config": {"folders": [{"local": "", "remote": "/my-files/Documents"}]}})
print(res); print("\n".join(log))

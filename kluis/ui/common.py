"""Small widget helpers shared by the UI."""
from __future__ import annotations

import os
import subprocess
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

WEB_URL = "https://drive.proton.me/"


def label(text="", *classes, xalign=0.0, wrap=False, markup=False, ellipsize=False, selectable=False):
    lb = Gtk.Label()
    if markup:
        lb.set_markup(text)
    else:
        lb.set_text(text)
    lb.set_xalign(xalign)
    lb.set_line_wrap(wrap)
    if ellipsize:
        from gi.repository import Pango
        lb.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
    lb.set_selectable(selectable)
    for c in classes:
        lb.get_style_context().add_class(c)
    return lb


def styled(widget, *classes):
    ctx = widget.get_style_context()
    for c in classes:
        ctx.add_class(c)
    return widget


def icon_button(icon: str, tooltip: str, on_click=None, *classes, flat=True):
    b = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
    b.set_tooltip_text(tooltip)
    b.set_valign(Gtk.Align.CENTER)
    if flat:
        styled(b, "flat")
    styled(b, *classes)
    if on_click:
        b.connect("clicked", lambda *_: on_click())
    return b


def text_button(text: str, on_click=None, *classes, icon: str | None = None):
    b = Gtk.Button()
    box = Gtk.Box(spacing=6)
    if icon:
        box.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON), False, False, 0)
    box.pack_start(Gtk.Label(label=text), False, False, 0)
    box.set_halign(Gtk.Align.CENTER)
    b.add(box)
    styled(b, *classes)
    if on_click:
        b.connect("clicked", lambda *_: on_click())
    return b


def popover_menu(relative_to, items):
    """items: list of (label, callback) or None for a separator."""
    pop = Gtk.Popover.new(relative_to)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=6)
    for it in items:
        if it is None:
            box.pack_start(Gtk.Separator(margin_top=4, margin_bottom=4), False, False, 0)
            continue
        text, cb = it[0], it[1]
        mb = Gtk.ModelButton(text=text)
        if len(it) > 2 and it[2]:
            styled(mb, "destructive-action")
        mb.connect("clicked", lambda _b, c=cb: c())
        box.pack_start(mb, False, False, 0)
    box.show_all()
    pop.add(box)
    return pop


def short_path(path: str) -> str:
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path == home or path.startswith(home + "/") else path


def ago(ts: float) -> str:
    if not ts:
        return "never"
    d = time.time() - ts
    if d < 45:
        return "just now"
    if d < 3600:
        return f"{int(d // 60) or 1} min ago"
    if d < 86400:
        return f"{int(d // 3600)} h ago"
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def human_size(n) -> str:
    if n is None:
        return ""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def iso_short(iso: str) -> str:
    """'2026-11-17T09:41:00.000Z' -> '2026-11-17 10:41' in local time."""
    if not iso:
        return ""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso[:16].replace("T", " ")


def open_uri(uri: str):
    try:
        Gio.AppInfo.launch_default_for_uri(uri, None)
    except GLib.Error:
        subprocess.Popen(["xdg-open", uri])


def open_path(path: str):
    open_uri(Gio.File.new_for_path(path).get_uri())


def run_bg(work, done=None, error=None):
    """Run `work()` in a thread; call `done(result)` or `error(exc)` on the main thread."""
    import threading

    def go():
        try:
            r = work()
        except Exception as e:  # noqa: BLE001
            if error:
                GLib.idle_add(lambda err=e: (error(err), False)[1])
            return
        if done:
            GLib.idle_add(lambda: (done(r), False)[1])
    threading.Thread(target=go, daemon=True).start()


def mode_glyph(mode: str) -> str:
    return {"two-way": "⇄", "backup": "↑", "mirror": "↓"}.get(mode, "•")


def user_dir(kind) -> str | None:
    p = GLib.get_user_special_dir(kind)
    return p if p and os.path.isdir(p) and p != os.path.expanduser("~") else None

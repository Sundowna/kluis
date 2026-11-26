"""Small widget helpers shared by the UI. Every interactive widget gets an accessible name (AT-SPI)."""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk, Pango  # noqa: E402

from ..status import human_bytes  # noqa: E402

WEB_URL = "https://drive.proton.me/"


def a11y(widget, name: str, description: str | None = None):
    acc = widget.get_accessible()
    if acc is not None:
        acc.set_name(name)
        if description:
            acc.set_description(description)
    widget.kluis_name = name          # the GUI tests find widgets by this (same as the ATK name)
    return widget


def styled(widget, *classes):
    ctx = widget.get_style_context()
    for c in classes:
        if c:
            ctx.add_class(c)
    return widget


def unstyle(widget, *classes):
    ctx = widget.get_style_context()
    for c in classes:
        ctx.remove_class(c)
    return widget


def set_class(widget, cls: str, on: bool):
    (styled if on else unstyle)(widget, cls)


def label(text="", *classes, xalign=0.0, wrap=False, markup=False, ellipsize=False, selectable=False,
          max_chars=None):
    lb = Gtk.Label()
    if markup:
        lb.set_markup(text)
    else:
        lb.set_text(text)
    lb.set_xalign(xalign)
    lb.set_line_wrap(wrap)
    if wrap:
        lb.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if ellipsize:
        lb.set_ellipsize(Pango.EllipsizeMode.END if ellipsize == "end" else Pango.EllipsizeMode.MIDDLE)
    if max_chars:
        lb.set_max_width_chars(max_chars)
    lb.set_selectable(selectable)
    styled(lb, *classes)
    return lb


def button(text: str, on_click=None, *classes, tooltip: str | None = None, name: str | None = None,
           icon: str | None = None, sensitive=True):
    b = Gtk.Button()
    if icon:
        box = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        box.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON), False, False, 0)
        lb = Gtk.Label(label=text)
        box.pack_start(lb, False, False, 0)
        b.add(box)
        b.kluis_label = lb
    else:
        b.set_label(text)
    if tooltip:
        b.set_tooltip_text(tooltip)
    styled(b, *classes)
    if on_click:
        b.connect("clicked", lambda *_: on_click())
    b.set_sensitive(sensitive)
    return a11y(b, name or text)


def set_button_text(b: Gtk.Button, text: str, name: str | None = None):
    if hasattr(b, "kluis_label"):
        b.kluis_label.set_text(text)
    else:
        b.set_label(text)
    a11y(b, name or text)


def icon_button(icon: str, tooltip: str, on_click=None, *classes, flat=True):
    b = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
    b.set_tooltip_text(tooltip)
    b.set_valign(Gtk.Align.CENTER)
    if flat:
        styled(b, "k-flat")
    styled(b, *classes)
    if on_click:
        b.connect("clicked", lambda *_: on_click())
    return a11y(b, tooltip)


def text_button(text: str, on_click=None, *classes, icon: str | None = None):
    return button(text, on_click, *classes, icon=icon)


def switch(active: bool, on_change=None, name: str = "", tooltip: str | None = None):
    sw = Gtk.Switch(active=active, valign=Gtk.Align.CENTER)
    if tooltip:
        sw.set_tooltip_text(tooltip)
    if on_change:
        sw.connect("notify::active", lambda s, _p: on_change(s.get_active()))
    return a11y(sw, name)


def combo(options: list[tuple[str, str]], active: str, on_change=None, name: str = "", max_chars: int = 0):
    c = Gtk.ComboBoxText()
    if max_chars:
        cell = c.get_cells()[0]
        cell.set_property("ellipsize", Pango.EllipsizeMode.END)
        cell.set_property("width-chars", max_chars)
    for k, t in options:
        c.append(k, t)
    c.set_active_id(active)
    if on_change:
        c.connect("changed", lambda w: on_change(w.get_active_id()))
    return a11y(c, name)


def popover_menu(relative_to, items):
    """items: (label, callback[, destructive[, accel]]) or None for a separator."""
    pop = Gtk.Popover.new(relative_to)
    styled(pop, "k-menu")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=4)
    for it in items:
        if it is None:
            box.pack_start(Gtk.Separator(margin_top=4, margin_bottom=4), False, False, 0)
            continue
        text, cb = it[0], it[1]
        b = Gtk.Button(relief=Gtk.ReliefStyle.NONE)
        row = Gtk.Box(spacing=16)
        row.pack_start(label(text, xalign=0), True, True, 0)
        if len(it) > 3 and it[3]:
            row.pack_end(label(it[3], "k-key"), False, False, 0)
        b.add(row)
        styled(b, "k-flat")
        if len(it) > 2 and it[2]:
            styled(b, "k-danger")
        a11y(b, text)
        b.connect("clicked", lambda _b, c=cb: (pop.popdown(), GLib.idle_add(lambda: (c(), False)[1])))
        box.pack_start(b, False, False, 0)
    box.show_all()
    pop.add(box)
    pop.kluis_items = box
    return pop


def short_path(path: str) -> str:
    home = os.path.expanduser("~")
    if os.name == "nt":              # Windows: the home folder in any letter case, shown as ~ too
        if os.path.normcase(path) == os.path.normcase(home) or                 os.path.normcase(path).startswith(os.path.normcase(home) + os.sep):
            return "~" + path[len(home):]
        return path
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
        return time.strftime("%H:%M", time.localtime(ts))
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def human_size(n) -> str:
    return "" if n is None else human_bytes(n)


def iso_date(iso: str) -> str:
    """'2026-11-17T09:41:00.000Z' -> '2026-11-17' in local time."""
    if not iso:
        return ""
    try:
        from datetime import datetime
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d")
    except ValueError:
        return iso[:10]


iso_short = iso_date


def open_uri(uri: str):
    if os.environ.get("KLUIS_TEST") == "1":
        OPENED.append(uri)           # tests assert what would open, without launching apps
        return
    if os.name == "nt":              # Windows: the default browser / Explorer / program, like a double-click
        from ..system import open_with_system
        try:
            open_with_system(Gio.File.new_for_uri(uri).get_path() if uri.startswith("file:") else uri)
        except OSError as e:
            logging.getLogger("kluis.ui").warning("could not open %s: %s", uri, e)
        return
    try:
        Gio.AppInfo.launch_default_for_uri(uri, None)
    except GLib.Error:
        subprocess.Popen(["xdg-open", uri])


OPENED: list[str] = []


def open_path(path: str):
    open_uri(Gio.File.new_for_path(path).get_uri())


def run_bg(work, done=None, error=None):
    """Run `work()` in a thread; call `done(result)` or `error(exc)` on the main thread."""
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


def special_dir(kind) -> str | None:
    """Documents, Pictures, … On Windows GLib asks Windows (known folders), which the test suites can't point
    into their temporary home: there, in test mode, they are the folders of that name in the home folder."""
    if os.name == "nt" and os.environ.get("KLUIS_TEST") == "1":
        names = {GLib.UserDirectory.DIRECTORY_DOCUMENTS: "Documents", GLib.UserDirectory.DIRECTORY_PICTURES: "Pictures",
                 GLib.UserDirectory.DIRECTORY_DESKTOP: "Desktop", GLib.UserDirectory.DIRECTORY_MUSIC: "Music",
                 GLib.UserDirectory.DIRECTORY_DOWNLOAD: "Downloads", GLib.UserDirectory.DIRECTORY_VIDEOS: "Videos"}
        return os.path.join(os.path.expanduser("~"), names[kind]) if kind in names else None
    return GLib.get_user_special_dir(kind)


def user_dir(kind) -> str | None:
    p = special_dir(kind)
    return p if p and os.path.isdir(p) and p != os.path.expanduser("~") else None


def clear(box: Gtk.Container):
    for c in box.get_children():
        c.destroy()


def hbox(*children, spacing=8, **kw):
    b = Gtk.Box(spacing=spacing, **kw)
    for c in children:
        if c is not None:
            b.pack_start(c, False, False, 0)
    return b


def vbox(*children, spacing=8, **kw):
    b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing, **kw)
    for c in children:
        if c is not None:
            b.pack_start(c, False, False, 0)
    return b


def wrapbar(*children, spacing=8, per_line=3):
    """A toolbar that wraps onto a second row when the window is narrow (1024×640)."""
    fb = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=spacing, row_spacing=6,
                     homogeneous=False, max_children_per_line=20, min_children_per_line=per_line)
    fb.set_valign(Gtk.Align.START)
    for c in children:
        if c is not None:
            child = Gtk.FlowBoxChild(can_focus=False)
            child.add(c)
            fb.add(child)
    return fb


def wrap_check(check: Gtk.CheckButton, chars=40):
    """A check box whose text wraps. GtkCheckButton reports the height of its narrowest wrap, which left empty
    space under it in wide cards, so the text is a separate label next to the box (a click on it still toggles)."""
    lb = check.get_child()
    if not isinstance(lb, Gtk.Label):
        return check
    text = lb.get_text()
    check.remove(lb)
    check.set_valign(Gtk.Align.START)
    t = Gtk.Label(label=text, xalign=0.0, wrap=True)
    t.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    t.set_max_width_chars(chars * 3)
    ev = Gtk.EventBox(visible_window=False)
    ev.add(t)
    ev.connect("button-release-event", lambda *_a: (check.set_active(not check.get_active()), True)[1])
    row = Gtk.Box(spacing=6)
    row.pack_start(check, False, False, 0)
    row.pack_start(ev, True, True, 0)
    row.kluis_check = check
    return row


def ellipsize_button(b: Gtk.Button, chars=24):
    """Path buttons: shorten long paths instead of widening the window."""
    lb = b.get_child()
    if isinstance(lb, Gtk.Label):
        lb.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        lb.set_max_width_chars(chars)
    return b

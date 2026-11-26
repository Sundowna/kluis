"""Main window (HANDOVER §1 layout): sidebar · main (header, page, status panel) · Quick settings column."""
from __future__ import annotations

import os
import time
from urllib.parse import unquote, urlparse

from gi.repository import Atk, Gdk, Gio, GLib, Gtk

from ..i18n import _
from .accounts import AccountButton
from .activity import ActivityPage
from .browser import BrowserPage
from .common import (WEB_URL, a11y, button, clear, hbox, label, open_uri, popover_menu, set_button_text, set_class,
                     styled, vbox)
from .folders import FoldersPage
from .home import HomePage
from .onboarding import Onboarding
from .photos import PhotosPage
from .shared import SharedPage
from .statuspanel import StatusPanel

TABS = [("home", _("Home")), ("folders", _("Folders")), ("browse", _("Browse")), ("photos", _("Photos")),
        ("shared", _("Shared with me")), ("activity", _("Activity"))]
TL_COLORS = {"ok": "", "info": "k-info", "warning": "k-warn", "error": "k-error"}


def logo_image(size):
    """The safe logo from Kluis's own data (not a possibly older system icon)."""
    from gi.repository import GdkPixbuf
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "icons", "dev.kluis.Kluis.svg")
    try:
        return Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_size(path, size, size))
    except Exception:  # noqa: BLE001
        return Gtk.Image.new_from_icon_name("dev.kluis.Kluis", Gtk.IconSize.LARGE_TOOLBAR)


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Kluis")
        self.app = app
        s = app.settings
        styled(self, "kluis")
        self.set_icon_name("dev.kluis.Kluis")
        self.set_size_request(1024, 640)
        win = s.window or {}
        self.set_default_size(max(1024, int(win.get("w", 1440))), max(640, int(win.get("h", 900))))
        if win.get("x", -1) >= 0 and win.get("y", -1) >= 0:
            self.move(int(win["x"]), int(win["y"]))
        if win.get("max"):
            self.maximize()
        self.connect("configure-event", self._configured)
        self.connect("window-state-event", self._state_ev)

        self.overlay = Gtk.Overlay()
        self.add(self.overlay)
        self.root = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=200)
        bg = Gtk.Box()
        styled(bg, "k-bg", "k-glow")
        bg.pack_start(self.root, True, True, 0)
        self.bgbox = bg
        self.overlay.add(bg)

        self.onboarding = Onboarding(app, self._onboarding_done)
        ob = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        ob.add(self.onboarding)
        self.root.add_named(ob, "welcome")

        main = Gtk.Box(spacing=16, margin=16)
        self.root.add_named(main, "main")
        main.pack_start(self._sidebar(), False, False, 0)
        center = vbox(spacing=14)
        main.pack_start(center, True, True, 0)
        center.pack_start(self._header(), False, False, 0)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE, vexpand=True, hhomogeneous=False,
                               vhomogeneous=False)          # each tab sizes itself (fits 1024×640)
        self.home = HomePage(app)
        self.folders = FoldersPage(app)
        self.browser = BrowserPage(app)
        self.photos = PhotosPage(app)
        self.shared = SharedPage(app)
        self.activity = ActivityPage(app)
        for (key, _t), page in zip(TABS, (self.home, self.folders, self.browser, self.photos, self.shared,
                                          self.activity)):
            self.stack.add_named(page, key)
        center.pack_start(self.stack, True, True, 0)
        self.status_panel = StatusPanel(app)
        sp = Gtk.Box()
        styled(sp, "k-panel")
        sp.pack_start(self.status_panel, True, True, 0)
        center.pack_start(sp, False, False, 0)
        self.qs_col = self._quick_settings()
        main.pack_start(self.qs_col, False, False, 0)

        # toast (bottom centre, one at a time, announced to screen readers)
        self.toast_rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP, valign=Gtk.Align.END,
                                      halign=Gtk.Align.CENTER, margin_bottom=24, transition_duration=200)
        tb = Gtk.Box(spacing=14)
        styled(tb, "k-toast")
        self.toast_lbl = label("")
        acc = self.toast_lbl.get_accessible()
        if acc:
            acc.set_role(Atk.Role.NOTIFICATION)
        self.toast_action = button(_("Undo"), None)
        self.toast_action.set_no_show_all(True)
        tb.pack_start(self.toast_lbl, False, False, 0)
        tb.pack_start(self.toast_action, False, False, 0)
        self.toast_rev.add(tb)
        self.overlay.add_overlay(self.toast_rev)
        self.overlay.set_overlay_pass_through(self.toast_rev, True)
        self._toast_src = 0
        self._toast_handler = None
        self.toast_text = ""
        self.toast_history: list[str] = []

        # drag a folder anywhere on the window to add it
        self.drag_dest_set(Gtk.DestDefaults.ALL, [Gtk.TargetEntry.new("text/uri-list", 0, 0)], Gdk.DragAction.COPY)
        self.connect("drag-data-received", self._on_drop)
        self.connect("drag-motion", lambda *_: self._drag_hl(True))
        self.connect("drag-leave", lambda *_: self._drag_hl(False))
        self.connect("key-press-event", self._key)

        for i, (key, _t) in enumerate(TABS, 1):
            a = Gio.SimpleAction.new(f"tab-{i}", None)
            a.connect("activate", lambda *_a, k=key: self.show_tab(k))
            self.add_action(a)
            app.set_accels_for_action(f"win.tab-{i}", [f"<Ctrl>{i}"])
        a = Gio.SimpleAction.new("search", None)
        a.connect("activate", lambda *_: self.search.grab_focus())
        self.add_action(a)
        app.set_accels_for_action("win.search", ["<Ctrl>f"])
        self.stack.connect("notify::visible-child-name", self._page_changed)
        self.show_all()
        self.set_qs_collapsed(s.qs_collapsed, save=False)

    # ---------- sidebar ----------
    def _sidebar(self):
        side = vbox(spacing=4)
        styled(side, "k-panel", "k-side")
        side.set_size_request(280, -1)
        head = Gtk.Box(spacing=10, margin_bottom=10)
        head.pack_start(logo_image(24), False, False, 0)
        head.pack_start(label("Kluis", "k-h2"), True, True, 0)
        gear = Gtk.Button.new_from_icon_name("kluis-gear-symbolic", Gtk.IconSize.BUTTON)
        styled(gear, "k-flat")
        gear.set_tooltip_text(_("Settings (Ctrl+,)"))
        gear.connect("clicked", lambda *_: self.app.open_settings())
        a11y(gear, _("Settings (Ctrl+,)"))
        head.pack_end(gear, False, False, 0)
        side.pack_start(head, False, False, 0)
        self.search = Gtk.SearchEntry(placeholder_text=_("Search files…  Ctrl+F"))
        a11y(self.search, _("Search Proton Drive"))
        self.search.connect("search-changed", self._search_changed)
        self.search.connect("activate", self._search_activate)
        self.search_pop = Gtk.Popover.new(self.search)
        self.search_pop.set_modal(False)
        self.search_list = vbox(spacing=2, margin=6)
        self.search_pop.add(self.search_list)
        side.pack_start(self.search, False, False, 6)
        nav = vbox(spacing=2)
        styled(nav, "k-nav")
        self.nav = {}
        for i, (key, title) in enumerate(TABS, 1):
            b = Gtk.Button()
            row = Gtk.Box(spacing=8)
            row.pack_start(label(title), True, True, 0)
            badge = label("", "k-badge")
            badge.set_no_show_all(True)
            row.pack_start(badge, False, False, 0)
            row.pack_start(label(f"Ctrl+{i}", "k-key"), False, False, 0)
            b.add(row)
            b.connect("clicked", lambda _b, k=key: self.show_tab(k))
            a11y(b, title)
            b.kluis_badge = badge
            nav.pack_start(b, False, False, 0)
            self.nav[key] = b
        side.pack_start(nav, False, False, 0)
        side.pack_start(label(_("Today’s timeline"), "k-section-head"), False, False, 14)
        self.timeline = vbox(spacing=8)
        a11y(self.timeline, _("Today’s timeline"))
        tl_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                       propagate_natural_height=True)
        tl_scroll.set_min_content_height(40)       # never makes the window taller than the screen
        tl_scroll.add(self.timeline)
        side.pack_start(tl_scroll, False, False, 0)
        allact = button(_("All activity"), lambda: self.show_tab("activity"), "k-link")
        allact.set_halign(Gtk.Align.START)
        side.pack_start(allact, False, False, 4)
        return side

    def refresh_timeline(self):
        clear(self.timeline)
        today = time.strftime("%Y%m%d")
        items = [a for a in list(self.app.manager.activity)[:40]
                 if time.strftime("%Y%m%d", time.localtime(a.ts)) == today][:5]
        if not items:
            self.timeline.pack_start(label(_("Nothing yet today"), "k-muted", "k-s12"), False, False, 0)
        for a in items:
            dot = Gtk.Box(valign=Gtk.Align.START, margin_top=4)
            styled(dot, "k-timeline-dot", TL_COLORS.get(a.level, ""))
            v = vbox(hbox(label(time.strftime("%H:%M", time.localtime(a.ts)), "k-muted", "k-s12", "k-num"),
                          label(a.folder or "Kluis", "k-s12", "k-bold", ellipsize="end", max_chars=24), spacing=6),
                     label(a.text, "k-muted", "k-s12", ellipsize="end", max_chars=30), spacing=0)
            self.timeline.pack_start(hbox(dot, v, spacing=10), False, False, 0)
        self.timeline.show_all()

    def _search_changed(self, entry):
        q = entry.get_text().strip().lower()
        clear(self.search_list)
        if len(q) < 2:
            self.search_pop.popdown()
            return
        hits = self.app.search(q)[:12]
        if not hits:
            self.search_list.pack_start(label(_("No matches in synced folders or folders you opened"), "k-muted",
                                              "k-s12"), False, False, 0)
        for remote, name in hits:
            self.search_list.pack_start(button(name, lambda r=remote: self._open_hit(r), "k-flat",
                                               tooltip=remote), False, False, 0)
        self.search_list.show_all()
        self.search_pop.popup()

    def _search_activate(self, _e):
        kids = self.search_list.get_children()
        if kids and isinstance(kids[0], Gtk.Button):
            kids[0].clicked()

    def _open_hit(self, remote):
        self.search_pop.popdown()
        self.show_remote(os.path.dirname(remote))

    # ---------- header ----------
    def _header(self):
        row = Gtk.Box(spacing=8)
        self.tab_title = label("", "k-h1")
        row.pack_start(self.tab_title, True, True, 0)
        self.sync_btn = button(_("↻ Sync now"), self._sync_or_stop, tooltip=_("Sync everything now (Ctrl+R)"),
                               name=_("Sync now"))
        self.pause_btn = button(_("⏸ Pause"), lambda: self.app.set_paused(not self.app.settings.paused),
                                name=_("Pause"))
        self.qs_header_btn = self._qs_button()
        self.qs_header_btn.get_child().show_all()     # no_show_all below would otherwise keep its icons hidden
        self.qs_header_btn.set_no_show_all(True)
        self.account_btn = AccountButton(self.app)
        row.pack_end(self.account_btn, False, False, 0)
        row.pack_end(self.qs_header_btn, False, False, 0)
        row.pack_end(self.pause_btn, False, False, 0)
        row.pack_end(self.sync_btn, False, False, 0)
        return row

    def _qs_button(self):
        b = Gtk.Button()
        box = hbox(Gtk.Image.new_from_icon_name("kluis-sliders-symbolic", Gtk.IconSize.BUTTON),
                   Gtk.Image.new_from_icon_name("kluis-chevron-down-symbolic", Gtk.IconSize.BUTTON), spacing=2)
        b.add(box)
        styled(b, "k-qs-head")
        b.connect("clicked", lambda *_: self.set_qs_collapsed(not self.app.settings.qs_collapsed))
        a11y(b, _("Collapse quick settings"))
        return b

    def _sync_or_stop(self):
        if self.app.manager.busy:
            self.app.stop_sync()
        else:
            self.app.manager.request()

    # ---------- Quick settings ----------
    def _quick_settings(self):
        col = vbox(spacing=6)
        styled(col, "k-panel", "k-qs")
        col.set_size_request(100, -1)
        col.set_hexpand(False)
        self.qs_btn = self._qs_button()
        col.pack_start(self.qs_btn, False, False, 0)
        allb = Gtk.MenuButton()
        allb.add(vbox(label("⚙", "k-h2", xalign=0.5), label(_("All settings…"), "k-s12", xalign=0.5, wrap=True,
                                                             max_chars=12), spacing=0))
        a11y(allb, _("All settings…"))
        self.all_menu = popover_menu(allb, [
            (_("+ Add folder"), self.app.add_folder_dialog, False, "Ctrl+N"),
            (_("Settings"), self.app.open_settings, False, "Ctrl+,"),
            (_("Sign in…"), self.app.sign_in_again),
            (_("Open Proton Drive on the web"), lambda: open_uri(WEB_URL)),
            (_("Run setup again"), self.app.run_setup_again),
            None,
            (_("About Kluis"), self.app.about),
            (_("Quit"), self.app.quit_app, False, "Ctrl+Q"),
        ])
        allb.set_popover(self.all_menu)
        self.all_btn = allb
        col.pack_start(allb, False, False, 0)
        div = Gtk.Box()
        styled(div, "k-divider")
        col.pack_start(div, False, False, 6)
        col.pack_start(label(_("Quick settings"), "k-section-head", xalign=0.5, wrap=True, max_chars=12), False, False, 0)
        self.qs = {}
        for key, title in (("pause", _("Pause sync")), ("notify", _("Notifications")), ("dark", _("Dark mode")),
                           ("login", _("Start at login")), ("vpn", _("VPN view"))):
            b = Gtk.Button()
            st = label("", "k-qs-state", xalign=0.5)
            st.set_line_wrap(True)
            st.set_max_width_chars(12)
            b.add(vbox(label(title, xalign=0.5, wrap=True, max_chars=12), st, spacing=2))
            b.connect("clicked", lambda _b, k=key: self.app.quick_toggle(k))
            styled(b, "k-qs-toggle")
            a11y(b, title)
            b.kluis_state = st
            col.pack_start(b, False, False, 0)
            self.qs[key] = b
        return col

    def set_qs_collapsed(self, collapsed, save=True):
        if collapsed:
            # the header button takes exactly the room the column frees (its width + the 16 px gap, minus the
            # header's 8 px gap), so Sync now, Pause and the account button don't move (Walter, 2026-11-26)
            w = self.qs_col.get_allocated_width()
            self.qs_header_btn.set_size_request((w if w > 1 else 132) + 8, -1)
        self.app.settings.qs_collapsed = collapsed
        self.qs_col.set_visible(not collapsed)
        self.qs_header_btn.set_visible(collapsed)
        for b in (self.qs_btn, self.qs_header_btn):
            a11y(b, _("Expand quick settings") if collapsed else _("Collapse quick settings"))
        if save:
            self.app.settings.save()

    def refresh_quick(self):
        s = self.app.settings
        states = {
            "pause": (s.paused, _("On") if s.paused else _("Off")),
            "notify": (s.notifications != "off", {"all": _("All"), "problems": _("Problems only"),
                                                  "off": _("Off")}[s.notifications]),
            "dark": (self.app.theme.dark, _("On") if self.app.theme.dark else _("Off")),
            "login": (s.autostart, _("On") if s.autostart else _("Off")),
            "vpn": (s.vpn_view, _("On") if s.vpn_view else _("Off")),
        }
        for k, (on, text) in states.items():
            b = self.qs[k]
            set_class(b, "k-pressed", on)
            b.kluis_state.set_text(text)
            a11y(b, b.kluis_name.split(":")[0] if ":" in b.kluis_name else b.kluis_name, text)
            b.kluis_value = text

    # ---------- pages ----------
    def show_onboarding(self, state):
        self.onboarding.refresh(state)
        self.root.set_visible_child_name("welcome")

    def show_main(self, page=None):
        self.folders.rebuild()
        self.activity.rebuild()
        self.root.set_visible_child_name("main")
        self.show_tab(page or self.app.settings.last_tab or "home")
        self.app.refresh_all()

    def show_tab(self, key):
        if self.root.get_visible_child_name() != "main":
            return
        if key not in dict(TABS):
            key = "home"
        self.stack.set_visible_child_name(key)

    def show_remote(self, path):
        self.root.set_visible_child_name("main")
        self.stack.set_visible_child_name("browse")
        self.browser.go(path)

    def account_changed(self):
        """Another Proton account is active: Browse, Shared with me and Photos showed the previous one's Drive.
        Forget it; the visible tab loads again now, the others when they are next opened (decisions D30)."""
        b = self.browser
        b.path = "/my-files"
        b.nodes = []
        b.stats.cache.clear()
        b.loaded_once = False
        self.shared.loaded = False
        self.shared.items = []
        self.app.shared_cache = []
        self.photos.loaded = False
        self.photos.album = ""
        self.photos._local = None
        self.folders.rebuild()
        page = self.stack.get_visible_child()
        if self.root.get_visible_child_name() == "main" and hasattr(page, "on_shown"):
            page.on_shown()

    def _page_changed(self, *_a):
        key = self.stack.get_visible_child_name()
        self.tab_title.set_text(dict(TABS).get(key, ""))
        for k, b in self.nav.items():
            set_class(b, "k-current", k == key)
        self.app.settings.last_tab = key
        self.app.save_soon()
        if key == "activity":
            self.app.manager.mark_read()
        page = self.stack.get_visible_child()
        if hasattr(page, "on_shown"):
            page.on_shown()

    def _onboarding_done(self):
        self.show_main("home")
        self.app.manager.request(reason="start")

    # ---------- header / badges ----------
    def refresh_header(self):
        m, s = self.app.manager, self.app.settings
        set_button_text(self.sync_btn, _("■ Stop") if m.busy else _("↻ Sync now"), _("Stop") if m.busy else _("Sync now"))
        self.sync_btn.set_tooltip_text(_("Stop syncing") if m.busy else _("Sync everything now (Ctrl+R)"))
        self.sync_btn.set_sensitive(not s.paused and m.logged_in is not False and bool(s.folders or s.photos.active))
        set_button_text(self.pause_btn, _("▶ Resume") if s.paused else _("⏸ Pause"),
                        _("Resume") if s.paused else _("Pause"))
        set_class(self.pause_btn, "k-pressed", s.paused)
        n = m.unread
        badge = self.nav["activity"].kluis_badge
        badge.set_text(str(n))
        badge.set_visible(n > 0)

    # ---------- toast ----------
    def toast(self, text, action=None):
        self.toast_text = text
        self.toast_history.append(text)
        self.toast_lbl.set_text(text)
        acc = self.toast_lbl.get_accessible()
        if acc:
            acc.set_name(text)          # live region: screen readers announce the change
        if self._toast_handler:
            self.toast_action.disconnect(self._toast_handler)
            self._toast_handler = None
        if action:
            set_button_text(self.toast_action, action[0])
            self._toast_handler = self.toast_action.connect(
                "clicked", lambda *_: (self._hide_toast(), action[1]()))
            self.toast_action.show()
        else:
            self.toast_action.hide()
        self.toast_rev.set_reveal_child(True)
        if self._toast_src:
            GLib.source_remove(self._toast_src)
        self._toast_src = GLib.timeout_add_seconds(8 if action else 5, self._hide_toast)

    def _hide_toast(self):
        if self._toast_src:
            GLib.source_remove(self._toast_src)
        self._toast_src = 0
        self.toast_rev.set_reveal_child(False)
        if self._toast_handler:
            self.toast_action.disconnect(self._toast_handler)
            self._toast_handler = None
        self.toast_action.hide()
        return False

    # ---------- drag & drop ----------
    def _drag_hl(self, on):
        set_class(self.bgbox, "k-drag-over", on)
        set_class(self.folders.drop, "k-drag-over", on)
        return False

    def _on_drop(self, _w, _ctx, _x, _y, data, _info, _time):
        self._drag_hl(False)
        if self.root.get_visible_child_name() != "main":
            return
        paths = [unquote(urlparse(u).path) for u in data.get_uris() if u.startswith("file://")]
        self.handle_drop(paths)

    def handle_drop(self, paths):
        folders = [p for p in paths if os.path.isdir(p)]
        if folders:
            GLib.idle_add(lambda: (self.app.add_folder_dialog(folders[0]), False)[1])
        elif paths:
            self.toast(_("Drop a folder to sync it. To upload files, use Browse."))

    # ---------- keyboard / window state ----------
    def _key(self, _w, ev):
        if ev.keyval == Gdk.KEY_Escape and self.search.has_focus():
            self.search.set_text("")
            self.search_pop.popdown()
            return True
        return False

    def _configured(self, _w, _ev):
        if not self.app.settings.window.get("max"):
            w, h = self.get_size()
            x, y = self.get_position()
            self.app.settings.window.update({"w": w, "h": h, "x": x, "y": y})
            self.app.save_soon()
        return False

    def _state_ev(self, _w, ev):
        self.app.settings.window["max"] = bool(ev.new_window_state & Gdk.WindowState.MAXIMIZED)
        self.app.save_soon()
        return False

"""Main window: status hero, synced-folder cards, Drive browser, activity."""
from __future__ import annotations

import os
import time
from urllib.parse import unquote, urlparse

from gi.repository import Gdk, GLib, Gtk

from ..config import MODES
from .browser import BrowserPage
from .common import (WEB_URL, ago, icon_button, label, mode_glyph, open_path, open_uri, popover_menu,
                     short_path, styled, text_button)
from .onboarding import Onboarding
from .photos import PhotosPage

STATE_DOT = {"ok": "ok", "syncing": "sync", "queued": "sync", "conflict": "warn", "error": "err"}


class FolderRow(Gtk.ListBoxRow):
    def __init__(self, app, folder):
        super().__init__(activatable=False, selectable=False)
        self.app = app
        self.fid = folder.id
        card = Gtk.Box(spacing=14)
        styled(card, "k-card")
        self.badge = label("", "k-badge", xalign=0.5)
        self.badge.set_valign(Gtk.Align.CENTER)
        card.pack_start(self.badge, False, False, 0)

        mid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, valign=Gtk.Align.CENTER)
        self.title = label("", "k-card-title", ellipsize=True)
        self.route = label("", "k-dim", "k-small", ellipsize=True)
        st = Gtk.Box(spacing=7)
        self.dot = Gtk.Box(valign=Gtk.Align.CENTER)
        styled(self.dot, "k-dot")
        self.status = label("", "k-small", ellipsize=True)
        st.pack_start(self.dot, False, False, 0)
        st.pack_start(self.status, True, True, 0)
        self.bar = Gtk.ProgressBar(no_show_all=True, margin_top=4)
        mid.pack_start(self.title, False, False, 0)
        mid.pack_start(self.route, False, False, 0)
        mid.pack_start(st, False, False, 2)
        mid.pack_start(self.bar, False, False, 0)
        card.pack_start(mid, True, True, 0)

        self.switch = Gtk.Switch(valign=Gtk.Align.CENTER, tooltip_text="Sync this folder")
        self.switch.connect("notify::active", self._toggled)
        card.pack_start(self.switch, False, False, 0)
        self.sync_btn = icon_button("view-refresh-symbolic", "Sync now", lambda: app.manager.request(self.fid))
        card.pack_start(self.sync_btn, False, False, 0)
        card.pack_start(icon_button("folder-open-symbolic", "Open folder",
                                    lambda: open_path(app.settings.folder(self.fid).local)), False, False, 0)
        more = Gtk.MenuButton(image=Gtk.Image.new_from_icon_name("view-more-symbolic", Gtk.IconSize.BUTTON),
                              valign=Gtk.Align.CENTER, tooltip_text="More")
        styled(more, "flat")
        more.set_popover(popover_menu(more, [
            ("Edit…", lambda: app.edit_folder(self.fid)),
            ("Show in Kluis browser", lambda: app.window.show_remote(app.settings.folder(self.fid).remote)),
            ("Open Proton Drive on the web", lambda: open_uri(WEB_URL)),
            ("Check every file again", lambda: app.manager.folder_changed(app.settings.folder(self.fid), True)),
            None,
            ("Stop syncing this folder…", lambda: app.remove_folder(self.fid), True),
        ]))
        card.pack_start(more, False, False, 0)
        self.add(card)
        self.refresh()

    def _toggled(self, sw, _p):
        f = self.app.settings.folder(self.fid)
        if f and f.enabled != sw.get_active():
            f.enabled = sw.get_active()
            self.app.settings.save()
            self.app.manager.folder_changed(f)

    def refresh(self):
        f = self.app.settings.folder(self.fid)
        if not f:
            return
        st = self.app.manager.status.get(self.fid)
        ctx = self.badge.get_style_context()
        for m in list(MODES) + ["off"]:
            ctx.remove_class(m)
        ctx.add_class(f.mode if f.enabled else "off")
        self.badge.set_text(mode_glyph(f.mode))
        self.badge.set_tooltip_text(MODES[f.mode][1])
        self.title.set_text(f.name)
        arrow = {"two-way": "⇄", "backup": "→", "mirror": "←"}[f.mode]
        self.route.set_text(f"{short_path(f.local)}   {arrow}   {f.remote}")
        if self.switch.get_active() != f.enabled:
            self.switch.set_active(f.enabled)
        state = st.state if st else "idle"
        dctx = self.dot.get_style_context()
        for c in ("ok", "sync", "warn", "err"):
            dctx.remove_class(c)
        if state in STATE_DOT:
            dctx.add_class(STATE_DOT[state])
        sctx = self.status.get_style_context()
        sctx.remove_class("k-status-err")
        sctx.remove_class("k-status-warn")
        if state == "error":
            sctx.add_class("k-status-err")
        elif state == "conflict":
            sctx.add_class("k-status-warn")
        if not f.enabled:
            text = "Sync is off for this folder"
        elif state == "syncing":
            text = st.text or "Syncing…"
        elif state == "queued":
            text = "Waiting for its turn…"
        elif state in ("ok", "conflict", "error"):
            text = f"{st.text} · {ago(f.last_sync)}" if f.last_sync else st.text
        else:
            text = st.text if st else ""
        self.status.set_text(text)
        self.status.set_tooltip_text(text)
        if state == "syncing" and st.total:
            self.bar.set_fraction(st.done / max(st.total, 1))
            self.bar.show()
        elif state == "syncing":
            self.bar.pulse()
            self.bar.show()
        else:
            self.bar.hide()
        self.sync_btn.set_sensitive(f.enabled and state not in ("syncing", "queued"))


class FoldersPage(Gtk.ScrolledWindow):
    def __init__(self, app):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.app = app
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        styled(body, "k-page")
        self.add(body)

        # hero
        self.hero = Gtk.Box(spacing=16)
        styled(self.hero, "k-hero")
        self.hero_icon = label("✓", "k-hero-icon", xalign=0.5)
        self.hero_icon.set_valign(Gtk.Align.CENTER)
        self.hero_spin = Gtk.Spinner(width_request=36, height_request=36, no_show_all=True)
        icon_stack = Gtk.Box()
        icon_stack.pack_start(self.hero_icon, False, False, 0)
        icon_stack.pack_start(self.hero_spin, False, False, 8)
        self.hero.pack_start(icon_stack, False, False, 0)
        hv = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER)
        self.hero_title = label("", "k-hero-title", ellipsize=True)
        self.hero_sub = label("", "k-hero-sub", ellipsize=True)
        self.hero_bar = Gtk.ProgressBar(no_show_all=True, margin_top=6)
        hv.pack_start(self.hero_title, False, False, 0)
        hv.pack_start(self.hero_sub, False, False, 0)
        hv.pack_start(self.hero_bar, False, False, 0)
        self.hero.pack_start(hv, True, True, 0)
        self.chip = label("● Signed in", "k-chip-light")
        self.chip.set_valign(Gtk.Align.START)
        self.hero.pack_start(self.chip, False, False, 0)
        body.pack_start(self.hero, False, False, 0)

        head = Gtk.Box(spacing=8, margin_top=6)
        head.pack_start(label("Synced folders", "k-section"), False, False, 0)
        self.count = label("", "k-dim")
        head.pack_start(self.count, False, False, 0)
        head.pack_end(text_button("Add folder", app.add_folder_dialog, "k-accent", "k-pill",
                                  icon="list-add-symbolic"), False, False, 0)
        body.pack_start(head, False, False, 0)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        styled(self.list, "k-cards")
        body.pack_start(self.list, False, False, 0)

        # empty state / drop zone
        self.drop = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        styled(self.drop, "k-drop")
        self.drop.pack_start(label("📁", "k-big-icon", xalign=0.5), False, False, 0)
        self.drop.pack_start(label("Drop a folder here to start syncing", "k-empty-title", xalign=0.5),
                             False, False, 0)
        self.drop.pack_start(label("Or use “Add folder”. You can sync as many folders as you like, each "
                                   "two-way, as a backup, or as a mirror.", "k-dim", xalign=0.5, wrap=True),
                             False, False, 0)
        body.pack_start(self.drop, False, False, 0)
        self.tip = label("Tip: drop any folder from the file manager onto this window to add it.",
                         "k-dim", "k-small", xalign=0.5)
        body.pack_start(self.tip, False, False, 0)
        self.rows: dict[str, FolderRow] = {}

    def rebuild(self):
        for r in self.list.get_children():
            r.destroy()
        self.rows.clear()
        for f in self.app.settings.folders:
            row = FolderRow(self.app, f)
            self.rows[f.id] = row
            self.list.add(row)
        self.list.show_all()
        for r in self.rows.values():
            r.refresh()
        n = len(self.rows)
        self.drop.set_visible(n == 0)
        self.tip.set_visible(n > 0)
        self.count.set_text(f"· {n}" if n else "")
        self.refresh_hero()

    def refresh_folder(self, fid):
        r = self.rows.get(fid)
        if r:
            r.refresh()

    def refresh_hero(self):
        m, s = self.app.manager, self.app.settings
        ctx = self.hero.get_style_context()
        ctx.remove_class("k-error")
        ctx.remove_class("k-paused")
        enabled = [f for f in s.folders if f.enabled]
        errors = [f for f in enabled if m.status.get(f.id) and m.status[f.id].state == "error"]
        conflicts = [f for f in enabled if m.status.get(f.id) and m.status[f.id].state == "conflict"]
        syncing = m.current and m.name_of(m.current)
        self.hero_bar.hide()
        self.hero_spin.hide()
        self.hero_icon.show()
        self.chip.set_text("● Signed in" if m.logged_in else "○ Signed out")
        if m.logged_in is False:
            ctx.add_class("k-error")
            self.hero_icon.set_text("🔑")
            self.hero_title.set_text("Sign in to keep syncing")
            self.hero_sub.set_text("Your Proton Drive session ended. Use the menu → Sign in.")
        elif s.paused:
            ctx.add_class("k-paused")
            self.hero_icon.set_text("⏸")
            self.hero_title.set_text("Syncing is paused")
            self.hero_sub.set_text("Press ▶ in the toolbar or the panel icon to resume.")
        elif syncing:
            st = m.status.get(m.current)
            self.hero_icon.hide()
            self.hero_spin.show()
            self.hero_spin.start()
            self.hero_title.set_text(f"Syncing {syncing}…")
            queued = len([f for f in enabled if m.status.get(f.id) and m.status[f.id].state == "queued"])
            self.hero_sub.set_text((st.text if st else "") + (f"  ·  {queued} more waiting" if queued else ""))
            if st and st.total:
                self.hero_bar.set_fraction(st.done / max(st.total, 1))
                self.hero_bar.show()
        elif errors:
            ctx.add_class("k-error")
            self.hero_icon.set_text("!")
            self.hero_title.set_text(f"{len(errors)} folder(s) need attention")
            self.hero_sub.set_text(m.status[errors[0].id].text)
        elif not s.folders:
            self.hero_icon.set_text("☁")
            self.hero_title.set_text("Ready when you are")
            self.hero_sub.set_text("Add a folder below to start syncing with Proton Drive.")
        else:
            self.hero_icon.set_text("✓")
            self.hero_title.set_text("Everything is up to date" if not conflicts
                                     else f"Up to date · {len(conflicts)} with conflict copies")
            last = max((f.last_sync for f in enabled), default=0)
            nxt = int(m.next_run_in() // 60)
            self.hero_sub.set_text(f"Last sync {ago(last)}  ·  next check in {nxt or '<1'} min  ·  "
                                   f"{len(enabled)} of {len(s.folders)} folders on")


class ActivityPage(Gtk.Box):
    ICONS = {"ok": "emblem-ok-symbolic", "info": "dialog-information-symbolic",
             "warning": "dialog-warning-symbolic", "error": "dialog-error-symbolic"}

    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        styled(self, "k-page")
        self.app = app
        bar = Gtk.Box(spacing=8)
        bar.pack_start(label("Recent activity", "k-section"), False, False, 0)
        self.filter = Gtk.ComboBoxText()
        for k, t in (("all", "Everything"), ("problems", "Problems only")):
            self.filter.append(k, t)
        self.filter.set_active_id("all")
        self.filter.connect("changed", lambda *_: self.rebuild())
        bar.pack_end(text_button("Clear", app.manager.clear_activity, "flat"), False, False, 0)
        bar.pack_end(text_button("Open log folder", lambda: open_path(os.path.dirname(
            str(__import__("kluis.paths", fromlist=["LOG_FILE"]).LOG_FILE))), "flat"), False, False, 0)
        bar.pack_end(self.filter, False, False, 0)
        self.pack_start(bar, False, False, 0)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        styled(self.list, "k-activity")
        ph = label("Nothing yet. Sync activity shows up here.", "k-dim", xalign=0.5)
        ph.set_margin_top(30)
        ph.show()
        self.list.set_placeholder(ph)
        sw = Gtk.ScrolledWindow(vexpand=True)
        styled(sw, "frame")
        sw.add(self.list)
        self.pack_start(sw, True, True, 0)

    def _row(self, a):
        row = Gtk.ListBoxRow()
        box = Gtk.Box(spacing=10)
        box.pack_start(Gtk.Image.new_from_icon_name(self.ICONS.get(a.level, "dialog-information-symbolic"),
                                                    Gtk.IconSize.BUTTON), False, False, 0)
        t = time.localtime(a.ts)
        box.pack_start(label(time.strftime("%Y-%m-%d %H:%M", t), "k-time"), False, False, 0)
        if a.folder:
            box.pack_start(label(a.folder, "k-card-title"), False, False, 0)
        msg = label(a.text, wrap=True, selectable=True)
        box.pack_start(msg, True, True, 0)
        row.add(box)
        return row

    def rebuild(self):
        for r in self.list.get_children():
            r.destroy()
        only = self.filter.get_active_id() == "problems"
        for a in list(self.app.manager.activity)[:300]:
            if only and a.level not in ("error", "warning"):
                continue
            self.list.add(self._row(a))
        self.list.show_all()

    def prepend(self, a):
        if self.filter.get_active_id() == "problems" and a.level not in ("error", "warning"):
            return
        row = self._row(a)
        row.show_all()
        self.list.prepend(row)


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Kluis")
        self.app = app
        self.set_default_size(920, 660)
        self.set_icon_name("dev.kluis.Kluis")

        hb = Gtk.HeaderBar(show_close_button=True)
        self.set_titlebar(hb)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=150)
        self.switcher = Gtk.StackSwitcher(stack=self.stack)
        hb.set_custom_title(self.switcher)
        logo = Gtk.Box(spacing=8)
        logo.pack_start(Gtk.Image.new_from_icon_name("dev.kluis.Kluis", Gtk.IconSize.LARGE_TOOLBAR), False, False, 0)
        logo.pack_start(label("<b>Kluis</b>", markup=True), False, False, 0)
        hb.pack_start(logo)

        menu = Gtk.MenuButton(image=Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON),
                              tooltip_text="Menu")
        self.menu_btn = menu
        hb.pack_end(menu)
        self.pause_btn = Gtk.ToggleButton(tooltip_text="Pause syncing")
        self.pause_btn.connect("toggled", self._pause_toggled)
        hb.pack_end(self.pause_btn)
        self.sync_btn = icon_button("view-refresh-symbolic", "Sync everything now", self._sync_or_stop, flat=False)
        hb.pack_end(self.sync_btn)

        self.overlay = Gtk.Overlay()
        self.add(self.overlay)
        self.root = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.overlay.add(self.root)

        self.onboarding = Onboarding(app, self._onboarding_done)
        self.folders = FoldersPage(app)
        self.browser = BrowserPage(app)
        self.photos = PhotosPage(app)
        self.activity = ActivityPage(app)
        self.root.add_named(self.onboarding, "welcome")
        self.root.add_named(self.stack, "main")
        self.stack.add_titled(self.folders, "folders", "Folders")
        self.stack.add_titled(self.browser, "browse", "Browse")
        self.stack.add_titled(self.photos, "photos", "Photos")
        self.stack.add_titled(self.activity, "activity", "Activity")
        self.stack.connect("notify::visible-child-name", self._page_changed)

        # toast
        self.toast_rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP,
                                      valign=Gtk.Align.END, halign=Gtk.Align.CENTER, margin_bottom=18)
        tb = Gtk.Box(spacing=12)
        styled(tb, "app-notification")
        self.toast_lbl = label("")
        self.toast_action = Gtk.Button(no_show_all=True)
        styled(self.toast_action, "flat")
        tb.pack_start(self.toast_lbl, False, False, 0)
        tb.pack_start(self.toast_action, False, False, 0)
        tb.pack_start(icon_button("window-close-symbolic", "Close", lambda: self.toast_rev.set_reveal_child(False)),
                      False, False, 0)
        self.toast_rev.add(tb)
        self.overlay.add_overlay(self.toast_rev)
        self._toast_src = 0
        self._toast_handler = None

        # drag a folder anywhere on the window to add it
        self.drag_dest_set(Gtk.DestDefaults.ALL, [Gtk.TargetEntry.new("text/uri-list", 0, 0)], Gdk.DragAction.COPY)
        self.connect("drag-data-received", self._on_drop)
        self.connect("drag-motion", lambda *_: self._drag_hl(True))
        self.connect("drag-leave", lambda *_: self._drag_hl(False))

        self._build_menu()
        self.refresh_toolbar()
        self.show_all()

    # ---------- pages ----------
    def show_onboarding(self, state):
        self.onboarding.refresh(state)
        self.switcher.set_visible(False)
        self.sync_btn.set_visible(False)
        self.pause_btn.set_visible(False)
        self.root.set_visible_child_name("welcome")

    def show_main(self, page="folders"):
        self.switcher.set_visible(True)
        self.sync_btn.set_visible(True)
        self.pause_btn.set_visible(True)
        self.folders.rebuild()
        self.activity.rebuild()
        self.root.set_visible_child_name("main")
        self.stack.set_visible_child_name(page)

    def show_remote(self, path):
        self.browser.path = path
        self.root.set_visible_child_name("main")
        self.stack.set_visible_child_name("browse")
        self.browser.load()

    def _onboarding_done(self):
        self.show_main()
        self.app.manager.request(reason="start")

    def _page_changed(self, *_):
        if self.stack.get_visible_child_name() == "browse":
            self.browser.on_shown()

    # ---------- toolbar ----------
    def _build_menu(self):
        self.menu_btn.set_popover(popover_menu(self.menu_btn, [
            ("Settings", self.app.open_settings),
            ("Sign in…", self.app.sign_in_again),
            ("Open Proton Drive on the web", lambda: open_uri(WEB_URL)),
            None,
            ("About Kluis", self.app.about),
            ("Quit", self.app.quit_app),
        ]))

    def _sync_or_stop(self):
        if self.app.manager.busy:
            self.app.manager.cancel()
        else:
            self.app.manager.request()

    def _pause_toggled(self, btn):
        if btn.get_active() != self.app.settings.paused:
            self.app.manager.set_paused(btn.get_active())

    def refresh_toolbar(self):
        m = self.app.manager
        busy = m.busy
        img = "process-stop-symbolic" if busy else "view-refresh-symbolic"
        self.sync_btn.set_image(Gtk.Image.new_from_icon_name(img, Gtk.IconSize.BUTTON))
        self.sync_btn.set_tooltip_text("Stop syncing" if busy else "Sync everything now (Ctrl+R)")
        paused = self.app.settings.paused
        self.pause_btn.handler_block_by_func(self._pause_toggled)
        self.pause_btn.set_active(paused)
        self.pause_btn.handler_unblock_by_func(self._pause_toggled)
        self.pause_btn.set_image(Gtk.Image.new_from_icon_name(
            "media-playback-start-symbolic" if paused else "media-playback-pause-symbolic", Gtk.IconSize.BUTTON))
        self.pause_btn.set_tooltip_text("Resume syncing" if paused else "Pause syncing")

    # ---------- toast ----------
    def toast(self, text, action=None):
        self.toast_lbl.set_text(text)
        if self._toast_handler:
            self.toast_action.disconnect(self._toast_handler)
            self._toast_handler = None
        if action:
            self.toast_action.set_label(action[0])
            self._toast_handler = self.toast_action.connect(
                "clicked", lambda *_: (action[1](), self.toast_rev.set_reveal_child(False)))
            self.toast_action.show()
        else:
            self.toast_action.hide()
        self.toast_rev.set_reveal_child(True)
        if self._toast_src:
            GLib.source_remove(self._toast_src)
        self._toast_src = GLib.timeout_add_seconds(5, self._hide_toast)

    def _hide_toast(self):
        self._toast_src = 0
        self.toast_rev.set_reveal_child(False)
        return False

    # ---------- drag & drop ----------
    def _drag_hl(self, on):
        ctx = self.folders.drop.get_style_context()
        (ctx.add_class if on else ctx.remove_class)("k-drag-over")
        return False

    def _on_drop(self, _w, _ctx, _x, _y, data, _info, _time):
        self._drag_hl(False)
        if self.root.get_visible_child_name() != "main" or self.stack.get_visible_child_name() == "browse":
            return  # the browser page handles its own drops (upload)
        for uri in data.get_uris():
            if uri.startswith("file://"):
                path = unquote(urlparse(uri).path)
                if os.path.isdir(path):
                    self.app.add_folder_dialog(path)
                    break

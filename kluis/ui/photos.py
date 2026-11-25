"""Photos tab: keep a local copy of Proton Photos, add photos from a folder, and browse the timeline."""
from __future__ import annotations

import os
from collections import defaultdict

from gi.repository import GLib, Gtk

from ..config import PHOTOS_ID
from ..photos import captured_dt
from ..thumbs import TILE, Thumbnailer
from .common import (ago, icon_button, label, open_path, open_uri, run_bg, short_path, styled, text_button,
                     user_dir)
from .dialogs import choose_local_folder, error_dialog

PAGE = 240
WEB_PHOTOS = "https://drive.proton.me/photos"


class SyncCard(Gtk.Box):
    def __init__(self, glyph, badge_cls, title, sub):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        styled(self, "k-card")
        head = Gtk.Box(spacing=12)
        b = label(glyph, "k-badge", badge_cls, xalign=0.5)
        b.set_valign(Gtk.Align.START)
        head.pack_start(b, False, False, 0)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        v.pack_start(label(title, "k-card-title"), False, False, 0)
        s = label(sub, "k-dim", "k-small", wrap=True)
        s.set_max_width_chars(40)
        v.pack_start(s, False, False, 0)
        head.pack_start(v, True, True, 0)
        self.switch = Gtk.Switch(valign=Gtk.Align.START)
        head.pack_start(self.switch, False, False, 0)
        self.pack_start(head, False, False, 0)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.pack_start(self.body, False, False, 0)

    def folder_button(self, on_click):
        btn = Gtk.Button()
        box = Gtk.Box(spacing=8)
        box.pack_start(Gtk.Image.new_from_icon_name("folder-pictures-symbolic", Gtk.IconSize.BUTTON), False, False, 0)
        lb = label("Choose a folder…", ellipsize=True)
        box.pack_start(lb, True, True, 0)
        btn.add(box)
        btn.connect("clicked", lambda *_: on_click())
        btn.lbl = lb
        return btn


class PhotosPage(Gtk.ScrolledWindow):
    def __init__(self, app):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.app = app
        self.thumbs = Thumbnailer(app.cli, self._preview_ready)
        self.thumbs.remote_enabled = app.settings.photos.remote_previews
        self.tile_widgets = defaultdict(list)   # uid -> [(image, name_label)]
        self.items = []          # PhotoItem list currently shown (newest first)
        self.shown = 0
        self.album = ""          # "" = timeline, else album uid
        self.loaded = False
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        styled(body, "k-page")
        self.add(body)

        head = Gtk.Box(spacing=8)
        head.pack_start(label("Proton Photos", "k-section"), False, False, 0)
        self.count = label("", "k-dim")
        head.pack_start(self.count, False, False, 0)
        head.pack_end(text_button("Open on the web", lambda: open_uri(WEB_PHOTOS), "flat",
                                  icon="web-browser-symbolic"), False, False, 0)
        body.pack_start(head, False, False, 0)
        body.pack_start(label("Photos and videos your phone backs up to Proton Drive. Keep a copy here, "
                              "add photos from this computer, or just look through them.", "k-dim", wrap=True),
                        False, False, 0)

        cards = Gtk.Box(spacing=12, homogeneous=True)
        body.pack_start(cards, False, False, 0)

        # --- save a copy here ---
        ps = app.settings.photos
        self.down = SyncCard("↓", "mirror", "Save my photos on this computer",
                             "New photos from your phone appear here automatically, sorted into folders.")
        self.down_btn = self.down.folder_button(self._pick_download)
        self.layout = Gtk.ComboBoxText()
        for k, t in (("month", "Folders by month  (2026 / 2026-11)"), ("year", "Folders by year  (2026)"),
                     ("flat", "All in one folder")):
            self.layout.append(k, t)
        self.layout.set_active_id(ps.layout)
        self.albums_chk = Gtk.CheckButton(label="Also save albums as folders (Albums/…)", active=ps.albums)
        self.trash_chk = Gtk.CheckButton(label="If a photo is deleted in Proton, move my copy to the Trash",
                                         active=ps.remove_deleted)
        for w in (self.down_btn, self.layout, self.albums_chk, self.trash_chk):
            self.down.body.pack_start(w, False, False, 0)
        self.down_status = self._status_row(self.down.body, lambda: open_path(ps.download_dir))
        cards.pack_start(self.down, True, True, 0)

        # --- add from this computer ---
        self.up = SyncCard("↑", "backup", "Add photos from this computer",
                           "New photos and videos in a folder (e.g. a camera import folder) are added to Proton "
                           "Photos. Ones already there are skipped.")
        self.up_btn = self.up.folder_button(self._pick_upload)
        self.up.body.pack_start(self.up_btn, False, False, 0)
        self.up.body.pack_start(label("Your saved copies above are never uploaded again.", "k-dim", "k-small",
                                      wrap=True), False, False, 0)
        self.up_status = self._status_row(self.up.body, lambda: open_path(ps.upload_dir))
        cards.pack_start(self.up, True, True, 0)

        self.down.switch.set_active(ps.download)
        self.up.switch.set_active(ps.upload)
        self.down.switch.connect("notify::active", lambda *_: self._toggle("download"))
        self.up.switch.connect("notify::active", lambda *_: self._toggle("upload"))
        self.layout.connect("changed", lambda *_: self._changed(reset=False))
        self.albums_chk.connect("toggled", lambda *_: self._changed(reset=False))
        self.trash_chk.connect("toggled", lambda *_: self._changed(reset=False))

        # --- gallery ---
        gh = Gtk.Box(spacing=8, margin_top=8)
        gh.pack_start(label("Your photos", "k-section"), False, False, 0)
        self.album_combo = Gtk.ComboBoxText()
        self.album_combo.append("", "All photos")
        self.album_combo.set_active_id("")
        self.album_combo.connect("changed", lambda *_: self._album_changed())
        gh.pack_start(self.album_combo, False, False, 0)
        gh.pack_end(icon_button("view-refresh-symbolic", "Reload from Proton Photos", self.load), False, False, 0)
        self.prev_sw = Gtk.Switch(active=app.settings.photos.remote_previews, valign=Gtk.Align.CENTER,
                                  tooltip_text="Photos not saved on this computer are fetched once in the "
                                               "background; only a small preview (~20 KB) is kept. "
                                               "Videos over 60 MB are skipped.")
        self.prev_sw.connect("notify::active", lambda *_: self._toggle_previews())
        gh.pack_end(self.prev_sw, False, False, 0)
        gh.pack_end(label("Previews for all photos", "k-dim", "k-small"), False, False, 0)
        self.dl_sel = text_button("Download selected", self._download_selected, "k-pill",
                                  icon="folder-download-symbolic")
        gh.pack_end(self.dl_sel, False, False, 0)
        body.pack_start(gh, False, False, 0)

        self.gstack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        intro = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin=30)
        styled(intro, "k-drop")
        intro.pack_start(label("🖼", "k-big-icon", xalign=0.5), False, False, 0)
        intro.pack_start(label("See your photo timeline", "k-empty-title", xalign=0.5), False, False, 0)
        intro.pack_start(label("Previews show for photos saved on this computer; others show their name. "
                               "Double-click any photo to open it.", "k-dim", xalign=0.5, wrap=True),
                         False, False, 0)
        show = text_button("Show my photos", self.load, "k-accent", "k-pill")
        show.set_halign(Gtk.Align.CENTER)
        intro.pack_start(show, False, False, 0)
        self.gstack.add_named(intro, "intro")
        sp = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=40)
        sp.pack_start(Gtk.Spinner(active=True, width_request=32, height_request=32), False, False, 0)
        self.wait = label("Reading your timeline…", "k-dim", xalign=0.5)
        sp.pack_start(self.wait, False, False, 0)
        self.gstack.add_named(sp, "loading")
        self.grid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.gstack.add_named(self.grid, "grid")
        self.gmsg = label("", "k-dim", xalign=0.5, wrap=True)
        self.gmsg.set_margin_top(30)
        self.gstack.add_named(self.gmsg, "msg")
        body.pack_start(self.gstack, False, False, 0)
        self.more = text_button("Show more", self._render_more, "k-pill")
        self.more.set_halign(Gtk.Align.CENTER)
        self.more.set_no_show_all(True)
        body.pack_start(self.more, False, False, 0)
        self.flows: list[Gtk.FlowBox] = []
        self._update_labels()
        self.refresh_status()

    # ---------- settings cards ----------
    def _status_row(self, box, open_cb):
        row = Gtk.Box(spacing=8)
        dot = Gtk.Box(valign=Gtk.Align.CENTER)
        styled(dot, "k-dot")
        lb = label("", "k-small", ellipsize=True)
        row.pack_start(dot, False, False, 0)
        row.pack_start(lb, True, True, 0)
        row.pack_end(icon_button("folder-open-symbolic", "Open folder", open_cb), False, False, 0)
        row.pack_end(icon_button("view-refresh-symbolic", "Sync photos now",
                                 lambda: self.app.manager.request(PHOTOS_ID)), False, False, 0)
        bar = Gtk.ProgressBar(no_show_all=True)
        box.pack_start(row, False, False, 0)
        box.pack_start(bar, False, False, 0)
        row.dot, row.lbl, row.bar = dot, lb, bar
        return row

    def _update_labels(self):
        ps = self.app.settings.photos
        self.down_btn.lbl.set_text(short_path(ps.download_dir) if ps.download_dir else "Choose a folder…")
        self.up_btn.lbl.set_text(short_path(ps.upload_dir) if ps.upload_dir else "Choose a folder…")
        for w in (self.down_btn, self.layout, self.albums_chk, self.trash_chk):
            w.set_sensitive(ps.download)
        self.up_btn.set_sensitive(ps.upload)
        self.count.set_text(f"· {ps.count:,} photos" if ps.count else "")

    def _default_download_dir(self):
        pics = user_dir(GLib.UserDirectory.DIRECTORY_PICTURES) or os.path.expanduser("~/Pictures")
        return os.path.join(pics, "Proton Photos")

    def _toggle(self, which):
        ps = self.app.settings.photos
        if which == "download":
            ps.download = self.down.switch.get_active()
            if ps.download and not ps.download_dir:
                ps.download_dir = self._default_download_dir()   # one click: sensible default
                os.makedirs(ps.download_dir, exist_ok=True)
        else:
            ps.upload = self.up.switch.get_active()
            if ps.upload and not ps.upload_dir:
                p = choose_local_folder(self.get_toplevel(), "Add photos from which folder?",
                                        user_dir(GLib.UserDirectory.DIRECTORY_PICTURES))
                if not p:
                    ps.upload = False
                    self.up.switch.set_active(False)
                    return
                ps.upload_dir = p
        self._changed(reset=False)

    def _pick_download(self):
        ps = self.app.settings.photos
        p = choose_local_folder(self.get_toplevel(), "Save photos to…", ps.download_dir or self._default_download_dir())
        if p and p != ps.download_dir:
            ps.download_dir = p
            self._changed(reset=True)

    def _pick_upload(self):
        ps = self.app.settings.photos
        p = choose_local_folder(self.get_toplevel(), "Add photos from…", ps.upload_dir)
        if p:
            ps.upload_dir = p
            self._changed(reset=False)

    def _changed(self, reset):
        ps = self.app.settings.photos
        old = (ps.layout, ps.albums)
        ps.layout = self.layout.get_active_id()
        ps.albums = self.albums_chk.get_active()
        ps.remove_deleted = self.trash_chk.get_active()
        if old[0] != ps.layout:
            reset = True   # new folder structure: start that copy over
        self.app.settings.save()
        self._update_labels()
        self.app.manager.photos_changed(reset=reset)

    def refresh_status(self, reload=False):
        m, ps = self.app.manager, self.app.settings.photos
        st = m.status.get(PHOTOS_ID)
        for row, on in ((self.down_status, ps.download), (self.up_status, ps.upload)):
            ctx = row.dot.get_style_context()
            for c in ("ok", "sync", "err"):
                ctx.remove_class(c)
            if not on:
                row.lbl.set_text("Off")
                row.bar.hide()
                continue
            state = st.state if st else "idle"
            ctx.add_class({"ok": "ok", "syncing": "sync", "queued": "sync", "error": "err"}.get(state, ""))
            if state == "syncing":
                row.lbl.set_text(st.text)
                if st.total:
                    row.bar.set_fraction(st.done / max(st.total, 1))
                    row.bar.show()
            else:
                row.bar.hide()
                text = st.text if st else ""
                row.lbl.set_text(f"{text} · {ago(ps.last_sync)}" if ps.last_sync and state != "queued" else text)
            row.lbl.set_tooltip_text(row.lbl.get_text())
        self._update_labels()
        if reload and self.loaded and not self.album and m.photos.timeline:
            self.items = m.photos.timeline
            self._render(reset=True)

    # ---------- gallery ----------
    def _local_paths(self):
        ps = self.app.settings.photos
        if not ps.download_dir:
            return {}
        return {k: os.path.join(ps.download_dir, rel) for k, rel in self.app.manager.store.photos_downloaded().items()}

    def load(self):
        self.loaded = True
        self.wait.set_text("Waiting for the current sync to finish…" if self.app.manager.busy
                           else "Reading your timeline…")
        self.gstack.set_visible_child_name("loading")
        album = self.album

        def work():
            items = self.app.cli.album_photos(album) if album else self.app.cli.photo_timeline()
            albums = self.app.cli.albums() if not album else None
            return items, albums

        def done(r):
            items, albums = r
            if album == "" and albums is not None:
                cur = self.album_combo.get_active_id()
                self.album_combo.remove_all()
                self.album_combo.append("", "All photos")
                for a in albums:
                    if a.type == "album":
                        self.album_combo.append(a.uid, f"{a.name}  ({a.count})")
                self.album_combo.set_active_id(cur or "")
                self.app.settings.photos.count = len(items)
                self._update_labels()
            self.items = items
            self._render(reset=True)

        def fail(e):
            self.gmsg.set_text(f"Could not read your photos.\n{e}")
            self.gstack.set_visible_child_name("msg")
        run_bg(work, done, fail)

    def _album_changed(self):
        aid = self.album_combo.get_active_id() or ""
        if aid != self.album and self.loaded:
            self.album = aid
            self.load()

    def _render(self, reset=False):
        if reset:
            self.thumbs.reset()
            self.tile_widgets.clear()
            for c in self.grid.get_children():
                c.destroy()
            self.flows.clear()
            self.shown = 0
            self._last_month = None
        if not self.items:
            self.gmsg.set_text("No photos here yet.")
            self.gstack.set_visible_child_name("msg")
            self.more.hide()
            return
        local = self._local_paths()
        flow = self.flows[-1] if self.flows else None
        for p in self.items[self.shown:self.shown + PAGE]:
            dt = captured_dt(p)
            month = dt.strftime("%B %Y") if dt else "Unknown date"
            if month != self._last_month:
                self._last_month = month
                self.grid.pack_start(label(month, "k-card-title", xalign=0), False, False, 8)
                flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.MULTIPLE, homogeneous=True,
                                   min_children_per_line=3, max_children_per_line=12, column_spacing=6,
                                   row_spacing=6, activate_on_single_click=False)
                flow.connect("child-activated", self._open_tile)
                flow.connect("selected-children-changed", lambda *_: self._sel_changed())
                self.flows.append(flow)
                self.grid.pack_start(flow, False, False, 0)
            flow.add(self._tile(p, local.get(p.uid)))
        self.shown = min(len(self.items), self.shown + PAGE)
        self.grid.show_all()
        self.gstack.set_visible_child_name("grid")
        self.more.set_visible(self.shown < len(self.items))
        self._sel_changed()

    def _render_more(self):
        self._render(reset=False)

    def _tile(self, p, local_path):
        child = Gtk.FlowBoxChild()
        child.photo, child.local = p, local_path
        ov = Gtk.Overlay()
        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, width_request=TILE, height_request=TILE)
        styled(frame, "k-tile")
        img = Gtk.Image.new_from_icon_name("video-x-generic" if p.is_video else "image-x-generic",
                                           Gtk.IconSize.DIALOG)
        img.set_vexpand(True)
        frame.pack_start(img, True, True, 0)
        name = label(p.name, "k-small", "k-dim", xalign=0.5, ellipsize=True)
        name.set_max_width_chars(14)
        frame.pack_start(name, False, False, 4)
        saved = bool(local_path and os.path.exists(local_path))
        child.set_tooltip_text(f"{p.name}\n" + (short_path(local_path) if saved else "In Proton Photos"))
        ov.add(frame)
        if p.is_video:
            badge = label("▶", "k-tile-badge")
            badge.set_halign(Gtk.Align.END)
            badge.set_valign(Gtk.Align.END)
            ov.add_overlay(badge)
        child.add(ov)
        self.tile_widgets[p.uid].append((img, name))
        self.thumbs.request(p, local_path if saved else None)
        return child

    def _preview_ready(self, uid, pixbuf):
        for img, name in self.tile_widgets.get(uid, []):
            img.set_from_pixbuf(pixbuf)
            name.hide()

    def _toggle_previews(self):
        ps = self.app.settings.photos
        ps.remote_previews = self.prev_sw.get_active()
        self.app.settings.save()
        self.thumbs.remote_enabled = ps.remote_previews
        if ps.remote_previews and self.items:
            self._render(reset=True)

    def _selected(self):
        return [c.photo for f in self.flows for c in f.get_selected_children()]

    def _sel_changed(self):
        n = len(self._selected())
        self.dl_sel.set_sensitive(n > 0)
        self.dl_sel.set_tooltip_text(f"Download {n} photo(s)" if n else "Select photos (Ctrl+click) to download")

    def _open_tile(self, _flow, child):
        if child.local and os.path.exists(child.local):
            open_path(child.local)
            return
        cache = os.path.join(GLib.get_user_cache_dir(), "kluis", "photos", child.photo.uid.replace("~", "_"))
        os.makedirs(cache, exist_ok=True)
        self.app.toast(f"Opening {child.photo.name}…")

        def done(_s):
            files = os.listdir(cache)
            if files:
                open_path(os.path.join(cache, files[0]))
        run_bg(lambda: self.app.cli.photo_download([child.photo.uid], cache, "remove"), done,
               lambda e: error_dialog(self.get_toplevel(), "Could not open the photo", str(e)))

    def _download_selected(self):
        photos = self._selected()
        if not photos:
            return
        dest = choose_local_folder(self.get_toplevel(), "Download photos to…", os.path.expanduser("~/Downloads"))
        if not dest:
            return
        self.app.toast(f"Downloading {len(photos)} photo(s)…")

        def done(s):
            self.app.manager.log("ok", PHOTOS_ID, f"Downloaded {s.transferred} photo(s) to {dest}")
            self.app.toast(f"Downloaded {s.transferred} photo(s)", ("Open folder", lambda: open_path(dest)))
        run_bg(lambda: self.app.cli.photo_download([p.uid for p in photos], dest, "rename"), done,
               lambda e: error_dialog(self.get_toplevel(), "Download failed", str(e)))

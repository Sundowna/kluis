"""Sync Center (was Folders, HANDOVER §3.2): everything in Proton Drive, one line per folder.

Columns: In Proton Drive (tick, files · size) · Folder on this computer · How it syncs · Status · Warnings.
Ticking or unticking only stages a change; the bar at the bottom applies or discards them (Walter, 2026-11-27:
"Sync Center shows everything in the drive"; mockup: the Kluis – Choose what to sync canvas, Sync Center artboard).
Below 1240 px each line wraps, so the page still fits a half-screen window (F-020).
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from gi.repository import GLib, Gtk

from ..cli import rjoin
from ..config import MODES, FolderPair, validate_local
from ..i18n import _, ngettext
from .browser import ROOT_NAMES, shared_stats
from .common import (WEB_URL, a11y, ago, button, clear, hbox, human_size, label, open_path, open_uri, popover_menu,
                     run_bg, set_class, short_path, styled, vbox)

SECTIONS = ("/my-files", "/devices", "/shared-with-me")
WIDE = 1240                     # below this page width a line wraps: name · status on top, the rest below
UNSET = object()


def num(n: int) -> str:
    return f"{n:,}".replace(",", "'")          # de-CH style thousands, like the rest of Walter's tools


def files_size(st) -> str:
    if not st:
        return _("Counting…")
    return ngettext("{n} file", "{n} files", st[0]).format(n=num(st[0])) + " · " + human_size(st[1])


def section_of(remote: str) -> str:
    return next((s for s in SECTIONS if remote == s or remote.startswith(s + "/")), "")


def parent_of(remote: str) -> str:
    return remote.rsplit("/", 1)[0] or "/"


def status_text(app, f: FolderPair) -> tuple[str, str, float | None]:
    """(text, css class, progress 0..1 or None) for a synced folder; the same words the Folders cards used."""
    st = app.manager.status.get(f.id)
    state = st.state if st else "idle"
    cls, frac = "", None
    if not f.enabled:
        text = _("Off · not syncing")
    elif state == "syncing":
        text = st.text or _("Syncing…")
        if st.total:
            frac = st.done / max(st.total, 1)
    elif state == "queued":
        text = _("Waiting for its turn…")
    elif state in ("guard", "missing", "hold"):
        text = st.text
        cls = "k-error" if state != "guard" else "k-warn"
    elif state in ("ok", "conflict", "error"):
        text = result_text(f, st)
        cls = {"conflict": "k-warn", "error": "k-error"}.get(state, "k-ok")
    elif not f.last_sync:
        text = _("First sync started…") if app.manager.busy else (st.text if st else "")
    else:
        text = st.text if st else ""
    if not f.watch and f.enabled and state not in ("syncing", "queued", "error", "missing", "guard"):
        text += " · " + _("changes wait for the next check")
    return text, cls, frac


def result_text(f, st):
    if st.state == "conflict":
        return _("{msg} · {t}").format(msg=st.text, t=ago(f.last_sync))
    if st.state == "error":
        return st.text
    when = ago(f.last_sync)
    if f.mode == "backup":
        return _("Backed up {t} · {n} files").format(t=when, n=f.last_files)
    if when == "just now":
        return _("Synced just now")
    return _("Synced {t} · {n} files").format(t=when, n=f.last_files)


@dataclass
class Node:
    """One folder in Proton Drive as Sync Center shows it."""
    remote: str                 # /my-files/0Proton/Brain, /devices/XPS/Desktop, /shared-with-me/<uid>
    name: str
    role: str = ""              # shares: viewer | editor | admin
    leaf: bool = False          # shares aren't opened further here


@dataclass
class Staged:
    """A folder ticked but not applied yet."""
    node: Node
    local: str
    mode: str
    use_copy: str = ""          # move this local folder into place first (an earlier download)


class ModeSeg(Gtk.Box):
    """⇄ Two-way · ↑ Back up · ↓ Mirror down as linked toggle buttons; one look for "selected" (W7)."""

    def __init__(self, name, active, on_pick, viewer=False):
        super().__init__()
        styled(self, "linked")
        self.on_pick = on_pick
        self.buttons = {}
        self._quiet = False
        self._current = None
        for key, (glyph, title, desc) in MODES.items():
            b = Gtk.ToggleButton(label=f"{glyph} {title}")
            b.set_tooltip_text(desc)
            styled(b, "k-small")
            if viewer and key != "mirror":
                b.set_sensitive(False)
                b.set_tooltip_text(_("Shared with you to view only, so it stays ↓ Mirror down"))
            b.connect("toggled", self._toggled, key)
            a11y(b, f"{glyph} {title}", desc)
            self.pack_start(b, False, False, 0)
            self.buttons[key] = b
        a11y(self, name)
        self.set_active_id(active)

    def get_active_id(self):
        return self._current

    def set_active_id(self, key):
        """Like a combo box: picking another mode (also from code) reports it once."""
        old = self._current
        self._current = key
        self._quiet = True
        for k, b in self.buttons.items():
            b.set_active(k == key)
        self._quiet = False
        if old is not None and key != old and self.on_pick:
            self.on_pick(key)

    def _toggled(self, b, key):
        if self._quiet:
            return
        if not b.get_active():
            if key == self._current:            # clicking the selected one keeps it selected
                self._quiet = True
                b.set_active(True)
                self._quiet = False
            return
        self.set_active_id(key)


class StatusCard(Gtk.Box):
    def __init__(self, app, with_add=True):
        super().__init__(spacing=16)
        styled(self, "k-card")
        self.icon = label("✓", "k-iconbox", xalign=0.5)
        self.icon.set_valign(Gtk.Align.CENTER)
        self.pack_start(self.icon, False, False, 0)
        self.title = label("", "k-h1", ellipsize="end")
        self.sub = label("", "k-muted", ellipsize="end")
        a11y(self.title, _("Sync Center status"))
        self.pack_start(vbox(self.title, self.sub, spacing=4, valign=Gtk.Align.CENTER), True, True, 0)
        if with_add:
            add = button(_("+ Add from this computer…"), app.add_folder_dialog,
                         tooltip=_("Sync a folder that starts on this computer (Ctrl+N)"))
            add.set_valign(Gtk.Align.CENTER)
            self.pack_end(add, False, False, 0)

    def refresh(self, st):
        icons = {"paused": "⏸", "syncing": "↻", "problems": "!", "empty": "☁", "ok": "✓"}
        self.icon.set_text(icons.get(st.kind, "✓"))
        for c in ("k-ok", "k-warn", "k-error"):
            self.icon.get_style_context().remove_class(c)
            self.sub.get_style_context().remove_class(c)
        self.icon.get_style_context().add_class({"warn": "k-warn", "error": "k-error"}.get(st.tone, "k-ok"))
        if st.tone in ("warn", "error"):
            self.sub.get_style_context().add_class("k-warn" if st.tone == "warn" else "k-error")
        self.title.set_text(st.title)
        self.sub.set_text(st.subtitle)
        self.sub.set_tooltip_text(st.subtitle)


class Row(Gtk.Box):
    """One line of the table. Its cells move between one line (wide) and two lines (narrow)."""

    def __init__(self, page, depth=0):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        styled(self, "k-sc-row")
        self.page = page
        self.top = Gtk.Box(spacing=12)
        self.bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=34 + 22 * depth)
        self.pack_start(self.top, False, False, 0)
        self.pack_start(self.bottom, False, False, 0)
        self.c_name = Gtk.Box(spacing=6, margin_start=22 * depth)
        self.c_path = Gtk.Box(spacing=8)
        self.c_mode = Gtk.Box(spacing=8)
        self.c_status = vbox(spacing=4, valign=Gtk.Align.CENTER)
        self.c_warn = Gtk.Box(spacing=8)
        self.c_more = Gtk.Box(spacing=4)
        page.groups["path"].add_widget(self.c_path)
        page.groups["mode"].add_widget(self.c_mode)
        page.groups["status"].add_widget(self.c_status)
        page.groups["warn"].add_widget(self.c_warn)
        page.groups["more"].add_widget(self.c_more)
        self.wide = None            # the page calls layout() once the cells are filled

    def layout(self, wide):
        if wide == self.wide:
            return
        self.wide = wide
        for c in (self.c_name, self.c_path, self.c_mode, self.c_status, self.c_warn, self.c_more):
            p = c.get_parent()
            if p:
                p.remove(c)
        if wide:
            self.top.pack_start(self.c_name, True, True, 0)
            for c in (self.c_path, self.c_mode, self.c_status, self.c_warn, self.c_more):
                self.top.pack_start(c, False, False, 0)
            self.bottom.hide()
            self.bottom.set_no_show_all(True)
        else:
            self.top.pack_start(self.c_name, True, True, 0)
            self.top.pack_start(self.c_status, False, False, 0)
            self.top.pack_start(self.c_more, False, False, 0)
            for c in (self.c_path, self.c_mode, self.c_warn):
                if c.get_children():
                    self.bottom.pack_start(c, False, False, 0)
            self.bottom.set_no_show_all(False)
            self.bottom.show_all()


class FoldersPage(Gtk.Box):
    """The Sync Center tab (key "folders", Ctrl+2). Kept under its old name so app.py and the tests need no change."""

    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.app = app
        self.wide = False           # two lines until the page is known to be wide: a first wide frame would
        #                             stretch the window past a small screen
        self.groups = {k: Gtk.SizeGroup(mode=Gtk.SizeGroupMode.HORIZONTAL)
                       for k in ("path", "mode", "status", "warn", "more")}
        self.kids: dict[str, list[Node]] = {}        # folder -> its subfolders (loaded when opened)
        self.loading: set[str] = set()
        self.errors: dict[str, str] = {}
        self.open: set[str] = {"/my-files"}
        self.staged: dict[str, Staged] = {}          # remote -> folder to start syncing
        self.unstaged: set[str] = set()              # folder ids to stop syncing
        self.stats = shared_stats(app)               # counts kept on disk, shared with Browse
        self.stats.listeners.append(lambda _p: self.render())
        self.shown_once = False
        self._render_src = 0
        self._menus_open = 0                         # a rebuild waits while a line's ⋯ menu is open
        self._render_waiting = False
        self.rows: dict[str, Row] = {}               # remote -> its row, for the tests and jump_to

        self.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.pack_start(self.scroller, True, True, 0)
        body = vbox(spacing=12)
        self.scroller.add(body)
        self.status = StatusCard(app)
        body.pack_start(self.status, False, False, 0)

        bar = Gtk.Box(spacing=10)
        bar.pack_start(label(_("Show"), "k-muted"), False, False, 0)
        self.view_btns = {}
        seg = Gtk.Box()
        styled(seg, "linked")
        for key, text in (("all", _("Everything in Drive")), ("synced", _("Synced only"))):
            b = Gtk.ToggleButton(label=text)
            b.connect("toggled", self._view_toggled, key)
            a11y(b, _("Show: {v}").format(v=text))
            seg.pack_start(b, False, False, 0)
            self.view_btns[key] = b
        a11y(seg, _("Show"))
        bar.pack_start(seg, False, False, 0)
        self.reload_btn = button("↻", self.reload, tooltip=_("Read Proton Drive again"), name=_("Reload Sync Center"))
        bar.pack_end(self.reload_btn, False, False, 0)
        body.pack_start(bar, False, False, 0)

        self.table = vbox(spacing=0)
        styled(self.table, "k-card", "k-sc-table")
        a11y(self.table, _("Folders"))
        body.pack_start(self.table, False, False, 0)

        # changes not applied yet
        self.pending = Gtk.Box(spacing=12)
        styled(self.pending, "k-card", "k-sc-pending")
        self.pending_lbl = label("", wrap=True)
        self.pending_lbl.set_hexpand(True)
        self.pending.pack_start(self.pending_lbl, True, True, 0)
        self.discard_btn = button(_("Discard changes"), self.discard, "k-big")
        self.apply_btn = button(_("Apply changes"), self.apply, "suggested-action", "k-big")
        self.pending.pack_end(self.apply_btn, False, False, 0)
        self.pending.pack_end(self.discard_btn, False, False, 0)
        self.pending.set_no_show_all(True)
        self.pack_end(self.pending, False, False, 0)          # stays in view however long the list is

        self.drop = vbox(label(_("Drag a folder onto this window to start syncing it"), "k-muted", xalign=0.5))
        styled(self.drop, "k-card", "k-drop")
        a11y(self.drop, _("Drop zone"))
        body.pack_start(self.drop, False, False, 0)
        legend = vbox(*[label(t, "k-muted", "k-s12") for t in (
            _("⇄ Two-way: edits, new files and deletions travel both ways"),
            _("↑ Back up: uploads only, never deletes in Proton Drive"),
            _("↓ Mirror down: local copy, never changes Proton Drive"))], spacing=2)
        body.pack_start(legend, False, False, 0)
        self.connect("size-allocate", self._allocated)
        self.view_btns[self.view].set_active(True)

    # ---------- view ----------
    @property
    def view(self) -> str:
        v = getattr(self.app.settings, "sync_view", "all")
        return v if v in ("all", "synced") else "all"

    def _view_toggled(self, b, key):
        if not b.get_active():
            if key == self.view:
                b.set_active(True)
            return
        if self.app.settings.sync_view != key:         # first, so the other button may let go
            self.app.settings.sync_view = key
            self.app.save_soon()
        for k, other in self.view_btns.items():
            if k != key and other.get_active():
                other.set_active(False)
        self.render()

    def _allocated(self, _w, alloc):
        wide = alloc.width >= WIDE
        if wide != self.wide:
            self.wide = wide
            GLib.idle_add(lambda: (self.render(), False)[1])

    def on_shown(self):
        if not self.shown_once:
            self.shown_once = True
            self._open_synced()
        self.render()

    def reload(self):
        """↻: read Proton Drive again and count every folder again."""
        self.kids.clear()
        self.errors.clear()
        self.stats.clear()
        self._open_synced()
        self.render()

    def _open_synced(self):
        """Open every folder above a synced one, so each synced folder has its line in "Everything in Drive"."""
        for f in self.app.settings.folders:
            p = parent_of(f.remote)
            while section_of(p) and p not in SECTIONS[2:]:
                self.open.add(p)
                if p in SECTIONS:
                    break
                p = parent_of(p)

    def account_changed(self):
        """Another Proton account is active: forget the previous account's Drive and anything not applied."""
        self.kids.clear()
        self.loading.clear()
        self.errors.clear()
        self.staged.clear()
        self.unstaged.clear()
        self.open = {"/my-files"}
        self.shown_once = False
        self.render()

    # ---------- data ----------
    def children(self, path) -> list[Node] | None:
        """Subfolders of `path`, or None while they load for the first time."""
        if path not in self.kids and path not in self.loading and path not in self.errors:
            self._fetch(path)
        return self.kids.get(path)

    def _fetch(self, path):
        """Read a folder's subfolders in the background; an earlier answer stays on screen meanwhile."""
        if path in self.loading:
            return
        self.loading.add(path)

        def work():
            if path == "/shared-with-me":
                raw = self.app.cli.shared_with_me()
                return raw, [Node(f"/shared-with-me/{n.uid}", n.name, n.role or "viewer", leaf=True)
                             for n in raw if n.is_folder]
            return None, [Node(rjoin(path, n.name), n.name) for n in self.app.cli.list(path) if n.is_folder]

        def done(res):
            raw, nodes = res
            self.loading.discard(path)
            self.errors.pop(path, None)
            self.kids[path] = sorted(nodes, key=lambda n: n.name.lower())
            if raw is not None:
                self.app.shared_cache = raw       # the share roles change_mode checks
            self.render()

        def fail(e):
            self.loading.discard(path)
            if path not in self.kids:
                self.errors[path] = str(e)
            self.render()
        run_bg(work, done, fail)

    def synced_by_remote(self) -> dict[str, FolderPair]:
        return {f.remote.rstrip("/"): f for f in self.app.settings.folders}

    def default_local(self, node: Node) -> str:
        root = self.app.settings.root_dir
        sec = section_of(node.remote)
        if sec == "/shared-with-me":
            return os.path.join(root, _("Shared with me"), node.name)
        rel = node.remote[len(sec) + 1:]
        if sec == "/devices":
            return os.path.join(root, _("Computers"), *rel.split("/"))
        return os.path.join(root, *rel.split("/"))

    def default_mode(self, node: Node) -> str:
        if node.leaf and node.role not in ("editor", "admin"):
            return "mirror"
        if section_of(node.remote) == "/devices":
            return "mirror"         # another computer's backup: keep a copy, never change it from here
        return "two-way"

    def jump_to(self, remote: str):
        """Browse → Sync to this computer…: open Sync Center at that folder, ticked (not applied yet)."""
        self.app.window.show_tab("folders")
        if self.view != "all":
            self.view_btns["all"].set_active(True)
        p = parent_of(remote)
        while section_of(p):
            self.open.add(p)
            if p in SECTIONS:
                break
            p = parent_of(p)
        if remote not in self.synced_by_remote() and not self._covering(remote):
            node = Node(remote, os.path.basename(remote))
            self.stage(node)
        self.render()
        GLib.timeout_add(300, self._scroll_to, remote, 20)

    def _scroll_to(self, remote, tries):
        row = self.rows.get(remote)
        if row is None or not row.get_mapped():
            if tries:
                GLib.timeout_add(300, self._scroll_to, remote, tries - 1)
            return False
        xy = row.translate_coordinates(self.scroller.get_child(), 0, 0)
        if xy:
            self.scroller.get_vadjustment().set_value(max(0, xy[1] - 80))
        return False

    def _covering(self, remote) -> FolderPair | None:
        """A synced folder that already includes `remote`."""
        for r, f in self.synced_by_remote().items():
            if remote.startswith(r + "/"):
                return f
        return None

    # ---------- staging ----------
    def stage(self, node: Node):
        for r in list(self.staged):                  # a ticked parent includes its ticked subfolders
            if r.startswith(node.remote + "/"):
                self.staged.pop(r)
        self.staged[node.remote] = Staged(node, self.default_local(node), self.default_mode(node))
        self.stats.want([node.remote])

    def tick(self, node: Node, f: FolderPair | None, on: bool):
        if f:
            (self.unstaged.discard if on else self.unstaged.add)(f.id)
        elif on:
            self.stage(node)
        else:
            self.staged.pop(node.remote, None)
        self.render()

    def discard(self):
        self.staged.clear()
        self.unstaged.clear()
        self.render()

    def problems(self, st: Staged) -> list[tuple[str, str]]:
        """(css class, text) warnings for a folder about to sync; "k-error" ones block Apply."""
        out = []
        s = self.app.settings
        err = validate_local(s, st.local) if os.path.isdir(st.local) else _overlap_text(s, st.local)
        if err:
            out.append(("k-error", err))
        for other in self.staged.values():
            if other is not st and _nested(other.local, st.local):
                out.append(("k-error", _("Same place as {n}").format(n=other.node.name)))
                break
        if not st.use_copy and _has_files(st.local):
            out.append(("k-warn", _("Already has files: identical ones are kept, nothing is deleted")))
        if st.node.leaf and st.node.role not in ("editor", "admin"):
            out.append(("", _("View only · Mirror down")))
        return out

    def copy_offer(self, st: Staged) -> str:
        copy = os.path.join(os.path.expanduser("~/Downloads"), st.node.name)
        if st.mode == "backup" or _has_files(st.local) or not os.path.isdir(copy):
            return ""
        if os.path.realpath(copy) == os.path.realpath(st.local):
            return ""
        return copy

    def apply(self):
        s = self.app.settings
        if any(c == "k-error" for st in self.staged.values() for c, _t in self.problems(st)):
            self.app.toast(_("Fix the problems marked in red first"))
            return
        for fid in list(self.unstaged):
            if s.folder(fid):
                self.app.remove_folder(fid)
        self.unstaged.clear()
        started, failed = [], []
        for remote, st in list(self.staged.items()):
            try:
                if st.use_copy and os.path.isdir(st.use_copy) and not _has_files(st.local):
                    os.makedirs(os.path.dirname(st.local), exist_ok=True)
                    if os.path.isdir(st.local):
                        os.rmdir(st.local)
                    shutil.move(st.use_copy, st.local)
                os.makedirs(st.local, exist_ok=True)
            except OSError as e:
                failed.append(f"{st.node.name}: {e.strerror or e}")
                continue
            err = validate_local(s, st.local)
            if err:
                failed.append(f"{st.node.name}: {err}")
                continue
            f = FolderPair(local=os.path.realpath(st.local), remote=remote, mode=st.mode)
            if st.node.leaf:
                s.shares[remote.rsplit("/", 1)[1]] = f.id
            self.app.add_folder(f, quiet=True)
            self.staged.pop(remote)
            started.append(st.node.name)
        if failed:
            self.app.toast(_("Couldn't start {f}").format(f="; ".join(failed)))
        elif started:
            self.app.toast(ngettext("Syncing {n} · first sync started", "Syncing {k} folders · first sync started",
                                    len(started)).format(n=started[0], k=len(started)))
        self.render()

    # ---------- rendering ----------
    def rebuild(self):
        """A folder was added, removed or edited: open the folders above it so its line shows, and read the
        open folders again (a folder synced for the first time has only now reached Proton Drive)."""
        self._open_synced()
        if self.shown_once:
            for p in list(self.kids):
                if p in self.open or p in SECTIONS:
                    self._fetch(p)
        self.render()

    def refresh_all(self):
        """Every few seconds and after each sync: statuses only, so focus and open menus stay put."""
        for row in self.rows.values():
            if getattr(row, "refresh_status", None):
                row.refresh_status()

    def refresh_folder(self, fid):
        f = self.app.settings.folder(fid)
        row = self.rows.get(f.remote.rstrip("/")) if f else None
        if row is not None and getattr(row, "refresh_status", None):
            row.refresh_status()
        else:
            self.render()

    def render(self):
        """Coalesce bursts (stats, listings, manager events) into one rebuild. Nothing is read from Proton Drive
        before the tab is first opened: an unvisited tab must not slow down the first sync."""
        if not self.shown_once:
            return
        if self._menus_open:                 # rebuilding now would close the menu under the pointer
            self._render_waiting = True
            return
        if not self._render_src:
            self._render_src = GLib.idle_add(self._render)

    def _render(self):
        self._render_src = 0
        adj = self.scroller.get_vadjustment()
        keep = adj.get_value()
        top = self.get_toplevel()
        focus = top.get_focus() if isinstance(top, Gtk.Window) else None
        refocus = getattr(focus, "kluis_name", None) if focus and focus.is_ancestor(self.table) else None
        clear(self.table)
        for g in self.groups.values():
            for w in list(g.get_widgets()):
                g.remove_widget(w)
        self.rows = {}
        synced = self.synced_by_remote()
        if self.wide:
            self.table.pack_start(self._head(), False, False, 0)
        if self.view == "synced":
            folders = sorted(self.app.settings.folders, key=lambda f: f.name.lower())
            pend = [st for st in self.staged.values()]
            if not folders and not pend:
                self.table.pack_start(vbox(
                    label("☁", "k-h0", xalign=0.5), label(_("Nothing syncs yet"), "k-h2", xalign=0.5),
                    label(_("Show “Everything in Drive” and tick a folder, or add one from this computer."),
                          "k-muted", xalign=0.5, wrap=True),
                    hbox(button(_("Show everything in Drive"), lambda: self.view_btns["all"].set_active(True)),
                         button(_("+ Add from this computer…"), self.app.add_folder_dialog),
                         halign=Gtk.Align.CENTER), spacing=8, margin=24), False, False, 0)
            for f in folders:
                node = Node(f.remote.rstrip("/"), f.name)
                self._add(self._row(node, f, None, 0, flat=True))
            for st in pend:
                self._add(self._row(st.node, None, None, 0, flat=True))
        else:
            for sec in SECTIONS:
                self._section(sec, synced)
        self.table.show_all()
        self._pending_bar()
        if refocus:                         # ticking a box rebuilds the table: keep the keyboard where it was
            w = _find(self.table, refocus)
            if w:
                w.grab_focus()
        GLib.idle_add(lambda: (adj.set_value(min(keep, adj.get_upper())), False)[1])
        return False

    def _add(self, row):
        self.table.pack_start(row, False, False, 0)

    def _head(self):
        r = Row(self)
        styled(r, "k-sc-head")
        r.c_name.pack_start(label(_("In Proton Drive"), "k-tablehead"), False, False, 0)
        r.c_path.pack_start(label(_("Folder on this computer"), "k-tablehead"), False, False, 0)
        r.c_mode.pack_start(label(_("How it syncs"), "k-tablehead"), False, False, 0)
        r.c_status.pack_start(label(_("Status"), "k-tablehead"), False, False, 0)
        r.c_warn.pack_start(label(_("Warnings"), "k-tablehead"), False, False, 0)
        r.layout(True)
        return r

    def _section(self, sec, synced):
        head = Gtk.Box(spacing=8)
        styled(head, "k-sc-section")
        head.pack_start(label(ROOT_NAMES[sec], "k-section-head"), False, False, 0)
        self.table.pack_start(head, False, False, 0)
        self._level(sec, synced, 0, None)

    def _level(self, path, synced, depth, inherited):
        nodes = self.children(path)
        if nodes is None:
            if path in self.errors:
                self.table.pack_start(self._note(_("Couldn't read this folder: {e}").format(e=self.errors[path]),
                                                 depth, retry=path), False, False, 0)
            else:
                self.table.pack_start(self._note(_("Reading Proton Drive…"), depth), False, False, 0)
            return
        # a synced folder always has its line, even before its first upload or a fresh listing shows it
        have = {n.remote for n in nodes}
        extra = [Node(r, os.path.basename(r)) for r in synced if parent_of(r) == path and r not in have
                 and path != "/shared-with-me"]
        if extra:
            nodes = sorted(nodes + extra, key=lambda n: n.name.lower())
        if not nodes:
            self.table.pack_start(self._note(_("No folders here") if depth else _("Nothing here yet"), depth),
                                  False, False, 0)
            return
        for n in nodes:
            f = synced.get(n.remote)
            self._add(self._row(n, f, inherited, depth))
            if n.leaf or n.remote not in self.open:
                continue
            own_on = (f and f.id not in self.unstaged) or n.remote in self.staged
            self._level(n.remote, synced, depth + 1, inherited or (self._inherit_info(n, f) if own_on else None))

    def _inherit_info(self, n, f):
        if f:
            return (n.name, f.local, f.mode)
        st = self.staged[n.remote]
        return (n.name, st.local, st.mode)

    def _note(self, text, depth, retry=None):
        b = Gtk.Box(spacing=8, margin_start=40 + 22 * depth)
        styled(b, "k-sc-note")
        b.pack_start(label(text, "k-muted", "k-s13", wrap=True), False, False, 0)
        if retry:
            b.pack_start(button(_("Retry"), lambda: (self.errors.pop(retry, None), self.render()), "k-link"),
                         False, False, 0)
        return b

    def _row(self, node: Node, f: FolderPair | None, inherited, depth, flat=False) -> Row:
        r = Row(self, 0 if flat else depth)
        self.rows[node.remote] = r
        st = self.staged.get(node.remote)
        stopping = bool(f and f.id in self.unstaged)
        own = bool(f and not stopping) or st is not None
        pending = stopping or st is not None
        set_class(r, "k-sc-on", own or bool(inherited))
        set_class(r, "k-sc-pending", pending)
        set_class(r, "k-off", bool(f and not f.enabled))

        # 1. In Proton Drive
        if not flat and not node.leaf:
            opened = node.remote in self.open
            chev = Gtk.Button(label="▾" if opened else "▸")
            styled(chev, "k-flat", "k-sc-chev")
            chev.set_valign(Gtk.Align.CENTER)
            chev.connect("clicked", lambda *_a: self._toggle_open(node.remote))
            a11y(chev, (_("Hide folders in {n}") if opened else _("Show folders in {n}")).format(n=node.name))
            r.c_name.pack_start(chev, False, False, 0)
        elif not flat:
            r.c_name.pack_start(Gtk.Box(width_request=30), False, False, 0)
        tick = Gtk.CheckButton()
        tick.set_active(own or bool(inherited))
        tick.set_sensitive(not inherited)
        tick.set_valign(Gtk.Align.CENTER)
        tick.connect("toggled", lambda b: self.tick(node, f, b.get_active()))
        a11y(tick, _("Include {n}").format(n=node.name),
             _("Synced along with {p}").format(p=inherited[0]) if inherited else None)
        r.c_name.pack_start(tick, False, False, 0)
        stats = self.stats.get(node.remote)
        self.stats.want([node.remote])              # only when missing or older than a day
        meta = files_size(stats)
        if flat:
            crumbs = ROOT_NAMES.get(section_of(node.remote), "")
            sec = section_of(node.remote)
            inner = node.remote[len(sec):].strip("/") if sec != "/shared-with-me" else node.name
            meta = " / ".join([crumbs] + inner.split("/")[:-1]) + " · " + meta
        nm = label(node.name, "k-bold" if own else "", ellipsize="end")
        nm.set_tooltip_text(node.name)
        r.c_name.pack_start(vbox(nm, label(meta, "k-muted", "k-s12", ellipsize="end"), spacing=0,
                                 valign=Gtk.Align.CENTER), True, True, 0)

        # 2. Folder on this computer
        if f and not stopping:
            r.c_path.pack_start(self._path_label(f.local), False, False, 0)
            r.c_path.pack_start(button(_("Change…"), lambda: self.app.edit_folder(f.id), "k-small",
                                       name=_("Change folder for {n}").format(n=node.name)), False, False, 0)
        elif st:
            r.c_path.pack_start(self._path_label(st.local), False, False, 0)
            r.c_path.pack_start(button(_("Change…"), lambda: self._pick_local(st), "k-small",
                                       name=_("Change folder for {n}").format(n=node.name)), False, False, 0)
        elif inherited:
            r.c_path.pack_start(self._path_label(os.path.join(inherited[1], node.name), "k-dim"),
                                False, False, 0)
        else:
            r.c_path.pack_start(label(_("Stops syncing") if stopping else _("Not synced"), "k-muted"), False, False, 0)

        # 3. How it syncs
        viewer = (node.leaf and node.role not in ("editor", "admin")) or bool(f and f.is_share
                                                                              and self.app._share_role(f) == "viewer")
        if f and not stopping:
            seg = ModeSeg(_("Mode of {n}").format(n=f.name), f.mode, None, viewer)
            seg.on_pick = lambda m, fid=f.id, s=seg: self._mode_picked(fid, m, s)
            r.c_mode.pack_start(seg, False, False, 0)
        elif st:
            seg = ModeSeg(_("Mode of {n}").format(n=node.name), st.mode, None, viewer)
            seg.on_pick = lambda m, s=st: (setattr(s, "mode", m), self.render())
            r.c_mode.pack_start(seg, False, False, 0)
        elif inherited:
            g, t, _d = MODES[inherited[2]]
            r.c_mode.pack_start(label(_("Same as {n} ({m})").format(n=inherited[0], m=f"{g} {t}"), "k-muted",
                                      "k-s13", ellipsize="end"), False, False, 0)

        # 4. Status   5. Warnings   6. ⋯
        if f and not stopping:
            self._synced_cells(r, f)
        elif st:
            r.c_status.pack_start(label(_("Starts when you apply"), "k-warn", "k-bold"), False, False, 0)
            self._staged_warnings(r, st)
        elif stopping:
            r.c_status.pack_start(label(_("Stops when you apply"), "k-warn", "k-bold"), False, False, 0)
            r.c_warn.pack_start(label(_("Local files stay"), "k-muted", "k-s13"), False, False, 0)
        elif inherited:
            r.c_status.pack_start(label(_("With {n}").format(n=inherited[0]), "k-muted", "k-s13"), False, False, 0)
        r.layout(self.wide)
        return r

    def _path_label(self, path, *classes):
        lb = label(short_path(path), "k-mono", *classes, ellipsize="middle", max_chars=34)
        lb.set_tooltip_text(path)
        return lb

    def _toggle_open(self, remote):
        (self.open.discard if remote in self.open else self.open.add)(remote)
        self.render()

    def _mode_picked(self, fid, mode, seg):
        if not self.app.change_mode(fid, mode):
            f = self.app.settings.folder(fid)
            GLib.idle_add(lambda: (seg.set_active_id(f.mode) if f else None, False)[1])

    def _pick_local(self, st: Staged):
        from .dialogs import choose_local_folder
        p = choose_local_folder(self.get_toplevel(), _("Where should {n} go on this computer?").format(
            n=st.node.name), os.path.dirname(st.local) if os.path.isdir(os.path.dirname(st.local))
            else os.path.expanduser("~"))
        if p:
            st.local = p if not os.path.isdir(p) or not os.listdir(p) or os.path.basename(p) == st.node.name \
                else os.path.join(p, st.node.name)
            st.use_copy = ""
            self.render()

    def _synced_cells(self, r: Row, f: FolderPair):
        status = label("", "k-s13", ellipsize="end")
        status.set_max_width_chars(26)
        a11y(status, _("Status of {n}").format(n=f.name))
        bar = Gtk.ProgressBar(no_show_all=True)
        r.c_status.pack_start(status, False, False, 0)
        r.c_status.pack_start(bar, False, False, 0)
        review = button(_("Review…"), lambda: self.app.ask_guard(f.id), "k-small",
                        name=_("Review {n}").format(n=f.name))
        review.set_no_show_all(True)
        sync_btn = button("↻", lambda: self.app.manager.request(f.id), "k-small", tooltip=_("Sync this folder now"),
                          name=_("Sync {n} now").format(n=f.name))
        r.c_warn.pack_start(review, False, False, 0)
        if f.is_share and self.app._share_role(f) == "viewer":
            r.c_warn.pack_start(label(_("View only · Mirror down"), "k-muted", "k-s13"), False, False, 0)
        more = Gtk.MenuButton(image=Gtk.Image.new_from_icon_name("kluis-more-symbolic", Gtk.IconSize.BUTTON),
                              tooltip_text=_("More"))
        styled(more, "k-flat")
        a11y(more, _("More for {n}").format(n=f.name))

        def pause():
            g = self.app.settings.folder(f.id)
            if g:
                g.enabled = not g.enabled
                if g.enabled and g.hold == "guard":
                    g.hold = ""
                self.app.settings.save()
                self.app.manager.folder_changed(g)
                self.render()
        more.set_popover(popover_menu(more, [
            (_("Open {n}").format(n=f.name), lambda: open_path(self.app.settings.folder(f.id).local)),
            (_("Resume this folder") if not f.enabled else _("Pause this folder"), pause),
            (_("Edit…"), lambda: self.app.edit_folder(f.id)),
            (_("Show in Kluis browser"), lambda: self.app.window.show_remote(self.app.settings.folder(f.id).remote)),
            (_("Open Proton Drive on the web"), lambda: open_uri(WEB_URL)),
            (_("Check every file again"), lambda: self.app.recheck_folder(f.id)),
            None,
            (_("Stop syncing this folder…"), lambda: self.app.remove_folder(f.id), True),
        ]))
        pop = more.get_popover()
        pop.connect("show", lambda *_a: self._menu_shown(True))
        pop.connect("closed", lambda *_a: self._menu_shown(False))
        r.c_more.pack_start(sync_btn, False, False, 0)
        r.c_more.pack_start(more, False, False, 0)

        def refresh_status():
            g = self.app.settings.folder(f.id)
            if not g or not status.get_parent():
                return
            text, cls, frac = status_text(self.app, g)
            status.set_text(text)
            status.set_tooltip_text(text)
            for c in ("k-ok", "k-warn", "k-error"):
                set_class(status, c, c == cls)
            if frac is not None:
                bar.set_fraction(frac)
                bar.show()
            else:
                bar.hide()
            st = self.app.manager.status.get(g.id)
            state = st.state if st else "idle"
            sync_btn.set_sensitive(g.enabled and state not in ("syncing", "queued") and not self.app.settings.paused)
            review.set_visible(state == "guard")
        r.refresh_status = refresh_status
        refresh_status()
        r.sync_btn, r.more, r.status_lbl = sync_btn, more, status

    def _staged_warnings(self, r: Row, st: Staged):
        for cls, text in self.problems(st):
            lb = label(text, "k-s13", cls or "k-muted", wrap=True, max_chars=28)
            r.c_warn.pack_start(lb, False, False, 0)
        copy = self.copy_offer(st)
        if copy and not st.use_copy:
            r.c_warn.pack_start(label(_("Already here: {p}").format(p=short_path(copy)), "k-warn", "k-s13",
                                      ellipsize="middle", max_chars=40), False, False, 0)
            r.c_warn.pack_start(button(_("Use that copy"), lambda: (setattr(st, "use_copy", copy), self.render()),
                                       "k-link", name=_("Use the copy in {p}").format(p=short_path(copy))),
                                False, False, 0)
        elif st.use_copy:
            r.c_warn.pack_start(label(_("✓ Moves {p} here").format(p=short_path(st.use_copy)), "k-ok", "k-s13",
                                      ellipsize="middle", max_chars=40), False, False, 0)
            r.c_warn.pack_start(button(_("Download again"), lambda: (setattr(st, "use_copy", ""), self.render()),
                                       "k-link"), False, False, 0)

    def _menu_shown(self, on):
        self._menus_open = max(0, self._menus_open + (1 if on else -1))
        if not self._menus_open and self._render_waiting:
            self._render_waiting = False
            self.render()

    def _pending_bar(self):
        adds, stops = len(self.staged), len([i for i in self.unstaged if self.app.settings.folder(i)])
        n = adds + stops
        if not n:
            self.pending.hide()
            return
        parts = []
        if adds:
            parts.append(ngettext("start {n} folder", "start {n} folders", adds).format(n=adds))
        if stops:
            parts.append(ngettext("stop {n} folder", "stop {n} folders", stops).format(n=stops))
        size, unknown = 0, False
        for st in self.staged.values():
            if st.mode == "backup" or st.use_copy:
                continue
            s = self.stats.get(st.node.remote)
            if s is None:
                unknown = True
            else:
                size += s[1]
        text = ngettext("{n} change not applied yet: {what}", "{n} changes not applied yet: {what}", n).format(
            n=n, what=", ".join(parts))
        if adds:
            try:
                free = shutil.disk_usage(_existing(self.app.settings.root_dir)).free
            except OSError:
                free = None
            text += " · " + (_("size still counting…") if unknown else
                             _("about {s} to download").format(s=human_size(size)))
            if free is not None:
                text += " · " + _("{f} free").format(f=human_size(free))
                if not unknown and size > free:
                    text += " · " + _("not enough space")
        blocked = any(c == "k-error" for st in self.staged.values() for c, _t in self.problems(st))
        if blocked:
            text += " · " + _("fix the problems marked in red first")
        self.pending_lbl.set_text(text)
        self.apply_btn.set_sensitive(not blocked)
        self.pending.set_no_show_all(False)
        self.pending.show_all()


def _find(root, name):
    if getattr(root, "kluis_name", None) == name:
        return root
    if isinstance(root, Gtk.Container):
        for c in root.get_children():
            w = _find(c, name)
            if w:
                return w
    return None


def _has_files(path) -> bool:
    try:
        with os.scandir(path) as it:
            return any(True for _e in it)
    except OSError:
        return False


def _existing(path) -> str:
    while path and not os.path.isdir(path):
        path = os.path.dirname(path)
    return path or "/"


def _nested(a, b) -> bool:
    a = os.path.realpath(a).rstrip("/") + "/"
    b = os.path.realpath(b).rstrip("/") + "/"
    return a.startswith(b) or b.startswith(a)


def _overlap_text(settings, local) -> str | None:
    other = settings.overlaps(local)
    if not other:
        return None
    real = os.path.realpath(local)
    if os.path.realpath(other.local) == real:
        return _("Already syncing")
    if real.startswith(os.path.realpath(other.local) + "/"):
        return _("It's inside {n}, which is already syncing").format(n=other.name)
    return _("It contains {n}, which is already syncing").format(n=other.name)



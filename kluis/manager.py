"""Runs syncs in a background thread, schedules them, watches folders, keeps the activity log."""
from __future__ import annotations

import collections
import json
import logging
import os
import threading
import time
from dataclasses import dataclass

from gi.repository import Gio, GLib

from .cli import CliError, CliMissing, ProtonDriveCli
from .config import PHOTOS_ID, FolderPair, Settings
from .engine import SyncEngine, SyncResult
from .paths import ACTIVITY_FILE
from .photos import PhotoSync
from .state import StateStore

log = logging.getLogger("kluis.manager")
DEBOUNCE_S = 8
MAX_WATCHED_DIRS = 4000


@dataclass
class FolderStatus:
    state: str = "idle"   # idle | queued | syncing | ok | error | conflict | disabled
    text: str = ""
    done: int = 0
    total: int = 0


@dataclass
class Activity:
    ts: float
    level: str            # info | ok | warning | error
    folder: str
    text: str


class SyncManager:
    def __init__(self, settings: Settings, cli: ProtonDriveCli):
        self.settings = settings
        self.cli = cli
        self.store = StateStore()
        self.engine = SyncEngine(cli, self.store, self._engine_event)
        self.photos = PhotoSync(cli, self.store, self._engine_event)
        self.status: dict[str, FolderStatus] = {}
        self.activity: collections.deque[Activity] = collections.deque(maxlen=500)
        self.logged_in: bool | None = None
        self.current: str | None = None
        self.last_run = 0.0
        self.listeners = []                 # callables(kind, fid)
        self._queue: collections.deque[str] = collections.deque()
        self._wake = threading.Event()
        self._stop = False
        self._monitors: dict[str, list[Gio.FileMonitor]] = {}
        self._debounce: dict[str, int] = {}
        self._quiet_until: dict[str, float] = {}
        self._load_activity()
        for f in settings.folders:
            self.status[f.id] = self._initial_status(f)
        self.status[PHOTOS_ID] = self._photo_status()
        self._thread = threading.Thread(target=self._worker, name="kluis-sync", daemon=True)
        self._thread.start()
        GLib.timeout_add_seconds(30, self._tick)

    # ---------- notifications to the UI (always on the GTK main thread) ----------
    def _notify(self, kind: str, fid: str | None = None, payload=None):
        def go():
            for cb in list(self.listeners):
                try:
                    cb(kind, fid, payload)
                except Exception:  # noqa: BLE001
                    log.exception("listener failed")
            return False
        GLib.idle_add(go)

    def _initial_status(self, f: FolderPair) -> FolderStatus:
        if not f.enabled:
            return FolderStatus("disabled", "Paused for this folder")
        if f.last_result:
            return FolderStatus(f.last_result, f.last_message)
        return FolderStatus("idle", "Waiting for first sync")

    def _photo_status(self) -> FolderStatus:
        ps = self.settings.photos
        if not ps.active:
            return FolderStatus("disabled", "Off")
        if ps.last_result:
            return FolderStatus(ps.last_result, ps.last_message)
        return FolderStatus("idle", "Waiting for first sync")

    def name_of(self, fid: str | None) -> str:
        if fid == PHOTOS_ID:
            return "Photos"
        f = self.settings.folder(fid) if fid else None
        return f.name if f else ""

    def photos_changed(self, reset: bool = False):
        if reset:
            self.store.photos_reset()
        self.status[PHOTOS_ID] = self._photo_status()
        self._notify("folder", PHOTOS_ID)
        if self.settings.photos.active:
            self.request(PHOTOS_ID)

    # ---------- public API ----------
    @property
    def busy(self) -> bool:
        return self.current is not None or bool(self._queue)

    def request(self, fid: str | None = None, reason: str = "manual"):
        if self.settings.paused and reason != "manual":
            return
        if self.logged_in is False:
            return
        ids = [fid] if fid else [f.id for f in self.settings.folders if f.enabled]
        if not fid and self.settings.photos.active:
            ids.append(PHOTOS_ID)
        for i in ids:
            if i in self._queue or i == self.current:
                continue
            if i == PHOTOS_ID:
                if not self.settings.photos.active:
                    continue
            else:
                f = self.settings.folder(i)
                if not f or not f.enabled:
                    continue
            self._queue.append(i)
            self.status[i] = FolderStatus("queued", "Waiting…")
            self._notify("folder", i)
        self._notify("global")
        self._wake.set()

    def cancel(self):
        self._queue.clear()
        self.engine.cancel()
        self.photos.cancel()
        self._notify("global")

    def set_paused(self, paused: bool):
        self.settings.paused = paused
        self.settings.save()
        if paused:
            self.cancel()
        else:
            self.request(reason="resume")
        self._notify("global")

    def folder_added(self, f: FolderPair):
        self.status[f.id] = self._initial_status(f)
        self.rewatch()
        self.request(f.id)

    def folder_removed(self, fid: str):
        self.status.pop(fid, None)
        if fid in self._queue:
            self._queue.remove(fid)
        if self.current == fid:
            self.engine.cancel()
        self.store.forget_folder(fid)
        self.rewatch()
        self._notify("global")

    def folder_changed(self, f: FolderPair, reset_state: bool = False):
        if reset_state:
            self.store.forget_folder(f.id)
        self.status[f.id] = self._initial_status(f)
        self.rewatch()
        self._notify("folder", f.id)
        if f.enabled:
            self.request(f.id)

    def check_account(self, then=None):
        """Find the CLI, then check sign-in. Runs in a thread; reports via 'account'."""
        def work():
            state = "ok"
            try:
                self.logged_in = self.cli.is_logged_in()
                if not self.logged_in:
                    state = "signed-out"
            except CliMissing:
                state, self.logged_in = "no-cli", None
            except CliError as e:
                state = "offline"
                self.log("error", "", f"Could not reach Proton Drive: {e}")
            self._notify("account", None, state)
            if then:
                GLib.idle_add(then, state)
        threading.Thread(target=work, daemon=True).start()

    def log(self, level: str, fid: str, text: str):
        a = Activity(time.time(), level, self.name_of(fid), text)
        self.activity.appendleft(a)
        try:
            with open(ACTIVITY_FILE, "a") as fh:
                fh.write(json.dumps(a.__dict__, ensure_ascii=False) + "\n")
        except OSError:
            pass
        self._notify("activity", fid, a)

    def clear_activity(self):
        self.activity.clear()
        try:
            ACTIVITY_FILE.unlink()
        except OSError:
            pass
        self._notify("activity")

    def shutdown(self):
        self._stop = True
        self.engine.cancel()
        self._wake.set()

    # ---------- worker ----------
    def _worker(self):
        while not self._stop:
            self._wake.wait(timeout=5)
            self._wake.clear()
            while self._queue and not self._stop:
                fid = self._queue.popleft()
                if fid == PHOTOS_ID:
                    self._run_photos()
                    continue
                f = self.settings.folder(fid)
                if not f or not f.enabled:
                    continue
                self.current = fid
                self.status[fid] = FolderStatus("syncing", "Starting…")
                self._notify("folder", fid)
                self._notify("global")
                started = time.time()
                res: SyncResult = self.engine.sync(f)
                self.current = None
                self._quiet_until[fid] = time.time() + 4
                self._finish(f, res, time.time() - started)

    def _run_photos(self):
        ps = self.settings.photos
        if not ps.active:
            return
        self.current = PHOTOS_ID
        self.status[PHOTOS_ID] = FolderStatus("syncing", "Starting…")
        self._notify("folder", PHOTOS_ID)
        self._notify("global")
        started = time.time()
        res = self.photos.sync(ps)
        self.current = None
        took = time.time() - started
        if res.status == "cancelled":
            self.status[PHOTOS_ID] = FolderStatus("idle", "Stopped")
        else:
            ps.last_sync, ps.last_result, ps.last_message = time.time(), res.status, res.message
            self.status[PHOTOS_ID] = FolderStatus(res.status, res.message)
            GLib.idle_add(self._save)
            if res.status == "error":
                self.log("error", PHOTOS_ID, res.message)
                for e in res.errors[1:6]:
                    self.log("error", PHOTOS_ID, e)
            elif res.message != "Up to date":
                self.log("ok", PHOTOS_ID, f"{res.message} ({took:.0f}s)")
        self.last_run = time.time()
        self._notify("folder", PHOTOS_ID)
        self._notify("global")
        self._notify("photos-done", PHOTOS_ID, res)
        self._notify("result", PHOTOS_ID, res)

    def _finish(self, f: FolderPair, res: SyncResult, took: float):
        if res.status == "cancelled":
            self.status[f.id] = FolderStatus("idle", "Stopped")
        else:
            f.last_sync = time.time()
            f.last_result, f.last_message = res.status, res.message
            self.status[f.id] = FolderStatus(res.status, res.message)
            GLib.idle_add(self._save)
            if res.status == "error":
                if any("login" in e.lower() for e in res.errors):
                    self.logged_in = False
                    self._notify("account", None, "signed-out")
                self.log("error", f.id, res.message)
                for e in res.errors[1:6]:
                    self.log("error", f.id, e)
            elif res.status == "conflict":
                self.log("warning", f.id, res.message)
            elif res.message != "Up to date":
                self.log("ok", f.id, f"{res.message} ({took:.0f}s)")
        self.last_run = time.time()
        self._notify("folder", f.id)
        self._notify("global")
        self._notify("result", f.id, res)

    def _save(self):
        self.settings.save()
        return False

    def _engine_event(self, fid, kind, **data):
        if kind == "phase":
            self.status[fid] = FolderStatus("syncing", data.get("text", ""))
        elif kind == "progress":
            self.status[fid] = FolderStatus("syncing", data.get("text", ""), data.get("done", 0),
                                            data.get("total", 0))
        elif kind == "log":
            self.log(data.get("level", "info"), fid, data.get("text", ""))
            return
        self._notify("folder", fid)
        self._notify("global")

    # ---------- schedule ----------
    def _tick(self):
        if not self.settings.paused and self.logged_in and not self.busy:
            if time.time() - self.last_run >= self.settings.interval_minutes * 60:
                self.request(reason="schedule")
        self._notify("tick")
        return True

    def next_run_in(self) -> float:
        return max(0.0, self.last_run + self.settings.interval_minutes * 60 - time.time())

    # ---------- watching local folders ----------
    def rewatch(self):
        for mons in self._monitors.values():
            for m in mons:
                m.cancel()
        self._monitors.clear()
        budget = MAX_WATCHED_DIRS
        for f in self.settings.folders:
            if not (f.enabled and f.watch and f.mode in ("two-way", "backup") and os.path.isdir(f.local)):
                continue
            mons = []
            for dirpath, dirnames, _ in os.walk(f.local):
                dirnames[:] = [d for d in dirnames if not d.startswith(".Trash")]
                if budget <= 0:
                    break
                try:
                    m = Gio.File.new_for_path(dirpath).monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
                except GLib.Error:
                    continue
                m.connect("changed", self._on_local_change, f.id)
                mons.append(m)
                budget -= 1
            self._monitors[f.id] = mons

    def _on_local_change(self, _mon, file, _other, event, fid):
        if event in (Gio.FileMonitorEvent.ATTRIBUTE_CHANGED, Gio.FileMonitorEvent.PRE_UNMOUNT):
            return
        if self.current == fid or time.time() < self._quiet_until.get(fid, 0):
            return
        if event == Gio.FileMonitorEvent.CREATED and file.query_file_type(Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
                                                                           None) == Gio.FileType.DIRECTORY:
            GLib.timeout_add_seconds(1, lambda: (self.rewatch(), False)[1])
        if fid in self._debounce:
            GLib.source_remove(self._debounce[fid])

        def fire():
            self._debounce.pop(fid, None)
            self.request(fid, reason="change")
            return False
        self._debounce[fid] = GLib.timeout_add_seconds(DEBOUNCE_S, fire)

    # ---------- persistence ----------
    def _load_activity(self):
        try:
            lines = ACTIVITY_FILE.read_text().splitlines()[-500:]
        except OSError:
            return
        for line in lines:
            try:
                self.activity.appendleft(Activity(**json.loads(line)))
            except (ValueError, TypeError):
                continue

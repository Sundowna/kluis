"""Runs syncs in a background thread, schedules them, watches folders, keeps the activity log.

Safety jobs that live here:
  * hold states (offline, disk full, signed out, rate limit) pause everything and retry with
    exponential backoff, max 15 min, never a retry storm (invariant 10);
  * guard results (mass deletion, missing folder) pause only that folder until it is safe (8, 9);
  * Pause and Stop cancel the CLI; the engine leaves no half-written files (7).
"""
from __future__ import annotations

import collections
import json
import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass

from gi.repository import Gio, GLib

from .cli import CliError, CliMissing, ProtonDriveCli
from .config import PART_DIR, PHOTOS_ID, FolderPair, Settings
from .engine import SyncEngine, SyncResult
from .errors import DISK_FULL, SIGNED_OUT, STATUS_TEXT, backoff_delay, classify
from .paths import ACTIVITY_FILE, STATE_DIR
from .photos import PhotoSync
from .state import StateStore

log = logging.getLogger("kluis.manager")
DEBOUNCE_S = 8
MAX_WATCHED_DIRS = 4000
RATE_WINDOW = 120          # seconds of transfer history for the graph (1 sample/s)
MIN_FREE_BYTES = 200 * 1024 * 1024


@dataclass
class FolderStatus:
    state: str = "idle"   # idle | queued | syncing | ok | error | conflict | disabled | guard | missing | hold
    text: str = ""
    done: int = 0
    total: int = 0


@dataclass
class Activity:
    ts: float
    level: str            # info | ok | warning | error
    folder: str
    text: str
    detail: str = ""


class SyncManager:
    def __init__(self, settings: Settings, cli: ProtonDriveCli, store: StateStore | None = None,
                 start_thread: bool = True):
        self.settings = settings
        self.cli = cli
        self.store = store or StateStore()
        self.engine = SyncEngine(cli, self.store, self._engine_event)
        self.photos = PhotoSync(cli, self.store, self._engine_event)
        self.status: dict[str, FolderStatus] = {}
        self.activity: collections.deque[Activity] = collections.deque(maxlen=500)
        self.unread = 0
        self.logged_in: bool | None = None
        self.email = ""
        self.switching = False              # a Proton account switch is under way: start nothing
        self.current: str | None = None
        self.last_run = 0.0
        self.last_remote_check = 0.0
        self.listeners = []                 # callables(kind, fid, payload)
        self.hold: dict | None = None       # {"kind", "until", "attempt", "text"}
        self.guard_counts: dict[str, int] = {}
        self._allow_trash: dict[str, int] = {}
        self._queue: collections.deque[str] = collections.deque()
        self._again: set[str] = set()      # asked for while running: run once more afterwards
        self._wake = threading.Event()
        self._stop = False
        self._monitors: dict[str, list[Gio.FileMonitor]] = {}
        self._debounce: dict[str, int] = {}
        self._quiet_until: dict[str, float] = {}
        # run progress (for "Syncing 27 of 40 files", Stop toast and ETA)
        self.run_started = 0.0
        self.run_done = 0
        self.run_total = 0
        self.run_file_times: list[float] = []
        self.state_since = time.time()      # when the overall status last changed kind
        self._last_kind = ""
        # transfer history
        self.samples: collections.deque[tuple[float, float]] = collections.deque(
            [(0.0, 0.0)] * RATE_WINDOW, maxlen=RATE_WINDOW)
        self._pending_bytes: list[list[float]] = []   # [up_per_s, down_per_s, seconds_left]
        self.today = self._load_today()
        self._load_activity()
        for f in settings.folders:
            self.status[f.id] = self._initial_status(f)
        self.status[PHOTOS_ID] = self._photo_status()
        if start_thread:
            self._thread = threading.Thread(target=self._worker, name="kluis-sync", daemon=True)
            self._thread.start()
            GLib.timeout_add_seconds(1, self._second)
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
            return FolderStatus("disabled", "Off · not syncing")
        if f.hold == "missing":
            return FolderStatus("missing", f"Folder not found: {f.local}. Reconnect the drive or choose "
                                           "the folder again.")
        if f.hold == "guard":
            return FolderStatus("guard", "Paused · Kluis wants to check before moving files to the trash")
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
            if self.current == PHOTOS_ID:
                # a run is writing download records for the old folder: stop it, reset when it has ended
                self._photo_reset = True
                self.photos.cancel()
                self._again.add(PHOTOS_ID)
            else:
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
        if self.settings.paused:
            return          # paused: new changes wait on this computer until resume (§4.2)
        if self.logged_in is False or self.hold or self.switching:
            return
        ids = [fid] if fid else [f.id for f in self.settings.folders if f.enabled]
        if not fid and self.settings.photos.active:
            ids.append(PHOTOS_ID)
        if not self.busy:
            self.run_started, self.run_done, self.run_total, self.run_file_times = time.time(), 0, 0, []
        for i in ids:
            if i == self.current:
                self._again.add(i)          # a change during the run is never lost
                continue
            if i in self._queue:
                continue
            if i == PHOTOS_ID:
                if not self.settings.photos.active:
                    continue
            else:
                f = self.settings.folder(i)
                if not f or not f.enabled:
                    continue
                if f.hold and not fid:
                    continue        # a guarded folder only runs when asked for by name
            self._queue.append(i)
            self.status[i] = FolderStatus("queued", "Waiting for its turn…")
            self._notify("folder", i)
        self._notify("global")
        self._wake.set()

    def cancel(self) -> tuple[int, int]:
        """Stop now. Returns (done, total) of the current run for the "Stopped at N of M" toast."""
        done, total = self.run_done, self.run_total
        self._queue.clear()
        self._again.clear()
        self.engine.cancel()
        self.photos.cancel()
        for k, st in self.status.items():
            if st.state == "queued":
                self.status[k] = self._initial_status(self.settings.folder(k)) if k != PHOTOS_ID \
                    else self._photo_status()
        self._notify("global")
        return done, total

    def use_account(self, store_path: str):
        """After a Proton account switch: that account's sync history, folder status and watchers."""
        self._queue.clear()
        self._again.clear()
        self.store = StateStore(store_path)
        self.engine.store = self.store
        self.photos.store = self.store
        self.hold = None
        self.guard_counts.clear()
        self._allow_trash.clear()
        self.status = {f.id: self._initial_status(f) for f in self.settings.folders}
        self.status[PHOTOS_ID] = self._photo_status()
        self.rewatch()
        self._notify("global")

    def set_paused(self, paused: bool):
        if self.settings.paused == paused:
            return
        self.settings.paused = paused
        self.settings.save()
        if paused:
            self.cancel()
            self.log("info", "", "Sync paused")
        else:
            self.log("info", "", "Sync resumed")
            self.request(reason="resume")
        self._notify("global")

    def folder_added(self, f: FolderPair):
        self.status[f.id] = self._initial_status(f)
        self.rewatch()
        self.request(f.id)

    def folder_removed(self, fid: str):
        """Stops syncing only: nothing is deleted on either side (invariant 5)."""
        self.status.pop(fid, None)
        if fid in self._queue:
            self._queue.remove(fid)
        if self.current == fid:
            self.engine.cancel()
        self.rewatch()
        self._notify("global")

    def folder_restored(self, f: FolderPair):
        """Undo of a remove: the sync state was kept, so nothing is re-downloaded."""
        self.status[f.id] = self._initial_status(f)
        self.rewatch()
        self._notify("global")
        if f.enabled:
            self.request(f.id)

    def forget_folder_state(self, fid: str):
        self.store.forget_folder(fid)

    def folder_changed(self, f: FolderPair, reset_state: bool = False):
        if reset_state:
            self.store.forget_folder(f.id)
            self.log("info", f.id, "Every file will be checked again on the next sync")
        self.status[f.id] = self._initial_status(f)
        self.rewatch()
        self._notify("folder", f.id)
        self._notify("global")
        if f.enabled:
            self.request(f.id)

    # ---------- guards ----------
    def approve_trash(self, fid: str):
        """The user chose "Move them to the trash" in the mass-deletion dialog."""
        f = self.settings.folder(fid)
        if not f:
            return
        self._allow_trash[fid] = self.guard_counts.get(fid, 0)
        f.hold = ""
        self.settings.save()
        self.log("info", fid, f"Moving {self._allow_trash[fid]} files to the trash, as you confirmed")
        self.status[fid] = FolderStatus("idle", "")
        self.request(fid)

    def keep_paused(self, fid: str):
        f = self.settings.folder(fid)
        if not f:
            return
        f.hold = "guard"
        self.settings.save()
        self.status[fid] = self._initial_status(f)
        self.log("warning", fid, "Kept everything; this folder is paused until you check it")
        self._notify("folder", fid)
        self._notify("global")

    # ---------- account ----------
    def check_account(self, then=None):
        """Find the CLI, then check sign-in. Runs in a thread; reports via 'account'."""
        def work():
            state = "ok"
            try:
                self.logged_in = self.cli.is_logged_in()
                if not self.logged_in:
                    state = "signed-out"
                else:
                    self.clear_hold(SIGNED_OUT)
                    self._read_email()
            except CliMissing:
                state, self.logged_in = "no-cli", None
            except CliError as e:
                state = "offline"
                self.log("error", "", "Couldn't reach Proton Drive", str(e))
            self._notify("account", None, state)
            if then:
                GLib.idle_add(then, state)
        threading.Thread(target=work, daemon=True).start()

    def _read_email(self):
        try:
            info = self.cli.info("/my-files")
            owner = info.get("ownedBy") or {}
            self.email = owner.get("email", "") if isinstance(owner, dict) else ""
        except CliError:
            pass

    # ---------- holds (invariant 10) ----------
    def set_hold(self, kind: str, detail: str = ""):
        attempt = (self.hold or {}).get("attempt", -1) + 1 if self.hold and self.hold["kind"] == kind else 0
        delay = backoff_delay(attempt)
        first = not self.hold or self.hold["kind"] != kind
        self.hold = {"kind": kind, "until": time.time() + delay, "attempt": attempt,
                     "text": STATUS_TEXT.get(kind, kind), "detail": detail}
        self._queue.clear()
        if kind == SIGNED_OUT:
            self.logged_in = False
            self._notify("account", None, "signed-out")
        if first:
            nxt = time.strftime("%H:%M", time.localtime(self.hold["until"]))
            self.log("error" if kind != "offline" else "warning", "", self.hold["text"],
                     f"Kluis will try again at {nxt}." + (f" ({detail})" if detail else ""))
            self._notify("problem", None, kind)
        self._notify("global")

    def clear_hold(self, kind: str | None = None):
        if self.hold and (kind is None or self.hold["kind"] == kind):
            was = self.hold["kind"]
            self.hold = None
            self.log("ok", "", "Back to normal", f"{STATUS_TEXT.get(was, was)} — resolved")
            self._notify("global")
            GLib.idle_add(lambda: (self.request(reason="resume"), False)[1])

    def _probe_hold(self):
        """Runs in a thread when the backoff time is up: is the problem gone?"""
        h = self.hold
        if not h:
            return
        try:
            if h["kind"] == DISK_FULL:
                if all(shutil.disk_usage(f.local).free >= MIN_FREE_BYTES
                       for f in self.settings.folders if f.enabled and os.path.isdir(f.local)):
                    self.clear_hold(DISK_FULL)
                    return
                raise OSError("still full")
            ok = self.cli.is_logged_in()
            if not ok:
                self.set_hold(SIGNED_OUT)
                return
            self.logged_in = True
            self.clear_hold()
        except (CliError, OSError) as e:
            kind = classify(e) or h["kind"]
            self.set_hold(kind, str(e))

    # ---------- activity ----------
    def log(self, level: str, fid: str, text: str, detail: str = ""):
        a = Activity(time.time(), level, self.name_of(fid), text, detail)
        self.activity.appendleft(a)
        if level in ("warning", "error"):
            self.unread += 1
        try:
            with open(ACTIVITY_FILE, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(a.__dict__, ensure_ascii=False) + "\n")
        except OSError:
            pass
        self._notify("activity", fid, a)

    def clear_activity(self) -> list:
        """Returns the removed entries so Undo can put them back."""
        old = list(self.activity)
        self.activity.clear()
        self.unread = 0
        try:
            ACTIVITY_FILE.unlink()
        except OSError:
            pass
        self._notify("activity")
        return old

    def restore_activity(self, entries: list):
        self.activity.clear()
        self.activity.extend(entries)
        try:
            with open(ACTIVITY_FILE, "w", encoding="utf-8") as fh:
                for a in reversed(entries):
                    fh.write(json.dumps(a.__dict__, ensure_ascii=False) + "\n")
        except OSError:
            pass
        self._notify("activity")

    def mark_read(self):
        self.unread = 0
        self._notify("global")

    def shutdown(self):
        self._stop = True
        self.engine.cancel()
        self.photos.cancel()
        self._wake.set()
        self._save_today()

    # ---------- worker ----------
    def _worker(self):
        while not self._stop:
            self._wake.wait(timeout=5)
            self._wake.clear()
            while self._queue and not self._stop and not self.settings.paused and not self.hold                     and not self.switching:
                fid = self._queue.popleft()
                if fid == PHOTOS_ID:
                    self._run_photos()
                    self._requeue(fid, "ok")
                    continue
                f = self.settings.folder(fid)
                if not f or not f.enabled:
                    continue
                self.current = fid
                self.status[fid] = FolderStatus("syncing", "Starting…")
                self._notify("folder", fid)
                self._notify("global")
                started = time.time()
                allow = self._allow_trash.pop(fid, 0)
                res: SyncResult = self.engine.sync(f, allow_trash=allow)
                self.current = None
                self._quiet_until[fid] = time.time() + 4
                self._finish(f, res, time.time() - started)
                self._requeue(fid, res.status)

    def _requeue(self, fid, status):
        if fid in self._again:
            self._again.discard(fid)
            if status not in ("hold", "guard", "missing") and fid not in self._queue:
                self._queue.append(fid)

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
        if getattr(self, "_photo_reset", False):
            self._photo_reset = False
            self.store.photos_reset()
            res.status, res.message = "cancelled", "Stopped"
            self._again.add(PHOTOS_ID)
        self.current = None
        took = time.time() - started
        if res.status == "cancelled":
            self.status[PHOTOS_ID] = FolderStatus("idle", "Stopped")
        elif res.status == "hold":
            self.status[PHOTOS_ID] = self._photo_status()
            self.set_hold(res.hold_kind, res.message)
        else:
            ps.last_sync, ps.last_result, ps.last_message = time.time(), res.status, res.message
            self.status[PHOTOS_ID] = FolderStatus(res.status, res.message)
            GLib.idle_add(self._save)
            if res.status == "error":
                self.log("error", PHOTOS_ID, res.message, "Kluis will try again on the next check.")
                for e in res.errors[1:6]:
                    self.log("error", PHOTOS_ID, e)
            elif res.message != "Up to date":
                self.log("ok", PHOTOS_ID, res.message, f"took {took:.0f} s")
        self.last_run = time.time()
        self._notify("folder", PHOTOS_ID)
        self._notify("global")
        self._notify("photos-done", PHOTOS_ID, res)
        self._notify("result", PHOTOS_ID, res)

    def _finish(self, f: FolderPair, res: SyncResult, took: float):
        if res.status == "cancelled":
            self.status[f.id] = FolderStatus("idle", "Stopped · nothing lost")
        elif res.status == "hold":
            self.status[f.id] = FolderStatus("hold", STATUS_TEXT.get(res.hold_kind, res.message))
            self.set_hold(res.hold_kind, res.message)
        elif res.status == "guard":
            f.hold = "guard"
            self.guard_counts[f.id] = res.pending_trash
            self.status[f.id] = FolderStatus("guard", "Paused · waiting for you to confirm the trash")
            GLib.idle_add(self._save)
            self.log("warning", f.id, f"Paused: {res.pending_trash} files would go to the trash",
                     "Kluis waits for you to confirm or keep everything.")
            self._notify("guard", f.id, res.pending_trash)
        elif res.status == "missing":
            f.hold = "missing"
            self.status[f.id] = FolderStatus("missing", res.message)
            GLib.idle_add(self._save)
            self.log("error", f.id, res.message, "Nothing was moved to the trash. Kluis checks again every 30 s.")
            self._notify("problem", f.id, "missing")
        else:
            if f.hold == "missing":
                f.hold = ""
            f.last_sync = time.time()
            f.last_result, f.last_message = res.status, res.message
            f.last_files = res.files
            self.status[f.id] = FolderStatus(res.status, res.message)
            GLib.idle_add(self._save)
            if res.status == "error":
                self.log("error", f.id, res.message, "Kluis will try again on the next check.")
                for e in res.errors[1:6]:
                    self.log("error", f.id, e)
            elif res.status == "conflict":
                self.log("warning", f.id, res.message, "Both copies are in the folder.")
            elif res.message != "Up to date":
                self.log("ok", f.id, res.message, f"took {took:.0f} s")
        self.last_run = time.time()
        self.last_remote_check = time.time()
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
            st = self.status.get(fid)
            prev_done = st.done if st and st.state == "syncing" else 0
            prev_total = st.total if st and st.state == "syncing" else 0
            done, total = data.get("done", 0), data.get("total", 0)
            self.run_total += max(0, total - prev_total)
            if done > prev_done:
                self.run_file_times.append(time.time())
                self.run_done += done - prev_done
            self.status[fid] = FolderStatus("syncing", data.get("text", ""), done, total)
        elif kind == "bytes":
            secs = max(1.0, data.get("seconds", 1.0))
            up, down = data.get("up", 0), data.get("down", 0)
            self._pending_bytes.append([up / secs, down / secs, secs])
            self.today["up"] += up
            self.today["down"] += down
            return
        elif kind == "log":
            self.log(data.get("level", "info"), fid, data.get("text", ""))
            return
        self._notify("folder", fid)
        self._notify("global")

    # ---------- schedule ----------
    def _second(self):
        """1 sample per second for the transfer graph (D6)."""
        up = down = 0.0
        for p in self._pending_bytes:
            up += p[0]
            down += p[1]
            p[2] -= 1
        self._pending_bytes = [p for p in self._pending_bytes if p[2] > 0]
        if self.settings.paused or not self.busy:
            up = down = 0.0
            self._pending_bytes.clear()
        self.samples.append((up, down))
        self._notify("rate")
        return True

    def _tick(self):
        now = time.time()
        if self.switching:
            return True
        if self.hold and now >= self.hold["until"]:
            threading.Thread(target=self._probe_hold, daemon=True).start()
        for f in self.settings.folders:
            if f.hold == "missing" and f.enabled and os.path.isdir(f.local) and os.access(f.local, os.R_OK):
                if any(True for _ in os.scandir(f.local)):
                    f.hold = ""
                    self.log("info", f.id, "Folder is back; syncing again")
                    self.request(f.id, reason="schedule")
        if not self.settings.paused and self.logged_in and not self.busy and not self.hold:
            if now - self.last_run >= self.settings.interval_minutes * 60:
                self.request(reason="schedule")
        self._roll_today()
        self._notify("tick")
        return True

    # ---------- today's totals ----------
    def _today_file(self):
        return STATE_DIR / "today.json"

    def _load_today(self) -> dict:
        day = time.strftime("%Y-%m-%d")
        try:
            d = json.loads(self._today_file().read_text(encoding="utf-8"))
            if d.get("day") == day:
                return d
        except (OSError, ValueError):
            pass
        return {"day": day, "up": 0, "down": 0}

    def _roll_today(self):
        day = time.strftime("%Y-%m-%d")
        if self.today.get("day") != day:
            self.today = {"day": day, "up": 0, "down": 0}
        self._save_today()

    def _save_today(self):
        try:
            tmp = self._today_file().with_suffix(".tmp")
            tmp.write_text(json.dumps(self.today), encoding="utf-8")
            os.replace(tmp, self._today_file())
        except OSError:
            pass

    # ---------- watching local folders ----------
    def unwatch(self):
        """Stop watching (Windows: no handle stays open in a synced folder, e.g. while it is being moved)."""
        for mons in self._monitors.values():
            for m in mons:
                m.cancel()
        self._monitors.clear()

    def rewatch(self):
        self.unwatch()
        if os.name == "nt":
            return self._rewatch_windows()
        budget = MAX_WATCHED_DIRS
        for f in self.settings.folders:
            if not (f.enabled and f.watch and f.mode in ("two-way", "backup") and os.path.isdir(f.local)):
                continue
            mons = []
            for dirpath, dirnames, _ in os.walk(f.local):
                dirnames[:] = [d for d in dirnames if not d.startswith(".Trash") and d != PART_DIR]
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

    def _rewatch_windows(self):
        """One handle per synced folder (kluis/winwatch.py): subfolders stay free to rename and move."""
        from .winwatch import TreeWatcher
        for f in self.settings.folders:
            if not (f.enabled and f.watch and f.mode in ("two-way", "backup") and os.path.isdir(f.local)):
                continue
            try:
                w = TreeWatcher(f.local, lambda rel, action, fid=f.id: GLib.idle_add(
                    lambda: (self._local_changed(fid, rel), False)[1]))
            except OSError as e:
                log.warning("can't watch %s: %s", f.local, e)
                continue
            self._monitors[f.id] = [w]

    def watching(self) -> int:
        return sum(1 for f in self.settings.folders if f.enabled and f.watch and not f.hold
                   and f.mode in ("two-way", "backup") and f.id in self._monitors)

    def _on_local_change(self, _mon, file, _other, event, fid):
        if event in (Gio.FileMonitorEvent.ATTRIBUTE_CHANGED, Gio.FileMonitorEvent.PRE_UNMOUNT):
            return
        path = file.get_path() or ""
        if event == Gio.FileMonitorEvent.CREATED and not self._is_part(path) and                 time.time() >= self._quiet_until.get(fid, 0) and                 file.query_file_type(Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, None) == Gio.FileType.DIRECTORY:
            GLib.timeout_add_seconds(1, lambda: (self.rewatch(), False)[1])
        self._local_changed(fid, path)

    @staticmethod
    def _is_part(path: str) -> bool:
        p = "/" + path.replace("\\", "/").strip("/") + "/"
        return f"/{PART_DIR}/" in p

    def _local_changed(self, fid, path):
        """Something changed in a synced folder: sync it DEBOUNCE_S seconds after the last change."""
        if self._is_part(path):
            return
        if time.time() < self._quiet_until.get(fid, 0):
            return                          # our own writes right after a run
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
            lines = ACTIVITY_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-500:]
        except OSError:
            return
        for line in lines:
            try:
                d = json.loads(line)
                self.activity.appendleft(Activity(**{k: v for k, v in d.items()
                                                     if k in Activity.__dataclass_fields__}))
            except (ValueError, TypeError):
                continue

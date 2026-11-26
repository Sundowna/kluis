"""The big-items lane: big files and big folders sync next to everything else, not in front of it.

A sync run (kluis/engine.py) hands every big item to this lane instead of transferring it itself:
a file of at least BIG_BYTES, or a folder with at least that much to transfer (a folder full of photos).
The lane transfers one item at a time with its own copy of the Proton Drive CLI, which is built for
more than one process at a time (its cache is SQLite in WAL mode; only one process listens for events).
Meanwhile the normal sync keeps running, and leaves the lane's items alone (engine.drop_held).

The user can pause an item (it stays out of every sync until resumed: FolderPair.held, so a restart
keeps it paused), resume it, or send it first. Paused items resume by themselves once nothing else
has synced for Settings.resume_paused_after minutes (0 = never), see SyncManager._auto_resume.

Pausing an item that is being transferred stops its CLI process. The CLI can't continue an upload or
download where it stopped, so that file starts again from the beginning; a folder keeps the files
that were already done.

No GTK here: the manager passes callbacks, so the script tests can drive the lane directly.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from .cli import CliError
from .config import PART_DIR, FolderPair
from .engine import LANE_DIR, Cancelled, LocalItem, SyncEngine, SyncResult
from .errors import HoldError, classify

log = logging.getLogger("kluis.lane")


@dataclass
class LaneItem:
    fid: str
    direction: str              # up | down
    rel: str                    # the file, or the folder, relative to the synced folder
    is_folder: bool
    files: list                 # rel paths of the files to transfer
    bytes: int
    local: dict = field(default_factory=dict)     # snapshots of the files at planning time (engine dicts)
    remote: dict | None = None
    state: str = "waiting"      # waiting | running | paused
    added: float = field(default_factory=time.time)
    started: float = 0.0
    done_files: int = 0

    @property
    def key(self) -> tuple:
        return (self.fid, self.direction, self.rel)

    @property
    def hold_path(self) -> str:
        return self.rel + "/" if self.is_folder else self.rel

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1] or self.rel


class BigLane:
    def __init__(self, settings, make_cli: Callable, store_of: Callable, *,
                 may_run: Callable[[], bool] = lambda: True,
                 on_change: Callable[[], None] = lambda: None,
                 on_event: Callable[..., None] | None = None,
                 on_log: Callable[[str, str, str, str], None] = lambda *a: None,
                 on_hold: Callable[[str, str], None] = lambda kind, text: None,
                 on_quiet: Callable[[str], None] = lambda fid: None,
                 on_done: Callable[[str], None] = lambda fid: None,
                 start_thread: bool = True):
        self.settings = settings
        self.make_cli = make_cli            # a new ProtonDriveCli for each item (follows CLI updates)
        self.store_of = store_of            # the current account's StateStore
        self.may_run = may_run              # False while sync is paused, on hold or switching accounts
        self.on_change = on_change
        self.on_event = on_event or (lambda *a, **k: None)
        self.on_log = on_log                # (level, folder id, text, detail)
        self.on_hold = on_hold
        self.on_quiet = on_quiet            # the lane wrote into this folder: don't sync it again for that
        self.on_done = on_done              # an item finished well: a fresh look at its folder updates its status
        self.items: list[LaneItem] = []     # waiting and running, in order
        self.paused: dict[tuple, LaneItem] = {}   # (fid, hold path) -> last known item, for display
        self.current: LaneItem | None = None
        self.engine: SyncEngine | None = None
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = False
        self._drop_current = False          # the running item was paused or cancelled: don't log it as done
        if start_thread:
            threading.Thread(target=self._worker, name="kluis-lane", daemon=True).start()

    # ---------- what the sync runs ask ----------
    def held(self, fid: str) -> list:
        """Paths the normal sync leaves alone in this folder: paused, waiting or being transferred."""
        f = self.settings.folder(fid)
        out = list(f.held) if f else []
        with self._lock:
            out += [it.hold_path for it in self.items if it.fid == fid]
        return out

    def add(self, f: FolderPair, direction: str, item: tuple, local: dict, remote: dict | None):
        rel, is_folder, files, nbytes = item
        it = LaneItem(f.id, direction, rel, is_folder, list(files), nbytes,
                      {r: local[r] for r in files if r in local},
                      {r: remote[r] for r in files if remote and r in remote} if remote is not None else None)
        with self._lock:
            if any(x.key == it.key for x in self.items) or it.hold_path in f.held:
                return
            self.items.append(it)
        log.info("[%s] big item for the lane: %s %s (%d files, %d bytes)", f.name, direction, rel, len(files),
                 nbytes)
        self.on_log("info", f.id, f"{self._what(it)} goes to the big-items lane",
                    "It syncs next to everything else; pause it or send it first in Activity.")
        self.on_change()
        self._wake.set()

    # ---------- what the user does ----------
    def pause(self, key: tuple) -> bool:
        """Leaves the item out of every sync until resumed. True if it was being transferred (it restarts)."""
        with self._lock:
            it = next((x for x in self.items if x.key == key), None)
            if not it:
                return False
            was_running = it is self.current
            self.items.remove(it)
            it.state = "paused"
            self.paused[(it.fid, it.hold_path)] = it
            f = self.settings.folder(it.fid)
            if f and it.hold_path not in f.held:
                f.held.append(it.hold_path)
            if was_running:
                self._drop_current = True
        self.settings.save()
        if was_running and self.engine:
            self.engine.cancel()
        self.on_log("info", it.fid, f"Paused {self._what(it)}",
                    "It starts again from the beginning when resumed." if was_running and not it.is_folder else "")
        self.on_change()
        return was_running

    def resume(self, fid: str, path: str) -> bool:
        """Takes a paused item back into the sync. The caller asks for a sync of the folder."""
        f = self.settings.folder(fid)
        if not f or path not in f.held:
            return False
        f.held.remove(path)
        with self._lock:
            self.paused.pop((fid, path), None)
        self.settings.save()
        self.on_change()
        return True

    def paused_list(self) -> list[tuple[FolderPair, str, LaneItem | None]]:
        """Every paused item: (folder, path, last known item or None after a restart)."""
        out = []
        for f in self.settings.folders:
            for path in f.held:
                out.append((f, path, self.paused.get((f.id, path))))
        return out

    def send_first(self, key: tuple) -> bool:
        """Next in line. The item being transferred keeps going (stopping it would start it over)."""
        with self._lock:
            it = next((x for x in self.items if x.key == key), None)
            if not it or it is self.current:
                return False
            self.items.remove(it)
            at = 1 if self.current is not None and self.items and self.items[0] is self.current else 0
            self.items.insert(at, it)
        self.on_change()
        return True

    def cancel_all(self):
        """Stop, Pause all, sign-out, account switch: the lane empties; the next sync plans its items again."""
        with self._lock:
            if self.current is not None:
                self._drop_current = True
            self.items = []
        if self.engine:
            self.engine.cancel()
        self.on_change()

    def forget_folder(self, fid: str):
        with self._lock:
            if self.current is not None and self.current.fid == fid:
                self._drop_current = True
                if self.engine:
                    self.engine.cancel()
            self.items = [x for x in self.items if x.fid != fid]
            self.paused = {k: v for k, v in self.paused.items() if k[0] != fid}
        self.on_change()

    def shutdown(self):
        self._stop = True
        if self.engine:
            self.engine.cancel()
        self._wake.set()

    # ---------- state for the UI ----------
    @property
    def busy(self) -> bool:
        return bool(self.items)

    def waiting(self) -> list[LaneItem]:
        with self._lock:
            return [x for x in self.items if x is not self.current]

    # ---------- the worker ----------
    def _worker(self):
        while not self._stop:
            self._wake.wait(timeout=5)
            self._wake.clear()
            while not self._stop and self.items and self.may_run():
                with self._lock:
                    if not self.items:
                        break
                    it = self.items[0]
                    self.current, self._drop_current = it, False
                    it.state, it.started = "running", time.time()
                self.on_change()
                try:
                    self.run_item(it)
                finally:
                    with self._lock:
                        if it in self.items:
                            self.items.remove(it)
                        self.current = None
                    self.on_change()

    def run_item(self, it: LaneItem) -> SyncResult:
        """Transfers one item. Runs on the lane's thread (the tests call it directly)."""
        res = SyncResult()
        f = self.settings.folder(it.fid)
        if not f or not f.enabled or not os.path.isdir(f.local):
            return res
        eng = SyncEngine(self.make_cli(), self.store_of(), self._event)
        eng.windows = getattr(self, "windows", eng.windows)
        self.engine = eng
        local = dict(it.local)
        files = []
        for r in it.files:
            if it.direction == "up":
                try:
                    st = os.stat(os.path.join(f.local, r))
                except OSError:
                    continue                        # gone since: the next sync sees that
                local[r] = LocalItem(False, st.st_size, st.st_mtime_ns)
            files.append(r)
        total = len(files)
        eng._prog = (0, total)

        def step(label, n=1):
            it.done_files = min(it.done_files + n, total)
            eng._prog = (it.done_files, total)
            self.on_change()

        def done_of(rels):
            self.on_quiet(it.fid)

        started = time.time()
        try:
            if it.direction == "up":
                eng.upload_files(f, files, local, res, step, done_of)
            else:
                eng._clear_parts(f, lane=True)
                stage = os.path.join(f.local, PART_DIR, LANE_DIR, f"{os.getpid()}-{time.time_ns()}")
                try:
                    eng.download_files(f, files, local, it.remote, res, step, stage, done_of)
                finally:
                    eng._clear_parts(f, lane=True)
        except HoldError as e:
            res.status, res.hold_kind, res.message = "hold", e.kind, str(e)
        except CliError as e:
            kind = classify(e)
            if e.code == 130:
                res.status = "cancelled"
            elif kind:
                res.status, res.hold_kind, res.message = "hold", kind, str(e)
            else:
                res.errors.append(str(e))
        except Cancelled:
            res.status = "cancelled"
        except Exception as e:  # noqa: BLE001  (OSError: disk full, file in use …)
            if classify(e):
                res.status, res.hold_kind, res.message = "hold", classify(e), str(e)
            else:
                log.exception("lane item failed")
                res.errors.append(str(e))
        finally:
            self.engine = None
        took = time.time() - started
        if res.status == "hold":
            self.on_hold(res.hold_kind, res.message)
        elif res.status == "cancelled" or self._drop_current:
            pass
        elif res.errors:
            self.on_log("error", it.fid, f"{self._what(it)}: {res.errors[0]}",
                        "Kluis tries again on the next sync.")
        else:
            n = res.uploaded if it.direction == "up" else res.downloaded
            self.on_log("ok", it.fid, f"{'Uploaded' if it.direction == 'up' else 'Downloaded'} {self._what(it)}",
                        f"{n} file(s) · took {_took(took)}")
            self.on_done(it.fid)
        return res

    def _event(self, fid, kind, **data):
        if kind == "bytes":
            self.on_event(fid, kind, **data)       # the transfer graph and today's totals
        elif kind == "log":
            self.on_log(data.get("level", "info"), fid, data.get("text", ""), "")

    @staticmethod
    def _what(it: LaneItem) -> str:
        from .status import human_bytes
        size = human_bytes(it.bytes)
        if it.is_folder:
            return f"the folder {it.rel} ({len(it.files)} files, {size})"
        return f"{it.name} ({size})"


def _took(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min"
    return f"{s // 3600} h {s % 3600 // 60} min"

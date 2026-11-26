"""Sync engine: compares local, remote and last-synced state, then runs the official CLI.

Safety rules
  * Nothing is ever deleted permanently. Deletions go to the system Trash (local) or the
    Proton Drive trash (remote), and only when the other side was deleted and this side
    was not changed since the last sync.
  * When both sides changed, both copies are kept ("name (conflict 2026-11-17 host).ext").
  * Overwritten remote files stay available as earlier revisions in Proton Drive.
"""
from __future__ import annotations

import fnmatch
import hashlib
import logging
import os
import posixpath
import shutil
import socket
import stat as statmod
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from .cli import CliError, ProtonDriveCli, RemoteNode, TransferSummary, rjoin
from .config import PART_DIR, FolderPair
from .errors import DISK_FULL, HoldError, classify
from .state import Entry, StateStore
from .system import IS_WINDOWS, windows_name_problem
from .system import move_to_trash as _system_trash

log = logging.getLogger("kluis.engine")
BATCH = 40  # paths per CLI call
GUARD_FILES = 50        # §7.8: more than 50 files …
GUARD_SHARE = 0.10      # … or more than 10 % of the folder in one run asks first
# Big items (a file this size, or a folder with this much to transfer) go to their own lane (kluis/lane.py),
# so they don't hold up everything else. Tests set KLUIS_BIG_BYTES to a few bytes.
BIG_BYTES = int(os.environ.get("KLUIS_BIG_BYTES") or 1 << 30)
LANE_DIR = "lane"       # <folder>/.kluis-part/lane: the big-items lane's staging, kept while a run clears its own


def is_held(rel: str, held) -> bool:
    """`held`: paths of files ("a/b.zip") and folders ("photos/2023/", trailing slash = everything in it)."""
    for h in held:
        if h.endswith("/"):
            if rel == h[:-1] or rel.startswith(h) or h == "/":
                return True
        elif rel == h:
            return True
    return False


def holds_inside(rel: str, held) -> bool:
    """Is a held item inside the folder `rel` (so the folder must not go to a trash)?"""
    return any(h.rstrip("/").startswith(rel + "/") for h in held)


def split_big(files: list, size_of, big: int = 0):
    """Splits transfers into (small, items). An item is (rel, is_folder, [files], bytes): every file of at least
    `big` bytes on its own; then, deepest folder first, a folder whose files still left (its own and its
    subfolders' not taken yet) add up to `big`. Files directly in the synced folder itself only go as big files."""
    big = big or int(os.environ.get("KLUIS_BIG_BYTES") or BIG_BYTES)
    items, rest = [], []
    for r in files:
        s = size_of(r) or 0
        if s >= big:
            items.append((r, False, [r], s))
        else:
            rest.append(r)
    pending = defaultdict(list)
    dirs = set()
    for r in rest:
        d = posixpath.dirname(r)
        pending[d].append(r)
        while d:
            dirs.add(d)
            d = posixpath.dirname(d)
    taken = set()
    for d in sorted(dirs, key=lambda x: (-x.count("/"), x)):
        n = sum(size_of(r) or 0 for r in pending[d])
        if n >= big:
            items.append((d, True, list(pending[d]), n))
            taken.update(pending[d])
            pending[d] = []
        pending[posixpath.dirname(d)].extend(pending.pop(d, []))
    big_files = {it[0] for it in items if not it[1]}
    small = [r for r in files if r not in taken and r not in big_files]
    return small, items


def _win_case(name: str) -> str:
    """The key Windows (NTFS) compares names by: each character upper-cased on its own. Unlike casefold(),
    "ß" stays "ß", so "straße.txt" and "strasse.txt" are two files, as they are on Windows."""
    return "".join(u if len(u := c.upper()) == 1 else c for c in name)


class Cancelled(Exception):
    pass


@dataclass
class LocalItem:
    is_dir: bool
    size: int = 0
    mtime: int = 0  # ns


@dataclass
class Plan:
    upload: list = field(default_factory=list)          # rel paths (files)
    download: list = field(default_factory=list)        # rel paths (files)
    mkdir_remote: list = field(default_factory=list)    # rel dirs
    mkdir_local: list = field(default_factory=list)     # rel dirs
    trash_remote: list = field(default_factory=list)    # rel (file or dir)
    trash_local: list = field(default_factory=list)     # rel (file or dir)
    conflicts: list = field(default_factory=list)       # rel files: keep both
    record: list = field(default_factory=list)          # rel: already identical, just record
    forget: list = field(default_factory=list)          # rel: gone on both sides

    @property
    def transfers(self) -> int:
        return len(self.upload) + len(self.download) + len(self.conflicts)

    @property
    def empty(self) -> bool:
        return not any([self.upload, self.download, self.mkdir_remote, self.mkdir_local,
                        self.trash_remote, self.trash_local, self.conflicts])

    def describe(self) -> str:
        bits = []
        for n, label in ((len(self.upload), "↑ {}"), (len(self.download), "↓ {}"),
                         (len(self.conflicts), "{} conflict(s)"),
                         (len(self.trash_local) + len(self.trash_remote), "{} to trash")):
            if n:
                bits.append(label.format(n))
        return ", ".join(bits) or "up to date"


@dataclass
class SyncResult:
    status: str = "ok"          # ok | error | conflict | cancelled | guard | missing | hold
    message: str = ""
    hold_kind: str = ""         # errors.HOLD_KINDS when status == "hold"
    pending_trash: int = 0      # guard: files this run would move to a trash
    files: int = 0              # files in the folder after this run
    bytes_up: int = 0
    bytes_down: int = 0
    uploaded: int = 0
    downloaded: int = 0
    conflicts: int = 0
    trashed: int = 0
    deferred: int = 0           # big items handed to the big-items lane this run
    held: int = 0               # transfers left out: paused by the user, or already in the lane
    waiting: int = 0            # changes left for later because the files lane is paused
    errors: list = field(default_factory=list)


def sha1_file(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def conflict_name(rel: str) -> str:
    d, base = posixpath.split(rel)
    stem, ext = os.path.splitext(base)
    if stem.startswith(".") and not ext:
        stem, ext = base, ""
    tag = f" (conflict {datetime.now():%Y-%m-%d %H%M} {socket.gethostname()})"
    return posixpath.join(d, f"{stem}{tag}{ext}")


def move_to_trash(path: str):
    """Freedesktop Trash via Gio on Linux (what Nemo uses), the Recycle Bin on Windows (kluis/system.py)."""
    _system_trash(path)


class SyncEngine:
    def __init__(self, cli: ProtonDriveCli, store: StateStore,
                 on_event: Callable[..., None] | None = None):
        self.cli = cli
        self.store = store
        self.on_event = on_event or (lambda *a, **k: None)
        self._cancel = False
        self.windows = IS_WINDOWS          # names Windows can't store (fit_windows_names); tests switch it on
        self._told: set = set()            # (folder id, rel) of skipped names already logged this session
        # Big-items lane (kluis/lane.py), set by the manager. defer(f, direction, item, local, remote) takes a big
        # item; held(folder id) lists paths to leave alone this run (paused, or being transferred by the lane).
        self.defer: Callable | None = None
        self.held: Callable[[str], list] | None = None
        # files_paused(): the user paused lane 1 (everything but big items). A run then only hands big items
        # to the big-items lane; every other change waits on both sides, nothing is trashed.
        self.files_paused: Callable[[], bool] | None = None

    # ---------------- public ----------------
    def cancel(self):
        self._cancel = True
        self.cli.cancel()

    def sync(self, f: FolderPair, dry_run: bool = False, allow_trash: int = 0) -> SyncResult:
        """One run. `allow_trash`: the user confirmed the mass-deletion guard for up to this many files."""
        self._cancel = False
        res = SyncResult()
        f = self.effective(f)
        try:
            state = self.store.load(f.id)
            had_files = sum(1 for e in state.values() if not e.is_dir)
            # §7.9 missing-folder guard: a vanished folder or drive is never "everything deleted"
            if not os.path.isdir(f.local):
                if f.mode == "mirror" and not had_files:
                    os.makedirs(f.local, exist_ok=True)
                else:
                    return self._missing(f, res)
            if not os.access(f.local, os.R_OK | os.X_OK):
                return self._missing(f, res)
            self._clear_parts(f)
            self._emit(f, "phase", text="Looking for changes on this computer…")
            local = self.scan_local(f)
            if had_files and not any(not li.is_dir for li in local.values()):
                return self._missing(f, res)
            remote = None
            if f.mode != "backup":
                self._emit(f, "phase", text="Looking for changes in Proton Drive…")
                remote = self.scan_remote(f)
                if self.windows:
                    remote, local = self.fit_windows_names(f, local, remote, state)
            plan = self.make_plan(f, local, remote, state)
            res.held = self.drop_held(plan, self.held(f.id) if self.held else [])
            if self.defer is not None and self.files_paused and self.files_paused():
                res.waiting = len(plan.conflicts) + len(plan.trash_local) + len(plan.trash_remote)
                plan.conflicts, plan.trash_local, plan.trash_remote = [], [], []
                self._files_paused = True
            else:
                self._files_paused = False
            log.info("[%s] plan: %s", f.name, plan.describe())
            if dry_run:
                res.message = plan.describe()
                return res
            # §7.8 mass-deletion guard
            n_trash = self.trash_count(plan, local, remote)
            folder_files = max(had_files, 1)
            if n_trash and (n_trash > GUARD_FILES or n_trash > GUARD_SHARE * folder_files) \
                    and n_trash > allow_trash:
                res.status, res.pending_trash = "guard", n_trash
                res.message = (f"Kluis is about to move {n_trash} files from {f.name} to the trash. "
                               "This usually means a folder was moved or a drive is missing.")
                return res
            self.execute(f, plan, local, remote, res)
            res.files = sum(1 for e in self.store.load(f.id).values() if not e.is_dir)
        except Cancelled:
            res.status, res.message = "cancelled", "Stopped"
            return res
        except HoldError as e:
            res.status, res.hold_kind, res.message = "hold", e.kind, str(e)
            return res
        except CliError as e:
            if e.code == 130:
                res.status, res.message = "cancelled", "Stopped"
                return res
            kind = classify(e)
            if kind:
                res.status, res.hold_kind, res.message = "hold", kind, str(e)
                return res
            res.status, res.message = "error", str(e)
            res.errors.append(str(e))
            return res
        except OSError as e:
            if classify(e) == DISK_FULL:
                res.status, res.hold_kind, res.message = "hold", DISK_FULL, str(e)
                return res
            res.status, res.message = "error", str(e)
            res.errors.append(str(e))
            return res
        finally:
            self._clear_parts(f)
        if res.errors:
            res.status = "error"
            res.message = f"{len(res.errors)} problem(s): {res.errors[0]}"
        elif res.conflicts:
            res.status = "conflict"
            res.message = f"Kept both copies of {res.conflicts} file(s)"
        else:
            parts = []
            if res.uploaded:
                parts.append(f"↑ {res.uploaded} uploaded")
            if res.downloaded:
                parts.append(f"↓ {res.downloaded} downloaded")
            if res.trashed:
                parts.append(f"{res.trashed} moved to trash")
            res.message = ", ".join(parts) or "Up to date"
            if res.waiting:
                res.message = f"Files lane paused · {res.waiting} change(s) wait" + (
                    f" · {', '.join(parts)}" if parts else "")
            if res.deferred:
                res.message += f" · {res.deferred} big item(s) in the big-items lane"
        return res

    @staticmethod
    def drop_held(p: Plan, held) -> int:
        """Leaves paused items and items the big-items lane is transferring out of this run. Returns how many."""
        if not held:
            return 0
        n = 0
        for name in ("upload", "download", "conflicts", "record", "forget"):
            keep = [r for r in getattr(p, name) if not is_held(r, held)]
            if name in ("upload", "download", "conflicts"):
                n += len(getattr(p, name)) - len(keep)
            setattr(p, name, keep)
        for name in ("trash_remote", "trash_local"):
            setattr(p, name, [r for r in getattr(p, name) if not is_held(r, held) and not holds_inside(r, held)])
        return n

    # ---------------- guards ----------------
    def effective(self, f: FolderPair) -> FolderPair:
        """Viewer shares are always mirror-down (invariant 4). Unknown role counts as viewer."""
        if not f.is_share:
            return f
        role = self.share_role(f.remote)
        if role in ("editor", "admin") or f.mode == "mirror":
            return f
        import dataclasses
        return dataclasses.replace(f, mode="mirror")

    def share_role(self, remote: str) -> str:
        top = remote[len("/shared-with-me/"):].split("/")[0]
        try:
            for n in self.cli.list("/shared-with-me"):
                if n.uid == top or n.name == top:
                    return n.role or "viewer"
        except CliError as e:
            if classify(e):
                raise
        return "viewer"

    def _missing(self, f: FolderPair, res: SyncResult) -> SyncResult:
        res.status = "missing"
        res.message = f"Folder not found: {f.local}. Reconnect the drive or choose the folder again."
        return res

    def trash_count(self, plan: Plan, local: dict, remote: dict | None) -> int:
        """Files (not folders) this plan would move to either trash, including files inside trashed folders."""
        n = 0
        for rel in plan.trash_local:
            li = local.get(rel)
            if li and li.is_dir:
                n += sum(1 for r, x in local.items() if r.startswith(rel + "/") and not x.is_dir)
            else:
                n += 1
        for rel in plan.trash_remote:
            rn = (remote or {}).get(rel)
            if rn and rn.is_folder:
                n += sum(1 for r, x in (remote or {}).items() if r.startswith(rel + "/") and not x.is_folder)
            else:
                n += 1
        return n

    def _clear_parts(self, f: FolderPair, lane: bool = False):
        """Remove Kluis's own staging folder (only ever holds partial downloads Kluis made). The big-items lane's
        part (.kluis-part/lane) stays while the lane may be using it; `lane=True` clears only that part."""
        d = os.path.join(f.local, PART_DIR)
        if not os.path.isdir(d) or os.path.islink(d):
            return
        if lane:
            shutil.rmtree(os.path.join(d, LANE_DIR), ignore_errors=True)
            try:
                os.rmdir(d)          # only when empty: a normal run may be staging there
            except OSError:
                pass
            return
        if self.defer is None:
            shutil.rmtree(d, ignore_errors=True)
            return
        for name in os.listdir(d):
            if name != LANE_DIR:
                p = os.path.join(d, name)
                try:
                    shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.unlink(p)
                except OSError:
                    pass
        try:
            os.rmdir(d)          # only when empty
        except OSError:
            pass

    @staticmethod
    def _hold_if_fatal(e):
        kind = classify(e)
        if kind:
            raise HoldError(kind, str(e))

    # ---------------- scanning ----------------
    def _ignored(self, f: FolderPair, rel: str) -> bool:
        if rel == PART_DIR or rel.startswith(PART_DIR + "/"):
            return True
        base = posixpath.basename(rel)
        for pat in f.ignore:
            pat = pat.strip()
            if not pat:
                continue
            if fnmatch.fnmatch(base, pat) or ("/" in pat and fnmatch.fnmatch(rel, pat.strip("/"))):
                return True
        return False

    def scan_local(self, f: FolderPair) -> dict[str, LocalItem]:
        out: dict[str, LocalItem] = {}
        root = os.path.abspath(f.local)
        stack = [""]
        while stack:
            self._check()
            rel_dir = stack.pop()
            try:
                with os.scandir(os.path.join(root, rel_dir)) as it:
                    for de in it:
                        rel = posixpath.join(rel_dir, de.name) if rel_dir else de.name
                        if self._ignored(f, rel):
                            continue
                        if IS_WINDOWS and getattr(de, "is_junction", lambda: False)():
                            continue        # a Windows junction points elsewhere (like a symlink): not followed
                        try:
                            st = de.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        if statmod.S_ISDIR(st.st_mode):
                            out[rel] = LocalItem(True)
                            stack.append(rel)
                        elif statmod.S_ISREG(st.st_mode):
                            out[rel] = LocalItem(False, st.st_size, st.st_mtime_ns)
            except PermissionError:
                log.warning("No permission to read %s", rel_dir)
        return out

    def scan_remote(self, f: FolderPair) -> dict[str, RemoteNode] | None:
        out: dict[str, RemoteNode] = {}
        try:
            children = self.cli.list(f.remote)
        except CliError as e:
            if e.not_found and f.mode == "two-way":
                self.cli.ensure_folder(f.remote)
                return {}
            raise
        queue = [("", children)]
        done = 0
        while queue:
            self._check()
            rel_dir, kids = queue.pop()
            for n in kids:
                if n.type not in ("file", "folder"):
                    continue
                if n.media_type.startswith("application/vnd.proton"):
                    continue  # Proton Docs / Sheets cannot be downloaded
                rel = posixpath.join(rel_dir, n.name) if rel_dir else n.name
                if self._ignored(f, rel):
                    continue
                out[rel] = n
                if n.is_folder:
                    done += 1
                    self._emit(f, "phase", text=f"Looking in Proton Drive… {done} folders")
                    queue.append((rel, self.cli.list(rjoin(f.remote, rel))))
        return out

    # ---------------- Windows names ----------------
    def fit_windows_names(self, f: FolderPair, local: dict, remote: dict, state: dict):
        """Proton Drive (like Linux) allows names Windows can't store, and names that differ only in upper and
        lower case ("Notes.txt" next to "notes.txt"), which are the same file on Windows. Such items are left
        out of the sync: never downloaded under another name, never moved to a trash, nothing changed in
        Proton Drive; the Activity log says why. Of a pair that differs only in case, the one Kluis already
        syncs (or the one on this computer) stays in the sync.

        Local names Windows reports in another case than Proton Drive ("notes.txt" on disk, "Notes.txt" in
        Proton) are the same item: they take Proton Drive's spelling, so the sync doesn't see two files.
        Returns (remote, local) to plan with."""
        dropped: list[str] = []
        skipped: list[tuple[str, str]] = []
        for rel in sorted(remote):
            if self._under(rel, dropped):
                continue
            why = windows_name_problem(posixpath.basename(rel))
            if why:
                dropped.append(rel)
                skipped.append((rel, why))
        groups = defaultdict(list)
        for rel in remote:
            if not self._under(rel, dropped):
                groups[_win_case(rel)].append(rel)
        for key in sorted(groups, key=lambda k: k.count("/")):
            rels = [r for r in groups[key] if not self._under(r, dropped)]
            if len(rels) < 2:
                continue
            keep = next((r for r in sorted(rels) if r in state), None) or \
                next((r for r in sorted(rels) if r in local), None) or sorted(rels)[0]
            for r in sorted(rels):
                if r != keep:
                    dropped.append(r)
                    skipped.append((r, f"its name differs from {posixpath.basename(keep)} only in upper and "
                                       "lower case, and Windows can't keep both in one folder"))
        remote = {r: n for r, n in remote.items() if not self._under(r, dropped)}
        for rel, why in skipped:
            if (f.id, rel) not in self._told:
                self._told.add((f.id, rel))
                log.warning("[%s] not synced: %s (%s)", f.name, rel, why)
                self._emit(f, "log", level="warning", text=f"Left out {rel}: {why}. It stays in Proton Drive.")
        spelling = {_win_case(r): r for r in state}
        spelling.update({_win_case(r): r for r in remote})
        moves = {rel: spelling[_win_case(rel)] for rel in local
                 if rel not in remote and rel not in state and _win_case(rel) in spelling}
        if moves:
            fitted = {}
            for rel, li in local.items():
                new = moves.get(rel, rel)
                if new in local and new != rel or new in fitted:
                    new = rel        # a case-sensitive folder holds both spellings: keep each as it is
                fitted[new] = li
            local = fitted
        return remote, local

    # ---------------- planning ----------------
    def _local_sha1(self, f: FolderPair, rel: str, li: LocalItem) -> str:
        path = os.path.join(f.local, rel)
        cached = self.store.cached_sha1(path, li.size, li.mtime)
        if cached:
            return cached
        h = sha1_file(path)
        self.store.store_sha1(path, li.size, li.mtime, h)
        return h

    def make_plan(self, f: FolderPair, local: dict, remote: dict | None,
                  state: dict[str, Entry]) -> Plan:
        if f.mode == "backup":
            return self._plan_backup(f, local, state)
        if f.mode == "mirror":
            return self._plan_mirror(f, local, remote or {}, state)
        return self._plan_two_way(f, local, remote or {}, state)

    @staticmethod
    def _lchanged(li: LocalItem, s: Entry | None) -> bool:
        return s is None or s.is_dir or li.size != s.lsize or li.mtime != s.lmtime

    @staticmethod
    def _rchanged(rn: RemoteNode, s: Entry | None) -> bool:
        return s is None or s.is_dir or (rn.revision or rn.sha1) != (s.rrev or s.sha1)

    def _plan_backup(self, f, local, state) -> Plan:
        p = Plan()
        for rel in sorted(local):
            li, s = local[rel], state.get(rel)
            if li.is_dir:
                if s is None:
                    p.mkdir_remote.append(rel)
            elif self._lchanged(li, s):
                p.upload.append(rel)
        return p

    def _plan_mirror(self, f, local, remote, state) -> Plan:
        p = Plan()
        for rel in sorted(set(remote) | set(state)):
            rn, li, s = remote.get(rel), local.get(rel), state.get(rel)
            if rn is None:
                if s is not None and li is not None and f.mirror_deletions and not self._under(rel, p.trash_local):
                    if (self._subtree_unchanged_local(rel, local, state) if li.is_dir
                            else not self._lchanged(li, s)):
                        p.trash_local.append(rel)
                elif s is not None and li is None:
                    p.forget.append(rel)
                continue
            if rn.is_folder:
                if li is None:
                    p.mkdir_local.append(rel)
                elif not li.is_dir:
                    p.conflicts.append(rel)
                elif s is None:
                    p.record.append(rel)
                continue
            if li is None:
                p.download.append(rel)
            elif li.is_dir:
                p.conflicts.append(rel)
            elif s is None:
                if rn.sha1 and rn.sha1 == self._local_sha1(f, rel, li):
                    p.record.append(rel)
                else:
                    p.conflicts.append(rel)  # local copy kept as conflict file, remote wins the name
            elif self._rchanged(rn, s) or self._lchanged(li, s):
                if self._lchanged(li, s):
                    p.conflicts.append(rel)
                else:
                    p.download.append(rel)
        return p

    @staticmethod
    def _under(rel: str, dirs: list) -> bool:
        return any(rel == d or rel.startswith(d + "/") for d in dirs)

    def _subtree_unchanged_local(self, root, local, state) -> bool:
        for rel, li in local.items():
            if rel == root or rel.startswith(root + "/"):
                if not li.is_dir and self._lchanged(li, state.get(rel)):
                    return False
                if li.is_dir and rel not in state:
                    return False
        return True

    def _subtree_unchanged_remote(self, root, remote, state) -> bool:
        for rel, rn in remote.items():
            if rel == root or rel.startswith(root + "/"):
                if not rn.is_folder and self._rchanged(rn, state.get(rel)):
                    return False
                if rn.is_folder and rel not in state:
                    return False
        return True

    def _plan_two_way(self, f, local, remote, state) -> Plan:
        p = Plan()
        handled: list[str] = []
        for rel in sorted(set(local) | set(remote) | set(state)):
            if self._under(rel, handled):
                continue
            li, rn, s = local.get(rel), remote.get(rel), state.get(rel)

            # ----- folders -----
            ldir = li is not None and li.is_dir
            rdir = rn is not None and rn.is_folder
            if ldir and rdir:
                if s is None:
                    p.record.append(rel)
                continue
            if ldir and rn is None:
                if s is not None and f.mirror_deletions and self._subtree_unchanged_local(rel, local, state):
                    p.trash_local.append(rel)
                    handled.append(rel)
                else:
                    p.mkdir_remote.append(rel)
                continue
            if rdir and li is None:
                if s is not None and f.mirror_deletions and self._subtree_unchanged_remote(rel, remote, state):
                    p.trash_remote.append(rel)
                    handled.append(rel)
                else:
                    p.mkdir_local.append(rel)
                continue
            if ldir or rdir:  # folder on one side, file on the other
                p.conflicts.append(rel)
                handled.append(rel)
                continue

            # ----- files -----
            if li is None and rn is None:
                if s is not None:
                    p.forget.append(rel)
                continue
            if rn is None:
                if s is not None and f.mirror_deletions and not self._lchanged(li, s):
                    p.trash_local.append(rel)
                else:
                    p.upload.append(rel)
                continue
            if li is None:
                if s is not None and f.mirror_deletions and not self._rchanged(rn, s):
                    p.trash_remote.append(rel)
                else:
                    p.download.append(rel)
                continue
            lc, rc = self._lchanged(li, s), self._rchanged(rn, s)
            if not lc and not rc:
                continue
            if lc and not rc and s is not None:
                p.upload.append(rel)
            elif rc and not lc:
                p.download.append(rel)
            else:  # both changed, or first meeting of two existing files
                if rn.sha1 and rn.sha1 == self._local_sha1(f, rel, li):
                    p.record.append(rel)
                else:
                    p.conflicts.append(rel)
        return p

    # ---------------- execution ----------------
    def execute(self, f: FolderPair, p: Plan, local: dict, remote: dict | None, res: SyncResult):
        fid = f.id
        total = max(p.transfers, 1)
        done = 0

        def step(label: str, n: int = 1):
            nonlocal done
            done += n
            self._prog = (min(done, total), total)
            self._emit(f, "progress", done=min(done, total), total=total, text=label)
        self._prog = (0, total)

        # 0. bookkeeping that needs no network
        for rel in p.forget:
            self.store.delete(fid, rel)
        for rel in p.record:
            self._record_both(f, rel, local, remote)

        # 1. conflicts: rename the local copy, then the remote version takes the name
        for rel in p.conflicts:
            self._check()
            src = os.path.join(f.local, rel)
            new_rel = conflict_name(rel)
            try:
                os.rename(src, os.path.join(f.local, new_rel))
            except PermissionError as e:       # Windows: another program has the file open
                res.errors.append(f"{rel} is in use by another program; Kluis tries again next time ({e})")
                continue
            li = local.pop(rel)
            local[new_rel] = li
            self.store.delete(fid, rel)
            if remote and rel in remote:
                if remote[rel].is_folder:
                    p.mkdir_local.append(rel)
                    self._expand_remote_dir(rel, remote, p)
                else:
                    p.download.append(rel)
            if f.mode != "mirror":
                if li.is_dir:
                    self._expand_local_dir(f, new_rel, local, p)
                else:
                    p.upload.append(new_rel)
            res.conflicts += 1
            self._emit(f, "log", level="warning", text=f"Conflict in {rel}: kept both copies")

        # 2. trash (always recoverable)
        if p.trash_remote:
            for chunk in _chunks(p.trash_remote, BATCH):
                self._check()
                try:
                    self.cli.trash([rjoin(f.remote, r) for r in chunk])
                    for r in chunk:
                        self.store.delete(fid, r)
                    res.trashed += len(chunk)
                    self._emit(f, "log", level="info",
                               text=f"Moved {len(chunk)} item(s) to the Proton Drive trash")
                except CliError as e:
                    self._hold_if_fatal(e)
                    res.errors.append(f"Trash in Proton Drive failed: {e}")
        for rel in p.trash_local:
            self._check()
            try:
                move_to_trash(os.path.join(f.local, rel))
                self.store.delete(fid, rel)
                res.trashed += 1
            except Exception as e:  # noqa: BLE001
                res.errors.append(f"Could not move {rel} to the Trash: {e}")
        if p.trash_local:
            self._emit(f, "log", level="info", text=f"Moved {len(p.trash_local)} item(s) to the Trash")

        # 3. folders
        for rel in sorted(set(p.mkdir_remote), key=lambda r: r.count("/")):
            self._check()
            parent, name = posixpath.split(rel)
            try:
                self.cli.create_folder(rjoin(f.remote, parent), name)
                self.store.put(fid, Entry(rel, True))
            except CliError as e:
                self._hold_if_fatal(e)
                if e.not_found:
                    self.cli.ensure_folder(rjoin(f.remote, rel))
                    self.store.put(fid, Entry(rel, True))
                else:
                    res.errors.append(f"Could not create folder {rel}: {e}")
        for rel in sorted(set(p.mkdir_local), key=lambda r: r.count("/")):
            os.makedirs(os.path.join(f.local, rel), exist_ok=True)
            self.store.put(fid, Entry(rel, True))

        # 4.–6. uploads, then downloads; big items go to the big-items lane (kluis/lane.py) when there is one
        ups, downs = list(p.upload), list(p.download)
        if self.defer is not None:
            ups, up_items = split_big(ups, lambda r: local[r].size if r in local else 0)
            downs, down_items = split_big(downs, lambda r: (remote or {})[r].size if r in (remote or {}) else 0)
            for direction, items in (("up", up_items), ("down", down_items)):
                for it in items:
                    self.defer(f, direction, it, local, remote)
                    res.deferred += 1
                    total -= len(it[2])
            if getattr(self, "_files_paused", False):
                res.waiting += len(ups) + len(downs)
                total -= len(ups) + len(downs)
                ups, downs = [], []
            total = max(total, 1)
            self._prog = (min(done, total), total)
        self.upload_files(f, ups, local, res, step)
        self.download_files(f, downs, local, remote, res, step,
                            os.path.join(f.local, PART_DIR, f"{os.getpid()}-{time.time_ns()}"))

    def upload_files(self, f: FolderPair, rels: list, local: dict, res: SyncResult, step, done_of=None):
        """Uploads `rels`, grouped by folder, then checks each against Proton Drive and records it (invariant 3).
        `done_of(rels)` is told which files are confirmed (the big-items lane counts them)."""
        fid = f.id
        by_dir = defaultdict(list)
        for rel in rels:
            by_dir[posixpath.dirname(rel)].append(rel)
        touched_remote_dirs = set()
        for d in sorted(by_dir, key=lambda r: r.count("/")):
            for chunk in _chunks(by_dir[d], BATCH):
                self._check()
                label = f"Uploading {d or f.name} ({len(chunk)} file(s))"
                self._emit(f, "progress", text=label, **self._progress())
                target = rjoin(f.remote, d)
                t0 = time.monotonic()
                try:
                    summary = self._upload_retry(target, [os.path.join(f.local, r) for r in chunk])
                    self._failures(summary, res, "upload")
                    res.bytes_up += summary.bytes
                    self._emit(f, "bytes", up=summary.bytes, seconds=time.monotonic() - t0)
                except CliError as e:
                    if e.code == 130:
                        raise Cancelled()
                    self._hold_if_fatal(e)
                    res.errors.append(f"Upload to {target} failed: {e}")
                touched_remote_dirs.add(d)
                step(label, len(chunk))

        # verify uploads against Proton Drive and record the new revisions (invariant 3)
        for d in touched_remote_dirs:
            self._check()
            try:
                nodes = {n.name: n for n in self.cli.list(rjoin(f.remote, d))}
            except CliError as e:
                self._hold_if_fatal(e)
                res.errors.append(f"Could not verify {d or f.name}: {e}")
                continue
            confirmed = []
            for rel in by_dir[d]:
                li = local.get(rel)
                n = nodes.get(posixpath.basename(rel))
                if li is None or n is None:
                    continue
                lsha = self._local_sha1(f, rel, li)
                if n.sha1:
                    if n.sha1 != lsha:
                        continue  # not confirmed: retried next time
                elif n.size is not None and n.size != li.size:
                    continue      # Proton reports no SHA-1 (decisions D15): size must match at least
                self.store.put(fid, Entry(rel, False, li.size, li.mtime, n.revision, lsha))
                res.uploaded += 1
                confirmed.append(rel)
            if done_of and confirmed:
                done_of(confirmed)

    def download_files(self, f: FolderPair, rels: list, local: dict, remote: dict | None, res: SyncResult, step,
                       stage_root: str, done_of=None):
        """Downloads `rels` into `stage_root` inside <folder>/.kluis-part, verified, then renamed into place
        (invariant 7)."""
        by_ldir = defaultdict(list)
        for rel in rels:
            by_ldir[posixpath.dirname(rel)].append(rel)
        for d in sorted(by_ldir, key=lambda r: r.count("/")):
            ldir = os.path.join(f.local, d)
            os.makedirs(ldir, exist_ok=True)
            for chunk in _chunks(by_ldir[d], BATCH):
                self._check()
                label = f"Downloading {d or f.name} ({len(chunk)} file(s))"
                self._emit(f, "progress", text=label, **self._progress())
                stage = os.path.join(stage_root, d)
                os.makedirs(stage, exist_ok=True)
                t0 = time.monotonic()
                try:
                    summary = self.cli.download([rjoin(f.remote, r) for r in chunk], stage,
                                                file_strategy="rename", folder_strategy="merge")
                    self._failures(summary, res, "download")
                    res.bytes_down += summary.bytes
                    self._emit(f, "bytes", down=summary.bytes, seconds=time.monotonic() - t0)
                except CliError as e:
                    if e.code == 130:
                        raise Cancelled()
                    self._hold_if_fatal(e)
                    res.errors.append(f"Download into {d or f.name} failed: {e}")
                placed = []
                for rel in chunk:
                    self._check()
                    before = res.downloaded
                    self._place_download(f, rel, stage, local, remote, res)
                    if res.downloaded > before:
                        placed.append(rel)
                if done_of and placed:
                    done_of(placed)
                step(label, len(chunk))

    def _progress(self) -> dict:
        p = getattr(self, "_prog", None)
        return {"done": p[0], "total": p[1]} if p else {}

    # ---------------- helpers ----------------
    def _place_download(self, f, rel, stage, local, remote, res):
        staged = os.path.join(stage, posixpath.basename(rel))
        if not os.path.isfile(staged):
            return
        rn = remote.get(rel) if remote else None
        st = os.stat(staged)
        sha = sha1_file(staged)
        if rn and rn.sha1 and rn.sha1 != sha:
            os.unlink(staged)
            res.errors.append(f"download of {rel} didn't match Proton's checksum; it will be retried")
            return
        target = os.path.join(f.local, rel)
        before = local.get(rel)
        try:
            now = os.stat(target)
        except FileNotFoundError:
            now = None
        changed = now is not None and (before is None or before.is_dir or now.st_size != before.size
                                       or now.st_mtime_ns != before.mtime)
        try:
            if changed:
                # edited on this computer while we downloaded: keep both copies (invariant 2)
                os.rename(target, os.path.join(f.local, conflict_name(rel)))
                res.conflicts += 1
                self._emit(f, "log", level="warning", text=f"Conflict in {rel}: kept both copies")
            os.replace(staged, target)
        except PermissionError as e:           # Windows: another program has the file open
            os.unlink(staged)
            res.errors.append(f"{rel} is in use by another program; Kluis tries again next time ({e})")
            return
        st = os.stat(target)
        li = LocalItem(False, st.st_size, st.st_mtime_ns)
        self.store.store_sha1(target, li.size, li.mtime, sha)
        self.store.put(f.id, Entry(rel, False, li.size, li.mtime, rn.revision if rn else None, sha))
        res.downloaded += 1

    def _upload_retry(self, target: str, paths: list[str]) -> TransferSummary:
        try:
            return self.cli.upload(paths, target)
        except CliError as e:
            if not e.not_found:
                raise
            self.cli.ensure_folder(target)  # the folder was removed in Proton Drive meanwhile
            return self.cli.upload(paths, target)

    def _failures(self, summary: TransferSummary, res: SyncResult, verb: str):
        for fl in summary.failures:
            res.errors.append(f"{verb} failed for {fl.get('name')}: {fl.get('error')}")

    def _record_both(self, f, rel, local, remote):
        li = local.get(rel)
        rn = remote.get(rel) if remote else None
        if li is None:
            return
        if li.is_dir:
            self.store.put(f.id, Entry(rel, True))
        else:
            self.store.put(f.id, Entry(rel, False, li.size, li.mtime,
                                       rn.revision if rn else None, rn.sha1 if rn else None))

    def _expand_local_dir(self, f, new_rel, local, p: Plan):
        root = os.path.join(f.local, new_rel)
        p.mkdir_remote.append(new_rel)
        for dirpath, dirnames, filenames in os.walk(root):
            reld = os.path.relpath(dirpath, f.local).replace(os.sep, "/")
            for d in dirnames:
                p.mkdir_remote.append(posixpath.join(reld, d))
            for fn in filenames:
                rel = posixpath.join(reld, fn)
                st = os.stat(os.path.join(dirpath, fn))
                local[rel] = LocalItem(False, st.st_size, st.st_mtime_ns)
                p.upload.append(rel)

    def _expand_remote_dir(self, rel, remote, p: Plan):
        for r, n in remote.items():
            if r.startswith(rel + "/"):
                (p.mkdir_local if n.is_folder else p.download).append(r)

    def _check(self):
        if self._cancel:
            raise Cancelled()

    def _emit(self, f, kind, **data):
        try:
            self.on_event(f.id, kind, **data)
        except Exception:  # noqa: BLE001 - UI callbacks must never break a sync
            log.exception("event handler failed")


def _chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]

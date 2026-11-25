"""What each side looked like after the last successful sync (one sqlite db for all folders)."""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass

from .paths import STATE_DB, ensure_dirs


@dataclass
class Entry:
    rel: str
    is_dir: bool
    lsize: int | None = None
    lmtime: int | None = None      # ns
    rrev: str | None = None        # remote active revision uid
    sha1: str | None = None        # content hash both sides agreed on


class StateStore:
    def __init__(self, path=STATE_DB):
        ensure_dirs()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._db:
            self._db.execute("""CREATE TABLE IF NOT EXISTS entries(
                folder TEXT, rel TEXT, is_dir INTEGER, lsize INTEGER, lmtime INTEGER,
                rrev TEXT, sha1 TEXT, PRIMARY KEY(folder, rel))""")
            self._db.execute("""CREATE TABLE IF NOT EXISTS photos_down(
                key TEXT PRIMARY KEY, rel TEXT, sha1 TEXT)""")
            self._db.execute("""CREATE TABLE IF NOT EXISTS photos_up(
                path TEXT PRIMARY KEY, size INTEGER, mtime INTEGER)""")
            self._db.execute("""CREATE TABLE IF NOT EXISTS hashes(
                path TEXT PRIMARY KEY, size INTEGER, mtime INTEGER, sha1 TEXT)""")

    def load(self, folder: str) -> dict[str, Entry]:
        with self._lock:
            rows = self._db.execute(
                "SELECT rel,is_dir,lsize,lmtime,rrev,sha1 FROM entries WHERE folder=?", (folder,)).fetchall()
        return {r[0]: Entry(r[0], bool(r[1]), r[2], r[3], r[4], r[5]) for r in rows}

    def put(self, folder: str, e: Entry):
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO entries VALUES(?,?,?,?,?,?,?)",
                             (folder, e.rel, int(e.is_dir), e.lsize, e.lmtime, e.rrev, e.sha1))

    def delete(self, folder: str, rel: str):
        with self._lock, self._db:
            self._db.execute("DELETE FROM entries WHERE folder=? AND (rel=? OR rel LIKE ?)",
                             (folder, rel, rel.replace("%", r"\%") + "/%"))

    def forget_folder(self, folder: str):
        with self._lock, self._db:
            self._db.execute("DELETE FROM entries WHERE folder=?", (folder,))

    # cache of local sha1s so unchanged files are never re-hashed
    def cached_sha1(self, path: str, size: int, mtime: int) -> str | None:
        with self._lock:
            r = self._db.execute("SELECT size,mtime,sha1 FROM hashes WHERE path=?", (path,)).fetchone()
        return r[2] if r and r[0] == size and r[1] == mtime else None

    def store_sha1(self, path: str, size: int, mtime: int, sha1: str):
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO hashes VALUES(?,?,?,?)", (path, size, mtime, sha1))

    # ---------- photos ----------
    def photos_downloaded(self) -> dict[str, str]:
        with self._lock:
            return dict(self._db.execute("SELECT key, rel FROM photos_down").fetchall())

    def photo_downloaded(self, key: str, rel: str, sha1: str | None):
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO photos_down VALUES(?,?,?)", (key, rel, sha1))

    def photo_forget(self, key: str):
        with self._lock, self._db:
            self._db.execute("DELETE FROM photos_down WHERE key=?", (key,))

    def photos_uploaded(self) -> dict[str, tuple[int, int]]:
        with self._lock:
            return {r[0]: (r[1], r[2]) for r in self._db.execute("SELECT path,size,mtime FROM photos_up")}

    def photo_uploaded(self, path: str, size: int, mtime: int):
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO photos_up VALUES(?,?,?)", (path, size, mtime))

    def photos_reset(self):
        with self._lock, self._db:
            self._db.execute("DELETE FROM photos_down")
            self._db.execute("DELETE FROM photos_up")

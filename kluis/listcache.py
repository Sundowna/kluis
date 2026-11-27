"""The last answers from Proton Drive, kept on disk so every tab shows them at once (Walter, 2026-11-27).

Folder lists (Browse, Sync Center), Shared with me, the photo timeline and albums each take 1–5 s to read
through the CLI. A tab shows the kept answer immediately, asks Proton again in the background and quietly
updates when the answer differs ("stale while revalidate"). Kluis's own changes (upload, new folder, rename,
trash) forget the folder they touched, so an action is never followed by an outdated list.

Kept per Proton account in ~/.cache/kluis/lists-<id>.json, mode 600: names, sizes and dates as Proton reports
them, no account email. Never used by the sync engine, which always reads Proton Drive itself.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import time

from gi.repository import GLib

from .ui.common import run_bg


class ListCache:
    VERSION = 1
    MAX_ENTRIES = 3000                  # least recently refreshed lists go first

    def __init__(self, store=None):
        self.store = store              # () -> this account's file, or None (memory only)
        self.entries: dict[str, tuple[float, list]] = {}
        self._loaded_from = None
        self._save_src = 0

    # ---------- disk ----------
    def _load(self):
        path = self.store() if self.store else None
        if path == self._loaded_from:
            return
        self._loaded_from = path
        self.entries = {}
        if not path:
            return
        try:
            with open(path) as fh:
                raw = json.load(fh)
            if raw.get("v") == self.VERSION:
                self.entries = {k: (float(ts), items) for k, (ts, items) in raw.get("lists", {}).items()}
        except (OSError, ValueError, TypeError, AttributeError):
            pass                        # none yet, or unreadable: everything is read fresh

    def _save_soon(self):
        if not self._save_src:
            self._save_src = GLib.timeout_add(2000, self._save)

    def _save(self):
        self._save_src = 0
        path = self._loaded_from
        if not path:
            return False
        if len(self.entries) > self.MAX_ENTRIES:
            keep = sorted(self.entries.items(), key=lambda kv: kv[1][0], reverse=True)[:self.MAX_ENTRIES]
            self.entries = dict(keep)
        try:
            os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
            tmp = path + ".tmp"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as fh:
                json.dump({"v": self.VERSION, "lists": {k: [ts, it] for k, (ts, it) in self.entries.items()}}, fh)
            os.replace(tmp, path)
        except OSError:
            pass
        return False

    # ---------- lists ----------
    def get(self, key, cls):
        """(items, when) of the kept answer, or None. Items are rebuilt as `cls` (a dataclass)."""
        self._load()
        e = self.entries.get(key)
        if not e:
            return None
        names = {f.name for f in dataclasses.fields(cls)}
        try:
            return [cls(**{k: v for k, v in d.items() if k in names}) for d in e[1]], e[0]
        except TypeError:
            return None

    def put(self, key, items):
        self._load()
        self.entries[key] = (time.time(), [dataclasses.asdict(i) for i in items])
        self._save_soon()

    def age(self, key) -> float | None:
        self._load()
        e = self.entries.get(key)
        return time.time() - e[0] if e else None

    def forget(self, key):
        """This list and every list below it (a renamed or trashed folder takes its subfolders along)."""
        self._load()
        for k in [k for k in self.entries if k == key or k.startswith(key.rstrip("/") + "/")]:
            self.entries.pop(k, None)
        self._save_soon()

    def unload(self):
        """Another Proton account is active: the next get() reads that account's own file."""
        self._loaded_from = None
        self.entries = {}


def shared_lists(app) -> ListCache:
    """The one ListCache of this app, kept per Proton account."""
    lc = getattr(app, "list_cache", None)
    if lc is None:
        def store():
            acct = (app.settings.account or "").strip().lower()
            key = hashlib.sha1(acct.encode()).hexdigest()[:12] if acct else "default"
            return os.path.join(GLib.get_user_cache_dir(), "kluis", f"lists-{key}.json")
        lc = ListCache(store)
        app.list_cache = lc
    return lc


def signature(items) -> list:
    """What a view shows of a list, to skip redrawing when Proton's answer is the same as the kept one."""
    return [tuple(sorted(dataclasses.asdict(i).items(), key=lambda kv: kv[0])) for i in items]


def fetch(app, key, cls, work, show, fail):
    """Show the kept answer at once (show(items, kept=True)); ask Proton in the background (work()) and show
    its answer (show(items, kept=False)) unless it is the same. fail(e, kept_shown) when Proton can't answer."""
    lc = shared_lists(app)
    kept = lc.get(key, cls)
    if kept is not None:
        show(kept[0], True)

    def done(items):
        lc.put(key, items)
        if kept is None or signature(items) != signature(kept[0]):
            show(items, False)
        else:
            show(None, False)           # unchanged: the view only drops its "checking…" note

    run_bg(work, done, lambda e: fail(e, kept is not None))
    return kept[1] if kept else None

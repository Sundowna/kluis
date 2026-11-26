"""Proton Photos: keep a local copy of the timeline (and albums), and upload new photos from a folder.

Downloads are one-way and add-only: a photo already saved is never downloaded again, even if you
delete or move the local copy. Photos are fetched by their unique ID, so two different
"IMG_0001.jpg" from two phones both end up on disk ("IMG_0001 (1).jpg").
"""
from __future__ import annotations

import logging
import os
import shutil
import re
from collections import defaultdict
from datetime import datetime
from typing import Callable

from .cli import CliError, PhotoItem, ProtonDriveCli
from .system import is_inside
from .config import PhotoSettings
from .config import PART_DIR
from .engine import GUARD_FILES, GUARD_SHARE, Cancelled, SyncResult, move_to_trash, sha1_file
from .errors import DISK_FULL, HoldError, classify
from .state import StateStore

log = logging.getLogger("kluis.photos")
BATCH = 25
MEDIA_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif", ".tif", ".tiff", ".bmp", ".avif",
             ".dng", ".cr2", ".cr3", ".nef", ".arw", ".orf", ".rw2", ".raf",
             ".mp4", ".mov", ".m4v", ".3gp", ".avi", ".mkv", ".webm"}


def captured_dt(p: PhotoItem) -> datetime | None:
    if not p.captured:
        return None
    try:
        return datetime.fromisoformat(p.captured.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def layout_dir(p: PhotoItem, layout: str) -> str:
    dt = captured_dt(p)
    if layout == "flat":
        return ""
    if dt is None:
        return "Unknown date"
    return f"{dt:%Y}" if layout == "year" else f"{dt:%Y}/{dt:%Y-%m}"


def safe_name(name: str) -> str:
    name = re.sub(r'[/\x00]', "_", name).strip() or "Album"
    return name if name not in (".", "..") else "Album"


class PhotoSync:
    def __init__(self, cli: ProtonDriveCli, store: StateStore, on_event: Callable[..., None] | None = None):
        self.cli = cli
        self.store = store
        self.on_event = on_event or (lambda *a, **k: None)
        self._cancel = False
        self.timeline: list[PhotoItem] = []   # last fetched, newest first
        self.albums: list[PhotoItem] = []

    def cancel(self):
        self._cancel = True
        self.cli.cancel()

    def _check(self):
        if self._cancel:
            raise Cancelled()

    def _emit(self, kind, **data):
        try:
            self.on_event("photos", kind, **data)
        except Exception:  # noqa: BLE001
            log.exception("event handler failed")

    # ---------------- public ----------------
    def sync(self, ps: PhotoSettings) -> SyncResult:
        self._cancel = False
        res = SyncResult()
        try:
            if ps.download and ps.download_dir:
                self._download_timeline(ps, res)
                if ps.albums:
                    self._download_albums(ps, res)
            if ps.upload and ps.upload_dir:
                self._upload(ps, res)
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
            if classify(e):
                res.status, res.hold_kind, res.message = "hold", classify(e), str(e)
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
            if ps.download_dir:
                shutil.rmtree(os.path.join(ps.download_dir, PART_DIR), ignore_errors=True)
        if res.errors:
            res.status = "error"
            res.message = f"{len(res.errors)} problem(s): {res.errors[0]}"
        else:
            parts = []
            if res.downloaded:
                parts.append(f"↓ {res.downloaded} photo(s) saved")
            if res.uploaded:
                parts.append(f"↑ {res.uploaded} added to Proton Photos")
            if res.trashed:
                parts.append(f"{res.trashed} moved to Trash")
            res.message = ", ".join(parts) or "Up to date"
        return res

    # ---------------- download ----------------
    def _download_timeline(self, ps: PhotoSettings, res: SyncResult):
        self._emit("phase", text="Reading your Proton Photos timeline…")
        self.timeline = self.cli.photo_timeline()
        ps.count = len(self.timeline)
        have = self.store.photos_downloaded()
        todo = [p for p in self.timeline if p.uid not in have and p.type == "photo"]
        self._fetch(ps.download_dir, todo, lambda p: layout_dir(p, ps.layout), "", res)

        if ps.remove_deleted:
            live = {p.uid for p in self.timeline}
            gone = [(k, r) for k, r in have.items() if "/" not in k and k not in live]
            existing = [(k, r) for k, r in gone if os.path.exists(os.path.join(ps.download_dir, r))]
            base = max(1, sum(1 for k in have if "/" not in k))
            if len(existing) > GUARD_FILES or len(existing) > GUARD_SHARE * base:
                # §7.8: far more than usual; keep every copy and say so
                res.pending_trash = len(existing)
                self._emit("log", level="warning",
                           text=f"Kept {len(existing)} photos that are no longer in Proton Photos",
                           )
                return
            for key, rel in gone:   # album entries are handled with their album
                path = os.path.join(ps.download_dir, rel)
                if os.path.exists(path):
                    move_to_trash(path)
                    res.trashed += 1
                self.store.photo_forget(key)

    def _download_albums(self, ps: PhotoSettings, res: SyncResult):
        self._emit("phase", text="Reading your albums…")
        self.albums = [a for a in self.cli.albums() if a.type == "album"]
        have = self.store.photos_downloaded()
        for a in self.albums:
            self._check()
            photos = self.cli.album_photos(a.uid)
            prefix = f"{a.uid}/"
            todo = [p for p in photos if prefix + p.uid not in have]
            folder = os.path.join("Albums", safe_name(a.name))
            self._fetch(ps.download_dir, todo, lambda p, f=folder: f, prefix, res)

    def _fetch(self, root: str, todo: list[PhotoItem], dir_for, key_prefix: str, res: SyncResult):
        if not todo:
            return
        groups: dict[str, list[PhotoItem]] = defaultdict(list)
        for p in todo:
            groups[dir_for(p)].append(p)
        total, done = len(todo), 0
        for rel_dir in sorted(groups, reverse=True):   # newest months first
            items = groups[rel_dir]
            abs_dir = os.path.join(root, rel_dir)
            os.makedirs(abs_dir, exist_ok=True)
            # already on disk with identical content (e.g. state was reset): just remember it
            on_disk = self._hash_dir(abs_dir) if any(p.sha1 for p in items) else {}
            pending = []
            for p in items:
                fn = on_disk.pop(p.sha1, None) if p.sha1 else None
                if fn:
                    self.store.photo_downloaded(key_prefix + p.uid, os.path.join(rel_dir, fn), p.sha1)
                else:
                    pending.append(p)
            for i in range(0, len(pending), BATCH):
                self._check()
                chunk = pending[i:i + BATCH]
                label = f"Saving photos to {rel_dir or os.path.basename(root)} ({done + len(chunk)}/{total})"
                self._emit("progress", done=done, total=total, text=label)
                stage = os.path.join(root, PART_DIR, f"{os.getpid()}-{i}")
                os.makedirs(stage, exist_ok=True)
                try:
                    summary = self.cli.photo_download([p.uid for p in chunk], stage, "rename")
                    for fl in summary.failures:
                        res.errors.append(f"Photo {fl.get('name')}: {fl.get('error')}")
                except CliError as e:
                    if e.code == 130:
                        raise Cancelled()
                    if classify(e):
                        raise HoldError(classify(e), str(e))
                    res.errors.append(f"Saving photos into {rel_dir or root} failed: {e}")
                new = self._place(stage, abs_dir)
                res.downloaded += self._match(abs_dir, rel_dir, chunk, new, key_prefix)
                done += len(chunk)
        self._emit("progress", done=total, total=total, text="Photos saved")

    @staticmethod
    def _place(stage: str, abs_dir: str) -> list[str]:
        """Move complete downloads from the staging folder into place without overwriting anything."""
        out = []
        for fn in sorted(os.listdir(stage)):
            src = os.path.join(stage, fn)
            if not os.path.isfile(src):
                continue
            stem, ext = os.path.splitext(fn)
            name, i = fn, 1
            while os.path.exists(os.path.join(abs_dir, name)):
                name = f"{stem} ({i}){ext}"
                i += 1
            os.replace(src, os.path.join(abs_dir, name))
            out.append(name)
        shutil.rmtree(stage, ignore_errors=True)
        return out

    def _hash_dir(self, abs_dir) -> dict[str, str]:
        out = {}
        for fn in sorted(os.listdir(abs_dir)):
            path = os.path.join(abs_dir, fn)
            try:
                st = os.stat(path)
            except OSError:
                continue
            if not os.path.isfile(path):
                continue
            h = self.store.cached_sha1(path, st.st_size, st.st_mtime_ns)
            if not h:
                h = sha1_file(path)
                self.store.store_sha1(path, st.st_size, st.st_mtime_ns, h)
            out.setdefault(h, fn)
        return out

    def _match(self, abs_dir, rel_dir, chunk: list[PhotoItem], new_files: list[str], key_prefix: str) -> int:
        """Work out which new file belongs to which photo: by content hash, then by name."""
        by_sha = defaultdict(list)
        for p in chunk:
            by_sha[p.sha1].append(p)
        matched, left = 0, []
        for fn in new_files:
            path = os.path.join(abs_dir, fn)
            if not os.path.isfile(path):
                continue
            h = sha1_file(path)
            cands = by_sha.get(h)
            if cands:
                p = cands.pop(0)
                self.store.photo_downloaded(key_prefix + p.uid, os.path.join(rel_dir, fn), h)
                matched += 1
            else:
                left.append((fn, h))
        unmatched = [p for ps_ in by_sha.values() for p in ps_]
        for fn, h in left:   # no hash from Proton: fall back to the file name stem
            stem = os.path.splitext(fn)[0].split(" (")[0]
            p = next((q for q in unmatched if os.path.splitext(q.name)[0] == stem), None)
            if p:
                unmatched.remove(p)
                self.store.photo_downloaded(key_prefix + p.uid, os.path.join(rel_dir, fn), h)
                matched += 1
        return matched

    # ---------------- upload ----------------
    def _upload(self, ps: PhotoSettings, res: SyncResult):
        self._emit("phase", text="Looking for new photos to add…")
        done = self.store.photos_uploaded()
        skip_root = ps.download_dir if ps.download and ps.download_dir else None
        todo = []
        for dirpath, dirnames, filenames in os.walk(ps.upload_dir):
            self._check()
            if skip_root and is_inside(dirpath, skip_root):
                dirnames[:] = []
                continue  # never re-upload the downloaded copies
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                if fn.startswith(".") or os.path.splitext(fn)[1].lower() not in MEDIA_EXT:
                    continue
                path = os.path.join(dirpath, fn)
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                if done.get(path) == (st.st_size, st.st_mtime_ns):
                    continue
                todo.append((path, st.st_size, st.st_mtime_ns))
        total = len(todo)
        for i in range(0, total, BATCH):
            self._check()
            chunk = todo[i:i + BATCH]
            self._emit("progress", done=i, total=total, text=f"Adding photos to Proton Photos ({i + len(chunk)}/{total})")
            try:
                summary = self.cli.photo_upload([c[0] for c in chunk], "skip")
            except CliError as e:
                if e.code == 130:
                    raise Cancelled()
                if classify(e):
                    raise HoldError(classify(e), str(e))
                res.errors.append(f"Adding photos failed: {e}")
                continue
            ps.added += summary.transferred
            ps.skipped += summary.skipped
            failed = {fl.get("name") for fl in summary.failures}
            for fl in summary.failures:
                res.errors.append(f"Photo {fl.get('name')}: {fl.get('error')}")
            for path, size, mtime in chunk:
                if os.path.basename(path) not in failed:
                    self.store.photo_uploaded(path, size, mtime)
            res.uploaded += summary.transferred

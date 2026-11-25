"""Square previews for photos and videos.

Local files: the desktop's own thumbnailers (the ones Nemo uses: images, HEIC, RAW, videos via
ffmpegthumbnailer) and its shared cache in ~/.cache/thumbnails, so previews Nemo already made are reused.
Photos only in Proton: the CLI has no thumbnail command, so each photo is fetched once, a small
preview is kept in ~/.cache/kluis/previews and the full file is deleted again.
"""
from __future__ import annotations

import hashlib
import logging
import os
import queue
import shutil
import subprocess
import tempfile
import threading
from collections import OrderedDict

import gi
from gi.repository import GdkPixbuf, Gio, GLib

from .engine import sha1_file

log = logging.getLogger("kluis.thumbs")
TILE = 128
PREVIEW_PX = 256
REMOTE_MAX_BYTES = 60 * 1024 * 1024   # don't pull huge videos just for a preview
REMOTE_BATCH = 8
PREVIEW_DIR = os.path.join(GLib.get_user_cache_dir(), "kluis", "previews")


def _desktop_factory():
    for ns in ("CinnamonDesktop", "GnomeDesktop"):
        try:
            gi.require_version(ns, "3.0")
            mod = __import__("gi.repository." + ns, fromlist=[ns])
            return mod.DesktopThumbnailFactory.new(mod.DesktopThumbnailSize.LARGE)
        except (ValueError, ImportError, AttributeError):
            continue
    return None


def square(pb: GdkPixbuf.Pixbuf, size: int = TILE) -> GdkPixbuf.Pixbuf:
    pb = pb.apply_embedded_orientation() or pb
    w, h = pb.get_width(), pb.get_height()
    s = size / min(w, h)
    sw, sh = max(size, round(w * s)), max(size, round(h * s))
    pb = pb.scale_simple(sw, sh, GdkPixbuf.InterpType.BILINEAR)
    return pb.new_subpixbuf((sw - size) // 2, (sh - size) // 2, size, size).copy()


class PreviewMaker:
    def __init__(self):
        self.factory = _desktop_factory()
        self.ffmpegthumbnailer = shutil.which("ffmpegthumbnailer")
        self.ffmpeg = shutil.which("ffmpeg")
        self._lock = threading.Lock()   # the desktop factory is not meant for parallel use
        log.info("previews: factory=%s ffmpegthumbnailer=%s ffmpeg=%s", bool(self.factory),
                 bool(self.ffmpegthumbnailer), bool(self.ffmpeg))

    @property
    def can_video(self) -> bool:
        return bool(self.factory or self.ffmpegthumbnailer or self.ffmpeg)

    def make(self, path: str, use_cache: bool = True) -> GdkPixbuf.Pixbuf | None:
        """Best-effort large thumbnail (not yet squared) for an image or video file."""
        try:
            st = os.stat(path)
        except OSError:
            return None
        mime = Gio.content_type_guess(path, None)[0] or ""
        mime = Gio.content_type_get_mime_type(mime) or mime
        is_video = mime.startswith("video/")
        if self.factory:
            uri = Gio.File.new_for_path(path).get_uri()
            mtime = int(st.st_mtime)
            with self._lock:
                try:
                    cached = self.factory.lookup(uri, mtime) if use_cache else None
                    if cached:
                        return GdkPixbuf.Pixbuf.new_from_file(cached)
                    if self.factory.can_thumbnail(uri, mime, mtime):
                        pb = self.factory.generate_thumbnail(uri, mime)
                        if pb:
                            if use_cache:   # shared with Nemo; skip for temporary files
                                self.factory.save_thumbnail(pb, uri, mtime)
                            return pb
                except (GLib.Error, TypeError) as e:
                    log.debug("desktop thumbnailer failed for %s: %s", path, e)
        if is_video:
            return self._video(path)
        try:
            return GdkPixbuf.Pixbuf.new_from_file_at_scale(path, PREVIEW_PX * 2, PREVIEW_PX * 2, True)
        except GLib.Error:
            return None

    def _video(self, path):
        out = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
        try:
            if self.ffmpegthumbnailer:
                cmd = [self.ffmpegthumbnailer, "-i", path, "-o", out, "-s", str(PREVIEW_PX), "-t", "10%"]
            elif self.ffmpeg:
                cmd = [self.ffmpeg, "-v", "error", "-y", "-ss", "1", "-i", path, "-frames:v", "1",
                       "-vf", f"scale={PREVIEW_PX}:-1", out]
            else:
                return None
            subprocess.run(cmd, capture_output=True, timeout=60)
            if os.path.getsize(out) > 0:
                return GdkPixbuf.Pixbuf.new_from_file(out)
        except (OSError, subprocess.SubprocessError, GLib.Error) as e:
            log.debug("video preview failed for %s: %s", path, e)
        finally:
            try:
                os.unlink(out)
            except OSError:
                pass
        return None


def preview_path(uid: str) -> str:
    return os.path.join(PREVIEW_DIR, hashlib.sha1(uid.encode()).hexdigest() + ".png")


class Thumbnailer:
    """Two background workers: one for local files, one that fetches photos from Proton for previews."""

    def __init__(self, cli, on_ready):
        self.cli = cli
        self.on_ready = on_ready            # called on the main thread: on_ready(key, pixbuf)
        self.maker = PreviewMaker()
        self.cache: OrderedDict[str, GdkPixbuf.Pixbuf] = OrderedDict()
        self.local_q: queue.Queue = queue.Queue()
        self.remote_q: queue.Queue = queue.Queue()
        self.remote_enabled = True
        self.generation = 0
        self.failed: set[str] = set()
        os.makedirs(PREVIEW_DIR, exist_ok=True)
        threading.Thread(target=self._local_worker, daemon=True).start()
        threading.Thread(target=self._remote_worker, daemon=True).start()

    def reset(self):
        """Forget queued work (the gallery was re-rendered)."""
        self.generation += 1
        for q in (self.local_q, self.remote_q):
            while not q.empty():
                try:
                    q.get_nowait()
                except queue.Empty:
                    break

    def request(self, photo, local_path: str | None):
        key = photo.uid
        if key in self.cache:
            self._deliver(key, self.cache[key])
            return
        if local_path and os.path.exists(local_path):
            self.local_q.put((self.generation, key, local_path))
        elif os.path.exists(preview_path(key)):
            self.local_q.put((self.generation, key, preview_path(key)))
        elif self.remote_enabled and key not in self.failed and (photo.size or 0) <= REMOTE_MAX_BYTES:
            self.remote_q.put((self.generation, photo))

    def _deliver(self, key, pb):
        GLib.idle_add(lambda: (self.on_ready(key, pb), False)[1])

    def _store(self, key, pb):
        pb = square(pb)
        self.cache[key] = pb
        if len(self.cache) > 2000:
            self.cache.popitem(last=False)
        self._deliver(key, pb)

    def _local_worker(self):
        while True:
            gen, key, path = self.local_q.get()
            if gen != self.generation:
                continue
            pb = self.maker.make(path) if not path.startswith(PREVIEW_DIR) else self._load(path)
            if pb:
                self._store(key, pb)

    @staticmethod
    def _load(path):
        try:
            return GdkPixbuf.Pixbuf.new_from_file(path)
        except GLib.Error:
            return None

    def _remote_worker(self):
        while True:
            batch = [self.remote_q.get()]
            while len(batch) < REMOTE_BATCH:
                try:
                    batch.append(self.remote_q.get(timeout=0.3))
                except queue.Empty:
                    break
            photos = [p for g, p in batch if g == self.generation and not os.path.exists(preview_path(p.uid))]
            if not photos:
                continue
            tmp = tempfile.mkdtemp(prefix="kluis-preview-")
            try:
                self.cli.photo_download([p.uid for p in photos], tmp, "rename")
            except Exception as e:  # noqa: BLE001 - previews are best effort
                log.info("preview download failed: %s", e)
            try:
                files = [os.path.join(tmp, f) for f in os.listdir(tmp)]
                by_sha = {}
                for f in files:
                    try:
                        by_sha.setdefault(sha1_file(f), f)
                    except OSError:
                        pass
                for p in photos:
                    f = by_sha.get(p.sha1) if p.sha1 else None
                    if not f:
                        f = next((x for x in files if os.path.basename(x) == p.name), None)
                    pb = self.maker.make(f, use_cache=False) if f else None
                    if not pb:
                        self.failed.add(p.uid)
                        continue
                    big = square(pb, PREVIEW_PX)
                    big.savev(preview_path(p.uid), "png", [], [])
                    self._store(p.uid, pb)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)   # keep only the small preview

"""Thin, thread-safe wrapper around the official Proton Drive CLI (`proton-drive`).

Command syntax and JSON shapes follow Proton's source (ProtonDriveApps/sdk, cli/):
  filesystem list <path> --json            -> JSON array of NodeEntity objects
  filesystem upload <local...> <parent>    -f create-new-revision|rename|replace|skip
                                           -d merge|rename|replace|skip
  filesystem download <remote...> <dir>    -f rename|remove|skip  -d merge|rename|remove|skip
  filesystem create-folder <parent> <name>
  filesystem trash <path...>
  auth login --json                        -> prints {"signInUrl": ...}, waits for browser sign-in
Transfers print a summary object: {transferredItems, transferredBytes, skippedItems, failedItems, failures}.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import posixpath
import shutil
import subprocess
import threading
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .paths import BIN_DIR, CLI_NAME
from .system import IS_WINDOWS, bind_to_kluis, cli_popen_kwargs, command_for

log = logging.getLogger("kluis.cli")

DOWNLOAD_NAME = ".proton-drive.download" + (".exe" if IS_WINDOWS else "")   # Windows runs only .exe files
VERSION_JSON_URL = "https://proton.me/download/drive/cli/version.json"
DOWNLOAD_PAGE_URL = "https://proton.me/download/drive/cli/index.html"
NOT_LOGGED_IN_MARKERS = ("need to login", "need to log in", "not logged in", "login first")

# A PROTON_DRIVE_CACHE_DIR the user set themselves stays the first account's cache.
_USER_CACHE_DIR = os.environ.get("PROTON_DRIVE_CACHE_DIR", "")

# One CLI process at a time per ProtonDriveCli. The CLI itself copes with several processes (its cache is
# SQLite in WAL mode with a busy timeout; only one process holds events.lock and listens for events), so the
# big-items lane (kluis/lane.py) runs its own copy next to the normal sync: sibling().
_CLI_LOCK = threading.RLock()


class CliError(Exception):
    def __init__(self, message: str, code: int = 1, stderr: str = ""):
        super().__init__(message)
        self.code = code
        self.stderr = stderr

    @property
    def not_logged_in(self) -> bool:
        text = (str(self) + " " + self.stderr).lower()
        return any(m in text for m in NOT_LOGGED_IN_MARKERS)

    @property
    def already_exists(self) -> bool:
        text = (str(self) + " " + self.stderr).lower()
        return "already exists" in text or "same name" in text

    @property
    def not_found(self) -> bool:
        text = (str(self) + " " + self.stderr).lower()
        return "not found" in text or "does not exist" in text


class CliMissing(CliError):
    pass


@dataclass
class RemoteNode:
    name: str
    type: str  # "file" | "folder" | others (album, ...)
    uid: str = ""
    size: int | None = None
    revision: str = ""
    sha1: str | None = None
    modified: str = ""  # ISO string
    shared: bool = False
    media_type: str = ""
    role: str = ""          # viewer | editor | admin (shares)
    shared_by: str = ""     # Shared with me: who shared it
    shared_on: str = ""     # Shared with me: invite time (ISO)
    trashed: str = ""       # /trash: trash time (ISO)
    parent_uid: str = ""

    @property
    def is_folder(self) -> bool:
        return self.type == "folder"

    @classmethod
    def from_json(cls, d: dict) -> "RemoteNode":
        name = d.get("name")
        if isinstance(name, dict):
            name = name.get("value") if name.get("ok", True) else ""
        rev = d.get("activeRevision") or {}
        digests = rev.get("claimedDigests") or {}
        mem = d.get("membership") or {}
        by = mem.get("sharedBy") or {}
        if isinstance(by, dict):
            by = by.get("value") if by.get("ok", True) else ""
        return cls(
            name=name or d.get("path") or d.get("uid", "?"),
            # a computer under /devices ("type": "Windows", "Linux", …) opens like a folder: /devices/<name>/…
            type="folder" if "rootFolderUid" in d else d.get("type", "folder" if "path" in d else "file"),
            uid=d.get("uid", ""),
            size=rev.get("claimedSize", d.get("totalStorageSize")),
            revision=rev.get("uid", ""),
            sha1=digests.get("sha1"),
            modified=rev.get("claimedModificationTime") or d.get("modificationTime") or "",
            shared=bool(d.get("isShared")),
            media_type=d.get("mediaType") or "",
            role=mem.get("role") or d.get("directRole") or "",
            shared_by=by or "",
            shared_on=mem.get("inviteTime") or "",
            trashed=d.get("trashTime") or "",
            parent_uid=d.get("parentUid") or "",
        )


@dataclass
class PhotoItem:
    uid: str
    name: str
    type: str = "photo"          # photo | album
    size: int | None = None
    sha1: str | None = None
    captured: str = ""           # ISO capture time (falls back to creation time)
    media_type: str = ""
    count: int = 0               # albums: number of photos

    @classmethod
    def from_json(cls, d: dict) -> "PhotoItem":
        n = RemoteNode.from_json(d)
        photo = d.get("photo") or {}
        album = d.get("album") or {}
        return cls(uid=n.uid, name=n.name, type=d.get("type", "photo"), size=n.size, sha1=n.sha1,
                   captured=photo.get("captureTime") or d.get("creationTime") or n.modified or "",
                   media_type=n.media_type, count=album.get("photoCount", 0))

    @property
    def is_video(self) -> bool:
        return self.media_type.startswith("video/")


@dataclass
class TransferSummary:
    transferred: int = 0
    bytes: int = 0
    skipped: int = 0
    failed: int = 0
    failures: list = field(default_factory=list)

    @classmethod
    def from_json(cls, d: dict | None) -> "TransferSummary":
        d = d or {}
        return cls(
            transferred=d.get("transferredItems", 0),
            bytes=d.get("transferredBytes", 0),
            skipped=d.get("skippedItems", 0),
            failed=d.get("failedItems", 0),
            failures=d.get("failures", []) or [],
        )

    def add(self, other: "TransferSummary"):
        self.transferred += other.transferred
        self.bytes += other.bytes
        self.skipped += other.skipped
        self.failed += other.failed
        self.failures.extend(other.failures)


def rjoin(*parts: str) -> str:
    """Join remote path parts (always POSIX)."""
    p = posixpath.join(*[x for x in parts if x])
    return posixpath.normpath(p) if p else "/"


def _last_json(stdout: str):
    """The CLI prints one JSON document per command; take the last complete one."""
    text = stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    dec = json.JSONDecoder()
    found, i = None, 0
    while i < len(text):
        j = min([k for k in (text.find("{", i), text.find("[", i)) if k != -1], default=-1)
        if j == -1:
            break
        try:
            obj, end = dec.raw_decode(text, j)
            found, i = obj, end
        except json.JSONDecodeError:
            i = j + 1
    return found


def find_cli(configured: str | None = None) -> str | None:
    candidates = []
    if configured:
        candidates.append(os.path.expanduser(configured))
    which = shutil.which("proton-drive")
    if which:
        candidates.append(which)
    candidates += [str(BIN_DIR / CLI_NAME), str(Path.home() / "Downloads" / CLI_NAME)]
    if not IS_WINDOWS:
        candidates += ["/usr/local/bin/proton-drive", "/opt/proton-drive/proton-drive"]
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def platform_key() -> str:
    """The "Platform" of Proton's version.json: linux/x64, linux/x64-musl, windows/x64, windows/arm64, …"""
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("aarch64", "arm64") else "x64"
    if IS_WINDOWS:
        return f"windows/{arch}"
    try:
        musl = "musl" in subprocess.run(["ldd", "--version"], capture_output=True, text=True,
                                        stdin=subprocess.DEVNULL).stdout.lower()
    except Exception:
        musl = False
    return f"linux/{arch}{'-musl' if musl else ''}"


class ChecksumMismatch(CliError):
    pass


class IncompatibleCli(CliError):
    pass


def _manifest_url() -> str:
    # Tests point Kluis at a local manifest; only honoured in test mode, never in a normal run.
    if os.environ.get("KLUIS_TEST") == "1" and os.environ.get("KLUIS_TEST_MANIFEST"):
        return os.environ["KLUIS_TEST_MANIFEST"]
    return VERSION_JSON_URL


def _official(url: str) -> bool:
    if os.environ.get("KLUIS_TEST") == "1" and url.startswith(("file://", "http://127.0.0.1")):
        return True
    return url.startswith("https://proton.me/")


def fetch_latest_release(timeout: int = 15) -> dict | None:
    """Returns {"version", "url", "sha512"} for this machine from Proton's official version.json."""
    req = urllib.request.Request(_manifest_url(), headers={"User-Agent": "kluis"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        manifest = json.load(r)
    key = platform_key()
    for rel in manifest.get("Releases", []):
        if rel.get("CategoryName", "Stable") != "Stable":
            continue
        for f in rel.get("Files", []):
            if f.get("Platform") == key:
                url = f.get("Url", "")
                if url.startswith("/"):
                    url = "https://proton.me" + url
                return {"version": rel.get("Version"), "url": url, "sha512": (f.get("Sha512CheckSum") or "").lower()}
    return None


def download_cli(progress: Callable[[int, int], None] | None = None, dest_dir: Path = BIN_DIR,
                 verify: Callable[[str], tuple[bool, list]] | None = None, rel: dict | None = None) -> str:
    """Download the official CLI, verify its SHA-512 against version.json, optionally run the
    capability self-test on it, and only then switch to it atomically (os.replace)."""
    rel = rel or fetch_latest_release()
    if not rel or not _official(rel["url"]) or not rel.get("sha512"):
        raise CliError("Could not find an official Proton Drive CLI build for this computer.")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp = dest_dir / DOWNLOAD_NAME
    h = hashlib.sha512()
    req = urllib.request.Request(rel["url"], headers={"User-Agent": "kluis"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as out:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                out.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if h.hexdigest() != rel["sha512"]:
        tmp.unlink(missing_ok=True)
        raise ChecksumMismatch("The download didn't match Proton's checksum, so it was deleted. Try again.")
    os.chmod(tmp, 0o755)
    if verify:
        ok, problems = verify(str(tmp))
        if not ok:
            tmp.unlink(missing_ok=True)
            raise IncompatibleCli("Proton changed its Drive tool. Kluis needs an update for it.",
                                  stderr="; ".join(problems))
    dest = dest_dir / CLI_NAME
    try:
        os.replace(tmp, dest)
    except PermissionError:
        if not IS_WINDOWS:
            raise
        # Windows can't overwrite a program that is running, but it can rename it out of the way
        old = dest_dir / (CLI_NAME + ".old")
        try:
            old.unlink(missing_ok=True)
        except OSError:
            old = dest_dir / f"{CLI_NAME}.{os.getpid()}.old"
        os.replace(dest, old)
        os.replace(tmp, dest)
    return str(dest)


def cli_version_of(text: str) -> str:
    """'Proton Drive CLI cli-drive@0.9.0+756…' -> '0.9.0'"""
    import re
    m = re.search(r"cli-drive@([0-9][0-9A-Za-z.\-]*)", text or "")
    return m.group(1) if m else ""


class ProtonDriveCli:
    def __init__(self, path: str | None, skip_thumbnails: bool = False, lock=None):
        self.path = path
        self.skip_thumbnails = skip_thumbnails
        self._lock = lock or _CLI_LOCK
        self._current: subprocess.Popen | None = None
        self._cancelled = False
        self._cache_dir = ""

    @property
    def cache_dir(self) -> str:
        """Per Proton account (kluis/accounts.py); "" = the CLI's own default. Set in os.environ too, so the
        capability self-test and every other CLI process Kluis starts uses the same account's cache."""
        return self._cache_dir

    @cache_dir.setter
    def cache_dir(self, path: str):
        self._cache_dir = path or ""
        if path:
            os.makedirs(path, mode=0o700, exist_ok=True)
            os.environ["PROTON_DRIVE_CACHE_DIR"] = path
        elif _USER_CACHE_DIR:
            os.environ["PROTON_DRIVE_CACHE_DIR"] = _USER_CACHE_DIR
        else:
            os.environ.pop("PROTON_DRIVE_CACHE_DIR", None)

    def sibling(self) -> "ProtonDriveCli":
        """Another CLI for the same account that runs next to this one (its own lock)."""
        other = ProtonDriveCli(self.path, self.skip_thumbnails, lock=threading.RLock())
        other._cache_dir = self._cache_dir
        return other

    def env(self) -> dict:
        env = dict(os.environ)
        env.setdefault("PROTON_DRIVE_LOG_LEVEL", "INFO")
        return env

    # ---------- plumbing ----------
    def _require(self):
        if not self.path or not os.path.exists(self.path):
            raise CliMissing("The Proton Drive CLI was not found.")

    def run(self, args: list[str], json_out: bool = True, timeout: float | None = None,
            ok_codes: Iterable[int] = (0,)):
        self._require()
        cmd = [*command_for(self.path), *args] + (["--json"] if json_out else [])
        log.debug("run %s", cmd)
        env = self.env()
        with self._lock:
            self._cancelled = False
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                    env=env, **cli_popen_kwargs())
            bind_to_kluis(proc)
            self._current = proc
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, err = proc.communicate()
                raise CliError("The Proton Drive CLI timed out.", 124, err)
            finally:
                self._current = None
        if self._cancelled:
            raise CliError("Cancelled", 130, err)
        data = _last_json(out) if json_out else out
        if proc.returncode not in ok_codes:
            msg = (err or "").strip().splitlines()
            msg = [m for m in msg if m.strip() and not m.startswith("=====")]
            e = CliError(msg[-1] if msg else f"proton-drive exited with code {proc.returncode}",
                         proc.returncode, err)
            e.stdout = out
            raise e
        return data

    def cancel(self):
        self._cancelled = True
        p = self._current
        if p and p.poll() is None:
            p.terminate()

    # ---------- account ----------
    def version(self) -> str:
        out = self.run(["version"], json_out=False, timeout=30)
        first = (out or "").strip().splitlines()
        return first[0].replace("Proton Drive CLI", "").strip() if first else "?"

    def is_logged_in(self) -> bool:
        try:
            self.run(["filesystem", "list", "/"], timeout=60)
            return True
        except CliMissing:
            raise
        except CliError as e:
            if e.not_logged_in:
                return False
            raise

    def login(self, on_url: Callable[[str], None]) -> None:
        """Starts browser sign-in. Blocks until finished. The CLI opens the browser itself."""
        self._require()
        proc = subprocess.Popen([*command_for(self.path), "auth", "login", "--json"], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                errors="replace", env=self.env(), **cli_popen_kwargs())
        bind_to_kluis(proc)
        self._current = proc
        try:
            for line in proc.stdout:
                obj = _last_json(line)
                if isinstance(obj, dict) and obj.get("signInUrl"):
                    on_url(obj["signInUrl"])
            err = proc.stderr.read()
            proc.wait()
        finally:
            self._current = None
        if proc.returncode != 0:
            raise CliError((err or "Sign-in failed").strip().splitlines()[-1], proc.returncode, err)

    def logout(self):
        self.run(["auth", "logout"], json_out=False, timeout=60)

    # ---------- filesystem ----------
    def list(self, path: str) -> list[RemoteNode]:
        data = self.run(["filesystem", "list", path], timeout=300) or []
        return [RemoteNode.from_json(d) for d in data if isinstance(d, dict)]

    def info(self, path: str) -> dict:
        return self.run(["filesystem", "info", path], timeout=120) or {}

    def create_folder(self, parent: str, name: str, exist_ok: bool = True):
        try:
            return self.run(["filesystem", "create-folder", parent, name], timeout=120)
        except CliError as e:
            if exist_ok and (e.already_exists or (not e.not_found and self._has_folder(parent, name))):
                return None
            raise

    def _has_folder(self, parent: str, name: str) -> bool:
        try:
            return any(n.name == name and n.is_folder for n in self.list(parent))
        except CliError:
            return False

    def ensure_folder(self, path: str):
        """Create every missing folder along `path` (e.g. /my-files/a/b)."""
        parts = [p for p in path.strip("/").split("/") if p]
        if len(parts) <= 1:
            return
        cur = "/" + parts[0]
        for name in parts[1:]:
            self.create_folder(cur, name)
            cur = rjoin(cur, name)

    def upload(self, local_paths: list[str], remote_parent: str, file_strategy="create-new-revision",
               folder_strategy="merge") -> TransferSummary:
        args = ["filesystem", "upload", *local_paths, remote_parent,
                "--file-conflict-strategy", file_strategy, "--folder-conflict-strategy", folder_strategy]
        if self.skip_thumbnails:
            args.append("--skip-thumbnails")
        return self._transfer(args)

    def download(self, remote_paths: list[str], local_dir: str, file_strategy="remove",
                 folder_strategy="merge") -> TransferSummary:
        args = ["filesystem", "download", *remote_paths, local_dir,
                "--file-conflict-strategy", file_strategy, "--folder-conflict-strategy", folder_strategy]
        return self._transfer(args)

    def _transfer(self, args) -> TransferSummary:
        try:
            return TransferSummary.from_json(self.run(args))
        except CliError as e:
            # Failed items still print a summary; exit code is 1 then.
            summary = _last_json(getattr(e, "stdout", "") or "")
            if summary:
                return TransferSummary.from_json(summary)
            raise

    # ---------- photos ----------
    def photo_timeline(self) -> list["PhotoItem"]:
        data = self.run(["photo", "timeline", "--load-details"], timeout=1800) or []
        return [PhotoItem.from_json(d) for d in data if isinstance(d, dict) and "missingUid" not in d]

    def albums(self) -> list["PhotoItem"]:
        data = self.run(["album", "list"], timeout=600) or []
        return [PhotoItem.from_json(d) for d in data if isinstance(d, dict)]

    def album_photos(self, album_uid: str) -> list["PhotoItem"]:
        data = self.run(["album", "photos", f"/albums/{album_uid}", "--load-details"], timeout=1800) or []
        return [PhotoItem.from_json(d) for d in data if isinstance(d, dict) and "missingUid" not in d]

    def photo_download(self, uids: list[str], local_dir: str, strategy: str = "rename") -> TransferSummary:
        return self._transfer(["photo", "download", *[f"/photos/{u}" for u in uids], local_dir,
                               "--conflict-strategy", strategy])

    def photo_upload(self, local_paths: list[str], strategy: str = "skip") -> TransferSummary:
        """Adds files to the Photos timeline. Identical photos already there are skipped."""
        return self._transfer(["photo", "upload", *local_paths, "--conflict-strategy", strategy])

    def trash(self, paths: list[str]):
        return self.run(["filesystem", "trash", *paths], timeout=300)

    def list_trash(self) -> list[RemoteNode]:
        return self.list("/trash")

    @staticmethod
    def trash_path(name: str) -> str:
        """The real CLI addresses trashed items as /trash/<name> (uids are not accepted there)."""
        return "/trash/" + name.replace("/", "\\/")      # the CLI's documented escape for "/"

    def trashed(self, uids) -> list[RemoteNode] | None:
        """The trash entries for these uids, or None when any of them can't be addressed safely:
        missing, or its name appears more than once in the trash (it could hit someone else's item)."""
        trash = self.list_trash()
        counts: dict[str, int] = {}
        for n in trash:
            counts[n.name] = counts.get(n.name, 0) + 1
        mine = [n for n in trash if n.uid in set(uids)]
        if len(mine) != len(set(uids)) or any(counts[n.name] != 1 for n in mine):
            return None
        return mine

    def restore(self, nodes: list[RemoteNode]):
        """Undo a trash. `nodes` must come from trashed(): names checked unique in the trash."""
        return self.run(["filesystem", "restore", *[self.trash_path(n.name) for n in nodes]], timeout=300)

    def delete_trashed(self, nodes: list[RemoteNode]):
        """Permanent delete. Only --selftest calls this, and only for items it created (decisions D12)."""
        return self.run(["filesystem", "delete", *[self.trash_path(n.name) for n in nodes]], timeout=300)

    def shared_with_me(self) -> list[RemoteNode]:
        return [n for n in self.list("/shared-with-me") if n.type in ("file", "folder")]

    def help_text(self, *cmd: str) -> str:
        return self.run([*cmd, "--help"], json_out=False, timeout=60, ok_codes=(0, 1)) or ""

    def rename(self, path: str, new_name: str):
        return self.run(["filesystem", "rename", path, new_name], timeout=120)

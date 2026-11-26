"""User settings and the list of synced folders (~/.config/kluis/config.json).

Writes are atomic (temp file + fsync + rename) and the previous good file is kept as config.json.bak.
A corrupt config.json falls back to the backup (invariant 11). Old 0.3.x files migrate silently.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from dataclasses import asdict, dataclass, field

from .paths import CONFIG_DIR, CONFIG_FILE, ensure_dirs
from .system import is_inside, is_strictly_inside, is_system_root, path_key

log = logging.getLogger("kluis.config")

CONFIG_VERSION = 2
MODES = {
    "two-way": ("⇄", "Two-way", "Edits, new files and deletions travel both ways. Conflicts keep both copies."),
    "backup": ("↑", "Back up", "Uploads new and changed files. Never deletes in Proton Drive, never changes this computer."),
    "mirror": ("↓", "Mirror down", "Keeps a local copy of a Proton Drive folder. Never changes Proton Drive."),
}
INTERVALS = (5, 15, 30, 60)
NOTIFY_LEVELS = ("all", "problems", "off")
PART_DIR = ".kluis-part"          # staging folder for downloads, never synced

DEFAULT_IGNORES = [
    "*.tmp", "*.temp", "*.swp", "*~", ".~lock.*#", "*.part", "*.crdownload",
    ".DS_Store", "Thumbs.db", "desktop.ini", ".Trash-*", "__pycache__",
]


@dataclass
class FolderPair:
    local: str
    remote: str
    mode: str = "two-way"
    enabled: bool = True
    watch: bool = True               # sync shortly after local changes
    mirror_deletions: bool = True    # deletions go to the other side's trash (always recoverable)
    ignore: list = field(default_factory=lambda: list(DEFAULT_IGNORES))
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    hold: str = ""                   # "" | "guard" | "missing": paused by a safety guard
    # runtime info persisted for display
    last_sync: float = 0.0
    last_result: str = ""            # "ok" | "error" | "conflict" | ""
    last_message: str = ""
    last_files: int = 0              # files in the folder after the last sync

    @property
    def name(self) -> str:
        return os.path.basename(self.local.rstrip("/\\")) or self.local

    @property
    def is_share(self) -> bool:
        return self.remote.startswith("/shared-with-me/")


@dataclass
class PhotoSettings:
    download: bool = False           # keep a local copy of the Proton Photos timeline
    download_dir: str = ""
    layout: str = "month"            # month (2026/2026-11) | year (2026) | flat
    albums: bool = False             # also save each album as a folder
    remove_deleted: bool = False     # photo deleted in Proton -> move local copy to Trash
    upload: bool = False             # add new photos from a local folder to Proton Photos
    upload_dir: str = ""
    remote_previews: bool = True     # fetch photos not saved locally once, keep a small preview
    last_sync: float = 0.0
    last_result: str = ""
    last_message: str = ""
    count: int = 0                   # photos in the timeline at the last check
    added: int = 0                   # upload stats of the last run
    skipped: int = 0

    @property
    def active(self) -> bool:
        return (self.download and bool(self.download_dir)) or (self.upload and bool(self.upload_dir))


PHOTOS_ID = "photos"


def default_root() -> str:
    return os.path.join(os.path.expanduser("~"), "Proton Drive")


@dataclass
class Settings:
    config_version: int = CONFIG_VERSION
    cli_path: str = ""
    cli_custom: bool = False           # "Use another copy": never auto-updated
    cli_last_check: float = 0.0
    cli_pending_version: str = ""      # a newer CLI that failed the capability self-test
    interval_minutes: int = 15
    start_minimized: bool = False
    autostart: bool = True
    notifications: str = "problems"    # all | problems | off
    theme: str = "system"              # system | light | dark
    accent: str = "green"              # green | purple
    skip_thumbnails: bool = False
    paused: bool = False
    onboarded: bool = False
    onboarding_step: int = 1
    root_dir: str = field(default_factory=default_root)
    home_city: str = ""                # "" = from the system time zone
    vpn_view: bool = True
    beta: bool = False
    app_updates: bool = True
    app_last_check: float = 0.0
    app_notified_version: str = ""
    language: str = ""
    qs_collapsed: bool = False
    last_tab: str = "home"
    window: dict = field(default_factory=lambda: {"w": 1440, "h": 900, "x": -1, "y": -1, "max": False})
    columns: dict = field(default_factory=dict)     # table id -> {column id: width}
    told_background: bool = False
    selftest_for: str = ""             # "<kluis version>/<cli version>" the last automatic self-test ran for
    folders: list = field(default_factory=list)
    shares: dict = field(default_factory=dict)      # share uid -> folder id (Shared with me sync)
    photos: PhotoSettings = field(default_factory=PhotoSettings)
    # Proton accounts (kluis/accounts.py). folders/shares/photos above belong to `account`; the other
    # accounts' ones wait in accounts[i]["data"].
    account: str = ""
    accounts: list = field(default_factory=list)    # [{email, cache, state, signed_out[, data]}]

    # ---------- persistence ----------
    @classmethod
    def load(cls, path=None) -> "Settings":
        path = path or CONFIG_FILE
        raw = _read_json(path)
        if raw is None and os.path.exists(path):
            log.error("config.json is unreadable; starting from config.json.bak")
            raw = _read_json(str(path) + ".bak")
            if raw is not None:
                try:
                    shutil.copyfile(str(path), str(path) + ".corrupt")
                except OSError:
                    pass
        if raw is None:
            return cls()
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict) -> "Settings":
        raw = migrate(dict(raw))
        folders = [FolderPair(**{k: v for k, v in f.items() if k in FolderPair.__dataclass_fields__})
                   for f in raw.pop("folders", []) if isinstance(f, dict) and f.get("local")]
        ph = raw.pop("photos", {}) or {}
        s = cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})
        s.folders = folders
        s.accounts = [a for a in (s.accounts or []) if isinstance(a, dict) and a.get("email")]
        s.photos = PhotoSettings(**{k: v for k, v in ph.items() if k in PhotoSettings.__dataclass_fields__})
        return s

    def save(self, path=None):
        ensure_dirs()
        path = str(path or CONFIG_FILE)
        data = json.dumps(asdict(self), indent=2, ensure_ascii=False)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if os.path.exists(path) and _read_json(path) is not None:
            try:
                shutil.copyfile(path, path + ".bak")
            except OSError:
                log.warning("could not write config.json.bak")
        os.replace(tmp, path)

    def folder(self, fid: str) -> FolderPair | None:
        return next((f for f in self.folders if f.id == fid), None)

    def overlaps(self, local: str, exclude_id: str = "") -> FolderPair | None:
        """Nested or identical local folders would sync twice; refuse them (also across accounts)."""
        for f in self.folders:
            if f.id == exclude_id:
                continue
            if is_inside(local, f.local) or is_inside(f.local, local):
                return f
        other = self.other_account_overlap(local)
        return other[1] if other else None

    def other_account_overlap(self, local: str) -> tuple[str, FolderPair] | None:
        """(email, folder) when another Proton account in Kluis already syncs this folder or one around it."""
        from .accounts import stashed_folders
        for email, f in stashed_folders(self):
            if is_inside(local, f.local) or is_inside(f.local, local):
                return email, f
        return None


def _read_json(path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def migrate(raw: dict) -> dict:
    """0.3.x → 1.0. Unknown keys are dropped by the loader; new keys get their defaults."""
    if raw.get("notifications") == "important":
        raw["notifications"] = "problems"
    if raw.get("notifications") not in NOTIFY_LEVELS:
        raw["notifications"] = "problems"
    try:
        iv = int(raw.get("interval_minutes", 15))
    except (TypeError, ValueError):
        iv = 15
    raw["interval_minutes"] = min(INTERVALS, key=lambda x: (abs(x - iv), x))
    if raw.get("theme") not in ("system", "light", "dark"):
        raw["theme"] = "system"
    if raw.get("accent") not in ("green", "purple"):
        raw["accent"] = "green"
    for f in raw.get("folders", []) or []:
        if isinstance(f, dict) and "mode" in f and f["mode"] not in MODES:
            f["mode"] = "backup"          # unknown mode: the one that never deletes or changes local files
    raw["config_version"] = CONFIG_VERSION
    return raw


def validate_local(settings: Settings, path: str, exclude_id: str = "") -> str | None:
    """Reason a local folder can't be synced, or None (§3.3)."""
    if not path:
        return "Choose a folder on this computer."
    real = os.path.realpath(path)
    home = os.path.expanduser("~")
    if is_system_root(real):
        return "Pick a folder inside your home folder, not the whole computer"
    if path_key(real) == path_key(home):
        return "Pick a folder inside your home folder, not the whole home folder"
    cfg = str(CONFIG_DIR)
    if is_inside(real, cfg) or is_inside(cfg, real):
        return "That folder holds Kluis's own settings"
    if not os.path.isdir(real):
        return "That folder doesn't exist"
    acc = settings.other_account_overlap(real)
    if acc:
        return f"Your other Proton account {acc[0]} already syncs {acc[1].name}"
    other = settings.overlaps(real, exclude_id)
    if other:
        if path_key(other.local) == path_key(real):
            return "Already syncing"
        if is_strictly_inside(real, other.local):
            return f"It's inside {other.name}, which is already syncing"
        return f"It contains {other.name}, which is already syncing"
    return None

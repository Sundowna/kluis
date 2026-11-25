"""User settings and the list of synced folders (~/.config/kluis/config.json)."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field

from .paths import CONFIG_FILE, ensure_dirs

MODES = {
    "two-way": ("⇄", "Two-way sync", "Changes on either side are copied to the other. Conflicts keep both copies."),
    "backup": ("↑", "Back up", "Copies new and changed files to Proton Drive. Never changes this computer."),
    "mirror": ("↓", "Mirror down", "Keeps a local copy of a Proton Drive folder. Never changes Proton Drive."),
}

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
    # runtime info persisted for display
    last_sync: float = 0.0
    last_result: str = ""            # "ok" | "error" | "conflict" | ""
    last_message: str = ""

    @property
    def name(self) -> str:
        return os.path.basename(self.local.rstrip("/")) or self.local


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

    @property
    def active(self) -> bool:
        return (self.download and bool(self.download_dir)) or (self.upload and bool(self.upload_dir))


PHOTOS_ID = "photos"


@dataclass
class Settings:
    cli_path: str = ""
    interval_minutes: int = 15
    start_minimized: bool = False
    autostart: bool = True
    notifications: str = "important"   # "all" | "important" | "off"
    theme: str = "system"              # "system" | "light" | "dark"
    skip_thumbnails: bool = False
    paused: bool = False
    onboarded: bool = False
    folders: list = field(default_factory=list)
    photos: PhotoSettings = field(default_factory=PhotoSettings)

    # ---------- persistence ----------
    @classmethod
    def load(cls) -> "Settings":
        try:
            raw = json.loads(CONFIG_FILE.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return cls()
        folders = [FolderPair(**{k: v for k, v in f.items() if k in FolderPair.__dataclass_fields__})
                   for f in raw.pop("folders", [])]
        ph = raw.pop("photos", {}) or {}
        s = cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})
        s.folders = folders
        s.photos = PhotoSettings(**{k: v for k, v in ph.items() if k in PhotoSettings.__dataclass_fields__})
        return s

    def save(self):
        ensure_dirs()
        data = asdict(self)
        tmp = CONFIG_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        os.replace(tmp, CONFIG_FILE)

    def folder(self, fid: str) -> FolderPair | None:
        return next((f for f in self.folders if f.id == fid), None)

    def overlaps(self, local: str, exclude_id: str = "") -> FolderPair | None:
        """Nested or identical local folders would sync twice; refuse them."""
        a = os.path.realpath(local).rstrip("/") + "/"
        for f in self.folders:
            if f.id == exclude_id:
                continue
            b = os.path.realpath(f.local).rstrip("/") + "/"
            if a.startswith(b) or b.startswith(a):
                return f
        return None

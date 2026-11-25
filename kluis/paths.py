"""XDG locations used by Kluis."""
import os
from pathlib import Path


def _xdg(var: str, default: str) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / default


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "kluis"
DATA_DIR = _xdg("XDG_DATA_HOME", ".local/share") / "kluis"
STATE_DIR = _xdg("XDG_STATE_HOME", ".local/state") / "kluis"
AUTOSTART_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "autostart"
BIN_DIR = Path.home() / ".local" / "bin"

CONFIG_FILE = CONFIG_DIR / "config.json"
STATE_DB = DATA_DIR / "state.sqlite"
LOG_FILE = STATE_DIR / "kluis.log"
ACTIVITY_FILE = STATE_DIR / "activity.jsonl"


def ensure_dirs():
    for d in (CONFIG_DIR, DATA_DIR, STATE_DIR):
        d.mkdir(parents=True, exist_ok=True)

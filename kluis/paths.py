"""Where Kluis keeps its files.

Linux: the XDG locations (~/.config/kluis, ~/.local/share/kluis, ~/.local/state/kluis, ~/.local/bin).
Windows: %LOCALAPPDATA%\\Kluis\\{config,data,state,bin}. An XDG_* variable that is set wins on both
systems (the test suites use that to keep everything in a temporary folder).
"""
import os
from pathlib import Path

IS_WINDOWS = os.name == "nt"


def _xdg(var: str, default: str) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / default


def _win_base() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")) / "Kluis"


if IS_WINDOWS:
    _base = _win_base()
    CONFIG_DIR = Path(os.environ["XDG_CONFIG_HOME"]) / "kluis" if os.environ.get("XDG_CONFIG_HOME") else _base / "config"
    DATA_DIR = Path(os.environ["XDG_DATA_HOME"]) / "kluis" if os.environ.get("XDG_DATA_HOME") else _base / "data"
    STATE_DIR = Path(os.environ["XDG_STATE_HOME"]) / "kluis" if os.environ.get("XDG_STATE_HOME") else _base / "state"
    AUTOSTART_DIR = None          # Windows: the registry's Run key (kluis/system.py)
    BIN_DIR = DATA_DIR / "bin" if os.environ.get("XDG_DATA_HOME") else _base / "bin"
else:
    CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "kluis"
    DATA_DIR = _xdg("XDG_DATA_HOME", ".local/share") / "kluis"
    STATE_DIR = _xdg("XDG_STATE_HOME", ".local/state") / "kluis"
    AUTOSTART_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "autostart"
    BIN_DIR = Path.home() / ".local" / "bin"

CLI_NAME = "proton-drive.exe" if IS_WINDOWS else "proton-drive"
CONFIG_FILE = CONFIG_DIR / "config.json"
STATE_DB = DATA_DIR / "state.sqlite"
LOG_FILE = STATE_DIR / "kluis.log"
ACTIVITY_FILE = STATE_DIR / "activity.jsonl"


def ensure_dirs():
    for d in (CONFIG_DIR, DATA_DIR, STATE_DIR):
        d.mkdir(parents=True, exist_ok=True)

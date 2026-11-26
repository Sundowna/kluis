"""Copy diagnostics (HANDOVER §3.8.6): versions, system, last 200 log lines and config,
with no email, no tokens and no paths outside the synced folders."""
from __future__ import annotations

import json
import os
import platform
import re
from dataclasses import asdict

from . import VERSION
from .paths import LOG_FILE

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
TOKEN = re.compile(r"(?i)(token|secret|password|passphrase|authorization|cookie|session|bearer|key)"
                   r"(\"?\s*[:=]\s*\"?)[^\s\",}]+")
LONG_SECRET = re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")
URLQ = re.compile(r"(https?://[^\s?]+)\?\S+")


def _distro() -> str:
    if os.name == "nt":
        from .system import os_name
        return os_name()
    try:
        d = dict(line.rstrip().split("=", 1) for line in open("/etc/os-release", encoding="utf-8") if "=" in line)
        return d.get("PRETTY_NAME", "").strip('"')
    except OSError:
        return platform.platform()


def redact(text: str, allowed_roots: list[str]) -> str:
    text = EMAIL.sub("<email>", text)
    text = TOKEN.sub(lambda m: m.group(1) + m.group(2) + "<redacted>", text)
    text = URLQ.sub(lambda m: m.group(1) + "?<redacted>", text)
    text = LONG_SECRET.sub("<redacted>", text)
    home = os.path.expanduser("~")
    roots = sorted({x for r in allowed_roots if r for x in (r, os.path.realpath(r))}, key=len, reverse=True)

    def path_sub(m):
        p = m.group(0)
        for r in roots:
            if p == r or p.startswith(r + "/"):
                return p.replace(home, "~", 1)
        return "<path>"

    def win_path_sub(m):          # Windows: C:\Users\<name>\… would show the user's account name
        p = m.group(0)
        key = os.path.normcase(p.replace("/", "\\"))
        for r in roots:
            rk = os.path.normcase(r.replace("/", "\\")).rstrip("\\")
            if key == rk or key.startswith(rk + "\\"):
                hk = os.path.normcase(home.replace("/", "\\"))
                return "~" + p[len(home):] if key.startswith(hk + "\\") else p
        return "<path>"
    text = re.sub(r"(?<![\w~])[A-Za-z]:[\\/][^\s\"':,;()\[\]{}<>|?*]*", win_path_sub, text)
    text = re.sub(r"\\\\[^\s\"':,;()\[\]{}<>|?*]+", "<path>", text)          # \\server\share\…
    return re.sub(r"(?<![\w~])/(?:[^\s\"':,;()\[\]{}]+)", path_sub, text)


def collect(settings, cli_version: str) -> str:
    roots = [f.local for f in settings.folders]
    try:
        lines = open(LOG_FILE, encoding="utf-8", errors="replace").read().splitlines()[-200:]
    except OSError:
        lines = []
    cfg = asdict(settings)
    cfg.pop("window", None)
    for f in cfg.get("folders", []):
        f.pop("ignore", None)
        f["held"] = len(f.get("held") or [])      # paused big items: how many, not their names
    cfg["cli_path"] = "<path>" if cfg.get("cli_path") else ""
    cfg["root_dir"] = "<path>"
    cfg["account"] = "<email>" if cfg.get("account") else ""
    cfg["accounts"] = [{"signed_out": bool(a.get("signed_out")), "own_cache": bool(a.get("cache")),
                        "folders": len((a.get("data") or {}).get("folders") or [])} for a in cfg.get("accounts", [])]
    cfg["home_city"] = "<set>" if cfg.get("home_city") else ""
    ph = cfg.get("photos", {})
    for k in ("download_dir", "upload_dir"):
        if ph.get(k):
            ph[k] = "<path>"
    out = [
        f"Kluis {VERSION}",
        f"Proton Drive CLI {cli_version or '?'}",
        f"System: {_distro()} · {platform.machine()}",
        f"Desktop: {os.environ.get('XDG_CURRENT_DESKTOP', '?')} · {os.environ.get('XDG_SESSION_TYPE', '?')}",
        "",
        "--- config ---",
        json.dumps(cfg, indent=1, ensure_ascii=False),
        "",
        "--- last 200 log lines ---",
        *lines,
    ]
    return redact("\n".join(out), roots)

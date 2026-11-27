"""Status text shared by Home, Folders, the status panel and the panel icon (HANDOVER §4.2).

Priority: Paused → Syncing → Problems → No folders → Up to date. Pure functions; unit-tested.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .i18n import _, ngettext


@dataclass
class Snapshot:
    paused: bool = False
    syncing: bool = False
    done: int = 0
    total: int = 0
    eta_s: float | None = None
    city: str = ""
    via_vpn: bool = False
    problems: list = field(default_factory=list)      # texts, first one shown
    folders: int = 0
    enabled: int = 0
    watching: int = 0
    conflicts: int = 0
    remote_checked: float = 0.0
    signed_out: bool = False
    keyring_locked: bool = False
    hold_text: str = ""


@dataclass
class Status:
    kind: str          # paused | syncing | problems | empty | ok
    title: str
    subtitle: str
    tone: str          # warn | sync | error | idle | ok


def eta_text(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return ""
    s = int(round(seconds))
    if s < 60:
        return _("about {n} sec left").format(n=max(s, 1))
    m = int(round(s / 60))
    if m < 60:
        return _("about {n} min left").format(n=m)
    return _("about {h} h {m} min left").format(h=m // 60, m=m % 60)


def estimate_eta(file_times: list[float], done: int, total: int, started: float, now: float | None = None):
    """Seconds left from the average time per finished file. None until two files are done."""
    now = now or time.time()
    if done < 2 or total <= done or now <= started:
        return None
    per = (now - started) / done
    return per * (total - done)


def compute(snap: Snapshot) -> Status:
    if snap.paused:
        return Status("paused", _("Sync paused — your files are safe"),
                      _("New changes wait on this computer until you resume"), "warn")
    if snap.syncing:
        if snap.total:
            title = ngettext("Syncing {done} of {total} file", "Syncing {done} of {total} files",
                             snap.total).format(done=snap.done, total=snap.total)
        else:
            title = _("Syncing…")
        origin = snap.city or _("this computer")
        sub = _("From {city} via VPN to Proton Drive").format(city=origin) if snap.via_vpn \
            else _("From {city} to Proton Drive").format(city=origin)
        eta = eta_text(snap.eta_s)
        return Status("syncing", title, f"{sub} · {eta}" if eta else sub, "sync")
    if snap.signed_out:
        return Status("problems", _("Sign in to keep syncing"),
                      _("Your Proton Drive session ended. Your files are safe."), "error")
    if snap.keyring_locked:
        return Status("problems", _("Unlock your keyring to keep syncing"),
                      _("Your Proton session is still saved. Kluis continues as soon as it's unlocked."), "error")
    if snap.hold_text:
        return Status("problems", snap.hold_text, _("Kluis continues by itself when it can"), "error")
    if snap.problems:
        n = len(snap.problems)
        return Status("problems", ngettext("{n} folder needs attention", "{n} folders need attention", n).format(n=n),
                      snap.problems[0], "error")
    if snap.folders == 0:
        return Status("empty", _("Ready when you are"), _("Add a folder to start syncing with Proton Drive"), "idle")
    title = _("Everything is up to date") if not snap.conflicts else \
        ngettext("Up to date · {n} with conflict copies", "Up to date · {n} with conflict copies",
                 snap.conflicts).format(n=snap.conflicts)
    parts = [_("Watching {w} of {m} folders").format(w=snap.watching, m=snap.folders)]
    if snap.watching:
        parts.append(_("local edits sync ~10 s after you save"))
    if snap.remote_checked:
        parts.append(_("Proton Drive checked {t}").format(t=time.strftime("%H:%M", time.localtime(snap.remote_checked))))
    return Status("ok", title, " · ".join(parts), "ok")


def human_bytes(n: float) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.1f} TB"


def duration_text(seconds: float) -> str:
    s = int(max(0, seconds))
    if s < 60:
        return _("{n} sec").format(n=s)
    m = s // 60
    if m < 60:
        return _("{n} min").format(n=m)
    return _("{h} h {m} min").format(h=m // 60, m=m % 60)


def axis_max(values: list[float]) -> float:
    """Auto-scaled KB/s axis 0 / max/2 / max with max a multiple of 16 (0/8/16 at rest)."""
    peak = max(values or [0.0])
    top = 16.0
    while top < peak:
        top *= 2
    return top

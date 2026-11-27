"""Sort CLI and OS errors into the states that pause syncing (invariant 10) and the backoff schedule."""
from __future__ import annotations

import errno

OFFLINE = "offline"
DISK_FULL = "disk-full"
SIGNED_OUT = "signed-out"
RATE_LIMIT = "rate-limit"
KEYRING_LOCKED = "keyring-locked"   # signed in, but the keyring holding the session is locked
HOLD_KINDS = (OFFLINE, DISK_FULL, SIGNED_OUT, RATE_LIMIT, KEYRING_LOCKED)

_MARKERS = {
    SIGNED_OUT: ("need to login", "need to log in", "not logged in", "login first", "session expired",
                 "invalid refresh token", "unauthorized"),
    DISK_FULL: ("enospc", "no space left", "disk full", "not enough space", "quota exceeded on device"),
    RATE_LIMIT: ("429", "too many requests", "rate limit", "rate-limit"),
    OFFLINE: ("fetch failed", "enotfound", "econnrefused", "econnreset", "etimedout", "eai_again",
              "network error", "network is unreachable", "socket hang up", "offline", "getaddrinfo",
              "unable to connect", "connection refused", "timed out", "ehostunreach", "enetunreach"),
}

STATUS_TEXT = {
    OFFLINE: "Offline — will continue when you're back online",
    DISK_FULL: "Disk full on this computer",
    SIGNED_OUT: "Sign in to keep syncing",
    RATE_LIMIT: "Proton Drive asked Kluis to slow down — will continue shortly",
    KEYRING_LOCKED: "Unlock your keyring to keep syncing",
}

KEYRING_RETRY = 10          # seconds: unlocking is up to the user, so look again soon (the next tick)

BACKOFF_START = 30          # seconds
BACKOFF_MAX = 15 * 60       # §7.10: max 15 min


def classify(err) -> str | None:
    """One of HOLD_KINDS, or None for an ordinary (per-file) error."""
    if isinstance(err, OSError) and getattr(err, "errno", None) == errno.ENOSPC:
        return DISK_FULL
    text = (str(err) + " " + (getattr(err, "stderr", "") or "")).lower()
    for kind in (SIGNED_OUT, DISK_FULL, RATE_LIMIT, OFFLINE):
        if any(m in text for m in _MARKERS[kind]):
            return kind
    return None


def backoff_delay(attempt: int) -> int:
    """30 s, 60 s, 2 min, 4 min, 8 min, 15 min, 15 min, …"""
    if attempt <= 0:
        return BACKOFF_START
    return min(BACKOFF_MAX, BACKOFF_START * (2 ** attempt))


class HoldError(Exception):
    """Raised inside a sync run to stop it at once; the manager pauses and retries with backoff."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(detail or STATUS_TEXT.get(kind, kind))
        self.kind = kind

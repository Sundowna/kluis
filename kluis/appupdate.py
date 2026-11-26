"""Kluis update notices (HANDOVER §2, F16): notify only, never install.

Reads GitHub's public releases list once a day (only when "Tell me about Kluis updates" is on).
Beta access also offers pre-releases.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

from . import VERSION

RELEASES_URL = "https://api.github.com/repos/Sundowna/kluis/releases"
RELEASE_PAGE = "https://github.com/Sundowna/kluis/releases"


def _key(v: str):
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)(?:[-.]?(a|b|rc|beta|alpha)\.?(\d*))?", v or "")
    if not m:
        return (0, 0, 0, 0, 0)
    pre = m.group(4)
    rank = {"alpha": 0, "a": 0, "beta": 1, "b": 1, "rc": 2}.get(pre, 3) if pre else 3
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), rank, int(m.group(5) or 0))


def newer(a: str, b: str) -> bool:
    return _key(a) > _key(b)


def pick(releases: list[dict], current: str, beta: bool) -> dict | None:
    best = None
    for r in releases:
        if r.get("draft"):
            continue
        if r.get("prerelease") and not beta:
            continue
        tag = r.get("tag_name") or ""
        if newer(tag, current) and (best is None or newer(tag, best["tag_name"])):
            best = r
    return best


def check(beta: bool, timeout: int = 15) -> dict | None:
    """{"version", "url"} of a newer release, or None."""
    url = os.environ.get("KLUIS_TEST_RELEASES") if os.environ.get("KLUIS_TEST") == "1" else None
    req = urllib.request.Request(url or RELEASES_URL, headers={"User-Agent": "kluis",
                                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    rel = pick(data if isinstance(data, list) else [], VERSION, beta)
    if not rel:
        return None
    return {"version": (rel.get("tag_name") or "").lstrip("v"), "url": rel.get("html_url") or RELEASE_PAGE}

"""Capability self-test for a Proton Drive CLI binary (HANDOVER §6, invariant 12).

Runs `--help` for every command Kluis uses and checks the flags it needs, plus one read-only
listing when signed in. A binary that fails is never used for a sync.
"""
from __future__ import annotations

import json
import logging
import subprocess

log = logging.getLogger("kluis.capabilities")

COMMANDS = [
    "auth login", "auth logout",
    "filesystem list", "filesystem upload", "filesystem download", "filesystem rename",
    "filesystem trash", "filesystem restore", "filesystem create-folder",
    "photo timeline", "photo upload", "photo download", "album list", "album photos",
]
FLAGS = {
    ("filesystem", "upload"): ["create-new-revision", "merge", "--skip-thumbnails", "--file-conflict-strategy",
                               "--folder-conflict-strategy"],
    ("filesystem", "download"): ["rename", "skip", "merge", "--file-conflict-strategy", "--folder-conflict-strategy"],
    ("photo", "upload"): ["--conflict-strategy"],
    ("photo", "download"): ["--conflict-strategy"],
}


def _run(binary: str, args: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        p = subprocess.run([binary, *args], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)


def self_test(binary: str, signed_in: bool = True) -> tuple[bool, list[str]]:
    """Returns (passed, problems)."""
    problems: list[str] = []
    code, out = _run(binary, ["version"])
    if code != 0 or "cli-drive@" not in out:
        problems.append("`version` does not print cli-drive@…")
    code, out = _run(binary, ["--help"])
    usage = " ".join(out.split())
    for c in COMMANDS:
        if c not in usage:
            problems.append(f"command missing: {c}")
    for (g, c), flags in FLAGS.items():
        _, h = _run(binary, [g, c, "--help"])
        for fl in flags:
            if fl not in h:
                problems.append(f"{g} {c}: option {fl} missing")
    if signed_in and not problems:
        code, out = _run(binary, ["filesystem", "list", "/", "--json"], timeout=120)
        try:
            roots = json.loads(out[out.index("["):]) if "[" in out else None
        except ValueError:
            roots = None
        if code != 0 or not isinstance(roots, list) or not all(isinstance(r, dict) and "path" in r for r in roots):
            problems.append("`filesystem list /` JSON changed")
        else:
            code, out = _run(binary, ["filesystem", "list", "/my-files", "--json"], timeout=120)
            try:
                items = json.loads(out[out.index("["):]) if "[" in out else None
            except ValueError:
                items = None
            if code != 0 or not isinstance(items, list) or \
                    not all(isinstance(i, dict) and {"uid", "name", "type"} <= set(i) for i in items):
                problems.append("`filesystem list /my-files` JSON changed")
    if problems:
        log.warning("capability self-test failed for %s: %s", binary, problems)
    return (not problems), problems

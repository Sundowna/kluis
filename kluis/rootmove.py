"""Move "Your Proton Drive folder" to a new place (HANDOVER §3.8, invariant 6).

Atomic per item and resumable: a journal (config dir) lists every top-level item and its state.
Same drive → os.rename (atomic). Other drive → copy into `<dest>/.kluis-part-move/<name>`,
fsync, rename into place, and only then remove the source. At every moment each file exists
in at least one complete place. After a crash, `resume()` finishes the job from the journal.
"""
from __future__ import annotations

import json
import os
import shutil
from typing import Callable

from .paths import CONFIG_DIR

JOURNAL = CONFIG_DIR / "move-journal.json"
STAGE = ".kluis-part-move"


class MoveError(Exception):
    pass


def _write_journal(j: dict, path=None):
    path = str(path or JOURNAL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(j, fh)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _read_journal(path=None) -> dict | None:
    try:
        with open(str(path or JOURNAL)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def check_target(src: str, dest: str) -> str | None:
    s, d = os.path.realpath(src), os.path.realpath(dest)
    if s == d:
        return "That's already your Proton Drive folder"
    if d.startswith(s + "/"):
        return "The new place can't be inside the current folder"
    if os.path.exists(d) and not os.path.isdir(d):
        return "That isn't a folder"
    if os.path.isdir(d):
        clash = [n for n in os.listdir(s) if os.path.exists(os.path.join(d, n))] if os.path.isdir(s) else []
        if clash:
            return f"The new place already has “{clash[0]}”"
    parent = d if os.path.isdir(d) else os.path.dirname(d)
    if not os.access(parent, os.W_OK):
        return "Kluis can't write there"
    return None


def start(src: str, dest: str, journal=None) -> dict:
    problem = check_target(src, dest)
    if problem:
        raise MoveError(problem)
    os.makedirs(dest, exist_ok=True)
    items = sorted(os.listdir(src)) if os.path.isdir(src) else []
    j = {"src": os.path.realpath(src), "dest": os.path.realpath(dest),
         "items": {n: "todo" for n in items if n != STAGE}}
    _write_journal(j, journal)
    return j


def _fsync_tree(path: str):
    for dp, _dns, fns in os.walk(path):
        for fn in fns:
            try:
                fd = os.open(os.path.join(dp, fn), os.O_RDONLY)
                os.fsync(fd)
                os.close(fd)
            except OSError:
                pass


def _same_device(a: str, b: str) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def run(j: dict, progress: Callable[[int, int, str], None] | None = None,
        cancelled: Callable[[], bool] | None = None, journal=None, _crash_after: int | None = None) -> bool:
    """Process the journal. Returns True when finished, False when cancelled (resumable)."""
    src, dest = j["src"], j["dest"]
    names = list(j["items"])
    total = len(names)
    for i, name in enumerate(names):
        if cancelled and cancelled():
            return False
        state = j["items"][name]
        s, d = os.path.join(src, name), os.path.join(dest, name)
        if progress:
            progress(i, total, name)
        if state == "done":
            continue
        if not os.path.lexists(s):
            # source already gone: only OK when the destination is complete
            if os.path.lexists(d):
                j["items"][name] = "done"
                _write_journal(j, journal)
                continue
            raise MoveError(f"“{name}” is in neither place; stopping so nothing else moves")
        if os.path.lexists(d):
            # a crash after the atomic rename into place: the destination is complete (clashing
            # names are refused before a move starts), so only the source removal is left
            if not _same_device(src, dest) or state == "copied":
                (shutil.rmtree if os.path.isdir(s) and not os.path.islink(s) else os.unlink)(s)
            j["items"][name] = "done"
            _write_journal(j, journal)
            continue
        if _same_device(src, dest):
            os.rename(s, d)                               # atomic
        else:
            stage = os.path.join(dest, STAGE)
            os.makedirs(stage, exist_ok=True)
            tmp = os.path.join(stage, name)
            if os.path.lexists(tmp):
                (shutil.rmtree if os.path.isdir(tmp) and not os.path.islink(tmp) else os.unlink)(tmp)
            if os.path.isdir(s) and not os.path.islink(s):
                shutil.copytree(s, tmp, symlinks=True, copy_function=shutil.copy2)
            else:
                shutil.copy2(s, tmp, follow_symlinks=False)
            _fsync_tree(tmp)
            os.rename(tmp, d)                             # complete copy appears atomically
            j["items"][name] = "copied"
            _write_journal(j, journal)
            if _crash_after is not None and i >= _crash_after:
                raise KeyboardInterrupt("simulated crash")
            (shutil.rmtree if os.path.isdir(s) and not os.path.islink(s) else os.unlink)(s)
        j["items"][name] = "done"
        _write_journal(j, journal)
        if _crash_after is not None and i >= _crash_after:
            raise KeyboardInterrupt("simulated crash")
    stage = os.path.join(dest, STAGE)
    if os.path.isdir(stage) and not os.listdir(stage):
        os.rmdir(stage)
    if os.path.isdir(src) and not os.listdir(src):
        os.rmdir(src)                                     # the old, now empty folder (never a non-empty one)
    if progress:
        progress(total, total, "")
    try:
        os.unlink(str(journal or JOURNAL))
    except OSError:
        pass
    return True


def pending(journal=None) -> dict | None:
    """An unfinished move from a previous run (crash or power loss)."""
    return _read_journal(journal)


def remap(path: str, src: str, dest: str) -> str:
    """Where a synced folder ends up after the move."""
    rs, rp = os.path.realpath(src), os.path.realpath(path)
    if rp == rs:
        return os.path.realpath(dest)
    if rp.startswith(rs + "/"):
        return os.path.join(os.path.realpath(dest), rp[len(rs) + 1:])
    return path

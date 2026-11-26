"""`kluis --selftest` (HANDOVER §8 D): proves the real CLI and account work, touching only its own folder.

1. creates /my-files/Kluis-selftest-<random> and a matching temporary local folder;
2. runs F4/F6/F8/F14 for real: 25 generated files (0 bytes, 50 MB, äöü, spaces, emoji, 200-char name),
   edit on both sides → conflict copy, delete → Proton trash, trash + restore (Undo), mirror and back-up
   rules, a connection cut mid-upload (the CLI process is killed, decisions D2);
3. verifies SHA-1s, cleans up both sides (trash, then permanently deletes only items it created);
4. reports PASS/FAIL to the Activity log. On FAIL syncing stays paused.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import sys
import tempfile
import threading
import time

from .capabilities import self_test
from .cli import CliError, ProtonDriveCli, find_cli, rjoin
from .config import FolderPair, Settings
from .engine import SyncEngine, sha1_file
from .paths import ACTIVITY_FILE, ensure_dirs
from .state import StateStore


class Fail(Exception):
    pass


class SelfTest:
    def __init__(self, cli: ProtonDriveCli, out=print):
        self.cli = cli
        self.out = out
        tag = secrets.token_hex(4)
        self.name = f"Kluis-selftest-{tag}"
        self.remote = f"/my-files/{self.name}"
        base = os.path.join(os.path.expanduser("~"), ".cache")
        os.makedirs(base, exist_ok=True)
        self.tmp = tempfile.mkdtemp(prefix=f"kluis-selftest-{tag}-", dir=base)
        self.local = os.path.join(self.tmp, "Two-way")
        self.store = StateStore(os.path.join(self.tmp, "state.sqlite"))
        self.engine = SyncEngine(cli, self.store)
        self.created = False
        self.uids: set[str] = set()
        self.folder_uids: set[str] = set()
        self.steps = 0

    def ok(self, cond, what):
        if not cond:
            raise Fail(what)
        self.steps += 1
        self.out(f"  ok  {what}")

    # ---------- helpers ----------
    def remote_tree(self, path=None, rel=""):
        path = path or self.remote
        out = {}
        for n in self.cli.list(path):
            self.uids.add(n.uid)
            r = f"{rel}/{n.name}" if rel else n.name
            if n.is_folder:
                self.folder_uids.add(n.uid)
                out.update(self.remote_tree(rjoin(path, n.name), r))
            else:
                out[r] = n
        return out

    def local_tree(self, root):
        out = {}
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d != ".kluis-part"]
            for fn in fns:
                p = os.path.join(dp, fn)
                out[os.path.relpath(p, root)] = sha1_file(p)
        return out

    def same(self, root):
        rt, lt = self.remote_tree(), self.local_tree(root)
        mism = [r for r, s in lt.items() if r not in rt or (rt[r].sha1 and rt[r].sha1 != s)]
        return not mism and set(rt) >= set(lt), mism

    def sync(self, f, **kw):
        r = self.engine.sync(f, **kw)
        if r.status == "guard":
            r = self.engine.sync(f, allow_trash=r.pending_trash)
        return r

    # ---------- the run ----------
    def run(self):
        self.ok(self.cli.is_logged_in(), "the CLI is signed in")
        passed, problems = self_test(self.cli.path, signed_in=True)
        self.ok(passed, f"capability self-test passes {problems or ''}")
        root_names = {n.name for n in self.cli.list("/my-files")}
        self.ok(self.name not in root_names, f"{self.remote} does not exist yet")
        self.cli.create_folder("/my-files", self.name, exist_ok=False)
        self.created = True
        me = next(n for n in self.cli.list("/my-files") if n.name == self.name)
        self.uids.add(me.uid)
        self.folder_uids.add(me.uid)

        # F4: 25 generated files
        os.makedirs(os.path.join(self.local, "sub dir"), exist_ok=True)
        files = {
            "empty.bin": b"",
            "big-50MB.bin": os.urandom(50 * 1024 * 1024),
            "äöü Ümlaut.txt": "Grüezi äöü".encode(),
            "with spaces in name.txt": b"spaces",
            "📷 emoji photo.txt": "emoji 📷".encode(),
            ("n" * 196) + ".txt": b"long name",
        }
        for i in range(19):
            files[f"sub dir/file {i:02}.txt"] = f"content {i} {secrets.token_hex(8)}".encode()
        for rel, data in files.items():
            with open(os.path.join(self.local, rel), "wb") as fh:
                fh.write(data)
        self.ok(len(files) == 25, "25 test files generated")
        f = FolderPair(local=self.local, remote=self.remote, mode="two-way")
        r = self.sync(f)
        self.ok(r.status == "ok", f"first two-way sync ({r.message})")
        same, mism = self.same(self.local)
        self.ok(same, f"every file is in Proton Drive with a matching SHA-1 {mism[:3]}")

        # F6/F14.7: edit on both sides → conflict copy
        edit = os.path.join(self.local, "with spaces in name.txt")
        with open(edit, "wb") as fh:
            fh.write(b"local edit")
        remote_copy = os.path.join(self.tmp, "remote-edit", "with spaces in name.txt")
        os.makedirs(os.path.dirname(remote_copy))
        with open(remote_copy, "wb") as fh:
            fh.write(b"remote edit")
        self.cli.upload([remote_copy], self.remote)
        r = self.sync(f)
        conf = [n for n in os.listdir(self.local) if n.startswith("with spaces in name (conflict ")]
        self.ok(r.status == "conflict" and len(conf) == 1, "edit on both sides keeps both copies")
        self.ok(open(edit, "rb").read() == b"remote edit" and open(os.path.join(self.local, conf[0]), "rb").read()
                == b"local edit", "both contents are intact")
        r = self.sync(f)
        same, _m = self.same(self.local)
        self.ok(same, "conflict copy is uploaded too")

        # delete → Proton trash
        os.remove(os.path.join(self.local, "sub dir", "file 00.txt"))
        r = self.sync(f)
        trashed = [n for n in self.cli.list_trash() if n.name == "file 00.txt" and n.parent_uid in self.folder_uids]
        self.ok(len(trashed) == 1 and "sub dir/file 00.txt" not in self.remote_tree(),
                "a local delete lands in the Proton Drive trash")
        self.uids.update(n.uid for n in trashed)

        # trash + restore (Browse Undo)
        target = rjoin(self.remote, "sub dir", "file 01.txt")
        self.cli.trash([target])
        t = [n for n in self.cli.list_trash() if n.name == "file 01.txt" and n.parent_uid in self.folder_uids]
        self.ok(len(t) == 1, "Browse “Move to trash” works")
        found = self.cli.trashed([t[0].uid])
        self.ok(found is not None, "the trashed item can be addressed safely (unique name in the trash)")
        self.cli.restore(found)
        self.ok("sub dir/file 01.txt" in self.remote_tree(), "Undo restores it from the trash (filesystem restore)")

        # mirror and back-up rules
        mirror = os.path.join(self.tmp, "Mirror")
        fm = FolderPair(local=mirror, remote=self.remote, mode="mirror")
        r = self.sync(fm)
        self.ok(r.status in ("ok", "conflict") and os.path.exists(os.path.join(mirror, "empty.bin")),
                f"mirror down copies Proton Drive ({r.message})")
        before = {k: v.sha1 for k, v in self.remote_tree().items()}
        with open(os.path.join(mirror, "mirror-local-only.txt"), "w") as fh:
            fh.write("x")
        os.remove(os.path.join(mirror, "empty.bin"))
        self.sync(fm)
        after = {k: v.sha1 for k, v in self.remote_tree().items()}
        self.ok(before == after, "mirror down never changes Proton Drive")
        backup = os.path.join(self.tmp, "Backup")
        os.makedirs(backup)
        with open(os.path.join(backup, "b.txt"), "w") as fh:
            fh.write("b")
        fb = FolderPair(local=backup, remote=rjoin(self.remote, "Backup"), mode="backup")
        self.sync(fb)
        os.remove(os.path.join(backup, "b.txt"))
        self.sync(fb, allow_trash=10)
        self.ok("Backup/b.txt" in self.remote_tree() and not os.path.exists(os.path.join(backup, "b.txt")),
                "back up never deletes in Proton Drive and never changes this computer")

        # F14.1-2: connection cut mid-upload, then resume without duplicates
        with open(os.path.join(self.local, "cut-mid-upload.bin"), "wb") as fh:
            fh.write(os.urandom(30 * 1024 * 1024))
        res = {}
        th = threading.Thread(target=lambda: res.setdefault("r", self.engine.sync(f)))
        th.start()
        time.sleep(4)
        self.engine.cancel()          # kills the CLI process: its connection drops mid-transfer
        th.join(300)
        r = self.sync(f)
        same, mism = self.same(self.local)
        dups = [k for k in self.remote_tree() if "cut-mid-upload" in k and k != "cut-mid-upload.bin"]
        self.ok(r.status in ("ok", "conflict") and same and not dups,
                f"after a cut connection the upload resumes, no duplicates, SHA-1s match {mism[:2]}")
        self.ok(not any(".kluis-part" in p for p in os.listdir(self.local)), "no .kluis-part leftovers")

    def cleanup(self):
        """Proton trash first, then permanently delete only the items this run created (decisions D12)."""
        if self.created:
            try:
                self.remote_tree()
            except CliError:
                pass
            try:
                self.cli.trash([self.remote])
            except CliError as e:
                self.out(f"  !!  could not trash {self.remote}: {e}")
            try:
                trash = self.cli.list_trash()
                counts: dict[str, int] = {}
                for n in trash:
                    counts[n.name] = counts.get(n.name, 0) + 1
                mine = [n for n in trash if n.uid in self.uids or n.parent_uid in self.folder_uids
                        or (n.name == self.name and n.is_folder)]
                safe = [n for n in mine if counts[n.name] == 1]     # never risk someone else's item
                if safe:
                    self.cli.delete_trashed(safe)
                left = len(mine) - len(safe)
                self.out(f"  ok  removed {len(safe)} test item(s) from the Proton Drive trash"
                         + (f"; {left} left there because another trashed item has the same name" if left else ""))
            except CliError as e:
                self.out(f"  !!  test items stay in the Proton Drive trash: {e}")
        shutil.rmtree(self.tmp, ignore_errors=True)


def _log(level, text, detail=""):
    ensure_dirs()
    with open(ACTIVITY_FILE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": time.time(), "level": level, "folder": "", "text": text, "detail": detail},
                            ensure_ascii=False) + "\n")


def main(argv=None) -> int:
    settings = Settings.load()
    path = find_cli(settings.cli_path)
    if not path:
        print("FAIL: the Proton Drive CLI was not found")
        _log("error", "Self-test FAILED", "The Proton Drive CLI was not found.")
        return 1
    t = SelfTest(ProtonDriveCli(path))
    print(f"Kluis self-test in {t.remote} (nothing else in your account is touched)")
    started = time.time()
    try:
        t.run()
        verdict, detail = "PASS", f"{t.steps} checks in {time.time() - started:.0f} s"
    except Fail as e:
        verdict, detail = "FAIL", str(e)
    except Exception as e:  # noqa: BLE001 - any surprise is a failure, never a crash
        verdict, detail = "FAIL", f"{type(e).__name__}: {e}"
    finally:
        t.cleanup()
    print(f"\n{verdict}: {detail}")
    if verdict == "PASS":
        _log("ok", "Self-test passed", detail)
        return 0
    _log("error", "Self-test FAILED — syncing stays paused", detail)
    settings.paused = True
    settings.save()
    if os.name == "nt":              # the running Kluis shows it in Activity; no notify-send on Windows
        return 1
    try:
        import subprocess
        subprocess.run(["notify-send", "-a", "Kluis", "Kluis self-test failed",
                        "Syncing stays paused. Open Kluis → Activity for details."], timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))


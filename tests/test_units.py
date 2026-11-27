"""Pure-logic tests (HANDOVER §8 A). Run: python3 tests/test_units.py"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

TMP = harness.setup("kluis-units-")
check = harness.Checker()

from kluis import appupdate, diagnostics, geo, scrubber, status  # noqa: E402
from kluis.config import Settings, validate_local  # noqa: E402
from kluis.status import Snapshot, compute  # noqa: E402

print("status text priority (§4.2)")
all_on = Snapshot(paused=True, syncing=True, total=40, done=27, problems=["x"], folders=3, enabled=3)
check(compute(all_on).kind == "paused", "Paused beats everything")
check(compute(Snapshot(paused=True)).title == "Sync paused — your files are safe" and compute(
    Snapshot(paused=True)).subtitle == "New changes wait on this computer until you resume", "paused copy")
s = compute(Snapshot(syncing=True, total=40, done=27, problems=["x"], city="Zürich", via_vpn=True, eta_s=12))
check(s.kind == "syncing" and s.title == "Syncing 27 of 40 files", "Syncing beats Problems")
check(s.subtitle == "From Zürich via VPN to Proton Drive · about 12 sec left", f"syncing subtitle ({s.subtitle})")
s = compute(Snapshot(problems=["Folder not found: /x", "b"], folders=2))
check(s.kind == "problems" and s.title == "2 folders need attention" and s.subtitle.startswith("Folder not found"),
      "Problems show count and first problem")
check(compute(Snapshot(problems=["a"], folders=1)).title == "1 folder needs attention", "singular")
check(compute(Snapshot(folders=0)).kind == "empty", "No folders")
ok = compute(Snapshot(folders=4, enabled=3, watching=3, remote_checked=1700000000))
check(ok.title == "Everything is up to date" and ok.subtitle.startswith("Watching 3 of 4 folders")
      and "local edits sync ~10 s after you save" in ok.subtitle and "Proton Drive checked" in ok.subtitle, "Up to date")
check("next" not in ok.subtitle.lower(), "no “next sync” countdown")
check(compute(Snapshot(folders=2, conflicts=1)).title == "Up to date · 1 with conflict copies", "conflict copies")
check(compute(Snapshot(hold_text="Offline — will continue when you're back online", folders=1)).title.startswith("Offline"),
      "offline hold title")
k = compute(Snapshot(keyring_locked=True, hold_text="x", folders=1))
check(k.kind == "problems" and k.title == "Unlock your keyring to keep syncing" and "still saved" in k.subtitle,
      "locked keyring: unlock, not sign in")
check(compute(Snapshot(signed_out=True, keyring_locked=True)).title == "Sign in to keep syncing",
      "a real sign-out wins over a locked keyring")

print("ETA and rates")
check(status.estimate_eta([], 1, 10, 0, 100) is None, "no ETA before two files")
check(abs(status.estimate_eta([], 4, 10, 0, 40) - 60) < 1e-6, "ETA = average time per file × files left")
check(status.eta_text(12) == "about 12 sec left" and status.eta_text(130) == "about 2 min left", "ETA wording")
check(status.axis_max([0, 3]) == 16 and status.axis_max([20]) == 32, "graph axis 0/8/16, doubles when needed")
check(status.human_bytes(1_200_000_000) == "1.2 GB" and status.human_bytes(214_000_000) == "214.0 MB", "sizes")

print("scrubber ring mapping (pure, monotonic, ends on the last dot)")
random.seed(4)
for trial in range(30):
    n = random.randint(2, 40)
    heights = [random.randint(60, 900) for _ in range(n)]
    offs, y = [], 0
    for h in heights:
        offs.append(y)
        y += h
    content, view = y, random.randint(300, 900)
    if content <= view:
        continue
    smax = content - view
    prev, maxjump, ok_mono = -1.0, 0.0, True
    step = 40
    s = 0.0
    positions = []
    while s <= smax + 0.1:
        p = scrubber.ring_position(s, view, content, offs)
        if p < prev - 1e-9:
            ok_mono = False
        if prev >= 0:
            maxjump = max(maxjump, p - prev)
        positions.append(p)
        prev = p
        s += step
    end = scrubber.ring_position(smax, view, content, offs)
    if not (ok_mono and abs(end - (n - 1)) < 1e-9 and maxjump <= 1.0 and positions[0] == 0.0):
        check(False, f"trial {trial}: mono={ok_mono} end={end} n={n} jump={maxjump}")
check(True, "30 random libraries: monotonic, starts on dot 0, ends exactly on the last dot, no jump > 1 dot")
offs = [0, 500, 1000, 1500, 2000, 2500]
for i in (1, 2, 3):
    sc = scrubber.scroll_for_dot(i, 600, 3000, offs)
    check(abs(scrubber.ring_position(sc, 600, 3000, offs) - i) < 1e-9, f"click on dot {i}: heading at top, ring on that dot")

print("config migration from 0.3.x")
old = {"cli_path": "/x", "interval_minutes": 20, "notifications": "important", "theme": "dark", "onboarded": True,
       "folders": [{"local": "/home/a/Docs", "remote": "/my-files/Docs", "mode": "two-way", "id": "abc"},
                   {"local": "/home/a/Odd", "remote": "/my-files/Odd", "mode": "weird", "id": "def"}],
       "photos": {"download": True, "download_dir": "/p"}, "unknown_key": 1}
p = os.path.join(TMP, "old.json")
json.dump(old, open(p, "w"))
s = Settings.load(p)
check(s.notifications == "problems" and s.interval_minutes == 15 and s.theme == "dark" and s.onboarded,
      "old values carried over / mapped (important→problems, 20→15 min)")
check(len(s.folders) == 2 and s.folders[0].id == "abc" and s.folders[1].mode == "backup",
      "folders kept; unknown mode falls back to the safest (backup)")
check(s.vpn_view and s.root_dir.endswith("Proton Drive") and s.config_version == 2, "new keys get defaults")
check(Settings.from_dict({"folders": [{"local": "/x", "remote": "/my-files/x"}]}).folders[0].mode == "two-way",
      "a folder saved without a mode gets the default (two-way)")
check(Settings.from_dict({"accent": "pink"}).accent == "green", "unknown accent falls back to green")
check(s.photos.download and s.photos.download_dir == "/p", "photo settings kept")

print("add-folder validation (§3.3)")
home = os.path.expanduser("~")
check(validate_local(s, home).startswith("Pick a folder inside your home folder"), "home folder refused")
check(validate_local(s, "/") is not None, "/ refused")
cfgdir = os.path.join(os.environ["XDG_CONFIG_HOME"], "kluis")
os.makedirs(cfgdir, exist_ok=True)
check(validate_local(s, cfgdir) == "That folder holds Kluis's own settings", "Kluis config dir refused")
d = os.path.join(TMP, "home", "Docs")
os.makedirs(d + "/inner", exist_ok=True)
s.folders[0].local = d
check(validate_local(s, d) == "Already syncing", "already synced")
check("inside" in validate_local(s, d + "/inner"), "nested inside refused")
check("contains" in validate_local(s, os.path.join(TMP, "home")), "containing refused")

print("VPN country and locations")
check(geo.country_from_connection("ProtonVPN CH#23") == "CH", "ProtonVPN CH#23 → CH")
check(geo.country_from_connection("ProtonVPN US-NY#5") == "US", "state code → country")
check(geo.country_from_connection("ProtonVPN CH-AU#1") == "AU", "Secure Core exit country")
check(geo.country_from_connection("My WireGuard") is None, "unknown name → none (D13)")
check(geo.capital("AU")[0] == "Canberra", "Australia → Canberra")
z = geo.zone_cities()
check("Europe/Zurich" in z and z["Europe/Zurich"][0] == "Zurich" and 47 < z["Europe/Zurich"][1] < 48,
      "zone1970.tab cities with coordinates")

print("Kluis update notices (notify only)")
rels = [{"tag_name": "v1.0.1", "prerelease": False, "html_url": "u1"},
        {"tag_name": "v1.1.0-beta.1", "prerelease": True, "html_url": "u2"}]
check(appupdate.pick(rels, "1.0.0", False)["tag_name"] == "v1.0.1", "stable release found")
check(appupdate.pick(rels, "1.0.0", True)["tag_name"] == "v1.1.0-beta.1", "beta access offers pre-releases")
check(appupdate.pick(rels[1:], "1.0.0", False) is None, "no beta access: pre-release ignored")
check(appupdate.pick(rels, "1.0.1", False) is None, "nothing when current")

print("diagnostics redaction")
txt = diagnostics.redact("user walter@proton.me token=abc123 at /home/x/secret/a.txt and /home/x/Docs/b.txt "
                         "refresh=" + "A" * 40 + " https://x.y/a?code=zz", ["/home/x/Docs"])
check("walter@proton.me" not in txt and "abc123" not in txt and "A" * 40 not in txt and "code=zz" not in txt,
      "no email, no tokens")
check("<path>" in txt and "/home/x/Docs/b.txt" in txt.replace("~", "/home/x"), "paths outside synced folders hidden")

print("contrast (§5): text ≥ 4.5:1, UI parts ≥ 3:1, both themes")
from kluis.ui.theme import ACCENTS, TOKENS  # noqa: E402


def lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


variants = dict(TOKENS)
for acc, modes in ACCENTS.items():
    for mode, over in modes.items():
        variants[f"{mode}+{acc}"] = {**TOKENS[mode], **over}
for theme, t in variants.items():
    for fg in ("text", "muted"):
        for bg in ("bg", "panel", "surface"):
            r = ratio(t[fg], t[bg])
            check(r >= 4.5, f"{theme}: {fg} on {bg} {r:.1f}:1")
    for fg in ("accent", "warn", "error", "upload"):
        for bg in ("bg", "panel"):
            r = ratio(t[fg], t[bg])
            check(r >= 3.0, f"{theme}: {fg} on {bg} {r:.1f}:1 (UI part)")
    r = ratio(t["on_accent"], t["accent"])
    check(r >= 4.5, f"{theme}: text on accent buttons {r:.1f}:1")

print("Proton accounts (decisions D30)")
import dataclasses  # noqa: E402

from kluis import accounts  # noqa: E402
from kluis.config import FolderPair  # noqa: E402

check(accounts.initials("lindi.kirsten@pm.me") == "LK" and accounts.initials("walter@agriland.com.na") == "WA",
      "F-002 initials like Proton's avatar")
check(accounts.display_name("lindi.kirsten@pm.me") == "lindi.kirsten", "F-002 account name from the email")
home = os.path.expanduser("~")
for n in ("AccDocs", "AccLindi"):
    os.makedirs(os.path.join(home, n), exist_ok=True)
st = Settings()
st.folders = [FolderPair(local=os.path.join(home, "AccDocs"), remote="/my-files/AccDocs", id="docs")]
check(accounts.adopt(st, "walter@agriland.com.na") is False and st.account == "walter@agriland.com.na"
      and [f.id for f in st.folders] == ["docs"], "F-006 an existing install's folders belong to the first account")
first = accounts.record(st, "walter@agriland.com.na")
check(first["cache"] == "" and accounts.state_path(first) == str(accounts.STATE_DB),
      "F-006 the first account keeps the CLI's default cache and Kluis's original sync history")
check(accounts.adopt(st, "WALTER@agriland.com.na") is False, "same account in other letter case: no switch")
check(accounts.adopt(st, "lindi.kirsten@pm.me") is True and st.account == "lindi.kirsten@pm.me"
      and st.folders == [], "F-004 signing in as another account shows that account's (empty) folder list")
lindi = accounts.record(st, "lindi.kirsten@pm.me")
check(bool(lindi["cache"]) and lindi["cache"] != first["cache"]
      and accounts.state_path(lindi) != accounts.state_path(first),
      "F-006 the second account gets its own CLI cache and sync history")
check(validate_local(st, os.path.join(home, "AccDocs")) ==
      "Your other Proton account walter@agriland.com.na already syncs AccDocs",
      "F-007 a folder the other account syncs is refused, with the account named")
check(st.overlaps(os.path.join(home, "AccDocs", "sub")) is not None, "F-007 also a folder inside it")
st.folders.append(FolderPair(local=os.path.join(home, "AccLindi"), remote="/my-files/AccLindi", id="lindi"))
st.photos.download = True
accounts.swap_profile(st, "walter@agriland.com.na")
check(st.account == "walter@agriland.com.na" and [f.id for f in st.folders] == ["docs"]
      and not st.photos.download, "F-003 switching back brings back exactly that account's folders and photo settings")
again = Settings.from_dict(json.loads(json.dumps(dataclasses.asdict(st))))
accounts.swap_profile(again, "lindi.kirsten@pm.me")
check([f.id for f in again.folders] == ["lindi"] and again.photos.download,
      "F-003 the other account's folders survive a save and reload")
check([r["email"] for r in accounts.others(again)] == ["walter@agriland.com.na"], "F-002 other accounts list")
accounts.forget(again, "walter@agriland.com.na")
check(not accounts.others(again) and again.account == "lindi.kirsten@pm.me", "F-009 remove an account from Kluis")
v = accounts.FileVault(os.path.join(TMP, "v"), os.path.join(TMP, "v-slot"))
check(v.read_live() is None, "F-003 empty keyring slot")
v.write_live({"secret": "lindi.kirsten@pm.me"})
v.save("Lindi.Kirsten@pm.me", v.read_live())
v.clear_live()
check(v.read_live() is None and v.load("lindi.kirsten@pm.me") == {"secret": "lindi.kirsten@pm.me"},
      "F-003 a kept session comes back for its account (any letter case)")
v.forget("lindi.kirsten@pm.me")
check(v.load("lindi.kirsten@pm.me") is None, "F-008 a signed-out account's kept session is deleted")
lockv = accounts.FileVault(os.path.join(TMP, "lv"), os.path.join(TMP, "lv-slot"))
open(os.path.join(TMP, "lv-slot.locked"), "w").close()
check(lockv.is_locked() and lockv.unlock() and not lockv.is_locked(), "a vault reports and clears a locked keyring")
check(accounts.Vault().is_locked() is False, "no keyring: never reported as locked")
check(accounts.Vault().available is False and accounts.Vault().load("x") is None,
      "F-005 without a keyring switching falls back to the browser sign-in")

from kluis.state import StateStore  # noqa: E402
StateStore(accounts.state_path(lindi))
check(os.path.exists(accounts.state_path(lindi)), "F-006 the second account's sync history opens in its own new folder")
from kluis.cli import RemoteNode  # noqa: E402
dev = RemoteNode.from_json({"uid": "u", "type": "Windows", "rootFolderUid": "r", "name": {"ok": True, "value": "WalterXPS"}})
check(dev.is_folder and dev.name == "WalterXPS", "F-013 a computer under /devices is a folder named after it")

print("CLI processes end with Kluis")
import subprocess  # noqa: E402
import time as _time  # noqa: E402

_script = "\n".join([
    "import sys, threading, time",
    f"sys.path.insert(0, {harness.REPO!r})",
    "from kluis.cli import ProtonDriveCli",
    f"c = ProtonDriveCli({harness.MOCK!r})",
    "threading.Thread(target=lambda: c.list('/my-files'), daemon=True).start()",
    "time.sleep(1.5)",
    "print(c._current.pid, flush=True)",
    "time.sleep(60)",
])
_p = subprocess.Popen([sys.executable, "-c", _script], stdout=subprocess.PIPE, text=True,
                      env={**os.environ, "MOCK_DELAY": "30"})
_child = int(_p.stdout.readline())
_p.kill()                                     # like a force quit: no cleanup code runs
_p.wait()
_time.sleep(2)


def _alive(pid):
    try:
        return "Z" not in open(f"/proc/{pid}/status").read().split("State:")[1].split()[0]
    except OSError:
        return False


check(not _alive(_child), "a force-quit Kluis leaves no CLI process running (no orphan downloads)")

diag = diagnostics.collect(st, "1.0")
check("lindi" not in diag and "walter@" not in diag and "AccLindi" not in diag,
      "F-006 Copy diagnostics names no account email and no other account's folders")

print(f"\n{check.passed} checks passed")
harness.cleanup(TMP)

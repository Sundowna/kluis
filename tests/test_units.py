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

print(f"\n{check.passed} checks passed")
harness.cleanup(TMP)

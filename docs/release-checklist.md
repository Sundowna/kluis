# Kluis 1.0.0 release checklist (HANDOVER §10)

Date: 2026-11-26 · Kluis 1.0.0 · Proton Drive CLI 0.9.0+75612299 (latest Stable on proton.me)

## Definition of done
- [x] **Inventory diff shows no dropped features:** `docs/redesign/inventory.md` (every 0.3.1 feature mapped; changes on purpose are marked ✎ with the reason)
- [x] **`docs/cli-capabilities.md` written; unsupported UI hidden:** Space used hidden (no quota command); trash Undo only for unique names (D25); video length not shown (D22)
- [x] **Tests A–C green in CI** (Ubuntu 24.04, Ubuntu 22.04, Arch/EndeavourOS KDE); screenshots in `docs/screens/` and every step in the workflow artifacts, both themes
- [x] **No sample or hard-coded data:** grep of the prototype's sample names (Agriland, SAP Projekte, SecondBrain, Kapstadt, Zürcher Reisebüros, Anna Meier, Jan de Wet, walter@proton.me, "38.2 of 200 GB", "↑ 1.2 GB") over `kluis/` returns nothing
- [x] **Accessibility:** keyboard-only flow F20 (Tab reaches every control the flows use, on every tab); every control has an AT-SPI name (F17); contrast ≥ 4.5:1 text and ≥ 3:1 UI parts in both themes (`tests/test_units.py`)
- [x] **Every flow F1–F19 (+F20) passes**, light + dark, 1440×900 + 1024×640, Mint Cinnamon and EndeavourOS KDE: results below
- [x] **`kluis --selftest` passes on Walter's machine against the real account:** 18 checks, 222 s, PASS (second run; the first run found D25 and was fixed)
- [x] **Version 1.0.0**; `packaging/release-notes.md` lists what's new and what's hidden and why
- [ ] Only then: install on the EndeavourOS machine (pacman package), Start at login on, Notifications: Problems only; the self-test runs by itself after install (D18)

## Test results (local, before CI)
| Suite | Result |
|---|---|
| `tests/test_lint.py` | 37 modules, 0 problems |
| `tests/test_engine.py` (0.3.1 scenarios, guard-aware) | 34 checks passed |
| `tests/test_photos.py` | 12 checks passed |
| `tests/test_safety.py` (§7, all 13 invariants) | 48 checks passed |
| `tests/test_units.py` (§8 A + contrast, 2 themes × 2 accents) | 104 checks passed |
| `tests/gui/perf_photos.py` (50'000 photos) | avg 5.7 ms/frame, p95 7.5 ms, peak RSS 184 MB: PASS |
| Self-test against the mock | 18 checks: PASS |
| Self-test against the real account | 18 checks: PASS, trash restored to its previous state |
| GUI flows, Mint Cinnamon (Xvfb) | 92 of 92 passed (local, Ubuntu/Noto fonts) · CI Ubuntu 24.04 green (DejaVu fonts) |
| GUI flows, EndeavourOS/Arch KDE (container) | 92 of 92 passed (local container) · CI Arch/EndeavourOS KDE green |
| `.deb` build | `dist/kluis_1.0.0_all.deb` |
| pacman package build/install/start/remove (Arch container, KDE) | PASS: depends on gnome-keyring, StatusNotifier panel icon, removes cleanly |

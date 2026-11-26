# Kluis 1.0 build plan

Branch `redesign-1.0`, small commits, full suite after each.

## A. Groundwork
- [x] Handover kit in `docs/redesign/`; inventory, CLI capabilities, decisions
- [x] Config 1.0: new keys, migration from 0.3.x, `.bak`, corrupt → backup (+ tests)
- [x] gettext wrapper `kluis/i18n.py`

## B. Engine safety (§7), each with a test in `tests/test_safety.py`
- [x] Staged downloads `.kluis-part` + atomic rename + leftover cleanup (inv. 7, 3)
- [x] Mass-deletion guard (inv. 8) → folder state `guard`, UI dialog
- [x] Missing-folder guard (inv. 9)
- [x] Offline / disk full / signed out / rate limit → paused state + exponential backoff ≤ 15 min (inv. 10)
- [x] Viewer shares always mirror (inv. 4)
- [x] Root-folder move with journal, resumable (inv. 6)
- [x] CLI capability self-test + atomic switch + daily check (inv. 12)
- [x] Network allow-list check: only CLI, proton.me, api.github.com (inv. 13)

## C. Pure logic (tests in `tests/test_units.py`)
- [x] Status text priority §4.2, ETA, transfer rate
- [x] Scrubber ring mapping (monotonic, ends on last dot)
- [x] VPN: NetworkManager reader, country → capital, timezone → city
- [x] World dot grid from Natural Earth 110m land (bundled)

## D. UI (GTK 3, kit CSS)
- [x] Window shell: sidebar, header, Quick settings column, status panel, toasts + Undo, theme switching
- [x] Onboarding (3-step stepper)
- [x] Home (map, VPN chip)
- [x] Folders (+ Add/Edit dialog)
- [x] Browse (TreeView, resizable columns)
- [x] Photos (cards, virtualised gallery, scrubber)
- [x] Shared with me
- [x] Activity
- [x] Settings dialog, All settings… menu, About, diagnostics
- [x] Panel icon + notifications
- [x] Safe logo + tray icons

## E. Tests and release
- [x] Mock CLI: restore, size, shared-with-me, offline/disk-full/expire switches, manifest + corrupt binary
- [x] GUI flows F1–F19, screenshots light/dark × 1440×900/1024×640
- [x] `kluis --selftest` (§8 D) + run against Walter's account
- [x] .deb build + install here; pacman build + flows in Arch/KDE container (podman)
- [x] CI: tests on PRs, release on main
- [ ] Version 1.0.0, release notes, release checklist, PR with screenshots

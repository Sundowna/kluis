# Kluis 1.0 build plan

Branch `redesign-1.0`, small commits, full suite after each.

## A. Groundwork
- [x] Handover kit in `docs/redesign/`; inventory, CLI capabilities, decisions
- [ ] Config 1.0: new keys, migration from 0.3.x, `.bak`, corrupt → backup (+ tests)
- [ ] gettext wrapper `kluis/i18n.py`

## B. Engine safety (§7), each with a test in `tests/test_safety.py`
- [ ] Staged downloads `.kluis-part` + atomic rename + leftover cleanup (inv. 7, 3)
- [ ] Mass-deletion guard (inv. 8) → folder state `guard`, UI dialog
- [ ] Missing-folder guard (inv. 9)
- [ ] Offline / disk full / signed out / rate limit → paused state + exponential backoff ≤ 15 min (inv. 10)
- [ ] Viewer shares always mirror (inv. 4)
- [ ] Root-folder move with journal, resumable (inv. 6)
- [ ] CLI capability self-test + atomic switch + daily check (inv. 12)
- [ ] Network allow-list check: only CLI, proton.me, api.github.com (inv. 13)

## C. Pure logic (tests in `tests/test_units.py`)
- [ ] Status text priority §4.2, ETA, transfer rate
- [ ] Scrubber ring mapping (monotonic, ends on last dot)
- [ ] VPN: NetworkManager reader, country → capital, timezone → city
- [ ] World dot grid from Natural Earth 110m land (bundled)

## D. UI (GTK 3, kit CSS)
- [ ] Window shell: sidebar, header, Quick settings column, status panel, toasts + Undo, theme switching
- [ ] Onboarding (3-step stepper)
- [ ] Home (map, VPN chip)
- [ ] Folders (+ Add/Edit dialog)
- [ ] Browse (TreeView, resizable columns)
- [ ] Photos (cards, virtualised gallery, scrubber)
- [ ] Shared with me
- [ ] Activity
- [ ] Settings dialog, All settings… menu, About, diagnostics
- [ ] Panel icon + notifications
- [ ] Safe logo + tray icons

## E. Tests and release
- [ ] Mock CLI: restore, size, shared-with-me, offline/disk-full/expire switches, manifest + corrupt binary
- [ ] GUI flows F1–F19, screenshots light/dark × 1440×900/1024×640
- [ ] `kluis --selftest` (§8 D) + run against Walter's account
- [ ] .deb build + install here; pacman build + flows in Arch/KDE container (podman)
- [ ] CI: tests on PRs, release on main
- [ ] Version 1.0.0, release notes, release checklist, PR with screenshots

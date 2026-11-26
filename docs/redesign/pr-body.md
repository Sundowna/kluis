## Kluis 1.0.0: the redesign from the handover

The approved prototype, built in GTK 3 on top of the same engine and CLI wrapper. Every 0.3.1 feature is kept
(`docs/redesign/inventory.md`), the CLI capabilities are checked against the real CLI (`docs/cli-capabilities.md`),
and every unclear point is decided on the safer side (`docs/redesign/decisions.md`, D1–D28).

![Home](docs/screens/home-dark.png)

| Folders | Browse | Photos |
|---|---|---|
| ![](docs/screens/folders-light.png) | ![](docs/screens/browse-dark.png) | ![](docs/screens/photos-dark.png) |
| **Shared with me** | **Add a folder** | **Purple accent** |
| ![](docs/screens/shared-dark.png) | ![](docs/screens/add-folder-light.png) | ![](docs/screens/purple-light.png) |

Every step of every flow is screenshotted in light and dark at 1440×900 and 1024×640. All of them are in the
workflow artifacts (`deb-24.04` → `flows-mint/`, `arch` → `flows-kde/`).

### What's in it
- New window: sidebar with search and today's timeline, Home map (offline, VPN-aware), Folders, Browse, Photos,
  Shared with me, Activity, status panel with transfer graph, collapsible Quick settings, toasts with Undo.
- Settings: Proton Drive folder (safe, resumable move), home location, Kluis update notices (notify only),
  accent colour (green or purple), Copy diagnostics.
- CLI always the latest official release: SHA-512, then a capability self-test, then an atomic switch.
- `kluis --selftest` against the real account, in its own folder only; it also runs by itself after an install or update.

### Safety (HANDOVER §7, all 13 rules tested in `tests/test_safety.py`)
Staged, verified downloads (`.kluis-part`), mass-deletion guard, missing-folder guard, pause and backoff for
offline / disk full / signed out, atomic config with `.bak`, viewer shares always mirror down, nothing deleted for good.

### Found and fixed along the way
- Real CLI: trash restore works only as `/trash/<name>`, so Undo is offered only when the name is unique (D25).
- Arch's `python-gobject` lacks the Cairo bridge, so the package now depends on `python-cairo` (D26).
- Mint-Y lacks some symbolic icons and paints its own switch marks: Kluis ships its own icons and styles (D28).
- Edits during a running sync were ignored until the next check (D20); the photo folder changed mid-run (D23).
- The layout fits 1024×640 with Ubuntu, Noto and DejaVu fonts; every flow fails if the window outgrows the screen.

### Tests
| Suite | Result |
|---|---|
| lint (imports, gettext shadowing, icons, Cairo bridge) | 0 problems |
| engine (0.3.1 scenarios) | 34 passed |
| photos | 12 passed |
| safety (§7) | 48 passed |
| units (status, ETA, ring mapping, migration, contrast for 2 themes × 2 accents) | 104 passed |
| GUI flows F1–F20 × light/dark × 1440×900/1024×640, Mint Cinnamon | RESULT_MINT |
| GUI flows, Arch/EndeavourOS KDE container | RESULT_KDE |
| 50,000-photo gallery | 5.7 ms/frame avg, 184 MB peak |
| `kluis --selftest` on the real account | PASS (18 checks) |

Release gate: `docs/release-checklist.md`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

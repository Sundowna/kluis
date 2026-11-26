## Kluis 1.0.0: a new look, the same safe engine

Kluis now looks like a companion to Proton VPN: a dark (or light) window with floating panels, a
Home map, and a status panel at the bottom. Everything that worked in 0.3.1 still works.

**Install**
- Linux Mint / Ubuntu: download `kluis_1.0.0_all.deb` and double-click it.
- EndeavourOS / Arch: `curl -LO https://github.com/Sundowna/kluis/releases/latest/download/kluis-latest-any.pkg.tar.zst && sudo pacman -U kluis-latest-any.pkg.tar.zst`

### New
- **Home**: a world map with your location (or your Proton VPN exit) and Proton Drive in Zürich. No network lookups: the VPN country comes from NetworkManager, your home city from Settings or the time zone.
- **Sidebar** with search (Ctrl+F), tabs (Ctrl+1…6), an Activity badge and today's timeline.
- **Quick settings** column (Pause, Notifications, Dark mode, Start at login, VPN view), which can collapse into the header.
- **Status panel**: in-sync time, last run, today's totals and a live transfer graph.
- **Folders**: size of each folder, Mode drop-down, Remove with Undo, and a confirm only when a change is riskier (to two-way).
- **Browse**: Files and Size columns for folders, resizable columns (mouse or ←/→), downloads to ~/Downloads, and **Undo for Move to trash** (restores from the Proton Drive trash).
- **Photos**: collapsible Download/Upload cards, a gallery grouped by month that stays smooth with 50,000 photos, and a month scrubber.
- **Shared with me**: sync items shared with you into a folder of your choice. Viewer items sync down only.
- **Settings**: move your Proton Drive folder (safe, resumable, with Undo), home location, beta access, Kluis update notices (notify only), and Copy diagnostics (no email, no tokens, no private paths).
- **The Proton Drive CLI is always the latest official release**: SHA-512 checked, then a capability self-test; a build that fails is never used.
- **`kluis --selftest`** proves your account works, in its own test folder only. It also runs once by itself after each install or update.

### Safer than ever
- **Mass-deletion guard**: if one sync would move more than 50 files (or more than 10 % of a folder) to a trash, Kluis pauses that folder and asks first.
- **Missing-folder guard**: an unplugged drive or a moved folder is never treated as "everything deleted".
- Downloads land in a hidden `.kluis-part` folder, are checked against Proton's SHA-1, then moved into place: no half-written files, even after a crash.
- Offline, disk full, signed out and rate limits pause syncing and retry with backoff (at most every 15 min), with no retry storms.
- Settings are saved atomically with a backup copy.

### Hidden, because the Proton Drive CLI can't do it (never faked)
- **Space used**: the CLI has no quota command, so the status panel shows no storage figure.
- **Video length** on gallery tiles: shown as ▶ only, because no duration is available without extra tools.

### Notes
- Search finds files in your synced folders and in folders you've opened in Browse. The CLI has no server-side search.
- On KDE, the package now depends on `gnome-keyring` so your Proton sign-in is remembered without KWallet.
- Not affiliated with Proton AG.

# Features

What Kluis does, one line per feature. Each line names the tests that prove it.
Sessions: read this before changing anything; never delete a line without the user's OK.

Run the tests: `python3 tests/test_units.py` (and the other `tests/test_*.py`, including `tests/test_windows.py`), and the GUI flows with
`tests/gui/run_all.sh /tmp/flows` (Xvfb, light/dark × 1440x900/1024x640); on Windows `python tests/gui/run_windows.py OUT`
and, after building the installer, `python tests/windows/test_install.py`. CI runs all of them on Mint (Cinnamon),
Arch (KDE) and Windows for every push and pull request.

## Before this ledger

Everything Kluis 1.0 does is listed in `docs/redesign/inventory.md` (0.3.1 → 1.0, nothing dropped) and proven by
GUI flows F1–F20 in `tests/gui/flows.py` plus the script suites in `tests/`. Those features don't have F-numbers here
yet — untested-in-ledger, not untested. A fresh-eyes audit (`e2e-fresh-eyes-audit`) should move them into this file.

## Proton accounts (decisions D30)

- F-001 The account button at the top right shows the active account's initials and name; it opens a menu with big initials, name, email, *Sign out* and *Other accounts* with a ⋮ menu — `tests/gui/flows.py: F21`
- F-002 *Other accounts* lists every other account Kluis keeps (initials, name, email, or "Signed out · sign in to switch"); a click switches to it — `tests/gui/flows.py: F21`, `tests/test_units.py: Proton accounts`
- F-003 Switching to an account with a kept session takes one click, no browser: that account's folders and photo settings come back and only that account syncs — `tests/gui/flows.py: F21`, `tests/test_units.py: Proton accounts`
- F-004 *Add another Proton account* (⋮ menu, the link under Other accounts, or Settings → Add…) opens Proton's browser sign-in, then *Pick folders*; the new account starts with no folders and nothing syncs while it signs in — `tests/gui/flows.py: F21`, `tests/test_units.py: Proton accounts`
- F-005 When a kept session no longer works (or there is no keyring), switching opens that account's sign-in page with "Use … instead" to go back — `tests/gui/flows.py: F21`, `tests/test_units.py: Proton accounts`
- F-006 Each account has its own Proton CLI cache and sync history; the first account keeps the existing locations, so an update changes nothing for one-account users — `tests/gui/flows.py: F21`, `tests/test_units.py: Proton accounts`
- F-007 A folder on this computer that one account syncs is refused for the others ("Your other Proton account … already syncs …") and isn't offered in *Pick folders* — `tests/gui/flows.py: F21`, `tests/test_units.py: Proton accounts`
- F-008 *Sign out* (asks first) ends the active account's session, deletes its kept copy and hands over to the next account; the account stays listed as signed out — `tests/gui/flows.py: F21`, `tests/test_units.py: Proton accounts`
- F-009 ✕ next to another account removes it from Kluis (asks first); its files stay on this computer and in Proton Drive — `tests/gui/flows.py: F21`, `tests/test_units.py: Proton accounts`
- F-010 Settings → *Other accounts* lists the kept accounts with *Switch*, and *Add…* for another one — `tests/gui/flows.py: F21`
- F-011 After adding or switching accounts, Browse, Shared with me and Photos show the active account's Proton Drive, never the previous account's — `tests/gui/flows.py: F21`

## Browse

- F-012 When *My files* is empty but Proton's desktop app syncs folders from a computer, Browse says "Folders synced from your computers are under Computers: …" with *Open Computers* — `tests/gui/flows.py: F22`
- F-014 Browse shows its sections as buttons with icons (*My files*, *Computers*, *Shared with me*), the current one highlighted; *↻ Reload* has a normal button border — `tests/gui/flows.py: F22`
- F-013 Computers (`/devices`) list each computer as a folder; opening one shows the folders it syncs — `tests/gui/flows.py: F22`, `tests/test_units.py: Proton accounts`
- F-017 Search (Ctrl+F) also finds names in all subfolders of the folder open in Browse (read in the background; "Still reading the subfolders…" until done); a hit opens the folder it is in — `tests/gui/flows.py: F22`

## Window

- F-016 On Browse and Photos the bottom status panel is one line (status, Encryption, Last run, Total today, a slim graph and ↓/↑ side by side); its chevron opens the full card, which that tab then keeps — `tests/gui/flows.py: F22`
- F-015 Collapsing or expanding Quick settings doesn't move *Sync now*, *Pause* or the account button — `tests/gui/flows.py: F13`
- F-018 Quick settings opens and closes with a small icon button at the far right of the header; its column starts level with the page content — `tests/gui/flows.py: F13`
- F-019 Activity: *Show*, *Open log folder* and *Clear* sit side by side in one row — `tests/gui/flows.py: F22`
- F-020 Every tab fits 960 px wide (half of a 1920 px screen), so Mint and KDE can snap Kluis to a side of the screen — `tests/gui/flows.py: F23`

## Windows (Kluis 1.2)

Same window, tabs and behaviour as on Linux; these lines are what Windows does differently.

- F-021 A file or folder in Proton Drive whose name Windows can't store (`: ? " < > | \ *`, a trailing dot or space, CON, NUL…) or that differs from a neighbour only in upper/lower case is left out: never downloaded under another name, never moved to a trash, untouched in Proton Drive; Activity says once which and why, and the rest of the folder syncs — `tests/test_engine.py: names Windows can't store`, `tests/test_units.py: Windows`, `tests/test_windows.py: names Windows tells apart`
- F-022 Windows letter case: notes.txt on this computer and Notes.txt in Proton Drive are one file (no duplicate, no conflict); folder checks (already syncing, inside, drive root) ignore case — `tests/test_engine.py: names Windows can't store`, `tests/test_units.py: Windows`, `tests/test_windows.py: names Windows tells apart`; straße.txt and strasse.txt are two files, like on Windows (fixed after audit 2026-11-26)
- F-023 Kluis's icon sits in the Windows notification area with the same menu as on Linux (status, Sync now, Pause, Open Kluis, Proton Drive on the web, Quit); a click opens Kluis; notifications come from the icon and a click on one opens Kluis — `tests/gui/flows.py: F24`
- F-024 Switching Proton accounts keeps each account's session in Windows Credential Manager (the CLI's own item `ch.proton.drive/drive-sdk-cli/auth-session`, copied byte for byte) — `tests/test_units.py: Windows`, `tests/test_windows.py: Credential Manager item`
- F-025 *Start at sign-in* adds Kluis to Windows' startup apps (registry Run key, `--hidden` with *Start hidden*); off removes it — `tests/gui/flows.py: F24`, `tests/gui/flows.py: F17`
- F-026 No console window flashes up when Kluis runs Proton's CLI or another program — `tests/test_lint.py`
- F-027 A file deleted in Proton Drive goes to the Recycle Bin on Windows (the Trash on Linux); on a drive without a Recycle Bin (USB stick, network share) Kluis leaves the file in place and says so — `tests/test_safety.py: 1`, `tests/test_engine.py: names Windows can't store`, `tests/test_windows.py: a drive without a Recycle Bin`
- F-028 One Kluis at a time: starting Kluis again brings the running one to the front — `tests/test_units.py: Windows`, `tests/windows/test_install.py`
- F-029 When Kluis ends in any way (Quit, crash, force quit), a running Proton CLI process ends too, on Windows as on Linux — `tests/test_units.py: CLI processes end with Kluis`
- F-030 `Kluis-Setup-<version>.exe` installs Kluis for the current user (no administrator rights) with a Start menu entry; uninstalling removes the program and its startup entry and keeps settings and files — `tests/windows/test_install.py`
- F-031 *System* theme follows Windows' app mode (light/dark), also when it changes while Kluis runs — untested (CI runners have one fixed mode)
- F-032 Changes on this computer sync by themselves on Windows too: one watch per synced folder notices changes in every subfolder, and subfolders and the folder itself can still be renamed or moved while Kluis runs — `tests/test_windows.py: changes on this computer`
- F-033 A file another program has open (Word, a video player) is not replaced: Activity says it is in use, the rest of the folder syncs, and the next sync brings the new version once it is closed — `tests/test_windows.py: a file open in another program`
- F-034 Updating Proton's CLI works while `proton-drive.exe` is still running: the running one is moved aside, the new one takes its place — `tests/test_windows.py: updating proton-drive.exe`
- F-035 A junction (Windows' link to another folder) inside a synced folder is not followed: nothing behind it is uploaded — `tests/test_windows.py: junctions`

## Removed

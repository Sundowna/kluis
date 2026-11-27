# Features

What Kluis does, one line per feature. Each line names the tests that prove it.
Sessions: read this before changing anything; never delete a line without the user's OK.

Run the tests: `python3 tests/test_units.py` (and the other `tests/test_*.py`), and the GUI flows with
`tests/gui/run_all.sh /tmp/flows` (Xvfb, light/dark × 1440x900/1024x640). CI runs all of them on Mint (Cinnamon)
and Arch (KDE) for every push and pull request.

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
- F-021 A locked keyring (automatic login) shows “Unlock your keyring”, never a new sign-in, and syncing carries on once it's unlocked — `tests/gui/flows.py: F24`, `tests/test_safety.py: 10`, `tests/test_units.py: status text priority`
- F-022 Settings → General → *Unlock the keyring at login* (on by default): a locked keyring at start brings up the desktop's password prompt by itself, and syncing starts once it's answered; a cancelled prompt isn't repeated; the setting turns on *Start at login* — `tests/gui/flows.py: F24, F24b`
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

## Sync Center (was Folders)

- F-023 Sync Center (Ctrl+2, the old Folders tab) lists My files, Computers and Shared with me one line per folder, in five columns: In Proton Drive (tick, files · size), Folder on this computer, How it syncs (⇄ ↑ ↓), Status, Warnings; below 1240 px a line wraps into two, so the tab still fits 960 px — `tests/gui/flows.py: F25, F23`
- F-024 Ticking or unticking a folder only marks the line (amber edge, “Starts/Stops when you apply”); a bar pinned at the bottom says what will change and how much to download, with *Discard changes* and *Apply changes* — `tests/gui/flows.py: F25`
- F-025 A ticked folder goes to `~/Proton Drive/<its path>` by default (*Change…* picks another place); folders inside a ticked one show as included, with its path and mode — `tests/gui/flows.py: F25`
- F-026 When `~/Downloads/<name>` holds an earlier one-off download, the line warns “Already here” and *Use that copy* moves it into place on Apply instead of downloading again — `tests/gui/flows.py: F25`
- F-027 *Show: Everything in Drive / Synced only* (remembered); each synced line keeps what the Folders card had: status and progress, ↻ Sync now, Review…, and in ⋯ Open, Pause/Resume, Edit…, Show in Kluis browser, Open on the web, Check every file again, Stop syncing (with Undo) — `tests/gui/flows.py: F25, F6, F20`
- F-029 Files/Size counts of Proton Drive folders are kept on disk per account (`~/.cache/kluis/folder-counts-<id>.json`, mode 600, folder paths and numbers only, no email): Browse and Sync Center show them at once after a restart; a count older than a day is counted again in the background; ↻ in Sync Center counts again now; names for search in subfolders are read when you search and stay in memory — `tests/test_units.py: folder counts kept on disk`, `tests/gui/flows.py: F22, F25`
- F-030 A ↓ Mirror down run that didn't finish (Kluis quit or crashed, Stop, offline) continues on the next run with the Proton Drive folder listings it already has, if they are under 2 hours old, so a restart doesn't list every folder again; a completed run throws them away, so ordinary syncs list fresh; two-way and back-up runs never keep listings (an edit made in Drive meanwhile must be seen) — `tests/test_engine.py: an unfinished run continues`, `tests/gui/flows.py: F14, F14b`
- F-028 Browse → *⇄ Sync to this computer…* opens Sync Center at the ticked or open folder, ticked and waiting for Apply; *↓ Download* says it is a one-off copy — `tests/gui/flows.py: F25`

## Window

- F-016 On Sync Center, Browse and Photos the bottom status panel is one line (status, Encryption, Last run, Total today, a slim graph and ↓/↑ side by side); its chevron opens the full card, which that tab then keeps — `tests/gui/flows.py: F22`
- F-031 The left sidebar collapses to a 56 px icon rail (its ▯ button or Ctrl+B, remembered): one icon per tab with its tooltip and the Activity badge, a search icon (Ctrl+F opens the sidebar), Settings; Sync Center's one-line table never sets the window's minimum width, so a maximized Kluis snaps to half a screen — `tests/gui/flows.py: F23, F25`
- F-015 Collapsing or expanding Quick settings doesn't move *Sync now*, *Pause* or the account button — `tests/gui/flows.py: F13`
- F-018 Quick settings opens and closes with a small icon button at the far right of the header; its column starts level with the page content — `tests/gui/flows.py: F13`
- F-019 Activity: *Show*, *Open log folder* and *Clear* sit side by side in one row — `tests/gui/flows.py: F22`
- F-020 Every tab fits 960 px wide (half of a 1920 px screen), so Mint and KDE can snap Kluis to a side of the screen — `tests/gui/flows.py: F23`

## Removed

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

## Removed

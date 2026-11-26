# Decisions made while building Kluis 1.0

The handover (§11.5) says: when something is unclear, choose the safer option, log it here and carry on.
Each entry has the question, the choice, and why.

**D1 · GUI test driver.** §8 B names dogtail/AT-SPI. The flows are driven *in-process*: the test loads
Kluis into the same Python process under Xvfb and acts on widgets found by their **accessible names**
(the same ATK names AT-SPI exposes), with real `clicked`/`activate`/key events. *Why:* dogtail over the
session bus is timing-sensitive under Xvfb (it polls a separate bus), which makes flaky tests, and
flaky tests can hide real bugs. Every control still has to carry an accessible name, or the test can't find it.

**D2 · "Network drop mid-upload" in `--selftest`.** Blocking one process's traffic needs root (a network
namespace or firewall rule), and the self-test must run without a password. The self-test instead
**kills the CLI process mid-upload**, which drops its connection just as a network loss would, then checks
that the next sync finishes with no duplicates and matching SHA-1s. CI covers a real "offline" state through the mock CLI.

**D3 · Downloads never half-write or delete first.** The engine used `--file-conflict-strategy remove`,
which deletes the local file before the new one arrives. Now each download goes into
`<folder>/.kluis-part/<run>/`, its SHA-1 is checked against Proton's, and then it is renamed into place
(`os.replace`, atomic on the same drive). If the local file changed since the scan, it becomes a conflict copy
instead. Leftover `.kluis-part` folders (after a crash) contain only Kluis's own partial downloads and are
cleared on the next sync. `.kluis-part` is always skipped by the scanner.

**D4 · Folder sizes and counts in Browse.** `filesystem size` counts *trashed* items too, so it would
over-report. Files/Size for folders are computed from a recursive listing of active items, lazily for
visible rows, and cached. "…" shows while counting; nothing is guessed.

**D5 · Space used hidden.** The CLI has no quota command, so the status-panel cell is hidden (never faked).

**D6 · Transfer rate.** The CLI reports no live progress. The graph's rate comes from the bytes of each
finished CLI batch over its duration, spread across that batch's seconds. It reads 0 when idle or paused.

**D7 · Old setting values.** `notifications: "important"` (0.3.x) becomes `"problems"`. `interval_minutes`
snaps to the nearest of 5/15/30/60. New keys get defaults. A `.bak` is written before every save.

**D8 · Missing-folder guard.** A folder counts as "not found" (sync paused, nothing trashed) when its
path is missing, unreadable, or **empty while the last sync recorded files in it**. An unmounted drive
often leaves an empty mount-point directory behind, and treating that as "everything was deleted" is the
dangerous case.

**D9 · Mass-deletion guard thresholds.** As specified: more than 50 files, or more than 10 % of the
folder's files, in one run (local and remote trash counted together, files inside trashed folders included).
Small folders will ask more often (deleting 2 of 10 files asks). That's the safer side, so it is kept exactly as specified.

**D10 · Kluis update check switch.** §7.13 says the GitHub check runs "only if updates are enabled", but
§3.8 lists no such switch. Settings → General has **"Tell me about Kluis updates"** (on by default), next to Beta access.

**D11 · Language.** Only English ships, so the Language row is hidden (§2). Strings are wrapped in gettext.

**D12 · Self-test cleanup.** `--selftest` is the only code that calls `filesystem delete`, and only on the
`/Kluis-selftest-<random>` folder it created, after it is in the trash (by uid).

**D13 · VPN connections without a country code.** When NetworkManager shows an active VPN whose name has
no recognisable country (e.g. a custom WireGuard profile), the chip says "VPN on" and the caption
"Location unknown". The pin stays at the home location. Nothing is looked up online.

**D14 · Browse download target.** As §3.4 says, files go to `~/Downloads` (the folder chooser from 0.3.1 is
gone). Existing names are never overwritten: the CLI's `rename` strategy adds a suffix.

**D15 · Files Proton reports without a SHA-1.** Invariant 3 needs a SHA-1 to compare. Files Proton lists
without one (older uploads from other apps) are confirmed by size after an upload; the first time such a
file meets a local file of the same name, Kluis keeps both copies rather than guessing they are equal.

**D16 · Scrubber ring mapping.** The review asked for "the month in the middle of the viewport". That conflicts
with F9 step 8 (heading at the top → ring on that dot) and leaves the first months unreachable. The ring follows
the month at the **top edge**, interpolated inside the month; over the last viewport-height it eases to the last
dot; and the gallery has one viewport of room after the last month, so every month can reach the top. The result
is monotonic, never jumps more than one dot, starts on dot 0 and ends exactly on the last dot (unit-tested on 30
random libraries, and in F9).

**D17 · Search (Ctrl+F).** The CLI has no search, and crawling the whole drive would be slow and noisy. Search
looks through file names Kluis already knows: everything in synced folders (from the sync state) and folders
opened in Browse. Choosing a hit opens its folder in Browse.

**D18 · Self-test after install.** A package's post-install script runs as root, without the user's keyring
or Proton session, so it can't run `--selftest`. The app runs the self-test once by itself, in the background,
the first time it starts with a new Kluis or CLI version (and only when signed in). On FAIL, syncing pauses with
one notification, as §8 D asks.

**D19 · How the flows are split.** Steps that need a real relaunch or a fresh login session are separate
runs on the saved state: F3b (relaunch resumes the step), F14b (relaunch after a kill: no `.kluis-part`,
nothing lost), F17b (autostart with Start hidden). The 5-minute sign-in timeout uses a mock clock
(`KLUIS_SIGNIN_TIMEOUT`). Native file choosers are answered through a test-only queue (`KLUIS_TEST=1`).

**D20 · Changes during a running sync.** A local edit or a manual request while that folder is syncing used to
be ignored until the next periodic check (up to 60 min). Now it always triggers one more run right after,
so "local edits sync ~10 s after you save" holds even mid-sync. Found by the flows.

**D21 · Mint versions in CI.** There are no Linux Mint images for CI runners. Mint 22 and Mint 21.3 are based on
Ubuntu 24.04 and 22.04, so CI installs, starts and removes the `.deb` on those. The real Mint 22.3 install
is done on Walter's machine. EndeavourOS runs as an Arch container with KDE session variables.

**D22 · Video length badge.** The prototype shows "▶ 0:23". Nothing available gives a reliable duration
without extra tools, so the badge shows ▶ only (never a made-up time).

**D23 · Photo download folder change during a run.** Changing the folder while photos download now stops that run
and resets the download records only after it has ended, so no photo is recorded against the old folder.
Found by F9.

**D24 · Photos "follow deletions" and the mass-deletion guard.** When far more photos than usual (over 50, or
over 10 %) disappear from Proton Photos in one check, Kluis keeps every local copy and logs a warning instead
of asking. Photo copies are never synced back, so keeping them is always safe.

**D25 · Trash restore works by name only.** Found by the first `--selftest` run against the real account: the CLI
resolves trashed items as `/trash/<name>`, not by uid. A name can repeat in the trash (someone may have trashed
another "Notes.txt"), and restoring or deleting by name could then hit the wrong item. So Kluis offers Undo, and
the self-test permanently deletes its own items, **only when each name is unique in the trash**. Otherwise the
item stays in the Proton Drive trash, where it can be restored on the web. The mock CLI now behaves like the real one.

**D26 · Cairo bridge as a hard dependency.** Found by the Arch/KDE container run: Arch's `python-gobject` does not
pull in `python-cairo`, and without it every Cairo drawing (Home map, photo gallery, transfer graph) fails silently.
The pacman package now depends on `python-cairo` and the `.deb` on `python3-gi-cairo`. Kluis checks for the bridge at
start (`gi.require_foreign("cairo")`), `tests/test_lint.py` checks it, and every GUI flow now fails on any uncaught
exception in a GTK callback (before, those were only printed).

**D27 · Purple accent (Walter's request, 2026-11-26).** Settings → General → Accent colour: Green (the kit) or
Purple, for people used to Proton's apps. Light uses Proton's own #6d4aff, dark a lighter #9b7dff so text and
controls keep ≥ 4.5:1 / ≥ 3:1 contrast (unit-tested for every theme × accent). The logo stays green.

**D28 · Controls look the same on every desktop theme.** Found on the installed app: Mint-Y draws its own ✓/×
images and colours on switches, and lacks some symbolic icons (the Quick settings button was blank). Switches,
check boxes and radio buttons are now fully styled by Kluis in every state, and the UI's icons (sliders, gear,
chevrons, ⋯) ship with Kluis. A lint test fails if a named Kluis icon is missing.

**D29 · SVG loader as a hard dependency.** Found on CI: without GdkPixbuf's SVG loader, Kluis's own icons and the
logo show as "missing image". The pacman package depends on `librsvg` and the `.deb` on `librsvg2-common`;
`tests/test_lint.py` fails without the loader.

**D30 · More than one Proton account (Walter's request, 2026-11-26).** Like Proton's own account menu
(account button at the top right → active account, *Sign out*, *Other accounts* with ⋮), in Kluis's look.
Proton's CLI keeps exactly one session per Linux user, in one fixed keyring item (service
`ch.proton.drive/drive-sdk-cli`). Kluis therefore copies the CLI's keyring item, unchanged and with the exact schema
and attributes the CLI wrote, into its own keyring entry per account ("Kluis: Proton session for …"), and puts the
chosen account's copy back to switch. Kluis never reads or changes what is inside a session. Before a switch the
current session is copied again, because the CLI rotates its tokens. Switching clears the slot locally and never
runs `auth logout`, which would end the kept session at Proton. If a kept copy no longer works, or there is no
keyring, Kluis opens Proton's browser sign-in for that account, with "Use … instead" to go back.
Each account has its own `PROTON_DRIVE_CACHE_DIR` (the CLI's caches are encrypted per session) and its own
`state.sqlite`, so a sync can never act on another account's files. The first account keeps the original locations,
so existing installs change nothing. Only the active account syncs. A local folder synced by one account is refused
for the others. *Sign out* ends the active session (`auth logout`) and hands over to the next kept account.
Tests: `tests/test_units.py` (accounts) and GUI flow F21; FEATURES.md F-001…F-009.

**D31 · Big items get their own lane (Walter's request, 2026-11-26).** Backups of several hundred GB, and folders of
photos of many GB, held up every other change for hours, because Kluis synced one folder at a time and one CLI call
at a time. Proton's CLI copes with more than one process (its caches are SQLite in WAL mode with a busy timeout;
only one process holds `events.lock` and listens for events, the others just don't), so a second copy now runs
next to the normal sync: the big-items lane (`kluis/lane.py`). A sync run hands it every file of at least 1 GB and,
deepest folder first, every folder with at least 1 GB still to transfer (files directly in the synced folder only
go as big files, so the lane never swallows a whole folder). The lane does one item at a time with the engine's
own upload/verify and download/stage/verify code, staging under `.kluis-part/lane`, which a normal run leaves
alone. While an item waits or runs, and while the user has paused it (`FolderPair.held`, kept over restarts),
the normal sync leaves its paths out of the plan entirely, trashes included. Pausing a running item stops its CLI
process; the CLI can't resume, so that file starts over later (said in the toast and the README's known limits).
*Send first* never interrupts the running item, for the same reason. Paused items resume by themselves after
`resume_paused_after` minutes (default 5) without other syncing, so a forgotten pause doesn't keep a backup out of
Proton Drive. Photos timeline sync (`kluis/photos.py`) is not part of the lane.
Tests: `tests/test_lane.py`, `tests/test_units.py` (big items), GUI flow F25; FEATURES.md F-036…F-039.

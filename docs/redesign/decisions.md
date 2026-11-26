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

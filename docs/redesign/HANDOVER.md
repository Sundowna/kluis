# Kluis 1.0 — GUI redesign handover for Claude Code

**Date:** 2026-11-26 · **Build kit in this zip:** `kit/design/` (GTK CSS for both themes, tokens.json, safe logo + symbolic icon, dot-map prototype script), `kit/tests/flows.json` (F1–F19, machine-readable), `kit/docs/review-log.md` (every design decision from the chats).
**From:** Walter (design reviewed in claude.ai; canvas: https://claude.ai/artifact/RYWQYA1ri4UBnewt3YD1nm, sign-in needed, everything required is in this zip) · **For:** Claude Code, working in `github.com/Sundowna/kluis`
**End user:** Walter's sister, on **EndeavourOS (KDE Plasma)** with **Proton VPN**. Walter will not provide support. **Rock solid beats feature-rich**: if something can't be made reliable, hide it rather than ship it half-working.
**Testing:** there is **no test account and no manual user testing**. Everything is proven by the automated end-to-end flows in §12 (mock CLI) plus the automatic self-test against the real account in §8 D. That makes the safeguards in §7 the last line of defence; implement them exactly.

> Ground rules for Claude Code
> 1. **Read the repo first.** Build a feature inventory from the *code* (not just this doc) and diff it against §9. Nothing that exists today may be dropped (rule W11). If you find a feature not listed here, keep it and add it to the inventory.
> 2. **Never fake data.** Every number on screen comes from the CLI, the sync engine or the file system. If the CLI can't provide something (see §6 "verify"), hide that UI and log why. No sample values in the shipped app.
> 3. **Safety invariants in §7 are non-negotiable.** Each one has a test.
> 4. **Nothing is "done" until §10 (release gate) passes.** Every flow in §12 is an automated test.
> 5. Work in small commits, run the full test suite after each, and keep the 33 sync + 12 photo scenario tests green.

---

## 1. What we're building

A redesign of Kluis's GTK window. It's the same app, engine and CLI wrapper, with a new interface modelled on the clickable prototype Walter approved:

- **Prototype (source of truth for look, copy and flows):** canvas page "Kluis prototype", board `Kluis.dc.html` (included in this pack as `reference/Kluis.dc.html`). Read its markup for exact wording, states and layout. The `<script>` block shows every state transition. All names, sizes and figures in it are **sample data**.
- **Visual language:** a dark, medium-grey window with a green glow across the top, floating rounded panels, a Proton-VPN-style status panel at the bottom, and a collapsible Quick settings column on the right.

### Window layout (1440 × 900 default, min 1024 × 640)

```
┌ title bar (system) ─────────────────────────────────────────────────────────┐
│┌ Sidebar 280px ┐┌ Main ─────────────────────────────────────┐┌ QS 100px ┐ │
││ ⚙ Kluis   [⚙] ││ Tab title            [↻ Sync now][⏸ Pause]││ ⚙ All    │ │
││ [Search… ^F]  ││                                          ││ settings │ │
││ Home      ^1  ││   CONTENT (per tab, see §3)               ││ ──────── │ │
││ Folders   ^2  ││   only Photos' gallery scrolls             ││ Quick    │ │
││ Browse    ^3  ││                                          ││ settings │ │
││ Photos    ^4  ││                                          ││ toggles  │ │
││ Shared    ^5  ││                                          ││          │ │
││ Activity  ^6  │├──────────────────────────────────────────┤│          │ │
││ Today's       ││ STATUS PANEL (all tabs, §4.3)            ││          │ │
││ timeline      ││                                          ││          │ │
│└───────────────┘└──────────────────────────────────────────┘└──────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```
When Quick settings is collapsed, its column disappears, its toggle button moves into the header row after Pause, and Main takes the width.

---

## 2. Architecture decisions (already made, don't re-litigate)

| Topic | Decision | Why |
|---|---|---|
| Toolkit | Keep **Python + GTK 3** (current code), restyle with a `Gtk.CssProvider` stylesheet | Ships on Linux Mint 21/22 and EndeavourOS with no new dependencies; a GTK4 port is a separate project |
| Backend | Unchanged: `kluis/cli.py` (official `proton-drive` CLI), `engine.py`, photo engine | Already tested, the only place file operations happen |
| Threads | All CLI calls stay off the GTK main thread (existing `run_bg`). The UI never blocks for >100 ms | No frozen window, ever |
| Map | Offline world map, drawn with Cairo from a bundled **Natural Earth 110m land** dataset (public domain), simplified to a dot grid like the prototype | No network calls, no tile servers, private |
| VPN view | **Always on** (Home map + chip). With a VPN active, the pin shows the VPN exit; without one, it shows her home location | Walter's decision |
| "You" location | **VPN on:** read the active VPN connection from NetworkManager (D-Bus `org.freedesktop.NetworkManager`, connection id like `ProtonVPN CH#23`) and map the country code to a capital-city coordinate (bundled table). **VPN off / unknown:** use "Home location" from Settings (city picker, default from system timezone). **Never** call a geo-IP service | Privacy-first, no surprises |
| Cloud pin | Proton Drive data is in Switzerland; draw the cloud pin at Zürich | Matches Proton's own statement |
| Theme | System / Light / Dark; tokens in §5 | |
| i18n | Wrap all strings in gettext now. Ship **English**. The Language menu lists only languages with a 100 % complete catalogue (so with English only, hide the setting) | No half-translated UI |
| Proton CLI version | **Always the latest official release.** Never pinned. On every start and once a day: check proton.me, download, verify the SHA-512, then run the **capability self-test** (§6) on the new binary. Pass → switch atomically. Fail → keep the previous binary *only* to stay safe, pause nothing, and show one notification: "Proton changed its Drive tool. Kluis needs an update for it." Retry daily. | We don't maintain the CLI or tie ourselves to a version |
| Kluis app updates | **Notify only** ("Kluis 1.0.1 is available" with a link to the GitHub release). Never install automatically. Beta access = also notify for pre-releases | Walter's decision |
| Primary platform | **EndeavourOS + KDE Plasma** (StatusNotifier tray, KWallet → install gnome-keyring via the package dependency). Linux Mint Cinnamon stays fully supported | Sister's machine |
| Persistence | Existing `config.json` (XDG). Add new keys with defaults; migrate old configs silently; keep a `.bak` before writing | Upgrades never lose settings |

---

## 3. Screens and flows

For each screen: **purpose · content · actions · states · data source**. Wording follows the prototype; take exact copy from `reference/Kluis.dc.html`.

### 3.0 Onboarding (first run; also menu → "Run setup again"; also after Sign out, at step 2)
- **Step 1 of 3 — Get the official Proton Drive CLI.** Button "Download from proton.me" → progress "12.4 of 38.0 MB" → "✓ Downloaded · proton-drive 0.9.x · SHA-512 checksum matches". On checksum mismatch: delete the file, show "The download didn't match Proton's checksum, so it was deleted. Try again." Next is disabled until it succeeds.
- **Step 2 — Sign in to Proton.** "Open Proton sign-in" opens the browser (existing CLI auth flow) → "Waiting for your browser…" → "✓ Signed in as <email>". Show the KDE note (gnome-keyring) **only** on KDE sessions. Timeout after 5 min, with "Sign-in didn't finish. Try again."
- **Step 3 — Pick folders.** Toggle chips for Documents, Pictures and Desktop (only those that exist), "+ Other folder…" opens the folder chooser. Each starts as two-way. "Start syncing" goes to Home and starts the first sync.
- Back/Next on every step; the stepper shows "Step N of 3". Closing the window mid-setup resumes at the same step next launch.

### 3.1 Home (landing page, Ctrl+1)
- VPN chip ("VPN on" / "VPN off", read-only state from NetworkManager; clicking opens the Proton VPN app if installed, otherwise does nothing) + caption "Showing as <city>" / "Your location <city>".
- Big status title + subtitle (same text as the Folders status, §4.2).
- World dot map: cloud pin (Zürich) and "You" pin with a pulse, and an animated dashed arc between them while syncing (static when idle or paused). Label "You · <city> (VPN)".
- No scrolling.

### 3.2 Folders (Ctrl+2)
- Status card: icon, title and subtitle (§4.2) + **"+ Add folder"** (Ctrl+N).
- One card per synced folder: on/off **switch**, name + **size chip** (du of the local folder, computed in the background, "Measuring…" until known), path line `<local> ⇢ Proton Drive<remote>`, status line (amber if conflict copies exist), **Mode** drop-down (⇄ Two-way / ↑ Back up / ↓ Mirror down), **↻ Sync** (this folder only; disabled when off or paused), **Open** (file manager), **Remove** (stops syncing and keeps files on both sides; toast with **Undo** for 8 s).
- Drop zone: "Drag a folder onto this window to start syncing it" (drag a folder anywhere on the window → Add-folder dialog prefilled).
- Mode legend under the list.
- Empty state: "Ready when you are" + Add folder.
- Changing mode: **confirm only when it's riskier**, i.e. switching *to* Two-way from Back up or Mirror down: "Two-way sync also sends deletions. Switch <name> to two-way?" with buttons "Switch to two-way" / "Keep <current mode>". Other mode changes: toast.

### 3.3 Add-folder dialog
- "Folder on this computer" button (folder chooser), "Folder in Proton Drive" button (remote folder picker reusing the Browse view; default `<root>/<local name>`), mode radio cards with one-line explanations, "Cancel" / "Start syncing".
- Validation: refuse a folder that is already synced, nested inside or containing a synced folder, the home folder itself, `/`, or the Kluis config dir. Show the reason beside the field.

### 3.4 Browse (Ctrl+3) — Proton Drive file browser
- Breadcrumbs (`My files › …`, each clickable). Toolbar: **↑ Upload…** (file chooser, multi-select), **+ New folder** (name dialog), **↓ Download** (to `~/Downloads`, toast with "Show in folder"), **Rename** (exactly one selected), **Move to trash** (red; confirm "Move N item(s) to the trash? You can restore them from the Proton Drive trash." with buttons "Move to trash" / "Keep files"; afterwards a toast with **Undo** that restores from trash).
- Columns: checkbox · Name · **Files** (folders: item count, files: —) · **Size** (folders: total) · **Modified** (YYYY-MM-DD). **Every column is resizable** (drag the header edge; keyboard ←/→ on a focused divider); widths are saved per table in config.
- Click a folder to open it; Enter/double-click opens files with the default app (download to the cache first).
- Drag files onto the list to upload into the current folder.
- States: loading (skeleton rows after 300 ms), empty folder ("This folder is empty. Drag files here to upload them."), error ("Couldn't load this folder: <reason>" + Retry), offline.
- Folder counts and sizes: use CLI listing data if available; otherwise compute lazily per visible folder and cache. **Verify** (§6).

### 3.5 Photos (Ctrl+4)
- Two **collapsible cards** (start collapsed; the **whole header row** toggles; chevron points **down when closed, up when open**):
  - **↓ Download** (switch in the header, outside the toggle area): path row (path opens the folder · "Change…" folder picker), layout drop-down (by month `2026/2026-11` / by year / one folder), "Also save albums as folders", "If a photo is deleted in Proton, move my copy to the Trash", status line. When collapsed, only the status line shows.
  - **↑ Upload**: path row (path · "Change…"), note "Photos you downloaded above are never uploaded again.", status "N new added · M skipped (already in Proton Photos)".
- Toolbar: Gallery heading · Album drop-down · "N selected" · **Open** (exactly one) · **↓ Download selected**.
- **Gallery** grouped by month (year headings where the year changes, "Month YYYY · N items"). Tiles are square thumbnails; videos get a "▶ 0:23" badge; click toggles selection (✓ badge, green border); double-click opens.
- **Only the gallery scrolls** (everything above it stays fixed). Scrollbar style §5.
- **Month scrubber** on the right of the gallery: a vertical line with **one dot per month in the library, evenly spaced**, plus year labels. A ring with a month label ("Jun 2026") marks the month in view, and the line above the ring fills green.
  - Click a dot → smooth-scroll to that month.
  - **Ring mapping (fix from the review):** the ring follows the month at the *middle* of the viewport, interpolated within the month. Over the last viewport-height of content, ease the ring across the remaining dots so it reaches the last dot exactly at the bottom. **No jumps.** The ring and the scrollbar move independently.
- Thumbnails: existing thumbnail pipeline (local file → GdkPixbuf; Proton-only → download once, keep about 20 KB thumbnail, delete original; video → system thumbnailer). Load lazily for visible rows only; virtualise rows so 50'000 photos stay smooth.

### 3.6 Shared with me (Ctrl+5) — **only if the CLI supports listing shares** (verify, §6); otherwise hide the tab
- "N of M items synced" heading. Table: Permissions · Name (sheet/doc/folder icon) · Shared by · **Local folder** (path opens it · folder-icon picker; default `<Proton Drive folder>/Shared with me/<name>`, dimmed until synced) · Shared on (sortable ▼/▲) · **Sync** switch with an ⓘ tooltip.
- Editor items sync two-way; **Viewer items sync down only** (enforce Mirror-down mode; tooltip says why).
- Turning Sync off keeps the local copy (toast says so). All columns resizable.

### 3.7 Activity (Ctrl+6)
- Filter Everything / Problems only · "Open log folder" · "Clear" (toast with Undo).
- Rows: coloured icon (✓ ok / i info / ! warning / ✕ error) · text · detail line · time. Errors always say what happened and what Kluis will do ("will retry at 07:31").
- Empty state "Nothing yet. Sync activity shows up here."
- Sidebar badge: the count of unread warnings and errors (cleared when Activity is opened).

### 3.8 Settings (dialog; Ctrl+, · sidebar gear · All settings… → Settings)
1. **Your Proton Drive folder:** Location path · ✓ when it exists and is writable (⚠ otherwise) · "Change…". Moving it **moves** the contents (progress dialog, cancellable, atomic per item); Undo for 8 s.
2. **General:** Start at login (switch) · Start hidden (switch) · Check Proton Drive every 5/15/30/60 min (local changes are watched instantly) · Theme System/Light/Dark · Notifications All/Problems only/Off · Language (hidden while English only, §2) · Beta access (switch: also offer Kluis *pre-release* updates) · Home location (city, used when no VPN is detected).
3. **Proton Drive CLI:** version, "Always uses the latest official version", last checked HH:MM, "Check now" (checksum-verified, progress, "✓ Up to date"). No version pinning option.
4. **Account:** email · "Sign out…" (confirm: "Syncing stops until you sign in again. Your files stay on this computer and in Proton Drive." with buttons "Sign out" / "Stay signed in").
5. Footer: shortcuts list · version · "Not affiliated with Proton AG".
6. **New: "Copy diagnostics"** button: copies the app version, CLI version, distro, desktop, last 200 log lines and config (with **no paths outside the synced folders, no email, no tokens**) to the clipboard, so Walter's sister can paste it to him if ever needed.

### 3.9 All settings… menu (top of the Quick settings column)
⚙ "All settings…" opens a menu: + Add folder (Ctrl+N) · Settings (Ctrl+,) · Run setup again · About Kluis · Quit (Ctrl+Q). Quit really quits; closing the window only hides it (§4.5).

### 3.10 Quick settings column
Order: **⚙ All settings…** → fading divider → small heading "Quick settings" → toggles: Pause sync · Notifications (cycles All → Problems only → Off) · Dark mode · Start at login · VPN view (shows or hides the VPN chip and pin on Home). Each toggle shows a pressed state + "On/Off" text. The header button (sliders icon + ▾, 36 px, same style as Sync now/Pause) collapses the column; state is saved.

### 3.11 Panel icon (XApp on Cinnamon/MATE/Xfce, StatusNotifier on KDE) — unchanged features
Menu: status line · Open Kluis · Sync now · Pause/Resume syncing · Quit. Icon variants: idle / syncing / paused / problem.

### 3.12 Desktop notifications
Respect the Notifications setting. Problems: conflicts kept, failed uploads after retries, sign-in expired, disk full, CLI update available. Never more than 1 per 30 s (batch: "3 files couldn't upload").

---

## 4. Global behaviour

### 4.1 Header actions
**↻ Sync now** (Ctrl+R) becomes **Stop** while syncing (stopping keeps finished files; toast "Stopped at 27 of 40 · nothing lost"). **⏸ Pause / ▶ Resume** toggles (pressed style while paused).

### 4.2 Status text (shared by Home, Folders, status panel, panel icon)
Priority: Paused → Syncing → Problems → No folders → Up to date.
- Paused: "Sync paused — your files are safe" / "New changes wait on this computer until you resume" (amber)
- Syncing: "Syncing 27 of 40 files" / "From <city> [via VPN] to Proton Drive · about 12 sec left"
- Problems: "N folder(s) need attention" / first problem's text (red)
- Up to date: "Everything is up to date" or "Up to date · N with conflict copies" / "Watching N of M folders · local edits sync ~10 s after you save · Proton Drive checked HH:MM"
- **No "next sync" countdowns** (Walter's review: local folders are watched; only the remote check is periodic).

### 4.3 Status panel (bottom of Main, Proton-VPN style, no card)
Left: 🔒 **In sync** • for 2 h 14 min (or "Syncing • started HH:MM", "Paused • paused HH:MM"); a 2×2 grid: Encryption "End to end" · Space used "X of Y GB" + mini bar · Uploading/Last run "N of M files" + mini bar + ETA · Total today "↑ 1.2 GB · ↓ 214 MB".
Right: "Current transfer (KB/s)" with ↓/↑ figures, a 0/8/16 auto-scaled axis, dashed gridlines, a solid green download line and a dashed red upload line over the last 2 minutes (1 sample/s). Flat at 0 when paused or idle.
**Space used**: from the CLI account/quota info; hide the cell if unavailable (verify §6).

### 4.4 Toasts and Undo
Bottom-centre toast, 5 s (8 s when it has **Undo**). One at a time; new replaces old. Announced to screen readers (`Gtk.Accessible`/ATK live region). Undo exists for: remove folder, trash, clear activity, move root folder, mode change.

### 4.5 Window and lifecycle
- Closing the window hides it; syncing continues; the first time, a notification says so.
- Single instance (D-Bus `Gtk.Application` id `dev.kluis.Kluis`); launching again shows the window.
- Restore window size, position, sidebar tab, Quick settings state and column widths.
- Keyboard: Ctrl+1…6 tabs, Ctrl+R, Ctrl+N, Ctrl+, , Ctrl+Q, Ctrl+F search, Esc closes dialogs and menus. Full Tab order; visible focus ring (2 px accent).

### 4.6 Motion budget
Instant: shortcuts, tab switches, selection. 120–150 ms: hovers, menus. 200–250 ms: dialogs, collapsibles, chevrons, Quick settings. Pulses and arcs only while syncing; all motion off under GNOME/Cinnamon "reduce animations" (`gtk-enable-animations=false`).

---

## 5. Visual tokens (GTK CSS)

| Token | Dark | Light |
|---|---|---|
| `bg` | #262530 | #f0eff7 |
| `panel` | #1f1e28 | #faf9fe |
| `surface` | #32313e | #ebeaf3 |
| `line` | #4d4b59 | #d4d3de |
| `text` | #eeedf5 | #24222d |
| `muted` | #bdbcca | #555460 |
| `mapdot` | #575665 | #bdbcca |
| `accent` | #5ed8a9 | #00704e |
| `accent_soft` | #1a533e | #c3ecd9 |
| `on_accent` | #0c1f17 | #fcfcfc |
| `upload` | #f49191 | #af3b43 |
| `warn` | #f0ba59 | #a16100 |
| `error` | #f7857d | #b63132 |

- Top glow: the accent at 45 % alpha fading to transparent over 300 px.
- Radius 10 px for panels and cards, 8 px for buttons, inputs and tiles. 1 px `line` borders at rest; a shadow (`0 4px 6px rgba(0,0,0,.12), 0 2px 4px rgba(0,0,0,.08)`) only on menus, dialogs and dragged items.
- Font: the system UI font (Ubuntu/Cantarell/Noto); tabular numerals for numbers. Sizes 12/13/14/15/18/20/32.
- Buttons 36 px high (44 px primary and dialog buttons), switches 44 × 26.
- **Scrollbar** (gallery and any overflow): a 2 px track line in `line` colour, and a rounded thumb with a vertical gradient from `accent` to `accent` at 35 % alpha, brighter on hover. The same look as the sidebar timeline.
- Logo: **a safe** (body, inner door, dial with 4 ticks, handle, 2 feet), 1.5 px stroke in `accent`. Supply it as `dev.kluis.Kluis.svg` + a symbolic version for the panel.
- Check contrast in both themes: text ≥ 4.5:1, UI parts ≥ 3:1.

---

## 6. CLI mapping — verify each before building its UI

Check every item against the real `proton-drive` CLI help output and the `ProtonDriveApps/sdk/cli` source, **then** record the result in `docs/cli-capabilities.md`. If a capability is missing, hide that UI element (and say so in the release notes); do not emulate it unsafely.

| UI need | Expected source | Verify |
|---|---|---|
| Listing, upload, download, rename, trash, create folder | existing `cli.py` methods | ✓ already used |
| Restore from trash (Undo) | CLI trash restore? | **verify**; if missing, Undo for trash is hidden and the confirm text drops "Undo" |
| Folder item count and size in Browse | listing JSON fields | **verify**; fall back to lazy recursive listing with cache |
| Quota / space used | account or info command | **verify** |
| Shared with me list + sync | shares/shared command | **verify**; hide the tab if missing |
| Transfer rate | progress output or bytes per completed file | compute from bytes and time if no rate is given |
| Photos timeline, albums, download, upload | existing photo commands | ✓ already used |
| CLI version + checksum update | existing | ✓ |
| **Capability self-test** (gates every CLI update) | run `--help` for each command Kluis uses and check that the flags and JSON keys it needs are present, plus one read-only `list` call | write it once from this table |

---

## 7. Safety invariants (each needs an automated test)

1. Nothing is ever deleted permanently by Kluis: local deletes go to the freedesktop Trash, remote deletes to the Proton Drive trash.
2. A file changed on both sides keeps both copies: `name (conflict YYYY-MM-DD HHMM <host>).ext`.
3. A file is marked synced only after its SHA-1 matches what the CLI reports.
4. Back up never deletes remotely and never changes local files. Mirror down never changes Proton Drive. Viewer shares are always mirror-down.
5. Removing a folder from Kluis never deletes files on either side.
6. Moving the Proton Drive folder is atomic per item and resumable after a crash or power loss; no file exists in neither place at any moment.
7. Pause and Stop finish or roll back the current file; no half-written files are left (write to `.kluis-part`, then rename).
8. **Mass-deletion guard:** if one sync run would move more than 50 files or more than 10 % of a folder to a trash, Kluis pauses that folder and asks: "Kluis is about to move 312 files from Agriland to the trash. This usually means a folder was moved or a drive is missing." with buttons "Move them to the trash" / "Keep everything and pause". The default and Esc choose keep.
9. **Missing-folder guard:** if a synced local folder or its drive disappears, never treat it as "everything deleted". Pause that folder with "Folder not found: <path>. Reconnect the drive or choose the folder again."
10. Disk full, offline, expired sign-in and rate limits pause sync with a clear status and auto-resume when fixed; **no data loss and no retry storms** (exponential backoff, max 15 min).
11. Config writes are atomic (temp + rename, `.bak` kept). A corrupt config → start with the backup and log it.
12. **CLI capability self-test** gates every new CLI binary (§2); an incompatible CLI can never run a sync.
13. No network calls except the CLI itself, the CLI download from proton.me, and the GitHub release check (only if updates are enabled).

---

## 8. Test plan (everything automated, no manual testing)

**A. Unit and engine:** keep the existing 33 sync + 12 photo scenarios green. Add tests for every §7 invariant, mode-change rules, the status-text priority (§4.2), ETA and transfer-rate maths, config migration from 0.3.x, root-folder move (including a simulated crash mid-move), and the ring mapping (pure function: scroll position → ring position, monotonic, ends exactly at the last dot).

**B. GUI end-to-end (Xvfb + mock CLI + dogtail/AT-SPI):** script every flow and screenshot each step in **light and dark**, at **1440×900 and 1024×640**:
1. First run → steps 1-3 (including checksum failure, sign-in timeout, Back) → Home.
2. Add folder by dialog and by drag-and-drop; every validation refusal.
3. Toggle, change mode (including the two-way confirm), Sync one folder, Open, Remove + Undo.
4. Browse: navigate, breadcrumbs, upload by button and drag, new folder, rename, download, trash + confirm + Undo, resize every column with mouse and keyboard, empty/error/loading states.
5. Photos: expand/collapse both cards by header click, switch, Change… pickers, layouts, album filter, select/open/download, scrubber click on every 6th dot, wheel-scroll top→bottom asserting the ring increases monotonically with no jump > 1 dot, 50'000-photo performance (scroll stays at 60 fps on a mid laptop; memory < 400 MB).
6. Shared with me (if supported): sort, target picker, sync on/off, Viewer forced to mirror.
7. Activity: filter, clear + Undo, badge counts.
8. Settings: every control persists across restart; root folder move + Undo; CLI update; sign out → onboarding step 2.
9. Quick settings: every toggle, collapse/expand, the All settings… menu items, state persisted.
10. Pause/Resume/Sync now/Stop from the header, Quick settings and the panel icon all stay consistent.
11. Close → hidden + syncing; relaunch → same window; Quit.
12. Offline, disk full, expired sign-in, CLI missing, CLI too old: each shows its state and recovers.
13. Keyboard-only run of flows 1–9.

**C. Install tests (CI):** build the `.deb` and the pacman package; install, launch, autostart and uninstall (with and without `--purge`) on clean **Linux Mint 22 (Cinnamon)**, **Linux Mint 21.3**, **EndeavourOS (KDE)**, plus Xfce. Panel icon visible on each.

**D. Automatic self-test against the real account (no test account, no person needed).** `kluis --selftest` (also run after install and after every CLI update):
1. Creates `/Kluis-selftest-<random>` in Proton Drive and a matching temporary local folder.
2. Runs flows F4, F6, F8 and F14 (§12) for real: upload 25 generated files (0 bytes, 50 MB, `äöü`, spaces, emoji, 200-character names), edit on both sides → conflict copy, delete → Proton trash, mirror and back-up mode rules, a network drop mid-upload (blocks the CLI process' traffic, then restores it).
3. Verifies SHA-1s, cleans up both sides (Proton trash, then empty **only** the items it created) and reports PASS/FAIL to the Activity log.
4. It never touches any other file in her account. On FAIL: sync stays paused with one clear notification.
CI runs the same suite against the mock CLI on every commit.
Record the results in `docs/release-checklist.md` (checkbox per item, date, Kluis and CLI versions).

---

## 9. Feature inventory (must all survive; extend from the code)

Onboarding (CLI download + SHA-512, sign-in + keyring, KDE note, folder picks, run setup again) · Folders (status hero, add dialog, drag-drop add, per-folder switch/mode/sync/open/remove, size, conflict status, empty state) · Browse (breadcrumbs, upload button + drag, new folder, rename, download, trash + confirm, multi-select, counts, sizes, dates, resizable columns, empty/error states) · Photos (download to computer with layout/albums/trash-follow/status/open, upload folder with duplicate skip, month gallery with thumbnails/videos/albums/multi-select/open/download, scrubber) · Shared with me · Activity (filter, open log folder, clear, icons, empty state) · Settings (root folder, start at login, start hidden, check interval, theme, notifications, language, beta, home location, CLI update, sign out, diagnostics, shortcuts, about) · Header (sync now/stop, pause) · Quick settings · Status panel · Panel icon menu · Notifications · Close-to-background · Single instance · Shortcuts · Safety invariants §7 · Mint + EndeavourOS packages.

---

### 9b. Also in the Kluis 0.3.1 code (checked 2026-11-26) — keep every one
- **Onboarding:** auto-detect an installed CLI ("Looking for the Proton Drive CLI…"), **"I already have it…"** (pick an existing `proton-drive`), "Download page" link, **"Skip for now"**, **"Open the sign-in page again"**.
- **Add/Edit folder dialog:** **Edit synced folder** (Save) for existing folders; the Proton Drive folder picker with **New folder**; remote paths under `/my-files`, `/devices`, `/shared-with-me` (with the existing validation messages); **More options** expander: *Sync soon after I change files* (watcher on/off), *Copy deletions to the other side* (off = deleted files come back), *Skip files that match* (exclude patterns, one per line), *Check every file again on the next sync*.
- **Folder card "More" menu:** Edit…, Show in Kluis browser, Open Proton Drive on the web, Check every file again, Stop syncing this folder…
- **Main menu** (now under ⚙ All settings…): also **Sign in…** and **Open Proton Drive on the web**.
- **Settings:** CLI **Location** + **"Use another copy"** (a custom binary; when chosen, Kluis doesn't auto-update it and says so), **Skip image previews when uploading**, **Troubleshooting → Logs**.
- **Photos:** **Previews for all photos** toggle (download-once thumbnails for photos not saved locally), loading state "Reading your timeline…", **Show more** paging, empty-state actions "Show my photos" / "See your photo timeline".
- **Panel icon menu:** also **Proton Drive on the web**; the 4 existing tray icons (idle, sync, paused, error) get the safe logo.
- **Status:** "Sign in to keep syncing" when the session ends (menu → Sign in…), and "Waiting for its turn…" per folder.
- Existing `kluis/data/style.css` is replaced by `kit/design/kluis-{dark,light}.css`.

## 10. Release gate (Definition of Done)

- [ ] Inventory diff (§1, rule 1) shows no dropped features
- [ ] `docs/cli-capabilities.md` written; unsupported UI hidden
- [ ] All tests A–C green in CI; screenshots attached to the PR for every flow in both themes
- [ ] No sample or hard-coded data in the shipped app (grep for the sample names in `reference/` returns nothing)
- [ ] Accessibility: keyboard-only run passes; AT-SPI names on every control; contrast checked
- [ ] Every flow in §12 passes as an automated GUI test (mock CLI), light + dark, 1440×900 + 1024×640, on EndeavourOS KDE and Mint Cinnamon in CI
- [ ] `kluis --selftest` passes on Walter's machine against the real account
- [ ] Version bumped to **1.0.0**; release notes list what's new and what's hidden and why
- [ ] Only then: install on his sister's EndeavourOS machine (pacman package), with "Start at login" on and "Notifications: Problems only"; `--selftest` runs once automatically after install

## 11. Decisions from Walter (2026-11-26) — no open questions
1. Target: **EndeavourOS, KDE Plasma** for his sister. **Delivery order: Linux Mint first** (Walter's machine: build, install, full suite, self-test), **then EndeavourOS** (pacman package, tests in an Arch/KDE container).
5. Claude Code works **autonomously**: no checkpoints or questions. Unclear points → choose the safer option and log it in `docs/redesign/decisions.md`. Walter's only action is signing the CLI in once, if needed.
2. She uses **Proton VPN**; the VPN view stays **always on** either way.
3. Kluis updates: **notify only**. Proton CLI: **always latest**, never pinned (§2).
4. **No test account, no manual testing.** Proof comes from the §12 flows (automated) and `--selftest` (§8 D).

---

## 12. End-to-end flows (each one is an automated GUI test)

Run with Xvfb + the mock CLI (+ dogtail/AT-SPI for clicks), on Mint Cinnamon and EndeavourOS KDE, light + dark, 1440×900 + 1024×640. Screenshot every step and attach the screenshots to the PR. A flow passes only when every “Expected” holds. Machine-readable copy: `kit/tests/flows.json`.


### F1 · First run
*Where:* Onboarding · *Given:* Clean install, no config, no CLI

| # | Action | Expected |
|---|---|---|
| 1 | Launch Kluis from the app menu | Window opens on Welcome · Step 1 of 3; Back disabled; Next disabled |
| 2 | Click “Download from proton.me” | Button shows “Downloading…” (fixed width), progress “x of y MB” within 300 ms |
| 3 | Download completes | “✓ Downloaded · proton-drive <latest> · SHA-512 checksum matches”; Next enabled |
| 4 | Click Next | Step 2 of 3 · “Open Proton sign-in”; KDE note visible only on KDE |
| 5 | Click “Open Proton sign-in”, finish in browser | “Waiting for your browser…” → “✓ Signed in as <email>”; Next enabled |
| 6 | Click Next | Step 3 of 3 · chips for existing Documents/Pictures/Desktop, Documents + Pictures preselected |
| 7 | Toggle Desktop on, click “+ Other folder…”, pick ~/Music | 4 chips selected, each pressed style |
| 8 | Click “Start syncing” | Home opens; status “Syncing N of M files”; arc animates; timeline gets entries |
| 9 | Wait for completion | Status “Everything is up to date”; toast “Everything is up to date ✓”; panel icon idle |

### F2 · CLI download fails its checksum
*Where:* Onboarding · *Given:* Mock serves a corrupted binary

| # | Action | Expected |
|---|---|---|
| 1 | Click “Download from proton.me” | Progress shows |
| 2 | Checksum mismatch | File deleted; message “The download didn't match Proton's checksum, so it was deleted. Try again.”; Next stays disabled |
| 3 | Click the button again (mock now serves a good file) | ✓ Downloaded; Next enabled |

### F3 · Sign-in timeout, Back, resume
*Where:* Onboarding · *Given:* Step 2, browser never completes

| # | Action | Expected |
|---|---|---|
| 1 | Click “Open Proton sign-in”, wait 5 min (mock clock) | “Sign-in didn't finish. Try again.”; button enabled |
| 2 | Click Back | Step 1 with its ✓ state kept |
| 3 | Close the window, relaunch | Opens on the same step with the same state |

### F4 · Add a folder with the dialog
*Where:* Folders · *Given:* Signed in, 3 folders synced

| # | Action | Expected |
|---|---|---|
| 1 | Press Ctrl+N | Add-folder dialog; focus on “Folder on this computer” |
| 2 | Pick an already-synced folder | Inline error beside the field: “Already syncing”; Start disabled |
| 3 | Pick ~/ (home) | Inline error “Pick a folder inside your home folder, not the whole home folder” |
| 4 | Pick ~/Documents/Startup | Proton folder prefilled “<root>/Startup”; Two-way selected |
| 5 | Choose ↑ Back up, click “Start syncing” | Dialog closes; Folders tab; new card “Startup · Measuring…”, status “First sync started…”; toast |
| 6 | Wait | Size chip shows a real size; status “Backed up HH:MM · N files” |

### F5 · Add a folder by drag and drop
*Where:* Folders · *Given:* Any tab open

| # | Action | Expected |
|---|---|---|
| 1 | Drag a folder from the file manager onto the window | Drop highlight on the whole window |
| 2 | Drop | Add-folder dialog prefilled with that folder |
| 3 | Drop a file instead of a folder | Toast “Drop a folder to sync it. To upload files, use Browse.” |

### F6 · Folder card actions
*Where:* Folders · *Given:* Folder “Agriland”, two-way, on

| # | Action | Expected |
|---|---|---|
| 1 | Toggle its switch off | Card dims; status “Off · not syncing”; ↻ Sync disabled; watching count drops |
| 2 | Toggle on | Status “Synced just now” after a sync |
| 3 | Change Mode to ↑ Back up | Toast “Agriland: ↑ Back up” with Undo |
| 4 | Change Mode back to ⇄ Two-way | Confirm: “Two-way sync also sends deletions…” · “Switch to two-way” / “Keep ↑ Back up” |
| 5 | Click “Keep ↑ Back up” | Mode stays Back up |
| 6 | Click ↻ Sync | Only this folder syncs; status updates; toast |
| 7 | Click Open | File manager opens the local folder |
| 8 | Click Remove | Card disappears; toast “Stopped syncing Agriland · files kept on both sides” + Undo |
| 9 | Click Undo within 8 s | Card returns exactly as before, still syncing |

### F7 · Sync now, Stop, Pause, Resume (everywhere stays consistent)
*Where:* Header · Quick settings · panel icon · *Given:* Idle

| # | Action | Expected |
|---|---|---|
| 1 | Press Ctrl+R | Header button becomes Stop; status “Syncing…”; transfer graph moves; panel icon syncing |
| 2 | Click Stop | Toast “Stopped at N of M · nothing lost”; no .kluis-part files left |
| 3 | Click ⏸ Pause in the header | Pressed style; amber “Paused”; Quick settings “Pause sync: On”; panel menu shows “Resume syncing”; graph flat 0 |
| 4 | Edit a file in a synced folder | Nothing uploads; status still paused |
| 5 | Click “Resume syncing” in the panel menu | All three controls show resumed; the edited file uploads within 10 s |

### F8 · Browse Proton Drive
*Where:* Browse · *Given:* Root has 4 folders + 2 files

| # | Action | Expected |
|---|---|---|
| 1 | Press Ctrl+3 | List with Files, Size, Modified columns; skeleton rows if loading > 300 ms |
| 2 | Click folder “Agriland” | Breadcrumb “My files › Agriland”; its items listed |
| 3 | Click “↑ Upload…”, pick 2 files | Progress, then both rows appear; toast “Uploaded 2 files ✓” |
| 4 | Drag a file onto the list | Uploads into the current folder |
| 5 | Click “+ New folder”, type “Archiv 2026”, Enter | Row appears; toast |
| 6 | Select one file, click Rename, type new name | Row renamed; Rename disabled with 0 or 2+ selected |
| 7 | Select 2 items, click ↓ Download | Files land in ~/Downloads; toast with “Show in folder” |
| 8 | Select 2 items, click “Move to trash” | Confirm “Move 2 items to the trash? …” · “Move to trash” / “Keep files” (no default) |
| 9 | Confirm | Rows gone; toast + Undo (if restore is supported, §6) |
| 10 | Click Undo | Rows restored from the Proton trash |
| 11 | Drag the Size column divider 60 px right; press ← twice on the Files divider | Columns resize; widths survive a restart |
| 12 | Open an empty folder | “This folder is empty. Drag files here to upload them.” |
| 13 | Go offline, open a folder | “Couldn't load this folder: offline” + Retry |

### F9 · Photos end to end
*Where:* Photos · *Given:* 2 years of photos (mock: 24 months, 5–15 per month, some videos)

| # | Action | Expected |
|---|---|---|
| 1 | Press Ctrl+4 | Download and Upload cards collapsed (status line only, chevrons pointing down); gallery fills the rest; scrubber shows 24 dots + year labels |
| 2 | Click anywhere on the Download header | Card opens, chevron up; path row, layout, albums, trash-follow visible |
| 3 | Click the Download switch | Toggles without opening/closing the card |
| 4 | Click “Change…”, pick a folder; click the path | Path updates; the path opens the file manager |
| 5 | Set layout “Folders by year” | Next download uses YYYY/ folders (assert on disk) |
| 6 | Open Upload, click “Change…”, pick ~/Pictures/Camera | Status “N new added · M skipped (already in Proton Photos)” |
| 7 | Scroll the gallery with the mouse wheel to the bottom | Only the gallery scrolls; the ring moves monotonically, never jumps > 1 dot, ends exactly on the last dot |
| 8 | Click the dot for March 2025 | Gallery smooth-scrolls; “March 2025” heading at the top; ring on that dot |
| 9 | Click 3 tiles | ✓ badges; “3 selected”; Open disabled; Download selected enabled |
| 10 | Click “↓ Download selected” | Files saved to the download folder; toast; selection cleared |
| 11 | Double-click a video tile | Opens in the default video player |
| 12 | Pick Album “Kapstadt” | Gallery and scrubber show only that album's months |

### F10 · Shared with me (only if the CLI supports it)
*Where:* Shared with me · *Given:* 3 shared items: 2 editor, 1 viewer

| # | Action | Expected |
|---|---|---|
| 1 | Press Ctrl+5 | “0 of 3 items synced”; columns Permissions, Name, Shared by, Local folder, Shared on, Sync |
| 2 | Click “Shared on” | Order flips; arrow ▼/▲ |
| 3 | Click the folder icon on row 1, pick ~/Documents/Papies | Path updates (dimmed until synced) |
| 4 | Switch Sync on for row 1 | Toast “Syncing … to …”; “1 of 3 items synced”; files appear locally |
| 5 | Switch Sync on for the Viewer item | Syncs as mirror-down; tooltip explains why |
| 6 | Switch Sync off | Toast “local copy kept”; files stay on disk |

### F11 · Activity
*Where:* Activity · *Given:* Log has ok, info, warning, error entries

| # | Action | Expected |
|---|---|---|
| 1 | Press Ctrl+6 | Rows with coloured icons; sidebar badge clears |
| 2 | Set filter “Problems only” | Only warnings + errors |
| 3 | Click “Open log folder” | File manager at ~/.local/state/kluis |
| 4 | Click Clear, then Undo | Empty state, then the entries return |

### F12 · Settings
*Where:* Settings dialog · *Given:* Defaults

| # | Action | Expected |
|---|---|---|
| 1 | Press Ctrl+, | Dialog; first section “Your Proton Drive folder” with Location ✓ + Change… |
| 2 | Click Change…, pick /data/Proton | Progress “Moving N of M files”; ends ✓; toast + Undo; no file missing at any point (assert) |
| 3 | Toggle Start at login, Start hidden; set interval 30 min, theme Light, notifications Problems only | Each applies instantly; all persist after restart; autostart .desktop written/removed |
| 4 | Click “Check now” under Proton Drive CLI | “Checking…” → “✓ Up to date” or update flow F15 |
| 5 | Click “Copy diagnostics” | Toast “Copied”; clipboard has versions + log, no email, no tokens (assert) |
| 6 | Click “Sign out…” | Confirm “Sign out” / “Stay signed in” |
| 7 | Confirm | Sync stops; onboarding Step 2 opens; files untouched |

### F13 · Quick settings column
*Where:* Quick settings · *Given:* Expanded

| # | Action | Expected |
|---|---|---|
| 1 | Check the order | ⚙ All settings… → divider → “Quick settings” → Pause, Notifications, Dark mode, Start at login, VPN view |
| 2 | Click ⚙ All settings… | Menu drops down: Add folder, Settings, Run setup again, About Kluis, Quit |
| 3 | Click Notifications 3 times | All → Problems only → Off → All; Settings shows the same value |
| 4 | Click the sliders ▾ button | Column disappears; button moves into the header after Pause; main area widens |
| 5 | Restart | Column stays collapsed |

### F14 · Things going wrong — always recover
*Where:* Everywhere · *Given:* Syncing

| # | Action | Expected |
|---|---|---|
| 1 | Cut the network mid-upload | Status “Offline — will continue when you're back online”; no retry storm (backoff) |
| 2 | Restore the network | Resumes; no duplicate files (assert SHA-1s) |
| 3 | Fill the disk (mock) | Folder paused, “Disk full on this computer”; resumes after space is freed |
| 4 | Expire the session (mock) | Notification + Home banner “Sign in again” → opens onboarding Step 2 |
| 5 | Unplug the drive holding a synced folder | Folder paused “Folder not found…”; nothing trashed remotely |
| 6 | Delete 400 files locally in a two-way folder | Mass-deletion guard dialog; default keeps everything |
| 7 | Edit the same file locally and remotely | Both kept: “name (conflict 2026-11-26 0942 <host>).ext”; activity warning |
| 8 | Kill the app mid-sync, relaunch | Resumes; no .kluis-part leftovers; nothing lost |

### F15 · Proton CLI auto-update (always latest)
*Where:* Background · *Given:* Newer CLI published

| # | Action | Expected |
|---|---|---|
| 1 | App start / daily check finds a new version | Downloads in the background, SHA-512 verified |
| 2 | Capability self-test passes | Switches atomically; Settings shows the new version; activity entry; no prompt |
| 3 | Capability self-test fails (mock incompatible CLI) | Keeps the previous binary; one notification “Proton changed its Drive tool. Kluis needs an update for it.”; retries daily |

### F16 · Kluis update available (notify only)
*Where:* Background · *Given:* Newer GitHub release

| # | Action | Expected |
|---|---|---|
| 1 | Daily check finds Kluis 1.0.1 | Notification “Kluis 1.0.1 is available” + link; nothing installs |
| 2 | Beta access off, only a pre-release exists | No notification |

### F17 · Window and session
*Where:* App · *Given:* Running

| # | Action | Expected |
|---|---|---|
| 1 | Close the window | Hides; keeps syncing; first time: notification “Kluis keeps syncing in the background” |
| 2 | Launch Kluis again | Same window comes back (single instance) |
| 3 | Log out and in (Start at login + Start hidden) | Only the panel icon appears; syncing runs |
| 4 | ⚙ All settings… → Quit | Process ends; panel icon gone |
| 5 | Keyboard only: Tab through every screen | Visible focus everywhere; every action reachable |

### F18 · Home map and VPN
*Where:* Home · *Given:* Proton VPN connected to Zürich

| # | Action | Expected |
|---|---|---|
| 1 | Press Ctrl+1 | Chip “VPN on”, “Showing as Zürich”; pin “You · Zürich (VPN)” |
| 2 | Disconnect the VPN (NetworkManager event) | Within 2 s: chip “VPN off”, “Your location <home city>”; pin moves |
| 3 | Connect to Australia | Pin moves to the Australian capital |
| 4 | No home city set and no VPN | Pin uses the city from the system time zone |

### F19 · Advanced folder options and Edit (from 0.3.1)
*Where:* Folders · *Given:* Folder “Agriland”, two-way

| # | Action | Expected |
|---|---|---|
| 1 | Card ⋯ More → Edit… | Edit synced folder dialog, prefilled; button “Save” |
| 2 | Open “More options”, switch off “Copy deletions to the other side”, Save | Deleting a file locally does not trash it remotely; the next sync brings it back |
| 3 | Add skip pattern “*.tmp”, Save | New .tmp files are never uploaded (assert) |
| 4 | Switch off “Sync soon after I change files” | Edits wait for the next periodic check; status says so |
| 5 | ⋯ More → Check every file again | Full rescan on the next sync; activity entry |
| 6 | ⋯ More → Show in Kluis browser | Browse opens at the folder's remote path |
| 7 | ⋯ More → Open Proton Drive on the web | Default browser opens drive.proton.me |

# Feature inventory: Kluis 0.3.1 code → Kluis 1.0 (HANDOVER §1 rule 1, §9, §9b)

Built from the code at `main` 50e2c6a, not just the handover. ✓ = kept (where it lives in 1.0),
➕ = new in 1.0, ✎ = kept but changed on purpose (reason). Nothing is dropped.

## App and lifecycle (`app.py`, `tray.py`)
| 0.3.1 feature | 1.0 |
|---|---|
| Single instance `Gtk.Application` `dev.kluis.Kluis` | ✓ |
| `--hidden` start (autostart) | ✓ + Start hidden setting |
| Close hides window, notification the first time | ✓ "Kluis keeps syncing in the background" |
| No panel icon available → close quits | ✓ |
| Actions + shortcuts Ctrl+R, Ctrl+N, Ctrl+, , Ctrl+Q | ✓ + Ctrl+1…6, Ctrl+F, Esc |
| Startup account check (no-cli / signed-out / offline / ok); offline → toast + retry every 2 min | ✓ + exponential backoff (max 15 min) |
| Autostart `.desktop` written/removed | ✓ |
| About dialog ("Kluis" = safe, not affiliated) | ✓ |
| Notifications: errors, conflicts, "synced" when All; sign-in expired | ✓ + batching (max 1 per 30 s), disk full, CLI update |
| Panel icon: XApp on Cinnamon/MATE/Xfce, Ayatana/AppIndicator (StatusNotifier) on KDE | ✓ |
| Panel menu: status line, Sync now, Pause/Resume, Open Kluis, Proton Drive on the web, Quit | ✓ |
| 4 tray icons (idle/sync/paused/error) | ✓ redrawn with the safe logo |
| Rotating log file `~/.local/state/kluis/kluis.log`; `KLUIS_DEBUG` | ✓ |

## Onboarding (`ui/onboarding.py`)
| "Looking for the Proton Drive CLI…" auto-detect (`find_cli`) | ✓ |
| Download from proton.me + SHA-512 check, progress bar | ✓ "x of y MB", mismatch message per §3.0 |
| "I already have it…" (pick binary, chmod +x) | ✓ |
| "Download page" link | ✓ |
| Sign in with browser, "Waiting…", "Open the sign-in page again" link | ✓ + 5-min timeout, "✓ Signed in as <email>" (email only if the CLI prints it, else "✓ Signed in") |
| Step 3 chips Documents/Pictures/Desktop/Music + "Another folder…" + "Skip for now" | ✓ (Music kept as a chip when it exists) |
| — | ➕ stepper "Step N of 3", Back/Next, resume at the same step, KDE keyring note |

## Folders (`ui/window.py` FolderRow/FoldersPage, `ui/dialogs.py` FolderDialog)
| Status hero (sign-in needed / paused / syncing / problems / empty / up to date + conflicts) | ✓ shared status text §4.2 (✎ no "next check in" countdown, per review) |
| "Signed in" chip | ✎ moved to Settings → Account (Home shows the VPN chip) |
| Folder card: mode badge, name, route, status dot + text, progress bar, switch, Sync, Open | ✓ + size chip, Mode drop-down, Remove + Undo |
| "Waiting for its turn…" | ✓ |
| ⋯ More: Edit…, Show in Kluis browser, Open Proton Drive on the web, Check every file again, Stop syncing… | ✓ |
| Empty state + drop zone; drag a folder anywhere on the window | ✓ + "Drop a folder to sync it…" toast for files |
| Add/Edit dialog: local picker, remote entry + Browse… (RemotePicker with New folder), mode cards, preview | ✓ |
| Remote roots `/my-files`, `/devices`, `/shared-with-me` + validation messages | ✓ |
| Validation: overlapping, home folder | ✓ + `/`, Kluis config dir, inline errors |
| More options: watch, copy deletions, skip patterns, check every file again | ✓ |

## Browse (`ui/browser.py`)
| Breadcrumbs + section menu (My files / Computers / Shared with me) + Up + Refresh | ✓ |
| Upload… (multi), drag & drop upload, New folder, Download, Rename, Move to trash + confirm | ✓ + Undo (restore) |
| Right-click menu: Download N, Move to trash | ✓ |
| Row ⋯ menu per item | ✓ |
| Shared emblem on shared items | ✓ |
| File-type icons | ✓ |
| Size, Modified | ✓ + Files column, folder sizes, resizable columns, saved widths |
| Loading / empty / error states, "Waiting for the current sync to finish…" | ✓ + skeleton rows, offline + Retry |
| Double-click file → download | ✎ opens with the default app (download to cache first), per §3.4 |
| Download → folder chooser | ✎ goes to ~/Downloads with "Show in folder" (§3.4, D14) |

## Photos (`ui/photos.py`, `photos.py`, `thumbs.py`)
| Save photos on this computer: switch, folder, layout month/year/flat, albums as folders, follow deletions to Trash, status + Sync + Open | ✓ in the collapsible **Download** card |
| Add photos from a folder: switch, folder, "never uploaded again", status | ✓ in the **Upload** card |
| Open on the web | ✓ (header link) |
| Album filter, Reload, Previews for all photos toggle, Download selected, multi-select, double-click open | ✓ |
| "See your photo timeline" / "Show my photos" intro, "Reading your timeline…", "Show more" paging, "No photos here yet." | ✓ (✎ "Show more" replaced by virtualised scrolling; the intro stays as the first-load state) |
| Video badge ▶ | ✓ + duration when the system thumbnailer gives it |
| Thumbnail pipeline (local → pixbuf; remote → download once, keep ~20 KB; video → system thumbnailer; >60 MB videos skipped) | ✓ |
| — | ➕ month groups with year headings, month scrubber, Open (exactly one) |

## Activity (`ui/window.py` ActivityPage, `manager.py`)
| Filter Everything / Problems only, Open log folder, Clear, icons, empty state, persisted `activity.jsonl` (500) | ✓ + Clear Undo, unread badge |

## Settings (`ui/dialogs.py` SettingsDialog)
| Start at login, Start hidden, check interval, notifications, theme | ✓ (interval 5/15/30/60, D7) |
| CLI Location, "Use another copy", Version, "Check for update", Skip image previews when uploading | ✓ (custom copy → not auto-updated, says so) |
| Sign out + confirm | ✓ copy per §3.8 |
| Troubleshooting → Logs | ✓ |
| — | ➕ Proton Drive folder location + move, Beta access, Kluis update notices, Home location, Copy diagnostics, shortcuts list, version + "Not affiliated with Proton AG" |

## Main menu (header ⋮ in 0.3.1)
| Settings, Sign in…, Open Proton Drive on the web, About, Quit | ✓ under ⚙ All settings… (+ Add folder, Run setup again) |

## Sync engine and safety (`engine.py`, `manager.py`, `state.py`, `config.py`)
| Modes two-way / backup / mirror; conflict copies; trash only; verify SHA-1 before recording | ✓ |
| Debounced folder watcher (8 s), watch budget 4000 dirs, quiet period after a sync | ✓ |
| Default ignore patterns; Proton Docs/Sheets skipped | ✓ + `.kluis-part` |
| Periodic remote check; one CLI process at a time (`_CLI_LOCK`) | ✓ |
| Login-expired detection from errors | ✓ |
| Atomic config save (tmp + rename) | ✓ + `.bak`, corrupt → backup |
| — | ➕ mass-deletion guard, missing-folder guard, staged downloads, backoff, capability self-test, root-folder move journal |

## Packaging
| `.deb` (build-deb.sh), PKGBUILD, install.sh/uninstall.sh (apt+pacman), desktop file, release workflow on version bump | ✓ (+ gnome-keyring dependency on Arch, tests on pull requests) |

# Handover: Kluis for Windows

Written 2026-11-26 at the end of the session that built Kluis 1.1.0, so a fresh session can start the
Windows port without that conversation. Read this, then `FEATURES.md`, `README.md` and
`docs/redesign/decisions.md` (D1–D30).

## The task (Walter's words)

"The app is so nice. Build it for Windows as well, please … that UI, it works."
Same look and feel as Linux: keep the GTK UI exactly as it is, make it run on Windows 10/11, ship a normal
Windows installer as part of the GitHub release, built and tested by CI. Walter (the user) is on Windows 11;
his sister uses Kluis on Linux Mint and EndeavourOS. Tell Walter once, plainly: Proton has its own official
Proton Drive app for Windows; a folder should be synced by only one of the two.

## Where things are

- Repo: `D:\dev\kluis` (git data in `D:\Git\kluis.git`, `core.autocrlf false`: keep LF line endings),
  GitHub `Sundowna/kluis`. Work on branch `feature/windows` (already created from `main` at 0535602 = v1.1.0).
- Released: v1.1.0 (Latest). `main` publishes a release by itself when `kluis/__init__.py` VERSION changes
  (see `.github/workflows/release.yml`, job `release`). `packaging/arch/PKGBUILD` pkgver must match VERSION.
- This PC has **no WSL, Docker or GTK**. Everything is tested in GitHub CI; local Python is Windows Python 3.15
  (only good for `py_compile`/`pyflakes`). Scratch tools: `python -m pyflakes`.
- Feature ledger: `FEATURES.md` (F-001…F-020 + "Before this ledger" pointing at `docs/redesign/inventory.md`).
  Checker: `python ~/.claude/skills/feature-guard/scripts/check_features.py`. Every new behaviour gets a
  ledger line and a test with its F-number in the test file. Never drop a test/feature without Walter's OK.

## How CI tests today (Linux)

- `tests/test_lint.py`, `test_engine.py`, `test_photos.py`, `test_safety.py`, `test_units.py`: script suites,
  isolated by `tests/harness.py` (XDG dirs + mock cloud in a temp dir, `KLUIS_TEST_VAULT` file keyring).
- `tests/gui/flows.py` F1…F23 via `tests/gui/run_all.sh` under Xvfb, light/dark × 1440x900 and 1024x640,
  on Ubuntu 24.04 (Cinnamon env) and Arch (KDE env). 104 runs, all green on 0535602.
- `tests/mock_cli/proton-drive`: Python stand-in for Proton's CLI (`#!/usr/bin/env python3`, multi-account:
  session in `$MOCK_ROOT/.logged_in`, other accounts under `$MOCK_ROOT/accounts/<email>`, devices under
  `my cloud/devices/<name>`). On Windows it needs a launcher (e.g. `proton-drive.cmd` → `python …`).
- Flows fail if the window's minimum size exceeds the screen; the window must fit 960 px wide (F-020).

## Linux-only spots to give Windows counterparts (audit these first; grep for each)

1. **Paths** `kluis/paths.py`: XDG dirs → on Windows `%LOCALAPPDATA%\Kluis\{config,data,state}` (or
   `GLib.get_user_config_dir()` etc.); `BIN_DIR` `~/.local/bin` → `%LOCALAPPDATA%\Kluis\bin`.
2. **Path logic with "/"**: `config.py` `validate_local`/`overlaps`/`other_account_overlap` use
   `rstrip("/") + "/"` and `real == "/"`; engine/photos/rootmove/scrubber relative paths. Remote paths stay
   POSIX ("/my-files/…", `rjoin`). Windows: drive letters, `\`, case-insensitive names, names that are illegal
   on Windows (`<>:"/\|?*`, trailing dot/space, CON/PRN…): a Proton file with such a name must not break a sync
   (skip with a clear message, never delete). This is the riskiest part: add engine tests for it.
3. **Proton CLI** `kluis/cli.py`: `find_cli`, `download_cli` pick the platform from
   `https://proton.me/download/drive/cli/version.json` (`Releases[].Files[].Platform`), `musl` via `ldd`;
   Windows needs the Windows build (`proton-drive.exe`). Every `subprocess` call on Windows needs
   `creationflags=CREATE_NO_WINDOW` (no console flashes). `_die_with_kluis` (PR_SET_PDEATHSIG) → on Windows a
   Job Object with KILL_ON_JOB_CLOSE (so a force-quit Kluis never leaves a CLI download running, F-020-era fix).
   `capabilities.py` `_run` too. Unit test "CLI processes end with Kluis" reads `/proc` → Windows variant.
4. **Keyring** `kluis/accounts.py`: `SecretVault` (libsecret) → add a Windows Credential Manager vault
   (ctypes `CredReadW/CredWriteW/CredDeleteW`). Proton's CLI stores its session with `Bun.secrets` under
   service `ch.proton.drive/drive-sdk-cli`, name `auth-session`; check Bun's `src/jsc/bindings/SecretsWindows.cpp`
   (oven-sh/bun) for the exact TargetName/UserName format and copy the CLI's item unchanged (D30 rule: never
   read or change what is inside a session).
5. **Trash** `engine.py:119` runs `gio trash` → use `Gio.File.trash()` (works on Windows) or the Recycle Bin.
6. **Open files/URLs** `ui/common.py` `open_uri`/`open_path` (`xdg-open`) → `os.startfile`.
7. **Tray** `kluis/tray.py`: XApp / AyatanaAppIndicator → on Windows `Gtk.StatusIcon` (works) with the same menu.
8. **Autostart** `app.py` `_write_autostart` (`~/.config/autostart/*.desktop`) → registry
   `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.
9. **Notifications** (`app.notify`, `selftest.py` `notify-send`) → check `Gio.Notification` on Windows; fall back
   to the tray icon's balloon.
10. **VPN view** `kluis/vpn.py` (NetworkManager D-Bus) → on Windows report "unknown/off" without errors.
11. **Thumbnails** `kluis/thumbs.py` (GNOME thumbnail factory, ffmpegthumbnailer) → GdkPixbuf for images; no video
    previews unless a tool exists.
12. **Single instance**: `Gtk.Application` uniqueness uses D-Bus; check it on Windows (second launch must bring the
    window forward, not start a second Kluis).
13. **Diagnostics** reads `/etc/os-release` (has a fallback); `geo.py` time zone → check on Windows.
14. **Fonts/CSS/icons**: data dir `kluis/data`; symbolic icons ship with Kluis; check the theme looks the same
    (Adwaita on Windows) in CI screenshots.
15. `install.sh`/`uninstall.sh`, `.desktop`, `packaging/*` are Linux-only; add `packaging/windows/`.

## Build and CI plan (proposed; adjust if research says otherwise)

- Runtime: MSYS2 UCRT64 (`mingw-w64-ucrt-x86_64-gtk3`, `-python-gobject`, `-python-cairo`, `-librsvg`,
  `-adwaita-icon-theme`), frozen with PyInstaller (or a plain bundled MSYS2 tree), installer with Inno Setup
  (per-user install to `%LOCALAPPDATA%\Programs\Kluis`, Start menu entry, uninstaller, optional autostart).
- CI: new job `windows` in `release.yml` on `windows-latest` with `msys2/setup-msys2`: lint + unit suites, then
  GUI flows (no Xvfb; the runner has a desktop), then build the installer, install it silently, start Kluis,
  screenshot, uninstall. The `release` job attaches `Kluis-Setup-<version>.exe` (+ a `latest` copy).
- Version: ship as 1.2.0 (bump `kluis/__init__.py` + PKGBUILD pkgver; release notes in
  `packaging/release-notes.md`).

## Working style that worked with Walter

- Short progress lines; he tests on real machines and sends photos of the screen.
- He wants one-line, copy-paste commands. Never put `rm` with variables in a pasted command.
- Test builds as GitHub pre-releases (`v1.2.0-testN`), deleted after the real release.
- After CI is green and he has tested, he authorizes merge + publish; delete test pre-releases after.

## Kluis 1.2.0: Kluis for Windows

**Install**
- Windows 10 / 11: download `Kluis-Setup-1.2.0.exe` and run it. It installs for your user only, no administrator
  rights. If Windows says "Windows protected your PC", click **More info → Run anyway** (Kluis isn't signed by a company).
- Linux Mint / Ubuntu: download `kluis_1.2.0_all.deb` and double-click it.
- EndeavourOS / Arch: `curl -LO https://github.com/Sundowna/kluis/releases/latest/download/kluis-latest-any.pkg.tar.zst && sudo pacman -U kluis-latest-any.pkg.tar.zst`

### New
- **Kluis runs on Windows 10 and 11**, with the same window, tabs, light and dark theme, folder sync, Photos,
  Browse, Shared with me and Proton accounts as on Linux.
  - Kluis's icon sits in the notification area (bottom right) with the same menu; notifications come from it.
  - *Start at sign-in* adds Kluis to Windows' startup apps. *System* theme follows Windows' light/dark app mode.
  - Proton sessions for switching accounts are kept in Windows Credential Manager.
  - A file deleted in Proton Drive goes to the Recycle Bin. On a drive without a Recycle Bin (USB stick, network
    share) Kluis leaves the file where it is and tells you.
  - Starting Kluis a second time brings the open Kluis to the front.
  - Proton Drive names that can't exist on Windows (`a:b.txt`, `notes.`, `CON.txt`, or `Notes.txt` next to
    `notes.txt`) are left out and never deleted; Activity says which ones.
- Proton also has its own official Proton Drive app for Windows. You can use both, but let each folder be synced by
  only one of them.

### Fixed (all systems)
- Turning *Start hidden* on or off now updates the start-at-login entry right away, not only at the next start.

### Notes
- Nothing changes on Linux: same folders, settings and history.
- Not affiliated with Proton AG.

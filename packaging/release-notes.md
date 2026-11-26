## Kluis 1.1.0: more than one Proton account

**Install**
- Linux Mint / Ubuntu: download `kluis_1.1.0_all.deb` and double-click it.
- EndeavourOS / Arch: `curl -LO https://github.com/Sundowna/kluis/releases/latest/download/kluis-latest-any.pkg.tar.zst && sudo pacman -U kluis-latest-any.pkg.tar.zst`

### New
- **Switch between Proton accounts**, like on proton.me. The account button at the top right opens a menu with your account, **Sign out**, and **Other accounts**.
  - **Add another Proton account** from the ⋮ menu (or Settings → Other accounts → Add…). Proton's own browser sign-in opens; Kluis never sees your password.
  - Click an account to switch. When your desktop keyring keeps that account's session, it takes one click; otherwise Proton's browser sign-in opens for that account, with "Use … instead" to go back.
  - **Sign out** hands over to your next account. ✕ removes an account from Kluis; its files stay on this computer and in Proton Drive.
- Each account keeps **its own folders, photo settings and sync history**. Only the active account syncs, and two accounts can't sync the same folder.
- **Browse: Computers is easy to find.** *My files*, *Computers* and *Shared with me* are now buttons with icons at the top of Browse. Computers lists each computer Proton's desktop app syncs (for example a Windows PC); click one to see its folders. If *My files* is empty but a computer has folders, Browse says so.
- The ↻ Reload button in Browse now looks like a button.
- **Search finds files in subfolders** of the folder open in Browse, not only in that folder.
- **More room on Browse and Photos:** the status panel at the bottom becomes one line there, with everything side by side; its chevron opens the full card.
- **Tidier layout:** Quick settings opens and closes with a small icon at the top right, and its column starts level with the page. The buttons at the top never move.
- Activity's buttons sit side by side; the Photos Download card has no empty space under its options.
- If Kluis is closed or force-quit during a download, the download stops too.

### Notes
- Nothing changes for one account: your folders and history stay where they were.
- New dependency on Mint/Ubuntu: `gir1.2-secret-1` (installed automatically with the .deb). On Arch it's part of `libsecret`.
- Copy diagnostics names no account emails.
- Not affiliated with Proton AG.

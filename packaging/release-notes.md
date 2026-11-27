## Kluis 1.1.2: enter your password in the morning, and Kluis syncs

**Install**
- Linux Mint / Ubuntu: download `kluis_1.1.2_all.deb` and double-click it.
- EndeavourOS / Arch: `curl -LO https://github.com/Sundowna/kluis/releases/latest/download/kluis-latest-any.pkg.tar.zst && sudo pacman -U kluis-latest-any.pkg.tar.zst`

### New
- **Kluis unlocks your keyring at login.** If your keyring is still locked when Kluis starts (for example with automatic login), Kluis shows your desktop's own keyring password prompt by itself. Type your login password and syncing starts with your saved Proton session: no click, no new sign-in. Kluis never sees the password.
- **New setting: Settings → General → Unlock the keyring at login** (on by default). It needs Kluis to start at login, so turning it on also turns on *Start at login*. With it off, Kluis waits and shows **Unlock keyring** on Home instead.
- If you cancel the prompt, Kluis doesn't ask again by itself: Home shows **Unlock keyring**, and syncing carries on as soon as the keyring is unlocked, from Kluis or any other app.

### Notes
- Turning off automatic login also works: your keyring then unlocks with the password you type at login, and Kluis doesn't need to ask.
- Not affiliated with Proton AG.

## Kluis 1.1.1: a locked keyring is no longer "signed out"

**Install**
- Linux Mint / Ubuntu: download `kluis_1.1.1_all.deb` and double-click it.
- EndeavourOS / Arch: `curl -LO https://github.com/Sundowna/kluis/releases/latest/download/kluis-latest-any.pkg.tar.zst && sudo pacman -U kluis-latest-any.pkg.tar.zst`

### Fixed
- **Kluis no longer asks you to sign in again after a restart when your keyring is locked.** With automatic login, nobody types the password that unlocks the desktop keyring, so Proton's CLI couldn't read your saved session and Kluis said *Sign in to keep syncing*. Your sign-in was never lost.
  - Kluis now says **Unlock your keyring to keep syncing**. The Home banner has an **Unlock keyring** button that opens your desktop's own password prompt (Kluis never sees the password).
  - Once the keyring is unlocked, from Kluis or from any other app, syncing carries on with the saved session, with no new sign-in.
  - While the keyring is locked, Kluis doesn't run the CLI, so it doesn't keep triggering keyring prompts.
- The Home banner (*Sign in again*, and now *Unlock keyring*) shows its explanation again; before, only the button was visible.

### Notes
- To skip the unlock step at every start, turn off automatic login: your keyring then unlocks with your login password.
- Not affiliated with Proton AG.

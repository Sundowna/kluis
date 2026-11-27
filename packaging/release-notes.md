## Kluis 1.2.0: Sync Center

**Install**
- Linux Mint / Ubuntu: download `kluis_1.2.0_all.deb` and double-click it.
- EndeavourOS / Arch: `curl -LO https://github.com/Sundowna/kluis/releases/latest/download/kluis-latest-any.pkg.tar.zst && sudo pacman -U kluis-latest-any.pkg.tar.zst`

### New
- **Sync Center replaces Folders** (same place in the sidebar, still `Ctrl+2`). It shows everything in your Proton Drive, one line per folder: tick it, see where it lands on this computer, pick how it syncs (⇄ Two-way, ↑ Back up, ↓ Mirror down), and read its status and warnings.
- **Nothing happens until you apply.** Ticking or unticking only marks the line. A bar at the bottom says what will change and roughly how much will download, with *Discard changes* and *Apply changes*.
- **Your folders land in `~/Proton Drive`** with the same structure as in the cloud, unless you choose another place with *Change…*.
- **No double downloads.** If you already downloaded a folder to `~/Downloads`, Sync Center says so and can move that copy into place instead of fetching it again.
- **Synced only** shows just the folders you sync, with everything the old Folders cards had (progress, ↻ Sync now, Pause, Edit, Stop syncing with Undo).
- **Browse → ⇄ Sync to this computer…** opens Sync Center at that folder, ticked. *↓ Download* now says it is a one-off copy.
- **Folder sizes appear at once.** Files/Size counts of your Proton Drive folders are kept on this computer (per account, readable only by you) instead of being counted again at every start; they're refreshed in the background once a day, or now with ↻ in Sync Center.
- **More room for the list.** On Sync Center (as on Browse and Photos) the bottom status panel is one line: the facts on the left, the transfer graph filling the rest. The ▴ at its end opens the full card.
- Folders that start on this computer are still added with **+ Add from this computer…** and then appear in Sync Center like any other.

### Notes
- Not affiliated with Proton AG.

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
- **Restarting no longer starts a big download over.** A ↓ Mirror down folder that was still being read or downloaded when Kluis quit carries on with the folder listings it already has (if they're under 2 hours old) instead of listing every folder of Proton Drive again. Two-way folders always look fresh, so nothing edited in Drive meanwhile is missed.
- **Everything opens instantly.** Browse, Sync Center, Shared with me and Photos show the last list Kluis read straight away (no more 1–5 s wait each time), then check Proton Drive in the background and update quietly if something changed. Browse also reads the subfolders of the folder you're in, so clicking into one is instant. Offline, you still see the last list, with its date. Previews were already kept on disk; now the photo timeline is too.
- **Half screen works.** The left sidebar collapses to a slim icon rail (its button at the top, or Ctrl+B), and a maximized Kluis can always be snapped to half the screen.
- **Folder sizes appear at once.** Files/Size counts of your Proton Drive folders are kept on this computer (per account, readable only by you) instead of being counted again at every start; they're refreshed in the background once a day, or now with ↻ in Sync Center.
- **More room for the list.** On Sync Center (as on Browse and Photos) the bottom status panel is one line: the facts on the left, the transfer graph filling the rest. The ▴ at its end opens the full card.
- Folders that start on this computer are still added with **+ Add from this computer…** and then appear in Sync Center like any other.

### Notes
- Not affiliated with Proton AG.

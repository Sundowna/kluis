## Kluis 1.2.1: folder sizes keep coming while you sync

**Install**
- Linux Mint / Ubuntu: download `kluis_1.2.1_all.deb` and double-click it.
- EndeavourOS / Arch: `curl -LO https://github.com/Sundowna/kluis/releases/latest/download/kluis-latest-any.pkg.tar.zst && sudo pacman -U kluis-latest-any.pkg.tar.zst`

### Fixed
- **Folder sizes keep counting while a folder downloads.** Files/Size counts in Sync Center and Browse now run in a lane of their own, next to the sync instead of waiting behind it. Before, every count had to queue behind each download batch, so the other folders' sizes barely moved until the sync finished.
- **Small folders don't wait for big ones.** Folders being counted take turns, so a folder with a few subfolders gets its size in seconds, even while one with thousands of subfolders is still being counted.

### Notes
- The counting lane keeps a cache of its own next to the Proton Drive CLI's (`~/.cache/proton-drive-cli.lane-count`, readable only by you). You stay signed in once: both lanes use the same Proton sign-in.
- Not affiliated with Proton AG.

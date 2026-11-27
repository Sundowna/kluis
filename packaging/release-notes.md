## Kluis 1.2.2: every subfolder's size, kept

**Install**
- Linux Mint / Ubuntu: download `kluis_1.2.2_all.deb` and double-click it.
- EndeavourOS / Arch: `curl -LO https://github.com/Sundowna/kluis/releases/latest/download/kluis-latest-any.pkg.tar.zst && sudo pacman -U kluis-latest-any.pkg.tar.zst`

### Improved
- **Sizes all the way down.** When Kluis counts a folder's files and size, it now keeps the count of every subfolder it passes through as well, so opening a subfolder in Browse or Sync Center shows its size at once instead of counting again. Counts are kept on this computer (per account, readable only by you) and refreshed once a day.
- **Less listing.** A subfolder that was counted recently isn't listed again when a folder above it is counted.
- **A restart doesn't start a count over.** Each subfolder's size is kept as soon as everything inside it is counted, so if Kluis quits halfway through a big folder, it carries on from there.
- After updating, the sizes from 1.2.1 still show straight away while Kluis counts them again with their subfolders.

### From 1.2.1
- Folder sizes keep counting while a folder downloads (a CLI lane of their own), and small folders don't wait for big ones.

### Notes
- Not affiliated with Proton AG.

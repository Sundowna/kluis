# Proton Drive CLI capabilities (HANDOVER §6)

Checked on 2026-11-26 against the real, latest official build
`cli-drive@0.9.0+75612299` (SDK `js@0.22.2`), downloaded from proton.me (version.json lists 0.9.0
as the only Stable release). Each row was verified with `--help` and, where it is read-only, one
real call against a signed-in account. JSON field names below are what the CLI actually prints.

| UI need | CLI source | Result | What Kluis does |
|---|---|---|---|
| Listing | `filesystem list <path> --json` | ✓ array of nodes: `uid, name{ok,value}, type, mediaType, modificationTime, creationTime, activeRevision{uid, claimedSize, claimedModificationTime, claimedDigests{sha1}}, isShared, directRole, totalStorageSize` (files) | used everywhere |
| Upload | `filesystem upload [-f create-new-revision\|rename\|replace\|skip] [-d merge…] [-t] local… parent` | ✓ prints `{transferredItems, transferredBytes, skippedItems, failedItems, failures}` | sync engine, Browse |
| Download | `filesystem download [-f rename\|remove\|skip] [-d …] path… localFolder` | ✓ | engine downloads into a `.kluis-part` staging folder and renames into place after the SHA-1 check (see decisions D3) |
| Rename | `filesystem rename path newName` | ✓ | Browse |
| Trash | `filesystem trash path…` ("Does not permanently delete") | ✓ | engine, Browse |
| **Restore from trash (Undo)** | `filesystem restore path…` ("Restores trashed items"); trashed nodes are listed under `/trash` with `uid`, `parentUid`, `trashTime` | ✓ **supported** | Browse "Move to trash" shows **Undo**; restore by `/trash/<uid>` |
| Create folder | `filesystem create-folder parent name` | ✓ | engine, Browse, pickers |
| **Folder item count + size (Browse)** | listing has **no** count/size for folders. `filesystem size <path>` → `{"size", "numberOfDescendants"}` but its help says it **includes trashed descendants** | ⚠ partial | Files/Size of a folder are computed lazily from a recursive listing of *active* items only (cached per folder, refreshed on change). `filesystem size` is not used because it would over-report (decisions D4) |
| **Quota / space used** | no account/quota command exists (`auth` has only login/logout) | ✗ **missing** | the "Space used" cell in the status panel is **hidden**; release notes say so |
| **Shared with me** | `filesystem list /shared-with-me` → nodes with `directRole` (`viewer`/`editor`/`admin`), `membership{role, inviteTime, sharedBy{value}}` | ✓ **supported** | the Shared with me tab is shown; Viewer items are forced to Mirror down |
| Pending invitations | `invitation list/accept/reject` | ✓ (not used in 1.0; no UI in the approved design) | — |
| Transfer rate | no progress stream; the summary has `transferredBytes` | computed | rate = bytes of each finished CLI batch ÷ its duration, sampled 1/s (decisions D6) |
| Photos timeline / albums / download / upload | `photo timeline -d`, `album list`, `album photos -d`, `photo download -c`, `photo upload -c` | ✓ already used | unchanged |
| Permanent delete | `filesystem delete` (trashed items only), `filesystem empty-trash` | exists | **never used by Kluis**, except `--selftest` which deletes only the items it created itself |
| CLI version | `proton-drive version` → `Proton Drive CLI cli-drive@X.Y.Z+hash` | ✓ | Settings |
| CLI update | `https://proton.me/download/drive/cli/version.json` → `Releases[].{Version, CategoryName, Files[].{Platform, Url, Sha512CheckSum}}` | ✓ | always latest Stable, SHA-512 verified, then capability self-test |

## Capability self-test (gates every CLI binary, invariant 12)

`kluis/capabilities.py` runs, against a candidate binary and before it is ever used for a sync:

1. `version` prints `cli-drive@`.
2. `--help` lists every command Kluis uses (`filesystem list|upload|download|rename|trash|restore|create-folder`,
   `photo timeline|upload|download`, `album list|photos`, `auth login|logout`).
3. `filesystem upload --help` lists `create-new-revision`, `merge`, `--skip-thumbnails`;
   `filesystem download --help` lists `rename`, `skip`, `merge`; `photo download/upload --help` list `--conflict-strategy`.
4. When signed in: one read-only `filesystem list / --json` returns JSON objects with `path`, and one
   `filesystem list /my-files --json` returns objects with `uid`, `name`, `type`.

Any failure → the new binary is not switched to; the old one stays; one notification
"Proton changed its Drive tool. Kluis needs an update for it."; retried daily.

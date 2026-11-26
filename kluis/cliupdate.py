"""Keeps the official Proton Drive CLI at the latest release (HANDOVER §2, F15).

On start and once a day: read Proton's version.json, download the new build, verify SHA-512,
run the capability self-test on it, and only then switch to it (atomic rename). A failing build
is never used: the previous binary stays, and the user gets one notification per version.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from .capabilities import self_test
from .cli import BIN_DIR, CliError, IncompatibleCli, cli_version_of, download_cli, fetch_latest_release

log = logging.getLogger("kluis.cliupdate")
DAY = 24 * 3600


@dataclass
class UpdateResult:
    status: str           # up-to-date | updated | incompatible | custom | error | skipped
    version: str = ""
    path: str = ""
    message: str = ""


def check_and_update(settings, cli, signed_in: bool, force: bool = False, progress=None,
                     dest_dir=BIN_DIR) -> UpdateResult:
    """Runs off the GTK thread. Mutates settings (cli_path, cli_last_check, cli_pending_version)."""
    if settings.cli_custom:
        return UpdateResult("custom", message="You chose your own copy, so Kluis doesn't update it.")
    if not force and time.time() - settings.cli_last_check < DAY and settings.cli_last_check:
        return UpdateResult("skipped")
    settings.cli_last_check = time.time()
    try:
        rel = fetch_latest_release()
    except Exception as e:  # noqa: BLE001 - offline etc.: try again tomorrow
        return UpdateResult("error", message=f"Couldn't check for a new version: {e}")
    if not rel:
        return UpdateResult("error", message="Couldn't read Proton's version list.")
    current = ""
    if cli.path:
        try:
            current = cli_version_of(cli.run(["version"], json_out=False, timeout=30))
        except CliError:
            current = ""
    if current and current.split("+")[0] == (rel["version"] or "").split("+")[0]:
        settings.cli_pending_version = ""
        return UpdateResult("up-to-date", rel["version"], cli.path or "")
    if settings.cli_pending_version == rel["version"] and not force:
        return UpdateResult("incompatible", rel["version"], message="Still incompatible; previous CLI kept.")
    try:
        path = download_cli(progress, dest_dir=dest_dir, rel=rel,
                            verify=lambda p: self_test(p, signed_in=signed_in))
    except IncompatibleCli as e:
        first = settings.cli_pending_version != rel["version"]
        settings.cli_pending_version = rel["version"]
        log.warning("CLI %s failed the capability self-test: %s", rel["version"], e.stderr)
        return UpdateResult("incompatible", rel["version"], message=str(e) if first else "")
    except Exception as e:  # noqa: BLE001
        return UpdateResult("error", rel["version"], message=str(e))
    settings.cli_pending_version = ""
    settings.cli_path = path
    cli.path = path
    return UpdateResult("updated", rel["version"], path)

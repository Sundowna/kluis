"""More than one Proton account (decisions D30).

Proton's CLI keeps exactly one signed-in session per Linux user, in one fixed keyring slot
(service ``ch.proton.drive/drive-sdk-cli``). Kluis switches accounts by keeping a copy of each
account's session under its own keyring entry and putting the chosen one back into the CLI's slot.
If that isn't possible (no keyring, a session Proton no longer accepts), switching falls back to
Proton's browser sign-in for that account.

Everything that belongs to one account lives apart from the others:
- folders, shared-folder syncs and photo settings: the active account's are the top-level fields of
  ``Settings``; the others wait in ``Settings.accounts[i]["data"]``;
- the CLI's cache, keys cache and events (``PROTON_DRIVE_CACHE_DIR``);
- Kluis's sync history (``state.sqlite``), so one account's sync can never act on another's files.
The first account keeps the original locations, so existing installs don't change at all.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict

from .config import FolderPair, PhotoSettings, Settings
from .paths import DATA_DIR, STATE_DB

log = logging.getLogger("kluis.accounts")

CLI_SERVICE = "ch.proton.drive/drive-sdk-cli"     # Proton CLI: cli/src/credentials/constants.ts
STASH_SCHEMA = "dev.kluis.AccountSession"


# ---------- account records in Settings ----------
def records(settings: Settings) -> list[dict]:
    return [r for r in settings.accounts if isinstance(r, dict) and r.get("email")]


def record(settings: Settings, email: str) -> dict | None:
    e = (email or "").lower()
    return next((r for r in records(settings) if r["email"].lower() == e), None)


def others(settings: Settings) -> list[dict]:
    return [r for r in records(settings) if r["email"].lower() != (settings.account or "").lower()]


def account_dir(email: str) -> str:
    key = hashlib.sha1(email.lower().encode()).hexdigest()[:12]
    return os.path.join(str(DATA_DIR), "accounts", key)


def new_record(settings: Settings, email: str) -> dict:
    """The first account keeps the CLI's default cache and Kluis's original state.sqlite."""
    first = not records(settings)
    d = account_dir(email)
    rec = {"email": email, "cache": "" if first else os.path.join(d, "cli"),
           "state": "" if first else os.path.join(d, "state.sqlite"), "signed_out": False}
    settings.accounts.append(rec)
    return rec


def state_path(rec: dict | None) -> str:
    return (rec or {}).get("state") or str(STATE_DB)


def initials(email: str) -> str:
    """"lindi.kirsten@pm.me" -> "LK", "walter@x" -> "WA" (Proton's avatar style)."""
    local = (email or "?").split("@")[0]
    parts = [p for p in local.replace("_", ".").replace("-", ".").split(".") if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return (local[:2] or "?").upper()


def display_name(email: str) -> str:
    """Proton's own menu shows the account's user name; the CLI only tells Kluis the email."""
    return (email or "").split("@")[0]


# ---------- swapping the per-account part of Settings ----------
def stash(settings: Settings):
    """Moves the active account's folders, shares and photo settings into its record."""
    rec = record(settings, settings.account)
    if rec is None:
        return
    rec["data"] = {"folders": [asdict(f) for f in settings.folders], "shares": dict(settings.shares),
                   "photos": asdict(settings.photos)}


def unstash(settings: Settings, email: str):
    """Makes ``email`` the active account: its folders etc. become the top-level fields."""
    rec = record(settings, email) or new_record(settings, email)
    data = rec.pop("data", None) or {}
    settings.folders = [FolderPair(**{k: v for k, v in f.items() if k in FolderPair.__dataclass_fields__})
                        for f in data.get("folders", []) if isinstance(f, dict) and f.get("local")]
    settings.shares = dict(data.get("shares") or {})
    ph = data.get("photos") or {}
    settings.photos = PhotoSettings(**{k: v for k, v in ph.items() if k in PhotoSettings.__dataclass_fields__})
    settings.account = rec["email"]
    rec["signed_out"] = False


def swap_profile(settings: Settings, email: str):
    if (settings.account or "").lower() == (email or "").lower():
        rec = record(settings, email) or new_record(settings, email)
        rec["signed_out"] = False
        settings.account = rec["email"]
        return
    stash(settings)
    unstash(settings, email)


def adopt(settings: Settings, email: str) -> bool:
    """Called with the email the CLI is signed in as. Returns True when the active account changed.

    - a first-time or 0.3/1.0 install: the existing folders simply belong to this account;
    - the same account: nothing to do;
    - another account (added in Kluis, or signed in from a terminal): its own profile becomes active,
      so folders set up for one account are never synced with another account's Drive.
    """
    if not email:
        return False
    if not settings.account:
        rec = record(settings, email) or new_record(settings, email)
        settings.account = rec["email"]
        rec["signed_out"] = False
        return False
    if settings.account.lower() == email.lower():
        rec = record(settings, email) or new_record(settings, email)
        rec["signed_out"] = False
        return False
    swap_profile(settings, email)
    return True


def stashed_folders(settings: Settings) -> list[tuple[str, FolderPair]]:
    """Folders of the other accounts, for the "already syncing" check."""
    out = []
    for r in others(settings):
        for f in (r.get("data") or {}).get("folders", []):
            if isinstance(f, dict) and f.get("local"):
                out.append((r["email"], FolderPair(**{k: v for k, v in f.items()
                                                     if k in FolderPair.__dataclass_fields__})))
    return out


def forget(settings: Settings, email: str):
    """Removes an account from Kluis (its local files are not touched)."""
    settings.accounts = [r for r in records(settings) if r["email"].lower() != email.lower()]


# ---------- the keyring ----------
class Vault:
    """Where Kluis keeps each account's CLI session, and access to the CLI's own slot."""
    available = False

    def read_live(self) -> dict | None:        # the session the CLI uses now
        return None

    def write_live(self, rec: dict) -> None:
        raise OSError("no keyring")

    def clear_live(self) -> None:              # local only: never revokes the session at Proton
        pass

    def save(self, email: str, rec: dict) -> None:
        pass

    def load(self, email: str) -> dict | None:
        return None

    def forget(self, email: str) -> None:
        pass


class FileVault(Vault):
    """For the test suites: the mock CLI keeps its session in a file (``KLUIS_TEST_VAULT_SLOT``)."""
    available = True

    def __init__(self, folder: str, slot: str):
        self.folder, self.slot = folder, slot
        os.makedirs(folder, exist_ok=True)

    def _p(self, email):
        return os.path.join(self.folder, hashlib.sha1(email.lower().encode()).hexdigest()[:12] + ".json")

    def read_live(self):
        try:
            with open(self.slot, encoding="utf-8") as fh:
                return {"secret": fh.read()}
        except OSError:
            return None

    def write_live(self, rec):
        with open(self.slot, "w", encoding="utf-8") as fh:
            fh.write(rec["secret"])

    def clear_live(self):
        try:
            os.remove(self.slot)
        except OSError:
            pass

    def save(self, email, rec):
        with open(self._p(email), "w", encoding="utf-8") as fh:
            json.dump(rec, fh)
        os.chmod(self._p(email), 0o600)

    def load(self, email):
        try:
            with open(self._p(email), encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def forget(self, email):
        try:
            os.remove(self._p(email))
        except OSError:
            pass


class SecretVault(Vault):
    """libsecret (GNOME Keyring, KWallet's Secret Service). Kluis never reads what's inside a session:
    it copies the CLI's keyring item as it is, with the exact schema and attributes the CLI wrote, so a
    later CLI that names its fields differently still gets back what it stored."""
    available = True

    def __init__(self):
        import gi
        gi.require_version("Secret", "1")
        from gi.repository import Secret
        self.S = Secret
        self.stash_schema = Secret.Schema.new(STASH_SCHEMA, Secret.SchemaFlags.NONE,
                                              {"kluis-account": Secret.SchemaAttributeType.STRING})

    def _service(self):
        S = self.S
        return S.Service.get_sync(S.ServiceFlags.OPEN_SESSION | S.ServiceFlags.LOAD_COLLECTIONS, None)

    def _live_items(self):
        S = self.S
        flags = S.SearchFlags.ALL | S.SearchFlags.UNLOCK | S.SearchFlags.LOAD_SECRETS
        return self._service().search_sync(None, {"service": CLI_SERVICE}, flags, None) or []

    def read_live(self):
        for item in self._live_items():
            secret = item.get_secret()
            if secret is None:
                continue
            attrs = dict(item.get_attributes())
            schema = attrs.pop("xdg:schema", "") or item.get_schema_name() or ""
            return {"secret": secret.get_text(), "attrs": attrs, "schema": schema, "label": item.get_label()}
        return None

    def clear_live(self):
        for item in self._live_items():
            item.delete_sync(None)

    def write_live(self, rec):
        S = self.S
        attrs = {k: v for k, v in (rec.get("attrs") or {}).items() if not k.startswith("xdg:")}
        if not attrs or not rec.get("schema"):
            raise OSError("saved session has no keyring attributes")
        self.clear_live()
        schema = S.Schema.new(rec["schema"], S.SchemaFlags.NONE,
                              {k: S.SchemaAttributeType.STRING for k in attrs})
        if not S.password_store_sync(schema, attrs, S.COLLECTION_DEFAULT, rec.get("label") or CLI_SERVICE,
                                     rec["secret"], None):
            raise OSError("the keyring refused the session")

    def save(self, email, rec):
        S = self.S
        S.password_store_sync(self.stash_schema, {"kluis-account": email.lower()}, S.COLLECTION_DEFAULT,
                              f"Kluis: Proton session for {email}", json.dumps(rec), None)

    def load(self, email):
        raw = self.S.password_lookup_sync(self.stash_schema, {"kluis-account": email.lower()}, None)
        try:
            return json.loads(raw) if raw else None
        except ValueError:
            return None

    def forget(self, email):
        self.S.password_clear_sync(self.stash_schema, {"kluis-account": email.lower()}, None)


CLI_WIN_TARGET = CLI_SERVICE + "/auth-session"   # Bun.secrets on Windows: TargetName = service + "/" + name
STASH_WIN_PREFIX = "dev.kluis.Kluis/account/"


class WinCredVault(Vault):
    """Windows Credential Manager. Proton's CLI (Bun.secrets) keeps its session as a generic credential
    named ``ch.proton.drive/drive-sdk-cli/auth-session``. Like on Linux, Kluis copies that credential as it
    is (bytes, user name, persistence) and never reads what's inside. Each kept copy is a generic
    credential ``dev.kluis.Kluis/account/<email>``, visible in Control Panel → Credential Manager.
    Tests point the CLI's slot elsewhere with KLUIS_TEST_WIN_TARGET."""
    available = True

    def __init__(self, live_target: str = CLI_WIN_TARGET, prefix: str = STASH_WIN_PREFIX):
        import ctypes
        from ctypes import wintypes
        self.ct, self.wt = ctypes, wintypes
        self.live_target, self.prefix = live_target, prefix

        class CREDENTIALW(ctypes.Structure):
            _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                        ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                        ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
                        ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
                        ("UserName", wintypes.LPWSTR)]
        self.CRED = CREDENTIALW
        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        self.read_ = adv.CredReadW
        self.read_.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                               ctypes.POINTER(ctypes.POINTER(CREDENTIALW))]
        self.write_ = adv.CredWriteW
        self.write_.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
        self.delete_ = adv.CredDeleteW
        self.delete_.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self.free_ = adv.CredFree
        self.free_.argtypes = [ctypes.c_void_p]

    GENERIC = 1
    NOT_FOUND = 1168

    def _read(self, target: str) -> dict | None:
        ct = self.ct
        p = ct.POINTER(self.CRED)()
        if not self.read_(target, self.GENERIC, 0, ct.byref(p)):
            err = ct.get_last_error()
            if err == self.NOT_FOUND:
                return None
            raise OSError(err, f"Credential Manager could not read {target}")
        try:
            c = p.contents
            blob = ct.string_at(c.CredentialBlob, c.CredentialBlobSize) if c.CredentialBlobSize else b""
            return {"blob": blob, "user": c.UserName or "", "persist": int(c.Persist), "comment": c.Comment or ""}
        finally:
            self.free_(p)

    def _write(self, target: str, blob: bytes, user: str, persist: int, comment: str = ""):
        ct = self.ct
        buf = (ct.c_ubyte * max(len(blob), 1)).from_buffer_copy(blob or b"\0")
        c = self.CRED()
        c.Type = self.GENERIC
        c.TargetName = target
        c.Comment = comment or None
        c.CredentialBlobSize = len(blob)
        c.CredentialBlob = ct.cast(buf, ct.POINTER(ct.c_ubyte))
        c.Persist = persist or 2                     # CRED_PERSIST_LOCAL_MACHINE
        c.UserName = user or None
        if not self.write_(ct.byref(c), 0):
            raise OSError(ct.get_last_error(), "Credential Manager refused the session")

    def _delete(self, target: str):
        if not self.delete_(target, self.GENERIC, 0):
            err = self.ct.get_last_error()
            if err != self.NOT_FOUND:
                raise OSError(err, f"Credential Manager could not delete {target}")

    def read_live(self):
        c = self._read(self.live_target)
        if c is None or not c["blob"]:
            return None
        import base64
        return {"secret": base64.b64encode(c["blob"]).decode(), "user": c["user"], "persist": c["persist"],
                "target": self.live_target}

    def write_live(self, rec):
        import base64
        if rec.get("target") not in (None, self.live_target):
            raise OSError("saved session belongs to another kind of keyring")
        blob = base64.b64decode(rec.get("secret") or "")
        if not blob:
            raise OSError("saved session is empty")
        self._write(self.live_target, blob, rec.get("user") or "", int(rec.get("persist") or 2))

    def clear_live(self):
        self._delete(self.live_target)

    def save(self, email, rec):
        import base64
        # the session's own bytes as the blob (Credential Manager allows 2560 bytes: no base64/JSON around it)
        meta = json.dumps({"user": rec.get("user") or "", "persist": int(rec.get("persist") or 2),
                           "target": rec.get("target") or self.live_target})
        self._write(self.prefix + email.lower(), base64.b64decode(rec.get("secret") or ""), "kluis", 2, meta)

    def load(self, email):
        import base64
        c = self._read(self.prefix + email.lower())
        if c is None or not c["blob"]:
            return None
        try:
            meta = json.loads(c["comment"] or "{}")
        except ValueError:
            meta = {}
        return {"secret": base64.b64encode(c["blob"]).decode(), "user": meta.get("user", ""),
                "persist": meta.get("persist", 2), "target": meta.get("target", self.live_target)}

    def forget(self, email):
        self._delete(self.prefix + email.lower())


def open_vault() -> Vault:
    if os.environ.get("KLUIS_TEST_VAULT"):
        return FileVault(os.environ["KLUIS_TEST_VAULT"], os.environ.get("KLUIS_TEST_VAULT_SLOT", ""))
    if os.name == "nt":
        try:
            return WinCredVault()
        except Exception as e:  # noqa: BLE001
            log.warning("Credential Manager not available, switching accounts needs a browser sign-in: %s", e)
            return Vault()
    try:
        return SecretVault()
    except Exception as e:  # noqa: BLE001  (no typelib, no Secret Service)
        log.warning("keyring not available, switching accounts needs a browser sign-in: %s", e)
        return Vault()

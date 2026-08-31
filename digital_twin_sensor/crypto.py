"""Encryption at rest for the local event ledger.

WHY THIS EXISTS
---------------
"Local-first" and "plaintext SQLite on disk" in the same README is a contradiction,
and it is the first one a security review finds. The threat model for this product
is a laptop at rest — lost, stolen, backed up to somewhere unexpected, or simply
readable by any other process running as the same user. Redaction reduces what is
in the file. It does not protect the file.

WHAT THIS DOES AND DOES NOT CLAIM
---------------------------------
Field-level authenticated encryption on the three columns that carry meaning:
`title`, `artifact` and `metadata`. AES-256-GCM via `cryptography`, which is a
vetted implementation of a standard AEAD — nothing here invents a primitive.

Deliberately NOT encrypted, and you should know why before relying on this:
`ts_start`, `ts_end`, `dwell_seconds`, `domain`, `app` and `subject_id` stay
readable, because the store queries and sorts on them. So an attacker with the
file still learns your rhythm, your app mix and your domain distribution. That is
real signal. Full-database encryption (SQLCipher) is the answer to that, and it
needs a C extension this project does not currently take.

This is a meaningful improvement, not a complete one. It is documented that way
in docs/UNDER_THE_HOOD.md rather than being claimed as solved.

KEY HANDLING
------------
The key lives in the OS keychain (`keyring`) where one is available. Failing that
it goes to a 0600 file beside the database, which is weaker — a process running as
you can read it — and the code says so out loud rather than quietly degrading.

OPTIONAL BY DESIGN
------------------
    pip install -e ".[encrypted]"
    digital-twin-sensor encrypt-store --enable

The sensor's own `dependencies = []` stays true. A user who does not opt in gets
exactly today's behaviour, and a user who does gets a clear error rather than a
silent fallback if the extra is missing.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from pathlib import Path
from typing import Any

KEY_BYTES = 32  # AES-256
NONCE_BYTES = 12  # GCM standard
PREFIX = "enc:v1:"  # so a mixed-state table is unambiguous during migration
KEYRING_SERVICE = "digital-twin-sensor"
KEYRING_USER = "event-store"


class CryptoUnavailable(RuntimeError):
    """The optional encryption extra is not installed."""


class KeyUnavailable(RuntimeError):
    """Encryption is enabled but no key could be loaded."""


def _aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: PLC0415
    except ImportError as exc:
        raise CryptoUnavailable(
            "encryption at rest needs the optional extra:\n"
            '    pip install -e ".[encrypted]"\n'
            "Without it the store stays plaintext, which is the current default."
        ) from exc
    return AESGCM


def key_file_path(db_path: Path) -> Path:
    return Path(db_path).with_suffix(".key")


def _load_from_keyring() -> bytes | None:
    try:
        import keyring  # noqa: PLC0415
    except ImportError:
        return None
    try:
        raw = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception:
        return None  # a locked or unavailable keychain is not a crash
    return base64.b64decode(raw) if raw else None


def _store_in_keyring(key: bytes) -> bool:
    try:
        import keyring  # noqa: PLC0415
    except ImportError:
        return False
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, base64.b64encode(key).decode())
        return True
    except Exception:
        return False


def load_existing_key(db_path: Path) -> tuple[bytes, str]:
    """An enabled store must never silently create a replacement key."""
    path = key_file_path(db_path)
    if path.exists():
        try:
            key = base64.b64decode(path.read_text(encoding="utf-8").strip(), validate=True)
        except (ValueError, OSError) as exc:
            raise KeyUnavailable(f"key file {path} cannot be read") from exc
        if len(key) != KEY_BYTES:
            raise KeyUnavailable(f"key file {path} is malformed")
        return key, "key file"
    existing = _load_from_keyring()
    if existing and len(existing) == KEY_BYTES:
        return existing, "keychain"
    raise KeyUnavailable("Encryption is enabled but its key is unavailable; storage is closed.")


def cipher_for_config(db_path: Path, config: dict[str, Any]):
    if not config.get("encrypt_at_rest", False):
        return None
    key, _ = load_existing_key(db_path)
    return FieldCipher(key)


def load_or_create_key(db_path: Path) -> tuple[bytes, str]:
    """Return (key, where_it_came_from). Creates one on first use."""
    if key_file_path(db_path).exists():
        return load_existing_key(db_path)
    existing = _load_from_keyring()
    if existing and len(existing) == KEY_BYTES:
        return existing, "keychain"

    path = key_file_path(db_path)
    if path.exists():
        key = base64.b64decode(path.read_text(encoding="utf-8").strip())
        if len(key) != KEY_BYTES:
            raise KeyUnavailable(f"key file {path} is malformed")
        return key, "key file"

    key = secrets.token_bytes(KEY_BYTES)
    if _store_in_keyring(key):
        return key, "keychain (created)"

    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(base64.b64encode(key).decode())
    return key, "key file (created)"


class FieldCipher:
    """Encrypts individual column values, leaving already-encrypted ones alone.

    Idempotent in both directions so a partial migration can be resumed rather
    than corrupting rows it already touched.
    """

    def __init__(self, key: bytes):
        if len(key) != KEY_BYTES:
            raise KeyUnavailable(f"key must be {KEY_BYTES} bytes, got {len(key)}")
        self._key = key
        self._aead = _aesgcm()(key)

    @staticmethod
    def is_encrypted(value: Any) -> bool:
        return isinstance(value, str) and value.startswith(PREFIX)

    def encrypt(self, value: Any) -> Any:
        if value is None or value == "":
            return value
        text = value if isinstance(value, str) else json.dumps(value)
        if self.is_encrypted(text):
            return text
        nonce = secrets.token_bytes(NONCE_BYTES)
        blob = self._aead.encrypt(nonce, text.encode("utf-8"), None)
        return PREFIX + base64.b64encode(nonce + blob).decode("ascii")

    def decrypt(self, value: Any) -> Any:
        if not self.is_encrypted(value):
            return value
        raw = base64.b64decode(value[len(PREFIX):])
        nonce, blob = raw[:NONCE_BYTES], raw[NONCE_BYTES:]
        return self._aead.decrypt(nonce, blob, None).decode("utf-8")


ENCRYPTED_FIELDS = ("title", "artifact", "metadata")


def encrypt_event(event: dict[str, Any], cipher: FieldCipher | None) -> dict[str, Any]:
    if cipher is None:
        return event
    out = dict(event)
    for field in ENCRYPTED_FIELDS:
        if field in out:
            value = out[field]
            if field == "metadata" and not isinstance(value, str):
                value = json.dumps(value)
            out[field] = cipher.encrypt(value)
    return out


def decrypt_event(event: dict[str, Any], cipher: FieldCipher | None) -> dict[str, Any]:
    """Decrypt in place-ish. Rows written before encryption was enabled pass
    through untouched, which is what makes a rolling migration safe."""
    if cipher is None:
        return event
    out = dict(event)
    for field in ENCRYPTED_FIELDS:
        if field in out and FieldCipher.is_encrypted(out[field]):
            out[field] = cipher.decrypt(out[field])
    return out

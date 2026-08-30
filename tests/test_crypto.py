import json
import secrets
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from digital_twin_sensor.store import EventStore, utc_now

try:
    from digital_twin_sensor.crypto import (
        ENCRYPTED_FIELDS,
        FieldCipher,
        CryptoUnavailable,
    )
    CRYPTO = True
except Exception:  # pragma: no cover
    CRYPTO = False


def event(title="invoice reconciliation card 4111111111111111"):
    start = utc_now() - timedelta(minutes=5)
    return {
        "subject_id": "test",
        "source": "test",
        "app": "Numbers",
        "title": title,
        "artifact": title,
        "domain": "data",
        "action": "focus",
        "ts_start": start.isoformat(),
        "ts_end": (start + timedelta(seconds=60)).isoformat(),
        "dwell_seconds": 60.0,
        "metadata": {"redaction_findings": {"card": 1}},
    }


@unittest.skipUnless(CRYPTO, "encryption extra not installed")
class FieldCipherTests(unittest.TestCase):
    def setUp(self):
        self.cipher = FieldCipher(secrets.token_bytes(32))

    def test_roundtrip(self):
        text = "payments gateway retry logic"
        self.assertEqual(self.cipher.decrypt(self.cipher.encrypt(text)), text)

    def test_encryption_is_idempotent(self):
        once = self.cipher.encrypt("x")
        self.assertEqual(self.cipher.encrypt(once), once)

    def test_plaintext_passes_through_decrypt(self):
        """Rows written before encryption was enabled must still read."""
        self.assertEqual(self.cipher.decrypt("legacy plaintext row"), "legacy plaintext row")

    def test_nonce_is_not_reused(self):
        self.assertNotEqual(self.cipher.encrypt("same"), self.cipher.encrypt("same"))

    def test_wrong_key_cannot_decrypt(self):
        blob = self.cipher.encrypt("secret")
        other = FieldCipher(secrets.token_bytes(32))
        with self.assertRaises(Exception):
            other.decrypt(blob)

    def test_tampered_ciphertext_is_rejected(self):
        """GCM is authenticated: a flipped byte must fail, not decrypt to garbage."""
        blob = self.cipher.encrypt("secret")
        body = list(blob)
        body[-2] = "A" if body[-2] != "A" else "B"
        with self.assertRaises(Exception):
            self.cipher.decrypt("".join(body))

    def test_short_key_is_rejected(self):
        with self.assertRaises(Exception):
            FieldCipher(b"too-short")


@unittest.skipUnless(CRYPTO, "encryption extra not installed")
class EncryptedStoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = Path(self.dir.name) / "events.sqlite"
        self.key = secrets.token_bytes(32)

    def tearDown(self):
        self.dir.cleanup()

    def test_sensitive_fields_are_ciphertext_on_disk(self):
        store = EventStore(self.db, cipher=FieldCipher(self.key))
        store.insert_event(event())
        store.close()

        raw = self.db.read_bytes()
        self.assertNotIn(b"4111111111111111", raw, "card number found in the database file")
        self.assertNotIn(b"invoice reconciliation", raw, "title found in plaintext")

    def test_reads_come_back_decrypted(self):
        cipher = FieldCipher(self.key)
        store = EventStore(self.db, cipher=cipher)
        store.insert_event(event())
        events = store.fetch_events(subject_id="test")
        store.close()
        self.assertEqual(len(events), 1)
        self.assertIn("invoice reconciliation", events[0]["title"])
        self.assertEqual(events[0]["metadata"]["redaction_findings"]["card"], 1)

    def test_wrong_key_does_not_silently_return_empty_metadata(self):
        store = EventStore(self.db, cipher=FieldCipher(self.key))
        store.insert_event(event())
        store.close()

        other = EventStore(self.db, cipher=FieldCipher(secrets.token_bytes(32)))
        with self.assertRaises(Exception):
            other.fetch_events(subject_id="test")
        other.close()

    def test_plaintext_rows_survive_enabling_encryption(self):
        """A half-migrated store must stay readable, or migration is all-or-nothing."""
        plain = EventStore(self.db)
        plain.insert_event(event("legacy row before encryption"))
        plain.close()

        store = EventStore(self.db, cipher=FieldCipher(self.key))
        store.insert_event(event("new row after encryption"))
        titles = [e["title"] for e in store.fetch_events(subject_id="test")]
        store.close()
        self.assertIn("legacy row before encryption", titles)
        self.assertIn("new row after encryption", titles)

    def test_unencrypted_store_is_unchanged(self):
        store = EventStore(self.db)
        store.insert_event(event())
        events = store.fetch_events(subject_id="test")
        store.close()
        self.assertIn("4111111111111111", events[0]["title"])


class BoundaryTests(unittest.TestCase):
    @unittest.skipUnless(CRYPTO, "encryption extra not installed")
    def test_timing_columns_are_deliberately_not_encrypted(self):
        """Documented limitation, asserted so it cannot be quietly forgotten:
        the store queries and sorts on these, so they stay readable and an
        attacker with the file still learns rhythm and app mix."""
        for field in ("ts_start", "ts_end", "dwell_seconds", "domain", "app", "subject_id"):
            self.assertNotIn(field, ENCRYPTED_FIELDS)


if __name__ == "__main__":
    unittest.main()

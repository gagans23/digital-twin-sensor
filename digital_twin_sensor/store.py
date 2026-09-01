from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import DEFAULT_DB_PATH
from .observability import observed


SCHEMA = """
CREATE TABLE IF NOT EXISTS storage_policy (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  encryption_required INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO storage_policy(id, encryption_required) VALUES(1, 0);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  subject_id TEXT NOT NULL,
  source TEXT NOT NULL,
  app TEXT NOT NULL,
  title TEXT NOT NULL,
  artifact TEXT NOT NULL,
  domain TEXT NOT NULL,
  action TEXT NOT NULL,
  ts_start TEXT NOT NULL,
  ts_end TEXT NOT NULL,
  dwell_seconds REAL NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_events_subject_time
ON events(subject_id, ts_start);

CREATE INDEX IF NOT EXISTS idx_events_domain_time
ON events(domain, ts_start);

CREATE INDEX IF NOT EXISTS idx_events_artifact
ON events(artifact);
"""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def filter_window(events: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    """Keep only events inside a rolling window.

    EventStore.fetch_window already does this on the way out of SQLite, but the
    derivation builders accept a `days` argument and stamp it on their output.
    A caller that hands in a wider list would otherwise get stale evidence
    labelled as a fresh window. Enforce it where it is claimed.
    """
    if days is None or days <= 0:
        return list(events)
    cutoff = utc_now() - timedelta(days=days)
    kept = []
    for event in events:
        try:
            if parse_dt(event["ts_start"]) >= cutoff:
                kept.append(event)
        except (KeyError, TypeError, ValueError):
            kept.append(event)  # undateable events are a store problem, not a window problem
    return kept


def assert_encrypted_write(conn, cipher) -> None:
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'storage_policy'").fetchone()
    if exists and conn.execute("SELECT encryption_required FROM storage_policy WHERE id = 1").fetchone()[0] and cipher is None:
        raise RuntimeError("This database requires encryption; reload its policy and key before writing")


def open_event_store(db_path: Path, config: dict[str, Any]):
    from .crypto import cipher_for_config

    return EventStore(db_path, cipher=cipher_for_config(db_path, config))


class EventStore:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH, *, cipher: Any = None):
        """`cipher` is a crypto.FieldCipher, or None for a plaintext store.

        Rows written before encryption was enabled decrypt to themselves, so a
        store can be half-migrated without breaking reads. That is what makes
        `encrypt-store --enable` resumable rather than all-or-nothing."""
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        os.chmod(self.db_path, 0o600)
        self.conn.execute("PRAGMA secure_delete = ON")
        self.conn.row_factory = sqlite3.Row
        self.cipher = cipher
        self.init_db()

    def init_db(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    @observed("collection.persist")
    def insert_event(self, event: dict[str, Any]) -> int:
        assert_encrypted_write(self.conn, self.cipher)
        if self.cipher is not None:
            from .crypto import encrypt_event  # noqa: PLC0415

            event = encrypt_event(event, self.cipher)
        metadata = event.get("metadata", {})
        cur = self.conn.execute(
            """
            INSERT INTO events (
              subject_id, source, app, title, artifact, domain, action,
              ts_start, ts_end, dwell_seconds, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["subject_id"],
                event["source"],
                event["app"],
                event["title"],
                event["artifact"],
                event["domain"],
                event.get("action", "focus"),
                event["ts_start"],
                event["ts_end"],
                float(event["dwell_seconds"]),
                # Already an encrypted string when a cipher is active; dumping
                # it again would wrap it in quotes and defeat the prefix check
                # that tells a reader whether a row is encrypted.
                metadata if isinstance(metadata, str) else json.dumps(metadata, sort_keys=True),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def fetch_events(
        self,
        *,
        subject_id: str | None = None,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM events WHERE 1=1"
        params: list[Any] = []
        if subject_id:
            query += " AND subject_id = ?"
            params.append(subject_id)
        if since:
            query += " AND ts_start >= ?"
            params.append(since.isoformat())
        query += " ORDER BY ts_start ASC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        decrypt = None
        if self.cipher is not None:
            from .crypto import decrypt_event  # noqa: PLC0415

            decrypt = decrypt_event
        events = []
        for row in rows:
            item = dict(row)
            raw_metadata = item.pop("metadata_json") or "{}"
            item["metadata"] = raw_metadata
            if decrypt is not None:
                item = decrypt(item, self.cipher)
            metadata = item.get("metadata") or "{}"
            try:
                item["metadata"] = json.loads(metadata) if isinstance(metadata, str) else metadata
            except json.JSONDecodeError:
                # An undecryptable metadata blob means the wrong key, not a
                # corrupt row. Surface it rather than silently emptying it.
                item["metadata"] = {"error": "metadata could not be read with the current key"}
            events.append(item)
        return events

    def fetch_window(
        self,
        *,
        subject_id: str,
        days: int,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        since = utc_now() - timedelta(days=days)
        return self.fetch_events(subject_id=subject_id, since=since, limit=limit)

    def count_events(self, *, subject_id: str | None = None) -> int:
        if subject_id:
            row = self.conn.execute(
                "SELECT COUNT(*) AS count FROM events WHERE subject_id = ?",
                (subject_id,),
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) AS count FROM events").fetchone()
        return int(row["count"])

    def count_before(self, *, cutoff: datetime, subject_id: str | None = None) -> int:
        if subject_id:
            row = self.conn.execute(
                "SELECT COUNT(*) AS count FROM events WHERE subject_id = ? AND ts_start < ?",
                (subject_id, cutoff.isoformat()),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) AS count FROM events WHERE ts_start < ?",
                (cutoff.isoformat(),),
            ).fetchone()
        return int(row["count"])

    def oldest_event(self, *, subject_id: str | None = None) -> str | None:
        if subject_id:
            row = self.conn.execute(
                "SELECT ts_start FROM events WHERE subject_id = ? ORDER BY ts_start ASC LIMIT 1",
                (subject_id,),
            ).fetchone()
        else:
            row = self.conn.execute("SELECT ts_start FROM events ORDER BY ts_start ASC LIMIT 1").fetchone()
        return str(row["ts_start"]) if row else None

    def delete_before(self, *, cutoff: datetime, subject_id: str | None = None) -> int:
        if subject_id:
            cur = self.conn.execute(
                "DELETE FROM events WHERE subject_id = ? AND ts_start < ?",
                (subject_id, cutoff.isoformat()),
            )
        else:
            cur = self.conn.execute("DELETE FROM events WHERE ts_start < ?", (cutoff.isoformat(),))
        deleted = int(cur.rowcount)
        if deleted:
            self._clear_derived_memory(subject_id)
        if self.conn.execute("SELECT 1 FROM sqlite_master WHERE name='task_identities'").fetchone():
            from .task_identity import expire_identities
            expire_identities(self.conn, cutoff.isoformat(), subject_id)
        self.conn.commit()
        return deleted

    def delete_all(self, *, subject_id: str | None = None) -> int:
        if subject_id:
            cur = self.conn.execute("DELETE FROM events WHERE subject_id = ?", (subject_id,))
        else:
            cur = self.conn.execute("DELETE FROM events")
        deleted = int(cur.rowcount)
        self._clear_derived_memory(subject_id, clear_feedback=True)
        self.conn.commit()
        from .observability import purge
        purge(self.db_path)
        return deleted

    def _clear_derived_memory(self, subject_id: str | None, *, clear_feedback: bool = False) -> None:
        # Until every derived field has source lineage, discard cached cards on
        # retention. Keep active restrictions so retention cannot weaken consent.
        tables = {row[0] for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        names = ["context_cards", "resume_checkpoints", "resume_sessions"] + (["context_feedback"] if clear_feedback else [])
        if clear_feedback:
            names.extend(["task_bindings", "task_identities", "task_identity_edits"])
        for name in names:
            if name in tables:
                if subject_id:
                    self.conn.execute(f"DELETE FROM {name} WHERE subject_id = ?", (subject_id,))
                else:
                    self.conn.execute(f"DELETE FROM {name}")

    def update_event_text(
        self,
        event_id: int,
        *,
        title: str,
        artifact: str,
        metadata: dict[str, Any],
    ) -> None:
        assert_encrypted_write(self.conn, self.cipher)
        if self.cipher is not None:
            from .crypto import encrypt_event

            encrypted = encrypt_event({"title": title, "artifact": artifact, "metadata": metadata}, self.cipher)
            title, artifact, metadata = encrypted["title"], encrypted["artifact"], encrypted["metadata"]
        self.conn.execute(
            """
            UPDATE events
            SET title = ?, artifact = ?, metadata_json = ?
            WHERE id = ?
            """,
            (title, artifact, metadata if isinstance(metadata, str) else json.dumps(metadata, sort_keys=True), event_id),
        )
        self.conn.commit()

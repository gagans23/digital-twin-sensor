from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import DEFAULT_DB_PATH


SCHEMA = """
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


class EventStore:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.init_db()

    def init_db(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def insert_event(self, event: dict[str, Any]) -> int:
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
                json.dumps(metadata, sort_keys=True),
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
        events = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
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

    def update_event_text(
        self,
        event_id: int,
        *,
        title: str,
        artifact: str,
        metadata: dict[str, Any],
    ) -> None:
        self.conn.execute(
            """
            UPDATE events
            SET title = ?, artifact = ?, metadata_json = ?
            WHERE id = ?
            """,
            (title, artifact, json.dumps(metadata, sort_keys=True), event_id),
        )
        self.conn.commit()

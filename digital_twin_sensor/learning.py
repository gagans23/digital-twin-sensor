from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any

from .context_pack import _stable_key
from .redaction import redact_text
from .store import DEFAULT_DB_PATH, assert_encrypted_write, filter_window, parse_dt, utc_now
from .working_spheres import build_working_spheres
from .observability import observed


FEEDBACK_LABELS = {
    "useful": "Useful",
    "wrong": "Wrong",
    "stale": "Stale",
    "too_broad": "Too broad",
    "too_private": "Too private",
    "missing_context": "Missing context",
}

FEEDBACK_SCOPES = {"pack", "sphere", "evidence"}

LEARNING_SCHEMA = """
CREATE TABLE IF NOT EXISTS context_feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  subject_id TEXT NOT NULL,
  pack_id TEXT NOT NULL,
  sphere_id TEXT,
  evidence_key TEXT,
  scope TEXT NOT NULL,
  label TEXT NOT NULL,
  purpose TEXT NOT NULL,
  target TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_context_feedback_subject_time
ON context_feedback(subject_id, created_at);

CREATE INDEX IF NOT EXISTS idx_context_feedback_pack
ON context_feedback(pack_id);

CREATE INDEX IF NOT EXISTS idx_context_feedback_sphere
ON context_feedback(subject_id, sphere_id);

CREATE TABLE IF NOT EXISTS context_cards (
  id TEXT PRIMARY KEY,
  subject_id TEXT NOT NULL,
  sphere_id TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  status TEXT NOT NULL,
  sensitivity TEXT NOT NULL,
  confidence REAL NOT NULL,
  evidence_count INTEGER NOT NULL,
  useful_count INTEGER NOT NULL,
  issue_count INTEGER NOT NULL,
  stale_count INTEGER NOT NULL,
  privacy_count INTEGER NOT NULL,
  labels_json TEXT NOT NULL DEFAULT '{}',
  evidence_json TEXT NOT NULL DEFAULT '[]',
  open_questions_json TEXT NOT NULL DEFAULT '[]',
  next_actions_json TEXT NOT NULL DEFAULT '[]',
  first_seen TEXT,
  last_seen TEXT,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_context_cards_subject_updated
ON context_cards(subject_id, updated_at);

CREATE TABLE IF NOT EXISTS resume_checkpoints (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  subject_id TEXT NOT NULL,
  sphere_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_resume_checkpoint_subject_sphere
ON resume_checkpoints(subject_id, sphere_id, id);

CREATE TABLE IF NOT EXISTS resume_sessions (
  id TEXT PRIMARY KEY,
  subject_id TEXT NOT NULL,
  sphere_id TEXT NOT NULL,
  pack_id TEXT NOT NULL,
  checkpoint_id INTEGER,
  created_at TEXT NOT NULL,
  shown_at TEXT,
  outcome TEXT,
  completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_resume_session_subject_sphere
ON resume_sessions(subject_id, sphere_id, created_at);
"""


def normalize_label(label: str) -> str:
    key = str(label or "").strip().lower().replace("-", "_").replace(" ", "_")
    if key not in FEEDBACK_LABELS:
        raise ValueError(f"unknown feedback label: {label}")
    return key


def normalize_scope(scope: str) -> str:
    key = str(scope or "pack").strip().lower()
    if key not in FEEDBACK_SCOPES:
        raise ValueError(f"unknown feedback scope: {scope}")
    return key


class LearningStore:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH, *, config: dict[str, Any] | None = None, cipher: Any = None):
        from .crypto import cipher_for_config

        self.cipher = cipher if cipher is not None else cipher_for_config(db_path, config or {})
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA secure_delete = ON")
        self.conn.row_factory = sqlite3.Row
        self.init_db()

    def init_db(self) -> None:
        self.conn.executescript(LEARNING_SCHEMA)
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(context_feedback)")}
        if "resolved_at" not in columns:
            self.conn.execute("ALTER TABLE context_feedback ADD COLUMN resolved_at TEXT")
        self.conn.commit()

    def resolve_feedback(self, *, subject_id: str, feedback_id: int) -> bool:
        cur = self.conn.execute(
            "UPDATE context_feedback SET resolved_at = ? WHERE subject_id = ? AND id = ? AND resolved_at IS NULL",
            (utc_now().isoformat(), subject_id, feedback_id),
        )
        self.conn.commit()
        return bool(cur.rowcount)

    def close(self) -> None:
        self.conn.close()

    def _seal(self, value: str) -> str:
        return self.cipher.encrypt(value) if self.cipher else value

    def _open_fields(self, item: dict[str, Any]) -> dict[str, Any]:
        if self.cipher:
            for key, value in item.items():
                if isinstance(value, str):
                    item[key] = self.cipher.decrypt(value)
        return item

    def migrate_encryption(self) -> int:
        if self.cipher is None:
            raise ValueError("Migration requires an encryption key")
        tables = {
            "context_feedback": ["note", "metadata_json"],
            "context_cards": ["title", "summary", "labels_json", "evidence_json", "open_questions_json", "next_actions_json"],
            "resume_checkpoints": ["payload_json"],
        }
        changed = 0
        with self.conn:
            for table, fields in tables.items():
                for row in self.conn.execute(f"SELECT * FROM {table}").fetchall():
                    values = [self._seal(row[field]) for field in fields]
                    if values != [row[field] for field in fields]:
                        assignments = ", ".join(f"{field} = ?" for field in fields)
                        self.conn.execute(f"UPDATE {table} SET {assignments} WHERE id = ?", [*values, row["id"]])
                        changed += 1
        return changed

    def add_feedback(
        self,
        *,
        subject_id: str,
        pack_id: str,
        label: str,
        config: dict[str, Any],
        scope: str = "pack",
        sphere_id: str | None = None,
        evidence_key: str | None = None,
        purpose: str = "coding",
        target: str = "kiro",
        note: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert_encrypted_write(self.conn, self.cipher)
        if not pack_id:
            raise ValueError("pack_id is required")
        label_key = normalize_label(label)
        scope_key = normalize_scope(scope)
        if scope_key == "evidence" and not evidence_key:
            raise ValueError("evidence feedback requires evidence_key")

        redacted_note = redact_text(note or "", config).text[:500]
        created_at = utc_now().isoformat()
        cur = self.conn.execute(
            """
            INSERT INTO context_feedback (
              subject_id, pack_id, sphere_id, evidence_key, scope, label,
              purpose, target, note, created_at, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                subject_id,
                pack_id,
                sphere_id,
                evidence_key,
                scope_key,
                label_key,
                purpose,
                target,
                self._seal(redacted_note),
                created_at,
                self._seal(json.dumps(metadata or {}, sort_keys=True)),
            ),
        )
        self.conn.commit()
        return {
            "id": int(cur.lastrowid),
            "subject_id": subject_id,
            "pack_id": pack_id,
            "sphere_id": sphere_id,
            "evidence_key": evidence_key,
            "scope": scope_key,
            "label": label_key,
            "label_text": FEEDBACK_LABELS[label_key],
            "purpose": purpose,
            "target": target,
            "note": redacted_note,
            "created_at": created_at,
        }

    def list_feedback(self, *, subject_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM context_feedback
            WHERE subject_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (subject_id, int(limit)),
        ).fetchall()
        return [self._feedback_row(row) for row in rows]

    def feedback_for_subject(self, *, subject_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM context_feedback
            WHERE subject_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (subject_id,),
        ).fetchall()
        return [self._feedback_row(row) for row in rows]

    def _feedback_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = self._open_fields(dict(row))
        try:
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        except json.JSONDecodeError:
            item["metadata"] = {}
        item["label_text"] = FEEDBACK_LABELS.get(item["label"], item["label"])
        return item

    def upsert_cards(self, cards: list[dict[str, Any]]) -> None:
        assert_encrypted_write(self.conn, self.cipher)
        for card in cards:
            self.conn.execute(
                """
                INSERT INTO context_cards (
                  id, subject_id, sphere_id, title, summary, status, sensitivity,
                  confidence, evidence_count, useful_count, issue_count, stale_count,
                  privacy_count, labels_json, evidence_json, open_questions_json,
                  next_actions_json, first_seen, last_seen, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  title = excluded.title,
                  summary = excluded.summary,
                  status = excluded.status,
                  sensitivity = excluded.sensitivity,
                  confidence = excluded.confidence,
                  evidence_count = excluded.evidence_count,
                  useful_count = excluded.useful_count,
                  issue_count = excluded.issue_count,
                  stale_count = excluded.stale_count,
                  privacy_count = excluded.privacy_count,
                  labels_json = excluded.labels_json,
                  evidence_json = excluded.evidence_json,
                  open_questions_json = excluded.open_questions_json,
                  next_actions_json = excluded.next_actions_json,
                  first_seen = excluded.first_seen,
                  last_seen = excluded.last_seen,
                  updated_at = excluded.updated_at
                """,
                (
                    card["id"],
                    card["subject_id"],
                    card["sphere_id"],
                    self._seal(card["title"]),
                    self._seal(card["summary"]),
                    card["status"],
                    card["sensitivity"],
                    float(card["confidence"]),
                    int(card["evidence_count"]),
                    int(card["useful_count"]),
                    int(card["issue_count"]),
                    int(card["stale_count"]),
                    int(card["privacy_count"]),
                    self._seal(json.dumps(card["labels"], sort_keys=True)),
                    self._seal(json.dumps(card["evidence"], sort_keys=True)),
                    self._seal(json.dumps(card["open_questions"], sort_keys=True)),
                    self._seal(json.dumps(card["next_actions"], sort_keys=True)),
                    card.get("first_seen"),
                    card.get("last_seen"),
                    card["updated_at"],
                ),
            )
        self.conn.commit()

    def list_cards(self, *, subject_id: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM context_cards
            WHERE subject_id = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (subject_id, int(limit)),
        ).fetchall()
        return [self._card_row(row) for row in rows]

    def _card_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = self._open_fields(dict(row))
        for key, default in [
            ("labels_json", {}),
            ("evidence_json", []),
            ("open_questions_json", []),
            ("next_actions_json", []),
        ]:
            out_key = key.removesuffix("_json")
            try:
                item[out_key] = json.loads(item.pop(key) or json.dumps(default))
            except json.JSONDecodeError:
                item[out_key] = default
        return item


def _feedback_by_sphere(feedback: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in feedback:
        if item.get("resolved_at"):
            continue
        sphere_id = item.get("sphere_id")
        if sphere_id:
            grouped[sphere_id].append(item)
    return grouped


def _status_for(labels: Counter[str], last_seen: str | None, confidence: float) -> str:
    issue_count = sum(labels[label] for label in ("wrong", "too_broad", "missing_context"))
    if labels["too_private"]:
        return "privacy_review"
    if labels["stale"]:
        return "stale"
    if issue_count:
        return "needs_evidence"
    if confidence < 0.45:
        return "weak"
    if labels["useful"]:
        return "validated"
    if last_seen:
        age = max(0, (utc_now() - parse_dt(last_seen)).total_seconds())
        if age > timedelta(days=7).total_seconds():
            return "aging"
    return "learning"


def _questions_for(labels: Counter[str], sphere: dict[str, Any]) -> list[str]:
    questions = []
    if labels["missing_context"]:
        questions.append("What evidence should be present before this pack is trusted?")
    if labels["wrong"]:
        questions.append("Which artifact, task label, or domain caused the wrong grouping?")
    if labels["too_broad"]:
        questions.append("Should this working sphere split into smaller task cards?")
    if labels["stale"]:
        questions.append("Has the task changed since this evidence was last seen?")
    if labels["too_private"] or sphere.get("gate_mode") == "masked":
        questions.append("Can the same handoff be expressed with less sensitive context?")
    if not questions:
        questions.append("Does the next context pack help resume the work faster than no context?")
    return questions[:4]


def _actions_for(labels: Counter[str], status: str) -> list[str]:
    actions = []
    if labels["useful"]:
        actions.append("Keep this sphere as positive training evidence for the current gate policy.")
    if labels["wrong"] or labels["too_broad"]:
        actions.append("Lower confidence in the current grouping until new evidence confirms it.")
    if labels["missing_context"]:
        actions.append("Collect a labelled correction describing what context was missing.")
    if labels["stale"] or status == "aging":
        actions.append("Refresh the context pack before using it for an agent handoff.")
    if labels["too_private"]:
        actions.append("Route future packs through a stricter masking policy before export.")
    if not actions:
        actions.append("Ask for a useful/not-useful label after the next handoff.")
    return actions[:4]


def build_context_cards(
    events: list[dict[str, Any]],
    config: dict[str, Any],
    *,
    subject_id: str,
    feedback: list[dict[str, Any]],
    days: int = 14,
    max_cards: int = 12,
) -> list[dict[str, Any]]:
    activities = build_working_spheres(events, config, days=days, max_spheres=max_cards)
    grouped_feedback = _feedback_by_sphere(feedback)
    cards = []
    updated_at = utc_now().isoformat()
    for sphere in activities.get("spheres", [])[:max_cards]:
        sphere_feedback = grouped_feedback.get(sphere.get("id"), [])
        labels = Counter(item["label"] for item in sphere_feedback)
        confidence = round(float(sphere.get("confidence", 0.0)), 3)
        status = _status_for(labels, sphere.get("last_seen"), confidence)
        artifacts = [
            {
                "evidence_key": _stable_key("ev", sphere.get("id"), item.get("name"), item.get("events"), item.get("dwell_seconds")),
                "name": item.get("name"),
                "events": int(item.get("events", 0)),
                "hours": round(float(item.get("hours", 0.0)), 2),
            }
            for item in sphere.get("artifacts", [])[:5]
        ]
        useful_count = int(labels["useful"])
        stale_count = int(labels["stale"])
        privacy_count = int(labels["too_private"])
        issue_count = int(labels["wrong"] + labels["too_broad"] + labels["missing_context"])
        cards.append(
            {
                "id": _stable_key("card", subject_id, sphere.get("id")),
                "subject_id": subject_id,
                "sphere_id": sphere.get("id"),
                "title": sphere.get("label", "Working sphere"),
                "summary": (
                    f"{sphere.get('task', 'unclassified work')} in {sphere.get('domain', 'other')} "
                    f"across {sphere.get('session_count', 0)} sessions and {sphere.get('events', 0)} events."
                ),
                "status": status,
                "sensitivity": sphere.get("sensitivity", "low"),
                "confidence": confidence,
                "evidence_count": int(sphere.get("events", 0)),
                "useful_count": useful_count,
                "issue_count": issue_count,
                "stale_count": stale_count,
                "privacy_count": privacy_count,
                "labels": dict(sorted(labels.items())),
                "evidence": artifacts,
                "open_questions": _questions_for(labels, sphere),
                "next_actions": _actions_for(labels, status),
                "first_seen": sphere.get("first_seen"),
                "last_seen": sphere.get("last_seen"),
                "updated_at": updated_at,
            }
        )
    return cards


@observed("learning.refresh")
def build_learning_state(
    events: list[dict[str, Any]],
    config: dict[str, Any],
    *,
    subject_id: str,
    db_path: Path = DEFAULT_DB_PATH,
    days: int = 14,
    max_cards: int = 12,
) -> dict[str, Any]:
    events = filter_window(events, days)
    store = LearningStore(db_path, config=config)
    try:
        feedback = store.feedback_for_subject(subject_id=subject_id)
        cards = build_context_cards(
            events,
            config,
            subject_id=subject_id,
            feedback=feedback,
            days=days,
            max_cards=max_cards,
        )
        store.conn.execute("DELETE FROM context_cards WHERE subject_id = ?", (subject_id,))
        store.upsert_cards(cards)
        cards = store.list_cards(subject_id=subject_id, limit=max_cards)
        recent_feedback = store.list_feedback(subject_id=subject_id, limit=20)
    finally:
        store.close()

    label_counts = Counter(item["label"] for item in feedback)
    issue_count = sum(label_counts[label] for label in ("wrong", "stale", "too_broad", "too_private", "missing_context"))
    useful_count = label_counts["useful"]
    total = sum(label_counts.values())
    return {
        "status": "active" if total else "ready",
        "policy": "learning-mode-v1-local",
        "days": days,
        "labels": [
            {"key": key, "label": label}
            for key, label in FEEDBACK_LABELS.items()
        ],
        "stats": {
            "feedback_count": int(total),
            "useful_count": int(useful_count),
            "issue_count": int(issue_count),
            "context_cards": len(cards),
            "validated_cards": sum(1 for card in cards if card.get("status") == "validated"),
            "needs_review": sum(1 for card in cards if card.get("status") in {"needs_evidence", "privacy_review", "stale", "weak"}),
        },
        "label_counts": dict(sorted(label_counts.items())),
        "cards": cards,
        "recent_feedback": recent_feedback,
        "maintenance": [
            {
                "name": "Update cards from latest spheres",
                "status": "complete",
                "detail": f"{len(cards)} context cards refreshed from redacted working-sphere evidence.",
            },
            {
                "name": "Apply feedback labels",
                "status": "complete" if total else "ready",
                "detail": f"{total} local labels recorded; privacy, wrong, and stale restrictions are enforced on stored-context exports.",
            },
            {
                "name": "Tune retrieval policy",
                "status": "designed",
                "detail": "Labels are captured and exposed; automatic router weight changes are intentionally offline-only next.",
            },
        ],
    }

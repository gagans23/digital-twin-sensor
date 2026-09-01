"""Content-free operational traces. This module never imports a network client."""
from __future__ import annotations

import contextvars
import functools
import hashlib
import inspect
import json
import logging
import math
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit


OPERATIONS = frozenset({
    "collection.sample", "collection.capture", "collection.persist",
    "collection.browser", "collection.accessibility", "collection.ocr",
    "context.pack", "learning.refresh", "resume.view", "resume.action",
    "dashboard.overview", "query.retrieve", "observability.test",
})
OUTCOMES = frozenset({"ok", "error", "blocked", "empty", "ready", "active", "ignored", "paused", "captured", "no_result"})
ERRORS = frozenset({"none", "permission", "timeout", "storage", "validation", "internal"})
COUNTS = frozenset({"events", "context_cards", "feedback_count", "allow", "deny", "redact", "stored"})
MAX_RECORDS = 2000
MAX_SPANS = 64
RETENTION_SECONDS = 7 * 86400
DEFAULT_SETTINGS = {"mode": "off", "endpoint": "", "project": "digital-twin-sensor", "workspace": "default", "generation": ""}
_current = contextvars.ContextVar("dts_operational_trace", default=None)
_last_warning = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS records (
 id TEXT PRIMARY KEY, created REAL NOT NULL, destination TEXT NOT NULL,
 state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 next_attempt REAL NOT NULL DEFAULT 0, payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS records_created ON records(created);
CREATE TABLE IF NOT EXISTS exporter (
 id INTEGER PRIMARY KEY CHECK(id=1), last_attempt REAL, last_success REAL,
 last_error TEXT NOT NULL DEFAULT '', failures INTEGER NOT NULL DEFAULT 0,
 accepted INTEGER NOT NULL DEFAULT 0, dropped INTEGER NOT NULL DEFAULT 0,
 lease_until REAL NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO exporter(id) VALUES(1);
"""


def log_path(db_path):
    return Path(db_path).expanduser().with_suffix(".observability.sqlite")


@contextmanager
def connect(db_path, *, create=False, timeout=0.025):
    path = log_path(db_path)
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
    if path.is_symlink():
        raise ValueError("Operational log cannot be a symbolic link")
    # mode=rw avoids creating files when instrumentation is off or a path is wrong.
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True, timeout=timeout)
    try:
        os.chmod(path, 0o600)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA secure_delete=ON")
        if create:
            conn.executescript(SCHEMA)
            conn.execute("INSERT OR IGNORE INTO settings VALUES(1, ?)", (json.dumps(DEFAULT_SETTINGS),))
            conn.commit()
        yield conn
    finally:
        conn.close()


def validate_settings(value):
    mode = value.get("mode", "off")
    if mode not in {"off", "local", "opik"}:
        raise ValueError("Choose off, local, or opik mode")
    result = {key: value.get(key, default) for key, default in DEFAULT_SETTINGS.items()}
    if result["generation"]:
        result["generation"] = str(uuid.UUID(result["generation"]))
    for key in ("project", "workspace"):
        if not isinstance(result[key], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", result[key]):
            raise ValueError("Project and workspace must be short non-personal identifiers")
    endpoint = result["endpoint"]
    if not isinstance(endpoint, str) or len(endpoint) > 512:
        raise ValueError("Invalid Opik endpoint")
    if endpoint:
        parts = urlsplit(endpoint)
        local = parts.hostname in {"127.0.0.1", "localhost", "::1"}
        if (parts.scheme not in {"http", "https"} or not parts.hostname or parts.username is not None
                or parts.password is not None or parts.query or parts.fragment or parts.port == 0
                or any(char.isspace() for char in endpoint) or "\\" in endpoint
                or (parts.scheme != "https" and not local)):
            raise ValueError("Use HTTPS (HTTP only on loopback), without credentials, query, or fragment")
        result["endpoint"] = endpoint.rstrip("/")
    elif mode == "opik":
        raise ValueError("An explicit Opik API endpoint is required")
    return result


def settings(db_path):
    if not log_path(db_path).exists():
        return dict(DEFAULT_SETTINGS)
    with connect(db_path) as conn:
        return validate_settings(json.loads(conn.execute("SELECT payload FROM settings WHERE id=1").fetchone()[0]))


def destination(config):
    value = [config[key] for key in ("mode", "endpoint", "project", "workspace", "generation")]
    return hashlib.sha256(json.dumps(value).encode()).hexdigest()


def configure(db_path, *, mode, endpoint=None, project=None, workspace=None, allow_remote=False):
    current = settings(db_path)
    updated = {**current, "mode": mode, "generation": str(uuid.uuid4())}
    for key, value in (("endpoint", endpoint), ("project", project), ("workspace", workspace)):
        if value is not None:
            updated[key] = value
    updated = validate_settings(updated)
    if mode == "opik" and urlsplit(updated["endpoint"]).hostname not in {"127.0.0.1", "localhost", "::1"} and not allow_remote:
        raise ValueError("Remote telemetry requires --allow-remote and an approved endpoint")
    with connect(db_path, create=True, timeout=2) as conn:
        # Re-enabling or changing destinations must never upload an old backlog.
        conn.execute("UPDATE records SET state='withheld' WHERE state='pending'")
        conn.execute("UPDATE settings SET payload=? WHERE id=1", (json.dumps(updated),))
        conn.commit()
    return status(db_path)


def _prune(conn, now):
    expired = conn.execute("SELECT count(*) FROM records WHERE created<? AND state='pending'", (now-RETENTION_SECONDS,)).fetchone()[0]
    conn.execute("DELETE FROM records WHERE created<?", (now-RETENTION_SECONDS,))
    overflow = max(0, conn.execute("SELECT count(*) FROM records").fetchone()[0] - MAX_RECORDS)
    lost = conn.execute("SELECT count(*) FROM (SELECT state FROM records ORDER BY created LIMIT ?) WHERE state='pending'", (overflow,)).fetchone()[0]
    conn.execute("DELETE FROM records WHERE id IN (SELECT id FROM records ORDER BY created LIMIT ?)", (overflow,))
    conn.execute("UPDATE exporter SET dropped=dropped+? WHERE id=1", (expired+lost,))


def _warning():
    global _last_warning
    now = time.monotonic()
    if _last_warning is None or now - _last_warning > 60:
        logging.getLogger(__name__).warning("Operational trace unavailable; sensor operation continues")
        _last_warning = now


def safe_counts(values):
    return {key: value for key, value in values.items()
            if key in COUNTS and type(value) is int and 0 <= value <= 10_000_000}


def _safe_span(value):
    name, outcome, error = value["name"], value["outcome"], value["error"]
    if name not in OPERATIONS or outcome not in OUTCOMES or error not in ERRORS:
        raise ValueError("Unrecognized operational vocabulary")
    start, duration = float(value["start"]), float(value["duration_ms"])
    if not math.isfinite(start) or not 0 <= start <= 4_102_444_800 or not math.isfinite(duration) or not 0 <= duration <= 86400000:
        raise ValueError("Invalid operational timing")
    return {"id": str(uuid.UUID(value["id"])), "parent_id": str(uuid.UUID(value["parent_id"])) if value.get("parent_id") else None,
            "name": name, "start": start, "duration_ms": round(duration, 3),
            "outcome": outcome, "error": error, "counts": safe_counts(value.get("counts", {}))}


def safe_trace(value):
    # Reconstruct at both persistence and export boundaries. Never pass through extras.
    result = _safe_span(value)
    result["schema"] = "dts-operations-v1"
    result["spans"] = [_safe_span(item) for item in value.get("spans", [])[:MAX_SPANS]]
    return result


def _save(db_path, expected_destination, trace):
    payload = json.dumps(safe_trace(trace), separators=(",", ":"))
    with connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        cfg = validate_settings(json.loads(conn.execute("SELECT payload FROM settings WHERE id=1").fetchone()[0]))
        if cfg["mode"] == "off" or destination(cfg) != expected_destination:
            return
        conn.execute("INSERT INTO records(id,created,destination,state,payload) VALUES(?,?,?,?,?)",
                     (trace["id"], time.time(), expected_destination, "pending" if cfg["mode"] == "opik" else "local", payload))
        _prune(conn, time.time())
        conn.commit()


def _error_category(exc):
    if isinstance(exc, PermissionError):
        return "permission"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, sqlite3.Error):
        return "storage"
    if isinstance(exc, (ValueError, TypeError)):
        return "validation"
    return "internal"


class Span:
    def __init__(self, name, parent_id=None):
        self.data = {"id": str(uuid.uuid4()), "parent_id": parent_id, "name": name,
                     "start": time.time(), "duration_ms": 0, "outcome": "ok", "error": "none", "counts": {}}
        self.clock = time.monotonic()

    def outcome(self, value):
        if isinstance(value, str) and value in OUTCOMES:
            self.data["outcome"] = value

    def counts(self, **values):
        self.data["counts"].update(safe_counts(values))


@contextmanager
def operation(db_path, name):
    parent = _current.get()
    enabled = False
    cfg = None
    try:
        cfg = settings(db_path) if db_path is not None and parent is None else None
        enabled = name in OPERATIONS and (parent is not None or (cfg and cfg["mode"] != "off"))
    except Exception:
        _warning()
    span = Span(name, parent[1].data["id"] if parent else None)
    if not enabled:
        yield span
        return
    root = parent[0] if parent else span.data
    if not parent:
        root["spans"] = []
    token = _current.set((root, span))
    try:
        yield span
    except BaseException as exc:
        span.outcome("error")
        span.data["error"] = _error_category(exc)
        raise
    finally:
        _current.reset(token)
        span.data["duration_ms"] = min(86400000, max(0, (time.monotonic()-span.clock)*1000))
        try:
            if parent:
                if len(root["spans"]) < MAX_SPANS:
                    root["spans"].append(span.data)
            else:
                _save(db_path, destination(cfg), root)
        except Exception:
            _warning()


def observed(name):
    """Instrument a named boundary, without recording arguments or return content."""
    def decorate(function):
        signature = inspect.signature(function)

        @functools.wraps(function)
        def wrapped(*args, **kwargs):
            bound = signature.bind_partial(*args, **kwargs).arguments
            with operation(bound.get("db_path"), name) as span:
                result = function(*args, **kwargs)
                try:
                    if isinstance(result, dict):
                        span.outcome(result.get("status"))
                        span.counts(**safe_counts(result.get("stats", {})))
                        span.counts(**safe_counts(result.get("admission", {}).get("counts", {})))
                    elif result is None and name.startswith("collection."):
                        span.outcome("no_result")
                except Exception:
                    _warning()
                return result
        return wrapped
    return decorate


def status(db_path):
    empty = {"mode": "off", "destination": "Not configured", "project": "digital-twin-sensor",
             "pending": 0, "records": 0, "recent": [], "exporter": {},
             "retention_days": 7, "capacity": MAX_RECORDS}
    if not log_path(db_path).exists():
        return empty
    try:
        cfg = settings(db_path)
        with connect(db_path, timeout=0.1) as conn:
            _prune(conn, time.time())
            conn.commit()
            rows = conn.execute("SELECT payload,state FROM records ORDER BY created DESC LIMIT 30").fetchall()
            recent = [{**safe_trace(json.loads(row["payload"])), "delivery": row["state"]} for row in rows]
            return {**empty, "mode": cfg["mode"], "destination": cfg["endpoint"] or "Local only", "project": cfg["project"],
                    "records": conn.execute("SELECT count(*) FROM records").fetchone()[0],
                    "pending": conn.execute("SELECT count(*) FROM records WHERE state='pending'").fetchone()[0],
                    "recent": recent, "exporter": dict(conn.execute("SELECT * FROM exporter WHERE id=1").fetchone())}
    except Exception:
        return {**empty, "mode": "unavailable"}


def purge(db_path):
    if log_path(db_path).exists():
        with connect(db_path, timeout=2) as conn:
            cfg = validate_settings(json.loads(conn.execute("SELECT payload FROM settings WHERE id=1").fetchone()[0]))
            cfg["generation"] = str(uuid.uuid4())
            conn.execute("UPDATE settings SET payload=? WHERE id=1", (json.dumps(cfg),))
            conn.execute("DELETE FROM records")
            conn.execute("UPDATE exporter SET last_attempt=NULL,last_success=NULL,last_error='',failures=0,accepted=0,dropped=0 WHERE id=1")
            conn.commit()
    return status(db_path)

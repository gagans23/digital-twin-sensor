"""Local task resumption. Observations, user reports, and guesses stay separate."""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from .context_pack import build_context_pack
from .learning import LearningStore
from .redaction import redact_text
from .store import assert_encrypted_write, open_event_store, parse_dt, utc_now
from .working_spheres import build_working_spheres


class ResumeConflict(ValueError):
    pass


def _safe_text(value, config, limit=1200):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"Checkpoint fields must be text of at most {limit} characters")
    policy = {**config, "mask_pii": True, "mask_configured_names": True, "redact_url_paths": True}
    return redact_text(value.strip(), policy).text


def _history(store, subject, sphere, config):
    cutoff = (utc_now() - timedelta(days=max(1, int(config.get("retention_days", 30))))).isoformat()
    rows = store.conn.execute(
        "SELECT * FROM resume_checkpoints WHERE subject_id=? AND sphere_id=? AND created_at>=? ORDER BY id DESC LIMIT 10",
        (subject, sphere, cutoff),
    ).fetchall()
    history = []
    for row in rows:
        value = json.loads(store.cipher.decrypt(row["payload_json"]) if store.cipher else row["payload_json"])
        # Apply current masking policy again when old checkpoints are displayed.
        for field in ("state", "next_step", "question"):
            value[field] = _safe_text(value.get(field, ""), config)
        history.append({"id": row["id"], "confirmed_at": row["created_at"], **value})
    return history


def _coverage(events, config):
    times = []
    for event in events:
        try:
            times.append(parse_dt(event["ts_end"]))
        except (KeyError, ValueError, TypeError):
            continue
    age = max(0, int((utc_now() - max(times)).total_seconds())) if times else None
    if config.get("collection_paused"):
        state, detail = "paused", "Collection is paused. Recent activity may be missing."
    elif age is None:
        state, detail = "unavailable", "No samples in this window. This does not mean no work happened."
    elif age > max(180, int(config.get("sample_interval_seconds", 15)) * 3):
        state, detail = "stale", "No recent sample. Sleep, permissions, ignored apps, or a stopped collector can create gaps."
    else:
        state, detail = "recent", "Recent foreground samples are available; reading and progress are not measured."
    return {"state": state, "detail": detail, "sample_age_seconds": age, "permissions": "not_verified"}


def _build(events, config, store, sphere_id, days):
    activities = build_working_spheres(events, config, days=days)
    feedback = store.feedback_for_subject(subject_id=config["subject_id"])
    packs = [build_context_pack(events, config, days=days, purpose="self_review", target="local_file",
                                sphere_id=sphere["id"], activities=activities, feedback=feedback)
             for sphere in activities.get("spheres", [])]
    selected = next((p for p in packs if p["selected_sphere_id"] == sphere_id), None) if sphere_id else next((p for p in packs if p["status"] == "ready"), packs[0] if packs else None)
    result = {
        "status": "empty", "reason": "No available task in this window.", "generated_at": utc_now().isoformat(),
        "coverage": _coverage(events, config), "selected_sphere_id": sphere_id,
        "tasks": [{"id": p["selected_sphere_id"], "title": p["summary"].get("title", "Restricted context"),
                   "status": p["status"], "last_seen": p["summary"].get("last_seen")} for p in packs],
        "checkpoint": None, "history": [], "observations": [], "sessions": [],
        "inference": None, "change": None,
    }
    if selected is None:
        if sphere_id:
            result["reason"] = "This task is no longer in the selected window. Choose another task."
        return result
    result.update(status=selected["status"], selected_sphere_id=selected["selected_sphere_id"],
                  reason=selected.get("selection_reason"), pack_id=selected["pack_id"])
    if selected["status"] != "ready":
        return result
    sphere = selected["selected_sphere_id"]
    history = _history(store, config["subject_id"], sphere, config)
    checkpoint = history[0] if history else None
    observations = selected["context"].get("recent_path", [])
    new_samples = [item for item in observations if checkpoint and item.get("time") and
                   parse_dt(item["time"]) > parse_dt(checkpoint["observed_through"])]
    sessions = [dict(row) for row in store.conn.execute(
        "SELECT id, pack_id, checkpoint_id, created_at, shown_at, outcome, completed_at FROM resume_sessions WHERE subject_id=? AND sphere_id=? ORDER BY created_at DESC LIMIT 10",
        (config["subject_id"], sphere),
    )]
    result.update(
        title=selected["summary"]["title"], checkpoint=checkpoint, history=history,
        observations=observations, sessions=sessions,
        inference={"text": selected["summary"]["objective"], "basis": "Task-category template; not a confirmed next step."},
        change={"since": checkpoint["observed_through"] if checkpoint else None,
                "recent_samples_since": len(new_samples) if checkpoint else None,
                "scope": "Only the displayed recent samples; not a complete activity diff.",
                "content_changes_verified": False},
        observed_through=selected["summary"]["last_seen"],
        validity="Task membership is inferred from artifact/title similarity. Foreground presence is observed, not attention.",
    )
    return result


def build_resume_view(db_path: Path, config: dict, *, sphere_id=None, days=14):
    events_store = open_event_store(db_path, config)
    try:
        events = events_store.fetch_window(subject_id=config["subject_id"], days=days)
    finally:
        events_store.close()
    store = LearningStore(db_path, config=config)
    try:
        return _build(events, config, store, sphere_id, days)
    finally:
        store.close()


def resume_action(db_path: Path, config: dict, payload: dict):
    action = payload.get("action")
    if action not in {"checkpoint", "start", "shown", "outcome"}:
        raise ValueError("Unknown resume action")
    subject = config["subject_id"]
    events_store = open_event_store(db_path, config)
    store = LearningStore(db_path, config=config)
    try:
        # Serialize the evidence read and write against purge and concurrent edits.
        store.conn.execute("BEGIN IMMEDIATE")
        assert_encrypted_write(store.conn, store.cipher)
        if action in {"shown", "outcome"}:
            session_id = str(payload.get("session_id", ""))
            row = store.conn.execute("SELECT * FROM resume_sessions WHERE id=? AND subject_id=?", (session_id, subject)).fetchone()
            if row is None:
                raise ResumeConflict("Resume session is missing or expired")
            if action == "shown":
                store.conn.execute("UPDATE resume_sessions SET shown_at=COALESCE(shown_at, ?) WHERE id=?", (utc_now().isoformat(), session_id))
            else:
                outcome = payload.get("outcome")
                if outcome not in {"progress", "no_progress", "not_used"}:
                    raise ValueError("Unknown resume outcome")
                if not row["shown_at"]:
                    raise ResumeConflict("The resume view has not been acknowledged as shown")
                if row["outcome"] and row["outcome"] != outcome:
                    raise ResumeConflict("This session already has an outcome")
                store.conn.execute("UPDATE resume_sessions SET outcome=?, completed_at=COALESCE(completed_at, ?) WHERE id=?",
                                   (outcome, utc_now().isoformat(), session_id))
            store.conn.commit()
            return {"stored": True, "session_id": session_id}

        sphere_id = payload.get("sphere_id")
        if not isinstance(sphere_id, str) or not sphere_id:
            raise ValueError("A task is required")
        days = payload.get("days", 14)
        if type(days) is not int or not 1 <= days <= 365:
            raise ValueError("days must be between 1 and 365")
        events = events_store.fetch_window(subject_id=subject, days=days)
        view = _build(events, config, store, sphere_id, days)
        if view["status"] != "ready":
            raise ResumeConflict("Task context is restricted, missing, or expired. Refresh before continuing.")
        checkpoint_id = view["checkpoint"]["id"] if view["checkpoint"] else None
        if action == "checkpoint":
            if payload.get("base_checkpoint_id") != checkpoint_id:
                raise ResumeConflict("Checkpoint changed in another window. Refresh and review before saving.")
            values = {field: _safe_text(payload.get(field, ""), config) for field in ("state", "next_step", "question")}
            if not values["state"]:
                raise ValueError("Describe the state you can confirm")
            values["observed_through"] = view["observed_through"]
            values["source"] = "user_report"
            result = store.conn.execute("INSERT INTO resume_checkpoints(subject_id,sphere_id,created_at,payload_json) VALUES(?,?,?,?)",
                                        (subject, sphere_id, utc_now().isoformat(), store._seal(json.dumps(values))))
            store.conn.commit()
            return {"stored": True, "checkpoint_id": result.lastrowid}

        try:
            session_id = str(UUID(str(payload.get("request_id", ""))))
        except ValueError:
            raise ValueError("request_id must be a UUID") from None
        existing = store.conn.execute("SELECT * FROM resume_sessions WHERE id=?", (session_id,)).fetchone()
        if existing and (existing["subject_id"] != subject or existing["sphere_id"] != sphere_id):
            raise ResumeConflict("Request ID belongs to another resume session")
        if not existing:
            store.conn.execute("INSERT INTO resume_sessions(id,subject_id,sphere_id,pack_id,checkpoint_id,created_at) VALUES(?,?,?,?,?,?)",
                               (session_id, subject, sphere_id, view["pack_id"], checkpoint_id, utc_now().isoformat()))
        elif existing["pack_id"] != view["pack_id"] or existing["checkpoint_id"] != checkpoint_id:
            raise ResumeConflict("Context changed since this request. Start a new resume session.")
        store.conn.commit()
        return {"stored": True, "session_id": session_id, "view": view}
    finally:
        store.close()
        events_store.close()

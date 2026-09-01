"""User-confirmed aliases, not automatic merges or a replacement for evidence."""
from __future__ import annotations

import json
from datetime import timedelta
from uuid import uuid4

from .redaction import redact_text
from .store import utc_now


class IdentityConflict(ValueError):
    pass


def task_name(value, config):
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise ValueError("Task name must contain 1 to 160 characters")
    policy = {**config, "mask_pii": True, "mask_configured_names": True, "redact_url_paths": True}
    return redact_text(value.strip(), policy).text


def expire_identities(conn, cutoff, subject=None):
    args = (cutoff, subject) if subject else (cutoff,)
    subject_sql = " AND subject_id=?" if subject else ""
    conn.execute("DELETE FROM task_bindings WHERE last_seen<?" + subject_sql, args)
    conn.execute("DELETE FROM task_identity_edits WHERE created_at<?" + subject_sql, args)
    conn.execute("DELETE FROM task_identities WHERE NOT EXISTS (SELECT 1 FROM task_bindings b WHERE b.task_id=task_identities.id AND b.subject_id=task_identities.subject_id)" + (" AND subject_id=?" if subject else ""), (subject,) if subject else ())


def registry(store, config, activities, packs, feedback):
    subject = config["subject_id"]
    cutoff = (utc_now()-timedelta(days=max(1, int(config.get("retention_days", 30))))).isoformat()
    # Refresh only from actual observed timestamps, not from opening the dashboard.
    for sphere in activities.get("spheres", []):
        if sphere.get("last_seen"):
            store.conn.execute("UPDATE task_bindings SET last_seen=MAX(last_seen,?) WHERE subject_id=? AND sphere_id=?",
                               (sphere["last_seen"], subject, sphere["id"]))
    expire_identities(store.conn, cutoff, subject)
    current = {p["selected_sphere_id"]: p for p in packs}
    restrictions = [item for item in feedback if not item.get("resolved_at") and item.get("label") in {"too_private", "wrong", "stale"}]
    legacy_private = any(item.get("label") == "too_private" and item.get("sphere_id") not in current for item in restrictions)
    identities = []
    for row in store.conn.execute("SELECT * FROM task_identities WHERE subject_id=? ORDER BY created_at,id LIMIT 100", (subject,)):
        aliases = [binding[0] for binding in store.conn.execute("SELECT sphere_id FROM task_bindings WHERE subject_id=? AND task_id=? ORDER BY sphere_id", (subject, row["id"]))]
        restricted = legacy_private or any(item.get("sphere_id") in aliases for item in restrictions) or any(current[a]["status"] == "blocked" for a in aliases if a in current)
        name = "Restricted task"
        if not restricted:
            payload = store.cipher.decrypt(row["name_json"]) if store.cipher else row["name_json"]
            name = task_name(json.loads(payload)["name"], config)
        identities.append({"id": row["id"], "name": name, "revision": row["revision"], "aliases": aliases,
                           "restricted": restricted, "active_groups": sum(a in current for a in aliases)})
    return identities


def identity_for(identities, sphere):
    return next((item for item in identities if sphere in item["aliases"]), None)


def scope_matches(scope, aliases, origin):
    scope = scope or [origin]
    return isinstance(scope, list) and all(isinstance(item, str) for item in scope) and set(scope).issubset(aliases)


def edit_identity(store, config, view, payload):
    action, subject, sphere = payload["action"], config["subject_id"], view["selected_sphere_id"]
    current = view.get("identity")
    expected = current["revision"] if current else None
    if payload.get("identity_revision") != expected:
        raise IdentityConflict("Task membership changed. Refresh before saving.")
    now = utc_now().isoformat()
    if action == "unlink_task":
        if not current:
            raise IdentityConflict("This activity group has no saved task")
        task_id = current["id"]
        store.conn.execute("DELETE FROM task_bindings WHERE subject_id=? AND sphere_id=?", (subject, sphere))
        store.conn.execute("UPDATE task_identities SET revision=revision+1 WHERE id=? AND subject_id=?", (task_id, subject))
        edit_action = "unlink_task"
    elif action == "save_task":
        name = task_name(payload.get("name"), config)
        task_id = current["id"] if current else "task_" + str(uuid4())
        if not current and len(view["saved_tasks"]) >= 100:
            raise ValueError("At most 100 saved task identities are supported")
        if current:
            store.conn.execute("UPDATE task_identities SET name_json=?,revision=revision+1 WHERE id=? AND subject_id=?",
                               (store._seal(json.dumps({"name": name})), task_id, subject))
            edit_action = "rename_task"
        else:
            store.conn.execute("INSERT INTO task_identities VALUES(?,?,?,?,?)", (task_id, subject, store._seal(json.dumps({"name": name})), 1, now))
            store.conn.execute("INSERT INTO task_bindings VALUES(?,?,?,?)", (subject, sphere, task_id, view["observed_through"]))
            edit_action = "create_task"
    else:
        target = next((item for item in view["saved_tasks"] if item["id"] == payload.get("task_id")), None)
        if current:
            raise IdentityConflict("Unlink this activity group before assigning it to another task")
        if not target or target["restricted"] or payload.get("target_revision") != target["revision"]:
            raise IdentityConflict("The destination task is missing, restricted, or changed")
        if len(target["aliases"]) >= 32:
            raise ValueError("At most 32 activity groups can be linked to a saved task")
        task_id = target["id"]
        store.conn.execute("INSERT INTO task_bindings VALUES(?,?,?,?)", (subject, sphere, task_id, view["observed_through"]))
        store.conn.execute("UPDATE task_identities SET revision=revision+1 WHERE id=? AND subject_id=?", (task_id, subject))
        edit_action = "link_task"
    store.conn.execute("INSERT INTO task_identity_edits(subject_id,task_id,sphere_id,action,created_at) VALUES(?,?,?,?,?)", (subject, task_id, sphere, edit_action, now))
    return {"stored": True, "task_id": task_id}

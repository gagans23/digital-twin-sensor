from __future__ import annotations

from collections.abc import Callable
from collections import Counter
from typing import Any

from .redaction import redact_text
from .store import utc_now
from .working_spheres import build_working_spheres


PURPOSES = {
    "coding": "Continue software implementation",
    "gitlab": "Prepare a GitLab issue or progress update",
    "research": "Summarize research and product context",
    "self_review": "Review personal work patterns",
    "agent_prompt": "Ground an assistant with current work context",
}

TARGETS = {
    "kiro": "Kiro agent",
    "codex": "Codex agent",
    "gitlab": "GitLab issue or merge request",
    "local_file": "Local file",
    "markdown": "Markdown document",
    "json": "JSON document",
}

LOCAL_TARGETS = {"local_file", "markdown", "json"}
DECISION_ORDER = ("allow", "summarize", "generalize", "mask", "deny")
SENSITIVE_MARKERS = (
    "[credit-card]",
    "[email]",
    "[ip-address]",
    "[name]",
    "[phone]",
    "[redacted",
    "[secret]",
    "[ssn]",
)

WITHHELD_DEFAULTS = [
    ("subject_id", "identity is not required for task handoff"),
    ("event_ids", "local database pointers are not useful outside this machine"),
    ("raw_event_payloads", "context packs export summaries only"),
    ("metadata_json", "connector metadata may contain implementation-specific private detail"),
    ("full_urls", "URL paths, query strings, fragments, usernames, and passwords stay out"),
    ("document_bodies", "source content requires explicit connector-level consent"),
    ("screenshots", "images are never included by the context-pack gate"),
    ("keystrokes", "keystrokes are outside the collection boundary"),
    ("clipboard", "clipboard content is outside the collection boundary"),
    ("credentials", "passwords, tokens, and secrets are denied"),
]


def _shorten(value: Any, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."


def _target_allowed(target: str, config: dict[str, Any]) -> tuple[bool, str]:
    if target not in TARGETS:
        return False, "target is not recognized by this exporter"
    if target in LOCAL_TARGETS:
        return True, "local preview/export targets are allowed"

    allowed = {str(item) for item in config.get("fleet_allowed_export_targets", [])}
    if target in allowed:
        return True, "target is present in fleet_allowed_export_targets"
    return False, "target is not allowed by fleet policy"


def _has_sensitive_marker(value: Any) -> bool:
    label = str(value or "").lower()
    return any(marker in label for marker in SENSITIVE_MARKERS)


def _sphere_is_sensitive(sphere: dict[str, Any]) -> bool:
    if sphere.get("gate_mode") != "allowed":
        return True
    if sphere.get("redaction_summary"):
        return True
    fields = [
        sphere.get("label"),
        sphere.get("task"),
        sphere.get("domain"),
        sphere.get("resume_pack", {}).get("last_artifact"),
    ]
    fields.extend(item.get("name") for item in sphere.get("artifacts", []))
    return any(_has_sensitive_marker(value) for value in fields)


def _decision(field: str, decision: str, reason: str) -> dict[str, str]:
    return {"field": field, "decision": decision, "reason": reason}


def _withheld(field: str, reason: str) -> dict[str, str]:
    return {"field": field, "reason": reason}


def _counts(decisions: list[dict[str, str]]) -> dict[str, int]:
    counter = Counter(item["decision"] for item in decisions)
    return {key: int(counter.get(key, 0)) for key in DECISION_ORDER}


def _select_sphere(activities: dict[str, Any], sphere_id: str | None) -> tuple[dict[str, Any] | None, str]:
    spheres = list(activities.get("spheres", []))
    if not spheres:
        return None, "no working spheres in the requested window"

    if sphere_id:
        for sphere in spheres:
            if sphere.get("id") == sphere_id:
                return sphere, "matched requested sphere"
        return None, "requested sphere was not found in this time window"

    for sphere in spheres:
        if sphere.get("state") == "active":
            return sphere, "selected active working sphere"
    return spheres[0], "selected strongest suspended or dormant sphere"


def _safe_artifacts(
    sphere: dict[str, Any],
    safe_text: Callable[[Any, int], str],
    limit: int = 5,
) -> list[dict[str, Any]]:
    artifacts = []
    for item in sphere.get("artifacts", [])[:limit]:
        artifacts.append(
            {
                "name": safe_text(item.get("name"), 120),
                "events": int(item.get("events", 0)),
                "dwell_seconds": round(float(item.get("dwell_seconds", 0.0)), 2),
                "hours": round(float(item.get("hours", 0.0)), 2),
            }
        )
    return artifacts


def _safe_apps(
    sphere: dict[str, Any],
    safe_text: Callable[[Any, int], str],
    limit: int = 5,
) -> list[dict[str, Any]]:
    return [
        {"name": safe_text(item.get("name"), 72), "events": int(item.get("events", 0))}
        for item in sphere.get("apps", [])[:limit]
    ]


def _safe_recent_path(
    sphere: dict[str, Any],
    safe_text: Callable[[Any, int], str],
    max_events: int,
) -> list[dict[str, Any]]:
    recent = sphere.get("resume_pack", {}).get("recent_events", [])
    result = []
    for item in recent[:max_events]:
        result.append(
            {
                "time": item.get("ts_start"),
                "app": safe_text(item.get("app"), 72),
                "artifact": safe_text(item.get("artifact"), 120),
                "domain": safe_text(item.get("domain"), 64),
                "dwell_seconds": round(float(item.get("dwell_seconds", 0.0)), 2),
                "gate_mode": item.get("gate_mode", "allowed"),
            }
        )
    return result


def _privacy_summary(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "raw_events_included": False,
        "subject_id_included": False,
        "pii_masking": bool(config.get("mask_pii", True)),
        "name_masking": bool(config.get("mask_configured_names", True)),
        "url_paths": "stored" if config.get("browser_tab_store_url_path", False) else "redacted",
        "url_queries": "stored" if config.get("browser_tab_store_query", False) else "redacted",
        "screenshots_included": False,
        "keystrokes_included": False,
        "clipboard_included": False,
        "source_content_included": False,
    }


def _base_decisions(target: str, target_ok: bool, target_reason: str) -> list[dict[str, str]]:
    return [
        _decision("target", "allow" if target_ok else "deny", target_reason),
        _decision("purpose", "allow", "purpose label guides formatting only"),
        _decision("events.source_count", "summarize", "event counts are admitted without raw rows"),
        _decision("system_events", "deny", "system/locked-session events are excluded from working spheres"),
        _decision("raw_event_payloads", "deny", "context packs are summary-only"),
        _decision("subject_id", "deny", "identity is not needed for handoff"),
        _decision("event_ids", "deny", "local database pointers stay local"),
        _decision("full_urls", "deny", "paths, query strings, fragments, usernames, and passwords stay out"),
        _decision("screenshots", "deny", "screenshots are outside this export boundary"),
        _decision("keystrokes", "deny", "keystrokes are outside this collection boundary"),
        _decision("clipboard", "deny", "clipboard content is outside this collection boundary"),
        _decision("credentials", "deny", "passwords, tokens, and secrets are never admitted"),
    ]


def _pack_pipeline(event_count: int, status: str) -> list[dict[str, str]]:
    return [
        {"stage": "Working Sphere", "state": "selected", "output": f"{event_count} redacted events considered"},
        {"stage": "Memory Admission Gate", "state": status, "output": "field-level allow, summarize, mask, and deny decisions"},
        {"stage": "Context Pack", "state": "summary-only", "output": "resume cue, evidence summary, recent path"},
        {"stage": "Export", "state": "ready" if status == "ready" else status, "output": "Markdown or JSON for Kiro, Codex, GitLab, or local file"},
    ]


def build_context_pack(
    events: list[dict[str, Any]],
    config: dict[str, Any],
    *,
    days: int = 14,
    purpose: str = "coding",
    target: str = "kiro",
    sphere_id: str | None = None,
    max_events: int = 8,
    activities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    purpose_key = purpose if purpose in PURPOSES else "agent_prompt"
    target_key = target if target in TARGETS else target
    target_ok, target_reason = _target_allowed(target_key, config)
    decisions = _base_decisions(target_key, target_ok, target_reason)
    withheld = [_withheld(field, reason) for field, reason in WITHHELD_DEFAULTS]

    activities = activities or build_working_spheres(events, config, days=days)
    selected, selection_reason = _select_sphere(activities, sphere_id)
    if selected is None:
        decisions.append(_decision("working_sphere", "deny", selection_reason))
        pack = {
            "status": "empty",
            "generated_at": utc_now().isoformat(),
            "days": days,
            "purpose": {"key": purpose_key, "label": PURPOSES[purpose_key]},
            "target": {"key": target_key, "label": TARGETS.get(target_key, target_key), "allowed": target_ok},
            "selected_sphere_id": None,
            "selection_reason": selection_reason,
            "summary": {},
            "context": {},
            "admission": {
                "policy": "memory-admission-gate-v1",
                "target_allowed": target_ok,
                "target_reason": target_reason,
                "decisions": decisions,
                "counts": _counts(decisions),
                "withheld": withheld,
            },
            "privacy": _privacy_summary(config),
            "pipeline": _pack_pipeline(0, "empty"),
        }
        pack["export"] = {"format": "markdown", "markdown": format_context_pack_markdown(pack)}
        return pack

    if not target_ok:
        decisions.append(_decision("working_sphere", "deny", "selected sphere is not exported because the target is blocked"))
        pack = {
            "status": "blocked",
            "generated_at": utc_now().isoformat(),
            "days": days,
            "purpose": {"key": purpose_key, "label": PURPOSES[purpose_key]},
            "target": {"key": target_key, "label": TARGETS.get(target_key, target_key), "allowed": False},
            "selected_sphere_id": selected.get("id"),
            "selection_reason": selection_reason,
            "summary": {},
            "context": {},
            "admission": {
                "policy": "memory-admission-gate-v1",
                "target_allowed": False,
                "target_reason": target_reason,
                "decisions": decisions,
                "counts": _counts(decisions),
                "withheld": withheld,
            },
            "privacy": _privacy_summary(config),
            "pipeline": _pack_pipeline(int(activities.get("stats", {}).get("events", 0)), "blocked"),
        }
        pack["export"] = {"format": "markdown", "markdown": format_context_pack_markdown(pack)}
        return pack

    stored_sensitive = _sphere_is_sensitive(selected)
    export_findings: Counter[str] = Counter()

    def safe_text(value: Any, limit: int = 120) -> str:
        result = redact_text(str(value or ""), config)
        export_findings.update(result.findings)
        return _shorten(result.text, limit)

    resume_pack = selected.get("resume_pack", {})
    recent_path = _safe_recent_path(selected, safe_text, max_events=max(1, min(12, max_events)))
    summary = {
        "title": safe_text(selected.get("label"), 96),
        "objective": safe_text(resume_pack.get("next_action_guess") or f"Continue {selected.get('task', 'work')}", 180),
        "state": safe_text(selected.get("state", "unknown"), 32),
        "domain": safe_text(selected.get("domain", "other"), 64),
        "task": safe_text(selected.get("task", "unclassified work"), 96),
        "confidence": round(float(selected.get("confidence", 0.0)), 2),
        "events": int(selected.get("events", 0)),
        "dwell_seconds": round(float(selected.get("dwell_seconds", 0.0)), 2),
        "hours": round(float(selected.get("hours", 0.0)), 2),
        "session_count": int(selected.get("session_count", 0)),
        "return_count": int(selected.get("return_count", 0)),
        "first_seen": selected.get("first_seen"),
        "last_seen": selected.get("last_seen"),
    }
    top_artifacts = _safe_artifacts(selected, safe_text)
    apps = _safe_apps(selected, safe_text)
    keywords = [safe_text(item, 36) for item in selected.get("keywords", [])[:8]]
    resume = {
        "last_app": safe_text(resume_pack.get("last_app"), 72),
        "last_artifact": safe_text(resume_pack.get("last_artifact"), 120),
        "last_seen": resume_pack.get("last_seen"),
        "next_action_guess": summary["objective"],
        "privacy_gate": resume_pack.get("privacy_gate", "Depth 1 metadata only"),
    }
    redaction_summary = Counter(dict(selected.get("redaction_summary", {})))
    redaction_summary.update(export_findings)
    sensitive = stored_sensitive or bool(redaction_summary)
    context = {
        "working_sphere": {
            "id": selected.get("id"),
            "label": summary["title"],
            "state": summary["state"],
            "domain": summary["domain"],
            "task": summary["task"],
            "gate_mode": "masked" if sensitive else selected.get("gate_mode", "allowed"),
            "sensitivity": "medium" if sensitive else selected.get("sensitivity", "low"),
            "selection_reason": selection_reason,
        },
        "top_artifacts": top_artifacts,
        "apps": apps,
        "keywords": keywords,
        "resume": resume,
        "recent_path": recent_path,
        "redaction_summary": dict(sorted(redaction_summary.items())),
    }

    decisions.extend(
        [
            _decision("summary.title", "mask" if sensitive else "allow", "title is already pre-redacted before export" if sensitive else "non-sensitive sphere label admitted"),
            _decision("summary.objective", "summarize", "next-action cue is derived from sphere type and recent path"),
            _decision("summary.time_window", "summarize", "only sphere-level first/last seen timestamps are included"),
            _decision("context.working_sphere", "allow", "domain, task, state, confidence, and dwell are safe summary fields"),
            _decision("context.top_artifacts", "mask" if sensitive else "summarize", "artifact labels come from redacted storage and are limited to top items"),
            _decision("context.apps", "allow", "application names are admitted as surface metadata"),
            _decision("context.keywords", "summarize", "keywords are derived from redacted artifact labels"),
            _decision("context.resume", "summarize", "resume cue contains last redacted artifact and next-action guess"),
            _decision("context.recent_path", "summarize", "recent path includes compact event summaries without ids or raw metadata"),
            _decision("context.redaction_summary", "mask" if sensitive else "allow", "redaction categories are counts only"),
        ]
    )

    status = "ready"
    pack = {
        "status": status,
        "generated_at": utc_now().isoformat(),
        "days": days,
        "purpose": {"key": purpose_key, "label": PURPOSES[purpose_key]},
        "target": {"key": target_key, "label": TARGETS[target_key], "allowed": True},
        "selected_sphere_id": selected.get("id"),
        "selection_reason": selection_reason,
        "summary": summary,
        "context": context,
        "admission": {
            "policy": "memory-admission-gate-v1",
            "target_allowed": True,
            "target_reason": target_reason,
            "decisions": decisions,
            "counts": _counts(decisions),
            "withheld": withheld,
        },
        "privacy": _privacy_summary(config),
        "pipeline": _pack_pipeline(int(activities.get("stats", {}).get("events", 0)), status),
    }
    pack["export"] = {"format": "markdown", "markdown": format_context_pack_markdown(pack)}
    return pack


def _bullet(label: str, value: Any) -> str:
    return f"- {label}: {value}"


def format_context_pack_markdown(pack: dict[str, Any]) -> str:
    status = pack.get("status", "unknown")
    target = pack.get("target", {})
    purpose = pack.get("purpose", {})
    admission = pack.get("admission", {})
    counts = admission.get("counts", {})

    if status != "ready":
        lines = [
            f"# Context Pack: {status.title()}",
            "",
            _bullet("Purpose", purpose.get("label", "unknown")),
            _bullet("Target", target.get("label", target.get("key", "unknown"))),
            _bullet("Generated", pack.get("generated_at", "unknown")),
            _bullet("Decision", admission.get("target_reason") or pack.get("selection_reason") or "not exportable"),
            "",
            "## Memory Admission Gate",
            f"- Policy: {admission.get('policy', 'memory-admission-gate-v1')}",
            f"- Counts: allow {counts.get('allow', 0)}, summarize {counts.get('summarize', 0)}, generalize {counts.get('generalize', 0)}, mask {counts.get('mask', 0)}, deny {counts.get('deny', 0)}",
            "",
            "## Withheld",
        ]
        lines.extend(f"- {item['field']}: {item['reason']}" for item in admission.get("withheld", [])[:12])
        return "\n".join(lines).strip() + "\n"

    summary = pack.get("summary", {})
    context = pack.get("context", {})
    resume = context.get("resume", {})
    artifacts = context.get("top_artifacts", [])
    apps = context.get("apps", [])
    recent = context.get("recent_path", [])
    privacy = pack.get("privacy", {})

    lines = [
        f"# Context Pack: {summary.get('title', 'Working Sphere')}",
        "",
        _bullet("Purpose", purpose.get("label", "unknown")),
        _bullet("Target", target.get("label", target.get("key", "unknown"))),
        _bullet("Generated", pack.get("generated_at", "unknown")),
        _bullet("Window", f"{pack.get('days', 14)} days"),
        "",
        "## Summary",
        _bullet("State", summary.get("state", "unknown")),
        _bullet("Domain", summary.get("domain", "other")),
        _bullet("Task", summary.get("task", "unclassified work")),
        _bullet("Confidence", f"{round(float(summary.get('confidence', 0)) * 100)}%"),
        _bullet("Observed", f"{summary.get('events', 0)} events, {summary.get('hours', 0)}h dwell, {summary.get('session_count', 0)} sessions, {summary.get('return_count', 0)} returns"),
        _bullet("Last seen", summary.get("last_seen", "unknown")),
        "",
        "## Resume Cue",
        str(resume.get("next_action_guess") or summary.get("objective") or "Review the latest artifact and continue."),
        "",
        "## Admitted Evidence",
        "Apps:",
    ]

    if apps:
        lines.extend(f"- {item['name']} ({item['events']} events)" for item in apps)
    else:
        lines.append("- no app signal")

    lines.append("")
    lines.append("Artifacts:")
    if artifacts:
        lines.extend(
            f"- {item['name']} ({item['events']} events, {item['hours']}h)"
            for item in artifacts
        )
    else:
        lines.append("- no artifact signal")

    keywords = context.get("keywords", [])
    lines.append("")
    lines.append("Keywords:")
    lines.append("- " + (", ".join(keywords) if keywords else "none"))

    lines.extend(["", "## Recent Path"])
    if recent:
        for item in recent:
            lines.append(
                f"- {item.get('time', 'unknown')}: {item.get('app', 'unknown app')} -> "
                f"{item.get('artifact', 'unknown artifact')} "
                f"({item.get('domain', 'other')}, {item.get('dwell_seconds', 0)}s, {item.get('gate_mode', 'allowed')})"
            )
    else:
        lines.append("- no recent path")

    lines.extend(
        [
            "",
            "## Privacy Gate",
            f"- Policy: {admission.get('policy', 'memory-admission-gate-v1')}",
            f"- Counts: allow {counts.get('allow', 0)}, summarize {counts.get('summarize', 0)}, generalize {counts.get('generalize', 0)}, mask {counts.get('mask', 0)}, deny {counts.get('deny', 0)}",
            f"- Raw events included: {str(bool(privacy.get('raw_events_included'))).lower()}",
            f"- Subject identity included: {str(bool(privacy.get('subject_id_included'))).lower()}",
            f"- URL paths: {privacy.get('url_paths', 'redacted')}",
            f"- URL queries: {privacy.get('url_queries', 'redacted')}",
            "",
            "Withheld:",
        ]
    )
    lines.extend(f"- {item['field']}: {item['reason']}" for item in admission.get("withheld", [])[:12])
    return "\n".join(lines).strip() + "\n"

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from .store import filter_window, parse_dt, utc_now


STOPWORDS = {
    "about",
    "active",
    "after",
    "again",
    "all",
    "and",
    "app",
    "apps",
    "are",
    "around",
    "ask",
    "browser",
    "can",
    "chat",
    "com",
    "current",
    "data",
    "doc",
    "doing",
    "edit",
    "for",
    "from",
    "git",
    "github",
    "google",
    "how",
    "html",
    "http",
    "https",
    "index",
    "local",
    "localhost",
    "make",
    "new",
    "not",
    "now",
    "open",
    "page",
    "paper",
    "papers",
    "pdf",
    "query",
    "read",
    "search",
    "setup",
    "site",
    "tab",
    "task",
    "the",
    "this",
    "untitled",
    "use",
    "user",
    "using",
    "view",
    "what",
    "with",
    "work",
    "workspace",
    "www",
    "you",
}

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

TASK_KEYWORDS = [
    ("arxiv", "research sources"),
    ("paper", "research sources"),
    ("papers", "research sources"),
    ("docs", "research docs"),
    ("documentation", "research docs"),
    ("readme", "document project"),
    ("roadmap", "plan roadmap"),
    ("spec", "plan implementation"),
    ("dashboard", "inspect dashboard"),
    ("localhost", "test local app"),
    ("127.0.0.1", "test local app"),
    ("unittest", "verify code"),
    ("pytest", "verify code"),
    ("test", "verify code"),
    ("gitlab", "prepare handoff"),
    ("issue", "track implementation"),
    ("pull request", "review code"),
    ("merge request", "review code"),
]

TASK_BY_DOMAIN = {
    "browser-research": "research sources",
    "coding": "build software",
    "communication": "communicate",
    "data": "analyze data",
    "documents": "document project",
    "planning": "plan roadmap",
    "system": "system state",
}


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(value.lower().encode("utf-8")).hexdigest()[:12]
    return f"{prefix}:{digest}"


def _safe_text(value: Any, fallback: str = "unknown") -> str:
    text = str(value or "").strip()
    return text if text else fallback


def _shorten(value: str, limit: int = 92) -> str:
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3].rstrip()}..."


def _normalize_artifact(value: str) -> str:
    text = re.sub(r"\[[^\]]+\]", " ", value.lower())
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _tokenize(value: str) -> list[str]:
    normalized = _normalize_artifact(value)
    tokens = []
    for token in normalized.split():
        if len(token) < 3:
            continue
        if token in STOPWORDS:
            continue
        if token.isdigit():
            continue
        tokens.append(token)
    return tokens[:24]


def _event_findings(event: dict[str, Any]) -> dict[str, int]:
    metadata = event.get("metadata", {})
    findings = metadata.get("redaction_findings", {})
    if not isinstance(findings, dict):
        return {}

    result: dict[str, int] = {}
    for key, value in findings.items():
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        if count > 0:
            result[str(key)] = count
    return result


def _gate_mode_for_event(event: dict[str, Any]) -> tuple[str, str, str]:
    label = f"{event.get('title', '')} {event.get('artifact', '')}".lower()
    findings = _event_findings(event)
    if findings:
        keys = ", ".join(sorted(findings))
        return "masked", "medium", f"redaction findings: {keys}"
    if any(marker in label for marker in SENSITIVE_MARKERS):
        return "masked", "medium", "label contains a redaction placeholder"
    if "[title capture disabled]" in label:
        return "generalized", "low", "window title capture is disabled"
    if "[redacted sensitive title]" in label:
        return "masked", "high", "sensitive window title was replaced"
    return "allowed", "low", "redacted metadata allowed by current policy"


def _task_label(domain: str, title: str, artifact: str) -> str:
    text = f"{title} {artifact}".lower()
    for keyword, task in TASK_KEYWORDS:
        if keyword in text:
            return task
    return TASK_BY_DOMAIN.get(domain, "unclassified work")


def _hours(seconds: float) -> float:
    return round(seconds / 3600, 2)


def _age_seconds(value: str) -> int:
    return max(0, round((utc_now() - parse_dt(value)).total_seconds()))


def _event_features(event: dict[str, Any]) -> dict[str, Any]:
    title = _safe_text(event.get("title"), "untitled")
    artifact = _safe_text(event.get("artifact") or title, "untitled")
    domain = _safe_text(event.get("domain"), "other")
    app = _safe_text(event.get("app"), "unknown app")
    tokens = _tokenize(f"{artifact} {title}")
    normalized_artifact = _normalize_artifact(artifact)
    task = _task_label(domain, title, artifact)
    gate_mode, sensitivity, gate_reason = _gate_mode_for_event(event)
    return {
        "app": app,
        "domain": domain,
        "artifact": artifact,
        "title": title,
        "normalized_artifact": normalized_artifact,
        "tokens": set(tokens),
        "task": task,
        "gate_mode": gate_mode,
        "sensitivity": sensitivity,
        "gate_reason": gate_reason,
        "findings": _event_findings(event),
    }


def _top_counter(counter: Counter[str], limit: int) -> list[dict[str, Any]]:
    return [{"name": name, "events": int(count)} for name, count in counter.most_common(limit)]


def _dominant(counter: Counter[str], fallback: str) -> str:
    if not counter:
        return fallback
    return counter.most_common(1)[0][0]


@dataclass
class WorkingSphere:
    id: str
    seed_key: str
    domains: Counter[str] = field(default_factory=Counter)
    apps: Counter[str] = field(default_factory=Counter)
    artifacts: Counter[str] = field(default_factory=Counter)
    artifact_dwell: defaultdict[str, float] = field(default_factory=lambda: defaultdict(float))
    normalized_artifacts: set[str] = field(default_factory=set)
    tokens: Counter[str] = field(default_factory=Counter)
    tasks: Counter[str] = field(default_factory=Counter)
    findings: Counter[str] = field(default_factory=Counter)
    gate_modes: Counter[str] = field(default_factory=Counter)
    event_ids: list[int] = field(default_factory=list)
    recent_events: list[dict[str, Any]] = field(default_factory=list)
    dwell_seconds: float = 0.0
    first_seen: str | None = None
    last_seen: str | None = None
    assignment_scores: list[float] = field(default_factory=list)

    def add(self, event: dict[str, Any], features: dict[str, Any], score: float) -> None:
        dwell = float(event.get("dwell_seconds", 0.0))
        artifact = features["artifact"]
        self.domains[features["domain"]] += 1
        self.apps[features["app"]] += 1
        self.artifacts[artifact] += 1
        self.artifact_dwell[artifact] += dwell
        if features["normalized_artifact"]:
            self.normalized_artifacts.add(features["normalized_artifact"])
        self.tokens.update(features["tokens"])
        self.tasks[features["task"]] += 1
        self.gate_modes[features["gate_mode"]] += 1
        self.findings.update(features["findings"])
        if event.get("id") is not None:
            self.event_ids.append(int(event["id"]))
        self.dwell_seconds += dwell
        self.first_seen = self.first_seen or event["ts_start"]
        self.last_seen = event["ts_end"]
        self.assignment_scores.append(score)
        self.recent_events.append(
            {
                "id": event.get("id"),
                "ts_start": event.get("ts_start"),
                "ts_end": event.get("ts_end"),
                "app": features["app"],
                "artifact": artifact,
                "domain": features["domain"],
                "dwell_seconds": round(dwell, 2),
                "gate_mode": features["gate_mode"],
            }
        )
        self.recent_events = self.recent_events[-8:]

    def token_set(self) -> set[str]:
        return {token for token, _ in self.tokens.most_common(18)}


def _score_sphere(
    sphere: WorkingSphere,
    features: dict[str, Any],
    *,
    previous_sphere_id: str | None,
    gap_seconds: float | None,
    session_gap_seconds: int,
) -> float:
    score = 0.0
    event_tokens = set(features["tokens"])
    sphere_tokens = sphere.token_set()

    if features["domain"] in sphere.domains:
        score += 0.18
    if features["app"] in sphere.apps:
        score += 0.12
    if features["task"] in sphere.tasks:
        score += 0.13
    if features["normalized_artifact"] and features["normalized_artifact"] in sphere.normalized_artifacts:
        score += 0.46

    if event_tokens and sphere_tokens:
        overlap = len(event_tokens & sphere_tokens)
        union = len(event_tokens | sphere_tokens)
        score += min(0.48, (overlap / max(union, 1)) * 0.72)
        if overlap >= 2:
            score += 0.08

    if previous_sphere_id == sphere.id and gap_seconds is not None and gap_seconds <= session_gap_seconds:
        score += 0.16

    return round(min(score, 1.0), 4)


def _new_sphere(features: dict[str, Any], event: dict[str, Any]) -> WorkingSphere:
    token_part = "-".join(sorted(features["tokens"])[:5])
    anchor = event.get("id") or event.get("ts_start") or event.get("ts_end") or "unknown"
    seed = "|".join(
        [
            features["domain"],
            features["app"],
            features["task"],
            features["normalized_artifact"][:80],
            token_part,
            str(anchor),
        ]
    )
    return WorkingSphere(id=_stable_id("sphere", seed), seed_key=seed)


def _segments(
    assignments: list[dict[str, Any]],
    sphere_labels: dict[str, str],
    *,
    session_gap_seconds: int,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    previous_end = None

    for item in assignments:
        event = item["event"]
        sphere_id = item["sphere_id"]
        start = parse_dt(event["ts_start"])
        gap = (start - previous_end).total_seconds() if previous_end else 0
        should_start = (
            current is None
            or current["sphere_id"] != sphere_id
            or gap > session_gap_seconds
        )
        if should_start:
            if current is not None:
                result.append(current)
            current = {
                "id": _stable_id("segment", f"{sphere_id}:{event['ts_start']}"),
                "sphere_id": sphere_id,
                "label": sphere_labels.get(sphere_id, "Activity"),
                "start": event["ts_start"],
                "end": event["ts_end"],
                "events": 0,
                "dwell_seconds": 0.0,
                "apps": Counter(),
            }

        current["events"] += 1
        current["dwell_seconds"] = round(float(current["dwell_seconds"]) + float(event["dwell_seconds"]), 2)
        current["end"] = event["ts_end"]
        current["apps"][event["app"]] += 1
        previous_end = parse_dt(event["ts_end"])

    if current is not None:
        result.append(current)

    for item in result:
        item["hours"] = _hours(float(item["dwell_seconds"]))
        item["top_app"] = _dominant(item.pop("apps"), "unknown app")
    return result


def _transition_summary(
    assignments: list[dict[str, Any]],
    sphere_labels: dict[str, str],
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str]] = Counter()
    last_seen: dict[tuple[str, str], str] = {}
    previous = None
    for item in assignments:
        sphere_id = item["sphere_id"]
        if previous and previous != sphere_id:
            key = (previous, sphere_id)
            counts[key] += 1
            last_seen[key] = item["event"]["ts_start"]
        previous = sphere_id

    return [
        {
            "source_id": source,
            "source": sphere_labels.get(source, "Activity"),
            "target_id": target,
            "target": sphere_labels.get(target, "Activity"),
            "count": int(count),
            "last_seen": last_seen.get((source, target)),
        }
        for (source, target), count in counts.most_common(limit)
    ]


def _label_sphere(sphere: WorkingSphere) -> str:
    task = _dominant(sphere.tasks, "activity")
    top_artifact, artifact_count = sphere.artifacts.most_common(1)[0]
    top_tokens = [token for token, _ in sphere.tokens.most_common(3)]

    if artifact_count >= 2 and not top_artifact.startswith("["):
        return _shorten(top_artifact, 72)
    if top_tokens:
        return _shorten(f"{task}: {' '.join(top_tokens)}", 72)
    domain = _dominant(sphere.domains, "work")
    return _shorten(f"{task}: {domain}", 72)


def _state_for_sphere(sphere: WorkingSphere, newest_event: str) -> str:
    if not sphere.last_seen:
        return "unknown"
    age = _age_seconds(sphere.last_seen)
    if sphere.last_seen == newest_event and age <= 15 * 60:
        return "active"
    if age <= 24 * 3600:
        return "suspended"
    return "dormant"


def _confidence(sphere: WorkingSphere, session_count: int) -> float:
    event_factor = min(1.0, math.log1p(len(sphere.event_ids) or sum(sphere.artifacts.values())) / math.log1p(24))
    session_factor = min(1.0, session_count / 5)
    token_factor = min(1.0, len(sphere.tokens) / 8)
    domain_share = 0.0
    if sphere.domains:
        domain_share = sphere.domains.most_common(1)[0][1] / max(sum(sphere.domains.values()), 1)
    score_factor = sum(sphere.assignment_scores) / max(len(sphere.assignment_scores), 1)
    privacy_penalty = 0.04 if sphere.findings else 0.0
    value = 0.25 + event_factor * 0.22 + session_factor * 0.2 + token_factor * 0.12 + domain_share * 0.11 + score_factor * 0.14
    return round(max(0.2, min(0.96, value - privacy_penalty)), 2)


def _explain_sphere(sphere: WorkingSphere, session_count: int) -> list[str]:
    explanations = []
    domain = _dominant(sphere.domains, "unknown")
    task = _dominant(sphere.tasks, "unclassified work")
    top_tokens = [token for token, _ in sphere.tokens.most_common(4)]
    top_artifact = sphere.artifacts.most_common(1)[0][0] if sphere.artifacts else "unknown artifact"

    explanations.append(f"Dominant work signal: {domain} / {task}")
    if top_tokens:
        explanations.append(f"Shared terms: {', '.join(top_tokens)}")
    explanations.append(f"Top artifact: {_shorten(top_artifact, 76)}")
    if session_count > 1:
        explanations.append(f"Returned across {session_count} sessions")
    else:
        explanations.append("Single continuous session so far")
    if sphere.findings:
        findings = ", ".join(f"{key}: {value}" for key, value in sorted(sphere.findings.items()))
        explanations.append(f"Privacy gate fired before inference: {findings}")
    else:
        explanations.append("Uses redacted Depth 1 metadata only")
    return explanations


def _next_action_hint(sphere: WorkingSphere) -> str:
    task = _dominant(sphere.tasks, "activity")
    if "research" in task:
        return "Summarize the strongest source and connect it to the active product concept."
    if "build" in task or "verify" in task or "test" in task:
        return "Open the latest artifact, check the last verification result, then continue the next small implementation step."
    if "document" in task or "plan" in task:
        return "Review the latest note, extract decisions, and turn the next open item into a task."
    if "communicate" in task:
        return "Draft the next response using only the admitted context for this sphere."
    return "Review the latest artifact and decide whether this sphere should continue, pause, or be ignored."


def _resume_pack(
    sphere: WorkingSphere,
    segments_for_sphere: list[dict[str, Any]],
    *,
    state: str,
) -> dict[str, Any]:
    recent = list(reversed(sphere.recent_events[-5:]))
    last_event = recent[0] if recent else {}
    return {
        "state": state,
        "last_artifact": last_event.get("artifact", "unknown artifact"),
        "last_app": last_event.get("app", "unknown app"),
        "last_seen": sphere.last_seen,
        "return_count": max(0, len(segments_for_sphere) - 1),
        "recent_events": recent,
        "next_action_guess": _next_action_hint(sphere),
        "privacy_gate": "masked before inference" if sphere.findings else "Depth 1 metadata only",
    }


def _empty_result(
    config: dict[str, Any],
    days: int,
    *,
    source_events: int = 0,
    excluded_system_events: int = 0,
) -> dict[str, Any]:
    return {
        "status": "empty",
        "days": days,
        "capture_depth": int(config.get("context_capture_depth", 1)),
        "stats": {
            "sphere_count": 0,
            "active_count": 0,
            "suspended_count": 0,
            "dormant_count": 0,
            "events": 0,
            "source_events": source_events,
            "excluded_system_events": excluded_system_events,
            "dwell_seconds": 0.0,
            "gated_spheres": 0,
        },
        "spheres": [],
        "timeline": [],
        "transitions": [],
        "pipeline": _pipeline(0, 0, config),
        "explanations": _explanation_cards(),
    }


def _pipeline(sphere_count: int, event_count: int, config: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "stage": "Events",
            "state": "redacted",
            "output": f"{event_count} Depth {int(config.get('context_capture_depth', 1))} samples",
        },
        {
            "stage": "Features",
            "state": "derived",
            "output": "app, domain, artifact terms, dwell, returns",
        },
        {
            "stage": "Spheres",
            "state": "inferred",
            "output": f"{sphere_count} working contexts",
        },
        {
            "stage": "Resume",
            "state": "ready",
            "output": "last artifact, recent path, next-action guess",
        },
    ]


def _explanation_cards() -> list[dict[str, str]]:
    return [
        {
            "title": "What is a working sphere?",
            "body": "A sphere is a cluster of related focus events that likely belong to one real activity, even when the work is interrupted and resumed later.",
        },
        {
            "title": "What signal is used?",
            "body": "Only redacted Depth 1 metadata: app, title/artifact label, domain, time, dwell, sequence, and return patterns.",
        },
        {
            "title": "What is not used?",
            "body": "No screenshots, keystrokes, clipboard, microphone, camera, document bodies, passwords, or raw tokens.",
        },
        {
            "title": "Why confidence changes",
            "body": "Confidence rises when events share artifacts, terms, domains, apps, task labels, and repeated return sessions.",
        },
    ]


def build_working_spheres(
    events: list[dict[str, Any]],
    config: dict[str, Any],
    *,
    days: int = 14,
    max_spheres: int | None = None,
) -> dict[str, Any]:
    events = filter_window(events, days)
    source_event_count = len(events)
    excluded_system_events = 0
    if not config.get("working_spheres_include_system_events", False):
        filtered = [
            event
            for event in events
            if event.get("domain") != "system" and event.get("action") != "system"
        ]
        excluded_system_events = source_event_count - len(filtered)
        events = filtered

    if not events:
        return _empty_result(
            config,
            days,
            source_events=source_event_count,
            excluded_system_events=excluded_system_events,
        )

    ordered = sorted(events, key=lambda item: item["ts_start"])
    session_gap_minutes = int(config.get("working_spheres_session_gap_minutes", 45))
    session_gap_seconds = max(5 * 60, session_gap_minutes * 60)
    threshold = float(config.get("working_spheres_match_threshold", 0.42))
    sphere_limit = int(max_spheres or config.get("working_spheres_max_spheres", 12))

    spheres: list[WorkingSphere] = []
    assignments: list[dict[str, Any]] = []
    previous_sphere_id: str | None = None
    previous_event: dict[str, Any] | None = None

    for event in ordered:
        features = _event_features(event)
        gap_seconds = None
        if previous_event is not None:
            gap_seconds = (
                parse_dt(event["ts_start"]) - parse_dt(previous_event["ts_end"])
            ).total_seconds()

        best_sphere: WorkingSphere | None = None
        best_score = 0.0
        for sphere in spheres:
            score = _score_sphere(
                sphere,
                features,
                previous_sphere_id=previous_sphere_id,
                gap_seconds=gap_seconds,
                session_gap_seconds=session_gap_seconds,
            )
            if score > best_score:
                best_score = score
                best_sphere = sphere

        if best_sphere is None or best_score < threshold:
            best_sphere = _new_sphere(features, event)
            spheres.append(best_sphere)
            best_score = 0.52

        best_sphere.add(event, features, best_score)
        assignments.append(
            {
                "event": event,
                "sphere_id": best_sphere.id,
                "confidence": best_score,
            }
        )
        previous_sphere_id = best_sphere.id
        previous_event = event

    labels = {sphere.id: _label_sphere(sphere) for sphere in spheres}
    segments = _segments(assignments, labels, session_gap_seconds=session_gap_seconds)
    segments_by_sphere: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for segment in segments:
        segments_by_sphere[segment["sphere_id"]].append(segment)

    newest_event = ordered[-1]["ts_end"]
    total_dwell = sum(float(event.get("dwell_seconds", 0.0)) for event in ordered)
    serialized_spheres = []
    state_counts: Counter[str] = Counter()

    for sphere in spheres:
        state = _state_for_sphere(sphere, newest_event)
        state_counts[state] += 1
        sphere_segments = segments_by_sphere.get(sphere.id, [])
        session_count = len(sphere_segments)
        gate_mode = "masked" if sphere.findings or sphere.gate_modes.get("masked") else "allowed"
        sensitivity = "medium" if gate_mode == "masked" else "low"
        top_artifacts = [
            {
                "name": name,
                "events": int(count),
                "dwell_seconds": round(sphere.artifact_dwell[name], 2),
                "hours": _hours(sphere.artifact_dwell[name]),
            }
            for name, count in sphere.artifacts.most_common(5)
        ]
        events_count = sum(sphere.artifacts.values())
        serialized_spheres.append(
            {
                "id": sphere.id,
                "label": labels[sphere.id],
                "state": state,
                "domain": _dominant(sphere.domains, "other"),
                "task": _dominant(sphere.tasks, "unclassified work"),
                "confidence": _confidence(sphere, session_count),
                "events": int(events_count),
                "dwell_seconds": round(sphere.dwell_seconds, 2),
                "hours": _hours(sphere.dwell_seconds),
                "share": round(sphere.dwell_seconds / max(total_dwell, 1.0), 4),
                "first_seen": sphere.first_seen,
                "last_seen": sphere.last_seen,
                "last_age_seconds": _age_seconds(sphere.last_seen) if sphere.last_seen else None,
                "session_count": session_count,
                "return_count": max(0, session_count - 1),
                "apps": _top_counter(sphere.apps, 4),
                "artifacts": top_artifacts,
                "keywords": [token for token, _ in sphere.tokens.most_common(6)],
                "gate_mode": gate_mode,
                "sensitivity": sensitivity,
                "redaction_summary": dict(sorted(sphere.findings.items())),
                "explanation": _explain_sphere(sphere, session_count),
                "resume_pack": _resume_pack(sphere, sphere_segments, state=state),
            }
        )

    order = {"active": 0, "suspended": 1, "dormant": 2, "unknown": 3}
    serialized_spheres = sorted(
        serialized_spheres,
        key=lambda item: (
            order.get(item["state"], 9),
            -float(item["dwell_seconds"]),
            -float(item["confidence"]),
        ),
    )[:sphere_limit]

    selected_ids = {sphere["id"] for sphere in serialized_spheres}
    timeline = [
        segment
        for segment in sorted(segments, key=lambda item: item["start"], reverse=True)
        if segment["sphere_id"] in selected_ids
    ][:20]
    transitions = [
        transition
        for transition in _transition_summary(assignments, labels)
        if transition["source_id"] in selected_ids and transition["target_id"] in selected_ids
    ]
    gated_spheres = sum(1 for sphere in serialized_spheres if sphere["gate_mode"] != "allowed")

    return {
        "status": "ready",
        "days": days,
        "capture_depth": int(config.get("context_capture_depth", 1)),
        "stats": {
            "sphere_count": len(serialized_spheres),
            "total_sphere_count": len(spheres),
            "active_count": int(state_counts.get("active", 0)),
            "suspended_count": int(state_counts.get("suspended", 0)),
            "dormant_count": int(state_counts.get("dormant", 0)),
            "events": len(ordered),
            "source_events": source_event_count,
            "excluded_system_events": excluded_system_events,
            "dwell_seconds": round(total_dwell, 2),
            "hours": _hours(total_dwell),
            "gated_spheres": gated_spheres,
            "session_gap_minutes": session_gap_minutes,
            "match_threshold": threshold,
        },
        "spheres": serialized_spheres,
        "timeline": timeline,
        "transitions": transitions,
        "pipeline": _pipeline(len(serialized_spheres), len(ordered), config),
        "explanations": _explanation_cards(),
    }
